import numpy as np
from typing import List, Union
from core.interfaces.retriever import BaseRetriever, Document, ScoredDocument


class SimpleRetriever(BaseRetriever):

    def __init__(self, docs: List[Union[dict, Document, str]], embedder):
        self.embedder = embedder
        self.docs: List[Document] = []
        for idx, doc in enumerate(docs or []):
            if isinstance(doc, Document):
                meta = dict(doc.metadata) if doc.metadata else {}
                meta.setdefault("doc_id", idx)
                self.docs.append(Document(content=doc.content, metadata=meta, score=doc.score))
            elif isinstance(doc, dict):
                meta = dict(doc.get("metadata") or {})
                meta.setdefault("doc_id", idx)
                self.docs.append(Document(content=doc["content"], metadata=meta))
            else:
                self.docs.append(Document(content=str(doc), metadata={"doc_id": idx}))

        self.embeddings = [
            self.embedder.embed(doc.content)
            for doc in self.docs
        ]

    @property
    def index_dimension(self) -> int:
        return self.embedder.dimension

    @staticmethod
    def _cosine(a, b) -> float:
        a_arr = np.asarray(a, dtype=np.float32)
        b_arr = np.asarray(b, dtype=np.float32)
        denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
        if denom == 0.0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / denom)

    def retrieve_with_scores(self, query_embedding: List[float], top_k: int = 3) -> List[ScoredDocument]:
        if len(query_embedding) != self.index_dimension:
            raise ValueError(
                f"Query embedding dimension ({len(query_embedding)}) does not match index dimension ({self.index_dimension})."
            )
        if not self.docs or top_k <= 0:
            return []

        scores = [
            self._cosine(query_embedding, emb)
            for emb in self.embeddings
        ]

        ranked = sorted(
            zip(self.docs, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        results: List[ScoredDocument] = []
        for rank_idx, (doc, score) in enumerate(ranked[:top_k]):
            score_val = round(float(score), 6)
            meta = dict(doc.metadata) if doc.metadata else {}
            meta["score"] = score_val
            meta["retrieval_rank"] = rank_idx
            doc_copy = Document(content=doc.content, metadata=meta, score=score_val)
            results.append(ScoredDocument(document=doc_copy, score=score_val))
        return results

    def retrieve(self, query_embedding: List[float], top_k: int = 3) -> List[Document]:
        scored_results = self.retrieve_with_scores(query_embedding, top_k=top_k)
        return [item.document for item in scored_results]
