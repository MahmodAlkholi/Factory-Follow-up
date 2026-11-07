"""
Create (or re-create) an API token for a machine / gateway.

    python manage.py create_api_token --username operator --name "PLC line A"

The token is printed once - it is shown in the admin under
"Authtoken > Tokens" as well.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import ApiToken


class Command(BaseCommand):
    help = "Create or refresh a DRF API token for the ingestion endpoints."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Owner of the token.")
        parser.add_argument("--name", default="ingestion", help="Human readable name.")
        parser.add_argument("--rotate", action="store_true", help="Delete an existing token first.")

    def handle(self, *args, **options):
        username = options["username"]
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"No user named '{username}'.")

        existing = ApiToken.objects.filter(user=user, name=options["name"]).first()
        if existing:
            if not options["rotate"]:
                self.stdout.write(existing.key)
                return
            existing.delete()
            token = ApiToken.objects.create(user=user, name=options["name"])
            self.stdout.write(self.style.SUCCESS(token.key))
            return

        token = ApiToken.objects.create(user=user, name=options["name"])
        self.stdout.write(self.style.SUCCESS(token.key))
