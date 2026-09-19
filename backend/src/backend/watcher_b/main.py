"""Consume application failures and coordinate safe service repair."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

from backend.agent.diagnosis import DiagnosisResult, diagnose_failure
from backend.agent.recovery import repair_orders
from backend.relay import publish

BACKEND_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = BACKEND_ROOT / "src" / "backend" / "manifests" / "services.json"
RELAY_URL = os.getenv("AUTODECK_RELAY_URL", "http://127.0.0.1:8005")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8001")
logger = logging.getLogger(__name__)


def load_services() -> dict[str, dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {service["name"]: service for service in manifest["services"]}


def parse_sse_event(lines: list[str]) -> dict[str, Any] | None:
    data = "".join(line[6:] for line in lines if line.startswith("data:"))
    if not data:
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Ignoring malformed relay event")
        return None
    return payload if isinstance(payload, dict) else None


def event_stream(client: httpx.Client) -> Iterator[dict[str, Any]]:
    with client.stream("GET", f"{RELAY_URL.rstrip('/')}/events/stream") as response:
        response.raise_for_status()
        lines: list[str] = []
        for line in response.iter_lines():
            if line == "":
                event = parse_sse_event(lines)
                lines = []
                if event is not None:
                    yield event
            else:
                lines.append(line)


class WatcherB:
    def __init__(self, *, auto_repair: bool | None = None) -> None:
        self.auto_repair = (
            os.getenv("AUTODECK_AUTO_REPAIR", "false").lower() == "true"
            if auto_repair is None
            else auto_repair
        )
        self._active_services: set[str] = set()
        self._active_lock = threading.Lock()

    def _claim_service(self, service: str) -> bool:
        with self._active_lock:
            if service in self._active_services:
                return False
            self._active_services.add(service)
            return True

    def _release_service(self, service: str) -> None:
        with self._active_lock:
            self._active_services.discard(service)

    def _source_for(self, service_entry: dict[str, Any]) -> str:
        module_name = service_entry["entrypoint"].split(":", 1)[0]
        source_path = BACKEND_ROOT / "src" / "backend" / "/".join(module_name.split(".")[1:])
        return source_path.with_suffix(".py").read_text(encoding="utf-8")

    def _diagnose(self, event: dict[str, Any], service_entry: dict[str, Any]) -> DiagnosisResult:
        metadata = event.get("metadata", {})
        status_code = int(metadata.get("status_code", 500))
        detail = str(metadata.get("detail", event.get("message", "application failure")))
        request = metadata.get("request")
        if not isinstance(request, dict):
            request = {}
        result = diagnose_failure(
            service_entry["name"],
            status_code,
            detail,
            self._source_for(service_entry),
            service_entry=service_entry,
            request=request,
        )
        publish(
            type="agent_diagnosis",
            service=service_entry["name"],
            status=result.action,
            message=result.reason,
            metadata={"status_code": status_code, "detail": detail},
        )
        return result

    def _replay(self, request: dict[str, Any]) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(f"{GATEWAY_URL.rstrip('/')}/orders", json=request)
            if response.is_success:
                publish(
                    type="application_recovered",
                    service="gateway",
                    status="healthy",
                    message="Original Gateway request succeeded after repair.",
                    metadata={"request": request, "response": response.json()},
                )
                return True
            publish(
                type="replay_failed",
                service="gateway",
                status="failed",
                message="Original Gateway request still failed after repair.",
                metadata={"request": request, "status_code": response.status_code},
            )
        except (httpx.HTTPError, ValueError) as error:
            publish(
                type="replay_failed",
                service="gateway",
                status="failed",
                message="Original Gateway request could not be replayed.",
                metadata={"request": request, "error_type": error.__class__.__name__},
            )
        return False

    def handle_event(self, event: dict[str, Any]) -> None:
        if event.get("type") != "application_failure":
            return
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            logger.warning("Ignoring application failure without metadata")
            return
        service_name = metadata.get("target_service")
        if not isinstance(service_name, str):
            logger.warning("Ignoring application failure without target service")
            return
        service_entry = load_services().get(service_name)
        if service_entry is None:
            logger.warning("Ignoring application failure for unknown service=%s", service_name)
            return
        if not self._claim_service(service_name):
            logger.info("Ignoring duplicate active failure service=%s", service_name)
            return

        try:
            diagnosis = self._diagnose(event, service_entry)
            if diagnosis.patch is None:
                publish(
                    type="patch_rejected",
                    service=service_name,
                    status="rejected",
                    message="No approved repair exists for the observed application failure.",
                    metadata={"reason": diagnosis.reason},
                )
                return
            if not self.auto_repair:
                logger.info("Repair approval required service=%s", service_name)
                publish(
                    type="repair_pending",
                    service=service_name,
                    status="approval_required",
                    message="An approved diagnosis is waiting for AUTODECK_AUTO_REPAIR=true.",
                    metadata={"reason": diagnosis.reason},
                )
                return
            if service_name != "orders":
                publish(
                    type="patch_rejected",
                    service=service_name,
                    status="rejected",
                    message="The current recovery executor only supports Orders.",
                    metadata={"reason": "unsupported_recovery_executor"},
                )
                return
            metadata_request = metadata.get("request")
            request = metadata_request if isinstance(metadata_request, dict) else {}
            status_code = int(metadata.get("status_code", 500))
            detail = str(metadata.get("detail", event.get("message", "application failure")))
            repair_orders(status_code, detail, request, diagnosis=diagnosis)
            self._replay(request)
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
            logger.exception("Watcher B recovery failed service=%s", service_name)
            publish(
                type="recovery_failed",
                service=service_name,
                status="failed",
                message="Watcher B could not complete application recovery.",
                metadata={"error_type": error.__class__.__name__},
            )
        finally:
            self._release_service(service_name)

    def run(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        logger.info("Watcher B started relay=%s auto_repair=%s", RELAY_URL, self.auto_repair)
        while not stop_event.is_set():
            try:
                # The relay sends keepalives every 15 seconds. A finite read
                # timeout ensures a stale or hung relay connection is
                # discarded and reconnected instead of blocking forever.
                stream_timeout = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
                with httpx.Client(timeout=stream_timeout) as client:
                    for event in event_stream(client):
                        if stop_event.is_set():
                            return
                        self.handle_event(event)
            except (httpx.HTTPError, OSError) as error:
                logger.warning("Watcher B relay connection failed error_type=%s", error.__class__.__name__)
                stop_event.wait(1.0)
        logger.info("Watcher B stopped")


def main() -> None:
    logging.basicConfig(
        level=os.getenv("AUTODECK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    WatcherB().run()


if __name__ == "__main__":
    main()
