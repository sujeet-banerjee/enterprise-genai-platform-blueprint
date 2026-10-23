import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import yaml

from core.interfaces.chunker import BaseChunker
from core.interfaces.retriever import BaseRetriever, Document
from core.services.acl import normalize_document

DocsInput = Optional[Sequence[Union[dict, Document, str]]]


class RetrieverRegistry:
    """
    Configuration-driven registry and factory for retrieval backends.

    Adding a new retriever follows the blueprint's customization path: implement
    ``BaseRetriever`` in ``core/implementations`` and add a provider + config entry
    under ``retrieval.retrievers`` in ``config/retrieval.yaml``. No changes to the
    orchestration layer (``RAGPipeline``) or to this registry are required beyond a
    one-line provider registration for a brand-new backend family.
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}

        self._providers: Dict[str, Callable[..., BaseRetriever]] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        self.register("faiss", self._build_faiss)
        self.register("simple", self._build_simple)
        self.register("dummy", self._build_dummy)
        self.register("kg", self._build_kg)
        self.register("hybrid", self._build_hybrid)

    @staticmethod
    def _build_faiss(
        docs: DocsInput = None,
        embedder: Any = None,
        dimension: Optional[int] = None,
        similarity_metric: str = "cosine",
        **_ignored: Any,
    ) -> BaseRetriever:
        from core.implementations.faiss_retriever import FAISSRetriever

        return FAISSRetriever(
            docs=docs,
            embedder=embedder,
            dimension=dimension,
            similarity_metric=similarity_metric,
        )

    @staticmethod
    def _build_simple(
        docs: DocsInput = None,
        embedder: Any = None,
        dimension: Optional[int] = None,
        **_ignored: Any,
    ) -> BaseRetriever:
        from core.implementations.simple_retriever import SimpleRetriever

        if embedder is None:
            raise ValueError("The 'simple' retriever requires an embedder.")
        return SimpleRetriever(docs=docs or [], embedder=embedder)

    @staticmethod
    def _build_dummy(
        docs: DocsInput = None,
        embedder: Any = None,
        dimension: Optional[int] = None,
        **_ignored: Any,
    ) -> BaseRetriever:
        from core.implementations.dummy_retriever import DummyRetriever

        resolved_dimension = dimension
        if resolved_dimension is None and embedder is not None:
            resolved_dimension = int(embedder.dimension)
        if resolved_dimension is None:
            resolved_dimension = 10

        resolved_docs: Any = list(docs) if docs else None
        return DummyRetriever(docs=resolved_docs, dimension=resolved_dimension)

    @staticmethod
    def _build_kg(
        docs: DocsInput = None,
        embedder: Any = None,
        dimension: Optional[int] = None,
        triples: Optional[Sequence[Dict[str, Any]]] = None,
        graph_path: Optional[str] = None,
        expansion_hops: int = 0,
        max_expansion: int = 3,
        **_ignored: Any,
    ) -> BaseRetriever:
        from core.implementations.kg_retriever import KGRetriever

        if embedder is None:
            raise ValueError("The 'kg' retriever requires an embedder.")
        return KGRetriever(
            docs=docs,
            embedder=embedder,
            triples=triples,
            graph_path=graph_path,
            expansion_hops=expansion_hops,
            max_expansion=max_expansion,
        )

    @staticmethod
    def _build_hybrid(
        docs: DocsInput = None,
        embedder: Any = None,
        dimension: Optional[int] = None,
        keyword_weight: float = 0.5,
        vector_weight: float = 0.5,
        k1: float = 1.5,
        b: float = 0.75,
        **_ignored: Any,
    ) -> BaseRetriever:
        from core.implementations.hybrid_retriever import HybridRetriever

        if embedder is None:
            raise ValueError("The 'hybrid' retriever requires an embedder.")
        return HybridRetriever(
            docs=docs,
            embedder=embedder,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
            k1=k1,
            b=b,
        )

    def register(self, provider_name: str, factory: Callable[..., BaseRetriever]) -> None:
        """
        Register a retriever provider factory. Enables third-party plug-ins
        without modifying registry logic.
        """
        self._providers[str(provider_name).lower()] = factory

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())

    def list_retrievers(self) -> List[str]:
        return sorted((self.config.get("retrieval") or {}).get("retrievers", {}).keys())

    def resolve(self, name: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
        """
        Resolve a retriever key to (key, provider, provider_config) using config.
        """
        ret_cfg = self.config.get("retrieval") or {}
        retrievers = ret_cfg.get("retrievers") or {}

        key = name if name is not None else ret_cfg.get("default_retriever")
        if not key:
            raise ValueError(
                "No retriever specified and 'retrieval.default_retriever' is missing from config."
            )

        if key in retrievers and isinstance(retrievers[key], dict):
            entry = dict(retrievers[key])
            provider = str(entry.get("provider", key)).lower()
        else:
            entry = {}
            provider = str(key).lower()

        # Global ``retrieval.similarity_metric`` (issue #15) fills in unless a
        # retriever entry overrides it. Providers that don't take a metric
        # swallow the kwarg via their ``**_ignored`` factories.
        if "similarity_metric" not in entry and ret_cfg.get("similarity_metric"):
            entry["similarity_metric"] = str(ret_cfg["similarity_metric"])

        if provider not in self._providers:
            raise ValueError(
                f"Unknown retriever provider: '{provider}'. "
                f"Registered providers: {self.list_providers()}"
            )
        return str(key), provider, entry

    def _repo_root(self) -> Path:
        return Path(self.config_path).resolve().parent.parent

    def _load_documents(self, documents_path: str) -> List[Any]:
        path = Path(documents_path)
        if not path.is_absolute():
            path = self._repo_root() / path
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "documents" in data:
            data = data["documents"]
        if not isinstance(data, list):
            raise ValueError(
                f"Corpus file '{path}' must contain a JSON list of documents."
            )
        return data

    def create(
        self,
        name: Optional[str] = None,
        *,
        docs: DocsInput = None,
        embedder: Any = None,
        dimension: Optional[int] = None,
        chunk: Optional[bool] = None,
        chunker: Optional[BaseChunker] = None,
    ) -> BaseRetriever:
        _key, provider, entry = self.resolve(name)
        if docs is None and entry.get("documents_path"):
            docs = self._load_documents(str(entry["documents_path"]))

        if docs:
            # Normalize ACL fields (issue #51) so top-level loader keys such as
            # ``allowed_groups`` become canonical metadata for every backend.
            docs = [normalize_document(doc) for doc in docs]

        docs = self._maybe_chunk(docs, enabled=chunk, chunker=chunker)

        factory = self._providers[provider]
        return factory(docs=docs, embedder=embedder, dimension=dimension, **entry)

    def _chunking_enabled(self, override: Optional[bool]) -> bool:
        """
        Chunking is active when explicitly requested, when ``chunking.enabled`` is
        true, or (by default) when ``chunking.active_strategy`` is configured.
        """
        if override is not None:
            return bool(override)
        chunking_cfg = self.config.get("chunking") or {}
        if "enabled" in chunking_cfg:
            return bool(chunking_cfg["enabled"])
        return bool(chunking_cfg.get("active_strategy"))

    def _maybe_chunk(
        self,
        docs: DocsInput,
        *,
        enabled: Optional[bool],
        chunker: Optional[BaseChunker],
    ) -> DocsInput:
        if not docs:
            return docs
        if chunker is None:
            if not self._chunking_enabled(enabled):
                return docs
            from core.implementations.chunker import ChunkerFactory

            chunker = ChunkerFactory.create_from_config(self.config_path)
        return chunker.chunk_documents(list(docs))
