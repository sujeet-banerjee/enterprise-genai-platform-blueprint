from copy import deepcopy
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import yaml

from core.interfaces.reranker import BaseReranker
from core.interfaces.retriever import Document
from core.services.failure_classifier import FailureClassifier, FailureType
from core.services.observability import PipelineObservabilityTracker


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
        top_k: Optional[int] = None,
        config_path: Optional[str] = None,
        raise_on_failure: bool = True,
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
        self.raise_on_failure = raise_on_failure
        self.config_path = config_path or str(
            Path(__file__).resolve().parent.parent / "config" / "retrieval.yaml"
        )
        self._retrieval_config = self._load_config(self.config_path)

        ret_cfg = self._retrieval_config.get("retrieval") or {}
        obs_cfg = self._retrieval_config.get("observability") or {}

        self.top_k = int(top_k if top_k is not None else ret_cfg.get("top_k", 3))
        self.low_score_threshold = float(
            obs_cfg.get("low_retrieval_score_threshold", ret_cfg.get("low_score_threshold", 0.25))
        )

        self.last_observability: Optional[Dict[str, Any]] = None
        self.last_failure: Optional[str] = None

        self._validate_contracts()

    @staticmethod
    def _load_config(config_path: str) -> dict:
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _validate_contracts(self):
        if self.embedder.dimension != self.retriever.index_dimension:
            exc = ValueError("Embedding dimension mismatch with retriever index.")
            exc.failure_type = FailureType.DIMENSION_MISMATCH.value
            raise exc

    def _extract_docs_and_scores(self, raw_results: list) -> tuple[List[Document], List[float]]:
        docs: List[Document] = []
        scores: List[float] = []
        for idx, item in enumerate(raw_results or []):
            if hasattr(item, "document") and hasattr(item, "score"):
                doc_obj = item.document
                score_val = float(item.score) if item.score is not None else 0.0
                doc_obj.score = score_val
            elif isinstance(item, tuple) and len(item) == 2:
                doc_obj, raw_score = item
                score_val = float(raw_score) if raw_score is not None else 0.0
                if isinstance(doc_obj, Document):
                    doc_obj.score = score_val
            elif isinstance(item, Document):
                doc_obj = item
                if getattr(doc_obj, "score", None) is not None:
                    score_val = float(doc_obj.score)
                elif isinstance(doc_obj.metadata, dict) and doc_obj.metadata.get("score") is not None:
                    score_val = float(doc_obj.metadata["score"])
                else:
                    score_val = round(max(0.0, 1.0 - idx * 0.1), 4)
                doc_obj.score = score_val
            else:
                score_val = round(max(0.0, 1.0 - idx * 0.1), 4)
                doc_obj = Document(content=str(item), score=score_val)

            docs.append(doc_obj)
            scores.append(score_val)
        return docs, scores

    def _record_and_handle_stage_error(
        self,
        stage: str,
        exc: Exception,
        tracker: PipelineObservabilityTracker,
        query: str,
        effective_top_k: int,
        should_raise: bool,
    ) -> Dict[str, Any]:
        failure_tag = FailureClassifier.classify_exception(exc, stage=stage)
        exc.failure_type = failure_tag
        tracker.add_failure_tag(failure_tag)
        self.last_failure = failure_tag

        latency_report = tracker.get_latency_report()
        trace = {
            "request_id": tracker.request_id,
            "status": "failed",
            "failed_stage": stage,
            "error_message": str(exc),
            "failure_tags": list(tracker.failure_tags),
            "query": query,
            "embedding_model": getattr(self.embedder, "model_name", self.embedder.__class__.__name__),
            "embedding_dimension": getattr(self.embedder, "dimension", None),
            "retriever": self.retriever.__class__.__name__,
            "top_k": effective_top_k,
            "reranker": getattr(self.reranker, "reranker_name", "none") if self.reranker else "none",
            "llm_model": getattr(self.llm, "model_name", self.llm.__class__.__name__),
            "latency": latency_report,
        }
        self.last_observability = tracker.log_trace(trace, is_error=True)

        if should_raise:
            raise exc

        return {
            "response": None,
            "error": str(exc),
            "failure_type": failure_tag,
            "failure_tags": list(tracker.failure_tags),
            "retrieved_docs": [],
            "retrieval_scores": [],
            "metrics": {},
            "cost": {},
            "token_budget": getattr(exc, "budget_details", {}),
            "latency": latency_report,
            "observability": self.last_observability,
        }

    def run(
        self,
        query: str,
        top_k: Optional[int] = None,
        raise_on_failure: Optional[bool] = None,
    ) -> dict:
        start_time = time.time()
        effective_top_k = int(top_k if top_k is not None else self.top_k)
        should_raise = self.raise_on_failure if raise_on_failure is None else bool(raise_on_failure)
        tracker = PipelineObservabilityTracker(config_path=self.config_path)

        # 1. Embedding stage
        try:
            with tracker.measure_stage("embedding"):
                embedding = self.embedder.embed(query)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "embedding", exc, tracker, query, effective_top_k, should_raise
            )

        # 2. Retrieval stage
        try:
            with tracker.measure_stage("retrieval"):
                if hasattr(self.retriever, "retrieve_with_scores"):
                    try:
                        raw_retrieved = self.retriever.retrieve_with_scores(embedding, top_k=effective_top_k)
                    except TypeError:
                        raw_retrieved = self.retriever.retrieve_with_scores(embedding)
                else:
                    try:
                        raw_retrieved = self.retriever.retrieve(embedding, top_k=effective_top_k)
                    except TypeError:
                        raw_retrieved = self.retriever.retrieve(embedding)

                docs, initial_scores = self._extract_docs_and_scores(raw_retrieved)
                initial_docs_summary = tracker.summarize_documents(docs)

                quality_tags = FailureClassifier.classify_retrieval_quality(
                    retrieved_docs=docs,
                    scores=initial_scores,
                    low_score_threshold=self.low_score_threshold,
                )
                for tag in quality_tags:
                    tracker.add_failure_tag(tag)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "retrieval", exc, tracker, query, effective_top_k, should_raise
            )

        # 3. Reranking stage
        try:
            with tracker.measure_stage("reranking"):
                if self.reranker is not None and docs:
                    if hasattr(self.reranker, "rerank_with_scores"):
                        reranked = self.reranker.rerank_with_scores(
                            query=query, documents=docs, top_k=effective_top_k
                        )
                    else:
                        reranked = self.reranker.rerank(
                            query=query, documents=docs, top_k=effective_top_k
                        )
                    docs, final_scores = self._extract_docs_and_scores(reranked)
                else:
                    final_scores = list(initial_scores)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "reranking", exc, tracker, query, effective_top_k, should_raise
            )

        # 4. Token Budget Governance stage (delegated to TokenBudgetService; system_prompt from PromptBuilder)
        try:
            with tracker.measure_stage("token_budget"):
                system_prompt = getattr(self.prompt_builder, "system_prompt", "")
                budget = self.token_budget_service.compute_budget(
                    query=query,
                    retrieved_docs=docs,
                    system_prompt=system_prompt,
                    context_window=self.llm.context_window,
                    requested_max_tokens=self.generation_config.max_tokens,
                )
                if isinstance(budget, dict) and "retained_docs" in budget:
                    docs = budget["retained_docs"]
                    final_scores = [
                        float(doc.score) if getattr(doc, "score", None) is not None else 0.0
                        for doc in docs
                    ]
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "token_budget", exc, tracker, query, effective_top_k, should_raise
            )

        # 5. Prompt Construction stage (PromptBuilder owns prompt construction & templates)
        try:
            with tracker.measure_stage("prompt_construction"):
                prompt = self.prompt_builder.build(query, docs)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "prompt_construction", exc, tracker, query, effective_top_k, should_raise
            )

        # 6. LLM Generation stage
        try:
            with tracker.measure_stage("llm_generation"):
                gen_config = deepcopy(self.generation_config)
                gen_config.max_tokens = budget["allowed_output_tokens"]
                response = self.llm.generate(prompt, gen_config)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "llm_generation", exc, tracker, query, effective_top_k, should_raise
            )

        # 7. Evaluation stage
        try:
            with tracker.measure_stage("evaluation"):
                metrics = self.evaluator.evaluate(query, docs, response)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "evaluation", exc, tracker, query, effective_top_k, should_raise
            )

        cost = self.cost_tracker.compute(self.llm.model_name, start_time)
        latency_report = tracker.get_latency_report()
        final_ordering_summary = tracker.summarize_documents(docs)
        public_budget = {k: v for k, v in budget.items() if k != "retained_docs"}

        trace = {
            "request_id": tracker.request_id,
            "status": "degraded" if tracker.failure_tags else "success",
            "query": query,
            "embedding_model": getattr(self.embedder, "model_name", self.embedder.__class__.__name__),
            "embedding_dimension": self.embedder.dimension,
            "retriever": self.retriever.__class__.__name__,
            "top_k": effective_top_k,
            "initial_retrieved_documents": initial_docs_summary,
            "initial_retrieval_scores": initial_scores,
            "reranker": getattr(self.reranker, "reranker_name", self.reranker.__class__.__name__)
            if self.reranker
            else "none",
            "final_document_ordering": final_ordering_summary,
            "retrieved_documents": final_ordering_summary,
            "retrieval_scores": final_scores,
            "token_budget": public_budget,
            "latency": latency_report,
            "llm_model": self.llm.model_name,
            "failure_tags": list(tracker.failure_tags),
        }
        self.last_observability = tracker.log_trace(trace, is_error=False)
        self.last_failure = tracker.failure_tags[0] if tracker.failure_tags else None

        return {
            "response": response,
            "retrieved_docs": [doc.content for doc in docs],
            "retrieved_docs_with_scores": [
                {
                    "content": doc.content,
                    "score": getattr(doc, "score", None),
                    "metadata": getattr(doc, "metadata", {}),
                }
                for doc in docs
            ],
            "retrieval_scores": final_scores,
            "metrics": metrics,
            "cost": cost,
            "token_budget": public_budget,
            "latency": latency_report,
            "failure_tags": list(tracker.failure_tags),
            "observability": self.last_observability,
        }
