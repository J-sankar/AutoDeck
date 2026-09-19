"""Model-backed diagnosis with a deterministic repair fallback."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from .patch import PatchDecision

logger = logging.getLogger(__name__)
load_dotenv()


@dataclass(frozen=True)
class DiagnosisResult:
    action: str
    service: str
    file: str
    expected_text: str
    replacement_text: str
    reason: str

    @property
    def patch(self) -> PatchDecision | None:
        if self.action != "patch":
            return None
        return PatchDecision(
            service=self.service,
            file=self.file,
            expected_text=self.expected_text,
            replacement_text=self.replacement_text,
        )


REPAIR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["patch", "no_repair"]},
        "service": {"type": "string"},
        "file": {"type": "string"},
        "expected_text": {"type": "string"},
        "replacement_text": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "action",
        "service",
        "file",
        "expected_text",
        "replacement_text",
        "reason",
    ],
}


def redact_secrets(value: str) -> str:
    value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", value)
    return re.sub(
        r"(?i)(api[_-]?key|token|secret|password)\s*([:=])\s*(['\"]?)[^\s,;\"']+\3",
        r"\1\2\3[REDACTED]\3",
        value,
    )


def deterministic_diagnosis(
    service: str,
    status_code: int,
    detail: str,
    source: str,
) -> DiagnosisResult:
    if (
        service == "orders"
        and status_code == 409
        and detail == "insufficient inventory"
        and 'inventory["quantity"] <= order.quantity' in source
    ):
        return DiagnosisResult(
            action="patch",
            service="orders",
            file="src/backend/services/orders/main.py",
            expected_text='inventory["quantity"] <= order.quantity',
            replacement_text='inventory["quantity"] < order.quantity',
            reason="The inventory boundary comparison rejects an order for exactly the available quantity.",
        )
    return DiagnosisResult(
        action="no_repair",
        service=service,
        file="",
        expected_text="",
        replacement_text="",
        reason="No approved deterministic repair matches the observed failure.",
    )


def _model_result(response: Any) -> DiagnosisResult:
    output_text = getattr(response, "output_text", "")
    if not output_text:
        raise ValueError("model returned no structured output")
    payload = json.loads(output_text)
    required = {"action", "service", "file", "expected_text", "replacement_text", "reason"}
    if set(payload) != required or payload["action"] not in {"patch", "no_repair"}:
        raise ValueError("model response does not match the repair schema")
    if not all(isinstance(payload[field], str) for field in required):
        raise ValueError("repair schema fields must be strings")
    return DiagnosisResult(**payload)


def diagnose_with_openai(
    *,
    service_entry: dict[str, Any],
    status_code: int,
    detail: str,
    request: dict[str, Any] | None,
    source: str,
    client: Any | None = None,
) -> DiagnosisResult:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not model:
        raise RuntimeError("OPENAI_MODEL is not configured")

    if client is None:
        from openai import OpenAI

        client:OpenAI = OpenAI(api_key=api_key)

    instructions = (
        "You are a read-only software diagnosis agent. Inspect the supplied service context and "
        "return only the requested structured repair decision. Never propose shell commands, "
        "arbitrary files, process actions, or edits outside the supplied service source. "
        "Return no_repair when the evidence is insufficient. For patch, expected_text must "
        "match the source exactly and replacement_text must be a minimal safe replacement."
    )
    input_context = json.dumps(
        {
            "service": service_entry,
            "canonical_source_file": "src/backend/"
            + "/".join(service_entry["entrypoint"].split(":", 1)[0].split(".")[1:])
            + ".py",
            "failure": {"status_code": status_code, "detail": detail, "request": request or {}},
            "source": redact_secrets(source),
        },
        indent=2,
    )
    logger.info(
        "OpenAI diagnosis started service=%s model=%s status_code=%s",
        service_entry.get("name"),
        model,
        status_code,
    )
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=input_context,
        text={
            "format": {
                "type": "json_schema",
                "name": "repair_decision",
                "strict": True,
                "schema": REPAIR_SCHEMA,
            }
        },
    )
    result = _model_result(response)
    logger.info("OpenAI diagnosis completed service=%s action=%s", result.service, result.action)
    return result


def diagnose_failure(
    service: str,
    status_code: int,
    detail: str,
    source: str,
    *,
    service_entry: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    client: Any | None = None,
) -> DiagnosisResult:
    mode = os.getenv("AUTODECK_AGENT_MODE", "deterministic").lower()
    logger.info("Diagnosis started service=%s mode=%s status_code=%s", service, mode, status_code)
    if mode == "openai":
        try:
            if service_entry is None:
                raise ValueError("service manifest entry is required for OpenAI diagnosis")
            return diagnose_with_openai(
                service_entry=service_entry,
                status_code=status_code,
                detail=detail,
                request=request,
                source=source,
                client=client,
            )
        except Exception as error:
            # Diagnosis is advisory; provider failures must not bypass the
            # deterministic fallback or the patch executor's safety checks.
            logger.warning(
                "OpenAI diagnosis failed service=%s error_type=%s; using fallback",
                service,
                type(error).__name__,
            )

    result = deterministic_diagnosis(service, status_code, detail, source)
    logger.info("Diagnosis completed service=%s action=%s provider=deterministic", service, result.action)
    return result
