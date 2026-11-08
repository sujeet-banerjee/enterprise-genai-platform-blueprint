"""Human-in-the-loop approval workflow for sensitive actions (#123)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.interfaces.policy import PolicyDecision

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
DECIDED = {APPROVED, REJECTED}


@dataclass
class ApprovalRequest:
    request_id: str
    action: str
    status: str = PENDING
    reason: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    policy: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None


class ApprovalRequiredError(Exception):
    def __init__(self, request: ApprovalRequest):
        super().__init__(f"approval required: {request.action} ({request.request_id})")
        self.request = request


class ApprovalService:
    def __init__(self, config_path: Optional[str] = None, clock=time.time):
        if config_path is None:
            config_path = str(Path(__file__).resolve().parent.parent.parent / "config" / "policies.yaml")
        self.config_path = config_path
        self.clock = clock
        self.config = self._load(config_path)
        self._requests: Dict[str, ApprovalRequest] = {}

    @staticmethod
    def _load(config_path: str) -> dict:
        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _cfg(self) -> dict:
        return self.config.get("policies") or self.config

    def enabled(self) -> bool:
        hitl = (self._cfg().get("hitl") or {})
        return bool(hitl.get("enabled", False))

    def requires_approval(self, action: str, decision: Optional[PolicyDecision] = None) -> bool:
        if not self.enabled():
            return False
        hitl = (self._cfg().get("hitl") or {})
        actions = [str(a) for a in (hitl.get("require_approval_for") or [])]
        if decision is not None and decision.action == "require_approval":
            return True
        return "*" in actions or action in actions

    def _new_id(self) -> str:
        return secrets.token_hex(8)

    def create_request(self, action: str, context: Optional[Dict[str, Any]] = None, decision: Optional[PolicyDecision] = None, reason: str = "") -> ApprovalRequest:
        req = ApprovalRequest(
            request_id=self._new_id(),
            action=action,
            status=PENDING,
            reason=reason or (decision.reason if decision else "hitl"),
            context=dict(context or {}),
            policy={
                "action": getattr(decision, "action", None),
                "policy_id": getattr(decision, "policy_id", None),
                "bundle": getattr(decision, "bundle", None),
                "dry_run": getattr(decision, "dry_run", None),
                "labels": list(getattr(decision, "labels", []) or []),
            } if decision else {},
            created_at=float(self.clock()),
        )
        self._requests[req.request_id] = req
        return req

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._requests.get(request_id)

    def list_requests(self, status: Optional[str] = None) -> List[ApprovalRequest]:
        items = list(self._requests.values())
        if status:
            items = [r for r in items if r.status == status]
        return sorted(items, key=lambda r: r.created_at, reverse=True)

    def decide(self, request_id: str, status: str, decided_by: Optional[str] = None, note: Optional[str] = None) -> ApprovalRequest:
        if status not in DECIDED:
            raise ValueError(f"invalid decision status: {status}")
        req = self.get(request_id)
        if req is None:
            raise KeyError(request_id)
        if req.status != PENDING:
            return req
        req.status = status
        req.decided_at = float(self.clock())
        req.decided_by = decided_by
        req.decision_note = note
        return req

    def gate(self, action: str, context: Optional[Dict[str, Any]] = None, decision: Optional[PolicyDecision] = None) -> Optional[ApprovalRequest]:
        if not self.requires_approval(action, decision):
            return None
        req = self.create_request(action, context=context, decision=decision)
        raise ApprovalRequiredError(req)
