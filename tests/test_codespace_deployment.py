"""GitHub Codespaces demo artifacts (issue #105).

Structural checks for the devcontainer manifest, compose workspace, lifecycle
scripts, optional secret placeholders and docs - plus one genuine run of
``start.sh`` that boots the real API (dummy smoke config, no downloads) and
verifies ``/health``, ``/ready`` and ``/v1/query`` before stopping it.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

REPO_BASE = Path(__file__).resolve().parents[1]
DEVCONTAINER = REPO_BASE / ".devcontainer" / "devcontainer.json"
CODESPACE = REPO_BASE / "deployment" / "codespace"
COMPOSE = CODESPACE / "docker-compose.yml"
SETUP = CODESPACE / "setup.sh"
START = CODESPACE / "start.sh"
STOP = CODESPACE / "stop.sh"
ENV_EXAMPLE = CODESPACE / ".env.example"
CODESPACE_README = CODESPACE / "README.md"
SMOKE_CONFIG = REPO_BASE / "deployment" / "smoke" / "config"

WORKSPACE_FOLDER = "/workspaces/enterprise-genai-platform-blueprint"

BASH = shutil.which("bash")
CURL = shutil.which("curl")

requires_bash = pytest.mark.skipif(BASH is None, reason="bash not installed")
requires_bash_curl = pytest.mark.skipif(
    BASH is None or CURL is None, reason="bash/curl not installed"
)


def _manifest() -> Dict[str, Any]:
    return json.loads(DEVCONTAINER.read_text(encoding="utf-8"))


def _compose() -> Dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _bash_syntax(path: Path) -> None:
    assert BASH is not None
    result = subprocess.run(
        [BASH, "-n", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http(url: str, payload: Dict[str, Any] | None = None) -> tuple[int, str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def test_devcontainer_manifest_points_at_codespace_compose() -> None:
    manifest = _manifest()
    assert manifest["dockerComposeFile"] == "../deployment/codespace/docker-compose.yml"
    resolved = (DEVCONTAINER.parent / manifest["dockerComposeFile"]).resolve()
    assert resolved == COMPOSE.resolve()
    assert manifest["service"] == "workspace"
    assert manifest["workspaceFolder"] == WORKSPACE_FOLDER
    assert manifest["remoteUser"] == "vscode"
    assert "deployment/codespace/setup.sh" in manifest["postCreateCommand"]
    assert "deployment/codespace/start.sh" in manifest["postStartCommand"]
    assert manifest["hostRequirements"]["memory"] == "8gb"


def test_ports_are_forwarded_and_console_is_public() -> None:
    manifest = _manifest()
    assert manifest["forwardPorts"] == [8000, 8501]
    attributes = manifest["portsAttributes"]
    assert attributes["8501"]["visibility"] == "public"
    assert attributes["8501"]["onAutoForward"] == "openBrowser"
    assert "API" in attributes["8000"]["label"]
    assert attributes["8000"]["onAutoForward"] == "notify"


def test_compose_workspace_mounts_repo_at_workspace_folder() -> None:
    compose = _compose()
    workspace = compose["services"]["workspace"]
    assert workspace["image"].startswith("mcr.microsoft.com/devcontainers/python:")
    assert workspace["command"] == "sleep infinity"
    assert f"../..:{WORKSPACE_FOLDER}:cached" in workspace["volumes"]
    env = workspace["environment"]
    assert env["GENAI_CONFIG_DIR"] == f"{WORKSPACE_FOLDER}/config"
    assert env["HF_HOME"].startswith("/home/vscode/")


@requires_bash
def test_setup_installs_all_requirement_sets_and_seeds_env() -> None:
    _bash_syntax(SETUP)
    script = SETUP.read_text(encoding="utf-8")
    for requirement_file in (
        "requirements.txt",
        "requirements-ui.txt",
        "requirements-observability.txt",
    ):
        assert requirement_file in script
    assert '-m app.config_validate --config-dir config' in script
    assert 'PYTHON_BIN="${GENAI_DEMO_PYTHON:-python}"' in script
    assert '-m venv "$ROOT/.venv"' in script
    assert 'VENV_PY="$ROOT/.venv/bin/python"' in script
    assert "deployment/codespace/.env.example" in script
    assert 'if [ ! -f "$ENV_FILE" ]' in script


def test_env_example_has_only_commented_placeholders() -> None:
    lines = [
        line.strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines, "placeholder file must not be empty"
    assert all(line.startswith("#") for line in lines)
    body = "\n".join(lines)
    for name in ("OPENAI_API_KEY", "HF_TOKEN", "GENAI_API_KEY"):
        assert name in body
    gitignore = (REPO_BASE / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore


@requires_bash
def test_start_and_stop_scripts_are_valid_and_configure_ports() -> None:
    _bash_syntax(START)
    _bash_syntax(STOP)
    start = START.read_text(encoding="utf-8")
    assert 'API_PORT="${GENAI_DEMO_API_PORT:-8000}"' in start
    assert 'UI_PORT="${GENAI_DEMO_UI_PORT:-8501}"' in start
    assert '.venv/bin/python' in start
    assert '-m uvicorn app.main:app --host 0.0.0.0' in start
    assert '--port "$API_PORT"' in start
    assert "-m streamlit run ui/app.py" in start
    assert "--server.address 0.0.0.0" in start
    assert '--server.port "$UI_PORT"' in start
    assert '--api-base "http://localhost:${API_PORT}"' in start
    stop = STOP.read_text(encoding="utf-8")
    assert 'for name in ui api' in stop and "$name.pid" in stop


def test_codespace_docs_cover_launch_ports_secrets_and_cleanup() -> None:
    doc = CODESPACE_README.read_text(encoding="utf-8")
    assert "Codespaces" in doc
    assert "8501" in doc and "8000" in doc
    assert "OPENAI_API_KEY" in doc and "HF_TOKEN" in doc
    assert "stop.sh" in doc and "start.sh" in doc
    assert "1.5 GB" in doc

    readme = (REPO_BASE / "README.md").read_text(encoding="utf-8")
    assert "deployment/codespace/README.md" in readme
    assert "Codespaces" in readme

    deployment_doc = (REPO_BASE / "docs" / "deployment.md").read_text(encoding="utf-8")
    assert "### 2.7 GitHub Codespaces (demo)" in deployment_doc
    assert "deployment/codespace/README.md" in deployment_doc


def test_codespace_artifacts_are_confined() -> None:
    manifests = sorted(
        path.relative_to(REPO_BASE)
        for path in REPO_BASE.rglob("devcontainer.json")
        if ".git" not in path.parts
    )
    assert manifests == [Path(".devcontainer/devcontainer.json")]
    for name in ("docker-compose.yml", "setup.sh", "start.sh", "stop.sh", ".env.example"):
        assert (CODESPACE / name).is_file()
    root_codespace_entries = [
        path.name for path in REPO_BASE.iterdir() if "codespace" in path.name.lower()
    ]
    assert root_codespace_entries == []


@pytest.mark.skipif(os.name == "nt", reason="lifecycle scripts target Linux/macOS")
@requires_bash_curl
def test_start_script_boots_backend_with_smoke_config(tmp_path: Path) -> None:
    api_port = _free_port()
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env.update(
        {
            "GENAI_CONFIG_DIR": str(SMOKE_CONFIG),
            "GENAI_DEMO_API_PORT": str(api_port),
            "GENAI_DEMO_START_UI": "0",
            "GENAI_DEMO_START_TIMEOUT": "90",
            "GENAI_DEMO_LOG_DIR": str(log_dir),
            "GENAI_DEMO_PYTHON": sys.executable,
            "HF_HOME": str(tmp_path / "hf"),
        }
    )
    assert BASH is not None
    try:
        result = subprocess.run(
            [BASH, str(START)],
            cwd=str(REPO_BASE),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr + result.stdout

        health_status, health_body = _http(f"http://127.0.0.1:{api_port}/health")
        ready_status, ready_body = _http(f"http://127.0.0.1:{api_port}/ready")
        query_status, query_body = _http(
            f"http://127.0.0.1:{api_port}/v1/query",
            {"query": "what is governance?", "top_k": 2},
        )

        assert health_status == 200
        assert health_body
        assert ready_status == 200
        assert json.loads(ready_body)["status"] == "ready"
        assert query_status == 200
        payload = json.loads(query_body)
        assert payload["error"] is None
        assert payload["failure_type"] is None
    finally:
        subprocess.run(
            [BASH, str(STOP)],
            cwd=str(REPO_BASE),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    deadline = time.time() + 15
    while time.time() < deadline and _port_open(api_port):
        time.sleep(0.25)
    assert not _port_open(api_port), "stop.sh did not stop the API"
