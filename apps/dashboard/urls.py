"""URL map of the dashboard UI."""

from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("login/", views.DashboardLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    # ---- pages ----
    path("production/", views.production, name="production"),
    path("downtime/", views.downtime, name="downtime"),
    path("quality/", views.quality, name="quality"),
    path("inventory/", views.inventory, name="inventory"),
    path("reports/", views.reports, name="reports"),
    path("data-entry/", views.data_entry, name="data-entry"),
    path("import/", views.import_data, name="import"),
    path("alerts/", views.alerts, name="alerts"),
    path("thresholds/", views.thresholds, name="thresholds"),
    # ---- HTMX partials ----
    path("overview/kpis/", views.overview_kpis, name="overview-kpis"),
    # ---- exports ----
    path("reports/export/<str:fmt>/", views.report_export, name="report-export"),
    path("reports/template/<str:data_type>/", views.import_template, name="import-template"),
    # ---- data entry (POST) ----
    path("data-entry/production/", views.entry_production, name="entry-production"),
    path("data-entry/downtime/", views.entry_downtime, name="entry-downtime"),
    path("data-entry/quality/", views.entry_quality, name="entry-quality"),
    path("data-entry/stock/", views.entry_stock, name="entry-stock"),
    # ---- alerts ----
    path("alerts/<int:pk>/action/", views.alert_action, name="alert-action"),
    path("thresholds/<int:pk>/delete/", views.threshold_delete, name="threshold-delete"),
    path("thresholds/run/", views.run_threshold_check, name="threshold-run"),
    # ---- JSON ----
    path("charts/<str:dataset>/", views.chart_data, name="chart-data"),
]
