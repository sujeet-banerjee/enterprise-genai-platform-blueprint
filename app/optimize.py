"""``python -m app.optimize`` - config-driven cost/quality/latency sweep (#181).

Exit codes:

- ``0`` - sweep ran (or optimization is disabled), and ``--gate`` passed if used,
- ``1`` - ``--gate`` failed on the recommended combination,
- ``2`` - the sweep could not run (config/dataset/limit error).

Usage::

    python -m app.optimize --config config/optimization.yaml
    python -m app.optimize --config config/optimization.yaml --json
    python -m app.optimize --config config/optimization.yaml --gate
    python -m app.optimize --config config/optimization.yaml --gate \
        --threshold context_recall=0.8 --threshold max_cost_per_request_usd=0.01
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Mapping, Optional

from core.evaluation.config_sweep import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    SweepConfigError,
    gate_recommended,
    load_optimization_config,
    run_sweep,
)
from core.evaluation.regression_gate import configured_regression_thresholds


def _parse_threshold(arg: str) -> Dict[str, float]:
    if "=" not in arg:
        raise argparse.ArgumentTypeError(f"threshold must be metric=value, got: {arg}")
    metric, value = arg.split("=", 1)
    try:
        return {metric.strip(): float(value)}
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"threshold value must be numeric: {arg}") from exc


def _objective_thresholds(config: Mapping[str, Any]) -> Dict[str, float]:
    objective = config.get("objective")
    if not isinstance(objective, Mapping):
        return {}
    out: Dict[str, float] = {}
    quality = objective.get("quality")
    min_quality = objective.get("min_quality")
    if quality is not None and min_quality is not None:
        try:
            out[str(quality)] = float(min_quality)
        except (TypeError, ValueError):
            pass
    for key, metric in (
        ("cost_budget_usd", "max_cost_per_request_usd"),
        ("latency_budget_ms", "max_p95_latency_ms"),
    ):
        value = objective.get(key)
        if value is None:
            continue
        try:
            out[metric] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _resolve_thresholds(
    explicit: Mapping[str, float],
    config: Mapping[str, Any],
    config_dir: str,
) -> Dict[str, float]:
    if explicit:
        return dict(explicit)
    derived = _objective_thresholds(config)
    if derived:
        return derived
    return configured_regression_thresholds(config_dir)


def _format_row(row: Mapping[str, Any]) -> str:
    params = ", ".join(f"{key}={value}" for key, value in sorted(row["parameters"].items()))
    return (
        f"  {row['combination_id']}  {params or '(default)'}  "
        f"quality={float(row['quality']):.4f} "
        f"cost=${float(row['cost_usd']):.6f} "
        f"latency={float(row['latency_ms']):.1f}ms "
        f"p95={float(row['p95_latency_ms']):.1f}ms"
    )


def _print_summary(summary: Mapping[str, Any], gate: Optional[Mapping[str, Any]]) -> None:
    if summary.get("skipped"):
        print(f"SKIP {summary.get('reason', 'optimization disabled')}")
        return
    dataset = summary.get("dataset") or {}
    print(
        f"SWEEP dataset={dataset.get('name', 'dataset')} "
        f"combinations={summary.get('num_combinations', 0)} "
        f"frontier={len(summary.get('pareto_frontier') or [])}"
    )
    for row in summary.get("rows") or []:
        marker = " *" if row.get("combination_id") in (summary.get("pareto_frontier") or []) else ""
        print(_format_row(row) + marker)
    recommended = summary.get("recommended")
    if isinstance(recommended, Mapping):
        print(
            f"RECOMMENDED {recommended['combination_id']} "
            f"quality={float(recommended['quality']):.4f} "
            f"cost=${float(recommended['cost_usd']):.6f} "
            f"latency={float(recommended['latency_ms']):.1f}ms "
            f"within_budget={recommended.get('within_budget')}"
        )
        print("OVERLAY")
        print(json.dumps(recommended.get("config_overlay") or {}, indent=2, sort_keys=True))
    if isinstance(gate, Mapping):
        status = "PASS" if gate.get("passed") else "FAIL"
        print(f"GATE {status}")
        for failure in gate.get("failures") or []:
            print(f"       {failure}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.optimize",
        description="Sweep config levers and report the cost/quality/latency Pareto frontier.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR))
    parser.add_argument(
        "--max-combinations",
        type=int,
        default=None,
        help="Override optimization.max_combinations (safety bound).",
    )
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        type=_parse_threshold,
        help="Gate threshold, e.g. context_recall=0.8 (repeatable; with --gate).",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Gate the recommended combination with the #180 budget-aware gate.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = load_optimization_config(args.config)
        summary = run_sweep(
            config,
            config_dir=args.config_dir,
            max_combinations=args.max_combinations,
        )
        gate: Optional[Dict[str, Any]] = None
        if args.gate and not summary.get("skipped"):
            explicit: Dict[str, float] = {}
            for item in args.threshold:
                explicit.update(item)
            thresholds = _resolve_thresholds(explicit, config, args.config_dir)
            if not thresholds:
                raise SweepConfigError(
                    "--gate requires --threshold, objective budgets/min_quality, "
                    "or regression.thresholds in eval_datasets.yaml"
                )
            gate = gate_recommended(summary, thresholds)
            if gate is None:
                raise SweepConfigError("sweep produced no recommendation to gate")
    except SweepConfigError as exc:
        print(f"optimize error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"optimize error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"optimize error: {exc}", file=sys.stderr)
        return 2

    payload: Dict[str, Any] = dict(summary)
    if gate is not None:
        payload["gate"] = gate

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_summary(summary, gate)

    if gate is not None and not gate.get("passed"):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
