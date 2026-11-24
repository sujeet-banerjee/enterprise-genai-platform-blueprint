"""Structured Audit presentation tests (#250)."""

from __future__ import annotations

from html import unescape
from pathlib import Path

from ui import audit_view

EVENT = {
    "event_id": "evt-1",
    "timestamp": 1_800_000.0,
    "event_type": "config",
    "action": "pipeline_rebuild",
    "outcome": "denied",
    "request_id": "req-1",
    "tenant": "tenant-a",
    "attribution": {"user": "alice", "workspace": "ws-1"},
    "details": {"policy": "governance", "api_key": "sk-detail-secret"},
}


def test_correlation_extractors_cover_attribution_and_details() -> None:
    assert audit_view.actor_of(EVENT) == "alice"
    assert audit_view.tenant_of(EVENT) == "tenant-a"
    assert audit_view.request_of(EVENT) == "req-1"
    assert audit_view.actor_of({"details": {"actor": "svc-bot"}}) == "svc-bot"
    assert audit_view.tenant_of({"attribution": {"tenant": "tenant-b"}}) == "tenant-b"
    assert audit_view.request_of({"details": {"request_id": "req-2"}}) == "req-2"
    assert audit_view.actor_of(None) == "-"


def test_timeline_rows_emit_badges_and_action_cells() -> None:
    rows = audit_view.timeline_rows([EVENT, None, {}])
    assert len(rows) == 1
    row = rows[0]
    assert row["event_badge"]["label"] == "config"
    assert row["outcome_badge"]["label"] == "denied"
    assert row["event_badge"]["tone"] in {"success", "warning", "danger", "neutral"}
    assert row["action"] == "pipeline_rebuild"
    assert row["actor"] == "alice"
    assert row["tenant"] == "tenant-a"
    assert row["request_id"] == "req-1"
    assert "genai-audit-detail" in row["detail_html"]


def test_detail_html_is_expandable_and_redacts_secrets() -> None:
    event = {
        **EVENT,
        "details": {
            "api_key": "sk-detail-secret",
            "note": "Bearer abcdefghijklmnop",
            "reference": "env:SESSION_SECRET",
            "nested": {"token": "sk-nested-secret"},
        },
    }
    html = audit_view.detail_html(event)
    assert "<details" in html
    assert "Redacted detail" in html
    assert "[REDACTED]" in html
    assert "sk-detail-secret" not in html
    assert "sk-nested-secret" not in html
    assert "Bearer abcdefghijklmnop" not in html
    assert "env:SESSION_SECRET" not in html


def test_timeline_markdown_has_correlation_columns_and_escapes_values() -> None:
    html = audit_view.timeline_markdown(
        audit_view.timeline_rows([{**EVENT, "action": "<script>alert(1)</script>"}])
    )
    assert "genai-audit-timeline" in html
    for column in ("Time", "Event type", "Action", "Outcome", "Actor", "Tenant", "Request", "Detail"):
        assert f"<th>{column}</th>" in html
    assert "alice" in html
    assert "tenant-a" in html
    assert "req-1" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "No audit events returned" in audit_view.timeline_markdown([])


def test_audit_view_models_summarizes_counts_and_exports() -> None:
    second = {**EVENT, "event_id": "evt-2", "event_type": "governance", "outcome": "ok"}
    view = audit_view.audit_view_models(
        {"enabled": True, "count": 2, "total": 9, "events": [EVENT, second]},
        request_id="req-1",
        event_type="config",
    )
    assert [kpi["label"] for kpi in view["kpis"]] == [
        "Audit enabled",
        "Events returned",
        "Total retained",
        "Event types",
        "Outcomes",
    ]
    assert view["kpis"][0]["value"] == "yes"
    assert view["kpis"][1]["value"] == "2"
    assert view["kpis"][2]["value"] == "9"
    assert [row["label"] for row in view["event_types"]] == ["config", "governance"]
    assert [row["label"] for row in view["outcomes"]] == ["denied", "ok"]
    assert len(view["timeline"]) == 2
    assert len(view["export"]) == 2
    assert view["csv_filename"].startswith("audit-events-config-req-1")
    assert view["json_filename"].endswith(".json")


def test_export_rows_are_metadata_only_and_csv_guards_formulas() -> None:
    rows = audit_view.export_rows(
        [
            {
                **EVENT,
                "event_type": "=HYPERLINK(1)",
                "details": {"api_key": "sk-export-secret", "request_id": "ignored"},
            }
        ]
    )
    assert set(rows[0]) == {
        "timestamp",
        "event_type",
        "action",
        "outcome",
        "actor",
        "tenant",
        "request_id",
        "event_id",
    }
    assert rows[0]["request_id"] == "req-1"
    assert "api_key" not in str(rows)
    assert "sk-export-secret" not in str(rows)
    csv_text = audit_view.export_csv(rows)
    assert "timestamp,event_type,action,outcome,actor,tenant,request_id,event_id" in csv_text
    assert "'=HYPERLINK(1)" in csv_text


def test_export_json_is_deterministic_and_filename_is_safe() -> None:
    rows = audit_view.export_rows([EVENT])
    first = audit_view.export_json(rows)
    second = audit_view.export_json(list(reversed(rows)))
    assert first == second
    assert '"event_id": "evt-1"' in first
    assert audit_view.export_filename("csv", "req/1", "CONFIG!") == "audit-events-config-req-1.csv"
    assert audit_view.export_filename("json") == "audit-events.json"


def test_audit_view_helpers_are_pure() -> None:
    source = Path("ui/audit_view.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_app_wires_structured_audit_view_without_raw_dumps() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_audit")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    assert "audit_view_models(" in body
    assert "kpi_strip_markdown(view[\"kpis\"])" in body
    assert "view[\"timeline_markdown\"]" in body
    assert "audit_timeline_csv" in body
    assert "audit_timeline_json" in body
    assert "audit_events_for(" in body
    assert "audit_request_id" in body
    assert "st.json(events)" not in body
    assert "st.dataframe(" not in body


def test_audit_wireframe_and_theme_are_indexed() -> None:
    assert Path("docs/wireframes/250-audit-view.excalidraw").is_file()
    assert Path("docs/wireframes/250-audit-view.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "250-audit-view.svg" in plan
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    assert "genai-audit-table" in theme
    assert "genai-audit-detail" in theme


def test_timeline_markdown_uses_escaped_badges() -> None:
    html = audit_view.timeline_markdown(audit_view.timeline_rows([EVENT]))
    decoded = unescape(html)
    assert "config" in decoded
    assert "denied" in decoded
    assert "genai-chip" in html
