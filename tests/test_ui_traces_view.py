"""Structured Traces view-model and waterfall tests (#244)."""

from __future__ import annotations

import ast
from pathlib import Path

from ui import traces

TRACE = {
    "request_id": "req-1",
    "tenant": "tenant-a",
    "workspace": "workspace-a",
    "app": "console",
    "attribution": {"user": "user-a"},
    "cache_hit": True,
    "cost": {"estimated_cost_usd": 0.0123},
    "retrieved_documents": [{"content": "doc"}],
    "guardrail_decisions": [
        {"guardrail": "pii", "decision": "redact"},
        {"guardrail": "injection", "decision": "allow"},
    ],
    "latency": {
        "total_ms": 100.0,
        "stages": {
            "embedding": {"ms": 10, "count": 1},
            "retrieval": {"ms": 20, "count": 2},
            "llm_generation": {"ms": 60, "count": 1},
        },
    },
    "otel": {"trace_id": "trace-1", "span_id": "span-1"},
    "observability": {"request_id": "req-1"},
}


def test_build_waterfall_uses_stage_order_and_running_offsets():
    rows = traces.build_waterfall(TRACE)
    by_stage = {row["stage"]: row for row in rows}
    assert ["embedding", "retrieval", "llm_generation"] == [
        row["stage"] for row in rows
    ]
    assert by_stage["embedding"]["start_ms"] == 0.0
    assert by_stage["embedding"]["end_ms"] == 10.0
    assert by_stage["retrieval"]["start_ms"] == 10.0
    assert by_stage["retrieval"]["end_ms"] == 30.0
    assert by_stage["llm_generation"]["start_ms"] == 30.0
    assert by_stage["llm_generation"]["end_ms"] == 90.0
    assert by_stage["llm_generation"]["pct"] == 60.0
    assert "#" in by_stage["llm_generation"]["bar"]


def test_build_waterfall_adds_unknown_stages_and_total_fallback():
    extra = {
        "latency": {
            "total_ms": 12.0,
            "stages": {"custom_stage": {"ms": 4}, "embedding": {"ms": 8}},
        }
    }
    rows = traces.build_waterfall(extra)
    assert [row["stage"] for row in rows] == ["embedding", "custom_stage"]
    assert rows[-1]["start_ms"] == 8.0
    fallback = traces.build_waterfall({"latency": {"total_ms": 42.0}})
    assert fallback[0]["stage"] == "total"
    assert fallback[0]["pct"] == 100.0


def test_waterfall_markdown_renders_bars_and_escapes_stage_names():
    rows = traces.build_waterfall(
        {"latency": {"total_ms": 10.0, "stages": {"<script>alert(1)</script>": {"ms": 10}}}}
    )
    rendered = traces.waterfall_markdown(rows)
    assert "genai-waterfall-table" in rendered
    assert "genai-waterfall-fill" in rendered
    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered
    assert traces.waterfall_markdown([]) == traces.waterfall_markdown([])


def test_trace_summary_view_covers_outcome_latency_cost_guardrails_cache_and_scope():
    summary = traces.trace_summary_view(TRACE)
    assert summary["request_id"] == "req-1"
    assert summary["status"] == "success"
    assert summary["tenant"] == "tenant-a"
    assert summary["workspace"] == "workspace-a"
    assert summary["app"] == "console"
    assert summary["user"] == "user-a"
    assert summary["total_ms"] == 100.0
    assert summary["cost_usd"] == 0.0123
    assert summary["documents"] == 1
    assert summary["guardrail_blocks"] == 0
    assert summary["guardrail_redactions"] == 1
    assert summary["cache_hit"] is True
    assert summary["otel_trace_id"] == "trace-1"
    degraded = traces.trace_summary_view({"failure_tags": ["upstream"]})
    assert degraded["status"] == "degraded"
    assert degraded["failure_tags"] == "upstream"


def test_summary_badges_reflect_failure_cache_guardrails_and_tenant():
    summary = traces.trace_summary_view(TRACE)
    labels = [badge["label"] for badge in traces.summary_badges(summary)]
    assert any("Success" in label for label in labels)
    assert "Cache hit" in labels
    assert "1 redacted" in labels
    assert "tenant: tenant-a" in labels
    assert "OTel linked" in labels
    failed = traces.trace_summary_view({"failure_type": "guardrail_input_blocked", "cache_hit": False})
    failed_badges = traces.summary_badges(failed)
    assert failed_badges[0]["label"] == "Failed"
    assert failed_badges[0]["tone"] == "danger"
    assert "Cache miss" in [badge["label"] for badge in failed_badges]


def test_summary_card_markdown_is_curated_and_escaped():
    trace = dict(TRACE)
    trace["tenant"] = "<tenant>"
    rendered = traces.summary_card_markdown(trace)
    assert "Request summary" in rendered
    assert "genai-kpi-strip" in rendered
    assert "genai-query-badges" in rendered
    assert "Request id" in rendered
    assert "&lt;tenant&gt;" in rendered
    assert "<tenant>" not in rendered


def test_compare_highlight_markdown_colors_deltas_and_escapes_values():
    rows = [
        {"metric": "total latency (ms)", "left": 100, "right": 150, "delta": 50, "change": "changed"},
        {"metric": "cache hit", "left": False, "right": True, "delta": "", "change": "changed"},
        {"metric": "status", "left": "success", "right": "success", "delta": "", "change": "same"},
        {"metric": "<img src=x>", "left": "a", "right": "b", "delta": "", "change": "changed"},
    ]
    rendered = traces.compare_highlight_markdown(rows)
    assert "genai-diff-table" in rendered
    assert "genai-delta-worse" in rendered
    assert "genai-delta-better" in rendered
    assert "genai-delta-neutral" in rendered
    assert "&lt;img src=x&gt;" in rendered
    assert "<img" not in rendered
    assert "No differing trace metrics" in traces.compare_highlight_markdown([])


def test_traces_helpers_are_pure_and_bot_win_boundary_is_clean():
    src = Path("ui/traces.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not name.name.startswith(("app.", "core.")) for name in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(("app.", "core."))
            assert node.module != "streamlit"


def test_app_wires_structured_trace_view_and_keeps_raw_in_expanders():
    src = Path("ui/app.py").read_text(encoding="utf-8")
    assert "build_waterfall" in src
    assert "waterfall_markdown" in src
    assert "summary_card_markdown" in src
    assert "compare_highlight_markdown" in src
    assert "st.markdown(waterfall_markdown(waterfall)" in src
    assert "st.markdown(compare_highlight_markdown(highlights)" in src
    assert "st.json(redaction_safe_view(trace))" not in src
    assert "with st.expander(DETAIL_EXPANDER_LABEL, expanded=False):" in src


def test_feedback_screen_does_not_render_duplicate_trace_screen():
    src = Path("ui/app.py").read_text(encoding="utf-8")
    assert src.count('st.subheader("Traces")') == 1


def test_wireframe_guard():
    svg = Path("docs/wireframes/244-traces-waterfall.svg").read_text(encoding="utf-8")
    source = Path("docs/wireframes/244-traces-waterfall.excalidraw")
    assert source.is_file()
    assert 'viewBox="0 0 1184 744"' in svg
