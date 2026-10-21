from enum import Enum
from typing import List, Optional, Sequence

from core.services.token_budget_service import TokenBudgetExceededError


class FailureType(str, Enum):
    """
    Taxonomy of failure classifications across the RAG pipeline.

    Also the single source of truth for API error envelopes (issue #41): every
    ``failure_type`` string in an API response must be a member of this enum.
    """
    EMBEDDING_FAILURE = "embedding_failure"
    DIMENSION_MISMATCH = "dimension_mismatch"
    RETRIEVAL_FAILURE = "retrieval_failure"
    NO_DOCUMENTS_RETRIEVED = "no_documents_retrieved"
    LOW_RETRIEVAL_SCORE = "low_retrieval_score"
    RERANKING_FAILURE = "reranking_failure"
    TOKEN_BUDGET_EXCEEDED = "token_budget_exceeded"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
    RETRIEVAL_POLICY_FAILURE = "retrieval_policy_failure"
    PROMPT_CONSTRUCTION_FAILURE = "prompt_construction_failure"
    LLM_FAILURE = "llm_failure"
    EVALUATION_FAILURE = "evaluation_failure"
    UNKNOWN_FAILURE = "unknown_failure"
    # API-level failure categories (group A): readiness/auth/batch-cap. These
    # are API responses rather than pipeline stage failures, but they live in
    # the same taxonomy so envelopes never invent ad-hoc strings.
    NOT_READY = "not_ready"
    UNAUTHORIZED = "unauthorized"
    BATCH_TOO_LARGE = "batch_too_large"
    FORBIDDEN = "forbidden"
    # Input guardrail category (issue #73): the query exceeded the configured
    # character bound before it could be token-budgeted.
    QUERY_TOO_LONG = "query_too_long"
    # Guardrail framework categories (issue #52): a configured input/output
    # guardrail blocked the request/response.
    GUARDRAIL_INPUT_BLOCKED = "guardrail_input_blocked"
    GUARDRAIL_OUTPUT_BLOCKED = "guardrail_output_blocked"


class FailureClassifier:
    """
    Classifies runtime exceptions and retrieval/pipeline quality anomalies
    into explicit failure tags for observability and governance.
    """

    STAGE_TO_FAILURE = {
        "embedding": FailureType.EMBEDDING_FAILURE.value,
        "retrieval": FailureType.RETRIEVAL_FAILURE.value,
        "reranking": FailureType.RERANKING_FAILURE.value,
        "query_validation": FailureType.QUERY_TOO_LONG.value,
        "guardrail_input": FailureType.GUARDRAIL_INPUT_BLOCKED.value,
        "guardrail_output": FailureType.GUARDRAIL_OUTPUT_BLOCKED.value,
        "token_budget": FailureType.TOKEN_BUDGET_EXCEEDED.value,
        "cost_governance": FailureType.COST_LIMIT_EXCEEDED.value,
        "retrieval_policy": FailureType.RETRIEVAL_POLICY_FAILURE.value,
        "prompt_construction": FailureType.PROMPT_CONSTRUCTION_FAILURE.value,
        "llm_generation": FailureType.LLM_FAILURE.value,
        "evaluation": FailureType.EVALUATION_FAILURE.value,
    }

    @classmethod
    def classify_exception(cls, exc: Exception, stage: Optional[str] = None) -> str:
        if hasattr(exc, "failure_type") and getattr(exc, "failure_type"):
            return str(getattr(exc, "failure_type"))

        if isinstance(exc, TokenBudgetExceededError):
            return FailureType.TOKEN_BUDGET_EXCEEDED.value

        msg = str(exc).lower()
        if "dimension mismatch" in msg or "does not match index dimension" in msg:
            return FailureType.DIMENSION_MISMATCH.value
        if "cost threshold" in msg or "cost limit" in msg:
            return FailureType.COST_LIMIT_EXCEEDED.value
        if "context window exceeded" in msg or "token budget" in msg:
            return FailureType.TOKEN_BUDGET_EXCEEDED.value

        if stage and stage.lower() in cls.STAGE_TO_FAILURE:
            return cls.STAGE_TO_FAILURE[stage.lower()]

        return FailureType.UNKNOWN_FAILURE.value

    @classmethod
    def classify_retrieval_quality(
        cls,
        retrieved_docs: Optional[Sequence],
        scores: Optional[Sequence[float]] = None,
        low_score_threshold: float = 0.25,
    ) -> List[str]:
        tags: List[str] = []
        if not retrieved_docs:
            tags.append(FailureType.NO_DOCUMENTS_RETRIEVED.value)
            return tags

        valid_scores = [float(s) for s in (scores or []) if s is not None]
        if valid_scores and max(valid_scores) < float(low_score_threshold):
            tags.append(FailureType.LOW_RETRIEVAL_SCORE.value)

        return tags
