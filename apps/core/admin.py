from django.contrib import admin

from .models import (
    Alert,
    ApiToken,
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
    UserProfile,
)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created")
    search_fields = ("name", "user__username")
    readonly_fields = ("key",)


@admin.register(Factory)
class FactoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("name", "code", "location")


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "factory", "target_daily_qty", "is_active")
    list_filter = ("factory", "is_active")
    search_fields = ("name", "code")


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "production_line", "status", "is_active")
    list_filter = ("status", "is_active", "production_line__factory")
    search_fields = ("name", "code")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "start_time", "end_time", "is_active")
    list_filter = ("is_active",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "unit", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")


@admin.register(ProductionLog)
class ProductionLogAdmin(admin.ModelAdmin):
    list_display = ("date", "hour", "production_line", "product", "qty_produced", "qty_defect", "source")
    list_filter = ("date", "production_line__factory", "shift", "source")
    date_hierarchy = "date"
    search_fields = ("production_line__code", "product__code")


@admin.register(DowntimeEvent)
class DowntimeEventAdmin(admin.ModelAdmin):
    list_display = ("started_at", "machine", "production_line", "reason_category", "duration_minutes", "is_ongoing")
    list_filter = ("reason_category", "production_line__factory", "source")
    date_hierarchy = "started_at"


@admin.register(QualityCheck)
class QualityCheckAdmin(admin.ModelAdmin):
    list_display = ("checked_at", "production_line", "product", "defect_type", "qty_checked", "qty_defected")
    list_filter = ("defect_type", "production_line__factory", "source")
    date_hierarchy = "checked_at"


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("product", "warehouse_code", "qty_on_hand", "reorder_point", "stock_status")
    list_filter = ("warehouse_code", "is_active")
    search_fields = ("product__code", "product__name")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("moved_at", "inventory_item", "movement_type", "quantity", "balance_after")
    list_filter = ("movement_type", "source")
    date_hierarchy = "moved_at"


@admin.register(Threshold)
class ThresholdAdmin(admin.ModelAdmin):
    list_display = ("name", "metric", "operator", "value", "severity", "scope_label", "is_active")
    list_filter = ("metric", "severity", "scope_type", "is_active")
    filter_horizontal = ("recipients",)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "message", "severity", "status", "factory", "production_line")
    list_filter = ("severity", "status", "metric")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "acknowledged_at", "acknowledged_by", "resolved_at", "email_sent_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "factory", "production_line", "shift", "job_title")
    list_filter = ("factory", "shift")
    search_fields = ("user__username", "user__first_name", "user__last_name")


admin.site.site_header = "Factory Follow-up - Administration"
admin.site.site_title = "Factory Follow-up"
admin.site.index_title = "Factory data administration"

admin.site.empty_value_display = "-"
