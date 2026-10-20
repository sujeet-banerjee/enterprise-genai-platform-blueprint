"""Tests for issue #29: config-driven RBAC / persona layer.

Covers the ``AccessController`` (role resolution, capabilities, caps) and API
enforcement (allow / deny paths, top_k clamping, persona introspection).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from core.services.access_control import ALL_CAPABILITIES, AccessController

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"


# -- unit ------------------------------------------------------------------


def test_disabled_controller_grants_everything():
    ctrl = AccessController(enabled=False)
    assert ctrl.has_capability("viewer", "rebuild") is True
    assert ctrl.capabilities("viewer") == list(ALL_CAPABILITIES)
    assert ctrl.top_k_max("viewer") is None


def test_enabled_controller_resolves_keys_to_roles():
    ctrl = AccessController(
        enabled=True,
        roles={"viewer": {"capabilities": ["query"], "top_k_max": 3}},
        api_keys={"viewer-key": "viewer"},
        default_role="admin",
    )
    assert ctrl.resolve_role("viewer-key") == "viewer"
    assert ctrl.resolve_role("unknown") == "admin"
    assert ctrl.resolve_role(None) == "admin"


def test_enabled_controller_capability_checks():
    ctrl = AccessController(
        enabled=True,
        roles={"viewer": {"capabilities": ["query", "introspect"], "top_k_max": 3}},
        default_role="viewer",
    )
    assert ctrl.has_capability("viewer", "query") is True
    assert ctrl.has_capability("viewer", "rebuild") is False
    assert ctrl.top_k_max("viewer") == 3
    assert ctrl.describe("viewer")["capabilities"] == ["query", "introspect"]


def test_from_config_defaults_disabled():
    assert AccessController.from_config({}).enabled is False
    assert AccessController.from_config(None).enabled is False


def test_from_config_normalizes_roles():
    ctrl = AccessController.from_config(
        {
            "enabled": True,
            "default_role": "viewer",
            "roles": {"viewer": {"capabilities": ["query"], "top_k_max": 4}},
            "api_keys": {"k": "viewer"},
        }
    )
    assert ctrl.resolve_role("k") == "viewer"
    assert ctrl.top_k_max("viewer") == 4


# -- API enforcement -------------------------------------------------------

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


class _RecordingPipeline:
    def __init__(self):
        self.top_k_calls = []

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        self.top_k_calls.append(top_k)
        return {
            "response": f"answer:{query}",
            "failure_tags": [],
            "cost": {"estimated_cost_usd": 0.0},
            "latency": {"total_ms": 1.0},
            "observability": {"status": "success"},
        }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path, *, rbac_enabled: bool):
    access_yaml = (
        """
enabled: true
default_role: admin
roles:
  admin:
    capabilities: ["query", "batch", "evaluate", "experiment", "rebuild", "introspect", "governance", "audit"]
  viewer:
    capabilities: ["query", "introspect"]
    top_k_max: 2
api_keys:
  viewer-key: viewer
  admin-key: admin
"""
        if rbac_enabled
        else "enabled: false\n"
    )
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", "redact_sensitive_data: true\n"
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml", "enabled: false\n"
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            "require_api_key: false\napi_key: \"\"\nallow_rebuild: false\n"
            "history_max_runs: 1000\ntrace_store_max: 500\nmax_batch_size: 25\n",
        ),
        "audit_config_path": _write(tmp_path / "audit.yaml", "enabled: false\n"),
        "access_control_config_path": _write(tmp_path / "access_control.yaml", access_yaml),
    }


def _app(config_paths, pipeline):
    def builder(**_ignored):
        return pipeline

    return create_app(pipeline_builder=builder, **config_paths)


def test_api_viewer_can_query(tmp_path):
    pipeline = _RecordingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path, rbac_enabled=True), pipeline)) as client:
        response = client.post(
            "/v1/query", json={"query": "hi"}, headers={"X-API-Key": "viewer-key"}
        )
    assert response.status_code == 200
    assert response.json()["response"] == "answer:hi"


def test_api_viewer_denied_on_audit_and_metrics(tmp_path):
    pipeline = _RecordingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path, rbac_enabled=True), pipeline)) as client:
        audit = client.get("/v1/audit", headers={"X-API-Key": "viewer-key"})
        metrics = client.get("/v1/metrics", headers={"X-API-Key": "viewer-key"})

    assert audit.status_code == 403
    assert audit.json()["failure_type"] == "forbidden"
    assert audit.json()["failure_tags"] == ["forbidden_audit"]
    assert metrics.status_code == 403
    assert metrics.json()["failure_tags"] == ["forbidden_governance"]


def test_api_admin_can_reach_governance(tmp_path):
    pipeline = _RecordingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path, rbac_enabled=True), pipeline)) as client:
        metrics = client.get("/v1/metrics", headers={"X-API-Key": "admin-key"})
    assert metrics.status_code == 200


def test_api_top_k_clamped_by_role(tmp_path):
    pipeline = _RecordingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path, rbac_enabled=True), pipeline)) as client:
        # viewer top_k_max=2 -> an explicit top_k=10 is clamped to 2.
        client.post(
            "/v1/query",
            json={"query": "hi", "top_k": 10},
            headers={"X-API-Key": "viewer-key"},
        )
        # admin has no cap -> top_k passes through.
        client.post(
            "/v1/query",
            json={"query": "hi", "top_k": 10},
            headers={"X-API-Key": "admin-key"},
        )
    assert pipeline.top_k_calls == [2, 10]


def test_api_rbac_disabled_allows_everything(tmp_path):
    pipeline = _RecordingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path, rbac_enabled=False), pipeline)) as client:
        metrics = client.get("/v1/metrics", headers={"X-API-Key": "viewer-key"})
        access = client.get("/v1/access").json()
    assert metrics.status_code == 200
    assert access["enabled"] is False


def test_api_access_endpoint_reports_persona(tmp_path):
    pipeline = _RecordingPipeline()
    with TestClient(_app(_tmp_configs(tmp_path, rbac_enabled=True), pipeline)) as client:
        viewer = client.get("/v1/access", headers={"X-API-Key": "viewer-key"}).json()
        admin = client.get("/v1/access", headers={"X-API-Key": "admin-key"}).json()

    assert viewer["role"] == "viewer"
    assert viewer["capabilities"] == ["query", "introspect"]
    assert viewer["top_k_max"] == 2
    assert admin["role"] == "admin"
    assert admin["top_k_max"] is None
