# Sprint 2 Review — Root Cause Resolver + Event Enrichment

**Sprint:** 2
**Date:** 2026-03-05
**Status:** Complete

## Objective

Add topology-based root cause attribution and K8s event enrichment. Every non-HEALTHY entity now gets a `root_cause_entity_id` with confidence score, and K8s events (CrashLoopBackOff, OOMKilled) enrich the reason text and boost confidence.

## What We Shipped

- **2 new Python modules** — root_cause.py, event_enricher.py
- **5 modified files** — ssot_client.py, config.py, state_engine.py, evaluator.py, main.py
- **1 K8s manifest update** — deployment.yaml (LOKI_URL env var)
- **5 new E2E tests** — test_root_cause.py (all passing)

### Components Delivered

| Component | File | What It Does |
|-----------|------|-------------|
| Root Cause Resolver | `root_cause.py` | Traverses SSOT topology (DEPENDS_ON, OWNS, RUNS_ON) to attribute root cause |
| Event Enricher | `event_enricher.py` | Queries Loki for K8s events, normalizes signals with TTL |
| SSOT Client (updated) | `ssot_client.py` | Added `get_relationships()` for topology queries |
| State Engine (updated) | `state_engine.py` | Tracks root_cause_entity_id, fires immediate transition on root cause change |
| Evaluator (updated) | `evaluator.py` | Builds health_map from SSOT, queries Loki for events, integrates root cause |

## Key Metrics

| Metric | Value |
|--------|-------|
| Entities evaluated per cycle | 75 |
| Evaluation cycle duration | ~2.5s (up from ~1.6s due to topology queries) |
| E2E tests passing | 11/11 (6 Sprint 1 + 5 Sprint 2) |
| SSOT health records with root cause | All UNHEALTHY entities |
| Confidence range | 0.5 (self) to 0.95 (dependency + events) |

## Incidents & Fixes During Rollout

- **Version string mismatch**: Root endpoint had hardcoded "0.1.0" while FastAPI app had "0.2.0". Fixed with follow-up commit.
- **Loki instant query returns empty**: Had to use `query_range` API with nanosecond timestamps instead of `query` endpoint.

## Architecture Before & After

**Before (Sprint 1):**
```
DHS → Prometheus → derive state → debounce → write SSOT
                                  root_cause_entity_id = null
                                  confidence = 0.0
```

**After (Sprint 2):**
```
DHS → Prometheus → derive state
    → SSOT topology (DEPENDS_ON, OWNS, RUNS_ON) → resolve root cause
    → Loki (K8s events) → enrich reason + boost confidence
    → debounce → write SSOT with root_cause + confidence
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Query Loki for K8s events (not Kafka) | Team3 ships events to Loki with `source="k8s-events"` label. Simpler than adding Kafka consumer. |
| Root cause changes fire immediately (no debounce) | Manager decision. Debouncing root cause adds complexity with no practical benefit. Eval interval (30s) provides natural rate-limiting. |
| Build health_map from SSOT each cycle | Fresh authoritative data. 35 records is trivial overhead. Better than stale in-memory state after restarts. |
| Pod name → Deployment: strip last 2 suffixes | Pod names follow `<deployment>-<rs-hash>-<pod-hash>`. Regex strips both hashes to match entity name. |
| Use `query_range` not `query` for Loki | Loki `query` (instant) returned empty from within the DHS pod. `query_range` with explicit nanosecond timestamps works reliably. |

## What We Didn't Do (and why)

- **Cooldown / flap detection** — Sprint 3 scope. Only basic debounce is implemented.
- **Kafka event emission** — Sprint 3 scope. No transition events published to Kafka yet.
- **Multi-signal confidence boost** — Simplified to single +0.05 for multiple UNHEALTHY dependencies. Event boost is +0.10.

## Completion Checklist

- [x] Root cause resolver traverses SSOT topology
- [x] Confidence scoring: dependency (0.85), ownership (0.75-0.85), node (0.70), self (0.50)
- [x] K8s event enrichment via Loki with TTL-based filtering
- [x] State engine fires transitions on root_cause change
- [x] health_summary includes root_cause_entity_id and confidence
- [x] LOKI_URL configurable via env var
- [x] dhs_events_ingested_total metric exposed
- [x] 11/11 E2E tests passing
- [x] ROADMAP.md updated
- [x] Version bumped to 0.2.0

## What's Next

Sprint 3: Kafka Event Emitter + Transition Polish
- Kafka producer for health.transition.v1 topic
- Transition events with ownership context from SSOT
- Cooldown logic (no flip-back for 60s)
- Flap detection and suppression
