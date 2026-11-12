"""``python -m app.eval_gate`` - CI regression gates for eval (issue #125).

Exit codes:

- ``0`` - gates passed, or regression gating is disabled (safe/no-op default),
- ``1`` - at least one evaluated metric regressed below its configured threshold,
- ``2`` - the gate could not run (config/read/discovery error).

Usage::

    python -m app.eval_gate                 # uses config/eval_datasets.yaml
    python -m app.eval_gate --config-dir config
    python -m app.eval_gate --dataset data/benchmark.json --threshold context_recall=0.5
    python -m app.eval_gate --report report.json --threshold max_cost_per_request_usd=0.01
    python -m app.eval_gate --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.evaluation.eval_datasets import EvalDatasetValidationError, load_eval_dataset
from core.evaluation.regression_gate import (
    DEFAULT_CONFIG_DIR,
    configured_regression_thresholds,
    evaluate_report_thresholds,
    run_ir_benchmark_dataset,
    run_regression_gates,
)


def _parse_threshold(arg: str) -> Dict[str, float]:
    if "=" not in arg:
        raise argparse.ArgumentTypeError(f"threshold must be metric=value, got: {arg}")
    metric, value = arg.split("=", 1)
    try:
        return {metric.strip(): float(value)}
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"threshold value must be numeric: {arg}") from exc


def _load_reports(path: str) -> List[Dict[str, Any]]:
    """Load one JSON report object, or a JSON list of report objects."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    raise ValueError("report must be a JSON object or a list of objects")


def _print_summary(summary: Dict[str, object]) -> None:
    if summary.get("skipped"):
        print(f"SKIP {summary.get('reason', 'regression gates disabled')}")
        return
    results = summary.get("results") or []
    if not isinstance(results, list):
        results = []
    for result in results:
        if not isinstance(result, dict):
            continue
        status = "PASS" if result.get("passed") else "FAIL"
        name = result.get("dataset", "dataset")
        print(f"{status} {name}")
        for failure in result.get("failures") or []:
            print(f"       {failure}", file=sys.stderr)
        if result.get("details", {}).get("skipped"):
            print(f"       skipped: {result['details'].get('reason', 'no thresholds')}")
    totals = (
        f"datasets={summary.get('num_datasets', 0)} "
        f"evaluated={summary.get('num_evaluated', 0)} "
        f"failed={summary.get('num_failed', 0)}"
    )
    print(f"RESULT {'OK' if summary.get('ok') else 'FAIL'} ({totals})")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval_gate",
        description="Run evaluation regression gates (blocks on threshold regressions).",
    )
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR))
    parser.add_argument("--config-path", default=None, help="Model/retriever config path.")
    parser.add_argument("--dataset", action="append", default=[], help="Dataset file path(s).")
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        type=_parse_threshold,
        help="Metric threshold, e.g. context_recall=0.8 (repeatable).",
    )
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument(
        "--report",
        default=None,
        help="JSON experiment/eval report to gate (quality + cost + latency).",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run gates even when config disables regression (requires --dataset/--threshold).",
    )
    args = parser.parse_args(argv)

    thresholds: Dict[str, float] = {}
    for item in args.threshold:
        thresholds.update(item)

    try:
        if args.report:
            # Gate a pre-computed experiment/eval report (quality + cost + latency).
            reports = _load_reports(args.report)
            gate_thresholds: Dict[str, Any] = dict(thresholds)
            if not gate_thresholds:
                gate_thresholds = configured_regression_thresholds(args.config_dir)
            if not gate_thresholds:
                raise EvalDatasetValidationError(
                    "--report requires --threshold or regression.thresholds in eval_datasets.yaml"
                )
            results = []
            for index, report in enumerate(reports):
                name = str(
                    report.get("dataset")
                    or report.get("name")
                    or f"{Path(args.report).stem}-{index}"
                )
                results.append(
                    evaluate_report_thresholds(report, gate_thresholds, dataset=name).to_dict()
                )
            evaluated = [r for r in results if r.get("thresholds")]
            summary = {
                "ok": all(r.get("passed") for r in evaluated) and bool(evaluated),
                "skipped": False,
                "results": results,
                "num_datasets": len(results),
                "num_evaluated": len(evaluated),
                "num_failed": sum(1 for r in evaluated if not r.get("passed")),
            }
        elif args.dataset or thresholds:
            # Explicit invocation: evaluate given datasets against given thresholds.
            datasets = [load_eval_dataset(path) for path in args.dataset] or []
            if not datasets:
                raise EvalDatasetValidationError("--threshold/--dataset requires at least --dataset")
            if not thresholds:
                raise EvalDatasetValidationError("--dataset requires --threshold metric=value")
            results = []
            for ds in datasets:
                report = run_ir_benchmark_dataset(
                    ds, top_k=args.top_k or 3, config_path=args.config_path
                )
                result = evaluate_report_thresholds(report, thresholds, dataset=ds.name)
                result.details.update({"kind": ds.kind, "path": ds.path})
                results.append(result.to_dict())
            evaluated = [r for r in results if r.get("thresholds")]
            summary = {
                "ok": all(r.get("passed") for r in evaluated) and bool(evaluated),
                "skipped": False,
                "results": results,
                "num_datasets": len(results),
                "num_evaluated": len(evaluated),
                "num_failed": sum(1 for r in evaluated if not r.get("passed")),
            }
        else:
            summary = run_regression_gates(
                config_dir=args.config_dir,
                config_path=args.config_path,
                top_k=args.top_k,
                enabled_override=True if args.force else None,
            )
    except EvalDatasetValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"eval gate error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_summary(summary)

    if summary.get("skipped"):
        return 0
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
