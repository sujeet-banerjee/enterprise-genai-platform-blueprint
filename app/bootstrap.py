"""Shared composition of pipeline components (issue #75).

Both the HTTP application (`app/main.py::build_pipeline`) and the experiment
runner (`core/services/experiment_runner.py`) previously assembled a
`RAGPipeline` independently. That duplication drifted: experiments silently
skipped governance, observability-driven redaction, provider resilience, query
expansion and the config-driven generation settings.

This module is the single source of truth for *component assembly*. Callers ask
for a bundle of components (optionally overriding a few knobs, which is what
experiments do), then build a `RAGPipeline` from it. `build_pipeline` is a thin
wrapper; `ExperimentRunner` reuses the same assembler so production and
experiments can never diverge again.

Layering: this lives in the ``app`` layer (it may import concrete ``core``
implementations via the registries and construct ``app.pipeline``). ``core`` code
that needs it (the experiment runner) imports it lazily inside a method, exactly
as it already lazy-imports ``app.pipeline``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.pipeline import RAGPipeline
from core.config.generation_config import GenerationConfig
from core.config.schema import SCHEMAS
from core.config.validator import load_and_validate, resolve_config_file
from core.registry.evaluator_registry import EvaluatorRegistry
from core.registry.guardrail_registry import GuardrailRegistry
from core.registry.model_registry import ModelRegistry
from core.registry.pii_registry import PiiRegistry
from core.registry.query_expander_registry import QueryExpanderRegistry
from core.registry.reranker_registry import RerankerRegistry
from core.registry.retriever_registry import RetrieverRegistry
from core.services.acl import AclSettings
from core.services.cost_governor import CostGovernor
from core.services.cost_tracker import CostTracker
from core.services.observability import SensitiveDataRedactor
from core.services.prompt_builder import PromptBuilder
from core.services.resilience import build_resilient_embedder, build_resilient_llm
from core.services.retrieval_policy_service import RetrievalPolicyService
from core.services.token_budget_service import TokenBudgetService


def load_config(config_path: Optional[Path], *, validate: bool = True) -> dict:
    """Load a config file, resolving secret references (issue #46).

    When ``validate`` is true (the default) and the file exists, it is checked
    against its schema first and a hard schema/secret error fails fast with a
    precise message. Missing optional files still yield ``{}`` (backward
    compatible); files whose stem has no registered schema load leniently.
    """
    if config_path is None:
        return {}
    path = Path(config_path)
    if not path.exists():
        return {}
    if validate and path.stem in SCHEMAS:
        return load_and_validate(path)
    return resolve_config_file(path)


def validate_startup_configs(*paths: Optional[Path]) -> None:
    """Validate each existing schema-backed config, failing fast on errors.

    ``prompt_config.yaml`` uses the ``prompt_config`` schema; its stem already
    matches. Configs without a registered schema (or missing optional files) are
    skipped. Raises :class:`ConfigValidationError` on the first invalid file.
    """
    from core.config.validator import ConfigValidationError, validate_config_file

    for path in paths:
        if path is None:
            continue
        candidate = Path(path)
        if not candidate.exists() or candidate.stem not in SCHEMAS:
            continue
        issues = [i for i in validate_config_file(candidate) if i.kind != "version-warning"]
        if issues:
            raise ConfigValidationError(candidate, issues)


def generation_config_from_model(model_cfg: dict) -> GenerationConfig:
    """
    Derive GenerationConfig from the active model's configuration so
    temperature / max_tokens / top_p / stop are tunable via models.yaml
    (issue #12). ``max_new_tokens`` (HuggingFace naming) is honored as a
    fallback for ``max_tokens``. Defaults match GenerationConfig's own.
    """
    max_tokens = int(model_cfg.get("max_tokens") or model_cfg.get("max_new_tokens") or 256)
    return GenerationConfig(
        temperature=float(model_cfg.get("temperature", 0.7)),
        top_p=float(model_cfg.get("top_p", 0.9)),
        max_tokens=max_tokens,
        stop=model_cfg.get("stop"),
    )


@dataclass
class PipelineComponents:
    """A resolved bundle of components ready to construct a `RAGPipeline`.

    Keeping this explicit (rather than returning a bare dict) lets callers -
    in particular the experiment runner - inspect and reuse individual pieces
    (e.g. the embedder, retriever, registries) without re-deriving them.
    """

    llm: Any
    embedder: Any
    retriever: Any
    reranker: Any
    evaluator: Any
    prompt_builder: PromptBuilder
    token_budget_service: TokenBudgetService
    generation_config: GenerationConfig
    cost_tracker: CostTracker
    query_expander: Any = None
    cache: Any = None
    redactor: Optional[SensitiveDataRedactor] = None
    trace_redactor: Optional[SensitiveDataRedactor] = None
    cost_governor: Any = None
    retrieval_policy_service: Any = None
    input_guardrails: Any = None
    output_guardrails: Any = None
    model_registry: Optional[ModelRegistry] = None
    retriever_registry: Optional[RetrieverRegistry] = None
    reranker_registry: Optional[RerankerRegistry] = None
    evaluator_registry: Optional[EvaluatorRegistry] = None
    query_expander_registry: Optional[QueryExpanderRegistry] = None
    guardrail_registry: Optional[GuardrailRegistry] = None
    pii_registry: Optional[PiiRegistry] = None
    pii_detector: Any = None
    retrieval_config: dict = field(default_factory=dict)
    governance_config: dict = field(default_factory=dict)
    observability_config: dict = field(default_factory=dict)
    max_query_chars: Optional[int] = None
    acl: AclSettings = field(default_factory=AclSettings)

    def build_pipeline(
        self,
        *,
        config_path: Optional[str] = None,
        governance_config_path: Optional[str] = None,
        observability_config_path: Optional[str] = None,
        top_k: Optional[int] = None,
        raise_on_failure: bool = True,
        max_query_chars: Optional[int] = None,
    ) -> RAGPipeline:
        """Construct a `RAGPipeline` from this component bundle."""
        return RAGPipeline(
            embedder=self.embedder,
            prompt_builder=self.prompt_builder,
            retriever=self.retriever,
            llm=self.llm,
            evaluator=self.evaluator,
            token_budget_service=self.token_budget_service,
            generation_config=self.generation_config,
            cost_tracker=self.cost_tracker,
            reranker=self.reranker,
            top_k=top_k,
            config_path=config_path,
            raise_on_failure=raise_on_failure,
            cost_governor=self.cost_governor,
            retrieval_policy_service=self.retrieval_policy_service,
            governance_config_path=governance_config_path,
            observability_config_path=observability_config_path,
            query_expander=self.query_expander,
            cache=self.cache,
            redactor=self.redactor,
            trace_redactor=self.trace_redactor,
            max_query_chars=max_query_chars,
            input_guardrails=self.input_guardrails,
            output_guardrails=self.output_guardrails,
            acl=self.acl,
        )


def assemble_components(
    *,
    models_config_path: Path,
    prompt_config_path: Path,
    retrieval_config_path: Path,
    governance_config_path: Optional[Path] = None,
    observability_config_path: Optional[Path] = None,
    resilience_config_path: Optional[Path] = None,
    guardrails_config_path: Optional[Path] = None,
    acl_config_path: Optional[Path] = None,
    validate: bool = True,
    # Overrides used by experiments (issue #75). ``None`` -> resolved from config.
    embedding_model: Optional[str] = None,
    retriever_backend: Optional[str] = None,
    use_reranker: Optional[bool] = None,
    docs: Optional[Any] = None,
    chunk: bool = True,
    enable_cache: Optional[bool] = None,
    generation_max_tokens: Optional[int] = None,
) -> PipelineComponents:
    """Resolve every pluggable component from configuration.

    Embedder/LLM come from ``ModelRegistry``, the retriever from
    ``RetrieverRegistry``, the reranker from ``RerankerRegistry`` and the
    evaluator from ``EvaluatorRegistry`` - so swapping vendors is a config change.
    Optional keyword overrides let the experiment runner vary a single axis
    (embedding model, chunking, retriever backend, reranker on/off) without
    re-implementing any of this assembly.
    """
    if validate:
        validate_startup_configs(
            models_config_path,
            prompt_config_path,
            retrieval_config_path,
            governance_config_path,
            observability_config_path,
            resilience_config_path,
            guardrails_config_path,
            acl_config_path,
        )

    model_registry = ModelRegistry(str(models_config_path))
    retriever_registry = RetrieverRegistry(str(retrieval_config_path))
    reranker_registry = RerankerRegistry(str(retrieval_config_path))
    evaluator_registry = EvaluatorRegistry(str(retrieval_config_path))
    query_expander_registry = QueryExpanderRegistry(str(retrieval_config_path))
    guardrail_registry = GuardrailRegistry(
        str(guardrails_config_path) if guardrails_config_path else None
    )

    retrieval_config = load_config(retrieval_config_path)
    governance_config = load_config(governance_config_path) if governance_config_path else {}
    if not governance_config:
        governance_config = retrieval_config.get("governance") or {}
    observability_config = (
        (load_config(observability_config_path) if observability_config_path else {})
        or (retrieval_config.get("observability") or {})
    )
    # Permission-aware retrieval (issue #51): off by default (open ACLs).
    acl_settings = AclSettings.from_config(
        load_config(acl_config_path) if acl_config_path else {}
    )

    active_llm = model_registry.get_active_model()
    embedder = (
        model_registry.get_embedder(embedding_model)
        if embedding_model
        else model_registry.get_active_embedder()
    )

    # Provider resilience (issue #45): transparent pass-throughs when disabled.
    resilience_config = (load_config(resilience_config_path) or {}).get("resilience") or {}
    if resilience_config.get("enabled", False):
        fallback_models = [str(name) for name in (resilience_config.get("fallback_models") or [])]
        llm_chain = [active_llm] + [model_registry.get_model(name) for name in fallback_models]
        active_llm = build_resilient_llm(llm_chain, resilience_config)
        embedder = build_resilient_embedder(embedder, resilience_config)

    retriever = retriever_registry.create(
        name=retriever_backend, docs=docs, embedder=embedder, chunk=chunk
    )
    reranker = reranker_registry.create(enabled=use_reranker)
    evaluator = evaluator_registry.create()
    # Query expansion is opt-in; the LLM provider gets the active model injected
    # so it never loads a second copy (issue #23).
    query_expander = query_expander_registry.create(llm=active_llm)

    # Guardrail framework (issue #52): ordered input/output chains, disabled by
    # default (empty lists => the pipeline stages are pure no-ops).
    input_guardrails = guardrail_registry.build_input_chain()
    output_guardrails = guardrail_registry.build_output_chain()

    # Optional response cache (issue #26); off by default. The namespace ties
    # entries to the active component identities so a rebuild cannot serve stale
    # answers from a different model/retriever.
    cache = None
    cache_cfg = retrieval_config.get("cache") or {}
    cache_on = bool(cache_cfg.get("enabled", False)) if enable_cache is None else bool(enable_cache)
    if cache_on:
        from core.services.response_cache import ResponseCache

        cache = ResponseCache(
            enabled=True,
            max_entries=int(cache_cfg.get("max_entries", 128)),
            ttl_seconds=cache_cfg.get("ttl_seconds", 300.0),
            namespace=f"{getattr(active_llm, 'model_name', 'llm')}|"
            f"{type(retriever).__name__}|"
            f"{getattr(embedder, 'model_name', 'embedder')}",
        )

    prompt_builder = PromptBuilder(str(prompt_config_path))
    active_model_config = model_registry.get_active_model_config()
    generation_config = generation_config_from_model(active_model_config)
    if generation_max_tokens is not None:
        generation_config.max_tokens = int(generation_max_tokens)
    token_budget_service = TokenBudgetService(config_path=str(retrieval_config_path))

    # Input-side redaction (issue #72): strip secrets from the query and
    # retrieved docs before prompt construction. Driven by the observability
    # config (issue #16) with the legacy inline section as a fallback.
    #
    # PII / DLP scrubbing (issue #54) layers on top: the ``pii:`` block of the
    # observability config decides which personal-data classes are stripped
    # from the query, the docs, the traces and the logs.
    pii_registry = PiiRegistry(config=observability_config)
    pii_detector = pii_registry.build_detector()
    input_redactor = SensitiveDataRedactor(
        enabled=bool(observability_config.get("redact_sensitive_data", True)),
        patterns=observability_config.get("sensitive_patterns"),
        pii_detector=pii_detector,
        pii_classes=pii_registry.classes() if pii_detector is not None else None,
    )

    # Traces and logs must never carry a value that a ``pii`` guardrail is
    # protecting, even when the observability ``pii:`` block is off (defense in
    # depth). This is a *separate* redactor: the input redaction stage must not
    # pre-empt a guardrail ``block`` decision, so the edge still sees raw text.
    guardrail_pii_classes: list = []
    for _chain in (input_guardrails, output_guardrails):
        for _guardrail in _chain or []:
            if getattr(_guardrail, "name", None) != "pii":
                continue
            for _cls in getattr(_guardrail, "classes", None) or []:
                if _cls not in guardrail_pii_classes:
                    guardrail_pii_classes.append(_cls)
    if guardrail_pii_classes:
        trace_pii_classes = list(pii_registry.classes()) if pii_detector is not None else []
        for _cls in guardrail_pii_classes:
            if _cls not in trace_pii_classes:
                trace_pii_classes.append(_cls)
        trace_redactor = SensitiveDataRedactor(
            enabled=bool(observability_config.get("redact_sensitive_data", True)),
            patterns=observability_config.get("sensitive_patterns"),
            pii_detector=pii_registry.build_detector(trace_pii_classes, force=True),
            pii_classes=trace_pii_classes,
        )
    else:
        trace_redactor = input_redactor

    # Per-model pricing from models.yaml (issue #14).
    model_pricing: dict = {}
    for _name, _cfg in (model_registry.config.get("models") or {}).items():
        _cfg = _cfg or {}
        if "input_cost_per_1k" in _cfg or "output_cost_per_1k" in _cfg:
            _entry = {
                "input_cost_per_1k": _cfg.get("input_cost_per_1k"),
                "output_cost_per_1k": _cfg.get("output_cost_per_1k"),
            }
            model_pricing[_name] = _entry
            model_pricing.setdefault(str(_cfg.get("model_name", _name)), _entry)
    cost_tracker = CostTracker(
        input_cost_per_1k=active_model_config.get("input_cost_per_1k"),
        output_cost_per_1k=active_model_config.get("output_cost_per_1k"),
        model_pricing=model_pricing,
    )

    # Governance services (issue #10/#14 unrelated): cost + retrieval policy.
    # ``governance.enabled`` gates whether they are attached at all.
    governance_enabled = bool(governance_config.get("enabled", True))
    if governance_enabled:
        cost_governor = CostGovernor(
            max_cost_per_request=float(governance_config.get("max_cost_per_request_usd", 1.0))
        )
        retrieval_policy_service = RetrievalPolicyService(
            context_window=active_llm.context_window,
            system_prompt_tokens=token_budget_service.estimate_tokens(prompt_builder.system_prompt),
            reserved_output_tokens=generation_config.max_tokens,
            safety_margin=int(governance_config.get("safety_margin_tokens", 200)),
        )
    else:
        cost_governor = None
        retrieval_policy_service = None

    # Query-length bound (issue #73): read the pipeline-level guardrail config.
    guardrail_cfg = retrieval_config.get("guardrails") or {}
    _mqc = guardrail_cfg.get("max_query_chars")
    max_query_chars = int(_mqc) if _mqc is not None else None

    return PipelineComponents(
        llm=active_llm,
        embedder=embedder,
        retriever=retriever,
        reranker=reranker,
        evaluator=evaluator,
        prompt_builder=prompt_builder,
        token_budget_service=token_budget_service,
        generation_config=generation_config,
        cost_tracker=cost_tracker,
        query_expander=query_expander,
        cache=cache,
        redactor=input_redactor,
        trace_redactor=trace_redactor,
        cost_governor=cost_governor,
        retrieval_policy_service=retrieval_policy_service,
        input_guardrails=input_guardrails,
        output_guardrails=output_guardrails,
        model_registry=model_registry,
        retriever_registry=retriever_registry,
        reranker_registry=reranker_registry,
        evaluator_registry=evaluator_registry,
        query_expander_registry=query_expander_registry,
        guardrail_registry=guardrail_registry,
        pii_registry=pii_registry,
        pii_detector=pii_detector,
        retrieval_config=retrieval_config,
        governance_config=governance_config,
        observability_config=observability_config,
        max_query_chars=max_query_chars,
        acl=acl_settings,
    )
