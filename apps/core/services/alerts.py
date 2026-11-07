"""
The monitoring loop: measure a KPI, compare it with the thresholds, raise an
Alert when it breaks and send the notification.

The engine is pure Python - it can be triggered by the Celery beat schedule
(every minute), by a button in the UI, or from a test.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from ..constants import AlertStatus, Metric, ThresholdScope
from ..models import Alert, DowntimeEvent, InventoryItem, Threshold
from . import kpi
from .filters import FilterParams

logger = logging.getLogger(__name__)


def scope_filters_for(threshold: Threshold, now=None) -> FilterParams:
    """Build the filter window a threshold is measured against."""
    now = now or timezone.localtime()
    today = now.date()
    return FilterParams(
        date_from=today,
        date_to=today,
        factory=threshold.factory_id,
        line=threshold.production_line_id,
        product=threshold.product_id,
        machine=threshold.machine_id,
    )


def ongoing_stop_minutes(filters: FilterParams, now=None) -> float:
    """Minutes the scoped line/machine has been stopped right now."""
    now = now or timezone.localtime()
    events = filters.apply_downtime(
        DowntimeEvent.objects.filter(ended_at__isnull=True)
    ).order_by("-started_at")
    longest = 0
    for event in events:
        minutes = int((now - event.started_at).total_seconds() // 60)
        longest = max(longest, max(minutes, 0))
    return longest


def low_stock_count(filters: FilterParams) -> int:
    items = filters.apply_inventory(InventoryItem.objects.select_related("product"))
    return sum(1 for item in items if item.is_low)


def metric_value(threshold: Threshold, now=None) -> float | None:
    """Measure the KPI a threshold watches."""
    filters = scope_filters_for(threshold, now=now)
    metric = threshold.metric

    if metric == Metric.OEE:
        return kpi.oee_summary(filters)["oee"]
    if metric == Metric.AVAILABILITY:
        return kpi.oee_summary(filters)["availability"]
    if metric == Metric.PERFORMANCE:
        return kpi.oee_summary(filters)["performance"]
    if metric == Metric.QUALITY:
        return kpi.quality_summary(filters)["pass_rate"]
    if metric == Metric.DEFECT_RATE:
        return kpi.quality_summary(filters)["defect_rate"]
    if metric == Metric.DOWNTIME_MINUTES:
        return kpi.downtime_summary(filters)["minutes"]
    if metric == Metric.LINE_STOPPED_MINUTES:
        return ongoing_stop_minutes(filters, now=now)
    if metric == Metric.OUTPUT_ATTACHMENT:
        return kpi.production_summary(filters)["attainment"]
    if metric == Metric.LOW_STOCK:
        return low_stock_count(filters)
    return None


def build_message(threshold: Threshold, value) -> str:
    operator = {
        "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    }.get(threshold.operator, threshold.operator)
    metric_label = dict(Metric.choices).get(threshold.metric, threshold.metric)
    return _("%(scope)s: %(metric)s is %(value)s %(operator)s %(threshold)s") % {
        "scope": threshold.scope_label(),
        "metric": metric_label,
        "value": value,
        "operator": operator,
        "threshold": threshold.value,
    }


def alert_is_duplicate(threshold: Threshold, now=None) -> bool:
    """True when the same rule fired inside its cooldown window."""
    now = now or timezone.localtime()
    window_start = now - timedelta(minutes=max(threshold.cooldown_minutes, 1))
    return Alert.objects.filter(
        threshold=threshold,
        created_at__gte=window_start,
    ).exclude(status=AlertStatus.RESOLVED).exists()


def resolve_threshold_alerts(threshold: Threshold, now=None) -> int:
    """Auto-close alerts whose KPI recovered."""
    now = now or timezone.now()
    return Alert.objects.filter(
        threshold=threshold, status__in=[AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]
    ).update(status=AlertStatus.RESOLVED, resolved_at=now)


def create_alert(threshold: Threshold, value, now=None) -> Alert:
    now = now or timezone.now()
    return Alert.objects.create(
        threshold=threshold,
        factory=threshold.factory,
        production_line=threshold.production_line,
        machine=threshold.machine,
        product=threshold.product,
        metric=threshold.metric,
        value=value,
        threshold_value=threshold.value,
        message=build_message(threshold, value),
        severity=threshold.severity,
        status=AlertStatus.OPEN,
        created_at=now,
    )


def alert_recipients(threshold: Threshold):
    recipients = set()
    for user in threshold.recipients.all():
        if user.email:
            recipients.add(user.email)
    recipients.update(settings.ALERTS_RECIPIENTS if hasattr(settings, "ALERTS_RECIPIENTS") else [])
    if not recipients:
        recipients.update(settings.ADMINS and [email for _, email in settings.ADMINS] or [])
    return sorted(recipients)


def send_alert_email(alert: Alert) -> bool:
    """Send the alert by email. Returns True when the mail was handed over."""
    recipients = alert_recipients(alert.threshold) if alert.threshold_id else []
    if not recipients:
        logger.info("Alert %s has no recipients - not emailed.", alert.pk)
        return False
    subject = f"[{alert.get_severity_display()}] {alert.message}"
    body = (
        f"A dashboard threshold was breached.\n\n"
        f"Message : {alert.message}\n"
        f"Severity: {alert.get_severity_display()}\n"
        f"Raised  : {alert.created_at:%Y-%m-%d %H:%M}\n\n"
        f"Open the dashboard: {settings.ALERTS_DASHBOARD_URL}\n"
    )
    try:
        send_mail(
            subject,
            body,
            settings.ALERTS_FROM_EMAIL,
            recipients,
            fail_silently=False,
        )
    except Exception:  # pragma: no cover - depends on the mail backend
        logger.exception("Could not send alert email to %s", recipients)
        return False
    alert.email_sent_at = timezone.now()
    alert.save(update_fields=["email_sent_at"])
    return True


def evaluate_thresholds(now=None, send_email: bool = True) -> list:
    """
    Evaluate every active threshold.

    Returns the list of alerts that were created during this run.
    """
    now = now or timezone.now()
    created = []
    for threshold in Threshold.objects.filter(is_active=True).select_related(
        "factory", "production_line", "machine", "product"
    ):
        try:
            value = metric_value(threshold, now=now)
        except Exception:  # pragma: no cover - defensive, one bad rule must not stop the rest
            logger.exception("Could not evaluate threshold %s", threshold.pk)
            continue

        if value is None:
            continue

        if threshold.passes(value):
            if alert_is_duplicate(threshold, now=now):
                continue
            alert = create_alert(threshold, value, now=now)
            created.append(alert)
            if send_email and threshold.notify_email:
                send_alert_email(alert)
        else:
            resolve_threshold_alerts(threshold, now=now)
    return created


def open_alerts_qs():
    return Alert.objects.filter(status=AlertStatus.OPEN).select_related(
        "factory", "production_line", "machine", "product", "threshold"
    )


def acknowledge_alert(alert: Alert, user) -> Alert:
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = timezone.now()
    alert.acknowledged_by = user
    alert.save(update_fields=["status", "acknowledged_at", "acknowledged_by"])
    return alert


def resolve_alert(alert: Alert) -> Alert:
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = timezone.now()
    alert.save(update_fields=["status", "resolved_at"])
    return alert
