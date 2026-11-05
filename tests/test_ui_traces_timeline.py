"""UX4: Traces timeline/waterfall tests (#133)."""

from __future__ import annotations

from pathlib import Path

from ui import traces


def test_trace_timeline_builds_from_latency_stages():
    item = {
        "latency": {
            "total_ms": 100.0,
            "stages": {
                "embedding": {"ms": 10},
                "retrieval": {"ms": 20},
                "llm_generation": {"ms": 60},
            },
        },
        "observability": {"request_id": "req-1", "otel": {"trace_id": "t1", "span_id": "s1"}},
    }
    tl = traces.build_timeline(item)
    assert tl
    stages = [r["stage"] for r in tl]
    assert "embedding" in stages and "llm_generation" in stages
    assert any(r["pct"] >= 0 for r in tl)
    flt = traces.span_filters(tl)
    assert "embedding" in flt
    ctx = traces.trace_context(item)
    assert ctx.get("trace_id") == "t1"


def test_redaction_safe_view_strips_secrets():
    trace = {"request_id": "r1", "api_key": "sk-secret", "nested": {"token": "abc"}}
    safe = traces.redaction_safe_view(trace)
    assert safe["api_key"] == "[REDACTED]"
    assert safe["nested"]["token"] == "[REDACTED]"


def test_traces_screen_wired():
    src = Path("ui/app.py").read_text(encoding="utf-8")
    assert "build_timeline" in src
    assert "Timeline / waterfall" in src
    assert "redaction_safe_view" in src
