"""Shared HTTP and SSE relay for AutoDeck recovery events."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .events import Event, relay

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = BACKEND_ROOT / "src" / "backend" / "manifests" / "services.json"


class EventRequest(BaseModel):
    type: str = Field(min_length=1)
    service: str = Field(min_length=1)
    status: str = Field(min_length=1)
    message: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_services() -> list[dict[str, Any]]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["services"]


async def service_status(service: dict[str, Any], client: httpx.AsyncClient) -> dict[str, Any]:
    result = dict(service)
    url = f"http://127.0.0.1:{service['port']}{service['health']}"
    try:
        response = await client.get(url)
        healthy = response.is_success and response.json() == {
            "service": service["name"],
            "status": "healthy",
        }
        result["status"] = "healthy" if healthy else "unhealthy"
    except httpx.HTTPError:
        result["status"] = "unknown"
    except ValueError:
        result["status"] = "unhealthy"
    return result


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="AutoDeck Relay", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "relay", "status": "healthy"}


@app.get("/services")
async def services() -> dict[str, list[dict[str, Any]]]:
    registered = load_services()
    async with httpx.AsyncClient(timeout=0.75) as client:
        current = [await service_status(service, client) for service in registered]
    return {"services": current}


@app.get("/events")
def events(limit: int = Query(default=100, ge=1, le=100)) -> dict[str, list[dict[str, Any]]]:
    return {"events": relay.recent(limit)}


@app.post("/events", status_code=201)
def publish_event(event: EventRequest) -> dict[str, Any]:
    logger.info("Relay event received type=%s service=%s status=%s", event.type, event.service, event.status)
    published = relay.publish(**event.model_dump())
    if published is None:
        raise RuntimeError("event could not be published")
    return published.to_dict()


@app.get("/topology")
async def topology() -> dict[str, list[dict[str, Any]]]:
    registered = load_services()
    async with httpx.AsyncClient(timeout=0.75) as client:
        nodes = [await service_status(service, client) for service in registered]

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    registered_names = {service["name"] for service in registered}
    for service in registered:
        for target in service.get("depends_on", []):
            if target in registered_names:
                edges[(service["name"], target)] = {
                    "source": service["name"],
                    "target": target,
                    "status": "planned",
                    "last_seen": None,
                }

    for event in relay.recent(100):
        if event["type"] != "dependency_edge_observed":
            continue
        metadata = event.get("metadata", {})
        source = metadata.get("source", event.get("service"))
        target = metadata.get("target_service")
        if isinstance(source, str) and isinstance(target, str):
            key = (source, target)
            if key in edges:
                edges[key].update(status="active", last_seen=event["timestamp"])
            else:
                logger.warning(
                    "Ignoring runtime topology edge outside manifest source=%s target=%s",
                    source,
                    target,
                )
    result = {"nodes": nodes, "edges": list(edges.values())}
    logger.info("Relay topology requested nodes=%s edges=%s", len(nodes), len(result["edges"]))
    return result


async def stream_events(request: Request) -> AsyncIterator[str]:
    subscriber: Queue[Event] = relay.subscribe()
    logger.info("Relay SSE client connected")
    yield "retry: 2000\n\n"
    yield ": connected\n\n"
    last_keepalive = asyncio.get_running_loop().time()
    try:
        while True:
            if await request.is_disconnected():
                return
            while True:
                try:
                    event = subscriber.get_nowait()
                except Empty:
                    break
                yield f"id: {event.id}\ndata: {json.dumps(event.to_dict())}\n\n"
                last_keepalive = asyncio.get_running_loop().time()
            if asyncio.get_running_loop().time() - last_keepalive >= 15:
                yield ": keepalive\n\n"
                last_keepalive = asyncio.get_running_loop().time()
            await asyncio.sleep(0.5)
    finally:
        relay.unsubscribe(subscriber)
        logger.info("Relay SSE client disconnected")


@app.get("/events/stream")
async def event_stream(request: Request) -> StreamingResponse:
    return StreamingResponse(
        stream_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )
