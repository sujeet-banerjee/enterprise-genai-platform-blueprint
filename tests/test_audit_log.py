"""Tests for issue #28: config-driven, append-only audit logging.

Covers the ``AuditLogger`` (record/read/filter/limit/redaction/JSONL/disabled),
governance-event emission from the query endpoint, and config-change events from
the pipeline-rebuild endpoint.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from core.services.audit_log import AuditLogger

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"


# -- unit ------------------------------------------------------------------


def test_disabled_logger_records_nothing():
    logger = AuditLogger(enabled=False)
    assert logger.record("config", "startup", "success") is None
    assert logger.events() == []
    assert logger.count() == 0


def test_logger_records_and_reads(tmp_path):
    logger = AuditLogger(enabled=True, path=tmp_path / "audit.jsonl")
    event = logger.record(
        "governance", "cost_check", "denied", details={"reason": "over_budget"}
    )
    assert event is not None
    assert event["event_type"] == "governance"
    assert event["outcome"] == "denied"
    assert event["details"]["reason"] == "over_budget"
    assert logger.count() == 1
    assert logger.events()[0]["event_id"] == event["event_id"]


def test_logger_writes_append_only_jsonl(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(enabled=True, path=path)
    logger.record("config", "startup", "success", details={"config_revision": 0})
    logger.record("config", "pipeline_rebuild", "success", details={"config_revision": 1})

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["action"] == "startup"
    assert second["action"] == "pipeline_rebuild"
    assert second["details"]["config_revision"] == 1


def test_logger_redacts_secrets(tmp_path):
    logger = AuditLogger(enabled=True, path=tmp_path / "audit.jsonl")
    event = logger.record(
        "config",
        "pipeline_rebuild",
        "success",
        details={"api_key": "sk-live-supersecret", "note": "token=sk-abcdef123456"},
    )
    assert "sk-live-supersecret" not in json.dumps(event)
    assert event["details"]["api_key"] == "[REDACTED]"


def test_logger_filter_and_limit(tmp_path):
    logger = AuditLogger(enabled=True, max_entries=10)
    for _ in range(3):
        logger.record("governance", "cost_check", "denied")
    logger.record("config", "pipeline_rebuild", "success")

    assert len(logger.events(event_type="config")) == 1
    assert len(logger.events(event_type="governance")) == 3
    assert len(logger.events(limit=2)) == 2


def test_logger_bounded_ring(tmp_path):
    logger = AuditLogger(enabled=True, max_entries=3)
    for i in range(5):
        logger.record("governance", "cost_check", "denied", details={"i": i})
    assert logger.count() == 3
    assert logger.events()[0]["details"]["i"] == 2


def test_logger_from_config_defaults_disabled():
    assert AuditLogger.from_config({}).enabled is False
    assert AuditLogger.from_config(None).enabled is False
    enabled = AuditLogger.from_config({"enabled": True, "max_entries": 5})
    assert enabled.enabled is True
    assert enabled.max_entries == 5


def test_logger_close_stops_recording():
    logger = AuditLogger(enabled=True)
    logger.close()
    assert logger.record("config", "startup", "success") is None
    assert logger.count() == 0


# -- API integration -------------------------------------------------------

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
    def __init__(self, results):
        self._results = list(results)

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return self._results.pop(0)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _success():
    return {
        "response": "answer",
        "failure_tags": [],
        "cost": {"estimated_cost_usd": 0.001},
        "latency": {"total_ms": 5.0},
        "observability": {"status": "success"},
    }


def _denied():
    return {
        "response": None,
        "error": "cost limit exceeded",
        "failure_type": "cost_limit_exceeded",
        "failure_tags": ["cost_limit_exceeded"],
        "cost": {"estimated_cost_usd": 0.9},
        "latency": {"total_ms": 5.0},
        "observability": {"status": "failed", "api_key": "sk-live-secret"},
    }


def _tmp_configs(tmp_path: Path, *, audit_enabled: bool, audit_path: str = ""):
    return {
        "models_config_path": _write(tmp_path / "models.yaml", MODELS_YAML),
        "retrieval_config_path": _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML),
        "prompt_config_path": REPO_PROMPT,
        "observability_config_path": _write(
            tmp_path / "observability.yaml", "redact_sensitive_data: true\n"
        ),
        "governance_config_path": _write(
            tmp_path / "governance.yaml",
            "enabled: true\nmax_cost_per_request_usd: 0.5\nsafety_margin_tokens: 128\n"
            "avg_chunk_tokens: 300\n",
        ),
        "api_config_path": _write(
            tmp_path / "api.yaml",
            "require_api_key: false\napi_key: \"\"\nallow_rebuild: false\n"
            "history_max_runs: 1000\ntrace_store_max: 500\nmax_batch_size: 25\n",
        ),
        "audit_config_path": _write(
            tmp_path / "audit.yaml",
            f"enabled: {'true' if audit_enabled else 'false'}\n"
            f"path: {json.dumps(audit_path)}\nmax_entries: 100\n",
        ),
        "persistence_config_path": _write(tmp_path / "persistence.yaml", "backend: memory\n"),
    }


def _app(config_paths, results):
    scripted = _ScriptedPipeline(results)

    def builder(**_ignored):
        return scripted

    return create_app(pipeline_builder=builder, **config_paths)


def test_api_audit_records_governance_denial(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    with TestClient(
        _app(_tmp_configs(tmp_path, audit_enabled=True, audit_path=str(audit_path)), [_denied()])
    ) as client:
        client.post("/v1/query", json={"query": "expensive"}, headers={"X-Request-ID": "rid-1"})
        body = client.get("/v1/audit").json()

    assert body["enabled"] is True
    governance_events = [e for e in body["events"] if e["event_type"] == "governance"]
    assert len(governance_events) == 1
    assert governance_events[0]["outcome"] == "denied"
    assert governance_events[0]["request_id"] == "rid-1"
    assert governance_events[0]["details"]["failure_type"] == "cost_limit_exceeded"
    # Persistence: JSONL file written and never contains a secret.
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(line)["event_type"] == "governance" for line in lines)
    assert "sk-live-secret" not in audit_path.read_text(encoding="utf-8")


def test_api_audit_successful_query_records_no_governance_event(tmp_path):
    with TestClient(
        _app(_tmp_configs(tmp_path, audit_enabled=True), [_success()])
    ) as client:
        client.post("/v1/query", json={"query": "cheap"})
        body = client.get("/v1/audit").json()

    assert all(e["event_type"] != "governance" for e in body["events"])
    # Only the startup config event should exist.
    assert {e["event_type"] for e in body["events"]} == {"config"}


def test_api_audit_disabled_by_default(tmp_path):
    with TestClient(
        _app(_tmp_configs(tmp_path, audit_enabled=False), [_denied()])
    ) as client:
        client.post("/v1/query", json={"query": "expensive"})
        body = client.get("/v1/audit").json()

    assert body["enabled"] is False
    assert body["events"] == []
    assert body["total"] == 0


def test_api_audit_event_type_filter(tmp_path):
    with TestClient(
        _app(_tmp_configs(tmp_path, audit_enabled=True), [_denied()])
    ) as client:
        client.post("/v1/query", json={"query": "expensive"})
        only_config = client.get("/v1/audit", params={"event_type": "config"}).json()
        only_governance = client.get("/v1/audit", params={"event_type": "governance"}).json()

    assert all(e["event_type"] == "config" for e in only_config["events"])
    assert len(only_governance["events"]) == 1


def test_api_audit_503_without_lifespan(tmp_path):
    client = TestClient(_app(_tmp_configs(tmp_path, audit_enabled=True), []))
    response = client.get("/v1/audit")

    assert response.status_code == 503
    assert response.json()["failure_type"] == "not_ready"
