"""The dashboard pages, the data entry forms, the import and the export."""

import io
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import DowntimeEvent, InventoryItem, ProductionLog, QualityCheck, StockMovement

pytestmark = pytest.mark.django_db


PAGES = [
    "/",
    "/production/",
    "/downtime/",
    "/quality/",
    "/inventory/",
    "/reports/",
    "/data-entry/",
    "/import/",
    "/alerts/",
]


@pytest.mark.parametrize("url", PAGES)
def test_pages_render_for_a_manager(client, manager_user, url):
    client.force_login(manager_user)
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.parametrize("url", PAGES)
def test_pages_redirect_when_logged_out(client, url):
    response = client.get(url)
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_overview_contains_the_kpi_cards(client, manager_user, production_log):
    client.force_login(manager_user)
    response = client.get("/")
    assert response.status_code == 200
    assert b"kpi-card" in response.content
    assert b"kpi-cards" in response.content


def test_filters_are_applied_to_the_page(client, manager_user, other_line, production_log):
    client.force_login(manager_user)
    response = client.get(f"/production/?line={other_line.id}")
    assert response.status_code == 200
    assert b"No data" in response.content


def test_htmx_kpi_partial(client, manager_user, production_log):
    client.force_login(manager_user)
    response = client.get("/overview/kpis/")
    assert response.status_code == 200
    assert b"hx-trigger" in response.content


def test_chart_json_endpoint(client, manager_user, production_log):
    client.force_login(manager_user)
    response = client.get("/charts/daily/")
    assert response.status_code == 200
    assert "data" in response.json()


def test_production_entry_creates_a_record(client, operator_user, line, machine, shift, product):
    client.force_login(operator_user)
    response = client.post(
        reverse("dashboard:entry-production"),
        {
            "production_line": line.id,
            "machine": machine.id,
            "shift": shift.id,
            "product": product.id,
            "date": timezone.localdate().isoformat(),
            "hour": 11,
            "qty_produced": 120,
            "qty_good": 118,
            "qty_defect": 2,
            "target_qty": 130,
        },
    )
    assert response.status_code == 302
    assert ProductionLog.objects.filter(hour=11).exists()


def test_production_entry_rejects_impossible_quantities(
    client, operator_user, line, machine, shift, product
):
    client.force_login(operator_user)
    response = client.post(
        reverse("dashboard:entry-production"),
        {
            "production_line": line.id,
            "machine": machine.id,
            "shift": shift.id,
            "product": product.id,
            "date": timezone.localdate().isoformat(),
            "hour": 11,
            "qty_produced": 10,
            "qty_good": 9,
            "qty_defect": 9,
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert not ProductionLog.objects.filter(hour=11).exists()


def test_downtime_entry_creates_an_event(client, operator_user, machine):
    client.force_login(operator_user)
    start = timezone.now() - timedelta(hours=1)
    response = client.post(
        reverse("dashboard:entry-downtime"),
        {
            "machine": machine.id,
            "started_at": start.strftime("%Y-%m-%dT%H:%M"),
            "ended_at": (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"),
            "reason_category": "mechanical",
            "reason_code": "BEARING",
        },
    )
    assert response.status_code == 302
    assert DowntimeEvent.objects.filter(machine=machine).exists()


def test_stock_entry_updates_the_balance(client, operator_user, product):
    client.force_login(operator_user)
    item = InventoryItem.objects.create(
        product=product, warehouse_code="WH-1", qty_on_hand=100, reorder_point=10
    )
    response = client.post(
        reverse("dashboard:entry-stock"),
        {
            "inventory_item": item.id,
            "movement_type": "out",
            "quantity": 30,
            "reference_no": "PO-1",
            "reason": "consumption",
            "moved_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
        },
    )
    assert response.status_code == 302
    item.refresh_from_db()
    assert float(item.qty_on_hand) == 70
    assert StockMovement.objects.count() == 1


def test_quality_entry(client, operator_user, line, product):
    client.force_login(operator_user)
    response = client.post(
        reverse("dashboard:entry-quality"),
        {
            "production_line": line.id,
            "product": product.id,
            "checked_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            "qty_checked": 50,
            "qty_passed": 48,
            "qty_defected": 2,
            "defect_type": "dimensional",
            "defect_count": 2,
        },
    )
    assert response.status_code == 302
    assert QualityCheck.objects.count() == 1


def test_csv_import(client, operator_user, line, machine, shift, product):
    client.force_login(operator_user)
    csv_content = (
        "line_code,machine_code,shift_code,product_code,date,hour,qty_produced,qty_good,qty_defect,target_qty\n"
        f"{line.code},{machine.code},{shift.code},{product.code},2026-11-06,8,120,118,2,130\n"
        f"{line.code},{machine.code},{shift.code},{product.code},2026-11-06,9,110,110,0,130\n"
    )
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile(
        "production.csv", csv_content.encode("utf-8"), content_type="text/csv"
    )
    response = client.post(
        reverse("dashboard:import"),
        {"data_type": "production", "file": upload, "update_existing": "on"},
    )
    assert response.status_code == 200
    assert ProductionLog.objects.filter(date="2026-11-06").count() == 2


def test_import_template_download(client, manager_user):
    client.force_login(manager_user)
    response = client.get(reverse("dashboard:import-template", args=["production"]))
    assert response.status_code == 200
    assert b"line_code" in response.content


def test_excel_export(client, manager_user, production_log):
    client.force_login(manager_user)
    response = client.get(reverse("dashboard:report-export", args=["xlsx"]))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert len(response.content) > 2000


def test_pdf_export(client, manager_user, production_log):
    client.force_login(manager_user)
    response = client.get(reverse("dashboard:report-export", args=["pdf"]))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"


def test_operator_cannot_export(client, operator_user):
    client.force_login(operator_user)
    response = client.get(reverse("dashboard:report-export", args=["xlsx"]))
    assert response.status_code == 403


def test_excel_export_labels_follow_the_language(client, manager_user, production_log):
    """The summary sheet must not stay English in the Arabic UI."""
    from openpyxl import load_workbook

    client.force_login(manager_user)
    response = client.get(
        reverse("dashboard:report-export", args=["xlsx"]),
        HTTP_ACCEPT_LANGUAGE="ar",
    )
    assert response.status_code == 200
    sheet = load_workbook(io.BytesIO(response.content))["Summary"]
    labels = [cell.value for cell in sheet["A"] if cell.value]
    assert "الإنتاج" in labels
    assert "Produced" not in labels


def test_excel_export_reason_labels_follow_the_language(client, manager_user, production_log, machine):
    """The downtime sheet carries the translated reason, not the raw code."""
    from openpyxl import load_workbook

    start = timezone.now() - timedelta(hours=3)
    DowntimeEvent.objects.create(
        machine=machine,
        started_at=start,
        ended_at=start + timedelta(minutes=45),
        reason_category="mechanical",
    )
    client.force_login(manager_user)
    response = client.get(
        reverse("dashboard:report-export", args=["xlsx"]),
        HTTP_ACCEPT_LANGUAGE="ar",
    )
    sheet = load_workbook(io.BytesIO(response.content))["Downtime"]
    # "reason" is the seventh column of the downtime sheet.
    reasons = [cell.value for cell in sheet["G"] if cell.value]
    assert "ميكانيكي" in reasons
    assert "mechanical" not in reasons


def test_the_chart_endpoint_needs_a_login(client):
    response = client.get("/charts/daily/")
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_the_chart_endpoint_respects_the_user_scope(
    client, supervisor_user, other_line, product, shift
):
    from apps.core.models import ProductionLog

    # A record of the supervisor's own line ...
    ProductionLog.objects.create(
        production_line=supervisor_user.profile.production_line,
        shift=shift,
        product=product,
        date=timezone.localdate(),
        hour=9,
        qty_produced=50,
        qty_good=50,
        qty_defect=0,
    )
    # ... and one of another line that must stay invisible.
    ProductionLog.objects.create(
        production_line=other_line,
        shift=shift,
        product=product,
        date=timezone.localdate(),
        hour=9,
        qty_produced=999,
        qty_good=999,
        qty_defect=0,
    )
    client.force_login(supervisor_user)
    response = client.get("/charts/daily/")
    assert response.status_code == 200
    produced = response.json()["data"][0]["produced"]
    assert produced == 50


def test_a_supervisor_cannot_acknowledge_an_alert_of_another_line(
    client, supervisor_user, other_line, machine
):
    from apps.core.constants import AlertStatus
    from apps.core.models import Alert

    alert = Alert.objects.create(
        production_line=other_line,
        metric="defect_rate",
        value=9,
        message="Other line is in trouble",
        severity="warning",
        status=AlertStatus.OPEN,
    )
    client.force_login(supervisor_user)
    response = client.post(
        reverse("dashboard:alert-action", args=[alert.pk]), {"action": "ack"}
    )
    assert response.status_code == 403
    alert.refresh_from_db()
    assert alert.status == AlertStatus.OPEN
