from pathlib import Path

from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.implementations.simple_retriever import SimpleRetriever
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_CONFIG_PATH = BASE_DIR / "config" / "prompt_config.yaml"

AI_DOCS = [
    {"content": "Artificial Intelligence is the simulation of human intelligence."},
    {"content": "Machine Learning is a subset of AI focused on learning from data."},
    {"content": "Neural networks are inspired by the human brain."},
]


def build_pipeline(docs, embedder, llm, evaluator):
    retriever = SimpleRetriever(docs=docs, embedder=embedder)
    return RAGPipeline(
        embedder=embedder,
        prompt_builder=PromptBuilder(str(PROMPT_CONFIG_PATH)),
        retriever=retriever,
        llm=llm,
        token_budget_service=TokenBudgetService(),
        evaluator=evaluator,
        generation_config=GenerationConfig(max_tokens=64, temperature=0.0),
        cost_tracker=CostTracker(),
    )


def _invoke_pipeline(docs, query, embedder, llm, evaluator):
    pipeline = build_pipeline(docs, embedder, llm, evaluator)
    result = pipeline.run(query)

    assert "response" in result
    assert isinstance(result["response"], str)
    assert result["response"].strip()
    assert "retrieved_docs" in result
    assert "metrics" in result
    assert len(result["retrieved_docs"]) > 0

    retrieved_text = " ".join(result["retrieved_docs"]).lower()
    assert "intelligence" in retrieved_text or "ai" in retrieved_text

    metrics = result["metrics"]
    assert "context_precision" in metrics
    assert -1.0 <= metrics["context_precision"] <= 1.0
    return result


def test_real_rag_basic_flow_qry_explain_ai(real_embedder, real_llm, semantic_evaluator):
    _invoke_pipeline(AI_DOCS, "What is AI?", real_embedder, real_llm, semantic_evaluator)


def test_real_rag_basic_flow_qry_explain_artificial_intelligence(
    real_embedder, real_llm, semantic_evaluator
):
    _invoke_pipeline(
        AI_DOCS, "What is artificial intelligence?", real_embedder, real_llm, semantic_evaluator
    )


def test_real_rag_basic_flow_qry_Explain_intelligence(
    real_embedder, real_llm, semantic_evaluator
):
    _invoke_pipeline(AI_DOCS, "Explain Intelligence?", real_embedder, real_llm, semantic_evaluator)


def test_real_rag_basic_flow_qry_Neural_networks(real_embedder, real_llm, semantic_evaluator):
    result = _invoke_pipeline(
        AI_DOCS, "What are Neural networks?", real_embedder, real_llm, semantic_evaluator
    )
    retrieved = " ".join(result["retrieved_docs"]).lower()
    assert "neural" in retrieved or "brain" in retrieved


def test_real_rag_basic_flow_qry_which_technique_inspired_by_human_brain(
    real_embedder, real_llm, semantic_evaluator
):
    result = _invoke_pipeline(
        AI_DOCS,
        "Which technique is inspired by human brain?",
        real_embedder,
        real_llm,
        semantic_evaluator,
    )
    assert result["retrieved_docs"][0].lower().startswith("neural")


def test_real_rag_basic_flow_qry_explain_quantum_computing_HIGH(
    real_embedder, real_llm, semantic_evaluator
):
    docs = AI_DOCS + [{"content": "Quantum computing is inspired by Schrodinger's cat!"}]
    result = _invoke_pipeline(
        docs, "Explain Quantum Computing?", real_embedder, real_llm, semantic_evaluator
    )
    assert any("quantum" in doc.lower() for doc in result["retrieved_docs"])


def test_real_rag_basic_flow_qry_explain_quantum_computing_LOW(
    real_embedder, real_llm, semantic_evaluator
):
    docs = [
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are inspired by the human brain."},
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
    ]
    result = _invoke_pipeline(
        docs, "Explain Quantum Computing?", real_embedder, real_llm, semantic_evaluator
    )
    assert not any("quantum" in doc.lower() for doc in result["retrieved_docs"])


def test_real_rag_query_variation_changes_retrieval(real_embedder, real_llm, semantic_evaluator):
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI."},
        {"content": "Neural networks model brain-like structures."},
    ]
    result_ai = _invoke_pipeline(docs, "What is AI?", real_embedder, real_llm, semantic_evaluator)
    result_nn = _invoke_pipeline(
        docs, "What are neural networks?", real_embedder, real_llm, semantic_evaluator
    )

    docs_ai = " ".join(result_ai["retrieved_docs"]).lower()
    docs_nn = " ".join(result_nn["retrieved_docs"]).lower()
    assert docs_ai != docs_nn


def test_real_rag_top_k_effect(real_embedder):
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI."},
        {"content": "Deep learning uses neural networks."},
        {"content": "Statistics is used in data science."},
    ]
    retriever = SimpleRetriever(docs=docs, embedder=real_embedder)
    query_embedding = real_embedder.embed("What is AI?")

    docs_k1 = retriever.retrieve(query_embedding, top_k=1)
    docs_k3 = retriever.retrieve(query_embedding, top_k=3)

    assert len(docs_k1) == 1
    assert len(docs_k3) == 3
