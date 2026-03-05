"""SSOT API client for DHS — reads entities/health, writes health_summary."""

import logging

import httpx
from prometheus_client import Counter

import config

logger = logging.getLogger("dhs.ssot_client")

SSOT_WRITES = Counter(
    "dhs_ssot_writes_total",
    "SSOT health_summary writes",
    ["status"],
)


class SSOTClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = base_url or config.SSOT_API_URL
        self.api_key = api_key or config.DHS_API_KEY
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10)

    async def get_entities(self, entity_type: str | None = None) -> list[dict]:
        """GET /entities with optional type filter."""
        params = {}
        if entity_type:
            params["type"] = entity_type
        try:
            resp = await self._client.get("/entities", params=params)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("get_entities failed: %d", resp.status_code)
            return []
        except httpx.HTTPError as e:
            logger.error("get_entities error: %s", e)
            return []

    async def get_health_summary_all(self) -> list[dict]:
        """GET /health_summary — all health records (for startup seeding)."""
        try:
            resp = await self._client.get("/health_summary")
            if resp.status_code == 200:
                return resp.json()
            return []
        except httpx.HTTPError as e:
            logger.error("get_health_summary_all error: %s", e)
            return []

    async def get_relationships(
        self,
        source_entity_id: str | None = None,
        rel_type: str | None = None,
    ) -> list[dict]:
        """GET /relationships with optional source_entity_id and type filters."""
        params = {}
        if source_entity_id:
            params["source_entity_id"] = source_entity_id
        if rel_type:
            params["type"] = rel_type
        try:
            resp = await self._client.get("/relationships", params=params)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("get_relationships failed: %d", resp.status_code)
            return []
        except httpx.HTTPError as e:
            logger.error("get_relationships error: %s", e)
            return []

    async def put_health_summary(self, payload: dict) -> bool:
        """PUT /health_summary with X-DHS-Key auth header."""
        try:
            resp = await self._client.put(
                "/health_summary",
                json=payload,
                headers={"X-DHS-Key": self.api_key},
            )
            if resp.status_code == 200:
                SSOT_WRITES.labels(status="success").inc()
                logger.info(
                    "Health summary written: entity=%s state=%s",
                    payload.get("entity_id"),
                    payload.get("health_state"),
                )
                return True
            SSOT_WRITES.labels(status="failure").inc()
            logger.warning(
                "put_health_summary failed: %d %s",
                resp.status_code, resp.text,
            )
            return False
        except httpx.HTTPError as e:
            SSOT_WRITES.labels(status="failure").inc()
            logger.error("put_health_summary error: %s", e)
            return False

    async def close(self):
        await self._client.aclose()
