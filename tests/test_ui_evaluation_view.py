"""Evaluation structured presentation tests (#248)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ui import evaluation_view

RUNS = [
    {
        "id": "run-a",
        "evaluator": "semantic",
        "ground_truth_used": True,
        "metrics": {
            "context_precision": 0.4,
            "answer_relevance": 0.9,
            "faithfulness": 0.6,
        },
    },
    {
        "id": "run-b",
        "evaluator": "llm_judge",
        "ground_truth_used": False,
        "metrics": {
            "context_precision": 0.8,
            "answer_relevance": 0.6,
            "faithfulness": 0.7,
        },
    },
]


def test_evaluation_section_cards_render_dataset_run_and_results() -> None:
    cards = evaluation_view.evaluation_section_cards(
        {
            "label": "<Bench>",
            "description": "Labeled set",
            "docs_count": 6,
            "cases_count": 6,
        },
        {"evaluator": "semantic", "query": "What is RAG?", "ground_truth": True},
        {
            "evaluator": "semantic",
            "num_retrieved_docs": 3,
            "ground_truth_used": True,
            "metrics": {"context_precision": 0.8},
        },
    )
    assert set(cards) == {"dataset", "run", "results"}
    assert all("genai-section-card" in html for html in cards.values())
    assert "&lt;Bench&gt;" in cards["dataset"]
    assert "What is RAG?" in cards["run"]
    assert "Ground truth" in cards["run"]
    assert "context_precision" in cards["results"]
    assert "Retrieved docs" in cards["results"]


def test_evaluation_section_cards_handle_empty_payloads() -> None:
    cards = evaluation_view.evaluation_section_cards()
    assert "No details available." in cards["dataset"]
    assert "No details available." in cards["run"]
    assert "No details available." in cards["results"]


def test_job_status_markdown_shows_badge_and_case_kpis() -> None:
    html = evaluation_view.job_status_markdown(
        {
            "status": "running",
            "label": "Built-in benchmark",
            "job_id": "ev-041",
            "total": 6,
            "done": 4,
            "succeeded": 3,
            "failed": 1,
        }
    )
    assert "genai-chip" in html
    assert "Running" in html
    assert "Built-in benchmark" in html
    assert "ev-041" in html
    assert "4 / 6" in html
    assert "Succeeded" in html
    assert "Failed" in html


def test_job_status_markdown_covers_all_job_states() -> None:
    for status in ("queued", "running", "cancelling", "completed", "cancelled", "failed"):
        html = evaluation_view.job_status_markdown({"status": status})
        assert status.replace("_", " ").title() in html
    assert "Unknown" in evaluation_view.job_status_markdown({})


def test_comparison_matrix_rows_mark_best_numeric_metric_per_column() -> None:
    rows = evaluation_view.comparison_matrix_rows(RUNS)
    assert [row["run"] for row in rows] == ["run-a", "run-b"]
    assert rows[0]["evaluator"] == "semantic"
    assert rows[0]["gt_used"] == "Yes"
    assert rows[0]["context_precision__best"] is False
    assert rows[0]["answer_relevance__best"] is True
    assert rows[1]["context_precision__best"] is True
    assert rows[1]["answer_relevance__best"] is False
    assert rows[1]["faithfulness__best"] is True


def test_comparison_matrix_markdown_highlights_best_cells_and_escapes_html() -> None:
    rows = evaluation_view.comparison_matrix_rows(
        [{"id": "<run>", "evaluator": "semantic", "metrics": {"faithfulness": 0.8}}]
    )
    html = evaluation_view.comparison_matrix_markdown(rows)
    assert "genai-eval-matrix" in html
    assert "genai-metric-best" in html
    assert "&lt;run&gt;" in html
    assert "<run>" not in html
    assert "No comparison runs yet." in evaluation_view.comparison_matrix_markdown([])


def test_comparison_chart_data_averages_finite_numeric_metrics() -> None:
    chart = evaluation_view.comparison_chart_data(
        evaluation_view.comparison_matrix_rows(RUNS)
    )
    assert chart == pytest.approx(
        {
            "Context precision": 0.6,
            "Answer relevance": 0.75,
            "Faithfulness": 0.65,
        }
    )
    invalid = evaluation_view.comparison_matrix_rows(
        [{"id": "nan", "metrics": {"context_precision": float("nan")}}]
    )
    assert "Context precision" not in evaluation_view.comparison_chart_data(invalid)


def test_experiment_status_view_structures_status_and_redacts_raw() -> None:
    view = evaluation_view.experiment_status_view(
        {
            "id": "exp-1",
            "status": "completed",
            "kind": "single",
            "metrics": {"faithfulness": 0.7},
            "api_key": "sk-should-not-leak",
        }
    )
    assert view["summary"]["experiment_id"] == "exp-1"
    assert view["summary"]["state"] == "completed"
    assert "faithfulness" in view["summary"]["metrics"]
    assert "Experiment status" in view["markdown"]
    assert "Structured id/state/metrics" in view["markdown"]
    assert view["raw"]["api_key"] == "[REDACTED]"
    assert "sk-should-not-leak" not in str(view["raw"])


def test_experiment_status_view_finds_nested_fields() -> None:
    view = evaluation_view.experiment_status_view(
        {
            "experiment": {
                "id": "exp-2",
                "state": "running",
                "result": {"metrics": {"answer_relevance": 0.3}},
            }
        }
    )
    assert view["summary"]["experiment_id"] == "exp-2"
    assert view["summary"]["state"] == "running"
    assert "answer_relevance" in view["summary"]["metrics"]


def test_evaluation_view_helpers_are_pure() -> None:
    source = Path("ui/evaluation_view.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_app_wires_structured_evaluation_without_raw_experiment_dumps() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_evaluation")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    assert "evaluation_section_cards" in body
    assert "comparison_matrix_rows" in body
    assert "comparison_matrix_markdown" in body
    assert "comparison_chart_data" in body
    assert "experiment_status_view(launch.data)" in body
    assert "experiment_status_view(poll.data)" in body
    assert "st.json(launch.data)" not in body
    assert "st.json(poll.data)" not in body
    assert "job_status_markdown(snap)" in source


def test_evaluation_view_wireframe_is_indexed() -> None:
    assert Path("docs/wireframes/248-evaluation-view.excalidraw").is_file()
    assert Path("docs/wireframes/248-evaluation-view.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "248-evaluation-view.svg" in plan
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    assert "genai-metric-best" in theme
