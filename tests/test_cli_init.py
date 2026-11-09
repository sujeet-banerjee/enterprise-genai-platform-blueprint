"""``genai init`` scaffolding CLI (issue #128, Workstream L).

The CLI must turn a golden path template (issue #127) into a project that:

- contains a complete, schema-valid config set,
- resolves the sample corpus from ``<target>/data``, and
- actually boots the application when ``GENAI_CONFIG_DIR`` points at it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest
import yaml

from app.cli import (
    DEFAULT_TEMPLATE,
    ScaffoldError,
    available_templates,
    main,
    scaffold,
)
from core.config.validator import validate_all

REPO_BASE = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_BASE / "deployment" / "templates"


def _hard_issues(config_dir: Path) -> Dict[str, list]:
    return {
        name: [str(issue) for issue in issues if issue.kind != "version-warning"]
        for name, issues in validate_all(config_dir).items()
        if any(issue.kind != "version-warning" for issue in issues)
    }


def test_available_templates_and_list_command(capsys: pytest.CaptureFixture[str]) -> None:
    names = set(available_templates())
    assert names == {"local-demo", "rag-assistant", "governed-enterprise"}
    assert DEFAULT_TEMPLATE == "rag-assistant"

    assert main(["templates", "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == names

    assert main(["templates"]) == 0
    assert "rag-assistant (recommended)" in capsys.readouterr().out


def test_init_scaffolds_valid_default_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "my-app"
    assert main(["init", str(target)]) == 0
    output = capsys.readouterr().out
    assert "Scaffolded 'rag-assistant'" in output
    assert f"GENAI_CONFIG_DIR={target / 'config'}" in output

    config_files = sorted(path.name for path in (target / "config").glob("*.yaml"))
    assert config_files == [
        "eval_datasets.yaml",
        "governance.yaml",
        "guardrails.yaml",
        "models.yaml",
        "observability.yaml",
        "prompt_config.yaml",
        "retrieval.yaml",
    ]
    assert _hard_issues(target / "config") == {}

    for name in ("docs.json", "benchmark.json", "knowledge_graph.json"):
        assert (target / "data" / name).is_file(), name

    retrieval = yaml.safe_load((target / "config" / "retrieval.yaml").read_text(encoding="utf-8"))
    assert retrieval["retrieval"]["retrievers"]["faiss"]["documents_path"] == "data/docs.json"


def test_init_local_demo_is_minimal_and_offline(tmp_path: Path) -> None:
    result = scaffold(tmp_path / "demo", template="local-demo", include_data=False)
    files = sorted(path.name for path in result.files)
    assert files == ["models.yaml", "prompt_config.yaml", "retrieval.yaml"]
    assert not (result.target / "data").exists()
    assert _hard_issues(result.config_dir) == {}
    models = yaml.safe_load((result.config_dir / "models.yaml").read_text(encoding="utf-8"))
    assert models["active_model"] == "dummy"


def test_init_refuses_to_overwrite_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "existing"
    (target / "config").mkdir(parents=True)
    marker = target / "config" / "keep-me.txt"
    marker.write_text("hand-written", encoding="utf-8")

    assert main(["init", str(target), "--template", "local-demo"]) == 1
    assert "already exists and is not empty" in capsys.readouterr().err
    assert marker.is_file()

    assert main(["init", str(target), "--template", "local-demo", "--force"]) == 0
    assert marker.read_text(encoding="utf-8") == "hand-written"
    assert (target / "config" / "retrieval.yaml").is_file()


def test_init_unknown_template_and_missing_templates_dir(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError) as unknown:
        scaffold(tmp_path / "a", template="does-not-exist")
    assert "Unknown template" in str(unknown.value)
    assert "rag-assistant" in str(unknown.value)

    empty = tmp_path / "no-templates"
    empty.mkdir()
    with pytest.raises(ScaffoldError) as missing:
        scaffold(tmp_path / "b", templates_dir=empty)
    assert "--templates-dir" in str(missing.value)


def test_init_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "json-app"
    assert main(["init", str(target), "--template", "governed-enterprise", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["template"] == "governed-enterprise"
    assert payload["config_dir"] == str((target / "config").resolve())
    assert len(payload["files"]) == 14


def test_validate_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good"
    assert main(["init", str(good), "--template", "local-demo"]) == 0
    capsys.readouterr()
    assert main(["validate", str(good / "config")]) == 0
    assert "OK models.yaml" in capsys.readouterr().out

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    bad = bad_dir / "models.yaml"
    bad.write_text("config_version: 1\nbogus_key: true\n", encoding="utf-8")
    assert main(["validate", str(bad_dir)]) == 1
    assert "INVALID models.yaml" in capsys.readouterr().out


def test_genai_console_script_is_declared() -> None:
    pyproject = (REPO_BASE / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in pyproject
    assert 'genai = "app.cli:main"' in pyproject


def test_ci_exercises_genai_init() -> None:
    workflow = (REPO_BASE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Scaffold with genai init" in workflow
    assert "python -m app.cli init" in workflow


def test_scaffolded_local_demo_boots_end_to_end(tmp_path: Path) -> None:
    target = tmp_path / "boot"
    init = subprocess.run(
        [sys.executable, "-m", "app.cli", "init", str(target), "--template", "local-demo"],
        cwd=str(REPO_BASE),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert init.returncode == 0, init.stderr + init.stdout

    script = """
import json
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    health = client.get("/health")
    ready = client.get("/ready")
    query = client.post("/v1/query", json={"query": "What is governance?", "top_k": 2})
    body = query.json()
    print(json.dumps({
        "health": health.status_code,
        "ready": ready.status_code,
        "ready_status": ready.json().get("status"),
        "query": query.status_code,
        "query_error": body.get("error"),
        "has_response": isinstance(body.get("response"), str) and bool(body.get("response")),
    }))
"""
    env = os.environ.copy()
    env["GENAI_CONFIG_DIR"] = str(target / "config")
    env["PYTHONPATH"] = str(REPO_BASE)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_BASE),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["health"] == 200
    assert payload["ready"] == 200
    assert payload["ready_status"] == "ready"
    assert payload["query"] == 200
    assert payload["query_error"] is None
    assert payload["has_response"] is True
