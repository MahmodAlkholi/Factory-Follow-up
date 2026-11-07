"""Celery application for background jobs (alerts, imports, maintenance)."""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "factory_dashboard.settings")

app = Celery("factory_dashboard")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):  # pragma: no cover - diagnostics helper
    return {"request": repr(self.request)}


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    """Extra periodic jobs declared in code (settings hold the rest)."""
    sender.add_periodic_task(crontab(minute="*/15"), dashboard.refresh_ongoing_downtime.s(), name="refresh-downtime")
