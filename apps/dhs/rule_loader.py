"""Health rule loader — parses YAML rule files and matches rules to entities."""

import logging
import os
from dataclasses import dataclass, field

import yaml
from jinja2 import Template

logger = logging.getLogger("dhs.rule_loader")

SEVERITY_ORDER = {"UNHEALTHY": 0, "DEGRADED": 1, "HEALTHY": 2}


@dataclass
class HealthRule:
    name: str
    entity_type: str
    state: str  # UNHEALTHY, DEGRADED
    duration: int  # debounce seconds (rule-specific)
    reason_template: str  # Jinja2 template
    # Single-query pattern
    promql: str | None = None
    threshold: float | None = None
    operator: str | None = None
    # Dual-query pattern (e.g., available vs desired)
    promql_desired: str | None = None
    promql_available: str | None = None
    # Match labels for sub-filtering (e.g., component: api)
    match_labels: dict = field(default_factory=dict)

    @property
    def is_dual_query(self) -> bool:
        return self.promql_desired is not None and self.promql_available is not None


@dataclass
class RuleFile:
    entity_type: str
    match_labels: dict
    rules: list[HealthRule]


def load_rules(rules_dir: str) -> list[RuleFile]:
    """Load all YAML rule files from directory. Returns list of RuleFile objects."""
    rule_files = []

    if not os.path.isdir(rules_dir):
        logger.error("Rules directory does not exist: %s", rules_dir)
        return rule_files

    for filename in sorted(os.listdir(rules_dir)):
        if not filename.endswith((".yaml", ".yml")):
            continue
        filepath = os.path.join(rules_dir, filename)
        try:
            with open(filepath) as f:
                data = yaml.safe_load(f)

            if not data or "rules" not in data:
                logger.warning("Skipping %s: no 'rules' key", filename)
                continue

            entity_type = data["entity_type"]
            match_labels = data.get("match_labels") or {}
            rules = []

            for r in data["rules"]:
                rule = HealthRule(
                    name=r["name"],
                    entity_type=entity_type,
                    state=r["state"],
                    duration=int(r["duration"]),
                    reason_template=r.get("reason", ""),
                    promql=r.get("promql"),
                    threshold=float(r["threshold"]) if r.get("threshold") is not None else None,
                    operator=r.get("operator"),
                    promql_desired=r.get("promql_desired"),
                    promql_available=r.get("promql_available"),
                    match_labels=match_labels,
                )
                rules.append(rule)

            # Sort by severity: UNHEALTHY first, then DEGRADED
            rules.sort(key=lambda r: SEVERITY_ORDER.get(r.state, 99))

            rf = RuleFile(entity_type=entity_type, match_labels=match_labels, rules=rules)
            rule_files.append(rf)
            logger.info(
                "Loaded %d rules for %s (match_labels=%s) from %s",
                len(rules), entity_type, match_labels, filename,
            )

        except Exception as e:
            logger.error("Failed to load rule file %s: %s", filename, e)

    return rule_files


def parse_entity_context(entity: dict) -> dict:
    """Extract template variables from entity for Jinja2 PromQL rendering.

    Entity ID formats:
      K8s 5-part: k8s:<cluster>:<namespace>:<Kind>:<name>
      K8s 4-part: k8s:<cluster>:Node:<name>  (Node has no namespace)
      Kafka:      kafka:<cluster>:<name>
      Database:   db:<env>:postgres:<name>
    """
    entity_id = entity.get("entity_id", "")
    parts = entity_id.split(":")
    context = {
        "entity_id": entity_id,
        "name": entity.get("name", ""),
        "entity_type": entity.get("type", ""),
        "namespace": "",
    }

    if entity_id.startswith("k8s:") and len(parts) >= 5:
        # k8s:<cluster>:<namespace>:<Kind>:<name>
        context["namespace"] = parts[2]
    elif entity_id.startswith("k8s:") and len(parts) == 4:
        # k8s:<cluster>:Node:<name> — no namespace
        context["namespace"] = ""

    return context


def render_promql(template_str: str, entity: dict) -> str:
    """Render a Jinja2 PromQL template with entity context variables."""
    context = parse_entity_context(entity)
    try:
        return Template(template_str).render(**context).strip()
    except Exception as e:
        logger.error("Failed to render PromQL template: %s error=%s", template_str, e)
        return template_str.strip()


def render_reason(rule: HealthRule, entity: dict, value: float | None = None,
                  available: float | None = None, desired: float | None = None) -> str:
    """Render the reason template with entity context and metric values."""
    context = parse_entity_context(entity)
    context["value"] = value
    context["available"] = available
    context["desired"] = desired
    try:
        return Template(rule.reason_template).render(**context)
    except Exception:
        return rule.reason_template


def matches_entity(rule_file: RuleFile, entity: dict) -> bool:
    """Check if a rule file applies to this entity.

    Manager decision: match_labels.component matches entity["name"].
    """
    if rule_file.entity_type != entity.get("type"):
        return False

    if not rule_file.match_labels:
        return True

    for label_key, label_value in rule_file.match_labels.items():
        if label_key == "component":
            # Manager decision: component matches entity name
            if entity.get("name") != label_value:
                return False
        else:
            # For other labels, check entity labels dict
            if entity.get("labels", {}).get(label_key) != label_value:
                return False

    return True
