"""Config-driven showcase benchmark suites (issue #195, Workstream K).

Loads ``config/benchmarks.yaml``, resolves a named suite and materialises its
datasets through :mod:`core.evaluation.eval_datasets`. The module is
dependency-light and does not import ``app.*`` or ``ui.*`` so the report
generator (issue #196) and CI can reuse it.

Config shape::

    enabled: false
    default_suite: showcase
    datasets:
      enterprise-it: {path: benchmarks/data/enterprise-it/benchmark.json}
    suites:
      showcase:
        datasets: [enterprise-it]
        max_cases: 0            # 0 = all cases (per dataset)
        max_combinations: 24
        parameters: {top_k: [3, 5], reranker: [true, false]}
        objective: {quality: context_recall, cost_budget_usd: 0.01}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from core.evaluation.eval_datasets import EvalDataset, load_eval_dataset

DEFAULT_BENCHMARKS_CONFIG = "config/benchmarks.yaml"


class BenchmarkConfigError(ValueError):
    """Raised when a benchmark config or suite is invalid."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(path: Optional[str]) -> Path:
    target = Path(path) if path else _repo_root() / DEFAULT_BENCHMARKS_CONFIG
    if not target.is_absolute():
        target = _repo_root() / target
    return target


def load_benchmarks_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load ``config/benchmarks.yaml`` (or an explicit path)."""
    target = _resolve_path(path)
    if not target.exists():
        raise BenchmarkConfigError(f"Benchmark config not found: {target}")
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:  # pragma: no cover - yaml reports details
        raise BenchmarkConfigError(f"{target}: invalid YAML: {exc}") from exc
    if not isinstance(data, Mapping):
        raise BenchmarkConfigError(f"{target}: config must be a mapping")
    return dict(data)


def is_enabled(config: Mapping[str, Any]) -> bool:
    return bool(config.get("enabled", False))


def _datasets(config: Mapping[str, Any]) -> Mapping[str, Any]:
    declared = config.get("datasets") or {}
    if not isinstance(declared, Mapping):
        raise BenchmarkConfigError("`datasets` must be a mapping of name -> path/spec")
    return declared


def resolve_suite(
    config: Mapping[str, Any],
    suite_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve and validate a suite, returning a normalized mapping."""
    suites = config.get("suites") or {}
    if not isinstance(suites, Mapping) or not suites:
        raise BenchmarkConfigError("No `suites` declared")
    name = suite_name or config.get("default_suite")
    if not name:
        raise BenchmarkConfigError("No suite name given and no `default_suite` set")
    if name not in suites:
        available = ", ".join(sorted(str(k) for k in suites))
        raise BenchmarkConfigError(f"Unknown suite '{name}'; available: {available}")
    raw = suites[name]
    if not isinstance(raw, Mapping):
        raise BenchmarkConfigError(f"Suite '{name}' must be a mapping")

    datasets = raw.get("datasets") or []
    if not isinstance(datasets, list) or not datasets:
        raise BenchmarkConfigError(f"Suite '{name}' must declare at least one dataset")
    datasets = [str(item) for item in datasets]
    if len(datasets) != len(set(datasets)):
        raise BenchmarkConfigError(f"Suite '{name}' lists a dataset more than once")
    declared = _datasets(config)
    unknown = [item for item in datasets if item not in declared]
    if unknown:
        raise BenchmarkConfigError(
            f"Suite '{name}' references unknown dataset(s): {', '.join(unknown)}"
        )

    max_cases = raw.get("max_cases", 0)
    if not isinstance(max_cases, int) or isinstance(max_cases, bool) or max_cases < 0:
        raise BenchmarkConfigError(f"Suite '{name}' max_cases must be a non-negative integer")
    max_combinations = raw.get("max_combinations")
    if max_combinations is not None and (
        not isinstance(max_combinations, int)
        or isinstance(max_combinations, bool)
        or max_combinations <= 0
    ):
        raise BenchmarkConfigError(
            f"Suite '{name}' max_combinations must be a positive integer"
        )

    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise BenchmarkConfigError(f"Suite '{name}' parameters must be a mapping")
    objective = raw.get("objective") or {}
    if not isinstance(objective, Mapping):
        raise BenchmarkConfigError(f"Suite '{name}' objective must be a mapping")

    return {
        "name": str(name),
        "description": str(raw.get("description") or ""),
        "datasets": datasets,
        "max_cases": max_cases,
        "max_combinations": max_combinations,
        "parameters": {str(k): list(v) if isinstance(v, list) else v for k, v in parameters.items()},
        "objective": dict(objective),
    }


def resolve_dataset_specs(
    config: Mapping[str, Any],
    suite: Mapping[str, Any],
) -> List[Tuple[str, str]]:
    """Return ``(dataset_name, path)`` pairs for a resolved suite."""
    declared = _datasets(config)
    specs: List[Tuple[str, str]] = []
    for name in suite.get("datasets") or []:
        raw = declared.get(name)
        path: Optional[str]
        if isinstance(raw, str):
            path = raw
        elif isinstance(raw, Mapping):
            path = raw.get("path")
        else:
            path = None
        if not path:
            raise BenchmarkConfigError(f"Dataset '{name}' requires a `path`")
        specs.append((str(name), str(path)))
    return specs


def load_suite_datasets(
    config: Mapping[str, Any],
    suite: Mapping[str, Any],
) -> List[EvalDataset]:
    """Load a suite's datasets, applying the deterministic ``max_cases`` cap."""
    max_cases = int(suite.get("max_cases") or 0)
    loaded: List[EvalDataset] = []
    for name, path in resolve_dataset_specs(config, suite):
        dataset = load_eval_dataset(path, name=name)
        if dataset.name != name:
            dataset.metadata.setdefault("display_name", dataset.name)
            dataset.name = name
        if max_cases > 0 and len(dataset.cases) > max_cases:
            dataset = EvalDataset(
                name=dataset.name,
                path=dataset.path,
                format=dataset.format,
                cases=list(dataset.cases[:max_cases]),
                docs=dataset.docs,
                metadata=dict(dataset.metadata),
            )
        loaded.append(dataset)
    return loaded


def load_suite(
    suite_name: Optional[str] = None,
    *,
    config_path: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[EvalDataset]]:
    """Convenience wrapper: load config, resolve a suite and load its datasets."""
    config = load_benchmarks_config(config_path)
    suite = resolve_suite(config, suite_name)
    return suite, load_suite_datasets(config, suite)


def suite_summary(suite: Mapping[str, Any], datasets: Sequence[EvalDataset]) -> Dict[str, Any]:
    """Small JSON-friendly summary used by tests and the report generator."""
    return {
        "suite": suite.get("name"),
        "description": suite.get("description"),
        "max_cases": suite.get("max_cases"),
        "max_combinations": suite.get("max_combinations"),
        "parameters": dict(suite.get("parameters") or {}),
        "objective": dict(suite.get("objective") or {}),
        "datasets": [
            {
                "name": dataset.name,
                "domain": dataset.metadata.get("domain"),
                "num_docs": len(dataset.docs),
                "num_cases": len(dataset.cases),
            }
            for dataset in datasets
        ],
    }
