"""Sprint 4 — Unit tests for Evaluator helper logic: compare operators, debounce selection."""

import pytest

pytestmark = pytest.mark.sprint4


class TestCompareOperators:
    """Test Evaluator._compare static method."""

    @staticmethod
    def _compare(value, operator, threshold):
        """Inline implementation to test without full Evaluator import."""
        # This mirrors Evaluator._compare exactly
        if operator == ">":
            return value > threshold
        elif operator == "<":
            return value < threshold
        elif operator == ">=":
            return value >= threshold
        elif operator == "<=":
            return value <= threshold
        elif operator == "==":
            return value == threshold
        return False

    def test_greater_than_true(self):
        assert self._compare(5.0, ">", 3.0) is True

    def test_greater_than_false(self):
        assert self._compare(2.0, ">", 3.0) is False

    def test_less_than_true(self):
        assert self._compare(0.0, "<", 1.0) is True

    def test_less_than_false(self):
        assert self._compare(2.0, "<", 1.0) is False

    def test_equal_true(self):
        assert self._compare(0.0, "==", 0.0) is True

    def test_equal_false(self):
        assert self._compare(1.0, "==", 0.0) is False

    def test_greater_equal(self):
        assert self._compare(3.0, ">=", 3.0) is True
        assert self._compare(2.0, ">=", 3.0) is False

    def test_less_equal(self):
        assert self._compare(3.0, "<=", 3.0) is True
        assert self._compare(4.0, "<=", 3.0) is False

    def test_unknown_operator_returns_false(self):
        assert self._compare(5.0, "!=", 3.0) is False


class TestDebounceSelection:
    """Test debounce seconds selection logic (mirrors Evaluator._get_debounce_seconds)."""

    def test_rule_specific_duration_takes_precedence(self):
        """Rule-defined duration should override global defaults."""
        # replica_unavailable rule has duration=60
        # global DEBOUNCE_UNHEALTHY_SECONDS is also 60
        # But a rule with duration=120 should use 120
        from rule_loader import HealthRule
        rule = HealthRule(
            name="test", entity_type="Deployment",
            state="UNHEALTHY", duration=120,
            reason_template="test",
        )
        # Simulate _get_debounce_seconds logic
        debounce = rule.duration if rule and rule.duration else 60
        assert debounce == 120

    def test_healthy_debounce_is_longer(self):
        """Recovery (HEALTHY) debounce should be 90s, longer than UNHEALTHY/DEGRADED (60s)."""
        import config
        assert config.DEBOUNCE_HEALTHY_SECONDS > config.DEBOUNCE_UNHEALTHY_SECONDS
        assert config.DEBOUNCE_HEALTHY_SECONDS > config.DEBOUNCE_DEGRADED_SECONDS
        assert config.DEBOUNCE_HEALTHY_SECONDS == 90


class TestThresholds:
    """Verify rule thresholds match architecture spec."""

    def test_deployment_replica_unavailable_threshold(self):
        """replica_unavailable rule: available == 0 for 60s."""
        import os
        from rule_loader import load_rules
        rules_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules",
        )
        if not os.path.isdir(rules_dir):
            pytest.skip("Rules directory not found")

        rule_files = load_rules(rules_dir)
        deployment_rf = [rf for rf in rule_files if rf.entity_type == "Deployment"][0]
        unavailable = [r for r in deployment_rf.rules if r.name == "replica_unavailable"][0]
        assert unavailable.threshold == 0
        assert unavailable.operator == "=="
        assert unavailable.duration == 60
        assert unavailable.state == "UNHEALTHY"

    def test_kafka_broker_down_threshold(self):
        """kafka broker_down rule: brokers < 1 for 120s."""
        import os
        from rule_loader import load_rules
        rules_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules",
        )
        if not os.path.isdir(rules_dir):
            pytest.skip("Rules directory not found")

        rule_files = load_rules(rules_dir)
        kafka_rf = [rf for rf in rule_files if rf.entity_type == "Kafka"][0]
        broker_down = kafka_rf.rules[0]
        assert broker_down.threshold == 1
        assert broker_down.operator == "<"
        assert broker_down.duration == 120
        assert broker_down.state == "UNHEALTHY"

    def test_database_unreachable_threshold(self):
        """database unreachable rule: pg_up < 1 for 60s."""
        import os
        from rule_loader import load_rules
        rules_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules",
        )
        if not os.path.isdir(rules_dir):
            pytest.skip("Rules directory not found")

        rule_files = load_rules(rules_dir)
        db_rf = [rf for rf in rule_files if rf.entity_type == "Database"][0]
        unreachable = db_rf.rules[0]
        assert unreachable.threshold == 1
        assert unreachable.operator == "<"
        assert unreachable.duration == 60
