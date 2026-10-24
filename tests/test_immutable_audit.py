"""Tests for issue #55: immutable audit trail + compliance evidence exports.

Covers the hash-chained store (append/verify/tamper detection), retention with
export-before-purge, regional routing, evidence packs, ``AuditLogger`` wiring,
and the compliance API (filters, verify, export, evidence, purge).

The plain in-memory + JSONL trail must remain the default and unchanged.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.services.audit_log import AuditLogger
from core.services.audit_store import (
    GENESIS_HASH,
    ImmutableAuditStore,
    RegionalAuditStore,
    RetentionPolicy,
    build_audit_sink,
    build_evidence_pack,
    compute_record_hash,
    parse_time,
)

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"
NOW = 1_700_000_000.0
DAY = 86400.0


def _event(
    event_type: str = "governance",
    action: str = "cost_check",
    outcome: str = "denied",
    tenant: Optional[str] = None,
    timestamp: float = NOW,
    **details: Any,
) -> Dict[str, Any]:
    return {
        "event_id": f"{event_type}-{action}-{timestamp}-{details.get('i', '')}",
        "timestamp": timestamp,
        "event_type": event_type,
        "action": action,
        "outcome": outcome,
        "request_id": None,
        "tenant": tenant,
        "attribution": {},
        "details": {"failure_type": "cost_limit_exceeded", **details},
    }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# -- store: hash chain / tamper detection ---------------------------------


def test_append_creates_verifiable_hash_chain(tmp_path):
    store = ImmutableAuditStore(tmp_path / "audit.jsonl")
    first = store.append(_event(timestamp=NOW))
    second = store.append(_event(event_type="config", timestamp=NOW + 1))

    assert first["sequence"] == 1
    assert first["prev_hash"] == GENESIS_HASH
    assert second["sequence"] == 2
    assert second["prev_hash"] == first["hash"]
    assert first["hash"] == compute_record_hash(first, GENESIS_HASH)

    result = store.verify()
    assert result["valid"] is True
    assert result["entries"] == 2
    assert result["head"] == second["hash"]

    reloaded = ImmutableAuditStore(tmp_path / "audit.jsonl")
    assert reloaded.verify()["valid"] is True
    assert reloaded.events()[1]["event_id"] == second["event_id"]


def test_mutated_record_is_detected(tmp_path):
    store = ImmutableAuditStore(tmp_path / "audit.jsonl")
    store.append(_event(timestamp=NOW))
    store.append(_event(timestamp=NOW + 1))
    store._records[1]["outcome"] = "allowed"

    result = store.verify()
    assert result["valid"] is False
    assert result["broken_at"] == 2
    assert "hash mismatch" in result["reason"]


def test_tampered_file_is_detected_on_reload(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = ImmutableAuditStore(path)
    store.append(_event(timestamp=NOW))
    store.append(_event(timestamp=NOW + 1))

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    tampered = json.loads(lines[0])
    tampered["outcome"] = "allowed"
    lines[0] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = ImmutableAuditStore(path).verify()
    assert result["valid"] is False
    assert result["broken_at"] == 1


def test_deleted_middle_record_breaks_sequence(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = ImmutableAuditStore(path)
    for index in range(3):
        store.append(_event(timestamp=NOW + index))

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")

    result = ImmutableAuditStore(path).verify()
    assert result["valid"] is False
    assert result["broken_at"] == 2
    assert "sequence mismatch" in result["reason"]


# -- retention ------------------------------------------------------------


def test_retention_purge_exports_before_deleting(tmp_path):
    export_dir = tmp_path / "exports"
    store = ImmutableAuditStore(
        tmp_path / "audit.jsonl",
        retention=RetentionPolicy(default_days=30),
    )
    old = store.append(_event(timestamp=NOW - 40 * DAY))
    fresh = store.append(_event(timestamp=NOW - DAY))

    result = store.purge(now=NOW, export_dir=export_dir)

    assert result["purged"] == 1
    assert result["retained"] == 1
    assert result["export"] is not None
    exported = json.loads(Path(result["export"]).read_text(encoding="utf-8"))
    assert exported["count"] == 1
    assert exported["events"][0]["event_id"] == old["event_id"]
    assert result["previous_head"] == fresh["hash"]

    events = store.events()
    assert [event["action"] for event in events] == ["retention_purge", "cost_check"]
    assert events[0]["event_type"] == "audit"
    assert events[0]["outcome"] == "purged"
    assert events[0]["details"]["purged"] == 1
    assert events[0]["details"]["previous_head"] == fresh["hash"]
    assert events[1]["event_id"] == fresh["event_id"]

    verified = store.verify()
    assert verified["valid"] is True
    assert ImmutableAuditStore(tmp_path / "audit.jsonl").verify()["valid"] is True


def test_retention_overrides_per_event_type_and_tenant():
    policy = RetentionPolicy(
        default_days=90,
        event_types={"security": 1},
        tenants={"acme": 7},
    )
    assert policy.days_for(_event(event_type="security")) == 1
    assert policy.days_for(_event(event_type="governance", tenant="acme")) == 7
    assert policy.days_for(_event(event_type="governance")) == 90

    assert policy.is_expired(_event(event_type="security", timestamp=NOW - 2 * DAY), NOW)
    assert not policy.is_expired(_event(event_type="governance", timestamp=NOW - 2 * DAY), NOW)
    assert policy.is_expired(
        _event(event_type="governance", tenant="acme", timestamp=NOW - 8 * DAY), NOW
    )
    assert not policy.is_expired(
        _event(event_type="governance", tenant="acme", timestamp=NOW - 6 * DAY), NOW
    )


def test_zero_retention_keeps_events_forever(tmp_path):
    store = ImmutableAuditStore(
        tmp_path / "audit.jsonl",
        retention=RetentionPolicy(default_days=0),
    )
    store.append(_event(timestamp=NOW - 10000 * DAY))
    result = store.purge(now=NOW, export_dir=tmp_path / "exports")
    assert result["purged"] == 0
    assert store.count() == 1


def test_purge_without_expired_events_is_a_noop(tmp_path):
    store = ImmutableAuditStore(
        tmp_path / "audit.jsonl",
        retention=RetentionPolicy(default_days=30),
    )
    store.append(_event(timestamp=NOW - DAY))
    before_head = store.head()
    result = store.purge(now=NOW, export_dir=tmp_path / "exports")
    assert result["purged"] == 0
    assert result["export"] is None
    assert store.head() == before_head


# -- evidence pack --------------------------------------------------------


def test_evidence_pack_contains_who_what_when_and_counts():
    events = [
        _event(timestamp=NOW - 10, tenant="acme"),
        _event(
            event_type="guardrail",
            action="input",
            outcome="blocked",
            tenant="acme",
            timestamp=NOW - 5,
            failure_type="guardrail_input_blocked",
        ),
        _event(
            event_type="pii",
            action="detect",
            outcome="blocked",
            tenant="globex",
            timestamp=NOW - 4,
            failure_type=None,
        ),
        _event(event_type="config", action="startup", outcome="success", timestamp=NOW),
        _event(timestamp=NOW - 100 * DAY, tenant="acme"),
    ]
    pack = build_evidence_pack(
        events,
        start=NOW - 1000,
        end=NOW + 1,
        tenant="acme",
        generated_at=NOW + 2,
        chain={"available": True, "valid": True},
        context={"config_revision": 3, "components": {"llm": "DummyLLM"}},
    )

    assert pack["schema_version"] == 1
    assert pack["window"]["tenant"] == "acme"
    assert pack["window"]["start"] is not None
    assert pack["summary"]["total_events"] == 2
    assert pack["summary"]["by_event_type"] == {"governance": 1, "guardrail": 1}
    assert pack["summary"]["guardrail_blocks"] == 1
    assert pack["summary"]["governance_denials"] == 1
    assert pack["summary"]["by_tenant"] == {"acme": 2}
    assert pack["chain"]["valid"] is True
    assert pack["context"]["config_revision"] == 3

    first = pack["events"][0]
    assert first["tenant"] == "acme"
    assert first["action"] == "cost_check"
    assert first["outcome"] == "denied"
    assert first["timestamp"] == NOW - 10


def test_evidence_pack_handles_empty_window():
    pack = build_evidence_pack([], start=NOW, end=NOW + 10, generated_at=NOW)
    assert pack["summary"]["total_events"] == 0
    assert pack["events"] == []
    assert pack["chain"] == {"available": False}


# -- regional routing -----------------------------------------------------


def test_region_routing_selects_tenant_sink(tmp_path):
    us = ImmutableAuditStore(tmp_path / "us.jsonl")
    eu = ImmutableAuditStore(tmp_path / "eu.jsonl")
    store = RegionalAuditStore(
        {"us": us, "eu": eu},
        default_region="us",
        tenant_regions={"acme-eu": "eu"},
    )

    store.append(_event(tenant="acme-eu", timestamp=NOW))
    store.append(_event(tenant="globex", timestamp=NOW + 1))
    store.append(_event(tenant=None, timestamp=NOW + 2))

    assert store.count() == 3
    assert us.count() == 2
    assert eu.count() == 1
    assert len(store.events(tenant="acme-eu")) == 1
    assert [e["tenant"] for e in store.events()] == ["acme-eu", "globex", None]
    assert store.verify()["valid"] is True
    assert set(store.verify()["regions"]) == {"us", "eu"}


def test_regional_purge_exports_and_rechains_each_region(tmp_path):
    us = ImmutableAuditStore(
        tmp_path / "us.jsonl", retention=RetentionPolicy(default_days=30)
    )
    eu = ImmutableAuditStore(
        tmp_path / "eu.jsonl", retention=RetentionPolicy(default_days=30)
    )
    store = RegionalAuditStore(
        {"us": us, "eu": eu}, default_region="us", tenant_regions={"acme": "eu"}
    )
    store.append(_event(tenant="acme", timestamp=NOW - 40 * DAY))
    store.append(_event(tenant="globex", timestamp=NOW - 40 * DAY))
    store.append(_event(tenant="globex", timestamp=NOW - DAY))

    result = store.purge(now=NOW, export_dir=tmp_path / "exports")
    assert result["purged"] == 2
    assert result["retained"] == 1
    assert len(result["exports"]) == 2
    assert store.verify()["valid"] is True
    assert {e.get("action") for e in store.events()} == {"retention_purge", "cost_check"}


def test_build_audit_sink_is_opt_in(tmp_path):
    assert build_audit_sink({}) is None
    assert build_audit_sink({"immutable": {"enabled": False}}) is None

    sink = build_audit_sink(
        {
            "immutable": {
                "enabled": True,
                "regions": {
                    "us": {"path": str(tmp_path / "us.jsonl")},
                    "eu": str(tmp_path / "eu.jsonl"),
                },
                "default_region": "us",
                "tenant_regions": {"acme": "eu"},
            },
            "retention": {"default_days": 7},
        }
    )
    assert sink is not None
    assert sink.default_region == "us"
    assert set(sink.stores) == {"us", "eu"}
    assert sink.stores["us"].retention.default_days == 7


# -- logger wiring --------------------------------------------------------


def _immutable_config(tmp_path: Path, **overrides: Any) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "enabled": True,
        "path": "",
        "max_entries": 100,
        "immutable": {
            "enabled": True,
            "path": str(tmp_path / "immutable.jsonl"),
            "default_region": "default",
        },
        "retention": {"default_days": 30, "export_dir": str(tmp_path / "exports")},
    }
    config.update(overrides)
    return config


def test_logger_writes_immutable_sink(tmp_path):
    logger = AuditLogger.from_config(_immutable_config(tmp_path))
    assert logger.sink is not None
    first = logger.record("governance", "cost_check", "denied")
    second = logger.record("config", "startup", "success")

    assert first is not None and second is not None
    lines = (tmp_path / "immutable.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    stored = json.loads(lines[0])
    assert stored["sequence"] == 1
    assert stored["prev_hash"] == GENESIS_HASH
    assert stored["hash"]

    assert logger.count() == 2
    assert logger.events(outcome="denied")[0]["event_id"] == first["event_id"]
    verify = logger.verify()
    assert verify["available"] is True
    assert verify["valid"] is True
    logger.close()


def test_logger_purge_uses_configured_export_dir(tmp_path):
    logger = AuditLogger.from_config(
        _immutable_config(tmp_path), clock=lambda: NOW
    )
    logger.record("governance", "cost_check", "denied")

    result = logger.purge(now=NOW + 100 * DAY)
    assert result["purged"] == 1
    assert result["export"] is not None
    assert Path(result["export"]).parent == tmp_path / "exports"
    assert logger.count() == 1
    assert logger.events()[0]["action"] == "retention_purge"


def test_default_logger_stays_in_memory_without_immutable(tmp_path):
    logger = AuditLogger.from_config(
        {"enabled": True, "path": str(tmp_path / "audit.jsonl"), "max_entries": 10}
    )
    assert logger.sink is None
    logger.record("config", "startup", "success")
    assert logger.verify() == {
        "available": False,
        "valid": None,
        "reason": "immutable audit store is not enabled",
    }
    with pytest.raises(RuntimeError):
        logger.purge()


def test_parse_time_accepts_epoch_and_iso():
    assert parse_time(None) is None
    assert parse_time(0) == 0.0
    assert parse_time("0") == 0.0
    assert parse_time("1970-01-01T00:00:00Z") == 0.0
    with pytest.raises(ValueError):
        parse_time("not-a-time")


# -- API ------------------------------------------------------------------

MODELS_YAML = """
active_model: dummy
active_embedding_model: emb-a
models:
  dummy:
    provider: dummy
    context_window: 4096
embedding_models:
  emb-a:
    provider: dummy
    model_name: emb-a
"""

RETRIEVAL_YAML = """
retrieval:
  default_retriever: dummy
  similarity_metric: cosine
  top_k: 3
  retrievers:
    dummy:
      provider: dummy
evaluation:
  enabled: false
  active_evaluator: dummy
  evaluators:
    dummy:
      provider: dummy
reranking:
  enabled: false
"""


class _ScriptedPipeline:
    def __init__(self, results: List[Dict[str, Any]]):
        self._results = list(results)

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return self._results.pop(0)


def _audit_yaml(
    tmp_path: Path,
    *,
    enabled: bool = True,
    immutable: bool = True,
    retention_days: int = 30,
) -> str:
    path = tmp_path / "immutable.jsonl"
    return (
        f"enabled: {'true' if enabled else 'false'}\n"
        'path: ""\n'
        "max_entries: 100\n"
        "immutable:\n"
        f"  enabled: {'true' if immutable else 'false'}\n"
        f"  path: {json.dumps(str(path))}\n"
        "  default_region: default\n"
        "retention:\n"
        f"  default_days: {retention_days}\n"
        f"  export_dir: {json.dumps(str(tmp_path / 'exports'))}\n"
    )


def _api_app(
    tmp_path: Path,
    results: List[Dict[str, Any]],
    *,
    immutable: bool = True,
    enabled: bool = True,
    retention_days: int = 30,
) -> Any:
    paths = {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", "redact_sensitive_data: true\n"
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            "require_api_key: false\napi_key: \"\"\nallow_rebuild: false\n"
            "history_max_runs: 1000\ntrace_store_max: 500\nmax_batch_size: 25\n",
        ),
        "audit_config_path": _write(
            tmp_path / "audit.yaml",
            _audit_yaml(
                tmp_path,
                enabled=enabled,
                immutable=immutable,
                retention_days=retention_days,
            ),
        ),
    }
    pipeline = _ScriptedPipeline(results)
    return create_app(pipeline_builder=lambda **_: pipeline, **paths)


def _denied() -> Dict[str, Any]:
    return {
        "response": None,
        "error": "cost limit exceeded",
        "failure_type": "cost_limit_exceeded",
        "failure_tags": ["cost_limit_exceeded"],
        "cost": {"estimated_cost_usd": 0.9},
        "latency": {"total_ms": 5.0},
        "observability": {"status": "failed"},
    }


def _success() -> Dict[str, Any]:
    return {
        "response": "answer",
        "failure_tags": [],
        "cost": {"estimated_cost_usd": 0.001},
        "latency": {"total_ms": 5.0},
        "observability": {"status": "success"},
    }


def test_api_audit_filters_outcome_and_time_window(tmp_path):
    with TestClient(_api_app(tmp_path, [_denied(), _success()], immutable=False)) as client:
        client.post("/v1/query", json={"query": "expensive"})
        client.post("/v1/query", json={"query": "cheap"})

        denied = client.get("/v1/audit", params={"outcome": "denied"}).json()
        assert len(denied["events"]) == 1
        assert denied["events"][0]["outcome"] == "denied"

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        empty = client.get("/v1/audit", params={"since": future}).json()
        assert empty["events"] == []

        invalid = client.get("/v1/audit", params={"since": "nope"})
        assert invalid.status_code == 400
        assert invalid.json()["failure_type"] == "invalid_request"


def test_api_verify_reports_unavailable_without_immutable(tmp_path):
    with TestClient(_api_app(tmp_path, [_success()], immutable=False)) as client:
        body = client.get("/v1/audit/verify").json()
    assert body["available"] is False
    assert body["valid"] is None


def test_api_verify_hash_chain(tmp_path):
    with TestClient(_api_app(tmp_path, [_denied()])) as client:
        client.post("/v1/query", json={"query": "expensive"})
        body = client.get("/v1/audit/verify").json()
    assert body["available"] is True
    assert body["valid"] is True
    assert body["entries"] >= 2


def test_api_evidence_pack_for_window(tmp_path):
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=1)).isoformat()
    end = (now + timedelta(hours=1)).isoformat()
    with TestClient(_api_app(tmp_path, [_denied()])) as client:
        client.post("/v1/query", json={"query": "expensive"})
        response = client.get(
            "/v1/audit/evidence", params={"start": start, "end": end}
        )
    assert response.status_code == 200
    pack = response.json()
    assert pack["summary"]["total_events"] >= 2
    assert pack["summary"]["governance_denials"] == 1
    assert pack["chain"]["available"] is True
    assert pack["chain"]["valid"] is True
    assert pack["events"][0]["timestamp"] is not None
    assert "action" in pack["events"][0]


def test_api_export_downloads_json(tmp_path):
    with TestClient(_api_app(tmp_path, [_denied()])) as client:
        client.post("/v1/query", json={"query": "expensive"})
        response = client.get("/v1/audit/export", params={"start": "0"})
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    body = response.json()
    assert body["count"] >= 2
    assert body["chain"]["valid"] is True
    assert any(event["event_type"] == "governance" for event in body["events"])


def test_api_purge_requires_immutable_store(tmp_path):
    with TestClient(_api_app(tmp_path, [_success()], immutable=False)) as client:
        response = client.post("/v1/audit/purge", json={})
    assert response.status_code == 400
    assert response.json()["failure_type"] == "immutable_audit_disabled"


def test_api_purge_exports_then_deletes(tmp_path):
    with TestClient(_api_app(tmp_path, [_denied()])) as client:
        client.post("/v1/query", json={"query": "expensive"})
        response = client.post(
            "/v1/audit/purge", json={"now": NOW + 10 * 365 * DAY}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["purged"] >= 2
        assert body["export"] is not None
        assert Path(body["export"]).exists()

        remaining = client.get("/v1/audit").json()
        assert remaining["events"][0]["action"] == "retention_purge"
        assert all(event["action"] == "retention_purge" for event in remaining["events"])

        verify = client.get("/v1/audit/verify").json()
        assert verify["valid"] is True


def test_api_evidence_rejects_inverted_window(tmp_path):
    with TestClient(_api_app(tmp_path, [_success()], immutable=False)) as client:
        response = client.get(
            "/v1/audit/evidence", params={"start": "2000", "end": "1000"}
        )
    assert response.status_code == 400
    assert response.json()["failure_type"] == "invalid_request"
