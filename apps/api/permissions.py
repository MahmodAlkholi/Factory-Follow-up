"""API permissions.

The catalogue endpoints are read-only for everybody and writable for Admins.
The ingestion endpoints are token only and never accept session auth, so a
browser session can not post machine data.
"""

from rest_framework import permissions

from apps.core.permissions import is_admin


class IsAdminOrReadOnly(permissions.BasePermission):
    """Safe methods for everybody, writes for Admins only."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return is_admin(request.user)

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return is_admin(request.user)


class IsManagerOrReadOnly(permissions.BasePermission):
    """Managers and Admins may write; everybody else may read."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        from apps.core.permissions import can_manage_structure

        return can_manage_structure(request.user)


class CanEnterData(permissions.BasePermission):
    """Supervisors, operators, managers and admins may create records."""

    def has_permission(self, request, view):
        from apps.core.permissions import can_enter_data

        return bool(request.user and request.user.is_authenticated and can_enter_data(request.user))


class IsTokenAuthenticated(permissions.BasePermission):
    """Only a DRF token may be used - session / JWT login is rejected."""

    def has_permission(self, request, view):
        from rest_framework.authtoken.models import Token

        return bool(
            request.user
            and request.user.is_authenticated
            and request.auth
            and isinstance(request.auth, Token)
        )
