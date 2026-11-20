"""Guardrails structured view tests (#246)."""

from __future__ import annotations

from pathlib import Path

from ui import guardrails

INTROSPECTION = {
    "enabled": True,
    "profile": "standard",
    "providers": ["injection", "deny_list", "pii"],
    "input": [
        {
            "provider": "injection",
            "type": "guardrail",
            "stage": "input",
            "options": {"sensitivity": "medium", "api_key": "sk-secret"},
        },
        {"provider": "pii", "type": "guardrail", "stage": "input", "options": {}},
    ],
    "output": [
        {
            "provider": "deny_list",
            "type": "guardrail",
            "stage": "output",
            "options": {"mask": "[REDACTED-POLICY]"},
        }
    ],
}
METRICS = {
    "guardrails": {
        "total_decisions": 5,
        "total_blocks": 1,
        "by_decision": {"allow": 3, "redact": 1, "block": 1},
        "by_guardrail": {
            "injection": {"allow": 2, "redact": 1, "block": 1},
            "pii": {"allow": 1, "redact": 0, "block": 0},
        },
    }
}
DECISIONS = [
    {
        "guardrail": "injection",
        "stage": "input",
        "decision": "block",
        "allowed": False,
        "reason": "instruction override",
        "labels": ["injection:instruction_override"],
        "api_key": "sk-should-not-leak",
    },
    {
        "guardrail": "pii",
        "stage": "output",
        "decision": "redact",
        "allowed": True,
        "reason": "email detected",
        "labels": ["pii:email"],
    },
    {
        "guardrail": "deny_list",
        "stage": "output",
        "decision": "allow",
        "allowed": True,
        "reason": "no policy match",
        "labels": [],
    },
]


def test_chain_cards_preserve_edge_order_and_redact_options() -> None:
    cards = guardrails.chain_cards(INTROSPECTION)
    assert [card["edge"] for card in cards] == ["input", "output"]
    assert [card["count"] for card in cards] == [2, 1]
    assert [node["order"] for node in cards[0]["nodes"]] == [1, 2]
    assert cards[0]["nodes"][0]["provider"] == "injection"
    assert [row["value"] for row in cards[0]["nodes"][0]["options"]] == [
        "medium",
        "[REDACTED]",
    ]


def test_chain_cards_markdown_renders_ordered_nodes_and_escapes_html() -> None:
    introspection = {
        "input": [
            {
                "provider": "<b>injection</b>",
                "type": "guardrail",
                "stage": "input",
                "options": {},
            },
            {
                "provider": "pii",
                "type": "guardrail",
                "stage": "input",
                "options": {},
            },
        ],
        "output": [],
    }
    html = guardrails.chain_cards_markdown(guardrails.chain_cards(introspection))
    assert "Input chain" in html and "Output chain" in html
    assert "genai-guardrail-node" in html
    assert "genai-guardrail-arrow" in html
    assert "&lt;b&gt;injection&lt;/b&gt;" in html
    assert "<b>injection</b>" not in html
    assert "No guardrails configured on this edge." in html


def test_decision_badge_uses_semantic_palette() -> None:
    assert guardrails.decision_badge("allow")["tone"] == "success"
    assert guardrails.decision_badge("redact")["tone"] == "warning"
    assert guardrails.decision_badge("block")["tone"] == "danger"
    assert guardrails.decision_badge("unexpected")["tone"] == "neutral"


def test_decision_rows_normalize_and_redact_raw_records() -> None:
    rows = guardrails.decision_rows(DECISIONS)
    assert [row["decision"] for row in rows] == ["block", "redact", "allow"]
    assert rows[0]["allowed"] == "No"
    assert rows[0]["labels"] == "injection:instruction_override"
    assert "sk-should-not-leak" not in str(rows[0]["raw"])
    assert rows[1]["stage"] == "output"


def test_decision_history_markdown_has_badges_and_raw_disclosure() -> None:
    html = guardrails.decision_history_markdown(guardrails.decision_rows(DECISIONS))
    assert "genai-decision-table" in html
    assert "genai-chip-success" in html
    assert "genai-chip-warning" in html
    assert "genai-chip-danger" in html
    assert "<details" in html and "<summary>Raw</summary>" in html
    assert "sk-should-not-leak" not in html
    assert "No decision history recorded yet." in guardrails.decision_history_markdown([])


def test_hit_rate_summary_uses_totals_with_by_decision_fallback() -> None:
    summary = guardrails.hit_rate_summary(METRICS)
    assert summary == {"total": 5, "blocks": 1, "redactions": 1, "allow_rate": 60.0}
    fallback = guardrails.hit_rate_summary(
        {"guardrails": {"by_decision": {"allow": 1, "redact": 1, "block": 2}}}
    )
    assert fallback["total"] == 4
    assert fallback["blocks"] == 2
    assert guardrails.hit_rate_summary({})["allow_rate"] == 0.0


def test_hit_rate_rows_and_markdown_keep_readable_legend() -> None:
    rows = guardrails.hit_rate_rows(METRICS)
    assert [row["label"] for row in rows] == ["injection", "pii"]
    html = guardrails.hit_rate_markdown(rows)
    assert "genai-guardrail-chart" in html
    assert "Allow" in html and "Redact" in html and "Block" in html
    assert "genai-guardrail-segment genai-guardrail-block" in html


def test_guardrail_view_models_combines_all_sections() -> None:
    views = guardrails.guardrail_view_models(INTROSPECTION, METRICS, DECISIONS)
    assert set(views) == {"kpis", "chain", "hit_rate", "hit_rate_rows", "decisions", "errors"}
    assert [kpi["label"] for kpi in views["kpis"]] == [
        "Enabled",
        "Profile",
        "Providers",
        "Config errors",
    ]
    assert len(views["chain"]) == 2
    assert len(views["decisions"]) == 3
    assert views["hit_rate"]["blocks"] == 1


def test_guardrails_helpers_are_pure() -> None:
    source = Path("ui/guardrails.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_app_wires_structured_guardrails_and_keeps_probe() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    assert "guardrail_view_models" in source
    assert "chain_cards_markdown" in source
    assert "decision_history_markdown" in source
    assert "hit_rate_markdown" in source
    assert "api.guardrails()" in source
    assert "Run to inspect decisions" in source
    assert 'st.session_state.last_guardrail_at =' in source


def test_guardrails_view_wireframe_is_indexed() -> None:
    assert Path("docs/wireframes/246-guardrails-view.excalidraw").is_file()
    assert Path("docs/wireframes/246-guardrails-view.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "246-guardrails-view.svg" in plan
