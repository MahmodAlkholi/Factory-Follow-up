"""Render the authenticated pages to static HTML for visual QA (dev helper)."""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "factory_dashboard.settings")
django.setup()

from django.test.utils import setup_test_environment  # noqa: E402

setup_test_environment()

from django.test import Client  # noqa: E402
from django.utils import translation  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "_preview")

PAGES = {
    "overview": "/",
    "production": "/production/",
    "downtime": "/downtime/",
    "quality": "/quality/",
    "inventory": "/inventory/",
    "reports": "/reports/",
    "data-entry": "/data-entry/",
    "import": "/import/",
    "alerts": "/alerts/",
    "thresholds": "/thresholds/",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    client = Client()
    if not client.login(username="admin", password="factory123"):
        print("Could not log in as admin")
        return 1
    stamp = str(int(os.path.getmtime(os.path.join(os.path.dirname(__file__), "..", "static", "js", "dashboard.js"))))
    for language in ("en", "ar"):
        for name, path in PAGES.items():
            # LocaleMiddleware picks the language from the request, so the
            # Accept-Language header is what actually switches the page.
            response = client.get(path, HTTP_ACCEPT_LANGUAGE=language)
            suffix = "" if language == "en" else "_ar"
            target = os.path.join(OUT, f"{name}{suffix}.html")
            html = response.content.decode("utf-8")
            # Cache-bust the two files we iterate on so the browser really
            # reloads them instead of serving a stale copy.
            html = html.replace(
                'src="/static/js/dashboard.js"',
                f'src="/static/js/dashboard.js?v={stamp}"',
            )
            html = html.replace(
                'href="/static/css/app.css"', f'href="/static/css/app.css?v={stamp}"'
            )
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(html)
            print(f"{target} ({response.status_code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
