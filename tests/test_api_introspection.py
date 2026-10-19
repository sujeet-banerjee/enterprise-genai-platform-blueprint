"""Tests for issue #35: introspection endpoints.

Verifies registry listings, active flags, typed OpenAPI models and, critically,
that `/v1/config` never leaks secrets (config-file keys or env-resolved values).
"""

from fastapi.testclient import TestClient

from app.main import create_app


class _FakePipeline:
    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return {"response": "ok", "failure_tags": [], "observability": {}}


def _make_app(**kwargs):
    def builder(**_ignored):
        return _FakePipeline()

    return create_app(pipeline_builder=builder, **kwargs)


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_config_endpoint_returns_config_sections():
    with TestClient(_make_app()) as client:
        response = client.get("/v1/config")
    assert response.status_code == 200
    config = response.json()["config"]
    for section in ("models", "retrieval", "prompt", "governance", "observability", "api"):
        assert section in config


def test_config_endpoint_redacts_secrets(tmp_path):
    models = _write(
        tmp_path / "models.yaml",
        """
active_model: dummy
active_embedding_model: dummy
models:
  dummy:
    provider: dummy
    api_key: sk-supersecret-value
embedding_models:
  dummy:
    provider: dummy
    model_name: dummy-embedder
""",
    )
    retrieval = _write(
        tmp_path / "retrieval.yaml",
        """
retrieval:
  default_retriever: dummy
  similarity_metric: cosine
  retrievers:
    dummy:
      provider: dummy
evaluation:
  enabled: false
reranking:
  enabled: false
""",
    )

    with TestClient(_make_app(models_config_path=models, retrieval_config_path=retrieval)) as client:
        body = client.get("/v1/config").text

    assert "sk-supersecret-value" not in body
    assert "[REDACTED]" in body


def test_config_endpoint_never_leaks_env_resolved_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-only-secret")

    with TestClient(_make_app()) as client:
        body = client.get("/v1/config").text

    assert "sk-env-only-secret" not in body


def test_models_endpoint_lists_models_with_active_flag():
    with TestClient(_make_app()) as client:
        data = client.get("/v1/models").json()

    names = [model["name"] for model in data["models"]]
    assert "local-qwen" in names
    active = [model["name"] for model in data["models"] if model["active"]]
    assert active == [data["active"]]
    assert data["active"] == "local-qwen"
    assert data["active_config"]["context_window"] > 0


def test_embedding_models_endpoint_lists_models_with_active_flag():
    with TestClient(_make_app()) as client:
        data = client.get("/v1/embedding-models").json()

    names = [model["name"] for model in data["embedding_models"]]
    assert "all-MiniLM-L6-v2" in names
    active = [model["name"] for model in data["embedding_models"] if model["active"]]
    assert active == [data["active"]]
    assert data["active"] == "all-MiniLM-L6-v2"


def test_retrievers_endpoint_reports_default_and_metric():
    with TestClient(_make_app()) as client:
        data = client.get("/v1/retrievers").json()

    assert data["default_retriever"] == "faiss"
    assert data["similarity_metric"] == "cosine"
    assert {"faiss", "simple", "dummy"} <= set(data["providers"])
    keys = {item["key"] for item in data["retrievers"]}
    assert {"faiss", "simple", "dummy"} <= keys


def test_rerankers_endpoint_reports_enabled_and_active():
    with TestClient(_make_app()) as client:
        data = client.get("/v1/rerankers").json()

    assert data["enabled"] is True
    assert data["active_reranker"] == "simple"
    assert {"simple", "cross_encoder", "dummy", "none"} <= set(data["providers"])


def test_evaluators_endpoint_reports_enabled_and_active():
    with TestClient(_make_app()) as client:
        data = client.get("/v1/evaluators").json()

    assert data["enabled"] is True
    assert data["active_evaluator"] == "semantic"
    assert {"semantic", "llm_judge", "dummy", "noop"} <= set(data["providers"])


def test_listings_follow_custom_config_paths(tmp_path):
    models = _write(
        tmp_path / "models.yaml",
        """
active_model: custom-llm
active_embedding_model: custom-emb
models:
  custom-llm:
    provider: dummy
    context_window: 1024
embedding_models:
  custom-emb:
    provider: dummy
    model_name: org/custom-embedder
""",
    )
    retrieval = _write(
        tmp_path / "retrieval.yaml",
        """
retrieval:
  default_retriever: simple
  similarity_metric: l2
  retrievers:
    simple:
      provider: simple
evaluation:
  enabled: false
  active_evaluator: dummy
  evaluators:
    dummy:
      provider: dummy
reranking:
  enabled: false
  active_reranker: none
  rerankers:
    none:
      provider: none
""",
    )

    with TestClient(_make_app(models_config_path=models, retrieval_config_path=retrieval)) as client:
        models_data = client.get("/v1/models").json()
        embedding_data = client.get("/v1/embedding-models").json()
        retrievers_data = client.get("/v1/retrievers").json()
        rerankers_data = client.get("/v1/rerankers").json()
        evaluators_data = client.get("/v1/evaluators").json()

    assert models_data["active"] == "custom-llm"
    assert embedding_data["active"] == "custom-emb"
    assert retrievers_data["default_retriever"] == "simple"
    assert retrievers_data["similarity_metric"] == "l2"
    assert rerankers_data["enabled"] is False
    assert evaluators_data["enabled"] is False


def test_introspection_returns_503_without_startup():
    client = TestClient(_make_app())
    response = client.get("/v1/models")
    assert response.status_code == 503
    assert response.json()["failure_type"] == "not_ready"


def test_openapi_exposes_typed_introspection_models():
    client = TestClient(_make_app())
    schema = client.get("/openapi.json").json()
    components = schema["components"]["schemas"]
    for name in (
        "EffectiveConfigResponse",
        "ModelsResponse",
        "EmbeddingModelsResponse",
        "RetrieversResponse",
        "RerankersResponse",
        "EvaluatorsResponse",
    ):
        assert name in components
    for path in (
        "/v1/config",
        "/v1/models",
        "/v1/embedding-models",
        "/v1/retrievers",
        "/v1/rerankers",
        "/v1/evaluators",
    ):
        assert path in schema["paths"]
