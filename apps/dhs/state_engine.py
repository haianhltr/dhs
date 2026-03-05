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


@dataclass
class Transition:
    entity_id: str
    entity_type: str
    old_state: str
    new_state: str
    reason: str
    since: datetime  # When condition first appeared (derived_since)
    transition_time: datetime  # When debounce expired (now)


class StateEngine:
    def __init__(self):
        self.entity_states: dict[str, EntityState] = {}

    def seed(self, entity_id: str, state: str):
        """Seed known state from SSOT on startup to avoid false re-transitions."""
        self.entity_states[entity_id] = EntityState(
            entity_id=entity_id,
            current_state=state,
            derived_state=state,
            derived_since=None,
            reason="",
        )

    def update(
        self,
        entity_id: str,
        entity_type: str,
        derived_state: str,
        reason: str,
        debounce_seconds: int,
    ) -> Transition | None:
        """Process a new derived state. Returns Transition if debounce expired."""
        now = datetime.now(timezone.utc)

        if entity_id not in self.entity_states:
            # First time seeing this entity — initialize
            self.entity_states[entity_id] = EntityState(
                entity_id=entity_id,
                current_state="UNKNOWN",
                derived_state=derived_state,
                derived_since=now if derived_state != "UNKNOWN" else None,
                reason=reason,
            )
            return None

        es = self.entity_states[entity_id]

        # Case 1: derived matches current — no transition needed, reset pending
        if derived_state == es.current_state:
            es.derived_state = derived_state
            es.derived_since = None
            es.reason = reason
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
            )
            # Commit the new state
            es.current_state = derived_state
            es.derived_since = None

            TRANSITIONS_COUNTER.labels(
                entity_type=entity_type,
                old_state=transition.old_state,
                new_state=transition.new_state,
            ).inc()

            logger.info(
                "Transition: %s %s -> %s (reason: %s)",
                entity_id, transition.old_state, transition.new_state, reason,
            )
            return transition

        # Still debouncing
        es.reason = reason
        return None
