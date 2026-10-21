"""Config validation + secret resolution (issue #46, workstreams E2 + E3).

Single entrypoint used by:

- the composition root / ``create_app`` (fail fast at start-up),
- the ``python -m app.config_validate`` CLI (CI + pre-deploy),
- tests.

Validation performs three checks per file, in order:

1. **schema** - parse YAML and validate against the typed model
   (:mod:`core.config.schema`); unknown top-level keys and wrong types produce
   a precise, actionable message (file, JSON path, expected vs got),
2. **secrets** - every ``${ENV_VAR}`` / ``env:VAR`` reference must resolve from
   the environment,
3. **version** - a ``config_version`` newer than the running schema is reported
   as a warning (a migration note) rather than a hard failure.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from core.config.schema import CURRENT_CONFIG_VERSION, SCHEMAS
from core.config.secrets import SecretResolutionError, find_secret_refs

__all__ = [
    "ConfigError",
    "ConfigValidationError",
    "ValidationIssue",
    "validate_config_file",
    "validate_config_data",
    "validate_all",
    "load_and_validate",
    "resolve_config_file",
    "schema_for",
]


class ConfigValidationError(RuntimeError):
    """Raised when a config file fails schema validation."""

    def __init__(self, path: Path, issues: List["ValidationIssue"]):
        self.path = path
        self.issues = issues
        detail = "\n".join(f"  - {issue}" for issue in issues)
        super().__init__(f"Invalid configuration in '{path}':\n{detail}")


class ConfigError(RuntimeError):
    """Raised for config problems that are not schema errors (e.g. bad YAML)."""


class ValidationIssue:
    def __init__(self, path: str, message: str, *, kind: str = "schema"):
        self.path = path
        self.message = message
        self.kind = kind

    def __str__(self) -> str:
        prefix = f"[{self.kind}] " if self.kind != "schema" else ""
        where = f"{self.path}: " if self.path else ""
        return f"{prefix}{where}{self.message}"


def schema_for(kind: str) -> Any:
    """Return the schema class for a config kind (filename stem)."""
    if kind not in SCHEMAS:
        raise ConfigError(
            f"No schema registered for config kind '{kind}'. "
            f"Known kinds: {', '.join(sorted(SCHEMAS))}."
        )
    return SCHEMAS[kind]


def _issues_from_validation_error(error: ValidationError) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for err in error.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        issues.append(ValidationIssue(loc, err["msg"]))
    return issues


def validate_config_data(
    data: Any,
    kind: str,
    *,
    source: str = "<data>",
    environ: Optional[Dict[str, str]] = None,
) -> List[ValidationIssue]:
    """Validate already-loaded config ``data`` against the ``kind`` schema.

    Returns the list of issues (empty when valid). Does not raise.
    """
    from core.config.secrets import resolve_secrets

    issues: List[ValidationIssue] = []
    schema = schema_for(kind)

    if data is None:
        data = {}
    if not isinstance(data, dict):
        return [ValidationIssue("<root>", f"expected a mapping, got {type(data).__name__}")]

    try:
        schema.model_validate(data)
    except ValidationError as exc:
        issues.extend(_issues_from_validation_error(exc))

    # Secret references must be resolvable.
    try:
        resolve_secrets(data, environ)
    except SecretResolutionError as exc:
        issues.append(ValidationIssue("", str(exc), kind="secret"))

    # Version drift is a warning, not a failure.
    version = data.get("config_version")
    if isinstance(version, int) and version > CURRENT_CONFIG_VERSION:
        issues.append(
            ValidationIssue(
                "config_version",
                f"config_version {version} is newer than this build supports "
                f"({CURRENT_CONFIG_VERSION}); some keys may be ignored. See the "
                f"config migration notes.",
                kind="version-warning",
            )
        )
    return issues


def validate_config_file(
    path: Path,
    *,
    kind: Optional[str] = None,
    environ: Optional[Dict[str, str]] = None,
) -> List[ValidationIssue]:
    """Validate a YAML config file. ``kind`` defaults to the filename stem."""
    path = Path(path)
    kind = kind or path.stem
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {path}: {exc}") from exc
    return validate_config_data(data, kind, source=str(path), environ=environ)


def _errors_only(issues: List[ValidationIssue]) -> List[ValidationIssue]:
    return [issue for issue in issues if issue.kind != "version-warning"]


def load_and_validate(
    path: Optional[Path],
    *,
    kind: Optional[str] = None,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Load a config file after validating it; raises on any hard issue.

    Missing path -> ``{}`` (matches the existing ``_load_config`` behaviour for
    optional configs). Secret references are **resolved** in the returned dict.
    """
    from core.config.secrets import resolve_secrets

    if path is None:
        return {}
    path = Path(path)
    issues = validate_config_file(path, kind=kind, environ=environ)
    hard = _errors_only(issues)
    if hard:
        raise ConfigValidationError(path, hard)

    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigValidationError(
            path, [ValidationIssue("<root>", "expected a mapping at the top level")]
        )
    return resolve_secrets(data, environ)


def resolve_config_file(
    path: Optional[Path],
    *,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Load + resolve secrets without schema validation (lenient loader)."""
    from core.config.secrets import resolve_secrets

    if path is None:
        return {}
    try:
        with open(Path(path), "r") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return resolve_secrets(data, environ)


def validate_all(
    config_dir: Path,
    *,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, List[ValidationIssue]]:
    """Validate every schema-backed config present in ``config_dir``.

    Returns ``{filename: issues}`` for the files that exist. Files with no
    registered schema are skipped.
    """
    results: Dict[str, List[ValidationIssue]] = {}
    config_dir = Path(config_dir)
    for stem in sorted(SCHEMAS):
        candidate = config_dir / f"{stem}.yaml"
        if not candidate.exists():
            continue
        results[candidate.name] = validate_config_file(candidate, kind=stem, environ=environ)
    return results


def find_referenced_secret_names(data: Any) -> List[str]:
    """Convenience wrapper used by docs/tests: list secret refs in config data."""
    return sorted(set(find_secret_refs(data)))
