# AutoDeck

AutoDeck is a small self-healing service demo. It contains a Python service chain, a deterministic recovery agent, and a React/Vite dashboard scaffold.

The current service flow is:

```text
Gateway (8001) -> Orders (8002) -> Inventory (8003)
                              |
                              v
                        Payment (8004)
```

## Current implementation

Implemented:

- four FastAPI services: Gateway, Orders, Inventory, and Payment
- `/health` endpoints for every service
- Gateway-to-Orders request forwarding
- Orders-to-Inventory stock checks
- Orders-to-Payment authorization
- service manifest at `backend/src/backend/manifests/services.json`
- deterministic diagnosis and source patching
- recovery restart logic in `backend/src/backend/agent/recovery.py`
- `python-dotenv` support for local configuration
- React 19 + Vite dashboard scaffold

The dashboard is still the default Vite interface. Live topology, event streaming, and recovery controls are planned next.

## Repository structure

```text
AutoDeck/
├── README.md
├── CONTEXT.md
├── .gitignore
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .python-version
│   ├── .env                 # local only, ignored by Git
│   └── src/backend/
│       ├── agent/
│       │   ├── diagnosis.py
│       │   ├── patch.py
│       │   └── recovery.py
│       ├── manifests/services.json
│       ├── services/
│       │   ├── gateway/main.py
│       │   ├── orders/main.py
│       │   ├── inventory/main.py
│       │   └── payment/main.py
│       ├── tools/validate_manifest.py
│       └── watcher_a/main.py
└── dashboard/
    ├── package.json
    ├── package-lock.json
    └── src/
```

Generated files such as `.venv/`, `__pycache__/`, `node_modules/`, build output, and `.env` files are ignored by Git.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- npm

## Backend setup

From the repository root:

```bash
cd backend
uv sync
```

The backend dependencies are defined in `backend/pyproject.toml`, including FastAPI, Uvicorn, OpenAI, and `python-dotenv`.

## Environment configuration

Create `backend/.env` for local service URLs:

```env
ORDERS_URL=http://127.0.0.1:8002
INVENTORY_URL=http://127.0.0.1:8003
PAYMENT_URL=http://127.0.0.1:8004
AUTODECK_AGENT_MODE=deterministic
AUTODECK_LOG_LEVEL=INFO
```

For OpenAI diagnosis mode, also configure:

```env
AUTODECK_AGENT_MODE=openai
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=your-model-name
```

Do not commit `.env` or API keys. The service modules call `load_dotenv()` and use shell environment variables when they are already set.

## Run the services

Open four terminals. Run every command from the `backend/` directory.

### Inventory

```bash
uv run uvicorn backend.services.inventory.main:app --host 127.0.0.1 --port 8003
```

### Payment

```bash
uv run uvicorn backend.services.payment.main:app --host 127.0.0.1 --port 8004
```

### Orders

```bash
uv run uvicorn backend.services.orders.main:app --host 127.0.0.1 --port 8002
```

### Gateway

```bash
uv run uvicorn backend.services.gateway.main:app --host 127.0.0.1 --port 8001
```

Start Inventory and Payment before Orders, and Orders before Gateway. Do not use `gateway:main`; Uvicorn needs the full import target ending in `:app`.

## Check service health

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8003/health
curl http://127.0.0.1:8004/health
```

Each service should return a healthy status response.

## Send a test order

```bash
curl -X POST http://127.0.0.1:8001/orders \
  -H "content-type: application/json" \
  -d '{"item_id":"widget","quantity":2}'
```

A successful response travels through Gateway, Orders, Inventory, and Payment.

## Run the recovery agent

The recovery CLI currently supports the Orders repair flow. Run it from `backend/`:

```bash
uv run python -m backend.agent.recovery \
  --service orders \
  --status-code 409 \
  --detail "insufficient inventory" \
  --request-json '{"item_id":"widget","quantity":10}'
```

The workflow:

1. reads the service manifest
2. diagnoses the known Orders failure
3. validates and applies an approved source replacement
4. stops the process listening on port `8002`
5. restarts Orders
6. waits for its health endpoint

The deterministic repair is approved only when the known seeded comparison is present. If the source is already repaired, the command correctly reports that no approved repair is available.

## Validate the manifest

```bash
uv run python -m backend.tools.validate_manifest
```

## Dashboard

From the repository root:

```bash
cd dashboard
npm install
npm run dev
```

Other frontend commands:

```bash
npm run build
npm run lint
npm run preview
```

## Design principles

- Keep service recovery deterministic and observable.
- Let diagnosis produce a structured decision rather than arbitrary file edits.
- Validate patch targets against the service manifest.
- Keep the dashboard independent from backend recovery internals.
- Build the live dashboard only after the service and recovery paths are reliable.

## Next steps

1. Add live service events and a relay/WebSocket endpoint.
2. Connect the dashboard to service health and recovery events.
3. Expand `watcher_a` into heartbeat-based process monitoring.
4. Add replay verification to the recovery workflow.
5. Replace the starter dashboard with the service topology UI.
