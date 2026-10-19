"""Tests for issue #37: runtime component swap via POST /v1/pipeline:rebuild.

Acceptance:
- api.allow_rebuild=false -> 403 standard envelope,
- successful rebuild changes /ready summary + subsequent query behaviour,
- invalid override -> 4xx with the old pipeline still serving,
- governance cannot be loosened without explicit opt-in.
"""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import create_app

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"
REPO_OBSERVABILITY = REPO_BASE / "config" / "observability.yaml"
REPO_API = REPO_BASE / "config" / "api.yaml"


class _LLM:
    def __init__(self, model_name):
        self.model_name = model_name


class _Retriever:
    def __init__(self, name):
        self.retriever_name = name


class _Evaluator:
    pass


class _FakePipeline:
    def __init__(self, active_model, default_retriever, governance=None):
        self.llm = _LLM(active_model)
        self.retriever = _Retriever(default_retriever)
        self.reranker = None
        self.evaluator = _Evaluator()
        self.governance = dict(governance or {})

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return {
            "response": f"retriever={self.retriever.retriever_name}",
            "failure_tags": [],
            "observability": {},
        }


def _load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _recording_builder(calls):
    def builder(
        models_config_path=None,
        prompt_config_path=None,
        retrieval_config_path=None,
        governance_config_path=None,
        observability_config_path=None,
        **_ignored,
    ):
        calls.append(
            {
                "models_config_path": Path(models_config_path),
                "retrieval_config_path": Path(retrieval_config_path),
                "governance_config_path": Path(governance_config_path),
            }
        )
        models_cfg = _load(models_config_path)
        retrieval_cfg = _load(retrieval_config_path)
        governance_cfg = _load(governance_config_path)

        active_model = models_cfg["active_model"]
        if active_model == "broken":
            raise ValueError("model 'broken' is not configured")
        default_retriever = retrieval_cfg["retrieval"]["default_retriever"]
        if default_retriever not in {"simple", "faiss", "dummy"}:
            raise ValueError(f"unknown retriever provider: {default_retriever}")

        return _FakePipeline(active_model, default_retriever, governance_cfg)

    return builder


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path, *, allow_rebuild: bool = True):
    models = _write(
        tmp_path / "models.yaml",
        """
active_model: dummy
active_embedding_model: emb-a
models:
  dummy:
    provider: dummy
    context_window: 4096
  broken:
    provider: dummy
    context_window: 4096
embedding_models:
  emb-a:
    provider: dummy
    model_name: emb-a
    api_key: sk-supersecret-value
""",
    )
    retrieval = _write(
        tmp_path / "retrieval.yaml",
        """
retrieval:
  default_retriever: faiss
  similarity_metric: cosine
  top_k: 3
  retrievers:
    faiss:
      provider: faiss
    simple:
      provider: simple
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
""",
    )
    governance = _write(
        tmp_path / "governance.yaml",
        """
enabled: true
max_cost_per_request_usd: 1.0
safety_margin_tokens: 200
avg_chunk_tokens: 400
""",
    )
    api = _write(
        tmp_path / "api.yaml",
        f"""
require_api_key: false
api_key: ""
allow_rebuild: {"true" if allow_rebuild else "false"}
""",
    )
    return {
        "models_config_path": models,
        "retrieval_config_path": retrieval,
        "governance_config_path": governance,
        "api_config_path": api,
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": REPO_OBSERVABILITY,
    }


def _make_app(config_paths, calls=None):
    return create_app(
        pipeline_builder=_recording_builder(calls if calls is not None else []),
        **config_paths,
    )


# -- gatekeeping ----------------------------------------------------------


def test_rebuild_disabled_returns_403_and_keeps_old_pipeline(tmp_path):
    config_paths = _tmp_configs(tmp_path, allow_rebuild=False)
    calls = []

    with TestClient(_make_app(config_paths, calls)) as client:
        before = client.post("/v1/query", json={"query": "hi", "include_trace": False})
        assert before.json()["response"] == "retriever=faiss"

        response = client.post("/v1/pipeline:rebuild", json={})

        after = client.post("/v1/query", json={"query": "hi", "include_trace": False})
        ready = client.get("/ready")

    assert response.status_code == 403
    body = response.json()
    assert "rebuild_disabled" in body["failure_tags"]
    assert body["request_id"]
    assert after.json()["response"] == "retriever=faiss"
    assert ready.json()["config_revision"] == 0
    assert len(calls) == 1  # only the lifespan build; rebuild never built anything


def test_rebuild_503_without_lifespan():
    client = TestClient(create_app(pipeline_builder=_recording_builder([])))
    response = client.post("/v1/pipeline:rebuild", json={})
    assert response.status_code == 503
    assert response.json()["failure_type"] == "not_ready"


# -- successful rebuild ---------------------------------------------------


def test_successful_rebuild_swaps_pipeline_ready_and_config(tmp_path):
    config_paths = _tmp_configs(tmp_path)
    calls = []

    with TestClient(_make_app(config_paths, calls)) as client:
        assert client.get("/ready").json()["components"]["retriever"] == "faiss"

        response = client.post(
            "/v1/pipeline:rebuild",
            json={
                "overrides": {
                    "active_model": "dummy",
                    "default_retriever": "simple",
                    "similarity_metric": "l2",
                    "top_k": 5,
                }
            },
        )
        body = response.json()
        ready = client.get("/ready")
        query = client.post("/v1/query", json={"query": "hi", "include_trace": False})
        config = client.get("/v1/config").json()["config"]

        # Candidate configs were materialised as files, not silently ignored.
        assert len(calls) == 2  # lifespan build + rebuild
        rebuild_call = calls[-1]
        assert rebuild_call["retrieval_config_path"].parent != config_paths["retrieval_config_path"]
        assert rebuild_call["retrieval_config_path"].exists()

    assert response.status_code == 200
    assert body["status"] == "rebuilt"
    assert body["config_revision"] == 1
    assert body["components"]["llm"] == "dummy"
    assert body["components"]["retriever"] == "simple"
    assert body["applied_overrides"] == {
        "active_model": "dummy",
        "default_retriever": "simple",
        "similarity_metric": "l2",
        "top_k": 5,
    }
    retrieval_cfg = body["effective_config"]["retrieval"]["retrieval"]
    assert retrieval_cfg["default_retriever"] == "simple"
    assert retrieval_cfg["similarity_metric"] == "l2"
    assert retrieval_cfg["top_k"] == 5

    # /ready reflects the new pipeline (summary + revision).
    assert ready.json()["status"] == "ready"
    assert ready.json()["config_revision"] == 1
    assert ready.json()["components"]["retriever"] == "simple"

    # Subsequent queries use the swapped pipeline.
    assert query.json()["response"] == "retriever=simple"

    # Introspection was swapped too, from the same candidate config.
    assert config["retrieval"]["retrieval"]["default_retriever"] == "simple"


def test_rebuild_with_no_overrides_is_a_clean_noop_swap(tmp_path):
    config_paths = _tmp_configs(tmp_path)

    with TestClient(_make_app(config_paths)) as client:
        response = client.post("/v1/pipeline:rebuild", json={})
        body = response.json()
        query = client.post("/v1/query", json={"query": "hi", "include_trace": False})

    assert response.status_code == 200
    assert body["config_revision"] == 1
    assert body["applied_overrides"] == {}
    assert body["governance_overrides_applied"] is False
    assert body["components"]["retriever"] == "faiss"
    assert query.json()["response"] == "retriever=faiss"


# -- failed validation ----------------------------------------------------


def test_invalid_rebuild_keeps_old_pipeline_serving(tmp_path):
    config_paths = _tmp_configs(tmp_path)

    with TestClient(_make_app(config_paths)) as client:
        response = client.post(
            "/v1/pipeline:rebuild",
            json={"overrides": {"default_retriever": "does-not-exist"}},
        )
        after_query = client.post("/v1/query", json={"query": "hi", "include_trace": False})
        ready = client.get("/ready")
        retrievers = client.get("/v1/retrievers").json()

    assert response.status_code == 400
    body = response.json()
    assert body["failure_type"] == "unknown_failure"
    assert "invalid_rebuild_config" in body["failure_tags"]
    # Old pipeline still serves queries and introspection still shows old config.
    assert after_query.json()["response"] == "retriever=faiss"
    assert ready.json()["config_revision"] == 0
    assert ready.json()["components"]["retriever"] == "faiss"
    assert retrievers["default_retriever"] == "faiss"


def test_invalid_model_override_keeps_old_pipeline_serving(tmp_path):
    config_paths = _tmp_configs(tmp_path)

    with TestClient(_make_app(config_paths)) as client:
        response = client.post(
            "/v1/pipeline:rebuild", json={"overrides": {"active_model": "broken"}}
        )
        after_query = client.post("/v1/query", json={"query": "hi", "include_trace": False})

    assert response.status_code == 400
    assert "invalid_rebuild_config" in response.json()["failure_tags"]
    assert after_query.json()["response"] == "retriever=faiss"


# -- governance safety ----------------------------------------------------


def test_governance_override_without_opt_in_is_rejected(tmp_path):
    config_paths = _tmp_configs(tmp_path)

    with TestClient(_make_app(config_paths)) as client:
        response = client.post(
            "/v1/pipeline:rebuild",
            json={"governance": {"max_cost_per_request_usd": 999.0}},
        )
        ready = client.get("/ready")

    assert response.status_code == 400
    body = response.json()
    assert "governance_override_requires_opt_in" in body["failure_tags"]
    assert ready.json()["config_revision"] == 0


def test_governance_override_with_opt_in_is_applied_and_echoed(tmp_path):
    config_paths = _tmp_configs(tmp_path)

    with TestClient(_make_app(config_paths)) as client:
        response = client.post(
            "/v1/pipeline:rebuild",
            json={
                "governance": {"max_cost_per_request_usd": 0.25},
                "allow_governance_override": True,
            },
        )
        body = response.json()
        ready = client.get("/ready")

    assert response.status_code == 200
    assert body["governance_overrides_applied"] is True
    assert body["effective_config"]["governance"]["max_cost_per_request_usd"] == 0.25
    assert body["config_revision"] == 1
    assert ready.json()["config_revision"] == 1


# -- response contract ----------------------------------------------------


def test_rebuild_effective_config_redacts_secrets(tmp_path):
    config_paths = _tmp_configs(tmp_path)

    with TestClient(_make_app(config_paths)) as client:
        body = client.post("/v1/pipeline:rebuild", json={}).json()

    dumped = str(body["effective_config"])
    assert "sk-supersecret-value" not in dumped
    assert "[REDACTED]" in dumped


def test_rebuild_rejects_unknown_override_keys(tmp_path):
    config_paths = _tmp_configs(tmp_path)

    with TestClient(_make_app(config_paths)) as client:
        response = client.post(
            "/v1/pipeline:rebuild", json={"overrides": {"nonsense": 1}}
        )

    assert response.status_code == 422


def test_openapi_exposes_rebuild_schema():
    client = TestClient(create_app(pipeline_builder=_recording_builder([])))
    schema = client.get("/openapi.json").json()
    assert "/v1/pipeline:rebuild" in schema["paths"]
    components = schema["components"]["schemas"]
    for name in ("RebuildRequest", "RebuildResponse", "RebuildOverrides", "RebuildComponents"):
        assert name in components
    request_body = schema["paths"]["/v1/pipeline:rebuild"]["post"]["requestBody"]
    assert "RebuildRequest" in str(request_body)


