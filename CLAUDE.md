# DHS (Derived Health System) — Agent Instructions

## Start Here

1. Read `documentation/progress/ARCHITECTURE_DESIRED.md` — the **target specification**. This is what DHS must become.
2. Read the code (`apps/`, `k8s/`, `rules/`) — this is the **current state**. The gap between code and desired architecture is your work.
3. Read `documentation/sprint/ROADMAP.md` — overall sprint sequence and what's done vs remaining.
4. Read the current sprint `documentation/sprint/sprintN/PLAN.md` — your concrete work for this session.

**There is no separate "current architecture" document. The code IS the current architecture.**

## What DHS Is

DHS is the **brain** that converts raw telemetry + topology into health states. It:
- **Evaluates** health for every registered entity on a periodic loop (15–60s)
- **Derives** a single health state: HEALTHY, DEGRADED, UNHEALTHY, or UNKNOWN
- **Attributes root cause** using SSOT topology (best-effort, with confidence)
- **Debounces** transitions (no alert spam)
- **Writes** health_summary to SSOT on state transitions only
- **Emits** `health.transition` events to Kafka for alerting/actions

**DHS does NOT collect telemetry** (that's Observability). **DHS does NOT act on Kubernetes** (that's Actions). DHS reads signals, thinks, and writes conclusions.

## What You Own

1. **DHS Service** — Python service: evaluator loop, event ingestor, state machine, root cause resolver, emitter
2. **Health Rules** — YAML-defined rules mapping signals to health states (in `rules/`)
3. **PromQL Query Catalog** — the specific queries DHS uses against Prometheus
4. **Transition Logic** — debounce, cooldown, flap control

## Context: Other Teams

| Team | What They Provide to DHS | DHS Interface |
|------|-------------------------|---------------|
| Team 2 (App) | Calculator services with `/metrics` endpoints | DHS evaluates their health |
| Team 3 (Observability) | Prometheus (metrics), Loki (logs), Tempo (traces), K8s events | DHS **reads** Prometheus API + K8s event stream |
| Team 4 (SSOT) | Entities, relationships, ownership, health_summary endpoint | DHS **reads** entities/topology/ownership, **writes** health_summary |

### What DHS Reads

| Source | Endpoint | What |
|--------|----------|------|
| Prometheus | `http://prometheus.observability:9090/api/v1/query` | Metric queries (golden signals, kube-state, exporters) |
| SSOT API | `http://ssot-api.ssot:8080` | Entities, relationships, ownership, current health |
| K8s Event Stream | Kafka topic or webhook from event exporter | CrashLoopBackOff, OOMKilled, NodeNotReady, etc. |

### What DHS Writes

| Target | Endpoint | What |
|--------|----------|------|
| SSOT API | `PUT /health_summary` | Health state transitions (only on change) |
| Kafka | Topic `health.transition.v1` | Transition events with ownership context |

## Machines

- **This PC (Windows):** Dev machine — write code, push to GitHub
- **Lenovo 5560 (Ubuntu 24.04):** Server — runs k3s, all pods live here. Reach it via `ssh 5560` (IP: `192.168.1.210`)

## Deployment Flow

```
Edit code in apps/ → git push origin main → GitHub Actions builds images → ArgoCD deploys to k3s
Edit manifests in k8s/ → git push origin main → ArgoCD picks up within ~3 min
```

## Namespace Strategy

DHS resources live in the `dhs` namespace.
- DHS service pod runs here
- DHS does NOT have its own Postgres — it reads/writes via SSOT API and Prometheus API

## Working Convention

### Before starting work
1. Read `ARCHITECTURE_DESIRED.md` to know what the platform should look like
2. Read the current sprint `PLAN.md` — milestones are ordered and self-contained
3. Read the relevant source code to understand what exists today

### While working (after each milestone)
1. **Sprint PLAN.md** — mark milestone status as `[x] Done`
2. **Update ARCHITECTURE_DESIRED.md** ONLY if the goal itself changes (rare)

### After finishing a sprint
1. Write `documentation/sprint/sprintN/REVIEW.md`
2. Update `ROADMAP.md` — mark sprint as complete
3. Update contract docs if applicable
4. Commit and push

### Sprint directory structure
```
documentation/sprint/sprintN/
├── PLAN.md     ← written BEFORE the sprint
└── REVIEW.md   ← written AFTER the sprint
```

### REVIEW.md template
```markdown
# Sprint N Review — <Title>

**Sprint:** N
**Duration:** <date or date range>
**Status:** Complete

## Objective
## What We Shipped
## Key Metrics
## Incidents & Fixes During Rollout
## Architecture Before & After
## Design Decisions
## What We Didn't Do (and why)
## Completion Checklist
## What's Next
```

## Testing

Every sprint must ship with automated E2E tests following Team 2's pattern.

### Test structure
```
tests/
├── requirements.txt          # pytest, httpx, pytest-timeout
└── e2e/
    ├── conftest.py           # shared fixtures: dhs_client, ssot_client, prom_query
    ├── test_evaluator.py         # Sprint 1 — DHS running, metrics, health_summary written
    ├── test_root_cause.py        # Sprint 2 — root cause attribution in health_summary
    ├── test_transitions.py       # Sprint 3 — Kafka events, debounce, cooldown
    └── test_failure_scenarios.py # Sprint 4 — deployment failure, Kafka outage, etc.
```

### Running tests
```bash
# Install test deps:
pip install -r tests/requirements.txt

# All tests against k3s (default):
pytest tests/e2e/ -v

# Only Sprint 1 tests:
pytest tests/e2e/ -m sprint1 -v

# Against a different DHS:
DHS_API_URL=http://localhost:8080 pytest tests/e2e/ -v
```

### Convention
- **One test file per sprint feature area**
- **File-level `pytestmark = pytest.mark.sprintN`**
- **DHS tests read from SSOT** to verify health_summary was written correctly
- **DHS tests read from Prometheus** to verify DHS metrics (evaluations, transitions)
- **After deploying, always run the sprint's tests** to verify

## Quick Reference

```bash
ssh 5560 "sudo kubectl get pods -n dhs"                              # check DHS pods
ssh 5560 "sudo kubectl logs -n dhs deploy/dhs --tail=20"             # DHS logs
ssh 5560 "curl -s http://192.168.1.210:30900/health_summary?state=UNHEALTHY"  # check SSOT health
```

## Ports on 5560 (192.168.1.210)

| Port | Service | Namespace |
|------|---------|-----------|
| 30950 | DHS API (metrics + admin) | dhs |
| 30900 | SSOT API | ssot |
| 30800 | Calculator API | calculator |
| 30090 | Prometheus | observability |
| 30300 | Grafana | observability |
| 30443 | ArgoCD UI | argocd |
