"""Async operations API for long-running query work (issue #279)."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from app.schemas import (
    OperationListResponse,
    OperationStatusResponse,
    OperationSubmitResponse,
    QueryRequest,
)
from core.services.failure_classifier import FailureType
from core.services.operation_jobs import OperationJobsService, OperationQueueFullError

MAX_RECENT_WINDOW_SECONDS = 7 * 24 * 3600


def operation_owner(request: Request) -> str:
    """Resolve a stable, non-spoofable owner key for an async operation.

    An authenticated subject always wins. The `X-Client-Session` fallback is a
    possession token for anonymous/UI sessions and is tenant-qualified; callers
    still cannot enumerate another owner's operations.
    """
    subject = getattr(request.state, "subject", None)
    tenant = getattr(request.state, "tenant_id", None) or "default"
    if subject:
        return f"subject:{subject}"
    session = str(request.headers.get("X-Client-Session") or "").strip()
    if session:
        return f"session:{tenant}:{session}"
    return f"tenant:{tenant}:anonymous"


def _public_operation(entry: Dict[str, Any]) -> OperationStatusResponse:
    fields = OperationStatusResponse.model_fields.keys()
    return OperationStatusResponse(**{key: entry.get(key) for key in fields if key in entry})


def _operation_visible(entry: Dict[str, Any], request: Request) -> bool:
    caller_tenant = getattr(request.state, "tenant_id", None)
    resolver = getattr(request.app.state, "tenants", None)
    if resolver is not None and getattr(resolver, "enabled", False):
        if entry.get("tenant") not in (None, caller_tenant):
            return False
    return str(entry.get("owner") or "") == operation_owner(request)


def register_operations_routes(
    application: FastAPI,
    *,
    error_envelope: Callable[..., dict],
    execute_query: Callable[[Request, QueryRequest, str], tuple[dict, int]],
    on_complete: Optional[Callable[[Request, Dict[str, Any]], None]] = None,
) -> None:
    def _request_id(request: Request) -> str:
        return str(getattr(request.state, "request_id", None) or uuid.uuid4())

    def _error(
        request: Request,
        message: str,
        failure_type: FailureType,
        tags: list[str],
        status_code: int,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=error_envelope(
                message, failure_type.value, tags, _request_id(request)
            ),
            headers={"X-Request-ID": _request_id(request)},
        )

    def _service(request: Request) -> tuple[Optional[OperationJobsService], Optional[JSONResponse]]:
        service = getattr(request.app.state, "operations", None)
        if service is None or not getattr(service, "enabled", True):
            return None, _error(
                request,
                "Operations service is not ready.",
                FailureType.NOT_READY,
                ["operations_not_ready"],
                503,
            )
        return service, None

    def _experiment_operation(request: Request, op_id: str) -> Optional[Dict[str, Any]]:
        service = getattr(request.app.state, "evaluate", None)
        if service is None:
            return None
        entry = service.get_experiment(op_id)
        if entry is None:
            return None
        return OperationJobsService.experiment_as_operation(entry)

    @application.post(
        "/v1/operations/query",
        response_model=OperationSubmitResponse,
        status_code=202,
    )
    def submit_query_operation(request: Request, payload: QueryRequest):
        service, error = _service(request)
        if error is not None:
            return error
        assert service is not None
        request_id = _request_id(request)
        tenant = getattr(request.state, "tenant_id", None)
        tenant_obj = getattr(request.state, "tenant", None)

        def _runner() -> Dict[str, Any]:
            body, _status = execute_query(request, payload, request_id)
            return body

        def _complete(final: Dict[str, Any]) -> None:
            if on_complete is not None:
                on_complete(request, final)

        try:
            entry = service.submit_query(
                request_id=request_id,
                kind="query",
                owner=operation_owner(request),
                tenant=tenant,
                workspace=getattr(tenant_obj, "workspace", None),
                app=getattr(tenant_obj, "app", None),
                payload=payload.model_dump(),
                runner=_runner,
                on_complete=_complete,
            )
        except OperationQueueFullError as exc:
            return _error(
                request,
                str(exc),
                FailureType.RATE_LIMITED,
                ["rate_limited", "operation_queue_full"],
                429,
            )
        return _public_operation(entry)

    @application.get("/v1/operations/{op_id}", response_model=OperationStatusResponse)
    def get_operation(request: Request, op_id: str):
        service, error = _service(request)
        if error is not None:
            return error
        assert service is not None
        entry = service.get(op_id) or _experiment_operation(request, op_id)
        if entry is None or not _operation_visible(entry, request):
            return _error(
                request,
                f"Operation '{op_id}' was not found.",
                FailureType.UNKNOWN_FAILURE,
                ["operation_not_found"],
                404,
            )
        return _public_operation(entry)

    @application.get("/v1/operations", response_model=OperationListResponse)
    def list_operations(
        request: Request,
        status: Optional[str] = None,
        mine: bool = True,
        recent_window_seconds: Optional[int] = Query(
            None, ge=1, le=MAX_RECENT_WINDOW_SECONDS
        ),
        limit: Optional[int] = Query(None, ge=1),
    ):
        service, error = _service(request)
        if error is not None:
            return error
        assert service is not None
        if not mine and "governance" not in set(
            getattr(request.state, "capabilities", None) or []
        ):
            return _error(
                request,
                "Cross-owner operation listing requires the governance capability.",
                FailureType.FORBIDDEN,
                ["forbidden_operation_scope"],
                403,
            )
        default_limit = int(getattr(request.app.state, "operations_list_limit_default", 100))
        max_limit = int(getattr(request.app.state, "operations_list_limit_max", 500))
        eff_limit = min(int(limit or default_limit), max(1, max_limit))
        eff_recent = recent_window_seconds or int(
            getattr(service, "recent_window_seconds", 3600)
        )
        eval_service = getattr(request.app.state, "evaluate", None)
        experiment_entries = (
            eval_service.list_experiments(limit=eff_limit)
            if eval_service is not None and hasattr(eval_service, "list_experiments")
            else []
        )
        items = service.list_operations(
            owner=operation_owner(request),
            tenant=getattr(request.state, "tenant_id", None),
            status=status,
            mine=mine,
            recent_window_seconds=eff_recent,
            limit=eff_limit,
            experiment_entries=experiment_entries,
        )
        return OperationListResponse(
            operations=[_public_operation(item) for item in items],
            count=len(items),
            request_id=_request_id(request),
        )
