from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

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
        acl_config_path: Optional[str] = None,
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
        self.acl_config_path = acl_config_path

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
            acl_config_path=(
                Path(self.acl_config_path) if self.acl_config_path else None
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
        cost = pipeline_result.get("cost") or {}
        latency = pipeline_result.get("latency") or {}

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
            "cost": cost,
            "cost_usd": self._cost_usd(cost),
            "latency": latency,
            "latency_summary": self._latency_summary(latency),
            "observability": pipeline_result.get("observability", {}),
        }

    # ------------------------------------------------------------------
    # Cost / latency reporting (issue #179)
    # ------------------------------------------------------------------
    QUALITY_METRIC_PRIORITY = (
        "context_recall",
        "context_precision",
        "answer_correctness",
        "ground_truth_similarity",
        "answer_relevance",
        "faithfulness",
    )

    @staticmethod
    def _cost_usd(cost: Any) -> float:
        """Return the estimated USD cost from a pipeline cost dict."""
        if not isinstance(cost, dict):
            return 0.0
        try:
            return float(cost.get("estimated_cost_usd") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _latency_summary(latency: Any) -> Dict[str, Any]:
        """Return a stable latency summary from the pipeline's flat latency dict."""
        empty: Dict[str, Any] = {
            "total_ms": 0.0,
            "stages": {},
            "slowest_stage": None,
            "slowest_stage_ms": 0.0,
        }
        if not isinstance(latency, dict):
            return empty
        stages: Dict[str, float] = {}
        for key, value in latency.items():
            if not isinstance(value, (int, float)):
                continue
            # The report contains both ``stage`` and ``stage_ms`` aliases plus
            # ``total_*`` keys; keep only the canonical stage values.
            if key.endswith("_ms") or str(key).startswith("total"):
                continue
            stages[str(key)] = float(value)
        total = latency.get("total_ms", latency.get("total_pipeline_ms", 0.0))
        try:
            total_ms = float(total or 0.0)
        except (TypeError, ValueError):
            total_ms = 0.0
        slowest_stage: Optional[str] = None
        slowest_ms = 0.0
        for stage, ms in stages.items():
            if ms > slowest_ms:
                slowest_stage, slowest_ms = stage, ms
        return {
            "total_ms": total_ms,
            "stages": stages,
            "slowest_stage": slowest_stage,
            "slowest_stage_ms": slowest_ms,
        }

    @classmethod
    def summarize_run(cls, run: Mapping[str, Any]) -> Dict[str, Any]:
        """Return a compact cost/latency/quality summary for one experiment run."""
        metrics = run.get("metrics") or {}
        quality: Dict[str, float] = {}
        if isinstance(metrics, dict):
            for key, value in metrics.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    quality[str(key)] = float(value)
        latency_summary = run.get("latency_summary")
        total_latency: Optional[float] = None
        if isinstance(latency_summary, dict):
            candidate = latency_summary.get("total_ms")
            if isinstance(candidate, (int, float)):
                total_latency = float(candidate)
        if total_latency is None:
            latency = run.get("latency")
            if isinstance(latency, dict) and isinstance(latency.get("total_ms"), (int, float)):
                total_latency = float(latency["total_ms"])
        return {
            "cost_usd": cls._cost_usd(run.get("cost")),
            "total_latency_ms": total_latency or 0.0,
            "quality": quality,
        }

    @classmethod
    def _primary_quality_metric(
        cls, summaries: Mapping[str, Mapping[str, Any]]
    ) -> Optional[str]:
        available: set[str] = set()
        for summary in summaries.values():
            quality = summary.get("quality")
            if isinstance(quality, Mapping):
                available.update(str(key) for key in quality)
        for metric in cls.QUALITY_METRIC_PRIORITY:
            if metric in available:
                return metric
        return sorted(available)[0] if available else None

    @classmethod
    def summarize_comparison(cls, runs: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        """Aggregate per-run cost/latency/quality for a comparison."""
        summaries = {name: cls.summarize_run(run) for name, run in runs.items()}
        quality_metric = cls._primary_quality_metric(summaries)

        best_quality: Optional[Dict[str, Any]] = None
        if quality_metric:
            ranked = sorted(
                (
                    (name, summary["quality"][quality_metric])
                    for name, summary in summaries.items()
                    if summary["quality"].get(quality_metric) is not None
                ),
                key=lambda item: (-float(item[1]), item[0]),
            )
            if ranked:
                name, value = ranked[0]
                best_quality = {
                    "name": name,
                    "value": float(value),
                    "metric": quality_metric,
                }

        cheapest: Optional[Dict[str, Any]] = None
        fastest: Optional[Dict[str, Any]] = None
        if summaries:
            cheap_name = min(summaries, key=lambda n: (summaries[n]["cost_usd"], n))
            cheapest = {"name": cheap_name, "cost_usd": summaries[cheap_name]["cost_usd"]}
            fast_name = min(summaries, key=lambda n: (summaries[n]["total_latency_ms"], n))
            fastest = {
                "name": fast_name,
                "total_latency_ms": summaries[fast_name]["total_latency_ms"],
            }

        count = len(summaries)
        total_cost = sum(summary["cost_usd"] for summary in summaries.values())
        total_latency = sum(summary["total_latency_ms"] for summary in summaries.values())
        return {
            "runs": summaries,
            "count": count,
            "total_cost_usd": total_cost,
            "avg_cost_usd": (total_cost / count) if count else 0.0,
            "avg_total_latency_ms": (total_latency / count) if count else 0.0,
            "quality_metric": quality_metric,
            "best_quality": best_quality,
            "cheapest": cheapest,
            "fastest": fastest,
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
            "summary": self.summarize_comparison(runs),
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
            "summary": self.summarize_comparison(runs),
        }


EmbeddingExperimentRunner = ExperimentRunner
