"""Dev helper: render the Arabic PDF export to disk for inspection."""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "factory_dashboard.settings")
django.setup()

from django.test.utils import setup_test_environment  # noqa: E402

setup_test_environment()

from django.utils import translation  # noqa: E402

from apps.core.services.filters import FilterParams  # noqa: E402
from apps.dashboard import exports  # noqa: E402


def main():
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "_preview")
    os.makedirs(out_dir, exist_ok=True)
    filters = FilterParams()
    for language in ("en", "ar"):
        with translation.override(language):
            buffer = exports.export_pdf(filters)
        target = os.path.join(out_dir, f"report_{language}.pdf")
        with open(target, "wb") as handle:
            handle.write(buffer.getvalue())
        print(f"{target} ({len(buffer.getvalue())} bytes)")


if __name__ == "__main__":
    main()
