"""Human-in-the-loop approval workflow for sensitive actions (#123, #175)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from core.interfaces.policy import PolicyDecision

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
DECIDED = {APPROVED, REJECTED}
STATUSES = {PENDING, APPROVED, REJECTED}

#: Stable sort keys exposed by the queue contract (issue #175).
SORTABLE_FIELDS = ("created_at", "updated_at", "request_id", "status", "action")
ORDERS = ("asc", "desc")
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGE_SIZE = 200


def _effective_updated(request: "ApprovalRequest") -> float:
    """Return the last-mutated timestamp (falls back to ``created_at``)."""
    return request.updated_at if request.updated_at is not None else request.created_at


@dataclass
class ApprovalRequest:
    request_id: str
    action: str
    status: str = PENDING
    reason: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    policy: Dict[str, Any] = field(default_factory=dict)
    tenant: Optional[str] = None
    requester: Optional[str] = None
    workspace: Optional[str] = None
    app: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: Optional[float] = None
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

    def create_request(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None,
        decision: Optional[PolicyDecision] = None,
        reason: str = "",
        tenant: Optional[str] = None,
        requester: Optional[str] = None,
        workspace: Optional[str] = None,
        app: Optional[str] = None,
    ) -> ApprovalRequest:
        created_at = float(self.clock())
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
            tenant=tenant,
            requester=requester,
            workspace=workspace,
            app=app,
            created_at=created_at,
            updated_at=created_at,
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

    @staticmethod
    def _validate_query(
        *,
        status: Optional[str],
        sort_by: str,
        order: str,
        page: int,
        page_size: int,
        max_page_size: int,
        created_after: Optional[float],
        created_before: Optional[float],
        updated_after: Optional[float],
        updated_before: Optional[float],
    ) -> None:
        if status is not None and status not in STATUSES:
            raise ValueError(
                f"invalid status filter: {status!r} (expected one of {sorted(STATUSES)})"
            )
        if sort_by not in SORTABLE_FIELDS:
            raise ValueError(
                f"invalid sort_by: {sort_by!r} (expected one of {list(SORTABLE_FIELDS)})"
            )
        if order not in ORDERS:
            raise ValueError(f"invalid order: {order!r} (expected one of {list(ORDERS)})")
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        if page_size > max_page_size:
            raise ValueError(f"page_size must be <= {max_page_size}")
        if created_after is not None and created_before is not None and created_after > created_before:
            raise ValueError("created_after must be <= created_before")
        if updated_after is not None and updated_before is not None and updated_after > updated_before:
            raise ValueError("updated_after must be <= updated_before")

    def query_requests(
        self,
        *,
        status: Optional[str] = None,
        action: Optional[str] = None,
        policy: Optional[str] = None,
        requester: Optional[str] = None,
        tenant: Optional[str] = None,
        created_after: Optional[float] = None,
        created_before: Optional[float] = None,
        updated_after: Optional[float] = None,
        updated_before: Optional[float] = None,
        sort_by: str = "created_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_page_size: int = DEFAULT_MAX_PAGE_SIZE,
    ) -> Tuple[List[ApprovalRequest], int]:
        """Return one deterministic page of the queue plus the total match count.

        Filters are applied before ordering; ordering uses the requested sort key
        with ``request_id`` as a stable tie-breaker so pagination never skips or
        duplicates an item. Invalid arguments raise ``ValueError`` (mapped to a
        400 ``approval_invalid`` envelope by the API).
        """
        self._validate_query(
            status=status,
            sort_by=sort_by,
            order=order,
            page=page,
            page_size=page_size,
            max_page_size=max_page_size,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
        )

        def matches(req: ApprovalRequest) -> bool:
            if status is not None and req.status != status:
                return False
            if action is not None and req.action != action:
                return False
            if policy is not None and str(req.policy.get("policy_id")) != policy:
                return False
            if requester is not None and req.requester != requester:
                return False
            if tenant is not None and req.tenant != tenant:
                return False
            if created_after is not None and req.created_at < created_after:
                return False
            if created_before is not None and req.created_at > created_before:
                return False
            updated = _effective_updated(req)
            if updated_after is not None and updated < updated_after:
                return False
            if updated_before is not None and updated > updated_before:
                return False
            return True

        filtered = [r for r in self._requests.values() if matches(r)]

        def sort_key(req: ApprovalRequest) -> Tuple[Any, str]:
            value: Any = _effective_updated(req) if sort_by == "updated_at" else getattr(req, sort_by)
            return (value, req.request_id)

        ordered = sorted(filtered, key=sort_key, reverse=(order == "desc"))
        total = len(ordered)
        start = (page - 1) * page_size
        return ordered[start : start + page_size], total

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
        req.updated_at = req.decided_at
        req.decided_by = decided_by
        req.decision_note = note
        return req

    def gate(self, action: str, context: Optional[Dict[str, Any]] = None, decision: Optional[PolicyDecision] = None) -> Optional[ApprovalRequest]:
        if not self.requires_approval(action, decision):
            return None
        req = self.create_request(action, context=context, decision=decision)
        raise ApprovalRequiredError(req)
