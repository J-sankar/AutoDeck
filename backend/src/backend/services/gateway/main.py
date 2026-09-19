import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.relay import publish

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
        publish(
            type="application_failure",
            service="gateway",
            status="failed",
            message="orders service unavailable",
            metadata={
                "target_service": "orders",
                "status_code": 502,
                "detail": "orders service unavailable",
                "request": order.model_dump(),
            },
        )
        raise HTTPException(status_code=502, detail="orders service unavailable") from error

    if response.is_error:
        try:
            detail = response.json().get("detail", "orders service error")
        except ValueError:
            detail = "orders service error"
        publish(
            type="application_failure",
            service="gateway",
            status="failed",
            message=str(detail),
            metadata={
                "target_service": "orders",
                "status_code": response.status_code,
                "detail": str(detail),
                "request": order.model_dump(),
            },
        )
        raise HTTPException(status_code=response.status_code, detail=detail)

    return {"service": "gateway", "order": response.json()}
