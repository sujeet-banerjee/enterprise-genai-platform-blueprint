"""Input/output guardrails (Workstream B).

This module starts the guardrail surface with the lowest-risk, highest-value
slice: a **query length bound** so a single request cannot exceed the model's
context window before token budgeting even runs (issue #73 finding 5).

The query-length check is deliberately self-contained here; the pluggable
``BaseGuardrail`` framework (issue #52), prompt-injection defense (#53) and
PII/DLP scanning (#54) extend the same seam later.
"""

from __future__ import annotations

from typing import Optional

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
