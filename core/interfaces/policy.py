"""Policy-as-Code engine interface (#121).

Declarative policies (CEL/Rego bundles) with dry-run and HITL hooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PolicyDecision:
    allowed: bool = True
    action: str = "allow"  # allow|deny|require_approval
    reason: str = ""
    labels: List[str] = field(default_factory=list)
    dry_run: bool = False
    bundle: Optional[str] = None
    policy_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BasePolicyEngine(ABC):
    """Contract for policy evaluation engines (CEL/Rego/OPA-compatible)."""

    name: str = "policy_engine"

    @abstractmethod
    def load_bundle(self, path: str) -> Dict[str, Any]:
        """Load a policy bundle from path (git/versioned)."""

    @abstractmethod
    def evaluate(
        self,
        action: str,
        context: Dict[str, Any],
        dry_run: bool = False,
    ) -> PolicyDecision:
        """Evaluate an action against loaded policies."""


class NoopPolicyEngine(BasePolicyEngine):
    name = "noop"

    def load_bundle(self, path: str) -> Dict[str, Any]:
        return {"path": path, "policies": []}

    def evaluate(self, action: str, context: Dict[str, Any], dry_run: bool = False) -> PolicyDecision:
        return PolicyDecision(allowed=True, action="allow", reason="noop", dry_run=dry_run)
