"""Deployment artifacts + config-dir seam (issue #65 / G0).

These tests guard the *contract* the deployment work relies on:
- ``GENAI_CONFIG_DIR`` redirects the composition root's config discovery without
  changing the default (backward compatible).
- the container image is hardened (multi-stage, non-root, healthchecked).
- the single-node Compose reference is genuine (probes, volumes, limits, secrets
  are externalised, no guessing).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

REPO_BASE = Path(__file__).resolve().parents[1]
DEPLOYMENT = REPO_BASE / "deployment"


# --------------------------------------------------------------------------- #
# Config-dir seam (behavioural, via subprocess so the import-time default is not
# polluted for the rest of the suite).
# --------------------------------------------------------------------------- #
def _run_python(code: str, *, env: dict | None = None) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_BASE),
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_config_dir_env_override_redirects_paths(tmp_path):
    target = tmp_path / "mounted-config"
    out = _run_python(
        "import app.main as m; print(m.CONFIG_DIR)",
        env={"GENAI_CONFIG_DIR": str(target)},
    )
    assert Path(out) == target


def test_config_dir_defaults_to_repo_config():
    out = _run_python("import app.main as m; print(m.CONFIG_DIR)")
    assert Path(out) == REPO_BASE / "config"


def test_blank_env_falls_back_to_default():
    out = _run_python(
        "import app.main as m; print(m.CONFIG_DIR)",
        env={"GENAI_CONFIG_DIR": "   "},
    )
    assert Path(out) == REPO_BASE / "config"


def test_derived_config_paths_live_under_config_dir(tmp_path):
    target = tmp_path / "cfg"
    code = textwrap.dedent(
        """
        import app.main as m
        print(m.MODELS_CONFIG_PATH.parent)
        print(m.RETRIEVAL_CONFIG_PATH.parent)
        print(m.OBSERVABILITY_CONFIG_PATH.parent)
        """
    )
    out = _run_python(code, env={"GENAI_CONFIG_DIR": str(target)})
    parents = {Path(line) for line in out.splitlines()}
    assert parents == {target}


# --------------------------------------------------------------------------- #
# Dockerfile
# --------------------------------------------------------------------------- #
def test_dockerfile_is_multistage_and_nonroot():
    dockerfile = (DEPLOYMENT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("FROM ") >= 2, "expected a multi-stage build"
    assert " AS builder" in dockerfile and " AS runtime" in dockerfile
    assert re.search(r"^USER\s+appuser", dockerfile, re.MULTILINE), "must drop to non-root"
    assert "useradd" in dockerfile


def test_dockerfile_installs_from_declared_dependencies():
    dockerfile = (DEPLOYMENT / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements.txt" in dockerfile, "must install the real dependency file"
    assert "venv" in dockerfile, "dependencies should live in an isolated venv"
    assert "--extra-index-url" in dockerfile, "torch index selectable for CPU/GPU"


def test_dockerfile_has_healthcheck_and_config_seam():
    dockerfile = (DEPLOYMENT / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile
    assert "GENAI_CONFIG_DIR=/app/config" in dockerfile
    assert "uvicorn" in dockerfile and "app.main:app" in dockerfile


def test_dockerignore_excludes_heavy_and_secret_paths():
    ignore = (REPO_BASE / ".dockerignore").read_text(encoding="utf-8")
    lines = {ln.strip() for ln in ignore.splitlines()}
    for pattern in {".git", "tests/", "docs/", "__pycache__/", ".env", ".venv/"}:
        assert pattern in lines, f"{pattern} should be excluded from the build context"
    assert "!README.md" in lines, "README is re-included (needed by the build)"


# --------------------------------------------------------------------------- #
# docker-compose single-node reference
# --------------------------------------------------------------------------- #
def _compose() -> dict:
    return yaml.safe_load((DEPLOYMENT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_api_is_hardened():
    api = _compose()["services"]["api"]
    assert api.get("restart") == "unless-stopped"
    assert api["healthcheck"]["test"][-1].endswith("/health")
    assert "GENAI_CONFIG_DIR" in api["environment"]
    assert any("/app/config" in v for v in api["volumes"])
    limits = api["deploy"]["resources"]["limits"]
    assert "memory" in limits and "cpus" in limits


def test_compose_observability_waits_for_healthy_api():
    services = _compose()["services"]
    depends = services["prometheus"]["depends_on"]
    assert depends["api"]["condition"] == "service_healthy"


def test_compose_externalises_secrets_and_persists_cache():
    compose = _compose()
    api = compose["services"]["api"]
    # Secrets come from an optional .env, never hardcoded in the file.
    env_file = api["env_file"]
    entry = env_file[0] if isinstance(env_file, list) else env_file
    assert entry["path"].endswith(".env")
    assert entry["required"] is False
    # A named volume backs the model cache.
    assert "hf-cache" in compose["volumes"]
    assert any("hf-cache" in v for v in api["volumes"])
    # No real secret values committed in the compose file.
    raw = (DEPLOYMENT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "sk-" not in raw


# --------------------------------------------------------------------------- #
# .env.example template
# --------------------------------------------------------------------------- #
def test_env_example_documents_vars_without_real_secrets():
    text = (REPO_BASE / ".env.example").read_text(encoding="utf-8")
    for var in ("OPENAI_API_KEY", "HF_TOKEN", "GENAI_API_KEY", "GENAI_CONFIG_DIR"):
        assert var in text
    # Every secret-looking assignment must be empty in the template.
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("OPENAI_API_KEY=", "HF_TOKEN=", "GENAI_API_KEY=")):
            assert line.endswith("="), f"{line} must not ship a value"
