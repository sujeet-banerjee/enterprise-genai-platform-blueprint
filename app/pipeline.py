import time
from copy import deepcopy
from typing import Optional, List, Dict, Any
from core.interfaces.reranker import BaseReranker
from core.observability.structured_logger import StructuredLogger
from core.observability.failure_classifier import FailureType, FailureClassifier


class RAGPipeline:

    def __init__(
        self,
        embedder,
        retriever,
        llm,
        prompt_builder,
        evaluator,
        token_budget_service,
        generation_config,
        cost_tracker,
        reranker: Optional[BaseReranker] = None,
        top_k: int = 3,
        similarity_threshold: float = 0.0,
        logger: Optional[StructuredLogger] = None
    ):
        self.embedder = embedder
        self.prompt_builder = prompt_builder
        self.retriever = retriever
        self.llm = llm
        self.evaluator = evaluator
        self.cost_tracker = cost_tracker
        self.token_budget_service = token_budget_service
        self.generation_config = generation_config
        self.reranker = reranker
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.logger = logger or StructuredLogger("rag_pipeline")

        self._validate_contracts()

    def _validate_contracts(self):
        if self.embedder.dimension != self.retriever.index_dimension:
            raise ValueError("Embedding dimension mismatch with retriever index.")

    def run(self, query: str) -> Dict[str, Any]:
        pipeline_start = time.time()
        latencies: Dict[str, float] = {}
        failure_tags: List[str] = []

        # 1. Embedding Stage
        t0 = time.time()
        try:
            embedding = self.embedder.embed(query)
        except Exception as e:
            failure_tags.append(FailureClassifier.classify_exception(e, "embedding").value)
            self.logger.error(f"Embedding stage failed: {e}")
            raise
        latencies["embedding_ms"] = round((time.time() - t0) * 1000, 2)

        # 2. Retrieval Stage
        t0 = time.time()
        try:
            if hasattr(self.retriever, "retrieve_with_scores"):
                scored_docs = self.retriever.retrieve_with_scores(embedding, top_k=self.top_k)
            else:
                docs_raw = self.retriever.retrieve(embedding, top_k=self.top_k)
                scored_docs = [(d, getattr(d, "score", 0.0)) for d in docs_raw]
        except Exception as e:
            failure_tags.append(FailureClassifier.classify_exception(e, "retrieval").value)
            self.logger.error(f"Retrieval stage failed: {e}")
            raise
        latencies["retrieval_ms"] = round((time.time() - t0) * 1000, 2)

        initial_docs = [doc for doc, _ in scored_docs]
        initial_scores = [score for _, score in scored_docs]

        # Tag retrieval anomalies
        if not initial_docs:
            failure_tags.append(FailureType.NO_DOCUMENTS_RETRIEVED.value)
        elif initial_scores and max(initial_scores) < self.similarity_threshold:
            failure_tags.append(FailureType.LOW_RETRIEVAL_SCORE.value)

        # 3. Reranking Stage
        t0 = time.time()
        if self.reranker is not None and initial_docs:
            try:
                if hasattr(self.reranker, "rerank_with_scores"):
                    reranked_tuples = self.reranker.rerank_with_scores(query, initial_docs, top_k=self.top_k)
                    docs = [d for d, _ in reranked_tuples]
                    scores = [s for _, s in reranked_tuples]
                else:
                    docs = self.reranker.rerank(query, initial_docs, top_k=self.top_k)
                    scores = [getattr(d, "score", 0.0) for d in docs]
            except Exception as e:
                failure_tags.append(FailureClassifier.classify_exception(e, "reranking").value)
                self.logger.error(f"Reranking stage failed: {e}")
                docs = initial_docs
                scores = initial_scores
        else:
            docs = initial_docs
            scores = initial_scores
        latencies["reranking_ms"] = round((time.time() - t0) * 1000, 2)

        # 4. Token Budget Stage
        t0 = time.time()
        system_prompt = getattr(self.prompt_builder, "system_prompt", "You are a helpful assistant.")
        try:
            budget = self.token_budget_service.compute_budget(
                query=query,
                retrieved_docs=docs,
                system_prompt=system_prompt,
                context_window=self.llm.context_window,
                requested_max_tokens=self.generation_config.max_tokens
            )
        except Exception as e:
            failure_tags.append(FailureClassifier.classify_exception(e, "token_budget").value)
            self.logger.error(f"Token budget stage failed: {e}")
            raise
        latencies["token_budget_ms"] = round((time.time() - t0) * 1000, 2)

        # Use documents retained by the budget service
        final_docs = budget.get("retained_docs", docs)
        final_scores = [getattr(d, "score", 0.0) if getattr(d, "score", None) is not None else 0.0 for d in final_docs]

        # 5. Prompt Construction Stage
        t0 = time.time()
        try:
            prompt = self.prompt_builder.build(query, final_docs)
        except Exception as e:
            self.logger.error(f"Prompt construction stage failed: {e}")
            raise
        latencies["prompt_construction_ms"] = round((time.time() - t0) * 1000, 2)

        # 6. LLM Generation Stage
        t0 = time.time()
        try:
            gen_config = deepcopy(self.generation_config)
            gen_config.max_tokens = budget["allowed_output_tokens"]
            response = self.llm.generate(prompt, gen_config)
        except Exception as e:
            failure_tags.append(FailureClassifier.classify_exception(e, "llm").value)
            self.logger.error(f"LLM generation stage failed: {e}")
            raise
        latencies["llm_generation_ms"] = round((time.time() - t0) * 1000, 2)

        # 7. Evaluation Stage
        t0 = time.time()
        try:
            metrics = self.evaluator.evaluate(query, final_docs, response)
        except Exception as e:
            failure_tags.append(FailureClassifier.classify_exception(e, "evaluation").value)
            self.logger.error(f"Evaluation stage failed: {e}")
            metrics = {}
        latencies["evaluation_ms"] = round((time.time() - t0) * 1000, 2)

        # 8. Cost Tracking
        cost = self.cost_tracker.compute(self.llm.model_name, pipeline_start)
        latencies["total_pipeline_ms"] = round((time.time() - pipeline_start) * 1000, 2)

        # Observability Metadata
        embedder_name = getattr(self.embedder, "model_name", self.embedder.__class__.__name__)
        observability = {
            "query": query,
            "embedding_model": embedder_name,
            "embedding_dimension": self.embedder.dimension,
            "retriever": self.retriever.__class__.__name__,
            "top_k": self.top_k,
            "retrieved_documents": [doc.content for doc in docs],
            "retrieval_scores": scores,
            "reranker": self.reranker.__class__.__name__ if self.reranker else "None",
            "final_document_ordering": [doc.content for doc in final_docs],
            "token_budget": budget,
            "latencies": latencies,
            "llm_model": self.llm.model_name,
            "failure_tags": failure_tags,
        }

        # Structured Log
        self.logger.log_stage(
            stage="pipeline_run",
            data={
                "query": query,
                "embedding_model": embedder_name,
                "retrieved_count": len(docs),
                "retained_count": len(final_docs),
                "latencies": latencies,
                "failure_tags": failure_tags
            }
        )

        return {
            "response": response,
            "retrieved_docs": [doc.content for doc in final_docs],
            "retrieval_scores": final_scores,
            "metrics": metrics,
            "cost": cost,
            "token_budget": budget,
            "latencies": latencies,
            "failure_tags": failure_tags,
            "observability": observability
        }
