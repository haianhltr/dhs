# Sprint 1 Review — Evaluator Loop + State Engine (Core)

**Sprint:** 1
**Date:** 2026-03-05
**Status:** Complete

## Objective

Stand up the DHS service from scratch — evaluator loop, state engine, SSOT writer. After this sprint, DHS evaluates health for every SSOT entity on a 30s loop, debounces transitions, and writes health_summary to SSOT only on state changes.

## What We Shipped

- **9 Python source files** — config, prom_client, ssot_client, rule_loader, state_engine, evaluator, main, requirements.txt, Dockerfile
- **4 K8s manifests** — namespace, deployment, service, configmap-rules
- **GitHub Actions CI pipeline** — auto-builds and pushes image on push to main
- **GitHub repo** — `haianhltr/dhs` with all code pushed

### Components Delivered

| Component | File | What It Does |
|-----------|------|-------------|
| Config | `config.py` | All env vars with defaults |
| Prometheus Client | `prom_client.py` | Async query_instant with NaN/timeout handling |
| SSOT Client | `ssot_client.py` | GET entities, GET/PUT health_summary with X-DHS-Key auth |
| Rule Loader | `rule_loader.py` | Loads YAML rules, Jinja2 PromQL rendering, entity matching |
| State Engine | `state_engine.py` | Per-entity state tracking, debounce, transition detection |
| Evaluator | `evaluator.py` | 30s eval loop, SSOT startup seeding, entity-to-rule matching |
| Main | `main.py` | FastAPI with /, /health, /metrics endpoints |

## Key Metrics

| Metric | Value |
|--------|-------|
| Entities evaluated per cycle | 75 |
| Entity types covered | Service, Deployment, Kafka, Database, Node |
| Evaluation cycle duration | ~1.6s |
| Prometheus queries per cycle | ~71 |
| E2E tests passing | 6/6 |
| SSOT health records written | 34 |

## Incidents & Fixes During Rollout

- **No Docker Desktop**: Solved by setting up GitHub Actions CI pipeline (originally Sprint 5 scope) to build and push the image automatically.
- **No git repo existed**: Created `haianhltr/dhs` and initialized git in `team5/dhs/`.
- **sudo not available on k3s**: kubectl works without sudo — all commands adjusted.

## Architecture Before & After

**Before:** Empty directories. No namespace, no service, no code.

**After:**
```
dhs namespace (k3s)
  └── Deployment: dhs (1 replica, running)
       ├── Reads: Prometheus (prometheus.observability:9090)
       ├── Reads: SSOT API (ssot-api.ssot:8080)
       ├── Writes: SSOT PUT /health_summary (on transitions only)
       ├── Rules: 6 YAML files mounted via ConfigMap
       └── Exposes: NodePort 30950 (/, /health, /metrics)
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Named `prom_client.py` not `prometheus_client.py` | Avoids shadowing the `prometheus-client` pip package |
| Supports dual-query rule pattern | deployment.yaml needs `available < desired` comparison of two Prometheus queries |
| `match_labels.component` matches `entity.name` | Manager decision — SSOT entity name matches K8s resource name |
| Seed state from SSOT on startup | Prevents false transitions after restart |
| Rule-specific debounce via `duration` field | Per-rule control (120s for error rate, 300s for latency) vs flat global |
| GitHub Actions CI in Sprint 1 | Pulled forward from Sprint 5 — needed to build and push image without Docker Desktop |

## What We Didn't Do (and why)

- **Root cause attribution** — Sprint 2 scope. All health_summary writes have `root_cause_entity_id=null`, `confidence=0.0`.
- **Kafka event emission** — Sprint 3 scope. No transition events published to Kafka yet.
- **Cooldown / flap detection** — Sprint 3 scope. Only basic debounce is implemented.
- **ArgoCD Application** — Still Sprint 5. Using manual `kubectl apply` for now.

## Completion Checklist

- [x] `dhs` namespace exists in k3s
- [x] DHS pod running (1/1 Ready)
- [x] YAML health rules loaded from ConfigMap at startup
- [x] Evaluator loop runs every 30s
- [x] Prometheus queries return metrics for all entity types
- [x] State engine debounces transitions correctly
- [x] SSOT health_summary written only on transitions
- [x] Prometheus metrics exposed at /metrics (5 metrics)
- [x] Structured JSON logging
- [x] Health probe at /health (readiness gate on first eval cycle)
- [x] Accessible at http://192.168.1.210:30950
- [x] 6/6 E2E tests pass
- [x] GitHub Actions CI builds and pushes image

## What's Next

Sprint 2: Root Cause Resolver + Event Ingestor
- Root cause resolution using SSOT topology (DEPENDS_ON edges)
- Confidence scoring (dependency vs ownership vs node vs self)
- K8s event enrichment via Loki queries
