"""State engine — tracks per-entity health state with debounced transitions."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from prometheus_client import Counter

logger = logging.getLogger("dhs.state_engine")

TRANSITIONS_COUNTER = Counter(
    "dhs_transitions_total",
    "Health state transitions",
    ["entity_type", "old_state", "new_state"],
)


@dataclass
class EntityState:
    entity_id: str
    current_state: str  # Last committed state (what SSOT has)
    derived_state: str  # Latest evaluation result
    derived_since: datetime | None  # When derived_state first differed from current
    reason: str = ""
    root_cause_entity_id: str | None = None  # Current committed root cause


@dataclass
class Transition:
    entity_id: str
    entity_type: str
    old_state: str
    new_state: str
    reason: str
    since: datetime  # When condition first appeared (derived_since)
    transition_time: datetime  # When debounce expired (now)
    root_cause_entity_id: str | None = None


class StateEngine:
    def __init__(self):
        self.entity_states: dict[str, EntityState] = {}

    def seed(self, entity_id: str, state: str, root_cause_entity_id: str | None = None):
        """Seed known state from SSOT on startup to avoid false re-transitions."""
        self.entity_states[entity_id] = EntityState(
            entity_id=entity_id,
            current_state=state,
            derived_state=state,
            derived_since=None,
            reason="",
            root_cause_entity_id=root_cause_entity_id,
        )

    def update(
        self,
        entity_id: str,
        entity_type: str,
        derived_state: str,
        reason: str,
        debounce_seconds: int,
        root_cause_entity_id: str | None = None,
    ) -> Transition | None:
        """Process a new derived state. Returns Transition if debounce expired.

        Fires a transition when EITHER:
        - derived_state != current_state (with debounce), OR
        - root_cause_entity_id changed AND state is not HEALTHY (immediate)
        """
        now = datetime.now(timezone.utc)

        if entity_id not in self.entity_states:
            # First time seeing this entity — initialize
            self.entity_states[entity_id] = EntityState(
                entity_id=entity_id,
                current_state="UNKNOWN",
                derived_state=derived_state,
                derived_since=now if derived_state != "UNKNOWN" else None,
                reason=reason,
                root_cause_entity_id=root_cause_entity_id,
            )
            return None

        es = self.entity_states[entity_id]

        # Check for root cause change (immediate transition, no debounce)
        if (
            derived_state == es.current_state
            and derived_state != "HEALTHY"
            and root_cause_entity_id != es.root_cause_entity_id
        ):
            transition = Transition(
                entity_id=entity_id,
                entity_type=entity_type,
                old_state=es.current_state,
                new_state=derived_state,
                reason=reason,
                since=now,
                transition_time=now,
                root_cause_entity_id=root_cause_entity_id,
            )
            es.root_cause_entity_id = root_cause_entity_id
            es.reason = reason

            TRANSITIONS_COUNTER.labels(
                entity_type=entity_type,
                old_state=transition.old_state,
                new_state=transition.new_state,
            ).inc()

            logger.info(
                "Transition (root cause change): %s root_cause=%s (reason: %s)",
                entity_id, root_cause_entity_id, reason,
            )
            return transition

        # Case 1: derived matches current — no transition needed, reset pending
        if derived_state == es.current_state:
            es.derived_state = derived_state
            es.derived_since = None
            es.reason = reason
            es.root_cause_entity_id = root_cause_entity_id
            return None

        # Case 2: derived changed from what we saw last cycle — reset debounce timer
        if derived_state != es.derived_state:
            es.derived_state = derived_state
            es.derived_since = now
            es.reason = reason
            return None

        # Case 3: derived same as last cycle, different from current — check debounce
        if es.derived_since is None:
            es.derived_since = now
            es.reason = reason
            return None

        elapsed = (now - es.derived_since).total_seconds()
        if elapsed >= debounce_seconds:
            # Debounce expired — fire transition
            transition = Transition(
                entity_id=entity_id,
                entity_type=entity_type,
                old_state=es.current_state,
                new_state=derived_state,
                reason=reason,
                since=es.derived_since,
                transition_time=now,
                root_cause_entity_id=root_cause_entity_id,
            )
            # Commit the new state
            es.current_state = derived_state
            es.derived_since = None
            es.root_cause_entity_id = root_cause_entity_id

            TRANSITIONS_COUNTER.labels(
                entity_type=entity_type,
                old_state=transition.old_state,
                new_state=transition.new_state,
            ).inc()

            logger.info(
                "Transition: %s %s -> %s root_cause=%s (reason: %s)",
                entity_id, transition.old_state, transition.new_state,
                root_cause_entity_id, reason,
            )
            return transition

        # Still debouncing
        es.reason = reason
        return None
