"""Tests for issue #223: bind X-Tenant-ID to the authenticated identity.

Acceptance covered:
- a JWT tenant claim / service-account key mapping binds the caller,
- a contradicting header is rejected with 403 ``forbidden_tenant_scope``,
- allowlisted roles and API keys may still cross tenant boundaries,
- unknown tenants stay 400 ``unknown_tenant`` (no silent fallback),
- denied override attempts are audited,
- identity-disabled tenancy keeps the legacy trusted-gateway ordering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.services.tenancy import (
    TenantResolver,
    TenantScopeError,
    UnknownTenantError,
)

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"
SECRET = "tenant-binding-test-secret-0123456789abcdef"
ISSUER = "https://idp.example.test/"
AUDIENCE = "genai-platform"

MODELS_YAML = """
active_model: dummy
active_embedding_model: emb-a
models:
  dummy:
    provider: dummy
    context_window: 4096
embedding_models:
  emb-a:
    provider: dummy
    model_name: emb-a
"""

RETRIEVAL_YAML = """
retrieval:
  default_retriever: dummy
  similarity_metric: cosine
  top_k: 3
  retrievers:
    dummy:
      provider: dummy
evaluation:
  enabled: false
  active_evaluator: dummy
  evaluators:
    dummy:
      provider: dummy
reranking:
  enabled: false
"""

ACCESS_YAML = """
enabled: true
default_role: viewer
roles:
  admin:
    capabilities: [query, introspect, governance, audit]
  analyst:
    capabilities: [query, introspect]
  viewer:
    capabilities: [query, introspect]
api_keys:
  svc-key: analyst
  gateway-key: analyst
"""

IDENTITY_YAML = f"""
enabled: true
issuer: {ISSUER}
audience: {AUDIENCE}
algorithms: [HS256]
secret: env:JWT_SECRET
leeway_seconds: 0
group_claim: groups
group_role_map:
  team-admin: admin
  team-analyst: analyst
default_role: viewer
allow_anonymous: false
allow_api_keys: true
scim:
  enabled: false
  tokens: []
saml:
  enabled: false
"""

TENANTS_YAML = """
enabled: true
default_tenant: default
tenants:
  default:
    workspace: default
    app: platform
  acme:
    workspace: acme-prod
    app: support
  beta:
    workspace: beta-dev
    app: reports
api_keys:
  svc-key: acme
header_override:
  roles: [admin]
  api_keys: [gateway-key]
"""

TENANTS_LEGACY_YAML = """
enabled: true
default_tenant: default
tenants:
  default: {}
  acme:
    workspace: acme-prod
  beta:
    workspace: beta-dev
api_keys:
  acme-key: acme
"""


class _DummyPipeline:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None, **kwargs):
        self.calls.append({"query": query, "request_id": request_id, **kwargs})
        return {
            "response": f"answer:{query}",
            "retrieved_docs": [],
            "retrieval_scores": [],
            "metrics": {},
            "cost": {"estimated_cost_usd": 0.0},
            "latency": {"total_ms": 0.0},
            "failure_tags": [],
            "observability": {"request_id": request_id, "status": "success"},
        }


def _token(
    *,
    subject: str = "user@example.test",
    groups: Optional[List[str]] = None,
    tenant: Optional[str] = None,
) -> str:
    now = datetime.now(timezone.utc)
    claims: Dict[str, Any] = {
        "sub": subject,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=600),
        "groups": groups or [],
    }
    if tenant:
        claims["tenant"] = tenant
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenants: str = TENANTS_YAML,
    identity: str = IDENTITY_YAML,
    pipeline: Optional[_DummyPipeline] = None,
) -> TestClient:
    monkeypatch.setenv("JWT_SECRET", SECRET)
    pipeline = pipeline or _DummyPipeline()
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    prompt = tmp_path / "prompt_config.yaml"
    prompt.write_text(REPO_PROMPT.read_text(encoding="utf-8"), encoding="utf-8")
    observability = _write(
        tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
    )
    access = _write(tmp_path / "access_control.yaml", ACCESS_YAML)
    identity_path = _write(tmp_path / "identity.yaml", identity)
    tenants_path = _write(tmp_path / "tenants.yaml", tenants)
    audit = _write(tmp_path / "audit.yaml", "enabled: true\nmax_entries: 100\n")
    app = create_app(
        models_config_path=models,
        retrieval_config_path=retrieval,
        prompt_config_path=prompt,
        observability_config_path=observability,
        access_control_config_path=access,
        identity_config_path=identity_path,
        tenants_config_path=tenants_path,
        audit_config_path=audit,
        pipeline_builder=lambda **_: pipeline,
    )
    return TestClient(app)


def _auth(groups: List[str], tenant: Optional[str] = None, **kwargs) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_token(groups=groups, tenant=tenant, **kwargs)}"}


# -- resolver unit tests -------------------------------------------------


def _resolver(**overrides) -> TenantResolver:
    config: Dict[str, Any] = {
        "enabled": True,
        "default_tenant": "default",
        "tenants": {"default": {}, "acme": {}, "beta": {}},
        "api_keys": {"svc-key": "acme"},
        "header_override": {"roles": ["admin"], "api_keys": ["gateway-key"]},
    }
    config.update(overrides)
    return TenantResolver.from_config(config)


def test_identity_binds_claim_and_matching_header_is_allowed():
    resolver = _resolver()
    assert resolver.resolve(principal_tenant="acme", identity_enabled=True).id == "acme"
    assert (
        resolver.resolve(
            tenant_header="acme", principal_tenant="acme", identity_enabled=True
        ).id
        == "acme"
    )


def test_contradicting_header_is_rejected_without_override_permission():
    resolver = _resolver()
    with pytest.raises(TenantScopeError) as exc:
        resolver.resolve(
            tenant_header="beta",
            principal_tenant="acme",
            principal_role="analyst",
            identity_enabled=True,
        )
    assert exc.value.requested == "beta"
    assert exc.value.bound == "acme"


def test_override_role_and_key_are_honored_but_unknown_target_still_fails():
    resolver = _resolver()
    assert (
        resolver.resolve(
            tenant_header="beta",
            principal_tenant="acme",
            principal_role="admin",
            identity_enabled=True,
        ).id
        == "beta"
    )
    assert (
        resolver.resolve(
            tenant_header="beta", api_key="gateway-key", identity_enabled=True
        ).id
        == "beta"
    )
    with pytest.raises(UnknownTenantError):
        resolver.resolve(
            tenant_header="ghost",
            principal_tenant="acme",
            principal_role="admin",
            identity_enabled=True,
        )


def test_service_account_key_mapping_binds_and_blocks_other_tenants():
    resolver = _resolver()
    assert (
        resolver.resolve(
            tenant_header="acme", api_key="svc-key", identity_enabled=True
        ).id
        == "acme"
    )
    with pytest.raises(TenantScopeError):
        resolver.resolve(
            tenant_header="beta", api_key="svc-key", identity_enabled=True
        )


def test_identity_disabled_keeps_legacy_header_and_key_precedence():
    resolver = _resolver()
    assert resolver.resolve(tenant_header="beta", api_key="svc-key").id == "beta"
    assert resolver.resolve(api_key="svc-key").id == "acme"
    assert resolver.resolve().id == "default"


def test_tenancy_disabled_ignores_header_even_with_identity():
    resolver = _resolver(enabled=False)
    assert (
        resolver.resolve(
            tenant_header="beta", principal_tenant="acme", identity_enabled=True
        ).id
        == "default"
    )


def test_header_override_projection_never_echoes_keys():
    resolver = _resolver()
    described = resolver.describe_header_override("admin", "gateway-key")
    assert described["enabled"] is True
    assert described["caller_allowed"] is True
    assert described["key_override_allowed"] is True
    assert "gateway-key" not in str(described)


# -- API behaviour -------------------------------------------------------


def test_api_rejects_cross_tenant_header_for_normal_caller(tmp_path, monkeypatch):
    pipeline = _DummyPipeline()
    with _client(tmp_path, monkeypatch, pipeline=pipeline) as client:
        denied = client.post(
            "/v1/query",
            json={"query": "hello"},
            headers={**_auth(["team-analyst"], tenant="acme"), "X-Tenant-ID": "beta"},
        )
        allowed = client.post(
            "/v1/query",
            json={"query": "hello"},
            headers={**_auth(["team-analyst"], tenant="acme"), "X-Tenant-ID": "acme"},
        )
    assert denied.status_code == 403
    assert denied.json()["failure_type"] == "forbidden"
    assert "forbidden_tenant_scope" in denied.json()["failure_tags"]
    assert "authenticated tenant" in denied.json()["error"]
    assert allowed.status_code == 200
    assert len(pipeline.calls) == 1


def test_api_override_role_can_select_another_tenant(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/v1/tenants",
            headers={**_auth(["team-admin"], tenant="acme"), "X-Tenant-ID": "beta"},
        )
    assert response.status_code == 200
    assert response.json()["current"]["id"] == "beta"


def test_api_service_account_mapping_blocks_header_spoofing(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        denied = client.get("/v1/tenants", headers={"X-API-Key": "svc-key", "X-Tenant-ID": "beta"})
        allowed = client.get("/v1/tenants", headers={"X-API-Key": "svc-key", "X-Tenant-ID": "acme"})
        override = client.get(
            "/v1/tenants", headers={"X-API-Key": "gateway-key", "X-Tenant-ID": "beta"}
        )
    assert denied.status_code == 403
    assert allowed.status_code == 200 and allowed.json()["current"]["id"] == "acme"
    assert override.status_code == 200 and override.json()["current"]["id"] == "beta"


def test_api_no_claim_binds_to_default_and_rejects_header(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        denied = client.get("/v1/tenants", headers={**_auth(["team-analyst"]), "X-Tenant-ID": "acme"})
        bound = client.get("/v1/tenants", headers=_auth(["team-analyst"]))
    assert denied.status_code == 403
    assert bound.status_code == 200
    assert bound.json()["current"]["id"] == "default"


def test_api_unknown_tenant_header_with_override_is_still_400(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/v1/tenants",
            headers={**_auth(["team-admin"], tenant="acme"), "X-Tenant-ID": "ghost"},
        )
    assert response.status_code == 400
    assert response.json()["failure_type"] == "unknown_tenant"


def test_denied_override_is_audited_and_scoped_to_bound_tenant(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post(
            "/v1/query",
            json={"query": "hello"},
            headers={**_auth(["team-analyst"], tenant="acme"), "X-Tenant-ID": "beta"},
        )
        events = client.get(
            "/v1/audit?event_type=tenant", headers=_auth(["team-admin"], tenant="acme")
        ).json()["events"]
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "tenant"
    assert event["action"] == "tenant_override"
    assert event["outcome"] == "denied"
    assert event["tenant"] == "acme"
    assert event["details"]["requested_tenant"] == "beta"
    assert event["details"]["authenticated_tenant"] == "acme"


def test_tenants_introspection_exposes_policy_and_caller_permission(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        analyst = client.get("/v1/tenants", headers=_auth(["team-analyst"], tenant="acme"))
        admin = client.get("/v1/tenants", headers=_auth(["team-admin"], tenant="acme"))
    assert analyst.status_code == 200
    policy = analyst.json()["header_override"]
    assert policy == {
        "enabled": True,
        "roles": ["admin"],
        "key_override_allowed": False,
        "caller_allowed": False,
    }
    assert admin.json()["header_override"]["caller_allowed"] is True
    assert "gateway-key" not in analyst.text


def test_legacy_tenancy_without_identity_still_honors_header(tmp_path, monkeypatch):
    identity = "enabled: false\nscim:\n  enabled: false\n  tokens: []\n"
    with _client(
        tmp_path,
        monkeypatch,
        tenants=TENANTS_LEGACY_YAML,
        identity=identity,
    ) as client:
        response = client.get(
            "/v1/tenants", headers={"X-API-Key": "acme-key", "X-Tenant-ID": "beta"}
        )
    assert response.status_code == 200
    assert response.json()["current"]["id"] == "beta"
    assert response.json()["header_override"]["enabled"] is False
