"""Compare what-if structured presentation tests (#247)."""

from __future__ import annotations

from pathlib import Path

from ui import compare

BEFORE_READY = {
    "status": "ready",
    "config_revision": 4,
    "components": {
        "llm": "LocalHFLLM",
        "retriever": "FAISSRetriever",
        "reranker": "SimpleReranker",
        "evaluator": "SemanticEvaluator",
        "query_expander": None,
    },
}
REBUILD = {
    "status": "rebuilt",
    "config_revision": 5,
    "components": {
        "llm": "LocalHFLLM",
        "retriever": "SimpleRetriever",
        "reranker": "SimpleReranker",
        "evaluator": "SemanticEvaluator",
        "query_expander": None,
    },
    "applied_overrides": {
        "default_retriever": "simple",
        "similarity_metric": "l2",
    },
    "effective_config": {
        "models": {"active_model": "local-qwen"},
        "retrieval": {
            "default_retriever": "simple",
            "similarity_metric": "l2",
            "top_k": 4,
        },
    },
}
BEFORE_CONFIG = {
    "models": {"active_model": "local-qwen"},
    "retrieval": {
        "default_retriever": "faiss",
        "similarity_metric": "cosine",
        "top_k": 4,
    },
}


def test_component_rows_keep_stable_order_and_mark_missing() -> None:
    rows = compare.component_rows(BEFORE_READY["components"])
    assert [row["key"] for row in rows] == list(compare.COMPONENT_LABELS)
    assert rows[1]["label"] == "Retriever"
    assert rows[1]["value"] == "FAISSRetriever"
    assert rows[4]["missing"] is True
    assert rows[4]["value"] == "-"


def test_component_cards_markdown_renders_side_by_side_and_escapes_html() -> None:
    html = compare.component_cards_markdown(
        {"llm": "<b>before</b>"},
        {"llm": "after"},
    )
    assert "genai-diff-cards" in html
    assert "Before" in html and "After" in html
    assert "&lt;b&gt;before&lt;/b&gt;" in html
    assert "<b>before</b>" not in html


def test_diff_tone_distinguishes_added_removed_and_changed() -> None:
    assert compare.diff_tone(None, "x") == "better"
    assert compare.diff_tone("x", None) == "worse"
    assert compare.diff_tone("x", "y") == "neutral"
    assert compare.diff_tone("x", "x") == "neutral"


def test_component_delta_rows_label_and_color_changes() -> None:
    rows = compare.component_delta_rows(
        BEFORE_READY["components"], REBUILD["components"]
    )
    by_key = {row["key"]: row for row in rows}
    assert by_key["llm"]["change"] == "unchanged"
    assert by_key["retriever"]["change"] == "changed"
    assert by_key["retriever"]["before"] == "FAISSRetriever"
    assert by_key["retriever"]["after"] == "SimpleRetriever"
    assert by_key["retriever"]["tone"] == "neutral"

    added = compare.component_delta_rows({}, {"llm": "X"})[0]
    removed = compare.component_delta_rows({"llm": "X"}, {})[0]
    assert (added["change"], added["tone"]) == ("added", "better")
    assert (removed["change"], removed["tone"]) == ("removed", "worse")


def test_delta_table_markdown_uses_semantic_classes_and_escapes_fields() -> None:
    html = compare.delta_table_markdown(
        [
            {
                "field": "<b>Field</b>",
                "before": "old",
                "after": "new",
                "change": "changed",
                "tone": "neutral",
            }
        ]
    )
    assert "genai-diff-table" in html
    assert "genai-delta genai-delta-neutral" in html
    assert "&lt;b&gt;Field&lt;/b&gt;" in html
    assert "<b>Field</b>" not in html
    assert "No deltas available." in compare.delta_table_markdown([])


def test_override_delta_rows_resolve_config_paths_and_requested_values() -> None:
    rows = compare.override_delta_rows(
        BEFORE_CONFIG,
        REBUILD["effective_config"],
        REBUILD["applied_overrides"],
    )
    assert [row["key"] for row in rows] == ["default_retriever", "similarity_metric"]
    by_key = {row["key"]: row for row in rows}
    assert by_key["default_retriever"]["before"] == "faiss"
    assert by_key["default_retriever"]["after"] == "simple"
    assert by_key["default_retriever"]["change"] == "changed"
    assert by_key["similarity_metric"]["before"] == "cosine"
    assert by_key["similarity_metric"]["after"] == "l2"

    fallback = compare.override_delta_rows({}, {}, {"top_k": 7})[0]
    assert fallback["after"] == "7"
    assert fallback["change"] == "added"
    assert fallback["tone"] == "better"


def test_compare_view_models_combines_all_sections() -> None:
    views = compare.compare_view_models(BEFORE_READY, REBUILD, BEFORE_CONFIG)
    assert set(views) == {
        "kpis",
        "cards",
        "components",
        "overrides",
        "before_available",
        "revision",
        "raw",
    }
    assert views["before_available"] is True
    assert views["revision"] == 5
    assert [kpi["label"] for kpi in views["kpis"]] == [
        "Config revision",
        "Components changed",
        "Overrides applied",
        "Before snapshot",
    ]
    assert len(views["components"]) == 5
    assert len(views["overrides"]) == 2
    assert "genai-diff-cards" in views["cards"]


def test_compare_view_models_redacts_raw_payloads() -> None:
    rebuild = dict(REBUILD)
    rebuild["applied_overrides"] = {"api_key": "sk-should-not-leak"}
    views = compare.compare_view_models(BEFORE_READY, rebuild, BEFORE_CONFIG)
    assert "sk-should-not-leak" not in str(views["raw"])


def test_compare_helpers_are_pure() -> None:
    source = Path("ui/compare.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_app_wires_structured_compare_without_raw_component_dump() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_compare")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    assert "compare_view_models" in body
    assert "delta_table_markdown" in body
    assert "api.ready()" in body
    assert "api.effective_config()" in body
    assert "st.json(views[\"raw\"])" in body
    assert "st.json(rebuild.data" not in body


def test_compare_view_wireframe_is_indexed() -> None:
    assert Path("docs/wireframes/247-compare-diff.excalidraw").is_file()
    assert Path("docs/wireframes/247-compare-diff.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "247-compare-diff.svg" in plan
