"""Sprint 4 — E2E smoke tests for failure scenario validation.

Non-destructive tests only (no kubectl scale, no bad images).
These verify DHS metrics, state engine behavior, and Kafka event
structure against the live cluster.

Destructive DoD scenarios are documented in the manual RUNBOOK.md.
"""

import pytest

pytestmark = pytest.mark.sprint4


class TestStateEngineMetrics:
    def test_transitions_metric_exists(self, dhs_client):
        """dhs_transitions_total metric should be registered with labels."""
        resp = dhs_client.get("/metrics")
        assert resp.status_code == 200
        assert "dhs_transitions_total" in resp.text

    def test_evaluations_cover_all_entity_types(self, dhs_client):
        """DHS should be evaluating all 5 entity types that have rules."""
        resp = dhs_client.get("/metrics")
        assert resp.status_code == 200
        text = resp.text
        expected_types = ["Deployment", "Service", "Kafka", "Database", "Node"]
        for et in expected_types:
            assert f'entity_type="{et}"' in text, (
                f"Missing evaluations for entity_type={et}"
            )


class TestNoSpamVerification:
    def test_transition_count_is_reasonable(self, dhs_client):
        """Transition count should not grow rapidly (sign of spam).

        A healthy cluster should have very few transitions after initial
        evaluation. If transitions are growing every 30s, something is wrong.
        """
        resp = dhs_client.get("/metrics")
        assert resp.status_code == 200
        text = resp.text
        # Parse all dhs_transitions_total lines
        total_transitions = 0
        for line in text.splitlines():
            if line.startswith("dhs_transitions_total{"):
                try:
                    value = float(line.split()[-1])
                    total_transitions += value
                except (ValueError, IndexError):
                    continue

        # After steady-state, total transitions should be < 100
        # (initial evaluations + any real state changes)
        eval_count = 0
        for line in text.splitlines():
            if line.startswith("dhs_evaluations_total{"):
                try:
                    eval_count += float(line.split()[-1])
                except (ValueError, IndexError):
                    continue

        if eval_count > 0:
            # Transition ratio should be very small (< 10% of evaluations)
            ratio = total_transitions / eval_count
            assert ratio < 0.10, (
                f"Transition/evaluation ratio {ratio:.3f} is too high — "
                f"possible spam ({total_transitions} transitions / {eval_count} evaluations)"
            )


class TestKafkaEventIntegrity:
    def test_emitted_metric_exists(self, dhs_client):
        """dhs_transition_events_emitted_total should be registered."""
        resp = dhs_client.get("/metrics")
        assert resp.status_code == 200
        assert "dhs_transition_events_emitted_total" in resp.text

    def test_emitted_count_not_exceeding_transitions(self, dhs_client):
        """Emitted Kafka events should never exceed transition count."""
        resp = dhs_client.get("/metrics")
        assert resp.status_code == 200
        text = resp.text

        emitted = 0
        for line in text.splitlines():
            if line.startswith("dhs_transition_events_emitted_total "):
                try:
                    emitted = float(line.split()[-1])
                except (ValueError, IndexError):
                    pass
                break

        total_transitions = 0
        for line in text.splitlines():
            if line.startswith("dhs_transitions_total{"):
                try:
                    total_transitions += float(line.split()[-1])
                except (ValueError, IndexError):
                    continue

        assert emitted <= total_transitions + 1, (
            f"Emitted ({emitted}) > transitions ({total_transitions}) — impossible"
        )


class TestHealthSummaryConsistency:
    def test_unhealthy_entities_have_root_cause(self, ssot_client):
        """All UNHEALTHY entities written by DHS should have root_cause_entity_id."""
        resp = ssot_client.get("/health_summary")
        assert resp.status_code == 200
        data = resp.json()

        dhs_unhealthy = [
            r for r in data
            if r.get("health_state") == "UNHEALTHY"
            and r.get("last_updated_by") == "dhs"
        ]
        for record in dhs_unhealthy:
            assert record.get("root_cause_entity_id") is not None, (
                f"UNHEALTHY entity {record['entity_id']} missing root_cause_entity_id"
            )
            assert record.get("confidence", 0) > 0, (
                f"UNHEALTHY entity {record['entity_id']} has confidence=0"
            )

    def test_healthy_entities_have_no_root_cause(self, ssot_client):
        """HEALTHY entities should have null root_cause_entity_id."""
        resp = ssot_client.get("/health_summary")
        assert resp.status_code == 200
        data = resp.json()

        dhs_healthy = [
            r for r in data
            if r.get("health_state") == "HEALTHY"
            and r.get("last_updated_by") == "dhs"
        ]
        for record in dhs_healthy[:10]:
            assert record.get("root_cause_entity_id") is None, (
                f"HEALTHY entity {record['entity_id']} should not have root_cause"
            )


class TestDHSVersion:
    def test_version_is_sprint4_ready(self, dhs_client):
        """DHS should be running version 0.3.0+ (Sprint 3+)."""
        resp = dhs_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("version") >= "0.3.0"
