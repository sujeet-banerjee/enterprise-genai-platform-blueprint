from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from core.implementations.chunker import ChunkerFactory
from core.interfaces.retriever import Document


class ExperimentRunner:
    """
    Executes reproducible comparative experiments across embedding models,
    chunking strategies, and retrieval/reranking configurations.

    Component assembly is delegated to ``app.bootstrap.assemble_components``
    (issue #75) so experiments share the exact composition root used by the HTTP
    application - including governance, observability-driven redaction, provider
    resilience, query expansion, caching and config-driven generation settings.
    Previously this class re-implemented assembly and silently drifted from
    production.
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
        governance_config_path: Optional[str] = None,
        observability_config_path: Optional[str] = None,
        resilience_config_path: Optional[str] = None,
        guardrails_config_path: Optional[str] = None,
    ):
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.models_config_path = models_config_path or str(base_dir / "config" / "models.yaml")
        self.prompt_config_path = prompt_config_path or str(
            base_dir / "config" / "prompt_config.yaml"
        )
        self.retrieval_config_path = retrieval_config_path or str(
            base_dir / "config" / "retrieval.yaml"
        )
        # Dedicated governance/observability/resilience files (issues #34/#72/#45).
        # ``None`` falls back to the legacy inline sections in retrieval.yaml so
        # existing callers keep working unchanged.
        self.governance_config_path = governance_config_path
        self.observability_config_path = observability_config_path
        self.resilience_config_path = resilience_config_path
        self.guardrails_config_path = guardrails_config_path

    def run_single_experiment(
        self,
        docs: List[Union[dict, Document, str]],
        query: str,
        embedding_model: Optional[str] = None,
        chunk_strategy: Optional[str] = None,
        retriever_backend: Optional[str] = None,
        use_reranker: Optional[bool] = None,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        from app.bootstrap import assemble_components

        if chunk_strategy:
            chunker = ChunkerFactory.create(
                strategy=chunk_strategy, config_path=self.retrieval_config_path
            )
            indexed_docs: Sequence[Union[dict, Document, str]] = chunker.chunk_documents(docs)
        else:
            indexed_docs = docs

        # Assemble via the shared composition root (issue #75): governance,
        # redaction, resilience, caching and generation config are all wired the
        # same way as production. Chunking is applied above, so the retriever's
        # own chunking is disabled (``chunk=False``).
        components = assemble_components(
            models_config_path=Path(self.models_config_path),
            prompt_config_path=Path(self.prompt_config_path),
            retrieval_config_path=Path(self.retrieval_config_path),
            governance_config_path=(
                Path(self.governance_config_path) if self.governance_config_path else None
            ),
            observability_config_path=(
                Path(self.observability_config_path) if self.observability_config_path else None
            ),
            resilience_config_path=(
                Path(self.resilience_config_path) if self.resilience_config_path else None
            ),
            guardrails_config_path=(
                Path(self.guardrails_config_path) if self.guardrails_config_path else None
            ),
            embedding_model=embedding_model,
            retriever_backend=retriever_backend,
            use_reranker=use_reranker,
            docs=indexed_docs,
            chunk=False,
        )

        embedder = components.embedder
        retriever = components.retriever
        reranker = components.reranker
        evaluator = components.evaluator

        pipeline = components.build_pipeline(
            config_path=self.retrieval_config_path,
            governance_config_path=self.governance_config_path,
            observability_config_path=self.observability_config_path,
            top_k=top_k,
        )

        pipeline_result = pipeline.run(query)

        return {
            "query": query,
            "embedding_model": embedder.model_name,
            "embedding_dimension": embedder.dimension,
            "index_dimension": retriever.index_dimension,
            "retriever": retriever.__class__.__name__,
            "reranker": reranker.__class__.__name__ if reranker is not None else None,
            "evaluator": evaluator.__class__.__name__,
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
        retriever_backend: Optional[str] = None,
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
        retriever_backend: Optional[str] = None,
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
