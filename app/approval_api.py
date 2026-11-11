"""HITL approval workflow endpoints (#123, #175)."""

import uuid
from dataclasses import asdict
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas import ApprovalDecisionRequest, ApprovalListResponse, ApprovalRequestResponse
from core.services.approval import DEFAULT_PAGE_SIZE
from core.services.failure_classifier import FailureType


def register_approval_routes(application: FastAPI, error_envelope: Callable[..., dict]) -> None:
    def _request_id(request: Request) -> str:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())

    def _svc(request: Request):
        return getattr(request.app.state, "approvals", None)

    def _error(
        request: Request,
        status: int,
        message: str,
        failure_type: str,
        tags: Optional[list] = None,
    ):
        return JSONResponse(
            status_code=status,
            content=error_envelope(message, failure_type, list(tags or []), _request_id(request)),
        )

    def _max_page_size(request: Request) -> int:
        return int(getattr(request.app.state, "approvals_page_size_max", 100))

    def _tenant_scope(request: Request, requested: Optional[str]):
        """Resolve the tenant filter for a queue read (issue #175).

        With tenancy enabled a caller can only read its own tenant; asking for a
        different tenant yields a 403 envelope (query params cannot widen the
        scope). Disabled tenancy keeps the legacy behaviour.
        """
        resolver = getattr(request.app.state, "tenants", None)
        caller = getattr(request.state, "tenant_id", None)
        if resolver is not None and getattr(resolver, "enabled", False):
            if requested is not None and str(requested) != str(caller):
                return None, _error(
                    request,
                    403,
                    f"Tenant scope '{requested}' is not permitted.",
                    FailureType.FORBIDDEN.value,
                    ["forbidden_tenant_scope"],
                )
            return (str(caller) if caller is not None else None), None
        return (str(requested) if requested is not None else None), None

    def _request_visible(request: Request, req) -> bool:
        resolver = getattr(request.app.state, "tenants", None)
        if resolver is None or not getattr(resolver, "enabled", False):
            return True
        return req.tenant == getattr(request.state, "tenant_id", None)

    @application.get("/v1/approvals", response_model=ApprovalListResponse)
    def list_approvals(
        request: Request,
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
    ):
        svc = _svc(request)
        if svc is None:
            return _error(request, 503, "Approval service is not ready.", FailureType.NOT_READY.value)
        scoped_tenant, error = _tenant_scope(request, tenant)
        if error is not None:
            return error
        try:
            items, total = svc.query_requests(
                status=status,
                action=action,
                policy=policy,
                requester=requester,
                tenant=scoped_tenant,
                created_after=created_after,
                created_before=created_before,
                updated_after=updated_after,
                updated_before=updated_before,
                sort_by=sort_by,
                order=order,
                page=page,
                page_size=page_size,
                max_page_size=_max_page_size(request),
            )
        except ValueError as exc:
            return _error(request, 400, str(exc), FailureType.APPROVAL_INVALID.value)
        responses = [ApprovalRequestResponse(**asdict(r)) for r in items]
        pages = (total + page_size - 1) // page_size if page_size else 0
        return ApprovalListResponse(
            enabled=svc.enabled(),
            count=len(responses),
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            sort_by=sort_by,
            order=order,
            requests=responses,
            request_id=_request_id(request),
        )

    @application.get("/v1/approvals/{request_id}", response_model=ApprovalRequestResponse)
    def get_approval(request: Request, request_id: str):
        svc = _svc(request)
        if svc is None:
            return _error(request, 503, "Approval service is not ready.", FailureType.NOT_READY.value)
        req = svc.get(request_id)
        if req is None or not _request_visible(request, req):
            return _error(request, 404, "Approval request not found.", FailureType.APPROVAL_NOT_FOUND.value)
        return ApprovalRequestResponse(**asdict(req))

    @application.post("/v1/approvals/{request_id}/decision", response_model=ApprovalRequestResponse)
    def decide_approval(request: Request, request_id: str, payload: ApprovalDecisionRequest):
        svc = _svc(request)
        if svc is None:
            return _error(request, 503, "Approval service is not ready.", FailureType.NOT_READY.value)
        existing = svc.get(request_id)
        if existing is None:
            return _error(request, 404, "Approval request not found.", FailureType.APPROVAL_NOT_FOUND.value)
        if not _request_visible(request, existing):
            return _error(
                request,
                403,
                "Approval request belongs to another tenant.",
                FailureType.FORBIDDEN.value,
                ["forbidden_tenant_scope"],
            )
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
