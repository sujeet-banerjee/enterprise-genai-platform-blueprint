"""``python -m app.config_validate`` - validate config files (issue #46).

Exit codes:

- ``0`` - every config is valid,
- ``1`` - at least one config failed schema/secret validation,
- ``2`` - a config could not be read/parsed at all.

Usage::

    python -m app.config_validate                 # validate config/*.yaml
    python -m app.config_validate path/to/file.yaml
    python -m app.config_validate --json          # machine-readable output
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from core.config.validator import (
    ConfigError,
    ValidationIssue,
    validate_all,
    validate_config_file,
)

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _print_issues(issues: List[ValidationIssue]) -> None:
    for issue in issues:
        stream = sys.stderr
        print(f"  - {issue}", file=stream)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.config_validate",
        description="Validate GenAI platform config files against their schemas.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Config files to validate (default: all config/*.yaml with a schema).",
    )
    parser.add_argument(
        "--config-dir",
        default=str(DEFAULT_CONFIG_DIR),
        help="Directory used when no explicit paths are given.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    results: dict = {}
    hard_failure = False
    parse_failure = False

    if args.paths:
        for raw in args.paths:
            path = Path(raw)
            try:
                issues = validate_config_file(path)
            except ConfigError as exc:
                parse_failure = True
                results[str(path)] = {"error": str(exc)}
                continue
            hard = [i for i in issues if i.kind != "version-warning"]
            if hard:
                hard_failure = True
            results[str(path)] = {
                "valid": not hard,
                "issues": [str(i) for i in issues],
            }
    else:
        try:
            all_results = validate_all(Path(args.config_dir))
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not all_results:
            print(f"No schema-backed config files found in {args.config_dir}", file=sys.stderr)
            return 2
        for name, issues in all_results.items():
            hard = [i for i in issues if i.kind != "version-warning"]
            if hard:
                hard_failure = True
            results[name] = {"valid": not hard, "issues": [str(i) for i in issues]}

    if args.json:
        print(json.dumps({"ok": not (hard_failure or parse_failure), "results": results}, indent=2))
    else:
        for name, info in results.items():
            if "error" in info:
                print(f"FAIL {name}: {info['error']}", file=sys.stderr)
            elif info["valid"]:
                print(f"OK   {name}")
                for issue in info["issues"]:
                    print(f"       warning: {issue}", file=sys.stderr)
            else:
                print(f"FAIL {name}", file=sys.stderr)
                for issue in info["issues"]:
                    print(f"       {issue}", file=sys.stderr)

    if parse_failure:
        return 2
    return 1 if hard_failure else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
