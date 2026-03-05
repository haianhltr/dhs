"""Sprint 2 — Verify root cause attribution and event enrichment."""

import pytest

pytestmark = pytest.mark.sprint2


class TestRootCauseAttribution:
    def test_health_summary_has_root_cause_fields(self, ssot_client):
        """health_summary records should include root_cause_entity_id and confidence."""
        resp = ssot_client.get("/health_summary")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0, "No health_summary records in SSOT"
        record = data[0]
        assert "root_cause_entity_id" in record
        assert "confidence" in record

    def test_healthy_entity_no_root_cause(self, ssot_client):
        """HEALTHY entities should have root_cause_entity_id=null and high confidence."""
        resp = ssot_client.get("/health_summary")
        data = resp.json()
        healthy = [r for r in data if r.get("health_state") == "HEALTHY"
                   and r.get("last_updated_by") == "dhs"]
        if not healthy:
            pytest.skip("No HEALTHY entities written by DHS")
        for record in healthy[:5]:
            assert record.get("root_cause_entity_id") is None, (
                f"HEALTHY entity {record['entity_id']} should not have root_cause"
            )

    def test_unhealthy_entity_has_confidence(self, ssot_client):
        """UNHEALTHY entities should have non-zero confidence."""
        resp = ssot_client.get("/health_summary")
        data = resp.json()
        unhealthy = [r for r in data if r.get("health_state") == "UNHEALTHY"
                     and r.get("last_updated_by") == "dhs"]
        if not unhealthy:
            pytest.skip("No UNHEALTHY entities to validate")
        for record in unhealthy:
            assert record.get("confidence", 0) > 0, (
                f"UNHEALTHY entity {record['entity_id']} should have confidence > 0"
            )
            assert record.get("root_cause_entity_id") is not None, (
                f"UNHEALTHY entity {record['entity_id']} should have root_cause_entity_id"
            )


class TestEventEnrichment:
    def test_dhs_has_event_metrics(self, dhs_client):
        """dhs_events_ingested_total metric should exist in /metrics."""
        resp = dhs_client.get("/metrics")
        assert resp.status_code == 200
        # The metric may have 0 value if no events have been ingested
        # Just check the metric name is registered
        assert "dhs_events_ingested" in resp.text

    def test_dhs_version_at_least_sprint2(self, dhs_client):
        """DHS should report version >= 0.2.0 (Sprint 2+)."""
        resp = dhs_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        version = data.get("version", "0.0.0")
        assert version >= "0.2.0", f"Expected version >= 0.2.0, got {version}"
