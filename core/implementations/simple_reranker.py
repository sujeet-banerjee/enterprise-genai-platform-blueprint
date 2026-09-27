from pathlib import Path
import re
from typing import Callable, List, Optional
import yaml

from core.interfaces.reranker import BaseReranker
from core.interfaces.retriever import Document, ScoredDocument


class SimpleReranker(BaseReranker):
    """
    Local configurable reranker suitable for experimentation and plug-and-play replacement.
    Supports lexical/keyword relevance, hybrid (lexical + initial retrieval score),
    score-based sorting, passthrough, or custom scoring callables (e.g. cross-encoder/LLM).
    """

    _STOPWORDS = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "in", "on", "at", "to", "for", "of", "with", "by", "about", "what",
        "which", "who", "whom", "how", "why", "when", "where", "do", "does",
        "did", "and", "or", "but", "if", "then", "from", "as",
    }

    def __init__(
        self,
        strategy: Optional[str] = None,
        lexical_weight: Optional[float] = None,
        initial_score_weight: Optional[float] = None,
        top_k: Optional[int] = None,
        config_path: Optional[str] = None,
        scoring_fn: Optional[Callable[[str, Document], float]] = None,
    ):
        cfg = self._load_config(config_path)
        rerank_cfg = cfg.get("reranking", {})

        self.strategy = (strategy or rerank_cfg.get("strategy", "lexical_hybrid")).lower()
        self.lexical_weight = (
            float(lexical_weight)
            if lexical_weight is not None
            else float(rerank_cfg.get("lexical_weight", 0.7))
        )
        self.initial_score_weight = (
            float(initial_score_weight)
            if initial_score_weight is not None
            else float(rerank_cfg.get("initial_score_weight", 0.3))
        )
        self.default_top_k = top_k if top_k is not None else rerank_cfg.get("top_k")
        self.scoring_fn = scoring_fn

    @staticmethod
    def _load_config(config_path: Optional[str] = None) -> dict:
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        content_tokens = [t for t in tokens if t not in cls._STOPWORDS]
        return content_tokens if content_tokens else tokens

    @classmethod
    def _compute_lexical_score(cls, query: str, content: str) -> float:
        q_tokens = cls._tokenize(query)
        d_tokens = cls._tokenize(content)
        if not q_tokens or not d_tokens:
            return 0.0

        q_set = set(q_tokens)
        d_set = set(d_tokens)
        overlap = len(q_set & d_set) / len(q_set)

        # Check prefix/stem matches (e.g. "intelligence" vs "intelligent", "neural" vs "neuron")
        stem_matches = 0
        for qt in q_set:
            prefix = qt[:5] if len(qt) >= 5 else qt
            if any(dt.startswith(prefix) or qt.startswith(dt[:5] if len(dt) >= 5 else dt) for dt in d_set):
                stem_matches += 1
        stem_score = stem_matches / len(q_set)

        # Phrase match bonus
        q_norm = " ".join(q_tokens)
        d_norm = " ".join(d_tokens)
        phrase_bonus = 0.2 if (len(q_tokens) > 1 and q_norm in d_norm) else 0.0

        raw = 0.65 * overlap + 0.35 * stem_score + phrase_bonus
        return min(1.0, round(float(raw), 6))

    def _score_document(self, query: str, doc: Document, initial_rank: int, total: int) -> float:
        if self.scoring_fn is not None:
            return float(self.scoring_fn(query, doc))

        initial_score = doc.score
        if initial_score is None and isinstance(doc.metadata, dict):
            initial_score = doc.metadata.get("score")
        if initial_score is None:
            initial_score = max(0.0, 1.0 - (initial_rank / max(1, total)))
        initial_score = float(initial_score)

        if self.strategy in ("noop", "passthrough"):
            return float(total - initial_rank)
        if self.strategy == "reverse":
            return float(initial_rank)
        if self.strategy in ("score", "score_desc"):
            return initial_score

        lexical_score = self._compute_lexical_score(query, doc.content)
        if self.strategy in ("lexical", "keyword"):
            return lexical_score

        # Default: lexical_hybrid
        combined = (self.lexical_weight * lexical_score) + (self.initial_score_weight * initial_score)
        return round(float(combined), 6)

    def rerank_with_scores(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[ScoredDocument]:
        if not documents:
            return []

        total = len(documents)
        scored_candidates = []
        for idx, doc in enumerate(documents):
            initial_score = doc.score
            if initial_score is None and isinstance(doc.metadata, dict):
                initial_score = doc.metadata.get("score")
            rerank_score = self._score_document(query, doc, idx, total)

            meta = dict(doc.metadata) if doc.metadata else {}
            meta["initial_rank"] = idx
            if initial_score is not None:
                meta["initial_score"] = float(initial_score)
            meta["rerank_score"] = float(rerank_score)
            meta["score"] = float(rerank_score)

            updated_doc = Document(
                content=doc.content,
                metadata=meta,
                score=float(rerank_score),
            )
            scored_candidates.append((updated_doc, float(rerank_score), idx))

        if self.strategy not in ("noop", "passthrough"):
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
