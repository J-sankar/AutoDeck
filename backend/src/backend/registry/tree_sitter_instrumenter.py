"""Safe, idempotent Tree-sitter decorator insertion for service functions."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tree_sitter import Language, Parser
import tree_sitter_python

if TYPE_CHECKING:
    from .service import TelemetryTarget

logger = logging.getLogger(__name__)


def _function_names(source: bytes) -> set[str]:
    parser = Parser(Language(tree_sitter_python.language()))
    tree = parser.parse(source)
    names: set[str] = set()
    pending = [tree.root_node]
    while pending:
        node = pending.pop()
        if node.type == "function_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                names.add(name.text.decode())
        pending.extend(node.children)
    return names


def _source_path(service: dict[str, Any], backend_root: Path) -> Path:
    module = service["entrypoint"].split(":", 1)[0]
    path = backend_root / "src" / "backend" / Path(*module.split(".")[1:])
    return path.with_suffix(".py")


def _decorate(source: str, target: TelemetryTarget) -> str:
    decorator = (
        f'@trace_endpoint(service={target.service!r}, operation={target.operation!r}, '
        f"targets={tuple(target.targets)!r})\n"
    )
    if decorator.rstrip() in source:
        return source
    lines = source.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("def ") and line.split("(", 1)[0][4:] == target.function:
            lines.insert(index, decorator)
            return "".join(lines)
        if line.startswith("async def ") and line.split("(", 1)[0][10:] == target.function:
            lines.insert(index, decorator)
            return "".join(lines)
    raise ValueError(f"telemetry function not found: {target.function}")


def apply_telemetry_plan(targets: list[TelemetryTarget], manifest: dict[str, Any], backend_root: Path) -> list[str]:
    logger.info("Tree-sitter instrumentation started targets=%s", len(targets))
    services = {service["name"]: service for service in manifest["services"]}
    grouped: dict[Path, list[TelemetryTarget]] = {}
    for target in targets:
        service = services.get(target.service)
        if service is None:
            raise ValueError(f"unknown telemetry service: {target.service}")
        path = _source_path(service, backend_root)
        if not path.is_file() or not str(path).startswith(str(backend_root / "src" / "backend" / "services")):
            raise ValueError("telemetry source must be inside backend/src/backend/services")
        grouped.setdefault(path, []).append(target)

    applied: list[str] = []
    for path, file_targets in grouped.items():
        logger.info("Tree-sitter inspecting file=%s targets=%s", path, len(file_targets))
        original = path.read_text(encoding="utf-8")
        source_bytes = original.encode()
        names = _function_names(source_bytes)
        for target in file_targets:
            if target.function not in names:
                raise ValueError(f"telemetry function is not defined in source: {target.function}")
            logger.info(
                "Tree-sitter target approved file=%s service=%s function=%s operation=%s dependencies=%s",
                path,
                target.service,
                target.function,
                target.operation,
                list(target.targets),
            )
        updated = original
        if "from backend.telemetry import trace_endpoint" not in updated:
            updated = "from backend.telemetry import trace_endpoint\n" + updated
        for target in file_targets:
            updated = _decorate(updated, target)
        ast.parse(updated)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            applied.append(str(path.relative_to(backend_root)))
            logger.info("Tree-sitter instrumentation applied file=%s", path)
        else:
            logger.info("Tree-sitter instrumentation already present file=%s", path)
    logger.info("Tree-sitter instrumentation completed applied_files=%s", len(applied))
    return applied
