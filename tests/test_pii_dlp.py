"""PII / DLP detection and redaction (issue #54, Workstream B3).

The B1 guardrail framework (#52) gave the pipeline an ordered input/output
safety seam. This slice adds *personal data* to it: regex detectors for email,
phone, credit card (Luhn validated), national id and IP, an optional injected
NER detector for names/addresses, a ``pii`` guardrail provider (redact vs
block), and PII scrubbing for traces/logs/the config view.

Everything stays disabled by default, and only the PII **class** and a
**count** ever leave the detector - the matched value never reaches a trace,
an audit event or the response body.

Covers: detection per class, Luhn validation, per-class toggles, overlap
resolution, the detector-free defaults, the guardrail (redact/block/custom
mask/no-value labels), the registry resolution (off by default), the
trace/log redactor, pipeline integration on both edges, the governed 403, the
audit trail, and the config schema.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.implementations.pii_detector import (
    NerPiiDetector,
    RegexPiiDetector,
    build_pii_detector,
    luhn_valid,
)
from core.implementations.pii_guardrail import PiiGuardrail
from core.interfaces.guardrail import DECISION_BLOCK, DECISION_REDACT, GuardrailContext
from core.interfaces.pii import (
    PII_CREDIT_CARD,
    PII_EMAIL,
    PII_IP_ADDRESS,
    PII_NATIONAL_ID,
    PII_PERSON_NAME,
    PII_PHONE,
    apply_pii_masks,
    mask_token,
    resolve_overlaps,
)
from core.registry.guardrail_registry import GuardrailRegistry
from core.registry.pii_registry import PiiRegistry
from core.services.observability import SensitiveDataRedactor

REPO = Path(__file__).resolve().parents[1]
PROMPT_CONFIG = REPO / "config" / "prompt_config.yaml"
VALID_CARD = "4111 1111 1111 1111"
INVALID_CARD = "4111 1111 1111 1112"


# -- detectors -------------------------------------------------------------


def test_detects_email():
    matches = RegexPiiDetector().detect("contact jane.doe+ops@example.co.uk today")
    assert [m.pii_class for m in matches] == [PII_EMAIL]
    assert matches[0].value == "jane.doe+ops@example.co.uk"


@pytest.mark.parametrize(
    "phone",
    ["+1 555-123-4567", "(555) 123-4567", "555-123-4567", "5551234567", "555 123 4567"],
)
def test_detects_phone_formats(phone):
    matches = RegexPiiDetector(classes=[PII_PHONE]).detect(f"call {phone} now")
    assert [m.pii_class for m in matches] == [PII_PHONE]
    assert phone in matches[0].value


def test_detects_credit_card_only_when_luhn_valid():
    detector = RegexPiiDetector(classes=[PII_CREDIT_CARD])
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
    assert detector.detect(f"card {VALID_CARD}")[0].pii_class == PII_CREDIT_CARD
    assert detector.detect(f"card {INVALID_CARD}") == []


def test_detects_national_id_and_honours_custom_patterns():
    assert RegexPiiDetector(classes=[PII_NATIONAL_ID]).detect("ssn 123-45-6789")
    custom = RegexPiiDetector(
        classes=[PII_NATIONAL_ID], national_id_patterns=[r"\bNH-\d{6}\b"]
    )
    matches = custom.detect("id NH-123456 here")
    assert [m.pii_class for m in matches] == [PII_NATIONAL_ID]
    assert matches[0].value == "NH-123456"


def test_detects_ip_addresses():
    detector = RegexPiiDetector(classes=[PII_IP_ADDRESS])
    assert detector.detect("host 10.0.0.7 up")[0].value == "10.0.0.7"
    assert detector.detect("v6 2001:0db8:85a3:0000:0000:8a2e:0370:7334")[0].value


def test_per_class_toggles_only_report_selected_classes():
    text = "jane@example.com and 555-123-4567"
    only_email = RegexPiiDetector(classes=[PII_EMAIL]).detect(text)
    assert [m.pii_class for m in only_email] == [PII_EMAIL]
    only_phone = RegexPiiDetector(classes=[PII_PHONE]).detect(text)
    assert [m.pii_class for m in only_phone] == [PII_PHONE]


def test_no_false_positives_on_benign_text():
    detector = RegexPiiDetector()
    for text in (
        "the meeting is on 2024-01-15",
        "order 12345 shipped",
        "artificial intelligence simulates human intelligence",
        "version 1.2.3",
    ):
        assert detector.detect(text) == [], text


def test_overlap_resolution_prefers_higher_priority_class():
    matches = RegexPiiDetector().detect("ssn 123-45-6789")
    assert [m.pii_class for m in matches] == [PII_NATIONAL_ID]
    # The card is one span, not several phone-like fragments.
    card_matches = RegexPiiDetector().detect(f"card {VALID_CARD}")
    assert [m.pii_class for m in card_matches] == [PII_CREDIT_CARD]
    assert len(card_matches) == 1


def test_resolve_overlaps_drops_contained_spans():
    from core.interfaces.pii import PiiMatch

    outer = PiiMatch(PII_CREDIT_CARD, 0, 10, "4111111111")
    inner = PiiMatch(PII_PHONE, 2, 8, "111111")
    assert resolve_overlaps([inner, outer]) == [outer]


def test_empty_text_and_empty_classes():
    assert RegexPiiDetector().detect("") == []
    assert RegexPiiDetector(classes=[]).detect("jane@example.com") == []


def test_ner_detector_uses_injected_extractor():
    def _extract(text):
        return [("PERSON", 0, 4, text[:4])]

    matches = NerPiiDetector(entity_extractor=_extract).detect("Jane lives here")
    assert [m.pii_class for m in matches] == [PII_PERSON_NAME]
    assert matches[0].value == "Jane"


def test_build_detector_composes_regex_and_ner(monkeypatch):
    import core.implementations.pii_detector as module

    monkeypatch.setattr(
        module,
        "build_spacy_ner_detector",
        lambda model, classes: NerPiiDetector(
            entity_extractor=lambda text: [("PERSON", 0, 4, text[:4])], classes=classes
        ),
    )
    detector = build_pii_detector(
        classes=[PII_EMAIL, PII_PERSON_NAME], ner={"enabled": True}
    )
    found = {m.pii_class for m in detector.detect("Jane jane@example.com")}
    assert found == {PII_PERSON_NAME, PII_EMAIL}


# -- mask helpers ----------------------------------------------------------


def test_apply_masks_and_mask_token():
    detector = RegexPiiDetector(classes=[PII_EMAIL])
    matches = detector.detect("mail jane@example.com now")
    assert apply_pii_masks("mail jane@example.com now", matches) == (
        "mail [REDACTED_EMAIL] now"
    )
    assert mask_token("credit_card") == "[REDACTED_CREDIT_CARD]"


# -- guardrail -------------------------------------------------------------


def test_guardrail_redact_mode_rewrites_and_reports_counts():
    guardrail = PiiGuardrail(classes=[PII_EMAIL], mode="redact")
    result = guardrail.check("mail jane@example.com", GuardrailContext(stage="output"))
    assert result.allowed and result.decision == DECISION_REDACT
    assert result.text == "mail [REDACTED_EMAIL]"
    assert result.labels == ["pii:email"]
    assert result.details == {"classes": {"email": 1}, "total": 1}


def test_guardrail_block_mode_blocks():
    guardrail = PiiGuardrail(classes=[PII_CREDIT_CARD], mode="block")
    result = guardrail.check(f"pay {VALID_CARD}", GuardrailContext(stage="input"))
    assert not result.allowed and result.decision == DECISION_BLOCK
    assert "credit_card" in (result.reason or "")
    assert result.labels == ["pii:credit_card"]


def test_guardrail_invalid_mode_raises():
    with pytest.raises(ValueError):
        PiiGuardrail(mode="obliterate")


def test_guardrail_custom_mask_and_allow_when_clean():
    guardrail = PiiGuardrail(classes=[PII_EMAIL], mask="<email>")
    assert guardrail.check("a@b.co", GuardrailContext()).text == "<email>"
    assert guardrail.check("no pii here", GuardrailContext()).allowed


def test_guardrail_never_leaks_matched_value():
    guardrail = PiiGuardrail(classes=[PII_EMAIL, PII_PHONE], mode="block")
    secret = "jane.doe@example.com"
    result = guardrail.check(f"mail {secret} or 555-123-4567", GuardrailContext())
    blob = repr(result)
    assert secret not in blob
    assert "555-123-4567" not in blob
    assert result.details["classes"] == {"email": 1, "phone": 1}


# -- registries ------------------------------------------------------------


def test_guardrail_registry_exposes_pii_provider():
    registry = GuardrailRegistry(str(REPO / "config" / "guardrails.yaml"))
    assert "pii" in registry.list_providers()
    assert registry.is_enabled() is False
    assert registry.build_output_chain() == []


def test_guardrail_registry_builds_pii_from_config(tmp_path):
    path = tmp_path / "guardrails.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "enabled": True,
                "output": [
                    {
                        "provider": "pii",
                        "classes": ["email"],
                        "mode": "redact",
                        "mask": "<x>",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    chain = GuardrailRegistry(str(path)).build_output_chain()
    assert len(chain) == 1 and isinstance(chain[0], PiiGuardrail)
    assert chain[0].check("a@b.co", GuardrailContext()).text == "<x>"


def test_guardrail_registry_unknown_provider_still_raises(tmp_path):
    path = tmp_path / "guardrails.yaml"
    path.write_text(
        yaml.safe_dump({"enabled": True, "input": [{"provider": "nope"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        GuardrailRegistry(str(path)).build_input_chain()


def test_pii_registry_defaults_disabled():
    registry = PiiRegistry(config={})
    assert registry.is_enabled() is False
    assert registry.build_detector() is None


def test_pii_registry_reads_policy():
    registry = PiiRegistry(
        config={
            "pii": {
                "enabled": True,
                "classes": ["email", "phone"],
                "mode": "block",
                "mask": "<m>",
            }
        }
    )
    assert registry.is_enabled() is True
    assert registry.classes() == ["email", "phone"]
    assert registry.mode() == "block"
    assert registry.mask() == "<m>"
    detector = registry.build_detector()
    assert detector is not None
    assert [m.pii_class for m in detector.detect("a@b.co 555-123-4567")] == [
        PII_EMAIL,
        PII_PHONE,
    ]


# -- trace / log redactor --------------------------------------------------


def test_redactor_scrubs_pii_in_text_and_objects():
    detector = RegexPiiDetector(classes=[PII_EMAIL])
    redactor = SensitiveDataRedactor(pii_detector=detector, pii_classes=[PII_EMAIL])
    assert redactor.redact_text("mail jane@example.com") == "mail [REDACTED_EMAIL]"
    scrubbed = redactor.redact_obj({"note": "jane@example.com", "n": 5})
    assert scrubbed == {"note": "[REDACTED_EMAIL]", "n": 5}


def test_redactor_without_detector_is_unchanged():
    redactor = SensitiveDataRedactor()
    assert redactor.redact_text("jane@example.com") == "jane@example.com"


def test_redactor_survives_detector_failure():
    class _BoomDetector:
        classes = ("email",)

        def detect(self, text):  # noqa: D102
            raise RuntimeError("detector exploded")

    redactor = SensitiveDataRedactor(pii_detector=_BoomDetector(), pii_classes=["email"])
    assert redactor.redact_text("jane@example.com") == "jane@example.com"


# -- pipeline integration --------------------------------------------------


def _build_pipeline(*, input_guardrails=None, output_guardrails=None):
    from app.pipeline import RAGPipeline
    from core.config.generation_config import GenerationConfig
    from core.implementations.dummy_embedder import DummyEmbedder
    from core.implementations.dummy_llm import DummyLLM
    from core.interfaces.retriever import Document
    from core.services.cost_tracker import CostTracker
    from core.services.prompt_builder import PromptBuilder
    from core.services.token_budget_service import TokenBudgetService

    class _Retriever:
        def __init__(self):
            self.docs = [Document(content="Artificial intelligence simulates human intelligence.")]

        def retrieve(self, query_embedding, top_k=3):
            return self.docs

        def retrieve_with_scores(self, query_embedding, top_k=3):
            return [(doc, 1.0) for doc in self.docs]

        @property
        def index_dimension(self):
            return 7

    return RAGPipeline(
        embedder=DummyEmbedder(dimension=7),
        prompt_builder=PromptBuilder(str(PROMPT_CONFIG)),
        retriever=_Retriever(),
        llm=DummyLLM(),
        evaluator=None,
        token_budget_service=TokenBudgetService(policy_mode="strict", config_path=None),
        generation_config=GenerationConfig(max_tokens=32, temperature=0.0),
        cost_tracker=CostTracker(),
        input_guardrails=input_guardrails,
        output_guardrails=output_guardrails,
    )


def test_pipeline_output_guardrail_redacts_response():
    pipeline = _build_pipeline(
        output_guardrails=[PiiGuardrail(classes=[PII_EMAIL], mode="redact")]
    )
    result = pipeline.run("my email is jane@example.com", top_k=1)
    assert "jane@example.com" not in result["response"]
    assert "[REDACTED_EMAIL]" in result["response"]
    decision = result["guardrail_decisions"][0]
    assert decision["guardrail"] == "pii"
    assert decision["details"]["classes"] == {"email": 1}


def test_pipeline_input_guardrail_redacts_query_before_llm():
    pipeline = _build_pipeline(
        input_guardrails=[PiiGuardrail(classes=[PII_EMAIL], mode="redact")]
    )
    result = pipeline.run("my email is jane@example.com", top_k=1)
    assert "jane@example.com" not in result["response"]
    assert "[REDACTED_EMAIL]" in result["response"]


def test_pipeline_block_mode_raises_governed_failure():
    from core.services.guardrails import GuardrailBlockedError

    pipeline = _build_pipeline(
        input_guardrails=[PiiGuardrail(classes=[PII_EMAIL], mode="block")]
    )
    with pytest.raises(GuardrailBlockedError) as excinfo:
        pipeline.run("my email is jane@example.com", top_k=1)
    assert excinfo.value.failure_type == "guardrail_input_blocked"
    assert "jane@example.com" not in str(excinfo.value)


# -- API -------------------------------------------------------------------


def _make_app(tmp_path, guardrails_cfg, observability_cfg=None, audit_cfg=None):
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump(
            {
                "active_model": "dummy",
                "active_embedding_model": "emb-a",
                "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
                "embedding_models": {"emb-a": {"provider": "dummy", "model_name": "emb-a"}},
            }
        ),
        encoding="utf-8",
    )
    retrieval = tmp_path / "retrieval.yaml"
    retrieval.write_text(
        yaml.safe_dump(
            {
                "retrieval": {
                    "default_retriever": "dummy",
                    "top_k": 3,
                    "retrievers": {"dummy": {"provider": "dummy"}},
                },
                "evaluation": {"enabled": False},
                "reranking": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    guardrails = tmp_path / "guardrails.yaml"
    guardrails.write_text(yaml.safe_dump(guardrails_cfg), encoding="utf-8")

    observability = tmp_path / "observability.yaml"
    observability.write_text(
        yaml.safe_dump(observability_cfg or {"redact_sensitive_data": True}),
        encoding="utf-8",
    )
    audit = tmp_path / "audit.yaml"
    audit.write_text(yaml.safe_dump(audit_cfg or {"enabled": False}), encoding="utf-8")

    return TestClient(
        create_app(
            models_config_path=models,
            retrieval_config_path=retrieval,
            prompt_config_path=PROMPT_CONFIG,
            guardrails_config_path=guardrails,
            observability_config_path=observability,
            audit_config_path=audit,
        )
    )


def test_api_pii_block_returns_403(tmp_path):
    app = _make_app(
        tmp_path,
        {
            "enabled": True,
            "input": [{"provider": "pii", "classes": ["email"], "mode": "block"}],
        },
    )
    with app as client:
        response = client.post("/v1/query", json={"query": "mail jane@example.com"})
        assert response.status_code == 403
        body = response.json()
        assert body["failure_type"] == "guardrail_input_blocked"
        assert body["guardrail"] == "pii"
        assert "jane@example.com" not in response.text


def test_api_pii_redact_returns_scrubbed_response(tmp_path):
    app = _make_app(
        tmp_path,
        {
            "enabled": True,
            "output": [{"provider": "pii", "classes": ["email"], "mode": "redact"}],
        },
    )
    with app as client:
        response = client.post("/v1/query", json={"query": "mail jane@example.com"})
        assert response.status_code == 200
        body = response.json()
        assert "jane@example.com" not in body["response"]
        assert "[REDACTED_EMAIL]" in body["response"]


def test_api_records_pii_audit_without_value(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    app = _make_app(
        tmp_path,
        {
            "enabled": True,
            "output": [{"provider": "pii", "classes": ["email"], "mode": "redact"}],
        },
        audit_cfg={"enabled": True, "path": str(audit_path)},
    )
    with app as client:
        response = client.post("/v1/query", json={"query": "mail jane@example.com"})
        assert response.status_code == 200
        events = client.get("/v1/audit", params={"event_type": "pii"}).json()["events"]
        assert events, "expected a PII audit event"
        event = events[-1]
        assert event["event_type"] == "pii"
        assert event["outcome"] == "redacted"
        assert event["details"]["classes"] == ["email"]
        assert event["details"]["counts"] == {"email": 1}
        assert "jane@example.com" not in str(event)


def test_api_observability_pii_block_scrubs_traces(tmp_path):
    app = _make_app(
        tmp_path,
        {"enabled": False},
        observability_cfg={
            "redact_sensitive_data": True,
            "pii": {"enabled": True, "classes": ["email"]},
        },
    )
    with app as client:
        response = client.post("/v1/query", json={"query": "mail jane@example.com"})
        assert response.status_code == 200
        body = response.json()
        assert "jane@example.com" not in str(body.get("observability"))


# -- config ----------------------------------------------------------------


def test_shipped_configs_are_valid_and_pii_disabled():
    from core.config.validator import validate_all

    results = validate_all(REPO / "config")
    assert results, "expected the shipped configs to be validated"
    invalid = {name: issues for name, issues in results.items() if issues}
    assert not invalid, invalid

    observability = yaml.safe_load((REPO / "config" / "observability.yaml").read_text())
    assert observability["pii"]["enabled"] is False
    guardrails = yaml.safe_load((REPO / "config" / "guardrails.yaml").read_text())
    assert guardrails["enabled"] is False


def test_observability_schema_accepts_pii_block():
    from core.config.schema import ObservabilityConfig

    cfg = ObservabilityConfig.model_validate(
        {
            "log_level": "INFO",
            "pii": {
                "enabled": True,
                "classes": ["email", "phone"],
                "mode": "block",
                "ner": {"enabled": False},
            },
        }
    )
    assert cfg.pii is not None and cfg.pii.enabled is True
    with pytest.raises(Exception):
        ObservabilityConfig.model_validate({"pii": {"enabled": True, "unknown": 1}})
