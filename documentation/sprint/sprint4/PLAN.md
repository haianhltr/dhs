# Sprint 4 — Failure Scenario Validation

**Goal:** Validate all 7 Definition of Done scenarios end-to-end. After this sprint, DHS handles every failure mode correctly: right health state, right root cause, no spam, clean recovery, correct Kafka events.

**Status:** In Progress
**Depends on:** Sprints 1–3 complete, Team 2 Sprint 9 (K8s labels — ✅ complete), Team 3 Sprint 2 (dashboards — ✅ complete)

---

## Pre-Sprint State

- DHS evaluates health, attributes root cause, enriches with K8s events, emits Kafka events
- Not yet validated against real failure scenarios
- Edge cases (multiple simultaneous failures, cascading failures) untested

## Post-Sprint State

- All 7 DoD scenarios validated (manual runbook + automated unit tests)
- Edge cases documented and handled
- DHS is production-ready for the lab environment

---

## Manager Corrections (from challenge review)

| Challenge | Manager Correction |
|-----------|-------------------|
| Kafka outage kills DHS Kafka producer | Expected. After Kafka recovers, aiokafka reconnects automatically — do NOT create a new KafkaEmitter. Verify the recovery transition is emitted. |
| Kafka failure detection takes ~5m | Kafka-exporter fails when Kafka is down → Prometheus marks target as down → existing metrics go stale after 5m. Test needs longer timeout (360s) for Kafka scenario. |
| Service:api stays HEALTHY when Deployment scaled to 0 | Correct behavior. No pods = no requests = no errors. Failure point is Deployment (replica mismatch). Test should assert Deployment:api → UNHEALTHY, not expect Service:api to independently detect. |
| Recovery timing ~150-180s | Use polling loops with 240s timeout, not fixed sleep. |
| Ownership data empty | Assert on defaults: `owner_team: "unknown"`, `tier: "tier-3"`, `contact: {}`. |
| Hybrid test approach | Automated pytest: unit tests for state engine, rules, debounce/cooldown. Manual runbook: 7 destructive DoD scenarios. Do NOT automate destructive tests in CI. |

---

## Definition of Done Scenarios

| # | Scenario | Expected Outcome | Validated |
|---|----------|-------------------|-----------|
| 1 | Deployment failure (scale to 0) | Deployment UNHEALTHY, one transition per entity | [ ] |
| 2 | Kafka outage (stop Kafka) | Kafka UNHEALTHY, Worker/API impacted, root cause = Kafka | [ ] |
| 3 | Worker CrashLoop (bad image) | Worker Deployment UNHEALTHY, root cause = Worker (not Kafka) | [ ] |
| 4 | Node failure (simulated) | Node rule evaluates, root cause logic validated at code level | [ ] |
| 5 | Clean recovery (restore each failure) | Entities transition back to HEALTHY after debounce | [ ] |
| 6 | No spam | Each scenario produces exactly one transition per affected entity | [ ] |
| 7 | Kafka events correct | `health.transition.v1` contains correct payload with ownership | [ ] |

---

## Milestones

### Milestone 1 — Automated unit tests (non-destructive)

**Status:** [ ] Not Started

Unit tests for logic that doesn't require cluster access:

**`tests/unit/test_state_engine.py`:**
- Cooldown suppresses de-escalation (UNHEALTHY→HEALTHY blocked for 60s)
- Cooldown allows escalation (HEALTHY→UNHEALTHY fires immediately)
- Flap detection doubles debounce when >3 transitions in window
- Flap clears after 5m stability
- Debounce timer fires after configured duration
- Debounce resets when derived state changes
- Root cause change fires immediately (no debounce)

**`tests/unit/test_rule_loader.py`:**
- Rule files load correctly from YAML
- Entity matching with and without match_labels
- PromQL template rendering with entity context
- Severity ordering (UNHEALTHY first)

**`tests/unit/test_evaluator.py`:**
- Compare operators work correctly
- Debounce seconds selection (rule-specific vs global default)

### Milestone 2 — Manual runbook for DoD scenarios

**Status:** [ ] Not Started

Document in `documentation/sprint/sprint4/RUNBOOK.md`:
- Exact commands for each scenario
- Expected state transitions with entity IDs
- Verification steps with polling
- Cleanup/restore procedures
- Known timing constraints

### Milestone 3 — Execute Scenario 1: Deployment failure

**Status:** [ ] Not Started

```bash
# Scale API deployment to 0, wait for debounce (60s rule + eval cycle)
# Verify: Deployment:api → UNHEALTHY, reason mentions "0 available replicas"
# Note: Service:api may stay HEALTHY (correct — no pods = no errors)
# Restore: scale back to 1, wait 120s for recovery debounce
# Verify: Deployment:api → HEALTHY
```

### Milestone 4 — Execute Scenario 2: Kafka outage

**Status:** [ ] Not Started

```bash
# Scale Kafka StatefulSet to 0
# IMPORTANT: Detection takes up to 5m (Prometheus staleness window)
# Wait 360s total (5m staleness + 120s Kafka rule duration)
# Verify: kafka:lab:calculator-kafka → UNHEALTHY
# Note: DHS Kafka producer will fail during outage — expected
# Restore: scale back to 1, wait 120s
# Verify: Kafka → HEALTHY, aiokafka auto-reconnects, recovery event emitted
```

### Milestone 5 — Execute Scenario 3: Worker CrashLoop

**Status:** [ ] Not Started

```bash
# Set bad image on worker deployment
# Wait 120s for CrashLoopBackOff + debounce
# Verify: Deployment:worker → UNHEALTHY, root cause = self (NOT Kafka)
# Verify: reason includes CrashLoopBackOff (event enrichment)
# Restore: rollout undo, wait 120s
# Verify: Deployment:worker → HEALTHY
```

### Milestone 6 — Verify scenarios 4-7

**Status:** [ ] Not Started

- Scenario 4 (Node): Verify Node entity evaluated, rule logic correct (code-level)
- Scenario 5 (Recovery): Verified as part of each restore step above
- Scenario 6 (No spam): Check `dhs_transitions_total` metric — should show exactly 2 per entity per scenario
- Scenario 7 (Kafka events): Consume all events from topic, verify payload matches contract

### Milestone 7 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `ROADMAP.md` — mark Sprint 4 complete
- Write `sprint4/REVIEW.md`

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Unit tests for logic, manual runbook for destructive scenarios | Manager direction. Destructive tests in CI risk leaving cluster in broken state. |
| Polling with 240s timeout for recovery checks | Manager correction. Accounts for Prometheus scrape + DHS eval + debounce variance. |
| Kafka detection timeout 360s | Manager note: kafka-exporter fails → metrics go stale after 5m. Need longer timeout than Deployment failure. |
| Service:api may stay HEALTHY on Deployment scale-to-0 | Manager correction. No pods = no requests = no errors. Deployment-level detection is the primary signal. |
| aiokafka auto-reconnects | Manager note. Do NOT create new KafkaEmitter on Kafka recovery. Existing producer retries internally. |
| Assert default ownership values | Manager approved. `owner_team: "unknown"`, `tier: "tier-3"` until Team 4 populates ownership data. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `tests/unit/test_state_engine.py` | Unit tests for state engine (cooldown, flap, debounce) |
| `tests/unit/test_rule_loader.py` | Unit tests for rule loading and entity matching |
| `tests/unit/test_evaluator.py` | Unit tests for evaluator compare logic |
| `tests/e2e/test_failure_scenarios.py` | Sprint 4 E2E smoke tests (non-destructive) |
| `documentation/sprint/sprint4/RUNBOOK.md` | Manual runbook for 7 DoD scenarios |
| `documentation/sprint/sprint4/REVIEW.md` | Sprint retrospective |
