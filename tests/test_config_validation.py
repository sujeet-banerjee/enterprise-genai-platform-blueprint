"""Tests for issue #46: config schema + validation + secrets management.

Covers the acceptance criteria:
- an invalid config (bad type / unknown key / missing required-value type) fails
  fast with a precise message,
- ``config validate`` exits non-zero on invalid config and zero on all shipped
  configs,
- ``${ENV_VAR}`` / ``env:VAR`` refs resolve from the environment, a missing ref
  fails fast, and resolved secrets are never emitted by ``/v1/config`` (redaction),
- all shipped ``config/*.yaml`` validate against their schemas,
- existing (partial) configs keep validating (backward compatibility).
"""

import json
from pathlib import Path

import pytest
import yaml

from app.config_validate import main as validate_main
from core.config.secrets import (
    SecretResolutionError,
    find_secret_refs,
    resolve_secrets,
)
from core.config.validator import (
    ConfigError,
    ConfigValidationError,
    load_and_validate,
    validate_all,
    validate_config_data,
    validate_config_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _write_yaml(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


# -- schemas: shipped configs all valid -----------------------------------


def test_all_shipped_configs_validate():
    results = validate_all(CONFIG_DIR)
    # Every schema-backed shipped config is present and valid.
    assert set(results) == {
        "access_control.yaml",
        "api.yaml",
        "audit.yaml",
        "governance.yaml",
        "guardrails.yaml",
        "models.yaml",
        "observability.yaml",
        "prompt_config.yaml",
        "resilience.yaml",
        "retrieval.yaml",
        "tenants.yaml",
        "identity.yaml",
    }
    for name, issues in results.items():
        hard = [i for i in issues if i.kind != "version-warning"]
        assert hard == [], f"{name} has issues: {hard}"


def test_cli_exits_zero_on_shipped_configs(capsys):
    assert validate_main([]) == 0
    out = capsys.readouterr()
    assert "OK" in out.out


def test_cli_json_output(capsys):
    assert validate_main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["results"]["retrieval.yaml"]["valid"] is True


# -- schema: type + unknown-key errors ------------------------------------


def test_type_error_is_reported(tmp_path):
    path = _write_yaml(tmp_path / "governance.yaml", {"enabled": "not-a-bool"})
    issues = validate_config_file(path)
    assert issues
    assert any("enabled" in i.path for i in issues)


def test_unknown_top_level_key_is_rejected(tmp_path):
    path = _write_yaml(
        tmp_path / "api.yaml", {"require_api_key": False, "totally_unknown_key": 1}
    )
    issues = validate_config_file(path)
    joined = " ".join(str(i) for i in issues)
    assert "totally_unknown_key" in joined


def test_validator_does_not_mutate_input():
    data = {"enabled": True, "avg_chunk_tokens": 128}
    validate_config_data(data, "governance")
    assert data == {"enabled": True, "avg_chunk_tokens": 128}


def test_partial_config_still_valid(tmp_path):
    # Backward compatibility: a minimal partial config validates (defaults fill in).
    path = _write_yaml(tmp_path / "governance.yaml", {"enabled": True})
    assert [i for i in validate_config_file(path) if i.kind != "version-warning"] == []


def test_load_and_validate_raises_on_invalid(tmp_path):
    path = _write_yaml(tmp_path / "retrieval.yaml", {"retrieval": {"top_k": "three"}})
    with pytest.raises(ConfigValidationError) as excinfo:
        load_and_validate(path)
    assert "top_k" in str(excinfo.value)


def test_load_and_validate_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_and_validate(tmp_path / "nope.yaml")


def test_cli_exits_nonzero_on_invalid(tmp_path, capsys):
    bad = _write_yaml(tmp_path / "api.yaml", {"max_batch_size": "lots"})
    assert validate_main([str(bad)]) == 1
    err = capsys.readouterr().err
    assert "max_batch_size" in err


def test_cli_exits_two_on_unparseable(tmp_path):
    bad = tmp_path / "api.yaml"
    bad.write_text("::: not: valid: yaml: [", encoding="utf-8")
    assert validate_main([str(bad)]) == 2


# -- secrets ---------------------------------------------------------------


def test_find_secret_refs():
    data = {
        "a": "${OPENAI_API_KEY}",
        "b": "env:HF_TOKEN",
        "c": ["plain", "${ANOTHER}"],
        "d": {"nested": "env:DEEP"},
    }
    assert set(find_secret_refs(data)) == {
        "OPENAI_API_KEY",
        "HF_TOKEN",
        "ANOTHER",
        "DEEP",
    }


def test_resolve_secrets_brace_and_scheme():
    env = {"OPENAI_API_KEY": "sk-secret", "HF_TOKEN": "hf_abc"}
    resolved = resolve_secrets({"a": "${OPENAI_API_KEY}", "b": "env:HF_TOKEN"}, env)
    assert resolved == {"a": "sk-secret", "b": "hf_abc"}


def test_resolve_secrets_missing_raises():
    with pytest.raises(SecretResolutionError) as excinfo:
        resolve_secrets({"a": "${MISSING_KEY}"}, {})
    assert "MISSING_KEY" in str(excinfo.value)


def test_config_with_secret_ref_valid_when_present(tmp_path):
    path = _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "api_key": "${OPENAI_API_KEY}"}},
        },
    )
    issues = validate_config_file(path, environ={"OPENAI_API_KEY": "sk-test"})
    assert [i for i in issues if i.kind != "version-warning"] == []


def test_config_with_secret_ref_fails_when_missing(tmp_path):
    path = _write_yaml(
        tmp_path / "api.yaml",
        {"require_api_key": True, "api_key": "${OPENAI_API_KEY}"},
    )
    issues = validate_config_file(path, environ={})
    assert any(i.kind == "secret" for i in issues)


def test_load_and_validate_resolves_secret(tmp_path):
    path = _write_yaml(
        tmp_path / "audit.yaml", {"enabled": True, "path": "${AUDIT_PATH}"}
    )
    data = load_and_validate(path, environ={"AUDIT_PATH": "/var/log/audit.jsonl"})
    assert data["path"] == "/var/log/audit.jsonl"


# -- version drift warning -------------------------------------------------


def test_future_config_version_is_warning_not_error(tmp_path):
    path = _write_yaml(
        tmp_path / "governance.yaml", {"config_version": 999, "enabled": True}
    )
    issues = validate_config_file(path)
    assert [i.kind for i in issues] == ["version-warning"]
    # Warning alone must not fail loading.
    assert load_and_validate(path)["enabled"] is True


# -- redaction: resolved secrets never leak --------------------------------


def test_resolved_secret_redacted_from_effective_config(tmp_path):
    """A resolved secret must not appear in the introspection output (#46 + #16)."""
    from app.introspection import _read_yaml  # noqa: F401  (ensures import path)
    from core.services.observability import SensitiveDataRedactor

    resolved = resolve_secrets(
        {"api": {"api_key": "${SECRET_TOKEN}"}}, {"SECRET_TOKEN": "sk-live-1234567890"}
    )
    redacted = SensitiveDataRedactor(enabled=True).redact_obj(resolved)
    assert "sk-live-1234567890" not in json.dumps(redacted)
    assert redacted["api"]["api_key"] == "[REDACTED]"


# -- composition root fails fast ------------------------------------------


def _dummy_models(tmp_path, *, active="dummy"):
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": active,
            "active_embedding_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )


def _dummy_retrieval(tmp_path):
    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "top_k": 3,
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "evaluation": {"enabled": False},
            "reranking": {"enabled": False},
        },
    )


def test_build_pipeline_fails_fast_on_invalid_models_config(tmp_path):
    from app.main import build_pipeline

    bad_models = _write_yaml(
        tmp_path / "models.yaml",
        {"active_model": "dummy", "models": {"dummy": {"provider": "dummy"}}, "bogus_key": 1},
    )
    with pytest.raises(ConfigValidationError) as excinfo:
        build_pipeline(
            models_config_path=bad_models,
            retrieval_config_path=_dummy_retrieval(tmp_path),
        )
    assert "bogus_key" in str(excinfo.value)


def test_build_pipeline_succeeds_with_valid_minimal_config(tmp_path):
    from app.main import build_pipeline

    pipeline = build_pipeline(
        models_config_path=_dummy_models(tmp_path),
        retrieval_config_path=_dummy_retrieval(tmp_path),
    )
    assert type(pipeline.llm).__name__ == "DummyLLM"


def test_load_config_resolves_secret_env(tmp_path, monkeypatch):
    from app.main import _load_config

    monkeypatch.setenv("MY_SECRET_PATH", "/tmp/audit.jsonl")
    path = _write_yaml(tmp_path / "audit.yaml", {"enabled": True, "path": "${MY_SECRET_PATH}"})
    loaded = _load_config(path)
    assert loaded["path"] == "/tmp/audit.jsonl"


def test_load_config_missing_secret_fails_fast(tmp_path):
    from app.main import _load_config

    path = _write_yaml(tmp_path / "audit.yaml", {"enabled": True, "path": "${DEFINITELY_NOT_SET}"})
    with pytest.raises(ConfigValidationError) as excinfo:
        _load_config(path)
    assert "DEFINITELY_NOT_SET" in str(excinfo.value)

