from fastapi import FastAPI
from pydantic import BaseModel

from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_evaluator import DummyEvaluator

from app.pipeline import RAGPipeline
from core.services.cost_tracker import CostTracker

app = FastAPI()

pipeline = RAGPipeline(
    embedder=DummyEmbedder(),
    retriever=DummyRetriever(),
    llm=DummyLLM(),
    evaluator=DummyEvaluator(),
    cost_tracker=CostTracker()
)


class QueryRequest(BaseModel):
    query: str


@app.post("/query")
def query_endpoint(request: QueryRequest):
    return pipeline.run(request.query)