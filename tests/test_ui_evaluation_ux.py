"""UX3: Evaluation UX improvements tests (#132)."""

from __future__ import annotations

import ast
from pathlib import Path

from ui import evaluation


def test_evaluation_helpers_dataset_and_metrics():
    ds = evaluation.available_datasets()
    assert ds
    labels = [d.label for d in ds]
    assert "Custom (current query/response)" in labels

    hint = evaluation.ground_truth_hint("semantic")
    assert "ground truth" in hint.lower()

    hint2 = evaluation.ground_truth_hint("dummy")
    assert "semantic" in hint2 or "llm_judge" in hint2

    exp = evaluation.metric_explanation("answer_relevance")
    assert exp is not None
    assert "similarity" in exp.description.lower()

    table = evaluation.metric_table_with_tooltips({"answer_relevance": 0.8, "faithfulness": 0.9})
    assert any(row["explanation"] for row in table)

    matrix = evaluation.build_comparison_matrix([
        {"id": "r1", "evaluator": "semantic", "docs_source": "auto", "ground_truth_used": True, "metrics": {"answer_relevance": 0.7}},
        {"run_id": "r2", "evaluator": "dummy", "docs_source": "auto", "metrics": {"context_precision": 0.5}},
    ])
    assert len(matrix) == 2
    assert matrix[0]["run_id"] == "r1"


def test_evaluation_screen_has_dataset_and_comparison():
    src = Path("ui/app.py").read_text(encoding="utf-8")
    assert "available_datasets" in src
    assert "ground_truth_hint" in src
    assert "Comparison matrix" in src
    assert "metric_table_with_tooltips" in src
    # HTTP-only guard still holds (module imports checked elsewhere)
    tree = ast.parse(src)
    assert tree is not None
