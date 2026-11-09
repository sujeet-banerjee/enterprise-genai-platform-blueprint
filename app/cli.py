"""``genai`` command line interface (issue #128, Workstream L).

Scaffolds a runnable project from a golden path template (issue #127) and
validates config sets with the same schema stack the server uses at startup.

Usage::

    genai init my-app                      # recommended path (rag-assistant)
    genai init my-app --template local-demo
    genai init my-app --template governed-enterprise --force
    genai templates                        # list available golden paths
    genai validate my-app/config           # validate a generated config set

Exit codes: ``0`` success, ``1`` usage/scaffolding/validation failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from core.config.validator import (
    ConfigError,
    ValidationIssue,
    validate_all,
    validate_config_file,
)

REPO_BASE = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_BASE / "deployment" / "templates"
DATA_DIR = REPO_BASE / "data"

REQUIRED_TEMPLATE_FILES = ("models.yaml", "prompt_config.yaml", "retrieval.yaml")
DEFAULT_TEMPLATE = "rag-assistant"
DEFAULT_CONFIG_NAME = "config"


class ScaffoldError(RuntimeError):
    """Raised when a scaffold cannot be produced (usage or filesystem problem)."""


@dataclass
class ScaffoldResult:
    target: Path
    template: str
    config_dir: Path
    template_source: Path
    files: List[Path] = field(default_factory=list)
    data_files: List[Path] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "target": str(self.target),
            "template": self.template,
            "config_dir": str(self.config_dir),
            "template_source": str(self.template_source),
            "files": [str(path) for path in self.files],
            "data_files": [str(path) for path in self.data_files],
        }


def available_templates(templates_dir: Path = TEMPLATES_DIR) -> Dict[str, Path]:
    """Return ``name -> directory`` for every discoverable golden path template."""
    if not templates_dir.is_dir():
        return {}
    templates: Dict[str, Path] = {}
    for candidate in sorted(templates_dir.iterdir()):
        if not candidate.is_dir():
            continue
        if all((candidate / name).is_file() for name in REQUIRED_TEMPLATE_FILES):
            templates[candidate.name] = candidate
    return templates


def _resolve_template(template: str, templates_dir: Path) -> Path:
    templates = available_templates(templates_dir)
    if not templates:
        raise ScaffoldError(
            f"No golden path templates found in {templates_dir}. Run from a repository "
            "checkout, or pass --templates-dir pointing at deployment/templates."
        )
    if template not in templates:
        known = ", ".join(sorted(templates))
        raise ScaffoldError(f"Unknown template '{template}'. Available templates: {known}.")
    return templates[template]


def _scaffold_config(template_source: Path, config_dir: Path, force: bool) -> List[Path]:
    config_files = sorted(template_source.glob("*.yaml"))
    existing = config_dir.is_dir() and any(config_dir.iterdir())
    if existing and not force:
        raise ScaffoldError(
            f"{config_dir} already exists and is not empty. "
            "Pass --force to overwrite matching config files."
        )
    config_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for source in config_files:
        destination = config_dir / source.name
        shutil.copy2(source, destination)
        written.append(destination)
    return written


def _copy_data(target: Path, data_dir: Path) -> List[Path]:
    if not data_dir.is_dir():
        return []
    destination_dir = target / "data"
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied: List[Path] = []
    for source in sorted(data_dir.glob("*.json")):
        destination = destination_dir / source.name
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def _validate_scaffold(written: List[Path]) -> List[str]:
    failures: List[str] = []
    for path in written:
        try:
            issues = validate_config_file(path)
        except ConfigError as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        for issue in issues:
            if issue.kind != "version-warning":
                failures.append(str(issue))
    return failures


def scaffold(
    target: Path,
    template: str = DEFAULT_TEMPLATE,
    config_name: str = DEFAULT_CONFIG_NAME,
    include_data: bool = True,
    force: bool = False,
    templates_dir: Path = TEMPLATES_DIR,
) -> ScaffoldResult:
    """Copy a golden path template into ``target/config`` and validate it."""
    template_source = _resolve_template(template, templates_dir)
    target = target.resolve()
    config_dir = target / config_name
    files = _scaffold_config(template_source, config_dir, force)
    failures = _validate_scaffold(files)
    if failures:
        raise ScaffoldError(
            "Scaffolded config is invalid (this is a bug in the template): "
            + "; ".join(failures)
        )
    data_files = _copy_data(target, DATA_DIR) if include_data else []
    return ScaffoldResult(
        target=target,
        template=template,
        config_dir=config_dir,
        template_source=template_source,
        files=files,
        data_files=data_files,
    )


def _print_scaffold(result: ScaffoldResult) -> None:
    print(f"Scaffolded '{result.template}' into {result.target}")
    print(f"  config: {len(result.files)} files -> {result.config_dir}")
    if result.data_files:
        print(f"  data:   {len(result.data_files)} files -> {result.target / 'data'}")
    print()
    print("Next steps:")
    print(f"  export GENAI_CONFIG_DIR={result.config_dir}")
    print("  python -m app.config_validate")
    print("  uvicorn app.main:app")


def _print_templates(templates: Dict[str, Path]) -> None:
    if not templates:
        print("No golden path templates found.", file=sys.stderr)
        return
    print("Available golden paths:")
    for name, path in templates.items():
        recommended = " (recommended)" if name == DEFAULT_TEMPLATE else ""
        print(f"  {name}{recommended} -> {path}")


def _cmd_init(args: argparse.Namespace) -> int:
    try:
        result = scaffold(
            target=Path(args.target),
            template=args.template,
            config_name=args.config_name,
            include_data=not args.no_data,
            force=args.force,
            templates_dir=Path(args.templates_dir),
        )
    except ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        _print_scaffold(result)
    return 0


def _cmd_templates(args: argparse.Namespace) -> int:
    templates = available_templates(Path(args.templates_dir))
    if args.json:
        print(json.dumps(sorted(templates), indent=2))
    else:
        _print_templates(templates)
    return 0 if templates else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    target = Path(args.path)
    try:
        if target.is_file():
            results: Dict[str, List[ValidationIssue]] = {
                target.name: validate_config_file(target)
            }
        else:
            results = validate_all(target)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    hard_failure = False
    for name, issues in results.items():
        hard = [issue for issue in issues if issue.kind != "version-warning"]
        status = "OK" if not hard else "INVALID"
        print(f"{status} {name}")
        for issue in hard:
            print(f"  - {issue}", file=sys.stderr)
        hard_failure = hard_failure or bool(hard)
    return 1 if hard_failure else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="genai",
        description="Scaffold and validate enterprise GenAI platform configuration.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Scaffold a project from a golden path template.")
    init.add_argument("target", help="Project directory to create (config/ and data/ inside).")
    init.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        help=f"Golden path template name (default: {DEFAULT_TEMPLATE}).",
    )
    init.add_argument(
        "--config-name",
        default=DEFAULT_CONFIG_NAME,
        help=f"Name of the config directory inside the target (default: {DEFAULT_CONFIG_NAME}).",
    )
    init.add_argument("--no-data", action="store_true", help="Skip copying the sample data corpus.")
    init.add_argument("--force", action="store_true", help="Overwrite an existing config directory.")
    init.add_argument(
        "--templates-dir",
        default=str(TEMPLATES_DIR),
        help="Directory containing golden path templates.",
    )
    init.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    init.set_defaults(func=_cmd_init)

    templates = subparsers.add_parser("templates", help="List available golden path templates.")
    templates.add_argument("--templates-dir", default=str(TEMPLATES_DIR))
    templates.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    templates.set_defaults(func=_cmd_templates)

    validate = subparsers.add_parser("validate", help="Validate a config file or directory.")
    validate.add_argument("path", nargs="?", default="config", help="Config file or directory.")
    validate.set_defaults(func=_cmd_validate)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
