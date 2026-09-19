"""Shared HTTP and SSE relay for AutoDeck recovery events."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .events import Event, relay

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
    except (httpx.HTTPError, ValueError):
        healthy = False
    result["status"] = "healthy" if healthy else "unhealthy"
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
    published = relay.publish(**event.model_dump())
    if published is None:
        raise RuntimeError("event could not be published")
    return published.to_dict()


async def stream_events(request: Request) -> AsyncIterator[str]:
    subscriber: Queue[Event] = relay.subscribe()
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
                yield f"data: {json.dumps(event.to_dict())}\n\n"
                last_keepalive = asyncio.get_running_loop().time()
            if asyncio.get_running_loop().time() - last_keepalive >= 15:
                yield ": keepalive\n\n"
                last_keepalive = asyncio.get_running_loop().time()
            await asyncio.sleep(0.5)
    finally:
        relay.unsubscribe(subscriber)


@app.get("/events/stream")
async def event_stream(request: Request) -> StreamingResponse:
    return StreamingResponse(
        stream_events(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

@app.get("/health")
def get_health():
    return {"status":"healthy"}
