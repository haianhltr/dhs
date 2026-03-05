# Contract: Kafka Event Schema

**Owner:** team5 (DHS)
**Consumers:** team6 (Actions service consumes these)
**Topic:** `health.transition.v1`
**Kafka:** `kafka.calculator:9092` (in-cluster)
**Consumer group (Actions):** `actions-consumer-group`

---

## When Events Are Emitted

DHS emits an event to `health.transition.v1` **only when a health state transition occurs**:
- Entity state changes (any direction)
- Root cause entity changes (even if state is the same)

DHS does NOT emit an event every evaluation cycle. One real transition = one event.

---

## Event Schema

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
  "root_cause_entity_name": "api",
  "confidence": 0.85,
  "reason": "API error rate 12% > 5% threshold for >2m. CrashLoopBackOff detected on api pod.",
  "owner_team": "app-team",
  "tier": "tier-2",
  "contact": {
    "slack": "#app-oncall"
  },
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "schema_version": "v1"
}
```

---

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | string | Yes | SSOT entity ID of the affected entity |
| `entity_type` | string | Yes | Entity type: `Service`, `Deployment`, `Kafka`, `Database`, `Node`, etc. |
| `entity_name` | string | Yes | Short human-readable entity name |
| `old_state` | enum | Yes | Previous health state |
| `new_state` | enum | Yes | New health state |
| `since` | ISO 8601 timestamp | Yes | When the new state condition first appeared (before debounce) |
| `transition_time` | ISO 8601 timestamp | Yes | When DHS actually fired the transition (after debounce) |
| `root_cause_entity_id` | string (nullable) | No | SSOT entity ID of the root cause, if known |
| `root_cause_entity_name` | string (nullable) | No | Short name of root cause entity |
| `confidence` | float 0–1 | Yes | Confidence in root cause attribution |
| `reason` | string | Yes | Human-readable explanation with metric values |
| `owner_team` | string | Yes | Team that owns the affected entity (from SSOT) |
| `tier` | string | Yes | `tier-1`, `tier-2`, `tier-3` |
| `contact` | JSON object | Yes | Contact info from SSOT: `{"slack": "...", "email": "..."}` |
| `event_id` | UUID string | Yes | Unique event ID for deduplication |
| `schema_version` | string | Yes | Always `v1` for this schema |

---

## State Enum Values

`old_state` and `new_state` are one of: `HEALTHY`, `DEGRADED`, `UNHEALTHY`, `UNKNOWN`

---

## Kafka Message Format

| Property | Value |
|----------|-------|
| Key | `entity_id` (string) — enables ordering per entity |
| Value | JSON string (UTF-8) |
| Headers | `event_type: health.transition`, `schema_version: v1` |
| Serialization | JSON |
| Compression | None (MVP), snappy (production) |

---

## Common Transition Scenarios

| Scenario | `old_state` | `new_state` | `entity_type` | Root cause |
|----------|------------|------------|---------------|------------|
| API crash | `HEALTHY` | `UNHEALTHY` | `Service` | `Deployment` |
| Kafka down | `HEALTHY` | `UNHEALTHY` | `Kafka` | `Kafka` itself |
| API degraded (latency) | `HEALTHY` | `DEGRADED` | `Service` | `Service` itself |
| API recovers | `UNHEALTHY` | `HEALTHY` | `Service` | null |
| Node goes down | `HEALTHY` | `UNHEALTHY` | `Node` | `Node` itself |
| Worker affected by Kafka | `HEALTHY` | `UNHEALTHY` | `Service` | `Kafka` entity |

---

## How Team 6 Uses This

1. Actions service subscribes to `health.transition.v1` with consumer group `actions-consumer-group`
2. For each event:
   - Store as a pending recommendation keyed by `entity_id`
   - If `new_state == UNHEALTHY` and entity type is `Deployment`: surface "Restart" recommendation
   - If `new_state == HEALTHY`: clear recommendation for that entity
3. Use `event_id` for idempotency — ignore duplicate events
4. UI shows: "Worker is UNHEALTHY — root cause: Worker Deployment — Recommended action: Restart"
5. Auto-remediation (Phase 2) uses `reason` to match against `config/auto-remediation.yaml` triggers

---

## Delivery Guarantee

- **At-least-once delivery** — consumers must be idempotent (use `event_id` for deduplication)
- **Ordering** — events for the same entity are ordered (same Kafka partition key = `entity_id`)
- **Retention** — topic retention: 24 hours (lab), 7 days (production)
