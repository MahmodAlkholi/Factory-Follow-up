"""Template helpers."""

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """``{{ mydict|get_item:key }}`` - dict lookup from a template."""
    if dictionary is None:
        return None
    try:
        return dictionary.get(key)
    except AttributeError:
        try:
            return dictionary[key]
        except (KeyError, IndexError, TypeError):
            return None


@register.filter
def percentage(value, total):
    try:
        total = float(total)
        value = float(value)
        if not total:
            return 0
        return round(value * 100 / total, 1)
    except (TypeError, ValueError):
        return 0


@register.filter
def severity_class(value):
    mapping = {
        "critical": "badge-critical",
        "warning": "badge-warning",
        "info": "badge-info",
        "open": "badge-critical",
        "acknowledged": "badge-warning",
        "resolved": "badge-success",
    }
    return mapping.get(str(value).lower(), "badge-info")


@register.filter
def status_class(value):
    mapping = {
        "ok": "badge-success",
        "low": "badge-warning",
        "out": "badge-critical",
        "over": "badge-info",
    }
    return mapping.get(str(value).lower(), "badge-info")


@register.filter
def tone_class(value):
    mapping = {
        "primary": "kpi-primary",
        "success": "kpi-success",
        "warning": "kpi-warning",
        "danger": "kpi-danger",
        "info": "kpi-info",
    }
    return mapping.get(str(value).lower(), "kpi-primary")


@register.filter
def to_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return value
    return [value]


@register.simple_tag
def query_with(base: str, **kwargs):
    """Rebuild a query string with some parameters replaced."""
    from urllib.parse import urlencode

    params = {key: value for key, value in kwargs.items() if value not in (None, "")}
    flat = urlencode(params)
    if not flat:
        return base
    return f"{base}?{flat}"


@register.simple_tag
def progress_bar(value, maximum=100, tone="primary"):
    try:
        value = float(value)
        maximum = float(maximum) or 1
    except (TypeError, ValueError):
        value, maximum = 0, 1
    percent = max(0.0, min(value * 100 / maximum, 100.0))
    return mark_safe(
        f'<div class="progress" role="progressbar" aria-valuenow="{percent:.0f}" '
        f'aria-valuemin="0" aria-valuemax="100">'
        f'<div class="progress-bar bg-{tone}" style="width:{percent:.1f}%"></div></div>'
    )
