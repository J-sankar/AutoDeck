"""Registry agent orchestration with deterministic source-editing boundaries."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .schema import build_registry_schema, write_generated_manifest
from .tree_sitter_instrumenter import apply_telemetry_plan

logger = logging.getLogger(__name__)
load_dotenv()

BACKEND_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = BACKEND_ROOT / "src" / "backend" / "manifests" / "services.json"


@dataclass(frozen=True)
class TelemetryTarget:
    service: str
    function: str
    operation: str
    targets: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["targets"] = list(self.targets)
        return result


def load_manifest() -> dict[str, Any]:
    logger.info("Registry loading manifest path=%s", MANIFEST_PATH)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    logger.info("Registry manifest loaded services=%s", len(manifest.get("services", [])))
    return manifest


def _catalog(schema: dict[str, Any]) -> dict[str, TelemetryTarget]:
    catalog: dict[str, TelemetryTarget] = {}
    dependencies = {service["id"]: tuple(service.get("depends_on", [])) for service in schema["services"]}
    for service in schema["services"]:
        for function in service["functions"]:
            for operation in function["operations"]:
                target_id = f"{service['id']}.{function['name']}"
                catalog[target_id] = TelemetryTarget(
                    service=service["id"],
                    function=function["name"],
                    operation=operation,
                    targets=dependencies[service["id"]],
                )
    if not catalog:
        raise ValueError("Tree-sitter registry schema contains no instrumentable endpoint functions")
    return catalog


def _fallback_targets(schema: dict[str, Any]) -> list[TelemetryTarget]:
    return list(_catalog(schema).values())


def _planner_schema(target_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_ids": {
                "type": "array",
                "items": {"type": "string", "enum": target_ids},
            }
        },
        "required": ["target_ids"],
    }


def _openai_targets(schema: dict[str, Any]) -> list[TelemetryTarget]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_MODEL are required for registry planning")
    from openai import OpenAI

    catalog = _catalog(schema)
    target_ids = sorted(catalog)
    logger.info(
        "Registry OpenAI planner request started model=%s schema_services=%s allowed_target_ids=%s",
        model,
        len(schema["services"]),
        target_ids,
    )
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        instructions=(
            "You are a registry telemetry planner. Select important endpoint functions "
            "from the supplied Tree-sitter registry schema. Return only target_ids from "
            "the allowed target_ids list. Do not output service names, function names, "
            "operations, dependencies, file paths, commands, or any other fields."
        ),
        input=json.dumps({"registry_schema": schema, "allowed_target_ids": target_ids}, indent=2),
        text={
            "format": {
                "type": "json_schema",
                "name": "telemetry_target_selection",
                "strict": True,
                "schema": _planner_schema(target_ids),
            }
        },
    )
    logger.info("Registry OpenAI planner response received output_chars=%s", len(response.output_text or ""))
    payload = json.loads(response.output_text)
    if set(payload) != {"target_ids"} or not isinstance(payload["target_ids"], list):
        raise ValueError("planner output must contain only target_ids")
    if len(payload["target_ids"]) != len(set(payload["target_ids"])):
        raise ValueError("planner output contains duplicate target_ids")
    selected = []
    for target_id in payload["target_ids"]:
        if target_id not in catalog:
            raise ValueError(f"planner returned unknown target_id={target_id!r}")
        selected.append(catalog[target_id])
    logger.info("Registry OpenAI planner response parsed target_ids=%s", payload["target_ids"])
    logger.info(
        "Registry planner targets resolved targets=%s",
        [target.to_dict() for target in selected],
    )
    return selected


def validate_targets(targets: list[TelemetryTarget], schema: dict[str, Any]) -> list[TelemetryTarget]:
    catalog = _catalog(schema)
    allowed: list[TelemetryTarget] = []
    for index, target in enumerate(targets):
        target_id = f"{target.service}.{target.function}"
        trusted = catalog.get(target_id)
        if trusted is None or trusted != target:
            raise ValueError(f"target[{index}] is not in the Tree-sitter registry catalog: {target_id!r}")
        allowed.append(target)
    logger.info("Registry telemetry targets validated count=%s", len(allowed))
    return allowed


def plan_targets(schema: dict[str, Any]) -> tuple[list[TelemetryTarget], str]:
    mode = os.getenv("AUTODECK_AGENT_MODE", "deterministic").lower()
    logger.info("Registry planning started mode=%s", mode)
    if mode == "openai":
        try:
            targets = validate_targets(_openai_targets(schema), schema)
            logger.info("Registry OpenAI planning completed targets=%s", len(targets))
            return targets, "openai"
        except ValueError as error:
            logger.warning(
                "Registry planner output rejected error_type=%s error=%s; using deterministic fallback",
                type(error).__name__,
                error,
            )
        except Exception as error:
            logger.exception(
                "Registry planner failed error_type=%s error=%s; using deterministic fallback",
                type(error).__name__,
                error,
            )
    targets = validate_targets(_fallback_targets(schema), schema)
    logger.info("Registry deterministic planning completed targets=%s", len(targets))
    return targets, "deterministic"


def run_telemetry_setup() -> dict[str, Any]:
    logger.info("Registry telemetry setup started")
    manifest = load_manifest()
    logger.info("Registry Tree-sitter schema generation started")
    schema = build_registry_schema(manifest, BACKEND_ROOT)
    logger.info(
        "Registry Tree-sitter schema generated services=%s functions=%s",
        len(schema["services"]),
        sum(len(service["functions"]) for service in schema["services"]),
    )
    write_generated_manifest(manifest, schema, MANIFEST_PATH)
    agent_manifest = load_manifest()
    targets, provider = plan_targets(agent_manifest)
    applied_files = apply_telemetry_plan(targets, manifest, BACKEND_ROOT)
    logger.info("Registry telemetry setup applied_files=%s", len(applied_files))
    return {
        "status": "instrumented",
        "provider": provider,
        "registry_schema": agent_manifest,
        "targets": [target.to_dict() for target in targets],
        "applied_files": applied_files,
        "restart_required": bool(applied_files),
    }
