"""Tests for issue #16: observability redaction is config-driven.

Acceptance criteria:
1. ``observability.sensitive_patterns`` from config drives which values are
   redacted (no code change needed to add/remove a pattern).
2. ``observability.redact_sensitive_data: false`` disables redaction entirely.
3. Existing class-level ``SensitiveDataRedactor.redact_text`` behaviour is
   preserved for backwards compatibility.
"""

import pytest
import yaml

from core.services.observability import PipelineObservabilityTracker, SensitiveDataRedactor


def _write_config(tmp_path, observability: dict) -> str:
    path = tmp_path / "retrieval.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "retrieval": {"top_k": 3},
                "observability": observability,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return str(path)


def test_class_level_redact_text_keeps_default_behaviour():
    assert "[REDACTED]" in SensitiveDataRedactor.redact_text(
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    )
    redacted = SensitiveDataRedactor.redact_text("api_key=sk-abc12345")
    assert "sk-abc12345" not in redacted
    assert "[REDACTED]" in redacted


def test_instance_default_patterns_redact_api_key_and_password():
    redactor = SensitiveDataRedactor()
    out = redactor.redact_text("api_key=sk-abc12345 password=hunter2secret")
    assert "sk-abc12345" not in out
    assert "hunter2secret" not in out
    assert "[REDACTED]" in out


def test_configured_patterns_replace_the_defaults():
    redactor = SensitiveDataRedactor(patterns=["ssn"])

    # A default pattern (api_key) is no longer applied...
    assert redactor.redact_text("api_key=sk-abc12345") == "api_key=sk-abc12345"
    # ...while the configured pattern is.
    assert "[REDACTED]" in redactor.redact_text("ssn: 123-45-6789")


def test_configured_pattern_keeps_label_and_redacts_assignment_value():
    redactor = SensitiveDataRedactor(patterns=["ssn"])
    out = redactor.redact_text("ssn=123-45-6789")
    assert out == "ssn=[REDACTED]"


def test_configured_bare_value_pattern_is_redacted():
    redactor = SensitiveDataRedactor(patterns=["sk-[A-Za-z0-9]{8,}"])
    out = redactor.redact_text("token sk-abc12345 here")
    assert "sk-abc12345" not in out
    assert "[REDACTED]" in out


def test_invalid_regex_pattern_falls_back_without_error():
    redactor = SensitiveDataRedactor(patterns=["a(b"])
    # Must not raise; invalid regex is treated as a literal so redaction
    # still removes the offending text.
    out = redactor.redact_text("literal a(b value")
    assert "a(b" not in out
    assert "[REDACTED]" in out


def test_disabled_redactor_returns_text_unchanged():
    redactor = SensitiveDataRedactor(enabled=False)
    text = "api_key=sk-abc12345 password=hunter2secret"
    assert redactor.redact_text(text) == text


def test_disabled_redactor_skips_object_key_heuristic():
    redactor = SensitiveDataRedactor(enabled=False)
    payload = {"password": "hunter2", "nested": {"api_key": "sk-abc12345"}}
    assert redactor.redact_obj(payload) == payload


def test_enabled_redactor_applies_object_key_heuristic():
    redactor = SensitiveDataRedactor()
    sanitized = redactor.redact_obj({"password": "hunter2", "safe": "value"})
    assert sanitized["password"] == redactor.REDACTION_PLACEHOLDER
    assert sanitized["safe"] == "value"


def test_tracker_honors_configured_patterns(tmp_path):
    config_path = _write_config(
        tmp_path, {"redact_sensitive_data": True, "sensitive_patterns": ["ssn"]}
    )
    tracker = PipelineObservabilityTracker(config_path=config_path)

    payload = {"note": "password: hunter2", "personal": "ssn: 123-45-6789"}
    sanitized = tracker.log_trace(payload)

    assert "123-45-6789" not in str(sanitized)
    assert "[REDACTED]" in str(sanitized)
    # "password" is not a configured pattern here (defaults were replaced),
    # so its value survives in a non-key-hint field.
    assert "hunter2" in str(sanitized)


def test_tracker_redaction_can_be_disabled(tmp_path):
    config_path = _write_config(tmp_path, {"redact_sensitive_data": False})
    tracker = PipelineObservabilityTracker(config_path=config_path)
    sanitized = tracker.log_trace({"note": "api_key=sk-abc12345"})
    assert "sk-abc12345" in str(sanitized)


def test_tracker_summarize_documents_honors_config(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"redact_sensitive_data": True, "sensitive_patterns": ["ssn"]},
    )
    tracker = PipelineObservabilityTracker(config_path=config_path)

    class _Doc:
        def __init__(self, content: str, score: float):
            self.content = content
            self.score = score
            self.metadata = {}

    summaries = tracker.summarize_documents([_Doc("personal ssn: 123-45-6789", 0.9)])
    preview = summaries[0]["preview"]
    assert "123-45-6789" not in preview
    assert "[REDACTED]" in preview


def test_tracker_defaults_use_repo_config_for_redaction():
    tracker = PipelineObservabilityTracker(config_path=None)
    sanitized = tracker.log_trace({"note": "api_key=sk-abc12345"})
    assert "sk-abc12345" not in str(sanitized)
    assert "[REDACTED]" in str(sanitized)


@pytest.mark.parametrize("redact", [True, False])
def test_pipeline_honors_redaction_toggle(tmp_path, make_pipeline, redact):
    config_path = _write_config(
        tmp_path,
        {"redact_sensitive_data": redact, "sensitive_patterns": ["ssn"]},
    )
    pipeline = make_pipeline(config_path=config_path)
    result = pipeline.run("my personal id is ssn: 123-45-6789", raise_on_failure=False)
    obs_str = str(result["observability"])

    if redact:
        assert "123-45-6789" not in obs_str
        assert "[REDACTED]" in obs_str
    else:
        assert "123-45-6789" in obs_str
