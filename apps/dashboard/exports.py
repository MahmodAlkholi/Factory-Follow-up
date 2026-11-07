"""
Report export.

* **Excel** - one workbook with a summary sheet plus one sheet per data set.
* **PDF**  - a short management report (KPIs + the three main tables).
"""

import io
from datetime import datetime

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import (
    DowntimeEvent,
    InventoryItem,
    ProductionLog,
    QualityCheck,
    StockMovement,
)
from apps.core.services import kpi

from . import pdf_support


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_production(filters):
    qs = filters.apply_production(
        ProductionLog.objects.select_related(
            "production_line", "production_line__factory", "shift", "product", "machine"
        )
    ).order_by("-date", "-hour")
    return [
        {
            "date": row.date.isoformat(),
            "hour": row.hour,
            "factory": row.production_line.factory.name,
            "line": row.production_line.name,
            "machine": row.machine.name if row.machine else "",
            "shift": row.shift.name,
            "product": row.product.code,
            "produced": row.qty_produced,
            "good": row.qty_good,
            "defect": row.qty_defect,
            "target": row.target_qty,
            "source": row.get_source_display(),
        }
        for row in qs
    ]


def collect_downtime(filters):
    qs = filters.apply_downtime(
        DowntimeEvent.objects.select_related(
            "machine", "production_line", "production_line__factory", "shift"
        )
    ).order_by("-started_at")
    return [
        {
            "started_at": timezone.localtime(row.started_at).strftime("%Y-%m-%d %H:%M"),
            "ended_at": timezone.localtime(row.ended_at).strftime("%Y-%m-%d %H:%M") if row.ended_at else _("ongoing"),
            "factory": row.production_line.factory.name,
            "line": row.production_line.name,
            "machine": row.machine.name,
            "shift": row.shift.name if row.shift else "",
            "reason": row.get_reason_category_display(),
            "code": row.reason_code,
            "minutes": row.duration_minutes,
            "note": row.reason_note,
        }
        for row in qs
    ]


def collect_quality(filters):
    qs = filters.apply_quality(
        QualityCheck.objects.select_related(
            "production_line", "production_line__factory", "product", "shift"
        )
    ).order_by("-checked_at")
    return [
        {
            "checked_at": timezone.localtime(row.checked_at).strftime("%Y-%m-%d %H:%M"),
            "factory": row.production_line.factory.name,
            "line": row.production_line.name,
            "product": row.product.code,
            "shift": row.shift.name if row.shift else "",
            "checked": row.qty_checked,
            "passed": row.qty_passed,
            "defected": row.qty_defected,
            "defect_rate": row.defect_rate,
            "defect_type": row.get_defect_type_display(),
        }
        for row in qs
    ]


def collect_inventory(filters):
    items = filters.apply_inventory(InventoryItem.objects.select_related("product"))
    return [
        {
            "product": row.product.code,
            "product_name": row.product.name,
            "warehouse": row.warehouse_code,
            "on_hand": row.qty_on_hand,
            "reserved": row.qty_reserved,
            "available": row.available_qty,
            "reorder_point": row.reorder_point,
            "status": row.stock_status_display,
            "value": row.stock_value,
        }
        for row in items
    ]


def collect_movements(filters):
    qs = filters.apply_movements(
        StockMovement.objects.select_related("inventory_item", "inventory_item__product")
    ).order_by("-moved_at")
    return [
        {
            "moved_at": timezone.localtime(row.moved_at).strftime("%Y-%m-%d %H:%M"),
            "product": row.inventory_item.product.code,
            "warehouse": row.inventory_item.warehouse_code,
            "type": row.get_movement_type_display(),
            "quantity": row.quantity,
            "balance_after": row.balance_after,
            "reference": row.reference_no,
            "reason": row.reason,
        }
        for row in qs
    ]


def collect_report(filters):
    """Everything the Excel and the PDF export need."""
    return {
        "generated_at": timezone.localtime(),
        "filters": filters,
        "summary": {
            "production": kpi.production_summary(filters),
            "oee": kpi.oee_summary(filters),
            "downtime": kpi.downtime_summary(filters),
            "quality": kpi.quality_summary(filters),
            "inventory": {
                key: value
                for key, value in kpi.inventory_summary(filters).items()
                if key != "low_stock_items"
            },
            "pareto": kpi.downtime_pareto(filters),
        },
        "production": collect_production(filters),
        "downtime": collect_downtime(filters),
        "quality": collect_quality(filters),
        "inventory": collect_inventory(filters),
        "movements": collect_movements(filters),
    }


def filter_description(filters):
    from apps.core.models import Factory, ProductionLine, Shift

    parts = []
    if filters.date_from:
        parts.append(str(_("from")) + f" {filters.date_from}")
    if filters.date_to:
        parts.append(str(_("to")) + f" {filters.date_to}")
    if filters.factory:
        factory = Factory.objects.filter(id=filters.factory).first()
        if factory:
            parts.append(str(factory.name))
    if filters.line:
        line = ProductionLine.objects.filter(id=filters.line).first()
        if line:
            parts.append(str(line.name))
    if filters.shift:
        shift = Shift.objects.filter(id=filters.shift).first()
        if shift:
            parts.append(str(shift.name))
    return " | ".join(parts) or _("All data")


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def export_excel(filters) -> io.BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    report = collect_report(filters)
    workbook = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")

    def add_sheet(title, rows, columns=None):
        sheet = workbook.create_sheet(title=title)
        if not rows:
            sheet.append([_("No data for the selected filters")])
            return sheet
        columns = columns or list(rows[0].keys())
        sheet.append(columns)
        for cell in sheet[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        for row in rows:
            sheet.append([row.get(column, "") for column in columns])
        for index, column in enumerate(columns, start=1):
            width = max(len(str(column)), *(len(str(row.get(column, ""))) for row in rows[:200]))
            sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 10), 45)
        sheet.freeze_panes = "A2"
        return sheet

    # --- summary sheet ---
    summary = workbook.active
    summary.title = "Summary"
    summary["A1"] = _("Factory Follow-up Report")
    summary["A1"].font = Font(bold=True, size=14)
    summary["A2"] = _("Filters")
    summary["B2"] = filter_description(filters)
    summary["A3"] = _("Generated at")
    summary["B3"] = report["generated_at"].strftime("%Y-%m-%d %H:%M")
    row = 5
    summary["A" + str(row)] = _("KPI")
    summary["B" + str(row)] = _("Value")
    for cell in summary[row]:
        cell.font = header_font
        cell.fill = header_fill
    kpi_rows = [
        (_("Produced"), report["summary"]["production"]["produced"]),
        (_("Target"), report["summary"]["production"]["target"]),
        (_("Attainment %"), report["summary"]["production"]["attainment"]),
        (_("Defect rate %"), report["summary"]["production"]["defect_rate"]),
        (_("OEE %"), report["summary"]["oee"]["oee"]),
        (_("Availability %"), report["summary"]["oee"]["availability"]),
        (_("Performance %"), report["summary"]["oee"]["performance"]),
        (_("Quality %"), report["summary"]["oee"]["quality"]),
        (_("Downtime (hours)"), report["summary"]["downtime"]["hours"]),
        (_("Downtime events"), report["summary"]["downtime"]["events"]),
        (_("Quality checked"), report["summary"]["quality"]["checked"]),
        (_("Defects found"), report["summary"]["quality"]["defected"]),
        (_("Stock value"), report["summary"]["inventory"]["total_value"]),
        (_("Low stock items"), report["summary"]["inventory"]["low_stock"]),
    ]
    for index, (label, value) in enumerate(kpi_rows, start=row + 1):
        summary[f"A{index}"] = label
        summary[f"B{index}"] = value
    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 34

    add_sheet(
        "Production",
        report["production"],
        ["date", "hour", "factory", "line", "machine", "shift", "product",
         "produced", "good", "defect", "target", "source"],
    )
    add_sheet(
        "Downtime",
        report["downtime"],
        ["started_at", "ended_at", "factory", "line", "machine", "shift",
         "reason", "code", "minutes", "note"],
    )
    add_sheet(
        "Quality",
        report["quality"],
        ["checked_at", "factory", "line", "product", "shift", "checked",
         "passed", "defected", "defect_rate", "defect_type"],
    )
    add_sheet(
        "Inventory",
        report["inventory"],
        ["product", "product_name", "warehouse", "on_hand", "reserved",
         "available", "reorder_point", "status", "value"],
    )
    add_sheet(
        "Stock movements",
        report["movements"],
        ["moved_at", "product", "warehouse", "type", "quantity",
         "balance_after", "reference", "reason"],
    )

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def export_pdf(filters, title=None) -> io.BytesIO:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    report = collect_report(filters)
    font_name, supports_arabic = pdf_support.register_font()

    def t(value):
        return pdf_support.prepare(value, supports_arabic)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=t(title or _("Factory Follow-up Report")),
        author="Factory Follow-up Dashboard",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ArabicTitle", parent=styles["Title"], fontName=font_name, fontSize=16, alignment=TA_CENTER
    )
    meta_style = ParagraphStyle(
        "ArabicMeta", parent=styles["Normal"], fontName=font_name, fontSize=8, alignment=TA_CENTER
    )
    head_style = ParagraphStyle(
        "ArabicHead", parent=styles["Normal"], fontName=font_name, fontSize=9
    )

    story = [
        Paragraph(t(title or _("Factory Follow-up Report")), title_style),
        Paragraph(t(filter_description(filters)), meta_style),
        Paragraph(
            t(_("Generated at %s") % report["generated_at"].strftime("%Y-%m-%d %H:%M")),
            meta_style,
        ),
        Spacer(1, 8 * mm),
    ]

    header_bg = colors.HexColor("#1F4E79")

    def make_table(header, rows, widths=None):
        data = [[Paragraph(t(cell), head_style) for cell in header]]
        for row in rows:
            data.append([Paragraph(t(cell), head_style) for cell in row])
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EFF4F8")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        return table

    summary = report["summary"]
    kpi_rows = [
        [_("Produced"), summary["production"]["produced"], _("Target"), summary["production"]["target"]],
        [_("Attainment %"), summary["production"]["attainment"], _("Defect rate %"), summary["production"]["defect_rate"]],
        [_("OEE %"), summary["oee"]["oee"], _("Availability %"), summary["oee"]["availability"]],
        [_("Performance %"), summary["oee"]["performance"], _("Quality %"), summary["oee"]["quality"]],
        [_("Downtime (h)"), summary["downtime"]["hours"], _("Downtime events"), summary["downtime"]["events"]],
        [_("Checked"), summary["quality"]["checked"], _("Defects"), summary["quality"]["defected"]],
        [_("Stock value"), summary["inventory"]["total_value"], _("Low stock"), summary["inventory"]["low_stock"]],
    ]
    story.append(Paragraph(t(_("Key figures")), head_style))
    story.append(
        make_table([_("Metric"), _("Value"), _("Metric"), _("Value")], kpi_rows,
                   widths=[60 * mm, 45 * mm, 60 * mm, 45 * mm])
    )
    story.append(Spacer(1, 6 * mm))

    pareto_rows = [
        [row["label"], row["events"], row["hours"], f"{row['share']}%", f"{row['cumulative']}%"]
        for row in summary["pareto"][:12]
    ]
    if pareto_rows:
        story.append(Paragraph(t(_("Downtime - top reasons")), head_style))
        story.append(
            make_table(
                [_("Reason"), _("Events"), _("Hours"), _("Share"), _("Cumulative")],
                pareto_rows,
                widths=[80 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm],
            )
        )
        story.append(Spacer(1, 6 * mm))

    production_rows = [
        [row["date"], row["line"], row["shift"], row["product"], row["produced"],
         row["target"], row["defect"]]
        for row in report["production"][:40]
    ]
    if production_rows:
        story.append(Paragraph(t(_("Production records (latest 40)")), head_style))
        story.append(
            make_table(
                [_("Date"), _("Line"), _("Shift"), _("Product"), _("Produced"),
                 _("Target"), _("Defect")],
                production_rows,
                widths=[30 * mm, 40 * mm, 30 * mm, 30 * mm, 25 * mm, 25 * mm, 20 * mm],
            )
        )

    doc.build(story)
    buffer.seek(0)
    return buffer
