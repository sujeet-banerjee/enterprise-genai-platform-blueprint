"""HITL approval workflow endpoints (#123)."""

import uuid
from dataclasses import asdict
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas import ApprovalDecisionRequest, ApprovalListResponse, ApprovalRequestResponse
from core.services.failure_classifier import FailureType


def register_approval_routes(application: FastAPI, error_envelope: Callable[..., dict]) -> None:
    def _request_id(request: Request) -> str:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())

    def _svc(request: Request):
        return getattr(request.app.state, "approvals", None)

    def _error(request: Request, status: int, message: str, failure_type: str):
        return JSONResponse(
            status_code=status,
            content=error_envelope(message, failure_type, [], _request_id(request)),
        )

    @application.get("/v1/approvals", response_model=ApprovalListResponse)
    def list_approvals(request: Request, status: Optional[str] = None):
        svc = _svc(request)
        if svc is None:
            return _error(request, 503, "Approval service is not ready.", FailureType.NOT_READY.value)
        items = [ApprovalRequestResponse(**asdict(r)) for r in svc.list_requests(status=status)]
        return ApprovalListResponse(enabled=svc.enabled(), count=len(items), requests=items, request_id=_request_id(request))

    @application.get("/v1/approvals/{request_id}", response_model=ApprovalRequestResponse)
    def get_approval(request: Request, request_id: str):
        svc = _svc(request)
        if svc is None:
            return _error(request, 503, "Approval service is not ready.", FailureType.NOT_READY.value)
        req = svc.get(request_id)
        if req is None:
            return _error(request, 404, "Approval request not found.", FailureType.APPROVAL_NOT_FOUND.value)
        return ApprovalRequestResponse(**asdict(req))

    @application.post("/v1/approvals/{request_id}/decision", response_model=ApprovalRequestResponse)
    def decide_approval(request: Request, request_id: str, payload: ApprovalDecisionRequest):
        svc = _svc(request)
        if svc is None:
            return _error(request, 503, "Approval service is not ready.", FailureType.NOT_READY.value)
        audit = getattr(request.app.state, "audit", None)
        tenant = getattr(getattr(request.state, "tenant", None), "id", None)
        try:
            req = svc.decide(request_id, payload.decision, decided_by=payload.decided_by, note=payload.note)
        except KeyError:
            return _error(request, 404, "Approval request not found.", FailureType.APPROVAL_NOT_FOUND.value)
        except ValueError as exc:
            return _error(request, 400, str(exc), FailureType.APPROVAL_INVALID.value)
        if audit is not None and getattr(audit, "enabled", False):
            audit.record(
                "policy",
                "approval_decision",
                payload.decision,
                details={"approval_request_id": request_id, "action": req.action, "decided_by": payload.decided_by},
                request_id=_request_id(request),
                tenant=tenant,
            )
        return ApprovalRequestResponse(**asdict(req))
