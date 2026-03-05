"""Root cause resolver — traverses SSOT topology to attribute root cause."""

import logging
from dataclasses import dataclass

from ssot_client import SSOTClient

logger = logging.getLogger("dhs.root_cause")


@dataclass
class RootCause:
    entity_id: str | None
    entity_name: str | None
    confidence: float
    reason_suffix: str | None


class RootCauseResolver:
    def __init__(self, ssot: SSOTClient):
        self.ssot = ssot

    async def resolve(
        self,
        entity_id: str,
        entity_type: str,
        derived_state: str,
        health_map: dict[str, str],
        active_events: dict[str, list] | None = None,
    ) -> RootCause:
        """Resolve root cause for an entity using SSOT topology.

        Resolution chain (first match wins):
        1. HEALTHY → no root cause
        2. Dependency UNHEALTHY → root cause = that dependency
        3. Owned Deployment UNHEALTHY (Service only) → root cause = Deployment
        4. Node UNHEALTHY + multiple failures → root cause = Node
        5. Self → root cause = entity itself
        """
        if derived_state == "HEALTHY":
            return RootCause(
                entity_id=None, entity_name=None,
                confidence=1.0, reason_suffix=None,
            )

        # Extract entity name from entity_id for event matching
        entity_name = entity_id.rsplit(":", 1)[-1] if ":" in entity_id else entity_id

        # 1. Dependency check
        rc = await self._check_dependencies(entity_id, health_map)
        if rc:
            return self._apply_event_boost(rc, entity_name, active_events)

        # 2. Ownership check (Service → owns → Deployment)
        if entity_type == "Service":
            rc = await self._check_ownership(entity_id, health_map)
            if rc:
                return self._apply_event_boost(rc, entity_name, active_events)

        # 3. Node check
        rc = await self._check_node(entity_id, health_map)
        if rc:
            return self._apply_event_boost(rc, entity_name, active_events)

        # 4. Self — no external root cause found
        rc = RootCause(
            entity_id=entity_id,
            entity_name=entity_name,
            confidence=0.5,
            reason_suffix=None,
        )
        return self._apply_event_boost(rc, entity_name, active_events)

    async def _check_dependencies(
        self, entity_id: str, health_map: dict[str, str],
    ) -> RootCause | None:
        """Check if any DEPENDS_ON target is UNHEALTHY."""
        rels = await self.ssot.get_relationships(
            source_entity_id=entity_id, rel_type="DEPENDS_ON",
        )
        unhealthy_deps = []
        for r in rels:
            target_id = r.get("target_entity_id", "")
            target_state = health_map.get(target_id, "UNKNOWN")
            if target_state == "UNHEALTHY":
                unhealthy_deps.append(target_id)

        if not unhealthy_deps:
            return None

        # Pick the first UNHEALTHY dependency as root cause
        root_id = unhealthy_deps[0]
        root_name = root_id.rsplit(":", 1)[-1] if ":" in root_id else root_id
        confidence = 0.85
        if len(unhealthy_deps) > 1:
            confidence = min(confidence + 0.05, 0.95)

        logger.info(
            "Root cause (dependency): %s -> %s (confidence=%.2f)",
            entity_id, root_id, confidence,
        )
        return RootCause(
            entity_id=root_id,
            entity_name=root_name,
            confidence=confidence,
            reason_suffix=f"Root cause: {root_name} is UNHEALTHY",
        )

    async def _check_ownership(
        self, entity_id: str, health_map: dict[str, str],
    ) -> RootCause | None:
        """Check if owned Deployment (Service → OWNS → Deployment) is UNHEALTHY."""
        rels = await self.ssot.get_relationships(
            source_entity_id=entity_id, rel_type="OWNS",
        )
        for r in rels:
            target_id = r.get("target_entity_id", "")
            target_state = health_map.get(target_id, "UNKNOWN")
            if target_state in ("UNHEALTHY", "DEGRADED"):
                target_name = target_id.rsplit(":", 1)[-1] if ":" in target_id else target_id
                confidence = 0.85 if target_state == "UNHEALTHY" else 0.75
                logger.info(
                    "Root cause (ownership): %s -> %s (confidence=%.2f)",
                    entity_id, target_id, confidence,
                )
                return RootCause(
                    entity_id=target_id,
                    entity_name=target_name,
                    confidence=confidence,
                    reason_suffix=f"Root cause: Deployment {target_name} is {target_state}",
                )
        return None

    async def _check_node(
        self, entity_id: str, health_map: dict[str, str],
    ) -> RootCause | None:
        """Check if the Node this entity runs on is UNHEALTHY."""
        rels = await self.ssot.get_relationships(
            source_entity_id=entity_id, rel_type="RUNS_ON",
        )
        for r in rels:
            node_id = r.get("target_entity_id", "")
            node_state = health_map.get(node_id, "UNKNOWN")
            if node_state == "UNHEALTHY":
                # Count how many entities on this node are failing
                failing_count = sum(
                    1 for eid, state in health_map.items()
                    if state in ("UNHEALTHY", "DEGRADED") and eid != entity_id
                )
                if failing_count >= 2:
                    node_name = node_id.rsplit(":", 1)[-1] if ":" in node_id else node_id
                    confidence = 0.70
                    logger.info(
                        "Root cause (node): %s -> %s (%d other failures, confidence=%.2f)",
                        entity_id, node_id, failing_count, confidence,
                    )
                    return RootCause(
                        entity_id=node_id,
                        entity_name=node_name,
                        confidence=confidence,
                        reason_suffix=f"Root cause: Node {node_name} is UNHEALTHY ({failing_count} other entities affected)",
                    )
        return None

    @staticmethod
    def _apply_event_boost(
        rc: RootCause,
        entity_name: str,
        active_events: dict[str, list] | None,
    ) -> RootCause:
        """Boost confidence if K8s events match this entity."""
        if not active_events:
            return rc

        events = active_events.get(entity_name, [])
        if not events:
            return rc

        # Boost confidence by 0.10 for matching events
        boost = 0.10
        rc.confidence = min(rc.confidence + boost, 0.95)

        # Enrich reason with event info
        event_reasons = list({e.signal for e in events})[:3]
        event_text = ", ".join(event_reasons)
        if rc.reason_suffix:
            rc.reason_suffix += f". K8s events: {event_text}"
        else:
            rc.reason_suffix = f"K8s events: {event_text}"

        return rc
