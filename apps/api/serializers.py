"""Serializers for the read/write API and for the IoT ingestion endpoint."""

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

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


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
class FactorySerializer(serializers.ModelSerializer):
    lines_count = serializers.IntegerField(source="lines.count", read_only=True)

    class Meta:
        model = Factory
        fields = [
            "id", "name", "code", "location", "city", "country",
            "timezone", "is_active", "notes", "lines_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class ProductionLineSerializer(serializers.ModelSerializer):
    factory_name = serializers.CharField(source="factory.name", read_only=True)
    machines_count = serializers.IntegerField(source="machines.count", read_only=True)

    class Meta:
        model = ProductionLine
        fields = [
            "id", "factory", "factory_name", "name", "code", "description",
            "target_daily_qty", "is_active", "sort_order", "machines_count",
        ]


class MachineSerializer(serializers.ModelSerializer):
    line_name = serializers.CharField(source="production_line.name", read_only=True)
    factory_name = serializers.CharField(source="production_line.factory.name", read_only=True)

    class Meta:
        model = Machine
        fields = [
            "id", "production_line", "line_name", "factory_name", "name", "code",
            "manufacturer", "model_name", "status", "install_date", "is_active",
        ]


class ShiftSerializer(serializers.ModelSerializer):
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Shift
        fields = [
            "id", "name", "code", "start_time", "end_time",
            "crosses_midnight", "duration_minutes", "is_active",
        ]


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id", "code", "name", "category", "unit",
            "ideal_cycle_time_seconds", "standard_daily_qty", "is_active",
        ]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class ProductionLogSerializer(serializers.ModelSerializer):
    line_code = serializers.CharField(source="production_line.code", read_only=True)
    shift_code = serializers.CharField(source="shift.code", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    machine_code = serializers.CharField(source="machine.code", read_only=True, default=None)
    defect_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = ProductionLog
        fields = [
            "id", "production_line", "line_code", "machine", "machine_code",
            "shift", "shift_code", "product", "product_code", "date", "hour",
            "qty_produced", "qty_good", "qty_defect", "target_qty",
            "defect_rate", "recorded_at", "source", "recorded_by", "notes",
        ]
        read_only_fields = ["id", "defect_rate", "recorded_at"]


class DowntimeEventSerializer(serializers.ModelSerializer):
    machine_code = serializers.CharField(source="machine.code", read_only=True)
    line_code = serializers.CharField(source="production_line.code", read_only=True)
    is_ongoing = serializers.BooleanField(read_only=True)

    class Meta:
        model = DowntimeEvent
        fields = [
            "id", "machine", "machine_code", "production_line", "line_code",
            "shift", "started_at", "ended_at", "duration_minutes",
            "reason_category", "reason_code", "reason_note", "is_ongoing",
            "source", "recorded_by",
        ]
        read_only_fields = ["id", "duration_minutes", "is_ongoing"]


class QualityCheckSerializer(serializers.ModelSerializer):
    line_code = serializers.CharField(source="production_line.code", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    defect_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = QualityCheck
        fields = [
            "id", "production_line", "line_code", "machine", "product",
            "product_code", "shift", "checked_at", "qty_checked", "qty_passed",
            "qty_defected", "defect_type", "defect_count", "defect_rate",
            "inspector", "notes", "source",
        ]
        read_only_fields = ["id", "defect_rate"]


class InventoryItemSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    available_qty = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    stock_status = serializers.CharField(read_only=True)
    stock_value = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = InventoryItem
        fields = [
            "id", "product", "product_code", "product_name", "warehouse_code",
            "warehouse_name", "qty_on_hand", "qty_reserved", "available_qty",
            "reorder_point", "reorder_qty", "unit_cost", "stock_status",
            "stock_value", "is_active",
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="inventory_item.product.code", read_only=True)
    warehouse_code = serializers.CharField(source="inventory_item.warehouse_code", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "inventory_item", "product_code", "warehouse_code",
            "movement_type", "quantity", "balance_after", "reference_no",
            "reason", "moved_at", "recorded_by", "source",
        ]


class ThresholdSerializer(serializers.ModelSerializer):
    scope_label = serializers.CharField(read_only=True)

    class Meta:
        model = Threshold
        fields = [
            "id", "name", "description", "scope_type", "factory",
            "production_line", "machine", "product", "metric", "operator",
            "value", "severity", "cooldown_minutes", "notify_email",
            "recipients", "is_active", "scope_label",
        ]


class AlertSerializer(serializers.ModelSerializer):
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    factory_name = serializers.CharField(source="factory.name", read_only=True, default=None)
    line_name = serializers.CharField(source="production_line.name", read_only=True, default=None)

    class Meta:
        model = Alert
        fields = [
            "id", "threshold", "factory", "factory_name", "production_line",
            "line_name", "machine", "product", "metric", "value",
            "threshold_value", "message", "severity", "severity_display",
            "status", "status_display", "created_at", "acknowledged_at",
            "acknowledged_by", "resolved_at", "email_sent_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Ingestion payloads (PLC / IoT friendly - codes instead of IDs)
# ---------------------------------------------------------------------------
class ProductionIngestSerializer(serializers.Serializer):
    line_code = serializers.CharField(help_text=_("Production line code, e.g. LINE-A"))
    machine_code = serializers.CharField(required=False, allow_blank=True, default="")
    shift_code = serializers.CharField(help_text=_("Shift code, e.g. M"))
    product_code = serializers.CharField(help_text=_("Product code, e.g. PRD-001"))
    date = serializers.DateField()
    hour = serializers.IntegerField(min_value=0, max_value=23)
    qty_produced = serializers.IntegerField(min_value=0)
    qty_good = serializers.IntegerField(min_value=0, required=False, default=0)
    qty_defect = serializers.IntegerField(min_value=0, required=False, default=0)
    target_qty = serializers.IntegerField(min_value=0, required=False, default=0)
    recorded_at = serializers.DateTimeField(required=False, default=timezone.now)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class DowntimeIngestSerializer(serializers.Serializer):
    machine_code = serializers.CharField()
    started_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    duration_minutes = serializers.IntegerField(min_value=0, required=False, default=0)
    reason_category = serializers.CharField(required=False, default="other")
    reason_code = serializers.CharField(required=False, allow_blank=True, default="")
    reason_note = serializers.CharField(required=False, allow_blank=True, default="")
    recorded_at = serializers.DateTimeField(required=False, default=timezone.now)


class QualityIngestSerializer(serializers.Serializer):
    line_code = serializers.CharField()
    product_code = serializers.CharField()
    machine_code = serializers.CharField(required=False, allow_blank=True, default="")
    shift_code = serializers.CharField(required=False, allow_blank=True, default="")
    checked_at = serializers.DateTimeField()
    qty_checked = serializers.IntegerField(min_value=0)
    qty_passed = serializers.IntegerField(min_value=0, required=False, default=0)
    qty_defected = serializers.IntegerField(min_value=0, required=False, default=0)
    defect_type = serializers.CharField(required=False, default="other")
    defect_count = serializers.IntegerField(min_value=0, required=False, default=0)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class StockMovementIngestSerializer(serializers.Serializer):
    product_code = serializers.CharField()
    warehouse_code = serializers.CharField()
    movement_type = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference_no = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    moved_at = serializers.DateTimeField(required=False, default=timezone.now)


class BulkIngestRequestSerializer(serializers.Serializer):
    """
    Wrapper accepted by every ingestion endpoint.

    Either ``{"records": [...]}`` or a bare JSON list ``[...]`` is fine.
    """

    records = serializers.ListField(child=serializers.DictField(), required=False)

    def to_records(self):
        if "records" in self.initial_data:
            return self.initial_data["records"]
        return self.initial_data or []


SOURCE_FOR_INGEST = DataSource.API
