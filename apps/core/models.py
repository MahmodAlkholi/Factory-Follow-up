"""Domain models for the Factory Data Follow-up Dashboard.

The hierarchy is:

    Factory -> ProductionLine -> Machine
    Product / Shift are shared catalogues.
    ProductionLog, DowntimeEvent, QualityCheck are the three "event" streams
    the dashboards aggregate over.
    InventoryItem / StockMovement cover the warehouse side.
    Threshold / Alert implement the monitoring loop.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.authtoken.models import Token

from .constants import (
    AlertStatus,
    ComparisonOperator,
    DataSource,
    DefectType,
    DowntimeReason,
    MachineStatus,
    Metric,
    MovementType,
    Severity,
    StockStatus,
    ThresholdScope,
)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
class Factory(TimeStampedModel):
    name = models.CharField(_("name"), max_length=120)
    code = models.CharField(_("code"), max_length=20, unique=True)
    location = models.CharField(_("location"), max_length=180, blank=True)
    city = models.CharField(_("city"), max_length=80, blank=True)
    country = models.CharField(_("country"), max_length=80, blank=True)
    timezone = models.CharField(
        _("timezone"), max_length=64, default="Africa/Cairo",
        help_text=_("IANA name, e.g. Africa/Cairo"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("factory")
        verbose_name_plural = _("factories")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class ProductionLine(TimeStampedModel):
    factory = models.ForeignKey(
        Factory, on_delete=models.CASCADE, related_name="lines", verbose_name=_("factory")
    )
    name = models.CharField(_("name"), max_length=120)
    code = models.CharField(_("code"), max_length=30)
    description = models.CharField(_("description"), max_length=200, blank=True)
    target_daily_qty = models.PositiveIntegerField(
        _("target daily quantity"), default=0,
        help_text=_("Used as the performance standard when computing OEE"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)

    class Meta:
        verbose_name = _("production line")
        verbose_name_plural = _("production lines")
        ordering = ["factory__name", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["factory", "code"], name="uniq_line_code_per_factory"),
        ]

    def __str__(self):
        return f"{self.name} @ {self.factory.code}"


class Machine(TimeStampedModel):
    production_line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE, related_name="machines", verbose_name=_("line")
    )
    name = models.CharField(_("name"), max_length=120)
    code = models.CharField(_("code"), max_length=30)
    manufacturer = models.CharField(_("manufacturer"), max_length=80, blank=True)
    model_name = models.CharField(_("model"), max_length=80, blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=MachineStatus.choices, default=MachineStatus.IDLE
    )
    install_date = models.DateField(_("install date"), null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("machine")
        verbose_name_plural = _("machines")
        ordering = ["production_line__sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["production_line", "code"], name="uniq_machine_code_per_line"),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def factory(self):
        return self.production_line.factory


class Shift(TimeStampedModel):
    name = models.CharField(_("name"), max_length=80)
    code = models.CharField(_("code"), max_length=20, unique=True)
    start_time = models.TimeField(_("start time"), default=time(8, 0))
    end_time = models.TimeField(_("end time"), default=time(16, 0))
    crosses_midnight = models.BooleanField(_("crosses midnight"), default=False)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("shift")
        verbose_name_plural = _("shifts")
        ordering = ["start_time", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # ``Shift.objects.create(start_time="08:00")`` keeps the *string* on
        # the instance, which would break every calculation that reads
        # ``shift.start_time.hour``. Coerce once, here.
        self.start_time = self._coerce_time(self.start_time)
        self.end_time = self._coerce_time(self.end_time)
        super().save(*args, **kwargs)

    @staticmethod
    def _coerce_time(value):
        if isinstance(value, str):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(value, fmt).time()
                except ValueError:
                    continue
            raise ValueError(f"Not a valid time: {value!r}")
        return value

    @property
    def duration_minutes(self):
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        if end <= start:
            end += 24 * 60
        return end - start

    def window_for(self, day):
        """Return the (start, end) datetimes of this shift on ``day``."""
        start = timezone.make_aware(
            datetime.combine(day, self.start_time), timezone.get_current_timezone()
        )
        end = timezone.make_aware(
            datetime.combine(day, self.end_time), timezone.get_current_timezone()
        )
        if self.end_time <= self.start_time:
            end += timedelta(days=1)
        return start, end

    @classmethod
    def for_datetime(cls, moment):
        """Return the shift covering ``moment`` (or ``None``)."""
        moment = timezone.localtime(moment)
        for shift in cls.objects.filter(is_active=True):
            start, end = shift.window_for(moment.date())
            if start <= moment < end:
                return shift
        return None


class Product(TimeStampedModel):
    code = models.CharField(_("code"), max_length=30, unique=True)
    name = models.CharField(_("name"), max_length=140)
    category = models.CharField(_("category"), max_length=80, blank=True)
    unit = models.CharField(_("unit"), max_length=20, default="pcs")
    ideal_cycle_time_seconds = models.PositiveIntegerField(
        _("ideal cycle time (seconds)"), default=0,
        help_text=_("Standard seconds per one good piece - used for OEE performance"),
    )
    standard_daily_qty = models.PositiveIntegerField(_("standard daily quantity"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("product")
        verbose_name_plural = _("products")
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


# ---------------------------------------------------------------------------
# Event streams
# ---------------------------------------------------------------------------
class ProductionLog(TimeStampedModel):
    """One production record: an hour of output for a line / shift / product."""

    production_line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE, related_name="production_logs", verbose_name=_("line")
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="production_logs", verbose_name=_("machine"),
    )
    shift = models.ForeignKey(
        Shift, on_delete=models.PROTECT, related_name="production_logs", verbose_name=_("shift")
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="production_logs", verbose_name=_("product")
    )
    date = models.DateField(_("date"), db_index=True)
    hour = models.PositiveSmallIntegerField(
        _("hour"), validators=[MinValueValidator(0)],
        help_text=_("Hour of day in the plant timezone (0-23)"),
    )
    qty_produced = models.PositiveIntegerField(_("produced"), default=0)
    qty_good = models.PositiveIntegerField(_("good"), default=0)
    qty_defect = models.PositiveIntegerField(_("defect"), default=0)
    target_qty = models.PositiveIntegerField(_("target"), default=0)
    recorded_at = models.DateTimeField(_("recorded at"), default=timezone.now, db_index=True)
    source = models.CharField(
        _("source"), max_length=20, choices=DataSource.choices, default=DataSource.MANUAL
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="production_logs", verbose_name=_("recorded by"),
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("production log")
        verbose_name_plural = _("production logs")
        ordering = ["-date", "-hour", "production_line__sort_order"]
        indexes = [
            models.Index(fields=["date", "hour"], name="idx_prodlog_date_hour"),
            models.Index(fields=["production_line", "date"], name="idx_prodlog_line_date"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(qty_good__lte=models.F("qty_produced")),
                name="prodlog_good_lte_produced",
            ),
            models.CheckConstraint(
                condition=Q(qty_defect__lte=models.F("qty_produced")),
                name="prodlog_defect_lte_produced",
            ),
        ]

    def __str__(self):
        return f"{self.date} {self.hour:02d}:00 {self.production_line.code} {self.qty_produced}"

    @property
    def defect_rate(self):
        if not self.qty_produced:
            return 0.0
        return round(self.qty_defect * 100 / self.qty_produced, 2)


class DowntimeEvent(TimeStampedModel):
    """A period where a machine (and therefore its line) was not producing."""

    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, related_name="downtime_events", verbose_name=_("machine")
    )
    production_line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE, related_name="downtime_events", verbose_name=_("line")
    )
    shift = models.ForeignKey(
        Shift, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="downtime_events", verbose_name=_("shift"),
    )
    started_at = models.DateTimeField(_("started at"), db_index=True)
    ended_at = models.DateTimeField(_("ended at"), null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(_("duration (minutes)"), default=0)
    reason_category = models.CharField(
        _("reason category"), max_length=30, choices=DowntimeReason.choices,
        default=DowntimeReason.OTHER, db_index=True,
    )
    reason_code = models.CharField(_("reason code"), max_length=60, blank=True)
    reason_note = models.CharField(_("detail"), max_length=250, blank=True)
    source = models.CharField(
        _("source"), max_length=20, choices=DataSource.choices, default=DataSource.MANUAL
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="downtime_events", verbose_name=_("recorded by"),
    )

    class Meta:
        verbose_name = _("downtime event")
        verbose_name_plural = _("downtime events")
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["production_line", "started_at"], name="idx_downtime_line_start"),
            models.Index(fields=["machine", "started_at"], name="idx_downtime_machine_start"),
        ]

    def __str__(self):
        return f"{self.machine.code} {self.get_reason_category_display()} {self.duration_minutes}min"

    def save(self, *args, **kwargs):
        if self.production_line_id is None and self.machine_id:
            self.production_line = self.machine.production_line
        if self.shift_id is None and self.started_at:
            self.shift = Shift.for_datetime(self.started_at)
        self.duration_minutes = self.compute_duration()
        super().save(*args, **kwargs)

    def compute_duration(self):
        if not self.started_at:
            return 0
        end = self.ended_at or timezone.now()
        minutes = int((end - self.started_at).total_seconds() // 60)
        return max(minutes, 0)

    @property
    def is_ongoing(self):
        return self.ended_at is None


class QualityCheck(TimeStampedModel):
    """A quality inspection on a sample taken from a line."""

    production_line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE, related_name="quality_checks", verbose_name=_("line")
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quality_checks", verbose_name=_("machine"),
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="quality_checks", verbose_name=_("product")
    )
    shift = models.ForeignKey(
        Shift, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quality_checks", verbose_name=_("shift"),
    )
    checked_at = models.DateTimeField(_("checked at"), db_index=True)
    qty_checked = models.PositiveIntegerField(_("checked"), default=0)
    qty_passed = models.PositiveIntegerField(_("passed"), default=0)
    qty_defected = models.PositiveIntegerField(_("defected"), default=0)
    defect_type = models.CharField(
        _("defect type"), max_length=30, choices=DefectType.choices,
        default=DefectType.OTHER, db_index=True,
    )
    defect_count = models.PositiveIntegerField(_("defect occurrences"), default=0)
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quality_checks", verbose_name=_("inspector"),
    )
    notes = models.TextField(_("notes"), blank=True)
    source = models.CharField(
        _("source"), max_length=20, choices=DataSource.choices, default=DataSource.MANUAL
    )

    class Meta:
        verbose_name = _("quality check")
        verbose_name_plural = _("quality checks")
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["production_line", "checked_at"], name="idx_qc_line_checked"),
            models.Index(fields=["product", "checked_at"], name="idx_qc_product_checked"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(qty_defected__lte=models.F("qty_checked")), name="qc_defect_lte_checked"
            ),
        ]

    def __str__(self):
        return f"{self.product.code} {self.qty_defected}/{self.qty_checked} {self.get_defect_type_display()}"

    @property
    def defect_rate(self):
        if not self.qty_checked:
            return 0.0
        return round(self.qty_defected * 100 / self.qty_checked, 2)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class InventoryItem(TimeStampedModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="inventory_items", verbose_name=_("product")
    )
    warehouse_code = models.CharField(_("warehouse code"), max_length=30)
    warehouse_name = models.CharField(_("warehouse"), max_length=80, blank=True)
    qty_on_hand = models.DecimalField(_("quantity on hand"), max_digits=14, decimal_places=2, default=0)
    qty_reserved = models.DecimalField(_("quantity reserved"), max_digits=14, decimal_places=2, default=0)
    reorder_point = models.DecimalField(_("reorder point"), max_digits=14, decimal_places=2, default=0)
    reorder_qty = models.DecimalField(_("reorder quantity"), max_digits=14, decimal_places=2, default=0)
    unit_cost = models.DecimalField(_("unit cost"), max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("inventory item")
        verbose_name_plural = _("inventory items")
        ordering = ["product__code", "warehouse_code"]
        verbose_name_plural = verbose_name_plural
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse_code"], name="uniq_inventory_product_warehouse"
            ),
        ]

    def __str__(self):
        return f"{self.product.code} @ {self.warehouse_code} ({self.qty_on_hand})"

    @property
    def available_qty(self):
        return self.qty_on_hand - self.qty_reserved

    @property
    def stock_status(self):
        if self.qty_on_hand <= 0:
            return StockStatus.OUT
        if self.qty_on_hand <= self.reorder_point:
            return StockStatus.LOW
        if self.reorder_qty and self.qty_on_hand >= self.reorder_qty * 2:
            return StockStatus.OVER
        return StockStatus.OK

    @property
    def is_low(self):
        return self.stock_status in {StockStatus.LOW, StockStatus.OUT}

    @property
    def stock_status_display(self):
        """Human readable label of :attr:`stock_status`."""
        return str(StockStatus(self.stock_status).label)

    @property
    def stock_value(self):
        return self.qty_on_hand * self.unit_cost


class StockMovement(TimeStampedModel):
    inventory_item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE, related_name="movements", verbose_name=_("item")
    )
    movement_type = models.CharField(
        _("movement type"), max_length=20, choices=MovementType.choices, default=MovementType.IN
    )
    quantity = models.DecimalField(_("quantity"), max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(
        _("balance after"), max_digits=14, decimal_places=2, default=0,
        help_text=_("Snapshot of the on-hand quantity once this movement was applied"),
    )
    reference_no = models.CharField(_("reference"), max_length=60, blank=True)
    reason = models.CharField(_("reason"), max_length=160, blank=True)
    moved_at = models.DateTimeField(_("moved at"), default=timezone.now, db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_movements", verbose_name=_("recorded by"),
    )
    source = models.CharField(
        _("source"), max_length=20, choices=DataSource.choices, default=DataSource.MANUAL
    )

    class Meta:
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-moved_at"]
        indexes = [
            models.Index(fields=["inventory_item", "moved_at"], name="idx_movement_item_time"),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity} {self.inventory_item.product.code}"

    @property
    def signed_quantity(self):
        if self.movement_type in {MovementType.OUT, MovementType.TRANSFER_OUT}:
            return -abs(self.quantity)
        if self.movement_type == MovementType.ADJUST:
            return self.quantity
        return abs(self.quantity)


# ---------------------------------------------------------------------------
# Users & scoping
# ---------------------------------------------------------------------------
class ApiToken(Token):
    """
    A *named* API token used by machines, PLCs and IoT gateways.

    DRF's own ``Token`` model has no label, and a factory usually runs more
    than one collector - "PLC line A" and "PLC line B" must be revocable
    separately.
    """

    name = models.CharField(_("name"), max_length=80, blank=True, default="ingestion")

    class Meta:
        verbose_name = _("API token")
        verbose_name_plural = _("API tokens")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class UserProfile(models.Model):
    """Extra, role specific scoping for a user.

    A Supervisor (and optionally an Operator) can be pinned to one factory,
    one production line and/or one shift. Every query in the app is filtered
    through this profile so a supervisor physically cannot read another
    line's numbers.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
        verbose_name=_("user"),
    )
    factory = models.ForeignKey(
        Factory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="user_profiles", verbose_name=_("factory"),
    )
    production_line = models.ForeignKey(
        ProductionLine, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="user_profiles", verbose_name=_("line"),
    )
    shift = models.ForeignKey(
        Shift, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="user_profiles", verbose_name=_("shift"),
    )
    job_title = models.CharField(_("job title"), max_length=80, blank=True)
    phone = models.CharField(_("phone"), max_length=30, blank=True)

    class Meta:
        verbose_name = _("user profile")
        verbose_name_plural = _("user profiles")

    def __str__(self):
        return f"Profile of {self.user.username}"


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------
class Threshold(TimeStampedModel):
    """A rule that raises an Alert when a KPI crosses a limit."""

    name = models.CharField(_("name"), max_length=140)
    description = models.CharField(_("description"), max_length=250, blank=True)
    scope_type = models.CharField(
        _("scope"), max_length=20, choices=ThresholdScope.choices, default=ThresholdScope.GLOBAL
    )
    factory = models.ForeignKey(
        Factory, on_delete=models.CASCADE, null=True, blank=True,
        related_name="thresholds", verbose_name=_("factory"),
    )
    production_line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE, null=True, blank=True,
        related_name="thresholds", verbose_name=_("line"),
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, null=True, blank=True,
        related_name="thresholds", verbose_name=_("machine"),
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, null=True, blank=True,
        related_name="thresholds", verbose_name=_("product"),
    )
    metric = models.CharField(_("metric"), max_length=30, choices=Metric.choices)
    operator = models.CharField(
        _("operator"), max_length=5, choices=ComparisonOperator.choices,
        default=ComparisonOperator.GT,
    )
    value = models.DecimalField(_("value"), max_digits=12, decimal_places=2)
    severity = models.CharField(
        _("severity"), max_length=12, choices=Severity.choices, default=Severity.WARNING
    )
    cooldown_minutes = models.PositiveIntegerField(
        _("cooldown (minutes)"), default=30,
        help_text=_("Minimum silence between two alerts raised by this rule"),
    )
    notify_email = models.BooleanField(_("send email"), default=True)
    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="alert_thresholds",
        verbose_name=_("email recipients"),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("threshold")
        verbose_name_plural = _("thresholds")
        ordering = ["severity", "name"]

    def __str__(self):
        return self.name

    def scope_label(self):
        if self.scope_type == ThresholdScope.FACTORY and self.factory_id:
            return str(self.factory)
        if self.scope_type == ThresholdScope.LINE and self.production_line_id:
            return str(self.production_line)
        if self.scope_type == ThresholdScope.MACHINE and self.machine_id:
            return str(self.machine)
        if self.scope_type == ThresholdScope.PRODUCT and self.product_id:
            return str(self.product)
        return _("All")

    def passes(self, measured):
        """True when ``measured`` violates this rule."""
        if measured is None:
            return False
        if self.operator == ComparisonOperator.GT:
            return measured > self.value
        if self.operator == ComparisonOperator.GTE:
            return measured >= self.value
        if self.operator == ComparisonOperator.LT:
            return measured < self.value
        if self.operator == ComparisonOperator.LTE:
            return measured <= self.value
        return False


class Alert(TimeStampedModel):
    """A raised threshold breach."""

    threshold = models.ForeignKey(
        Threshold, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="alerts", verbose_name=_("threshold"),
    )
    factory = models.ForeignKey(
        Factory, on_delete=models.CASCADE, null=True, blank=True,
        related_name="alerts", verbose_name=_("factory"),
    )
    production_line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE, null=True, blank=True,
        related_name="alerts", verbose_name=_("line"),
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, null=True, blank=True,
        related_name="alerts", verbose_name=_("machine"),
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, null=True, blank=True,
        related_name="alerts", verbose_name=_("product"),
    )
    metric = models.CharField(_("metric"), max_length=30, choices=Metric.choices)
    value = models.DecimalField(_("measured value"), max_digits=12, decimal_places=2, null=True, blank=True)
    threshold_value = models.DecimalField(
        _("threshold value"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    message = models.CharField(_("message"), max_length=300)
    severity = models.CharField(
        _("severity"), max_length=12, choices=Severity.choices, default=Severity.WARNING
    )
    status = models.CharField(
        _("status"), max_length=15, choices=AlertStatus.choices, default=AlertStatus.OPEN
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now, db_index=True)
    acknowledged_at = models.DateTimeField(_("acknowledged at"), null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="acknowledged_alerts", verbose_name=_("acknowledged by"),
    )
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)
    email_sent_at = models.DateTimeField(_("email sent at"), null=True, blank=True)

    class Meta:
        verbose_name = _("alert")
        verbose_name_plural = _("alerts")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="idx_alert_status_created"),
        ]

    def __str__(self):
        return self.message

    @property
    def is_open(self):
        return self.status in {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED}
