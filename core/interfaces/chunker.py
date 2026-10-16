from abc import ABC, abstractmethod
from typing import List, Optional, Union
from core.interfaces.retriever import Document


class BaseChunker(ABC):
    """
    Contract for document chunking strategies.
    """

    @abstractmethod
    def chunk_text(self, text: str, metadata: Optional[dict] = None) -> List[Document]:
        """
        Splits raw text into a list of Document chunks.
        """
        pass

    def chunk_documents(self, docs: List[Union[dict, Document, str]]) -> List[Document]:
        """
        Splits a collection of documents into Document chunks.
        """
        all_chunks: List[Document] = []
        for doc_idx, doc in enumerate(docs or []):
            if isinstance(doc, Document):
                base_meta = dict(doc.metadata) if doc.metadata else {}
                content = doc.content
            elif isinstance(doc, dict):
                base_meta = dict(doc.get("metadata") or {})
                for k, v in doc.items():
                    if k not in ("content", "metadata"):
                        base_meta.setdefault(k, v)
                content = str(doc.get("content", ""))
            else:
                base_meta = {}
                content = str(doc)

            base_meta.setdefault("source_doc_id", doc_idx)
            chunks = self.chunk_text(content, metadata=base_meta)
            all_chunks.extend(chunks)
        return all_chunks

    def chunk(self, docs_or_text: Union[str, List[Union[dict, Document, str]]]) -> List[Document]:
        if isinstance(docs_or_text, str):
            return self.chunk_text(docs_or_text)
        return self.chunk_documents(docs_or_text)

    @property
    @abstractmethod
    def chunk_size(self) -> int:
        pass

    @property
    def chunk_overlap(self) -> int:
        return 0

    @property
    def strategy_name(self) -> str:
        return self.__class__.__name__.lower()
