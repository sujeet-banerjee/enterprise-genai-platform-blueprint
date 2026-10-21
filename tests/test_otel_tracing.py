"""Tests for issue #47: OTel-native tracing export.

Acceptance:
- pipeline stages emit OTLP spans under a root ``pipeline.run`` span,
- span attributes carry request id / models / top_k / failure tags,
- logs carry the trace/span id for correlation,
- tracing is config-driven (observability.yaml ``otel:`` block) and a complete
  no-op when disabled (zero overhead),
- the compose profile ships an OTel collector + Jaeger backend.

``opentelemetry-*`` is an optional extra; the genuine span tests use the SDK's
in-memory exporter and skip when the SDK is absent (CI installs only
requirements.txt), while the disabled-path / packaging tests always run.
"""

from pathlib import Path

import pytest
import yaml

from core.services import telemetry
from core.services.observability import PipelineObservabilityTracker
from core.services.telemetry import OTEL_STAGE_SPANS, OtelTracer, build_otel_tracer

REPO_BASE = Path(__file__).resolve().parents[1]
DEPLOYMENT = REPO_BASE / "deployment"

otel_installed = telemetry._OTEL_AVAILABLE
requires_otel = pytest.mark.skipif(not otel_installed, reason="opentelemetry-sdk not installed")


def _tracer_with_exporter():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    tracer = OtelTracer(service_name="test-svc", exporter=exporter)
    return tracer, exporter


# --- availability & factory -------------------------------------------------


def test_otel_available_flag_matches_sdk():
    from core.services.telemetry import OtelTracer as _T

    tracer = _T()
    assert tracer.is_available() == telemetry._OTEL_AVAILABLE


def test_build_otel_tracer_disabled_returns_none():
    assert build_otel_tracer(None) is None
    assert build_otel_tracer({}) is None
    assert build_otel_tracer({"enabled": False}) is None


@requires_otel
def test_build_otel_tracer_enabled_returns_tracer():
    tracer = build_otel_tracer(
        {"enabled": True, "service_name": "svc-a", "sample_ratio": 0.5}
    )
    assert tracer is not None
    assert tracer.service_name == "svc-a"
    assert tracer.sample_ratio == 0.5
    tracer.force_flush()


def test_build_otel_tracer_enabled_but_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr(telemetry, "_OTEL_AVAILABLE", False)
    assert build_otel_tracer({"enabled": True}) is None


# --- genuine span export ----------------------------------------------------


@requires_otel
def test_root_span_with_nested_stage_children():
    tracer, exporter = _tracer_with_exporter()
    tracker = PipelineObservabilityTracker(observability_config_path=None, otel=tracer)
    with tracker.measure_stage("embedding"):
        pass
    with tracker.measure_stage("retrieval"):
        pass
    with tracker.measure_stage("llm_generation"):
        pass
    tracker.get_latency_report()
    tracker.log_trace({"status": "success"})

    tracer.force_flush()
    spans = {s.name: s for s in exporter.get_finished_spans()}
    root = spans["pipeline.run"]
    assert root.parent is None
    for stage in ("embedding", "retrieval", "llm_generation"):
        child = spans[f"pipeline.{stage}"]
        assert child.parent is not None
        assert child.parent.span_id == root.context.span_id
        assert child.context.trace_id == root.context.trace_id


@requires_otel
def test_root_span_carries_pipeline_attributes():
    tracer, exporter = _tracer_with_exporter()
    tracker = PipelineObservabilityTracker(observability_config_path=None, otel=tracer)
    tracker.set_trace_attribute("top_k", 5)
    tracker.set_trace_attribute("retriever", "HybridRetriever")
    tracker.set_trace_attribute("llm_model", "qwen")
    tracker.set_trace_attribute("embedding_model", "minilm")
    with tracker.measure_stage("embedding"):
        pass
    tracker.add_failure_tag("low_score")
    tracker.get_latency_report()
    tracker.log_trace({"status": "degraded"})

    tracer.force_flush()
    root = next(s for s in exporter.get_finished_spans() if s.name == "pipeline.run")
    attrs = dict(root.attributes or {})
    assert attrs["top_k"] == 5
    assert attrs["retriever"] == "HybridRetriever"
    assert attrs["llm_model"] == "qwen"
    assert attrs["embedding_model"] == "minilm"
    assert "low_score" in attrs["failure_tags"]
    assert attrs["request_id"] == tracker.request_id


@requires_otel
def test_logs_carry_trace_and_span_ids():
    tracer, _ = _tracer_with_exporter()
    tracker = PipelineObservabilityTracker(observability_config_path=None, otel=tracer)
    with tracker.measure_stage("embedding"):
        pass
    captured = {}

    class _Rec:
        pass

    original = tracker.logger.info

    def _capture(msg, *args, **kwargs):  # pragma: no cover - trivial wrapper
        captured["msg"] = msg % args if args else msg
        original(msg, *args, **kwargs)

    tracker.logger.info = _capture
    tracker.log_trace({"status": "success"})
    assert "trace_id=" in captured["msg"]
    assert "span_id=" in captured["msg"]


@requires_otel
def test_end_trace_closes_and_is_idempotent():
    tracer, exporter = _tracer_with_exporter()
    tracker = PipelineObservabilityTracker(observability_config_path=None, otel=tracer)
    with tracker.measure_stage("embedding"):
        pass
    tracker.end_trace()
    tracker.end_trace()  # idempotent
    tracer.force_flush()
    names = [s.name for s in exporter.get_finished_spans()]
    assert names.count("pipeline.run") == 1


# --- disabled path / zero overhead ------------------------------------------


def test_disabled_tracker_is_a_noop():
    tracker = PipelineObservabilityTracker(observability_config_path=None)
    assert tracker.otel is None
    with tracker.measure_stage("embedding"):
        pass
    tracker.set_trace_attribute("top_k", 3)  # no-op, must not raise
    tracker.add_failure_tag("x")
    tracker.end_trace()
    assert tracker.trace_context() == {"trace_id": None, "span_id": None}


def test_trace_context_empty_when_tracing_off():
    tracker = PipelineObservabilityTracker(observability_config_path=None)
    assert tracker.trace_context() == {"trace_id": None, "span_id": None}


def test_span_contextmanager_noop_when_unavailable(monkeypatch):
    monkeypatch.setattr(telemetry, "_OTEL_AVAILABLE", False)
    tracer = OtelTracer()
    assert tracer.is_available() is False
    with tracer.span("x", {"a": 1}) as span:
        assert span is None
    assert tracer.current_ids() == {"trace_id": None, "span_id": None}


# --- config-driven ----------------------------------------------------------


def test_tracker_builds_tracer_from_observability_config(tmp_path):
    cfg = tmp_path / "observability.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "log_level": "INFO",
                "redact_sensitive_data": True,
                "otel": {"enabled": True, "service_name": "from-config"},
            }
        ),
        encoding="utf-8",
    )
    tracker = PipelineObservabilityTracker(observability_config_path=str(cfg))
    if otel_installed:
        assert tracker.otel is not None
        assert tracker.otel.service_name == "from-config"
        tracker.otel.force_flush()
    else:
        assert tracker.otel is None


def test_disabled_observability_config_yields_no_tracer(tmp_path):
    cfg = tmp_path / "observability.yaml"
    cfg.write_text(
        yaml.safe_dump({"otel": {"enabled": False}}), encoding="utf-8"
    )
    tracker = PipelineObservabilityTracker(observability_config_path=str(cfg))
    assert tracker.otel is None


def test_stage_span_constants_cover_pipeline_stages():
    assert "embedding" in OTEL_STAGE_SPANS
    assert "retrieval" in OTEL_STAGE_SPANS
    assert "llm_generation" in OTEL_STAGE_SPANS


# --- packaging / deployment pack --------------------------------------------


def test_observability_yaml_ships_disabled_otel_block():
    cfg = yaml.safe_load(
        (REPO_BASE / "config" / "observability.yaml").read_text(encoding="utf-8")
    )
    assert cfg["otel"]["enabled"] is False
    assert "endpoint" in cfg["otel"]
    assert cfg["otel"]["sample_ratio"] == 1.0


def test_otel_schema_accepts_block_and_rejects_unknown(tmp_path):
    from core.config.validator import validate_config_data

    ok = {
        "otel": {
            "enabled": True,
            "endpoint": "http://localhost:4318/v1/traces",
            "service_name": "svc",
            "sample_ratio": 0.25,
        }
    }
    assert validate_config_data(ok, "observability") == []
    bad = {"otel": {"enabled": True, "bogus": 1}}
    assert validate_config_data(bad, "observability") != []


def test_compose_ships_otel_collector_and_jaeger():
    compose = yaml.safe_load(
        (DEPLOYMENT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    assert "otel-collector" in services
    assert "jaeger" in services
    assert services["otel-collector"]["profiles"] == ["observability"]
    assert services["jaeger"]["profiles"] == ["observability"]
    assert services["api"]["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"]


def test_otel_collector_config_is_valid_and_exports_to_jaeger():
    cfg = yaml.safe_load(
        (DEPLOYMENT / "observability" / "otel-collector" / "config.yml").read_text(
            encoding="utf-8"
        )
    )
    assert "otlp" in cfg["receivers"]
    exporters = cfg["exporters"]
    assert any("jaeger" in name for name in exporters)
    traces = cfg["service"]["pipelines"]["traces"]
    assert "otlp" in traces["receivers"]
    assert any("jaeger" in e for e in traces["exporters"])


def test_observability_extra_declares_otel_packages():
    pyproject = (REPO_BASE / "pyproject.toml").read_text(encoding="utf-8")
    assert "opentelemetry-api" in pyproject
    assert "opentelemetry-sdk" in pyproject
    assert "opentelemetry-exporter-otlp-proto-http" in pyproject
