"""A single, predictable error envelope for every API response."""

from django.utils.translation import gettext as _
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and set(data.keys()) == {"detail"}:
        payload = {
            "error": {
                "code": response.status_code,
                "message": str(data["detail"]),
            }
        }
    else:
        payload = {
            "error": {
                "code": response.status_code,
                "message": _("Validation failed"),
                "fields": data,
            }
        }
    response.data = payload
    return response
