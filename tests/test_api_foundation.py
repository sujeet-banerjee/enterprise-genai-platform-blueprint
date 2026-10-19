"""Tests for issue #30: the API foundation.

Covers the app factory + lifespan (no pipeline built at import), ``/health`` and
``/ready``, the versioned ``/v1/query`` with the legacy ``/query`` alias, the
error envelope + ``X-Request-ID`` echo, and the config-driven API-key stub.
"""

from fastapi.testclient import TestClient

from app.main import create_app


class _FakePipeline:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list = []

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "raise_on_failure": raise_on_failure,
                "request_id": request_id,
            }
        )
        if self.fail:
            return {
                "response": None,
                "error": "boom",
                "failure_type": "llm_failure",
                "failure_tags": ["llm_failure"],
                "observability": {"request_id": request_id},
            }
        return {
            "response": f"echo:{query}",
            "retrieved_docs": [],
            "retrieval_scores": [],
            "metrics": {},
            "cost": {},
            "token_budget": {},
            "latency": {},
            "failure_tags": [],
            "observability": {"request_id": request_id, "top_k": top_k or 3},
        }


def _make_app(pipeline=None, **kwargs):
    pipeline = pipeline or _FakePipeline()

    def builder(**_ignored):
        return pipeline

    return create_app(pipeline_builder=builder, **kwargs)


def _write_api_config(tmp_path, *, require: bool, api_key: str = "") -> str:
    path = tmp_path / "api.yaml"
    path.write_text(
        f"require_api_key: {str(require).lower()}\napi_key: \"{api_key}\"\n",
        encoding="utf-8",
    )
    return str(path)


def test_pipeline_is_built_in_lifespan_not_at_factory_time():
    app = _make_app()
    # create_app() must not build the pipeline; only startup does.
    assert getattr(app.state, "pipeline", None) is None
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert app.state.pipeline is not None


def test_health_is_public_and_ok():
    with TestClient(_make_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_ready_after_startup():
    with TestClient(_make_app()) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_reports_not_ready_without_startup():
    client = TestClient(_make_app())
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_v1_query_returns_envelope_fields():
    with TestClient(_make_app()) as client:
        response = client.post("/v1/query", json={"query": "hello"})
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "echo:hello"
    assert data["error"] is None
    assert data["failure_type"] is None
    assert data["failure_tags"] == []
    assert data["request_id"]


def test_v1_query_and_legacy_query_match():
    with TestClient(_make_app()) as client:
        v1 = client.post("/v1/query", json={"query": "same"}).json()
        legacy = client.post("/query", json={"query": "same"}).json()
    assert v1["response"] == legacy["response"] == "echo:same"


def test_request_id_header_is_echoed():
    with TestClient(_make_app()) as client:
        response = client.post(
            "/v1/query", json={"query": "hello"}, headers={"X-Request-ID": "req-123"}
        )
    assert response.headers["X-Request-ID"] == "req-123"
    assert response.json()["request_id"] == "req-123"


def test_request_id_is_generated_when_absent():
    with TestClient(_make_app()) as client:
        response = client.post("/v1/query", json={"query": "hello"})
    assert response.headers.get("X-Request-ID")
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_top_k_forwarded_and_include_trace_can_drop_observability():
    pipeline = _FakePipeline()
    with TestClient(_make_app(pipeline)) as client:
        response = client.post(
            "/v1/query", json={"query": "hello", "top_k": 5, "include_trace": False}
        )
        assert pipeline.calls[-1]["top_k"] == 5
    assert response.status_code == 200
    assert "observability" not in response.json()


def test_failure_returns_error_envelope_with_status():
    with TestClient(_make_app(_FakePipeline(fail=True))) as client:
        response = client.post("/v1/query", json={"query": "hello"})
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "boom"
    assert data["failure_type"] == "llm_failure"
    assert data["failure_tags"] == ["llm_failure"]


def test_auth_disabled_by_default():
    with TestClient(_make_app()) as client:
        response = client.post("/v1/query", json={"query": "hello"})
    assert response.status_code == 200


def test_auth_enabled_rejects_missing_or_wrong_key(tmp_path):
    app = _make_app(api_config_path=_write_api_config(tmp_path, require=True, api_key="s3cr3t"))
    with TestClient(app) as client:
        missing = client.post("/v1/query", json={"query": "hello"})
        wrong = client.post("/v1/query", json={"query": "hello"}, headers={"X-API-Key": "nope"})
        good = client.post("/v1/query", json={"query": "hello"}, headers={"X-API-Key": "s3cr3t"})
    assert missing.status_code == 401
    assert missing.json()["failure_type"] == "unauthorized"
    assert wrong.status_code == 401
    assert good.status_code == 200


def test_auth_enabled_keeps_health_public(tmp_path):
    app = _make_app(api_config_path=_write_api_config(tmp_path, require=True, api_key="s3cr3t"))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
