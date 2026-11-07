"""Token authentication bound to the project's named :class:`ApiToken` model."""

from rest_framework.authentication import TokenAuthentication

from apps.core.models import ApiToken


class ApiTokenAuthentication(TokenAuthentication):
    """Same behaviour as DRF's, but it reads ``apps.core.models.ApiToken``."""

    model = ApiToken
