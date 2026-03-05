# Sprint Roadmap — DHS (Derived Health System)

**Goal:** Convert raw telemetry + topology into a single health state per entity, with root-cause attribution, debounced transitions, and clean event output.

**Source of truth for target state:** `documentation/progress/ARCHITECTURE_DESIRED.md`
**Source of truth for current state:** the code itself (`apps/`, `k8s/`, `rules/`)

---

## Current State

Nothing exists. Greenfield build.

---

## Sprint Sequence

```
Sprint 1     Evaluator Loop + State Engine (Core)
    │         dhs namespace, Python project structure
    │         Prometheus query client, SSOT API client
    │         Health rule loader (YAML → evaluator)
    │         Evaluator loop: query Prometheus, evaluate rules, derive state
    │         State engine: compare derived vs stored, debounce transitions
    │         SSOT writer: PUT /health_summary on transition only
    │         Deploy to k3s, verify with manual metric injection
    │
    ▼
Sprint 2     Root Cause Resolver + Event Ingestor
    │         Root cause resolution using SSOT topology (DEPENDS_ON edges)
    │         Confidence scoring (dependency vs ownership vs node vs self)
    │         K8s event ingestor (Kafka consumer for k8s-events topic)
    │         Event normalization with TTL (CrashLoop, OOM, NodeNotReady)
    │         Events enrich reason text and boost confidence
    │
    ▼
Sprint 3     Kafka Event Emitter + Transition Polish
    │         Kafka producer for health.transition.v1 topic
    │         Transition events with ownership context from SSOT
    │         Cooldown logic (no flip-back for 60s)
    │         Recovery debounce (healthy for 90s before marking HEALTHY)
    │         Flap detection and suppression
    │
    ▼
Sprint 4     Failure Scenario Validation
    │         Test: Deployment failure → UNHEALTHY, one transition only
    │         Test: Kafka outage → root cause = Kafka, dependents impacted
    │         Test: Worker CrashLoop → root cause = Worker (not Kafka)
    │         Test: Node failure → multiple deployments degrade, root = Node
    │         Test: Clean recovery → HEALTHY after debounce
    │         Test: No spam — one transition per entity per scenario
    │
    ▼
Sprint 5     CI/CD + Integration + Contract Docs
               GitHub Actions build pipeline for DHS image
               ArgoCD Application for dhs namespace
               Full integration test against live cluster
               Validate all 7 Definition of Done scenarios
               Write contract docs (DHS_CONTRACT.md)
               Handoff to Ops UI team
```

---

## Dependencies

| Sprint | Hard Dependencies | Why |
|--------|-------------------|-----|
| 1 (Evaluator + State) | **Team 3 Sprint 1** (Prometheus running), **Team 4 Sprint 1** (SSOT API with entities/health_summary) | DHS reads Prometheus metrics and writes health_summary to SSOT |
| 2 (Root Cause + Events) | Sprint 1, **Team 4 Sprint 2** (Registrar populating topology) | Root cause needs DEPENDS_ON edges from SSOT |
| 3 (Kafka Emitter) | Sprint 2, **Team 4 Sprint 3** (Ownership data in SSOT) | Transition events include ownership context |
| 4 (Failure Validation) | Sprints 1-3, **Team 2 Sprint 9** (K8s labels), **Team 3 Sprint 2** (Dashboards) | Need labeled resources and dashboards for validation |
| 5 (Integration) | Sprint 4, all teams operational | Full end-to-end validation |

---

## Dependencies on Other Teams

| What DHS Needs | Team | Status |
|----------------|------|--------|
| Prometheus running with kube-state-metrics, Kafka exporter, Postgres exporter | Team 3 Sprint 1 | ✅ Complete (all 6 sprints done) |
| SSOT API with entities, relationships, health_summary endpoints | Team 4 Sprints 1+3 | ✅ Complete (Sprint 6 done, 54 tests) |
| Registrar populating topology (CONTAINS, OWNS, DEPENDS_ON, RUNS_ON) | Team 4 Sprint 2 | ✅ Complete |
| Ownership data in SSOT | Team 4 Sprint 3 | ✅ Complete |
| K8s events exported to Loki (query via Loki API, not Kafka topic) | Team 3 Sprint 5 | ✅ Complete (events in Loki, label `source="k8s-events"`) |
| K8s labels on Team 2 resources | Team 2 Sprint 9 | ✅ Complete |

---

## What Each Sprint Unlocks

| After Sprint | Platform Can... |
|--------------|-----------------|
| 1 | Evaluate health for every entity on a loop, write transitions to SSOT |
| 2 | Attribute root cause using topology, ingest K8s events for enrichment |
| 3 | Emit health.transition events to Kafka for alerting/actions |
| 4 | Survive all failure scenarios cleanly (no spam, correct root cause) |
| 5 | Full integration validated, contract docs ready for Ops UI |

---

## Definition of Done Mapping

| Criterion | Sprint |
|-----------|--------|
| Deployment failure → UNHEALTHY, one transition | Sprint 4 |
| Kafka outage → root cause = Kafka | Sprint 4 |
| Worker CrashLoop → root cause = Worker | Sprint 4 |
| Node failure → root cause = Node | Sprint 4 |
| Clean recovery → HEALTHY after debounce | Sprint 4 |
| No spam — one transition per entity | Sprint 4 |
| health.transition events on Kafka with ownership | Sprint 3 (validated Sprint 4) |
