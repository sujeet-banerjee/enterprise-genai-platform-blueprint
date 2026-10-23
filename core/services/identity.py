"""Standards-based identity for the API (issue #49, workstream A2).

The platform ships with an API-key stub (``config/api.yaml``) and a config-driven
RBAC layer (``core/services/access_control.py``). This module adds the missing
enterprise identity layer:

* **OIDC / OAuth2 bearer tokens** - signature, issuer, audience and expiry are
  validated against a JWKS endpoint (or a shared secret for local/testing use).
  Subject, groups, role and tenant claims are extracted.
* **IdP group -> RBAC role mapping** - ``group_role_map`` in
  ``config/identity.yaml`` turns group claims into an existing RBAC role.
* **SCIM directory sync** - ``ScimDirectory`` applies user/group lifecycle
  pushes from an IdP; group membership feeds the same role mapping, so
  off-boarding a group removes capabilities without a redeploy.
* **Service accounts** - scoped API keys from ``config/access_control.yaml``
  keep working for machine callers.

Everything is disabled by default: with ``identity.enabled: false`` the
resolver returns ``None`` and the existing API-key/RBAC behaviour is untouched.

SAML: direct SAML SP support is intentionally not implemented. The supported
path is an OIDC bridge (any SAML IdP can front OIDC, e.g. via the IdP itself or
a broker); ``saml.enabled: true`` fails fast with that guidance instead of
silently pretending to support SAML.

Tokens are never logged. The observability redactor already scrubs
``authorization``/``bearer`` values (issue #16), and this module never returns
or records a token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from core.services.access_control import AccessController

GROUP_CLAIM_DEFAULT = "groups"
ROLE_CLAIM_DEFAULT = "role"
TENANT_CLAIM_DEFAULT = "tenant"
DEFAULT_ROLE = "viewer"


class IdentityError(RuntimeError):
    """Base class for identity configuration/runtime errors."""


class IdentityConfigError(IdentityError):
    """Raised at startup when the identity configuration is unusable."""


class IdentityAuthError(IdentityError):
    """Raised when a request cannot be authenticated (maps to HTTP 401)."""

    def __init__(self, message: str, *, reason: str = "invalid_token"):
        super().__init__(message)
        self.reason = reason
        self.failure_tags = [f"identity_{reason}"]


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity."""

    subject: str
    role: str
    groups: List[str] = field(default_factory=list)
    tenant: Optional[str] = None
    email: Optional[str] = None
    claims: Dict[str, Any] = field(default_factory=dict)
    auth_method: str = "oidc"

    def describe(self) -> Dict[str, Any]:
        """Safe projection for /v1/access - claims and tokens never leave."""
        return {
            "subject": self.subject,
            "role": self.role,
            "groups": list(self.groups),
            "tenant": self.tenant,
            "auth_method": self.auth_method,
        }


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


def _import_jwt():
    try:
        import jwt as pyjwt  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - dependency is pinned
        raise IdentityConfigError(
            "Identity requires PyJWT. Install it with `pip install pyjwt[crypto]`."
        ) from exc
    return pyjwt


class JwtVerifier:
    """Validates JWT bearer tokens (HS* shared secret or JWKS)."""

    def __init__(
        self,
        *,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        algorithms: Optional[Sequence[str]] = None,
        jwks_uri: Optional[str] = None,
        secret: Optional[str] = None,
        leeway_seconds: int = 30,
        key_resolver: Optional[Callable[[str], Any]] = None,
    ):
        self.issuer = issuer or None
        self.audience = audience or None
        self.algorithms = list(algorithms or (["HS256"] if secret else ["RS256"]))
        self.jwks_uri = jwks_uri or None
        self.secret = secret or None
        self.leeway_seconds = max(0, int(leeway_seconds))
        self._key_resolver = key_resolver
        self._jwks_client: Any = None
        if not self.secret and not self.jwks_uri and key_resolver is None:
            raise IdentityConfigError(
                "identity requires either `jwks_uri`, `secret`, or a key resolver."
            )
        # Fail at startup, not on the first request, if PyJWT is missing.
        _import_jwt()

    def _key_for(self, token: str) -> Any:
        if self._key_resolver is not None:
            header = _import_jwt().get_unverified_header(token)
            return self._key_resolver(str(header.get("kid") or ""))
        if self.secret:
            return self.secret
        if self._jwks_client is None:
            pyjwt = _import_jwt()
            self._jwks_client = pyjwt.PyJWKClient(self.jwks_uri)
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Dict[str, Any]:
        pyjwt = _import_jwt()
        if not token:
            raise IdentityAuthError("Missing bearer token.", reason="missing_token")
        try:
            key = self._key_for(token)
            claims = pyjwt.decode(
                token,
                key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub"]},
                leeway=self.leeway_seconds,
            )
        except IdentityError:
            raise
        except Exception as exc:
            reason = "invalid_token"
            name = type(exc).__name__
            if "Expired" in name:
                reason = "token_expired"
            elif "MissingRequiredClaim" in name:
                reason = "missing_claim"
            elif "InvalidAudience" in name:
                reason = "invalid_audience"
            elif "InvalidIssuer" in name:
                reason = "invalid_issuer"
            raise IdentityAuthError(
                f"Invalid bearer token ({name}).", reason=reason
            ) from exc
        if not isinstance(claims, dict):  # pragma: no cover - defensive
            raise IdentityAuthError("Invalid bearer token.", reason="invalid_token")
        return claims


# ---------------------------------------------------------------------------
# SCIM directory (user/group lifecycle)
# ---------------------------------------------------------------------------


@dataclass
class ScimUser:
    id: str
    user_name: str
    active: bool = True
    external_id: Optional[str] = None
    display_name: Optional[str] = None


class ScimDirectory:
    """In-memory SCIM user/group projection.

    The API surface (``app/scim_api.py``) applies IdP pushes here; identity
    resolution reads group membership from it on every request. Persistence is
    deliberately out of scope (roadmap E4 / #56 owns durable stores).
    """

    def __init__(self) -> None:
        self._users: Dict[str, ScimUser] = {}
        self._groups: Dict[str, Dict[str, Any]] = {}

    # -- users ------------------------------------------------------------
    def upsert_user(
        self,
        user_id: str,
        user_name: str,
        *,
        active: bool = True,
        external_id: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> ScimUser:
        user = ScimUser(
            id=str(user_id),
            user_name=str(user_name),
            active=bool(active),
            external_id=str(external_id) if external_id else None,
            display_name=display_name,
        )
        self._users[user.id] = user
        return user

    def delete_user(self, user_id: str) -> bool:
        return self._users.pop(str(user_id), None) is not None

    def get_user(self, user_id: str) -> Optional[ScimUser]:
        return self._users.get(str(user_id))

    def users(self) -> List[ScimUser]:
        return list(self._users.values())

    # -- groups -----------------------------------------------------------
    def upsert_group(
        self, group_id: str, display_name: str, member_ids: Iterable[str]
    ) -> Dict[str, Any]:
        group: Dict[str, Any] = {
            "id": str(group_id),
            "display_name": str(display_name),
            "members": sorted({str(m) for m in member_ids}),
        }
        self._groups[group["id"]] = group
        return dict(group)

    def delete_group(self, group_id: str) -> bool:
        return self._groups.pop(str(group_id), None) is not None

    def groups(self) -> List[Dict[str, Any]]:
        return [dict(group) for group in self._groups.values()]

    def _identifiers(self, identity: str) -> Set[str]:
        identity = str(identity)
        ids: Set[str] = {identity}
        for user in self._users.values():
            if identity in {user.id, user.user_name, user.external_id}:
                ids.add(user.id)
        return ids

    def groups_for(self, identity: str) -> List[str]:
        """Group display names for an identity (subject/userName/externalId)."""
        ids = self._identifiers(identity)
        membership: List[str] = []
        for group in self._groups.values():
            if ids.intersection(group["members"]):
                membership.append(str(group["display_name"]))
        return sorted(membership)

    def active(self, identity: str) -> bool:
        """False only when the identity maps to a deactivated SCIM user."""
        ids = self._identifiers(identity)
        for user in self._users.values():
            if user.id in ids:
                return user.active
        return True


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


class IdentityResolver:
    """Turns a bearer token / service-account key into a :class:`Principal`."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        verifier: Optional[JwtVerifier] = None,
        access: Optional[AccessController] = None,
        group_claim: str = GROUP_CLAIM_DEFAULT,
        role_claim: str = ROLE_CLAIM_DEFAULT,
        tenant_claim: str = TENANT_CLAIM_DEFAULT,
        group_role_map: Optional[Dict[str, str]] = None,
        default_role: str = DEFAULT_ROLE,
        allow_anonymous: bool = False,
        allow_api_keys: bool = True,
        directory: Optional[ScimDirectory] = None,
        scim_tokens: Optional[Sequence[str]] = None,
        scim_enabled: bool = False,
    ):
        self.enabled = bool(enabled)
        self.verifier = verifier
        self.access = access or AccessController(enabled=False)
        self.group_claim = group_claim or GROUP_CLAIM_DEFAULT
        self.role_claim = role_claim or ROLE_CLAIM_DEFAULT
        self.tenant_claim = tenant_claim or TENANT_CLAIM_DEFAULT
        self.group_role_map = {
            str(group): str(role) for group, role in (group_role_map or {}).items()
        }
        self.default_role = str(default_role or DEFAULT_ROLE)
        self.allow_anonymous = bool(allow_anonymous)
        self.allow_api_keys = bool(allow_api_keys)
        self.directory = directory or ScimDirectory()
        self.scim_enabled = bool(scim_enabled)
        self._scim_tokens = {str(token) for token in (scim_tokens or []) if token}
        if self.enabled and self.verifier is None:
            raise IdentityConfigError("identity.enabled requires a configured verifier.")

    # -- role / group mapping --------------------------------------------
    def groups_for_claims(self, claims: Dict[str, Any]) -> List[str]:
        raw = claims.get(self.group_claim) or []
        if isinstance(raw, str):
            groups = [raw]
        elif isinstance(raw, (list, tuple, set)):
            groups = [str(item) for item in raw]
        else:
            groups = []
        subject = str(claims.get("sub") or "")
        scim_groups = self.directory.groups_for(subject) if subject else []
        combined = {group for group in groups if group}
        combined.update(scim_groups)
        return sorted(combined)

    def role_for(
        self, groups: Sequence[str], claimed_role: Optional[str] = None
    ) -> str:
        for group in groups:
            mapped = self.group_role_map.get(str(group))
            if mapped:
                return mapped
        if claimed_role and claimed_role in self.access.roles:
            return str(claimed_role)
        return self.default_role

    def _principal_from_claims(self, claims: Dict[str, Any]) -> Principal:
        subject = str(claims.get("sub") or "")
        if not subject:
            raise IdentityAuthError("Token has no subject.", reason="missing_claim")
        if not self.directory.active(subject):
            raise IdentityAuthError(
                "Identity is deactivated.", reason="inactive_subject"
            )
        groups = self.groups_for_claims(claims)
        claimed_role = claims.get(self.role_claim)
        role = self.role_for(groups, str(claimed_role) if claimed_role else None)
        tenant = claims.get(self.tenant_claim)
        email = claims.get("email") or claims.get("preferred_username")
        return Principal(
            subject=subject,
            role=role,
            groups=groups,
            tenant=str(tenant) if tenant else None,
            email=str(email) if email else None,
            claims=dict(claims),
            auth_method="oidc",
        )

    # -- request authentication ------------------------------------------
    @staticmethod
    def bearer_token(authorization: Optional[str]) -> Optional[str]:
        if not authorization:
            return None
        parts = authorization.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        token = parts[1].strip()
        return token or None

    def authenticate(
        self, authorization: Optional[str], api_key: Optional[str] = None
    ) -> Optional[Principal]:
        """Resolve a principal, or ``None`` when identity is disabled."""
        if not self.enabled:
            return None

        token = self.bearer_token(authorization)
        if token:
            assert self.verifier is not None
            claims = self.verifier.verify(token)
            return self._principal_from_claims(claims)

        if api_key and self.allow_api_keys:
            role = self.access.api_keys.get(str(api_key))
            if role is None:
                raise IdentityAuthError(
                    "Unknown service-account API key.", reason="invalid_api_key"
                )
            return Principal(
                subject=f"service-account:{role}",
                role=role,
                groups=[],
                auth_method="api_key",
            )

        if self.allow_anonymous:
            return Principal(
                subject="anonymous",
                role=self.default_role,
                groups=[],
                auth_method="anonymous",
            )
        raise IdentityAuthError(
            "Authentication required.", reason="missing_credentials"
        )

    # -- SCIM authorisation ----------------------------------------------
    def scim_authorized(self, authorization: Optional[str]) -> bool:
        if not self.scim_enabled:
            return False
        token = self.bearer_token(authorization)
        return bool(token) and token in self._scim_tokens

    # -- config -----------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        config: Optional[Dict[str, Any]],
        *,
        access: Optional[AccessController] = None,
        directory: Optional[ScimDirectory] = None,
    ) -> "IdentityResolver":
        config = config or {}
        saml = config.get("saml") or {}
        if isinstance(saml, dict) and saml.get("enabled"):
            raise IdentityConfigError(
                "Direct SAML SP support is not built in. Terminate SAML at an "
                "OIDC bridge (broker or IdP) and configure `issuer`/`jwks_uri`."
            )
        scim = config.get("scim") or {}
        verifier = None
        if bool(config.get("enabled", False)):
            verifier = JwtVerifier(
                issuer=config.get("issuer"),
                audience=config.get("audience"),
                algorithms=config.get("algorithms"),
                jwks_uri=config.get("jwks_uri"),
                secret=config.get("secret"),
                leeway_seconds=int(config.get("leeway_seconds", 30) or 0),
            )
        tokens = scim.get("tokens") if isinstance(scim, dict) else []
        return cls(
            enabled=bool(config.get("enabled", False)),
            verifier=verifier,
            access=access,
            group_claim=str(config.get("group_claim", GROUP_CLAIM_DEFAULT)),
            role_claim=str(config.get("role_claim", ROLE_CLAIM_DEFAULT)),
            tenant_claim=str(config.get("tenant_claim", TENANT_CLAIM_DEFAULT)),
            group_role_map=config.get("group_role_map") or {},
            default_role=str(config.get("default_role", DEFAULT_ROLE)),
            allow_anonymous=bool(config.get("allow_anonymous", False)),
            allow_api_keys=bool(config.get("allow_api_keys", True)),
            directory=directory,
            scim_tokens=[
                str(token) for token in (tokens or []) if isinstance(token, str)
            ],
            scim_enabled=bool(scim.get("enabled", False))
            if isinstance(scim, dict)
            else False,
        )


def groups_from_claims(
    claims: Dict[str, Any], claim: str = GROUP_CLAIM_DEFAULT
) -> List[str]:
    """Small helper for adapters/tests that only need claim extraction."""
    raw = claims.get(claim) or []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        return [str(item) for item in raw]
    return []
