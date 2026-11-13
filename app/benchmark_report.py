"""CLI for reproducible showcase benchmark reports (issue #196, Workstream K).

Examples::

    python -m app.benchmark_report --suite quick --config-dir deployment/smoke/config
    python -m app.benchmark_report --full --out docs/showcase/report.json \\
        --markdown docs/showcase/report.md --csv docs/showcase/report.csv
    python -m app.benchmark_report --check --out docs/showcase/report.json

Exit codes: 0 report produced/valid, 1 provenance/schema check failed,
2 invalid configuration or oversized sweep.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from core.evaluation.benchmarks import BenchmarkConfigError
from core.evaluation.config_sweep import DEFAULT_CONFIG_DIR, SweepConfigError
from core.evaluation.showcase_report import (
    ShowcaseReportError,
    build_report,
    check_report,
    load_report,
    write_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.benchmark_report",
        description="Run a config-driven showcase benchmark suite and write a reproducible report.",
    )
    parser.add_argument("--suite", help="suite name from config/benchmarks.yaml")
    parser.add_argument("--quick", action="store_true", help="use the quick CI suite")
    parser.add_argument("--full", action="store_true", help="use the full showcase suite")
    parser.add_argument("--config", help="benchmarks config path (default: config/benchmarks.yaml)")
    parser.add_argument(
        "--config-dir",
        default=str(DEFAULT_CONFIG_DIR),
        help="directory containing models/prompt/retrieval configs",
    )
    parser.add_argument(
        "--max-combinations",
        type=int,
        help="override the suite's max_combinations bound",
    )
    parser.add_argument("--seed", type=int, default=0, help="recorded run seed")
    parser.add_argument("--out", help="write the JSON report here")
    parser.add_argument("--markdown", help="write a Markdown report here")
    parser.add_argument("--csv", dest="csv_path", help="write a CSV report here")
    parser.add_argument(
        "--svg-dir",
        help="write Pareto and latency SVG plots here (named after --out)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate provenance/schema; reuses --out when it already exists",
    )
    parser.add_argument("--json", action="store_true", help="print the JSON report")
    return parser


def _ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _write_outputs(
    report: dict,
    *,
    out: Optional[str],
    markdown: Optional[str],
    csv_path: Optional[str],
    svg_dir: Optional[str],
) -> None:
    if out:
        _ensure_parent(out)
    if markdown:
        _ensure_parent(markdown)
    if csv_path:
        _ensure_parent(csv_path)
    write_report(report, out=out, markdown=markdown, csv_path=csv_path)
    if svg_dir:
        from core.evaluation.benchmark_plots import plot_stem_for, write_plots

        write_plots(report, svg_dir, stem=plot_stem_for(out))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.quick and args.full:
        parser.error("--quick and --full are mutually exclusive")
    if args.max_combinations is not None and args.max_combinations <= 0:
        parser.error("--max-combinations must be a positive integer")

    suite_name = "quick" if args.quick else "showcase" if args.full else args.suite

    try:
        if args.check and args.out and Path(args.out).exists():
            report = load_report(args.out)
        else:
            report = build_report(
                suite_name=suite_name,
                config_path=args.config,
                config_dir=args.config_dir,
                max_combinations=args.max_combinations,
                seed=args.seed,
            )
            _write_outputs(
                report,
                out=args.out,
                markdown=args.markdown,
                csv_path=args.csv_path,
                svg_dir=args.svg_dir,
            )

        problems = check_report(report)
        if args.json:
            print(json.dumps(report, indent=2))
        elif not args.check:
            suite = report.get("suite") or {}
            print(
                f"report: suite={suite.get('suite')} "
                f"datasets={len(report.get('datasets') or [])} "
                f"combinations={report.get('num_combinations')} "
                f"pareto={len(report.get('pareto_frontier') or [])}"
            )
        if args.check:
            if problems:
                for problem in problems:
                    print(f"CHECK FAILED: {problem}", file=sys.stderr)
                return 1
            print("CHECK OK")
        return 0
    except (ShowcaseReportError, BenchmarkConfigError, SweepConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
