"""Tests for issue #40: the Streamlit console.

Two contract guarantees are covered here without needing Streamlit installed:

1. **HTTP-only rule** — ``ui/`` never imports ``app.pipeline``, ``core.*`` or any
   backend module (AST-based guard, per ``docs/ux-and-api.md`` §3.2).
2. **Client correctness** — ``ui.client.ApiClient`` talks to the real FastAPI app
   and produces the payloads the screens render, including failure-taxonomy data.
"""

import ast
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import pytest

from app.main import create_app

REPO_BASE = Path(__file__).resolve().parents[1]
UI_DIR = REPO_BASE / "ui"
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"

FORBIDDEN_ROOTS = ("app", "core")


def _ui_python_files() -> List[Path]:
    return sorted(UI_DIR.glob("*.py"))


def _imported_modules(tree: ast.AST) -> List[str]:
    modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


# -- HTTP-only guard ------------------------------------------------------


@pytest.mark.parametrize("path", _ui_python_files(), ids=lambda p: p.name)
def test_ui_files_do_not_import_backend(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = [
        module
        for module in _imported_modules(tree)
        if module.split(".")[0] in FORBIDDEN_ROOTS
    ]
    assert not offenders, f"{path.name} imports backend modules {offenders}"


def test_ui_has_no_concrete_pipeline_imports():
    # Explicit regression guard for the exact strings the issue calls out.
    for path in _ui_python_files():
        text = path.read_text(encoding="utf-8")
        assert "app.pipeline" not in text
        assert "import core" not in text
        assert "from core" not in text


def test_ui_directory_exists_with_expected_entrypoint():
    assert (UI_DIR / "app.py").exists()
    assert (UI_DIR / "client.py").exists()
    assert (REPO_BASE / "requirements-ui.txt").exists()


# -- client against the real API -----------------------------------------

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


class _FakePipeline:
    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        if query == "fail":
            return {
                "response": None,
                "error": "boom",
                "failure_type": "llm_failure",
                "failure_tags": ["llm_failure"],
                "cost": {},
                "latency": {"total_ms": 1.0},
                "observability": {"status": "failed"},
            }
        return {
            "response": f"echo:{query}",
            "failure_tags": [],
            "retrieved_docs": ["doc-a"],
            "retrieved_docs_with_scores": [{"content": "doc-a", "score": 0.9, "metadata": {}}],
            "cost": {"estimated_cost_usd": 0.001},
            "latency": {"embedding": 1.0, "total_ms": 2.0},
            "observability": {"status": "success"},
        }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _tmp_configs(tmp_path: Path) -> Dict[str, Any]:
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml", "enabled: true\nmax_cost_per_request_usd: 0.5\n"
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            "require_api_key: false\napi_key: \"\"\nallow_rebuild: false\nmax_batch_size: 5\n",
        ),
    }


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    """ApiClient whose ``requests.request`` is routed into a TestClient."""
    pytest.importorskip("requests")
    from fastapi.testclient import TestClient

    import ui.client as client_module

    app = create_app(pipeline_builder=lambda **_ignored: _FakePipeline(), **_tmp_configs(tmp_path))
    test_client = TestClient(app)
    test_client.__enter__()

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        path = urlparse(url).path
        return test_client.request(method, path, headers=headers or {}, **kwargs)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    yield client_module.ApiClient(base_url="http://testserver")
    test_client.__exit__(None, None, None)


def test_client_health_and_ready(api_client):
    assert api_client.health().data["status"] == "ok"
    ready = api_client.ready()
    assert ready.ok
    assert "components" in ready.data


def test_client_query_success(api_client):
    result = api_client.query("hello")
    assert result.ok
    assert result.data["response"] == "echo:hello"
    assert result.data["retrieved_docs_with_scores"][0]["score"] == 0.9
    assert result.request_id


def test_client_query_failure_exposes_taxonomy(api_client):
    result = api_client.query("fail")
    assert not result.ok
    assert result.failure_type == "llm_failure"
    assert result.failure_tags == ["llm_failure"]


def test_client_batch_query(api_client):
    result = api_client.batch_query(["a", "b"])
    assert result.ok
    assert result.data["summary"]["batch_size"] == 2
    assert result.data["summary"]["succeeded"] == 2


def test_client_introspection_endpoints(api_client):
    assert api_client.models().data["active"] == "dummy"
    assert api_client.retrievers().data["default_retriever"] == "dummy"
    assert api_client.rerankers().ok
    assert api_client.evaluators().ok
    assert "config" in api_client.effective_config().data


def test_client_ops_endpoints(api_client):
    api_client.query("hello")
    assert api_client.governance_status().ok
    metrics = api_client.metrics()
    assert metrics.ok
    assert metrics.data["total_runs"] == 1
