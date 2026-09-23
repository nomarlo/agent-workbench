"""Exports one page of orders per queue message."""

import logging

from exporter.records import InvalidRecord, to_warehouse_row
from exporter.warehouse import Warehouse, WarehouseRejected

logger = logging.getLogger(__name__)


class BatchFailed(Exception):
    pass


class ExportWorker:
    # Read by the /health endpoint: how many recent batches failed, and why.
    recent_failures: list[BaseException] = []

    def __init__(self, warehouse: Warehouse):
        self.warehouse = warehouse

    def handle(self, page: list[dict]) -> int:
        rows = []
        for raw in page:
            try:
                rows.append(to_warehouse_row(raw))
            except InvalidRecord:
                logger.warning("dropping invalid order %s", raw.get("order_id"))
        try:
            self.warehouse.insert_many(rows)
        except WarehouseRejected as error:
            ExportWorker.recent_failures.append(error)
            raise BatchFailed(f"{len(rows)} rows not exported") from error
        return len(rows)
