"""Model behaviour."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.constants import StockStatus
from apps.core.models import (
    DowntimeEvent,
    InventoryItem,
    ProductionLog,
    QualityCheck,
    Shift,
    StockMovement,
)

pytestmark = pytest.mark.django_db


def test_downtime_duration_is_computed_from_the_timestamps(machine, shift):
    start = timezone.now() - timedelta(hours=2)
    event = DowntimeEvent.objects.create(
        machine=machine,
        started_at=start,
        ended_at=start + timedelta(minutes=45),
        reason_category="mechanical",
    )
    assert event.duration_minutes == 45
    assert event.production_line_id == machine.production_line_id
    assert event.shift_id == shift.id


def test_ongoing_downtime_keeps_growing(machine):
    event = DowntimeEvent.objects.create(
        machine=machine,
        started_at=timezone.now() - timedelta(minutes=30),
        reason_category="mechanical",
    )
    assert event.is_ongoing
    assert 29 <= event.duration_minutes <= 31


def test_production_log_rejects_good_greater_than_produced(line, shift, product):
    from django.core.exceptions import ValidationError

    log = ProductionLog(
        production_line=line,
        shift=shift,
        product=product,
        date=timezone.localdate(),
        hour=9,
        qty_produced=10,
        qty_good=20,
    )
    with pytest.raises(ValidationError):
        log.full_clean()


def test_quality_check_defect_rate(product, line):
    check = QualityCheck.objects.create(
        production_line=line,
        product=product,
        checked_at=timezone.now(),
        qty_checked=200,
        qty_passed=190,
        qty_defected=10,
    )
    assert check.defect_rate == 5.0


def test_inventory_low_stock_detection(product):
    item = InventoryItem.objects.create(
        product=product,
        warehouse_code="WH-1",
        qty_on_hand=50,
        reorder_point=100,
    )
    assert item.stock_status == StockStatus.LOW
    assert item.is_low
    assert item.available_qty == 50


def test_stock_movement_signed_quantity(product):
    item = InventoryItem.objects.create(product=product, warehouse_code="WH-1", qty_on_hand=100)
    movement = StockMovement.objects.create(
        inventory_item=item, movement_type="out", quantity=30
    )
    assert movement.signed_quantity == -30


def test_shift_duration_and_window(shift):
    assert shift.duration_minutes == 480


def test_shift_for_datetime_handles_the_night_shift(db):
    night = Shift.objects.create(
        name="Night", code="N", start_time="00:00", end_time="08:00"
    )
    moment = timezone.make_aware(
        timezone.datetime.combine(timezone.localdate(), timezone.datetime.min.time())
    ) + timedelta(hours=3)
    assert Shift.for_datetime(moment) == night
