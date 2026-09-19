from fastapi import FastAPI
from pydantic import BaseModel, Field


app = FastAPI(title="AutoDeck Payment")


class PaymentRequest(BaseModel):
    item_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "payment", "status": "healthy"}


@app.post("/payments")
def authorize_payment(payment: PaymentRequest) -> dict[str, object]:
    return {
        "status": "authorized",
        "item_id": payment.item_id,
        "quantity": payment.quantity,
    }
