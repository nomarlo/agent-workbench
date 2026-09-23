"""The queue loop: a failed message is redelivered with the same cursor."""

import logging

from exporter.worker import BatchFailed, ExportWorker

logger = logging.getLogger(__name__)


def run(queue: list[str], worker: ExportWorker, fetch_page):
    while queue:
        cursor = queue.pop(0)
        page = fetch_page(cursor)
        try:
            worker.handle(page)
        except BatchFailed:
            logger.exception("export of %s failed, redelivering", cursor)
            queue.append(cursor)
