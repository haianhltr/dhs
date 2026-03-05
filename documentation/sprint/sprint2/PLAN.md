# Sprint 2 — Root Cause Resolver + Event Enrichment

**Goal:** Add topology-based root cause attribution and K8s event enrichment. After this sprint, every non-HEALTHY entity gets a `root_cause_entity_id` with confidence score, and K8s events (CrashLoopBackOff, OOMKilled) enrich the reason text and boost confidence.

**Status:** Complete
**Depends on:** Sprint 1 complete, Team 4 Sprint 2 (Registrar populating topology — ✅ complete)

---

## Pre-Sprint State

- DHS evaluator loop running, writing health_summary to SSOT on transitions
- No root cause attribution — `root_cause_entity_id` is always null
- No K8s event awareness

## Post-Sprint State

- Root cause resolver traverses SSOT topology (DEPENDS_ON, OWNS, RUNS_ON edges)
- `root_cause_entity_id` and `confidence` populated in every health_summary write
- K8s events queried from Loki enrich reason text and boost confidence
- Event signals have TTL (auto-expire after 5–10 minutes)

---

## Milestones

### Milestone 1 — Root cause resolver module

**Status:** [ ] Not Started

**`apps/dhs/root_cause.py`:**
- `class RootCauseResolver`:
  - `__init__(ssot_client)`
  - `async def resolve(entity_id: str, entity_type: str, derived_state: str, current_health_map: dict) -> RootCause`
    - If entity is HEALTHY → return `RootCause(entity_id=None, confidence=1.0, reason=None)`
    - Resolution chain (first match wins):
      1. **Dependency check:** Query SSOT for `DEPENDS_ON` edges from this entity. If any dependency is UNHEALTHY in `current_health_map` → root cause = that dependency, confidence 0.80–0.95
      2. **Ownership check:** If entity is a Service, query SSOT for `OWNS` edges. If the owning Deployment is UNHEALTHY → root cause = Deployment, confidence 0.70–0.90
      3. **Node check:** Query SSOT for `RUNS_ON` edge. If the Node is UNHEALTHY and multiple entities on that Node are failing → root cause = Node, confidence 0.60–0.80
      4. **Self:** No external cause found → root cause = entity itself, confidence 0.40–0.70

- `@dataclass RootCause`:
  ```python
  entity_id: str | None      # root cause entity ID
  entity_name: str | None     # human-readable name
  confidence: float           # 0.0–1.0
  reason_suffix: str | None   # appended to reason text
  ```

- Confidence calculation:
  - Base confidence from resolution tier (see above)
  - +0.05 if multiple signals confirm (e.g., both error rate and latency degraded)
  - Cap at 0.95

**Files to create:**
- `apps/dhs/root_cause.py`

**Verification:**
```python
# Unit test with mocked SSOT topology
resolver = RootCauseResolver(mock_ssot)
result = await resolver.resolve("k8s:lab:calculator:Service:api", "Service", "UNHEALTHY", health_map)
assert result.entity_id == "k8s:lab:calculator:Deployment:api"
assert result.confidence >= 0.70
```

---

### Milestone 2 — Integrate root cause into evaluator

**Status:** [ ] Not Started

**Modify `apps/dhs/evaluator.py`:**
- After deriving health state for an entity, call `root_cause_resolver.resolve()`
- Pass the full `current_health_map` (entity_id → current state) to the resolver
  - Build this map at the start of each evaluation cycle from SSOT
- Include `root_cause_entity_id`, `root_cause_entity_name`, and `confidence` in the `put_health_summary` payload
- Update reason text: append root cause info (e.g., "Root cause: Kafka broker down")

**Modify `apps/dhs/state_engine.py`:**
- Add `root_cause_entity_id` to `EntityState` and `Transition` dataclasses
- A transition fires when `root_cause_entity_id` changes (even if `health_state` stays the same)

**Files to modify:**
- `apps/dhs/evaluator.py`
- `apps/dhs/state_engine.py`

**Verification:**
```bash
# Scale API deployment to 0 replicas
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=0"
# Wait 90s for debounce
# Check health_summary — should show root_cause_entity_id pointing to Deployment
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Service:api' | python3 -m json.tool"
# Restore
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=1"
```

---

### Milestone 3 — K8s event enrichment via Loki

**Status:** [ ] Not Started

> **Design note:** Team3's K8s Event Exporter ships events to Loki (label `source="k8s-events"`), not to a Kafka topic. DHS queries Loki's HTTP API for recent events rather than consuming from Kafka.

**`apps/dhs/event_enricher.py`:**
- `class EventEnricher`:
  - `__init__(loki_url: str)` — default: `http://loki.observability.svc.cluster.local:3100`
  - `async def get_recent_events(namespace: str, minutes: int = 10) -> list[K8sEvent]`
    - Query Loki: `{source="k8s-events"} | json | namespace="<namespace>"`
    - Time range: last N minutes
    - Parse JSON log lines into `K8sEvent` objects
  - `async def get_entity_events(entity_name: str, namespace: str, minutes: int = 10) -> list[K8sEvent]`
    - Query Loki: `{source="k8s-events"} |~ "<entity_name>"`

- `@dataclass K8sEvent`:
  ```python
  reason: str         # CrashLoopBackOff, OOMKilled, NodeNotReady, etc.
  message: str        # full event message
  namespace: str
  involved_object: str  # pod/deployment name
  timestamp: datetime
  signal: str         # normalized: crash_loop, oom_killed, node_not_ready, etc.
  ttl_minutes: int    # how long this signal stays active
  ```

- Signal normalization:
  | K8s Event Reason | Normalized Signal | TTL |
  |-----------------|-------------------|-----|
  | `CrashLoopBackOff` | `crash_loop` | 5 min |
  | `OOMKilled` | `oom_killed` | 5 min |
  | `NodeNotReady` | `node_not_ready` | 10 min |
  | `ImagePullBackOff` / `ErrImagePull` | `image_pull_fail` | 5 min |
  | `FailedScheduling` | `scheduling_failed` | 5 min |

- `LOKI_URL` env var added to `config.py`

**Files to create:**
- `apps/dhs/event_enricher.py`

**Files to modify:**
- `apps/dhs/config.py` (add `LOKI_URL`)
- `apps/dhs/requirements.txt` (no new deps — httpx already included)

---

### Milestone 4 — Integrate event enrichment into evaluator + root cause

**Status:** [ ] Not Started

**Modify `apps/dhs/evaluator.py`:**
- At the start of each evaluation cycle, call `event_enricher.get_recent_events()` for all relevant namespaces
- Build an `active_events` map: `entity_name → list[K8sEvent]` (only events within TTL)
- Pass `active_events` to `root_cause_resolver.resolve()`

**Modify `apps/dhs/root_cause.py`:**
- Accept `active_events` parameter in `resolve()`
- If K8s events match the entity:
  - Boost confidence by 0.10–0.15
  - Append event info to reason text (e.g., "CrashLoopBackOff detected on api-xyz pod")

**Modify `apps/dhs/state_engine.py`:**
- No changes needed (reason text already flows through)

**Files to modify:**
- `apps/dhs/evaluator.py`
- `apps/dhs/root_cause.py`

**Verification:**
```bash
# Force a CrashLoop by deploying a bad image
ssh 5560 "sudo kubectl set image deployment/api api=ghcr.io/nonexistent/image:bad -n calculator"
# Wait 2-3 minutes for CrashLoopBackOff events to appear in Loki
# Check health_summary — reason should mention CrashLoopBackOff
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Deployment:api' | python3 -m json.tool"
# Restore
ssh 5560 "sudo kubectl rollout undo deployment/api -n calculator"
```

---

### Milestone 5 — Deploy updated DHS + E2E tests

**Status:** [ ] Not Started

**Deploy:**
- Update deployment manifest env vars to include `LOKI_URL`
- Rebuild and push image
- Wait for ArgoCD sync

**E2E tests — `tests/e2e/test_root_cause.py`:**
```python
pytestmark = pytest.mark.sprint2

class TestRootCauseAttribution:
    def test_health_summary_has_root_cause_fields(self, ssot_client):
        """health_summary records should include root_cause_entity_id and confidence."""

    def test_healthy_entity_no_root_cause(self, ssot_client):
        """HEALTHY entities should have root_cause_entity_id=null."""

    def test_deployment_down_root_cause_is_deployment(self, ssot_client):
        """When Deployment has 0 replicas, Service root cause should point to Deployment."""

class TestEventEnrichment:
    def test_dhs_has_event_metrics(self, dhs_client):
        """dhs_events_ingested_total metric should exist."""

    def test_reason_includes_event_info(self, ssot_client):
        """When K8s events are present, reason text should mention the event type."""
```

**Files to create:**
- `tests/e2e/test_root_cause.py`

**Files to modify:**
- `k8s/dhs/deployment.yaml` (add LOKI_URL env var)

---

### Milestone 6 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 2 as complete
- Write `documentation/sprint/sprint2/REVIEW.md`

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Query Loki for K8s events instead of Kafka consumer | Team3 ships K8s events to Loki, not a Kafka topic. Querying Loki is simpler than adding a new Kafka sink. |
| Build health_map at start of each cycle | Avoids stale root cause data. Fresh SSOT state ensures accurate dependency resolution. |
| Event TTL (5-10 min) | K8s events are ephemeral signals. Old events should not permanently bias root cause. |
| Confidence boost capped at 0.15 per event | Events confirm but don't override metric-based assessment. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `apps/dhs/root_cause.py` | Topology-based root cause resolver |
| `apps/dhs/event_enricher.py` | K8s event enrichment via Loki queries |
| `tests/e2e/test_root_cause.py` | Sprint 2 E2E tests |
| `documentation/sprint/sprint2/REVIEW.md` | Sprint retrospective |
