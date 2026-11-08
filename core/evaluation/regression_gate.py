"""CI regression gates for evaluation (issue #125, Workstream K).

Compares evaluation metrics against configured minimum thresholds and fails
(non-zero) when a metric regresses below its threshold. Designed to be
config-driven and safe by default: gates run only when ``eval_datasets.regression.enabled``
is true.

Supports IR benchmark datasets (``BenchmarkRunner`` -> context_precision/context_recall).
Deterministic/offline execution is supported by injecting a retriever + embedder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import yaml

from core.evaluation.benchmark_runner import BenchmarkRunner
from core.evaluation.eval_datasets import EvalDataset, discover_eval_datasets

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"

METRIC_ALIASES = {
    "precision": "context_precision",
    "recall": "context_recall",
    "context_precision": "context_precision",
    "context_recall": "context_recall",
}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_thresholds(raw: Any) -> Dict[str, float]:
    """Return a metric->minimum mapping from flexible config shapes."""
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, float] = {}
    for key, value in raw.items():
        metric = METRIC_ALIASES.get(str(key).strip().lower())
        if not metric:
            continue
        if isinstance(value, Mapping):
            candidate = value.get("min")
            if candidate is None:
                candidate = value.get("minimum")
            if candidate is None:
                candidate = value.get("gte")
        else:
            candidate = value
        num = _to_float(candidate)
        if num is not None:
            out[metric] = num
    return out


@dataclass
class GateResult:
    dataset: str
    passed: bool
    metrics: Dict[str, float] = field(default_factory=dict)
    thresholds: Dict[str, float] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "passed": self.passed,
            "metrics": dict(self.metrics),
            "thresholds": dict(self.thresholds),
            "failures": list(self.failures),
            "details": dict(self.details),
        }


def evaluate_report_thresholds(
    report: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    *,
    dataset: str = "dataset",
) -> GateResult:
    """Pure gate: compare a metrics report to thresholds."""
    mins = normalize_thresholds(thresholds)
    metrics: Dict[str, float] = {}
    failures: List[str] = []
    for metric, minimum in mins.items():
        actual = _to_float(report.get(metric))
        if actual is None:
            failures.append(f"{metric}: missing (required >= {minimum})")
            continue
        metrics[metric] = actual
        if actual + 1e-12 < minimum:
            failures.append(f"{metric}: {actual:.6f} < {minimum:.6f}")
    passed = not failures and bool(mins)
    return GateResult(
        dataset=dataset,
        passed=passed,
        metrics=metrics,
        thresholds=mins,
        failures=failures,
        details={
            "num_cases": report.get("num_cases"),
            "top_k": report.get("top_k"),
        },
    )


def _load_yaml(path: Union[str, Path]) -> Dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _eval_cfg(config_dir: Union[str, Path]) -> Dict[str, Any]:
    cfg = _load_yaml(Path(config_dir) / "eval_datasets.yaml")
    if isinstance(cfg.get("eval_datasets"), Mapping):
        cfg = cfg["eval_datasets"]
    return cfg if isinstance(cfg, dict) else {}


def _dataset_thresholds(
    dataset: EvalDataset, spec: Any, regression_cfg: Mapping[str, Any]
) -> Dict[str, float]:
    candidates: List[Any] = []
    if isinstance(spec, Mapping):
        candidates.extend([spec.get("thresholds"), spec.get("regression_thresholds")])
    candidates.append(dataset.metadata.get("thresholds"))
    candidates.append(dataset.metadata.get("regression_thresholds"))
    ds_map = regression_cfg.get("datasets")
    if isinstance(ds_map, Mapping) and dataset.name in ds_map:
        entry = ds_map[dataset.name]
        if isinstance(entry, Mapping):
            candidates.extend([entry.get("thresholds"), entry, entry.get("metrics")])
    for candidate in candidates:
        mins = normalize_thresholds(candidate)
        if mins:
            return mins
    return normalize_thresholds(regression_cfg.get("thresholds"))


def run_ir_benchmark_dataset(
    dataset: EvalDataset,
    *,
    top_k: int = 3,
    retriever: Any = None,
    embedder: Any = None,
    config_path: Optional[str] = None,
    retriever_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Run an IR benchmark dataset and return a report dict."""
    # Reuse BenchmarkRunner by materializing the dataset to a temp-compatible
    # shape via an in-memory path workaround: BenchmarkRunner loads from a file,
    # so prefer the dataset path when available; otherwise write nothing and use
    # the injected retriever path by constructing a runner over the file.
    if not dataset.path and retriever is None:
        raise ValueError(f"Dataset '{dataset.name}' has no path; provide retriever+embedder")
    runner = BenchmarkRunner(
        config_path=config_path,
        benchmark_path=dataset.path,
        retriever=retriever,
        embedder=embedder,
        retriever_name=retriever_name,
    )
    # If the dataset came from JSONL/canonical form without docs on disk in the
    # legacy shape, BenchmarkRunner.load_benchmark may not apply; fall back to a
    # direct path-based run which is the supported contract.
    return runner.run(top_k=top_k)


def run_regression_gates(
    *,
    config_dir: Union[str, Path] = DEFAULT_CONFIG_DIR,
    config_path: Optional[str] = None,
    datasets: Optional[Sequence[EvalDataset]] = None,
    retriever: Any = None,
    embedder: Any = None,
    top_k: Optional[int] = None,
    enabled_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run configured regression gates.

    Returns a summary with ``ok`` and per-dataset results. When regression gating
    is disabled (default), returns ``ok=True`` with ``skipped=True`` so CI can run
    the gate step unconditionally without blocking.
    """
    cfg = _eval_cfg(config_dir)
    reg = cfg.get("regression")
    regression_cfg: Dict[str, Any] = dict(reg) if isinstance(reg, Mapping) else {}
    enabled = bool(cfg.get("enabled", False)) and bool(regression_cfg.get("enabled", False))
    if enabled_override is not None:
        enabled = enabled_override
    if not enabled:
        return {
            "ok": True,
            "skipped": True,
            "reason": "eval_datasets.regression.enabled is false",
            "results": [],
        }

    default_top_k = int(regression_cfg.get("top_k") or 3)
    gate_datasets = list(datasets) if datasets is not None else discover_eval_datasets(cfg)
    if not gate_datasets:
        return {
            "ok": False,
            "skipped": False,
            "reason": "regression enabled but no eval datasets were discovered",
            "results": [],
        }

    dec = cfg.get("datasets")
    declared: Dict[str, Any] = dict(dec) if isinstance(dec, Mapping) else {}
    results: List[GateResult] = []
    for dataset in gate_datasets:
        spec = declared.get(dataset.name) if isinstance(declared, Mapping) else None
        thresholds = _dataset_thresholds(dataset, spec, regression_cfg)
        if not thresholds:
            results.append(
                GateResult(
                    dataset=dataset.name,
                    passed=True,
                    thresholds={},
                    failures=[],
                    details={"skipped": True, "reason": "no thresholds configured"},
                )
            )
            continue
        ds_top_k = default_top_k
        if isinstance(spec, Mapping) and spec.get("top_k") is not None:
            try:
                ds_top_k = int(spec["top_k"])
            except (TypeError, ValueError):
                ds_top_k = default_top_k
        ds_map = regression_cfg.get("datasets")
        if isinstance(ds_map, Mapping):
            ds_entry = ds_map.get(dataset.name)
            if isinstance(ds_entry, Mapping) and ds_entry.get("top_k") is not None:
                try:
                    ds_top_k = int(ds_entry["top_k"])
                except (TypeError, ValueError):
                    pass
        effective_top_k = int(top_k) if top_k is not None else ds_top_k
        report = run_ir_benchmark_dataset(
            dataset,
            top_k=effective_top_k,
            retriever=retriever,
            embedder=embedder,
            config_path=config_path,
        )
        result = evaluate_report_thresholds(report, thresholds, dataset=dataset.name)
        result.details.update(
            {
                "kind": dataset.kind,
                "path": dataset.path,
                "num_cases": report.get("num_cases"),
                "top_k": report.get("top_k"),
            }
        )
        results.append(result)

    evaluated = [r for r in results if r.thresholds]
    ok = all(r.passed for r in evaluated) and bool(evaluated)
    return {
        "ok": ok,
        "skipped": False,
        "results": [r.to_dict() for r in results],
        "num_datasets": len(results),
        "num_evaluated": len(evaluated),
        "num_failed": sum(1 for r in evaluated if not r.passed),
    }
