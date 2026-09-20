"""Manifest-driven local runtime supervisor for the AutoDeck demo."""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("autodeck.runtime")
BACKEND_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = BACKEND_ROOT / "src" / "backend" / "manifests" / "services.json"
STATE_PATH = BACKEND_ROOT / ".autodeck-runtime.json"
LOCK_PATH = BACKEND_ROOT / ".autodeck-runtime.lock"

CONTROL = {"name": "control", "entrypoint": "backend.main:app", "port": 8000, "health": "/"}
RELAY = {"name": "relay", "entrypoint": "backend.relay.main:app", "port": 8005, "health": "/health"}
SERVICE_RESTART_GRACE = 20.0


def load_services() -> dict[str, dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {service["name"]: service for service in manifest["services"]}


def _read_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"invalid runtime state at {STATE_PATH}") from error


def _write_state(state: dict[str, Any]) -> None:
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def _listener_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _command(pid: int) -> str:
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], check=False, capture_output=True, text=True)
    return result.stdout.strip()


def _processes_matching(fragment: str) -> list[int]:
    result = subprocess.run(["ps", "-eo", "pid=,args="], check=False, capture_output=True, text=True)
    pids: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and fragment in parts[1] and int(parts[0]) != os.getpid():
            pids.append(int(parts[0]))
    return pids


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        try:
            state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
            return state != "Z"
        except (FileNotFoundError, IndexError):
            return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _set_parent_death_signal() -> None:
    """Ensure managed children do not outlive a crashed supervisor on Linux."""
    libc = ctypes.CDLL(None)
    libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def _health(component: dict[str, Any], timeout: float = 1.0) -> bool:
    health_path = component.get("health", "/" if component["name"] == "control" else "/health")
    try:
        response = httpx.get(
            f"http://127.0.0.1:{component['port']}{health_path}",
            timeout=timeout,
        )
        if not response.is_success:
            return False
        if component["name"] == "control":
            return response.json() == {"service": "control-plane", "status": "healthy"}
        if component["name"] == "relay":
            return response.json() == {"service": "relay", "status": "healthy"}
        return response.json() == {"service": component["name"], "status": "healthy"}
    except (httpx.HTTPError, ValueError):
        return False


def _wait_healthy(component: dict[str, Any], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health(component):
            logger.info("ready component=%s port=%s", component["name"], component["port"])
            return
        time.sleep(0.25)
    raise RuntimeError(f"component {component['name']} did not become healthy on port {component['port']}")


def _adopt_restarted_service(record: dict[str, Any]) -> bool:
    """Accept a valid listener started by Watcher A or the recovery agent."""
    listeners = _listener_pids(int(record["port"]))
    valid = [pid for pid in listeners if _expected_command(record) in _command(pid)]
    if not valid:
        return False
    if not _health(record):
        return False
    replacement_pid = valid[0]
    if int(record["pid"]) != replacement_pid:
        logger.info(
            "Adopting restarted service service=%s old_pid=%s new_pid=%s",
            record["name"],
            record["pid"],
            replacement_pid,
        )
        record["pid"] = replacement_pid
    return True


def _expected_command(component: dict[str, Any]) -> str:
    return component["entrypoint"]


def _assert_port_available(component: dict[str, Any]) -> None:
    pids = _listener_pids(component["port"])
    if pids:
        commands = [_command(pid) for pid in pids]
        raise RuntimeError(
            f"port {component['port']} for {component['name']} is already occupied: "
            + "; ".join(f"pid={pid} command={command!r}" for pid, command in zip(pids, commands))
        )


def _start_component(component: dict[str, Any], environment: dict[str, str]) -> dict[str, Any]:
    _assert_port_available(component)
    process = subprocess.Popen(
        ["uv", "run", "uvicorn", component["entrypoint"], "--host", "127.0.0.1", "--port", str(component["port"])],
        cwd=BACKEND_ROOT,
        env=environment,
        start_new_session=True,
        preexec_fn=_set_parent_death_signal,
        text=True,
    )
    record = {
        "name": component["name"],
        "kind": "service",
        "pid": process.pid,
        "port": component["port"],
        "health": component["health"],
        "entrypoint": component["entrypoint"],
    }
    logger.info("started component=%s pid=%s port=%s", component["name"], process.pid, component["port"])
    _wait_healthy(component)
    return record


def _start_worker(name: str, module: str, environment: dict[str, str]) -> dict[str, Any]:
    process = subprocess.Popen(
        ["uv", "run", "python", "-m", module],
        cwd=BACKEND_ROOT,
        env=environment,
        start_new_session=True,
        preexec_fn=_set_parent_death_signal,
        text=True,
    )
    logger.info("started worker=%s pid=%s", name, process.pid)
    return {"name": name, "kind": "worker", "pid": process.pid, "module": module}


def _terminate(record: dict[str, Any]) -> bool:
    pid = int(record["pid"])
    listener_pids: list[int] = []
    if record.get("kind") == "service":
        listener_pids = _listener_pids(int(record["port"]))
        if listener_pids and any(_expected_command(record) not in _command(listener) for listener in listener_pids):
            logger.error("refusing stop name=%s unexpected listener on port=%s", record["name"], record["port"])
            return False
    groups: set[int] = set()
    if _alive(pid):
        groups.add(os.getpgid(pid))
    for listener in listener_pids:
        try:
            groups.add(os.getpgid(listener))
        except ProcessLookupError:
            continue
    if not groups:
        return True
    for group in groups:
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 8
    while any(_alive(group) for group in groups) and time.monotonic() < deadline:
        time.sleep(0.1)
    if any(_alive(group) for group in groups):
        logger.warning("graceful stop timed out; forcing stop name=%s pid=%s", record["name"], pid)
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                continue
        force_deadline = time.monotonic() + 2
        while any(_alive(group) for group in groups) and time.monotonic() < force_deadline:
            time.sleep(0.1)
        if any(_alive(group) for group in groups):
            logger.error("process did not stop name=%s pid=%s", record["name"], pid)
            return False
    if record.get("kind") == "service":
        while _listener_pids(int(record["port"])) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _listener_pids(int(record["port"])):
            logger.error("port remained occupied name=%s port=%s", record["name"], record["port"])
            return False
    logger.info("stopped name=%s pid=%s", record["name"], pid)
    return True


def _acquire_lock() -> Any:
    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        lock.close()
        raise RuntimeError("another AutoDeck runtime supervisor is already active") from error
    return lock


def start() -> None:
    if _read_state():
        raise RuntimeError("runtime state already exists; run `make demo-status` or `make demo-down` first")
    environment = os.environ.copy()
    environment.setdefault("AUTODECK_RELAY_URL", "http://127.0.0.1:8005")
    environment.setdefault("AUTODECK_AUTO_REPAIR", "true")
    services = load_services()
    records: list[dict[str, Any]] = []
    state = {"manager_pid": os.getpid(), "started_at": time.time(), "processes": records}
    _write_state(state)
    owns_runtime = True
    try:
        records.append(_start_component(RELAY, environment))
        records.append(_start_component(CONTROL, environment))
        for name in ("inventory", "payment", "orders", "gateway"):
            records.append(_start_component(services[name], environment))
            _write_state(state)
        records.append(_start_worker("watcher-a", "backend.watcher_a.main", environment))
        records.append(_start_worker("watcher-b", "backend.watcher_b.main", environment))
        _write_state(state)
        logger.info("demo runtime ready services=4 relay=8005 control=8000 watchers=2")
        missing_since: dict[str, float] = {}
        while True:
            time.sleep(1)
            current_state = _read_state()
            if current_state is None:
                logger.info("runtime stopped by external command")
                owns_runtime = False
                return
            state = current_state
            records = state.get("processes", [])
            dead: list[str] = []
            for record in records:
                name = record["name"]
                if _alive(int(record["pid"])):
                    missing_since.pop(name, None)
                    continue
                if record.get("kind") == "service" and _adopt_restarted_service(record):
                    missing_since.pop(name, None)
                    _write_state(state)
                    continue
                started_missing = missing_since.setdefault(name, time.monotonic())
                elapsed = time.monotonic() - started_missing
                if elapsed < SERVICE_RESTART_GRACE:
                    logger.warning(
                        "Managed service is restarting service=%s elapsed=%.1fs grace=%.1fs",
                        name,
                        elapsed,
                        SERVICE_RESTART_GRACE,
                    )
                    continue
                dead.append(name)
            if dead:
                raise RuntimeError(f"managed process exited unexpectedly: {', '.join(dead)}")
    except (KeyboardInterrupt, SystemExit):
        logger.info("shutdown requested")
    finally:
        if owns_runtime:
            for record in reversed(records):
                _terminate(record)
            STATE_PATH.unlink(missing_ok=True)


def down() -> None:
    state = _read_state()
    if not state:
        logger.info("no runtime state found; checking for manifest-matching AutoDeck processes")
        records: list[dict[str, Any]] = []
        components = [RELAY, CONTROL, *load_services().values()]
        for component in components:
            listeners = _listener_pids(component["port"])
            if not listeners:
                continue
            unexpected = [pid for pid in listeners if component["entrypoint"] not in _command(pid)]
            if unexpected:
                logger.error("refusing cleanup name=%s unexpected_pids=%s", component["name"], unexpected)
                continue
            records.append({
                "name": component["name"],
                "kind": "service",
                "pid": listeners[0],
                "port": component["port"],
                "health": component["health"],
                "entrypoint": component["entrypoint"],
            })
        for name, module in (("watcher-a", "backend.watcher_a.main"), ("watcher-b", "backend.watcher_b.main")):
            pids = _processes_matching(module)
            if pids:
                records.append({"name": name, "kind": "worker", "pid": pids[0], "module": module})
        for record in reversed(records):
            _terminate(record)
        logger.info("unmanaged AutoDeck cleanup complete processes=%s", len(records))
        return
    success = True
    for record in reversed(state.get("processes", [])):
        success = _terminate(record) and success
    if success:
        STATE_PATH.unlink(missing_ok=True)
        logger.info("demo runtime stopped")
    else:
        raise RuntimeError("runtime shutdown was incomplete; inspect the listed process owners")


def status() -> None:
    state = _read_state()
    if not state:
        print("AutoDeck runtime: stopped")
        for service in load_services().values():
            listeners = _listener_pids(service["port"])
            if listeners:
                print(f"- unmanaged listener: {service['name']} port={service['port']} pids={listeners}")
        return
    manager_alive = _alive(int(state.get("manager_pid", 0)))
    print(f"AutoDeck runtime: {'running' if manager_alive else 'stale'} (manager pid={state.get('manager_pid')})")
    for record in state.get("processes", []):
        pid = int(record["pid"])
        healthy = record.get("kind") == "worker" or _health(record)
        print(f"- {record['name']}: pid={pid} alive={_alive(pid)} healthy={healthy}")


def restart(service_name: str) -> None:
    services = load_services()
    component = services.get(service_name)
    if component is None:
        raise ValueError(f"unknown manifest service: {service_name}")
    state = _read_state()
    managed = state is not None
    if managed:
        records = state.get("processes", [])
        record = next((item for item in records if item["name"] == service_name), None)
        if record is None:
            raise RuntimeError(f"service {service_name} is not managed by the active runtime")
    else:
        listeners = _listener_pids(component["port"])
        if not listeners:
            raise RuntimeError(f"no listener found for {service_name}; start it with `make demo-up`")
        unexpected = [pid for pid in listeners if component["entrypoint"] not in _command(pid)]
        if unexpected:
            raise RuntimeError(f"refusing restart: unexpected process owns port {component['port']}: {unexpected}")
        record = {
            "name": service_name,
            "kind": "service",
            "pid": listeners[0],
            "port": component["port"],
            "health": component["health"],
            "entrypoint": component["entrypoint"],
        }
        records = [record]
    watcher = next((item for item in records if item["name"] == "watcher-a"), None)
    watcher_was_alive = bool(watcher and _alive(int(watcher["pid"])))
    if watcher_was_alive and not _terminate(watcher):
        raise RuntimeError("refused to pause Watcher A during service restart")
    try:
        if not _terminate(record):
            raise RuntimeError(f"refused to stop service {service_name}")
        replacement = _start_component(component, os.environ.copy())
        record.update(replacement)
        if watcher_was_alive:
            watcher_replacement = _start_worker(
                "watcher-a",
                "backend.watcher_a.main",
                os.environ.copy(),
            )
            watcher.update(watcher_replacement)
        if managed:
            _write_state(state)
        logger.info("service restart complete service=%s", service_name)
    except Exception:
        if watcher_was_alive and not _alive(int(watcher["pid"])):
            watcher_replacement = _start_worker("watcher-a", "backend.watcher_a.main", os.environ.copy())
            watcher.update(watcher_replacement)
            if managed:
                _write_state(state)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the AutoDeck local demo runtime")
    parser.add_argument("command", choices=("up", "down", "status", "restart"))
    parser.add_argument("service", nargs="?")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("AUTODECK_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    lock = None
    try:
        if args.command == "up":
            lock = _acquire_lock()
            start()
        elif args.command == "down":
            down()
        elif args.command == "status":
            status()
        elif args.command == "restart":
            if not args.service:
                parser.error("restart requires a service name")
            restart(args.service)
    except (OSError, RuntimeError, ValueError) as error:
        logger.error("runtime command failed error=%s", error)
        raise SystemExit(1) from error
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    main()
