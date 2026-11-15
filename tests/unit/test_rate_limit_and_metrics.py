"""Rate limiting and metrics endpoint tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.core import metrics as app_metrics
from backend.core.rate_limit import check_rate_limit, reset_rate_limiter
from backend.main import app


@pytest.fixture(autouse=True)
def clean_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


class FakeRequest:
    """Minimal stand-in for starlette Request."""

    def __init__(self, ip: str = "10.0.0.1", forwarded: str | None = None):
        self._ip = ip
        headers = {}
        if forwarded:
            headers["x-forwarded-for"] = forwarded

        class _Headers:
            def __init__(self, data):
                self._data = data

            def get(self, key, default=None):
                return self._data.get(key, default)

        self.headers = _Headers(headers)

        class _Client:
            host = ip

        self.client = _Client()


@pytest.mark.unit
class TestRateLimit:
    def test_allows_under_limit(self, monkeypatch):
        monkeypatch.setattr("backend.core.rate_limit.GENERAL_LIMIT", 5)
        request = FakeRequest("1.2.3.4")
        for _ in range(5):
            check_rate_limit(request, bucket="general")  # no raise

    def test_rejects_over_limit_with_429(self, monkeypatch):
        monkeypatch.setattr("backend.core.rate_limit.GENERAL_LIMIT", 3)
        request = FakeRequest("1.2.3.5")
        for _ in range(3):
            check_rate_limit(request, bucket="general")
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(request, bucket="general")
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    def test_admin_bucket_is_independent_and_stricter(self, monkeypatch):
        monkeypatch.setattr("backend.core.rate_limit.GENERAL_LIMIT", 100)
        monkeypatch.setattr("backend.core.rate_limit.ADMIN_LIMIT", 2)
        request = FakeRequest("1.2.3.6")
        check_rate_limit(request, bucket="general")
        check_rate_limit(request, bucket="admin")
        check_rate_limit(request, bucket="admin")
        with pytest.raises(HTTPException):
            check_rate_limit(request, bucket="admin")

    def test_forwarded_header_takes_precedence(self, monkeypatch):
        monkeypatch.setattr("backend.core.rate_limit.ADMIN_LIMIT", 1)
        # two different forwarded IPs share nothing
        check_rate_limit(FakeRequest("127.0.0.1", forwarded="8.8.8.8"), bucket="admin")
        check_rate_limit(FakeRequest("127.0.0.1", forwarded="9.9.9.9"), bucket="admin")

    def test_disabled_when_zero(self, monkeypatch):
        monkeypatch.setattr("backend.core.rate_limit.ADMIN_LIMIT", 0)
        request = FakeRequest("1.2.3.7")
        for _ in range(50):
            check_rate_limit(request, bucket="admin")  # never raises


@pytest.mark.unit
class TestMetricsEndpoint:
    def test_metrics_snapshot_shape(self, client=None):
        with TestClient(app) as client:
            client.get("/health")
            snapshot = client.get("/metrics").json()
        assert snapshot["requests"]["total"] >= 1  # /metrics itself is observed after the snapshot
        assert "200" in snapshot["requests"]["by_status"]
        assert "/health" in snapshot["latency_by_route"]
        assert "uptime_s" in snapshot

    def test_stage_recording(self):
        app_metrics.record_stage("unit_stage", 12.0)
        app_metrics.record_stage("unit_stage", 20.0)
        snapshot = app_metrics.snapshot()
        assert snapshot["stages"]["unit_stage"]["count"] == 2
        assert snapshot["stages"]["unit_stage"]["p50_ms"] == 12.0
