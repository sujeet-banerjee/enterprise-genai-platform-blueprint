"""Structured Feedback presentation tests (#254)."""

from __future__ import annotations

import json
from html import unescape
from pathlib import Path

from ui import feedback_view
from ui.feedback import new_annotation

ANNOTATIONS = [
    new_annotation(
        "req-1042",
        query="What is our refund window?",
        reason="unsupported",
        note="Check policy v3",
        tenant="finance",
        user="a.nguyen",
        created_at="2026-11-25T10:00:00Z",
    ),
    new_annotation(
        "req-1039",
        query="What plan includes SSO?",
        reason="incorrect",
        note="Updated from docs",
        tenant="sales",
        user="m.chen",
        promoted=True,
        created_at="2026-11-24T10:00:00Z",
    ),
]


def test_feedback_view_helpers_are_pure() -> None:
    source = Path("ui/feedback_view.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source
    assert "requests." not in source


def test_redact_feedback_payload_masks_keys_literals_and_env_refs() -> None:
    payload = {
        "api_key": "sk-live-abcdefgh",
        "note": "Bearer abc.def and ${JWT_TOKEN} and env:GENAI_SECRET",
        "nested": [{"token": "sk-should-not-appear"}],
    }
    safe = feedback_view.redact_feedback_payload(payload)
    assert safe["api_key"] == "[REDACTED]"
    assert "Bearer abc.def" not in str(safe)
    assert "sk-live-abcdefgh" not in str(safe)
    assert "sk-should-not-appear" not in str(safe)
    assert "${JWT_TOKEN}" not in str(safe)
    assert "env:GENAI_SECRET" not in str(safe)


def test_state_and_reason_badges_use_semantic_tones() -> None:
    flagged = feedback_view.state_badge(ANNOTATIONS[0])
    promoted = feedback_view.state_badge(ANNOTATIONS[1])
    unsafe = feedback_view.reason_badge({"reason": "unsafe"})
    assert flagged["label"] == "flagged" and flagged["tone"] == "warning"
    assert promoted["label"] == "promoted" and promoted["tone"] == "success"
    assert unsafe["status"] == "danger" and unsafe["label"] == "unsafe"
    assert feedback_view.state_badge({})["label"] == "noted"


def test_feedback_kpis_and_reason_breakdown_are_bounded() -> None:
    kpis = feedback_view.feedback_kpis(ANNOTATIONS)
    assert [kpi["label"] for kpi in kpis] == [
        "Total annotations",
        "Flagged",
        "Promoted",
        "Open flags",
    ]
    assert [kpi["value"] for kpi in kpis] == ["2", "2", "1", "1"]
    reasons = feedback_view.reason_breakdown(ANNOTATIONS)
    counts = {row["label"]: row["count"] for row in reasons}
    assert counts["incorrect"] == 1
    assert counts["unsupported"] == 1
    assert counts["off-topic"] == 0
    assert len(reasons) == 6


def test_feedback_rows_are_redacted_truncated_and_badged() -> None:
    rows = feedback_view.feedback_rows(
        [
            new_annotation(
                "req-999",
                query="<img src=x>" + "q" * 400,
                reason="unsafe",
                note="sk-live-secret-value",
            )
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["request_id"] == "req-999"
    assert row["query"].endswith("…")
    assert "sk-" not in row["note"]
    assert "genai-chip-danger" in row["reason_badge"]
    assert "genai-chip-warning" in row["state_badge"]
    assert feedback_view.feedback_rows(ANNOTATIONS, max_rows=1)[0]["request_id"] == "req-1042"


def test_feedback_table_markdown_escapes_values_and_shows_empty_state() -> None:
    html = feedback_view.feedback_table_markdown(
        feedback_view.feedback_rows([new_annotation("req-1", query="<script>alert(1)</script>")])
    )
    assert "genai-feedback-table" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "genai-chip" in html
    empty = feedback_view.feedback_table_markdown([])
    assert "No flagged runs match the current filters." in unescape(empty)


def test_selected_feedback_card_keeps_privacy_cue_and_redacts_notes() -> None:
    card = feedback_view.selected_feedback_card(
        new_annotation("req-7", reason="unsafe", note="token sk-live-abcdefgh")
    )
    assert "Request req-7" in card
    assert "Reviewer note" in card
    assert "Notes are redacted" in card
    assert "sk-live-abcdefgh" not in card


def test_feedback_exports_use_consistent_labels_and_filenames() -> None:
    exports = feedback_view.feedback_exports(ANNOTATIONS)
    assert [export["label"] for export in exports] == [
        "Export feedback (JSON)",
        "Export feedback (CSV)",
    ]
    assert [export["key"] for export in exports] == [
        "feedback_export_json",
        "feedback_export_csv",
    ]
    assert [export["mime"] for export in exports] == ["application/json", "text/csv"]
    assert all(export["file_name"] == "genai-feedback.json" for export in exports[:1])
    assert "genai-feedback/v1" in exports[0]["data"]
    assert "req-1042" in exports[1]["data"]
    assert feedback_view.feedback_exports([]) == []


def test_feedback_view_models_filter_select_and_redact_raw_payload() -> None:
    view = feedback_view.feedback_view_models(
        ANNOTATIONS,
        reason="unsupported",
        promoted="no",
        selected="req-1042",
    )
    assert view["total_count"] == 2
    assert view["filtered_count"] == 1
    assert view["filtered"][0]["request_id"] == "req-1042"
    assert view["selected"]["request_id"] == "req-1042"
    assert view["expander_label"] == "Raw (redacted)"
    assert view["raw"]["summary"]["flagged"] == 2
    assert "Privacy &amp; redaction" in view["privacy_markdown"]
    assert "req-1039" not in str(view["filtered"])
    assert "genai-feedback-table" in view["table_markdown"]
    empty = feedback_view.feedback_view_models()
    assert empty["raw"] == {
        "annotations": [],
        "filtered": [],
        "selected": None,
        "summary": {
            "total": 0,
            "flagged": 0,
            "promoted": 0,
            "by_reason": {
                "incorrect": 0,
                "unsupported": 0,
                "outdated": 0,
                "unsafe": 0,
                "off_topic": 0,
                "other": 0,
            },
        },
    }


def test_app_wires_structured_feedback_without_raw_dumps() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_feedback")
    end = source.index("\ndef screen_settings", start)
    body = source[start:end]
    assert "feedback_view_models(" in body
    for key in ("privacy_markdown", "kpis_markdown", "reasons_markdown", "table_markdown", "selected_markdown"):
        assert f'view["{key}"]' in body
    assert "with st.expander(FEEDBACK_RAW_EXPANDER_LABEL, expanded=False)" in body
    assert 'st.json(view["raw"])' in body
    assert "for column, export in zip(export_columns, view[\"exports\"])" in body
    assert "st.dataframe(annotation_rows" not in body
    assert "st.metric(" not in body
    assert "st.json(annotations)" not in body


def test_feedback_wireframe_and_theme_are_indexed() -> None:
    source_path = Path("docs/wireframes/254-feedback-view.excalidraw")
    svg_path = Path("docs/wireframes/254-feedback-view.svg")
    assert source_path.is_file() and svg_path.is_file()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    assert payload["type"] == "excalidraw"
    assert any("Privacy" in element.get("text", "") for element in payload["elements"])
    assert "Feedback" in svg_path.read_text(encoding="utf-8")
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "254-feedback-view.svg" in plan
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    assert "genai-feedback-table" in theme
    assert "genai-feedback-reasons" in theme
