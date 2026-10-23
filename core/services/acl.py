"""Permission-aware retrieval (issue #51, workstream A4).

The platform supported tenant and identity resolution but retrieval itself was
blind: once a caller passed authentication, every indexed chunk was eligible for
ranking and prompt construction. This module adds a small, dependency-free ACL
layer that filters retrieved candidates by the caller's identity *before*
reranking, prompt construction and generation.

Design
------
* ACLs live in document metadata (``allowed_groups``, ``allowed_users``,
  ``allowed_roles`` and ``tenant_id``/``allowed_tenants``) or in a nested
  ``acl`` mapping. Loaders may also put those keys at the top level of a
  document; :func:`normalize_acl_metadata` lifts them into metadata.
* A document with no ACL fields is **open** by default. This keeps existing
  corpora and deployments byte-identical until an ACL is attached.
* All constraints on a document are AND-ed: a document restricted to both a
  tenant and a group requires both to match.
* Filtering happens in :class:`app.pipeline.RAGPipeline` immediately after
  retrieval (and after query/KG expansion, which return through the same path),
  so denied chunks never reach reranking, guardrails, the prompt, the answer or
  the observability trace. Retriever backends (vector, hybrid, KG) need no
  changes.
* When filtering is active the pipeline over-fetches candidates
  (``overfetch_factor``) so denied chunks cannot crowd allowed ones out of a
  truncated top-k result.

Config (``config/acl.yaml``)::

    enabled: false
    default_policy: open      # open | deny
    overfetch_factor: 4
    bypass_roles: []          # roles that see everything (e.g. ["admin"])
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.interfaces.retriever import Document

ACL_TENANTS = "allowed_tenants"
ACL_USERS = "allowed_users"
ACL_GROUPS = "allowed_groups"
ACL_ROLES = "allowed_roles"

_CANONICAL_KEYS = (ACL_TENANTS, ACL_USERS, ACL_GROUPS, ACL_ROLES)

_ALIASES: Dict[str, Tuple[str, ...]] = {
    ACL_TENANTS: ("allowed_tenants", "allowed_tenant", "tenant_id", "tenant", "tenants"),
    ACL_USERS: ("allowed_users", "allowed_user", "users"),
    ACL_GROUPS: ("allowed_groups", "allowed_group", "groups"),
    ACL_ROLES: ("allowed_roles", "allowed_role", "roles"),
}


def _normalize_values(raw: Any) -> Tuple[str, ...]:
    """Coerce a scalar or list into a de-duplicated tuple of lowercase ids."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        items: Iterable[Any] = [raw]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        items = raw
    else:
        items = [raw]
    values: List[str] = []
    for item in items:
        text = str(item).strip().lower()
        if text and text not in values:
            values.append(text)
    return tuple(values)


@dataclass(frozen=True)
class AccessContext:
    """The caller identity used to evaluate document ACLs."""

    tenant: Optional[str] = None
    user: Optional[str] = None
    groups: Tuple[str, ...] = ()
    roles: Tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        tenant: Optional[str] = None,
        user: Optional[str] = None,
        groups: Optional[Sequence[str]] = None,
        role: Optional[str] = None,
        roles: Optional[Sequence[str]] = None,
    ) -> "AccessContext":
        role_values: List[str] = []
        if role:
            role_values.append(str(role))
        role_values.extend(str(r) for r in (roles or ()))
        return cls(
            tenant=str(tenant).strip() if tenant else None,
            user=str(user).strip() if user else None,
            groups=_normalize_values(list(groups or ())),
            roles=_normalize_values(role_values),
        )

    @property
    def normalized_tenant(self) -> Optional[str]:
        return self.tenant.strip().lower() if self.tenant else None

    @property
    def normalized_user(self) -> Optional[str]:
        return self.user.strip().lower() if self.user else None


@dataclass(frozen=True)
class AclSettings:
    """Tunables for permission-aware retrieval; disabled by default."""

    enabled: bool = False
    default_policy: str = "open"
    overfetch_factor: int = 4
    bypass_roles: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        policy = str(self.default_policy).strip().lower()
        if policy not in ("open", "deny"):
            raise ValueError(
                f"acl.default_policy must be 'open' or 'deny', got '{self.default_policy}'"
            )
        if int(self.overfetch_factor) < 1:
            raise ValueError("acl.overfetch_factor must be >= 1")

    @property
    def fetch_factor(self) -> int:
        return max(1, int(self.overfetch_factor))

    def is_bypass_role(self, context: Optional[AccessContext]) -> bool:
        if not context or not self.bypass_roles:
            return False
        bypass = set(_normalize_values(list(self.bypass_roles)))
        return bool(bypass.intersection(context.roles))

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "AclSettings":
        data: Mapping[str, Any] = config or {}
        nested = data.get("acl")
        if isinstance(nested, Mapping):
            data = nested
        raw_factor = data.get("overfetch_factor", 4)
        factor = 4 if raw_factor is None else int(raw_factor)
        return cls(
            enabled=bool(data.get("enabled", False)),
            default_policy=str(data.get("default_policy", "open")),
            overfetch_factor=factor,
            bypass_roles=_normalize_values(data.get("bypass_roles")),
        )


@dataclass(frozen=True)
class AclRecord:
    """Per-document access constraints (all present constraints are AND-ed)."""

    tenants: Tuple[str, ...] = ()
    users: Tuple[str, ...] = ()
    groups: Tuple[str, ...] = ()
    roles: Tuple[str, ...] = ()

    @property
    def restricted(self) -> bool:
        return bool(self.tenants or self.users or self.groups or self.roles)

    def allows(self, context: Optional[AccessContext]) -> bool:
        if not self.restricted:
            return True
        if context is None:
            return False
        if self.tenants and context.normalized_tenant not in self.tenants:
            return False
        if self.users and context.normalized_user not in self.users:
            return False
        if self.groups and not set(self.groups).intersection(context.groups):
            return False
        if self.roles and not set(self.roles).intersection(context.roles):
            return False
        return True


def _merge_acl_source(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    """Collect ACL fields from a nested ``acl`` mapping and top-level aliases."""
    source: Dict[str, Any] = {}
    nested = metadata.get("acl")
    if isinstance(nested, Mapping):
        for canonical, aliases in _ALIASES.items():
            for key in aliases:
                if key in nested:
                    source[canonical] = nested[key]
                    break
    for canonical, aliases in _ALIASES.items():
        for key in aliases:
            if key in metadata:
                source[canonical] = metadata[key]
                break
    return source


def acl_record(metadata: Optional[Mapping[str, Any]]) -> AclRecord:
    """Extract an :class:`AclRecord` from document metadata."""
    if not metadata:
        return AclRecord()
    source = _merge_acl_source(metadata)
    return AclRecord(
        tenants=_normalize_values(source.get(ACL_TENANTS)),
        users=_normalize_values(source.get(ACL_USERS)),
        groups=_normalize_values(source.get(ACL_GROUPS)),
        roles=_normalize_values(source.get(ACL_ROLES)),
    )


def normalize_acl_metadata(metadata: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return metadata with canonical, normalized ACL keys.

    Loaders frequently carry ACLs as top-level document fields. This function
    merges those aliases (and a nested ``acl`` mapping) into canonical
    ``allowed_*`` lists so every retriever backend sees the same shape. The
    original keys are preserved.
    """
    result: Dict[str, Any] = dict(metadata or {})
    source = _merge_acl_source(result)
    for canonical in _CANONICAL_KEYS:
        values = _normalize_values(source.get(canonical))
        if values:
            result[canonical] = list(values)
    return result


def normalize_document(doc: Any) -> Any:
    """Normalize ACL metadata on a ``Document`` or document mapping in place."""
    if isinstance(doc, Document):
        doc.metadata = normalize_acl_metadata(doc.metadata)
        return doc
    if isinstance(doc, Mapping):
        normalized = dict(doc)
        if isinstance(normalized.get("metadata"), Mapping):
            normalized["metadata"] = normalize_acl_metadata(
                normalized.get("metadata")
            )
        else:
            lifted = {
                key: value
                for key, value in normalized.items()
                if key not in ("content", "metadata")
            }
            normalized["metadata"] = normalize_acl_metadata(lifted)
        return normalized
    return doc


def is_document_allowed(
    metadata: Optional[Mapping[str, Any]],
    context: Optional[AccessContext],
    settings: AclSettings,
) -> bool:
    """Decide whether the caller may see a document."""
    if not settings.enabled:
        return True
    if settings.is_bypass_role(context):
        return True
    record = acl_record(metadata)
    if not record.restricted:
        return settings.default_policy == "open"
    return record.allows(context)


def filter_documents(
    docs: Sequence[Document],
    scores: Sequence[float],
    context: Optional[AccessContext],
    settings: AclSettings,
) -> Tuple[List[Document], List[float], int]:
    """Filter retrieved documents by ACL.

    Returns ``(allowed_docs, allowed_scores, denied_count)``. The input order is
    preserved (already relevance-sorted). When ACLs are disabled the input is
    returned unchanged and ``denied_count`` is 0.
    """
    if not settings.enabled:
        return list(docs), list(scores), 0

    allowed_docs: List[Document] = []
    allowed_scores: List[float] = []
    denied = 0
    for idx, doc in enumerate(docs):
        metadata = getattr(doc, "metadata", None) or {}
        if is_document_allowed(metadata, context, settings):
            allowed_docs.append(doc)
            allowed_scores.append(scores[idx] if idx < len(scores) else 0.0)
        else:
            denied += 1
    return allowed_docs, allowed_scores, denied
