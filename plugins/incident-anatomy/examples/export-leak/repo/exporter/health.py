"""GET /health for the export worker."""

from exporter.worker import ExportWorker


def health() -> dict:
    failures = ExportWorker.recent_failures
    return {
        "recent_failures": len(failures),
        "last_failure": str(failures[-1]) if failures else None,
    }
