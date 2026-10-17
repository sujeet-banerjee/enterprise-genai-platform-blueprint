from pathlib import Path

import yaml
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.simple_reranker import SimpleReranker
from core.registry.evaluator_registry import EvaluatorRegistry
from core.registry.model_registry import ModelRegistry
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


def _load_retrieval_config() -> dict:
    try:
        with open(RETRIEVAL_CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


model_registry = ModelRegistry(str(MODELS_CONFIG_PATH))
retrieval_config = _load_retrieval_config()
governance_config = retrieval_config.get("governance") or {}

active_llm = model_registry.get_active_model()
prompt_builder = PromptBuilder(str(PROMPT_CONFIG_PATH))
generation_config = GenerationConfig(max_tokens=512)
token_budget_service = TokenBudgetService(policy_mode="strict", config_path=str(RETRIEVAL_CONFIG_PATH))
evaluator_registry = EvaluatorRegistry(str(RETRIEVAL_CONFIG_PATH))
evaluator = evaluator_registry.create()

# Governance services wired into the composition root so every request is cost- and
# token-governed. Both are optional in RAGPipeline, so the pipeline stays vendor-neutral.
cost_governor = CostGovernor(
    max_cost_per_request=float(governance_config.get("max_cost_per_request_usd", 1.0))
)
retrieval_policy_service = RetrievalPolicyService(
    context_window=active_llm.context_window,
    system_prompt_tokens=token_budget_service.estimate_tokens(prompt_builder.system_prompt),
    reserved_output_tokens=generation_config.max_tokens,
    safety_margin=int(governance_config.get("safety_margin_tokens", 200)),
)

pipeline = RAGPipeline(
    embedder=DummyEmbedder(),
    prompt_builder=prompt_builder,
    retriever=DummyRetriever(),
    llm=active_llm,
    evaluator=evaluator,
    token_budget_service=token_budget_service,
    generation_config=generation_config,
    cost_tracker=CostTracker(),
    reranker=SimpleReranker(config_path=str(RETRIEVAL_CONFIG_PATH)),
    config_path=str(RETRIEVAL_CONFIG_PATH),
    cost_governor=cost_governor,
    retrieval_policy_service=retrieval_policy_service,
)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The user query to run through the RAG pipeline.")


@app.post("/query")
def query_endpoint(request: QueryRequest):
    return pipeline.run(request.query)
