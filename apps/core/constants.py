"""
Enumerations shared by models, serializers, forms and the seed command.

Keeping them in one module means the API, the UI and the alert engine can
never disagree about what "mechanical downtime" or "critical severity" means.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class MachineStatus(models.TextChoices):
    IDLE = "idle", _("Idle")
    RUNNING = "running", _("Running")
    STOPPED = "stopped", _("Stopped")
    MAINTENANCE = "maintenance", _("Maintenance")
    FAULT = "fault", _("Fault")


class DowntimeReason(models.TextChoices):
    MECHANICAL = "mechanical", _("Mechanical")
    ELECTRICAL = "electrical", _("Electrical")
    MATERIAL = "material", _("Material / feeding")
    MANPOWER = "manpower", _("Manpower")
    PROCESS = "process", _("Process / changeover")
    PLANNED = "planned_maintenance", _("Planned maintenance")
    QUALITY = "quality_hold", _("Quality hold")
    OTHER = "other", _("Other")


class DefectType(models.TextChoices):
    DIMENSIONAL = "dimensional", _("Dimensional")
    SURFACE = "surface", _("Surface")
    FUNCTIONAL = "functional", _("Functional")
    ASSEMBLY = "assembly", _("Assembly")
    MATERIAL = "material", _("Material flaw")
    CONTAMINATION = "contamination", _("Contamination")
    COLOR = "color", _("Colour")
    OTHER = "other", _("Other")


class DataSource(models.TextChoices):
    MANUAL = "manual", _("Manual entry")
    IMPORT = "import", _("CSV / Excel import")
    API = "api", _("API / IoT")
    SYSTEM = "system", _("System")


class MovementType(models.TextChoices):
    IN = "in", _("Stock in")
    OUT = "out", _("Stock out")
    ADJUST = "adjust", _("Adjustment")
    TRANSFER_IN = "transfer_in", _("Transfer in")
    TRANSFER_OUT = "transfer_out", _("Transfer out")


class StockStatus(models.TextChoices):
    OK = "ok", _("In stock")
    LOW = "low", _("Low stock")
    OUT = "out", _("Out of stock")
    OVER = "over", _("Over stocked")


class Metric(models.TextChoices):
    OEE = "oee", _("OEE (%)")
    AVAILABILITY = "availability", _("Availability (%)")
    PERFORMANCE = "performance", _("Performance (%)")
    QUALITY = "quality", _("Quality rate (%)")
    DEFECT_RATE = "defect_rate", _("Defect rate (%)")
    DOWNTIME_MINUTES = "downtime_minutes", _("Downtime (minutes)")
    LINE_STOPPED_MINUTES = "line_stopped_minutes", _("Line stopped (minutes)")
    OUTPUT_ATTACHMENT = "output_attachment", _("Output vs target (%)")
    LOW_STOCK = "low_stock", _("Low stock items")


class ThresholdScope(models.TextChoices):
    GLOBAL = "global", _("Global")
    FACTORY = "factory", _("Factory")
    LINE = "line", _("Production line")
    MACHINE = "machine", _("Machine")
    PRODUCT = "product", _("Product")


class ComparisonOperator(models.TextChoices):
    GT = "gt", _("Greater than")
    GTE = "gte", _("Greater or equal")
    LT = "lt", _("Less than")
    LTE = "lte", _("Less or equal")


class Severity(models.TextChoices):
    INFO = "info", _("Info")
    WARNING = "warning", _("Warning")
    CRITICAL = "critical", _("Critical")


class AlertStatus(models.TextChoices):
    OPEN = "open", _("Open")
    ACKNOWLEDGED = "acknowledged", _("Acknowledged")
    RESOLVED = "resolved", _("Resolved")
