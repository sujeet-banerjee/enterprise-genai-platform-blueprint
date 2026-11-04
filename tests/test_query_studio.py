"""Tests for UX2 (#131): Query Studio templates, history, comparison and export.

The workflow helpers live in ``ui/query_studio.py`` and are free of Streamlit and
back-end imports, so this suite exercises real logic. Structural assertions
cover the console wiring in ``ui/app.py`` and the updated tour step.
"""

import ast
from pathlib import Path

from ui.query_studio import (
    MAX_HISTORY,
    QUERY_TEMPLATES,
    add_history,
    build_history_entry,
    comparison_rows,
    find_baseline,
    history_rows,
    result_markdown,
    template_by_label,
    template_labels,
)

REPO_BASE = Path(__file__).resolve().parents[1]
APP_PATH = REPO_BASE / "ui" / "app.py"
TOUR_PATH = REPO_BASE / "ui" / "tour.py"


def _item(**overrides):
    item = {
        "request_id": "req-1",
        "response": "RAG grounds an LLM on retrieved documents.",
        "retrieved_docs_with_scores": [
            {"score": 0.91, "content": "RAG combines retrieval and generation."},
            {"score": 0.72, "content": "Retrieved documents are injected into the prompt."},
        ],
        "cost": {"estimated_cost_usd": 0.0002},
        "latency": {"total_ms": 120.0, "retrieval_ms": 30.0},
        "cache_hit": False,
        "observability": {
            "guardrails_enabled": True,
            "redaction_enabled": True,
            "expanded_queries": ["retrieval augmented generation definition"],
            "otel": {"trace_id": "trace-abc", "span_id": "span-def"},
            "resilience": {"served_by": "primary", "retries": 0},
        },
        "guardrail_decisions": [
            {
                "guardrail": "injection",
                "stage": "input",
                "decision": "allow",
                "allowed": True,
            },
            {
                "guardrail": "deny_list",
                "stage": "output",
                "decision": "redact",
                "allowed": True,
                "reason": "policy term",
            },
        ],
        "failure_tags": [],
    }
    item.update(overrides)
    return item


def _entry(query, item, timestamp="2026-11-04T10:00:00+00:00", top_k=3):
    return build_history_entry(query, top_k, item, timestamp)


def test_templates_are_unique_and_actionable():
    labels = template_labels()
    assert len(labels) == len(QUERY_TEMPLATES)
    assert len(labels) == len(set(labels))
    for template in QUERY_TEMPLATES:
        assert template.query.strip()
        assert 1 <= template.top_k <= 10
        assert template.description.strip()
        assert template_by_label(template.label) is template
    assert template_by_label("not-a-template") is None


def test_build_history_entry_summarises_a_success():
    entry = _entry("What is RAG?", _item())
    assert entry["request_id"] == "req-1"
    assert entry["outcome"] == "success"
    assert entry["latency_ms"] == 120.0
    assert entry["cost_usd"] == 0.0002
    assert entry["doc_count"] == 2
    assert entry["cache_hit"] is False
    assert entry["guardrail_decisions"] == 2
    assert entry["guardrail_blocks"] == 0
    assert entry["top_k"] == 3
    assert entry["result"]["request_id"] == "req-1"


def test_build_history_entry_summarises_a_failure_and_truncates_response():
    item = _item(
        response="x" * 900,
        failure_type="guardrail_input_blocked",
        guardrail_decisions=[
            {"guardrail": "injection", "decision": "block"},
            {"guardrail": "pii", "decision": "block"},
        ],
        observability={},
    )
    entry = _entry("bad query", item)
    assert entry["outcome"] == "failure"
    assert entry["failure_type"] == "guardrail_input_blocked"
    assert entry["guardrail_blocks"] == 2
    assert len(entry["response"]) == 500


def test_history_is_newest_first_deduplicated_and_bounded():
    first = _entry("q1", _item(request_id="req-1"))
    second = _entry("q2", _item(request_id="req-2"))
    replacement = _entry("q1 again", _item(request_id="req-1"))

    history = add_history([], first)
    history = add_history(history, second)
    assert [entry["request_id"] for entry in history] == ["req-2", "req-1"]

    history = add_history(history, replacement)
    assert [entry["request_id"] for entry in history] == ["req-1", "req-2"]
    assert history[0]["query"] == "q1 again"

    bounded = add_history(
        [_entry("q2", _item(request_id="2")), _entry("q1", _item(request_id="1"))],
        _entry("q3", _item(request_id="3")),
        max_entries=2,
    )
    assert [entry["request_id"] for entry in bounded] == ["3", "2"]
    assert add_history([first], second, max_entries=0) == []
    assert MAX_HISTORY == 20


def test_find_baseline_prefers_the_same_query_then_the_latest_run():
    history = [
        _entry("other", _item(request_id="req-3")),
        _entry("same", _item(request_id="req-2")),
        _entry("same", _item(request_id="req-1")),
    ]
    assert find_baseline(history, "same")["request_id"] == "req-2"
    assert find_baseline(history, "same", exclude_request_id="req-2")["request_id"] == "req-1"
    assert find_baseline(history, "missing")["request_id"] == "req-3"
    assert find_baseline([], "anything") is None


def test_comparison_rows_show_deltas_and_changes():
    previous = _entry(
        "same",
        _item(
            request_id="req-1",
            response="old answer",
            latency={"total_ms": 100.0},
            cost={"estimated_cost_usd": 0.001},
            retrieved_docs_with_scores=[{"score": 0.9, "content": "one"}],
            guardrail_decisions=[],
        ),
    )
    current = _entry(
        "same",
        _item(
            request_id="req-2",
            response="new answer",
            latency={"total_ms": 70.0},
            cost={"estimated_cost_usd": 0.002},
            retrieved_docs_with_scores=[
                {"score": 0.9, "content": "one"},
                {"score": 0.8, "content": "two"},
                {"score": 0.7, "content": "three"},
            ],
            cache_hit=True,
            failure_type="guardrail_output_blocked",
            guardrail_decisions=[
                {"guardrail": "deny_list", "decision": "block"},
                {"guardrail": "pii", "decision": "redact"},
            ],
        ),
    )
    rows = {row["metric"]: row for row in comparison_rows(previous, current)}
    assert rows["Outcome"]["change"] == "success -> failure"
    assert rows["Failure type"]["current"] == "guardrail_output_blocked"
    assert rows["Latency (ms)"]["change"] == "-30.0 ms"
    assert rows["Cost (USD)"]["change"] == "+0.001000 USD"
    assert rows["Retrieved docs"]["change"] == "+2"
    assert rows["Cache"]["change"] == "miss -> hit"
    assert rows["Guardrail decisions"]["change"] == "+2"
    assert rows["Guardrail blocks"]["change"] == "+1"
    assert rows["Answer"]["change"] == "changed"


def test_comparison_rows_tolerate_missing_metrics():
    previous = _entry("q", _item(latency={}, cost={}))
    current = _entry("q", _item(latency={}, cost={}, retrieved_docs_with_scores=[]))
    rows = {row["metric"]: row for row in comparison_rows(previous, current)}
    assert rows["Latency (ms)"]["previous"] == "-"
    assert rows["Latency (ms)"]["change"] == "-"
    assert rows["Cost (USD)"]["change"] == "-"
    assert rows["Retrieved docs"]["change"] == "-2"


def test_result_markdown_is_shareable_and_carries_diagnostics():
    markdown = result_markdown("What is RAG?", _item())
    assert "# Query" in markdown
    assert "What is RAG?" in markdown
    assert "RAG grounds an LLM" in markdown
    assert "request_id: `req-1`" in markdown
    assert "RAG combines retrieval and generation." in markdown
    assert "injection (input): allow" in markdown
    assert "Provider resilience" in markdown
    assert "trace_id: `trace-abc`" in markdown
    assert "redacted by the backend" in markdown


def test_result_markdown_handles_a_failure():
    markdown = result_markdown(
        "bad query",
        _item(
            request_id="req-bad",
            response="",
            failure_type="guardrail_input_blocked",
            error="blocked by injection guardrail",
            observability={},
            retrieved_docs_with_scores=[],
            guardrail_decisions=[],
        ),
    )
    assert "Failure `guardrail_input_blocked`" in markdown
    assert "blocked by injection guardrail" in markdown
    assert "## Retrieved documents" not in markdown


def test_history_rows_are_table_ready():
    history = [_entry("q" * 120, _item())]
    rows = history_rows(history)
    assert rows[0]["query"] == "q" * 80
    assert rows[0]["outcome"] == "success"
    assert rows[0]["cache"] == "miss"
    assert rows[0]["request_id"] == "req-1"


def test_app_wires_templates_history_comparison_tabs_and_export():
    text = APP_PATH.read_text(encoding="utf-8")
    for needle in (
        "from ui.query_studio import",
        "QUERY_TEMPLATES",
        "_render_query_templates(",
        "_render_query_history(",
        "build_history_entry(",
        "add_history(",
        "find_baseline(",
        "comparison_rows(",
        "result_markdown(",
        "Compare with last run",
        "Recent runs (this session)",
        "Copy / share (Markdown)",
        "Download Markdown",
        "st.tabs(",
        '"Answer", "Documents", "Trace", "Guardrails", "Resilience", "Cache"',
        "Batch items are shown inline",
    ):
        assert needle in text, f"ui/app.py is missing {needle!r}"


def _tour_query_studio_payload():
    tree = ast.parse(TOUR_PATH.read_text(encoding="utf-8"), filename=str(TOUR_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TourStep":
            fields = {
                kw.arg: kw.value.value
                for kw in node.keywords
                if isinstance(kw.value, ast.Constant)
            }
            if fields.get("screen") == "Query Studio":
                return fields
    raise AssertionError("Query Studio tour step not found")


def test_tour_query_studio_step_covers_the_new_workflow():
    fields = _tour_query_studio_payload()
    body = fields["body"]
    assert "template" in body.lower()
    assert "history" in body.lower()
    assert "Compare with last run" in body
    assert "tabbed results" in body.lower()
