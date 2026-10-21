"""Input/output guardrails (Workstream B).

This module starts the guardrail surface with the lowest-risk, highest-value
slice: a **query length bound** so a single request cannot exceed the model's
context window before token budgeting even runs (issue #73 finding 5).

The query-length check is deliberately self-contained here; the pluggable
``BaseGuardrail`` framework (issue #52), prompt-injection defense (#53) and
PII/DLP scanning (#54) extend the same seam later.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.services.failure_classifier import FailureType


class QueryTooLongError(ValueError):
    """Raised when a query exceeds the configured character bound.

    Carries ``failure_type`` so the pipeline's ``FailureClassifier`` maps it onto
    the taxonomy (``query_too_long``) without ad-hoc strings.
    """

    failure_type = FailureType.QUERY_TOO_LONG.value

    def __init__(self, length: int, max_chars: int):
        self.length = length
        self.max_chars = max_chars
        super().__init__(
            f"Query length {length} exceeds the configured maximum of {max_chars} characters."
        )


def validate_query_length(query: str, max_chars: Optional[int]) -> None:
    """Enforce an optional upper bound on query length.

    A ``None`` or non-positive ``max_chars`` disables the bound (backward
    compatible: callers that never configured a limit behave exactly as before).
    Raises :class:`QueryTooLongError` when the query is too long.
    """
    if not max_chars or max_chars <= 0:
        return
    length = len(query or "")
    if length > int(max_chars):
        raise QueryTooLongError(length, int(max_chars))


class GuardrailBlockedError(ValueError):
    """Raised when a configured guardrail blocks input or output (issue #52).

    Carries ``failure_type`` (``guardrail_input_blocked`` / ``guardrail_output_blocked``)
    plus the guardrail name, reason and labels so the pipeline's
    ``FailureClassifier`` classifies it and the trace/audit trail records *why*.
    """

    def __init__(
        self,
        stage: str,
        guardrail: str,
        reason: Optional[str] = None,
        labels: Optional[List[str]] = None,
        decisions: Optional[List[Dict[str, Any]]] = None,
    ):
        self.stage = stage
        self.guardrail = guardrail
        self.reason = reason
        self.labels = list(labels or [])
        #: Per-guardrail decision records accumulated before the block, attached
        #: by the pipeline so the failure trace/audit can show the whole chain.
        self.decisions: List[Dict[str, Any]] = list(decisions or [])
        failure_type = (
            FailureType.GUARDRAIL_OUTPUT_BLOCKED.value
            if stage == "output"
            else FailureType.GUARDRAIL_INPUT_BLOCKED.value
        )
        self.failure_type = failure_type
        super().__init__(
            f"Guardrail '{guardrail}' blocked {stage}"
            + (f": {reason}" if reason else "")
        )
