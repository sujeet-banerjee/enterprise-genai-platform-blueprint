"""Evaluation UX helpers (issue #132).

Pure helpers for dataset selection, ground-truth guidance, run comparison,
and metric explanations. HTTP-only and Streamlit-free for testability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

BENCHMARK_PATH = "data/benchmark.json"


@dataclass(frozen=True)
class EvalDataset:
    key: str
    label: str
    description: str
    docs_count: int
    cases_count: int


@dataclass(frozen=True)
class MetricInfo:
    key: str
    label: str
    description: str
    direction: str  # higher_better or lower_better


METRIC_EXPLANATIONS: Tuple[MetricInfo, ...] = (
    MetricInfo("context_precision", "Context precision", "Share of retrieved docs relevant to the query (IR style).", "higher_better"),
    MetricInfo("answer_relevance", "Answer relevance", "Semantic similarity between query and answer.", "higher_better"),
    MetricInfo("faithfulness", "Faithfulness", "How well the answer is grounded in retrieved context.", "higher_better"),
    MetricInfo("ground_truth_similarity", "Ground-truth similarity", "Cosine similarity between answer and reference (when GT provided).", "higher_better"),
    MetricInfo("answer_correctness", "Answer correctness", "Correctness judged against reference when supported by the evaluator.", "higher_better"),
    MetricInfo("context_recall", "Context recall", "Share of relevant docs retrieved (requires ground truth/IR labels).", "higher_better"),
)


def metric_explanation(key: str) -> Optional[MetricInfo]:
    for m in METRIC_EXPLANATIONS:
        if m.key == key:
            return m
    return None


def format_metric_explanation(key: str) -> str:
    m = metric_explanation(key)
    if m:
        return f"{m.label}: {m.description} ({m.direction.replace('_', ' ')})"
    return key


def load_benchmark_summary(path: str = BENCHMARK_PATH) -> Optional[EvalDataset]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    docs = data.get("docs") or []
    cases = data.get("cases") or []
    return EvalDataset(
        key="benchmark",
        label="Built-in benchmark",
        description="Small labeled set for quick regression checks (issue #22).",
        docs_count=len(docs),
        cases_count=len(cases),
    )


def available_datasets() -> List[EvalDataset]:
    out = []
    ds = load_benchmark_summary()
    if ds:
        out.append(ds)
    out.append(
        EvalDataset(
            key="custom",
            label="Custom (current query/response)",
            description="Evaluate the ad-hoc query/response pair shown above.",
            docs_count=0,
            cases_count=1,
        )
    )
    return out


def ground_truth_hint(evaluator: str) -> str:
    ev = (evaluator or "(active)").lower()
    if ev in ("semantic", "llm_judge"):
        return "Ground truth is used by semantic/llm_judge evaluators to compute ground-truth similarity/correctness."
    return "This evaluator does not typically use ground truth; use semantic or llm_judge for GT scoring."


def comparison_row(run: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = run.get("metrics") or {}
    return {
        "run_id": run.get("id") or run.get("run_id") or "-",
        "evaluator": run.get("evaluator") or "-",
        "docs_source": run.get("docs_source") or "-",
        "gt_used": run.get("ground_truth_used"),
        "context_precision": metrics.get("context_precision"),
        "answer_relevance": metrics.get("answer_relevance"),
        "faithfulness": metrics.get("faithfulness"),
        "ground_truth_similarity": metrics.get("ground_truth_similarity"),
        "answer_correctness": metrics.get("answer_correctness"),
    }


def build_comparison_matrix(runs: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [comparison_row(run) for run in runs if isinstance(run, Mapping)]


def metric_table_with_tooltips(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for key, value in metrics.items():
        rows.append({"metric": key, "value": value, "explanation": format_metric_explanation(key)})
    return rows
