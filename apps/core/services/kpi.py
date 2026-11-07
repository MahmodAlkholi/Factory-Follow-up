"""
KPI aggregation - the single source of truth for every number on screen.

All functions take a :class:`~apps.core.services.filters.FilterParams`
instance and return plain dictionaries, so they can be used from a Django
view, a DRF serializer or a Celery task without changes.
"""

from collections import OrderedDict

from django.conf import settings
from django.db.models import Count, DecimalField, F, Max, Min, Sum, Value
from django.db.models.functions import Coalesce, TruncWeek
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.translation import gettext as _

from ..constants import DefectType, DowntimeReason, Metric
from ..models import (
    Alert,
    AlertStatus,
    DowntimeEvent,
    InventoryItem,
    ProductionLog,
    QualityCheck,
    StockMovement,
)

DECIMAL_ZERO = Value(0)


def _pct(numerator, denominator, default=0.0):
    if not denominator:
        return default
    return round((numerator / denominator) * 100, 2)


def _choice_labels(choices) -> dict:
    """Value -> label map for a ``TextChoices`` enum, in the active language.

    The enum labels are lazy translation proxies, so the map follows the
    language that is active while the page is rendered.  Falling back to the
    raw value keeps an unexpected database value readable instead of blank.
    """
    return {value: force_str(label) for value, label in choices.choices}


# ---------------------------------------------------------------------------
# Measurement window
# ---------------------------------------------------------------------------
def _window_bounds(filters, production_qs, downtime_qs):
    """The ``(start, end)`` dates the filtered window really covers.

    ``FilterParams.days`` assumes a *closed* date range, which is what every
    page and every API call produces.  When the range is open - no
    ``date_from`` / ``date_to`` - the aggregates cover the whole history, so
    the window has to be derived from the data as well.
    """
    if filters.date_from and filters.date_to:
        return filters.date_from, filters.date_to

    starts, ends = [], []
    span = production_qs.aggregate(first=Min("date"), last=Max("date"))
    if span["first"]:
        starts.append(span["first"])
        ends.append(span["last"])
    span = downtime_qs.aggregate(first=Min("started_at"), last=Max("started_at"))
    if span["first"]:
        starts.append(timezone.localtime(span["first"]).date())
        ends.append(timezone.localtime(span["last"]).date())
    if not starts:
        return None, None
    return min(starts), max(ends)


def window_days(filters) -> int:
    """Number of days the measurement window covers.

    Without this the *planned* production time of the OEE would be counted for
    a single day while the downtime is summed over the whole history, which
    drives the availability - and therefore the OEE - down to zero.
    """
    start, end = _window_bounds(
        filters,
        filters.apply_production(ProductionLog.objects.all()),
        filters.apply_downtime(DowntimeEvent.objects.all()),
    )
    if not start or not end:
        return 1
    return max((end - start).days + 1, 1)


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------
def production_summary(filters) -> dict:
    """Output, target and defect numbers for the filtered window."""
    qs = filters.apply_production(ProductionLog.objects.all())
    agg = qs.aggregate(
        produced=Coalesce(Sum("qty_produced"), 0),
        good=Coalesce(Sum("qty_good"), 0),
        defect=Coalesce(Sum("qty_defect"), 0),
        target=Coalesce(Sum("target_qty"), 0),
        records=Count("id"),
    )
    produced = agg["produced"]
    target = agg["target"]
    return {
        "produced": produced,
        "good": agg["good"],
        "defect": agg["defect"],
        "target": target,
        "records": agg["records"],
        "defect_rate": _pct(agg["defect"], produced),
        "good_rate": _pct(agg["good"], produced),
        "attainment": _pct(produced, target),
    }


def output_today(filters) -> dict:
    """Output of *today* only - the number on the Overview KPI card."""
    today = timezone.localdate()
    today_filters = filters.replace(date_from=today, date_to=today)
    return production_summary(today_filters)


# ---------------------------------------------------------------------------
# OEE
# ---------------------------------------------------------------------------
def oee_summary(filters) -> dict:
    """
    Overall Equipment Effectiveness.

        Availability = (planned time - downtime) / planned time
        Performance  = actual output / target output
        Quality      = good pieces / produced pieces
        OEE          = A x P x Q
    """
    lines_count = filters.scoped_lines().count()

    production_qs = filters.apply_production(ProductionLog.objects.all())
    downtime_qs = filters.apply_downtime(DowntimeEvent.objects.all())

    start, end = _window_bounds(filters, production_qs, downtime_qs)
    days = max((end - start).days + 1, 1) if start and end else 1
    planned_minutes = lines_count * days * settings.PLANNED_SHIFT_MINUTES

    downtime_minutes = downtime_qs.aggregate(total=Coalesce(Sum("duration_minutes"), 0))["total"]
    ongoing = downtime_qs.filter(ended_at__isnull=True).count()

    prod = production_summary(filters)
    target = prod["target"]
    if not target:
        # Fall back to the line level daily targets when no target was entered.
        target = sum(line.target_daily_qty for line in filters.scoped_lines()) * days

    availability = _pct(max(planned_minutes - downtime_minutes, 0), planned_minutes)
    performance = min(_pct(prod["produced"], target), 100.0)
    quality = prod["good_rate"]
    oee = round((availability * performance * quality) / 10000, 2) if planned_minutes else 0.0

    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": oee,
        "planned_minutes": planned_minutes,
        "downtime_minutes": downtime_minutes,
        "downtime_hours": round(downtime_minutes / 60, 2),
        "ongoing_downtime_events": ongoing,
        "target": target,
        "produced": prod["produced"],
        "lines": lines_count,
        "days": days,
    }


# ---------------------------------------------------------------------------
# Downtime
# ---------------------------------------------------------------------------
def downtime_summary(filters) -> dict:
    qs = filters.apply_downtime(DowntimeEvent.objects.all())
    agg = qs.aggregate(
        minutes=Coalesce(Sum("duration_minutes"), 0),
        events=Count("id"),
    )
    ongoing = qs.filter(ended_at__isnull=True).count()
    return {
        "minutes": agg["minutes"],
        "hours": round(agg["minutes"] / 60, 2),
        "events": agg["events"],
        "ongoing": ongoing,
        "avg_minutes": round(agg["minutes"] / agg["events"], 1) if agg["events"] else 0,
    }


def downtime_pareto(filters) -> list:
    """Top reasons by downtime minutes with a cumulative percentage."""
    qs = filters.apply_downtime(DowntimeEvent.objects.all())
    rows = (
        qs.values("reason_category")
        .annotate(minutes=Coalesce(Sum("duration_minutes"), 0), events=Count("id"))
        .order_by("-minutes")
    )
    total = sum(row["minutes"] for row in rows) or 1
    labels = _choice_labels(DowntimeReason)
    data = []
    cumulative = 0.0
    for row in rows:
        share = round((row["minutes"] / total) * 100, 2)
        cumulative = round(cumulative + share, 2)
        data.append(
            {
                "reason": row["reason_category"],
                "label": labels.get(row["reason_category"], row["reason_category"]),
                "minutes": row["minutes"],
                "hours": round(row["minutes"] / 60, 2),
                "events": row["events"],
                "share": share,
                "cumulative": cumulative,
            }
        )
    return data


def downtime_by_machine(filters, limit: int = 15) -> list:
    qs = filters.apply_downtime(DowntimeEvent.objects.all())
    rows = (
        qs.values("machine__id", "machine__name", "machine__code", "production_line__name")
        .annotate(minutes=Coalesce(Sum("duration_minutes"), 0), events=Count("id"))
        .order_by("-minutes")[:limit]
    )
    return [
        {
            "machine_id": row["machine__id"],
            "machine": row["machine__name"],
            "code": row["machine__code"],
            "line": row["production_line__name"],
            "minutes": row["minutes"],
            "hours": round(row["minutes"] / 60, 2),
            "events": row["events"],
        }
        for row in rows
    ]


def downtime_timeline(filters, limit: int = 12) -> list:
    """Per machine timeline (start/end in minutes from window start)."""
    qs = filters.apply_downtime(DowntimeEvent.objects.all()).filter(ended_at__isnull=False)
    machines = list(
        qs.values("machine__id", "machine__name", "machine__code")
        .annotate(minutes=Coalesce(Sum("duration_minutes"), 0))
        .order_by("-minutes")[:limit]
    )
    names = {m["machine__id"]: m for m in machines}
    events = list(qs.filter(machine_id__in=list(names)).order_by("started_at")[:500])
    start, _end = _window_bounds(
        filters,
        filters.apply_production(ProductionLog.objects.all()),
        qs,
    )
    window_start = None
    if start:
        window_start = timezone.make_aware(
            timezone.datetime.combine(start, timezone.datetime.min.time()),
            timezone.get_current_timezone(),
        )
    timeline = OrderedDict()
    for machine_id, info in names.items():
        timeline[machine_id] = {
            "machine": info["machine__name"],
            "code": info["machine__code"],
            "total_minutes": info["minutes"],
            "events": [],
        }
    for event in events:
        entry = timeline.get(event.machine_id)
        if entry is None:
            continue
        start_min = 0
        if window_start:
            start_min = max(int((event.started_at - window_start).total_seconds() // 60), 0)
        end_min = start_min + event.duration_minutes
        entry["events"].append(
            {
                "start": start_min,
                "end": end_min,
                "duration": event.duration_minutes,
                "reason": event.get_reason_category_display(),
                "note": event.reason_note,
            }
        )
    return list(timeline.values())


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
def quality_summary(filters) -> dict:
    qs = filters.apply_quality(QualityCheck.objects.all())
    agg = qs.aggregate(
        checked=Coalesce(Sum("qty_checked"), 0),
        passed=Coalesce(Sum("qty_passed"), 0),
        defected=Coalesce(Sum("qty_defected"), 0),
        checks=Count("id"),
        occurrences=Coalesce(Sum("defect_count"), 0),
    )
    return {
        "checked": agg["checked"],
        "passed": agg["passed"],
        "defected": agg["defected"],
        "checks": agg["checks"],
        "occurrences": agg["occurrences"],
        "defect_rate": _pct(agg["defected"], agg["checked"]),
        "pass_rate": _pct(agg["passed"], agg["checked"]),
    }


def quality_by_product(filters) -> list:
    qs = filters.apply_quality(QualityCheck.objects.all())
    rows = (
        qs.values("product__id", "product__code", "product__name")
        .annotate(
            checked=Coalesce(Sum("qty_checked"), 0),
            defected=Coalesce(Sum("qty_defected"), 0),
            checks=Count("id"),
        )
        .order_by("-defected")
    )
    return [
        {
            "product_id": row["product__id"],
            "code": row["product__code"],
            "product": row["product__name"],
            "checked": row["checked"],
            "defected": row["defected"],
            "checks": row["checks"],
            "defect_rate": _pct(row["defected"], row["checked"]),
        }
        for row in rows
    ]


def quality_by_line(filters) -> list:
    qs = filters.apply_quality(QualityCheck.objects.all())
    rows = (
        qs.values("production_line__id", "production_line__name", "production_line__code")
        .annotate(
            checked=Coalesce(Sum("qty_checked"), 0),
            defected=Coalesce(Sum("qty_defected"), 0),
            checks=Count("id"),
        )
        .order_by("-defected")
    )
    return [
        {
            "line_id": row["production_line__id"],
            "line": row["production_line__name"],
            "code": row["production_line__code"],
            "checked": row["checked"],
            "defected": row["defected"],
            "checks": row["checks"],
            "defect_rate": _pct(row["defected"], row["checked"]),
        }
        for row in rows
    ]


def quality_by_defect_type(filters) -> list:
    qs = filters.apply_quality(QualityCheck.objects.all())
    rows = (
        qs.values("defect_type")
        .annotate(
            checks=Count("id"),
            defected=Coalesce(Sum("qty_defected"), 0),
            occurrences=Coalesce(Sum("defect_count"), 0),
        )
        .order_by("-defected")
    )
    total = sum(row["defected"] for row in rows) or 1
    labels = _choice_labels(DefectType)
    return [
        {
            "defect_type": row["defect_type"],
            "label": labels.get(row["defect_type"], row["defect_type"]),
            "checks": row["checks"],
            "defected": row["defected"],
            "occurrences": row["occurrences"],
            "share": round((row["defected"] / total) * 100, 2),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
def inventory_summary(filters) -> dict:
    items = filters.apply_inventory(InventoryItem.objects.select_related("product"))
    money = DecimalField(max_digits=16, decimal_places=2)
    agg = items.aggregate(
        total=Coalesce(Sum(F("qty_on_hand")), 0, output_field=money),
        value=Coalesce(Sum(F("qty_on_hand") * F("unit_cost")), 0, output_field=money),
        count=Count("id"),
    )
    low_items = [item for item in items if item.is_low]
    movements = filters.apply_movements(
        StockMovement.objects.select_related("inventory_item", "inventory_item__product")
    )
    movement_agg = movements.aggregate(
        in_qty=Coalesce(
            Sum("quantity", filter=models_q("movement_type", ["in", "transfer_in"])),
            0,
            output_field=money,
        ),
        out_qty=Coalesce(
            Sum("quantity", filter=models_q("movement_type", ["out", "transfer_out"])),
            0,
            output_field=money,
        ),
        count=Count("id"),
    )
    return {
        "items": agg["count"],
        "total_qty": agg["total"],
        "total_value": round(float(agg["value"] or 0), 2),
        "low_stock": len(low_items),
        "low_stock_items": low_items[:20],
        "movements": movement_agg["count"],
        "qty_in": movement_agg["in_qty"],
        "qty_out": movement_agg["out_qty"],
    }


def models_q(field, values):
    """Small helper so we do not import ``Q`` in three places."""
    from django.db.models import Q

    return Q(**{f"{field}__in": values})


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------
def hourly_trend(filters) -> list:
    qs = filters.apply_production(ProductionLog.objects.all())
    rows = (
        qs.values("hour")
        .annotate(
            produced=Coalesce(Sum("qty_produced"), 0),
            defect=Coalesce(Sum("qty_defect"), 0),
            target=Coalesce(Sum("target_qty"), 0),
        )
        .order_by("hour")
    )
    data = {row["hour"]: row for row in rows}
    return [
        {
            "hour": hour,
            "produced": data.get(hour, {}).get("produced", 0),
            "target": data.get(hour, {}).get("target", 0),
            "defect": data.get(hour, {}).get("defect", 0),
        }
        for hour in range(24)
    ]


def daily_trend(filters) -> list:
    qs = filters.apply_production(ProductionLog.objects.all())
    rows = (
        qs.values("date")
        .annotate(
            produced=Coalesce(Sum("qty_produced"), 0),
            defect=Coalesce(Sum("qty_defect"), 0),
            target=Coalesce(Sum("target_qty"), 0),
        )
        .order_by("date")
    )
    return [
        {
            "date": row["date"].isoformat(),
            "produced": row["produced"],
            "target": row["target"],
            "defect": row["defect"],
            "defect_rate": _pct(row["defect"], row["produced"]),
        }
        for row in rows
    ]


def weekly_trend(filters) -> list:
    qs = filters.apply_production(ProductionLog.objects.all())
    rows = (
        qs.annotate(week=TruncWeek("date"))
        .values("week")
        .annotate(
            produced=Coalesce(Sum("qty_produced"), 0),
            defect=Coalesce(Sum("qty_defect"), 0),
            target=Coalesce(Sum("target_qty"), 0),
        )
        .order_by("week")
    )
    return [
        {
            "week": row["week"].isoformat(),
            "produced": row["produced"],
            "target": row["target"],
            "defect": row["defect"],
        }
        for row in rows
    ]


def comparison_by_line(filters) -> list:
    qs = filters.apply_production(ProductionLog.objects.all())
    rows = (
        qs.values("production_line__id", "production_line__name", "production_line__code")
        .annotate(
            produced=Coalesce(Sum("qty_produced"), 0),
            defect=Coalesce(Sum("qty_defect"), 0),
            target=Coalesce(Sum("target_qty"), 0),
        )
        .order_by("-produced")
    )
    return [
        {
            "line_id": row["production_line__id"],
            "line": row["production_line__name"],
            "code": row["production_line__code"],
            "produced": row["produced"],
            "target": row["target"],
            "defect": row["defect"],
            "attainment": _pct(row["produced"], row["target"]),
            "defect_rate": _pct(row["defect"], row["produced"]),
        }
        for row in rows
    ]


def comparison_by_shift(filters) -> list:
    qs = filters.apply_production(ProductionLog.objects.all())
    rows = (
        qs.values("shift__id", "shift__name", "shift__code")
        .annotate(
            produced=Coalesce(Sum("qty_produced"), 0),
            defect=Coalesce(Sum("qty_defect"), 0),
            target=Coalesce(Sum("target_qty"), 0),
        )
        .order_by("shift__start_time")
    )
    return [
        {
            "shift_id": row["shift__id"],
            "shift": row["shift__name"],
            "code": row["shift__code"],
            "produced": row["produced"],
            "target": row["target"],
            "defect": row["defect"],
            "attainment": _pct(row["produced"], row["target"]),
            "defect_rate": _pct(row["defect"], row["produced"]),
        }
        for row in rows
    ]


def comparison_by_product(filters) -> list:
    qs = filters.apply_production(ProductionLog.objects.all())
    rows = (
        qs.values("product__id", "product__code", "product__name")
        .annotate(
            produced=Coalesce(Sum("qty_produced"), 0),
            defect=Coalesce(Sum("qty_defect"), 0),
            target=Coalesce(Sum("target_qty"), 0),
        )
        .order_by("-produced")
    )
    return [
        {
            "product_id": row["product__id"],
            "code": row["product__code"],
            "product": row["product__name"],
            "produced": row["produced"],
            "target": row["target"],
            "defect": row["defect"],
            "attainment": _pct(row["produced"], row["target"]),
            "defect_rate": _pct(row["defect"], row["produced"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def active_alert_count(filters=None) -> int:
    qs = Alert.objects.filter(status=AlertStatus.OPEN)
    return qs.count()


def kpi_cards(filters) -> list:
    """The five KPI cards of the Overview page."""
    today = output_today(filters)
    oee = oee_summary(filters)
    downtime = downtime_summary(filters)
    quality = quality_summary(filters)
    alerts = active_alert_count(filters)
    return [
        {
            "key": "output",
            "label": _("Today output"),
            "value": today["produced"],
            "unit": _("pcs"),
            "sub": _("Target %(target)s pcs") % {"target": today["target"]},
            "trend": today["attainment"],
            "tone": "primary",
        },
        {
            "key": "oee",
            "label": _("OEE"),
            "value": oee["oee"],
            "unit": "%",
            "sub": _("A %(a)s%% / P %(p)s%% / Q %(q)s%%")
            % {"a": oee["availability"], "p": oee["performance"], "q": oee["quality"]},
            "trend": oee["oee"],
            "tone": "success",
        },
        {
            "key": "downtime",
            "label": _("Downtime"),
            "value": downtime["hours"],
            "unit": _("h"),
            "sub": _("%(events)s events - %(ongoing)s ongoing")
            % {"events": downtime["events"], "ongoing": downtime["ongoing"]},
            "trend": -downtime["hours"],
            "tone": "warning",
        },
        {
            "key": "defect",
            "label": _("Defect rate"),
            "value": quality["defect_rate"],
            "unit": "%",
            "sub": _("%(defected)s defective of %(checked)s checked")
            % {"defected": quality["defected"], "checked": quality["checked"]},
            "trend": -quality["defect_rate"],
            "tone": "danger",
        },
        {
            "key": "alerts",
            "label": _("Active alerts"),
            "value": alerts,
            "unit": "",
            "sub": _("Needs attention"),
            "trend": -alerts,
            "tone": "info",
        },
    ]
