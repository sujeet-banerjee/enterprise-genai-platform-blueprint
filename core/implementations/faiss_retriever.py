import faiss
import numpy as np
from typing import List, Tuple, Union, Dict, Any, Optional
from core.interfaces.retriever import BaseRetriever, Document
from core.interfaces.embedder import BaseEmbedder


class FAISSRetriever(BaseRetriever):
    """
    FAISS CPU-based local vector index retriever.
    Supports index creation, document insertion, similarity querying,
    and mapping index results back to Document objects with retrieval scores.
    """

    def __init__(
        self,
        dimension: Optional[int] = None,
        embedder: Optional[BaseEmbedder] = None,
        docs: Optional[List[Union[dict, Document, str]]] = None,
        index_type: str = "flat_ip"
    ):
        self.embedder = embedder
        if dimension is not None:
            self._dimension = dimension
        elif embedder is not None:
            self._dimension = embedder.dimension
        else:
            self._dimension = 384

        self.index_type = index_type.lower()
        self.documents: List[Document] = []
        self._init_index()

        if docs:
            self.add_documents(docs)

    def _init_index(self):
        if self.index_type in ["flat_l2", "l2"]:
            self.index = faiss.IndexFlatL2(self._dimension)
        else:
            self.index = faiss.IndexFlatIP(self._dimension)

    @property
    def index_dimension(self) -> int:
        return self._dimension

    def _convert_to_document(self, item: Union[dict, Document, str]) -> Document:
        if isinstance(item, Document):
            return item
        if isinstance(item, dict):
            content = item.get("content", "")
            metadata = {k: v for k, v in item.items() if k != "content"}
            return Document(content=content, metadata=metadata)
        return Document(content=str(item))

    def add_documents(self, docs: List[Union[dict, Document, str]]):
        if not docs:
            return

        doc_objs = [self._convert_to_document(d) for d in docs]
        if self.embedder is None:
            raise ValueError("Cannot embed documents without an embedder configured.")

        raw_embeddings = [self.embedder.embed(doc.content) for doc in doc_objs]
        vectors = np.array(raw_embeddings, dtype=np.float32)

        if self.index_type in ["flat_ip", "ip", "cosine"]:
            faiss.normalize_L2(vectors)

        self.index.add(vectors)
        self.documents.extend(doc_objs)

    def add_embeddings(self, embeddings: Union[List[List[float]], np.ndarray], docs: List[Union[dict, Document, str]]):
        doc_objs = [self._convert_to_document(d) for d in docs]
        vectors = np.array(embeddings, dtype=np.float32)

        if self.index_type in ["flat_ip", "ip", "cosine"]:
            faiss.normalize_L2(vectors)

        self.index.add(vectors)
        self.documents.extend(doc_objs)

    def retrieve_with_scores(self, query_embedding: List[float], top_k: int = 3) -> List[Tuple[Document, float]]:
        if self.index.ntotal == 0 or not self.documents:
            return []

        k = min(top_k, self.index.ntotal)
        query_vec = np.array([query_embedding], dtype=np.float32)

        if self.index_type in ["flat_ip", "ip", "cosine"]:
            faiss.normalize_L2(query_vec)

        scores, indices = self.index.search(query_vec, k)

        results: List[Tuple[Document, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1 or idx >= len(self.documents):
                continue
            doc = self.documents[idx]
            score_float = float(score)
            doc_copy = Document(
                content=doc.content,
                metadata=dict(doc.metadata) if doc.metadata else {},
                score=round(score_float, 4)
            )
            results.append((doc_copy, round(score_float, 4)))

        return results

    def retrieve(self, query_embedding: List[float], top_k: int = 3) -> List[Document]:
        return [doc for doc, _ in self.retrieve_with_scores(query_embedding, top_k=top_k)]

    def clear(self):
        self._init_index()
        self.documents.clear()

    @property
    def total_documents(self) -> int:
        return len(self.documents)
