"""
CSV / Excel bulk import.

The importer is deliberately forgiving about column names (a plant will
export "Line Code", "line_code" or "LINE" from three different systems) but
strict about the values.
"""

import csv
import io
from datetime import date, datetime

from django.utils import timezone

from apps.core.constants import DataSource, MovementType
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

# Canonical field -> accepted header spellings (normalised: lower, _ for space)
COLUMN_ALIASES = {
    "production": {
        "line_code": ["line_code", "line", "production_line", "line id"],
        "machine_code": ["machine_code", "machine", "machine id"],
        "shift_code": ["shift_code", "shift"],
        "product_code": ["product_code", "product", "item", "item_code"],
        "date": ["date", "day", "production_date"],
        "hour": ["hour", "hr", "hour_of_day"],
        "qty_produced": ["qty_produced", "produced", "quantity", "qty", "output"],
        "qty_good": ["qty_good", "good", "ok_qty", "accepted"],
        "qty_defect": ["qty_defect", "defect", "rejected", "scrap", "ng"],
        "target_qty": ["target_qty", "target", "plan", "planned_qty"],
        "notes": ["notes", "note", "comment", "remarks"],
    },
    "downtime": {
        "machine_code": ["machine_code", "machine", "machine id"],
        "started_at": ["started_at", "start", "start_time", "from", "downtime_start"],
        "ended_at": ["ended_at", "end", "end_time", "to", "downtime_end"],
        "duration_minutes": ["duration_minutes", "duration", "minutes", "downtime_minutes"],
        "reason_category": ["reason_category", "reason", "category", "cause"],
        "reason_code": ["reason_code", "code"],
        "reason_note": ["reason_note", "detail", "details", "description", "comment"],
    },
    "quality": {
        "line_code": ["line_code", "line", "production_line"],
        "machine_code": ["machine_code", "machine"],
        "product_code": ["product_code", "product", "item"],
        "shift_code": ["shift_code", "shift"],
        "checked_at": ["checked_at", "checked", "time", "timestamp", "date"],
        "qty_checked": ["qty_checked", "checked_qty", "sample", "sample_size"],
        "qty_passed": ["qty_passed", "passed", "ok_qty"],
        "qty_defected": ["qty_defected", "defected", "defect_qty", "ng"],
        "defect_type": ["defect_type", "defect", "type", "category"],
        "defect_count": ["defect_count", "occurrences", "count"],
        "notes": ["notes", "note", "comment"],
    },
    "stock": {
        "product_code": ["product_code", "product", "item"],
        "warehouse_code": ["warehouse_code", "warehouse", "location", "store"],
        "movement_type": ["movement_type", "type", "movement"],
        "quantity": ["quantity", "qty", "amount"],
        "reference_no": ["reference_no", "reference", "ref", "document"],
        "reason": ["reason", "note", "comment"],
        "moved_at": ["moved_at", "date", "timestamp", "time"],
    },
}

REQUIRED_FIELDS = {
    "production": ["line_code", "shift_code", "product_code", "date", "hour", "qty_produced"],
    "downtime": ["machine_code", "started_at"],
    "quality": ["line_code", "product_code", "checked_at", "qty_checked"],
    "stock": ["product_code", "warehouse_code", "movement_type", "quantity"],
}

TEMPLATE_HEADERS = {
    "production": [
        "line_code", "machine_code", "shift_code", "product_code", "date", "hour",
        "qty_produced", "qty_good", "qty_defect", "target_qty", "notes",
    ],
    "downtime": [
        "machine_code", "started_at", "ended_at", "duration_minutes",
        "reason_category", "reason_code", "reason_note",
    ],
    "quality": [
        "line_code", "machine_code", "product_code", "shift_code", "checked_at",
        "qty_checked", "qty_passed", "qty_defected", "defect_type", "defect_count", "notes",
    ],
    "stock": [
        "product_code", "warehouse_code", "movement_type", "quantity",
        "reference_no", "reason", "moved_at",
    ],
}

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"]
DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
]


def _normalise_header(value):
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _pick(row, canonical, aliases):
    for alias in aliases:
        if alias in row and str(row[alias]).strip() != "":
            return str(row[alias]).strip()
    return None


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    text = str(value).strip()
    for fmt in DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        except ValueError:
            continue
    parsed = parse_date(text)
    if parsed:
        return timezone.make_aware(
            datetime.combine(parsed, datetime.min.time()), timezone.get_current_timezone()
        )
    return None


def parse_int(value, default=0):
    if value in (None, ""):
        return default
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def parse_float(value, default=0.0):
    if value in (None, ""):
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_rows(upload):
    """Read an uploaded CSV/XLSX file into a list of raw dicts."""
    name = (upload.name or "").lower()
    upload.seek(0)
    if name.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(upload)
    return _read_csv(upload)


def _read_csv(upload):
    raw = upload.read()
    if isinstance(raw, bytes):
        for encoding in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        normalised = {_normalise_header(k): v for k, v in row.items() if k}
        if any(str(v).strip() for v in normalised.values()):
            rows.append(normalised)
    return rows


def _read_xlsx(upload):
    from openpyxl import load_workbook

    workbook = load_workbook(upload, read_only=True, data_only=True)
    sheet = workbook.active
    rows = []
    headers = None
    for raw_row in sheet.iter_rows(values_only=True):
        if headers is None:
            headers = [_normalise_header(cell) for cell in raw_row]
            continue
        if raw_row is None or all(cell in (None, "") for cell in raw_row):
            continue
        row = {}
        for index, cell in enumerate(raw_row):
            key = headers[index] if index < len(headers) else f"col{index}"
            if key:
                row[key] = "" if cell is None else cell
        rows.append(row)
    workbook.close()
    return rows


def normalise_rows(data_type, raw_rows):
    """Map raw rows onto the canonical field names of ``data_type``."""
    aliases = COLUMN_ALIASES[data_type]
    normalised = []
    for index, row in enumerate(raw_rows):
        item = {field: _pick(row, field, names) for field, names in aliases.items()}
        item["_row"] = index + 2  # +2 => header row + 1-based numbering
        normalised.append(item)
    return normalised


def import_records(data_type, rows, user=None, update_existing=True):
    """
    Import the rows and report what happened.

    Returns ``(created, updated, errors)`` where errors is a list of
    ``{"row": int, "error": str}`` dicts.
    """
    handler = {
        "production": _import_production,
        "downtime": _import_downtime,
        "quality": _import_quality,
        "stock": _import_stock,
    }[data_type]

    created = updated = 0
    errors = []
    for row in rows:
        try:
            result = handler(row, user=user, update_existing=update_existing)
            if result == "created":
                created += 1
            else:
                updated += 1
        except Exception as exc:
            errors.append({"row": row.get("_row"), "error": str(exc)})
    return created, updated, errors


def _import_production(row, user=None, update_existing=True):
    line = ProductionLine.objects.filter(code=row["line_code"]).first()
    if not line:
        raise ValueError(f"Unknown line code '{row['line_code']}'")
    shift = Shift.objects.filter(code=row["shift_code"]).first()
    if not shift:
        raise ValueError(f"Unknown shift code '{row['shift_code']}'")
    product = Product.objects.filter(code=row["product_code"]).first()
    if not product:
        raise ValueError(f"Unknown product code '{row['product_code']}'")
    machine = None
    if row.get("machine_code"):
        machine = Machine.objects.filter(
            code=row["machine_code"], production_line=line
        ).first()
        if not machine:
            raise ValueError(f"Unknown machine code '{row['machine_code']}' on line {line.code}")
    day = parse_date(row.get("date"))
    if not day:
        raise ValueError("Invalid or missing date")
    produced = parse_int(row.get("qty_produced"))
    good = parse_int(row.get("qty_good"), produced)
    defect = parse_int(row.get("qty_defect"), 0)
    if good + defect > produced:
        raise ValueError("qty_good + qty_defect is larger than qty_produced")
    defaults = {
        "machine": machine,
        "qty_produced": produced,
        "qty_good": good,
        "qty_defect": defect,
        "target_qty": parse_int(row.get("target_qty")),
        "notes": row.get("notes") or "",
        "source": DataSource.IMPORT,
        "recorded_by": user if (user and user.is_authenticated) else None,
    }
    if update_existing:
        obj, created = ProductionLog.objects.update_or_create(
            production_line=line, shift=shift, product=product,
            date=day, hour=parse_int(row.get("hour")), defaults=defaults,
        )
    else:
        obj = ProductionLog.objects.create(
            production_line=line, shift=shift, product=product,
            date=day, hour=parse_int(row.get("hour")), **defaults,
        )
        created = True
    return "created" if created else "updated"


def _import_downtime(row, user=None, update_existing=True):
    machine = Machine.objects.filter(code=row["machine_code"]).first()
    if not machine:
        raise ValueError(f"Unknown machine code '{row['machine_code']}'")
    started = parse_datetime(row.get("started_at"))
    if not started:
        raise ValueError("Invalid or missing start time")
    ended = parse_datetime(row.get("ended_at"))
    duration = parse_int(row.get("duration_minutes"))
    if ended and not duration:
        duration = int((ended - started).total_seconds() // 60)
    defaults = {
        "ended_at": ended,
        "duration_minutes": duration,
        "reason_category": (row.get("reason_category") or "other").lower(),
        "reason_code": row.get("reason_code") or "",
        "reason_note": row.get("reason_note") or "",
        "source": DataSource.IMPORT,
        "recorded_by": user if (user and user.is_authenticated) else None,
    }
    if update_existing:
        obj, created = DowntimeEvent.objects.update_or_create(
            machine=machine, started_at=started, defaults=defaults,
        )
    else:
        obj = DowntimeEvent.objects.create(machine=machine, started_at=started, **defaults)
        created = True
    return "created" if created else "updated"


def _import_quality(row, user=None, update_existing=True):
    line = ProductionLine.objects.filter(code=row["line_code"]).first()
    if not line:
        raise ValueError(f"Unknown line code '{row['line_code']}'")
    product = Product.objects.filter(code=row["product_code"]).first()
    if not product:
        raise ValueError(f"Unknown product code '{row['product_code']}'")
    checked_at = parse_datetime(row.get("checked_at"))
    if not checked_at:
        raise ValueError("Invalid or missing check time")
    shift = None
    if row.get("shift_code"):
        shift = Shift.objects.filter(code=row["shift_code"]).first()
    machine = None
    if row.get("machine_code"):
        machine = Machine.objects.filter(
            code=row["machine_code"], production_line=line
        ).first()
    checked = parse_int(row.get("qty_checked"))
    passed = parse_int(row.get("qty_passed"), checked)
    defected = parse_int(row.get("qty_defected"), 0)
    if passed + defected > checked:
        raise ValueError("qty_passed + qty_defected is larger than qty_checked")
    defaults = {
        "machine": machine,
        "shift": shift,
        "qty_checked": checked,
        "qty_passed": passed,
        "qty_defected": defected,
        "defect_type": (row.get("defect_type") or "other").lower(),
        "defect_count": parse_int(row.get("defect_count")),
        "notes": row.get("notes") or "",
        "source": DataSource.IMPORT,
        "inspector": user if (user and user.is_authenticated) else None,
    }
    if update_existing:
        obj, created = QualityCheck.objects.update_or_create(
            production_line=line, product=product, checked_at=checked_at, defaults=defaults,
        )
    else:
        obj = QualityCheck.objects.create(
            production_line=line, product=product, checked_at=checked_at, **defaults
        )
        created = True
    return "created" if created else "updated"


def _import_stock(row, user=None, update_existing=True):
    product = Product.objects.filter(code=row["product_code"]).first()
    if not product:
        raise ValueError(f"Unknown product code '{row['product_code']}'")
    item, _ = InventoryItem.objects.get_or_create(
        product=product,
        warehouse_code=row["warehouse_code"],
        defaults={"warehouse_name": row["warehouse_code"]},
    )
    movement_type = (row.get("movement_type") or MovementType.IN).lower()
    if movement_type not in MovementType.values:
        raise ValueError(f"Unknown movement type '{movement_type}'")
    quantity = parse_float(row.get("quantity"))
    if movement_type in {MovementType.OUT, MovementType.TRANSFER_OUT}:
        new_qty = item.qty_on_hand - abs(quantity)
    elif movement_type == MovementType.ADJUST:
        new_qty = quantity
    else:
        new_qty = item.qty_on_hand + abs(quantity)
    item.qty_on_hand = new_qty
    item.save(update_fields=["qty_on_hand", "updated_at"])

    defaults = {
        "quantity": abs(quantity),
        "balance_after": new_qty,
        "reference_no": row.get("reference_no") or "",
        "reason": row.get("reason") or "",
        "source": DataSource.IMPORT,
        "recorded_by": user if (user and user.is_authenticated) else None,
    }
    if update_existing:
        obj, created = StockMovement.objects.update_or_create(
            inventory_item=item,
            movement_type=movement_type,
            moved_at=parse_datetime(row.get("moved_at")) or timezone.now(),
            defaults=defaults,
        )
    else:
        obj = StockMovement.objects.create(
            inventory_item=item,
            movement_type=movement_type,
            moved_at=parse_datetime(row.get("moved_at")) or timezone.now(),
            **defaults,
        )
        created = True
    return "created" if created else "updated"


def template_csv(data_type: str) -> str:
    """A ready-to-fill CSV template for the given data type."""
    headers = TEMPLATE_HEADERS[data_type]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    if data_type == "production":
        writer.writerow(["LINE-A", "M-01", "M", "PRD-001", "2026-11-07", 8, 120, 118, 2, 130, ""])
    elif data_type == "downtime":
        writer.writerow(["M-01", "2026-11-07 08:15:00", "2026-11-07 08:45:00", 30, "mechanical", "BEARING", "Bearing hot"])
    elif data_type == "quality":
        writer.writerow(["LINE-A", "M-01", "PRD-001", "M", "2026-11-07 09:00:00", 50, 48, 2, "dimensional", 2, ""])
    elif data_type == "stock":
        writer.writerow(["PRD-001", "WH-01", "in", 500, "PO-8891", "Purchase receipt", "2026-11-07 07:30:00"])
    return buffer.getvalue()
