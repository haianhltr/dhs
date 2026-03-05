"""Sprint 1 — Verify DHS evaluator loop is running and writing to SSOT."""

import pytest

pytestmark = pytest.mark.sprint1


class TestDHSReachable:
    def test_dhs_root(self, dhs_client):
        resp = dhs_client.get("/")
        assert resp.status_code == 200

    def test_dhs_health(self, dhs_client):
        resp = dhs_client.get("/health")
        assert resp.status_code == 200


class TestDHSMetrics:
    def test_metrics_endpoint_exists(self, dhs_client):
        resp = dhs_client.get("/metrics")
        assert resp.status_code == 200
        assert "dhs_evaluations_total" in resp.text

    def test_evaluations_running(self, dhs_client):
        """At least one evaluation cycle has completed."""
        resp = dhs_client.get("/metrics")
        for line in resp.text.splitlines():
            if line.startswith("dhs_evaluations_total"):
                value = float(line.split()[-1])
                assert value > 0, "No evaluation cycles completed yet"
                return
        pytest.fail("dhs_evaluations_total metric not found")


class TestHealthSummaryWritten:
    def test_ssot_has_health_summaries(self, ssot_client):
        """DHS should have written at least one health_summary to SSOT."""
        resp = ssot_client.get("/health_summary")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0, "No health_summary records in SSOT — DHS may not be writing"

    def test_health_summary_has_required_fields(self, ssot_client):
        """Each health_summary should have entity_id, health_state, reason."""
        resp = ssot_client.get("/health_summary")
        data = resp.json()
        if len(data) == 0:
            pytest.skip("No health_summary records to validate")
        record = data[0]
        assert "entity_id" in record
        assert "health_state" in record
        assert record["health_state"] in ("HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN")
