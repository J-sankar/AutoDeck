"""Validate the service manifest against the service applications and runtime."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "src" / "backend" / "manifests" / "services.json"


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)

    if not isinstance(manifest.get("services"), list):
        raise TypeError("manifest must contain a services list")
    return manifest


def load_app(entrypoint: str) -> Any:
    module_name, separator, attribute_name = entrypoint.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError(f"invalid entrypoint: {entrypoint}")

    module = importlib.import_module(module_name)
    app = getattr(module, attribute_name, None)
    if app is None or not hasattr(app, "routes"):
        raise ValueError(f"entrypoint does not expose a FastAPI app: {entrypoint}")
    return app


def validate_structure(services: list[dict[str, Any]]) -> dict[str, Any]:
    names = [service.get("name") for service in services]
    ports = [service.get("port") for service in services]
    if len(names) != len(set(names)):
        raise ValueError("service names must be unique")
    if len(ports) != len(set(ports)):
        raise ValueError("service ports must be unique")

    known_names = set(names)
    results = {}
    for service in services:
        name = service["name"]
        app = load_app(service["entrypoint"])
        route_paths = {route.path for route in app.routes}

        missing_endpoints = [
            endpoint
            for endpoint in [service["health"], *service.get("endpoints", [])]
            if endpoint not in route_paths
        ]
        unknown_dependencies = [
            dependency
            for dependency in service.get("depends_on", [])
            if dependency not in known_names
        ]
        if missing_endpoints:
            raise ValueError(f"{name} is missing routes: {missing_endpoints}")
        if unknown_dependencies:
            raise ValueError(f"{name} has unknown dependencies: {unknown_dependencies}")

        results[name] = {
            "port": service["port"],
            "entrypoint": service["entrypoint"],
            "routes_checked": [service["health"], *service.get("endpoints", [])],
        }

    return results


def validate_health(services: list[dict[str, Any]]) -> None:
    with httpx.Client(timeout=3.0) as client:
        for service in services:
            name = service["name"]
            url = f"http://127.0.0.1:{service['port']}{service['health']}"
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise ValueError(f"{name} health check failed at {url}: {error}") from error

            body = response.json()
            expected = {"service": name, "status": "healthy"}
            if body != expected:
                raise ValueError(f"{name} returned {body!r}; expected {expected!r}")


def main() -> None:
    manifest = load_manifest()
    services = manifest["services"]
    structure = validate_structure(services)
    validate_health(services)

    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Services checked: {len(structure)}")
    for name, result in structure.items():
        print(f"PASS {name}: port {result['port']}, routes {', '.join(result['routes_checked'])}")
    print("PASS all manifest and health checks")


if __name__ == "__main__":
    main()
