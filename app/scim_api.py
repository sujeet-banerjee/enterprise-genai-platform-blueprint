"""Minimal SCIM 2.0 provisioning surface (issue #49, workstream A2).

An IdP pushes users and groups here; :class:`core.services.identity.ScimDirectory`
applies the lifecycle and :class:`IdentityResolver` maps group membership to RBAC
roles on the next request. Only the subset needed for on/off-boarding is
implemented (list/create/replace/delete). Authentication uses a dedicated SCIM
bearer token from ``config/identity.yaml`` (``scim.tokens``), enforced by the
request middleware - tokens are never logged.

Persistence is out of scope here; durable stores are roadmap E4 (#56).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.services.failure_classifier import FailureType
from core.services.identity import ScimDirectory

SCIM_SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_SCHEMA_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def _user_resource(user: Any) -> Dict[str, Any]:
    resource: Dict[str, Any] = {
        "schemas": [SCIM_SCHEMA_USER],
        "id": user.id,
        "userName": user.user_name,
        "active": user.active,
    }
    if user.external_id:
        resource["externalId"] = user.external_id
    if user.display_name:
        resource["displayName"] = user.display_name
    return resource


def _group_resource(group: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schemas": [SCIM_SCHEMA_GROUP],
        "id": group["id"],
        "displayName": group["display_name"],
        "members": [
            {"value": member_id, "display": member_id}
            for member_id in group["members"]
        ],
    }


def _directory(request: Request) -> ScimDirectory:
    return request.app.state.identity.directory


def _scim_disabled(error_envelope: Callable[..., Dict[str, Any]], request: Request):
    return JSONResponse(
        status_code=404,
        content=error_envelope(
            "SCIM provisioning is not enabled.",
            FailureType.NOT_READY.value,
            ["scim_disabled"],
            _request_id(request),
        ),
        headers={"X-Request-ID": _request_id(request)},
    )


def _scim_enabled(request: Request) -> bool:
    identity = getattr(request.app.state, "identity", None)
    return bool(identity is not None and identity.scim_enabled)


def register_scim_routes(
    application: FastAPI, error_envelope: Callable[..., Dict[str, Any]]
) -> None:
    @application.get("/scim/v2/Users")
    def list_users(request: Request):
        if not _scim_enabled(request):
            return _scim_disabled(error_envelope, request)
        resources = [_user_resource(user) for user in _directory(request).users()]
        return {
            "schemas": [SCIM_SCHEMA_LIST],
            "totalResults": len(resources),
            "Resources": resources,
        }

    @application.post("/scim/v2/Users", status_code=201)
    async def upsert_user(request: Request):
        if not _scim_enabled(request):
            return _scim_disabled(error_envelope, request)
        payload = await request.json()
        user_name = str(payload.get("userName") or "").strip()
        if not user_name:
            return JSONResponse(
                status_code=400,
                content=error_envelope(
                    "userName is required.",
                    FailureType.UNKNOWN_FAILURE.value,
                    ["scim_invalid_payload"],
                    _request_id(request),
                ),
                headers={"X-Request-ID": _request_id(request)},
            )
        user = _directory(request).upsert_user(
            str(payload.get("id") or user_name),
            user_name,
            active=bool(payload.get("active", True)),
            external_id=payload.get("externalId"),
            display_name=payload.get("displayName"),
        )
        return _user_resource(user)

    @application.delete("/scim/v2/Users/{user_id}", status_code=204)
    def delete_user(user_id: str, request: Request):
        if not _scim_enabled(request):
            return _scim_disabled(error_envelope, request)
        _directory(request).delete_user(user_id)
        return JSONResponse(status_code=204, content=None)

    @application.get("/scim/v2/Groups")
    def list_groups(request: Request):
        if not _scim_enabled(request):
            return _scim_disabled(error_envelope, request)
        resources = [
            _group_resource(group) for group in _directory(request).groups()
        ]
        return {
            "schemas": [SCIM_SCHEMA_LIST],
            "totalResults": len(resources),
            "Resources": resources,
        }

    @application.post("/scim/v2/Groups", status_code=201)
    async def upsert_group(request: Request):
        if not _scim_enabled(request):
            return _scim_disabled(error_envelope, request)
        payload = await request.json()
        display_name = str(payload.get("displayName") or "").strip()
        if not display_name:
            return JSONResponse(
                status_code=400,
                content=error_envelope(
                    "displayName is required.",
                    FailureType.UNKNOWN_FAILURE.value,
                    ["scim_invalid_payload"],
                    _request_id(request),
                ),
                headers={"X-Request-ID": _request_id(request)},
            )
        members: List[str] = []
        for member in payload.get("members") or []:
            if isinstance(member, dict) and member.get("value"):
                members.append(str(member["value"]))
            elif isinstance(member, str):
                members.append(member)
        group = _directory(request).upsert_group(
            str(payload.get("id") or display_name), display_name, members
        )
        return _group_resource(group)

    @application.delete("/scim/v2/Groups/{group_id}", status_code=204)
    def delete_group(group_id: str, request: Request):
        if not _scim_enabled(request):
            return _scim_disabled(error_envelope, request)
        _directory(request).delete_group(group_id)
        return JSONResponse(status_code=204, content=None)
