"""Guardrail introspection endpoint (issue #86).

``GET /v1/guardrails`` exposes the guardrail chains the registry resolves from
the effective ``guardrails.yaml``: the master toggle, the registered providers,
and each chain entry with its provider, edge and **effective** options. The
chains are previewable while the feature is disabled so an operator can see what
enabling it would run; a bad entry in a disabled config is reported in
``errors`` instead of turning the read-only endpoint into a 500.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from core.interfaces.guardrail import BaseGuardrail, GuardrailContext, GuardrailResult
from core.registry.guardrail_registry import GuardrailRegistry

DISABLED = {"enabled": False, "input": [], "output": []}


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _make_app(tmp_path: Path, guardrails_cfg: dict) -> TestClient:
    models = _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "emb-a",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {"emb-a": {"provider": "dummy", "model_name": "emb-a"}},
        },
    )
    retrieval = _write_yaml(
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
    guardrails = _write_yaml(tmp_path / "guardrails.yaml", guardrails_cfg)
    observability = _write_yaml(
        tmp_path / "observability.yaml", {"redact_sensitive_data": True}
    )

    return TestClient(
        create_app(
            models_config_path=models,
            retrieval_config_path=retrieval,
            guardrails_config_path=guardrails,
            observability_config_path=observability,
        )
    )


# -- unit: the contract every provider inherits ---------------------------


class _ThirdPartyGuardrail(BaseGuardrail):
    """A provider that does not override ``_options`` (no introspection code)."""

    name = "third_party"

    def check(self, text: str, context: GuardrailContext) -> GuardrailResult:
        return GuardrailResult.allow()


def test_base_describe_covers_providers_without_custom_options():
    described = _ThirdPartyGuardrail().describe()

    assert described == {
        "provider": "third_party",
        "type": "_ThirdPartyGuardrail",
        "stage": None,
        "options": {},
    }


# -- endpoint --------------------------------------------------------------


def test_guardrails_endpoint_defaults_to_disabled(tmp_path):
    with _make_app(tmp_path, DISABLED) as client:
        response = client.get("/v1/guardrails")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["input"] == []
    assert body["output"] == []
    assert body["errors"] == []
    for provider in ("noop", "deny_list", "schema_validator", "injection", "pii"):
        assert provider in body["providers"]


def test_configured_chains_are_previewable_while_disabled(tmp_path):
    cfg = {
        "enabled": False,
        "input": [{"provider": "deny_list", "terms": ["internal-only"]}],
        "output": [{"provider": "schema_validator", "expect_json": True}],
    }
    with _make_app(tmp_path, cfg) as client:
        body = client.get("/v1/guardrails").json()

    assert body["enabled"] is False
    assert [g["provider"] for g in body["input"]] == ["deny_list"]
    assert body["input"][0]["stage"] == "input"
    assert body["input"][0]["options"]["terms"] == ["internal-only"]
    assert [g["provider"] for g in body["output"]] == ["schema_validator"]
    assert body["output"][0]["stage"] == "output"
    assert body["output"][0]["options"]["expect_json"] is True


def test_injection_guardrail_reports_effective_options(tmp_path):
    cfg = {
        "enabled": True,
        "input": [
            {
                "provider": "injection",
                "sensitivity": "high",
                "trust_retrieved_documents": True,
                "neutralize_mode": "mask",
            }
        ],
    }
    with _make_app(tmp_path, cfg) as client:
        body = client.get("/v1/guardrails").json()

    entry = body["input"][0]
    assert entry["type"] == "InjectionGuardrail"
    assert entry["stage"] == "input"
    assert entry["options"]["sensitivity"] == "high"
    assert entry["options"]["trust_retrieved_documents"] is True
    assert entry["options"]["neutralize_mode"] == "mask"
    assert entry["options"]["classifier"] is None


def test_pii_guardrail_reports_classes_mode_and_mask(tmp_path):
    cfg = {
        "enabled": True,
        "output": [
            {"provider": "pii", "classes": ["email"], "mode": "redact", "mask": "<email>"}
        ],
    }
    with _make_app(tmp_path, cfg) as client:
        body = client.get("/v1/guardrails").json()

    entry = body["output"][0]
    assert entry["provider"] == "pii"
    assert entry["type"] == "PiiGuardrail"
    assert entry["stage"] == "output"
    assert entry["options"] == {
        "classes": ["email"],
        "mode": "redact",
        "mask": "<email>",
    }


def test_per_entry_stage_override_is_reported(tmp_path):
    cfg = {
        "enabled": True,
        "input": [{"provider": "deny_list", "terms": ["x"], "stage": "output"}],
    }
    with _make_app(tmp_path, cfg) as client:
        body = client.get("/v1/guardrails").json()

    assert body["input"][0]["stage"] == "output"


def test_chain_order_is_preserved_for_shorthand_entries(tmp_path):
    cfg = {"enabled": True, "input": ["deny_list", "noop"]}
    with _make_app(tmp_path, cfg) as client:
        body = client.get("/v1/guardrails").json()

    assert [g["provider"] for g in body["input"]] == ["deny_list", "noop"]
    assert body["output"] == []


def test_unknown_provider_in_disabled_config_is_reported_not_fatal(tmp_path):
    cfg = {"enabled": False, "input": [{"provider": "does-not-exist"}]}
    with _make_app(tmp_path, cfg) as client:
        response = client.get("/v1/guardrails")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["input"] == []
    assert len(body["errors"]) == 1
    assert "does-not-exist" in body["errors"][0]


def test_guardrails_requires_lifespan(tmp_path):
    client = _make_app(tmp_path, DISABLED)
    response = client.get("/v1/guardrails")

    assert response.status_code == 503
    body = response.json()
    assert body["failure_type"] == "not_ready"
    assert body["request_id"]


def test_openapi_exposes_typed_guardrail_models(tmp_path):
    with _make_app(tmp_path, DISABLED) as client:
        schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/v1/guardrails"]["get"]
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/GuardrailsResponse")
    assert "GuardrailInfo" in schema["components"]["schemas"]


def test_listing_matches_the_registry_single_source_of_truth(tmp_path):
    cfg = {
        "enabled": True,
        "input": [{"provider": "injection", "sensitivity": "low"}],
        "output": [{"provider": "deny_list", "terms": ["secret"], "mask": "[MASKED]"}],
    }
    with _make_app(tmp_path, cfg) as client:
        body = client.get("/v1/guardrails").json()

    expected = GuardrailRegistry(str(tmp_path / "guardrails.yaml")).describe()
    assert body == expected


def test_deny_list_does_not_echo_the_matched_value(tmp_path):
    # Labels/reasons feed traces, the failure envelope and the audit trail, so a
    # deny list that targets personal data or a credential must not leak the
    # matched span (issue #54 policy; regression guard for #86).
    cfg = {
        "enabled": True,
        "output": [{"provider": "deny_list", "terms": ["correct-horse-battery"]}],
    }
    with _make_app(tmp_path, cfg) as client:
        response = client.post("/v1/query", json={"query": "correct-horse-battery"})

    assert response.status_code == 403
    body = response.json()
    assert body["failure_type"] == "guardrail_output_blocked"
    decision = body["guardrail_decisions"][0]
    assert decision["labels"] == ["deny_list:match"]
    assert "correct-horse-battery" not in decision["reason"]
    assert all("correct-horse-battery" not in tag for tag in body["failure_tags"])


@pytest.mark.parametrize("section", ["input", "output"])
def test_empty_section_is_an_empty_chain(tmp_path, section):
    cfg = {"enabled": True, "input": [], "output": [], section: []}
    with _make_app(tmp_path, cfg) as client:
        body = client.get("/v1/guardrails").json()

    assert body["input"] == []
    assert body["output"] == []
