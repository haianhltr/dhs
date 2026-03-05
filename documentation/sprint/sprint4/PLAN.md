# Sprint 4 — Failure Scenario Validation

**Goal:** Validate all 7 Definition of Done scenarios end-to-end. After this sprint, DHS handles every failure mode correctly: right health state, right root cause, no spam, clean recovery, correct Kafka events.

**Status:** Not Started
**Depends on:** Sprints 1–3 complete, Team 2 Sprint 9 (K8s labels — ✅ complete), Team 3 Sprint 2 (dashboards — ✅ complete)

---

## Pre-Sprint State

- DHS evaluates health, attributes root cause, enriches with K8s events, emits Kafka events
- Not yet validated against real failure scenarios
- Edge cases (multiple simultaneous failures, cascading failures) untested

## Post-Sprint State

- All 7 DoD scenarios validated with automated tests
- Edge cases documented and handled
- DHS is production-ready for the lab environment

---

## Definition of Done Scenarios

| # | Scenario | Expected Outcome | Validated |
|---|----------|-------------------|-----------|
| 1 | Deployment failure (scale to 0) | Deployment UNHEALTHY, Service DEGRADED/UNHEALTHY, one transition per entity | [ ] |
| 2 | Kafka outage (stop Kafka) | Kafka UNHEALTHY, Worker/API impacted, root cause = Kafka | [ ] |
| 3 | Worker CrashLoop (bad image) | Worker Deployment UNHEALTHY, root cause = Worker (not Kafka) | [ ] |
| 4 | Node failure (simulate NotReady) | Multiple deployments degrade, root cause = Node | [ ] |
| 5 | Clean recovery (restore each failure) | Entities transition back to HEALTHY after debounce | [ ] |
| 6 | No spam | Each scenario produces exactly one transition per affected entity | [ ] |
| 7 | Kafka events correct | `health.transition.v1` contains correct payload with ownership | [ ] |

---

## Milestones

### Milestone 1 — Scenario 1: Deployment failure

**Status:** [ ] Not Started

**Test procedure:**
```bash
# 1. Record initial state
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -m json.tool" > /tmp/before.json

# 2. Scale API deployment to 0
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=0"

# 3. Wait 90s (debounce duration)
sleep 90

# 4. Check health_summary
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Deployment:api' | python3 -m json.tool"
# Expected: health_state=UNHEALTHY, reason mentions "0 available replicas"

ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Service:api' | python3 -m json.tool"
# Expected: health_state=DEGRADED or UNHEALTHY, root_cause_entity_id points to Deployment

# 5. Check transition count on DHS metrics
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"
# Expected: small number (not growing every cycle)

# 6. Restore
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=1"
sleep 120  # recovery debounce (90s)
```

**Expected results:**
- Deployment: `HEALTHY → UNHEALTHY` (one transition)
- Service: `HEALTHY → UNHEALTHY` with `root_cause_entity_id` = Deployment entity
- No repeated transitions while replicas stay at 0

---

### Milestone 2 — Scenario 2: Kafka outage

**Status:** [ ] Not Started

**Test procedure:**
```bash
# 1. Scale Kafka to 0
ssh 5560 "sudo kubectl scale statefulset kafka -n calculator --replicas=0"

# 2. Wait 150s (Kafka rule duration 120s + buffer)
sleep 150

# 3. Check health_summary
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/kafka:lab:calculator-kafka' | python3 -m json.tool"
# Expected: UNHEALTHY, reason mentions broker count

# Check dependent services
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Service:worker' | python3 -m json.tool"
# Expected: DEGRADED or UNHEALTHY, root_cause_entity_id = Kafka entity

# 4. Restore
ssh 5560 "sudo kubectl scale statefulset kafka -n calculator --replicas=1"
sleep 120
```

**Expected results:**
- Kafka entity: `HEALTHY → UNHEALTHY`
- Worker Service: root cause points to Kafka (not self)
- API Service: may show lag-related degradation, root cause = Kafka

---

### Milestone 3 — Scenario 3: Worker CrashLoop

**Status:** [ ] Not Started

**Test procedure:**
```bash
# 1. Deploy bad image to worker
ssh 5560 "sudo kubectl set image deployment/worker worker=ghcr.io/nonexistent/image:bad -n calculator"

# 2. Wait 120s for CrashLoopBackOff + debounce
sleep 120

# 3. Check health_summary
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Deployment:worker' | python3 -m json.tool"
# Expected: UNHEALTHY, root cause = self (Worker, NOT Kafka)
# reason should mention CrashLoopBackOff if event enrichment is working

# 4. Restore
ssh 5560 "sudo kubectl rollout undo deployment/worker -n calculator"
sleep 120
```

**Expected results:**
- Worker Deployment: `HEALTHY → UNHEALTHY`, root cause = Worker Deployment itself
- Root cause must NOT be Kafka (Kafka is healthy in this scenario)
- Reason text should include "CrashLoopBackOff" from event enrichment

---

### Milestone 4 — Scenario 4: Node failure (simulated)

**Status:** [ ] Not Started

> **Note:** On a single-node k3s cluster, true node failure would take down everything including DHS. This scenario validates the Node health rule logic using metrics.

**Test approach:**
- Verify Node health rule evaluates correctly by checking `kube_node_status_condition`
- If possible, use `kubectl cordon` to mark node as unschedulable (doesn't trigger NotReady but tests node awareness)
- Alternatively: verify that if `kube_node_status_condition{condition="Ready", status="true"}` returns 0, DHS would root-cause to Node

**Verification:**
```bash
# Check that DHS is evaluating the Node entity
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep 'dhs_evaluations_total.*Node'"

# Check current Node health
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    if 'Node' in d.get('entity_id', ''):
        print(json.dumps(d, indent=2))
\""
```

**Document limitation:** Single-node cluster means true node failure = total cluster outage. Root-cause-to-Node logic is validated at the code/unit level.

---

### Milestone 5 — Scenario 5: Clean recovery

**Status:** [ ] Not Started

After each scenario above (1-3), verify:
- Entity returns to `HEALTHY` after the 90s recovery debounce
- Transition `UNHEALTHY → HEALTHY` fires exactly once
- `health_summary` shows `health_state=HEALTHY`, `root_cause_entity_id=null`
- Kafka event emitted with `new_state=HEALTHY`

**Verification for each recovery:**
```bash
# After restoring the failure:
sleep 120  # wait for recovery debounce

# Check health state is HEALTHY
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/<entity_id>' | python3 -m json.tool"

# Check DHS metrics — transition count should only have incremented by 1 (for the recovery)
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"
```

---

### Milestone 6 — Scenario 6 & 7: No spam + correct Kafka events

**Status:** [ ] Not Started

**No spam validation:**
- During each failure scenario, monitor `dhs_transitions_total` metric
- After initial transition, the counter must NOT increment on subsequent evaluation cycles
- Only the recovery transition should increment it again
- Formula: for each entity affected, expect exactly 2 transitions per scenario (failure + recovery)

**Kafka event validation:**
```bash
# Consume all events from the topic
ssh 5560 "sudo kubectl exec -n calculator kafka-0 -- kafka-console-consumer.sh \
  --topic health.transition.v1 --bootstrap-server localhost:9092 \
  --from-beginning --timeout-ms 10000" | python3 -m json.tool
```

For each event, verify:
- `entity_id` matches expected entity
- `old_state` / `new_state` correct
- `root_cause_entity_id` correct
- `owner_team`, `tier`, `contact` present
- `event_id` is a valid UUID
- `schema_version` = "v1"
- No duplicate events (check `event_id` uniqueness)

---

### Milestone 7 — Automated E2E test suite

**Status:** [ ] Not Started

**`tests/e2e/test_failure_scenarios.py`:**
```python
pytestmark = pytest.mark.sprint4

class TestDeploymentFailure:
    def test_scale_to_zero_marks_unhealthy(self):
        """Scale API to 0, wait for debounce, check UNHEALTHY."""

    def test_recovery_marks_healthy(self):
        """Restore replicas, wait for recovery debounce, check HEALTHY."""

class TestNoSpam:
    def test_single_transition_per_entity(self):
        """During failure, only one transition fires (not one per eval cycle)."""

class TestKafkaEventPayload:
    def test_event_matches_contract(self):
        """Kafka event fields match KAFKA_EVENTS.md contract."""

    def test_event_has_ownership(self):
        """Kafka event includes owner_team, tier, contact."""
```

> **Note:** Kafka outage and CrashLoop scenarios are destructive and may require manual verification rather than automated tests in CI. Document the manual runbook alongside the automated suite.

**Files to create:**
- `tests/e2e/test_failure_scenarios.py`

---

### Milestone 8 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 4 as complete
- Write `documentation/sprint/sprint4/REVIEW.md`
- Update `HEALTH_STATES.md` if any state transition rules changed during validation
- Update `KAFKA_EVENTS.md` if any event schema changes

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Manual + automated testing | Destructive scenarios (Kafka outage, CrashLoop) are hard to automate safely in CI. Manual runbook + automated smoke tests provide best coverage. |
| Single-node limitation documented | Node failure on single-node k3s = total outage. Acknowledge and validate at code level. |
| 2 transitions per entity per scenario | Failure + recovery = exactly 2. More = spam. Less = missed transition. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `tests/e2e/test_failure_scenarios.py` | Sprint 4 E2E tests |
| `documentation/sprint/sprint4/REVIEW.md` | Sprint retrospective |
