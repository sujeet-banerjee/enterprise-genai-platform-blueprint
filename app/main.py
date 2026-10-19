from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.registry.evaluator_registry import EvaluatorRegistry
from core.registry.model_registry import ModelRegistry
from core.registry.reranker_registry import RerankerRegistry
from core.registry.retriever_registry import RetrieverRegistry
from core.services.cost_governor import CostGovernor
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.retrieval_policy_service import RetrievalPolicyService
from core.services.token_budget_service import TokenBudgetService

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_CONFIG_PATH = BASE_DIR / "config" / "prompt_config.yaml"
MODELS_CONFIG_PATH = BASE_DIR / "config" / "models.yaml"
RETRIEVAL_CONFIG_PATH = BASE_DIR / "config" / "retrieval.yaml"
GOVERNANCE_CONFIG_PATH = BASE_DIR / "config" / "governance.yaml"
OBSERVABILITY_CONFIG_PATH = BASE_DIR / "config" / "observability.yaml"


def _load_config(config_path: Path) -> dict:
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _generation_config_from_model(model_cfg: dict) -> GenerationConfig:
    """
    Derive GenerationConfig from the active model's configuration so
    temperature / max_tokens / top_p / stop are tunable via models.yaml
    (issue #12). ``max_new_tokens`` (HuggingFace naming) is honored as a
    fallback for ``max_tokens``. Defaults match GenerationConfig's own.
    """
    max_tokens = int(model_cfg.get("max_tokens") or model_cfg.get("max_new_tokens") or 256)
    return GenerationConfig(
        temperature=float(model_cfg.get("temperature", 0.7)),
        top_p=float(model_cfg.get("top_p", 0.9)),
        max_tokens=max_tokens,
        stop=model_cfg.get("stop"),
    )


def build_pipeline(
    models_config_path: Path = MODELS_CONFIG_PATH,
    prompt_config_path: Path = PROMPT_CONFIG_PATH,
    retrieval_config_path: Path = RETRIEVAL_CONFIG_PATH,
    governance_config_path: Optional[Path] = None,
    observability_config_path: Optional[Path] = None,
) -> RAGPipeline:
    """
    Composition root: assemble the RAG pipeline by resolving every pluggable
    component from configuration. Embedder/LLM come from ModelRegistry, the
    retriever from RetrieverRegistry, the reranker from RerankerRegistry and the
    evaluator from EvaluatorRegistry — so swapping vendors is a config change and
    this module never imports a concrete implementation.
    """
    model_registry = ModelRegistry(str(models_config_path))
    retriever_registry = RetrieverRegistry(str(retrieval_config_path))
    reranker_registry = RerankerRegistry(str(retrieval_config_path))
    evaluator_registry = EvaluatorRegistry(str(retrieval_config_path))

    retrieval_config = _load_config(retrieval_config_path)
    # Governance lives in its own file (issue #34); fall back to the legacy
    # inline section in retrieval.yaml when no dedicated file is configured.
    governance_config = _load_config(governance_config_path) if governance_config_path else {}
    if not governance_config:
        governance_config = retrieval_config.get("governance") or {}

    active_llm = model_registry.get_active_model()
    embedder = model_registry.get_active_embedder()
    retriever = retriever_registry.create(embedder=embedder)
    reranker = reranker_registry.create()
    evaluator = evaluator_registry.create()

    prompt_builder = PromptBuilder(str(prompt_config_path))
    active_model_config = model_registry.get_active_model_config()
    generation_config = _generation_config_from_model(active_model_config)
    token_budget_service = TokenBudgetService(config_path=str(retrieval_config_path))

    # Per-model pricing from models.yaml: the active model's rates are passed
    # explicitly and a keyed map covers models whose model_name differs from
    # their config key (issue #14).
    model_pricing: dict = {}
    for _name, _cfg in (model_registry.config.get("models") or {}).items():
        _cfg = _cfg or {}
        if "input_cost_per_1k" in _cfg or "output_cost_per_1k" in _cfg:
            _entry = {
                "input_cost_per_1k": _cfg.get("input_cost_per_1k"),
                "output_cost_per_1k": _cfg.get("output_cost_per_1k"),
            }
            model_pricing[_name] = _entry
            model_pricing.setdefault(str(_cfg.get("model_name", _name)), _entry)
    cost_tracker = CostTracker(
        input_cost_per_1k=active_model_config.get("input_cost_per_1k"),
        output_cost_per_1k=active_model_config.get("output_cost_per_1k"),
        model_pricing=model_pricing,
    )

    # Governance services wired into the composition root so every request is cost- and
    # token-governed. Both are optional in RAGPipeline, so the pipeline stays vendor-neutral.
    # ``governance.enabled`` gates whether they are attached at all (default: enabled).
    governance_enabled = bool(governance_config.get("enabled", True))
    if governance_enabled:
        cost_governor = CostGovernor(
            max_cost_per_request=float(governance_config.get("max_cost_per_request_usd", 1.0))
        )
        retrieval_policy_service = RetrievalPolicyService(
            context_window=active_llm.context_window,
            system_prompt_tokens=token_budget_service.estimate_tokens(prompt_builder.system_prompt),
            reserved_output_tokens=generation_config.max_tokens,
            safety_margin=int(governance_config.get("safety_margin_tokens", 200)),
        )
    else:
        cost_governor = None
        retrieval_policy_service = None

    return RAGPipeline(
        embedder=embedder,
        prompt_builder=prompt_builder,
        retriever=retriever,
        llm=active_llm,
        evaluator=evaluator,
        token_budget_service=token_budget_service,
        generation_config=generation_config,
        cost_tracker=cost_tracker,
        reranker=reranker,
        config_path=str(retrieval_config_path),
        cost_governor=cost_governor,
        retrieval_policy_service=retrieval_policy_service,
        governance_config_path=str(governance_config_path) if governance_config_path else None,
        observability_config_path=(
            str(observability_config_path) if observability_config_path else None
        ),
    )


pipeline = build_pipeline(
    governance_config_path=GOVERNANCE_CONFIG_PATH,
    observability_config_path=OBSERVABILITY_CONFIG_PATH,
)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The user query to run through the RAG pipeline.")


@app.post("/query")
def query_endpoint(request: QueryRequest):
    return pipeline.run(request.query)
