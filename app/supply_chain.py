"""Supply-chain waiver parsing for CI gates (issue #225).

Exit codes:

- ``0`` - waiver file is valid and ignore IDs were emitted,
- ``2`` - waiver file was unreadable or failed schema/expiry validation.

Usage::

    python -m app.supply_chain ignores --format pip-audit
    python -m app.supply_chain ignores --format trivy --output .trivyignore
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional

import yaml

DEFAULT_WAIVERS_PATH = Path(__file__).resolve().parent.parent / "security" / "waivers.yml"
FORMATS = ("pip-audit", "trivy")
TOP_LEVEL_FIELDS = frozenset({"version", "waivers"})
WAIVER_FIELDS = frozenset({"id", "package", "reason", "expires", "owner", "approved_by"})
ADVISORY_ID = re.compile(
    r"^(?:GHSA-[a-z0-9-]{10,}|CVE-\d{4}-\d{4,}|PYSEC-\d+)$",
    re.IGNORECASE,
)


class WaiverError(ValueError):
    """Raised when a waiver file is malformed, unknown or expired."""


@dataclass(frozen=True)
class Waiver:
    id: str
    package: str
    reason: str
    expires: date
    owner: str
    approved_by: str


def _require_mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise WaiverError(f"{label} must be a mapping")
    return value


def _required_text(entry: dict, key: str, label: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WaiverError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def load_waivers(path: Path, *, today: Optional[date] = None) -> List[Waiver]:
    """Load and validate a waiver file, failing closed on unknown or expired entries."""
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    document = _require_mapping(data, "waiver file")
    unknown = set(document) - TOP_LEVEL_FIELDS
    if unknown:
        raise WaiverError(f"unknown waiver fields: {', '.join(sorted(unknown))}")
    if document.get("version") != 1:
        raise WaiverError("version must be 1")
    entries = document.get("waivers", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise WaiverError("waivers must be a list")
    effective_today = today or date.today()
    waivers: List[Waiver] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"waivers[{index}]"
        record = _require_mapping(entry, label)
        unknown_fields = set(record) - WAIVER_FIELDS
        if unknown_fields:
            raise WaiverError(f"{label} has unknown fields: {', '.join(sorted(unknown_fields))}")
        missing = sorted(WAIVER_FIELDS - set(record))
        if missing:
            raise WaiverError(f"{label} is missing fields: {', '.join(missing)}")
        advisory_id = _required_text(record, "id", label)
        if not ADVISORY_ID.match(advisory_id):
            raise WaiverError(f"{label}.id is not a GHSA/CVE/PYSEC advisory id")
        if advisory_id in seen:
            raise WaiverError(f"duplicate waiver id: {advisory_id}")
        seen.add(advisory_id)
        reason = _required_text(record, "reason", label)
        if len(reason) < 20:
            raise WaiverError(f"{label}.reason must be at least 20 characters")
        raw_expiry = _required_text(record, "expires", label)
        try:
            expires = date.fromisoformat(raw_expiry)
        except ValueError as exc:
            raise WaiverError(f"{label}.expires must be an ISO date (YYYY-MM-DD)") from exc
        if expires <= effective_today:
            raise WaiverError(f"waiver {advisory_id} expired on {expires.isoformat()}")
        waivers.append(
            Waiver(
                id=advisory_id,
                package=_required_text(record, "package", label),
                reason=reason,
                expires=expires,
                owner=_required_text(record, "owner", label),
                approved_by=_required_text(record, "approved_by", label),
            )
        )
    return sorted(waivers, key=lambda item: item.id)


def ignores(waivers: Iterable[Waiver], fmt: str) -> List[str]:
    """Return sorted unique advisory IDs in the requested scanner ignore format."""
    if fmt not in FORMATS:
        raise WaiverError(f"unsupported ignore format: {fmt}")
    return sorted({waiver.id for waiver in waivers})


def write_ignores(waivers: Iterable[Waiver], fmt: str, path: Path) -> None:
    """Write scanner ignore IDs to *path* (empty file when there are no waivers)."""
    lines = ignores(waivers, fmt)
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    Path(path).write_text(payload, encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.supply_chain",
        description="Validate supply-chain waivers and emit scanner ignore IDs.",
    )
    parser.add_argument("action", nargs="?", default="ignores", choices=["ignores"])
    parser.add_argument("--waivers", default=str(DEFAULT_WAIVERS_PATH))
    parser.add_argument("--format", choices=FORMATS, default="pip-audit")
    parser.add_argument("--output", help="Write IDs to this file instead of stdout.")
    parser.add_argument("--today", help="Override today (YYYY-MM-DD) for expiry checks.")
    args = parser.parse_args(argv)

    try:
        today = date.fromisoformat(args.today) if args.today else None
    except ValueError as exc:
        print(f"FAIL --today must be an ISO date: {exc}", file=sys.stderr)
        return 2
    if today is None and args.today:
        print("FAIL --today must be an ISO date", file=sys.stderr)
        return 2

    try:
        waivers = load_waivers(Path(args.waivers), today=today)
        payload = "\n".join(ignores(waivers, args.format))
        if payload:
            payload += "\n"
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
    except (WaiverError, OSError, yaml.YAMLError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
