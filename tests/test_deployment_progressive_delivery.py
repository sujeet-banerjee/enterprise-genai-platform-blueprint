"""Progressive delivery artifacts (issue #69 / G4)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_BASE = Path(__file__).resolve().parents[1]
CHART = REPO_BASE / "deployment" / "helm" / "genai-platform"
VALUES = CHART / "values.yaml"
VALUES_PROD = CHART / "values.prod.yaml"
ROLLOUT_TEMPLATE = CHART / "templates" / "rollout.yaml"
CANARY_SERVICE = CHART / "templates" / "canary-service.yaml"
DEPLOYMENT_DOC = REPO_BASE / "docs" / "deployment.md"
ARCHITECTURE_DOC = REPO_BASE / "docs" / "architecture.md"
README = REPO_BASE / "README.md"
VERSIONS_README = REPO_BASE / "config" / "versions" / "README.md"
GITOPS_README = REPO_BASE / "deployment" / "gitops" / "README.md"

HELM = shutil.which("helm")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_values_have_rollout_knobs() -> None:
    defaults = _load_yaml(VALUES)
    rollout = defaults["rollout"]
    assert "enabled" in rollout
    assert rollout["strategy"] in ("canary", "blueGreen")
    assert "revisionHistoryLimit" in rollout
    assert "canary" in rollout
    assert "blueGreen" in rollout


def test_prod_values_opt_in_scaffold() -> None:
    prod = _load_yaml(VALUES_PROD)
    rollout = prod["rollout"]
    assert "enabled" in rollout
    assert rollout["strategy"] == "canary"
    assert isinstance(rollout["canary"]["steps"], list)
    assert len(rollout["canary"]["steps"]) >= 1


def test_rollout_template_has_canary_and_bluegreen() -> None:
    text = ROLLOUT_TEMPLATE.read_text(encoding="utf-8")
    assert "argoproj.io/v1alpha1" in text
    assert "Rollout" in text
    assert 'eq .Values.rollout.strategy "canary"' in text
    assert 'eq .Values.rollout.strategy "blueGreen"' in text
    assert "canaryService" in text
    assert "activeService" in text
    assert "fail" in text


def test_canary_service_template_gated() -> None:
    text = CANARY_SERVICE.read_text(encoding="utf-8")
    assert "rollout.enabled" in text
    assert "canary" in text


def test_config_versioning_and_rollback_documented() -> None:
    text = VERSIONS_README.read_text(encoding="utf-8")
    assert "config_version" in text
    assert "rollback" in text.lower()
    assert "git" in text.lower()


def test_deployment_docs_cover_progressive_delivery() -> None:
    text = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    assert "#69" in text or "G4" in text
    assert "rollback" in text.lower()
    assert "canary" in text.lower() or "blue" in text.lower()
    assert "/v1/config" in text


def test_gitops_and_architecture_reference() -> None:
    for path in (GITOPS_README, ARCHITECTURE_DOC):
        text = path.read_text(encoding="utf-8")
        assert "#69" in text or "G4" in text or "rollback" in text.lower()
    readme = README.read_text(encoding="utf-8")
    assert "#69" in readme or "G4" in readme or "rollback" in readme.lower() or "progressive" in readme.lower()


@pytest.mark.skipif(HELM is None, reason="helm binary not installed")
def test_helm_lint_and_template_still_clean() -> None:
    result = subprocess.run(
        [HELM, "lint", str(CHART)],
        cwd=str(REPO_BASE),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [HELM, "template", "smoke", str(CHART), "-f", str(VALUES_PROD)],
        cwd=str(REPO_BASE),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
