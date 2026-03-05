# Sprint 3 Review — Kafka Event Emitter + Transition Polish

**Sprint:** 3
**Date:** 2026-03-05
**Status:** Complete

## Objective

Emit health transition events to Kafka for downstream consumers (alerting, Ops UI), add cooldown to prevent de-escalation flip-back, and add flap detection to suppress oscillating entities.

## What We Shipped

- **1 new Python module** — kafka_emitter.py
- **5 modified files** — evaluator.py, main.py, state_engine.py, ssot_client.py, config.py
- **1 updated dependency** — aiokafka==0.11.0 added to requirements.txt
- **1 K8s manifest update** — deployment.yaml (5 new env vars)
- **4 new E2E tests** — test_transitions.py (all passing)

### Components Delivered

| Component | File | What It Does |
|-----------|------|-------------|
| Kafka Emitter | `kafka_emitter.py` | AIOKafka producer, publishes health.transition.v1 events with ownership context |
| Cooldown Logic | `state_engine.py` | Suppresses de-escalation for 60s after last transition. Escalation always fires immediately. |
| Flap Detection | `state_engine.py` | Tracks transitions in deque(maxlen=10), doubles debounce when >3 transitions in 600s window |
| Ownership Lookup | `ssot_client.py` | `get_ownership()` method to enrich events with team/tier/contact |
| Evaluator (updated) | `evaluator.py` | Emits Kafka event after SSOT write, caches ownership per cycle |

## Key Metrics

| Metric | Value |
|--------|-------|
| Entities evaluated per cycle | ~75 |
| E2E tests passing | 15/15 (6 Sprint 1 + 5 Sprint 2 + 4 Sprint 3) |
| Kafka events emitted | 1 (verified via topic consumption) |
| `dhs_transition_events_emitted_total` | 1.0 |
| Cooldown window | 60s (de-escalation only) |
| Flap threshold | 3 transitions in 600s |

## Kafka Event Payload (verified)

```json
{
  "entity_id": "k8s:lab:argocd:Deployment:argocd-applicationset-controller",
  "entity_type": "Deployment",
  "entity_name": "argocd-applicationset-controller",
  "old_state": "HEALTHY",
  "new_state": "UNHEALTHY",
  "since": "2026-03-05T18:53:40.165360+00:00",
  "transition_time": "2026-03-05T18:54:44.804983+00:00",
  "root_cause_entity_id": "k8s:lab:argocd:Deployment:argocd-applicationset-controller",
  "root_cause_entity_name": "argocd-applicationset-controller",
  "confidence": 0.5,
  "reason": "Deployment argocd-applicationset-controller has 0 available replicas for >60s",
  "owner_team": "unknown",
  "tier": "tier-3",
  "contact": {},
  "event_id": "fceec530-ad9a-4da7-a57f-9f7c3510323f",
  "schema_version": "v1"
}
```

## Incidents & Fixes During Rollout

- **Kafka cross-namespace connectivity**: Kafka's advertised listener was `PLAINTEXT://kafka:9092` (short name). DHS in the `dhs` namespace could not resolve the short name. Fix: patched Kafka StatefulSet with FQDN `kafka.calculator.svc.cluster.local:9092` (manager-approved hotfix).
- **Kafka topic creation**: `kafka-topics.sh` was not in $PATH; located at `/opt/kafka/bin/kafka-topics.sh`.

## Architecture Before & After

**Before (Sprint 2):**
```
DHS → Prometheus → derive state
    → SSOT topology → resolve root cause
    → Loki → enrich reason
    → debounce → write SSOT
    (no Kafka output, no cooldown, no flap detection)
```

**After (Sprint 3):**
```
DHS → Prometheus → derive state
    → SSOT topology → resolve root cause
    → Loki → enrich reason
    → debounce (2x if flapping)
    → cooldown check (de-escalation only)
    → write SSOT
    → emit Kafka event (health.transition.v1) with ownership context
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Cooldown only suppresses de-escalation | Manager decision. Escalation must always fire immediately for safety. Uses `_severity()` helper: HEALTHY(0) < DEGRADED(1) < UNHEALTHY(2). |
| Flap detection uses deque(maxlen=10) | Bounded memory. Timestamps pruned by window. >3 transitions in 600s = flapping = 2x debounce. |
| Graceful Kafka failure | DHS continues evaluating without Kafka if connection fails at startup. Prevents Kafka outage from blocking health evaluation. |
| Kafka key = entity_id | Ensures per-entity ordering within a partition. Consumers see transitions in order for each entity. |
| Ownership cached per eval cycle | Avoids repeated SSOT calls for the same entity within one cycle. Cache cleared at start of each cycle. |
| Two-tier E2E testing | Tier 1: HTTP metric assertions (CI-safe, runs from Windows). Tier 2: Kafka content verification (manual, via kubectl exec). |

## What We Didn't Do (and why)

- **Alertmanager integration** — Sprint 4+ scope. Kafka events are published but no consumer routes them to alerts yet.
- **Ownership data backfill** — SSOT `/ownership/{entity_id}` returns empty for most entities. Events use defaults (`owner_team: "unknown"`, `tier: "tier-3"`). This is expected until Team 4 populates ownership data.
- **Flap notification to Ops UI** — Flapping entities are logged and get extended debounce, but no separate notification channel exists yet.

## Completion Checklist

- [x] Kafka producer publishes health.transition.v1 events
- [x] Event payload matches contract (entity, state, root_cause, ownership, schema_version)
- [x] Cooldown suppresses de-escalation only (escalation always fires)
- [x] Flap detection with deque(maxlen=10) and 2x debounce multiplier
- [x] Graceful Kafka failure (DHS continues without Kafka)
- [x] `dhs_transition_events_emitted_total` metric exposed
- [x] Ownership lookup from SSOT with per-cycle caching
- [x] K8s deployment updated with KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC, COOLDOWN_SECONDS, FLAP_WINDOW_SECONDS, FLAP_THRESHOLD
- [x] Kafka topic `health.transition.v1` created (1 partition, replication-factor 1)
- [x] 15/15 E2E tests passing
- [x] Version bumped to 0.3.0
- [x] ROADMAP.md updated

## What's Next

Sprint 4: Failure Scenario Validation
- Test: Deployment failure → UNHEALTHY, one transition only
- Test: Kafka outage → root cause = Kafka, dependents impacted
- Test: Worker CrashLoop → root cause = Worker (not Kafka)
- Test: Node failure → multiple deployments degrade, root = Node
- Test: Clean recovery → HEALTHY after debounce
- Test: No spam — one transition per entity per scenario
