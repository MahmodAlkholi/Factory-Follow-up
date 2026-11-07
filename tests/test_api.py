"""The IoT / machine ingestion API."""

import json

import pytest
from django.urls import reverse

from apps.core.models import DowntimeEvent, ProductionLog, QualityCheck


pytestmark = pytest.mark.django_db


def test_ingest_requires_a_token(api_token):
    client = api_token.__class__.objects.none()  # keep the fixture alive
    response = api_client().post(
        reverse("api:ingest-production"),
        data=json.dumps({"records": []}),
        content_type="application/json",
    )
    assert response.status_code == 401


def api_client():
    from rest_framework.test import APIClient

    return APIClient()


def test_ingest_production_creates_a_record(api_token, line, machine, shift, product):
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + api_token.key)
    payload = {
        "records": [
            {
                "line_code": line.code,
                "machine_code": machine.code,
                "shift_code": shift.code,
                "product_code": product.code,
                "date": "2026-11-07",
                "hour": 9,
                "qty_produced": 120,
                "qty_good": 118,
                "qty_defect": 2,
                "target_qty": 130,
            }
        ]
    }
    response = client.post(
        reverse("api:ingest-production"), data=json.dumps(payload), content_type="application/json"
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["created"] == 1
    assert ProductionLog.objects.filter(date="2026-11-07", hour=9).exists()


def test_ingest_production_is_idempotent(api_token, line, shift, product):
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + api_token.key)
    payload = {
        "records": [
            {
                "line_code": line.code,
                "shift_code": shift.code,
                "product_code": product.code,
                "date": "2026-11-07",
                "hour": 9,
                "qty_produced": 120,
            }
        ]
    }
    client.post(reverse("api:ingest-production"), data=json.dumps(payload), content_type="application/json")
    response = client.post(
        reverse("api:ingest-production"), data=json.dumps(payload), content_type="application/json"
    )
    body = response.json()
    assert body["created"] == 0
    assert body["updated"] == 1
    assert ProductionLog.objects.count() == 1


def test_ingest_reports_a_broken_record_without_failing_the_batch(api_token, line, shift, product):
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + api_token.key)
    payload = {
        "records": [
            {
                "line_code": "DOES-NOT-EXIST",
                "shift_code": shift.code,
                "product_code": product.code,
                "date": "2026-11-07",
                "hour": 9,
                "qty_produced": 10,
            },
            {
                "line_code": line.code,
                "shift_code": shift.code,
                "product_code": product.code,
                "date": "2026-11-07",
                "hour": 10,
                "qty_produced": 10,
            },
        ]
    }
    response = client.post(
        reverse("api:ingest-production"), data=json.dumps(payload), content_type="application/json"
    )
    assert response.status_code == 207
    body = response.json()
    assert body["created"] == 1
    assert body["failed"] == 1
    assert body["errors"][0]["index"] == 0


def test_ingest_downtime(api_token, machine):
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + api_token.key)
    payload = {
        "records": [
            {
                "machine_code": machine.code,
                "started_at": "2026-11-07T08:15:00Z",
                "ended_at": "2026-11-07T08:45:00Z",
                "reason_category": "mechanical",
                "reason_code": "BEARING",
            }
        ]
    }
    response = client.post(
        reverse("api:ingest-downtime"), data=json.dumps(payload), content_type="application/json"
    )
    assert response.status_code == 200, response.content
    event = DowntimeEvent.objects.get(machine=machine)
    assert event.duration_minutes == 30


def test_ingest_quality(api_token, line, product):
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + api_token.key)
    payload = {
        "records": [
            {
                "line_code": line.code,
                "product_code": product.code,
                "checked_at": "2026-11-07T09:00:00Z",
                "qty_checked": 50,
                "qty_passed": 48,
                "qty_defected": 2,
                "defect_type": "dimensional",
            }
        ]
    }
    response = client.post(
        reverse("api:ingest-quality"), data=json.dumps(payload), content_type="application/json"
    )
    assert response.status_code == 200, response.content
    check = QualityCheck.objects.get()
    assert check.defect_rate == 4.0


def test_dashboard_summary_endpoint(manager_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(manager_user)
    response = client.get(reverse("api:dashboard-summary"))
    assert response.status_code == 200
    body = response.json()
    assert "kpis" in body and "oee" in body


def test_current_user_endpoint_reports_the_scope(supervisor_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(supervisor_user)
    response = client.get(reverse("api:current-user"))
    assert response.status_code == 200
    body = response.json()
    assert body["scope"]["line"] == supervisor_user.profile.production_line_id
    assert "Supervisor" in body["roles"]


# ---------------------------------------------------------------------------
# Scheduled alert evaluation
# ---------------------------------------------------------------------------
def test_evaluate_thresholds_needs_a_token():
    from rest_framework.test import APIClient

    response = APIClient().post(reverse("api:thresholds-evaluate"))
    assert response.status_code == 401


def test_evaluate_thresholds_rejects_an_operator_token(api_token):
    """The api_token fixture belongs to an operator - not enough."""
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + api_token.key)
    response = client.post(reverse("api:thresholds-evaluate"))
    assert response.status_code == 403


def test_evaluate_thresholds_with_an_admin_token(admin_user):
    from apps.core.models import ApiToken
    from rest_framework.test import APIClient

    token = ApiToken.objects.create(user=admin_user, name="scheduler")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + token.key)
    response = client.post(reverse("api:thresholds-evaluate"))
    assert response.status_code == 200
    body = response.json()
    assert "raised" in body and "alerts" in body


def test_evaluate_thresholds_can_skip_the_email(admin_user):
    from apps.core.models import ApiToken
    from rest_framework.test import APIClient

    token = ApiToken.objects.create(user=admin_user, name="scheduler")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + token.key)
    response = client.post(
        reverse("api:thresholds-evaluate"),
        data=json.dumps({"no_email": True}),
        content_type="application/json",
    )
    assert response.status_code == 200