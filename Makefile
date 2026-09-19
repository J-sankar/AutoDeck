.PHONY: relay gateway orders inventory payment watcher-a watcher-b services dashboard stop

BACKEND_DIR := backend

relay:
	cd $(BACKEND_DIR) && uv run uvicorn backend.relay.main:app --host 127.0.0.1 --port 8005

gateway:
	cd $(BACKEND_DIR) && uv run uvicorn backend.services.gateway.main:app --host 127.0.0.1 --port 8001

orders:
	cd $(BACKEND_DIR) && uv run uvicorn backend.services.orders.main:app --host 127.0.0.1 --port 8002

inventory:
	cd $(BACKEND_DIR) && uv run uvicorn backend.services.inventory.main:app --host 127.0.0.1 --port 8003

payment:
	cd $(BACKEND_DIR) && uv run uvicorn backend.services.payment.main:app --host 127.0.0.1 --port 8004

watcher-a:
	cd $(BACKEND_DIR) && uv run python -m backend.watcher_a.main

watcher-b:
	cd $(BACKEND_DIR) && uv run python -m backend.watcher_b.main

services:
	@trap 'trap - TERM INT; kill 0' TERM INT; \
		$(MAKE) relay & \
		$(MAKE) inventory & \
		$(MAKE) payment & \
		$(MAKE) orders & \
		$(MAKE) gateway & \
		wait

dashboard:
	cd dashboard && npm run dev

stop:
	@for port in 8001 8002 8003 8004 8005; do \
		pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
		if [ -n "$$pids" ]; then kill $$pids; fi; \
	done
	@pkill -f 'backend\.watcher_[ab]\.main' 2>/dev/null || true
