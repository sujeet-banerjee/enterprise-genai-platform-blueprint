"""HA / autoscaling artifacts (issue #68 / G3).

Validates Helm chart defaults and overlays for multi-replica HA, HPA/KEDA
templates, PVC access modes, and documentation of shared-state/cache semantics.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_BASE = Path(__file__).resolve().parents[1]
CHART = REPO_BASE / "deployment" / "helm" / "genai-platform"
VALUES = CHART / "values.yaml"
VALUES_DEV = CHART / "values.dev.yaml"
VALUES_STAGING = CHART / "values.staging.yaml"
VALUES_PROD = CHART / "values.prod.yaml"
DEPLOYMENT_TEMPLATE = CHART / "templates" / "deployment.yaml"
HPA_TEMPLATE = CHART / "templates" / "hpa.yaml"
KEDA_TEMPLATE = CHART / "templates" / "keda-scaledobject.yaml"
PVC_TEMPLATE = CHART / "templates" / "pvc.yaml"
DEPLOYMENT_DOC = REPO_BASE / "docs" / "deployment.md"
ARCHITECTURE_DOC = REPO_BASE / "docs" / "architecture.md"
README = REPO_BASE / "README.md"
KUSTOMIZE_PROD = REPO_BASE / "deployment" / "kustomize" / "overlays" / "prod" / "kustomization.yaml"

HELM = shutil.which("helm")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_all(path: Path):
    return list(yaml.safe_load_all(path.read_text(encoding="utf-8")))


def test_values_enable_ha_knobs() -> None:
    defaults = _load_yaml(VALUES)
    assert "replicaCount" in defaults
    assert defaults["autoscaling"]["enabled"] is False
    assert defaults["autoscaling"]["minReplicas"] >= 1
    assert defaults["autoscaling"]["maxReplicas"] >= defaults["autoscaling"]["minReplicas"]
    assert "targetCPUUtilizationPercentage" in defaults["autoscaling"]
    assert "targetMemoryUtilizationPercentage" in defaults["autoscaling"]
    assert defaults["autoscaling"]["keda"]["enabled"] is False
    assert "triggers" in defaults["autoscaling"]["keda"]
    assert defaults["modelCache"]["accessMode"] in ("ReadWriteOnce", "ReadWriteMany")


def test_overlays_enable_multi_replica_and_hpa() -> None:
    staging = _load_yaml(VALUES_STAGING)
    prod = _load_yaml(VALUES_PROD)
    assert staging["replicaCount"] >= 2
    assert prod["replicaCount"] >= 2
    assert staging["autoscaling"]["enabled"] is True
    assert prod["autoscaling"]["enabled"] is True
    assert staging["autoscaling"]["minReplicas"] >= 2
    assert prod["autoscaling"]["minReplicas"] >= 2
    assert staging["modelCache"]["accessMode"] == "ReadWriteMany"
    assert prod["modelCache"]["accessMode"] == "ReadWriteMany"


def test_kustomize_prod_multi_replica() -> None:
    content = KUSTOMIZE_PROD.read_text(encoding="utf-8")
    assert "replicas:" in content
    assert "count: 2" in content


def test_hpa_template_supports_cpu_and_memory() -> None:
    text = HPA_TEMPLATE.read_text(encoding="utf-8")
    assert "autoscaling/v2" in text
    assert "autoscaling.enabled" in text
    assert "autoscaling.keda.enabled" in text
    assert "targetCPUUtilizationPercentage" in text
    assert "targetMemoryUtilizationPercentage" in text


def test_keda_template_exists_and_validates_triggers() -> None:
    text = KEDA_TEMPLATE.read_text(encoding="utf-8")
    assert "keda.sh/v1alpha1" in text
    assert "ScaledObject" in text
    assert "autoscaling.keda.triggers" in text
    assert "fail" in text


def test_pvc_allows_configurable_access_mode() -> None:
    text = PVC_TEMPLATE.read_text(encoding="utf-8")
    assert "modelCache.accessMode" in text


def test_deployment_respects_hpa_replica_count() -> None:
    text = DEPLOYMENT_TEMPLATE.read_text(encoding="utf-8")
    assert "if not .Values.autoscaling.enabled" in text
    assert "replicas:" in text


def test_docs_describe_ha_and_cache_semantics() -> None:
    for path in (DEPLOYMENT_DOC, ARCHITECTURE_DOC, README):
        text = path.read_text(encoding="utf-8")
        assert "#68" in text or "G3" in text
        assert "persistence" in text.lower()
        assert "cache" in text.lower()


@pytest.mark.skipif(HELM is None, reason="helm binary not installed")
def test_helm_templates_multi_replica_overlays() -> None:
    result = subprocess.run(
        [HELM, "template", "smoke", str(CHART), "-f", str(VALUES_STAGING)],
        cwd=str(REPO_BASE),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    deployments = [d for d in docs if d.get("kind") == "Deployment"]
    assert deployments
    # HPA present, replicas not set explicitly when autoscaling enabled
    assert any(d.get("kind") == "HorizontalPodAutoscaler" for d in docs)
