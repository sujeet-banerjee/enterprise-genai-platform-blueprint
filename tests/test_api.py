import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # Context manager runs the lifespan startup so the pipeline is built (#30).
    with TestClient(app) as test_client:
        yield test_client


def test_query_endpoint_happy_path(client):
    response = client.post("/query", json={"query": "What is machine learning?"})
    assert response.status_code == 200

    data = response.json()
    assert data["response"] is not None
    for key in (
        "response",
        "retrieved_docs",
        "retrieval_scores",
        "metrics",
        "cost",
        "token_budget",
        "latency",
        "failure_tags",
        "observability",
    ):
        assert key in data

    assert data["failure_tags"] == []


def test_query_endpoint_reports_governance_fields(client):
    response = client.post("/query", json={"query": "What is retrieval augmented generation?"})
    assert response.status_code == 200

    data = response.json()
    # Cost governance output is surfaced on every successful response.
    assert "estimated_cost_usd" in data["cost"]
    assert "allowed_output_tokens" in data["token_budget"]
    # Token-economics retrieval policy is reflected in the observability trace.
    assert data["observability"]["top_k"] >= 1


def test_query_endpoint_rejects_missing_field(client):
    response = client.post("/query", json={})
    assert response.status_code == 422


def test_query_endpoint_rejects_empty_query(client):
    response = client.post("/query", json={"query": ""})
    assert response.status_code == 422


def test_query_endpoint_rejects_malformed_json(client):
    response = client.post(
        "/query",
        content="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_query_endpoint_rejects_wrong_method(client):
    response = client.get("/query")
    assert response.status_code == 405
