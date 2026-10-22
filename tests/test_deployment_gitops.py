"""Reference delivery artifacts (roadmap G2 / issue #67).

These are real checks, not string greps where a tool is available:

- ``helm lint`` / ``helm template`` for the chart and every values overlay
  (skipped when the Helm binary is absent, e.g. a bare local venv - CI installs it);
- ``kubectl kustomize`` for base + dev/staging/prod overlays (skipped without kubectl);
- the smoke config genuinely builds an app and serves /health + /ready + /v1/query
  with dummy providers (no model downloads);
- the GitOps Application and the CI smoke job are validated structurally.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_BASE = Path(__file__).resolve().parents[1]
CHART = REPO_BASE / "deployment" / "helm" / "genai-platform"
KUSTOMIZE = REPO_BASE / "deployment" / "kustomize"
SMOKE_CONFIG = REPO_BASE / "deployment" / "smoke" / "config"
GITOPS_APP = REPO_BASE / "deployment" / "gitops" / "argocd" / "application.yaml"
CI_WORKFLOW = REPO_BASE / ".github" / "workflows" / "ci.yml"

HELM = shutil.which("helm")
KUBECTL = shutil.which("kubectl")

requires_helm = pytest.mark.skipif(HELM is None, reason="helm binary not installed")
requires_kubectl = pytest.mark.skipif(KUBECTL is None, reason="kubectl binary not installed")


def _run(args: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(REPO_BASE), capture_output=True, text=True, **kwargs
    )


def _helm_template(*extra: str) -> List[Dict[str, Any]]:
    assert HELM is not None
    result = _run([HELM, "template", "smoke", str(CHART), *extra])
    assert result.returncode == 0, result.stderr
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    assert docs, "helm template produced no documents"
    return docs


def _by_kind(docs: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    return [d for d in docs if d.get("kind") == kind]


def _kustomize(overlay: str) -> List[Dict[str, Any]]:
    assert KUBECTL is not None
    result = _run(
        [
            KUBECTL,
            "kustomize",
            "--load-restrictor",
            "LoadRestrictionsNone",
            str(KUSTOMIZE / "overlays" / overlay),
        ]
    )
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def test_chart_layout_and_metadata() -> None:
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
    assert chart["name"] == "genai-platform"
    assert chart["apiVersion"] == "v2"
    assert chart["type"] == "application"
    for name in ("values.yaml", "values.dev.yaml", "values.staging.yaml", "values.prod.yaml"):
        assert (CHART / name).is_file(), name
    for template in ("deployment.yaml", "service.yaml", "pvc.yaml", "hpa.yaml", "ingress.yaml"):
        assert (CHART / "templates" / template).is_file(), template

    # No secret material may be rendered from values.
    values_text = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert "existingSecret" in values_text
    assert "password" not in values_text.lower()


@requires_helm
def test_helm_lint_passes() -> None:
    result = _run([HELM, "lint", str(CHART)])
    assert result.returncode == 0, result.stderr
    assert "0 chart(s) failed" in result.stdout


@requires_helm
def test_default_values_render_workload_and_probes() -> None:
    docs = _helm_template()

    assert len(_by_kind(docs, "Deployment")) == 1
    assert len(_by_kind(docs, "Service")) == 1
    assert len(_by_kind(docs, "PersistentVolumeClaim")) == 1
    assert _by_kind(docs, "Ingress") == []
    assert _by_kind(docs, "HorizontalPodAutoscaler") == []

    deployment = _by_kind(docs, "Deployment")[0]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["image"].startswith("enterprise-genai-platform:")
    assert container["ports"][0]["containerPort"] == 8000

    probes = container
    assert probes["startupProbe"]["httpGet"]["path"] == "/health"
    assert probes["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert probes["livenessProbe"]["httpGet"]["path"] == "/health"

    env = {item["name"]: item.get("value") for item in container["env"]}
    assert env["GENAI_CONFIG_DIR"] == "/app/config"
    assert env["HF_HOME"] == "/app/.cache/huggingface"

    # Baked-in config: no ConfigMap mount/volume unless configured.
    volume_names = [v["name"] for v in deployment["spec"]["template"]["spec"]["volumes"]]
    assert "config" not in volume_names
    assert "model-cache" in volume_names


@requires_helm
def test_environment_overlays_render() -> None:
    for env in ("dev", "staging", "prod"):
        docs = _helm_template("-f", str(CHART / f"values.{env}.yaml"))
        deployment = _by_kind(docs, "Deployment")[0]
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert f":{env}" in container["image"] or (
            env == "prod" and container["image"].endswith(":1.0.0")
        )

    prod = _helm_template("-f", str(CHART / "values.prod.yaml"))
    deployment = _by_kind(prod, "Deployment")[0]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item.get("value") for item in container["env"]}
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"].startswith("http://otel-collector")
    assert container["envFrom"][0]["secretRef"]["name"] == "genai-platform-secrets"
    assert _by_kind(prod, "Ingress")[0]["spec"]["rules"][0]["host"] == "genai.example.com"
    assert deployment["spec"]["replicas"] == 1


@requires_helm
def test_configmap_secret_wiring_and_worker_guard() -> None:
    docs = _helm_template(
        "--set", "config.existingConfigMap=genai-platform-config",
        "--set", "secrets.existingSecret=genai-platform-secrets",
    )
    deployment = _by_kind(docs, "Deployment")[0]
    pod = deployment["spec"]["template"]["spec"]
    config_volume = next(v for v in pod["volumes"] if v["name"] == "config")
    assert config_volume["configMap"]["name"] == "genai-platform-config"
    container = pod["containers"][0]
    mount = next(m for m in container["volumeMounts"] if m["name"] == "config")
    assert mount["mountPath"] == "/app/config"
    assert mount["readOnly"] is True

    # Enabling the worker without a command must fail loudly, not run a second API.
    result = _run([HELM, "template", "smoke", str(CHART), "--set", "worker.enabled=true"])
    assert result.returncode != 0
    assert "worker.command is required" in result.stderr

    docs = _helm_template(
        "--set", "worker.enabled=true",
        "--set", "worker.command={python,-m,my_agent_worker}",
    )
    workers = [
        d
        for d in _by_kind(docs, "Deployment")
        if d["metadata"]["name"].endswith("-worker")
    ]
    assert len(workers) == 1
    worker_container = workers[0]["spec"]["template"]["spec"]["containers"][0]
    assert worker_container["command"] == ["python", "-m", "my_agent_worker"]


@requires_kubectl
def test_kustomize_overlays_render_real_config() -> None:
    for env in ("dev", "staging", "prod"):
        docs = _kustomize(env)
        deployments = _by_kind(docs, "Deployment")
        assert len(deployments) == 1, env
        assert _by_kind(docs, "ConfigMap"), env

    dev = _kustomize("dev")
    configmap = _by_kind(dev, "ConfigMap")[0]
    assert "retrieval.yaml" in configmap["data"]
    deployment = _by_kind(dev, "Deployment")[0]
    pod = deployment["spec"]["template"]["spec"]
    config_volume = next(v for v in pod["volumes"] if v["name"] == "config")
    # nameReference rewrites the volume to the generated (hashed) ConfigMap name.
    assert config_volume["configMap"]["name"] == configmap["metadata"]["name"]
    pvc = _by_kind(dev, "PersistentVolumeClaim")[0]
    assert pvc["spec"]["resources"]["requests"]["storage"] == "5Gi"

    staging = _kustomize("staging")
    staging_container = _by_kind(staging, "Deployment")[0]["spec"]["template"]["spec"][
        "containers"
    ][0]
    assert staging_container["envFrom"][0]["secretRef"]["name"] == "genai-platform-secrets"
    assert any(
        item["name"] == "OTEL_EXPORTER_OTLP_ENDPOINT" for item in staging_container["env"]
    )

    prod = _kustomize("prod")
    assert _by_kind(prod, "Ingress")[0]["spec"]["rules"][0]["host"] == "genai.example.com"
    prod_pvc = _by_kind(prod, "PersistentVolumeClaim")[0]
    assert prod_pvc["spec"]["resources"]["requests"]["storage"] == "50Gi"
    # Single replica until shared state lands (G3).
    assert _by_kind(prod, "Deployment")[0]["spec"]["replicas"] == 1


def test_gitops_application_is_valid_and_points_at_existing_overlay() -> None:
    app = yaml.safe_load(GITOPS_APP.read_text(encoding="utf-8"))
    assert app["kind"] == "Application"
    assert app["apiVersion"] == "argoproj.io/v1alpha1"
    source = app["spec"]["source"]
    overlay = Path(source["path"])
    assert (REPO_BASE / overlay / "kustomization.yaml").is_file()
    assert "LoadRestrictionsNone" in source["kustomize"]["buildOptions"]
    assert app["spec"]["destination"]["namespace"] == "genai-platform"
    assert app["spec"]["syncPolicy"]["automated"]["selfHeal"] is True


def test_ci_deploy_smoke_job_covers_build_and_health() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "Deploy smoke (chart + image)" in workflow
    assert "helm lint deployment/helm/genai-platform" in workflow
    assert "kubectl kustomize --load-restrictor LoadRestrictionsNone" in workflow
    assert "docker build -f deployment/Dockerfile" in workflow
    assert 'curl -fsS http://localhost:8000/health' in workflow
    assert 'curl -fsS http://localhost:8000/ready' in workflow
    assert "deployment/smoke/config:/app/config:ro" in workflow


def test_smoke_config_is_valid_and_download_free() -> None:
    result = _run(
        [sys.executable, "-m", "app.config_validate", "--config-dir", str(SMOKE_CONFIG)]
    )
    assert result.returncode == 0, result.stderr + result.stdout

    models = yaml.safe_load((SMOKE_CONFIG / "models.yaml").read_text(encoding="utf-8"))
    assert models["active_model"] == "dummy"
    assert models["active_embedding_model"] == "dummy"
    assert models["models"]["dummy"]["provider"] == "dummy"

    retrieval = yaml.safe_load((SMOKE_CONFIG / "retrieval.yaml").read_text(encoding="utf-8"))
    assert retrieval["retrieval"]["retrievers"]["dummy"]["provider"] == "dummy"
    assert retrieval["evaluation"]["enabled"] is False
    assert retrieval["reranking"]["enabled"] is False


def test_smoke_app_serves_health_ready_and_query() -> None:
    script = """
import json
from fastapi.testclient import TestClient

from app.main import app

with TestClient(app) as client:
    health = client.get("/health")
    ready = client.get("/ready")
    query = client.post("/v1/query", json={"query": "what is governance?", "top_k": 2})
    print(json.dumps({
        "health": health.status_code,
        "ready": ready.status_code,
        "ready_body": ready.json(),
        "query": query.status_code,
        "query_error": query.json().get("error"),
        "query_failure_type": query.json().get("failure_type"),
    }))
"""
    env = os.environ.copy()
    env["GENAI_CONFIG_DIR"] = str(SMOKE_CONFIG)
    env["PYTHONPATH"] = str(REPO_BASE)
    result = _run([sys.executable, "-c", script], env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["health"] == 200
    assert payload["ready"] == 200
    assert payload["ready_body"]["status"] == "ready"
    assert payload["query"] == 200
    assert payload["query_error"] is None
    assert payload["query_failure_type"] is None


def test_docs_reference_the_reference_artifacts() -> None:
    deployment_doc = (REPO_BASE / "docs" / "deployment.md").read_text(encoding="utf-8")
    assert "deployment/helm/genai-platform" in deployment_doc
    assert "deployment/kustomize/overlays/prod" in deployment_doc
    assert "deployment/gitops/argocd/application.yaml" in deployment_doc

    readme = (REPO_BASE / "README.md").read_text(encoding="utf-8")
    assert "deployment/helm/genai-platform" in readme
    assert "deployment/kustomize/overlays/prod" in readme
