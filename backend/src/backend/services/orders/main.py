import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
async def create_order(order: OrderRequest) -> dict[str, object]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{INVENTORY_URL}/inventory/{order.item_id}")
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="inventory service unavailable") from error

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="item not found")
    if response.is_error:
        raise HTTPException(status_code=502, detail="inventory service error")

    inventory = response.json()
    if inventory["quantity"] < order.quantity:
        raise HTTPException(status_code=409, detail="insufficient inventory")

    try:
        async with httpx.AsyncClient() as client:
            payment_response = await client.post(
                f"{PAYMENT_URL}/payments",
                json=order.model_dump(),
            )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="payment service unavailable") from error

    if payment_response.is_error:
        raise HTTPException(status_code=502, detail="payment service error")

    return {
        "status": "accepted",
        "item_id": order.item_id,
        "quantity": order.quantity,
        "inventory": inventory,
        "payment": payment_response.json(),
    }
