"""Tests for issue #34: governance and observability live in their own config files.

Acceptance criteria:
1. ``config/governance.yaml`` and ``config/observability.yaml`` exist and
   ``config/retrieval.yaml`` no longer carries the ``governance`` /
   ``observability`` sections.
2. ``build_pipeline`` / ``RAGPipeline`` load them from explicit paths, with a
   legacy fallback to the inline sections inside ``retrieval.yaml``.
"""

from pathlib import Path

import pytest
import yaml

from app.main import build_pipeline
from core.services.observability import PipelineObservabilityTracker

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path, context_window: int = 4096) -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {
                "dummy": {
                    "provider": "dummy",
                    "context_window": context_window,
                    "temperature": 0.0,
                }
            },
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )


def _retrieval_config(tmp_path: Path, extra: dict | None = None) -> str:
    payload: dict = {
        "retrieval": {
            "default_retriever": "dummy",
            "top_k": 3,
            "similarity_metric": "cosine",
            "retrievers": {"dummy": {"provider": "dummy"}},
        },
        "evaluation": {
            "enabled": True,
            "active_evaluator": "dummy",
            "evaluators": {"dummy": {"provider": "dummy"}},
        },
        "reranking": {"strategy": "lexical_hybrid", "top_k": 3},
        "token_budget": {"default_mode": "strict", "max_output_cap": 512},
    }
    if extra:
        payload.update(extra)
    return _write_yaml(tmp_path / "retrieval.yaml", payload)


def _retrieval_config_inline(tmp_path: Path, governance: dict, observability: dict) -> str:
    return _retrieval_config(
        tmp_path,
        {
            "governance": governance,
            "observability": observability,
        },
    )


def test_repo_config_files_moved_out_of_retrieval():
    governance = yaml.safe_load((CONFIG_DIR / "governance.yaml").read_text(encoding="utf-8"))
    observability = yaml.safe_load((CONFIG_DIR / "observability.yaml").read_text(encoding="utf-8"))
    retrieval = yaml.safe_load((CONFIG_DIR / "retrieval.yaml").read_text(encoding="utf-8"))

    assert governance["enabled"] is True
    assert "max_cost_per_request_usd" in governance
    assert observability["redact_sensitive_data"] is True
    assert "sensitive_patterns" in observability

    assert "governance" not in retrieval
    assert "observability" not in retrieval


def test_pipeline_reads_governance_from_dedicated_file(make_pipeline, tmp_path):
    gov = _write_yaml(tmp_path / "governance.yaml", {"enabled": True, "avg_chunk_tokens": 999})

    pipeline = make_pipeline(governance_config_path=gov)

    assert pipeline.avg_chunk_tokens == 999


def test_pipeline_reads_observability_from_dedicated_file(make_pipeline, tmp_path):
    obs = _write_yaml(
        tmp_path / "observability.yaml",
        {"low_retrieval_score_threshold": 0.77, "redact_sensitive_data": True},
    )

    pipeline = make_pipeline(observability_config_path=obs)

    assert pipeline.low_score_threshold == pytest.approx(0.77)


def test_pipeline_falls_back_to_legacy_inline_sections(make_pipeline, tmp_path):
    config = _retrieval_config_inline(
        tmp_path,
        governance={"enabled": True, "avg_chunk_tokens": 555},
        observability={"low_retrieval_score_threshold": 0.55},
    )

    pipeline = make_pipeline(config_path=config)

    assert pipeline.avg_chunk_tokens == 555
    assert pipeline.low_score_threshold == pytest.approx(0.55)


def test_dedicated_file_overrides_legacy_inline_sections(make_pipeline, tmp_path):
    config = _retrieval_config_inline(
        tmp_path,
        governance={"enabled": True, "avg_chunk_tokens": 111},
        observability={"low_retrieval_score_threshold": 0.11},
    )
    gov = _write_yaml(tmp_path / "governance.yaml", {"enabled": True, "avg_chunk_tokens": 222})
    obs = _write_yaml(tmp_path / "observability.yaml", {"low_retrieval_score_threshold": 0.22})

    pipeline = make_pipeline(
        config_path=config,
        governance_config_path=gov,
        observability_config_path=obs,
    )

    assert pipeline.avg_chunk_tokens == 222
    assert pipeline.low_score_threshold == pytest.approx(0.22)


def test_tracker_uses_dedicated_observability_file(tmp_path):
    obs = _write_yaml(
        tmp_path / "observability.yaml",
        {"redact_sensitive_data": False, "sensitive_patterns": ["secret"]},
    )

    tracker = PipelineObservabilityTracker(config_path=None, observability_config_path=obs)

    assert tracker._redactor.enabled is False
    assert tracker._redactor.redact_text("secret=abc") == "secret=abc"


def test_tracker_dedicated_file_drives_patterns(tmp_path):
    obs = _write_yaml(
        tmp_path / "observability.yaml",
        {"redact_sensitive_data": True, "sensitive_patterns": ["accountnumber"]},
    )

    tracker = PipelineObservabilityTracker(config_path=None, observability_config_path=obs)

    redacted = tracker._redactor.redact_text("accountnumber: 12345")
    assert "12345" not in redacted
    assert "accountnumber" in redacted


def test_tracker_legacy_inline_section_still_supported(tmp_path):
    config = _write_yaml(
        tmp_path / "retrieval.yaml",
        {"observability": {"redact_sensitive_data": False, "sensitive_patterns": ["secret"]}},
    )

    tracker = PipelineObservabilityTracker(config_path=config)

    assert tracker._redactor.enabled is False


def test_build_pipeline_governance_from_dedicated_file(tmp_path):
    gov = _write_yaml(
        tmp_path / "governance.yaml",
        {"enabled": True, "max_cost_per_request_usd": 0.05, "safety_margin_tokens": 200},
    )
    obs = _write_yaml(
        tmp_path / "observability.yaml",
        {"low_retrieval_score_threshold": 0.25, "redact_sensitive_data": True},
    )

    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
        governance_config_path=Path(gov),
        observability_config_path=Path(obs),
    )

    assert pipeline.cost_governor is not None
    assert pipeline.retrieval_policy_service is not None
    assert pipeline.governance_config_path == gov
    assert pipeline.observability_config_path == obs


def test_build_pipeline_governance_disabled_via_dedicated_file(tmp_path):
    gov = _write_yaml(tmp_path / "governance.yaml", {"enabled": False})

    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
        governance_config_path=Path(gov),
    )

    assert pipeline.cost_governor is None
    assert pipeline.retrieval_policy_service is None


def test_build_pipeline_legacy_inline_governance_still_works(tmp_path):
    config = _retrieval_config(
        tmp_path,
        {"governance": {"enabled": False, "max_cost_per_request_usd": 0.05}},
    )

    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(config),
    )

    assert pipeline.cost_governor is None
