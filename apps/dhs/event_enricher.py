"""K8s event enrichment via Loki — queries recent K8s events for root cause enrichment."""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from prometheus_client import Counter

import config

logger = logging.getLogger("dhs.event_enricher")

EVENTS_INGESTED = Counter(
    "dhs_events_ingested_total",
    "K8s events ingested from Loki",
    ["event_type"],
)

# K8s event reason → normalized signal + TTL
SIGNAL_MAP = {
    "CrashLoopBackOff": ("crash_loop", 5),
    "OOMKilled": ("oom_killed", 5),
    "NodeNotReady": ("node_not_ready", 10),
    "ImagePullBackOff": ("image_pull_fail", 5),
    "ErrImagePull": ("image_pull_fail", 5),
    "FailedScheduling": ("scheduling_failed", 5),
}


@dataclass
class K8sEvent:
    reason: str
    message: str
    namespace: str
    involved_object: str
    timestamp: datetime
    signal: str
    ttl_minutes: int


def pod_name_to_deployment(pod_name: str) -> str:
    """Strip ReplicaSet hash and pod hash suffixes from pod name.

    api-7f8b9c6d4-x2k9m → api
    worker-5b4c8d7f6-abc12 → worker
    """
    # Pod names: <deployment>-<rs-hash>-<pod-hash>
    # RS hash is typically 8-10 alphanumeric chars
    # Pod hash is typically 5 alphanumeric chars
    match = re.match(r"^(.+)-[a-z0-9]{8,10}-[a-z0-9]{5}$", pod_name)
    if match:
        return match.group(1)
    # Fallback: try stripping just one suffix (StatefulSet pods: name-0)
    match = re.match(r"^(.+)-[a-z0-9]+$", pod_name)
    if match:
        return match.group(1)
    return pod_name


class EventEnricher:
    def __init__(self, loki_url: str | None = None):
        self.loki_url = loki_url or config.LOKI_URL
        self._client = httpx.AsyncClient(
            base_url=self.loki_url,
            timeout=config.LOKI_QUERY_TIMEOUT,
        )

    async def get_recent_events(
        self, namespace: str, minutes: int = 10,
    ) -> list[K8sEvent]:
        """Query Loki for recent K8s events in a namespace.

        Uses query_range API with nanosecond timestamps.
        Only returns events with recognized signals within TTL.
        """
        now_ns = str(int(time.time())) + "000000000"
        start_ns = str(int(time.time()) - minutes * 60) + "000000000"

        logql = f'{{source="k8s-events"}} | json | namespace="{namespace}"'

        try:
            resp = await self._client.get(
                "/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "start": start_ns,
                    "end": now_ns,
                    "limit": "200",
                },
            )
            if resp.status_code != 200:
                logger.warning("Loki query failed: %d", resp.status_code)
                return []

            data = resp.json()
            if data.get("status") != "success":
                logger.warning("Loki query non-success: %s", data)
                return []

            return self._parse_events(data)

        except httpx.TimeoutException:
            logger.warning("Loki query timed out for namespace=%s", namespace)
            return []
        except httpx.HTTPError as e:
            logger.error("Loki query error: %s", e)
            return []

    def _parse_events(self, loki_response: dict) -> list[K8sEvent]:
        """Parse Loki query_range response into K8sEvent objects."""
        events = []
        now = datetime.now(timezone.utc)

        for stream in loki_response.get("data", {}).get("result", []):
            for ts_ns, log_line in stream.get("values", []):
                try:
                    evt = json.loads(log_line)
                except (json.JSONDecodeError, TypeError):
                    continue

                reason = evt.get("reason", "")
                if reason not in SIGNAL_MAP:
                    continue

                signal, ttl = SIGNAL_MAP[reason]

                # Parse timestamp from log entry
                ts_seconds = int(ts_ns) / 1_000_000_000
                event_time = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)

                # Check TTL
                age_minutes = (now - event_time).total_seconds() / 60
                if age_minutes > ttl:
                    continue

                # Extract involved object
                involved = evt.get("involvedObject", {})
                obj_name = involved.get("name", "")
                obj_kind = involved.get("kind", "")

                # Normalize pod name to deployment name
                entity_name = obj_name
                if obj_kind == "Pod":
                    entity_name = pod_name_to_deployment(obj_name)

                k8s_event = K8sEvent(
                    reason=reason,
                    message=evt.get("message", ""),
                    namespace=evt.get("namespace", involved.get("namespace", "")),
                    involved_object=entity_name,
                    timestamp=event_time,
                    signal=signal,
                    ttl_minutes=ttl,
                )
                events.append(k8s_event)
                EVENTS_INGESTED.labels(event_type=signal).inc()

        logger.debug("Parsed %d relevant K8s events from Loki", len(events))
        return events

    async def close(self):
        await self._client.aclose()
