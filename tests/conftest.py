"""Shared fixtures for the test suite."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.utils import timezone

from apps.core.models import (
    ApiToken,
    Factory,
    Machine,
    Product,
    ProductionLine,
    ProductionLog,
    Shift,
    UserProfile,
)


@pytest.fixture(autouse=True)
def _groups(db):
    for name in ("Admin", "Manager", "Supervisor", "Operator"):
        Group.objects.get_or_create(name=name)


@pytest.fixture
def factory(db):
    return Factory.objects.create(name="Test Plant", code="TST-01", city="Cairo")


@pytest.fixture
def line(factory):
    return ProductionLine.objects.create(
        factory=factory, name="Line 1", code="L1", target_daily_qty=1000
    )


@pytest.fixture
def other_line(factory):
    return ProductionLine.objects.create(
        factory=factory, name="Line 2", code="L2", target_daily_qty=800
    )


@pytest.fixture
def machine(line):
    return Machine.objects.create(
        production_line=line, name="Machine 1", code="M1", status="running"
    )


@pytest.fixture
def other_machine(other_line):
    return Machine.objects.create(
        production_line=other_line, name="Machine 2", code="M2", status="running"
    )


@pytest.fixture
def product(db):
    return Product.objects.create(code="P1", name="Product 1", unit="pcs")


@pytest.fixture
def shift(db):
    return Shift.objects.create(
        name="Morning", code="M", start_time="08:00", end_time="16:00"
    )


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(username="admin", password="pw", email="admin@example.com", is_superuser=True)
    user.groups.add(Group.objects.get(name="Admin"))
    return user


@pytest.fixture
def manager_user(db):
    user = User.objects.create_user(username="manager", password="pw", email="manager@example.com")
    user.groups.add(Group.objects.get(name="Manager"))
    return user


@pytest.fixture
def supervisor_user(db, line, shift):
    user = User.objects.create_user(username="supervisor", password="pw", email="supervisor@example.com")
    user.groups.add(Group.objects.get(name="Supervisor"))
    UserProfile.objects.create(user=user, production_line=line, shift=shift)
    return user


@pytest.fixture
def operator_user(db, line, shift):
    user = User.objects.create_user(username="operator", password="pw", email="operator@example.com")
    user.groups.add(Group.objects.get(name="Operator"))
    UserProfile.objects.create(user=user, production_line=line, shift=shift)
    return user


@pytest.fixture
def api_token(operator_user):
    return ApiToken.objects.create(user=operator_user, name="test")


@pytest.fixture
def production_log(line, machine, shift, product):
    today = timezone.localdate()
    return ProductionLog.objects.create(
        production_line=line,
        machine=machine,
        shift=shift,
        product=product,
        date=today,
        hour=9,
        qty_produced=100,
        qty_good=97,
        qty_defect=3,
        target_qty=120,
    )


@pytest.fixture
def production_logs(line, machine, shift, product):
    """Three days of hourly production logs."""
    today = timezone.localdate()
    logs = []
    for day_offset in range(3):
        day = today - timedelta(days=day_offset)
        for hour in (8, 9, 10):
            logs.append(
                ProductionLog.objects.create(
                    production_line=line,
                    machine=machine,
                    shift=shift,
                    product=product,
                    date=day,
                    hour=hour,
                    qty_produced=100,
                    qty_good=95,
                    qty_defect=5,
                    target_qty=120,
                )
            )
    return logs
