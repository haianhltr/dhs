# Team 5 — DHS Sprint 3 Session Prompt

> Copy everything below this line and paste it as the first message to a new Claude Code session pointed at the `team5/dhs` directory.

---

You are the DHS (Derived Health System) engineer. You are executing **Sprint 3 — Kafka Event Emitter + Transition Polish**.

## Start Here

1. Read `CLAUDE.md` — your operating instructions
2. Read `documentation/progress/ARCHITECTURE_DESIRED.md` — target specification
3. Read `documentation/sprint/ROADMAP.md` — sprint sequence (Sprints 1-2 are COMPLETE)
4. Read `documentation/sprint/sprint3/PLAN.md` — **your concrete work for this session**
5. Read the current source code in `apps/dhs/` — this IS the current architecture

## What You're Doing This Sprint

Sprint 3 adds Kafka event emission so team6 (Actions) can consume health transition events. This is the **critical path to Gate 4** — team6 is blocked until this ships.

### 7 Milestones (execute in order):

1. **Kafka producer module** — `kafka_emitter.py` using `aiokafka`
2. **Ownership lookup** — Add `get_ownership()` to `ssot_client.py` + per-cycle cache
3. **Evaluator integration** — Wire Kafka emitter into the evaluation loop
4. **Cooldown + flap detection** — Enhance `state_engine.py` with cooldown timer + flap suppression
5. **Deploy + create Kafka topic** — K8s manifests, topic creation, verification
6. **E2E tests** — `test_transitions.py` with 6 test cases
7. **Docs + review** — ROADMAP.md, KAFKA_EVENTS.md updates, REVIEW.md

## Key Technical Context

- **Kafka broker:** `kafka.calculator.svc.cluster.local:9092` (cross-namespace FQDN)
- **Topic:** `health.transition.v1` (3 partitions, 24h retention)
- **Dependency:** `aiokafka` (add to requirements.txt)
- **SSOT ownership endpoint:** `GET /ownership/{entity_id}` returns `{team, tier, contact}` or 404
- **Auth for SSOT writes:** `X-DHS-Key: dhs-secret-key` (already configured)
- **Version bump:** Update to `0.3.0` for this sprint

## Critical Architecture Note

The `Transition` dataclass (state_engine.py) has `root_cause_entity_id` but does NOT have `root_cause_entity_name` or `confidence`. Those fields live on the `RootCause` dataclass (root_cause.py). When building Kafka event payloads, use:
- `root_cause.entity_name` for `root_cause_entity_name`
- `root_cause.confidence` for `confidence`

The `rc: RootCause` variable is already in scope in `evaluator.py:_evaluate_entity()` — pass it to the emitter.

## Machines

- **This PC (Windows):** Write code, push to GitHub (`haianhltr/dhs`)
- **Lenovo 5560 (Ubuntu 24.04):** `ssh 5560` (IP: 192.168.1.210) — runs k3s

## Deployment Flow

```
Edit code → git push origin main → GitHub Actions builds image → ArgoCD deploys (~3 min)
```

## After Each Milestone

Mark `[x] Done` in `documentation/sprint/sprint3/PLAN.md`.

## After Finishing Sprint

1. Write `documentation/sprint/sprint3/REVIEW.md`
2. Update `documentation/sprint/ROADMAP.md` — mark Sprint 3 complete
3. Update `documentation/contracts/KAFKA_EVENTS.md` if schema changed
4. Commit and push
5. Report completion to manager — Gate 4 prerequisite met

Begin by reading the files listed in "Start Here", then execute the milestones in order.
