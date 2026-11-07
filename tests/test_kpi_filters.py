"""Filters and KPI calculations."""

from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils import translation

from apps.core.models import DowntimeEvent, ProductionLog, QualityCheck
from apps.core.services import kpi
from apps.core.services.filters import FilterParams

pytestmark = pytest.mark.django_db


def filters_for(**kwargs):
    today = timezone.localdate()
    base = {"date_from": today - timedelta(days=6), "date_to": today}
    base.update(kwargs)
    return FilterParams(**base)


def test_production_summary(production_logs):
    summary = kpi.production_summary(filters_for())
    assert summary["produced"] == 900
    assert summary["good"] == 855
    assert summary["defect"] == 45
    assert summary["defect_rate"] == 5.0
    assert summary["target"] == 1080


def test_filter_by_line(other_line, production_logs):
    summary = kpi.production_summary(filters_for(line=other_line.id))
    assert summary["produced"] == 0


def test_filter_by_date_range_excludes_older_data(production_logs):
    today = timezone.localdate()
    summary = kpi.production_summary(
        FilterParams(date_from=today, date_to=today)
    )
    assert summary["produced"] == 300


def test_oee_uses_availability_performance_and_quality(production_logs, machine):
    downtime = DowntimeEvent.objects.create(
        machine=machine,
        started_at=timezone.now() - timedelta(hours=2),
        ended_at=timezone.now() - timedelta(hours=1),
    )
    oee = kpi.oee_summary(filters_for())
    assert oee["availability"] < 100
    assert oee["performance"] <= 100
    assert oee["quality"] == 95.0
    assert 0 < oee["oee"] <= 100
    assert oee["downtime_minutes"] == 60


def test_downtime_pareto_is_sorted_and_cumulative(machine):
    for minutes, reason in ((90, "mechanical"), (30, "electrical"), (30, "material")):
        start = timezone.now() - timedelta(hours=5)
        DowntimeEvent.objects.create(
            machine=machine,
            started_at=start,
            ended_at=start + timedelta(minutes=minutes),
            reason_category=reason,
        )
    pareto = kpi.downtime_pareto(filters_for())
    assert pareto[0]["reason"] == "mechanical"
    assert pareto[0]["minutes"] == 90
    assert pareto[-1]["cumulative"] == 100.0


def test_hourly_trend_covers_all_24_hours(production_logs):
    trend = kpi.hourly_trend(filters_for())
    assert len(trend) == 24
    assert trend[8]["produced"] == 300  # three days of data at 08:00
    assert trend[0]["produced"] == 0


def test_comparison_by_line_and_shift(production_logs):
    by_line = kpi.comparison_by_line(filters_for())
    by_shift = kpi.comparison_by_shift(filters_for())
    assert by_line[0]["produced"] == 900
    assert by_shift[0]["produced"] == 900
    assert by_shift[0]["attainment"] == 83.33


def test_filter_query_round_trip(production_logs):
    filters = filters_for(factory=1, line=2)
    assert filters.as_query_dict()["factory"] == 1
    assert filters.as_query_dict()["line"] == 2


def test_restricted_for_narrows_the_filters(supervisor_user, line):
    filters = FilterParams(factory=99, line=88).restricted_for(supervisor_user)
    assert filters.line == supervisor_user.profile.production_line_id
    # The factory is derived from the line of the profile.
    assert filters.factory == line.factory_id


# ---------------------------------------------------------------------------
# The measurement window
# ---------------------------------------------------------------------------
def test_window_days_follows_the_data_of_an_open_ended_window(production_logs):
    """Without a date range the window covers the whole history."""
    assert kpi.window_days(FilterParams()) == 3
    assert kpi.window_days(filters_for()) == 7


def test_oee_stays_sane_for_an_open_ended_window(production_logs, machine):
    """The planned production time has to follow the measured window.

    Otherwise the downtime of the whole history is compared with the planned
    time of a single day, the availability drops to zero and the OEE with it.
    """
    start = timezone.now() - timedelta(hours=2)
    DowntimeEvent.objects.create(
        machine=machine,
        started_at=start,
        ended_at=start + timedelta(minutes=60),
    )
    oee = kpi.oee_summary(FilterParams())
    assert oee["days"] == 3
    assert oee["availability"] > 0
    assert oee["oee"] > 0
    assert oee["oee"] <= 100


def test_oee_of_a_closed_window_is_unaffected(production_logs, machine):
    start = timezone.now() - timedelta(hours=2)
    DowntimeEvent.objects.create(
        machine=machine,
        started_at=start,
        ended_at=start + timedelta(minutes=60),
    )
    oee = kpi.oee_summary(filters_for())
    assert oee["days"] == 7
    assert oee["availability"] > 0


# ---------------------------------------------------------------------------
# Translations of the grouped labels
# ---------------------------------------------------------------------------
def test_pareto_labels_follow_the_active_language(machine):
    start = timezone.now() - timedelta(hours=5)
    DowntimeEvent.objects.create(
        machine=machine,
        started_at=start,
        ended_at=start + timedelta(minutes=30),
        reason_category="mechanical",
    )
    with translation.override("en"):
        english = kpi.downtime_pareto(filters_for())[0]["label"]
    with translation.override("ar"):
        arabic = kpi.downtime_pareto(filters_for())[0]["label"]
    assert english == "Mechanical"
    assert arabic == "ميكانيكي"
    # The raw code must never leak into the label.
    assert kpi.downtime_pareto(filters_for())[0]["reason"] == "mechanical"


def test_defect_type_labels_follow_the_active_language(line, shift, product):
    QualityCheck.objects.create(
        production_line=line,
        shift=shift,
        product=product,
        checked_at=timezone.now(),
        qty_checked=100,
        qty_passed=95,
        qty_defected=5,
        defect_type="dimensional",
    )
    with translation.override("en"):
        english = kpi.quality_by_defect_type(filters_for())[0]["label"]
    with translation.override("ar"):
        arabic = kpi.quality_by_defect_type(filters_for())[0]["label"]
    assert english == "Dimensional"
    assert arabic == "أبعاد"
