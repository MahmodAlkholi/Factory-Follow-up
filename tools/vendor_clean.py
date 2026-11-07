"""
Clean the vendored front-end assets in ``static/vendor/``.

Bootstrap and Chart.js ship a ``//# sourceMappingURL=...`` comment that points
at a ``.map`` file we do not vendor.  Django's
``ManifestStaticFilesStorage`` follows that reference while collecting the
static files and aborts the whole build when the target is missing::

    whitenoise.storage.MissingFileError: The file
    'vendor/bootstrap.bundle.min.js.map' could not be found

Stripping the comment removes the broken reference (the browser would only
ever fetch it with the devtools open) and keeps the production static build
working.

    python tools/vendor_clean.py           # check only
    python tools/vendor_clean.py --fix     # rewrite the files
"""

import argparse
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VENDOR_DIR = BASE_DIR / "static" / "vendor"

# ``//# sourceMappingURL=whatever.map`` at the end of a file.
SOURCE_MAP_RE = re.compile(rb"[ \t]*//[#@][ \t]*sourceMappingURL=[^\r\n]*(\r?\n)?")
# ``/*# sourceMappingURL=whatever.map */`` inside a CSS file.
CSS_SOURCE_MAP_RE = re.compile(rb"/\*[#@][ \t]*sourceMappingURL=[^*]*\*/[ \t]*")


def clean(path: Path) -> bool:
    """Return True when the file was changed."""
    original = path.read_bytes()
    cleaned = CSS_SOURCE_MAP_RE.sub(b"", SOURCE_MAP_RE.sub(b"", original))
    if cleaned == original:
        return False
    path.write_bytes(cleaned)
    return True


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Rewrite the files instead of only reporting.")
    args = parser.parse_args(argv[1:])

    if not VENDOR_DIR.exists():
        print(f"No vendor directory at {VENDOR_DIR}")
        return 1

    changed = []
    for path in sorted(VENDOR_DIR.iterdir()):
        if not path.is_file() or path.suffix not in {".js", ".css"}:
            continue
        if args.fix:
            if clean(path):
                changed.append(path.name)
        else:
            if SOURCE_MAP_RE.search(path.read_bytes()) or CSS_SOURCE_MAP_RE.search(path.read_bytes()):
                changed.append(path.name)

    if not changed:
        print("Nothing to do - no source map references left.")
        return 0

    for name in changed:
        print(f"{'fixed  ' if args.fix else 'stale  '} {name}")

    if not args.fix:
        print("\nRun with --fix to remove them.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
