"""Governance & Cost structured view tests (#245)."""

from __future__ import annotations

from pathlib import Path

from ui import governance

STATUS = {
    "enabled": True,
    "max_cost_per_request_usd": 0.01,
    "safety_margin_tokens": 256,
    "window": {
        "window_size": 100,
        "requests": 4,
        "total_cost_usd": 0.012,
        "mean_cost_usd": 0.003,
    },
}
METRICS = {
    "total_runs": 4,
    "failure_count": 1,
    "failure_rate": 0.25,
    "cost": {"total_cost_usd": 0.012, "mean_cost_usd": 0.003, "priced_runs": 4},
    "failures_by_type": {"timeout": 1, "unknown": 0},
    "guardrails": {
        "total_decisions": 5,
        "total_blocks": 1,
        "by_guardrail": {
            "injection": {"allow": 2, "redact": 1, "block": 1},
            "pii": {"allow": 1, "redact": 0, "block": 0},
        },
    },
}


def test_cost_summary_prefers_spend_window_and_policy_fields() -> None:
    summary = governance.cost_summary(STATUS, METRICS)
    assert summary["spend_usd"] == 0.012
    assert summary["mean_usd"] == 0.003
    assert summary["requests"] == 4
    assert summary["cap_usd"] == 0.01
    assert summary["enabled"] is True


def test_cost_kpis_are_structured_and_flag_guardrail_blocks() -> None:
    kpis = governance.cost_kpis(STATUS, METRICS)
    assert [kpi["label"] for kpi in kpis] == [
        "Window spend",
        "Mean / request",
        "Policy cap / request",
        "Requests",
        "Failure rate",
        "Guardrail blocks",
        "Governance",
    ]
    assert kpis[0]["value"] == "$0.0120"
    assert kpis[1]["value"] == "$0.0030"
    assert kpis[3]["value"] == "4"
    assert kpis[5]["status"]["tone"] == "danger"


def test_cost_chart_rows_use_model_breakdown_when_available() -> None:
    metrics = dict(METRICS)
    metrics["cost"] = dict(METRICS["cost"])
    metrics["cost"]["by_model"] = {"qwen": 0.008, "gpt": 0.004}
    rows = governance.cost_chart_rows(STATUS, metrics)
    assert [row["label"] for row in rows] == ["gpt", "qwen"]
    assert rows[1]["pct"] == 100.0


def test_cost_chart_rows_fall_back_to_window_metrics() -> None:
    rows = governance.cost_chart_rows(STATUS, METRICS)
    assert [row["label"] for row in rows] == [
        "Window spend",
        "Mean / request",
        "Policy cap / request",
    ]
    assert rows[0]["pct"] == 100.0


def test_chart_markdown_escapes_labels_and_keeps_widths_bounded() -> None:
    rows = [
        {"label": "<script>x</script>", "display": "$1", "pct": 250.0},
        {"label": "safe", "display": "$0", "pct": -4.0},
    ]
    html = governance.cost_chart_markdown(rows)
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "width:100.0%" in html
    assert "width:0.0%" in html


def test_alerts_preview_supports_top_level_and_legacy_shapes() -> None:
    flat = governance.alerts_preview(METRICS)
    assert flat and flat[0]["level"] == "critical"
    legacy = governance.alerts_preview(
        {"totals": {"requests": 50, "failures": 6}, "guardrails": {"total_blocks": 11}}
    )
    assert [alert["level"] for alert in legacy] == ["warning", "warning"]


def test_alert_banners_add_budget_breach_and_render_as_alerts() -> None:
    status = dict(STATUS)
    status["max_cost_per_request_usd"] = 0.002
    banners = governance.alert_banners(status, METRICS)
    assert banners[0]["title"] == "CostPerRequestLimit"
    assert banners[0]["tone"] == "danger"
    assert any(banner["title"] == "CriticalFailureRate" for banner in banners)
    html = governance.alert_banner_markdown(banners)
    assert 'class="genai-alert genai-alert-danger"' in html
    assert "CostPerRequestLimit" in html


def test_failure_chart_data_sorts_counts_and_ignores_zero_rows() -> None:
    rows = governance.failure_chart_data(METRICS)
    assert rows == [
        {"label": "timeout", "count": 1, "pct": 100.0, "width": 100.0}
    ]
    html = governance.failure_chart_markdown(rows)
    assert "1 (100.0%)" in html
    assert "genai-failure-fill" in html
    assert "No failures" in governance.failure_chart_markdown([])


def test_guardrail_chart_data_has_stacked_segments() -> None:
    rows = governance.guardrail_chart_data(METRICS)
    assert [row["label"] for row in rows] == ["injection", "pii"]
    injection = rows[0]
    assert injection["total"] == 4
    assert [segment["decision"] for segment in injection["segments"]] == [
        "allow",
        "redact",
        "block",
    ]
    assert sum(segment["width"] for segment in injection["segments"]) == 100.0


def test_guardrail_chart_markdown_has_legend_and_escapes_names() -> None:
    rows = governance.guardrail_chart_data(
        {
            "guardrails": {
                "by_guardrail": {"<b>pii</b>": {"allow": 1, "redact": 1, "block": 2}}
            }
        }
    )
    html = governance.guardrail_chart_markdown(rows)
    assert "&lt;b&gt;pii&lt;/b&gt;" in html
    assert "<b>pii</b>" not in html
    assert "genai-guardrail-segment genai-guardrail-block" in html
    assert "Allow" in html and "Redact" in html and "Block" in html


def test_governance_view_models_combines_all_sections() -> None:
    views = governance.governance_view_models(STATUS, METRICS)
    assert set(views) == {"kpis", "cost_rows", "failure_rows", "guardrail_rows", "alerts"}
    assert views["kpis"] and views["cost_rows"]
    assert views["failure_rows"] and views["guardrail_rows"] and views["alerts"]


def test_governance_helpers_are_pure_and_bot_win_boundary_is_clean() -> None:
    source = Path("ui/governance.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_app_wires_structured_governance_and_demotes_raw_payloads() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    assert "governance_view_models" in source
    assert "cost_chart_markdown" in source
    assert "failure_chart_markdown" in source
    assert "guardrail_chart_markdown" in source
    assert "alert_banner_markdown" in source
    assert "Prometheus scrape (advanced)" in source
    assert 'with st.expander("Spend window (raw)", expanded=False)' in source


def test_governance_view_wireframe_is_indexed() -> None:
    svg = Path("docs/wireframes/245-governance-cost.svg")
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert svg.is_file()
    assert "245-governance-cost.svg" in plan
