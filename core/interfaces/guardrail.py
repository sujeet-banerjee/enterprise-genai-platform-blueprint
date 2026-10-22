"""Guardrail contract (Workstream B1, issue #52).

A guardrail is a pluggable safety/policy check that runs on the **input** edge
(query + retrieved docs, before prompt construction) or the **output** edge
(generated response, before it is returned to the caller) of
``RAGPipeline.run``.

The contract is intentionally small and transport-agnostic so the same
abstraction covers:

- prompt-injection / jailbreak defense (Workstream B2, #53),
- PII / DLP scanning + masking (Workstream B3, #54),
- toxicity / policy / schema-format checks (this framework).

Guardrails are resolved from configuration by ``GuardrailRegistry`` and are
**disabled by default**, so the data path is byte-identical to before when the
feature is off.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Decisions a guardrail can return (ordered by severity).
DECISION_ALLOW = "allow"
DECISION_REDACT = "redact"
DECISION_BLOCK = "block"


@dataclass
class GuardrailContext:
    """Ambient information passed to a guardrail alongside the text.

    ``stage`` is ``"input"`` or ``"output"``; ``metadata`` is a free-form bag
    (e.g. ``top_k``, ``llm_model``, ``num_docs``) so a guardrail can make
    context-aware decisions without the pipeline knowing anything about it.
    """

    stage: str = "input"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailResult:
    """Outcome of a single guardrail check.

    - ``allowed``: ``False`` means the pipeline must stop with a governed
      failure (``block``). A redacting guardrail leaves ``allowed`` true and
      rewrites ``text``.
    - ``text``: the (possibly rewritten) text. ``None`` means "leave unchanged".
    - ``reason``: human-readable explanation surfaced in traces/metrics/audit.
    - ``labels``: machine-readable tags (e.g. policy names, PII categories) that
      feed governance/HITL reporting.
    - ``details``: optional structured context (e.g. the PII classes and counts
      for a DLP decision). Must never carry sensitive values - issue #54
      requires counts and classes only.
    """

    allowed: bool = True
    decision: str = DECISION_ALLOW
    text: Optional[str] = None
    reason: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls) -> "GuardrailResult":
        return cls(allowed=True, decision=DECISION_ALLOW)

    @classmethod
    def block(
        cls,
        reason: Optional[str] = None,
        labels: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "GuardrailResult":
        return cls(
            allowed=False,
            decision=DECISION_BLOCK,
            reason=reason,
            labels=list(labels or []),
            details=dict(details or {}),
        )

    @classmethod
    def redact(
        cls,
        text: str,
        reason: Optional[str] = None,
        labels: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "GuardrailResult":
        return cls(
            allowed=True,
            decision=DECISION_REDACT,
            text=text,
            reason=reason,
            labels=list(labels or []),
            details=dict(details or {}),
        )


class BaseGuardrail(ABC):
    """Contract for pluggable input/output safety and policy checks."""

    #: Human-readable identifier surfaced in traces (defaults to the class name).
    name: str = "guardrail"

    #: Which edge(s) this guardrail applies to by default; ``"input"``,
    #: ``"output"`` or ``None`` for both. A registry entry may override it.
    stage: Optional[str] = None

    @abstractmethod
    def check(self, text: str, context: GuardrailContext) -> GuardrailResult:
        """Inspect ``text`` and return a decision.

        Implementations must be side-effect free and must not raise for ordinary
        policy decisions; unexpected errors are handled by the pipeline stage.
        """
        raise NotImplementedError

    def check_input(self, text: str, context: Optional[GuardrailContext] = None) -> GuardrailResult:
        """Convenience wrapper for the input edge."""
        ctx = context or GuardrailContext(stage="input")
        return self.check(text, ctx)

    def check_output(self, text: str, context: Optional[GuardrailContext] = None) -> GuardrailResult:
        """Convenience wrapper for the output edge."""
        ctx = context or GuardrailContext(stage="output")
        return self.check(text, ctx)

    def describe(self) -> Dict[str, Any]:
        """Read-only view for introspection (issue #86).

        The base implementation reports the provider, class and resolved edge,
        so every guardrail - including third-party ones - is introspectable
        without extra code. Concrete providers override ``_options`` to expose
        their **effective** settings; those options must never include secrets.
        """
        return {
            "provider": str(self.name),
            "type": type(self).__name__,
            "stage": self.stage,
            "options": self._options(),
        }

    def _options(self) -> Dict[str, Any]:
        """Provider-specific effective options (override; no secrets)."""
        return {}
