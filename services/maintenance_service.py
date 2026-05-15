import logging

from config import DOCUMENT_HISTORY_RETENTION_DAYS, SERVICE_METRICS_RETENTION_DAYS
from database.db import (
    cleanup_service_metrics_older_than,
    delete_document_history_older_than,
)

logger = logging.getLogger(__name__)


async def run_maintenance_cleanup() -> dict[str, int]:
    cleaned_history = await delete_document_history_older_than(
        DOCUMENT_HISTORY_RETENTION_DAYS
    )
    cleaned_metrics = await cleanup_service_metrics_older_than(
        SERVICE_METRICS_RETENTION_DAYS
    )

    if cleaned_history or cleaned_metrics:
        logger.info(
            "Maintenance cleanup: document_history=%s service_metrics=%s",
            cleaned_history,
            cleaned_metrics,
        )

    return {
        "document_history": cleaned_history,
        "service_metrics": cleaned_metrics,
    }
