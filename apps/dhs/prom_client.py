"""Prometheus instant query client for DHS."""

import logging
import math
import time

import httpx
from prometheus_client import Histogram

import config

logger = logging.getLogger("dhs.prom_client")

QUERY_DURATION = Histogram(
    "dhs_prometheus_query_duration_seconds",
    "Time to query Prometheus",
)


class PrometheusClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or config.PROMETHEUS_URL
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=config.PROMETHEUS_QUERY_TIMEOUT,
        )

    async def query_instant(self, promql: str) -> float | None:
        """Execute an instant PromQL query. Returns numeric value or None."""
        start = time.time()
        try:
            resp = await self._client.get(
                "/api/v1/query",
                params={"query": promql},
            )
            duration = time.time() - start
            QUERY_DURATION.observe(duration)

            if resp.status_code != 200:
                logger.warning(
                    "Prometheus query failed: status=%d query=%s",
                    resp.status_code, promql,
                )
                return None

            data = resp.json()
            if data.get("status") != "success":
                logger.warning(
                    "Prometheus query non-success: %s",
                    data.get("error", "unknown"),
                )
                return None

            result = data.get("data", {}).get("result", [])
            if not result:
                logger.debug("Prometheus query returned empty result: %s", promql)
                return None

            value = float(result[0]["value"][1])

            if math.isnan(value) or math.isinf(value):
                logger.debug("Prometheus returned NaN/Inf for query: %s", promql)
                return None

            return value

        except httpx.TimeoutException:
            QUERY_DURATION.observe(time.time() - start)
            logger.warning("Prometheus query timed out: %s", promql)
            return None
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            QUERY_DURATION.observe(time.time() - start)
            logger.warning("Prometheus query error: %s query=%s", e, promql)
            return None

    async def close(self):
        await self._client.aclose()
