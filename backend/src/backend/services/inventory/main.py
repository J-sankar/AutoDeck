from fastapi import FastAPI, HTTPException


app = FastAPI(title="AutoDeck Inventory")

_inventory = {
    "widget": {"item_id": "widget", "quantity": 10},
    "gadget": {"item_id": "gadget", "quantity": 5},
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "inventory", "status": "healthy"}


@app.get("/inventory/{item_id}")
def get_inventory(item_id: str) -> dict[str, str | int | bool]:
    item = _inventory.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")

    return {**item, "available": item["quantity"] > 0}
