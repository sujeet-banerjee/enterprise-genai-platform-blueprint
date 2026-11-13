"""Config-driven parameter sweep + Pareto report (issue #181, Workstream K).

Expands a cartesian product of the config levers exposed by
``ExperimentRunner`` (embedding model, retriever, reranker, top_k, chunk
strategy), runs each combination against an evaluation dataset, and reports the
cost/quality/latency trade-off together with a Pareto frontier and a recommended
overlay.

The sweep is **off by default** (``optimization.enabled: false``), dependency
light, and bounded by ``max_combinations`` so CI cannot accidentally launch an
unbounded matrix. It reuses the same composition root as production
(``ExperimentRunner`` -> ``app.bootstrap.assemble_components``).
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import yaml

from core.evaluation.eval_datasets import EvalDataset, load_eval_dataset
from core.evaluation.metrics import Metrics

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "optimization.yaml"
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_DATASET_PATH = "data/benchmark.json"
DEFAULT_MAX_COMBINATIONS = 25

#: Sweep parameter aliases -> canonical ExperimentRunner keyword.
PARAMETER_ALIASES = {
    "embedding": "embedding_model",
    "embedding_model": "embedding_model",
    "retriever": "retriever_backend",
    "retriever_backend": "retriever_backend",
    "reranker": "reranker",
    "use_reranker": "reranker",
    "top_k": "top_k",
    "chunking": "chunk_strategy",
    "chunk_strategy": "chunk_strategy",
}

#: Levers forwarded to ``ExperimentRunner.run_single_experiment``.
SUPPORTED_PARAMETERS = frozenset(PARAMETER_ALIASES.values())


class SweepConfigError(ValueError):
    """Raised when an optimization config is structurally invalid."""


class SweepLimitError(SweepConfigError):
    """Raised when the matrix exceeds ``max_combinations``."""


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_optimization_config(path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Load ``config/optimization.yaml`` (flat, or wrapped in ``optimization:``)."""
    target = Path(path)
    if not target.exists():
        return {}
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise SweepConfigError(f"Optimization config '{target}' must be a mapping")
    if isinstance(data.get("optimization"), Mapping):
        data = data["optimization"]
    return dict(data)


def _coerce(canonical: str, value: Any, source: str) -> Any:
    if canonical == "top_k":
        if isinstance(value, bool):
            raise SweepConfigError(f"'{source}' top_k values must be integers, got {value!r}")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise SweepConfigError(
                f"'{source}' top_k values must be integers, got {value!r}"
            ) from exc
        if parsed < 1:
            raise SweepConfigError(f"'{source}' top_k values must be >= 1, got {parsed}")
        return parsed
    if canonical == "reranker":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise SweepConfigError(f"'{source}' reranker values must be booleans, got {value!r}")
    return str(value)


def normalize_parameters(raw: Any) -> Dict[str, List[Any]]:
    """Return ``{canonical_parameter: [values...]}`` from a flexible mapping."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise SweepConfigError("optimization.parameters must be a mapping")
    out: Dict[str, List[Any]] = {}
    for key, value in raw.items():
        canonical = PARAMETER_ALIASES.get(str(key).strip().lower())
        if canonical is None:
            known = ", ".join(sorted(SUPPORTED_PARAMETERS))
            raise SweepConfigError(
                f"Unknown sweep parameter '{key}'. Supported parameters: {known}"
            )
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        if not values:
            raise SweepConfigError(f"Sweep parameter '{key}' must have at least one value")
        out[canonical] = [_coerce(canonical, item, str(key)) for item in values]
    return out


def expand_combinations(
    parameters: Mapping[str, Sequence[Any]],
    max_combinations: int = DEFAULT_MAX_COMBINATIONS,
) -> List[Dict[str, Any]]:
    """Expand a parameter matrix into deterministic combinations.

    Keys are sorted so the ordering is stable across Python runs. Raises
    :class:`SweepLimitError` when the product exceeds ``max_combinations``.
    """
    limit = int(max_combinations)
    if limit < 1:
        raise SweepConfigError("max_combinations must be >= 1")
    keys = sorted(parameters)
    values = [list(parameters[key]) for key in keys]
    total = 1
    for items in values:
        total *= max(1, len(items))
    if total > limit:
        raise SweepLimitError(
            f"parameter sweep expands to {total} combinations, "
            f"above max_combinations={limit}"
        )
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _dominates(a: Mapping[str, Any], b: Mapping[str, Any], eps: float = 1e-9) -> bool:
    better_or_equal = (
        float(a["quality"]) >= float(b["quality"]) - eps
        and float(a["cost_usd"]) <= float(b["cost_usd"]) + eps
        and float(a["latency_ms"]) <= float(b["latency_ms"]) + eps
    )
    strictly_better = (
        float(a["quality"]) > float(b["quality"]) + eps
        or float(a["cost_usd"]) < float(b["cost_usd"]) - eps
        or float(a["latency_ms"]) < float(b["latency_ms"]) - eps
    )
    return better_or_equal and strictly_better


def pareto_frontier(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Return the non-dominated rows (max quality, min cost, min latency)."""
    frontier: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        dominated = any(
            _dominates(other, row) for other in rows if other is not row
        )
        if not dominated:
            frontier.append(dict(row))
    return frontier


def _config_overlay(parameters: Mapping[str, Any]) -> Dict[str, Any]:
    """Translate sweep parameters into a YAML-shaped config overlay."""
    overlay: Dict[str, Any] = {}
    if "embedding_model" in parameters:
        overlay["active_embedding_model"] = parameters["embedding_model"]
    if "retriever_backend" in parameters:
        overlay.setdefault("retrieval", {})["default_retriever"] = parameters["retriever_backend"]
    if "top_k" in parameters:
        overlay.setdefault("retrieval", {})["top_k"] = parameters["top_k"]
    if "reranker" in parameters:
        overlay["reranking"] = {"enabled": parameters["reranker"]}
    if "chunk_strategy" in parameters:
        overlay["chunking"] = {"active_strategy": parameters["chunk_strategy"]}
    return overlay


def recommend_overlay(
    frontier: Sequence[Mapping[str, Any]],
    objective: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Pick the best frontier row under the objective's budgets.

    Highest quality wins; ties break on cost, latency and combination id so the
    recommendation is deterministic. When budgets are configured but no frontier
    row satisfies them, the best-quality row is still returned with
    ``within_budget: false``.
    """
    if not frontier:
        return None
    objective = objective or {}
    cost_budget = _to_float(objective.get("cost_budget_usd"))
    latency_budget = _to_float(objective.get("latency_budget_ms"))

    feasible = [
        row
        for row in frontier
        if (cost_budget is None or float(row["cost_usd"]) <= cost_budget + 1e-12)
        and (latency_budget is None or float(row["latency_ms"]) <= latency_budget + 1e-12)
    ]
    pool = feasible or list(frontier)
    best = sorted(
        pool,
        key=lambda row: (
            -float(row["quality"]),
            float(row["cost_usd"]),
            float(row["latency_ms"]),
            str(row["combination_id"]),
        ),
    )[0]
    budgets_set = cost_budget is not None or latency_budget is not None
    return {
        "combination_id": best["combination_id"],
        "parameters": dict(best.get("parameters") or {}),
        "metrics": dict(best.get("metrics") or {}),
        "quality": float(best["quality"]),
        "quality_metric": str(objective.get("quality") or "context_recall"),
        "cost_usd": float(best["cost_usd"]),
        "latency_ms": float(best["latency_ms"]),
        "p95_latency_ms": float(best["p95_latency_ms"]),
        "config_overlay": _config_overlay(best.get("parameters") or {}),
        "within_budget": bool(feasible) if budgets_set else True,
    }


def _prepare_docs(dataset: EvalDataset) -> Optional[List[Any]]:
    """Annotate corpus docs with stable ``doc_id`` metadata for IR metrics."""
    if not dataset.docs:
        return None
    docs: List[Any] = []
    for index, doc in enumerate(dataset.docs):
        if isinstance(doc, Mapping):
            metadata = dict(doc.get("metadata") or {})
            metadata.setdefault("doc_id", index)
            docs.append({**dict(doc), "metadata": metadata})
        else:
            docs.append(doc)
    return docs


def _default_top_k(config_dir: Union[str, Path]) -> int:
    retrieval_path = Path(config_dir) / "retrieval.yaml"
    if not retrieval_path.exists():
        return 3
    try:
        data = yaml.safe_load(retrieval_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return 3
    retrieval = data.get("retrieval") if isinstance(data, Mapping) else None
    if isinstance(retrieval, Mapping):
        try:
            return int(retrieval.get("top_k") or 3)
        except (TypeError, ValueError):
            return 3
    return 3


def _default_runner(config_dir: Union[str, Path]) -> Any:
    from core.services.experiment_runner import ExperimentRunner

    base = Path(config_dir)
    paths = {
        "models_config_path": base / "models.yaml",
        "prompt_config_path": base / "prompt_config.yaml",
        "retrieval_config_path": base / "retrieval.yaml",
        "governance_config_path": base / "governance.yaml",
        "observability_config_path": base / "observability.yaml",
        "resilience_config_path": base / "resilience.yaml",
        "guardrails_config_path": base / "guardrails.yaml",
        "acl_config_path": base / "acl.yaml",
    }
    kwargs = {name: str(path) for name, path in paths.items() if path.exists()}
    return ExperimentRunner(**kwargs)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(fraction * len(ordered)))))
    return float(ordered[rank - 1])


def _retrieved_ids(run: Mapping[str, Any]) -> List[Any]:
    """Extract ``doc_id`` values from an experiment run's retrieved documents."""
    with_scores = run.get("retrieved_docs_with_scores")
    if isinstance(with_scores, list):
        ids: List[Any] = []
        for doc in with_scores:
            if not isinstance(doc, Mapping):
                continue
            metadata = doc.get("metadata")
            if isinstance(metadata, Mapping) and "doc_id" in metadata:
                ids.append(metadata["doc_id"])
        return ids
    return Metrics.retrieved_doc_ids(run.get("retrieved_documents") or [])


def _run_combo(
    runner: Any,
    dataset: EvalDataset,
    combination: Mapping[str, Any],
    docs: Optional[List[Any]],
    base_top_k: int,
) -> Dict[str, Any]:
    metric_values: Dict[str, List[float]] = defaultdict(list)
    costs: List[float] = []
    latencies: List[float] = []

    for case in dataset.cases:
        run = runner.run_single_experiment(
            docs=docs,
            query=case.query,
            embedding_model=combination.get("embedding_model"),
            chunk_strategy=combination.get("chunk_strategy"),
            retriever_backend=combination.get("retriever_backend"),
            use_reranker=combination.get("reranker"),
            top_k=int(combination.get("top_k", base_top_k)),
        )
        run_metrics = dict(run.get("metrics") or {})
        if case.relevant_doc_ids:
            retrieved_ids = _retrieved_ids(run)
            run_metrics["context_precision"] = Metrics.context_precision_at_ids(
                case.relevant_doc_ids, retrieved_ids
            )
            run_metrics["context_recall"] = Metrics.context_recall_at_ids(
                case.relevant_doc_ids, retrieved_ids
            )
            run_metrics["mrr"] = Metrics.mrr_at_ids(
                case.relevant_doc_ids, retrieved_ids
            )
            run_metrics["ndcg"] = Metrics.ndcg_at_ids(
                case.relevant_doc_ids, retrieved_ids
            )
        for name, value in run_metrics.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metric_values[str(name)].append(float(value))
        costs.append(float(run.get("cost_usd") or 0.0))
        latency = run.get("latency_summary") or {}
        latencies.append(float(latency.get("total_ms") or 0.0))

    metrics = {name: _mean(values) for name, values in metric_values.items() if values}
    return {
        "metrics": metrics,
        "cost_usd": _mean(costs),
        "total_cost_usd": sum(costs),
        "latency_ms": _mean(latencies),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "num_cases": len(dataset.cases),
    }


def run_sweep(
    config: Mapping[str, Any],
    *,
    config_dir: Union[str, Path] = DEFAULT_CONFIG_DIR,
    dataset: Optional[EvalDataset] = None,
    runner: Optional[Any] = None,
    max_combinations: Optional[int] = None,
) -> Dict[str, Any]:
    """Run a config-driven sweep and return rows, Pareto frontier and overlay."""
    if not isinstance(config, Mapping):
        raise SweepConfigError("optimization config must be a mapping")
    if not bool(config.get("enabled", False)):
        return {
            "enabled": False,
            "skipped": True,
            "reason": "optimization.enabled is false",
            "rows": [],
            "pareto_frontier": [],
            "recommended": None,
        }

    raw_parameters = config.get("parameters")
    parameters = normalize_parameters(raw_parameters)
    if not parameters:
        return {
            "enabled": True,
            "skipped": True,
            "reason": "optimization.parameters is empty",
            "rows": [],
            "pareto_frontier": [],
            "recommended": None,
        }

    limit = max_combinations
    if limit is None:
        try:
            limit = int(config.get("max_combinations") or DEFAULT_MAX_COMBINATIONS)
        except (TypeError, ValueError) as exc:
            raise SweepConfigError("max_combinations must be an integer") from exc
    combinations = expand_combinations(parameters, limit)

    if dataset is None:
        dataset_path = config.get("dataset") or DEFAULT_DATASET_PATH
        dataset = load_eval_dataset(str(dataset_path))

    objective = config.get("objective")
    objective_map: Dict[str, Any] = dict(objective) if isinstance(objective, Mapping) else {}
    quality_metric = str(objective_map.get("quality") or "context_recall")

    active_runner = runner or _default_runner(config_dir)
    docs = _prepare_docs(dataset)
    base_top_k = _default_top_k(config_dir)

    rows: List[Dict[str, Any]] = []
    for index, combination in enumerate(combinations, start=1):
        result = _run_combo(active_runner, dataset, combination, docs, base_top_k)
        metrics = result["metrics"]
        rows.append(
            {
                "combination_id": f"combo-{index:04d}",
                "parameters": dict(combination),
                "metrics": metrics,
                "quality": float(metrics.get(quality_metric, 0.0)),
                **{key: result[key] for key in (
                    "cost_usd",
                    "total_cost_usd",
                    "latency_ms",
                    "p95_latency_ms",
                    "num_cases",
                )},
            }
        )

    frontier = pareto_frontier(rows)
    recommended = recommend_overlay(frontier, objective_map)
    return {
        "enabled": True,
        "skipped": False,
        "dataset": dataset.to_dict(),
        "objective": {"quality": quality_metric, **objective_map},
        "parameters": parameters,
        "max_combinations": limit,
        "num_combinations": len(rows),
        "rows": rows,
        "pareto_frontier": [row["combination_id"] for row in frontier],
        "frontier": frontier,
        "recommended": recommended,
    }


def gate_recommended(
    summary: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Gate the recommended row with the #180 budget-aware gate."""
    from core.evaluation.regression_gate import evaluate_report_thresholds

    recommended = summary.get("recommended")
    if not isinstance(recommended, Mapping):
        return None
    report = {
        "dataset": (summary.get("dataset") or {}).get("name", "dataset"),
        "metrics": dict(recommended.get("metrics") or {}),
        "cost": {"estimated_cost_usd": recommended.get("cost_usd", 0.0)},
        "latency": {
            "total_ms": recommended.get("latency_ms", 0.0),
            "p95_ms": recommended.get("p95_latency_ms", 0.0),
        },
        "num_cases": (summary.get("dataset") or {}).get("num_cases"),
    }
    dataset_name = str(report["dataset"])
    return evaluate_report_thresholds(report, thresholds, dataset=dataset_name).to_dict()
