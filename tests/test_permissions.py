"""Role based permissions and data scoping."""

import pytest

from apps.core.permissions import (
    can_enter_data,
    can_export,
    can_manage_structure,
    is_admin,
    is_manager,
    scope_for_user,
)

pytestmark = pytest.mark.django_db


def test_roles_are_recognised(admin_user, manager_user, supervisor_user, operator_user):
    assert is_admin(admin_user)
    assert is_manager(manager_user)
    assert not is_manager(operator_user)
    assert can_export(manager_user)
    assert not can_export(operator_user)
    assert can_enter_data(operator_user)
    assert can_manage_structure(admin_user)
    assert not can_manage_structure(manager_user)


def test_supervisor_is_scoped_to_his_line(supervisor_user, line):
    scope = scope_for_user(supervisor_user)
    assert scope["line"] == line.id
    assert scope["factory"] == line.factory_id


def test_manager_has_no_restriction(manager_user):
    scope = scope_for_user(manager_user)
    assert scope == {"factory": None, "line": None, "shift": None}


def test_supervisor_cannot_see_another_line(supervisor_user, other_line, production_log):
    from apps.core.services.filters import FilterParams

    filters = FilterParams().restricted_for(supervisor_user)
    assert filters.line == supervisor_user.profile.production_line_id
    # The other line's data is filtered away.
    from apps.core.models import ProductionLog

    qs = filters.apply_production(ProductionLog.objects.all())
    assert qs.count() == 1  # only the record of *his own* line stays visible

    # A record of another line must not show up.
    ProductionLog.objects.create(
        production_line=other_line,
        shift=supervisor_user.profile.shift,
        product=production_log.product,
        date=production_log.date,
        hour=11,
        qty_produced=50,
        qty_good=50,
        qty_defect=0,
    )
    assert filters.apply_production(ProductionLog.objects.all()).count() == 1


def test_supervisor_cannot_open_the_reports_page(supervisor_user, client):
    client.force_login(supervisor_user)
    response = client.get("/reports/")
    assert response.status_code == 403


def test_operator_cannot_manage_structure(supervisor_user, client):
    client.force_login(supervisor_user)
    response = client.get("/thresholds/")
    assert response.status_code == 403


def test_admin_can_open_the_thresholds_page(admin_user, client):
    client.force_login(admin_user)
    response = client.get("/thresholds/")
    assert response.status_code == 200


def test_api_scope_is_applied_to_the_queryset(supervisor_user, other_line, production_log):
    from apps.core.permissions import apply_scope
    from apps.core.models import ProductionLog

    qs = apply_scope(ProductionLog.objects.all(), supervisor_user, field="production_line")
    assert qs.count() == 1  # his own line

    ProductionLog.objects.create(
        production_line=other_line,
        shift=supervisor_user.profile.shift,
        product=production_log.product,
        date=production_log.date,
        hour=12,
        qty_produced=50,
        qty_good=50,
        qty_defect=0,
    )
    qs = apply_scope(ProductionLog.objects.all(), supervisor_user, field="production_line")
    assert qs.count() == 1
