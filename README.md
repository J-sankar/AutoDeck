# AutoDeck

AutoDeck is a hackathon-style project for demonstrating a self-healing service dashboard. The goal is to simulate a small distributed system where service health, error events, and recovery workflows are visible in a live UI.

The project is intentionally split into two parts:
- a Python backend for orchestration, event flow, and service simulation
- a React + Vite dashboard for visualizing topology, events, and recovery actions

## Project goal

The core concept is simple:
- detect unhealthy or failed services
- diagnose application-level errors
- recover automatically through a controlled workflow
- surface the full process in a dashboard for demonstration and debugging

This project is designed as a demo for ideas around:
- process-level self-healing
- AI-assisted diagnosis with deterministic execution
- event-driven service topology
- simple observability dashboards

## Current repo status

This workspace is currently scaffolded, but the full backend logic and service mesh are still under construction.

The repository already contains:
- a Python backend package initialized with uv
- a React/Vite frontend dashboard
- the project-level README and junior structure for expanding the system

The repository is not yet a complete running distributed system; it is a strong foundation for building one.

## Repository structure

```text
AutoDeck/
├── backend/
│   ├── pyproject.toml
│   ├── README.md
│   └── src/
│       └── backend/
│           └── __init__.py
├── dashboard/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── public/
│   └── src/
│       ├── App.jsx
│       ├── App.css
│       ├── index.css
│       └── main.jsx
├── README.md
└── .gitignore
```

## Architecture direction

The intended architecture is:

```text
Dashboard (React/Vite)
        |
        | WebSocket / event stream
        v
Relay / event bus
        |
   +----+----+
   |         |
   v         v
Services   Watchers
(gateway)  (process + diagnosis)
```

The long-term behavior is expected to include:
- service registration on startup
- heartbeat monitoring
- automatic restart of failed processes
- simulated application errors
- diagnosis workflow based on structured decisions
- deterministic source-code patching or recovery logic
- live topology and event updates in the dashboard

## Planned backend components

The system is intended to include a small service mesh such as:
- Gateway service
- Orders service
- Inventory service
- Relay/event transport
- Watcher A for process recovery
- Watcher B for diagnosis and repair flow

The project aims to stay simple and hackathon-friendly rather than building a large production system.

## Planned dashboard features

The dashboard should eventually provide:
- service topology view
- health and state indicators
- live event timeline
- failure injection controls
- process restart/recovery visibility

## Tech stack

### Backend
- Python 3.11+
- uv for dependency management
- FastAPI (planned)
- WebSockets / event stream (planned)
- AI-assisted diagnosis logic (planned)
- deterministic repair tooling (planned)

### Frontend
- React
- Vite
- ESLint

## Prerequisites

Before starting development, install:
- Python 3.11+
- uv
- Node.js 18+
- npm

## Getting started

### 1) Set up the backend

From the project root:

```bash
cd backend
uv sync
```

The backend package is currently a scaffold, so additional service modules and runtime entrypoints will be added as the app evolves.

### 2) Set up the dashboard

From the project root:

```bash
cd dashboard
npm install
npm run dev
```

This starts the Vite development server for the frontend UI.

### 3) Run the backend application

Once the backend service entrypoints are implemented, the app can be launched with:

```bash
cd backend
uv run python -m backend
```

If the project later grows into dedicated service modules, the runtime commands will be updated to match the concrete app structure.

## Development notes

A few important design principles for this project:

- keep the event model small and explicit
- prefer deterministic recovery steps over arbitrary file editing
- separate AI judgment from code execution
- build telemetry and topology from observed runtime behavior

This makes the demo easier to reason about and more convincing as a self-healing system.

## Recommended next steps

1. scaffold backend service modules and event bus
2. implement service registration and heartbeat flow
3. add simple failure injection for a service
4. build the dashboard topology and log timeline
5. add a deterministic diagnosis/recovery workflow
6. connect live events from backend to frontend

## Summary

AutoDeck is a lightweight, demo-oriented project for exploring self-healing service patterns in a small distributed system. It currently exists as a solid scaffold for both the backend and frontend, with the architecture and workflow intentionally designed for a future live demonstration.

This README will continue to be refined as the backend services, event model, and recovery logic are implemented.

       ↓
5. Generate normal traffic
       ↓
6. Dashboard shows live calls
       ↓
7. Kill a service
       ↓
8. Watcher A detects it
       ↓
9. Watcher A respawns it
       ↓
10. Health verification succeeds
       ↓
11. Inject application bug
       ↓
12. Request fails
       ↓
13. Watcher B receives error
       ↓
14. Agent analyzes failure
       ↓
15. Structured diagnosis returned
       ↓
16. Deterministic patch applied
       ↓
17. Service restarted
       ↓
18. Original request replayed
       ↓
19. Verification succeeds
       ↓
20. Dashboard shows complete recovery trace
This sequence is the main hackathon story.
17. Build Order
Implement in this exact order initially.
Phase 1 — Foundation
- Create repository
- Create backend/
- Initialize uv
- Create dashboard/
- Initialize React/Vite
- Create shared configuration
Phase 2 — Services
- Gateway service
- Orders service
- Inventory service
- Health endpoints
- Service registration
- Inter-service requests
- Seeded application bug
Phase 3 — Process Recovery
- Heartbeat system
- Watcher A
- Process spawning
- Process termination detection
- Respawn
- Recovery verification
Phase 4 — Relay
- Event model
- WebSocket relay
- Backend event publishing
- Dashboard WebSocket client
Phase 5 — Dashboard
- Service list
- Health state
- Topology graph
- Event stream
- Kill Service button
- Inject Bug button
Phase 6 — Static Analysis
- Manifest extractor
- Function discovery
- Route discovery
- Dependency classification
Phase 7 — AI Diagnosis
- Error context collection
- Agent prompt
- Structured agent response
- Diagnosis display
Phase 8 — Deterministic Patching
- Patch validation
- Patch application
- Service restart
- Original request replay
- Verification
Phase 9 — Demo Polish
- Recovery animations
- Diagnosis trace
- Failure states
- Clear status indicators
- One-command startup
- Reliable demo reset
18. Time-Constrained Fallback Plan
If hackathon time becomes limited, prioritize functionality over UI polish.
Fallback order:
1. Watcher A heartbeat/respawn
2. Watcher B diagnosis + one patch round
3. Live reasoning/diagnosis trace
4. Simple dashboard status list
5. Full topology graph
6. Dynamic topology discovery
7. Auto-instrumentation
8. Advanced dependency classification
The minimum viable demonstration should be:
Service dies
    ↓
Watcher detects it
    ↓
Service automatically restarts
    ↓
Recovery is verified
    ↓
Dashboard shows the recovery
Then, if possible, add:
Application bug
    ↓
AI diagnosis
    ↓
Deterministic patch
    ↓
Restart
    ↓
Replay
    ↓
Verified recovery
19. Development Principles
Keep components independently runnable
The dashboard should still be usable if advanced AI diagnosis is unavailable.
Watcher A should work without Watcher B.
Static analysis should work without the dashboard.
The relay should not contain application-specific recovery logic.
Prefer deterministic infrastructure
Use normal code for:
- health checks
- process management
- validation
- patch application
- event serialization
- service registration
- request replay
Use AI primarily for:
- diagnosis
- selecting relevant code
- explaining likely root cause
- deciding what deterministic operation should be performed
Optimize for a live demo
Every major feature should be demonstrable in seconds.
Avoid features that require complicated manual setup during the presentation.
20. Initial Commands
At repository root:
mkdir self-healing-dashboard
cd self-healing-dashboard

mkdir backend dashboard
Initialize backend:
cd backend
uv init
Return to root:
cd ..
The frontend can later be initialized separately with Vite.
21. Current Implementation Status
At the beginning of implementation:
Architecture:             Defined
Repository structure:     Defined
README/context:           Defined

Services:                 Not implemented
Relay:                    Not implemented
Watcher A:                Not implemented
Watcher B:                Not implemented
Agent:                    Not implemented
Static analysis:          Not implemented in Python version
Instrumentation:          Not implemented
Dashboard:                Not implemented
The project should now move from architecture into implementation.
22. Important Constraint
Do not prematurely implement every component.
Build vertically and verify each stage.
Preferred progression:
Gateway
  ↓
Orders
  ↓
Inventory
  ↓
Health
  ↓
Registration
  ↓
Heartbeat
  ↓
Watcher A
  ↓
Relay
  ↓
Dashboard
  ↓
Failure injection
  ↓
Watcher B
  ↓
AI diagnosis
  ↓
Patch
  ↓
Verification
Each stage should work before moving to the next.
23. Reference Design Decisions
The original project design establishes these important principles:
- Services self-register.
- The graph should reflect observed behavior.
- Two independent watchers handle process and application failures.
- The AI agent provides judgment.
- Deterministic tools perform source manipulation.
- Components should degrade gracefully.
- A working recovery loop is more important than a large collection of unfinished features.
These principles should remain stable while implementation details evolve.
24. Current Goal
The immediate goal is not to build the complete dashboard.
The immediate goal is:
Create the Python uv backend, implement three independently running services, establish health endpoints and inter-service communication, and introduce one deterministic seeded application failure.

Once that works, implement Watcher A and build upward from there.