"""Tree-sitter registry schema generation for the planning agent."""

from __future__ import annotations

import re
import logging
import json
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser
import tree_sitter_python

ROUTE_PATTERN = re.compile(r"@app\.(get|post)\(\s*['\"]([^'\"]+)['\"]")
logger = logging.getLogger(__name__)


def parse_functions(source: bytes) -> list[dict[str, Any]]:
    parser = Parser(Language(tree_sitter_python.language()))
    tree = parser.parse(source)
    functions: list[dict[str, Any]] = []
    for node in tree.root_node.children:
        if node.type == "function_definition":
            function = node
            decorators: list[str] = []
        elif node.type == "decorated_definition":
            function = next((child for child in node.children if child.type == "function_definition"), None)
            decorators = [child.text.decode() for child in node.children if child.type == "decorator"]
            if function is None:
                continue
        else:
            continue
        name_node = function.child_by_field_name("name")
        if name_node is None:
            continue
        routes = []
        for decorator in decorators:
            match = ROUTE_PATTERN.search(decorator)
            if match:
                routes.append({"method": match.group(1).upper(), "path": match.group(2)})
        functions.append(
            {
                "name": name_node.text.decode(),
                "line": function.start_point[0] + 1,
                "routes": routes,
            }
        )
    return functions


def build_registry_schema(manifest: dict[str, Any], backend_root: Path) -> dict[str, Any]:
    """Parse every registered service before the agent is called."""
    service_schema: list[dict[str, Any]] = []
    services_root = (backend_root / "src" / "backend" / "services").resolve()
    for service in manifest["services"]:
        module_name = service["entrypoint"].split(":", 1)[0]
        source_path = (backend_root / "src" / "backend" / Path(*module_name.split(".")[1:])).with_suffix(".py")
        resolved = source_path.resolve()
        if not resolved.is_relative_to(services_root):
            raise ValueError(f"registered source is outside services directory: {source_path}")
        parsed_functions = parse_functions(source_path.read_bytes())
        logger.info(
            "Registry schema source parsed service=%s file=%s functions=%s",
            service["name"],
            resolved,
            len(parsed_functions),
        )
        registered_paths = set(service.get("endpoints", []))
        functions = []
        for function in parsed_functions:
            operations = [
                f"{route['method']} {route['path']}"
                for route in function["routes"]
                if route["path"] in registered_paths
            ]
            functions.append(
                {
                    "id": f"{service['name']}.{function['name']}",
                    "name": function["name"],
                    "line": function["line"],
                    "operations": operations,
                }
            )
        service_schema.append(
            {
                "name": service["name"],
                "id": service["name"],
                "entrypoint": service["entrypoint"],
                "file": str(resolved.relative_to(backend_root.resolve())),
                "port": service["port"],
                "endpoints": service.get("endpoints", []),
                "depends_on": service.get("depends_on", []),
                "functions": functions,
            }
        )
        logger.info(
            "Registry schema service recorded service=%s endpoint_functions=%s dependencies=%s",
            service["name"],
            [function["id"] for function in functions if function["operations"]],
            service.get("depends_on", []),
        )
    return {"services": service_schema}


def write_generated_manifest(
    manifest: dict[str, Any],
    registry_schema: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    """Persist Tree-sitter-discovered functions alongside trusted service metadata."""
    discovered = {service["id"]: service for service in registry_schema["services"]}
    generated_services = []
    for service in manifest["services"]:
        parsed = discovered[service["name"]]
        generated = dict(service)
        generated["id"] = service["name"]
        generated["source_file"] = parsed["file"]
        generated["functions"] = parsed["functions"]
        generated_services.append(generated)
    generated_manifest = {"services": generated_services}
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(generated_manifest, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(manifest_path)
    logger.info("Registry generated manifest written path=%s services=%s", manifest_path, len(generated_services))
    return generated_manifest
