"""
Portable translation tooling.

GNU gettext (``xgettext`` / ``msgfmt``) is not available on every machine -
and certainly not on a stock Windows box - so this script does the same job
with nothing but the standard library plus ``polib``.

    python tools/i18n.py extract     # collect every translatable string
    python tools/i18n.py compile     # write the .mo files
    python tools/i18n.py stats       # how many strings are translated

The catalogue lives in ``locale/<lang>/LC_MESSAGES/django.po``.
"""

import os
import re
import sys
from pathlib import Path

import polib

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALE_DIR = BASE_DIR / "locale"
LANGUAGES = ["ar"]

SOURCE_DIRS = ["apps", "factory_dashboard", "templates", "tools"]
SOURCE_SUFFIXES = (".py", ".html", ".txt")

# ``_("text")`` / ``gettext("text")`` / ``gettext_lazy("text")``
PY_RE = re.compile(
    r"(?:gettext_lazy|gettext|ugettext|_)\(\s*(?P<quote>[\"'])(?P<text>(?:\\.|(?!(?P=quote)).)*)(?P=quote)",
    re.S,
)
# ``{% trans "text" %}``
TPL_RE = re.compile(
    r"\{%\s*trans(?:late)?\s+(?P<quote>[\"'])(?P<text>(?:\\.|(?!(?P=quote)).)*)(?P=quote)\s*%\}",
    re.S,
)
# ``{% blocktrans %}...{% endblocktrans %}``
BLOCK_RE = re.compile(
    r"\{%\s*blocktrans(?:late)?(?P<args>[^%]*)%\}(?P<text>.*?)\{%\s*endblocktrans(?:late)?\s*%\}",
    re.S,
)
# ``{% blocktrans with a=b %}`` -> ``%(a)s``
BLOCK_WITH_RE = re.compile(r"with\s+(?P<vars>[\w\s=,]+?)\s*$")


def _unescape(text):
    return (
        text.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\'", "'")
    )


def _blocktrans_msgid(text, args):
    body = text.strip()
    variables = []
    if args:
        match = BLOCK_WITH_RE.search(args.strip())
        if match:
            for pair in match.group("vars").split(","):
                if "=" in pair:
                    variables.append(pair.split("=")[0].strip())
    for name in variables:
        body = body.replace("{{%s}}" % name, "%%(%s)s" % name)
    return body


def extract_from_file(path):
    """Return the list of msgids found in one file."""
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    found = []
    if path.suffix == ".py":
        for match in PY_RE.finditer(content):
            found.append(_unescape(match.group("text")))
    elif path.suffix == ".html":
        for match in TPL_RE.finditer(content):
            found.append(_unescape(match.group("text")))
        for match in BLOCK_RE.finditer(content):
            found.append(_blocktrans_msgid(match.group("text"), match.group("args") or ""))
    return found


def collect_strings():
    strings = []
    for folder in SOURCE_DIRS:
        root = BASE_DIR / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in SOURCE_SUFFIXES:
                strings.extend(extract_from_file(path))
    # Preserve the order but drop duplicates.
    seen = set()
    unique = []
    for item in strings:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def po_path(language):
    return LOCALE_DIR / language / "LC_MESSAGES" / "django.po"


def do_extract(language="ar"):
    """Merge the found strings into the catalogue, keeping existing translations."""
    path = po_path(language)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        catalogue = polib.pofile(str(path))
    else:
        catalogue = polib.POFile()

    known = {entry.msgid for entry in catalogue}
    added = 0
    for msgid in collect_strings():
        if msgid not in known:
            catalogue.append(polib.POEntry(msgid=msgid, msgstr=""))
            known.add(msgid)
            added += 1

    catalogue.metadata = {
        "Project-Id-Version": "Factory Follow-up Dashboard",
        "Report-Msgid-Bugs-To": "",
        "POT-Creation-Date": "",
        "PO-Revision-Date": "",
        "Last-Translator": "",
        "Language-Team": "",
        "Language": language,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Plural-Forms": "nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);",
    }
    catalogue.save(str(path))
    print(f"[{language}] catalogue: {path}")
    print(f"[{language}] new strings: {added}, total: {len(catalogue)}")
    return 0


def do_compile(language="ar"):
    path = po_path(language)
    if not path.exists():
        print(f"No catalogue at {path}")
        return 1
    catalogue = polib.pofile(str(path))
    catalogue.save_as_mofile(str(path.with_suffix(".mo")))
    translated = sum(1 for entry in catalogue if entry.msgstr)
    print(f"[{language}] compiled {len(catalogue)} strings ({translated} translated) -> {path.with_suffix('.mo')}")
    return 0


def do_stats(language="ar"):
    path = po_path(language)
    if not path.exists():
        print("No catalogue yet - run: python tools/i18n.py extract")
        return 1
    catalogue = polib.pofile(str(path))
    untranslated = [entry.msgid for entry in catalogue if not entry.msgstr]
    print(f"[{language}] {len(catalogue)} strings, {len(untranslated)} untranslated")
    for msgid in untranslated:
        print("   -", msgid.replace("\n", " ")[:90])
    return 0


def main(argv):
    command = argv[1] if len(argv) > 1 else "extract"
    language = argv[2] if len(argv) > 2 else "ar"
    actions = {"extract": do_extract, "compile": do_compile, "stats": do_stats}
    action = actions.get(command)
    if action is None:
        print(__doc__)
        return 2
    return action(language)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
