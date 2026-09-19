"""Watch registered services and restart them after repeated health failures."""

from __future__ import annotations

import json
import fcntl
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any

from dotenv import load_dotenv
import httpx

from backend.relay import publish

BACKEND_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = BACKEND_ROOT / "src" / "backend" / "manifests" / "services.json"
logger = logging.getLogger(__name__)
WATCHER_LOCK_PATH = BACKEND_ROOT / ".watcher_a.lock"

load_dotenv()


def acquire_watcher_lock() -> Any:
    lock_file = WATCHER_LOCK_PATH.open("w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        lock_file.close()
        raise RuntimeError("Watcher A is already running") from error
    return lock_file


@dataclass
class Watcher:
    services: list[dict[str, Any]]
    interval: float = 2.0
    failure_threshold: int = 2
    request_timeout: float = 1.0
    failures: dict[str, int] = field(default_factory=dict)

    def health_url(self, service: dict[str, Any]) -> str:
        return f"http://127.0.0.1:{service['port']}{service['health']}"

    def check_health(self, service: dict[str, Any]) -> bool:
        try:
            with httpx.Client(timeout=self.request_timeout) as client:
                response = client.get(self.health_url(service))
                if not response.is_success:
                    return False
                return response.json() == {
                    "service": service["name"],
                    "status": "healthy",
                }
        except (httpx.HTTPError, ValueError):
            return False

    def _listener_pids(self, port: int) -> list[int]:
        result = subprocess.run(
            ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            check=False,
            capture_output=True,
            text=True,
        )
        return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]

    def _is_registered_process(self, pid: int, entrypoint: str) -> bool:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        )
        return "uvicorn" in result.stdout and entrypoint in result.stdout

    def _belongs_to_process_group(self, pid: int, process: subprocess.Popen[str]) -> bool:
        try:
            return os.getpgid(pid) == process.pid
        except ProcessLookupError:
            return False

    def _wait_for_port_free(self, port: int, deadline: float) -> bool:
        while time.monotonic() < deadline:
            if not self._listener_pids(port):
                return True
            time.sleep(0.1)
        return False

    def restart_service(self, service: dict[str, Any]) -> bool:
        name = service["name"]
        port = service["port"]
        entrypoint = service["entrypoint"]
        logger.warning("Restart requested service=%s port=%s", name, port)
        publish(
            type="restart_requested",
            service=name,
            status="recovering",
            message="Service restart requested after repeated health failures.",
            metadata={"port": port, "entrypoint": entrypoint},
        )

        pids = self._listener_pids(port)
        unexpected = [pid for pid in pids if not self._is_registered_process(pid, entrypoint)]
        if unexpected:
            logger.error(
                "Recovery refused service=%s port=%s unexpected_pids=%s",
                name,
                port,
                unexpected,
            )
            publish(
                type="recovery_failed",
                service=name,
                status="failed",
                message="Recovery refused because an unexpected process owns the port.",
                metadata={"port": port, "unexpected_pids": unexpected},
            )
            return False

        for pid in pids:
            logger.info("Stopping service=%s pid=%s", name, pid)
            os.kill(pid, signal.SIGTERM)

        deadline = time.monotonic() + 10.0
        if not self._wait_for_port_free(port, deadline):
            logger.error("Recovery failed service=%s reason=port_did_not_free", name)
            publish(
                type="recovery_failed",
                service=name,
                status="failed",
                message="The service port did not become available during recovery.",
                metadata={"port": port},
            )
            return False

        process = subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                entrypoint,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=BACKEND_ROOT,
            env=os.environ.copy(),
            text=True,
            start_new_session=True,
        )
        logger.info("Service process started service=%s pid=%s", name, process.pid)
        publish(
            type="service_started",
            service=name,
            status="starting",
            message="Service process started during recovery.",
            metadata={"port": port, "pid": process.pid},
        )

        while time.monotonic() < deadline:
            if process.poll() is not None:
                logger.error("Recovery failed service=%s exit_code=%s", name, process.returncode)
                publish(
                    type="recovery_failed",
                    service=name,
                    status="failed",
                    message="The restarted service exited before becoming healthy.",
                    metadata={"port": port, "exit_code": process.returncode},
                )
                return False
            listener_pids = self._listener_pids(port)
            owns_listener = any(
                self._belongs_to_process_group(pid, process)
                and self._is_registered_process(pid, entrypoint)
                for pid in listener_pids
            )
            if self.check_health(service) and owns_listener:
                logger.info("Service recovered service=%s pid=%s", name, process.pid)
                publish(
                    type="service_recovered",
                    service=name,
                    status="healthy",
                    message="Service health recovered after restart.",
                    metadata={"port": port, "pid": process.pid},
                )
                return True
            if self.check_health(service) and listener_pids:
                logger.warning(
                    "Recovery health response came from another process service=%s listener_pids=%s",
                    name,
                    listener_pids,
                )
            time.sleep(0.2)

        process.terminate()
        logger.error("Recovery failed service=%s reason=health_timeout", name)
        publish(
            type="recovery_failed",
            service=name,
            status="failed",
            message="The restarted service did not become healthy before timeout.",
            metadata={"port": port},
        )
        return False

    def poll_once(self) -> None:
        for service in self.services:
            name = service["name"]
            if self.check_health(service):
                if self.failures.pop(name, 0):
                    logger.info("Service healthy after failures service=%s", name)
                continue

            failures = self.failures.get(name, 0) + 1
            self.failures[name] = failures
            logger.warning(
                "Health check failed service=%s failure=%s/%s",
                name,
                failures,
                self.failure_threshold,
            )
            publish(
                type="health_failure",
                service=name,
                status="unhealthy",
                message="Service health check failed.",
                metadata={"failure_count": failures, "threshold": self.failure_threshold},
            )
            if failures >= self.failure_threshold:
                self.restart_service(service)
                self.failures[name] = 0

    def run(self, stop_event: Event | None = None) -> None:
        stop_event = stop_event or Event()
        logger.info(
            "Watcher A started services=%s interval=%s failure_threshold=%s",
            len(self.services),
            self.interval,
            self.failure_threshold,
        )
        try:
            while not stop_event.is_set():
                self.poll_once()
                stop_event.wait(self.interval)
        finally:
            logger.info("Watcher A stopped")


def load_services() -> list[dict[str, Any]]:
    with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    return manifest["services"]


def main() -> None:
    try:
        lock_file = acquire_watcher_lock()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    logging.basicConfig(
        level=os.getenv("AUTODECK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        Watcher(load_services()).run()
    finally:
        lock_file.close()


if __name__ == "__main__":
    main()
