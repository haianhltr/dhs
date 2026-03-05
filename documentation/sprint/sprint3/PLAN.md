# Sprint 3 — Kafka Event Emitter + Transition Polish

**Goal:** Add Kafka event emission for health transitions and polish the transition engine with cooldown, recovery debounce, and flap detection. After this sprint, team6 can consume `health.transition.v1` events from Kafka.

**Status:** Not Started
**Depends on:** Sprint 2 complete, Team 4 Sprint 3 (ownership data in SSOT — ✅ complete)

---

## Pre-Sprint State

- DHS evaluator running with root cause attribution and event enrichment
- Health transitions written to SSOT only
- No Kafka event emission — team6 has no data to consume
- Basic debounce exists (Sprint 1) but no cooldown or flap detection

## Post-Sprint State

- `health.transition.v1` Kafka events emitted on every transition
- Events include ownership context from SSOT (owner_team, tier, contact)
- Cooldown: no flip-back for 60s after a transition
- Recovery debounce: healthy for 90s before marking HEALTHY (already in Sprint 1 config, enforce in code)
- Flap detection: suppress rapid state oscillations
- Team6 unblocked — can begin consuming events

---

## Milestones

### Milestone 1 — Kafka producer module

**Status:** [ ] Not Started

**`apps/dhs/kafka_emitter.py`:**
- `class KafkaEmitter`:
  - `__init__(bootstrap_servers: str, topic: str)`
  - Uses `aiokafka.AIOKafkaProducer`
  - `async def start()` — connect to Kafka
  - `async def stop()` — flush and close
  - `async def emit_transition(transition: Transition, entity: dict, root_cause: RootCause, ownership: dict) -> bool`
    - Import `RootCause` from `root_cause.py`
    - Build event payload per `KAFKA_EVENTS.md` contract:
      ```python
      {
          "entity_id": transition.entity_id,
          "entity_type": entity["type"],
          "entity_name": entity["name"],
          "old_state": transition.old_state,
          "new_state": transition.new_state,
          "since": transition.since.isoformat(),
          "transition_time": transition.transition_time.isoformat(),
          "root_cause_entity_id": transition.root_cause_entity_id,
          "root_cause_entity_name": root_cause.entity_name,
          "confidence": root_cause.confidence,
          "reason": transition.reason,
          "owner_team": ownership.get("team", "unknown"),
          "tier": ownership.get("tier", "tier-3"),
          "contact": ownership.get("contact", {}),
          "event_id": str(uuid4()),
          "schema_version": "v1"
      }
      ```
    - **Important:** `root_cause_entity_name` and `confidence` come from the `RootCause` dataclass (root_cause.py:12-16), NOT from Transition. The Transition dataclass only has `root_cause_entity_id`. Do NOT add these fields to Transition — keep separation of concerns.
    - Key: `entity_id` (bytes) — ensures per-entity ordering
    - Headers: `[("event_type", b"health.transition"), ("schema_version", b"v1")]`
    - Instrument: `dhs_transition_events_emitted_total` counter
    - Structured logging: log entity_id, old_state, new_state, event_id
    - Return True on success, False on failure (never crash the evaluator)

- Config additions to `config.py`:
  - `KAFKA_BOOTSTRAP_SERVERS` = `kafka.calculator.svc.cluster.local:9092` (FQDN for cross-namespace)
  - `KAFKA_TOPIC` = `health.transition.v1`

**Files to create:**
- `apps/dhs/kafka_emitter.py`

**Files to modify:**
- `apps/dhs/config.py` (add Kafka config)
- `apps/dhs/requirements.txt` (add `aiokafka==0.11.0`)

---

### Milestone 2 — Ownership lookup from SSOT

**Status:** [ ] Not Started

**Modify `apps/dhs/ssot_client.py`:**
- Add `async def get_ownership(entity_id: str) -> dict | None`
  - `GET /ownership/{entity_id}`
  - Returns `{"team": "...", "tier": "...", "contact": {...}}` or None
- Cache ownership data per evaluation cycle (fetch once, reuse for all entities)

**Verification:**
```bash
ssh 5560 "curl -s http://192.168.1.210:30900/ownership/k8s:lab:calculator:Service:api | python3 -m json.tool"
# Should return ownership with team, tier, contact
```

---

### Milestone 3 — Integrate Kafka emitter into evaluator

**Status:** [ ] Not Started

**Modify `apps/dhs/evaluator.py`:**
- Accept `kafka_emitter` in constructor
- After a transition fires and SSOT write succeeds (in `_evaluate_entity`, after line 199):
  1. Fetch ownership for the entity from SSOT (or use per-cycle cache from Milestone 2)
  2. The `rc: RootCause` variable is already in scope — pass it directly
  3. Call `kafka_emitter.emit_transition(transition, entity, rc, ownership)`
  4. Log success/failure

**Modify `apps/dhs/main.py`:**
- Create `KafkaEmitter` on startup, call `start()`
- Pass to Evaluator
- Call `stop()` on shutdown
- Handle Kafka connection failure gracefully (log warning, continue without Kafka)

**Files to modify:**
- `apps/dhs/evaluator.py`
- `apps/dhs/main.py`

---

### Milestone 4 — Cooldown + flap detection

**Status:** [ ] Not Started

**Modify `apps/dhs/state_engine.py`:**

- **Cooldown timer (manager-corrected):**
  - After a transition fires, record `last_transition_time` per entity
  - Severity order: `HEALTHY(0) < DEGRADED(1) < UNHEALTHY(2)`
  - Add helper: `_severity(state) -> int`
  - **Escalation** (severity increasing, e.g., DEGRADED→UNHEALTHY): **always allowed immediately** — never delay detection of worsening health
  - **De-escalation** (severity decreasing, e.g., UNHEALTHY→DEGRADED, UNHEALTHY→HEALTHY): **suppressed during cooldown** — prevents flip-flop noise
  - Only apply cooldown when `severity(new_state) <= severity(old_state)`
  - Recovery to HEALTHY: 90s recovery debounce already exceeds 60s cooldown, so cooldown is never the binding constraint for full recovery
  - Partial recovery (UNHEALTHY→DEGRADED): cooldown prevents premature "it's getting better" noise during oscillation

- **Flap detection:**
  - Track transition timestamps per entity using `deque(maxlen=10)`
  - Prune timestamps older than `FLAP_WINDOW_SECONDS` from the front when checking
  - If an entity has > `FLAP_THRESHOLD` (3) transitions in `FLAP_WINDOW_SECONDS` (600s) → mark as `flapping`
  - When flapping:
    - Increase debounce durations by 2x
    - Log warning: "Entity X is flapping — extended debounce applied"
    - Add `"flapping": true` to health_summary reason
  - Flap flag clears when entity is stable (same state) for 5 minutes

- Config additions to `config.py`:
  - `COOLDOWN_SECONDS` = 60
  - `FLAP_WINDOW_SECONDS` = 600
  - `FLAP_THRESHOLD` = 3

**Files to modify:**
- `apps/dhs/state_engine.py`
- `apps/dhs/config.py`

---

### Milestone 5 — Deploy + create Kafka topic

**Status:** [ ] Not Started

**Kafka topic creation:**
```bash
# Create the health.transition.v1 topic on the calculator Kafka broker
ssh 5560 "sudo kubectl exec -n calculator kafka-0 -- kafka-topics.sh \
  --create --topic health.transition.v1 \
  --bootstrap-server localhost:9092 \
  --partitions 3 --replication-factor 1 \
  --config retention.ms=86400000"
```

**Deploy:**
- Update k8s/dhs/deployment.yaml:
  - Add `KAFKA_BOOTSTRAP_SERVERS` and `KAFKA_TOPIC` env vars
- Rebuild and push image
- Wait for ArgoCD sync

**Verification:**
```bash
# Verify DHS connects to Kafka
ssh 5560 "sudo kubectl logs -n dhs deploy/dhs --tail=20 | grep -i kafka"

# Verify topic exists
ssh 5560 "sudo kubectl exec -n calculator kafka-0 -- kafka-topics.sh \
  --list --bootstrap-server localhost:9092 | grep health"

# Consume a test message (trigger a transition first)
ssh 5560 "sudo kubectl exec -n calculator kafka-0 -- kafka-console-consumer.sh \
  --topic health.transition.v1 --bootstrap-server localhost:9092 \
  --from-beginning --max-messages 1 --timeout-ms 30000"
```

---

### Milestone 6 — E2E tests

**Status:** [ ] Not Started

**`tests/e2e/test_transitions.py`:**

> **Manager guidance (two-tier testing):**
> - **Tier 1 — HTTP-based tests (CI, reliable, fast, run from Windows):** Test `dhs_transition_events_emitted_total` metric via `GET :30950/metrics`. This proves the emitter code path executed. These are the primary automated tests.
> - **Tier 2 — Kafka content verification (Milestone 5 deployment step):** Use `ssh 5560 "kubectl exec kafka-0 ..."` to consume and verify event JSON. This is a manual/semi-automated deployment verification, NOT a CI test.
> - For `test_transition_produces_kafka_event`: verify the metric counter incremented. Don't shell out to SSH in the test — trust the metric as proof of emission.

```python
pytestmark = pytest.mark.sprint3

class TestKafkaEvents:
    def test_kafka_emitter_metric_exists(self, dhs_client):
        """dhs_transition_events_emitted_total metric should exist."""

    def test_transition_emitted_via_metric(self, dhs_client):
        """dhs_transition_events_emitted_total > 0 proves Kafka emission occurred."""

class TestCooldown:
    def test_no_rapid_flip_back(self, dhs_client):
        """After a transition, verify no flip-back within cooldown period."""

class TestTransitionPolish:
    def test_dhs_version_is_sprint3(self, dhs_client):
        """DHS version should be 0.3.0."""
```

**Files to create:**
- `tests/e2e/test_transitions.py`

---

### Milestone 7 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 3 as complete
- Update `documentation/contracts/KAFKA_EVENTS.md` if any schema deviations
- Write `documentation/sprint/sprint3/REVIEW.md`
- **Notify manager:** Gate 4 (DHS Live) prerequisite met — `health.transition.v1` events flowing

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| `aiokafka` for Kafka producer | Async-first, lightweight, well-tested. Matches the async evaluator loop. |
| Kafka FQDN `kafka.calculator.svc.cluster.local:9092` | DHS is in `dhs` namespace, needs full FQDN to reach Kafka in `calculator` namespace. |
| 3 Kafka partitions | Allows parallel consumption by team6 if needed. Key = entity_id for per-entity ordering. |
| Cooldown 60s (de-escalation only) | Manager correction: cooldown must NOT suppress escalation. Only apply when `severity(new) <= severity(old)`. Escalation always fires immediately. |
| Flap detection at 3 transitions / 10 min | Conservative threshold — normal operation should never hit this. |
| Graceful Kafka failure | DHS must keep evaluating even if Kafka is down. SSOT writes are the primary output. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `apps/dhs/kafka_emitter.py` | Kafka event producer |
| `tests/e2e/test_transitions.py` | Sprint 3 E2E tests |
| `documentation/sprint/sprint3/REVIEW.md` | Sprint retrospective |
