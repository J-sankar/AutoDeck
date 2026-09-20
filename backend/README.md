# AutoDeck backend

The backend uses a `src` layout. Run commands from this directory with `uv`:

```bash
uv sync
uv run python -m compileall -q src/backend
uv run python -m backend.tools.validate_manifest
```

Application code lives only under `src/backend/`.

## Main processes

| Process | Module | Port |
| --- | --- | ---: |
| Control plane | `backend.main:app` | 8000 |
| Gateway | `backend.services.gateway.main:app` | 8001 |
| Orders | `backend.services.orders.main:app` | 8002 |
| Inventory | `backend.services.inventory.main:app` | 8003 |
| Payment | `backend.services.payment.main:app` | 8004 |
| Relay | `backend.relay.main:app` | 8005 |

The recommended lifecycle is managed from the repository root:

```bash
make demo-up
make demo-status
make restart SERVICE=orders
make demo-down
```

Manual processes use `uv run uvicorn ...` with the import targets above. Do not use `--reload` during a recovery demo because patching service source can interrupt the relay SSE stream.

## Agents and watchers

```bash
uv run python -m backend.watcher_a.main
uv run python -m backend.watcher_b.main
uv run python -m backend.agent.recovery \
  --service orders \
  --status-code 409 \
  --detail 'insufficient inventory' \
  --request-json '{"item_id":"widget","quantity":10}'
```

Watcher A handles process and health recovery. Watcher B handles application failures and is diagnose-only unless `AUTODECK_AUTO_REPAIR=true`.

## Key files

- `src/backend/manifests/services.json` — service registry and source metadata
- `src/backend/registry/` — Tree-sitter schema generation and instrumentation
- `src/backend/relay/` — events, SSE, and topology
- `src/backend/agent/` — diagnosis, patch validation, and recovery
- `src/backend/tools/runtime.py` — managed demo lifecycle
