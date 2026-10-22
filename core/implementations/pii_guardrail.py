"""PII / DLP guardrail (Workstream B3, issue #54).

:class:`PiiGuardrail` plugs into the B1 guardrail framework (#52) so PII
enforcement happens at the **input** edge (query + retrieved docs, before
prompt construction) and the **output** edge (generated response, before it
is returned to the caller).

Policy:

- ``classes`` selects which PII classes are enforced (per-class toggles).
  Classes that are not selected pass through untouched.
- ``mode`` is ``redact`` (rewrite the span, keep going) or ``block`` (fail
  the request with a governed envelope).
- ``mask`` overrides the per-class default token (``[REDACTED_EMAIL]`` ...).

Only the **class** and a **count** ever leave this guardrail. The matched
value is used to rewrite the text and is then discarded - it is never put in
the reason, the labels, the trace or the audit trail.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from core.interfaces.guardrail import BaseGuardrail, GuardrailContext, GuardrailResult
from core.interfaces.pii import (
    DEFAULT_PII_CLASSES,
    PiiDetector,
    PiiMatch,
    apply_pii_masks,
    summarize_matches,
)

#: Supported enforcement modes.
MODE_REDACT = "redact"
MODE_BLOCK = "block"


class PiiGuardrail(BaseGuardrail):
    """Detect (and optionally redact or block) PII in text."""

    name = "pii"

    def __init__(
        self,
        classes: Optional[Sequence[str]] = None,
        mode: str = MODE_REDACT,
        mask: Optional[str] = None,
        detector: Optional[PiiDetector] = None,
        reason: Optional[str] = None,
    ):
        source = DEFAULT_PII_CLASSES if classes is None else classes
        selected = [str(c).strip().lower() for c in source]
        self.classes: Sequence[str] = tuple(c for c in selected if c)
        self.mode = str(mode or MODE_REDACT).strip().lower()
        if self.mode not in (MODE_REDACT, MODE_BLOCK):
            raise ValueError(
                f"Unsupported PII guardrail mode: '{mode}'. "
                f"Supported modes: {MODE_REDACT}, {MODE_BLOCK}"
            )
        self.mask = mask
        self.reason = reason or "pii_detected"
        self._detector = detector

    @property
    def detector(self) -> PiiDetector:
        """The detector in use (built lazily so construction never needs deps)."""
        if self._detector is None:
            from core.implementations.pii_detector import RegexPiiDetector

            self._detector = RegexPiiDetector(classes=self.classes)
        return self._detector

    def _options(self) -> Dict[str, Any]:
        return {
            "classes": list(self.classes),
            "mode": self.mode,
            "mask": self.mask,
        }

    def check(self, text: str, context: GuardrailContext) -> GuardrailResult:
        haystack = text if isinstance(text, str) else ""
        if not haystack or not self.classes:
            return GuardrailResult.allow()

        matches = self.detector.detect(haystack)
        if not matches:
            return GuardrailResult.allow()

        labels = self._labels(matches)
        details = self._details(matches)
        reason = "{}: {}".format(self.reason, ",".join(sorted(details["classes"])))

        if self.mode == MODE_BLOCK:
            return GuardrailResult.block(reason=reason, labels=labels, details=details)

        rewritten = apply_pii_masks(haystack, matches, self.mask)
        if rewritten == haystack:
            return GuardrailResult.allow()
        return GuardrailResult.redact(rewritten, reason=reason, labels=labels, details=details)

    @staticmethod
    def _labels(matches: Sequence[PiiMatch]) -> List[str]:
        """``pii:<class>`` tags - never the matched value."""
        return [f"pii:{name}" for name in sorted(summarize_matches(matches))]

    @staticmethod
    def _details(matches: Sequence[PiiMatch]) -> Dict[str, Any]:
        counts = summarize_matches(matches)
        return {"classes": counts, "total": len(matches)}
