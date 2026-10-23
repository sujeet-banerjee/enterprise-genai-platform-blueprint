"""Tests for issue #49: standards-based identity (workstream A2).

Acceptance covered:
- valid JWT grants access; invalid/missing/expired tokens yield 401 envelopes,
- IdP group claims map to RBAC roles,
- SCIM group changes alter effective capabilities at request time,
- service-account API keys keep working,
- identity is disabled by default (stub behaviour unchanged),
- tokens/secrets never appear in responses or the config view.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.services.access_control import AccessController
from core.services.identity import (
    IdentityAuthError,
    IdentityConfigError,
    IdentityResolver,
    JwtVerifier,
    ScimDirectory,
)
from core.services.observability import SensitiveDataRedactor

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"
SECRET = "unit-test-secret-value-0123456789abcdef"
SCIM_TOKEN = "unit-test-scim-token"
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
    capabilities: [query, batch, evaluate, experiment, rebuild, introspect, governance, audit]
  analyst:
    capabilities: [query, batch, evaluate, experiment, introspect]
  viewer:
    capabilities: [query, introspect]
api_keys:
  svc-key: analyst
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
  team-analyst: analyst
  team-viewer: viewer
default_role: viewer
allow_anonymous: false
allow_api_keys: true
scim:
  enabled: true
  tokens: ["env:SCIM_TOKEN"]
saml:
  enabled: false
"""

IDENTITY_DISABLED_YAML = """
enabled: false
scim:
  enabled: false
  tokens: []
"""


class _DummyPipeline:
    def run(self, query, top_k=None, raise_on_failure=None, request_id=None, **kwargs):
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
    subject: str = "user@example.test",
    groups: Optional[List[str]] = None,
    *,
    secret: str = SECRET,
    expires_in: int = 600,
    tenant: Optional[str] = None,
    audience: str = AUDIENCE,
    issuer: str = ISSUER,
) -> str:
    now = datetime.now(timezone.utc)
    claims: Dict[str, Any] = {
        "sub": subject,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "groups": groups or [],
    }
    if tenant:
        claims["tenant"] = tenant
    return jwt.encode(claims, secret, algorithm="HS256")


def _verifier() -> JwtVerifier:
    return JwtVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=["HS256"],
        secret=SECRET,
        leeway_seconds=0,
    )


def _access() -> AccessController:
    return AccessController(
        enabled=True,
        roles={
            "admin": {"capabilities": ["query", "batch", "rebuild", "audit"]},
            "analyst": {"capabilities": ["query", "batch", "evaluate"]},
            "viewer": {"capabilities": ["query", "introspect"]},
        },
        api_keys={"svc-key": "analyst"},
        default_role="viewer",
    )


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity: str = IDENTITY_YAML,
    tenants: Optional[str] = None,
) -> TestClient:
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("SCIM_TOKEN", SCIM_TOKEN)
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    prompt = tmp_path / "prompt_config.yaml"
    prompt.write_text(REPO_PROMPT.read_text(encoding="utf-8"), encoding="utf-8")
    observability = _write(
        tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
    )
    access = _write(tmp_path / "access_control.yaml", ACCESS_YAML)
    identity_path = _write(tmp_path / "identity.yaml", identity)
    kwargs: Dict[str, Any] = {}
    if tenants is not None:
        kwargs["tenants_config_path"] = _write(tmp_path / "tenants.yaml", tenants)
    app = create_app(
        models_config_path=models,
        retrieval_config_path=retrieval,
        prompt_config_path=prompt,
        observability_config_path=observability,
        access_control_config_path=access,
        identity_config_path=identity_path,
        pipeline_builder=lambda **_: _DummyPipeline(),
        **kwargs,
    )
    return TestClient(app)


# -- JWT verification ----------------------------------------------------


def test_valid_jwt_is_accepted():
    claims = _verifier().verify(_token(groups=["team-analyst"]))
    assert claims["sub"] == "user@example.test"
    assert claims["groups"] == ["team-analyst"]


def test_expired_jwt_is_rejected():
    with pytest.raises(IdentityAuthError) as exc:
        _verifier().verify(_token(expires_in=-10))
    assert exc.value.reason == "token_expired"
    assert "identity_token_expired" in exc.value.failure_tags


def test_invalid_signature_is_rejected():
    with pytest.raises(IdentityAuthError) as exc:
        _verifier().verify(_token(secret="the-wrong-secret"))
    assert exc.value.reason == "invalid_token"


def test_missing_credentials_and_anonymous_gate():
    resolver = IdentityResolver(
        enabled=True, verifier=_verifier(), access=_access(), allow_anonymous=False
    )
    with pytest.raises(IdentityAuthError) as exc:
        resolver.authenticate(None, None)
    assert exc.value.reason == "missing_credentials"

    anonymous = IdentityResolver(
        enabled=True,
        verifier=_verifier(),
        access=_access(),
        allow_anonymous=True,
        default_role="viewer",
    ).authenticate(None, None)
    assert anonymous is not None
    assert anonymous.subject == "anonymous"
    assert anonymous.role == "viewer"


def test_group_claim_maps_to_role_and_scim_change_updates_it():
    directory = ScimDirectory()
    directory.upsert_user("u1", "user@example.test")
    directory.upsert_group("g1", "team-analyst", ["u1"])
    resolver = IdentityResolver(
        enabled=True,
        verifier=_verifier(),
        access=_access(),
        directory=directory,
        group_role_map={"team-analyst": "analyst", "team-viewer": "viewer"},
        default_role="viewer",
    )
    principal = resolver.authenticate(f"Bearer {_token()}", None)
    assert principal is not None
    assert principal.role == "analyst"
    assert principal.groups == ["team-analyst"]

    # IdP pushes a group change -> effective capabilities change immediately.
    directory.upsert_group("g1", "team-viewer", ["u1"])
    principal = resolver.authenticate(f"Bearer {_token()}", None)
    assert principal is not None and principal.role == "viewer"
    assert resolver.access.has_capability(principal.role, "batch") is False


def test_service_account_api_key_and_unknown_key():
    resolver = IdentityResolver(
        enabled=True, verifier=_verifier(), access=_access(), allow_api_keys=True
    )
    principal = resolver.authenticate(None, "svc-key")
    assert principal is not None
    assert principal.role == "analyst"
    assert principal.auth_method == "api_key"
    with pytest.raises(IdentityAuthError) as exc:
        resolver.authenticate(None, "not-a-key")
    assert exc.value.reason == "invalid_api_key"


def test_scim_directory_matches_identity_identifiers():
    directory = ScimDirectory()
    directory.upsert_user("u1", "user@example.test", external_id="ext-42")
    directory.upsert_group("g1", "team-analyst", ["u1"])
    assert directory.groups_for("u1") == ["team-analyst"]
    assert directory.groups_for("user@example.test") == ["team-analyst"]
    assert directory.groups_for("ext-42") == ["team-analyst"]

    directory.upsert_user("u1", "user@example.test", active=False, external_id="ext-42")
    assert directory.active("user@example.test") is False


def test_saml_enabled_fails_fast_with_oidc_bridge_guidance():
    with pytest.raises(IdentityConfigError, match="OIDC bridge"):
        IdentityResolver.from_config({"enabled": False, "saml": {"enabled": True}})


# -- API integration -----------------------------------------------------


def test_identity_disabled_keeps_legacy_behaviour(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, identity=IDENTITY_DISABLED_YAML) as client:
        response = client.post("/v1/query", json={"query": "hello"})
        assert response.status_code == 200, response.text
        access = client.get("/v1/access").json()
        assert access["identity_enabled"] is False
        assert access["role"] == "viewer"


def test_api_valid_invalid_and_missing_tokens(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        token = _token(groups=["team-analyst"])
        ok = client.post(
            "/v1/query", json={"query": "hello"}, headers={"Authorization": f"Bearer {token}"}
        )
        assert ok.status_code == 200, ok.text
        assert token not in ok.text

        missing = client.post("/v1/query", json={"query": "hello"})
        assert missing.status_code == 401
        assert missing.json()["failure_type"] == "unauthorized"
        assert "identity_missing_credentials" in missing.json()["failure_tags"]

        invalid = client.post(
            "/v1/query",
            json={"query": "hello"},
            headers={"Authorization": f"Bearer {_token(secret='wrong')}"},
        )
        assert invalid.status_code == 401
        assert "identity_invalid_token" in invalid.json()["failure_tags"]

        access = client.get(
            "/v1/access", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert access["identity_enabled"] is True
        assert access["role"] == "analyst"
        assert access["subject"] == "user@example.test"
        assert access["groups"] == ["team-analyst"]


def test_scim_group_change_changes_effective_capabilities(tmp_path, monkeypatch):
    headers = {"Authorization": f"Bearer {SCIM_TOKEN}"}
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/scim/v2/Users").status_code == 401

        user = client.post(
            "/scim/v2/Users",
            json={"userName": "user@example.test", "active": True},
            headers=headers,
        )
        assert user.status_code == 201, user.text
        assert user.json()["userName"] == "user@example.test"

        group = client.post(
            "/scim/v2/Groups",
            json={
                "id": "g1",
                "displayName": "team-analyst",
                "members": [{"value": "user@example.test"}],
            },
            headers=headers,
        )
        assert group.status_code == 201, group.text
        assert client.get("/scim/v2/Groups", headers=headers).json()["totalResults"] == 1

        token = _token()
        access = client.get(
            "/v1/access", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert access["role"] == "analyst"
        assert "batch" in access["capabilities"]

        client.post(
            "/scim/v2/Groups",
            json={
                "id": "g1",
                "displayName": "team-viewer",
                "members": [{"value": "user@example.test"}],
            },
            headers=headers,
        )
        access = client.get(
            "/v1/access", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert access["role"] == "viewer"
        assert "batch" not in access["capabilities"]

        # Deactivating the SCIM user revokes access on the next request.
        client.post(
            "/scim/v2/Users",
            json={"id": user.json()["id"], "userName": "user@example.test", "active": False},
            headers=headers,
        )
        blocked = client.get(
            "/v1/access", headers={"Authorization": f"Bearer {token}"}
        )
        assert blocked.status_code == 401
        assert "identity_inactive_subject" in blocked.json()["failure_tags"]


def test_scim_disabled_endpoint_is_404(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, identity=IDENTITY_DISABLED_YAML) as client:
        response = client.get(
            "/scim/v2/Users", headers={"Authorization": f"Bearer {SCIM_TOKEN}"}
        )
        assert response.status_code == 404
        assert response.json()["failure_tags"] == ["scim_disabled"]


def test_tenant_claim_is_used_when_header_absent(tmp_path, monkeypatch):
    tenants = """
enabled: true
default_tenant: default
tenants:
  default: {}
  acme:
    workspace: acme-prod
    app: support
"""
    with _client(tmp_path, monkeypatch, tenants=tenants) as client:
        token = _token(tenant="acme")
        access = client.get(
            "/v1/access", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert access["tenant"]["id"] == "acme"
        assert access["tenant"]["workspace"] == "acme-prod"

        # An explicit header still wins over the token claim.
        override = client.get(
            "/v1/access",
            headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": "default"},
        ).json()
        assert override["tenant"]["id"] == "default"


def test_token_secrets_are_redacted_from_text_and_config_view(tmp_path, monkeypatch):
    token = _token()
    redacted = SensitiveDataRedactor().redact_text(f"Authorization: Bearer {token}")
    assert token not in redacted
    assert "[REDACTED]" in redacted

    with _client(tmp_path, monkeypatch) as client:
        config = client.get(
            "/v1/config", headers={"Authorization": f"Bearer {token}"}
        )
        assert config.status_code == 200, config.text
        body = config.text
        assert SECRET not in body
        assert SCIM_TOKEN not in body
        identity_section = config.json()["config"]["identity"]
        assert "secret" not in identity_section
        assert "tokens" not in identity_section["scim"]
