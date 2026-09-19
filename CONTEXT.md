# AutoDeck Project Context

## Project overview

AutoDeck is a small full-stack scaffold for a future **self-healing service dashboard**.

The project is being built incrementally around three ideas:

1. A small service topology that can be observed and intentionally broken.
2. A raw service manifest that acts as the initial registry of services.
3. An agentic patch/recovery flow that can inspect a failure, decide what should change, and apply a controlled repair.

The implementation should stay small and demonstrable. Do not build the complete self-healing platform up front.

---

## Current status

AutoDeck currently contains:

- a minimal FastAPI application
- a React 19 + Vite dashboard scaffold
- placeholder directories for the planned backend components
- a root `.gitignore`
- a `CONTEXT.md` describing the implementation plan

The distributed service mesh, raw service manifest, agentic patch flow, relay, watchers, and live dashboard integration are **planned work**.

The backend is being reorganized to use the **standard uv `src` layout**.

The canonical Python package location is:

```text
backend/src/backend/
```

There should not be a second copy of the Python application package at `backend/` alongside `src/backend/`.

---

# Repository structure

The target repository structure is:

```text
AutoDeck/
├── .gitignore
├── README.md
├── CONTEXT.md
│
├── backend/
│   ├── .python-version
│   ├── README.md
│   ├── pyproject.toml
│   ├── uv.lock
│   │
│   └── src/
│       └── backend/
│           ├── __init__.py
│           ├── main.py
│           │
│           ├── services/
│           │   ├── __init__.py
│           │   ├── gateway/
│           │   │   ├── __init__.py
│           │   │   └── main.py
│           │   ├── orders/
│           │   │   ├── __init__.py
│           │   │   └── main.py
│           │   └── inventory/
│           │       ├── __init__.py
│           │       └── main.py
│           │
│           ├── manifests/
│           │   └── services.json
│           │
│           ├── agent/
│           │   ├── __init__.py
│           │   └── patch.py
│           │
│           ├── relay/
│           │   └── __init__.py
│           │
│           ├── shared/
│           │   └── __init__.py
│           │
│           ├── tools/
│           │   └── __init__.py
│           │
│           ├── watcher_a/
│           │   └── __init__.py
│           │
│           └── watcher_b/
│               └── __init__.py
│
└── dashboard/
    ├── .gitignore
    ├── README.md
    ├── eslint.config.js
    ├── index.html
    ├── package.json
    ├── package-lock.json
    ├── public/
    │   ├── favicon.svg
    │   └── icons.svg
    ├── src/
    │   ├── App.css
    │   ├── App.jsx
    │   ├── index.css
    │   ├── main.jsx
    │   └── assets/
    │       ├── hero.png
    │       ├── react.svg
    │       └── vite.svg
    └── vite.config.js
```

### Important layout rule

The backend must follow the normal uv/Python `src` layout:

```text
backend/
├── pyproject.toml
└── src/
    └── backend/
        ├── __init__.py
        └── ...
```

Application code belongs under:

```text
backend/src/backend/
```

Do **not** create or maintain duplicate application packages such as:

```text
backend/services/
backend/agent/
backend/watcher_a/
backend/watcher_b/
backend/shared/
```

The `backend/src/backend/` tree is the canonical backend implementation.

Generated directories such as:

```text
backend/.venv/
backend/__pycache__/
dashboard/node_modules/
```

are local/generated files and should remain ignored by Git.

---

# Backend technology

The backend uses:

- Python
- uv
- FastAPI
- Uvicorn

The project should use the existing `backend/pyproject.toml` and uv dependency management.

The backend should remain dependency-light. Add dependencies only when an implementation phase actually requires them.

---

# Current backend

The initial FastAPI application is:

```text
backend/src/backend/main.py
```

The current basic endpoint is:

```http
GET /
```

with:

```json
{
  "status": "healthy"
}
```

The backend should be runnable through uv from the `backend/` directory.

For example:

```bash
cd backend
uv sync
uv run uvicorn backend.main:app --reload
```

The default development server is expected at:

```text
http://127.0.0.1:8000
```

---

# Dashboard

The dashboard is currently a default React/Vite scaffold.

It uses:

- React 19
- Vite
- ESLint

The dashboard is a separate frontend project and does **not** need to use uv.

Run it with:

```bash
cd dashboard
npm install
npm run dev
```

Available scripts include:

```bash
npm run build
npm run lint
npm run preview
```

The self-healing topology, service state, event stream, and recovery controls are future features.

---

# Intended service topology

The first service topology is:

```text
Gateway
   |
   v
Orders
   |
   v
Inventory
```

The three services are:

- Gateway
- Orders
- Inventory

Each service should eventually be independently runnable.

The services should initially be simple enough that their behavior can be understood and intentionally broken during the hackathon demo.

---

# Implementation strategy

The project must be implemented in the following order.

## Phase 1 — Service creation

**First, create the services.**

Implement the three basic services:

```text
backend/src/backend/services/gateway/
backend/src/backend/services/orders/
backend/src/backend/services/inventory/
```

Each service should have a clear entrypoint and a minimal API.

The first objective is simply to establish a working service topology.

At this stage:

- do not build the AI patcher
- do not build the watchers
- do not build WebSockets
- do not build the live dashboard integration
- do not over-engineer service discovery

The services should be independently runnable and testable.

The initial dependency direction is:

```text
Gateway -> Orders -> Inventory
```

---

## Phase 2 — Raw service manifest

**After the services exist, create the raw manifest.**

The first registry mechanism should be deliberately simple and deterministic.

Create:

```text
backend/src/backend/manifests/services.json
```

This is the raw service registry.

It should contain information needed to locate and understand the services, such as:

- service name
- service entrypoint
- service port
- health endpoint
- relevant API endpoints
- dependency information where required

The manifest is intentionally a plain/raw file.

It is not an AI-generated knowledge graph.

It is the initial source of truth that the later agentic system can inspect.

Example conceptual shape:

```json
{
  "services": [
    {
      "name": "inventory",
      "entrypoint": "backend.services.inventory.main:app",
      "port": 8003,
      "health": "/health"
    }
  ]
}
```

The exact fields should be decided during implementation based on the actual service interfaces.

The important design requirement is that the manifest describes the real services rather than duplicating undocumented assumptions.

---

# Phase 3 — Agentic patch implementation

**After the services and raw manifest are working, implement the agentic patch flow.**

The initial goal is not a complete autonomous self-healing platform.

The goal is a small, demonstrable agentic repair loop.

Conceptually:

```text
Failure
   |
   v
Agent inspects service + manifest + relevant source
   |
   v
Agent decides what needs to be changed
   |
   v
Controlled patch action
   |
   v
Restart / re-run service
   |
   v
Verify behavior
```

The agent should be responsible for **reasoning and judgment**.

Deterministic code should remain responsible for **actually modifying files and performing controlled actions**.

The initial implementation should therefore separate:

```text
agentic decision
```

from:

```text
deterministic patch execution
```

A planned location for this functionality is:

```text
backend/src/backend/agent/patch.py
```

Additional agent modules can be introduced later if the implementation requires them.

---

# Agentic patch boundary

The design principle is:

> **The agent decides what should be repaired; deterministic tooling performs the repair.**

The agent should be able to inspect:

- the service manifest
- the relevant source file
- the observed error
- the context needed to understand the failure

The deterministic patch layer should control:

- which files can be modified
- how a patch is applied
- validation of the resulting source
- restarting or re-running the affected service
- verification of the original failing behavior

Do not allow an unrestricted agent to arbitrarily manipulate the repository.

---

# Planned self-healing workflow

Once the initial three phases work, the project can evolve into the full self-healing workflow.

## Process recovery

1. A service registers and/or is represented by the service manifest.
2. A watcher detects a missing heartbeat or failed health check.
3. The service process is restarted.
4. The watcher waits for recovery.
5. Health is verified.
6. Recovery information is eventually sent to the dashboard.

## Application recovery

1. A service produces an application error.
2. The diagnosis agent inspects the error and relevant source.
3. The agent produces a structured repair decision.
4. A deterministic tool validates and applies the permitted patch.
5. The affected service is restarted.
6. The original failing request is replayed.
7. The result is verified.
8. The recovery is eventually shown in the dashboard.

These are later stages. They should not be implemented before the service + manifest + initial agentic patch foundation is working.

---

# Planned components

The following components are planned for later iterations:

### Services

```text
backend/src/backend/services/
├── gateway/
├── orders/
└── inventory/
```

### Manifest

```text
backend/src/backend/manifests/
└── services.json
```

### Agent

```text
backend/src/backend/agent/
└── patch.py
```

### Relay

A future relay/event layer for communicating service and recovery events:

```text
backend/src/backend/relay/
```

### Watcher A

A future process/health recovery component:

```text
backend/src/backend/watcher_a/
```

Its responsibility will be process-level recovery such as:

- health checking
- heartbeat monitoring
- process restart
- recovery verification

### Watcher B

A future application-level recovery component:

```text
backend/src/backend/watcher_b/
```

Its responsibility will be application-error diagnosis and repair orchestration.

### Shared

Common models, configuration, and event definitions can eventually live under:

```text
backend/src/backend/shared/
```

### Tools

Deterministic utilities can eventually live under:

```text
backend/src/backend/tools/
```

Examples may include:

- manifest handling
- source inspection
- controlled patch application
- validation
- instrumentation

---

# Development order

The implementation order is intentionally strict:

```text
1. Create services
        |
        v
2. Create raw service manifest
        |
        v
3. Implement agentic patch
        |
        v
4. Add deterministic verification
        |
        v
5. Add process recovery / watchers
        |
        v
6. Add relay/event transport
        |
        v
7. Connect live dashboard
        |
        v
8. Add richer self-healing behavior
```

Do not skip directly to the later architecture.

The first three phases form the minimum meaningful foundation.

---

# Development commands

## Backend

From the repository root:

```bash
cd backend
uv sync
```

Run the current application:

```bash
uv run uvicorn main:app --reload
```

Once the individual services are implemented, they should be run through their package paths, for example:

```bash
uv run uvicorn backend.services.inventory.main:app --port 8003
```

The exact ports should be kept consistent with the service manifest.

## Dashboard

```bash
cd dashboard
npm install
npm run dev
```

---

# Testing strategy

Testing should also be incremental.

## Phase 1

Verify that each service:

- starts successfully
- exposes its expected endpoints
- returns a valid health response
- performs its basic responsibility

## Phase 2

Verify that:

- `services.json` exists
- every registered service corresponds to a real implementation
- the manifest's entrypoints and ports match the services

## Phase 3

Verify the agentic patch workflow against a controlled failure:

```text
seeded failure
    ->
agent inspection
    ->
patch decision
    ->
deterministic patch
    ->
restart
    ->
verification
```

The patch system should fail safely when it cannot confidently determine or validate a repair.

---

# Git state and tracking

Do not commit generated/local files such as:

- Python bytecode
- `__pycache__/`
- `.venv/`
- `node_modules/`
- frontend build output
- local `.env` files
- editor metadata
- operating-system metadata

The root `.gitignore` should handle these generated artifacts.

`backend/uv.lock` should be committed once uv generates it for the project, so the backend dependency state is reproducible.

---

# Codex development rules

AutoDeck is intended to be built incrementally with Codex.

When asking Codex to implement a task:

1. Read `CONTEXT.md` first.
2. Inspect the existing repository before modifying files.
3. Follow the standard uv `src` layout.
4. Do not recreate duplicate backend packages outside `backend/src/backend/`.
5. Implement only the current phase.
6. Do not prematurely implement future architecture.
7. Prefer small, reviewable changes.
8. Run appropriate tests/checks after changes.
9. Report the files changed and what was verified.
10. Preserve working code unless the current task requires changing it.

---

# Immediate implementation task

The immediate implementation should start with **Phase 1: service creation**.

Codex should first inspect:

```text
README.md
CONTEXT.md
backend/pyproject.toml
backend/src/backend/
```

Then implement the three services under:

```text
backend/src/backend/services/
```

The immediate goal is:

```text
Gateway
Orders
Inventory
```

with a minimal working dependency flow:

```text
Gateway -> Orders -> Inventory
```

Do **not** implement the raw manifest yet.

Do **not** implement the agentic patch yet.

Those are the next phases after the service layer is verified.

---

# Definition of progress

The project is considered to have reached the first milestone when:

```text
[ ] Standard uv src layout is clean
[ ] Gateway service exists and runs
[ ] Orders service exists and runs
[ ] Inventory service exists and runs
[ ] Gateway -> Orders -> Inventory flow works
[ ] Basic service tests/checks pass
```

Then proceed to:

```text
[ ] Raw services.json manifest
[ ] Manifest matches actual services
```

Then:

```text
[ ] Agentic patch implementation
[ ] Controlled deterministic patch application
[ ] Verification after patch
```

Only after these foundations are stable should the project expand into watchers, relay/event transport, and the live dashboard.
