# Copy-Paste Prompt for Team 5 — DHS Agent

> Copy everything below this line and paste it as the first message to a new Claude Code session
> pointed at the `team5/dhs` directory.

---

You are the DHS (Derived Health System) engineer. Your job is to build the brain of the platform — converting raw telemetry and topology into health states with root-cause attribution.

## Start Here

1. Read `CLAUDE.md` — your operating instructions, what you own, what you don't, deployment flow
2. Read `documentation/progress/ARCHITECTURE_DESIRED.md` — the target specification
3. Read `documentation/sprint/ROADMAP.md` — sprint sequence and what's done vs remaining
4. Read `documentation/sprint/sprint1/PLAN.md` — your concrete work for this session

**The code in `apps/` IS the current architecture.** What doesn't exist isn't built yet.

## What You're Building

1. **Evaluator Loop** (Sprint 1) — runs every 30s, queries Prometheus, evaluates health rules, derives health state per entity
2. **State / Transition Engine** (Sprint 1) — compares derived vs stored state, debounces transitions, writes SSOT only on change
3. **SSOT Writer** (Sprint 1) — `PUT /health_summary` to SSOT API on transitions
4. **Kafka Emitter** (Sprint 1) — publishes `health.transition.v1` events
5. **Root Cause Resolver** (Sprint 2) — traverses SSOT topology to attribute root cause
6. **Event Ingestor** (Sprint 3) — consumes K8s events (CrashLoop, OOMKilled) to enrich reason text

## Tech Stack

- **Language:** Python 3.12
- **Prometheus client:** `httpx` or `requests` (query API, not scraping)
- **Kafka:** `aiokafka`
- **SSOT client:** `httpx` (REST calls)
- **K8s client:** `kubernetes` (Python client)
- **Port:** NodePort 30950 (metrics + admin)

## Key Files to Create

- `apps/dhs/main.py` — main service entrypoint
- `apps/dhs/evaluator.py` — evaluation loop
- `apps/dhs/state_engine.py` — transition logic + debounce
- `apps/dhs/root_cause.py` — topology-based root cause resolver
- `apps/dhs/ssot_client.py` — SSOT API client
- `apps/dhs/kafka_emitter.py` — Kafka event publisher
- `rules/` — already written ✓ (6 YAML rule files)

## What You Read

| Source | URL (in-cluster) | What |
|--------|-----------------|------|
| Prometheus | `http://prometheus.observability:9090/api/v1/query` | Metric queries |
| SSOT API | `http://ssot-api.ssot:8080` | Entities, topology, ownership, current health |

## What You Write

| Target | URL / Topic | What |
|--------|-------------|------|
| SSOT API | `http://ssot-api.ssot:8080/health_summary` | Health state on transitions |
| Kafka | `health.transition.v1` | Transition events with ownership |

## Health Rules

Rules are in `rules/` (already written). Each YAML file maps an entity type to signals and thresholds. Your evaluator loads these at startup. See `documentation/contracts/HEALTH_STATES.md` for state definitions and transition logic.

## Machines

- **This PC (Windows):** Dev machine — write code, push to GitHub
- **Lenovo 5560 (Ubuntu 24.04):** `ssh 5560` (IP: `192.168.1.210`) — runs k3s

## Prerequisites

DHS depends on these being deployed first:
- Team 3 Prometheus must be running (you query it for metrics)
- Team 4 SSOT API must be running (you read topology, write health states)

## Cross-Team Interfaces

| Team | What They Need From You |
|------|------------------------|
| Team 6 (Actions) | `health.transition.v1` Kafka events — see `documentation/contracts/KAFKA_EVENTS.md` |
| Team 4 (SSOT) | Correct `PUT /health_summary` payload — see `documentation/contracts/HEALTH_STATES.md` |
| Team 3 (Observability) | Use recording rules where available — see their `METRICS_CONTRACT.md` |

## Working Convention

After each milestone: mark `[x] Done` in Sprint 1 `PLAN.md`.
After finishing a sprint: write `REVIEW.md`, update `ROADMAP.md`, update contract docs if event schema changed, commit and push.

Begin by reading the files listed in "Start Here", then execute Sprint 1 milestones in order.
