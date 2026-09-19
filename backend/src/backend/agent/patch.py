"""Safely apply approved source replacements for registered services."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = BACKEND_ROOT / "src" / "backend"
MANIFEST_PATH = SOURCE_ROOT / "manifests" / "services.json"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PatchDecision:
    service: str
    file: str
    expected_text: str
    replacement_text: str


@dataclass(frozen=True)
class PatchResult:
    applied: bool
    file: str
    message: str


def _load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def _service_entry(service_name: str) -> dict[str, Any]:
    for service in _load_manifest()["services"]:
        if service["name"] == service_name:
            return service
    raise ValueError(f"unknown service: {service_name}")


def _resolve_target(decision: PatchDecision) -> Path:
    target = Path(decision.file)
    if target.is_absolute():
        resolved = target.resolve()
    elif target.parts[:1] == ("backend",):
        resolved = (BACKEND_ROOT.parent / target).resolve()
    else:
        resolved = (BACKEND_ROOT / target).resolve()

    entrypoint = _service_entry(decision.service)["entrypoint"]
    module_name, _, _ = entrypoint.partition(":")
    expected_target = SOURCE_ROOT.joinpath(*module_name.split(".")[1:]).with_suffix(".py").resolve()
    expected_suffix = "/".join(module_name.split(".")[1:]) + ".py"

    # Models may describe the same registered source as either
    # src/backend/services/... or backend/src/backend/services/.... Normalize
    # only that known module path; never accept an arbitrary target.
    if resolved != expected_target:
        normalized_target = target.as_posix().lstrip("./")
        if not normalized_target.endswith(expected_suffix):
            raise ValueError(f"patch target is not the registered source for {decision.service}")
        resolved = expected_target

    source_root = SOURCE_ROOT.resolve()
    if source_root not in resolved.parents:
        raise ValueError(f"patch target is not the registered source for {decision.service}")
    return resolved


def apply_patch(decision: PatchDecision) -> PatchResult:
    target = _resolve_target(decision)
    logger.info("Patch started service=%s file=%s", decision.service, target)
    original = target.read_text(encoding="utf-8")
    occurrences = original.count(decision.expected_text)
    if occurrences != 1:
        logger.warning("Patch rejected service=%s file=%s reason=match_count", decision.service, target)
        raise ValueError(f"expected text must occur exactly once; found {occurrences}")

    updated = original.replace(decision.expected_text, decision.replacement_text, 1)
    target.write_text(updated, encoding="utf-8")

    try:
        compile(updated, str(target), "exec")
    except SyntaxError:
        logger.error("Patch validation failed service=%s file=%s", decision.service, target)
        return PatchResult(False, str(target), "patch applied but resulting source does not compile")
    logger.info("Patch applied service=%s file=%s", decision.service, target)
    return PatchResult(True, str(target), "patch applied and source compiled successfully")
