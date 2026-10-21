"""Built-in guardrails (Workstream B1, issue #52).

These are the reference implementations the registry ships with:

- :class:`NoopGuardrail` - always allows (a safe default / test double).
- :class:`DenyListGuardrail` - blocks text matching configured keywords/regexes.
- :class:`SchemaValidatorGuardrail` - enforces a lightweight output schema
  (required keys and/or a JSON parse) for structured responses.

None of these import pipeline or API code, so they stay pure and reusable.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from core.interfaces.guardrail import (
    BaseGuardrail,
    GuardrailContext,
    GuardrailResult,
)


class NoopGuardrail(BaseGuardrail):
    """Always allows. Useful as an explicit placeholder in an ordered chain."""

    name = "noop"

    def check(self, text: str, context: GuardrailContext) -> GuardrailResult:
        return GuardrailResult.allow()


class DenyListGuardrail(BaseGuardrail):
    """Block text containing any configured denied term.

    ``terms`` are matched case-insensitively as whole-ish substrings by default;
    set ``regex: true`` to treat them as regular expressions. ``mask`` (optional)
    turns the guardrail into a **redactor** instead of a blocker: matching spans
    are replaced by ``mask`` and the decision is ``redact`` (the pipeline keeps
    going with the rewritten text).

    This is the seam injection defense (#53) and DLP (#54) build on, but is kept
    deliberately simple and deterministic here.
    """

    name = "deny_list"

    def __init__(
        self,
        terms: Optional[List[str]] = None,
        regex: bool = False,
        mask: Optional[str] = None,
        case_insensitive: bool = True,
        reason: Optional[str] = None,
    ):
        self.terms = [str(t) for t in (terms or []) if str(t)]
        self.regex = bool(regex)
        self.mask = mask
        self.reason = reason or "denied_term"
        flags = re.IGNORECASE if case_insensitive else 0
        self._patterns = [re.compile(t if self.regex else re.escape(t), flags) for t in self.terms]

    def _first_match(self, text: str) -> Optional["re.Match[str]"]:
        for pattern in self._patterns:
            match = pattern.search(text)
            if match:
                return match
        return None

    def check(self, text: str, context: GuardrailContext) -> GuardrailResult:
        haystack = text or ""
        match = self._first_match(haystack)
        if match is None:
            return GuardrailResult.allow()

        label = f"deny_list:{match.group(0)}"
        if self.mask is not None:
            masked = haystack
            for pattern in self._patterns:
                masked = pattern.sub(self.mask, masked)
            if masked != haystack:
                return GuardrailResult.redact(
                    masked, reason=self.reason, labels=[label]
                )
            return GuardrailResult.allow()

        return GuardrailResult.block(
            reason=f"{self.reason}: matched '{match.group(0)}'",
            labels=[label],
        )


class SchemaValidatorGuardrail(BaseGuardrail):
    """Validate structured output against a tiny schema.

    ``required_keys`` must all be present (after parsing JSON from ``text`` when
    ``expect_json`` is true); ``forbidden_keys`` must be absent. A JSON ``string``
    body that fails to parse is a block when ``expect_json`` is set. This is
    deliberately lightweight - it is a format/policy gate, not a full JSON Schema
    engine (that can be added as another guardrail without touching the pipeline).
    """

    name = "schema_validator"

    def __init__(
        self,
        required_keys: Optional[List[str]] = None,
        forbidden_keys: Optional[List[str]] = None,
        expect_json: bool = False,
        reason: Optional[str] = None,
    ):
        self.required_keys = [str(k) for k in (required_keys or [])]
        self.forbidden_keys = [str(k) for k in (forbidden_keys or [])]
        self.expect_json = bool(expect_json)
        self.reason = reason or "schema_violation"

    def check(self, text: str, context: GuardrailContext) -> GuardrailResult:
        payload: Any = text
        if self.expect_json:
            try:
                payload = json.loads(text or "")
            except (ValueError, TypeError):
                return GuardrailResult.block(
                    reason=f"{self.reason}: not valid JSON",
                    labels=["schema:invalid_json"],
                )

        if not isinstance(payload, dict):
            if self.required_keys or self.forbidden_keys:
                return GuardrailResult.block(
                    reason=f"{self.reason}: expected a JSON object",
                    labels=["schema:not_object"],
                )
            return GuardrailResult.allow()

        missing = [k for k in self.required_keys if k not in payload]
        if missing:
            return GuardrailResult.block(
                reason=f"{self.reason}: missing required keys {missing}",
                labels=[f"schema:missing:{k}" for k in missing],
            )

        present_forbidden = [k for k in self.forbidden_keys if k in payload]
        if present_forbidden:
            return GuardrailResult.block(
                reason=f"{self.reason}: forbidden keys present {present_forbidden}",
                labels=[f"schema:forbidden:{k}" for k in present_forbidden],
            )

        return GuardrailResult.allow()
