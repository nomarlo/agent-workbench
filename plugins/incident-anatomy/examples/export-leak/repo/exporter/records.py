"""Turning raw order rows from the shop into warehouse rows."""


class InvalidRecord(ValueError):
    pass


def to_warehouse_row(raw: dict) -> dict:
    if not raw.get("order_id"):
        raise InvalidRecord("order_id is required")
    return {
        "order_id": raw["order_id"],
        "customer": raw["customer"].strip(),
        "amount_cents": round(float(raw["amount"]) * 100),
        "notes": raw.get("notes", ""),
    }
