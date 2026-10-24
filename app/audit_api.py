"""Audit-log read, integrity, export and retention endpoints (issues #28, #55).

The logger writes events; this module only exposes the read/compliance side:

* ``GET /v1/audit`` - filtered events (tenant/type/outcome/time window),
* ``GET /v1/audit/verify`` - hash-chain verification of the immutable store,
* ``GET /v1/audit/export`` - downloadable JSON export for a window,
* ``GET /v1/audit/evidence`` - compliance evidence pack (who/what/when,
  guardrail/governance counts, component versions, chain status),
* ``POST /v1/audit/purge`` - apply retention, exporting before deletion.
"""

import time
import uuid
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas import AuditEventsResponse, AuditPurgeRequest
from app.whatif_api import describe_pipeline
from core.services.audit_store import build_evidence_pack, parse_time
from core.services.failure_classifier import FailureType


def register_audit_routes(
    application: FastAPI, error_envelope: Callable[..., dict]
) -> None:
    def _request_id(request: Request) -> str:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())

    def _audit(request: Request):
        return getattr(request.app.state, "audit", None)

    def _error(request: Request, status: int, message: str, failure_type: str):
        return JSONResponse(
            status_code=status,
            content=error_envelope(
                message, failure_type, [], _request_id(request)
            ),
        )

    def _window(
        request: Request, start: Optional[str], end: Optional[str]
    ) -> tuple[Optional[float], Optional[float]] | JSONResponse:
        try:
            since = parse_time(start)
            until = parse_time(end)
        except ValueError as error:
            return _error(
                request, 400, str(error), FailureType.INVALID_REQUEST.value
            )
        if since is None:
            if until is None:
                until = time.time()
            since = float(until) - 86400
        elif until is None:
            until = time.time()
        if since > until:
            return _error(
                request,
                400,
                "'start' must be before 'end'.",
                FailureType.INVALID_REQUEST.value,
            )
        return since, until

    @application.get("/v1/audit", response_model=AuditEventsResponse)
    def audit_events(
        request: Request,
        limit: Optional[int] = None,
        event_type: Optional[str] = None,
        tenant: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ):
        audit = _audit(request)
        if audit is None:
            return _error(
                request,
                503,
                "Audit log is not ready.",
                FailureType.NOT_READY.value,
            )
        try:
            since_value = parse_time(since)
            until_value = parse_time(until)
        except ValueError as error:
            return _error(
                request, 400, str(error), FailureType.INVALID_REQUEST.value
            )
        events = audit.events(
            limit=limit,
            event_type=event_type,
            tenant=tenant,
            outcome=outcome,
            since=since_value,
            until=until_value,
        )
        return AuditEventsResponse(
            enabled=bool(getattr(audit, "enabled", False)),
            count=len(events),
            total=audit.count(),
            events=events,
            request_id=_request_id(request),
        )

    @application.get("/v1/audit/verify")
    def audit_verify(request: Request, region: Optional[str] = None):
        audit = _audit(request)
        if audit is None:
            return _error(
                request, 503, "Audit log is not ready.", FailureType.NOT_READY.value
            )
        result = audit.verify(region)
        return JSONResponse(
            status_code=200, content={**result, "request_id": _request_id(request)}
        )

    @application.get("/v1/audit/export")
    def audit_export(
        request: Request,
        start: Optional[str] = None,
        end: Optional[str] = None,
        tenant: Optional[str] = None,
        event_type: Optional[str] = None,
        outcome: Optional[str] = None,
    ):
        audit = _audit(request)
        if audit is None:
            return _error(
                request, 503, "Audit log is not ready.", FailureType.NOT_READY.value
            )
        window = _window(request, start, end)
        if isinstance(window, JSONResponse):
            return window
        since, until = window
        events = audit.events(
            tenant=tenant,
            event_type=event_type,
            outcome=outcome,
            since=since,
            until=until,
        )
        exported_at = time.time()
        payload = {
            "schema_version": 1,
            "exported_at": exported_at,
            "window": {"start": since, "end": until, "tenant": tenant},
            "count": len(events),
            "chain": audit.verify(),
            "events": events,
        }
        filename = f"audit-export-{int(exported_at)}.json"
        return JSONResponse(
            status_code=200,
            content=payload,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @application.get("/v1/audit/evidence")
    def audit_evidence(
        request: Request,
        start: Optional[str] = None,
        end: Optional[str] = None,
        tenant: Optional[str] = None,
    ):
        audit = _audit(request)
        if audit is None:
            return _error(
                request, 503, "Audit log is not ready.", FailureType.NOT_READY.value
            )
        window = _window(request, start, end)
        if isinstance(window, JSONResponse):
            return window
        since, until = window
        events = audit.events(tenant=tenant, since=since, until=until)
        pipeline = getattr(request.app.state, "pipeline", None)
        context = {
            "config_revision": getattr(request.app.state, "config_revision", None),
            "components": describe_pipeline(pipeline),
        }
        pack = build_evidence_pack(
            events,
            start=since,
            end=until,
            tenant=tenant,
            chain=audit.verify(),
            context=context,
        )
        return JSONResponse(status_code=200, content=pack)

    @application.post("/v1/audit/purge")
    def audit_purge(request: Request, payload: AuditPurgeRequest):
        audit = _audit(request)
        if audit is None:
            return _error(
                request, 503, "Audit log is not ready.", FailureType.NOT_READY.value
            )
        if getattr(audit, "sink", None) is None:
            return _error(
                request,
                400,
                "Immutable audit storage is not enabled.",
                FailureType.IMMUTABLE_AUDIT_DISABLED.value,
            )
        try:
            now = parse_time(payload.now)
        except ValueError as error:
            return _error(
                request, 400, str(error), FailureType.INVALID_REQUEST.value
            )
        result = audit.purge(now=now)
        return JSONResponse(
            status_code=200,
            content={**result, "request_id": _request_id(request)},
        )
