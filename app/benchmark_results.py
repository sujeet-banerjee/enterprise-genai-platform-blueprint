"""CLI to validate committed benchmark results and regenerate the results index.

Examples::

    python -m app.benchmark_results
    python -m app.benchmark_results --check
    python -m app.benchmark_results --results-dir docs/benchmarks/results --json

Exit codes: 0 index written/valid, 1 integrity problem or stale index,
2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from core.evaluation.benchmark_results import (
    discover_results,
    index_problems,
    render_results_index,
)

DEFAULT_RESULTS_DIR = "docs/benchmarks/results"
DEFAULT_INDEX = "docs/benchmarks/README.md"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.benchmark_results",
        description="Validate published benchmark results and regenerate docs/benchmarks/README.md.",
    )
    parser.add_argument(
        "--results-dir",
        default=DEFAULT_RESULTS_DIR,
        help=f"directory of committed JSON reports (default: {DEFAULT_RESULTS_DIR})",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_INDEX,
        help=f"generated index path (default: {DEFAULT_INDEX})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify integrity and that --out matches the reports; write nothing",
    )
    parser.add_argument("--json", action="store_true", help="print a machine-readable summary")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        discovered = discover_results(args.results_dir)
        rendered = render_results_index(discovered)
        problems = index_problems(discovered)

        if args.json:
            print(
                json.dumps(
                    {
                        "results_dir": args.results_dir,
                        "index": args.out,
                        "entries": [entry.stem for entry in discovered["entries"]],
                        "orphans": [Path(item).name for item in discovered["orphans"]],
                        "problems": problems,
                        "ok": not problems,
                    },
                    indent=2,
                )
            )

        if args.check:
            for problem in problems:
                print(f"CHECK FAILED: {problem}", file=sys.stderr)
            if problems:
                return 1
            target = Path(args.out)
            if not target.exists():
                print(f"CHECK FAILED: index is missing: {target}", file=sys.stderr)
                return 1
            if target.read_text(encoding="utf-8") != rendered:
                print(
                    f"CHECK FAILED: {target} is out of date; rerun without --check",
                    file=sys.stderr,
                )
                return 1
            print("CHECK OK")
            return 0

        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(f"wrote {target} ({len(discovered['entries'])} results)")
        return 0
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
