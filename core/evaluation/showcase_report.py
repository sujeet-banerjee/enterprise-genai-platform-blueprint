"""Reproducible showcase benchmark report generator (issue #196, Workstream K).

Runs a config-driven benchmark suite (issue #195) across a bounded parameter
matrix using :class:`core.services.experiment_runner.ExperimentRunner`, then
reports retrieval quality (precision, recall, MRR, nDCG), cost and latency with
a Pareto frontier and a provenance block.

The report is the source of truth for published numbers: Markdown and CSV are
rendered from the JSON report, never hand-typed. ``--quick`` uses the dummy
providers from ``deployment/smoke/config`` for CI; full runs use local models.

No ``app.*``/``ui.*`` imports at module import time so the CLI and tests can use
the same code path.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from core.evaluation.benchmarks import (
    load_benchmarks_config,
    load_suite_datasets,
    resolve_suite,
    suite_summary,
)
from core.evaluation.config_sweep import (
    DEFAULT_CONFIG_DIR,
    SweepConfigError,
    _default_runner,
    _default_top_k,
    _prepare_docs,
    _run_combo,
    expand_combinations,
    normalize_parameters,
    pareto_frontier,
    recommend_overlay,
)
from core.evaluation.eval_datasets import EvalDataset

REPORT_SCHEMA_VERSION = "1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]


class ShowcaseReportError(ValueError):
    """Raised when a showcase report cannot be produced or validated."""


def _resolve_repo_path(path: Optional[str]) -> Optional[Path]:
    if not path:
        return None
    target = Path(path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    return target


def _sha256_file(path: Optional[str]) -> str:
    target = _resolve_repo_path(path)
    if target is None or not target.exists():
        return ""
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _read_config_text(path: Optional[str]) -> str:
    """Return the raw config text so a report can embed a verifiable snapshot."""
    target = _resolve_repo_path(path or "config/benchmarks.yaml")
    if target is None or not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def _git_sha() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        return output.decode("utf-8").strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _package_versions() -> Dict[str, str]:
    from importlib import metadata

    versions: Dict[str, str] = {}
    for name in ("torch", "sentence-transformers", "numpy", "pydantic", "fastapi"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions


def collect_provenance(
    config_path: Optional[str],
    datasets: Sequence[EvalDataset],
    *,
    seed: int = 0,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a provenance block for a report.

    ``config_snapshot`` embeds the exact benchmark config text so a published
    result can be verified against ``config_sha256`` even after the live config
    changes (see ``core.evaluation.benchmark_results``).
    """
    config_text = _read_config_text(config_path)
    config_sha = hashlib.sha256(config_text.encode("utf-8")).hexdigest() if config_text else ""
    return {
        "git_sha": _git_sha(),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "seed": int(seed),
        "config_path": str(config_path or "config/benchmarks.yaml"),
        "config_sha256": config_sha,
        "config_snapshot": config_text,
        "packages": _package_versions(),
    }


def _repo_relative(path: Optional[str]) -> str:
    """Return a repo-relative path when possible so reports stay portable."""
    if not path:
        return ""
    target = Path(path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    try:
        return target.resolve().relative_to(REPO_ROOT).as_posix()
    except (OSError, ValueError):
        return str(path)


def _dataset_provenance(datasets: Sequence[EvalDataset]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for dataset in datasets:
        rows.append(
            {
                "name": dataset.name,
                "display_name": dataset.metadata.get("display_name") or dataset.name,
                "path": _repo_relative(dataset.path),
                "sha256": _sha256_file(dataset.path),
                "num_docs": len(dataset.docs),
                "num_cases": len(dataset.cases),
                "domain": dataset.metadata.get("domain"),
            }
        )
    return rows


def _weighted_mean(pairs: Sequence[Tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in pairs) / total_weight


def _aggregate_rows(dataset_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-dataset results for one parameter combination."""
    metric_names: List[str] = []
    for row in dataset_rows:
        for name in (row.get("metrics") or {}):
            if name not in metric_names:
                metric_names.append(name)
    metrics: Dict[str, float] = {}
    for name in metric_names:
        pairs = []
        for row in dataset_rows:
            value = (row.get("metrics") or {}).get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                pairs.append((float(value), float(row.get("num_cases") or 0)))
        metrics[name] = _weighted_mean(pairs)

    num_cases = sum(int(row.get("num_cases") or 0) for row in dataset_rows)
    cost_pairs = [
        (float(row.get("cost_usd") or 0.0), float(row.get("num_cases") or 0))
        for row in dataset_rows
    ]
    latency_pairs = [
        (float(row.get("latency_ms") or 0.0), float(row.get("num_cases") or 0))
        for row in dataset_rows
    ]
    return {
        "metrics": metrics,
        "num_cases": num_cases,
        "cost_usd": _weighted_mean(cost_pairs),
        "total_cost_usd": sum(float(row.get("total_cost_usd") or 0.0) for row in dataset_rows),
        "latency_ms": _weighted_mean(latency_pairs),
        "p95_latency_ms": max(
            (float(row.get("p95_latency_ms") or 0.0) for row in dataset_rows),
            default=0.0,
        ),
    }


def run_suite_report(
    suite: Mapping[str, Any],
    datasets: Sequence[EvalDataset],
    *,
    config_dir: Union[str, Path] = DEFAULT_CONFIG_DIR,
    runner: Optional[Any] = None,
    max_combinations: Optional[int] = None,
    seed: int = 0,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a suite across its bounded matrix and return a JSON report."""
    if not datasets:
        raise ShowcaseReportError("suite has no datasets")
    parameters = normalize_parameters(suite.get("parameters"))
    if not parameters:
        raise ShowcaseReportError("suite has no parameters to sweep")

    limit = max_combinations or suite.get("max_combinations")
    if limit is None:
        limit = 25
    try:
        combinations = expand_combinations(parameters, int(limit))
    except SweepConfigError as exc:
        raise ShowcaseReportError(str(exc)) from exc

    active_runner = runner or _default_runner(config_dir)
    base_top_k = _default_top_k(config_dir)
    objective = dict(suite.get("objective") or {})
    quality_metric = str(objective.get("quality") or "context_recall")

    rows: List[Dict[str, Any]] = []
    for index, combination in enumerate(combinations, start=1):
        dataset_rows: List[Dict[str, Any]] = []
        for dataset in datasets:
            result = _run_combo(
                active_runner,
                dataset,
                combination,
                _prepare_docs(dataset),
                base_top_k,
            )
            dataset_rows.append(
                {
                    "dataset": dataset.name,
                    "num_cases": result["num_cases"],
                    "metrics": dict(result["metrics"]),
                    "cost_usd": result["cost_usd"],
                    "total_cost_usd": result["total_cost_usd"],
                    "latency_ms": result["latency_ms"],
                    "p95_latency_ms": result["p95_latency_ms"],
                }
            )
        aggregate = _aggregate_rows(dataset_rows)
        rows.append(
            {
                "combination_id": f"combo-{index:04d}",
                "parameters": dict(combination),
                "metrics": aggregate["metrics"],
                "quality": float(aggregate["metrics"].get(quality_metric, 0.0)),
                "quality_metric": quality_metric,
                "cost_usd": aggregate["cost_usd"],
                "total_cost_usd": aggregate["total_cost_usd"],
                "latency_ms": aggregate["latency_ms"],
                "p95_latency_ms": aggregate["p95_latency_ms"],
                "num_cases": aggregate["num_cases"],
                "datasets": dataset_rows,
            }
        )

    frontier = pareto_frontier(rows)
    recommended = recommend_overlay(frontier, objective)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite": suite_summary(suite, datasets),
        "provenance": collect_provenance(config_path, datasets, seed=seed),
        "datasets": _dataset_provenance(datasets),
        "parameters": parameters,
        "max_combinations": int(limit),
        "num_combinations": len(rows),
        "rows": rows,
        "pareto_frontier": [row["combination_id"] for row in frontier],
        "frontier": frontier,
        "recommended": recommended,
    }


def _format_parameters(parameters: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(parameters.items()))


def _metric(row: Mapping[str, Any], name: str) -> float:
    value = (row.get("metrics") or {}).get(name)
    return float(value) if isinstance(value, (int, float)) else 0.0


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a report as Markdown (all numbers come from the report)."""
    provenance = report.get("provenance") or {}
    suite = report.get("suite") or {}
    rows = report.get("rows") or []
    frontier = set(report.get("pareto_frontier") or [])
    quality_metric = (
        str((rows[0] or {}).get("quality_metric") or "context_recall")
        if rows
        else "context_recall"
    )

    lines: List[str] = [
        f"# Showcase benchmark report: {suite.get('suite', 'suite')}",
        "",
        "> Reference CPU numbers produced by `python -m app.benchmark_report`; "
        "not production benchmarks.",
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Git commit | `{provenance.get('git_sha', '')}` |",
        f"| Generated (UTC) | {provenance.get('timestamp', '')} |",
        f"| Platform | {provenance.get('platform', '')} |",
        f"| Python | {provenance.get('python_version', '')} |",
        f"| Seed | {provenance.get('seed', '')} |",
        f"| Config SHA-256 | `{provenance.get('config_sha256', '')}` |",
        "",
        "## Datasets",
        "",
        "| Dataset | Docs | Cases | SHA-256 |",
        "| --- | ---: | ---: | --- |",
    ]
    for dataset in report.get("datasets") or []:
        lines.append(
            f"| {dataset.get('name')} | {dataset.get('num_docs')} | "
            f"{dataset.get('num_cases')} | `{dataset.get('sha256')}` |"
        )

    lines += [
        "",
        "## Results",
        "",
        f"Quality metric: `{quality_metric}`. `*` marks the Pareto frontier.",
        "",
        "| Combination | Parameters | Quality | Precision | Recall | MRR | nDCG | "
        "Cost/request | Latency | p95 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        marker = " *" if row.get("combination_id") in frontier else ""
        lines.append(
            f"| {row.get('combination_id')}{marker} | "
            f"{_format_parameters(row.get('parameters') or {})} | "
            f"{float(row.get('quality') or 0.0):.4f} | {_metric(row, 'context_precision'):.4f} | "
            f"{_metric(row, 'context_recall'):.4f} | {_metric(row, 'mrr'):.4f} | "
            f"{_metric(row, 'ndcg'):.4f} | ${float(row.get('cost_usd') or 0.0):.6f} | "
            f"{float(row.get('latency_ms') or 0.0):.1f} ms | "
            f"{float(row.get('p95_latency_ms') or 0.0):.1f} ms |"
        )

    recommended = report.get("recommended")
    if isinstance(recommended, Mapping):
        lines += [
            "",
            "## Recommended configuration",
            "",
            f"`{recommended.get('combination_id')}` - quality "
            f"{float(recommended.get('quality') or 0.0):.4f}, cost "
            f"${float(recommended.get('cost_usd') or 0.0):.6f}, latency "
            f"{float(recommended.get('latency_ms') or 0.0):.1f} ms, "
            f"within budget: {recommended.get('within_budget')}.",
            "",
            "```json",
            json.dumps(recommended.get("config_overlay") or {}, indent=2, sort_keys=True),
            "```",
        ]
    lines.append("")
    return "\n".join(lines)


def render_csv(report: Mapping[str, Any]) -> str:
    """Render one row per combination as CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "combination_id",
            "parameters",
            "quality",
            "quality_metric",
            "context_precision",
            "context_recall",
            "mrr",
            "ndcg",
            "cost_usd",
            "total_cost_usd",
            "latency_ms",
            "p95_latency_ms",
            "num_cases",
            "pareto",
        ]
    )
    frontier = set(report.get("pareto_frontier") or [])
    for row in report.get("rows") or []:
        writer.writerow(
            [
                row.get("combination_id"),
                _format_parameters(row.get("parameters") or {}),
                row.get("quality"),
                row.get("quality_metric"),
                _metric(row, "context_precision"),
                _metric(row, "context_recall"),
                _metric(row, "mrr"),
                _metric(row, "ndcg"),
                row.get("cost_usd"),
                row.get("total_cost_usd"),
                row.get("latency_ms"),
                row.get("p95_latency_ms"),
                row.get("num_cases"),
                row.get("combination_id") in frontier,
            ]
        )
    return buffer.getvalue()


def check_report(report: Mapping[str, Any]) -> List[str]:
    """Return a list of provenance/schema problems (empty when complete)."""
    errors: List[str] = []
    if not isinstance(report, Mapping):
        return ["report must be an object"]
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {REPORT_SCHEMA_VERSION!r}, "
            f"got {report.get('schema_version')!r}"
        )

    provenance = report.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("missing provenance block")
    else:
        for key in (
            "git_sha",
            "timestamp",
            "platform",
            "python_version",
            "seed",
            "config_sha256",
        ):
            value = provenance.get(key)
            if value is None or value == "" or value == "unknown":
                errors.append(f"provenance.{key} is missing")
        if not isinstance(provenance.get("seed"), int):
            errors.append("provenance.seed must be an integer")

    datasets = report.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        errors.append("datasets must be a non-empty list")
    else:
        for index, dataset in enumerate(datasets):
            if not isinstance(dataset, Mapping):
                errors.append(f"datasets[{index}] must be an object")
                continue
            for key in ("name", "path", "sha256", "num_docs", "num_cases"):
                if dataset.get(key) in (None, ""):
                    errors.append(f"datasets[{index}].{key} is missing")

    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
    else:
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                errors.append(f"rows[{index}] must be an object")
                continue
            for key in ("combination_id", "parameters", "metrics", "cost_usd", "latency_ms"):
                if key not in row:
                    errors.append(f"rows[{index}].{key} is missing")
    return errors


def load_report(path: Union[str, Path]) -> Dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise ShowcaseReportError(f"report not found: {target}")
    with open(target, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ShowcaseReportError(f"{target}: invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ShowcaseReportError(f"{target}: report must be a JSON object")
    return data


def write_report(
    report: Mapping[str, Any],
    *,
    out: Optional[Union[str, Path]] = None,
    markdown: Optional[Union[str, Path]] = None,
    csv_path: Optional[Union[str, Path]] = None,
) -> None:
    if out:
        Path(out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if markdown:
        Path(markdown).write_text(render_markdown(report), encoding="utf-8")
    if csv_path:
        Path(csv_path).write_text(render_csv(report), encoding="utf-8")


def build_report(
    *,
    suite_name: Optional[str] = None,
    config_path: Optional[str] = None,
    config_dir: Union[str, Path] = DEFAULT_CONFIG_DIR,
    max_combinations: Optional[int] = None,
    seed: int = 0,
    runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """Load a suite and produce a report (convenience for CLI/tests)."""
    config = load_benchmarks_config(config_path)
    suite = resolve_suite(config, suite_name)
    datasets = load_suite_datasets(config, suite)
    return run_suite_report(
        suite,
        datasets,
        config_dir=config_dir,
        runner=runner,
        max_combinations=max_combinations,
        seed=seed,
        config_path=config_path,
    )
