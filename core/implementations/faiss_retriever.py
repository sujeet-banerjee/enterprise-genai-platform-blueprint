from typing import Dict, List, Optional, Union
import faiss
import numpy as np

from core.interfaces.retriever import BaseRetriever, Document, ScoredDocument


class FAISSRetriever(BaseRetriever):
    """
    Local vector index retriever backed by FAISS CPU.
    Supports index creation, document insertion/building, querying,
    retrieval similarity scores, and mapping index IDs back to Document objects.
    """

    def __init__(
        self,
        docs: Optional[List[Union[dict, Document, str]]] = None,
        embedder=None,
        dimension: Optional[int] = None,
        similarity_metric: str = "cosine",
    ):
        self.embedder = embedder
        self.similarity_metric = similarity_metric.lower()

        if dimension is not None:
            self._dimension = int(dimension)
        elif embedder is not None:
            self._dimension = int(embedder.dimension)
        else:
            raise ValueError("Either 'embedder' or 'dimension' must be provided to initialize FAISSRetriever.")

        self.index = self._create_index(self._dimension)
        self.documents: List[Document] = []
        self.id_to_document: Dict[int, Document] = {}

        if docs:
            self.add_documents(docs)

    def _create_index(self, dimension: int):
        if dimension <= 0:
            raise ValueError(f"Invalid index dimension: {dimension}")
        if self.similarity_metric == "l2":
            return faiss.IndexFlatL2(dimension)
        return faiss.IndexFlatIP(dimension)

    def _normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        arr = np.ascontiguousarray(vectors, dtype=np.float32)
        if self.similarity_metric != "l2":
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            arr = arr / norms
        return arr

    @staticmethod
    def _coerce_document(doc: Union[dict, Document, str], doc_id: int) -> Document:
        if isinstance(doc, Document):
            meta = dict(doc.metadata) if doc.metadata else {}
            meta.setdefault("doc_id", doc_id)
            return Document(content=doc.content, metadata=meta, score=doc.score)
        if isinstance(doc, dict):
            meta = dict(doc.get("metadata") or {})
            for k, v in doc.items():
                if k not in ("content", "metadata"):
                    meta.setdefault(k, v)
            meta.setdefault("doc_id", doc_id)
            return Document(content=doc["content"], metadata=meta)
        return Document(content=str(doc), metadata={"doc_id": doc_id})

    def add_documents(
        self,
        docs: List[Union[dict, Document, str]],
        embeddings: Optional[List[List[float]]] = None,
    ) -> int:
        if not docs:
            return 0

        new_docs: List[Document] = []
        start_id = len(self.documents)
        for offset, raw_doc in enumerate(docs):
            doc_obj = self._coerce_document(raw_doc, start_id + offset)
            new_docs.append(doc_obj)

        if embeddings is None:
            if self.embedder is None:
                raise ValueError("Cannot embed documents without an embedder or precomputed embeddings.")
            embeddings = [self.embedder.embed(doc.content) for doc in new_docs]

        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        if vectors.shape[1] != self._dimension:
            raise ValueError(
                f"Document embedding dimension ({vectors.shape[1]}) does not match FAISS index dimension ({self._dimension})."
            )

        normalized = self._normalize_vectors(vectors)
        self.index.add(normalized)

        for offset, doc_obj in enumerate(new_docs):
            idx = start_id + offset
            self.documents.append(doc_obj)
            self.id_to_document[idx] = doc_obj

        return len(new_docs)

    def build_index(
        self,
        docs: List[Union[dict, Document, str]],
        embeddings: Optional[List[List[float]]] = None,
    ) -> int:
        self.index = self._create_index(self._dimension)
        self.documents = []
        self.id_to_document = {}
        return self.add_documents(docs, embeddings=embeddings)

    @property
    def index_dimension(self) -> int:
        return self._dimension

    @property
    def total_documents(self) -> int:
        return int(self.index.ntotal)

    def retrieve_with_scores(self, embedding: List[float], top_k: int = 3) -> List[ScoredDocument]:
        query_vec = np.asarray(embedding, dtype=np.float32)
        if query_vec.ndim == 1:
            query_vec = query_vec.reshape(1, -1)

        if query_vec.shape[1] != self._dimension:
            raise ValueError(
                f"Query embedding dimension ({query_vec.shape[1]}) does not match FAISS index dimension ({self._dimension})."
            )

        if self.index.ntotal == 0 or top_k <= 0:
            return []

        k = min(int(top_k), int(self.index.ntotal))
        normalized_query = self._normalize_vectors(query_vec)
        distances, indices = self.index.search(normalized_query, k)

        results: List[ScoredDocument] = []
        for rank_idx, (raw_score, doc_idx) in enumerate(zip(distances[0], indices[0])):
            if int(doc_idx) < 0 or int(doc_idx) not in self.id_to_document:
                continue

            if self.similarity_metric == "l2":
                score_val = round(float(1.0 / (1.0 + max(0.0, float(raw_score)))), 6)
            else:
                score_val = round(float(raw_score), 6)

            source_doc = self.id_to_document[int(doc_idx)]
            meta = dict(source_doc.metadata) if source_doc.metadata else {}
            meta["score"] = score_val
            meta["faiss_id"] = int(doc_idx)
            meta["retrieval_rank"] = rank_idx

            doc_copy = Document(
                content=source_doc.content,
                metadata=meta,
                score=score_val,
            )
            results.append(ScoredDocument(document=doc_copy, score=score_val))

        return results

    def retrieve(self, embedding: List[float], top_k: int = 3) -> List[Document]:
        scored_results = self.retrieve_with_scores(embedding, top_k=top_k)
        return [item.document for item in scored_results]
