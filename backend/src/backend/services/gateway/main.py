import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI(title="AutoDeck Gateway")
ORDERS_URL = os.getenv("ORDERS_URL", "http://127.0.0.1:8002")


class OrderRequest(BaseModel):
    item_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "gateway", "status": "healthy"}


@app.post("/orders")
async def forward_order(order: OrderRequest) -> dict[str, object]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{ORDERS_URL}/orders", json=order.model_dump())
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="orders service unavailable") from error

    if response.is_error:
        raise HTTPException(status_code=response.status_code, detail=response.json().get("detail", "orders service error"))

    return {"service": "gateway", "order": response.json()}
