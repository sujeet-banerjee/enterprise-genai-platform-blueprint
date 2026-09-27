from abc import ABC, abstractmethod
from typing import List, Optional
from core.interfaces.retriever import Document


class BaseChunker(ABC):
    """
    Contract for document chunking strategies.
    """

    @abstractmethod
    def chunk_text(self, text: str) -> List[str]:
        """
        Splits raw text string into a list of chunk strings.
        """
        pass

    def chunk_document(self, document: Document) -> List[Document]:
        """
        Splits a Document object into multiple smaller Document chunks,
        preserving and extending metadata.
        """
        chunks = self.chunk_text(document.content)
        result = []
        for i, chunk in enumerate(chunks):
            meta = dict(document.metadata) if document.metadata else {}
            meta["chunk_index"] = i
            meta["total_chunks"] = len(chunks)
            result.append(Document(content=chunk, metadata=meta, score=document.score))
        return result

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        """
        Splits a collection of Document objects into smaller Document chunks.
        """
        result = []
        for doc in documents:
            result.extend(self.chunk_document(doc))
        return result
