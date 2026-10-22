import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.interfaces.reranker import BaseReranker
from core.interfaces.retriever import Document
from core.services.failure_classifier import FailureClassifier, FailureType
from core.services.guardrails import GuardrailBlockedError, validate_query_length
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
        cost_governor: Optional[Any] = None,
        retrieval_policy_service: Optional[Any] = None,
        governance_config_path: Optional[str] = None,
        observability_config_path: Optional[str] = None,
        query_expander: Optional[Any] = None,
        cache: Optional[Any] = None,
        redactor: Optional[Any] = None,
        trace_redactor: Optional[Any] = None,
        max_query_chars: Optional[int] = None,
        input_guardrails: Optional[List[Any]] = None,
        output_guardrails: Optional[List[Any]] = None,
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
        self.cost_governor = cost_governor
        self.retrieval_policy_service = retrieval_policy_service
        self.query_expander = query_expander
        self.cache = cache
        # Input-side redaction (issue #72): when a redactor is injected, secrets
        # in the query and retrieved docs are stripped *before* prompt
        # construction so nothing sensitive reaches the model provider or the
        # returned envelope. None => data path is byte-identical to before.
        self.redactor = redactor
        # Trace/log redaction may be stricter than input redaction (issue #54):
        # a ``pii`` guardrail protects values in traces even when the input
        # redaction stage is off, without pre-empting its block decision.
        self.trace_redactor = trace_redactor or redactor
        self.config_path = config_path or str(
            Path(__file__).resolve().parent.parent / "config" / "retrieval.yaml"
        )
        self._retrieval_config = self._load_config(self.config_path)

        # Governance and observability may live in their own files (issue #34).
        # When no dedicated path is supplied we fall back to the legacy inline
        # sections inside retrieval.yaml so existing deployments keep working.
        self.governance_config_path = governance_config_path
        self.observability_config_path = observability_config_path

        ret_cfg = self._retrieval_config.get("retrieval") or {}
        obs_cfg = self._load_section(observability_config_path) or (
            self._retrieval_config.get("observability") or {}
        )
        gov_cfg = self._load_section(governance_config_path) or (
            self._retrieval_config.get("governance") or {}
        )

        # Query-length bound (issue #73): enforce an upper bound on the raw query
        # before token budgeting so a single request cannot blow the context
        # window. Config-driven (guardrails.max_query_chars); None disables it.
        guardrail_cfg = self._retrieval_config.get("guardrails") or {}
        resolved_max_query_chars = (
            max_query_chars
            if max_query_chars is not None
            else guardrail_cfg.get("max_query_chars")
        )
        self.max_query_chars: Optional[int] = (
            int(resolved_max_query_chars)
            if resolved_max_query_chars is not None
            else None
        )

        # Guardrail framework (issue #52): ordered input/output chains. Empty
        # when the feature is disabled, so the stages are no-ops by default.
        self.input_guardrails: List[Any] = list(input_guardrails or [])
        self.output_guardrails: List[Any] = list(output_guardrails or [])

        self.top_k = int(top_k if top_k is not None else ret_cfg.get("top_k", 3))
        self.avg_chunk_tokens = int(gov_cfg.get("avg_chunk_tokens", ret_cfg.get("avg_chunk_tokens", 128)))
        self.low_score_threshold = float(
            obs_cfg.get("low_retrieval_score_threshold", ret_cfg.get("low_score_threshold", 0.25))
        )

        # OTel-native tracing (issue #47): build the exporter once (from the
        # ``otel:`` block) and reuse it across per-request trackers; None when
        # disabled, keeping the disabled path zero-overhead.
        from core.services.telemetry import build_otel_tracer

        otel_cfg = obs_cfg.get("otel") if isinstance(obs_cfg, dict) else None
        self.otel = build_otel_tracer(otel_cfg) if isinstance(otel_cfg, dict) else None

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

    @classmethod
    def _load_section(cls, config_path: Optional[str]) -> dict:
        """Load a single-concern config file whose top level *is* the section."""
        if not config_path:
            return {}
        loaded = cls._load_config(config_path)
        return loaded if isinstance(loaded, dict) else {}

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
                if doc_obj.score is not None:
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

    def _retrieve_for_embedding(self, embedding, top_k: int, query: Optional[str] = None) -> list:
        """Run a single retrieval pass, tolerating retrievers without 'top_k'.

        Retrievers that need the raw query text (e.g. the hybrid keyword+vector
        retriever, issue #25) expose ``retrieve_with_query``; others only see the
        embedding. Pure-vector retrievers are unaffected.
        """
        if query is not None and hasattr(self.retriever, "retrieve_with_query"):
            try:
                return self.retriever.retrieve_with_query(query, embedding, top_k=top_k)
            except TypeError:
                return self.retriever.retrieve_with_query(query, embedding)
        if hasattr(self.retriever, "retrieve_with_scores"):
            try:
                return self.retriever.retrieve_with_scores(embedding, top_k=top_k)
            except TypeError:
                return self.retriever.retrieve_with_scores(embedding)
        try:
            return self.retriever.retrieve(embedding, top_k=top_k)
        except TypeError:
            return self.retriever.retrieve(embedding)

    @staticmethod
    def _merge_documents(docs: List[Document], scores: List[float]) -> tuple[List[Document], List[float]]:
        """Merge documents across query variants, de-duplicating by id/content.

        The highest-scoring occurrence wins and results stay ordered by descending
        score so downstream stages (reranking, token budget) see a sensible order.
        """
        best: Dict[Any, tuple] = {}
        order: List[Any] = []
        for idx, doc in enumerate(docs):
            score = scores[idx] if idx < len(scores) else 0.0
            metadata = getattr(doc, "metadata", None) or {}
            key = metadata.get("doc_id") if isinstance(metadata, dict) else None
            if key is None:
                key = ("content", doc.content)
            if key not in best:
                best[key] = (doc, score)
                order.append(key)
            elif float(score) > float(best[key][1]):
                best[key] = (doc, score)

        merged = [best[key] for key in order]
        merged.sort(key=lambda pair: float(pair[1]), reverse=True)
        merged_docs = [pair[0] for pair in merged]
        merged_scores = [float(pair[1]) for pair in merged]
        for doc, score in zip(merged_docs, merged_scores):
            doc.score = score
        return merged_docs, merged_scores

    def _retrieve_expanded(self, query: str, top_k: int) -> tuple[List[Document], List[float], List[str], bool]:
        """Retrieve over the raw query, expanding into variants when configured.

        Returns (docs, scores, queries_used, expanded). Each variant is embedded
        and retrieved independently; results are merged and de-duplicated.
        """
        if self.query_expander is None:
            embedding = self.embedder.embed(query)
            raw = self._retrieve_for_embedding(embedding, top_k, query)
            docs, scores = self._extract_docs_and_scores(raw)
            return docs, scores, [query], False

        try:
            variants = list(self.query_expander.expand(query) or [query])
        except Exception:
            variants = [query]
        if not variants:
            variants = [query]

        all_docs: List[Document] = []
        all_scores: List[float] = []
        for variant in variants:
            embedding = self.embedder.embed(variant)
            raw = self._retrieve_for_embedding(embedding, top_k, variant)
            docs, scores = self._extract_docs_and_scores(raw)
            all_docs.extend(docs)
            all_scores.extend(scores)

        merged_docs, merged_scores = self._merge_documents(all_docs, all_scores)
        return merged_docs, merged_scores, variants, len(variants) > 1

    def _redact_inputs(
        self, query: str, docs: List[Document]
    ) -> tuple[str, List[Document], bool]:
        """Redact the query and retrieved docs before prompt construction (#72).

        Returns ``(redacted_query, redacted_docs, applied)``. ``applied`` is True
        only when a redactor is present and enabled; otherwise the inputs are
        returned unchanged and the pipeline behaves exactly as before.
        """
        redactor = self.redactor
        if redactor is None or not getattr(redactor, "enabled", False):
            return query, docs, False

        redacted_query = redactor.redact_text(query)

        redacted_docs: List[Document] = []
        for doc in docs:
            original = getattr(doc, "content", "")
            content = redactor.redact_text(original)
            if content == original:
                redacted_docs.append(doc)
                continue
            redacted_docs.append(
                Document(
                    content=content,
                    metadata=getattr(doc, "metadata", None),
                    score=getattr(doc, "score", None),
                )
            )
        return redacted_query, redacted_docs, True

    def _run_guardrail_chain(
        self,
        text: str,
        guardrails: List[Any],
        stage: str,
        tracker: PipelineObservabilityTracker,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Run an ordered guardrail chain over ``text`` (issue #52).

        Returns ``(possibly_rewritten_text, decisions)`` where ``decisions`` is a
        list of per-guardrail records for the trace/audit trail. A blocking
        decision raises :class:`GuardrailBlockedError` so the stage handler
        classifies it. Redacting guardrails rewrite the text and continue.
        """
        from core.interfaces.guardrail import GuardrailContext

        decisions: List[Dict[str, Any]] = []
        current = text
        context = GuardrailContext(stage=stage, metadata=dict(metadata or {}))
        for guardrail in guardrails:
            name = getattr(guardrail, "name", guardrail.__class__.__name__)
            result = guardrail.check(current, context)
            record = {
                "guardrail": name,
                "decision": getattr(result, "decision", "allow"),
                "allowed": bool(getattr(result, "allowed", True)),
                "reason": getattr(result, "reason", None),
                "labels": list(getattr(result, "labels", []) or []),
                # Issue #54: structured context (e.g. PII classes + counts).
                # Never carries the matched value - only class names and counts.
                "details": dict(getattr(result, "details", {}) or {}),
            }
            decisions.append(record)
            if not record["allowed"]:
                raise GuardrailBlockedError(
                    stage,
                    name,
                    reason=record["reason"],
                    labels=record["labels"],
                    decisions=decisions,
                )
            new_text = getattr(result, "text", None)
            if new_text is not None and new_text != current:
                current = new_text
                tracker.set_trace_attribute(f"{stage}_guardrail_redacted", True)
        return current, decisions

    def _record_and_handle_stage_error(
        self,
        stage: str,
        exc: Exception,
        tracker: PipelineObservabilityTracker,
        query: str,
        effective_top_k: int,
        should_raise: bool,
        cost: Optional[dict] = None,
    ) -> Dict[str, Any]:
        failure_tag = FailureClassifier.classify_exception(exc, stage=stage)
        setattr(exc, "failure_type", failure_tag)
        tracker.add_failure_tag(failure_tag)
        self.last_failure = failure_tag

        # Guardrail blocks (issue #52) contribute their labels as failure tags so
        # governance/HITL reporting can see *which* policy blocked the call.
        for label in getattr(exc, "labels", []) or []:
            tracker.add_failure_tag(str(label))

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
            "reranking_enabled": self.reranker is not None,
            "llm_model": getattr(self.llm, "model_name", self.llm.__class__.__name__),
            "latency": latency_report,
        }
        guardrail_name = getattr(exc, "guardrail", None)
        if guardrail_name is not None:
            trace["guardrail"] = guardrail_name
            chain = list(getattr(exc, "decisions", []) or [])
            if chain:
                trace["guardrail_decisions"] = chain
        self.last_observability = tracker.log_trace(trace, is_error=True)

        if should_raise:
            raise exc

        envelope = {
            "response": None,
            "error": str(exc),
            "failure_type": failure_tag,
            "failure_tags": list(tracker.failure_tags),
            "retrieved_docs": [],
            "retrieval_scores": [],
            "metrics": {},
            "cost": cost or {},
            "token_budget": getattr(exc, "budget_details", {}),
            "latency": latency_report,
            "observability": self.last_observability,
        }
        if guardrail_name is not None:
            envelope["guardrail"] = guardrail_name
            envelope["guardrail_reason"] = getattr(exc, "reason", None)
            envelope["guardrail_labels"] = list(getattr(exc, "labels", []) or [])
            chain = list(getattr(exc, "decisions", []) or [])
            if chain:
                envelope["guardrail_decisions"] = chain
        return envelope

    def run(
        self,
        query: str,
        top_k: Optional[int] = None,
        raise_on_failure: Optional[bool] = None,
        request_id: Optional[str] = None,
    ) -> dict:
        start_time = time.time()
        effective_top_k = int(top_k if top_k is not None else self.top_k)
        should_raise = self.raise_on_failure if raise_on_failure is None else bool(raise_on_failure)
        tracker = PipelineObservabilityTracker(
            config_path=self.config_path,
            observability_config_path=self.observability_config_path,
            otel=self.otel,
            redactor=getattr(self, "trace_redactor", None),
        )
        if request_id:
            tracker.request_id = request_id

        # -1. Response cache lookup (optional; off by default). A hit returns the
        # stored result immediately, skipping embedding/retrieval/generation and
        # surfacing a cache_hit flag in observability (issue #26).
        cache = getattr(self, "cache", None)
        cache_key = None
        if cache is not None and getattr(cache, "enabled", False):
            cache_key = cache.make_key(query, effective_top_k)
            cached = cache.get(cache_key)
            if cached is not None:
                hit = deepcopy(cached)
                hit["observability"] = dict(hit.get("observability") or {})
                hit["observability"]["cache_hit"] = True
                hit["cache_hit"] = True
                if request_id:
                    hit["observability"]["request_id"] = request_id
                self.last_observability = hit["observability"]
                return hit

        # 0. Query-length guard (issue #73): reject an over-long query *before*
        # any embedding/retrieval work. Config-driven; None disables the bound.
        try:
            with tracker.measure_stage("query_validation"):
                validate_query_length(query, self.max_query_chars)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "query_validation", exc, tracker, query, effective_top_k, should_raise
            )

        # 0. Retrieval depth governance (token economics tuned by RetrievalPolicyService)
        if self.retrieval_policy_service is not None and top_k is None:
            try:
                query_tokens = self.token_budget_service.estimate_tokens(query)
                policy_top_k = int(
                    self.retrieval_policy_service.compute_top_k(
                        query_tokens=query_tokens,
                        avg_chunk_tokens=self.avg_chunk_tokens,
                    )
                )
                effective_top_k = max(1, min(effective_top_k, policy_top_k))
            except Exception as exc:
                return self._record_and_handle_stage_error(
                    "retrieval_policy", exc, tracker, query, effective_top_k, should_raise
                )

        # 1. Embedding stage
        try:
            with tracker.measure_stage("embedding"):
                embedding = self.embedder.embed(query)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "embedding", exc, tracker, query, effective_top_k, should_raise
            )
        # OTel span attributes (issue #47): set after the first stage so the root
        # span exists; no-op when tracing is disabled.
        tracker.set_trace_attribute("top_k", effective_top_k)
        tracker.set_trace_attribute("retriever", type(self.retriever).__name__)
        tracker.set_trace_attribute("embedding_model", getattr(self.embedder, "model_name", None))
        tracker.set_trace_attribute("llm_model", getattr(self.llm, "model_name", None))

        # 2. Retrieval stage (multi-query expansion when configured, else verbatim)
        try:
            with tracker.measure_stage("retrieval"):
                if self.query_expander is None:
                    raw_retrieved = self._retrieve_for_embedding(embedding, effective_top_k, query)
                    docs, initial_scores = self._extract_docs_and_scores(raw_retrieved)
                    queries_used = [query]
                    expanded = False
                else:
                    docs, initial_scores, queries_used, expanded = self._retrieve_expanded(
                        query, effective_top_k
                    )

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

        # 3. Reranking stage (optional; skipped entirely when reranking.enabled is false)
        if self.reranker is not None:
            try:
                with tracker.measure_stage("reranking"):
                    if docs:
                        reranked: List[Any]
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
        else:
            final_scores = list(initial_scores)

        # 3b. Input redaction stage (issue #72). When a redactor is configured,
        # strip secrets from the query and retrieved docs *before* they are
        # token-budgeted, templated into the prompt, sent to the model provider,
        # or returned to the caller. Embedding/retrieval keep the original query
        # so retrieval semantics are unchanged.
        redaction_applied = False
        try:
            with tracker.measure_stage("input_redaction"):
                query, docs, redaction_applied = self._redact_inputs(query, docs)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "input_redaction", exc, tracker, query, effective_top_k, should_raise
            )
        if redaction_applied:
            tracker.set_trace_attribute("input_redaction", True)

        # 3c. Input guardrail stage (issue #52): ordered safety/policy checks on
        # the query and retrieved docs *before* prompt construction. Disabled by
        # default (empty chain => no-op). A blocking guardrail yields a governed
        # input failure; a redacting guardrail rewrites the text in place.
        input_guardrail_decisions: List[Dict[str, Any]] = []
        if self.input_guardrails:
            try:
                with tracker.measure_stage("guardrail_input"):
                    query, query_decisions = self._run_guardrail_chain(
                        query,
                        self.input_guardrails,
                        "input",
                        tracker,
                        metadata={"target": "query", "top_k": effective_top_k},
                    )
                    input_guardrail_decisions.extend(query_decisions)
                    guardrailed_docs: List[Document] = []
                    for doc in docs:
                        content, doc_decisions = self._run_guardrail_chain(
                            getattr(doc, "content", ""),
                            self.input_guardrails,
                            "input",
                            tracker,
                            metadata={"target": "document"},
                        )
                        input_guardrail_decisions.extend(doc_decisions)
                        if content == getattr(doc, "content", ""):
                            guardrailed_docs.append(doc)
                        else:
                            guardrailed_docs.append(
                                Document(
                                    content=content,
                                    metadata=getattr(doc, "metadata", None),
                                    score=getattr(doc, "score", None),
                                )
                            )
                    docs = guardrailed_docs
            except Exception as exc:
                return self._record_and_handle_stage_error(
                    "guardrail_input", exc, tracker, query, effective_top_k, should_raise
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
                # Providers that support chat roles get the system prompt as a
                # distinct system message instead of it only being inlined in
                # the prompt text (issue #13).
                gen_config.system_prompt = getattr(self.prompt_builder, "system_prompt", "")
                response = self.llm.generate(prompt, gen_config)
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "llm_generation", exc, tracker, query, effective_top_k, should_raise
            )

        # 6b. Output guardrail stage (issue #52): ordered safety/policy checks on
        # the generated response before it is evaluated or returned. Disabled by
        # default (empty chain => no-op). A blocking guardrail yields a governed
        # output failure; a redacting guardrail rewrites the response in place.
        output_guardrail_decisions: List[Dict[str, Any]] = []
        if self.output_guardrails:
            try:
                with tracker.measure_stage("guardrail_output"):
                    response, output_guardrail_decisions = self._run_guardrail_chain(
                        response,
                        self.output_guardrails,
                        "output",
                        tracker,
                        metadata={
                            "target": "response",
                            "llm_model": getattr(self.llm, "model_name", None),
                        },
                    )
            except Exception as exc:
                return self._record_and_handle_stage_error(
                    "guardrail_output", exc, tracker, query, effective_top_k, should_raise
                )

        # 7. Evaluation stage
        try:
            with tracker.measure_stage("evaluation"):
                if self.evaluator is not None:
                    metrics = self.evaluator.evaluate(query, docs, response)
                else:
                    metrics = {}
        except Exception as exc:
            return self._record_and_handle_stage_error(
                "evaluation", exc, tracker, query, effective_top_k, should_raise
            )

        input_tokens = self.token_budget_service.estimate_tokens(prompt)
        output_tokens = self.token_budget_service.estimate_tokens(response)
        cost = self.cost_tracker.compute(
            self.llm.model_name,
            start_time,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        # 8. Cost governance stage
        if self.cost_governor is not None:
            try:
                self.cost_governor.check_cost(cost.get("estimated_cost_usd", 0.0))
            except Exception as exc:
                return self._record_and_handle_stage_error(
                    "cost_governance", exc, tracker, query, effective_top_k, should_raise, cost=cost
                )

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
            "query_expansion_enabled": expanded,
            "expanded_queries": queries_used,
            "initial_retrieved_documents": initial_docs_summary,
            "initial_retrieval_scores": initial_scores,
            "reranker": getattr(self.reranker, "reranker_name", self.reranker.__class__.__name__)
            if self.reranker
            else "none",
            "reranking_enabled": self.reranker is not None,
            "final_document_ordering": final_ordering_summary,
            "retrieved_documents": final_ordering_summary,
            "retrieval_scores": final_scores,
            "token_budget": public_budget,
            "latency": latency_report,
            "llm_model": self.llm.model_name,
            "failure_tags": list(tracker.failure_tags),
            "cache_hit": False,
            "redaction_enabled": redaction_applied,
            "guardrails_enabled": bool(self.input_guardrails or self.output_guardrails),
            "guardrail_decisions": input_guardrail_decisions + output_guardrail_decisions,
        }
        # Resilience metadata (issue #45): populated only when the llm/embedder
        # are wrapped; empty otherwise.
        resilience = {}
        for component in (self.llm, self.embedder):
            pop = getattr(component, "pop_resilience", None)
            if callable(pop):
                data = pop()
                if data:
                    resilience.update(data)
        if resilience:
            trace["resilience"] = resilience
        self.last_observability = tracker.log_trace(trace, is_error=False)
        self.last_failure = tracker.failure_tags[0] if tracker.failure_tags else None

        result = {
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
            "cache_hit": False,
            "guardrail_decisions": input_guardrail_decisions + output_guardrail_decisions,
        }

        # Store a deep copy for future identical queries. Only successful runs
        # reach this point (hard failures return early via the stage handlers);
        # degraded-but-successful runs are still cacheable.
        if cache is not None and cache_key is not None:
            cache.set(cache_key, deepcopy(result))

        return result

    def run_batch(
        self,
        queries: List[str],
        top_k: Optional[int] = None,
        max_workers: Optional[int] = None,
        request_ids: Optional[List[str]] = None,
        raise_on_failure: Optional[bool] = None,
    ) -> List[dict]:
        """
        Run several queries, reusing ``run`` per query (issue #27).

        With ``max_workers`` > 1 the queries run concurrently through a thread
        pool (parallel inference); otherwise they run sequentially. Results are
        returned in input order regardless of completion order, so
        ``run_batch([q])[0]`` is equivalent to ``run(q)``.

        The embedder/LLM batch hooks (:meth:`BaseEmbedder.embed_batch` /
        :meth:`BaseLLM.generate_batch`) handle single-pass multi-item batching at
        the provider layer; this helper adds request-level parallelism on top.
        """
        if not queries:
            return []

        def _one(index: int, query: str) -> dict:
            return self.run(
                query,
                top_k=top_k,
                raise_on_failure=raise_on_failure,
                request_id=request_ids[index] if request_ids else None,
            )

        workers = int(max_workers or 1)
        if workers <= 1 or len(queries) == 1:
            return [_one(i, q) for i, q in enumerate(queries)]

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(workers, len(queries))) as pool:
            futures = [pool.submit(_one, i, q) for i, q in enumerate(queries)]
            return [future.result() for future in futures]
