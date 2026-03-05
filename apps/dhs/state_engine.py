"""State engine — tracks per-entity health state with debounced transitions,
cooldown (de-escalation only), and flap detection."""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from prometheus_client import Counter

import config

logger = logging.getLogger("dhs.state_engine")

TRANSITIONS_COUNTER = Counter(
    "dhs_transitions_total",
    "Health state transitions",
    ["entity_type", "old_state", "new_state"],
)

# Severity order: higher = worse health
_SEVERITY = {"HEALTHY": 0, "UNKNOWN": 0, "DEGRADED": 1, "UNHEALTHY": 2}


def _severity(state: str) -> int:
    return _SEVERITY.get(state, 0)


@dataclass
class EntityState:
    entity_id: str
    current_state: str  # Last committed state (what SSOT has)
    derived_state: str  # Latest evaluation result
    derived_since: datetime | None  # When derived_state first differed from current
    reason: str = ""
    root_cause_entity_id: str | None = None  # Current committed root cause
    last_transition_time: datetime | None = None  # For cooldown
    transition_history: deque = field(default_factory=lambda: deque(maxlen=10))
    flapping: bool = False
    last_stable_time: datetime | None = None  # When entity was last in stable state


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

    def _is_cooldown_active(self, es: EntityState, new_state: str, now: datetime) -> bool:
        """Check if cooldown suppresses this transition.

        Cooldown only applies to de-escalation (severity decreasing).
        Escalation always fires immediately.
        """
        if es.last_transition_time is None:
            return False

        # Escalation: always allowed
        if _severity(new_state) > _severity(es.current_state):
            return False

        elapsed = (now - es.last_transition_time).total_seconds()
        return elapsed < config.COOLDOWN_SECONDS

    def _check_flapping(self, es: EntityState, now: datetime) -> bool:
        """Check if entity is flapping based on recent transition history."""
        # Prune old timestamps
        window = config.FLAP_WINDOW_SECONDS
        while es.transition_history and (
            (now - es.transition_history[0]).total_seconds() > window
        ):
            es.transition_history.popleft()

        if len(es.transition_history) > config.FLAP_THRESHOLD:
            if not es.flapping:
                logger.warning(
                    "Entity %s is flapping — %d transitions in %ds, extended debounce applied",
                    es.entity_id, len(es.transition_history), window,
                )
            es.flapping = True
            es.last_stable_time = None
            return True

        # Clear flap if stable for 5 minutes
        if es.flapping:
            if es.last_stable_time is None:
                es.last_stable_time = now
            elif (now - es.last_stable_time).total_seconds() >= 300:
                logger.info("Entity %s flap cleared — stable for 5m", es.entity_id)
                es.flapping = False
                es.last_stable_time = None

        return es.flapping

    def _record_transition(self, es: EntityState, now: datetime):
        """Record transition timestamp for flap detection and cooldown."""
        es.last_transition_time = now
        es.transition_history.append(now)
        es.last_stable_time = None  # Reset stability timer on transition

    def _fire_transition(
        self,
        es: EntityState,
        entity_type: str,
        new_state: str,
        reason: str,
        since: datetime,
        now: datetime,
        root_cause_entity_id: str | None,
    ) -> Transition:
        """Create transition, update state, record metrics."""
        transition = Transition(
            entity_id=es.entity_id,
            entity_type=entity_type,
            old_state=es.current_state,
            new_state=new_state,
            reason=reason,
            since=since,
            transition_time=now,
            root_cause_entity_id=root_cause_entity_id,
        )

        es.current_state = new_state
        es.derived_since = None
        es.root_cause_entity_id = root_cause_entity_id
        es.reason = reason
        self._record_transition(es, now)

        TRANSITIONS_COUNTER.labels(
            entity_type=entity_type,
            old_state=transition.old_state,
            new_state=transition.new_state,
        ).inc()

        logger.info(
            "Transition: %s %s -> %s root_cause=%s (reason: %s)",
            es.entity_id, transition.old_state, transition.new_state,
            root_cause_entity_id, reason,
        )
        return transition

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
        - derived_state != current_state (with debounce + cooldown), OR
        - root_cause_entity_id changed AND state is not HEALTHY (immediate)

        Cooldown: only suppresses de-escalation (severity decreasing).
        Flap detection: doubles debounce when entity oscillates rapidly.
        """
        now = datetime.now(timezone.utc)

        if entity_id not in self.entity_states:
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

        # Check for root cause change (immediate transition, no debounce/cooldown)
        if (
            derived_state == es.current_state
            and derived_state != "HEALTHY"
            and root_cause_entity_id != es.root_cause_entity_id
        ):
            transition = self._fire_transition(
                es, entity_type, derived_state, reason,
                since=now, now=now,
                root_cause_entity_id=root_cause_entity_id,
            )
            logger.info(
                "Transition (root cause change): %s root_cause=%s",
                entity_id, root_cause_entity_id,
            )
            return transition

        # Case 1: derived matches current — no transition needed, reset pending
        if derived_state == es.current_state:
            es.derived_state = derived_state
            es.derived_since = None
            es.reason = reason
            es.root_cause_entity_id = root_cause_entity_id
            # Track stability for flap clearing
            if es.flapping and es.last_stable_time is None:
                es.last_stable_time = now
            self._check_flapping(es, now)
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

        # Apply flap-doubled debounce
        effective_debounce = debounce_seconds
        is_flapping = self._check_flapping(es, now)
        if is_flapping:
            effective_debounce = debounce_seconds * 2

        elapsed = (now - es.derived_since).total_seconds()
        if elapsed < effective_debounce:
            es.reason = reason
            return None

        # Debounce expired — check cooldown (de-escalation only)
        if self._is_cooldown_active(es, derived_state, now):
            logger.debug(
                "Cooldown active for %s — suppressing %s -> %s",
                entity_id, es.current_state, derived_state,
            )
            es.reason = reason
            return None

        # Fire transition
        flap_note = " [flapping]" if is_flapping else ""
        full_reason = f"{reason}{flap_note}" if is_flapping else reason

        return self._fire_transition(
            es, entity_type, derived_state, full_reason,
            since=es.derived_since, now=now,
            root_cause_entity_id=root_cause_entity_id,
        )
