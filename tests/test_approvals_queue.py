"""HITL approvals queue contract (issue #175).

Covers server-side pagination, filters, deterministic ordering, tenant scoping,
RBAC enforcement and validation envelopes on top of the #123 workflow.
"""

from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.interfaces.policy import PolicyDecision
from core.services.approval import ApprovalService

REPO = Path(__file__).resolve().parents[1]
PROMPT_CONFIG = REPO / "config" / "prompt_config.yaml"

MODELS_YAML = """
active_model: dummy
active_embedding_model: emb-a
models:
  dummy:
    provider: dummy
    context_window: 4096
embedding_models:
  emb-a:
    provider: dummy
    model_name: emb-a
"""

RETRIEVAL_YAML = """
retrieval:
  default_retriever: dummy
  similarity_metric: cosine
  top_k: 3
  retrievers:
    dummy:
      provider: dummy
evaluation:
  enabled: false
  active_evaluator: dummy
  evaluators:
    dummy:
      provider: dummy
reranking:
  enabled: false
"""

POLICIES_YAML = """
enabled: true
engine: noop
dry_run: false
hitl:
  enabled: true
  require_approval_for: ['*']
"""

TENANTS_YAML = """
enabled: true
default_tenant: default
tenants:
  default:
    workspace: default
    app: platform
  acme:
    workspace: acme-prod
    app: support-copilot
  beta:
    workspace: beta-dev
    app: beta-app
"""


class _StepClock:
    """Deterministic clock advancing by ``step`` on every call."""

    def __init__(self, start: float = 1000.0, step: float = 1.0):
        self._value = start
        self._step = step

    def __call__(self) -> float:
        self._value += self._step
        return self._value


class _ConstantClock:
    def __init__(self, value: float = 1000.0):
        self._value = value

    def __call__(self) -> float:
        return self._value


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _service(tmp_path: Path, clock=None) -> ApprovalService:
    policies = _write(tmp_path / "policies.yaml", POLICIES_YAML)
    return ApprovalService(config_path=str(policies), clock=clock or _StepClock())


def _client(
    tmp_path: Path,
    *,
    tenants: Optional[str] = None,
    access: Optional[str] = None,
    page_max: int = 100,
) -> TestClient:
    tmp_path.mkdir(parents=True, exist_ok=True)
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    prompt = _write(tmp_path / "prompt_config.yaml", PROMPT_CONFIG.read_text(encoding="utf-8"))
    observability = _write(tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n")
    api = _write(tmp_path / "api.yaml", f"approvals_page_size_max: {page_max}\n")
    kwargs = {}
    if tenants is not None:
        kwargs["tenants_config_path"] = _write(tmp_path / "tenants.yaml", tenants)
    if access is not None:
        kwargs["access_control_config_path"] = _write(tmp_path / "access_control.yaml", access)
    app = create_app(
        models_config_path=models,
        retrieval_config_path=retrieval,
        prompt_config_path=prompt,
        observability_config_path=observability,
        api_config_path=api,
        pipeline_builder=lambda **_: None,
        **kwargs,
    )
    return TestClient(app)


# -- service-level contract ------------------------------------------------


def test_pagination_slices_and_total(tmp_path):
    svc = _service(tmp_path, clock=_ConstantClock())
    for index in range(5):
        svc.create_request(f"action-{index}")

    page1, total = svc.query_requests(page=1, page_size=2)
    page2, total2 = svc.query_requests(page=2, page_size=2)
    page3, _ = svc.query_requests(page=3, page_size=2)
    page4, _ = svc.query_requests(page=4, page_size=2)

    assert total == total2 == 5
    assert [len(page1), len(page2), len(page3), len(page4)] == [2, 2, 1, 0]
    ids = [r.request_id for r in page1 + page2 + page3]
    assert len(set(ids)) == 5


def test_filters_status_action_requester_and_policy(tmp_path):
    svc = _service(tmp_path)
    decision = PolicyDecision(allowed=False, action="require_approval", policy_id="pol-1")
    first = svc.create_request(
        "pipeline_rebuild", decision=decision, requester="alice"
    )
    second = svc.create_request("model_swap", requester="bob")
    svc.decide(second.request_id, "approved", decided_by="reviewer")

    pending, total = svc.query_requests(status="pending")
    assert total == 1 and [r.request_id for r in pending] == [first.request_id]

    approved, total = svc.query_requests(status="approved")
    assert total == 1 and [r.request_id for r in approved] == [second.request_id]

    by_action, total = svc.query_requests(action="model_swap")
    assert total == 1 and by_action[0].request_id == second.request_id

    by_requester, total = svc.query_requests(requester="bob")
    assert total == 1 and by_requester[0].request_id == second.request_id

    by_policy, total = svc.query_requests(policy="pol-1")
    assert total == 1 and by_policy[0].request_id == first.request_id


def test_created_and_updated_time_range_filters(tmp_path):
    svc = _service(tmp_path, clock=_StepClock(start=1000.0, step=10.0))
    first = svc.create_request("a")  # created 1010
    second = svc.create_request("b")  # created 1020
    svc.decide(first.request_id, "approved")  # updated 1030

    by_created, total = svc.query_requests(created_after=1015)
    assert total == 1 and by_created[0].request_id == second.request_id

    by_created_before, total = svc.query_requests(created_before=1015)
    assert total == 1 and by_created_before[0].request_id == first.request_id

    by_updated, total = svc.query_requests(updated_after=1025)
    assert total == 1 and by_updated[0].request_id == first.request_id

    by_updated_before, total = svc.query_requests(updated_before=1025)
    assert total == 1 and by_updated_before[0].request_id == second.request_id


def test_ordering_is_deterministic_across_pages(tmp_path):
    svc = _service(tmp_path, clock=_ConstantClock())
    for index in range(6):
        svc.create_request(f"action-{index}")

    pages = [
        svc.query_requests(sort_by="request_id", order="asc", page=page, page_size=2)[0]
        for page in (1, 2, 3)
    ]
    flattened = [r.request_id for page in pages for r in page]
    assert len(flattened) == len(set(flattened)) == 6
    assert flattened == sorted(flattened)

    again = [
        svc.query_requests(sort_by="request_id", order="asc", page=page, page_size=2)[0]
        for page in (1, 2, 3)
    ]
    assert [r.request_id for page in again for r in page] == flattened


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "bogus"},
        {"sort_by": "bogus"},
        {"order": "sideways"},
        {"page": 0},
        {"page_size": 0},
        {"page_size": 1000},
        {"created_after": 10.0, "created_before": 5.0},
        {"updated_after": 10.0, "updated_before": 5.0},
    ],
)
def test_invalid_query_arguments_raise(tmp_path, kwargs):
    svc = _service(tmp_path)
    svc.create_request("a")
    with pytest.raises(ValueError):
        svc.query_requests(max_page_size=200, **kwargs)


# -- API contract ----------------------------------------------------------


def test_api_pagination_and_validation_envelopes(tmp_path):
    client = _client(tmp_path, page_max=3)
    with client as c:
        c.app.state.approvals = _service(tmp_path, clock=_ConstantClock())
        for index in range(5):
            c.app.state.approvals.create_request(f"action-{index}")

        ok = c.get("/v1/approvals", params={"page": 1, "page_size": 2})
        assert ok.status_code == 200
        body = ok.json()
        assert body["total"] == 5 and body["pages"] == 3
        assert body["count"] == 2 and body["page"] == 1 and body["page_size"] == 2
        assert body["sort_by"] == "created_at" and body["order"] == "desc"

        for params in (
            {"page": 0},
            {"page_size": 0},
            {"page_size": 99},
            {"sort_by": "bogus"},
            {"order": "sideways"},
            {"status": "bogus"},
            {"created_after": 10, "created_before": 5},
        ):
            bad = c.get("/v1/approvals", params=params)
            assert bad.status_code == 400, params
            assert bad.json()["failure_type"] == "approval_invalid", params


def test_api_tenant_isolation_and_scope_cannot_be_overridden(tmp_path):
    client = _client(tmp_path, tenants=TENANTS_YAML)
    with client as c:
        c.app.state.approvals = _service(tmp_path)
        acme = c.app.state.approvals.create_request("rebuild", tenant="acme")
        beta = c.app.state.approvals.create_request("rebuild", tenant="beta")

        scoped = c.get("/v1/approvals", headers={"X-Tenant-ID": "acme"})
        assert scoped.status_code == 200
        ids = [r["request_id"] for r in scoped.json()["requests"]]
        assert ids == [acme.request_id]

        override = c.get(
            "/v1/approvals", params={"tenant": "beta"}, headers={"X-Tenant-ID": "acme"}
        )
        assert override.status_code == 403
        assert override.json()["failure_type"] == "forbidden"
        assert "forbidden_tenant_scope" in override.json()["failure_tags"]

        matching = c.get(
            "/v1/approvals", params={"tenant": "acme"}, headers={"X-Tenant-ID": "acme"}
        )
        assert matching.status_code == 200

        hidden = c.get(
            f"/v1/approvals/{beta.request_id}", headers={"X-Tenant-ID": "acme"}
        )
        assert hidden.status_code == 404

        blocked = c.post(
            f"/v1/approvals/{beta.request_id}/decision",
            json={"decision": "approved"},
            headers={"X-Tenant-ID": "acme"},
        )
        assert blocked.status_code == 403
        assert "forbidden_tenant_scope" in blocked.json()["failure_tags"]

        allowed = c.post(
            f"/v1/approvals/{beta.request_id}/decision",
            json={"decision": "approved", "decided_by": "reviewer"},
            headers={"X-Tenant-ID": "beta"},
        )
        assert allowed.status_code == 200 and allowed.json()["status"] == "approved"


def test_api_requires_approve_capability(tmp_path):
    denied_cfg = "enabled: true\ndefault_role: viewer\nroles:\n  viewer:\n    capabilities: [query]\n"
    denied = _client(tmp_path / "denied", access=denied_cfg)
    with denied as c:
        response = c.get("/v1/approvals")
        assert response.status_code == 403
        assert response.json()["failure_type"] == "forbidden"
        assert "forbidden_approve" in response.json()["failure_tags"]

    allowed_cfg = "enabled: true\ndefault_role: reviewer\nroles:\n  reviewer:\n    capabilities: [approve]\n"
    allowed = _client(tmp_path / "allowed", access=allowed_cfg)
    with allowed as c:
        c.app.state.approvals = _service(tmp_path / "allowed")
        response = c.get("/v1/approvals")
        assert response.status_code == 200


def test_api_get_and_decision_keep_working(tmp_path):
    client = _client(tmp_path)
    with client as c:
        c.app.state.approvals = _service(tmp_path)
        req = c.app.state.approvals.create_request("rebuild", requester="alice")

        listed = c.get("/v1/approvals").json()
        assert listed["count"] == 1 and listed["total"] == 1
        item = listed["requests"][0]
        assert item["requester"] == "alice" and item["updated_at"] is not None

        one = c.get(f"/v1/approvals/{req.request_id}")
        assert one.status_code == 200 and one.json()["status"] == "pending"

        decided = c.post(
            f"/v1/approvals/{req.request_id}/decision",
            json={"decision": "rejected", "decided_by": "admin"},
        )
        assert decided.status_code == 200 and decided.json()["status"] == "rejected"

        missing = c.get("/v1/approvals/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["failure_type"] == "approval_not_found"
