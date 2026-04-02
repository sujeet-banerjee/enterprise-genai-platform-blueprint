import numpy as np
from typing import List
from core.interfaces.retriever import BaseRetriever, Document


class SimpleRetriever(BaseRetriever):

    def __init__(self, docs, embedder):
        self.embedder = embedder

        # Convert dicts → Document objects
        self.docs: List[Document] = [
            Document(content=doc["content"]) for doc in docs
        ]

        self.embeddings = [
            self.embedder.embed(doc.content)
            for doc in self.docs
        ]

    @property
    def index_dimension(self) -> int:
        return self.embedder.dimension

    def retrieve(self, query_embedding, top_k=3) -> List[Document]:

        def cosine(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

        scores = [
            cosine(query_embedding, emb)
            for emb in self.embeddings
        ]

        ranked = sorted(
            zip(self.docs, scores),
            key=lambda x: x[1],
            reverse=True
        )

        return [doc for doc, _ in ranked[:top_k]]