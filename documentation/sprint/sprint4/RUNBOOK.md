# Sprint 4 — Failure Scenario Runbook

Manual validation of all 7 Definition of Done scenarios. Each scenario includes exact commands, expected state transitions, and verification steps.

**Cluster:** k3s on Lenovo 5560 (192.168.1.210)
**DHS:** NodePort 30950
**SSOT:** NodePort 30900
**Kafka:** `kafka.calculator.svc.cluster.local:9092`

---

## Pre-Run Checklist

```bash
# Verify all calculator entities are HEALTHY before starting
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
calc = [d for d in data if 'calculator' in d.get('entity_id', '') or 'kafka:' in d.get('entity_id', '') or 'db:' in d.get('entity_id', '')]
for d in calc:
    print(f'{d[\"health_state\"]:10} {d[\"entity_id\"]}')
\""

# Record baseline transition count
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"

# Record baseline Kafka event count
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transition_events_emitted_total"
```

---

## Scenario 1 — Deployment Failure (Scale API to 0)

**Goal:** Verify DHS detects deployment failure and marks entity UNHEALTHY with correct root cause.

### Inject Failure

```bash
# Scale API deployment to 0 replicas
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=0"
```

### Wait & Verify (poll for ~120s)

```bash
# Poll SSOT until Deployment:api becomes UNHEALTHY (timeout 240s)
# Expected: 60s rule debounce + eval cycles
for i in $(seq 1 8); do
  echo "--- Check $i ($(($i * 30))s) ---"
  ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    if d.get('entity_id') in ['k8s:lab:calculator:Deployment:api', 'k8s:lab:calculator:Service:api']:
        print(json.dumps({k: d[k] for k in ['entity_id','health_state','root_cause_entity_id','confidence','reason']}, indent=2))
\""
  sleep 30
done
```

### Expected Results

| Entity | Expected State | Root Cause | Notes |
|--------|---------------|------------|-------|
| `k8s:lab:calculator:Deployment:api` | UNHEALTHY | self | reason: "0 available replicas" |
| `k8s:lab:calculator:Service:api` | HEALTHY (likely) | N/A | No pods = no requests = no errors. This is correct. |

### Verify No Spam

```bash
# Transition count should have incremented by exactly 1 (for Deployment:api)
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"

# Wait 60s more, check again — should NOT have incremented
sleep 60
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"
```

### Restore

```bash
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=1"
```

### Verify Recovery (poll for ~180s)

```bash
# Poll until Deployment:api returns to HEALTHY (recovery debounce = 90s)
for i in $(seq 1 6); do
  echo "--- Recovery check $i ($(($i * 30))s) ---"
  ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    if d.get('entity_id') == 'k8s:lab:calculator:Deployment:api':
        print(d['health_state'], d.get('root_cause_entity_id'))
\""
  sleep 30
done
```

**Expected:** `HEALTHY`, `root_cause_entity_id=None`

---

## Scenario 2 — Kafka Outage (Scale Kafka to 0)

**Goal:** Verify DHS detects Kafka failure and attributes dependent services' root cause to Kafka.

> **IMPORTANT:** Detection takes up to ~5 minutes due to Prometheus metric staleness window. When Kafka is down, kafka-exporter also fails. Prometheus marks the target as down and existing metrics go stale after 5m (Prometheus default).

> **NOTE:** DHS's own Kafka producer will fail during the outage. This is expected behavior. The recovery transition event should be emitted after Kafka comes back (aiokafka auto-reconnects).

### Inject Failure

```bash
ssh 5560 "sudo kubectl scale statefulset kafka -n calculator --replicas=0"
```

### Wait & Verify (poll for ~360s — longer due to staleness)

```bash
# Poll every 60s for up to 6 minutes
for i in $(seq 1 6); do
  echo "--- Check $i ($(($i * 60))s) ---"
  ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    eid = d.get('entity_id', '')
    if 'kafka' in eid.lower() or eid in ['k8s:lab:calculator:Service:worker', 'k8s:lab:calculator:Service:api']:
        print(json.dumps({k: d[k] for k in ['entity_id','health_state','root_cause_entity_id','confidence','reason'] if k in d}, indent=2))
\""
  sleep 60
done
```

### Expected Results

| Entity | Expected State | Root Cause | Notes |
|--------|---------------|------------|-------|
| `kafka:lab:calculator-kafka` | UNHEALTHY | self | reason: "broker count < 1" |
| `k8s:lab:calculator:Service:worker` | UNHEALTHY or DEGRADED | `kafka:lab:calculator-kafka` | DEPENDS_ON Kafka |
| `k8s:lab:calculator:Service:api` | UNHEALTHY or DEGRADED | `kafka:lab:calculator-kafka` | DEPENDS_ON Kafka |

### Verify DHS Kafka Producer Errors

```bash
# DHS logs should show Kafka emit failures (expected)
ssh 5560 "sudo kubectl logs -n dhs deploy/dhs --tail=20 2>&1 | grep -i kafka"
```

### Restore

```bash
ssh 5560 "sudo kubectl scale statefulset kafka -n calculator --replicas=1"
```

### Verify Recovery (poll for ~300s — staleness + debounce)

```bash
# Wait for Kafka pod to be ready
ssh 5560 "sudo kubectl wait --for=condition=ready pod/kafka-0 -n calculator --timeout=120s"

# Poll until recovery
for i in $(seq 1 6); do
  echo "--- Recovery check $i ($(($i * 60))s) ---"
  ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    eid = d.get('entity_id', '')
    if 'kafka' in eid.lower():
        print(d['health_state'], d.get('root_cause_entity_id'))
\""
  sleep 60
done
```

### Verify aiokafka Auto-Reconnect

```bash
# After Kafka recovers, DHS should auto-reconnect and emit recovery events
ssh 5560 "sudo kubectl logs -n dhs deploy/dhs --tail=30 2>&1 | grep -i 'kafka\|emit'"

# Check emitted count increased
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transition_events_emitted_total"
```

---

## Scenario 3 — Worker CrashLoop (Bad Image)

**Goal:** Verify DHS marks Worker Deployment UNHEALTHY with root cause = self (not Kafka).

### Inject Failure

```bash
# Save current worker image for rollback
ssh 5560 "sudo kubectl get deployment worker -n calculator -o jsonpath='{.spec.template.spec.containers[0].image}'"

# Set bad image
ssh 5560 "sudo kubectl set image deployment/worker -n calculator worker=ghcr.io/nonexistent/image:bad"
```

### Wait & Verify (poll for ~120s)

```bash
for i in $(seq 1 8); do
  echo "--- Check $i ($(($i * 30))s) ---"
  ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    if 'worker' in d.get('entity_id', '').lower():
        print(json.dumps({k: d[k] for k in ['entity_id','health_state','root_cause_entity_id','confidence','reason'] if k in d}, indent=2))
\""
  sleep 30
done
```

### Expected Results

| Entity | Expected State | Root Cause | Notes |
|--------|---------------|------------|-------|
| `k8s:lab:calculator:Deployment:worker` | UNHEALTHY | self | reason: "0 available replicas" |
| Root cause | NOT Kafka | | Kafka is healthy — root cause must be Worker itself |

### Verify Event Enrichment

```bash
# Check if reason includes CrashLoopBackOff or ImagePullBackOff
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    if d.get('entity_id') == 'k8s:lab:calculator:Deployment:worker':
        print('Reason:', d.get('reason', ''))
        print('Root cause:', d.get('root_cause_entity_id'))
\""
```

### Restore

```bash
ssh 5560 "sudo kubectl rollout undo deployment/worker -n calculator"
```

### Verify Recovery (poll for ~180s)

```bash
for i in $(seq 1 6); do
  echo "--- Recovery check $i ($(($i * 30))s) ---"
  ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    if d.get('entity_id') == 'k8s:lab:calculator:Deployment:worker':
        print(d['health_state'], d.get('root_cause_entity_id'))
\""
  sleep 30
done
```

---

## Scenario 4 — Node Failure (Simulated)

**Goal:** Verify Node health rule evaluates correctly. True node failure is not testable on single-node k3s.

### Verification (no failure injection)

```bash
# Verify DHS evaluates Node entities
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep 'dhs_evaluations_total.*Node'"

# Verify Node health in SSOT
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
for d in data:
    if 'Node' in d.get('entity_id', ''):
        print(json.dumps(d, indent=2))
\""

# Verify the Prometheus metric that the rule checks
ssh 5560 "curl -s 'http://192.168.1.210:30090/api/v1/query?query=kube_node_status_condition{condition=\"Ready\",status=\"true\"}' | python3 -m json.tool"
```

### Expected Results

| Check | Expected |
|-------|----------|
| `dhs_evaluations_total{entity_type="Node"}` | > 0 |
| Node health state in SSOT | HEALTHY |
| `kube_node_status_condition` metric | value = 1 |

### Limitation

Single-node k3s: node failure = total cluster outage (DHS included). Root-cause-to-Node logic is validated in unit tests (`test_state_engine.py`). The Node rule and RUNS_ON relationship traversal are verified at code level.

---

## Scenario 5 — Clean Recovery

**Verified as part of each scenario above.** After restoring each failure:

### Checklist

- [ ] Entity returns to HEALTHY after 90s recovery debounce
- [ ] Transition `UNHEALTHY → HEALTHY` fires exactly once
- [ ] `root_cause_entity_id` = null on HEALTHY entity
- [ ] Kafka event emitted with `new_state: "HEALTHY"` (check topic)

---

## Scenario 6 — No Spam

**Verified during each failure scenario.** During each outage:

### Verification

```bash
# Record transition count before failure
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"

# After failure detected (entity UNHEALTHY), wait 2 more eval cycles (60s)
sleep 60

# Check again — should NOT have incremented
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"
```

### Expected

Per entity per scenario: exactly 2 transitions total (failure + recovery). More = spam.

---

## Scenario 7 — Kafka Events Correct

### Consume All Events

```bash
ssh 5560 "sudo kubectl exec -n calculator kafka-0 -- /opt/kafka/bin/kafka-console-consumer.sh \
  --topic health.transition.v1 --bootstrap-server localhost:9092 \
  --from-beginning --timeout-ms 15000 2>/dev/null"
```

### Verify Each Event

For every event in the output:

| Field | Check |
|-------|-------|
| `entity_id` | Valid entity ID format |
| `entity_type` | Matches entity |
| `old_state` / `new_state` | Valid state transition |
| `root_cause_entity_id` | Correct per scenario |
| `confidence` | > 0 for non-HEALTHY |
| `owner_team` | Present (may be "unknown") |
| `tier` | Present (may be "tier-3") |
| `contact` | Present (may be `{}`) |
| `event_id` | Valid UUID |
| `schema_version` | "v1" |
| No duplicate `event_id` | Each event_id unique |

---

## Post-Run Summary Template

```
## Scenario Results

| # | Scenario | Result | Notes |
|---|----------|--------|-------|
| 1 | Deployment failure | PASS/FAIL | |
| 2 | Kafka outage | PASS/FAIL | |
| 3 | Worker CrashLoop | PASS/FAIL | |
| 4 | Node failure | PASS (code-level) | Single-node limitation |
| 5 | Clean recovery | PASS/FAIL | |
| 6 | No spam | PASS/FAIL | |
| 7 | Kafka events | PASS/FAIL | |

Total transitions observed: ___
Total Kafka events emitted: ___
```
