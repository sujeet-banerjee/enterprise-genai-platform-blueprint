from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.eval_trends import EvalTrendStore
from app.evaluation_api import _ExperimentStore
from app.ops_api import RunHistory
from core.config.validator import ConfigValidationError
from core.evaluation.multi_replica import (
    QUALIFICATION_ID,
    REQUIRED_CHECKS,
    UNSUPPORTED_STATE_CATEGORIES,
    build_report,
    check_report,
    collect_provenance,
    render_markdown,
    summarize_checks,
)
from core.services.audit_log import AuditLogger
from core.services.base_store import build_store
from core.services.store_backends import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = REPO_ROOT / "deployment" / "multi-replica"
REPORT = REPO_ROOT / "docs" / "benchmarks" / "multi-replica.json"
HARNESS = REPO_ROOT / "benchmarks" / "multi_replica" / "run_qualification.py"


def test_profile_artifacts_exist_and_validate() -> None:
    required = [
        PROFILE / "README.md",
        PROFILE / "docker-compose.yml",
        PROFILE / "config" / "models.yaml",
        PROFILE / "config" / "prompt_config.yaml",
        PROFILE / "config" / "retrieval.yaml",
        PROFILE / "config" / "tenants.yaml",
        PROFILE / "config" / "acl.yaml",
        PROFILE / "config" / "audit.yaml",
        PROFILE / "config" / "persistence.yaml",
        PROFILE / "config" / "documents.json",
    ]
    assert all(path.is_file() for path in required)
    env = os.environ.copy()
    env["GENAI_QUALIFICATION_STORE"] = "/tmp/qualification-validation.db"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.config_validate",
            "--config-dir",
            str(PROFILE / "config"),
            "--json",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True


def test_profile_declares_two_replicas_and_shared_volume() -> None:
    compose = (PROFILE / "docker-compose.yml").read_text(encoding="utf-8")
    assert "api-a:" in compose
    assert "api-b:" in compose
    assert compose.count("qualification-state:/app/state") == 2
    assert "GENAI_CONFIG_DIR: /app/config" in compose


def test_persistence_secret_reference_is_resolved_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "persistence.yaml"
    config.write_text(
        "backend: sqlite\npath: ${GENAI_MULTI_REPLICA_TEST_DB}\nmax_entries: 100\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "store.db"
    monkeypatch.setenv("GENAI_MULTI_REPLICA_TEST_DB", str(db_path))
    store = build_store(config_path=config)
    try:
        assert store.health()["backend"] == "sqlite"
        assert str(db_path) == str(store.health()["path"])
    finally:
        store.close()
    monkeypatch.delenv("GENAI_MULTI_REPLICA_TEST_DB")
    with pytest.raises(ConfigValidationError):
        build_store(config_path=config)


def test_run_history_prefers_shared_store_across_instances() -> None:
    store = MemoryStore()
    first = RunHistory(store=store)
    second = RunHistory(store=store)
    first.record(
        "shared-trace",
        {
            "observability": {"request_id": "shared-trace", "tenant": "acme"},
            "cost": {"estimated_cost_usd": 0.01},
            "latency": {"total_ms": 1.0},
        },
        tenant="acme",
    )
    assert second.trace("shared-trace", tenant="acme") is not None
    assert second.trace("shared-trace", tenant="beta") is None
    assert second.run_count() == 1
    assert second.trace_count() == 1


def test_experiment_status_refreshes_from_shared_store() -> None:
    store = MemoryStore()
    first = _ExperimentStore(store=store)
    second = _ExperimentStore(store=store)
    entry = first.create("exp-shared", "single", tenant="acme")
    assert second.get("exp-shared")["status"] == "running"
    first.complete("exp-shared", {"ok": True})
    refreshed = second.get("exp-shared")
    assert refreshed["status"] == "completed"
    assert refreshed["result"] == {"ok": True}
    assert entry["id"] == "exp-shared"


def test_eval_trend_points_visible_to_peer_store() -> None:
    store = MemoryStore()
    first = EvalTrendStore(store=store)
    second = EvalTrendStore(store=store)
    first.record({"answer_relevance": 0.8}, source="evaluate", tenant="acme")
    assert second.trends(tenant="acme")["num_points"] == 1
    assert second.trends(tenant="beta")["num_points"] == 0


def test_audit_events_are_tenant_scoped_through_shared_store() -> None:
    store = MemoryStore()
    first = AuditLogger.from_config({"enabled": True}, store=store)
    second = AuditLogger.from_config({"enabled": True}, store=store)
    first.record("config", "pipeline_rebuild", "denied", tenant="acme", details={"reason": "off"})
    events = second.events(limit=10, tenant="acme")
    assert len(events) == 1
    assert events[0]["tenant"] == "acme"
    assert second.events(limit=10, tenant="beta") == []


def test_qualification_helpers_enforce_required_checks() -> None:
    checks = [{"name": "both_replicas_ready", "passed": True, "detail": "ok"}]
    summary = summarize_checks(checks)
    assert summary["passed_all"] is False
    assert "restart_recovery" in summary["missing_required"]
    report = build_report(
        checks=[{"name": name, "passed": True, "detail": "ok"} for name in REQUIRED_CHECKS],
        provenance={"config_sha256": "abc"},
        profile={"backend": "sqlite"},
    )
    assert report["status"] == "pass"
    assert "Explicitly unsupported" in render_markdown(report)
    assert "response_cache" in UNSUPPORTED_STATE_CATEGORIES


def test_check_report_rejects_partial_or_failed_reports(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"status": "pass", "checks": []}), encoding="utf-8")
    assert check_report(report) is False
    report.write_text(
        json.dumps(
            {
                "status": "pass",
                "checks": [
                    {"name": name, "passed": True, "detail": "ok"} for name in REQUIRED_CHECKS
                ],
            }
        ),
        encoding="utf-8",
    )
    assert check_report(report) is True


def test_committed_evidence_passes_and_is_bounded(tmp_path: Path) -> None:
    assert REPORT.is_file()
    assert (REPO_ROOT / "docs" / "benchmarks" / "multi-replica.md").is_file()
    assert check_report(REPORT) is True
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["qualification_id"] == QUALIFICATION_ID
    assert report["summary"]["passed"] == len(REQUIRED_CHECKS)
    assert report["unsupported_state"]["response_cache"].startswith("Process-local")
    assert report["profile"]["replicas"] == 2
    provenance = collect_provenance(PROFILE / "config", "sqlite", 2, repo_root=REPO_ROOT)
    assert provenance["config_sha256"] == report["provenance"]["config_sha256"]


def test_support_matrix_documents_the_boundary() -> None:
    readme = (PROFILE / "README.md").read_text(encoding="utf-8")
    deployment = (REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    readiness = (REPO_ROOT / "docs" / "production-readiness.md").read_text(encoding="utf-8")
    assert "Support matrix" in readme
    assert "not an HA, DR" in readme
    assert "Qualified multi-replica profile" in deployment
    assert "bounded two-process" in readiness
    assert "Postgres runtime evidence" in deployment


def test_full_two_process_harness_generates_passing_evidence(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    completed = subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "--out",
            str(out),
            "--markdown",
            str(markdown),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert check_report(out) is True
    report = json.loads(out.read_text(encoding="utf-8"))
    assert {check["name"] for check in report["checks"]} == REQUIRED_CHECKS | {
        "cross_tenant_retrieval_denied"
    }
    assert markdown.read_text(encoding="utf-8").startswith("# Multi-replica qualification evidence")
