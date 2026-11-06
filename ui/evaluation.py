"""Evaluation UX helpers (issues #132 and #145).

Pure helpers for dataset selection/execution, ground-truth guidance, run
comparison, and metric explanations. HTTP-only and Streamlit-free for testability.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

BENCHMARK_PATH = "data/benchmark.json"
MAX_DATASET_CASES = 20
CUSTOM_DATASET_TEMPLATE = """[
  {
    "query": "What is retrieval augmented generation?",
    "reference": "RAG grounds a language model on documents retrieved for the query."
  }
]"""


@dataclass(frozen=True)
class EvalDataset:
    key: str
    label: str
    description: str
    docs_count: int
    cases_count: int


@dataclass(frozen=True)
class EvaluationCase:
    query: str
    reference: str = ""
    tags: Tuple[str, ...] = ()


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


CASE_COLUMNS = {
    "case",
    "query",
    "status",
    "ground_truth_used",
    "docs_source",
    "num_retrieved_docs",
    "request_id",
    "error",
    "evaluator",
}


def _document_content(document: Any) -> str:
    if isinstance(document, Mapping):
        return str(document.get("content") or "").strip()
    return str(document or "").strip()


def _reference_from_benchmark(case: Mapping[str, Any], docs: Any) -> str:
    if not isinstance(docs, list):
        return ""
    ids = case.get("relevant_doc_ids") or case.get("relevant_docs") or []
    if not isinstance(ids, list):
        return ""
    parts: List[str] = []
    for doc_id in ids:
        if not isinstance(doc_id, int) or not 0 <= doc_id < len(docs):
            continue
        content = _document_content(docs[doc_id])
        if content:
            parts.append(content)
    return " ".join(parts)


def parse_dataset_json(text: str) -> List[EvaluationCase]:
    """Parse a bare case list or benchmark-shaped ``{docs, cases}`` payload."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg} (line {exc.lineno})") from exc

    docs: Any = None
    if isinstance(payload, Mapping):
        docs = payload.get("docs")
        raw_cases = payload.get("cases")
    elif isinstance(payload, list):
        raw_cases = payload
    else:
        raise ValueError("Dataset must be a JSON list or an object with a `cases` list")

    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Dataset must contain at least one case")

    cases: List[EvaluationCase] = []
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Case {index} must be a JSON object")
        query = str(raw.get("query") or raw.get("question") or "").strip()
        if not query:
            raise ValueError(f"Case {index} is missing a `query`")

        reference: Any = (
            raw.get("reference")
            or raw.get("ground_truth")
            or raw.get("expected_answer")
            or _reference_from_benchmark(raw, docs)
            or ""
        )
        if isinstance(reference, list):
            reference = " ".join(str(item).strip() for item in reference if str(item).strip())
        tags: Any = raw.get("tags") or ()
        if isinstance(tags, str):
            tags = (tags,)
        if not isinstance(tags, (list, tuple)):
            tags = ()
        clean_tags = tuple(str(tag).strip() for tag in tags if str(tag).strip())
        cases.append(
            EvaluationCase(
                query=query,
                reference=str(reference).strip(),
                tags=clean_tags,
            )
        )
    return cases


def load_benchmark_cases(path: str = BENCHMARK_PATH) -> List[EvaluationCase]:
    """Load the repo's labeled benchmark, or return [] when it is unavailable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return parse_dataset_json(handle.read())
    except (OSError, ValueError):
        return []


def limit_cases(
    cases: Sequence[EvaluationCase], limit: int = MAX_DATASET_CASES
) -> List[EvaluationCase]:
    if limit <= 0:
        return []
    return list(cases)[: min(limit, MAX_DATASET_CASES)]


def dataset_preview_rows(cases: Sequence[EvaluationCase]) -> List[Dict[str, Any]]:
    return [
        {
            "#": index,
            "query": case.query,
            "reference": case.reference or "-",
            "tags": ", ".join(case.tags) or "-",
        }
        for index, case in enumerate(cases, start=1)
    ]


def _api_error(result: Any) -> str:
    data = getattr(result, "data", None)
    if isinstance(data, Mapping):
        for key in ("error", "detail", "message"):
            value = data.get(key)
            if value:
                return str(value)
    error = getattr(result, "error", None)
    if error:
        return str(error)
    status_code = getattr(result, "status_code", None)
    return f"HTTP {status_code}" if status_code else "request failed"


def build_evaluation_row(
    case: EvaluationCase,
    evaluation: Optional[Mapping[str, Any]] = None,
    *,
    index: int = 1,
    error: str = "",
) -> Dict[str, Any]:
    """Flatten one evaluator response into a case/metric matrix row."""
    payload = evaluation or {}
    metrics = payload.get("metrics") or {}
    row: Dict[str, Any] = {
        "case": index,
        "query": case.query,
        "status": "error" if error else "ok",
        "ground_truth_used": bool(payload.get("ground_truth_used")),
        "docs_source": payload.get("docs_source") or "auto",
        "num_retrieved_docs": payload.get("num_retrieved_docs", 0),
        "request_id": payload.get("request_id") or "",
        "error": error,
        "evaluator": payload.get("evaluator") or "",
    }
    if isinstance(metrics, Mapping):
        row.update(dict(metrics))
    return row


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def metric_columns(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    """Return numeric metric columns in guide order, then evaluator extras."""
    columns: List[str] = []
    for metric in METRIC_EXPLANATIONS:
        if any(_is_number(row.get(metric.key)) for row in rows):
            columns.append(metric.key)
    for row in rows:
        for key, value in row.items():
            if key in CASE_COLUMNS or key in columns or not _is_number(value):
                continue
            columns.append(key)
    return columns


def metric_matrix(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Case-by-metric matrix for the evaluation dataframe/chart."""
    columns = metric_columns(rows)
    matrix: List[Dict[str, Any]] = []
    for row in rows:
        matrix.append(
            {
                "case": row.get("case"),
                "query": row.get("query"),
                "status": row.get("status"),
                "ground_truth_used": row.get("ground_truth_used"),
                **{column: row.get(column) for column in columns},
            }
        )
    return matrix


def metric_summary(
    rows: Sequence[Mapping[str, Any]], metrics: Optional[Sequence[str]] = None
) -> Dict[str, float]:
    """Mean of each finite numeric metric across successful rows."""
    columns = list(metrics) if metrics is not None else metric_columns(rows)
    summary: Dict[str, float] = {}
    for key in columns:
        values = [
            float(row[key])
            for row in rows
            if _is_number(row.get(key)) and math.isfinite(float(row[key]))
        ]
        if values:
            summary[key] = round(sum(values) / len(values), 6)
    return summary


def compare_metric_averages(
    previous_rows: Sequence[Mapping[str, Any]],
    current_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Compare per-metric means between the previous and current dataset runs."""
    previous = metric_summary(previous_rows)
    current = metric_summary(current_rows)
    keys: List[str] = []
    for key in [*(metric.key for metric in METRIC_EXPLANATIONS), *previous, *current]:
        if key not in keys:
            keys.append(key)

    rows: List[Dict[str, Any]] = []
    for key in keys:
        before = previous.get(key)
        after = current.get(key)
        if before is None and after is None:
            continue
        if before is None or after is None:
            delta = None
            direction = "-"
        else:
            delta = round(after - before, 6)
            direction = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
        rows.append(
            {
                "metric": metric_explanation(key).label if metric_explanation(key) else key,
                "previous": before,
                "current": after,
                "delta": delta,
                "direction": direction,
            }
        )
    return rows


def run_dataset_evaluation(
    cases: Sequence[EvaluationCase],
    api: Any,
    *,
    evaluator: Optional[str] = None,
    top_k: int = 3,
    max_cases: int = MAX_DATASET_CASES,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Run query -> evaluate for each case, isolating per-case failures."""
    selected = None if not evaluator or evaluator == "(active)" else evaluator
    limited = limit_cases(cases, max_cases)
    total = len(limited)
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(limited, start=1):
        try:
            query_result = api.query(case.query, top_k=top_k, include_trace=False)
        except Exception as exc:
            rows.append(
                build_evaluation_row(case, index=index, error=f"query failed: {exc}")
            )
        else:
            if not getattr(query_result, "ok", False):
                rows.append(
                    build_evaluation_row(case, index=index, error=_api_error(query_result))
                )
            else:
                query_data = getattr(query_result, "data", {}) or {}
                response = str(query_data.get("response") or query_data.get("answer") or "")
                docs = query_data.get("retrieved_docs")
                retrieved_docs = docs if isinstance(docs, list) and docs else None
                try:
                    evaluation = api.evaluate(
                        case.query,
                        response,
                        retrieved_docs=retrieved_docs,
                        ground_truth=case.reference or None,
                        evaluator=selected,
                        top_k=top_k,
                    )
                except Exception as exc:
                    rows.append(
                        build_evaluation_row(
                            case, index=index, error=f"evaluation failed: {exc}"
                        )
                    )
                else:
                    if getattr(evaluation, "ok", False):
                        rows.append(
                            build_evaluation_row(
                                case,
                                getattr(evaluation, "data", {}) or {},
                                index=index,
                            )
                        )
                    else:
                        rows.append(
                            build_evaluation_row(
                                case, index=index, error=_api_error(evaluation)
                            )
                        )
        if on_progress:
            on_progress(index, total)
    return rows
