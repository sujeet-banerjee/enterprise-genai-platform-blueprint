"""Tests for issue #224: API rate limits and in-flight caps."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from core.services.failure_classifier import FailureType
from core.services.rate_limit import RateLimitSettings


class _FakePipeline:
    def run(self, _query, **_kwargs):
        return {
            "response": "ok",
            "retrieved_docs": [],
            "retrieval_scores": [],
            "metrics": {},
            "cost": {},
            "token_budget": {},
            "latency": {},
            "failure_tags": [],
            "observability": {},
        }


def _api_yaml(tmp_path: Path, rate_block: str = "") -> Path:
    path = tmp_path / "api.yaml"
    path.write_text(f"require_api_key: false\napi_key: \"\"\n{rate_block}", encoding="utf-8")
    return path


def _rate_block(*, enabled=True, rpm=60, burst=1, scope="key", in_flight=10) -> str:
    return (
        "rate_limit:\n"
        f"  enabled: {str(enabled).lower()}\n"
        f"  requests_per_minute: {rpm}\n"
        f"  burst: {burst}\n"
        f"  scope: {scope}\n"
        f"  in_flight_max: {in_flight}\n"
    )


def _client(tmp_path: Path, rate_block: str = "", **kwargs) -> TestClient:
    api_path = _api_yaml(tmp_path, rate_block)
    return TestClient(
        create_app(api_config_path=api_path, pipeline_builder=lambda **_: _FakePipeline(), **kwargs)
    )


def _query(client: TestClient, key: str = "key-a", tenant: str | None = None):
    headers = {"X-API-Key": key}
    if tenant:
        headers["X-Tenant-ID"] = tenant
    return client.post("/v1/query", json={"query": "hello"}, headers=headers)


def test_settings_default_off_and_validate_scope() -> None:
    settings = RateLimitSettings.from_config({})
    assert settings.enabled is False
    assert settings.requests_per_minute == 60
    assert settings.burst == 10
    assert settings.scope == "auto"
    assert settings.in_flight_max == 4
    with pytest.raises(ValueError):
        RateLimitSettings.from_config({"rate_limit": {"scope": "bogus"}})
    with pytest.raises(ValueError):
        RateLimitSettings.from_config({"rate_limit": {"requests_per_minute": 0}})


def test_rate_limited_failure_type_is_in_taxonomy() -> None:
    assert FailureType.RATE_LIMITED.value == "rate_limited"


def test_within_limit_then_429_envelope_with_retry_after(tmp_path: Path) -> None:
    with _client(tmp_path, _rate_block()) as client:
        assert _query(client).status_code == 200
        denied = _query(client)
    assert denied.status_code == 429
    body = denied.json()
    assert body["error"] == "Request rate limit exceeded."
    assert body["failure_type"] == "rate_limited"
    assert "rate_limited" in body["failure_tags"]
    assert "rate_limit_request_rate" in body["failure_tags"]
    assert int(denied.headers["Retry-After"]) >= 1
    assert denied.headers["X-Request-ID"] == body["request_id"]
    assert "key-a" not in denied.text


def test_rate_buckets_are_isolated_by_api_key(tmp_path: Path) -> None:
    with _client(tmp_path, _rate_block()) as client:
        assert _query(client, "key-a").status_code == 200
        assert _query(client, "key-b").status_code == 200
        assert _query(client, "key-a").status_code == 429
        assert _query(client, "key-b").status_code == 429


def test_rate_buckets_are_isolated_by_tenant(tmp_path: Path) -> None:
    tenants = tmp_path / "tenants.yaml"
    tenants.write_text(
        "enabled: true\n"
        "default_tenant: default\n"
        "tenants:\n"
        "  alpha: {workspace: alpha}\n"
        "  beta: {workspace: beta}\n"
        "api_keys: {}\n"
        "header_override: {roles: [], api_keys: []}\n",
        encoding="utf-8",
    )
    with _client(
        tmp_path,
        _rate_block(scope="tenant"),
        tenants_config_path=tenants,
    ) as client:
        assert _query(client, "shared-key", "alpha").status_code == 200
        assert _query(client, "shared-key", "beta").status_code == 200
        assert _query(client, "shared-key", "alpha").status_code == 429


def test_in_flight_cap_returns_429_before_pipeline(tmp_path: Path) -> None:
    with _client(tmp_path, _rate_block(burst=100, in_flight=1)) as client:
        limiter = client.app.state.rate_limiter
        held = limiter.acquire("held-key", "key")
        assert held.allowed
        try:
            denied = _query(client, "held-key")
        finally:
            limiter.release(held)
    assert denied.status_code == 429
    assert denied.json()["failure_tags"] == ["rate_limited", "rate_limit_in_flight"]
    assert denied.headers["Retry-After"] == "1"


def test_disabled_mode_is_unchanged(tmp_path: Path) -> None:
    with _client(tmp_path, _rate_block(enabled=False)) as client:
        assert _query(client).status_code == 200
        assert _query(client).status_code == 200
        tokens, in_flight = client.app.state.rate_limiter.snapshot("key-a")
        assert in_flight == 0
        assert tokens == 1.0


def test_prometheus_counter_records_rejection(tmp_path: Path) -> None:
    with _client(tmp_path, _rate_block()) as client:
        assert _query(client).status_code == 200
        assert _query(client).status_code == 429
        response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "genai_rate_limit_events_total" in text
    assert 'reason="request_rate"' in text
    assert 'scope="key"' in text
    assert 'tenant="default"' in text
