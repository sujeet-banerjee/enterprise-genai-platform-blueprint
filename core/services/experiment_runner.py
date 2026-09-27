from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from core.config.generation_config import GenerationConfig
from core.evaluation.evaluation_engine import EvaluationEngine
from core.evaluation.metrics import Metrics
from core.implementations.chunker import ChunkerFactory
from core.implementations.faiss_retriever import FAISSRetriever
from core.implementations.simple_retriever import SimpleRetriever
from core.implementations.simple_reranker import SimpleReranker
from core.interfaces.retriever import Document
from core.registry.model_registry import ModelRegistry
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.token_budget_service import TokenBudgetService


class ExperimentRunner:
    """
    Executes reproducible comparative experiments across embedding models,
    chunking strategies, and retrieval/reranking configurations.
    """

    DEFAULT_COMPARISON_MODELS = (
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/all-mpnet-base-v2",
    )

    def __init__(
        self,
        models_config_path: Optional[str] = None,
        prompt_config_path: Optional[str] = None,
        retrieval_config_path: Optional[str] = None,
    ):
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.models_config_path = models_config_path or str(base_dir / "config" / "models.yaml")
        self.prompt_config_path = prompt_config_path or str(base_dir / "config" / "prompt_config.yaml")
        self.retrieval_config_path = retrieval_config_path or str(base_dir / "config" / "retrieval.yaml")
        self.registry = ModelRegistry(self.models_config_path)

    def run_single_experiment(
        self,
        docs: List[Union[dict, Document, str]],
        query: str,
        embedding_model: Optional[str] = None,
        chunk_strategy: Optional[str] = None,
        retriever_backend: str = "faiss",
        use_reranker: bool = True,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        from app.pipeline import RAGPipeline

        embedder = self.registry.get_embedder(embedding_model)
        llm = self.registry.get_active_model()

        if chunk_strategy:
            chunker = ChunkerFactory.create(strategy=chunk_strategy, config_path=self.retrieval_config_path)
            indexed_docs = chunker.chunk_documents(docs)
        else:
            indexed_docs = docs

        if retriever_backend.lower() == "faiss":
            retriever = FAISSRetriever(docs=indexed_docs, embedder=embedder)
        else:
            retriever = SimpleRetriever(docs=indexed_docs, embedder=embedder)

        reranker = SimpleReranker(config_path=self.retrieval_config_path) if use_reranker else None
        prompt_builder = PromptBuilder(self.prompt_config_path)
        evaluator = EvaluationEngine(Metrics())
        token_budget_service = TokenBudgetService(config_path=self.retrieval_config_path)
        cost_tracker = CostTracker()

        pipeline = RAGPipeline(
            embedder=embedder,
            retriever=retriever,
            llm=llm,
            prompt_builder=prompt_builder,
            evaluator=evaluator,
            token_budget_service=token_budget_service,
            generation_config=GenerationConfig(max_tokens=512),
            cost_tracker=cost_tracker,
            reranker=reranker,
            top_k=top_k,
        )

        pipeline_result = pipeline.run(query)

        return {
            "query": query,
            "embedding_model": embedder.model_name,
            "embedding_dimension": embedder.dimension,
            "index_dimension": retriever.index_dimension,
            "chunk_strategy": chunk_strategy or "none",
            "num_indexed_chunks": len(indexed_docs),
            "retrieved_documents": pipeline_result.get("retrieved_docs", []),
            "retrieval_scores": pipeline_result.get("retrieval_scores", []),
            "metrics": pipeline_result.get("metrics", {}),
            "latency": pipeline_result.get("latency", {}),
            "observability": pipeline_result.get("observability", {}),
        }

    def compare_embedding_models(
        self,
        docs: List[Union[dict, Document, str]],
        query: str,
        model_names: Optional[Sequence[str]] = None,
        chunk_strategy: Optional[str] = None,
        retriever_backend: str = "faiss",
        top_k: int = 3,
    ) -> Dict[str, Any]:
        target_models = list(model_names) if model_names else list(self.DEFAULT_COMPARISON_MODELS)
        runs: Dict[str, Dict[str, Any]] = {}

        for model_name in target_models:
            run_data = self.run_single_experiment(
                docs=docs,
                query=query,
                embedding_model=model_name,
                chunk_strategy=chunk_strategy,
                retriever_backend=retriever_backend,
                top_k=top_k,
            )
            runs[model_name] = run_data

        return {
            "query": query,
            "models_compared": target_models,
            "results": runs,
        }

    def compare_chunking_strategies(
        self,
        docs: List[Union[dict, Document, str]],
        query: str,
        strategies: Sequence[str] = ("small", "large"),
        embedding_model: Optional[str] = None,
        retriever_backend: str = "faiss",
        top_k: int = 3,
    ) -> Dict[str, Any]:
        runs: Dict[str, Dict[str, Any]] = {}
        for strategy in strategies:
            runs[strategy] = self.run_single_experiment(
                docs=docs,
                query=query,
                embedding_model=embedding_model,
                chunk_strategy=strategy,
                retriever_backend=retriever_backend,
                top_k=top_k,
            )

        return {
            "query": query,
            "strategies_compared": list(strategies),
            "results": runs,
        }


EmbeddingExperimentRunner = ExperimentRunner
