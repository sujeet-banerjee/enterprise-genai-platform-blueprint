from core.interfaces.retriever import BaseRetriever, Document

class DummyRetriever(BaseRetriever):

    def retrieve(self, embedding, top_k: int = 3):
        return [
            Document(content="Dummy document 1"),
            Document(content="Dummy document 2"),
        ]

    @property
    def index_dimension(self) -> int:
        return 10