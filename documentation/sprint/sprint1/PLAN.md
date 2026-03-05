# Sprint 1 — Evaluator Loop + State Engine (Core)

**Goal:** Stand up the DHS service from scratch. After this sprint, DHS runs an evaluation loop that queries Prometheus, evaluates YAML-defined health rules for every SSOT entity, detects state transitions with debounce, and writes health_summary to SSOT only on transitions.

**Status:** Not Started
**Depends on:** Team 3 Sprint 1 (Prometheus), Team 4 Sprint 1 (SSOT API with entities + health_summary)

---

## Pre-Sprint State

- Nothing exists. No namespace, no service, no code.

## Post-Sprint State

- `dhs` namespace exists in k3s
- DHS Python service running as Deployment
- YAML health rules loaded from `rules/` at startup
- Evaluator loop runs every 30s (configurable)
- Prometheus client queries metrics for each entity
- State engine compares derived state vs SSOT current state
- Debounce: condition must hold for configured duration before transition
- SSOT writer: `PUT /health_summary` only on transitions
- Prometheus metrics exposed at `/metrics`
- Structured JSON logging
- Health probe at `/health`
- Accessible at `http://192.168.1.210:30950`

---

## Milestones

### Milestone 1 — Create dhs namespace + project structure

**Status:** [ ] Not Started

**`k8s/namespace.yaml`:**
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: dhs
  labels:
    team: team5
    purpose: dhs
```

**`apps/dhs/requirements.txt`:**
```
fastapi==0.115.0
uvicorn==0.30.6
httpx==0.27.2
pyyaml==6.0.2
jinja2==3.1.4
prometheus-client==0.21.0
python-json-logger==2.0.7
```

**`apps/dhs/Dockerfile`:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**`apps/dhs/config.py`:**
- Load all config from env vars with defaults:
  - `EVAL_INTERVAL_SECONDS` = 30
  - `PROMETHEUS_URL` = `http://prometheus.observability:9090`
  - `SSOT_API_URL` = `http://ssot-api.ssot:8080`
  - `DEBOUNCE_DEGRADED_SECONDS` = 60
  - `DEBOUNCE_UNHEALTHY_SECONDS` = 60
  - `DEBOUNCE_HEALTHY_SECONDS` = 90
  - `RULES_DIR` = `/app/rules`

**Files to create:**
- `k8s/namespace.yaml`
- `apps/dhs/requirements.txt`
- `apps/dhs/Dockerfile`
- `apps/dhs/config.py`

---

### Milestone 2 — Prometheus query client

**Status:** [ ] Not Started

**`apps/dhs/prometheus_client.py`:**
- Async HTTP client using `httpx` to query Prometheus
- `async def query_instant(promql: str) -> float | None`
  - `GET /api/v1/query?query={promql}`
  - Parse response: `data.result[0].value[1]` → float
  - Return `None` if no result or error
- `async def query_range(promql: str, start, end, step) -> list` (for future use)
- Instrument with `dhs_prometheus_query_duration_seconds` histogram
- Structured logging: log query, result, duration
- Handle timeouts gracefully (5s timeout per query)

**Files to create:**
- `apps/dhs/prometheus_client.py`

**Verification:**
```python
# Manual test in Python REPL or test script:
client = PrometheusClient("http://192.168.1.210:30090")
result = await client.query_instant("up")
# Should return 1.0 if Prometheus is scraping itself
```

---

### Milestone 3 — SSOT API client

**Status:** [ ] Not Started

**`apps/dhs/ssot_client.py`:**
- Async HTTP client using `httpx` to interact with SSOT API
- `async def get_entities(type: str = None, env: str = None) -> list[dict]`
  - `GET /entities?type={type}&env={env}`
- `async def get_entity(entity_id: str) -> dict`
  - `GET /entities/{entity_id}`
- `async def get_relationships(entity_id: str, type: str = None) -> list[dict]`
  - `GET /relationships?entity_id={entity_id}&type={type}`
- `async def get_health_summary(entity_id: str) -> dict | None`
  - `GET /health_summary/{entity_id}`
- `async def put_health_summary(payload: dict) -> bool`
  - `PUT /health_summary` with JSON body
  - **Must include `X-DHS-Key: dhs-secret-key` header** (required by SSOT API for health_summary writes)
  - Returns True on success, False on failure
- Auth header configurable via env var: `DHS_API_KEY` (default: `dhs-secret-key`)
- Instrument with `dhs_ssot_writes_total` counter (success/failure labels)
- Structured logging: log entity_id, operation, status

**Files to create:**
- `apps/dhs/ssot_client.py`

**Verification:**
```bash
# Requires SSOT API running:
ssh 5560 "curl -s http://192.168.1.210:30900/entities?type=Service"
# Should return entities if SSOT is populated
```

---

### Milestone 4 — Health rule loader

**Status:** [ ] Not Started

**`apps/dhs/rule_loader.py`:**
- Load YAML files from `rules/` directory at startup
- Parse each rule file into `HealthRule` dataclass:
  ```python
  @dataclass
  class HealthRule:
      name: str
      entity_type: str
      match_labels: dict | None  # optional label filter
      state: str  # HEALTHY, DEGRADED, UNHEALTHY
      duration: int  # seconds — debounce duration
      promql: str  # Jinja2 template with {{ namespace }}, {{ name }}
      threshold: float
      operator: str  # ">", "<", ">=", "<=", "=="
      reason: str  # Jinja2 template
      # For dual-query rules (available vs desired):
      promql_desired: str | None
      promql_available: str | None
  ```
- `load_rules(rules_dir: str) -> dict[str, list[HealthRule]]`
  - Returns mapping: entity_type → list of rules
  - Rules ordered by severity: UNHEALTHY first, then DEGRADED
- Jinja2 template rendering: `render_promql(rule, entity) -> str`
  - Substitutes `{{ namespace }}`, `{{ name }}`, etc. from entity metadata
- Log loaded rules count per entity type at startup

**Files to create:**
- `apps/dhs/rule_loader.py`

**Verification:**
```python
rules = load_rules("rules/")
assert "Deployment" in rules
assert rules["Deployment"][0].name == "replica_unavailable"
```

---

### Milestone 5 — State engine with debounce

**Status:** [ ] Not Started

**`apps/dhs/state_engine.py`:**
- In-memory state tracking per entity:
  ```python
  @dataclass
  class EntityState:
      entity_id: str
      current_state: str  # from SSOT (last written)
      derived_state: str  # from latest evaluation
      derived_since: datetime | None  # when derived state first appeared
      reason: str
  ```
- `class StateEngine`:
  - `entity_states: dict[str, EntityState]` — in-memory cache
  - `def update(entity_id, derived_state, reason) -> Transition | None`
    - If derived_state == current_state → no transition, return None
    - If derived_state != current_state:
      - If first time seeing this new state → record `derived_since = now()`
      - If `derived_since` + debounce_duration < now() → transition confirmed!
        - Return `Transition(entity_id, old_state, new_state, reason, since)`
        - Update `current_state` to `derived_state`
      - Else → still debouncing, return None
    - If derived_state flips back to current_state before debounce → reset `derived_since`
  - Debounce durations from config:
    - To UNHEALTHY: `DEBOUNCE_UNHEALTHY_SECONDS` (default 60s)
    - To DEGRADED: `DEBOUNCE_DEGRADED_SECONDS` (default 60s)
    - To HEALTHY: `DEBOUNCE_HEALTHY_SECONDS` (default 90s — longer for recovery)

- `@dataclass Transition`:
  ```python
  entity_id: str
  old_state: str
  new_state: str
  reason: str
  since: datetime
  transition_time: datetime
  ```

- Instrument: `dhs_transitions_total` counter (entity_type, old_state, new_state)

**Files to create:**
- `apps/dhs/state_engine.py`

---

### Milestone 6 — Evaluator loop + SSOT writer

**Status:** [ ] Not Started

**`apps/dhs/evaluator.py`:**
- `class Evaluator`:
  - `__init__(prometheus, ssot, rules, state_engine)`
  - `async def run_cycle()`:
    1. Fetch all entities from SSOT (grouped by type)
    2. For each entity:
       a. Find matching rules by entity type (and labels if `match_labels` set)
       b. Render PromQL templates with entity context
       c. Query Prometheus for each rule's signal
       d. Evaluate rule: compare value against threshold using operator
       e. First matching rule (ordered by severity) wins → derived state
       f. If no rule triggers → derived state = HEALTHY
       g. Pass (entity_id, derived_state, reason) to state_engine.update()
       h. If transition returned → write to SSOT via ssot_client.put_health_summary()
    3. Log cycle summary: entities evaluated, transitions fired
  - `async def run_loop()`:
    - `while True: await run_cycle(); await asyncio.sleep(EVAL_INTERVAL_SECONDS)`
    - Catch and log exceptions per cycle (never crash the loop)

- Instrument:
  - `dhs_evaluations_total` counter (entity_type)
  - `dhs_evaluation_duration_seconds` histogram

**`apps/dhs/main.py`:**
- FastAPI app with:
  - `GET /` — service status (name, version, uptime, eval_count)
  - `GET /health` — readiness probe (True if at least one eval cycle completed)
  - `GET /metrics` — Prometheus metrics
  - Startup event: load rules, create clients, create state engine, start evaluator loop as background task
  - Shutdown event: cancel evaluator loop
  - Structured JSON logging setup

**Files to create:**
- `apps/dhs/evaluator.py`
- `apps/dhs/main.py`

**Verification:**
```bash
# After deploying:
ssh 5560 "sudo kubectl logs -n dhs deploy/dhs --tail=30"
# Should see evaluation cycle logs with entity_id, derived_state, reason

# Check SSOT for health writes:
ssh 5560 "curl -s http://192.168.1.210:30900/health_summary | python3 -m json.tool"
# Should see health states written by DHS
```

---

### Milestone 7 — Deploy DHS to k3s

**Status:** [ ] Not Started

**`k8s/dhs/deployment.yaml`:**
- Image: `ghcr.io/<repo>/dhs:latest`
- Namespace: `dhs`
- Port: 8080
- Env:
  - `PROMETHEUS_URL=http://prometheus.observability:9090`
  - `SSOT_API_URL=http://ssot-api.ssot:8080`
  - `EVAL_INTERVAL_SECONDS=30`
  - `DEBOUNCE_DEGRADED_SECONDS=60`
  - `DEBOUNCE_UNHEALTHY_SECONDS=60`
  - `DEBOUNCE_HEALTHY_SECONDS=90`
  - `RULES_DIR=/app/rules`
- Volume mount: rules ConfigMap → `/app/rules`
- Readiness probe: `GET /health` on port 8080
- Liveness probe: `GET /health` on port 8080
- Resource limits: 100m CPU, 128Mi memory
- Labels (per `manager/standards.md`):
    ```yaml
    app.kubernetes.io/name: dhs
    app.kubernetes.io/component: evaluator
    app.kubernetes.io/part-of: dhs
    team: team5
    env: lab
    ```

**`k8s/dhs/service.yaml`:**
- NodePort 30950 → port 8080

**`k8s/dhs/configmap-rules.yaml`:**
- ConfigMap containing all rules YAML files
- Mounted into the container at `/app/rules`

**Files to create:**
- `k8s/dhs/deployment.yaml`
- `k8s/dhs/service.yaml`
- `k8s/dhs/configmap-rules.yaml`

**Verification:**
```bash
ssh 5560 "sudo kubectl get pods -n dhs"
ssh 5560 "curl -s http://192.168.1.210:30950/"
ssh 5560 "curl -s http://192.168.1.210:30950/health"
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | head -10"
```

---

### Milestone 8 — Smoke test: evaluator + transitions

**Status:** [ ] Not Started

Run a comprehensive smoke test to prove the evaluation loop and transition logic work:

```bash
# 1. Verify DHS is running and evaluating:
ssh 5560 "sudo kubectl logs -n dhs deploy/dhs --tail=50"
# Should see periodic evaluation cycles

# 2. Check that DHS wrote health_summary to SSOT:
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary' | python3 -m json.tool"
# Should show entities with health states

# 3. Check specific entity health:
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Deployment:api' | python3 -m json.tool"
# Should show health_state, reason, since, confidence

# 4. Verify DHS metrics:
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_"
# Should show dhs_evaluations_total, dhs_evaluation_duration_seconds, dhs_transitions_total, dhs_ssot_writes_total

# 5. Verify no spam — check transition count:
ssh 5560 "curl -s http://192.168.1.210:30950/metrics | grep dhs_transitions_total"
# Should be a small number (initial transitions only), not growing every cycle

# 6. Manual transition test — scale a deployment to 0 and watch:
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=0"
# Wait 90s (debounce)
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Deployment:api' | python3 -m json.tool"
# Should show UNHEALTHY
ssh 5560 "sudo kubectl scale deployment api -n calculator --replicas=1"
# Wait 120s (recovery debounce)
ssh 5560 "curl -s 'http://192.168.1.210:30900/health_summary/k8s:lab:calculator:Deployment:api' | python3 -m json.tool"
# Should show HEALTHY
```

All tests must pass. Fix any issues before proceeding.

---

### Milestone 9 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 1 as complete
- Write `documentation/sprint/sprint1/REVIEW.md`

**Files to modify:**
- `documentation/sprint/ROADMAP.md`

**Files to create:**
- `documentation/sprint/sprint1/REVIEW.md`

---

## Design Decisions

| Decision | Rationale | Why not X |
|----------|-----------|-----------|
| Python 3.12 / FastAPI | Same stack as SSOT API and Calculator API. Async-first. Team familiarity. | Go: different language. Node: less common for infra tools. |
| httpx for HTTP clients | Async, modern, well-tested. Drop-in replacement for requests. | aiohttp: more complex API. requests: synchronous. |
| YAML rules (not hardcoded) | Rules can change without code deploy. Easy to add new entity types. | Python code: requires redeploy for threshold changes. DB-stored: over-engineering for MVP. |
| Jinja2 for PromQL templates | Simple, well-known, handles `{{ namespace }}` substitution cleanly. | f-strings: can't load from YAML. Custom parser: unnecessary. |
| In-memory state engine | DHS is single-instance. State is derived, not authoritative (SSOT is). Memory is fast. | Redis: adds infra for no benefit. Postgres: DHS doesn't need its own DB. |
| Write-on-transition only | Prevents SSOT spam. SSOT health_summary is a clean log of state changes. | Write every cycle: floods SSOT, makes health_summary useless as event log. |
| ConfigMap for rules | Rules version-controlled in git, deployed via ArgoCD alongside DHS. | PVC: overkill. Baked into image: requires rebuild for rule changes. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `k8s/namespace.yaml` | dhs namespace |
| `k8s/dhs/deployment.yaml` | DHS deployment |
| `k8s/dhs/service.yaml` | NodePort 30950 |
| `k8s/dhs/configmap-rules.yaml` | Health rules mounted as volume |
| `apps/dhs/main.py` | FastAPI application |
| `apps/dhs/config.py` | Environment config |
| `apps/dhs/prometheus_client.py` | Prometheus query client |
| `apps/dhs/ssot_client.py` | SSOT API client |
| `apps/dhs/rule_loader.py` | YAML rule parser |
| `apps/dhs/state_engine.py` | Debounced transition logic |
| `apps/dhs/evaluator.py` | Main evaluation loop |
| `apps/dhs/requirements.txt` | Python dependencies |
| `apps/dhs/Dockerfile` | Container image |
| `rules/deployment.yaml` | Deployment health rules |
| `rules/service-api.yaml` | API service health rules |
| `rules/service-worker.yaml` | Worker service health rules |
| `rules/kafka.yaml` | Kafka health rules |
| `rules/database.yaml` | Database health rules |
| `rules/node.yaml` | Node health rules |
| `documentation/sprint/sprint1/REVIEW.md` | Sprint retrospective |
