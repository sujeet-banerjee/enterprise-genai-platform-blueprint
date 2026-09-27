from typing import List, Tuple
from core.interfaces.retriever import BaseRetriever, Document

class DummyRetriever(BaseRetriever):

    def retrieve(self, embedding, top_k: int = 3) -> List[Document]:
        return [doc for doc, _ in self.retrieve_with_scores(embedding, top_k=top_k)]

    def retrieve_with_scores(self, embedding, top_k: int = 3) -> List[Tuple[Document, float]]:
        docs_with_scores = [
            (Document(content="Dummy document 1", score=0.95), 0.95),
            (Document(content="Dummy document 2", score=0.85), 0.85),
        ]
        return docs_with_scores[:top_k]

    @property
    def index_dimension(self) -> int:
        return 10