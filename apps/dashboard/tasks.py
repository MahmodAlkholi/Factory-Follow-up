"""Celery tasks for the dashboard."""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="dashboard.evaluate_thresholds", ignore_result=True)
def evaluate_thresholds():
    """Measure every active threshold and raise alerts when one breaks."""
    from apps.core.services.alerts import evaluate_thresholds as _evaluate

    try:
        created = _evaluate()
        logger.info("Threshold evaluation finished, %s new alert(s).", len(created))
        return len(created)
    except Exception:  # pragma: no cover - keep the beat alive
        logger.exception("Threshold evaluation failed")
        return 0


@shared_task(name="dashboard.refresh_ongoing_downtime", ignore_result=True)
def refresh_ongoing_downtime():
    """
    Keep the duration of *ongoing* downtime events up to date.

    A machine that is still broken has no ``ended_at``, so its duration has
    to be recalculated - otherwise the dashboards show a stale number.
    """
    from apps.core.models import DowntimeEvent

    now = timezone.now()
    updated = 0
    for event in DowntimeEvent.objects.filter(ended_at__isnull=True):
        minutes = event.compute_duration()
        if minutes != event.duration_minutes:
            event.duration_minutes = minutes
            event.save(update_fields=["duration_minutes", "updated_at"])
            updated += 1
    logger.debug("Refreshed %s ongoing downtime event(s).", updated)
    return updated
