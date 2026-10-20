"""Tests for issue #23: config-driven query expansion / multi-query retrieval.

Covers the expander implementations, the registry (default-off, provider
resolution, config plumbing) and pipeline integration (retrieval over expanded
queries with de-duplication; unchanged behaviour when disabled).
"""

import pytest

from core.implementations.query_expanders import (
    LLMQueryExpander,
    NoopQueryExpander,
    SynonymQueryExpander,
)
from core.registry.query_expander_registry import QueryExpanderRegistry

# -- implementations -------------------------------------------------------


def test_noop_expander_returns_original_only():
    assert NoopQueryExpander().expand("what is rag?") == ["what is rag?"]


def test_synonym_expander_adds_variants_for_configured_terms():
    expander = SynonymQueryExpander(
        synonyms={"ai": ["artificial intelligence"], "ml": ["machine learning"]},
        max_variants=3,
    )
    variants = expander.expand("how does ai relate to ml?")
    assert variants[0] == "how does ai relate to ml?"
    assert "how does artificial intelligence relate to ml?" in variants
    assert len(variants) <= 3


def test_synonym_expander_is_case_insensitive_and_word_bounded():
    expander = SynonymQueryExpander(synonyms={"ai": ["artificial intelligence"]})
    # "said" must NOT match the "ai" synonym (whole-word matching).
    assert expander.expand("what was said") == ["what was said"]
    assert len(expander.expand("AI is broad")) == 2


def test_synonym_expander_respects_max_variants():
    expander = SynonymQueryExpander(
        synonyms={"ai": ["a", "b", "c", "d"]}, max_variants=2
    )
    assert len(expander.expand("ai")) == 2


def test_llm_expander_parses_lines_and_dedupes():
    class _StubLLM:
        context_window = 100
        model_name = "stub"

        def generate(self, prompt, config=None):
            return "What is RAG\n- What is retrieval augmented generation?\nWhat is RAG\n"

    variants = LLMQueryExpander(llm=_StubLLM(), max_variants=3).expand("What is RAG")
    assert variants[0] == "What is RAG"
    assert "What is retrieval augmented generation?" in variants
    assert len(variants) == 2


def test_llm_expander_degrades_gracefully_without_llm():
    assert LLMQueryExpander(llm=None).expand("q") == ["q"]


def test_llm_expander_handles_model_failure():
    class _BoomLLM:
        context_window = 10
        model_name = "boom"

        def generate(self, prompt, config=None):
            raise RuntimeError("offline")

    assert LLMQueryExpander(llm=_BoomLLM()).expand("q") == ["q"]


# -- registry --------------------------------------------------------------


def _write_config(tmp_path, body):
    path = tmp_path / "retrieval.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


_DISABLED = "query_expansion:\n  enabled: false\n"

_ENABLED = """
query_expansion:
  enabled: true
  active_expander: synonym
  max_variants: 2
  expanders:
    synonym:
      provider: synonym
      synonyms:
        ai: [artificial intelligence]
    noop:
      provider: noop
"""


def test_registry_default_off_returns_none(tmp_path):
    registry = QueryExpanderRegistry(_write_config(tmp_path, _DISABLED))
    assert registry.is_enabled() is False
    assert registry.create() is None


def test_registry_enabled_builds_active_expander(tmp_path):
    registry = QueryExpanderRegistry(_write_config(tmp_path, _ENABLED))
    expander = registry.create()
    assert isinstance(expander, SynonymQueryExpander)
    # section-level max_variants: 2 is plumbed through.
    assert len(expander.expand("ai ai")) == 2


def test_registry_lists_and_resolves_named_expander(tmp_path):
    registry = QueryExpanderRegistry(_write_config(tmp_path, _ENABLED))
    assert registry.list_expanders() == ["noop", "synonym"]
    assert isinstance(registry.create(name="noop"), NoopQueryExpander)


def test_registry_unknown_provider_raises(tmp_path):
    registry = QueryExpanderRegistry(_write_config(tmp_path, _ENABLED))
    with pytest.raises(ValueError):
        registry.create(name="does_not_exist")


def test_registry_llm_provider_receives_injected_llm(tmp_path):
    body = """
query_expansion:
  enabled: true
  active_expander: llm
  expanders:
    llm: {provider: llm}
"""
    registry = QueryExpanderRegistry(_write_config(tmp_path, body))
    sentinel = object()
    expander = registry.create(llm=sentinel)
    assert isinstance(expander, LLMQueryExpander)
    assert expander.llm is sentinel


# -- pipeline integration --------------------------------------------------


class _VariantAwareRetriever:
    """Returns a distinct document per query variant so merging is observable."""

    index_dimension = 8

    def __init__(self):
        self.queries_seen = []

    def retrieve(self, embedding, top_k=3):
        from core.interfaces.retriever import Document

        text = getattr(embedding, "query", "")
        self.queries_seen.append(text)
        return [Document(content=f"doc-for:{text}", metadata={"doc_id": text}, score=0.5)]


class _QueryEmbedder:
    dimension = 8

    def embed(self, text):
        vec = _Encoding(text)
        return vec


class _Encoding(list):
    def __init__(self, query):
        super().__init__([0.0] * 8)
        self.query = query


class _RecordingExpander:
    def __init__(self, variants):
        self.variants = variants

    def expand(self, query):
        return list(self.variants)


def _run(pipeline, query):
    return pipeline.run(query, raise_on_failure=False)


def test_pipeline_disabled_by_default_is_unchanged(make_pipeline):
    pipeline = make_pipeline()
    assert pipeline.query_expander is None
    result = _run(pipeline, "What is deep learning?")
    assert result["response"]
    assert result["failure_tags"] == [] or result["response"] is not None


def test_pipeline_expands_and_dedupes(make_pipeline):
    retriever = _VariantAwareRetriever()
    embedder = _QueryEmbedder()
    pipeline = make_pipeline(
        retriever=retriever,
        embedder=embedder,
        reranker=None,
        query_expander=_RecordingExpander(["q", "q alt", "q"]),
    )
    result = _run(pipeline, "q")

    # De-duplication: three variant slots, two distinct queries -> two documents.
    assert retriever.queries_seen == ["q", "q alt", "q"]
    contents = result["retrieved_docs"]
    assert sorted(contents) == ["doc-for:q", "doc-for:q alt"]
    trace = result["observability"]
    assert trace["query_expansion_enabled"] is True
    assert trace["expanded_queries"] == ["q", "q alt", "q"]


def test_pipeline_single_variant_marks_expansion_disabled(make_pipeline):
    retriever = _VariantAwareRetriever()
    pipeline = make_pipeline(
        retriever=retriever,
        embedder=_QueryEmbedder(),
        reranker=None,
        query_expander=_RecordingExpander(["only"]),
    )
    result = _run(pipeline, "only")
    assert result["observability"]["query_expansion_enabled"] is False
    assert result["retrieved_docs"] == ["doc-for:only"]


def test_pipeline_merge_keeps_highest_score(make_pipeline):
    from core.interfaces.retriever import Document

    class _ScoredRetriever:
        index_dimension = 8

        def __init__(self):
            self._scores = {"q": 0.2, "q alt": 0.9}

        def retrieve(self, embedding, top_k=3):
            text = getattr(embedding, "query", "")
            return [
                Document(
                    content="shared", metadata={"doc_id": "shared"}, score=self._scores[text]
                )
            ]

    pipeline = make_pipeline(
        retriever=_ScoredRetriever(),
        embedder=_QueryEmbedder(),
        reranker=None,
        query_expander=_RecordingExpander(["q", "q alt"]),
    )
    result = _run(pipeline, "q")
    assert result["retrieved_docs"] == ["shared"]
    # The higher score (0.9) must win the de-duplication.
    assert result["retrieval_scores"] == [pytest.approx(0.9)]
