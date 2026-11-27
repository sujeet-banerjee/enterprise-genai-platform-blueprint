"""Daily bot-win review fixes for structured view contracts (#290)."""

import ast
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ui.access_view import CAPABILITY_NOTES, capability_groups
from ui.admin import audit_export_rows
from ui.approval_view import (
    _evidence_route,
    decision_history_markdown,
    evidence_chips_markdown,
)
from ui.audit_view import export_csv


def _screen_admin_source() -> str:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_admin")
    end = source.index("\ndef ", start + 1)
    return source[start:end]


def _capability(data, name):
    for group in capability_groups(data):
        for item in group["items"]:
            if item["name"] == name:
                return item
    raise AssertionError(f"capability {name} not rendered")


def test_admin_csv_route_uses_guarded_audit_serializer() -> None:
    body = _screen_admin_source()
    assert "audit_export_data_rows(" in body
    assert "audit_export_csv(rows)" in body
    assert "csv.DictWriter" not in body
    assert "import csv" not in body


def test_admin_csv_export_escapes_formula_in_request_id() -> None:
    rows = audit_export_rows(
        [
            {
                "timestamp": "2026-11-26T00:00:00Z",
                "event_type": "config",
                "action": "update",
                "outcome": "ok",
                "request_id": "=CMD(1)",
                "tenant": "t1",
            }
        ]
    )
    csv_text = export_csv(rows)
    assert "'=CMD(1)" in csv_text
    assert ",=CMD(1)" not in csv_text
    assert "request_id" in csv_text


def test_evidence_route_only_treats_request_ids_as_deep_links() -> None:
    assert _evidence_route("request_id") == ("Traces", "traces_request_id")
    assert _evidence_route("trace_request_id") == ("Traces", "traces_request_id")
    assert _evidence_route("audit_request_id") == ("Audit", "audit_request")
    for kind in ("run_id", "trace_id", "span_id", "experiment_id", "correlation_id"):
        assert _evidence_route(kind) is None


def test_evidence_chips_keep_otel_and_job_ids_copy_only() -> None:
    html = evidence_chips_markdown(
        [
            {"kind": "request_id", "value": "req-42"},
            {"kind": "trace_id", "value": "otel-trace-42"},
            {"kind": "span_id", "value": "otel-span-42"},
            {"kind": "run_id", "value": "run-42"},
            {"kind": "experiment_id", "value": "exp-42"},
            {"kind": "correlation_id", "value": "corr-42"},
        ]
    )
    links = [unescape(match) for match in re.findall(r'href="([^"]+)"', html)]
    queries = [parse_qs(urlsplit(link).query) for link in links]
    assert queries == [{"screen": ["Traces"], "traces_request_id": ["req-42"]}]
    for value in ("otel-trace-42", "otel-span-42", "run-42", "exp-42", "corr-42"):
        assert value in html
    assert html.count("copy only") == 5
    assert "traces_request_id=otel" not in html


def test_admin_capability_is_effective_via_rebuild_grant() -> None:
    admin_item = _capability({"capabilities": ["rebuild"]}, "admin")
    assert admin_item["allowed"] is True
    assert admin_item["badge"]["label"] == "Granted"
    assert "rebuild" in CAPABILITY_NOTES["admin"]
    assert CAPABILITY_NOTES["admin"] in admin_item["note"]


def test_admin_capability_stays_denied_without_admin_or_rebuild() -> None:
    admin_item = _capability({"capabilities": ["query", "audit"]}, "admin")
    assert admin_item["allowed"] is False
    assert admin_item["badge"]["label"] == "Not granted"


def test_decision_history_renders_shipped_api_scalar_fields() -> None:
    html = decision_history_markdown(
        {
            "status": "approved",
            "decided_at": 1700000000,
            "decided_by": "reviewer@example.com",
            "decision_note": "Approved for rollout",
        }
    )
    assert "Decision 1: approved" in html
    assert "2023-11-14 22:13:20 UTC" in html
    assert "reviewer@example.com" in html
    assert "Approved for rollout" in html


def test_decision_history_escapes_note_and_handles_missing_history() -> None:
    html = decision_history_markdown(
        {"status": "pending", "decision_note": "<script>alert(1)</script>"}
    )
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "Decision 1: recorded" in html
    assert "No decision history recorded yet." in decision_history_markdown({"status": "pending"})


def test_audit_docs_match_request_id_filter_and_exports() -> None:
    ux_doc = Path("docs/ux-and-api.md").read_text(encoding="utf-8")
    walkthrough = Path("docs/console-walkthrough.md").read_text(encoding="utf-8")
    assert "`event_type`/request id" in ux_doc
    assert "export metadata-only CSV/JSON" in ux_doc
    assert "request-id filters" in walkthrough
    assert "metadata-only CSV/JSON" in walkthrough


def test_touched_ui_modules_keep_no_backend_imports() -> None:
    for path in (
        "ui/app.py",
        "ui/access_view.py",
        "ui/admin.py",
        "ui/approval_view.py",
        "ui/audit_view.py",
    ):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not name.name.startswith(("app.", "core.")) for name in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith(("app", "core"))
