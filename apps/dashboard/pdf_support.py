"""
Arabic aware PDF helpers.

reportlab does not shape Arabic by itself, so we (1) register a font that
contains the Arabic presentation forms and (2) run the text through
``arabic_reshaper`` + ``python-bidi`` before drawing it.
"""

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_FONT_CACHE = {}


def _candidate_font_paths():
    """Fonts that contain BOTH Latin and the Arabic presentation forms."""
    candidates = []
    configured = getattr(settings, "PDF_FONT_PATH", "")
    if configured:
        candidates.append(Path(configured))
    base = Path(settings.BASE_DIR)
    fonts_dir = base / "assets" / "fonts"
    # DejaVuSans covers Latin *and* Arabic presentation forms -> ideal for a
    # mixed Arabic / English report.
    for name in ("DejaVuSans.ttf",):
        candidates.append(fonts_dir / name)
    if fonts_dir.exists():
        for path in sorted(fonts_dir.glob("*.ttf")):
            if path not in candidates:
                candidates.append(path)
    candidates += [
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"),
    ]
    return candidates


def _covers(font, codepoints):
    try:
        char_to_glyph = font.face.charToGlyph
    except AttributeError:  # pragma: no cover - defensive
        return False
    return all(codepoint in char_to_glyph for codepoint in codepoints)


def register_font():
    """
    Register the best available font.

    Returns ``(font_name, supports_arabic)``. ``font_name`` is always a font
    that reportlab knows, so the caller never has to fail.
    """
    if "result" in _FONT_CACHE:
        return _FONT_CACHE["result"]

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    result = ("Helvetica", False)
    for path in _candidate_font_paths():
        try:
            if not path or not path.exists():
                continue
            name = "DashboardArabic"
            font = TTFont(name, str(path))
            pdfmetrics.registerFont(font)
            # 0x41 = "A", 0x30 = "0", 0xFEDF = Arabic final lam (presentation form)
            latin = _covers(font, (0x41, 0x30))
            arabic = _covers(font, (0xFEDF,))
            result = (name, arabic)
            if latin and arabic:
                break
        except Exception:  # pragma: no cover - depends on the local fonts
            logger.debug("Could not register font %s", path)
            continue

    _FONT_CACHE["result"] = result
    return result


def shape(text):
    """Reshape and reorder Arabic text for reportlab."""
    if text is None:
        return ""
    value = str(text)
    if not value.strip():
        return value
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(value))
    except Exception:  # pragma: no cover - reshaping is best effort
        return value


def prepare(text, supports_arabic=True):
    """Prepare any string for drawing (Arabic gets reshaped)."""
    if supports_arabic:
        return shape(text)
    return str(text or "")
