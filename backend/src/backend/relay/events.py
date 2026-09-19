"""Thread-safe, bounded, process-local recovery events."""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

MAX_EVENTS = 100
PUBLISH_ATTEMPTS = 3
PUBLISH_RETRY_DELAY = 0.05


@dataclass(frozen=True)
class Event:
    id: str
    timestamp: str
    type: str
    service: str
    status: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventRelay:
    """Keep the latest recovery events in a process-local bounded store."""

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._events: deque[Event] = deque(maxlen=max_events)
        self._lock = Lock()

    def publish(
        self,
        *,
        type: str,
        service: str,
        status: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> Event | None:
        event = Event(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            type=type,
            service=service,
            status=status,
            message=message,
            metadata=dict(metadata or {}),
        )
        for attempt in range(1, PUBLISH_ATTEMPTS + 1):
            try:
                with self._lock:
                    self._events.append(event)
                return event
            except Exception as error:  # pragma: no cover - defensive boundary
                if attempt < PUBLISH_ATTEMPTS:
                    time.sleep(PUBLISH_RETRY_DELAY)
                else:
                    logger.exception(
                        "Relay publish failed event_type=%s service=%s attempts=%s error_type=%s",
                        type,
                        service,
                        attempt,
                        error.__class__.__name__,
                    )
        return None

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must not be negative")
            events = events[-limit:] if limit else []
        return [event.to_dict() for event in reversed(events)]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


relay = EventRelay()


def publish(**kwargs: Any) -> Event | None:
    return relay.publish(**kwargs)


def recent(limit: int | None = None) -> list[dict[str, Any]]:
    return relay.recent(limit)


def clear() -> None:
    relay.clear()
