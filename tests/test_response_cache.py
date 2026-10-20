"""Tests for issue #26: optional, config-driven response cache.

Covers ``ResponseCache`` (hit/miss/eviction/TTL/disabled/stats), pipeline
integration (a hit skips retrieval + generation and surfaces ``cache_hit``) and
composition-root wiring from ``cache.*`` config.
"""

from pathlib import Path

import yaml

from app.main import build_pipeline
from core.services.response_cache import ResponseCache

# -- unit ------------------------------------------------------------------


def test_cache_disabled_is_a_noop():
    cache = ResponseCache(enabled=False)
    key = cache.make_key("q", 3)
    cache.set(key, {"response": "x"})
    assert cache.get(key) is None
    assert cache.stats()["hits"] == 0
    assert cache.stats()["misses"] == 0


def test_cache_hit_and_miss():
    cache = ResponseCache(enabled=True)
    key = cache.make_key("hello", 3)
    assert cache.get(key) is None  # miss
    cache.set(key, {"response": "world"})
    assert cache.get(key) == {"response": "world"}  # hit
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_cache_key_depends_on_query_and_top_k():
    cache = ResponseCache(enabled=True)
    assert cache.make_key("a", 3) != cache.make_key("b", 3)
    assert cache.make_key("a", 3) != cache.make_key("a", 5)


def test_cache_evicts_lru_entry():
    clock = [0.0]
    cache = ResponseCache(enabled=True, max_entries=2, ttl_seconds=None, clock=lambda: clock[0])
    k1, k2, k3 = cache.make_key("1", 1), cache.make_key("2", 1), cache.make_key("3", 1)
    cache.set(k1, {"v": 1})
    cache.set(k2, {"v": 2})
    cache.get(k1)  # touch k1 so k2 is least-recently-used
    cache.set(k3, {"v": 3})  # should evict k2
    assert cache.get(k2) is None
    assert cache.get(k1) == {"v": 1}
    assert cache.get(k3) == {"v": 3}
    assert cache.stats()["evictions"] == 1


def test_cache_ttl_expiry():
    clock = [0.0]
    cache = ResponseCache(enabled=True, ttl_seconds=10.0, clock=lambda: clock[0])
    key = cache.make_key("q", 3)
    cache.set(key, {"v": 1})
    clock[0] = 5.0
    assert cache.get(key) == {"v": 1}
    clock[0] = 11.0
    assert cache.get(key) is None


def test_cache_respects_max_entries_bound():
    cache = ResponseCache(enabled=True, max_entries=3, ttl_seconds=None)
    for i in range(10):
        cache.set(cache.make_key(f"q{i}", 1), {"i": i})
    assert cache.stats()["entries"] == 3


# -- pipeline integration --------------------------------------------------


def test_pipeline_cache_miss_then_hit(make_pipeline):
    cache = ResponseCache(enabled=True)
    pipeline = make_pipeline(cache=cache, reranker=None)

    first = pipeline.run("What is deep learning?", raise_on_failure=False)
    assert first["cache_hit"] is False
    assert first["observability"]["cache_hit"] is False

    second = pipeline.run("What is deep learning?", raise_on_failure=False)
    assert second["cache_hit"] is True
    assert second["observability"]["cache_hit"] is True
    # A hit returns the same answer without re-running the pipeline.
    assert second["response"] == first["response"]
    assert cache.stats()["hits"] == 1


def test_pipeline_without_cache_is_unchanged(make_pipeline):
    pipeline = make_pipeline(reranker=None)
    assert pipeline.cache is None
    result = pipeline.run("What is neural network?", raise_on_failure=False)
    assert result["cache_hit"] is False


def test_pipeline_cache_hit_skips_retrieval(make_pipeline):
    calls = {"count": 0}

    class _CountingRetriever:
        index_dimension = 384

        def __init__(self, inner):
            self.inner = inner

        def retrieve(self, embedding, top_k=3):
            calls["count"] += 1
            return self.inner.retrieve(embedding, top_k=top_k)

    pipeline = make_pipeline(reranker=None, cache=ResponseCache(enabled=True))
    inner = pipeline.retriever
    pipeline.retriever = _CountingRetriever(inner)

    pipeline.run("repeatable query", raise_on_failure=False)
    assert calls["count"] == 1
    pipeline.run("repeatable query", raise_on_failure=False)
    assert calls["count"] == 1  # second call served from cache, no retrieval


# -- composition root wiring ----------------------------------------------


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path) -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )


def _retrieval_config(tmp_path: Path, cache: dict) -> str:
    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "top_k": 3,
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "evaluation": {"enabled": False, "active_evaluator": "dummy"},
            "cache": cache,
        },
    )


def test_composition_root_cache_off_by_default(tmp_path):
    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path, {})),
    )
    assert pipeline.cache is None


def test_composition_root_builds_cache_from_config(tmp_path):
    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(
            _retrieval_config(
                tmp_path, {"enabled": True, "max_entries": 7, "ttl_seconds": 42}
            )
        ),
    )
    assert pipeline.cache is not None
    assert pipeline.cache.enabled is True
    assert pipeline.cache.max_entries == 7
    assert pipeline.cache.ttl_seconds == 42.0
    assert pipeline.cache.namespace  # non-empty component namespace
