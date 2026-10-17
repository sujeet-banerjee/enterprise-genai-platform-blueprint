import math
import os

import pytest

from core.implementations.openai_embedder import OpenAIEmbedder

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; skipping live OpenAI embedding tests",
)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_embedding_dimension_matches_model():
    embedder = OpenAIEmbedder(
        api_key=os.environ["OPENAI_API_KEY"], model_name="text-embedding-3-small"
    )
    vector = embedder.embed("artificial intelligence")
    assert embedder.dimension == 1536
    assert len(vector) == 1536


def test_semantic_similarity_reflects_meaning():
    embedder = OpenAIEmbedder(api_key=os.environ["OPENAI_API_KEY"])
    query = embedder.embed("artificial intelligence")
    related = embedder.embed("AI and machine learning")
    unrelated = embedder.embed("bananas are a yellow fruit")
    assert _cosine(query, related) > _cosine(query, unrelated)
