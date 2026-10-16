from typing import List
from core.interfaces.retriever import BaseRetriever, Document, ScoredDocument


class DummyRetriever(BaseRetriever):

    def __init__(self, docs: List[Document] = None, dimension: int = 10):
        self._dimension = dimension
        if docs is not None:
            self._docs = [
                doc if isinstance(doc, Document) else Document(content=doc["content"], metadata=doc.get("metadata"))
                for doc in docs
            ]
        else:
            self._docs = [
                Document(content="Dummy document 1", score=0.91),
                Document(content="Dummy document 2", score=0.84),
            ]

    def retrieve_with_scores(self, embedding: List[float], top_k: int = 3) -> List[ScoredDocument]:
        default_scores = [0.91, 0.84, 0.67, 0.55, 0.42]
        results: List[ScoredDocument] = []
        for idx, doc in enumerate(self._docs[:top_k]):
            score = doc.score if doc.score is not None else default_scores[idx % len(default_scores)]
            cloned_doc = Document(
                content=doc.content,
                metadata=dict(doc.metadata) if doc.metadata else {},
                score=score,
            )
            results.append(ScoredDocument(document=cloned_doc, score=score))
        return results

    def retrieve(self, embedding: List[float], top_k: int = 3) -> List[Document]:
        scored = self.retrieve_with_scores(embedding, top_k=top_k)
        return [item.document for item in scored]

    @property
    def index_dimension(self) -> int:
        return self._dimension
