import numpy as np
from typing import List, Tuple, Union, Dict, Any
from core.interfaces.retriever import BaseRetriever, Document


class SimpleRetriever(BaseRetriever):

    def __init__(self, docs: List[Union[dict, Document]], embedder):
        self.embedder = embedder

        # Convert dicts / Documents → Document objects
        self.docs: List[Document] = []
        for doc in docs:
            if isinstance(doc, Document):
                self.docs.append(doc)
            elif isinstance(doc, dict):
                content = doc.get("content", "")
                metadata = {k: v for k, v in doc.items() if k != "content"}
                self.docs.append(Document(content=content, metadata=metadata))
            else:
                self.docs.append(Document(content=str(doc)))

        self.embeddings = [
            self.embedder.embed(doc.content)
            for doc in self.docs
        ]

    @property
    def index_dimension(self) -> int:
        return self.embedder.dimension

    def retrieve_with_scores(self, query_embedding, top_k: int = 3) -> List[Tuple[Document, float]]:
        if not self.docs or not self.embeddings:
            return []

        def cosine(a, b):
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(np.dot(a, b) / (norm_a * norm_b))

        scores = [
            cosine(query_embedding, emb)
            for emb in self.embeddings
        ]

        ranked = sorted(
            zip(self.docs, scores),
            key=lambda x: x[1],
            reverse=True
        )

        results: List[Tuple[Document, float]] = []
        for doc, score in ranked[:top_k]:
            doc_copy = Document(
                content=doc.content,
                metadata=dict(doc.metadata) if doc.metadata else {},
                score=float(score)
            )
            results.append((doc_copy, float(score)))

        return results

    def retrieve(self, query_embedding, top_k: int = 3) -> List[Document]:
        return [doc for doc, _ in self.retrieve_with_scores(query_embedding, top_k=top_k)]