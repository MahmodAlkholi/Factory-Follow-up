"""
REST API.

Two families of endpoints:

* **Read / CRUD** for the catalogue and the event streams - the dashboard UI
  uses the HTML views, but an external tool or a future mobile app can use
  these.
* **Ingestion** (``/api/v1/ingest/...``) for machines, PLCs and IoT gateways.
  They are token authenticated, accept a batch of records keyed by *codes*
  and are idempotent (the same record twice updates instead of duplicating).
"""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.constants import DataSource
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
from apps.core.permissions import apply_scope, is_admin, scope_for_user
from apps.core.services import kpi
from apps.core.services.filters import FilterParams

from . import serializers
from .permissions import (
    CanEnterData,
    IsAdminOrReadOnly,
    IsAdminToken,
    IsTokenAuthenticated,
)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
class FactoryViewSet(viewsets.ModelViewSet):
    queryset = Factory.objects.all()
    serializer_class = serializers.FactorySerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["is_active", "code"]
    search_fields = ["name", "code", "city"]
    ordering_fields = ["name", "code"]


class ProductionLineViewSet(viewsets.ModelViewSet):
    queryset = ProductionLine.objects.select_related("factory")
    serializer_class = serializers.ProductionLineSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["factory", "is_active"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "sort_order"]

    def get_queryset(self):
        scope = scope_for_user(self.request.user)
        qs = super().get_queryset()
        if scope.get("factory"):
            qs = qs.filter(factory_id=scope["factory"])
        if scope.get("line"):
            qs = qs.filter(id=scope["line"])
        return qs


class MachineViewSet(viewsets.ModelViewSet):
    queryset = Machine.objects.select_related("production_line", "production_line__factory")
    serializer_class = serializers.MachineSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["production_line", "status", "is_active"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "status"]

    def get_queryset(self):
        scope = scope_for_user(self.request.user)
        qs = super().get_queryset()
        if scope.get("factory"):
            qs = qs.filter(production_line__factory_id=scope["factory"])
        if scope.get("line"):
            qs = qs.filter(production_line_id=scope["line"])
        return qs


class ShiftViewSet(viewsets.ModelViewSet):
    queryset = Shift.objects.all()
    serializer_class = serializers.ShiftSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["is_active"]
    search_fields = ["name", "code"]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = serializers.ProductSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["is_active", "category"]
    search_fields = ["name", "code"]
    ordering_fields = ["code", "name"]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class ScopedEventViewSet(viewsets.ModelViewSet):
    """Common behaviour: users only ever see their own scope."""

    scope_field = "production_line"

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_scope(qs, self.request.user, field=self.scope_field)


class ProductionLogViewSet(ScopedEventViewSet):
    queryset = ProductionLog.objects.select_related(
        "production_line", "production_line__factory", "shift", "product", "machine"
    )
    serializer_class = serializers.ProductionLogSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["production_line", "shift", "product", "machine", "date", "source"]
    search_fields = ["production_line__code", "product__code"]
    ordering_fields = ["date", "hour", "qty_produced"]

    def perform_create(self, serializer):
        serializer.save(
            recorded_by=self.request.user,
            source=serializer.validated_data.get("source") or DataSource.MANUAL,
        )


class DowntimeEventViewSet(ScopedEventViewSet):
    queryset = DowntimeEvent.objects.select_related(
        "machine", "production_line", "production_line__factory", "shift"
    )
    serializer_class = serializers.DowntimeEventSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["machine", "production_line", "shift", "reason_category", "source"]
    ordering_fields = ["started_at", "duration_minutes"]

    def perform_create(self, serializer):
        serializer.save(
            recorded_by=self.request.user,
            source=serializer.validated_data.get("source") or DataSource.MANUAL,
        )


class QualityCheckViewSet(ScopedEventViewSet):
    queryset = QualityCheck.objects.select_related(
        "production_line", "production_line__factory", "product", "shift", "machine"
    )
    serializer_class = serializers.QualityCheckSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["production_line", "product", "shift", "machine", "defect_type", "source"]
    ordering_fields = ["checked_at", "qty_defected"]

    def perform_create(self, serializer):
        serializer.save(
            recorded_by=self.request.user,
            source=serializer.validated_data.get("source") or DataSource.MANUAL,
        )


class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.select_related("product")
    serializer_class = serializers.InventoryItemSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["product", "warehouse_code", "is_active"]
    search_fields = ["product__code", "product__name", "warehouse_code"]

    def get_queryset(self):
        qs = super().get_queryset()
        scope = scope_for_user(self.request.user)
        if scope.get("factory"):
            qs = qs.filter(
                product__production_logs__production_line__factory_id=scope["factory"]
            ).distinct()
        return qs


class StockMovementViewSet(viewsets.ModelViewSet):
    queryset = StockMovement.objects.select_related(
        "inventory_item", "inventory_item__product"
    )
    serializer_class = serializers.StockMovementSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["inventory_item", "movement_type", "source"]
    ordering_fields = ["moved_at"]

    def perform_create(self, serializer):
        serializer.save(
            recorded_by=self.request.user,
            source=serializer.validated_data.get("source") or DataSource.MANUAL,
        )


class ThresholdViewSet(viewsets.ModelViewSet):
    queryset = Threshold.objects.select_related("factory", "production_line", "machine", "product")
    serializer_class = serializers.ThresholdSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["is_active", "metric", "severity", "scope_type"]


class AlertViewSet(viewsets.ModelViewSet):
    queryset = Alert.objects.select_related(
        "factory", "production_line", "machine", "product", "threshold"
    )
    serializer_class = serializers.AlertSerializer
    permission_classes = [IsAdminOrReadOnly]
    http_method_names = ["get", "post", "patch", "head", "options"]
    filterset_fields = ["status", "severity", "metric", "factory", "production_line"]
    ordering_fields = ["created_at", "severity"]

    def get_queryset(self):
        scope = scope_for_user(self.request.user)
        qs = super().get_queryset()
        if scope.get("factory"):
            qs = qs.filter(factory_id=scope["factory"])
        if scope.get("line"):
            qs = qs.filter(production_line_id=scope["line"])
        return qs

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        from apps.core.services.alerts import acknowledge_alert

        alert = acknowledge_alert(self.get_object(), request.user)
        return Response(self.get_serializer(alert).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        from apps.core.services.alerts import resolve_alert

        alert = resolve_alert(self.get_object())
        return Response(self.get_serializer(alert).data)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
class IngestViewSet(viewsets.ViewSet):
    """Base class for the machine-to-server endpoints."""

    authentication_classes = None  # replaced below
    permission_classes = [IsTokenAuthenticated]
    record_serializer = None
    source = DataSource.API

    def get_authenticators(self):
        from .authentication import ApiTokenAuthentication

        return [ApiTokenAuthentication()]

    def get_permissions(self):
        return [IsTokenAuthenticated()]

    def post(self, request, *args, **kwargs):
        payload = request.data
        if isinstance(payload, dict):
            records = payload.get("records", [payload] if "records" not in payload else [])
            if "records" not in payload:
                records = [payload]
        else:
            records = payload
        if not isinstance(records, list):
            records = [records]
        if not records:
            return Response(
                {"error": {"code": 400, "message": _("No records supplied")}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created, updated, errors = 0, 0, []
        for index, raw in enumerate(records):
            serializer = self.record_serializer(data=raw)
            if not serializer.is_valid():
                errors.append({"index": index, "errors": serializer.errors})
                continue
            try:
                with transaction.atomic():
                    action = self._persist(serializer.validated_data)
                if action == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as exc:  # pragma: no cover - defensive
                errors.append({"index": index, "errors": {"detail": str(exc)}})

        payload_out = {"created": created, "updated": updated, "failed": len(errors)}
        if errors:
            payload_out["errors"] = errors
        status_code = status.HTTP_200_OK if not errors else status.HTTP_207_MULTI_STATUS
        return Response(payload_out, status=status_code)

    def _persist(self, data):  # pragma: no cover - implemented by subclasses
        raise NotImplementedError


class ProductionIngestViewSet(IngestViewSet):
    record_serializer = serializers.ProductionIngestSerializer

    def _persist(self, data):
        line = ProductionLine.objects.filter(code=data["line_code"]).first()
        if line is None:
            raise ValueError(_("Unknown line code: %(code)s") % {"code": data["line_code"]})
        shift = Shift.objects.filter(code=data["shift_code"]).first()
        if shift is None:
            raise ValueError(_("Unknown shift code: %(code)s") % {"code": data["shift_code"]})
        product = Product.objects.filter(code=data["product_code"]).first()
        if product is None:
            raise ValueError(
                _("Unknown product code: %(code)s") % {"code": data["product_code"]}
            )
        machine = None
        if data.get("machine_code"):
            machine = Machine.objects.filter(
                code=data["machine_code"], production_line=line
            ).first()
            if machine is None:
                raise ValueError(
                    _("Unknown machine code: %(code)s") % {"code": data["machine_code"]}
                )

        defaults = {
            "qty_produced": data["qty_produced"],
            "qty_good": data.get("qty_good", 0),
            "qty_defect": data.get("qty_defect", 0),
            "target_qty": data.get("target_qty", 0),
            "machine": machine,
            "recorded_at": data.get("recorded_at") or timezone.now(),
            "source": self.source,
            "notes": data.get("notes", ""),
        }
        obj, created = ProductionLog.objects.update_or_create(
            production_line=line,
            shift=shift,
            product=product,
            date=data["date"],
            hour=data["hour"],
            defaults=defaults,
        )
        return "created" if created else "updated"


class DowntimeIngestViewSet(IngestViewSet):
    record_serializer = serializers.DowntimeIngestSerializer

    def _persist(self, data):
        machine = Machine.objects.filter(code=data["machine_code"]).first()
        if machine is None:
            raise ValueError(
                _("Unknown machine code: %(code)s") % {"code": data["machine_code"]}
            )
        started = data["started_at"]
        ended = data.get("ended_at")
        duration = data.get("duration_minutes") or 0
        if ended and not duration:
            duration = int((ended - started).total_seconds() // 60)
        event, created = DowntimeEvent.objects.update_or_create(
            machine=machine,
            started_at=started,
            defaults={
                "ended_at": ended,
                "duration_minutes": duration,
                "reason_category": data.get("reason_category") or "other",
                "reason_code": data.get("reason_code", ""),
                "reason_note": data.get("reason_note", ""),
                "source": self.source,
            },
        )
        return "created" if created else "updated"


class QualityIngestViewSet(IngestViewSet):
    record_serializer = serializers.QualityIngestSerializer

    def _persist(self, data):
        line = ProductionLine.objects.filter(code=data["line_code"]).first()
        if line is None:
            raise ValueError(_("Unknown line code: %(code)s") % {"code": data["line_code"]})
        product = Product.objects.filter(code=data["product_code"]).first()
        if product is None:
            raise ValueError(
                _("Unknown product code: %(code)s") % {"code": data["product_code"]}
            )
        shift = None
        if data.get("shift_code"):
            shift = Shift.objects.filter(code=data["shift_code"]).first()
        machine = None
        if data.get("machine_code"):
            machine = Machine.objects.filter(
                code=data["machine_code"], production_line=line
            ).first()

        check, created = QualityCheck.objects.update_or_create(
            production_line=line,
            product=product,
            checked_at=data["checked_at"],
            defaults={
                "machine": machine,
                "shift": shift,
                "qty_checked": data["qty_checked"],
                "qty_passed": data.get("qty_passed", 0),
                "qty_defected": data.get("qty_defected", 0),
                "defect_type": data.get("defect_type") or "other",
                "defect_count": data.get("defect_count", 0),
                "notes": data.get("notes", ""),
                "source": self.source,
            },
        )
        return "created" if created else "updated"


class StockMovementIngestViewSet(IngestViewSet):
    record_serializer = serializers.StockMovementIngestSerializer

    def _persist(self, data):
        product = Product.objects.filter(code=data["product_code"]).first()
        if product is None:
            raise ValueError(
                _("Unknown product code: %(code)s") % {"code": data["product_code"]}
            )
        item, _ = InventoryItem.objects.get_or_create(
            product=product,
            warehouse_code=data["warehouse_code"],
            defaults={"warehouse_name": data["warehouse_code"]},
        )
        from apps.core.constants import MovementType

        movement_type = data.get("movement_type") or MovementType.IN
        quantity = data["quantity"]
        if movement_type in {MovementType.OUT, MovementType.TRANSFER_OUT}:
            new_qty = item.qty_on_hand - abs(quantity)
        elif movement_type == MovementType.ADJUST:
            new_qty = quantity
        else:
            new_qty = item.qty_on_hand + abs(quantity)
        item.qty_on_hand = new_qty
        item.save(update_fields=["qty_on_hand", "updated_at"])

        movement, created = StockMovement.objects.get_or_create(
            inventory_item=item,
            movement_type=movement_type,
            moved_at=data.get("moved_at") or timezone.now(),
            defaults={
                "quantity": abs(quantity),
                "balance_after": new_qty,
                "reference_no": data.get("reference_no", ""),
                "reason": data.get("reason", ""),
                "source": self.source,
            },
        )
        return "created" if created else "updated"


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Liveness probe used by docker / nginx."""
    return Response({"status": "ok", "time": timezone.now()})


@api_view(["POST"])
@permission_classes([IsAdminToken])
def evaluate_thresholds(request):
    """
    Run the alert engine once.

    This is the endpoint a *scheduled job* calls on a platform that cannot
    keep a Celery beat alive next to the web container (Cloud Run, a cron
    entry, a Windows task).  It needs an API token that belongs to an Admin,
    so give the scheduler its own named token::

        python manage.py create_api_token --username admin --name "scheduler"

    The answer mirrors the management command: the alerts that were raised.
    """
    from apps.core.services.alerts import evaluate_thresholds as run_engine

    created = run_engine(send_email=not request.data.get("no_email", False))
    return Response(
        {
            "raised": len(created),
            "alerts": [
                {
                    "id": alert.pk,
                    "severity": alert.get_severity_display(),
                    "message": alert.message,
                    "metric": alert.metric,
                    "value": alert.value,
                }
                for alert in created
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user(request):
    """Who am I, what can I see? (handy for the frontend)"""
    scope = scope_for_user(request.user)
    return Response(
        {
            "id": request.user.id,
            "username": request.user.username,
            "full_name": request.user.get_full_name(),
            "roles": sorted(
                {g.name for g in request.user.groups.all()}
                | ({"Admin"} if request.user.is_superuser else set())
            ),
            "is_admin": is_admin(request.user),
            "scope": scope,
        }
    )


class DashboardSummaryView(APIView):
    """The five KPI cards as JSON - used by the mobile app / wall display."""

    def get(self, request):
        filters = FilterParams.from_queryset_params(request.query_params)
        filters.restricted_for(request.user)
        return Response(
            {
                "kpis": kpi.kpi_cards(filters),
                "oee": kpi.oee_summary(filters),
                "production": kpi.production_summary(filters),
                "downtime": kpi.downtime_summary(filters),
                "quality": kpi.quality_summary(filters),
                "inventory": {
                    key: value
                    for key, value in kpi.inventory_summary(filters).items()
                    if key != "low_stock_items"
                },
                "filters": filters.as_query_dict(),
            }
        )
