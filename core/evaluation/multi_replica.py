"""Machine-readable evidence helpers for the bounded multi-replica profile (#206).

The harness records checks, provenance and the explicit shared/unsupported state
boundary. It does not claim HA, DR or global consistency beyond the tested
single-host two-process profile.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

QUALIFICATION_ID = "single-host-two-replica-shared-store-v1"

SHARED_STATE_CATEGORIES = [
    "run_history",
    "trace_lookup",
    "spend_and_tenant_scoping",
    "audit_events",
    "experiment_status",
    "eval_trends",
]

UNSUPPORTED_STATE_CATEGORIES = {
    "response_cache": "Process-local; tenant-scoped keys only, no cross-replica sharing.",
    "rate_limits": "Process-local token buckets; external gateway/WAF required globally.",
    "approvals": "In-memory queue; not durable across restarts.",
    "scim_directory": "In-memory directory; external IdP required for multi-replica writes.",
    "pipeline_rebuild": "Swaps pipeline state in one process only; no cross-replica broadcast.",
    "prometheus_counters": "Per-process exposition; aggregate by scraping all replicas.",
    "immutable_audit_jsonl": "Multi-writer file sink requires separate single-writer qualification.",
}

REQUIRED_CHECKS = {
    "both_replicas_ready",
    "trace_visible_on_other_replica",
    "cross_tenant_trace_denied",
    "cross_tenant_retrieval_denied",
    "spend_visible_on_other_replica",
    "experiment_status_visible_on_other_replica",
    "cross_tenant_experiment_denied",
    "audit_event_visible_on_other_replica",
    "retrieval_acl_tenant_isolation",
    "cache_tenant_key_isolation",
    "restart_recovery",
    "persistence_secret_reference_resolved",
}


def _config_digest(config_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(config_dir).rglob("*")):
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(config_dir)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def collect_provenance(
    config_dir: Path,
    backend: str,
    replica_count: int,
    *,
    repo_root: Path | None = None,
) -> Dict[str, Any]:
    """Collect git/platform/config provenance for a qualification run."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        git_sha = completed.stdout.strip() if completed.returncode == 0 else "unknown"
    except OSError:
        git_sha = "unknown"
    return {
        "qualification_id": QUALIFICATION_ID,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "backend": backend,
        "replica_count": int(replica_count),
        "config_dir": str(Path(config_dir)),
        "config_sha256": _config_digest(Path(config_dir)),
    }


def summarize_checks(checks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize named pass/fail checks."""
    rows = list(checks)
    passed = sum(1 for row in rows if bool(row.get("passed")))
    names = {str(row.get("name")) for row in rows}
    missing = sorted(REQUIRED_CHECKS - names)
    overall = passed == len(rows) and not missing and bool(rows)
    return {
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "missing_required": missing,
        "passed_all": overall,
    }


def build_report(
    *,
    checks: List[Dict[str, Any]],
    provenance: Dict[str, Any],
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the final qualification report."""
    return {
        "qualification_id": QUALIFICATION_ID,
        "status": "pass" if summarize_checks(checks)["passed_all"] else "fail",
        "summary": summarize_checks(checks),
        "provenance": provenance,
        "profile": profile,
        "shared_state": list(SHARED_STATE_CATEGORIES),
        "unsupported_state": dict(UNSUPPORTED_STATE_CATEGORIES),
        "checks": checks,
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Dict[str, Any]) -> str:
    """Render a committed-human-readable summary from the JSON report."""
    summary = report.get("summary") or {}
    provenance = report.get("provenance") or {}
    profile = report.get("profile") or {}
    passed = "PASS" if report.get("status") == "pass" else "FAIL"
    lines = [
        "# Multi-replica qualification evidence",
        "",
        f"Status: **{passed}**",
        "",
        "Bounded single-host qualification for selected shared state only. This is not an "
        "HA, DR, performance or global-consistency claim.",
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for key in (
        "qualification_id",
        "timestamp_utc",
        "git_sha",
        "platform",
        "python",
        "backend",
        "replica_count",
        "config_sha256",
    ):
        lines.append(f"| {key} | {_cell(provenance.get(key, ''))} |")
    lines.extend(["", "## Profile", "", "| Field | Value |", "| --- | --- |"])
    for key in sorted(profile):
        lines.append(f"| {key} | {_cell(profile[key])} |")
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Result | Detail |",
            "| --- | --- | --- |",
        ]
    )
    for check in report.get("checks") or []:
        result = "PASS" if check.get("passed") else "FAIL"
        lines.append(
            f"| {_cell(check.get('name', ''))} | {result} | {_cell(check.get('detail', ''))} |"
        )
    lines.extend(
        [
            "",
            f"{summary.get('passed', 0)}/{summary.get('total', 0)} checks passed.",
            "",
            "## Shared state in scope",
            "",
        ]
    )
    lines.extend(f"- {name}" for name in report.get("shared_state") or [])
    lines.extend(["", "## Explicitly unsupported in this profile", "", "| State | Limit |", "| --- | --- |"])
    for name, limit in (report.get("unsupported_state") or {}).items():
        lines.append(f"| {_cell(name)} | {_cell(limit)} |")
    return "\n".join(lines) + "\n"


def write_report(report: Dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    """Write JSON and Markdown evidence files."""
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def check_report(report_path: Path) -> bool:
    """Return True only for a passing report with all required checks present."""
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(report, dict) or report.get("status") != "pass":
        return False
    return bool(summarize_checks(report.get("checks") or [])["passed_all"])
