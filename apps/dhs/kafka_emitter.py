"""Kafka event emitter — publishes health.transition.v1 events on state transitions."""

import json
import logging
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from prometheus_client import Counter

import config
from state_engine import Transition
from root_cause import RootCause

logger = logging.getLogger("dhs.kafka_emitter")

EVENTS_EMITTED = Counter(
    "dhs_transition_events_emitted_total",
    "Health transition events published to Kafka",
)


class KafkaEmitter:
    def __init__(
        self,
        bootstrap_servers: str | None = None,
        topic: str | None = None,
    ):
        self.bootstrap_servers = bootstrap_servers or config.KAFKA_BOOTSTRAP_SERVERS
        self.topic = topic or config.KAFKA_TOPIC
        self._producer: AIOKafkaProducer | None = None

    async def start(self):
        """Connect to Kafka broker."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self._producer.start()
        logger.info("Kafka producer connected to %s", self.bootstrap_servers)

    async def stop(self):
        """Flush pending messages and close."""
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def emit_transition(
        self,
        transition: Transition,
        entity: dict,
        root_cause: RootCause,
        ownership: dict,
    ) -> bool:
        """Publish a transition event to Kafka. Returns True on success.

        root_cause_entity_name and confidence come from the RootCause dataclass,
        NOT from Transition. Transition only has root_cause_entity_id.
        """
        if not self._producer:
            logger.warning("Kafka producer not initialized — skipping emit")
            return False

        event_id = str(uuid4())
        payload = {
            "entity_id": transition.entity_id,
            "entity_type": entity.get("type", ""),
            "entity_name": entity.get("name", ""),
            "old_state": transition.old_state,
            "new_state": transition.new_state,
            "since": transition.since.isoformat(),
            "transition_time": transition.transition_time.isoformat(),
            "root_cause_entity_id": transition.root_cause_entity_id,
            "root_cause_entity_name": root_cause.entity_name,
            "confidence": root_cause.confidence,
            "reason": transition.reason,
            "owner_team": ownership.get("team", "unknown"),
            "tier": ownership.get("tier", "tier-3"),
            "contact": ownership.get("contact", {}),
            "event_id": event_id,
            "schema_version": "v1",
        }

        try:
            await self._producer.send_and_wait(
                self.topic,
                value=payload,
                key=transition.entity_id,
                headers=[
                    ("event_type", b"health.transition"),
                    ("schema_version", b"v1"),
                ],
            )
            EVENTS_EMITTED.inc()
            logger.info(
                "Kafka event emitted: entity=%s %s->%s event_id=%s",
                transition.entity_id,
                transition.old_state,
                transition.new_state,
                event_id,
            )
            return True
        except Exception as e:
            logger.error(
                "Kafka emit failed: entity=%s error=%s",
                transition.entity_id, e,
            )
            return False
