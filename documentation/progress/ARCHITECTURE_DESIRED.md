# Desired Architecture — DHS (Derived Health System)

**Goal:** Convert raw telemetry + topology into a single health state per entity, with root-cause attribution, debounced transitions, and clean event output. DHS is the brain — it reads signals, thinks, and writes conclusions.

---

## System Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     k3s Cluster — Lenovo 5560                          │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  namespace: dhs (Team 5)                                         │    │
│  │                                                                  │    │
│  │  ┌──────────────────────────────────────────────────────┐        │    │
│  │  │              DHS Service                              │        │    │
│  │  │                                                       │        │    │
│  │  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │        │    │
│  │  │  │  Evaluator   │  │ Event        │  │ Root Cause │  │        │    │
│  │  │  │  Loop        │  │ Ingestor     │  │ Resolver   │  │        │    │
│  │  │  │  (15-60s)    │  │ (K8s events) │  │ (topology) │  │        │    │
│  │  │  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │        │    │
│  │  │         │                 │                 │         │        │    │
│  │  │  ┌──────▼─────────────────▼─────────────────▼──────┐  │        │    │
│  │  │  │          State / Transition Engine               │  │        │    │
│  │  │  │  - compare derived vs stored state               │  │        │    │
│  │  │  │  - debounce + flap control                       │  │        │    │
│  │  │  │  - write SSOT only on transition                 │  │        │    │
│  │  │  └──────┬──────────────────────────────┬───────────┘  │        │    │
│  │  │         │                              │              │        │    │
│  │  │  ┌──────▼───────┐              ┌───────▼──────────┐   │        │    │
│  │  │  │ SSOT Writer  │              │ Event Emitter    │   │        │    │
│  │  │  │ PUT /health  │              │ Kafka topic      │   │        │    │
│  │  │  │ _summary     │              │ health.transition│   │        │    │
│  │  │  └──────────────┘              └──────────────────┘   │        │    │
│  │  └───────────────────────────────────────────────────────┘        │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  READS FROM:                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐         │
│  │ Prometheus       │  │ SSOT API        │  │ K8s Event Stream │         │
│  │ :30090           │  │ :30900          │  │ (Kafka/webhook)  │         │
│  │ metrics queries  │  │ entities,       │  │ CrashLoop,       │         │
│  │ recording rules  │  │ relationships,  │  │ OOMKilled,       │         │
│  │ golden signals   │  │ ownership,      │  │ NodeNotReady     │         │
│  │                  │  │ current health  │  │                  │         │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘         │
│                                                                          │
│  WRITES TO:                                                              │
│  ┌─────────────────┐  ┌─────────────────────────────┐                    │
│  │ SSOT API        │  │ Kafka: health.transition.v1 │                    │
│  │ PUT /health     │  │ transition events with       │                    │
│  │ _summary        │  │ ownership context            │                    │
│  └─────────────────┘  └─────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## DHS Service Components

### Evaluator Loop
- Runs every 30s (configurable via `EVAL_INTERVAL_SECONDS`)
- For each entity registered in SSOT:
  1. Load the entity's health rules (from `rules/`)
  2. Query Prometheus for required signals
  3. Evaluate rules → derive health state
  4. Pass to State Engine for transition check
- Structured JSON logs with `entity_id`, `derived_state`, `reason`

### Event Ingestor
- Consumes Kubernetes events from Kafka topic `k8s-events` (or webhook)
- Normalizes events into signals with TTL:
  - `CrashLoopBackOff` → signal `crash_loop`, TTL 5min
  - `OOMKilled` → signal `oom_killed`, TTL 5min
  - `NodeNotReady` → signal `node_not_ready`, TTL 10min
  - `ImagePullBackOff` → signal `image_pull_fail`, TTL 5min
  - `FailedScheduling` → signal `scheduling_failed`, TTL 5min
- Events increase confidence and improve reason text but metrics remain the main driver

### State / Transition Engine
- Compares derived state vs current SSOT state for each entity
- A **transition** occurs when:
  - `health_state` changes, OR
  - `root_cause_entity_id` changes
- **Debounce:** condition must hold for configured duration before transition fires
- **Cooldown:** after a transition, don't flip back for 60s (configurable) unless clearly recovered
- **Recovery debounce:** require healthy for 90s before marking HEALTHY (longer than degradation threshold)

### Root Cause Resolver
- For an entity E that is DEGRADED or UNHEALTHY:
  1. Get E's dependencies from SSOT (`DEPENDS_ON` edges)
  2. If any dependency D is UNHEALTHY → root cause = D, confidence 0.8–0.95
  3. Else if E is a Service and its Deployment is DEGRADED/UNHEALTHY → root cause = Deployment, confidence 0.7–0.9
  4. Else if multiple entities failing on same Node → root cause = Node, confidence 0.6–0.8
  5. Else → root cause = E itself, confidence 0.4–0.7
- K8s events (OOMKilled, CrashLoop) increase confidence and enrich reason text

### SSOT Writer
- Writes `PUT /health_summary` to SSOT API **only on transitions**
- Payload: `entity_id`, `health_state`, `since`, `root_cause_entity_id`, `confidence`, `reason`, `last_updated_by="dhs"`
- Auth: API key or network policy (SSOT enforces write restriction)

### Event Emitter
- Publishes to Kafka topic `health.transition.v1` on each transition
- Payload includes ownership context from SSOT:
  ```json
  {
    "entity_id": "k8s:lab:calculator:Service:api",
    "entity_type": "Service",
    "entity_name": "calculator-api",
    "old_state": "HEALTHY",
    "new_state": "UNHEALTHY",
    "since": "2026-03-02T10:15:00Z",
    "transition_time": "2026-03-02T10:17:30Z",
    "root_cause_entity_id": "k8s:lab:calculator:Deployment:api",
    "confidence": 0.85,
    "reason": "API error rate 12% > 5% threshold for >2m. CrashLoopBackOff detected on api pod.",
    "owner_team": "app-team",
    "tier": "tier-2",
    "contact": {"slack": "#app-oncall"}
  }
  ```

---

## Health Rules (YAML-Defined)

Rules live in `rules/` and are loaded by the evaluator. Each rule maps an entity type to signals and thresholds.

### Rule Format

```yaml
# rules/deployment.yaml
entity_type: Deployment
rules:
  - name: replica_unavailable
    state: UNHEALTHY
    condition: "available_replicas == 0"
    duration: 60s
    promql: |
      kube_deployment_status_replicas_available{
        namespace="{{ namespace }}", deployment="{{ name }}"
      }
    threshold: 0
    operator: "=="
    reason: "Deployment {{ name }} has 0 available replicas for >60s"

  - name: replica_degraded
    state: DEGRADED
    condition: "available < desired"
    duration: 60s
    promql_desired: |
      kube_deployment_spec_replicas{
        namespace="{{ namespace }}", deployment="{{ name }}"
      }
    promql_available: |
      kube_deployment_status_replicas_available{
        namespace="{{ namespace }}", deployment="{{ name }}"
      }
    reason: "Deployment {{ name }} has {{ available }}/{{ desired }} replicas for >60s"
```

```yaml
# rules/service-api.yaml
entity_type: Service
match_labels:
  component: api
rules:
  - name: high_error_rate
    state: UNHEALTHY
    duration: 120s
    promql: |
      sum(rate(api_http_errors_total[5m])) /
      sum(rate(api_http_requests_total[5m]))
    threshold: 0.05
    operator: ">"
    reason: "API error rate {{ value }}% > 5% for >2m"

  - name: high_latency
    state: DEGRADED
    duration: 300s
    promql: |
      histogram_quantile(0.99,
        sum(rate(api_http_request_duration_seconds_bucket[5m])) by (le)
      )
    threshold: 2.0
    operator: ">"
    reason: "API p99 latency {{ value }}s > 2.0s SLO for >5m"
```

```yaml
# rules/service-worker.yaml
entity_type: Service
match_labels:
  component: worker
rules:
  - name: high_failure_rate
    state: UNHEALTHY
    duration: 180s
    promql: |
      sum(rate(worker_jobs_processed_total{status="failed"}[5m])) /
      sum(rate(worker_jobs_processed_total[5m]))
    threshold: 0.1
    operator: ">"
    reason: "Worker failure rate {{ value }}% > 10% for >3m"

  - name: high_lag
    state: DEGRADED
    duration: 300s
    promql: |
      calculator:kafka_consumer_lag
    threshold: 100
    operator: ">"
    reason: "Consumer lag {{ value }} > 100 for >5m"
```

```yaml
# rules/kafka.yaml
entity_type: Kafka
rules:
  - name: broker_down
    state: UNHEALTHY
    duration: 120s
    promql: "kafka_brokers"
    threshold: 1
    operator: "<"
    reason: "Kafka broker count {{ value }} < 1 for >2m"

# rules/database.yaml
entity_type: Database
rules:
  - name: unreachable
    state: UNHEALTHY
    duration: 60s
    promql: "pg_up"
    threshold: 1
    operator: "<"
    reason: "Postgres unreachable for >60s"

# rules/node.yaml
entity_type: Node
rules:
  - name: not_ready
    state: UNHEALTHY
    duration: 60s
    promql: |
      kube_node_status_condition{
        node="{{ name }}", condition="Ready", status="true"
      }
    threshold: 1
    operator: "<"
    reason: "Node {{ name }} not ready for >60s"
```

---

## PromQL Query Catalog

DHS uses these queries. Prefer recording rules from Observability team when available.

| Signal | Query | Source |
|--------|-------|--------|
| Deployment available replicas | `kube_deployment_status_replicas_available{ns=X, deploy=Y}` | kube-state-metrics |
| Deployment desired replicas | `kube_deployment_spec_replicas{ns=X, deploy=Y}` | kube-state-metrics |
| Node readiness | `kube_node_status_condition{node=X, condition="Ready", status="true"}` | kube-state-metrics |
| API error rate | `calculator:api_error_rate:5m` (recording rule) or raw PromQL | Prometheus |
| API p99 latency | `calculator:api_latency_p99:5m` (recording rule) or raw PromQL | Prometheus |
| Worker failure rate | `sum(rate(worker_jobs_processed_total{status="failed"}[5m])) / sum(rate(worker_jobs_processed_total[5m]))` | Worker metrics |
| Kafka consumer lag | `calculator:kafka_consumer_lag` (recording rule) or `kafka_consumergroup_lag` | Kafka exporter |
| Kafka broker count | `kafka_brokers` | Kafka exporter |
| Postgres up | `pg_up` | Postgres exporter |

---

## Kubernetes Deployment Model

| Component | Kind | Namespace | Replicas | Exposed | Notes |
|-----------|------|-----------|----------|---------|-------|
| DHS Service | Deployment | dhs | 1 | NodePort 30950 (metrics/admin) | Single instance, evaluator loop |

DHS has no database of its own — it reads from Prometheus and SSOT, writes to SSOT and Kafka.

Resource requests/limits, liveness/readiness probes required.

---

## Ports Summary

| Port | Service | Namespace |
|------|---------|-----------|
| 30950 | DHS (metrics + admin) | dhs |

---

## Prometheus Metrics (DHS Service)

| Metric | Type | Purpose |
|--------|------|---------|
| `dhs_evaluations_total` | Counter (entity_type) | Total evaluation cycles per entity type |
| `dhs_evaluation_duration_seconds` | Histogram | Time per full evaluation cycle |
| `dhs_transitions_total` | Counter (entity_type, old_state, new_state) | Health state transitions |
| `dhs_ssot_writes_total` | Counter (status) | Writes to SSOT (success/failure) |
| `dhs_prometheus_query_duration_seconds` | Histogram | PromQL query latency |
| `dhs_events_ingested_total` | Counter (event_type) | K8s events ingested |
| `dhs_transition_events_emitted_total` | Counter | Events published to Kafka |

---

## Definition of Done

DHS is done when the team can demonstrate:

1. **Deployment failure** — Scale API to 0 or break image → DHS marks Deployment UNHEALTHY, Service DEGRADED/UNHEALTHY, one transition written to SSOT (not spammed)
2. **Kafka outage** — Stop Kafka → DHS marks Kafka UNHEALTHY, marks Worker/API as impacted with root_cause = Kafka
3. **Worker crashes** — Force CrashLoop → DHS marks Worker Deployment UNHEALTHY, root cause = Worker (not Kafka, if Kafka is healthy)
4. **Node failure** — Simulate NodeNotReady → multiple deployments degrade, DHS roots to Node
5. **Clean recovery** — Restore each failure → DHS transitions back to HEALTHY after debounce period
6. **No spam** — Each scenario produces exactly one transition per affected entity (not per evaluation tick)
7. **health.transition events** — Kafka topic contains correct transition events with ownership context
