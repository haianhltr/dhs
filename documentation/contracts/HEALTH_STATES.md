# Contract: Health State Definitions

**Owner:** team5 (DHS)
**Consumers:** team6 (Actions UI displays these states), team4 (SSOT stores them), engineers (operational reference)

---

## Health States

| State | Value | Meaning |
|-------|-------|---------|
| `HEALTHY` | Green | All signals within thresholds, no anomalies detected |
| `DEGRADED` | Yellow | Service is functional but performance is degraded. SLOs are at risk but not breached. |
| `UNHEALTHY` | Red | Service is failing, unreachable, or has breached critical thresholds. |
| `UNKNOWN` | Gray | DHS has not yet evaluated this entity, or required signals are unavailable. |

---

## State Transition Rules

### HEALTHY → DEGRADED
Triggered when:
- p99 latency is above SLO threshold for > 5 minutes
- Kafka consumer lag is above 100 for > 5 minutes
- Available replicas < desired replicas for > 1 minute (but at least 1 replica available)

### DEGRADED → UNHEALTHY
Triggered when:
- Error rate > 5% for > 2 minutes (API)
- Failure rate > 10% for > 3 minutes (Worker)
- Available replicas == 0 for > 60 seconds
- Service unreachable (dependency down for > 60 seconds)
- Kafka brokers < 1 for > 2 minutes
- Postgres unreachable for > 60 seconds

### HEALTHY → UNHEALTHY (direct)
Triggered when signals cross critical thresholds immediately:
- 0 available replicas (deployment fully down)
- Critical dependency UNHEALTHY (Kafka, Postgres)
- Node NotReady for > 60 seconds

### Any state → HEALTHY (recovery)
- All signals within thresholds
- Recovery debounce: condition must hold for **90 seconds** before DHS marks HEALTHY
  (longer than the degradation threshold to prevent flapping)

### Cooldown
After any transition, DHS will not flip back for **60 seconds** minimum.
Exception: UNHEALTHY → HEALTHY requires the full 90s recovery debounce regardless of cooldown.

---

## Debounce Settings

| Direction | Duration | Purpose |
|-----------|----------|---------|
| HEALTHY → DEGRADED | 60s | Avoid noise from brief spikes |
| DEGRADED → UNHEALTHY | 60–180s (rule-dependent) | Confirm sustained failure |
| Any → HEALTHY | 90s | Confirm stable recovery |

---

## Root Cause Attribution

DHS assigns `root_cause_entity_id` and `confidence` for non-HEALTHY states:

| Scenario | Root Cause | Confidence Range |
|----------|-----------|-----------------|
| Dependency (Kafka/Postgres) UNHEALTHY | That dependency | 0.80 – 0.95 |
| Service's own Deployment unhealthy | That Deployment | 0.70 – 0.90 |
| Multiple entities failing on same Node | That Node | 0.60 – 0.80 |
| No clear external cause | The entity itself | 0.40 – 0.70 |

K8s events (CrashLoopBackOff, OOMKilled) increase confidence by 0.1–0.15 and enrich the `reason` text.

---

## Evaluation Frequency

| Setting | Value |
|---------|-------|
| Evaluation interval | 30 seconds (configurable via `EVAL_INTERVAL_SECONDS`) |
| Prometheus query window | 5 minutes (`[5m]` range vectors) |
| Max entities per cycle | All registered entities in SSOT |

---

## What DHS Does NOT Do

- DHS does NOT page anyone (that's Alertmanager / future integrations)
- DHS does NOT take remediation actions (that's Actions team)
- DHS does NOT store history — only current state in SSOT health_summary
- DHS does NOT evaluate entities not registered in SSOT
- DHS does NOT make changes to K8s resources

---

## Consistency with Alertmanager

DHS health states and Alertmanager alerts are **separate systems** that should be consistent:

| Alertmanager | DHS Equivalent |
|-------------|----------------|
| `CalculatorAPIHighErrorRate` firing | API Service → `UNHEALTHY` |
| `CalculatorAPIHighLatency` firing | API Service → `DEGRADED` |
| `CalculatorAPIDown` firing | API Service → `UNHEALTHY`, Deployment → `UNHEALTHY` |
| `PostgresDown` firing | Database entity → `UNHEALTHY`, dependent Services → `UNHEALTHY` |

DHS states are richer because they include root cause, ownership context, and confidence — making them the source of truth for the Ops UI.
