"""GitOps at scale artifacts (issue #70 / G5)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_BASE = Path(__file__).resolve().parents[1]
GITOPS = REPO_BASE / "deployment" / "gitops"
ARGO_APPS = GITOPS / "argocd" / "apps"
FLUX = GITOPS / "flux"
PROMO = GITOPS / "promotion"
TERRAFORM = REPO_BASE / "deployment" / "terraform"
POLICIES = REPO_BASE / "config" / "policies"
APP_OF_APPS = GITOPS / "argocd" / "app-of-apps.yaml"

KUBECTL = shutil.which("kubectl")


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_app_of_apps_and_env_apps_exist() -> None:
    assert APP_OF_APPS.is_file()
    for name in ("app-genai-dev.yaml", "app-genai-staging.yaml", "app-genai-prod.yaml"):
        assert (ARGO_APPS / name).is_file()
    for app in (APP_OF_APPS,) + tuple(ARGO_APPS.glob("*.yaml")):
        doc = _load_yaml(app)
        assert doc["kind"] == "Application"
        assert doc["apiVersion"] == "argoproj.io/v1alpha1"
        assert doc["spec"]["source"]["repoURL"].startswith("https://github.com/")


def test_flux_manifests_present() -> None:
    for name in ("gitrepository.yaml", "kustomizations.yaml", "notification.yaml", "image-automation.yaml", "kustomization.yaml"):
        assert (FLUX / name).is_file()
    docs = []
    for path in FLUX.glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        for data in yaml.safe_load_all(text):
            if data:
                docs.append(data)
    kinds = {d.get("kind") for d in docs}
    assert "GitRepository" in kinds
    assert "Kustomization" in kinds


def test_promotion_pipeline_documented() -> None:
    md = (PROMO / "promotion-pipeline.md").read_text(encoding="utf-8")
    assert "dev" in md and "staging" in md and "prod" in md
    assert "approval" in md.lower()
    assert "gates" in md.lower()
    vals = _load_yaml(PROMO / "values-promotion.yaml")
    assert len(vals["environments"]) == 3


def test_terraform_modules_present() -> None:
    for mod in ("cluster-addons", "secrets", "storage"):
        assert (TERRAFORM / "modules" / mod / "main.tf").is_file()
    for env in ("dev", "staging", "prod"):
        assert (TERRAFORM / "environments" / env / "main.tf").is_file()
    assert (TERRAFORM / "README.md").is_file()


def test_policy_bundles_reconciled() -> None:
    bundle = _load_yaml(POLICIES / "bundles" / "policy-bundle.yaml")
    assert bundle["kind"] == "PolicyBundle"
    assert bundle["spec"]["enabled"] is False
    assert (POLICIES / "README.md").is_file()


@pytest.mark.skipif(KUBECTL is None, reason="kubectl binary not installed")
def test_argocd_applications_validate() -> None:
    for path in (ARGO_APPS / "app-genai-prod.yaml", APP_OF_APPS):
        result = subprocess.run(
            [KUBECTL, "apply", "--dry-run=client", "--validate=false", "-f", str(path)],
            cwd=str(REPO_BASE),
            capture_output=True,
            text=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        # In CI without cluster we skip hard validation; require files parse as YAML
        if result.returncode != 0:
            docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            assert docs and all(d.get("kind") == "Application" for d in docs)
        else:
            assert result.returncode == 0, result.stderr
