# Sprint 4 Review — Failure Scenario Validation

**Sprint:** 4
**Date:** 2026-03-05
**Status:** Complete

## Objective

Validate all 7 Definition of Done scenarios end-to-end: deployment failure, Kafka outage, worker CrashLoop, node failure, clean recovery, no spam, and correct Kafka events.

## What We Shipped

- **51 new unit tests** — test_state_engine.py, test_rule_loader.py, test_evaluator_logic.py
- **8 new E2E tests** — test_failure_scenarios.py
- **1 bug fix** — absent metric detection (`or vector(0)` for kafka_brokers and pg_up)
- **1 manual runbook** — documentation/sprint/sprint4/RUNBOOK.md
- **3 DoD scenarios validated live** — Deployment failure, Kafka outage, Worker CrashLoop

### Bug Fix: Absent Metric Detection

During Scenario 2 (Kafka outage), discovered that when kafka-exporter goes down with Kafka, the `kafka_brokers` metric disappears from Prometheus entirely. DHS treated `None` (empty result) as "no data" and skipped the rule. Fixed by adding `or vector(0)` to the PromQL, which defaults to 0 when the metric is absent.

Same fix applied preemptively to `pg_up` (Database unreachable rule).

## Scenario Results

| # | Scenario | Result | Details |
|---|----------|--------|---------|
| 1 | Deployment failure (scale API to 0) | **PASS** | Deployment:api → UNHEALTHY, root cause = self, reason = "0 available replicas". Service:api stays HEALTHY (correct — no pods = no errors). Recovery to HEALTHY after 90s debounce. |
| 2 | Kafka outage (scale Kafka to 0) | **PASS** | kafka:lab:calculator-kafka → UNHEALTHY at ~240s (staleness + rule). DHS Kafka producer failed during outage (expected). aiokafka auto-reconnected after recovery — 3 events emitted post-recovery. |
| 3 | Worker CrashLoop (bad image) | **PASS** | Deployment:worker → UNHEALTHY, root cause = self (NOT Kafka). Recovery after rollout undo + 90s debounce. |
| 4 | Node failure (simulated) | **PASS (code-level)** | Node entity evaluated (48+ cycles), health_state=HEALTHY, rule logic validated in unit tests. Single-node k3s limitation documented. |
| 5 | Clean recovery | **PASS** | All 3 scenarios recovered to HEALTHY with root_cause_entity_id=null, confidence=1.0. Transitions fired exactly once per recovery. |
| 6 | No spam | **PASS** | Transition counters did not increment during sustained outage (verified 60s after failure detection). Each scenario: exactly 2 transitions per entity (failure + recovery). |
| 7 | Kafka events correct | **PASS** | 7 events consumed from topic — all fields present, all event_ids unique, schema_version=v1, ownership defaults correct. |

## Key Metrics

| Metric | Value |
|--------|-------|
| Unit tests | 51 (all passing) |
| E2E tests | 23 (8 Sprint 4 + 15 prior sprints, all passing) |
| Total tests | 74 |
| Kafka events emitted (this session) | 7 |
| Transition/evaluation ratio | < 1% (no spam verified) |
| Kafka outage detection time | ~240s (4 minutes) |
| Deployment failure detection time | ~90s (60s rule + eval cycle) |

## Incidents & Fixes

- **ArgoCD auto-sync reverted scale-to-0**: Scenario 1 initially failed because ArgoCD auto-synced and restored replicas. Fixed by pausing ArgoCD sync during testing.
- **HPA prevented CrashLoop**: Scenario 3 initially kept old pods running due to HPA (min=2, max=5) and rolling update strategy. Fixed by deleting HPA and scaling to 0 before injecting bad image.
- **Absent metric bug**: `kafka_brokers` returned empty (not 0) when Kafka was down. Fixed with `or vector(0)`.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| `or vector(0)` for absent metrics | Standard Prometheus pattern. When exporter goes down, metric disappears. `or vector(0)` returns 0, triggering the `< 1` check correctly. |
| Pause ArgoCD sync during testing | ArgoCD reverts manual kubectl changes. Must pause sync for destructive testing. Document in runbook. |
| HPA removal for CrashLoop test | HPA keeps min=2 old pods alive during rolling update, masking the failure. For real CrashLoop testing, need to remove HPA and scale to 0 first. |
| Service stays HEALTHY on Deployment failure | Correct behavior (manager confirmed). No pods = no requests = no Service-level metric degradation. Deployment-level detection is the primary signal. |

## What We Didn't Do (and why)

- **True node failure test** — Single-node k3s. Node failure = total cluster outage. Validated at code/unit level only.
- **Service-level Kafka impact detection** — Service rules use recording rules (`calculator:worker_failure_rate:5m`) that may not exist or have data. Services stay HEALTHY during Kafka outage; only the Kafka entity and Deployment replicas detect the issue.
- **Automated destructive CI tests** — Manager directive. Destructive scenarios are manual only (runbook) to avoid leaving cluster in broken state.

## Completion Checklist

- [x] Scenario 1: Deployment failure → UNHEALTHY, one transition
- [x] Scenario 2: Kafka outage → Kafka UNHEALTHY, detected via `or vector(0)` fix
- [x] Scenario 3: Worker CrashLoop → UNHEALTHY, root cause = Worker (not Kafka)
- [x] Scenario 4: Node failure → validated at code level (single-node limitation)
- [x] Scenario 5: Clean recovery → HEALTHY after debounce, exactly 1 recovery transition
- [x] Scenario 6: No spam → transition count stable during sustained outage
- [x] Scenario 7: Kafka events → 7 events verified, all fields correct, all event_ids unique
- [x] 74/74 tests passing (51 unit + 23 E2E)
- [x] Bug fix: absent metric detection with `or vector(0)`
- [x] Manual runbook documented
- [x] ArgoCD sync re-enabled after testing
- [x] ROADMAP.md updated

## What's Next

Sprint 5: CI/CD + Integration + Contract Docs
- GitHub Actions build pipeline for DHS image
- ArgoCD Application for dhs namespace
- Full integration test against live cluster
- Validate all 7 DoD scenarios (regression)
- Write contract docs (DHS_CONTRACT.md)
- Handoff to Ops UI team
