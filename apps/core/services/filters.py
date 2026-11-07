"""
The one place where "which slice of data is on screen" is decided.

Every dashboard page, every chart endpoint and every export builds a
``FilterParams`` object, so a filter can never behave differently on two
pages.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from ..models import (
    DowntimeEvent,
    InventoryItem,
    Machine,
    ProductionLine,
    ProductionLog,
    QualityCheck,
    Shift,
)


def _to_date(value, fallback=None):
    if value in (None, ""):
        return fallback
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return fallback


def _to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class FilterParams:
    """Normalised dashboard filters."""

    date_from: date | None = None
    date_to: date | None = None
    factory: int | None = None
    line: int | None = None
    shift: int | None = None
    product: int | None = None
    machine: int | None = None

    # -- construction ------------------------------------------------------
    @classmethod
    def from_request(cls, request, default_days: int = 7):
        """Parse ``request.GET`` into filters (today .. today-6 by default)."""
        get = request.GET
        today = timezone.localdate()
        default_from = today - timedelta(days=default_days - 1)
        return cls(
            date_from=_to_date(get.get("date_from"), default_from),
            date_to=_to_date(get.get("date_to"), today),
            factory=_to_int(get.get("factory")),
            line=_to_int(get.get("line")),
            shift=_to_int(get.get("shift")),
            product=_to_int(get.get("product")),
            machine=_to_int(get.get("machine")),
        )

    @classmethod
    def from_queryset_params(cls, params, default_days: int = 7):
        """Same as :meth:`from_request` but for DRF ``request.query_params``."""
        today = timezone.localdate()
        default_from = today - timedelta(days=default_days - 1)
        return cls(
            date_from=_to_date(params.get("date_from"), default_from),
            date_to=_to_date(params.get("date_to"), today),
            factory=_to_int(params.get("factory")),
            line=_to_int(params.get("line")),
            shift=_to_int(params.get("shift")),
            product=_to_int(params.get("product")),
            machine=_to_int(params.get("machine")),
        )

    # -- helpers -----------------------------------------------------------
    @property
    def days(self) -> int:
        if not self.date_from or not self.date_to:
            return 1
        return max((self.date_to - self.date_from).days + 1, 1)

    def as_query_dict(self):
        """Rebuild the query string (used to keep HTMX partials in sync)."""
        data = {}
        if self.date_from:
            data["date_from"] = self.date_from.isoformat()
        if self.date_to:
            data["date_to"] = self.date_to.isoformat()
        for name in ("factory", "line", "shift", "product", "machine"):
            value = getattr(self, name)
            if value:
                data[name] = value
        return data

    def replace(self, **kwargs):
        values = {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "factory": self.factory,
            "line": self.line,
            "shift": self.shift,
            "product": self.product,
            "machine": self.machine,
        }
        values.update(kwargs)
        return FilterParams(**values)

    # -- scoping -----------------------------------------------------------
    def scoped_lines(self) -> QuerySet:
        qs = ProductionLine.objects.select_related("factory").filter(is_active=True)
        if self.factory:
            qs = qs.filter(factory_id=self.factory)
        if self.line:
            qs = qs.filter(id=self.line)
        return qs

    def scoped_machines(self) -> QuerySet:
        qs = Machine.objects.select_related("production_line", "production_line__factory")
        line_ids = self.scoped_lines().values_list("id", flat=True)
        return qs.filter(production_line_id__in=list(line_ids))

    def scoped_products(self) -> QuerySet:
        from ..models import Product

        qs = Product.objects.filter(is_active=True)
        if self.product:
            qs = qs.filter(id=self.product)
        return qs

    def scoped_shifts(self) -> QuerySet:
        qs = Shift.objects.filter(is_active=True)
        if self.shift:
            qs = qs.filter(id=self.shift)
        return qs

    # -- queryset helpers --------------------------------------------------
    def apply_production(self, qs: QuerySet) -> QuerySet:
        if self.date_from:
            qs = qs.filter(date__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(date__lte=self.date_to)
        if self.factory:
            qs = qs.filter(production_line__factory_id=self.factory)
        if self.line:
            qs = qs.filter(production_line_id=self.line)
        if self.shift:
            qs = qs.filter(shift_id=self.shift)
        if self.product:
            qs = qs.filter(product_id=self.product)
        if self.machine:
            qs = qs.filter(machine_id=self.machine)
        return qs

    def apply_downtime(self, qs: QuerySet) -> QuerySet:
        if self.date_from:
            qs = qs.filter(started_at__date__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(started_at__date__lte=self.date_to)
        if self.factory:
            qs = qs.filter(production_line__factory_id=self.factory)
        if self.line:
            qs = qs.filter(production_line_id=self.line)
        if self.shift:
            qs = qs.filter(shift_id=self.shift)
        if self.machine:
            qs = qs.filter(machine_id=self.machine)
        return qs

    def apply_quality(self, qs: QuerySet) -> QuerySet:
        if self.date_from:
            qs = qs.filter(checked_at__date__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(checked_at__date__lte=self.date_to)
        if self.factory:
            qs = qs.filter(production_line__factory_id=self.factory)
        if self.line:
            qs = qs.filter(production_line_id=self.line)
        if self.shift:
            qs = qs.filter(shift_id=self.shift)
        if self.product:
            qs = qs.filter(product_id=self.product)
        if self.machine:
            qs = qs.filter(machine_id=self.machine)
        return qs

    def apply_inventory(self, qs: QuerySet) -> QuerySet:
        if self.factory:
            qs = qs.filter(product__production_logs__production_line__factory_id=self.factory)
        if self.product:
            qs = qs.filter(product_id=self.product)
        return qs.distinct()

    def apply_movements(self, qs: QuerySet) -> QuerySet:
        if self.date_from:
            qs = qs.filter(moved_at__date__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(moved_at__date__lte=self.date_to)
        return qs

    # -- user scoping ------------------------------------------------------
    def restricted_for(self, user) -> "FilterParams":
        """Narrow the filters down to what ``user`` is allowed to see."""
        from ..permissions import scope_for_user

        scope = scope_for_user(user)
        if scope.get("factory"):
            self.factory = scope["factory"]
        if scope.get("line"):
            self.line = scope["line"]
        if scope.get("shift"):
            self.shift = scope["shift"]
        return self

    def matches_scope(self, user) -> bool:
        """False when the requested scope is wider than the user's own scope."""
        from ..permissions import scope_for_user

        scope = scope_for_user(user)
        if scope.get("factory") and self.factory and self.factory != scope["factory"]:
            return False
        if scope.get("line") and self.line and self.line != scope["line"]:
            return False
        if scope.get("shift") and self.shift and self.shift != scope["shift"]:
            return False
        return True

    def scope_q(self) -> Q:
        """A reusable Q object matching the scope (for OR-combining)."""
        query = Q()
        if self.factory:
            query &= Q(production_line__factory_id=self.factory)
        if self.line:
            query &= Q(production_line_id=self.line)
        if self.shift:
            query &= Q(shift_id=self.shift)
        return query
