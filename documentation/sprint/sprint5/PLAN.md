# Sprint 5 — CI/CD + Integration + Contract Docs

**Goal:** Production-ready CI/CD pipeline, ArgoCD Application, full integration validation, and finalized contract docs. After this sprint, DHS is fully operational and documented — ready for team6 handoff.

**Status:** Not Started
**Depends on:** Sprint 4 complete, all teams operational

---

## Pre-Sprint State

- DHS fully functional: evaluator, root cause, event enrichment, Kafka emitter, transition polish
- All 7 DoD scenarios validated
- No CI/CD pipeline — manual image builds
- No ArgoCD Application — manual deployment
- Contract docs may need updates based on Sprint 2-4 learnings

## Post-Sprint State

- GitHub Actions workflow builds and pushes DHS image on every push to main
- ArgoCD Application auto-deploys DHS manifests
- Image tags use `sha-<short-commit>` (per platform convention)
- Full integration test validates DHS against live cluster
- Contract docs finalized and accurate
- Gate 4 (DHS Live) fully achieved — team6 unblocked

---

## Milestones

### Milestone 1 — GitHub Actions CI pipeline

**Status:** [ ] Not Started

**`.github/workflows/dhs.yaml`:**
```yaml
name: DHS Build
on:
  push:
    branches: [main]
    paths:
      - 'team5/dhs/apps/**'
      - 'team5/dhs/rules/**'
      - 'team5/dhs/Dockerfile'
      - '.github/workflows/dhs.yaml'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: team5/dhs/apps/dhs
          push: true
          tags: |
            ghcr.io/${{ github.repository }}/dhs:sha-${{ github.sha }}
            ghcr.io/${{ github.repository }}/dhs:latest
```

- Image path: `ghcr.io/<owner>/<repo>/dhs:sha-<commit>`
- Trigger: push to main that touches DHS source, rules, or Dockerfile
- Match existing team2/team4 CI patterns

**Files to create:**
- `.github/workflows/dhs.yaml`

---

### Milestone 2 — ArgoCD Application

**Status:** [ ] Not Started

**`k8s/argocd-app.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dhs
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/<owner>/<repo>
    targetRevision: main
    path: team5/dhs/k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: dhs
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Update `k8s/dhs/deployment.yaml`:**
- Change image from `latest` to `sha-<commit>` tag pattern
- Add `imagePullPolicy: Always`

**Apply to cluster:**
```bash
ssh 5560 "sudo kubectl apply -f -" < k8s/argocd-app.yaml
```

**Verification:**
```bash
# Check ArgoCD app status
ssh 5560 "sudo kubectl get applications -n argocd dhs"
# Should show Synced, Healthy
```

**Files to create:**
- `k8s/argocd-app.yaml`

**Files to modify:**
- `k8s/dhs/deployment.yaml` (image tag pattern)

---

### Milestone 3 — Full integration test

**Status:** [ ] Not Started

Run the complete E2E test suite against the live cluster:

```bash
# Install test deps
pip install -r tests/requirements.txt

# Run all tests
pytest tests/e2e/ -v --timeout=300

# Expected: all tests from sprints 1-4 pass
```

**Test coverage check:**
- Sprint 1: `test_evaluator.py` — DHS reachable, metrics, health_summary written
- Sprint 2: `test_root_cause.py` — root cause fields, event enrichment
- Sprint 3: `test_transitions.py` — Kafka events, cooldown, ownership context
- Sprint 4: `test_failure_scenarios.py` — deployment failure, no spam, correct events

**Fix any failures** before proceeding.

---

### Milestone 4 — Prometheus scrape target for DHS

**Status:** [ ] Not Started

**Verify team3 Prometheus can scrape DHS metrics:**
- DHS exposes `/metrics` on port 8080 (container port) / 30950 (NodePort)
- Team3 may need to add a scrape target for DHS — coordinate if needed
- Or DHS can be scraped via the existing `kube-state-metrics` → DHS is a Deployment in `dhs` namespace

**Check if DHS metrics appear in Prometheus:**
```bash
ssh 5560 "curl -s 'http://192.168.1.210:30090/api/v1/query?query=dhs_evaluations_total' | python3 -m json.tool"
```

If not scraped, coordinate with team3 to add scrape config (or document as a future task).

---

### Milestone 5 — Finalize contract docs

**Status:** [ ] Not Started

**Review and update:**

1. **`documentation/contracts/HEALTH_STATES.md`:**
   - Verify all state transition rules match actual implementation
   - Update debounce durations if changed
   - Add flap detection documentation
   - Verify root cause confidence ranges match code

2. **`documentation/contracts/KAFKA_EVENTS.md`:**
   - Verify event schema matches actual emitted events
   - Update Kafka bootstrap server if changed
   - Confirm consumer group name for team6
   - Add note about Kafka topic creation (partitions, retention)

3. **New: `documentation/contracts/DHS_CONTRACT.md`:**
   - DHS service endpoints (/, /health, /metrics)
   - Evaluation frequency and config
   - What DHS reads (Prometheus, SSOT, Loki) and writes (SSOT, Kafka)
   - Prometheus metrics exposed by DHS
   - How to verify DHS is working

**Files to create:**
- `documentation/contracts/DHS_CONTRACT.md`

**Files to modify:**
- `documentation/contracts/HEALTH_STATES.md`
- `documentation/contracts/KAFKA_EVENTS.md`

---

### Milestone 6 — Validate Gate 4 checklist

**Status:** [ ] Not Started

**Gate 4: DHS Live — Checklist:**

| Criterion | Verification | Status |
|-----------|-------------|--------|
| DHS pod running in `dhs` namespace | `kubectl get pods -n dhs` shows 1/1 Running | [ ] |
| Evaluator loop executing every 30s | DHS logs show periodic cycles | [ ] |
| health_summary written to SSOT for calculator entities | `GET /health_summary` returns records with `last_updated_by=dhs` | [ ] |
| Root cause attribution working | UNHEALTHY entities have `root_cause_entity_id` set | [ ] |
| K8s event enrichment working | Reason text includes K8s event info when applicable | [ ] |
| `health.transition.v1` Kafka events flowing | `kafka-console-consumer` shows events on topic | [ ] |
| Events include ownership context | Events have `owner_team`, `tier`, `contact` | [ ] |
| No transition spam | `dhs_transitions_total` stays stable during steady state | [ ] |
| CI/CD pipeline working | Push to main → image built → ArgoCD deploys | [ ] |
| All E2E tests pass | `pytest tests/e2e/ -v` — all green | [ ] |
| Contract docs finalized | HEALTH_STATES.md, KAFKA_EVENTS.md, DHS_CONTRACT.md accurate | [ ] |

---

### Milestone 7 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 5 as complete
- Write `documentation/sprint/sprint5/REVIEW.md`
- Update `ARCHITECTURE_DESIRED.md` if target state changed
- **Notify manager:** Gate 4 (DHS Live) fully achieved. Team6 can begin Sprint 1.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| GitHub Actions + ghcr.io | Matches team2/team4 CI pattern. Platform standard. |
| ArgoCD automated sync | Self-healing, prune orphaned resources. Matches platform convention. |
| `sha-<commit>` image tags | Immutable tags prevent "works on my machine" issues. Platform standard. |
| DHS_CONTRACT.md as new contract | Team6 needs to know DHS endpoints and behavior. Centralizes operational info. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `.github/workflows/dhs.yaml` | CI/CD pipeline |
| `k8s/argocd-app.yaml` | ArgoCD Application |
| `documentation/contracts/DHS_CONTRACT.md` | DHS service contract |
| `documentation/sprint/sprint5/REVIEW.md` | Sprint retrospective |
