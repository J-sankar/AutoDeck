from backend.telemetry import trace_endpoint
import os
import logging

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="AutoDeck Orders")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://127.0.0.1:8003")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://127.0.0.1:8004")


class OrderRequest(BaseModel):
    item_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "orders", "status": "healthy"}


@app.post("/orders")
@trace_endpoint(service='orders', operation='POST /orders', targets=('inventory', 'payment'))
async def create_order(order: OrderRequest) -> dict[str, object]:
    logger.info("Orders request received item_id=%s quantity=%s", order.item_id, order.quantity)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{INVENTORY_URL}/inventory/{order.item_id}")
    except httpx.HTTPError as error:
        logger.exception("Orders inventory request failed error_type=%s", error.__class__.__name__)
        raise HTTPException(status_code=502, detail="inventory service unavailable") from error

    logger.info("Orders inventory response status_code=%s", response.status_code)
    if response.status_code == 404:
        logger.warning("Orders item not found item_id=%s", order.item_id)
        raise HTTPException(status_code=404, detail="item not found")
    if response.is_error:
        logger.warning("Orders inventory failure status_code=%s", response.status_code)
        raise HTTPException(status_code=502, detail="inventory service error")

    inventory = response.json()
    if inventory["quantity"] < order.quantity:
        logger.warning(
            "Orders insufficient inventory item_id=%s available=%s requested=%s",
            order.item_id,
            inventory["quantity"],
            order.quantity,
        )
        raise HTTPException(status_code=409, detail="insufficient inventory")

    try:
        async with httpx.AsyncClient() as client:
            payment_response = await client.post(
                f"{PAYMENT_URL}/payments",
                json=order.model_dump(),
            )
    except httpx.HTTPError as error:
        logger.exception("Orders payment request failed error_type=%s", error.__class__.__name__)
        raise HTTPException(status_code=502, detail="payment service unavailable") from error

    logger.info("Orders payment response status_code=%s", payment_response.status_code)
    if payment_response.is_error:
        logger.warning("Orders payment failure status_code=%s", payment_response.status_code)
        raise HTTPException(status_code=502, detail="payment service error")

    logger.info("Orders request completed item_id=%s", order.item_id)
    return {
        "status": "accepted",
        "item_id": order.item_id,
        "quantity": order.quantity,
        "inventory": inventory,
        "payment": payment_response.json(),
    }
