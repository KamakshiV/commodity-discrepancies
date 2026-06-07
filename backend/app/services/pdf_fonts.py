"""Register Noto Sans fonts for PDF reports (matches Risk Analysis Report sample)."""

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

NOTO_REGULAR = "NotoSans"
NOTO_BOLD = "NotoSans-Bold"
NOTO_ITALIC = "NotoSans-Italic"

_registered = False


def register_pdf_fonts() -> None:
    global _registered
    if _registered:
        return

    pdfmetrics.registerFont(
        TTFont(NOTO_REGULAR, str(FONTS_DIR / "NotoSans-Regular.ttf"))
    )
    pdfmetrics.registerFont(
        TTFont(NOTO_BOLD, str(FONTS_DIR / "NotoSans-Bold.ttf"))
    )
    pdfmetrics.registerFont(
        TTFont(NOTO_ITALIC, str(FONTS_DIR / "NotoSans-Italic.ttf"))
    )
    pdfmetrics.registerFontFamily(
        NOTO_REGULAR,
        normal=NOTO_REGULAR,
        bold=NOTO_BOLD,
        italic=NOTO_ITALIC,
        boldItalic=NOTO_BOLD,
    )
    _registered = True
