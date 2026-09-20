from backend.telemetry import trace_endpoint
import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

app = FastAPI(title="AutoDeck Payment")


class PaymentRequest(BaseModel):
    item_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "payment", "status": "healthy"}


@app.post("/payments")
@trace_endpoint(service='payment', operation='POST /payments', targets=())
def authorize_payment(payment: PaymentRequest) -> dict[str, object]:
    logger.info("Payment authorization started item_id=%s quantity=%s", payment.item_id, payment.quantity)
    logger.info("Payment authorization completed item_id=%s", payment.item_id)
    return {
        "status": "authorized",
        "item_id": payment.item_id,
        "quantity": payment.quantity,
    }
