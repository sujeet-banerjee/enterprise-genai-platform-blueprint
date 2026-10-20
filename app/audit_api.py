"""Audit-log read endpoint (issue #28).

Exposes the bounded in-memory audit trail created by ``AuditLogger`` in the
lifespan hook. Only the read side lives here; events are written by the query
and pipeline-rebuild paths so the audit log stays append-only.
"""

import uuid
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas import AuditEventsResponse
from core.services.failure_classifier import FailureType


def register_audit_routes(
    application: FastAPI, error_envelope: Callable[..., dict]
) -> None:
    def _request_id(request: Request) -> str:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())

    def _audit(request: Request):
        return getattr(request.app.state, "audit", None)

    @application.get("/v1/audit", response_model=AuditEventsResponse)
    def audit_events(
        request: Request,
        limit: Optional[int] = None,
        event_type: Optional[str] = None,
    ):
        audit = _audit(request)
        if audit is None:
            return JSONResponse(
                status_code=503,
                content=error_envelope(
                    "Audit log is not ready.",
                    FailureType.NOT_READY.value,
                    [],
                    _request_id(request),
                ),
            )
        events = audit.events(limit=limit, event_type=event_type)
        return AuditEventsResponse(
            enabled=bool(getattr(audit, "enabled", False)),
            count=len(events),
            total=audit.count(),
            events=events,
            request_id=_request_id(request),
        )
