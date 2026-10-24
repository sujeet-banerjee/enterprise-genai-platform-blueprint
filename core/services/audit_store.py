"""Immutable audit storage, retention and compliance evidence packs (issue #55).

``AuditLogger`` (#28) keeps a bounded in-memory ring plus an optional plain
JSONL file. That is convenient for development but not sufficient when an
auditor asks whether the trail was tampered with. This module adds an opt-in,
hash-chained, append-only sink behind the same logger API:

* every record carries ``sequence``, ``prev_hash`` and ``hash``; the hash covers
  the canonical JSON of the record with the previous hash as its parent,
* :meth:`ImmutableAuditStore.verify` walks the chain and reports the first
  broken link,
* retention is configured per default/event type/tenant and a purge exports the
  expired slice before it removes it (leaving a hash-chained purge marker that
  preserves the previous head for continuity),
* :class:`RegionalAuditStore` routes records to region-specific sinks (tenant
  mappings supported) for data-residency requirements,
* :func:`build_evidence_pack` produces a portable who/what/when export for a
  time window.

The plain in-memory/JSONL path stays the default: nothing changes until
``audit.immutable.enabled`` is true.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

GENESIS_HASH = "0" * 64
EVIDENCE_SCHEMA_VERSION = 1


def canonical_json(record: Mapping[str, Any]) -> str:
    """Deterministic JSON used for hashing (stable across processes)."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def compute_record_hash(record: Mapping[str, Any], prev_hash: str) -> str:
    payload = {key: value for key, value in record.items() if key != "hash"}
    material = f"{prev_hash}\n{canonical_json(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def parse_time(value: Any) -> Optional[float]:
    """Parse an epoch number or ISO-8601 string; ``None`` passes through."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _iso(timestamp: Optional[float]) -> Optional[str]:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()


def _matches(
    record: Mapping[str, Any],
    tenant: Optional[str],
    event_type: Optional[str],
    outcome: Optional[str],
    since: Optional[float],
    until: Optional[float],
) -> bool:
    if event_type is not None and record.get("event_type") != event_type:
        return False
    if tenant is not None and record.get("tenant") != str(tenant):
        return False
    if outcome is not None and record.get("outcome") != outcome:
        return False
    timestamp = float(record.get("timestamp") or 0.0)
    if since is not None and timestamp < since:
        return False
    if until is not None and timestamp > until:
        return False
    return True


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention in days; ``<= 0`` means keep forever."""

    default_days: int = 90
    event_types: Mapping[str, int] = field(default_factory=dict)
    tenants: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_types", dict(self.event_types or {}))
        object.__setattr__(self, "tenants", dict(self.tenants or {}))

    def days_for(self, event: Mapping[str, Any]) -> int:
        tenant = event.get("tenant")
        if tenant is not None and str(tenant) in self.tenants:
            return int(self.tenants[str(tenant)])
        event_type = str(event.get("event_type") or "")
        if event_type in self.event_types:
            return int(self.event_types[event_type])
        return int(self.default_days)

    def is_expired(self, event: Mapping[str, Any], now: float) -> bool:
        days = self.days_for(event)
        if days <= 0:
            return False
        timestamp = float(event.get("timestamp") or 0.0)
        return timestamp < (now - days * 86400)

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "RetentionPolicy":
        config = config or {}
        return cls(
            default_days=int(config.get("default_days", 90) or 0),
            event_types=dict(config.get("event_types") or {}),
            tenants=dict(config.get("tenants") or {}),
        )


class ImmutableAuditStore:
    """Hash-chained append-only JSONL sink with retention and verification."""

    def __init__(
        self,
        path: Any,
        clock: Optional[Callable[[], float]] = None,
        retention: Optional[RetentionPolicy] = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or time.time
        self.retention = retention or RetentionPolicy()
        self._lock = threading.Lock()
        self._records: List[Dict[str, Any]] = []
        self._head = GENESIS_HASH
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        records: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        records.append(parsed)
        except (OSError, json.JSONDecodeError):
            # A corrupt file is left untouched; append starts a new chain and
            # verify() reports the problem instead of silently trusting it.
            self._records = []
            self._head = GENESIS_HASH
            return
        self._records = records
        self._head = str(records[-1].get("hash") or GENESIS_HASH) if records else GENESIS_HASH

    def _write_line(self, record: Mapping[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(canonical_json(record) + "\n")

    def _rewrite(self, records: Iterable[Mapping[str, Any]]) -> None:
        temp = self.path.with_name(self.path.name + ".tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(canonical_json(record) + "\n")
        os.replace(temp, self.path)

    # -- ingestion --------------------------------------------------------

    def append(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        with self._lock:
            record = dict(event)
            record["sequence"] = len(self._records) + 1
            record["prev_hash"] = self._head
            record["hash"] = compute_record_hash(record, self._head)
            self._records.append(record)
            self._head = record["hash"]
            try:
                self._write_line(record)
            except OSError:
                # Persistence failures must never break request handling.
                pass
            return dict(record)

    # -- reads ------------------------------------------------------------

    def events(
        self,
        limit: Optional[int] = None,
        tenant: Optional[str] = None,
        event_type: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            items = [dict(record) for record in self._records]
        items = [
            item
            for item in items
            if _matches(item, tenant, event_type, outcome, since, until)
        ]
        if limit is not None:
            items = items[-int(limit):]
        return items

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def head(self) -> str:
        with self._lock:
            return self._head

    def verify(self) -> Dict[str, Any]:
        with self._lock:
            records = [dict(record) for record in self._records]
        prev = GENESIS_HASH
        for index, record in enumerate(records):
            expected_sequence = index + 1
            if record.get("sequence") != expected_sequence:
                return self._broken(
                    index,
                    expected_sequence,
                    f"sequence mismatch (expected {expected_sequence})",
                )
            if index == 0 and not record.get("chain_reset"):
                record_prev = record.get("prev_hash")
                if record_prev != GENESIS_HASH:
                    return self._broken(index, expected_sequence, "unexpected chain root")
            elif index > 0:
                if record.get("prev_hash") != prev:
                    return self._broken(index, expected_sequence, "prev_hash mismatch")
            expected_hash = compute_record_hash(record, str(record.get("prev_hash")))
            if record.get("hash") != expected_hash:
                return self._broken(index, expected_sequence, "hash mismatch")
            prev = str(record.get("hash"))
        return {
            "valid": True,
            "entries": len(records),
            "head": prev,
            "broken_at": None,
            "reason": None,
        }

    def _broken(self, index: int, sequence: int, reason: str) -> Dict[str, Any]:
        return {
            "valid": False,
            "entries": len(self._records),
            "head": self._head,
            "broken_at": sequence,
            "broken_index": index,
            "reason": reason,
        }

    # -- retention --------------------------------------------------------

    def purge(
        self,
        now: Optional[float] = None,
        export_dir: Optional[Any] = None,
    ) -> Dict[str, Any]:
        now = float(now if now is not None else self._clock())
        with self._lock:
            records = [dict(record) for record in self._records]
            expired = [
                record for record in records if self.retention.is_expired(record, now)
            ]
            if not expired:
                return {
                    "purged": 0,
                    "retained": len(records),
                    "export": None,
                    "previous_head": self._head,
                    "new_head": self._head,
                }

            export_path: Optional[str] = None
            if export_dir is not None:
                directory = Path(export_dir)
                directory.mkdir(parents=True, exist_ok=True)
                stamp = int(now)
                target = directory / f"audit-purge-{stamp}-{uuid.uuid4().hex[:8]}.json"
                payload = {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "exported_at": _iso(now),
                    "reason": "retention",
                    "count": len(expired),
                    "events": expired,
                }
                target.write_text(
                    json.dumps(payload, indent=2, sort_keys=True, default=str),
                    encoding="utf-8",
                )
                export_path = str(target)

            previous_head = str(records[-1].get("hash") or GENESIS_HASH)
            expired_sequences = {record.get("sequence") for record in expired}
            remaining = [
                record
                for record in records
                if record.get("sequence") not in expired_sequences
            ]
            marker = {
                "event_id": str(uuid.uuid4()),
                "timestamp": round(now, 6),
                "event_type": "audit",
                "action": "retention_purge",
                "outcome": "purged",
                "request_id": None,
                "tenant": None,
                "attribution": {},
                "details": {
                    "purged": len(expired),
                    "retained": len(remaining),
                    "export": export_path,
                    "previous_head": previous_head,
                },
                "chain_reset": True,
                "prev_hash": previous_head,
            }
            marker["sequence"] = 1
            marker["hash"] = compute_record_hash(marker, previous_head)
            rewritten: List[Dict[str, Any]] = [marker]
            head = str(marker["hash"])
            for record in remaining:
                fresh = dict(record)
                fresh["sequence"] = len(rewritten) + 1
                fresh["prev_hash"] = head
                fresh["hash"] = compute_record_hash(fresh, head)
                rewritten.append(fresh)
                head = str(fresh["hash"])
            try:
                self._rewrite(rewritten)
            except OSError:
                return {
                    "purged": 0,
                    "retained": len(records),
                    "export": export_path,
                    "previous_head": previous_head,
                    "new_head": self._head,
                    "error": "could not rewrite audit store",
                }
            self._records = rewritten
            self._head = head
            return {
                "purged": len(expired),
                "retained": len(remaining),
                "export": export_path,
                "previous_head": previous_head,
                "new_head": head,
            }


class RegionalAuditStore:
    """Routes records to region-specific immutable sinks (data residency)."""

    def __init__(
        self,
        stores: Mapping[str, ImmutableAuditStore],
        default_region: str = "default",
        tenant_regions: Optional[Mapping[str, str]] = None,
    ):
        if not stores:
            raise ValueError("At least one audit region must be configured")
        if default_region not in stores:
            raise ValueError(f"Unknown default audit region: {default_region!r}")
        self.stores = dict(stores)
        self.default_region = default_region
        self.tenant_regions = {
            str(key): str(value) for key, value in (tenant_regions or {}).items()
        }
        for region in self.tenant_regions.values():
            if region not in self.stores:
                raise ValueError(f"Unknown audit region: {region!r}")

    def region_for(self, event: Mapping[str, Any]) -> str:
        tenant = event.get("tenant")
        if tenant is not None:
            mapped = self.tenant_regions.get(str(tenant))
            if mapped:
                return mapped
        return self.default_region

    def append(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        return self.stores[self.region_for(event)].append(event)

    def events(
        self,
        limit: Optional[int] = None,
        tenant: Optional[str] = None,
        event_type: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        for store in self.stores.values():
            merged.extend(
                store.events(
                    tenant=tenant,
                    event_type=event_type,
                    outcome=outcome,
                    since=since,
                    until=until,
                )
            )
        merged.sort(key=lambda item: (float(item.get("timestamp") or 0.0), item.get("sequence", 0)))
        if limit is not None:
            merged = merged[-int(limit):]
        return merged

    def count(self) -> int:
        return sum(store.count() for store in self.stores.values())

    def head(self) -> Dict[str, str]:
        return {region: store.head() for region, store in self.stores.items()}

    def verify(self, region: Optional[str] = None) -> Dict[str, Any]:
        if region is not None:
            if region not in self.stores:
                raise KeyError(region)
            return self.stores[region].verify()
        regions = {name: store.verify() for name, store in self.stores.items()}
        return {
            "valid": all(result["valid"] for result in regions.values()),
            "entries": sum(result["entries"] for result in regions.values()),
            "regions": regions,
        }

    def purge(
        self,
        now: Optional[float] = None,
        export_dir: Optional[Any] = None,
    ) -> Dict[str, Any]:
        regions = {
            name: store.purge(now=now, export_dir=export_dir)
            for name, store in self.stores.items()
        }
        exports = [
            result["export"]
            for result in regions.values()
            if result.get("export") is not None
        ]
        return {
            "purged": sum(result["purged"] for result in regions.values()),
            "retained": sum(result["retained"] for result in regions.values()),
            "regions": regions,
            "export": exports[0] if len(exports) == 1 else None,
            "exports": exports,
        }


def build_audit_sink(
    config: Optional[Mapping[str, Any]],
    clock: Optional[Callable[[], float]] = None,
) -> Optional[RegionalAuditStore]:
    """Build the immutable sink from an ``audit`` config section (opt-in)."""
    config = config or {}
    immutable = config.get("immutable") or {}
    if not isinstance(immutable, Mapping) or not immutable.get("enabled"):
        return None
    retention = RetentionPolicy.from_config(config.get("retention") or {})
    default_region = str(immutable.get("default_region") or "default")
    regions_config = immutable.get("regions") or {}
    stores: Dict[str, ImmutableAuditStore] = {}
    if isinstance(regions_config, Mapping) and regions_config:
        for name, spec in regions_config.items():
            if isinstance(spec, Mapping):
                path = spec.get("path")
            else:
                path = spec
            if not path:
                raise ValueError(f"Audit region {name!r} has no path")
            stores[str(name)] = ImmutableAuditStore(path, clock=clock, retention=retention)
    else:
        path = immutable.get("path") or "audit/immutable.jsonl"
        stores[default_region] = ImmutableAuditStore(
            path, clock=clock, retention=retention
        )
    return RegionalAuditStore(
        stores,
        default_region=default_region,
        tenant_regions=immutable.get("tenant_regions") or {},
    )


def build_evidence_pack(
    events: Iterable[Mapping[str, Any]],
    start: Optional[float] = None,
    end: Optional[float] = None,
    tenant: Optional[str] = None,
    generated_at: Optional[float] = None,
    chain: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a portable compliance evidence pack for a time window."""
    generated_at = float(generated_at if generated_at is not None else time.time())
    selected = [
        dict(event)
        for event in events
        if _matches(event, tenant, None, None, start, end)
    ]
    selected.sort(key=lambda item: (float(item.get("timestamp") or 0.0), item.get("sequence", 0)))

    by_event_type: Dict[str, int] = {}
    by_outcome: Dict[str, int] = {}
    by_tenant: Dict[str, int] = {}
    for event in selected:
        event_type = str(event.get("event_type") or "unknown")
        outcome = str(event.get("outcome") or "unknown")
        by_event_type[event_type] = by_event_type.get(event_type, 0) + 1
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        tenant_key = str(event.get("tenant") or "default")
        by_tenant[tenant_key] = by_tenant.get(tenant_key, 0) + 1

    def _failure_type(event: Mapping[str, Any]) -> str:
        details = event.get("details")
        if isinstance(details, Mapping):
            return str(details.get("failure_type") or "")
        return ""

    guardrail_blocks = sum(
        1
        for event in selected
        if _failure_type(event).startswith("guardrail_")
        or (event.get("event_type") == "pii" and event.get("outcome") == "blocked")
    )
    governance_denials = sum(
        1
        for event in selected
        if event.get("event_type") == "governance"
        and event.get("action") == "cost_check"
        and event.get("outcome") == "denied"
    )

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "pack_id": str(uuid.uuid4()),
        "generated_at": _iso(generated_at),
        "window": {
            "start": _iso(start),
            "end": _iso(end),
            "tenant": str(tenant) if tenant is not None else None,
        },
        "context": dict(context or {}),
        "summary": {
            "total_events": len(selected),
            "by_event_type": by_event_type,
            "by_outcome": by_outcome,
            "by_tenant": by_tenant,
            "guardrail_blocks": guardrail_blocks,
            "governance_denials": governance_denials,
        },
        "chain": dict(chain or {"available": False}),
        "events": selected,
    }
