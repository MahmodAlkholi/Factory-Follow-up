"""
Evaluate every active threshold once.

    python manage.py evaluate_thresholds
    python manage.py evaluate_thresholds --no-email

On a platform that cannot keep a long-running Celery beat alive (a container
service, a cron job, a scheduled task), this command replaces the beat: run it
every minute from the platform's scheduler and the alerts keep working.
"""

from django.core.management.base import BaseCommand

from apps.core.services.alerts import evaluate_thresholds


class Command(BaseCommand):
    help = "Evaluate every active threshold once and raise the alerts that broke."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-email",
            action="store_true",
            help="Raise the alerts but do not send the notification mails.",
        )

    def handle(self, *args, **options):
        created = evaluate_thresholds(send_email=not options["no_email"])
        for alert in created:
            self.stdout.write("  %-8s %s" % (alert.get_severity_display(), alert.message))
        self.stdout.write(self.style.SUCCESS("%d alert(s) raised." % len(created)))
