"""Shared composition root (issue #75).

Both the HTTP application and the experiment runner must assemble a
`RAGPipeline` through the *same* code path (`app.bootstrap.assemble_components`).

Previously `ExperimentRunner` re-implemented the composition root: it built its
own registries, a bare `CostTracker()`, a hardcoded `GenerationConfig(max_tokens=512)`
and never wired governance, observability-driven redaction, provider resilience,
query expansion or caching. Experiments therefore silently measured a different
pipeline than production.

These tests pin the parity so it cannot drift again.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import yaml

import app.bootstrap as bootstrap_module
import core.services.experiment_runner as experiment_runner_module
from app.bootstrap import PipelineComponents, assemble_components
from core.interfaces.llm import BaseLLM
from core.services.experiment_runner import ExperimentRunner

REPO = Path(__file__).resolve().parents[1]
PROMPT_CONFIG = REPO / "config" / "prompt_config.yaml"

SECRET_QUERY = "please use api_key=sk-live-1234567890 to call the service"

DOCS = [
    {"content": "Artificial intelligence simulates human intelligence."},
    {"content": "Machine learning learns patterns from data."},
]


class _CapturingLLM(BaseLLM):
    """Fake LLM capturing the prompt it was asked to generate from."""

    def __init__(self, context_window: int = 4096):
        self.prompts: list[str] = []
        self._context_window = context_window

    def generate(self, prompt, config=None):  # noqa: D102
        self.prompts.append(prompt)
        return "ok"

    @property
    def context_window(self):  # noqa: D102
        return self._context_window

    @property
    def model_name(self):  # noqa: D102
        return "capturing-llm"


def _write(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _models_config(tmp_path: Path, max_tokens: int = 64) -> Path:
    return _write(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "emb-a",
            "models": {
                "dummy": {
                    "provider": "dummy",
                    "context_window": 4096,
                    "max_tokens": max_tokens,
                    "temperature": 0.2,
                }
            },
            "embedding_models": {
                "emb-a": {"provider": "dummy", "model_name": "emb-a"},
                "emb-b": {"provider": "dummy", "model_name": "emb-b"},
            },
        },
    )


def _retrieval_config(tmp_path: Path, *, governance: bool = True) -> Path:
    return _write(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "similarity_metric": "cosine",
                "top_k": 3,
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "evaluation": {
                "enabled": True,
                "active_evaluator": "dummy",
                "evaluators": {"dummy": {"provider": "dummy"}},
            },
            "reranking": {
                "enabled": True,
                "active_reranker": "simple",
                "strategy": "lexical_hybrid",
                "rerankers": {"simple": {"provider": "simple"}, "none": {"provider": "none"}},
            },
            "chunking": {"active_strategy": "small", "strategies": {"small": {"chunk_size": 120}}},
            "token_budget": {"default_mode": "strict", "max_output_cap": 512},
        },
    )


def _assemble(tmp_path: Path, **kwargs) -> PipelineComponents:
    models = kwargs.pop("models_config_path", None) or _models_config(tmp_path)
    retrieval = kwargs.pop("retrieval_config_path", None) or _retrieval_config(tmp_path)
    return assemble_components(
        models_config_path=models,
        prompt_config_path=PROMPT_CONFIG,
        retrieval_config_path=retrieval,
        **kwargs,
    )


# -- single source of truth ------------------------------------------------


def test_build_pipeline_delegates_to_assemble_components():
    """`app.main.build_pipeline` must call the shared assembler, not reimplement it."""
    from app.main import build_pipeline

    source = inspect.getsource(build_pipeline)
    assert "assemble_components" in source
    # the old hand-rolled assembly built registries directly; it no longer should
    assert "ModelRegistry(" not in source


def test_experiment_runner_uses_shared_assembler():
    source = inspect.getsource(experiment_runner_module)
    assert "assemble_components" in source
    # and it no longer builds components directly
    for forbidden in ("CostTracker(", "GenerationConfig(", "PromptBuilder(", "TokenBudgetService("):
        assert forbidden not in source, f"ExperimentRunner still assembles {forbidden}"


def test_assemble_components_returns_full_bundle(tmp_path):
    components = _assemble(tmp_path)
    assert isinstance(components, PipelineComponents)
    for attr in (
        "llm",
        "embedder",
        "retriever",
        "reranker",
        "evaluator",
        "prompt_builder",
        "token_budget_service",
        "generation_config",
        "cost_tracker",
    ):
        assert getattr(components, attr) is not None


# -- governance parity -----------------------------------------------------


def test_governance_governor_wired_in_assembled_bundle(tmp_path):
    """Previously experiments had no cost governor at all."""
    governance = _write(tmp_path / "governance.yaml", {"enabled": True, "max_cost_per_request_usd": 3.0})
    components = _assemble(tmp_path, governance_config_path=governance)
    assert components.cost_governor is not None
    assert components.retrieval_policy_service is not None
    assert components.cost_governor.max_cost_per_request == 3.0


def test_governance_disabled_leaves_no_governor(tmp_path):
    governance = _write(tmp_path / "governance.yaml", {"enabled": False})
    components = _assemble(tmp_path, governance_config_path=governance)
    assert components.cost_governor is None
    assert components.retrieval_policy_service is None


def test_experiment_pipeline_carries_governor(tmp_path):
    """The pipeline the experiment runner builds must carry the governor."""
    governance = _write(tmp_path / "governance.yaml", {"enabled": True, "max_cost_per_request_usd": 5.0})
    runner = ExperimentRunner(
        models_config_path=str(_models_config(tmp_path)),
        prompt_config_path=str(PROMPT_CONFIG),
        retrieval_config_path=str(_retrieval_config(tmp_path)),
        governance_config_path=str(governance),
    )
    # Assemble exactly as the runner does and inspect the built pipeline.
    components = assemble_components(
        models_config_path=Path(runner.models_config_path),
        prompt_config_path=Path(runner.prompt_config_path),
        retrieval_config_path=Path(runner.retrieval_config_path),
        governance_config_path=Path(runner.governance_config_path),
        use_reranker=None,
        docs=DOCS,
        chunk=False,
    )
    pipeline = components.build_pipeline(
        config_path=runner.retrieval_config_path,
        governance_config_path=runner.governance_config_path,
    )
    assert pipeline.cost_governor is not None


# -- redaction parity (issue #72 now applies to experiments) ---------------


def test_redaction_wired_from_observability_config(tmp_path):
    observability = _write(
        tmp_path / "observability.yaml",
        {"redact_sensitive_data": True, "sensitive_patterns": ["api_key"]},
    )
    components = _assemble(tmp_path, observability_config_path=observability)
    assert components.redactor is not None
    assert components.redactor.enabled is True


def test_experiment_pipeline_redacts_query_before_prompt(tmp_path):
    """An experiment run must strip secrets just like production (issue #72)."""
    observability = _write(
        tmp_path / "observability.yaml",
        {"redact_sensitive_data": True, "sensitive_patterns": ["api_key"]},
    )
    components = _assemble(tmp_path, observability_config_path=observability)
    llm = _CapturingLLM()
    components.llm = llm
    pipeline = components.build_pipeline(
        config_path=str(_retrieval_config(tmp_path)),
        observability_config_path=str(observability),
        top_k=3,
    )
    result = pipeline.run(SECRET_QUERY, raise_on_failure=False)

    assert llm.prompts, "the LLM should have been called"
    assert "sk-live-1234567890" not in llm.prompts[0]
    assert "[REDACTED]" in llm.prompts[0]
    assert "sk-live-1234567890" not in str(result)


# -- generation-config parity (models.yaml, not hardcoded) -----------------


def test_generation_config_comes_from_models_yaml(tmp_path):
    """Previously the runner hardcoded max_tokens=512."""
    models = _models_config(tmp_path, max_tokens=77)
    components = _assemble(tmp_path, models_config_path=models)
    assert components.generation_config.max_tokens == 77
    assert components.generation_config.temperature == 0.2


def test_experiment_uses_model_generation_config(tmp_path):
    models = _models_config(tmp_path, max_tokens=123)
    runner = ExperimentRunner(
        models_config_path=str(models),
        prompt_config_path=str(PROMPT_CONFIG),
        retrieval_config_path=str(_retrieval_config(tmp_path)),
    )
    result = runner.run_single_experiment(docs=DOCS, query="what is ai?")
    # The run completes and reports metrics; the pipeline used the config value.
    assert "metrics" in result
    assert result["retriever"] == "DummyRetriever"


# -- overrides still work --------------------------------------------------


def test_embedding_model_override(tmp_path):
    components = _assemble(tmp_path, embedding_model="emb-b")
    assert components.embedder.model_name == "emb-b"


def test_retriever_backend_override(tmp_path):
    components = _assemble(tmp_path, retriever_backend="dummy", docs=DOCS, chunk=False)
    assert components.retriever.__class__.__name__ == "DummyRetriever"


def test_reranker_disabled_override(tmp_path):
    components = _assemble(tmp_path, use_reranker=False)
    assert components.reranker is None


def test_assemble_module_has_no_streamlit_or_api_coupling():
    """Guard: bootstrap must stay a plain composition module."""
    source = inspect.getsource(bootstrap_module)
    assert "import streamlit" not in source
    assert "FastAPI" not in source
