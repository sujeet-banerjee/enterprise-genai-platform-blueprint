from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path

from core.config.generation_config import GenerationConfig
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.simple_reranker import SimpleReranker
from core.registry.model_registry import ModelRegistry

from app.pipeline import RAGPipeline
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_CONFIG_PATH = BASE_DIR / "config" / "prompt_config.yaml"
MODELS_CONFIG_PATH = BASE_DIR / "config" / "models.yaml"
RETRIEVAL_CONFIG_PATH = BASE_DIR / "config" / "retrieval.yaml"

model_registry = ModelRegistry(str(MODELS_CONFIG_PATH))

pipeline = RAGPipeline(
    embedder=DummyEmbedder(),
    prompt_builder=PromptBuilder(str(PROMPT_CONFIG_PATH)),
    retriever=DummyRetriever(),
    llm=model_registry.get_active_model(),
    evaluator=DummyEvaluator(),
    token_budget_service=TokenBudgetService(policy_mode="strict", config_path=str(RETRIEVAL_CONFIG_PATH)),
    generation_config=GenerationConfig(max_tokens=512),
    cost_tracker=CostTracker(),
    reranker=SimpleReranker(config_path=str(RETRIEVAL_CONFIG_PATH)),
    config_path=str(RETRIEVAL_CONFIG_PATH),
)


class QueryRequest(BaseModel):
    query: str


@app.post("/query")
def query_endpoint(request: QueryRequest):
    return pipeline.run(request.query)
