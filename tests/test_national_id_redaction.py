"""National identifier detection and redaction (issue #162).

The reported bug: a query containing an Indian PAN (``AHSPB3220C``) was
returned unredacted even though input redaction was on. Two independent
defaults caused it: the ``national_id`` detector only matched US SSNs, and
PII scrubbing (``observability.pii.enabled``) is opt-in.

This slice widens the built-in ``national_id`` detector (PAN, Aadhaar with a
Verhoeff checksum, UK National Insurance) while keeping the opt-in posture:
nothing is masked until an operator enables the ``pii`` policy. Matched values
never leave the detector - only a class label appears in the text.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.implementations.pii_detector import RegexPiiDetector, verhoeff_valid
from core.interfaces.pii import PII_NATIONAL_ID
from core.registry.pii_registry import PiiRegistry
from core.services.observability import SensitiveDataRedactor

REPO = Path(__file__).resolve().parents[1]
PROMPT_CONFIG = REPO / "config" / "prompt_config.yaml"
PAN = "AHSPB3220C"
VALID_AADHAAR_PLAIN = "234567890124"
VALID_AADHAAR_SPACED = "2345 6789 0124"


def _detector() -> RegexPiiDetector:
    return RegexPiiDetector(classes=[PII_NATIONAL_ID])


# -- detection -------------------------------------------------------------


def test_pan_is_detected_by_default():
    matches = _detector().detect(f"I am Sujeet Banerjee, my PAN card number is {PAN}.")
    assert [m.pii_class for m in matches] == [PII_NATIONAL_ID]
    assert matches[0].value == PAN


@pytest.mark.parametrize(
    "value",
    [
        PAN,
        "123-45-6789",
        VALID_AADHAAR_PLAIN,
        VALID_AADHAAR_SPACED,
        "AB123456C",
    ],
)
def test_common_national_id_schemes_detected(value):
    matches = _detector().detect(f"id {value} on file")
    assert [m.value for m in matches] == [value]


def test_aadhaar_requires_checksum():
    detector = _detector()
    assert verhoeff_valid(VALID_AADHAAR_PLAIN)
    assert not verhoeff_valid("234567890123")
    assert detector.detect(VALID_AADHAAR_SPACED)
    assert detector.detect("2345 6789 0123") == []
    assert detector.detect("id 234567890123") == []


def test_benign_identifiers_are_not_masked():
    detector = _detector()
    for text in (
        "order ABCDE1234 shipped",
        "the meeting is on 2024-01-15",
        "version 1.2.3",
        "tracking 12345678",
    ):
        assert detector.detect(text) == [], text


def test_custom_national_id_patterns_replace_defaults():
    detector = RegexPiiDetector(
        classes=[PII_NATIONAL_ID], national_id_patterns=[r"\bNH-\d{6}\b"]
    )
    assert detector.detect("id NH-123456 here")
    assert detector.detect(f"my PAN is {PAN}") == []


# -- redaction -------------------------------------------------------------


def test_redactor_masks_pan_in_text_and_objects():
    detector = _detector()
    redactor = SensitiveDataRedactor(
        pii_detector=detector, pii_classes=[PII_NATIONAL_ID]
    )
    assert redactor.redact_text(f"PAN {PAN}") == "PAN [REDACTED_NATIONAL_ID]"
    scrubbed = redactor.redact_obj({"note": f"PAN {PAN}", "n": 5})
    assert scrubbed == {"note": "PAN [REDACTED_NATIONAL_ID]", "n": 5}


def test_pii_registry_builds_national_id_detector_from_config(tmp_path):
    config_path = tmp_path / "observability.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"pii": {"enabled": True, "classes": ["national_id"], "mode": "redact"}}
        ),
        encoding="utf-8",
    )
    registry = PiiRegistry(config_path=str(config_path))
    detector = registry.build_detector()
    assert detector is not None
    redactor = SensitiveDataRedactor(
        pii_detector=detector, pii_classes=registry.classes()
    )
    assert PAN not in redactor.redact_text(f"PAN {PAN}")


# -- end-to-end (opt-in scrubbing) ----------------------------------------


def _make_app(tmp_path, observability_cfg):
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump(
            {
                "active_model": "dummy",
                "active_embedding_model": "emb-a",
                "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
                "embedding_models": {
                    "emb-a": {"provider": "dummy", "model_name": "emb-a"}
                },
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
    observability = tmp_path / "observability.yaml"
    observability.write_text(yaml.safe_dump(observability_cfg), encoding="utf-8")

    return TestClient(
        create_app(
            models_config_path=models,
            retrieval_config_path=retrieval,
            prompt_config_path=PROMPT_CONFIG,
            observability_config_path=observability,
        )
    )


def test_api_masks_pan_when_pii_enabled(tmp_path):
    app = _make_app(
        tmp_path,
        {
            "redact_sensitive_data": True,
            "pii": {"enabled": True, "classes": ["national_id"], "mode": "redact"},
        },
    )
    with app as client:
        response = client.post(
            "/v1/query", json={"query": f"My PAN card number is {PAN}."}
        )
        assert response.status_code == 200
        assert PAN not in response.text
        assert "[REDACTED_NATIONAL_ID]" in response.json()["response"]


def test_api_leaves_pan_when_pii_disabled(tmp_path):
    app = _make_app(tmp_path, {"redact_sensitive_data": True, "pii": {"enabled": False}})
    with app as client:
        response = client.post(
            "/v1/query", json={"query": f"My PAN card number is {PAN}."}
        )
        assert response.status_code == 200
        assert PAN in response.text
