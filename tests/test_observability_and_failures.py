import pytest

from core.implementations.hf_local_llm import LocalHFLLM
from core.implementations.simple_retriever import SimpleRetriever
from core.interfaces.embedder import BaseEmbedder
from core.interfaces.retriever import BaseRetriever, Document, ScoredDocument
from core.services.failure_classifier import FailureType
from core.services.observability import SensitiveDataRedactor


class _FixedScoreRetriever(BaseRetriever):
    """Returns a single pre-scored document to exercise low-score classification."""

    def __init__(self, content: str, score: float, dimension: int):
        self._doc = Document(content=content, score=score)
        self._dimension = dimension

    @property
    def index_dimension(self) -> int:
        return self._dimension

    def retrieve_with_scores(self, embedding, top_k: int = 3):
        return [ScoredDocument(document=self._doc, score=self._doc.score)]

    def retrieve(self, embedding, top_k: int = 3):
        return [self._doc]


class _FailingEmbedder(BaseEmbedder):
    def __init__(self, dimension: int):
        self._dimension = dimension

    def embed(self, text: str):
        raise RuntimeError("Embedding model crashed")

    @property
    def dimension(self) -> int:
        return self._dimension


class _FailingLLM(LocalHFLLM):
    def generate(self, prompt, config=None):
        raise RuntimeError("LLM provider timeout")


def test_pipeline_stage_latency_and_observability_fields(make_pipeline, real_reranker):
    pipeline = make_pipeline(reranker=real_reranker)
    result = pipeline.run("What are neural networks?")
    assert "latency" in result
    assert "observability" in result
    assert "retrieval_scores" in result

    latency = result["latency"]
    for stage in (
        "embedding",
        "retrieval",
        "reranking",
        "token_budget",
        "prompt_construction",
        "llm_generation",
        "evaluation",
        "total_pipeline",
    ):
        assert stage in latency
        assert isinstance(latency[stage], float)
        assert latency[stage] >= 0.0

    obs = result["observability"]
    for expected_key in (
        "request_id",
        "query",
        "embedding_model",
        "embedding_dimension",
        "retriever",
        "top_k",
        "retrieved_documents",
        "retrieval_scores",
        "reranker",
        "final_document_ordering",
        "token_budget",
        "latency",
        "llm_model",
        "failure_tags",
    ):
        assert expected_key in obs


def test_sensitive_data_redaction_in_observability_logs(make_pipeline):
    secret_doc = Document(
        content="Internal configuration: api_key=sk-proj1234567890abcdef password=MySuperSecretPassword123",
        score=0.92,
    )
    pipeline = make_pipeline(docs=[secret_doc])
    result = pipeline.run("Check credentials api_key=sk-9999999999abcdef")
    obs_str = str(result["observability"])

    assert "sk-proj1234567890abcdef" not in obs_str
    assert "MySuperSecretPassword123" not in obs_str
    assert "sk-9999999999abcdef" not in obs_str
    assert "[REDACTED]" in obs_str
    assert "[REDACTED]" in SensitiveDataRedactor.redact_text(
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    )


def test_failure_classification_no_documents_and_low_retrieval_score(
    make_pipeline, real_embedder
):
    empty_retriever = SimpleRetriever(docs=[], embedder=real_embedder)
    pipeline_empty = make_pipeline(retriever=empty_retriever)
    res_empty = pipeline_empty.run("Query with no docs")
    assert FailureType.NO_DOCUMENTS_RETRIEVED.value in res_empty["failure_tags"]

    low_score_retriever = _FixedScoreRetriever(
        content="Weakly related text", score=0.05, dimension=real_embedder.dimension
    )
    pipeline_low = make_pipeline(retriever=low_score_retriever)
    res_low = pipeline_low.run("Query with low score")
    assert FailureType.LOW_RETRIEVAL_SCORE.value in res_low["failure_tags"]


def test_failure_classification_across_pipeline_exceptions(
    make_pipeline, real_embedder, sample_docs
):
    retriever = SimpleRetriever(docs=sample_docs, embedder=real_embedder)

    pipeline_emb_fail = make_pipeline(
        embedder=_FailingEmbedder(real_embedder.dimension),
        retriever=retriever,
        raise_on_failure=False,
    )
    res_emb = pipeline_emb_fail.run("Test failure")
    assert res_emb["failure_type"] == FailureType.EMBEDDING_FAILURE.value
    assert FailureType.EMBEDDING_FAILURE.value in res_emb["failure_tags"]

    pipeline_llm_fail = make_pipeline(llm=_FailingLLM())
    with pytest.raises(RuntimeError) as exc_info:
        pipeline_llm_fail.run("Test LLM failure")
    assert getattr(exc_info.value, "failure_type", None) == FailureType.LLM_FAILURE.value
    assert pipeline_llm_fail.last_failure == FailureType.LLM_FAILURE.value
