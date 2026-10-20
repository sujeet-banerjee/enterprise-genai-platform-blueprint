"""Query expansion implementations (issue #23).

Each expander returns the original query plus one or more variants. The
``SynonymQueryExpander`` is dependency-free and deterministic; the
``LLMQueryExpander`` uses an injected language model to rewrite/paraphrase.
"""

from typing import Any, Dict, List, Optional, Sequence

from core.config.generation_config import GenerationConfig
from core.interfaces.query_expander import BaseQueryExpander


class NoopQueryExpander(BaseQueryExpander):
    """Returns the query unchanged (used when expansion is disabled)."""

    def expand(self, query: str) -> List[str]:
        return [query]


class SynonymQueryExpander(BaseQueryExpander):
    """Expands a query with configured synonyms.

    The synonym map is ``{term: [synonyms...]}``. For each configured term that
    appears in the query (case-insensitive, whole-word), a variant is produced
    with that term replaced by each synonym. The original query is always first
    and the total number of variants is capped by ``max_variants``.
    """

    def __init__(
        self,
        synonyms: Optional[Dict[str, Sequence[str]]] = None,
        max_variants: int = 3,
        include_original: bool = True,
    ):
        self.synonyms: Dict[str, List[str]] = {
            str(term).lower(): [str(s) for s in (values or [])]
            for term, values in (synonyms or {}).items()
        }
        self.max_variants = int(max_variants)
        self.include_original = bool(include_original)

    def expand(self, query: str) -> List[str]:
        import re

        variants: List[str] = [query] if self.include_original else []
        lowered = query.lower()
        for term, replacements in self.synonyms.items():
            if not re.search(rf"\b{re.escape(term)}\b", lowered):
                continue
            for replacement in replacements:
                variant = re.sub(
                    rf"\b{re.escape(term)}\b",
                    replacement,
                    query,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if variant not in variants:
                    variants.append(variant)
                if len(variants) >= max(1, self.max_variants):
                    return variants
        return variants


class LLMQueryExpander(BaseQueryExpander):
    """Uses an LLM to generate paraphrased query variants.

    The model is asked for one variant per line; blank lines and duplicates are
    dropped and the original query is kept first. Failures (e.g. an offline
    model) degrade gracefully to the original query.
    """

    _PROMPT = (
        "Rewrite the following search query into up to {n} alternative phrasings "
        "that preserve its meaning. Return one phrasing per line, no numbering, "
        "no extra text.\n\nQuery: {query}\n"
    )

    def __init__(
        self,
        llm: Optional[Any] = None,
        max_variants: int = 3,
        max_new_tokens: int = 64,
    ):
        self.llm = llm
        self.max_variants = int(max_variants)
        self.max_new_tokens = int(max_new_tokens)

    def expand(self, query: str) -> List[str]:
        if self.llm is None:
            return [query]

        prompt = self._PROMPT.format(n=self.max_variants, query=query)
        try:
            config = GenerationConfig(temperature=0.0, max_tokens=self.max_new_tokens)
            raw = self.llm.generate(prompt, config)
        except Exception:
            return [query]

        variants: List[str] = [query]
        for line in str(raw or "").splitlines():
            candidate = line.strip().lstrip("-*0123456789. ").strip()
            if not candidate or candidate.lower() == query.lower():
                continue
            if candidate not in variants:
                variants.append(candidate)
            if len(variants) >= max(1, self.max_variants):
                break
        return variants
