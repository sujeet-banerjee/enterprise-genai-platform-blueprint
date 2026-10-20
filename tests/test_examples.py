"""Tests for issue #31: runnable examples.

These run the example scripts through the same composition root the API uses,
against fast dummy configs (no model downloads), so the examples stay genuinely
runnable in CI.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"

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

SWAP_RETRIEVAL_YAML = """
retrieval:
  default_retriever: dummy
  similarity_metric: cosine
  top_k: 3
  retrievers:
    dummy:
      provider: dummy
    simple:
      provider: simple
      documents_path: data/docs.json
evaluation:
  enabled: false
  active_evaluator: dummy
  evaluators:
    dummy:
      provider: dummy
reranking:
  enabled: false
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_examples_directory_has_scripts_and_readme():
    assert (EXAMPLES_DIR / "README.md").is_file()
    scripts = list(EXAMPLES_DIR.glob("*.py"))
    assert scripts, "examples/ should contain at least one runnable script"


def test_example_scripts_compile_and_expose_main():
    for script in EXAMPLES_DIR.glob("*.py"):
        source = script.read_text(encoding="utf-8")
        tree = ast.parse(source)
        funcs = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        assert "main" in funcs, f"{script.name} should expose a main() entrypoint"


def test_examples_do_not_import_concrete_implementations():
    forbidden = ("core.implementations", "core.registry")
    for script in EXAMPLES_DIR.glob("*.py"):
        source = script.read_text(encoding="utf-8")
        for module in forbidden:
            assert f"import {module}" not in source, f"{script.name} imports {module}"


def test_run_query_example_executes_against_dummy_config(tmp_path):
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    env = {
        "GENAI_MODELS_CONFIG": str(models),
        "GENAI_RETRIEVAL_CONFIG": str(retrieval),
        "PYTHONPATH": str(REPO_ROOT),
    }
    completed = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "run_query.py"), "What is AI?"],
        cwd=str(REPO_ROOT),
        env={**_base_env(), **env},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Query: What is AI?" in completed.stdout
    assert "Response:" in completed.stdout


def test_run_query_example_uses_default_query_without_args(tmp_path):
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    env = {
        "GENAI_MODELS_CONFIG": str(models),
        "GENAI_RETRIEVAL_CONFIG": str(retrieval),
        "PYTHONPATH": str(REPO_ROOT),
    }
    completed = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "run_query.py")],
        cwd=str(REPO_ROOT),
        env={**_base_env(), **env},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    assert "What is machine learning?" in completed.stdout


def test_swap_components_example_executes(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write(config_dir / "models.yaml", MODELS_YAML)
    _write(
        config_dir / "retrieval.yaml",
        SWAP_RETRIEVAL_YAML,
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "docs.json").write_text(
        '["AI is the simulation of human intelligence."]', encoding="utf-8"
    )

    # swap_components copies REPO_ROOT/config; point REPO_ROOT at our fake repo.
    script = EXAMPLES_DIR / "swap_components.py"
    source = script.read_text(encoding="utf-8").replace(
        'REPO_ROOT = Path(__file__).resolve().parents[1]',
        f'REPO_ROOT = Path(r"{tmp_path}")',
    )
    patched = tmp_path / "swap_components.py"
    patched.write_text(source, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(patched)],
        cwd=str(tmp_path),
        env={**_base_env(), "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Default retriever from config:" in completed.stdout
    assert "LLM resolved from config:" in completed.stdout


def _base_env() -> dict:
    import os

    return dict(os.environ)
