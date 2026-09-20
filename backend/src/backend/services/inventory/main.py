from backend.telemetry import trace_endpoint
import logging

from fastapi import FastAPI, HTTPException

logger = logging.getLogger(__name__)

app = FastAPI(title="AutoDeck Inventory")

_inventory = {
    "widget": {"item_id": "widget", "quantity": 10},
    "gadget": {"item_id": "gadget", "quantity": 5},
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "inventory", "status": "healthy"}


@app.get("/inventory/{item_id}")
@trace_endpoint(service='inventory', operation='GET /inventory/{item_id}', targets=())
def get_inventory(item_id: str) -> dict[str, str | int | bool]:
    logger.info("Inventory lookup started item_id=%s", item_id)
    item = _inventory.get(item_id)
    if item is None:
        logger.warning("Inventory item not found item_id=%s", item_id)
        raise HTTPException(status_code=404, detail="item not found")

    logger.info("Inventory lookup completed item_id=%s quantity=%s", item_id, item["quantity"])
    return {**item, "available": item["quantity"] > 0}
