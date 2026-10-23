"""Tests for issue #51: permission-aware (ACL) retrieval (workstream A4).

Acceptance covered:
- documents restricted to a group/user/role/tenant are only returned to a
  matching caller; other callers never see them,
- filtering happens before reranking, query expansion and KG expansion, so
  denied chunks cannot leak into prompts, answers or traces,
- a document with no ACL metadata stays open (existing corpora unchanged),
- `default_policy: deny` makes ACLs mandatory,
- ACLs are applied across vector, hybrid and KG backends,
- loaders normalize top-level ACL fields into canonical metadata,
- the response cache is scoped per identity (no cross-caller reuse),
- the HTTP layer passes the caller's role/groups only when ACL is enabled.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.implementations.faiss_retriever import FAISSRetriever
from core.implementations.hybrid_retriever import HybridRetriever
from core.implementations.kg_retriever import KGRetriever
from core.implementations.simple_retriever import SimpleRetriever
from core.registry.retriever_registry import RetrieverRegistry
from core.services.acl import (
    AccessContext,
    AclSettings,
    acl_record,
    filter_documents,
    is_document_allowed,
    normalize_acl_metadata,
    normalize_document,
)
from core.services.response_cache import ResponseCache

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"
SECRET = "unit-test-acl-secret-0123456789abcdef"
ISSUER = "https://idp.example.test/"
AUDIENCE = "genai-platform"


class _EchoLLM:
    model_name = "echo"
    context_window = 4096

    def generate(self, prompt: str, config: Any = None) -> str:
        return "ok"

    def generate_batch(self, prompts: List[str], config: Any = None) -> List[str]:
        return ["ok" for _ in prompts]


class _CapturingReranker:
    reranker_name = "capturing"

    def __init__(self) -> None:
        self.seen: List[str] = []

    def rerank(self, query: str, documents: List[Any], top_k: int = 3) -> List[Any]:
        self.seen = [doc.content for doc in documents]
        return documents[:top_k]


class _VariantExpander:
    def expand(self, query: str) -> List[str]:
        return [query, "zebra protocol alpha restricted runbook"]


def _settings(**overrides: Any) -> AclSettings:
    base: Dict[str, Any] = {"enabled": True}
    base.update(overrides)
    return AclSettings.from_config(base)


def _pipeline(make_pipeline, docs: List[Any], **kwargs: Any):
    return make_pipeline(
        docs=docs,
        llm=_EchoLLM(),
        evaluator=None,
        reranker=None,
        **kwargs,
    )


# -- settings / records --------------------------------------------------


def test_settings_default_to_disabled_and_validate():
    default = AclSettings.from_config({})
    assert default.enabled is False
    assert default.default_policy == "open"
    assert default.fetch_factor == 4

    parsed = AclSettings.from_config(
        {
            "acl": {
                "enabled": True,
                "default_policy": "deny",
                "overfetch_factor": 6,
                "bypass_roles": ["Admin"],
            }
        }
    )
    assert parsed.enabled is True
    assert parsed.default_policy == "deny"
    assert parsed.fetch_factor == 6
    assert parsed.is_bypass_role(AccessContext(roles=("admin",)))

    with pytest.raises(ValueError):
        AclSettings.from_config({"default_policy": "sometimes"})
    with pytest.raises(ValueError):
        AclSettings.from_config({"overfetch_factor": 0})


def test_acl_record_enforces_tenant_user_group_and_role():
    record = acl_record(
        {
            "tenant_id": "acme",
            "allowed_users": ["alice@acme.test"],
            "allowed_groups": ["engineering"],
            "allowed_roles": ["analyst"],
        }
    )
    good = AccessContext(
        tenant="acme",
        user="alice@acme.test",
        groups=("engineering",),
        roles=("analyst",),
    )
    assert record.allows(good)
    assert not record.allows(AccessContext(tenant="other", user="alice@acme.test", groups=("engineering",), roles=("analyst",)))
    assert not record.allows(AccessContext(tenant="acme", user="bob@acme.test", groups=("engineering",), roles=("analyst",)))
    assert not record.allows(AccessContext(tenant="acme", user="alice@acme.test", groups=("sales",), roles=("analyst",)))
    assert not record.allows(AccessContext(tenant="acme", user="alice@acme.test", groups=("engineering",), roles=("viewer",)))
    assert not record.allows(None)


def test_open_documents_and_default_policy():
    open_metadata = {"doc_id": 1}
    context = AccessContext(user="anyone")
    assert is_document_allowed(open_metadata, context, _settings())
    assert not is_document_allowed(open_metadata, context, _settings(default_policy="deny"))

    disabled = AclSettings()
    restricted = {"allowed_groups": ["secret"]}
    assert is_document_allowed(restricted, context, disabled)


def test_bypass_roles_see_everything():
    settings = _settings(bypass_roles=("admin",))
    restricted = {"allowed_groups": ["engineering"], "tenant_id": "acme"}
    assert is_document_allowed(restricted, AccessContext(roles=("admin",)), settings)
    assert not is_document_allowed(restricted, AccessContext(roles=("viewer",)), settings)


def test_filter_documents_preserves_order_and_counts_denials():
    docs = [
        type("D", (), {"metadata": {"allowed_groups": ["a"]}, "content": "one"})(),
        type("D", (), {"metadata": {}, "content": "two"})(),
        type("D", (), {"metadata": {"allowed_groups": ["b"]}, "content": "three"})(),
    ]
    allowed, scores, denied = filter_documents(
        docs, [0.9, 0.8, 0.7], AccessContext(groups=["a"]), _settings()
    )
    assert [doc.content for doc in allowed] == ["one", "two"]
    assert scores == [0.9, 0.8]
    assert denied == 1


# -- loader normalization ------------------------------------------------


def test_loader_normalizes_top_level_acl_fields(tmp_path):
    corpus = tmp_path / "docs.json"
    corpus.write_text(
        json.dumps(
            [
                {"content": "engineering only", "allowed_groups": ["Engineering"]},
                {
                    "content": "nested acl",
                    "acl": {"tenants": ["Acme"], "groups": ["Sales"]},
                },
                {"content": "public"},
            ]
        ),
        encoding="utf-8",
    )
    config = tmp_path / "retrieval.yaml"
    config.write_text(
        "retrieval:\n"
        "  default_retriever: simple\n"
        "  retrievers:\n"
        "    simple:\n"
        "      provider: simple\n"
        f"      documents_path: {json.dumps(str(corpus))}\n"
        "chunking:\n  enabled: false\n",
        encoding="utf-8",
    )

    retriever = RetrieverRegistry(str(config)).create(embedder=_StubEmbedder())
    metadata = [doc.metadata for doc in retriever.docs]
    assert metadata[0]["allowed_groups"] == ["engineering"]
    assert metadata[1]["allowed_tenants"] == ["acme"]
    assert metadata[1]["allowed_groups"] == ["sales"]
    assert "allowed_groups" not in metadata[2]


def test_normalize_document_does_not_copy_content_into_metadata():
    normalized = normalize_document({"content": "hello", "allowed_roles": ["Analyst"]})
    assert normalized["metadata"] == {"allowed_roles": ["analyst"]}
    metadata = normalize_acl_metadata({"acl": {"users": ["Alice"]}})
    assert metadata["allowed_users"] == ["alice"]


class _StubEmbedder:
    dimension = 4

    def embed(self, text: str) -> List[float]:
        seed = sum(ord(ch) for ch in text) % 5 + 1
        return [float(seed), float(len(text) % 7), 1.0, 0.0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(text) for text in texts]


# -- pipeline filtering --------------------------------------------------


def test_group_restricted_chunk_is_hidden_from_other_callers(make_pipeline):
    docs = [
        {"content": "engineering runbook for incident response", "allowed_groups": ["engineering"]},
        {"content": "public handbook for incident response"},
    ]
    pipeline = _pipeline(make_pipeline, docs, acl=_settings())

    denied = pipeline.run("incident response runbook", role="viewer", groups=["sales"])
    assert "engineering runbook" not in " ".join(denied["retrieved_docs"])
    assert denied["observability"]["access_control"]["filtered_documents"] >= 1
    assert "public handbook" in " ".join(denied["retrieved_docs"])

    allowed = pipeline.run("incident response runbook", role="viewer", groups=["engineering"])
    assert "engineering runbook" in " ".join(allowed["retrieved_docs"])


def test_tenant_isolation_filters_other_tenants(make_pipeline):
    docs = [
        {"content": "acme payroll policy", "tenant_id": "acme"},
        {"content": "globex payroll policy", "tenant_id": "globex"},
        {"content": "shared payroll policy"},
    ]
    pipeline = _pipeline(make_pipeline, docs, acl=_settings())
    result = pipeline.run("payroll policy", tenant="acme")
    joined = " ".join(result["retrieved_docs"])
    assert "acme payroll" in joined
    assert "globex payroll" not in joined
    assert "shared payroll" in joined


def test_default_deny_hides_documents_without_acl(make_pipeline):
    docs = [{"content": "legacy document about widgets"}, {"content": "another widget note"}]
    pipeline = _pipeline(make_pipeline, docs, acl=_settings(default_policy="deny"))
    result = pipeline.run("widgets", role="viewer", groups=["engineering"])
    assert result["retrieved_docs"] == []
    assert result["observability"]["access_control"]["filtered_documents"] == 2


def test_overfetch_keeps_allowed_docs_visible(make_pipeline):
    docs = [
        {"content": "zebra protocol alpha restricted runbook", "allowed_groups": ["engineering"]},
        {"content": "zebra protocol beta restricted runbook", "allowed_groups": ["engineering"]},
        {"content": "zebra protocol gamma restricted runbook", "allowed_groups": ["engineering"]},
        {"content": "zebra protocol overview for everyone"},
    ]
    pipeline = _pipeline(make_pipeline, docs, acl=_settings(), top_k=1)
    result = pipeline.run("zebra protocol alpha", role="viewer", groups=["sales"])
    assert result["retrieved_docs"] == ["zebra protocol overview for everyone"]


def test_reranker_never_receives_denied_documents(make_pipeline):
    docs = [
        {"content": "zebra protocol alpha restricted", "allowed_groups": ["engineering"]},
        {"content": "zebra protocol overview public"},
    ]
    reranker = _CapturingReranker()
    pipeline = make_pipeline(
        docs=docs,
        llm=_EchoLLM(),
        evaluator=None,
        reranker=reranker,
        acl=_settings(),
    )
    pipeline.run("zebra protocol alpha", role="viewer", groups=["sales"])
    assert reranker.seen
    assert all("restricted" not in content for content in reranker.seen)


def test_query_expansion_cannot_leak_denied_documents(make_pipeline):
    docs = [
        {"content": "zebra protocol alpha restricted runbook", "allowed_groups": ["engineering"]},
        {"content": "general handbook about zebras"},
    ]
    pipeline = _pipeline(
        make_pipeline,
        docs,
        acl=_settings(),
        query_expander=_VariantExpander(),
    )
    result = pipeline.run("handbook", role="viewer", groups=["sales"])
    assert "restricted runbook" not in " ".join(result["retrieved_docs"])
    assert "general handbook" in " ".join(result["retrieved_docs"])


def test_kg_expansion_cannot_leak_denied_triples(real_embedder, make_pipeline):
    triples = [
        {"subject": "Zebra", "predicate": "owns", "object": "Protocol Alpha", "allowed_groups": ["engineering"]},
        {"subject": "Zebra", "predicate": "lives_in", "object": "Savannah"},
    ]
    retriever = KGRetriever(
        embedder=real_embedder, triples=triples, expansion_hops=1, max_expansion=3
    )
    pipeline = _pipeline(
        make_pipeline,
        docs=[],
        retriever=retriever,
        acl=_settings(),
    )
    result = pipeline.run("Zebra", role="viewer", groups=["sales"])
    joined = " ".join(result["retrieved_docs"])
    assert "owns Protocol Alpha" not in joined
    assert "lives_in Savannah" in joined


@pytest.mark.parametrize(
    "factory",
    [
        lambda docs, embedder: SimpleRetriever(docs=docs, embedder=embedder),
        lambda docs, embedder: FAISSRetriever(docs=docs, embedder=embedder),
        lambda docs, embedder: HybridRetriever(docs=docs, embedder=embedder),
    ],
    ids=["simple", "faiss", "hybrid"],
)
def test_acl_filter_applies_to_all_retriever_backends(factory, real_embedder, make_pipeline):
    docs = [
        {"content": "zebra protocol alpha restricted", "allowed_groups": ["engineering"]},
        {"content": "zebra protocol overview public"},
    ]
    retriever = factory(docs, real_embedder)
    pipeline = _pipeline(make_pipeline, docs=[], retriever=retriever, acl=_settings(), top_k=1)
    result = pipeline.run("zebra protocol alpha", role="viewer", groups=["sales"])
    assert result["retrieved_docs"] == ["zebra protocol overview public"]


def test_cache_is_scoped_per_identity(make_pipeline):
    docs = [
        {"content": "engineering runbook for incident response", "allowed_groups": ["engineering"]},
        {"content": "public handbook for incident response"},
    ]
    cache = ResponseCache(enabled=True)
    pipeline = _pipeline(make_pipeline, docs, acl=_settings(), cache=cache)

    first = pipeline.run("incident response", role="viewer", groups=["engineering"])
    assert first.get("cache_hit") is False
    second = pipeline.run("incident response", role="viewer", groups=["engineering"])
    assert second.get("cache_hit") is True

    other = pipeline.run("incident response", role="viewer", groups=["sales"])
    assert other.get("cache_hit") is False
    assert "engineering runbook" not in " ".join(other["retrieved_docs"])


# -- HTTP wiring ---------------------------------------------------------

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
  viewer:
    capabilities: [query, introspect]
api_keys: {}
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
  team-viewer: viewer
default_role: viewer
allow_anonymous: false
scim:
  enabled: false
  tokens: []
saml:
  enabled: false
"""


class _CapturingPipeline:
    instances: List["_CapturingPipeline"] = []

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        _CapturingPipeline.instances.append(self)

    def run(self, query, top_k=None, raise_on_failure=None, request_id=None, **kwargs):
        self.calls.append(dict(kwargs))
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


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _token(groups: Optional[List[str]] = None) -> str:
    import jwt

    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "user@example.test",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=600),
            "groups": groups or [],
        },
        SECRET,
        algorithm="HS256",
    )


def _api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, acl_enabled: bool) -> TestClient:
    monkeypatch.setenv("JWT_SECRET", SECRET)
    _CapturingPipeline.instances.clear()
    models = _write(tmp_path / "models.yaml", MODELS_YAML)
    retrieval = _write(tmp_path / "retrieval.yaml", RETRIEVAL_YAML)
    prompt = tmp_path / "prompt_config.yaml"
    prompt.write_text(REPO_PROMPT.read_text(encoding="utf-8"), encoding="utf-8")
    observability = _write(
        tmp_path / "observability.yaml", "log_level: INFO\nredact_sensitive_data: true\n"
    )
    access = _write(tmp_path / "access_control.yaml", ACCESS_YAML)
    identity = _write(tmp_path / "identity.yaml", IDENTITY_YAML)
    acl = _write(
        tmp_path / "acl.yaml",
        "enabled: %s\ndefault_policy: open\noverfetch_factor: 2\nbypass_roles: []\n"
        % ("true" if acl_enabled else "false"),
    )
    app = create_app(
        models_config_path=models,
        retrieval_config_path=retrieval,
        prompt_config_path=prompt,
        observability_config_path=observability,
        access_control_config_path=access,
        identity_config_path=identity,
        acl_config_path=acl,
        pipeline_builder=lambda **_: _CapturingPipeline(),
    )
    return TestClient(app)


def test_api_passes_caller_identity_to_retrieval_when_acl_enabled(
    tmp_path, monkeypatch
):
    client = _api_client(tmp_path, monkeypatch, acl_enabled=True)
    with client:
        response = client.post(
            "/v1/query",
            json={"query": "hello", "include_trace": False},
            headers={"Authorization": f"Bearer {_token(groups=['team-viewer'])}"},
        )
        assert response.status_code == 200
        pipeline = _CapturingPipeline.instances[-1]
        assert pipeline.calls[-1]["role"] == "viewer"
        assert pipeline.calls[-1]["groups"] == ["team-viewer"]

        config = client.get(
            "/v1/config", headers={"Authorization": f"Bearer {_token(groups=['team-viewer'])}"}
        ).json()
        assert config["config"]["acl"]["enabled"] is True


def test_api_does_not_pass_identity_when_acl_disabled(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, acl_enabled=False)
    with client:
        response = client.post(
            "/v1/query",
            json={"query": "hello", "include_trace": False},
            headers={"Authorization": f"Bearer {_token(groups=['team-viewer'])}"},
        )
        assert response.status_code == 200
        pipeline = _CapturingPipeline.instances[-1]
        assert "role" not in pipeline.calls[-1]
        assert "groups" not in pipeline.calls[-1]
