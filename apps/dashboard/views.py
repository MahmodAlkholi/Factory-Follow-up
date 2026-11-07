"""Dashboard pages."""

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.constants import AlertStatus
from apps.core.models import (
    Alert,
    DowntimeEvent,
    Factory,
    InventoryItem,
    Machine,
    Product,
    ProductionLine,
    ProductionLog,
    QualityCheck,
    Shift,
    StockMovement,
    Threshold,
)
from apps.core.permissions import (
    can_enter_data,
    can_export,
    can_manage_structure,
    is_admin,
    scope_for_user,
)
from apps.core.services import kpi
from apps.core.services.alerts import (
    acknowledge_alert,
    evaluate_thresholds,
    resolve_alert,
)
from apps.core.services.filters import FilterParams

from . import exports, importer
from .forms import (
    DowntimeEventForm,
    FilterForm,
    ImportForm,
    ProductionLogForm,
    QualityCheckForm,
    StockMovementForm,
    ThresholdForm,
)


class FilterMixin:
    """Turns the query string into a :class:`FilterParams` object."""

    default_days = 7

    def get_filters(self):
        filters = FilterParams.from_request(self.request, default_days=self.default_days)
        filters.restricted_for(self.request.user)
        return filters


def filter_context(request, filters):
    """Shared context for every page that shows the filter bar."""
    query = filters.as_query_dict()
    flat = "&".join(f"{key}={value}" for key, value in query.items())
    return {
        "filters": filters,
        "filter_form": FilterForm(user=request.user, initial=query),
        "filter_query": flat,
        "filter_params": query,
        "factories": Factory.objects.filter(is_active=True),
        "lines": ProductionLine.objects.filter(is_active=True).select_related("factory"),
        "shifts": Shift.objects.filter(is_active=True),
        "products": Product.objects.filter(is_active=True),
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class DashboardLoginView(LoginView):
    template_name = "dashboard/login.html"
    redirect_authenticated_user = True


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, _("You have been signed out."))
    return redirect("dashboard:login")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@login_required
def overview(request):
    filters = FilterParams.from_request(request).restricted_for(request.user)
    context = filter_context(request, filters)
    context.update(
        {
            "kpi_cards": kpi.kpi_cards(filters),
            "oee": kpi.oee_summary(filters),
            "production": kpi.production_summary(filters),
            "downtime": kpi.downtime_summary(filters),
            "quality": kpi.quality_summary(filters),
            "inventory": {
                key: value
                for key, value in kpi.inventory_summary(filters).items()
                if key != "low_stock_items"
            },
            "hourly": kpi.hourly_trend(filters),
            "daily": kpi.daily_trend(filters),
            "by_line": kpi.comparison_by_line(filters),
            "by_shift": kpi.comparison_by_shift(filters),
            "pareto": kpi.downtime_pareto(filters)[:6],
            "alerts": Alert.objects.filter(status=AlertStatus.OPEN)
            .select_related("factory", "production_line")
            .order_by("-created_at")[:8],
            "alert_count": Alert.objects.filter(status=AlertStatus.OPEN).count(),
        }
    )
    return render(request, "dashboard/overview.html", context)


@login_required
def overview_kpis(request):
    """HTMX partial with the KPI cards - polled every N seconds."""
    filters = FilterParams.from_request(request).restricted_for(request.user)
    return render(
        request,
        "dashboard/partials/_kpi_cards.html",
        {"kpi_cards": kpi.kpi_cards(filters), "filters": filters},
    )


@login_required
def production(request):
    filters = FilterParams.from_request(request).restricted_for(request.user)
    context = filter_context(request, filters)
    trend = request.GET.get("trend", "daily")
    context.update(
        {
            "trend": trend,
            "trend_options": [
                ("hourly", _("Hourly")),
                ("daily", _("Daily")),
                ("weekly", _("Weekly")),
            ],
            "hourly": kpi.hourly_trend(filters),
            "daily": kpi.daily_trend(filters),
            "weekly": kpi.weekly_trend(filters),
            "by_line": kpi.comparison_by_line(filters),
            "by_shift": kpi.comparison_by_shift(filters),
            "by_product": kpi.comparison_by_product(filters),
            "summary": kpi.production_summary(filters),
            "records": filters.apply_production(
                ProductionLog.objects.select_related(
                    "production_line", "production_line__factory", "shift", "product", "machine"
                )
            ).order_by("-date", "-hour")[:100],
        }
    )
    return render(request, "dashboard/production.html", context)


@login_required
def downtime(request):
    filters = FilterParams.from_request(request).restricted_for(request.user)
    context = filter_context(request, filters)
    context.update(
        {
            "summary": kpi.downtime_summary(filters),
            "pareto": kpi.downtime_pareto(filters),
            "by_machine": kpi.downtime_by_machine(filters),
            "timeline": kpi.downtime_timeline(filters),
            "timeline_total": max(kpi.window_days(filters) * 24 * 60, 1),
            "events": filters.apply_downtime(
                DowntimeEvent.objects.select_related(
                    "machine", "production_line", "production_line__factory", "shift"
                )
            ).order_by("-started_at")[:100],
        }
    )
    return render(request, "dashboard/downtime.html", context)


@login_required
def quality(request):
    filters = FilterParams.from_request(request).restricted_for(request.user)
    context = filter_context(request, filters)
    context.update(
        {
            "summary": kpi.quality_summary(filters),
            "by_product": kpi.quality_by_product(filters),
            "by_line": kpi.quality_by_line(filters),
            "by_defect_type": kpi.quality_by_defect_type(filters),
            "checks": filters.apply_quality(
                QualityCheck.objects.select_related(
                    "production_line", "production_line__factory", "product", "shift"
                )
            ).order_by("-checked_at")[:100],
        }
    )
    return render(request, "dashboard/quality.html", context)


@login_required
def inventory(request):
    filters = FilterParams.from_request(request).restricted_for(request.user)
    context = filter_context(request, filters)
    summary = kpi.inventory_summary(filters)
    context.update(
        {
            "summary": summary,
            "items": filters.apply_inventory(
                InventoryItem.objects.select_related("product")
            ),
            "movements": filters.apply_movements(
                StockMovement.objects.select_related("inventory_item", "inventory_item__product")
            ).order_by("-moved_at")[:100],
        }
    )
    return render(request, "dashboard/inventory.html", context)


@login_required
def reports(request):
    if not can_export(request.user):
        raise PermissionDenied
    filters = FilterParams.from_request(request).restricted_for(request.user)
    context = filter_context(request, filters)
    summary = kpi.production_summary(filters)
    context.update(
        {
            "summary": summary,
            "oee": kpi.oee_summary(filters),
            "downtime": kpi.downtime_summary(filters),
            "quality": kpi.quality_summary(filters),
            "inventory_summary": {
                key: value
                for key, value in kpi.inventory_summary(filters).items()
                if key != "low_stock_items"
            },
            "by_line": kpi.comparison_by_line(filters),
            "pareto": kpi.downtime_pareto(filters),
            "records": filters.apply_production(
                ProductionLog.objects.select_related(
                    "production_line", "production_line__factory", "shift", "product"
                )
            ).order_by("-date", "-hour")[:50],
            "can_export": True,
        }
    )
    return render(request, "dashboard/reports.html", context)


@login_required
def report_export(request, fmt: str):
    """Export the current filter selection as Excel or PDF."""
    if not can_export(request.user):
        raise PermissionDenied
    if fmt not in {"xlsx", "pdf"}:
        raise Http404()
    filters = FilterParams.from_request(request).restricted_for(request.user)
    stamp = timezone_stamp()
    if fmt == "xlsx":
        buffer = exports.export_excel(filters)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="factory-report-{stamp}.xlsx"'
    else:
        buffer = exports.export_pdf(filters)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="factory-report-{stamp}.pdf"'
    return response


def timezone_stamp():
    from django.utils import timezone

    return timezone.localtime().strftime("%Y%m%d-%H%M")


@login_required
def import_template(request, data_type: str):
    """Download a ready-to-fill CSV template."""
    if data_type not in importer.TEMPLATE_HEADERS:
        raise Http404()
    response = HttpResponse(importer.template_csv(data_type), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{data_type}-template.csv"'
    return response


# ---------------------------------------------------------------------------
# Data entry
# ---------------------------------------------------------------------------
@login_required
def data_entry(request):
    if not can_enter_data(request.user):
        raise PermissionDenied
    context = {
        "production_form": ProductionLogForm(user=request.user),
        "downtime_form": DowntimeEventForm(user=request.user),
        "quality_form": QualityCheckForm(user=request.user),
        "stock_form": StockMovementForm(user=request.user),
        "import_form": ImportForm(),
        "machines": Machine.objects.select_related("production_line").filter(is_active=True),
        "lines_json": [
            {
                "id": line.id,
                "name": line.name,
                "machines": [
                    {"id": machine.id, "name": machine.name}
                    for machine in line.machines.filter(is_active=True)
                ],
            }
            for line in ProductionLine.objects.filter(is_active=True).select_related("factory")
        ],
    }
    return render(request, "dashboard/data_entry.html", context)


def _entry_response(request, template, context, success_message):
    if request.headers.get("HX-Request"):
        context = dict(context, message=success_message)
        return render(request, template, context)
    messages.success(request, success_message)
    return redirect("dashboard:data-entry")


@login_required
@require_POST
def entry_production(request):
    if not can_enter_data(request.user):
        raise PermissionDenied
    form = ProductionLogForm(request.POST, user=request.user)
    if form.is_valid():
        instance = form.save(user=request.user)
        return _entry_response(
            request,
            "dashboard/partials/_entry_production.html",
            {"form": ProductionLogForm(user=request.user), "record": instance},
            _("Production record saved (%(qty)s pcs).") % {"qty": instance.qty_produced},
        )
    return _entry_response(
        request,
        "dashboard/partials/_entry_production.html",
        {"form": form},
        "",
    )


@login_required
@require_POST
def entry_downtime(request):
    if not can_enter_data(request.user):
        raise PermissionDenied
    form = DowntimeEventForm(request.POST, user=request.user)
    if form.is_valid():
        instance = form.save(user=request.user)
        return _entry_response(
            request,
            "dashboard/partials/_entry_downtime.html",
            {"form": DowntimeEventForm(user=request.user), "record": instance},
            _("Downtime event saved (%(minutes)s min).") % {"minutes": instance.duration_minutes},
        )
    return _entry_response(
        request,
        "dashboard/partials/_entry_downtime.html",
        {"form": form},
        "",
    )


@login_required
@require_POST
def entry_quality(request):
    if not can_enter_data(request.user):
        raise PermissionDenied
    form = QualityCheckForm(request.POST, user=request.user)
    if form.is_valid():
        instance = form.save(user=request.user)
        return _entry_response(
            request,
            "dashboard/partials/_entry_quality.html",
            {"form": QualityCheckForm(user=request.user), "record": instance},
            _("Quality check saved (%(rate)s%% defect rate).") % {"rate": instance.defect_rate},
        )
    return _entry_response(
        request,
        "dashboard/partials/_entry_quality.html",
        {"form": form},
        "",
    )


@login_required
@require_POST
def entry_stock(request):
    if not can_enter_data(request.user):
        raise PermissionDenied
    form = StockMovementForm(request.POST, user=request.user)
    if form.is_valid():
        instance = form.save(user=request.user)
        return _entry_response(
            request,
            "dashboard/partials/_entry_stock.html",
            {"form": StockMovementForm(user=request.user), "record": instance},
            _("Stock movement saved."),
        )
    return _entry_response(
        request,
        "dashboard/partials/_entry_stock.html",
        {"form": form},
        "",
    )


@login_required
def import_data(request):
    if not can_enter_data(request.user):
        raise PermissionDenied
    result = None
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data_type = form.cleaned_data["data_type"]
        rows = importer.read_rows(request.FILES["file"])
        normalised = importer.normalise_rows(data_type, rows)
        missing = [
            field
            for field in importer.REQUIRED_FIELDS[data_type]
            if normalised and all(not row.get(field) for row in normalised)
        ]
        if missing:
            result = {
                "ok": False,
                "message": _("Missing required column(s): %(cols)s")
                % {"cols": ", ".join(missing)},
                "created": 0,
                "updated": 0,
                "errors": [],
            }
        else:
            created, updated, errors = importer.import_records(
                data_type,
                normalised,
                user=request.user,
                update_existing=form.cleaned_data["update_existing"],
            )
            result = {
                "ok": True,
                "created": created,
                "updated": updated,
                "errors": errors,
                "message": _("Import finished."),
            }
    return render(
        request,
        "dashboard/import.html",
        {"form": form, "result": result, "templates": importer.TEMPLATE_HEADERS.keys()},
    )


# ---------------------------------------------------------------------------
# Alerts & thresholds
# ---------------------------------------------------------------------------
@login_required
def alerts(request):
    scope = None
    queryset = Alert.objects.select_related(
        "factory", "production_line", "machine", "product", "threshold", "acknowledged_by"
    ).order_by("-created_at")
    scope = scope_for_user(request.user)
    if scope.get("factory"):
        queryset = queryset.filter(factory_id=scope["factory"])
    if scope.get("line"):
        queryset = queryset.filter(production_line_id=scope["line"])

    status_filter = request.GET.get("status", "open")
    if status_filter == "open":
        queryset = queryset.filter(status=AlertStatus.OPEN)
    elif status_filter in {s.value for s in AlertStatus}:
        queryset = queryset.filter(status=status_filter)

    return render(
        request,
        "dashboard/alerts.html",
        {
            "alerts": queryset[:200],
            "status_filter": status_filter,
            "open_count": Alert.objects.filter(status=AlertStatus.OPEN).count(),
            "can_manage": can_manage_structure(request.user),
        },
    )


@login_required
@require_POST
def alert_action(request, pk: int):
    alert = get_object_or_404(Alert, pk=pk)
    # A supervisor may only touch the alerts of his own scope.
    scope = scope_for_user(request.user)
    if scope.get("factory") and alert.factory_id and alert.factory_id != scope["factory"]:
        raise PermissionDenied
    if scope.get("line") and alert.production_line_id and alert.production_line_id != scope["line"]:
        raise PermissionDenied
    if scope.get("factory") and not alert.factory_id:
        raise PermissionDenied
    action = request.POST.get("action")
    if action == "ack":
        acknowledge_alert(alert, request.user)
        messages.success(request, _("Alert acknowledged."))
    elif action == "resolve":
        resolve_alert(alert)
        messages.success(request, _("Alert resolved."))
    return redirect(request.POST.get("next") or "dashboard:alerts")


@login_required
def thresholds(request):
    if not can_manage_structure(request.user):
        raise PermissionDenied
    form = ThresholdForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        threshold = form.save(commit=False)
        threshold.save()
        messages.success(request, _("Threshold created."))
        return redirect("dashboard:thresholds")
    return render(
        request,
        "dashboard/thresholds.html",
        {
            "form": form,
            "thresholds": Threshold.objects.select_related(
                "factory", "production_line", "machine", "product"
            ).order_by("severity", "name"),
        },
    )


@login_required
@require_POST
def threshold_delete(request, pk: int):
    if not can_manage_structure(request.user):
        raise PermissionDenied
    threshold = get_object_or_404(Threshold, pk=pk)
    threshold.delete()
    messages.success(request, _("Threshold deleted."))
    return redirect("dashboard:thresholds")


@login_required
@require_POST
def run_threshold_check(request):
    """Manual trigger of the alert engine (Admin / Manager only)."""
    if not is_admin(request.user) and not can_export(request.user):
        raise PermissionDenied
    created = evaluate_thresholds()
    messages.success(
        request,
        _("%(count)s alert(s) raised.") % {"count": len(created)},
    )
    return redirect(request.POST.get("next") or "dashboard:alerts")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
@login_required
def chart_data(request, dataset: str):
    """JSON endpoint used by the charts (also handy for a separate frontend)."""
    filters = FilterParams.from_request(request).restricted_for(request.user)
    mapping = {
        "hourly": kpi.hourly_trend,
        "daily": kpi.daily_trend,
        "weekly": kpi.weekly_trend,
        "line": kpi.comparison_by_line,
        "shift": kpi.comparison_by_shift,
        "product": kpi.comparison_by_product,
        "pareto": kpi.downtime_pareto,
        "defect_type": kpi.quality_by_defect_type,
        "quality_product": kpi.quality_by_product,
        "quality_line": kpi.quality_by_line,
        "machine_downtime": kpi.downtime_by_machine,
    }
    handler = mapping.get(dataset)
    if handler is None:
        return JsonResponse({"error": "unknown dataset"}, status=404)
    return JsonResponse({"dataset": dataset, "data": handler(filters)})
