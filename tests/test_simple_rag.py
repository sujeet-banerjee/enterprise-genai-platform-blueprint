import pytest

from core.config.generation_config import GenerationConfig
from core.implementations.simple_embedder import SimpleEmbedder
from core.implementations.simple_retriever import SimpleRetriever
from core.implementations.dummy_llm import DummyLLM
from core.implementations.dummy_evaluator import DummyEvaluator  # if still used
from pathlib import Path

from core.evaluation.metrics import Metrics
from core.evaluation.evaluation_engine import EvaluationEngine
from core.services.prompt_builder import PromptBuilder

from core.services.token_budget_service import TokenBudgetService
from core.services.cost_tracker import CostTracker

from app.pipeline import RAGPipeline

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_CONFIG_PATH = BASE_DIR / "config" / "prompt_config.yaml"

def build_pipeline(docs):
    '''
    Helper test method to build the pipeline from docs

    :param docs:
    :return:
    '''
    prompt_builder = PromptBuilder(str(PROMPT_CONFIG_PATH))
    embedder = SimpleEmbedder()
    retriever = SimpleRetriever(docs=docs, embedder=embedder)

    llm = DummyLLM()
    metrics = Metrics()
    evaluator = EvaluationEngine(metrics)
    token_budget_service = TokenBudgetService()
    cost_tracker = CostTracker()

    pipeline = RAGPipeline(
        embedder=embedder,
        prompt_builder=prompt_builder,  # or your actual PromptBuilder
        retriever=retriever,
        llm=llm,
        token_budget_service=token_budget_service,
        evaluator=evaluator,
        generation_config=GenerationConfig(max_tokens=512),
        cost_tracker=cost_tracker
    )

    return pipeline


def _do_pipline_invoke(docs: list[dict[str, str]], query: str):
    '''
    Helper test method to invoke the pipeline with docs

    :param docs:
    :param query:
    :return:
    '''
    pipeline = build_pipeline(docs)
    result = pipeline.run(query)

    # --- Basic assertions ---
    assert "response" in result
    assert "retrieved_docs" in result
    assert "metrics" in result

    # --- Retrieval assertions ---
    assert len(result["retrieved_docs"]) > 0

    # At least one doc should contain "intelligence" or "AI"
    retrieved_text = " ".join(result["retrieved_docs"]).lower()
    print("\n===============================")
    print(f"Query: {query}")
    print(f"Retrieved Text: {retrieved_text}")
    assert "intelligence" in retrieved_text or "ai" in retrieved_text

    # --- Metrics assertions ---
    metrics = result["metrics"]
    print(f"Metrics: {metrics}")
    assert "context_precision" in metrics
    assert metrics["context_precision"] >= 0
    return result


def test_real_rag_basic_flow_qry_explain_ai():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."}
    ]
    query = "What is AI?"
    _do_pipline_invoke(docs, query)


def test_real_rag_basic_flow_qry_explain_artificial_intelligence():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."}
    ]
    query = "What is artificial intelligence?"
    _do_pipline_invoke(docs, query)


def test_real_rag_basic_flow_qry_Explain_intelligence():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."}
    ]
    query = "Explain Intelligence?"
    _do_pipline_invoke(docs, query)

def test_real_rag_basic_flow_qry_Neural_networks():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."}
    ]
    query = "What are Neural networks?"
    _do_pipline_invoke(docs, query)


def test_real_rag_basic_flow_qry_which_technique_inspired_by_human_brain():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."}
    ]
    query = "Which technique is inspired by human brain?"
    _do_pipline_invoke(docs, query)


def test_real_rag_basic_flow_qry_explain_quantum_computing_HIGH():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."},
        {"content": "Quantum computing is inspired by Schrodinger's cat!"}
    ]
    query = "Explain Quantum Computing?"
    _do_pipline_invoke(docs, query)


def test_real_rag_basic_flow_qry_explain_quantum_computing_LOW():
    docs = [
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."},
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
    ]
    query = "Explain Quantum Computing?"
    _do_pipline_invoke(docs, query)


def test_real_rag_query_variation_changes_retrieval():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI."},
        {"content": "Neural networks model brain-like structures."}
    ]
    query1_ai = "What is AI?"
    query2_nn = "What are neural networks?"

    pipeline = build_pipeline(docs)
    result_ai = _do_pipline_invoke(docs, query1_ai)
    result_nn = _do_pipline_invoke(docs, query2_nn)

    docs_ai = " ".join(result_ai["retrieved_docs"]).lower()
    docs_nn = " ".join(result_nn["retrieved_docs"]).lower()

    # Expect different retrieval behavior
    assert docs_ai != docs_nn


def test_real_rag_top_k_effect():
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI."},
        {"content": "Deep learning uses neural networks."},
        {"content": "Statistics is used in data science."}
    ]

    embedder = SimpleEmbedder()
    retriever = SimpleRetriever(docs=docs, embedder=embedder)
    query_embedding = embedder.embed("What is AI?")

    docs_k1 = retriever.retrieve(query_embedding, top_k=1)
    docs_k3 = retriever.retrieve(query_embedding, top_k=3)

    assert len(docs_k1) == 1
    assert len(docs_k3) == 3