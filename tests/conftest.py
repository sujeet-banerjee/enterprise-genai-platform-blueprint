"""Shared genuine (real-model) fixtures for the test suite.

These fixtures construct actual models rather than dummies. They are
session-scoped so an expensive model is loaded once and reused by every test
that needs it. Only stateless components are shared; per-test state (retrievers,
pipelines) is built inside each test.
"""

import pytest

from core.implementations.cross_encoder_reranker import CrossEncoderReranker
from core.implementations.hf_local_llm import LocalHFLLM
from core.implementations.semantic_evaluator import SemanticEvaluator
from core.implementations.simple_embedder import SimpleEmbedder

DOCS = [
    {"content": "Artificial Intelligence is the simulation of human intelligence."},
    {"content": "Machine Learning is a subset of AI focused on learning from data."},
    {"content": "Neural networks are inspired by the human brain."},
    {"content": "Deep learning uses multi-layer neural networks for representation learning."},
]


@pytest.fixture(scope="session")
def real_embedder():
    return SimpleEmbedder("all-MiniLM-L6-v2")


@pytest.fixture(scope="session")
def real_llm():
    return LocalHFLLM(max_new_tokens=64)


@pytest.fixture(scope="session")
def real_reranker():
    return CrossEncoderReranker()


@pytest.fixture(scope="session")
def semantic_evaluator(real_embedder):
    return SemanticEvaluator(embedder=real_embedder)


@pytest.fixture(scope="session")
def sample_docs():
    return [dict(doc) for doc in DOCS]


@pytest.fixture
def make_pipeline(real_embedder, real_llm, semantic_evaluator, sample_docs):
    """Factory building a RAGPipeline wired with genuine components.

    Individual tests may override any component (e.g. a deliberately failing one)
    or pass extra RAGPipeline kwargs such as ``reranker``, ``top_k``,
    ``cost_governor`` or ``raise_on_failure``.
    """

    def _make(
        docs=None,
        reranker=None,
        embedder=None,
        llm=None,
        evaluator="default",
        retriever=None,
        **kwargs,
    ):
        from app.pipeline import RAGPipeline
        from core.config.generation_config import GenerationConfig
        from core.implementations.simple_retriever import SimpleRetriever
        from core.services.cost_tracker import CostTracker
        from core.services.prompt_builder import PromptBuilder
        from core.services.token_budget_service import TokenBudgetService

        embedder = real_embedder if embedder is None else embedder
        llm = real_llm if llm is None else llm
        if evaluator == "default":
            evaluator = semantic_evaluator
        source = sample_docs if docs is None else docs
        if retriever is None:
            retriever = SimpleRetriever(docs=source, embedder=embedder)

        policy_mode = kwargs.pop("policy_mode", "strict")
        max_tokens = kwargs.pop("max_tokens", 64)
        config_path = kwargs.pop("config_path", None)

        return RAGPipeline(
            embedder=embedder,
            prompt_builder=PromptBuilder("config/prompt_config.yaml"),
            retriever=retriever,
            llm=llm,
            token_budget_service=TokenBudgetService(
                policy_mode=policy_mode, config_path=config_path
            ),
            evaluator=evaluator,
            generation_config=GenerationConfig(max_tokens=max_tokens, temperature=0.0),
            cost_tracker=CostTracker(),
            config_path=config_path,
            reranker=reranker,
            **kwargs,
        )

    return _make

