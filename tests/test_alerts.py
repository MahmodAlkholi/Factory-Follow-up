"""The threshold engine, the alert lifecycle and the notification email."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.core.constants import AlertStatus, ComparisonOperator, Metric, Severity, ThresholdScope
from apps.core.models import Alert, DowntimeEvent, QualityCheck, Threshold
from apps.core.services.alerts import (
    acknowledge_alert,
    evaluate_thresholds,
    metric_value,
    resolve_alert,
)

pytestmark = pytest.mark.django_db


def make_threshold(**kwargs):
    defaults = {
        "name": "Defect rate above 3%",
        "scope_type": ThresholdScope.LINE,
        "metric": Metric.DEFECT_RATE,
        "operator": ComparisonOperator.GT,
        "value": 3,
        "severity": Severity.WARNING,
        "cooldown_minutes": 0,
        "notify_email": False,
    }
    defaults.update(kwargs)
    return Threshold.objects.create(**defaults)


def test_threshold_passes():
    threshold = make_threshold(value=3)
    assert threshold.passes(4) is True
    assert threshold.passes(3) is False

    threshold.operator = ComparisonOperator.LT
    assert threshold.passes(2) is True


def test_evaluate_raises_an_alert_when_the_defect_rate_is_too_high(line, product):
    make_threshold(value=3)
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=90,
        qty_defected=10,
    )
    created = evaluate_thresholds()
    assert len(created) == 1
    alert = created[0]
    assert alert.metric == Metric.DEFECT_RATE
    assert alert.severity == Severity.WARNING
    assert Alert.objects.filter(status=AlertStatus.OPEN).count() == 1


def test_no_alert_when_the_kpi_is_fine(line, product):
    make_threshold(value=3)
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=100,
        qty_defected=0,
    )
    assert evaluate_thresholds() == []


def test_alert_is_not_repeated_inside_the_cooldown(line, product):
    make_threshold(value=3, cooldown_minutes=60)
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=90,
        qty_defected=10,
    )
    assert len(evaluate_thresholds()) == 1
    assert evaluate_thresholds() == []
    assert Alert.objects.count() == 1


def test_alert_is_auto_resolved_when_the_kpi_recovers(line, product):
    threshold = make_threshold(value=3)
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=90,
        qty_defected=10,
    )
    created = evaluate_thresholds()
    assert len(created) == 1

    QualityCheck.objects.all().delete()
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=100,
        qty_defected=0,
    )
    evaluate_thresholds()
    alert = Alert.objects.get()
    assert alert.status == AlertStatus.RESOLVED
    assert alert.resolved_at is not None


def test_line_stopped_metric_counts_the_running_downtime(machine):
    threshold = make_threshold(
        metric=Metric.LINE_STOPPED_MINUTES,
        scope_type=ThresholdScope.GLOBAL,
        operator=ComparisonOperator.GT,
        value=15,
    )
    DowntimeEvent.objects.create(
        machine=machine,
        started_at=timezone.now() - timedelta(minutes=40),
        reason_category="mechanical",
    )
    assert metric_value(threshold) == 40
    assert len(evaluate_thresholds()) == 1


def test_alert_email_is_sent_to_the_recipients(line, product, manager_user):
    threshold = make_threshold(value=3, notify_email=True)
    threshold.recipients.add(manager_user)
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=90,
        qty_defected=10,
    )
    created = evaluate_thresholds()
    assert len(created) == 1
    assert len(mail.outbox) == 1
    assert manager_user.email in mail.outbox[0].to
    created[0].refresh_from_db()
    assert created[0].email_sent_at is not None


def test_acknowledge_and_resolve(line, product):
    threshold = make_threshold(value=3)
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=90,
        qty_defected=10,
    )
    alert = evaluate_thresholds()[0]
    acknowledge_alert(alert, None)
    assert alert.status == AlertStatus.ACKNOWLEDGED
    resolve_alert(alert)
    assert alert.status == AlertStatus.RESOLVED


def test_celery_task_runs_the_engine(line, product):
    from apps.dashboard.tasks import evaluate_thresholds as task

    make_threshold(value=3)
    QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=90,
        qty_defected=10,
    )
    assert task() == 1


def test_ongoing_downtime_task_refreshes_the_duration(machine):
    from apps.dashboard.tasks import refresh_ongoing_downtime

    event = DowntimeEvent.objects.create(
        machine=machine,
        started_at=timezone.now() - timedelta(minutes=50),
        duration_minutes=0,
        reason_category="mechanical",
    )
    refresh_ongoing_downtime()
    event.refresh_from_db()
    assert event.duration_minutes >= 49
