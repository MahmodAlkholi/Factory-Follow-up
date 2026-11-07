"""
Role based access control.

The four roles are plain Django groups, created automatically by the
``ensure_groups`` command / seed script:

    Admin       - full control (users, factories, lines, settings)
    Manager     - sees everything, exports reports
    Supervisor  - sees and enters data for his own line / shift
    Operator    - enters data only (production, downtime, defects)

Two important rules are enforced here:

1. A role check is never enough - an object-level check is added so a
   Supervisor can never read another line's data (see ``scope_for_user``).
2. Writes that would create a *higher* authority (changing ``role``,
   ``is_superuser``, ...) are only allowed for Admins.
"""

from functools import wraps

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

ROLE_ADMIN = "Admin"
ROLE_MANAGER = "Manager"
ROLE_SUPERVISOR = "Supervisor"
ROLE_OPERATOR = "Operator"

ALL_ROLES = [ROLE_ADMIN, ROLE_MANAGER, ROLE_SUPERVISOR, ROLE_OPERATOR]

# Which roles may see the whole plant.
GLOBAL_ROLES = {ROLE_ADMIN, ROLE_MANAGER}


def ensure_groups():
    """Create the four role groups if they do not exist yet."""
    created = []
    for role in ALL_ROLES:
        group, was_created = Group.objects.get_or_create(name=role)
        if was_created:
            created.append(group)
    return created


def groups_of(user):
    if not user or not user.is_authenticated:
        return set()
    return {group.name for group in user.groups.all()}


def roles_of(user):
    """Return the set of role names held by ``user``."""
    if not user or not user.is_authenticated:
        return set()
    roles = groups_of(user)
    if user.is_superuser:
        roles.add(ROLE_ADMIN)
    return roles


def has_role(user, *roles) -> bool:
    return bool(roles_of(user) & set(roles))


def is_admin(user) -> bool:
    return has_role(user, ROLE_ADMIN)


def is_manager(user) -> bool:
    return has_role(user, ROLE_MANAGER, ROLE_ADMIN)


def is_supervisor(user) -> bool:
    return has_role(user, ROLE_SUPERVISOR)


def can_view_dashboard(user) -> bool:
    """Everyone who is signed in may open the dashboards."""
    return bool(user and user.is_authenticated)


def can_enter_data(user) -> bool:
    """Supervisors and operators type data in; managers/admins may too."""
    return has_role(user, ROLE_SUPERVISOR, ROLE_OPERATOR, ROLE_MANAGER, ROLE_ADMIN)


def can_export(user) -> bool:
    """Only managers and admins may export reports."""
    return has_role(user, ROLE_MANAGER, ROLE_ADMIN)


def can_manage_structure(user) -> bool:
    """Only admins manage factories, lines, machines and thresholds."""
    return is_admin(user)


def scope_for_user(user):
    """
    Return the data scope of ``user``.

    ``{"factory": id|None, "line": id|None, "shift": id|None}``
    ``None`` means "no restriction on this level".
    """
    if not user or not user.is_authenticated:
        return {"factory": None, "line": None, "shift": None}
    if has_role(user, ROLE_ADMIN, ROLE_MANAGER):
        return {"factory": None, "line": None, "shift": None}
    profile = getattr(user, "profile", None)
    if profile is None:
        return {"factory": None, "line": None, "shift": None}
    line = profile.production_line_id
    factory = profile.factory_id
    if line and not factory:
        from .models import ProductionLine

        line_obj = ProductionLine.objects.filter(id=line).first()
        factory = line_obj.factory_id if line_obj else None
    return {"factory": factory, "line": line, "shift": profile.shift_id}


def apply_scope(queryset, user, field="production_line"):
    """
    Restrict ``queryset`` to the user's scope.

    ``field`` is the path to the line on the model, e.g. ``production_line``.
    For models that carry a direct ``production_line`` FK this is enough;
    inventory items are handled separately.
    """
    scope = scope_for_user(user)
    if scope.get("factory"):
        queryset = queryset.filter(**{f"{field}__factory_id": scope["factory"]})
    if scope.get("line"):
        queryset = queryset.filter(**{f"{field}_id": scope["line"]})
    if scope.get("shift"):
        queryset = queryset.filter(shift_id=scope["shift"])
    return queryset


def require_roles(*roles):
    """View decorator: only users holding one of ``roles`` may enter."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.shortcuts import redirect
                from django.conf import settings

                return redirect(f"{settings.LOGIN_URL}?next={request.path}")
            if not has_role(request.user, *roles):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
