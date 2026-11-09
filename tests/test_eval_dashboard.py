"""Issue #126 (K): eval dashboard enhancements (trends + regression alerts).

Backend/observability layer: records eval metrics, exposes trend/alert endpoints
and embeds an eval summary in /v1/metrics. No ui/* imports.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.eval_trends import EvalTrendStore
from app.main import create_app

REPO_BASE = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_BASE / "config" / "prompt_config.yaml"


class _FakePipeline:
    def run(self, query, top_k=None, raise_on_failure=None, request_id=None):
        return {
            "response": "ok",
            "retrieved_docs": [{"content": "Artificial intelligence simulates human intelligence."}],
            "retrieval_scores": [0.9],
            "metrics": {},
            "failure_tags": [],
            "observability": {"stages": {}},
        }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _make_configs(tmp_path: Path, *, regression_enabled: bool = False, threshold: float = 0.5):
    models = _write(
        tmp_path / "models.yaml",
        "active_model: dummy\nactive_embedding_model: emb-a\nmodels:\n  dummy:\n    provider: dummy\n    context_window: 4096\nembedding_models:\n  emb-a:\n    provider: dummy\n    model_name: emb-a\n",
    )
    retrieval = _write(
        tmp_path / "retrieval.yaml",
        "retrieval:\n  default_retriever: dummy\n  top_k: 2\n  retrievers:\n    dummy: {provider: dummy}\nevaluation:\n  enabled: true\n  active_evaluator: dummy\n  evaluators:\n    dummy: {provider: dummy}\nreranking: {enabled: false}\ngovernance: {enabled: false}\n",
    )
    eval_ds = _write(
        tmp_path / "eval_datasets.yaml",
        "enabled: true\ndatasets: {}\nregression:\n  enabled: %s\n  thresholds: {context_recall: %s}\n" % ("true" if regression_enabled else "false", threshold),
    )
    return models, retrieval, eval_ds


def test_trend_store_records_and_summarizes_metrics():
    store = EvalTrendStore()
    store.record({"context_precision": 0.8, "context_recall": 0.6}, source="evaluate", evaluator="dummy")
    store.record({"context_precision": 0.9, "context_recall": 0.7}, source="evaluate", evaluator="dummy")
    trends = store.trends()
    assert trends["num_points"] == 2
    assert "context_recall" in trends["summaries"]
    summary = trends["summaries"]["context_recall"]
    assert summary["latest"] == 0.7
    assert summary["count"] == 2
    assert summary["delta"] == 0.1
    assert summary["trend"] == "improving"


def test_trend_store_filters_and_limits():
    store = EvalTrendStore()
    for i in range(5):
        store.record({"score": float(i)}, evaluator="a", dataset="d1")
        store.record({"score": float(i)}, evaluator="b", dataset="d2")
    assert store.trends(evaluator="a")["num_points"] == 5
    assert store.trends(dataset="d2")["num_points"] == 5
    assert store.trends(limit=3)["num_points"] == 3
    # limit applies to points; metric series is derived from those points
    ms = store.trends(metric="score", limit=3)
    assert ms["num_points"] == 3
    assert ms["summaries"]["score"]["count"] == 3


def test_alerts_fire_below_threshold(tmp_path):
    _models, _retrieval, eval_ds = _make_configs(tmp_path, regression_enabled=True, threshold=0.75)
    store = EvalTrendStore(config_dir=tmp_path)
    store.record({"context_recall": 0.6}, evaluator="dummy")
    alerts = store.alerts()
    assert alerts["num_alerts"] == 1
    assert alerts["alerts"][0]["metric"] == "context_recall"
    assert alerts["alerts"][0]["status"] == "firing"
    assert alerts["regression_enabled"] is True


def test_alerts_do_not_fire_when_above_threshold(tmp_path):
    _make_configs(tmp_path, regression_enabled=True, threshold=0.5)
    store = EvalTrendStore(config_dir=tmp_path)
    store.record({"context_recall": 0.9}, evaluator="dummy")
    alerts = store.alerts()
    assert alerts["num_alerts"] == 0


def test_evaluate_endpoint_records_trends_and_alerts(tmp_path):
    models, retrieval, _eval_ds = _make_configs(tmp_path, regression_enabled=True, threshold=99.0)
    app = create_app(
        pipeline_builder=lambda **_: _FakePipeline(),
        models_config_path=models,
        prompt_config_path=REPO_PROMPT,
        retrieval_config_path=retrieval,
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/evaluate",
            json={
                "query": "What is artificial intelligence?",
                "response": "Artificial intelligence simulates human intelligence.",
                "retrieved_docs": [{"content": "Artificial intelligence simulates human intelligence."}],
                "evaluator": "dummy",
            },
        )
        assert resp.status_code == 200
        trends = client.get("/v1/eval/trends")
        assert trends.status_code == 200
        body = trends.json()
        assert body["num_points"] >= 1
        alerts = client.get("/v1/eval/alerts")
        assert alerts.status_code == 200
        # dummy evaluator returns 0-ish metrics vs absurd threshold => alert expected if metric present
        alert_body = alerts.json()
        assert "alerts" in alert_body
        metrics = client.get("/v1/metrics")
        assert metrics.status_code == 200
        assert "eval" in metrics.json()


def test_metrics_eval_block_present_without_points(tmp_path):
    models, retrieval, _eval_ds = _make_configs(tmp_path)
    app = create_app(
        pipeline_builder=lambda **_: _FakePipeline(),
        models_config_path=models,
        prompt_config_path=REPO_PROMPT,
        retrieval_config_path=retrieval,
    )
    with TestClient(app) as client:
        body = client.get("/v1/metrics").json()
    assert "eval" in body
    assert body["eval"]["trends"]["num_points"] == 0
    assert body["eval"]["alerts"]["num_alerts"] == 0
