"""Golden path templates (issue #127, Workstream L).

Golden paths are opinionated, schema-validated config sets under
``deployment/templates/``. These tests:

- discover every template and require the minimum config files + README row,
- validate every shipped template YAML against its schema (#46 validator),
- refuse templates that ship secrets or unresolved secret references,
- assert the opinionated posture of each path, and
- genuinely boot each template (``/health`` + ``/ready`` + ``/v1/query``) with
  the real application factory.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from core.config.validator import validate_config_file

REPO_BASE = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_BASE / "deployment" / "templates"
README = TEMPLATES / "README.md"

TEMPLATE_DIRS = sorted(p for p in TEMPLATES.iterdir() if p.is_dir())
TEMPLATE_IDS = [p.name for p in TEMPLATE_DIRS]
REQUIRED_FILES = ("models.yaml", "prompt_config.yaml", "retrieval.yaml")

# create_app config-path keyword -> filename inside a template.
CONFIG_KWARGS: Dict[str, str] = {
    "models_config_path": "models.yaml",
    "prompt_config_path": "prompt_config.yaml",
    "retrieval_config_path": "retrieval.yaml",
    "governance_config_path": "governance.yaml",
    "observability_config_path": "observability.yaml",
    "api_config_path": "api.yaml",
    "audit_config_path": "audit.yaml",
    "access_control_config_path": "access_control.yaml",
    "resilience_config_path": "resilience.yaml",
    "guardrails_config_path": "guardrails.yaml",
    "tenants_config_path": "tenants.yaml",
    "identity_config_path": "identity.yaml",
    "attribution_config_path": "attribution.yaml",
    "acl_config_path": "acl.yaml",
    "persistence_config_path": "persistence.yaml",
}


def _load(template: str, filename: str) -> dict:
    return yaml.safe_load((TEMPLATES / template / filename).read_text(encoding="utf-8")) or {}


def test_templates_discovered_and_documented() -> None:
    assert set(TEMPLATE_IDS) == {"local-demo", "rag-assistant", "governed-enterprise"}
    assert README.is_file()
    readme = README.read_text(encoding="utf-8")
    for name in TEMPLATE_IDS:
        assert f"`{name}`" in readme or name in readme, f"README omits {name}"
        for required in REQUIRED_FILES:
            assert (TEMPLATES / name / required).is_file(), f"{name} lacks {required}"


@pytest.mark.parametrize(
    "template",
    TEMPLATE_DIRS,
    ids=TEMPLATE_IDS,
)
def test_every_template_config_validates(template: Path) -> None:
    yaml_files = sorted(template.glob("*.yaml"))
    assert yaml_files, f"{template.name} ships no config files"
    failures = {}
    for path in yaml_files:
        hard = [i for i in validate_config_file(path) if i.kind != "version-warning"]
        if hard:
            failures[path.name] = [str(issue) for issue in hard]
    assert not failures, f"invalid template configs in {template.name}: {failures}"


def test_templates_do_not_ship_secrets_or_unresolved_refs() -> None:
    problems = []
    for template in TEMPLATE_DIRS:
        for path in template.glob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            if "sk-" in text:
                problems.append(f"{path}: looks like an API key")
            if "${" in text or "env:" in text:
                problems.append(f"{path}: unresolved secret reference")
            data = yaml.safe_load(text) or {}
            api_key = data.get("api_key")
            if isinstance(api_key, str) and api_key.strip():
                problems.append(f"{path}: non-empty api_key")
    assert not problems, problems


def test_local_demo_posture() -> None:
    models = _load("local-demo", "models.yaml")
    assert models["active_model"] == "dummy"
    assert models["active_embedding_model"] == "dummy"
    retrieval = _load("local-demo", "retrieval.yaml")
    assert retrieval["retrieval"]["retrievers"]["dummy"]["provider"] == "dummy"
    assert retrieval["evaluation"]["enabled"] is False
    assert retrieval["reranking"]["enabled"] is False
    # Minimal path: policy/observability files are intentionally absent.
    assert not (TEMPLATES / "local-demo" / "governance.yaml").exists()


def test_rag_assistant_is_the_recommended_path() -> None:
    models = _load("rag-assistant", "models.yaml")
    assert models["active_model"] == "local-qwen"
    assert models["active_embedding_model"] == "all-MiniLM-L6-v2"
    retrieval = _load("rag-assistant", "retrieval.yaml")
    assert retrieval["retrieval"]["default_retriever"] == "faiss"
    assert retrieval["evaluation"]["enabled"] is True
    assert retrieval["evaluation"]["active_evaluator"] == "semantic"
    assert retrieval["reranking"]["enabled"] is True
    assert retrieval["chunking"]["enabled"] is True
    governance = _load("rag-assistant", "governance.yaml")
    assert governance["enabled"] is True
    guardrails = _load("rag-assistant", "guardrails.yaml")
    assert guardrails["enabled"] is True
    assert guardrails["profile"] == "standard"
    datasets = _load("rag-assistant", "eval_datasets.yaml")
    assert datasets["enabled"] is True
    assert "benchmark" in datasets["datasets"]


def test_governed_enterprise_posture() -> None:
    models = _load("governed-enterprise", "models.yaml")
    assert models["active_model"] == "dummy"  # deterministic CI smoke
    assert "dummy-fallback" in models["models"]
    guardrails = _load("governed-enterprise", "guardrails.yaml")
    assert guardrails["enabled"] is True
    assert guardrails["profile"] == "strict"
    access = _load("governed-enterprise", "access_control.yaml")
    assert access["enabled"] is True
    assert access["default_role"] == "viewer"
    assert _load("governed-enterprise", "tenants.yaml")["enabled"] is True
    assert _load("governed-enterprise", "audit.yaml")["enabled"] is True
    assert _load("governed-enterprise", "acl.yaml")["enabled"] is True
    assert _load("governed-enterprise", "attribution.yaml")["enabled"] is True
    resilience = _load("governed-enterprise", "resilience.yaml")["resilience"]
    assert resilience["enabled"] is True
    assert resilience["fallback_models"] == ["dummy-fallback"]
    assert _load("governed-enterprise", "retrieval.yaml")["cache"]["enabled"] is True


def test_ci_validates_golden_path_templates() -> None:
    workflow = (REPO_BASE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Validate golden path templates" in workflow
    assert "app.config_validate deployment/templates/*/*.yaml" in workflow


def _materialize(template: Path, tmp_path: Path) -> Dict[str, Path]:
    """Copy a template into ``tmp/config`` and seed ``tmp/data``."""
    config_dir = tmp_path / "config"
    shutil.copytree(template, config_dir)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ("docs.json", "benchmark.json", "knowledge_graph.json"):
        source = REPO_BASE / "data" / name
        if source.is_file():
            shutil.copy2(source, data_dir / name)
    # Point every optional config at its template copy (or a missing path so the
    # platform falls back to documented safe defaults).
    return {kw: config_dir / filename for kw, filename in CONFIG_KWARGS.items()}


@pytest.mark.parametrize("template", TEMPLATE_DIRS, ids=TEMPLATE_IDS)
def test_template_boots_and_serves_query(template: Path, tmp_path: Path) -> None:
    kwargs = _materialize(template, tmp_path)
    app = create_app(**kwargs)
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        query = client.post(
            "/v1/query",
            json={"query": "What is artificial intelligence?", "top_k": 2},
        )

    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert query.status_code == 200, query.text
    body = query.json()
    assert body.get("error") is None, body
    assert isinstance(body.get("response"), str) and body["response"]
    assert "observability" in body


def test_template_data_paths_resolve_after_install(tmp_path: Path) -> None:
    """Installed templates resolve ``data/*.json`` relative to the config parent."""
    kwargs = _materialize(TEMPLATES / "rag-assistant", tmp_path)
    retrieval_path = kwargs["retrieval_config_path"]
    retrieval = yaml.safe_load(retrieval_path.read_text(encoding="utf-8"))
    documents_path = retrieval["retrieval"]["retrievers"]["faiss"]["documents_path"]
    resolved = (retrieval_path.resolve().parent.parent / documents_path).resolve()
    assert resolved.is_file(), f"{documents_path} does not resolve to a real corpus"
    assert json.loads(resolved.read_text(encoding="utf-8"))
