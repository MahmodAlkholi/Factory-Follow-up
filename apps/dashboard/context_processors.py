"""Template context available on every page."""

from django.conf import settings
from django.urls import reverse
from django.utils import translation

from apps.core.permissions import (
    can_enter_data,
    can_export,
    can_manage_structure,
    roles_of,
)


def dashboard_context(request):
    user = getattr(request, "user", None)
    language = translation.get_language() or settings.LANGUAGE_CODE
    nav = [
        {"label": "Overview", "url_name": "dashboard:overview", "icon": "grid"},
        {"label": "Production", "url_name": "dashboard:production", "icon": "chart"},
        {"label": "Downtime", "url_name": "dashboard:downtime", "icon": "pause"},
        {"label": "Quality", "url_name": "dashboard:quality", "icon": "shield"},
        {"label": "Inventory", "url_name": "dashboard:inventory", "icon": "box"},
        {"label": "Reports", "url_name": "dashboard:reports", "icon": "file"},
    ]
    return {
        "APP_NAME": "Factory Follow-up",
        "nav_items": nav,
        "user_roles": sorted(roles_of(user)) if user and user.is_authenticated else [],
        "can_enter_data": can_enter_data(user),
        "can_export": can_export(user),
        "can_manage": can_manage_structure(user),
        "current_language": language,
        "text_direction": "rtl" if language in settings.LANGUAGES_BIDI else "ltr",
        "is_rtl": language in settings.LANGUAGES_BIDI,
        "refresh_seconds": settings.DASHBOARD_REFRESH_SECONDS,
        "reverse_noop": reverse,
    }
