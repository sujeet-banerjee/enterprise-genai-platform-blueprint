"""Tests for async operations API (issue #279)."""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app
from app.operations_api import operation_owner
from core.services.operation_jobs import OperationJobsService

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

API_YAML = """require_api_key: false
api_key: ""
operations:
  enabled: true
  max_workers: 1
  max_operations: 100
  recent_window_seconds: 3600
  store_ttl_seconds: 60
  list_limit_default: 50
  list_limit_max: 100
"""


class _Pipeline:
    def __init__(self, delay=0.0, result=None):
        self.delay = delay
        self.result = result
        self.calls = 0

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None, **kwargs):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.result is not None:
            return dict(self.result, request_id=request_id)
        return {
            "response": f"ok:{query}",
            "request_id": request_id,
            "failure_tags": [],
            "cost": {"estimated_cost_usd": 0.001, "model": "dummy"},
            "latency": {"total_ms": 1.0},
            "observability": {"request_id": request_id, "status": "success"},
            "tenant": kwargs.get("tenant"),
        }


class _RaisingPipeline:
    def __init__(self):
        self.calls = 0

    def run(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("pipeline exploded")


class _RecordingStore:
    def __init__(self):
        self.writes = []

    def set(self, key, value, ttl_seconds=None):
        self.writes.append((key, value, ttl_seconds))

    def get(self, key):
        return None

    def list(self, prefix="", limit=1000, **filters):
        return []

    def delete(self, key):
        return False


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def _app(tmp_path, *, pipeline=None, api_yaml=None, access_yaml=None):
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(
        tmp_path / "retrieval.yaml",
        "retrieval:\n  default_retriever: dummy\n  top_k: 3\n  retrievers:\n    dummy:\n      provider: dummy\n"
        "evaluation:\n  enabled: false\n  active_evaluator: dummy\n  evaluators:\n    dummy:\n      provider: dummy\n"
        "reranking:\n  enabled: false\n",
    )
    prompt = tmp_path / "prompt.yaml"
    prompt.write_text(
        "active_prompt_profile: default\nprofiles:\n  default:\n    system_prompt: hi\n"
        "    template: '{query}\\n{context}'\n",
        encoding="utf-8",
    )
    obs = _write(tmp_path / "obs.yaml", "log_level: INFO\nredact_sensitive_data: true\n")
    gov = _write(tmp_path / "gov.yaml", "enabled: true\nmax_cost_per_request_usd: 1\n")
    api = _write(tmp_path / "api.yaml", api_yaml or API_YAML)
    tenants = _write(
        tmp_path / "tenants.yaml",
        "enabled: false\ndefault_tenant: default\ntenants:\n  default:\n    workspace: default\n    app: default\n",
    )
    access = _write(
        tmp_path / "access.yaml",
        access_yaml
        or "enabled: false\ndefault_role: admin\nroles:\n  admin:\n    capabilities: []\n",
    )
    pipeline = pipeline or _Pipeline()

    def builder(**kwargs):
        return pipeline

    return create_app(
        models_config_path=models,
        retrieval_config_path=retrieval,
        prompt_config_path=prompt,
        governance_config_path=gov,
        observability_config_path=obs,
        api_config_path=api,
        tenants_config_path=tenants,
        access_control_config_path=access,
        pipeline_builder=builder,
    )


def _wait_for_terminal(client, op_id, headers=None, timeout=3.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/v1/operations/{op_id}", headers=headers or {})
        if resp.status_code == 200:
            last = resp.json()
            if last["status"] in {"completed", "failed", "cancelled"}:
                return last
        time.sleep(0.02)
    return last


def test_submit_async_query_returns_immediate_id_and_completes(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_Pipeline(delay=0.05))) as client:
        submit = client.post(
            "/v1/operations/query",
            json={"query": "hello", "top_k": 2},
            headers={"X-Client-Session": "sess-1"},
        )
        assert submit.status_code == 202
        body = submit.json()
        assert body["id"]
        assert body["request_id"] == body["id"]
        assert body["status"] in {"queued", "running", "completed"}
        final = _wait_for_terminal(
            client, body["id"], headers={"X-Client-Session": "sess-1"}
        )
        assert final["status"] == "completed"
        assert final["stage"] == "completed"
        assert final["result"]["response"] == "ok:hello"
        assert final["result"]["request_id"] == body["id"]


def test_get_operation_owner_scoped_with_client_session(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_Pipeline(delay=0.05))) as client:
        op = client.post(
            "/v1/operations/query",
            json={"query": "q"},
            headers={"X-Client-Session": "a"},
        ).json()["id"]
        _wait_for_terminal(client, op, headers={"X-Client-Session": "a"})
        forbidden = client.get(
            f"/v1/operations/{op}", headers={"X-Client-Session": "b"}
        )
        assert forbidden.status_code == 404
        assert forbidden.json()["failure_tags"] == ["operation_not_found"]
        allowed = client.get(f"/v1/operations/{op}", headers={"X-Client-Session": "a"})
        assert allowed.status_code == 200


def test_list_operations_filters_by_status_and_mine(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_Pipeline())) as client:
        h1 = {"X-Client-Session": "a"}
        h2 = {"X-Client-Session": "b"}
        op1 = client.post(
            "/v1/operations/query", json={"query": "q1"}, headers=h1
        ).json()["id"]
        op2 = client.post(
            "/v1/operations/query", json={"query": "q2"}, headers=h2
        ).json()["id"]
        _wait_for_terminal(client, op1, headers=h1)
        _wait_for_terminal(client, op2, headers=h2)
        mine = client.get(
            "/v1/operations?mine=true&status=completed", headers=h1
        )
        assert mine.status_code == 200
        ids = [o["id"] for o in mine.json()["operations"]]
        assert op1 in ids
        assert op2 not in ids


def test_operations_unified_list_includes_own_experiments(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_Pipeline())) as client:
        headers = {"X-Client-Session": "a"}
        op = client.post(
            "/v1/operations/query", json={"query": "q"}, headers=headers
        ).json()["id"]
        exp = client.post(
            "/v1/experiments",
            json={"kind": "single", "query": "q", "docs": ["d1"], "retriever_backend": "dummy"},
            headers=headers,
        ).json()["id"]
        _wait_for_terminal(client, op, headers=headers)
        deadline = time.time() + 3
        while time.time() < deadline:
            e = client.get(f"/v1/experiments/{exp}", headers=headers)
            if e.status_code == 200 and e.json()["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        listing = client.get("/v1/operations?mine=true", headers=headers)
        assert listing.status_code == 200
        ids = {o["id"] for o in listing.json()["operations"]}
        assert op in ids
        assert exp in ids
        kinds = {o["kind"] for o in listing.json()["operations"]}
        assert "query" in kinds
        assert "experiment" in kinds


def test_cross_owner_listing_requires_governance_capability(tmp_path):
    access = (
        "enabled: true\ndefault_role: viewer\nroles:\n"
        "  viewer:\n    capabilities: [query]\n"
        "  admin:\n    capabilities: [query, governance]\n"
        "api_keys:\n  viewer-key: viewer\n  admin-key: admin\n"
    )
    with TestClient(_app(tmp_path, access_yaml=access)) as client:
        denied = client.get(
            "/v1/operations?mine=false", headers={"X-API-Key": "viewer-key"}
        )
        assert denied.status_code == 403
        assert denied.json()["failure_tags"] == ["forbidden_operation_scope"]
        allowed = client.get(
            "/v1/operations?mine=false", headers={"X-API-Key": "admin-key"}
        )
        assert allowed.status_code == 200


def test_queue_full_returns_429(tmp_path):
    api = API_YAML.replace("max_workers: 1", "max_workers: 1").replace(
        "max_operations: 100", "max_operations: 1"
    )
    with TestClient(
        _app(tmp_path, pipeline=_Pipeline(delay=0.2), api_yaml=api)
    ) as client:
        first = client.post(
            "/v1/operations/query", json={"query": "one"}
        )
        assert first.status_code == 202
        second = client.post(
            "/v1/operations/query", json={"query": "two"}
        )
        assert second.status_code == 429
        assert second.json()["failure_tags"] == [
            "rate_limited",
            "operation_queue_full",
        ]


def test_failed_result_is_reported_and_recorded_once(tmp_path):
    failed = {
        "error": "boom",
        "failure_type": "unknown_failure",
        "failure_tags": ["upstream_failure"],
        "observability": {"status": "failed"},
    }
    with TestClient(_app(tmp_path, pipeline=_Pipeline(result=failed))) as client:
        op = client.post("/v1/operations/query", json={"query": "bad"}).json()["id"]
        final = _wait_for_terminal(client, op)
        assert final["status"] == "failed"
        assert final["failure_type"] == "unknown_failure"
        metrics = client.get("/v1/metrics").json()
        assert metrics["total_runs"] == 1
        assert metrics["failures_by_type"].get("unknown_failure") == 1


def test_runner_exception_is_recorded_as_failed(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_RaisingPipeline())) as client:
        op = client.post("/v1/operations/query", json={"query": "boom"}).json()["id"]
        final = _wait_for_terminal(client, op)
        assert final["status"] == "failed"
        assert "pipeline exploded" in final["error"]
        metrics = client.get("/v1/metrics").json()
        assert metrics["total_runs"] == 1


def test_sync_query_endpoints_unchanged(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_Pipeline())) as client:
        r1 = client.post("/v1/query", json={"query": "sync"})
        r2 = client.post("/query", json={"query": "legacy"})
        assert r1.status_code == 200
        assert r1.json()["response"] == "ok:sync"
        assert r2.status_code == 200
        assert r2.json()["response"] == "ok:legacy"


def test_async_completion_records_run_history(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_Pipeline())) as client:
        headers = {"X-Client-Session": "a"}
        op = client.post(
            "/v1/operations/query", json={"query": "history"}, headers=headers
        ).json()["id"]
        final = _wait_for_terminal(client, op, headers=headers)
        assert final["status"] == "completed"
        metrics = client.get("/v1/metrics")
        assert metrics.status_code == 200
        assert metrics.json()["total_runs"] == 1
        assert metrics.json()["operations"]["total"] >= 1


def test_disabled_operations_returns_503(tmp_path):
    api = API_YAML.replace("enabled: true", "enabled: false")
    with TestClient(_app(tmp_path, api_yaml=api)) as client:
        submit = client.post("/v1/operations/query", json={"query": "q"})
        assert submit.status_code == 503
        assert submit.json()["failure_type"] == "not_ready"


def test_recent_window_is_bounded(tmp_path):
    with TestClient(_app(tmp_path, pipeline=_Pipeline())) as client:
        resp = client.get("/v1/operations?recent_window_seconds=99999999")
        assert resp.status_code == 422


def test_operation_owner_prefers_authenticated_subject():
    request = SimpleNamespace(
        state=SimpleNamespace(subject="alice", tenant_id="tenant-a"),
        headers={"X-Client-Session": "spoof"},
    )
    assert operation_owner(request) == "subject:alice"


def test_operation_owner_session_is_tenant_qualified():
    request = SimpleNamespace(
        state=SimpleNamespace(subject=None, tenant_id="tenant-a"),
        headers={"X-Client-Session": "session-1"},
    )
    assert operation_owner(request) == "session:tenant-a:session-1"


def test_store_persistence_uses_ttl_and_never_stores_payload():
    store = _RecordingStore()
    service = OperationJobsService(
        max_workers=1,
        max_operations=5,
        store=store,
        store_ttl_seconds=12,
    )
    try:
        entry = service.submit_query(
            request_id="op-ttl",
            kind="query",
            owner="session:t:s",
            tenant="t",
            workspace=None,
            app=None,
            payload={"query": "sk-secret-value", "top_k": 1},
            runner=lambda: {"response": "done"},
        )
        assert entry["status"] == "queued"
        deadline = time.time() + 2
        while time.time() < deadline:
            final = service.get("op-ttl")
            if final and final["status"] == "completed":
                break
            time.sleep(0.01)
        assert final["status"] == "completed"
        assert store.writes
        for _key, value, ttl in store.writes:
            assert ttl == 12
            assert "sk-secret-value" not in str(value)
            assert "payload" not in value
    finally:
        service.shutdown()
