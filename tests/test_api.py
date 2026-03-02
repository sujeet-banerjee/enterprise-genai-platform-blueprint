from fastapi.testclient import TestClient
from app.main import app

"""
Installation:
pip install fastapi uvicorn pytest httpx
"""

client = TestClient(app)


def test_query_endpoint():
    response = client.post("/query", json={"query": "Hello world"})
    print("TEST API RESPONSE: ", response.json())
    assert response.status_code == 200

    data = response.json()

    assert "response" in data
    assert "retrieved_docs" in data
    assert "metrics" in data
    assert "cost" in data
    assert "token_budget" in data