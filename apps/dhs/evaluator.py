"""Evaluator loop — queries Prometheus, evaluates rules, drives state transitions."""

import asyncio
import logging
import time
from collections import defaultdict

from prometheus_client import Counter, Histogram

import config
from prom_client import PrometheusClient
from ssot_client import SSOTClient
from rule_loader import (
    HealthRule, RuleFile, matches_entity, render_promql, render_reason,
)
from state_engine import StateEngine
from root_cause import RootCauseResolver, RootCause
from event_enricher import EventEnricher, K8sEvent
from kafka_emitter import KafkaEmitter

logger = logging.getLogger("dhs.evaluator")

EVALUATIONS_COUNTER = Counter(
    "dhs_evaluations_total",
    "Total evaluations per entity type",
    ["entity_type"],
)
EVAL_DURATION = Histogram(
    "dhs_evaluation_duration_seconds",
    "Duration of a full evaluation cycle",
)


class Evaluator:
    def __init__(
        self,
        prometheus: PrometheusClient,
        ssot: SSOTClient,
        rule_files: list[RuleFile],
        state_engine: StateEngine,
        root_cause_resolver: RootCauseResolver,
        event_enricher: EventEnricher,
        kafka_emitter: KafkaEmitter | None = None,
    ):
        self.prometheus = prometheus
        self.ssot = ssot
        self.rule_files = rule_files
        self.state_engine = state_engine
        self.root_cause_resolver = root_cause_resolver
        self.event_enricher = event_enricher
        self.kafka_emitter = kafka_emitter
        self.eval_count = 0
        self._ownership_cache: dict[str, dict] = {}

    def _get_entity_types_with_rules(self) -> set[str]:
        """Return entity types that have at least one rule."""
        return {rf.entity_type for rf in self.rule_files}

    def _find_matching_rules(self, entity: dict) -> list[HealthRule]:
        """Find all rules that apply to this entity, sorted by severity."""
        rules = []
        for rf in self.rule_files:
            if matches_entity(rf, entity):
                rules.extend(rf.rules)
        # Re-sort UNHEALTHY first in case multiple RuleFiles matched
        severity = {"UNHEALTHY": 0, "DEGRADED": 1}
        rules.sort(key=lambda r: severity.get(r.state, 99))
        return rules

    async def _evaluate_rule(self, rule: HealthRule, entity: dict) -> tuple[bool, str]:
        """Evaluate a single rule against an entity. Returns (triggered, reason)."""
        if rule.is_dual_query:
            return await self._evaluate_dual_query(rule, entity)
        return await self._evaluate_single_query(rule, entity)

    async def _evaluate_single_query(self, rule: HealthRule, entity: dict) -> tuple[bool, str]:
        """Single-query: compare value against threshold."""
        promql = render_promql(rule.promql, entity)
        value = await self.prometheus.query_instant(promql)

        if value is None:
            return False, ""

        triggered = self._compare(value, rule.operator, rule.threshold)
        reason = render_reason(rule, entity, value=value) if triggered else ""
        return triggered, reason

    async def _evaluate_dual_query(self, rule: HealthRule, entity: dict) -> tuple[bool, str]:
        """Dual-query: compare two Prometheus values (e.g., available < desired)."""
        promql_desired = render_promql(rule.promql_desired, entity)
        promql_available = render_promql(rule.promql_available, entity)

        desired = await self.prometheus.query_instant(promql_desired)
        available = await self.prometheus.query_instant(promql_available)

        if desired is None or available is None:
            return False, ""

        # operator is "available < desired"
        triggered = False
        if rule.operator == "available < desired":
            triggered = available < desired

        reason = ""
        if triggered:
            reason = render_reason(rule, entity, available=available, desired=desired)
        return triggered, reason

    @staticmethod
    def _compare(value: float, operator: str, threshold: float) -> bool:
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

    def _get_debounce_seconds(self, derived_state: str, rule: HealthRule | None) -> int:
        """Get debounce duration — rule-specific if available, else global default."""
        if rule and rule.duration:
            return rule.duration
        if derived_state == "UNHEALTHY":
            return config.DEBOUNCE_UNHEALTHY_SECONDS
        elif derived_state == "DEGRADED":
            return config.DEBOUNCE_DEGRADED_SECONDS
        elif derived_state == "HEALTHY":
            return config.DEBOUNCE_HEALTHY_SECONDS
        return 60

    async def _evaluate_entity(
        self,
        entity: dict,
        health_map: dict[str, str],
        active_events: dict[str, list[K8sEvent]],
    ) -> int:
        """Evaluate all rules for one entity. Returns 1 if transition fired, 0 otherwise."""
        entity_id = entity.get("entity_id", "")
        entity_type = entity.get("type", "")

        rules = self._find_matching_rules(entity)
        if not rules:
            return 0

        EVALUATIONS_COUNTER.labels(entity_type=entity_type).inc()

        derived_state = "HEALTHY"
        reason = "All signals within thresholds"
        triggering_rule = None

        for rule in rules:
            try:
                triggered, rule_reason = await self._evaluate_rule(rule, entity)
                if triggered:
                    derived_state = rule.state
                    reason = rule_reason
                    triggering_rule = rule
                    break
            except Exception as e:
                logger.error(
                    "Error evaluating rule %s for %s: %s",
                    rule.name, entity_id, e,
                )
                continue

        # Resolve root cause
        rc = await self.root_cause_resolver.resolve(
            entity_id=entity_id,
            entity_type=entity_type,
            derived_state=derived_state,
            health_map=health_map,
            active_events=active_events,
        )

        # Append root cause info to reason
        if rc.reason_suffix:
            reason = f"{reason}. {rc.reason_suffix}"

        debounce = self._get_debounce_seconds(derived_state, triggering_rule)
        transition = self.state_engine.update(
            entity_id=entity_id,
            entity_type=entity_type,
            derived_state=derived_state,
            reason=reason,
            debounce_seconds=debounce,
            root_cause_entity_id=rc.entity_id,
        )

        if transition:
            payload = {
                "entity_id": transition.entity_id,
                "health_state": transition.new_state,
                "since": transition.since.isoformat(),
                "root_cause_entity_id": rc.entity_id,
                "confidence": rc.confidence,
                "reason": transition.reason,
                "last_updated_by": "dhs",
            }
            ssot_ok = await self.ssot.put_health_summary(payload)

            # Emit Kafka event after successful SSOT write
            if ssot_ok and self.kafka_emitter:
                ownership = await self._get_ownership_cached(entity_id)
                try:
                    await self.kafka_emitter.emit_transition(
                        transition, entity, rc, ownership,
                    )
                except Exception as e:
                    logger.error("Kafka emit error for %s: %s", entity_id, e)

            return 1

        return 0

    async def _get_ownership_cached(self, entity_id: str) -> dict:
        """Get ownership from per-cycle cache, fetching from SSOT on miss."""
        if entity_id not in self._ownership_cache:
            self._ownership_cache[entity_id] = await self.ssot.get_ownership(
                entity_id
            )
        return self._ownership_cache[entity_id]

    async def _build_health_map(self) -> dict[str, str]:
        """Build entity_id → health_state map from SSOT (fresh each cycle)."""
        summaries = await self.ssot.get_health_summary_all()
        return {
            s["entity_id"]: s.get("health_state", "UNKNOWN")
            for s in summaries
            if s.get("entity_id")
        }

    async def _build_active_events(
        self, entities: list[dict],
    ) -> dict[str, list[K8sEvent]]:
        """Query Loki for K8s events across all relevant namespaces."""
        # Collect unique namespaces from entity IDs
        namespaces = set()
        for entity in entities:
            entity_id = entity.get("entity_id", "")
            parts = entity_id.split(":")
            if entity_id.startswith("k8s:") and len(parts) >= 5:
                namespaces.add(parts[2])

        # Query Loki for each namespace
        events_by_name: dict[str, list[K8sEvent]] = defaultdict(list)
        for ns in namespaces:
            try:
                events = await self.event_enricher.get_recent_events(namespace=ns)
                for evt in events:
                    events_by_name[evt.involved_object].append(evt)
            except Exception as e:
                logger.warning("Failed to get events for namespace %s: %s", ns, e)

        return dict(events_by_name)

    async def run_cycle(self):
        """Run one full evaluation cycle across all entity types with rules."""
        start = time.time()
        self._ownership_cache.clear()
        entity_types = self._get_entity_types_with_rules()
        total_entities = 0
        total_transitions = 0

        # Build health map from SSOT (fresh authoritative data)
        health_map = await self._build_health_map()

        # Collect all entities first for event queries
        all_entities = []
        entities_by_type: dict[str, list[dict]] = {}
        for entity_type in entity_types:
            entities = await self.ssot.get_entities(entity_type=entity_type)
            entities_by_type[entity_type] = entities
            all_entities.extend(entities)

        # Build active events from Loki
        active_events = await self._build_active_events(all_entities)

        # Evaluate all entities
        for entity_type, entities in entities_by_type.items():
            for entity in entities:
                transitions = await self._evaluate_entity(
                    entity, health_map, active_events,
                )
                total_entities += 1
                total_transitions += transitions

        duration = time.time() - start
        EVAL_DURATION.observe(duration)
        self.eval_count += 1

        logger.info(
            "Eval cycle %d: %d entities, %d transitions in %.2fs",
            self.eval_count, total_entities, total_transitions, duration,
        )

    async def seed_from_ssot(self):
        """Seed state engine with current SSOT health states on startup."""
        summaries = await self.ssot.get_health_summary_all()
        for s in summaries:
            entity_id = s.get("entity_id")
            state = s.get("health_state", "UNKNOWN")
            root_cause = s.get("root_cause_entity_id")
            if entity_id:
                self.state_engine.seed(entity_id, state, root_cause)
        logger.info("Seeded %d entity states from SSOT", len(summaries))

    async def run_loop(self):
        """Run the evaluation loop forever."""
        await self.seed_from_ssot()
        while True:
            try:
                await self.run_cycle()
            except Exception:
                logger.exception("Evaluation cycle failed")
            await asyncio.sleep(config.EVAL_INTERVAL_SECONDS)
