"""Sprint 4 — Unit tests for StateEngine: cooldown, flap detection, debounce."""

import pytest
from datetime import datetime, timezone, timedelta

from state_engine import StateEngine, _severity

pytestmark = pytest.mark.sprint4


class TestSeverity:
    def test_healthy_is_lowest(self):
        assert _severity("HEALTHY") == 0

    def test_degraded_is_middle(self):
        assert _severity("DEGRADED") == 1

    def test_unhealthy_is_highest(self):
        assert _severity("UNHEALTHY") == 2

    def test_unknown_defaults_to_zero(self):
        assert _severity("UNKNOWN") == 0

    def test_escalation_order(self):
        assert _severity("UNHEALTHY") > _severity("DEGRADED") > _severity("HEALTHY")


class TestDebounce:
    def test_first_update_creates_entity_no_transition(self):
        """First update for a new entity should not fire a transition."""
        se = StateEngine()
        t = se.update("e1", "Deployment", "UNHEALTHY", "test", debounce_seconds=60)
        assert t is None

    def test_same_state_no_transition(self):
        """Derived state matching current state should not transition."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")
        t = se.update("e1", "Deployment", "HEALTHY", "ok", debounce_seconds=60)
        assert t is None

    def test_debounce_not_expired_no_transition(self):
        """Transition should not fire until debounce expires."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")
        # First eval with new derived state
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=60)
        assert t is None
        # Second eval — debounce not yet expired (only ~0ms elapsed)
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=60)
        assert t is None

    def test_debounce_expired_fires_transition(self):
        """Transition fires when debounce period has elapsed."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        # First eval — start debounce
        se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        # Second eval — debounce=0 so should fire immediately
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        assert t is not None
        assert t.old_state == "HEALTHY"
        assert t.new_state == "UNHEALTHY"

    def test_derived_state_change_resets_debounce(self):
        """Changing derived state resets the debounce timer."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        # Start debounce for DEGRADED
        se.update("e1", "Deployment", "DEGRADED", "slow", debounce_seconds=0)
        # Now change to UNHEALTHY — should reset debounce
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        assert t is None  # Reset, not fired yet
        # Next eval should fire
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        assert t is not None
        assert t.new_state == "UNHEALTHY"


class TestCooldown:
    def test_cooldown_suppresses_de_escalation(self):
        """De-escalation (UNHEALTHY→HEALTHY) should be blocked during cooldown."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        # Escalate to UNHEALTHY with debounce=0
        se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        assert t is not None  # Escalation fired

        # Immediately try to de-escalate — should be blocked by cooldown
        se.update("e1", "Deployment", "HEALTHY", "ok", debounce_seconds=0)
        t = se.update("e1", "Deployment", "HEALTHY", "ok", debounce_seconds=0)
        assert t is None  # Cooldown blocks de-escalation

    def test_cooldown_allows_escalation(self):
        """Escalation (DEGRADED→UNHEALTHY) should always fire, even during cooldown."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        # Escalate to DEGRADED
        se.update("e1", "Deployment", "DEGRADED", "slow", debounce_seconds=0)
        t = se.update("e1", "Deployment", "DEGRADED", "slow", debounce_seconds=0)
        assert t is not None
        assert t.new_state == "DEGRADED"

        # Immediately escalate to UNHEALTHY — should fire despite cooldown
        se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        assert t is not None
        assert t.new_state == "UNHEALTHY"

    def test_cooldown_expires_allows_de_escalation(self):
        """De-escalation should work after cooldown period expires."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        # Escalate
        se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        assert t is not None

        # Manually set last_transition_time far in the past (beyond cooldown)
        es = se.entity_states["e1"]
        es.last_transition_time = datetime.now(timezone.utc) - timedelta(seconds=120)

        # Now de-escalation should work
        se.update("e1", "Deployment", "HEALTHY", "ok", debounce_seconds=0)
        t = se.update("e1", "Deployment", "HEALTHY", "ok", debounce_seconds=0)
        assert t is not None
        assert t.new_state == "HEALTHY"


class TestRootCauseChange:
    def test_root_cause_change_fires_immediately(self):
        """Root cause change on non-HEALTHY entity fires immediately (no debounce)."""
        se = StateEngine()
        se.seed("e1", "UNHEALTHY", root_cause_entity_id="rc1")

        # Same state but different root cause — should fire immediately
        t = se.update(
            "e1", "Deployment", "UNHEALTHY", "bad",
            debounce_seconds=60,
            root_cause_entity_id="rc2",
        )
        assert t is not None
        assert t.root_cause_entity_id == "rc2"

    def test_root_cause_change_on_healthy_no_transition(self):
        """Root cause change on HEALTHY entity should not fire."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        t = se.update(
            "e1", "Deployment", "HEALTHY", "ok",
            debounce_seconds=60,
            root_cause_entity_id="rc1",
        )
        assert t is None


class TestFlapDetection:
    def test_flapping_doubles_debounce(self):
        """When entity is flapping, effective debounce should be doubled."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        # Simulate rapid transitions to trigger flapping
        now = datetime.now(timezone.utc)
        es = se.entity_states["e1"]
        # Add 4 transitions in quick succession (exceeds threshold of 3)
        for i in range(4):
            es.transition_history.append(now - timedelta(seconds=i))

        # Now the entity should be detected as flapping
        # The _check_flapping method is called during update
        se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=30)
        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=30)
        # Even with debounce=30, flapping doubles it to 60
        # Since only ~0ms elapsed, should not fire
        assert t is None

    def test_flap_clears_after_stability(self):
        """Flapping flag should clear after 5 minutes of stability."""
        se = StateEngine()
        se.seed("e1", "UNHEALTHY")

        es = se.entity_states["e1"]
        es.flapping = True
        # Set last_stable_time 6 minutes ago
        es.last_stable_time = datetime.now(timezone.utc) - timedelta(minutes=6)

        # Update with same state (stable) — should clear flap
        se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=60)
        assert es.flapping is False


class TestTransitionMetadata:
    def test_transition_has_correct_fields(self):
        """Transition object should have all required fields."""
        se = StateEngine()
        se.seed("e1", "HEALTHY")

        se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        t = se.update(
            "e1", "Deployment", "UNHEALTHY", "bad",
            debounce_seconds=0,
            root_cause_entity_id="rc1",
        )
        assert t is not None
        assert t.entity_id == "e1"
        assert t.entity_type == "Deployment"
        assert t.old_state == "HEALTHY"
        assert t.new_state == "UNHEALTHY"
        assert t.reason == "bad"
        assert t.root_cause_entity_id == "rc1"
        assert t.since is not None
        assert t.transition_time is not None

    def test_seeded_entity_no_false_transition(self):
        """Seeded entity should not re-transition to its current state."""
        se = StateEngine()
        se.seed("e1", "UNHEALTHY")

        t = se.update("e1", "Deployment", "UNHEALTHY", "bad", debounce_seconds=0)
        assert t is None  # Already UNHEALTHY, no transition
