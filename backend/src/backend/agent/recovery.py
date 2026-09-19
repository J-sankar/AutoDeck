"""Run the first live service repair cycle."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import time
from typing import Any

import httpx

from .diagnosis import DiagnosisResult, diagnose_failure
from .patch import BACKEND_ROOT, PatchDecision, apply_patch
from backend.relay import publish

MANIFEST_PATH = BACKEND_ROOT / "src" / "backend" / "manifests" / "services.json"
logger = logging.getLogger(__name__)


def _service(service_name: str) -> dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    for service in manifest["services"]:
        if service["name"] == service_name:
            return service
    raise ValueError(f"unknown service: {service_name}")


def _source_for(decision: PatchDecision) -> str:
    return (BACKEND_ROOT / decision.file).read_text(encoding="utf-8")


def _listening_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def restart_service(service_name: str, timeout: float = 10.0) -> subprocess.Popen[str]:
    service = _service(service_name)
    port = service["port"]
    logger.info("Service restart started service=%s port=%s", service_name, port)
    publish(
        type="restart_requested",
        service=service_name,
        status="recovering",
        message="Service restart requested after an approved patch.",
        metadata={"port": port},
    )
    for pid in _listening_pids(port):
        logger.info("Service stop requested service=%s port=%s pid=%s", service_name, port, pid)
        os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while _listening_pids(port) and time.monotonic() < deadline:
        time.sleep(0.1)

    if _listening_pids(port):
        publish(
            type="recovery_failed",
            service=service_name,
            status="failed",
            message="The service did not stop before restart.",
            metadata={"port": port},
        )
        raise RuntimeError(f"service {service_name} did not stop on port {port}")

    process = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            service["entrypoint"],
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND_ROOT,
        text=True,
    )
    publish(
        type="service_started",
        service=service_name,
        status="starting",
        message="Service process started after patch application.",
        metadata={"port": port, "pid": process.pid},
    )
    health_url = f"http://127.0.0.1:{port}{service['health']}"
    with httpx.Client(timeout=1.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                publish(
                    type="recovery_failed",
                    service=service_name,
                    status="failed",
                    message="The restarted service exited before becoming healthy.",
                    metadata={"port": port, "exit_code": process.returncode},
                )
                raise RuntimeError(f"service {service_name} exited with code {process.returncode}")
            try:
                if client.get(health_url).is_success:
                    logger.info("Service healthy service=%s port=%s pid=%s", service_name, port, process.pid)
                    publish(
                        type="service_recovered",
                        service=service_name,
                        status="healthy",
                        message="Service health recovered after patch restart.",
                        metadata={"port": port, "pid": process.pid},
                    )
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    process.terminate()
    publish(
        type="recovery_failed",
        service=service_name,
        status="failed",
        message="The restarted service did not become healthy before timeout.",
        metadata={"port": port},
    )
    raise RuntimeError(f"service {service_name} did not become healthy")


def repair_orders(
    status_code: int,
    detail: str,
    request: dict[str, Any] | None = None,
    diagnosis: DiagnosisResult | None = None,
) -> tuple[PatchDecision, subprocess.Popen[str]]:
    logger.info("Recovery started service=orders status_code=%s", status_code)
    service_entry = _service("orders")
    source_path = BACKEND_ROOT / "src" / "backend" / "services" / "orders" / "main.py"
    source = source_path.read_text(encoding="utf-8")
    if diagnosis is None:
        diagnosis = diagnose_failure(
            "orders",
            status_code,
            detail,
            source,
            service_entry=service_entry,
            request=request,
        )
        publish(
            type="agent_diagnosis",
            service="orders",
            status=diagnosis.action,
            message=diagnosis.reason,
            metadata={"status_code": status_code, "detail": detail},
        )
    diagnosed = diagnosis.patch
    if diagnosed is None:
        logger.warning("Recovery aborted service=orders reason=no_repair")
        publish(
            type="patch_rejected",
            service="orders",
            status="rejected",
            message="Diagnosis did not approve a repair patch.",
            metadata={"reason": diagnosis.reason},
        )
        raise ValueError("no approved repair for the observed Orders failure")

    result = apply_patch(diagnosed)
    if not result.applied:
        logger.error("Recovery aborted service=orders reason=patch_validation_failed")
        raise RuntimeError(result.message)
    process = restart_service("orders")
    logger.info("Recovery completed service=orders pid=%s", process.pid)
    return diagnosed, process


def main() -> None:
    logging.basicConfig(
        level=os.getenv("AUTODECK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Diagnose and repair a service failure")
    parser.add_argument("--service", required=True)
    parser.add_argument("--status-code", required=True, type=int)
    parser.add_argument("--detail", required=True)
    parser.add_argument("--request-json", default="{}")
    args = parser.parse_args()
    if args.service != "orders":
        raise SystemExit("only the Orders repair flow is currently supported")
    decision, _ = repair_orders(args.status_code, args.detail, json.loads(args.request_json))
    print(json.dumps({"status": "repaired", "decision": decision.__dict__}, indent=2))


if __name__ == "__main__":
    main()
