from enum import Enum
from typing import List, Optional


class FailureType(str, Enum):
    """
    Taxonomy of failure types in RAG Pipeline.
    """
    EMBEDDING_FAILURE = "embedding_failure"
    RETRIEVAL_FAILURE = "retrieval_failure"
    NO_DOCUMENTS_RETRIEVED = "no_documents_retrieved"
    LOW_RETRIEVAL_SCORE = "low_retrieval_score"
    RERANKING_FAILURE = "reranking_failure"
    TOKEN_BUDGET_EXCEEDED = "token_budget_exceeded"
    LLM_FAILURE = "llm_failure"
    EVALUATION_FAILURE = "evaluation_failure"
    DIMENSION_MISMATCH = "dimension_mismatch"
    UNKNOWN_FAILURE = "unknown_failure"


class FailureClassifier:
    """
    Helper to classify and tag errors or anomalies in pipeline execution.
    """

    @staticmethod
    def classify_exception(exc: Exception, stage: str) -> FailureType:
        exc_msg = str(exc).lower()
        if "dimension" in exc_msg and "mismatch" in exc_msg:
            return FailureType.DIMENSION_MISMATCH
        if "context window" in exc_msg or "token" in exc_msg or stage == "token_budget":
            return FailureType.TOKEN_BUDGET_EXCEEDED

        stage_map = {
            "embedding": FailureType.EMBEDDING_FAILURE,
            "retrieval": FailureType.RETRIEVAL_FAILURE,
            "reranking": FailureType.RERANKING_FAILURE,
            "llm": FailureType.LLM_FAILURE,
            "evaluation": FailureType.EVALUATION_FAILURE,
        }
        return stage_map.get(stage.lower(), FailureType.UNKNOWN_FAILURE)
