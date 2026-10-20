"""Hybrid (keyword + vector) retriever provider (issue #25).

Pure vector retrieval can miss exact keyword matches (IDs, names, rare terms),
while pure lexical retrieval misses paraphrase/semantic matches. This provider
fuses both signals with a configurable weight.

Because ``BaseRetriever.retrieve`` only receives a query *embedding* (not the
query text), the pipeline calls the optional ``retrieve_with_query`` hook when a
retriever exposes it; pure-vector retrievers are unaffected. Without query text
the retriever degrades to vector-only retrieval so it still satisfies the base
contract.

Fusion is a weighted sum of a normalised BM25 lexical score and a normalised
vector (cosine) score:

    combined = keyword_weight * lexical_norm + vector_weight * vector_norm

and is deterministic (no randomness, stable tie-breaking by document order).

Selecting it is a config change:

    retrieval:
      default_retriever: hybrid
      retrievers:
        hybrid:
          provider: hybrid
          keyword_weight: 0.5
          vector_weight: 0.5
"""

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from core.implementations.simple_retriever import SimpleRetriever
from core.interfaces.retriever import BaseRetriever, Document, ScoredDocument


class HybridRetriever(BaseRetriever):
    """Configurable keyword + vector retriever."""

    def __init__(
        self,
        docs: Optional[Sequence[Union[dict, Document, str]]] = None,
        embedder: Any = None,
        keyword_weight: float = 0.5,
        vector_weight: float = 0.5,
        k1: float = 1.5,
        b: float = 0.75,
        **_ignored: Any,
    ):
        if embedder is None:
            raise ValueError("The 'hybrid' retriever requires an embedder.")

        self.embedder = embedder
        self.keyword_weight = float(keyword_weight)
        self.vector_weight = float(vector_weight)
        self.k1 = float(k1)
        self.b = float(b)

        self._base = SimpleRetriever(docs=docs, embedder=embedder)
        self._docs: List[Document] = list(self._base.docs)
        self._tokenized: List[List[str]] = [self._tokenize(doc.content) for doc in self._docs]
        self._doc_freqs: Dict[str, int] = {}
        for tokens in self._tokenized:
            for token in set(tokens):
                self._doc_freqs[token] = self._doc_freqs.get(token, 0) + 1
        self._avg_len = (
            sum(len(tokens) for tokens in self._tokenized) / len(self._tokenized)
            if self._tokenized
            else 0.0
        )

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", (text or "").lower())

    @property
    def index_dimension(self) -> int:
        return self._base.index_dimension

    # -- lexical (BM25) --------------------------------------------------

    def _bm25(self, query_tokens: Sequence[str], doc_index: int) -> float:
        if not query_tokens or self._avg_len == 0:
            return 0.0
        tokens = self._tokenized[doc_index]
        if not tokens:
            return 0.0
        doc_len = len(tokens)
        total_docs = len(self._tokenized)
        counts: Dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1

        score = 0.0
        for term in query_tokens:
            df = self._doc_freqs.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            tf = counts.get(term, 0)
            denom = tf + self.k1 * (1 - self.b + self.b * (doc_len / self._avg_len))
            score += idf * (tf * (self.k1 + 1)) / denom if denom else 0.0
        return score

    @staticmethod
    def _normalize(scores: Sequence[float]) -> List[float]:
        if not scores:
            return []
        lo = min(scores)
        hi = max(scores)
        if hi - lo == 0:
            return [0.0 for _ in scores] if hi == 0 else [1.0 for _ in scores]
        return [(s - lo) / (hi - lo) for s in scores]

    # -- retrieval -------------------------------------------------------

    def retrieve_with_query(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int = 3,
    ) -> List[ScoredDocument]:
        """Fuse BM25 keyword and vector scores for ``query``."""
        if not self._docs or top_k <= 0:
            return []

        vector_scores: List[float] = []
        for emb in self._base.embeddings:
            vector_scores.append(SimpleRetriever._cosine(query_embedding, emb))

        query_tokens = self._tokenize(query)
        lexical_scores = [self._bm25(query_tokens, idx) for idx in range(len(self._docs))]

        vector_norm = self._normalize(vector_scores)
        lexical_norm = self._normalize(lexical_scores)

        combined: List[Tuple[int, float]] = []
        for idx in range(len(self._docs)):
            fused = (
                self.keyword_weight * lexical_norm[idx]
                + self.vector_weight * vector_norm[idx]
            )
            combined.append((idx, round(float(fused), 6)))

        combined.sort(key=lambda item: (item[1], -item[0]), reverse=True)

        results: List[ScoredDocument] = []
        for rank_idx, (idx, fused) in enumerate(combined[:top_k]):
            meta = dict(self._docs[idx].metadata) if self._docs[idx].metadata else {}
            meta["score"] = fused
            meta["retrieval_rank"] = rank_idx
            meta["vector_score"] = round(float(vector_scores[idx]), 6)
            meta["lexical_score"] = round(float(lexical_scores[idx]), 6)
            doc_copy = Document(content=self._docs[idx].content, metadata=meta, score=fused)
            results.append(ScoredDocument(document=doc_copy, score=fused))
        return results

    def retrieve_with_scores(self, query_embedding: List[float], top_k: int = 3) -> List[ScoredDocument]:
        # No query text available -> degrade to vector-only retrieval.
        return self._base.retrieve_with_scores(query_embedding, top_k=top_k)

    def retrieve(self, query_embedding: List[float], top_k: int = 3) -> List[Document]:
        return [item.document for item in self.retrieve_with_scores(query_embedding, top_k=top_k)]
