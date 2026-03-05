"""
Shared fixtures for DHS E2E tests.

Usage:
    # Against k3s on 5560 (default):
    pytest tests/e2e/ -v

    # Against a different DHS:
    DHS_API_URL=http://localhost:8080 pytest tests/e2e/ -v
"""

import os

import httpx
import pytest

DHS_API_URL = os.environ.get("DHS_API_URL", "http://192.168.1.210:30950")
SSOT_API_URL = os.environ.get("SSOT_API_URL", "http://192.168.1.210:30900")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://192.168.1.210:30090")


@pytest.fixture(scope="session")
def dhs_client():
    """HTTP client pointed at the DHS API."""
    with httpx.Client(base_url=DHS_API_URL, timeout=10) as c:
        yield c


@pytest.fixture(scope="session")
def ssot_client():
    """HTTP client pointed at the SSOT API (for reading health_summary)."""
    with httpx.Client(base_url=SSOT_API_URL, timeout=10) as c:
        yield c


@pytest.fixture(scope="session")
def prom_client():
    """HTTP client pointed at Prometheus (for checking DHS metrics)."""
    with httpx.Client(base_url=PROMETHEUS_URL, timeout=10) as c:
        yield c


@pytest.fixture(scope="session")
def prom_query(prom_client):
    """Factory: run an instant PromQL query, return result list."""

    def _query(promql: str) -> list:
        resp = prom_client.get("/api/v1/query", params={"query": promql})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        return data["data"]["result"]

    return _query
