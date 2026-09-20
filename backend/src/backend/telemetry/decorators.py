"""Request and dependency telemetry that never changes service behavior."""

from __future__ import annotations

import functools
import inspect
import logging
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any, TypeVar, cast

from fastapi import HTTPException

from backend.relay import publish

F = TypeVar("F", bound=Callable[..., Any])
logger = logging.getLogger(__name__)


def _safe_publish(**event: Any) -> None:
    try:
        publish(**event)
    except Exception as error:
        # Telemetry is deliberately advisory. A relay outage must not fail an API request.
        logger.warning(
            "Telemetry event publish failed event_type=%s service=%s error_type=%s",
            event.get("type"),
            event.get("service"),
            error.__class__.__name__,
        )
        return


def _status_code(result: Any) -> int:
    return int(getattr(result, "status_code", 200) or 200)


def _emit_edges(service: str, operation: str, request_id: str, targets: Iterable[str]) -> None:
    for target in targets:
        _safe_publish(
            type="dependency_edge_observed",
            service=service,
            status="active",
            message=f"{service} called {target}",
            metadata={
                "source": service,
                "target_service": target,
                "operation": operation,
                "request_id": request_id,
            },
        )


def trace_endpoint(*, service: str, operation: str, targets: tuple[str, ...] = ()) -> Callable[[F], F]:
    """Decorate an approved endpoint with non-fatal runtime telemetry."""

    def decorator(function: F) -> F:
        if inspect.iscoroutinefunction(function):

            @functools.wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                request_id = str(uuid.uuid4())
                started = time.perf_counter()
                _safe_publish(
                    type="telemetry_request_started",
                    service=service,
                    status="started",
                    message=f"{operation} started",
                    metadata={"operation": operation, "request_id": request_id},
                )
                _emit_edges(service, operation, request_id, targets)
                try:
                    result = await function(*args, **kwargs)
                except HTTPException as error:
                    _safe_publish(
                        type="telemetry_request_failed",
                        service=service,
                        status="failed",
                        message=f"{operation} failed",
                        metadata={
                            "operation": operation,
                            "request_id": request_id,
                            "status_code": error.status_code,
                            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        },
                    )
                    raise
                except Exception:
                    _safe_publish(
                        type="telemetry_request_failed",
                        service=service,
                        status="failed",
                        message=f"{operation} failed",
                        metadata={
                            "operation": operation,
                            "request_id": request_id,
                            "status_code": 500,
                            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        },
                    )
                    raise
                _safe_publish(
                    type="telemetry_request_completed",
                    service=service,
                    status="completed",
                    message=f"{operation} completed",
                    metadata={
                        "operation": operation,
                        "request_id": request_id,
                        "status_code": _status_code(result),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                return result

            return cast(F, async_wrapper)

        @functools.wraps(function)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            request_id = str(uuid.uuid4())
            started = time.perf_counter()
            _safe_publish(
                type="telemetry_request_started",
                service=service,
                status="started",
                message=f"{operation} started",
                metadata={"operation": operation, "request_id": request_id},
            )
            _emit_edges(service, operation, request_id, targets)
            try:
                result = function(*args, **kwargs)
            except HTTPException as error:
                _safe_publish(
                    type="telemetry_request_failed",
                    service=service,
                    status="failed",
                    message=f"{operation} failed",
                    metadata={
                        "operation": operation,
                        "request_id": request_id,
                        "status_code": error.status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                raise
            except Exception:
                _safe_publish(
                    type="telemetry_request_failed",
                    service=service,
                    status="failed",
                    message=f"{operation} failed",
                    metadata={
                        "operation": operation,
                        "request_id": request_id,
                        "status_code": 500,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                raise
            _safe_publish(
                type="telemetry_request_completed",
                service=service,
                status="completed",
                message=f"{operation} completed",
                metadata={
                    "operation": operation,
                    "request_id": request_id,
                    "status_code": _status_code(result),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return result

        return cast(F, sync_wrapper)

    return decorator
