"""The warehouse client. Its columns have fixed widths, like any SQL table; the rows
themselves live in the warehouse, not in this process."""

AMOUNT_CENTS_LIMIT = 10**13  # amount is numeric(15,2) in the warehouse


class WarehouseRejected(Exception):
    pass


class Warehouse:
    def __init__(self):
        self.inserted = 0

    def insert_many(self, rows: list[dict]):
        for row in rows:
            if abs(row["amount_cents"]) >= AMOUNT_CENTS_LIMIT:
                raise WarehouseRejected(f"amount out of range for order {row['order_id']}")
        self.inserted += len(rows)
