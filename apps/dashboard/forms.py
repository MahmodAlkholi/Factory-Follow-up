"""Forms for the filter bar, the data entry screens and the bulk import."""

from datetime import date

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.constants import (
    DataSource,
    DefectType,
    DowntimeReason,
    MovementType,
)
from apps.core.models import (
    DowntimeEvent,
    InventoryItem,
    Machine,
    Product,
    ProductionLine,
    ProductionLog,
    QualityCheck,
    Shift,
    StockMovement,
)
from apps.core.permissions import scope_for_user


def _scoped_lines(user):
    qs = ProductionLine.objects.select_related("factory").filter(is_active=True)
    scope = scope_for_user(user)
    if scope.get("factory"):
        qs = qs.filter(factory_id=scope["factory"])
    if scope.get("line"):
        qs = qs.filter(id=scope["line"])
    return qs


def _scoped_machines(user):
    qs = Machine.objects.select_related("production_line").filter(is_active=True)
    scope = scope_for_user(user)
    if scope.get("factory"):
        qs = qs.filter(production_line__factory_id=scope["factory"])
    if scope.get("line"):
        qs = qs.filter(production_line_id=scope["line"])
    return qs


def _scoped_shifts(user):
    qs = Shift.objects.filter(is_active=True)
    scope = scope_for_user(user)
    if scope.get("shift"):
        qs = qs.filter(id=scope["shift"])
    return qs


def bootstrapize(form):
    """
    Give every widget the Bootstrap class it needs.

    Without this the forms render as bare browser inputs, which look broken
    next to the rest of the dashboard and overflow the grid on a tablet.
    """
    for field in form.fields.values():
        widget = field.widget
        css = widget.attrs.get("class", "").strip()
        if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
            widget.attrs["class"] = f"{css} form-check-input".strip()
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs["class"] = f"{css} form-select form-select-sm".strip()
        elif isinstance(widget, (forms.Textarea,)):
            widget.attrs["class"] = f"{css} form-control form-control-sm".strip()
        else:
            widget.attrs["class"] = f"{css} form-control form-control-sm".strip()
    return form


class FilterForm(forms.Form):
    """The filter bar that sits on top of every dashboard page."""

    date_from = forms.DateField(
        required=False,
        label="From",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}),
    )
    date_to = forms.DateField(
        required=False,
        label="To",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}),
    )
    factory = forms.ChoiceField(required=False, label="Factory")
    line = forms.ChoiceField(required=False, label="Line")
    shift = forms.ChoiceField(required=False, label="Shift")
    product = forms.ChoiceField(required=False, label="Product")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        lines = _scoped_lines(user) if user else ProductionLine.objects.all()
        scope = scope_for_user(user) if user else {}

        self.fields["factory"].choices = [("", _("All factories"))] + [
            (str(factory.id), factory.name)
            for factory in sorted(
                {line.factory for line in lines}, key=lambda f: f.name
            )
        ]
        self.fields["line"].choices = [("", _("All lines"))] + [
            (str(line.id), f"{line.factory.code} / {line.name}")
            for line in lines
        ]
        self.fields["shift"].choices = [("", _("All shifts"))] + [
            (str(shift.id), shift.name)
            for shift in (_scoped_shifts(user) if user else Shift.objects.filter(is_active=True))
        ]
        self.fields["product"].choices = [("", _("All products"))] + [
            (str(product.id), f"{product.code} - {product.name}")
            for product in Product.objects.filter(is_active=True)
        ]
        if scope.get("factory"):
            self.fields["factory"].widget = forms.HiddenInput()
        if scope.get("line"):
            self.fields["line"].widget = forms.HiddenInput()
        if scope.get("shift"):
            self.fields["shift"].widget = forms.HiddenInput()
        bootstrapize(self)

    def clean(self):
        cleaned = super().clean()
        date_from, date_to = cleaned.get("date_from"), cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError("The start date must not be after the end date.")
        return cleaned


class ProductionLogForm(forms.ModelForm):
    class Meta:
        model = ProductionLog
        fields = [
            "production_line", "machine", "shift", "product", "date", "hour",
            "qty_produced", "qty_good", "qty_defect", "target_qty", "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "hour": forms.NumberInput(attrs={"min": 0, "max": 23}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        lines = _scoped_lines(user)
        self.fields["production_line"].queryset = lines
        self.fields["machine"].queryset = _scoped_machines(user).filter(
            production_line__in=lines
        )
        self.fields["shift"].queryset = _scoped_shifts(user)
        self.fields["product"].queryset = Product.objects.filter(is_active=True)
        if not self.instance.pk:
            self.fields["date"].initial = timezone.localdate()
            self.fields["hour"].initial = timezone.localtime().hour
            self.fields["qty_good"].initial = 0
            self.fields["qty_defect"].initial = 0
        bootstrapize(self)

    def clean(self):
        cleaned = super().clean()
        produced = cleaned.get("qty_produced") or 0
        good = cleaned.get("qty_good") or 0
        defect = cleaned.get("qty_defect") or 0
        if good + defect > produced:
            raise forms.ValidationError(
                "Good + defect cannot be larger than the produced quantity."
            )
        machine = cleaned.get("machine")
        line = cleaned.get("production_line")
        if machine and line and machine.production_line_id != line.id:
            raise forms.ValidationError("The machine does not belong to the selected line.")
        return cleaned

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        instance.source = DataSource.MANUAL
        if user is not None and user.is_authenticated:
            instance.recorded_by = user
        if commit:
            instance.save()
        return instance


class DowntimeEventForm(forms.ModelForm):
    class Meta:
        model = DowntimeEvent
        fields = [
            "machine", "started_at", "ended_at",
            "reason_category", "reason_code", "reason_note",
        ]
        widgets = {
            "started_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "ended_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "reason_note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["machine"].queryset = _scoped_machines(user)
        self.fields["started_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        self.fields["ended_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        if not self.instance.pk:
            self.fields["started_at"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        bootstrapize(self)

    def clean(self):
        cleaned = super().clean()
        started, ended = cleaned.get("started_at"), cleaned.get("ended_at")
        if started and ended and ended < started:
            raise forms.ValidationError("The end time must not be before the start time.")
        return cleaned

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        instance.source = DataSource.MANUAL
        if user is not None and user.is_authenticated:
            instance.recorded_by = user
        if commit:
            instance.save()
        return instance


class QualityCheckForm(forms.ModelForm):
    class Meta:
        model = QualityCheck
        fields = [
            "production_line", "machine", "product", "shift", "checked_at",
            "qty_checked", "qty_passed", "qty_defected", "defect_type",
            "defect_count", "notes",
        ]
        widgets = {
            "checked_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        lines = _scoped_lines(user)
        self.fields["production_line"].queryset = lines
        self.fields["machine"].queryset = _scoped_machines(user).filter(
            production_line__in=lines
        )
        self.fields["product"].queryset = Product.objects.filter(is_active=True)
        self.fields["shift"].queryset = _scoped_shifts(user)
        self.fields["checked_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        if not self.instance.pk:
            self.fields["checked_at"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        bootstrapize(self)

    def clean(self):
        cleaned = super().clean()
        checked = cleaned.get("qty_checked") or 0
        passed = cleaned.get("qty_passed") or 0
        defected = cleaned.get("qty_defected") or 0
        if passed + defected > checked:
            raise forms.ValidationError("Passed + defective cannot exceed the checked quantity.")
        return cleaned

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        instance.source = DataSource.MANUAL
        if user is not None and user.is_authenticated:
            instance.inspector = user
        if commit:
            instance.save()
        return instance


class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = [
            "inventory_item", "movement_type", "quantity",
            "reference_no", "reason", "moved_at",
        ]
        widgets = {
            "moved_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inventory_item"].queryset = InventoryItem.objects.select_related("product")
        self.fields["moved_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        if not self.instance.pk:
            self.fields["moved_at"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        bootstrapize(self)

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        instance.source = DataSource.MANUAL
        if user is not None and user.is_authenticated:
            instance.recorded_by = user
        if commit:
            instance.save()
            self._update_balance(instance)
        return instance

    @staticmethod
    def _update_balance(movement):
        item = movement.inventory_item
        if movement.movement_type in {MovementType.OUT, MovementType.TRANSFER_OUT}:
            item.qty_on_hand = max(item.qty_on_hand - abs(movement.quantity), 0)
        elif movement.movement_type == MovementType.ADJUST:
            item.qty_on_hand = movement.quantity
        else:
            item.qty_on_hand += abs(movement.quantity)
        item.save(update_fields=["qty_on_hand", "updated_at"])
        movement.balance_after = item.qty_on_hand
        movement.save(update_fields=["balance_after"])


class ImportForm(forms.Form):
    """CSV / Excel bulk import."""

    DATA_TYPES = [
        ("production", "Production logs"),
        ("downtime", "Downtime events"),
        ("quality", "Quality checks"),
        ("stock", "Stock movements"),
    ]

    data_type = forms.ChoiceField(choices=DATA_TYPES, label="Data type")
    file = forms.FileField(
        label="File",
        help_text="CSV or XLSX file. Use the template download to get the right columns.",
    )
    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        label="Update rows that already exist (matched on date + line + shift + product)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapize(self)

    def clean_file(self):
        upload = self.cleaned_data["file"]
        name = (upload.name or "").lower()
        if not name.endswith((".csv", ".xlsx", ".xlsm")):
            raise forms.ValidationError("Only .csv and .xlsx files are supported.")
        if upload.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The file is larger than 10 MB.")
        return upload


class ThresholdForm(forms.ModelForm):
    class Meta:
        from apps.core.models import Threshold

        model = Threshold
        fields = [
            "name", "description", "scope_type", "factory", "production_line",
            "machine", "product", "metric", "operator", "value", "severity",
            "cooldown_minutes", "notify_email", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapize(self)
