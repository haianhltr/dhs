"""Sprint 4 — Unit tests for rule loader: YAML parsing, entity matching, PromQL rendering."""

import pytest

from rule_loader import (
    HealthRule, RuleFile, load_rules, matches_entity,
    render_promql, render_reason, parse_entity_context,
)

pytestmark = pytest.mark.sprint4


class TestEntityMatching:
    def test_matches_same_type_no_labels(self):
        """Rule with no match_labels matches any entity of same type."""
        rf = RuleFile(entity_type="Deployment", match_labels={}, rules=[])
        entity = {"type": "Deployment", "name": "api"}
        assert matches_entity(rf, entity) is True

    def test_no_match_different_type(self):
        """Rule should not match entity of different type."""
        rf = RuleFile(entity_type="Service", match_labels={}, rules=[])
        entity = {"type": "Deployment", "name": "api"}
        assert matches_entity(rf, entity) is False

    def test_component_label_matches_name(self):
        """match_labels.component should match against entity name."""
        rf = RuleFile(entity_type="Service", match_labels={"component": "api"}, rules=[])
        entity = {"type": "Service", "name": "api"}
        assert matches_entity(rf, entity) is True

    def test_component_label_no_match(self):
        """match_labels.component should not match different entity name."""
        rf = RuleFile(entity_type="Service", match_labels={"component": "api"}, rules=[])
        entity = {"type": "Service", "name": "worker"}
        assert matches_entity(rf, entity) is False

    def test_custom_label_matches(self):
        """Non-component labels should match against entity labels dict."""
        rf = RuleFile(entity_type="Service", match_labels={"env": "prod"}, rules=[])
        entity = {"type": "Service", "name": "api", "labels": {"env": "prod"}}
        assert matches_entity(rf, entity) is True

    def test_custom_label_no_match(self):
        rf = RuleFile(entity_type="Service", match_labels={"env": "prod"}, rules=[])
        entity = {"type": "Service", "name": "api", "labels": {"env": "lab"}}
        assert matches_entity(rf, entity) is False


class TestEntityContext:
    def test_k8s_5part_entity(self):
        """5-part k8s entity should parse namespace correctly."""
        entity = {
            "entity_id": "k8s:lab:calculator:Deployment:api",
            "name": "api",
            "type": "Deployment",
        }
        ctx = parse_entity_context(entity)
        assert ctx["namespace"] == "calculator"
        assert ctx["name"] == "api"
        assert ctx["entity_type"] == "Deployment"

    def test_k8s_4part_node(self):
        """4-part k8s Node entity should have empty namespace."""
        entity = {
            "entity_id": "k8s:lab:Node:5560",
            "name": "5560",
            "type": "Node",
        }
        ctx = parse_entity_context(entity)
        assert ctx["namespace"] == ""
        assert ctx["name"] == "5560"

    def test_kafka_entity(self):
        entity = {
            "entity_id": "kafka:lab:calculator-kafka",
            "name": "calculator-kafka",
            "type": "Kafka",
        }
        ctx = parse_entity_context(entity)
        assert ctx["name"] == "calculator-kafka"

    def test_database_entity(self):
        entity = {
            "entity_id": "db:lab:postgres:calculator",
            "name": "calculator",
            "type": "Database",
        }
        ctx = parse_entity_context(entity)
        assert ctx["name"] == "calculator"


class TestPromQLRendering:
    def test_render_deployment_promql(self):
        """Jinja2 template should substitute namespace and name."""
        template = 'kube_deployment_status_replicas_available{namespace="{{ namespace }}", deployment="{{ name }}"}'
        entity = {
            "entity_id": "k8s:lab:calculator:Deployment:api",
            "name": "api",
            "type": "Deployment",
        }
        result = render_promql(template, entity)
        assert 'namespace="calculator"' in result
        assert 'deployment="api"' in result

    def test_render_node_promql(self):
        template = 'kube_node_status_condition{node="{{ name }}", condition="Ready", status="true"}'
        entity = {
            "entity_id": "k8s:lab:Node:5560",
            "name": "5560",
            "type": "Node",
        }
        result = render_promql(template, entity)
        assert 'node="5560"' in result


class TestReasonRendering:
    def test_render_reason_with_value(self):
        rule = HealthRule(
            name="test", entity_type="Deployment", state="UNHEALTHY",
            duration=60, reason_template="Deployment {{ name }} has 0 replicas, value={{ value }}",
        )
        entity = {
            "entity_id": "k8s:lab:calculator:Deployment:api",
            "name": "api",
            "type": "Deployment",
        }
        result = render_reason(rule, entity, value=0.0)
        assert "api" in result
        assert "0.0" in result

    def test_render_reason_with_available_desired(self):
        rule = HealthRule(
            name="test", entity_type="Deployment", state="DEGRADED",
            duration=60, reason_template="{{ name }}: {{ available }}/{{ desired }} replicas",
        )
        entity = {
            "entity_id": "k8s:lab:calculator:Deployment:api",
            "name": "api",
            "type": "Deployment",
        }
        result = render_reason(rule, entity, available=1.0, desired=3.0)
        assert "1.0/3.0" in result


class TestRuleLoading:
    def test_load_rules_from_disk(self):
        """Load actual rules directory and verify structure."""
        import os
        rules_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules",
        )
        if not os.path.isdir(rules_dir):
            pytest.skip("Rules directory not found")

        rule_files = load_rules(rules_dir)
        assert len(rule_files) >= 4  # deployment, kafka, database, node at minimum

        entity_types = {rf.entity_type for rf in rule_files}
        assert "Deployment" in entity_types
        assert "Kafka" in entity_types
        assert "Database" in entity_types
        assert "Node" in entity_types

    def test_rules_sorted_by_severity(self):
        """UNHEALTHY rules should come before DEGRADED."""
        import os
        rules_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules",
        )
        if not os.path.isdir(rules_dir):
            pytest.skip("Rules directory not found")

        rule_files = load_rules(rules_dir)
        for rf in rule_files:
            if len(rf.rules) >= 2:
                states = [r.state for r in rf.rules]
                if "UNHEALTHY" in states and "DEGRADED" in states:
                    assert states.index("UNHEALTHY") < states.index("DEGRADED")

    def test_load_rules_missing_dir(self):
        """Missing directory should return empty list."""
        result = load_rules("/nonexistent/path")
        assert result == []


class TestSeverityOrder:
    def test_deployment_unhealthy_before_degraded(self):
        """Deployment rules should evaluate UNHEALTHY before DEGRADED."""
        import os
        rules_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules",
        )
        if not os.path.isdir(rules_dir):
            pytest.skip("Rules directory not found")

        rule_files = load_rules(rules_dir)
        deployment_rf = [rf for rf in rule_files if rf.entity_type == "Deployment"][0]
        assert deployment_rf.rules[0].state == "UNHEALTHY"  # replica_unavailable
        assert deployment_rf.rules[1].state == "DEGRADED"   # replica_degraded
