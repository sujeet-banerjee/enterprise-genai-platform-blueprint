from typing import Any, List, Optional

from core.implementations._local_models import get_cross_encoder
from core.interfaces.reranker import BaseReranker
from core.interfaces.retriever import Document, ScoredDocument


class CrossEncoderReranker(BaseReranker):
    """
    Genuine neural reranker backed by a sentence-transformers ``CrossEncoder``.

    Unlike the lexical ``SimpleReranker``, this scores every (query, document)
    pair through a real transformer, so relevance ordering is model-derived. The
    model is downloaded once and shared process-wide.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        top_k: Optional[int] = None,
        **_: Any,
    ):
        self._model_name = model_name
        self.default_top_k = top_k
        self._model: Optional[Any] = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            self._model = get_cross_encoder(self._model_name)
        return self._model

    def rerank_with_scores(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[ScoredDocument]:
        if not documents:
            return []

        model = self._ensure_model()
        pairs = [(query, doc.content) for doc in documents]
        raw_scores = model.predict(pairs)

        scored_candidates = []
        for idx, (doc, raw_score) in enumerate(zip(documents, raw_scores)):
            score = float(raw_score)
            meta = dict(doc.metadata) if doc.metadata else {}
            meta["initial_rank"] = idx
            meta["rerank_score"] = score
            meta["score"] = score
            meta["reranker"] = self.reranker_name
            scored_candidates.append(
                (Document(content=doc.content, metadata=meta, score=score), score, idx)
            )

        scored_candidates.sort(key=lambda item: (item[1], -item[2]), reverse=True)

        limit = top_k if top_k is not None else self.default_top_k
        if limit is not None:
            scored_candidates = scored_candidates[: int(limit)]

        results: List[ScoredDocument] = []
        for final_rank, (doc_obj, score_val, _) in enumerate(scored_candidates):
            doc_obj.metadata["final_rank"] = final_rank
            results.append(ScoredDocument(document=doc_obj, score=score_val))
        return results

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[Document]:
        scored = self.rerank_with_scores(query=query, documents=documents, top_k=top_k)
        return [item.document for item in scored]
