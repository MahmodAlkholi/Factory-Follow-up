"""URL map of the REST API."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "api"

router = DefaultRouter()
router.register("factories", views.FactoryViewSet, basename="factory")
router.register("lines", views.ProductionLineViewSet, basename="line")
router.register("machines", views.MachineViewSet, basename="machine")
router.register("shifts", views.ShiftViewSet, basename="shift")
router.register("products", views.ProductViewSet, basename="product")
router.register("production-logs", views.ProductionLogViewSet, basename="productionlog")
router.register("downtime-events", views.DowntimeEventViewSet, basename="downtimeevent")
router.register("quality-checks", views.QualityCheckViewSet, basename="qualitycheck")
router.register("inventory", views.InventoryItemViewSet, basename="inventoryitem")
router.register("stock-movements", views.StockMovementViewSet, basename="stockmovement")
router.register("thresholds", views.ThresholdViewSet, basename="threshold")
router.register("alerts", views.AlertViewSet, basename="alert")

urlpatterns = [
    # The explicit paths come first: the router would otherwise read
    # "thresholds/evaluate/" as a detail route with the pk "evaluate".
    path(
        "v1/thresholds/evaluate/",
        views.evaluate_thresholds,
        name="thresholds-evaluate",
    ),
    path("v1/", include(router.urls)),
    path("v1/health/", views.health, name="health"),
    path("v1/me/", views.current_user, name="current-user"),
    path("v1/dashboard/summary/", views.DashboardSummaryView.as_view(), name="dashboard-summary"),
    # ---- Machine / PLC ingestion (token authenticated) ----
    path(
        "v1/ingest/production/",
        views.ProductionIngestViewSet.as_view({"post": "post"}),
        name="ingest-production",
    ),
    path(
        "v1/ingest/downtime/",
        views.DowntimeIngestViewSet.as_view({"post": "post"}),
        name="ingest-downtime",
    ),
    path(
        "v1/ingest/quality/",
        views.QualityIngestViewSet.as_view({"post": "post"}),
        name="ingest-quality",
    ),
    path(
        "v1/ingest/stock/",
        views.StockMovementIngestViewSet.as_view({"post": "post"}),
        name="ingest-stock",
    ),
]
