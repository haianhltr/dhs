"""DHS — Derived Health System service entrypoint."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger

import config
from prom_client import PrometheusClient
from ssot_client import SSOTClient
from rule_loader import load_rules
from state_engine import StateEngine
from evaluator import Evaluator

# --- Structured JSON logging ---
handler = logging.StreamHandler()
handler.setFormatter(
    jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
)
logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)

logger = logging.getLogger("dhs")

# --- Globals ---
start_time = time.time()
evaluator: Evaluator | None = None
eval_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global evaluator, eval_task

    rule_files = load_rules(config.RULES_DIR)
    logger.info("Loaded %d rule files", len(rule_files))

    prometheus = PrometheusClient()
    ssot = SSOTClient()
    state_engine = StateEngine()

    evaluator = Evaluator(prometheus, ssot, rule_files, state_engine)
    eval_task = asyncio.create_task(evaluator.run_loop())
    logger.info(
        "DHS started — evaluator loop every %ds", config.EVAL_INTERVAL_SECONDS
    )

    yield

    if eval_task:
        eval_task.cancel()
        try:
            await eval_task
        except asyncio.CancelledError:
            pass
    await prometheus.close()
    await ssot.close()
    logger.info("DHS shutdown complete")


app = FastAPI(title="DHS", version="0.1.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {
        "service": "dhs",
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - start_time, 1),
        "eval_count": evaluator.eval_count if evaluator else 0,
    }


@app.get("/health")
async def health():
    if evaluator and evaluator.eval_count > 0:
        return {"status": "ok", "eval_count": evaluator.eval_count}
    return Response(
        content='{"status": "starting"}',
        status_code=503,
        media_type="application/json",
    )


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
