"""Colour themes, fonts, icon glyphs and the application stylesheet."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPixmap

from ..settings import THEME_KEYS

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Palette:
    key: str
    name: str
    dark: bool
    bg_top: str
    bg_bottom: str
    border: str
    text: str
    heading: str  # the big Korean word
    muted: str
    faint: str
    accent: str
    accent_text: str  # text on accent-tinted buttons
    menu_bg: str


PALETTES = {
    p.key: p
    for p in (
        Palette("midnight", "Midnight Lavender", True, "#1C1A3A", "#101224", "#4E437F", "#EEEAFB", "#F6F3FF",
                "#A9A4C9", "#7C779E", "#A78BFA", "#DDD6FE", "#1A1C35"),
        Palette("graphite", "Graphite", True, "#2A2C30", "#1C1D20", "#3D4046", "#E8E9EB", "#FFFFFF",
                "#A3A7AE", "#767A82", "#5EEAD4", "#99F6E4", "#232529"),
        Palette("ocean", "Seoul Night", True, "#10233A", "#0A1626", "#24476B", "#E3EDF7", "#F5F9FD",
                "#9DB3C9", "#6C849C", "#60A5FA", "#BFDBFE", "#0E1E31"),
        Palette("forest", "Forest", True, "#1A2B22", "#101B16", "#33553F", "#E6EFE9", "#F3F8F4",
                "#9DB5A8", "#6E877A", "#E2B34B", "#F2D28B", "#14221B"),
        Palette("paper", "Paper", False, "#FCFAF6", "#F3EEE7", "#DDD3C6", "#2B2622", "#16120F",
                "#6B625A", "#9A9087", "#C2410C", "#9A3412", "#FFFFFF"),
        Palette("hanji", "Hanji", False, "#F5EDDF", "#EADFCC", "#CDBB9C", "#2E2A24", "#1F2A44",
                "#6E6556", "#998D78", "#B23A3A", "#8E2C2C", "#FAF5EA"),
    )
}
assert tuple(PALETTES) == THEME_KEYS, "settings.THEME_KEYS must list the same themes"


def palette(key: str) -> Palette:
    return PALETTES.get(key, PALETTES["paper"])


def rgba(hex_color: str, alpha: int) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def card_colors(p: Palette) -> tuple[QColor, QColor, QColor]:
    """Gradient top, gradient bottom and border colours for painting the card."""
    top, bottom, border = QColor(p.bg_top), QColor(p.bg_bottom), QColor(p.border)
    top.setAlpha(252)
    bottom.setAlpha(252)
    return top, bottom, border


# Pretendard and Noto Nastaliq Urdu ship in resources/fonts (SIL Open Font
# License), so these first choices are always available; the rest are fallbacks.
KOREAN_FONTS = ("Pretendard", "Noto Sans KR", "Malgun Gothic")
URDU_FONTS = ("Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", "Urdu Typesetting", "Noto Naskh Arabic", "Segoe UI")
UI_FONTS = ("Pretendard", "Segoe UI Variable Text", "Segoe UI")
# Korean Hanja are traditional characters; Microsoft JhengHei ships with Windows.
HANJA_FONTS = ("Noto Serif KR", "Noto Serif CJK KR", "Noto Sans KR", "Microsoft JhengHei")
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

# Segoe Fluent Icons / MDL2 code points, with plain-text fallbacks.
_GLYPHS = {
    "prev": ("", "‹"),
    "next": ("", "›"),
    "pause": ("", "II"),
    "play": ("", "▶"),
    "hide": ("", "–"),
    "more": ("", "⋯"),
    "compact": ("", "▭"),
    "expand": ("", "▢"),
}


@dataclass(frozen=True)
class Fonts:
    korean: str
    urdu: str
    ui: str
    hanja: str
    icons: str | None

    def glyph(self, name: str) -> str:
        fluent, fallback = _GLYPHS[name]
        return fluent if self.icons else fallback


def _first_available(candidates: tuple[str, ...], installed: set[str]) -> str | None:
    lowered = {f.lower(): f for f in installed}
    for name in candidates:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def load_bundled_fonts(folder: Path) -> list[str]:
    """Register the app's own font files with Qt (no system install needed)."""
    loaded: list[str] = []
    for file in sorted(folder.glob("*.[ot]tf")):
        font_id = QFontDatabase.addApplicationFont(str(file))
        if font_id == -1:
            log.warning("Could not load bundled font %s", file.name)
        else:
            loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    return sorted(set(loaded))


def detect_fonts() -> Fonts:
    installed = set(QFontDatabase.families())
    return Fonts(
        korean=_first_available(KOREAN_FONTS, installed) or "Malgun Gothic",
        urdu=_first_available(URDU_FONTS, installed) or "Segoe UI",
        ui=_first_available(UI_FONTS, installed) or "Segoe UI",
        hanja=_first_available(HANJA_FONTS, installed) or "Microsoft JhengHei",
        icons=_first_available(ICON_FONTS, installed),
    )


# Unknown / Difficult / Known - the same hues in every theme so they stay recognisable.
RATE_COLORS = ("#E5484D", "#F5A524", "#30A46C")
_RATE_TEXT_DARK = ("#FF9DA0", "#FFCB7A", "#74D9A6")
_RATE_TEXT_LIGHT = ("#B4232A", "#8A5300", "#1B6E45")


def stylesheet(fonts: Fonts, p: Palette) -> str:
    icon_family = f'"{fonts.icons}"' if fonts.icons else f'"{fonts.ui}"'
    rate_text = _RATE_TEXT_DARK if p.dark else _RATE_TEXT_LIGHT
    return f"""
    QWidget {{
        color: {p.text}; font-family: "{fonts.ui}"; font-size: 10pt;
        selection-background-color: {rgba(p.accent, 90)}; selection-color: {p.heading};
    }}

    QLabel#category {{ color: {p.faint}; font-size: 8pt; letter-spacing: 0.5px; }}
    QLabel#korean {{ font-family: "{fonts.korean}"; font-size: 24pt; font-weight: 600; color: {p.heading}; }}
    QLabel#korean[compact="true"] {{ font-size: 19pt; }}
    QLabel#hanja {{ font-family: "{fonts.hanja}"; font-size: 13pt; color: {p.muted}; padding-bottom: 4px; }}
    QLabel#hanja[compact="true"] {{ font-size: 11pt; padding-bottom: 3px; }}
    QLabel#romanization {{ color: {p.accent}; font-size: 9.5pt; }}
    QLabel#meaningEn {{ font-size: 11.5pt; color: {p.text}; }}
    QLabel#meaningUr {{ font-family: "{fonts.urdu}"; font-size: 13pt; color: {p.text}; }}
    QLabel#exampleKo {{ font-family: "{fonts.korean}"; font-size: 11pt; color: {p.text}; }}
    QLabel#exampleEn {{ color: {p.muted}; font-size: 9.5pt; font-style: italic; }}
    QLabel#exampleUr {{ font-family: "{fonts.urdu}"; color: {p.muted}; font-size: 11pt; }}
    QLabel#notes {{ color: {p.faint}; font-size: 8.5pt; }}
    QLabel#status {{ color: {p.faint}; font-size: 8pt; }}

    QFrame#divider {{ background: {rgba(p.text, 24)}; max-height: 1px; min-height: 1px; border: none; }}

    QToolButton#iconButton {{
        font-family: {icon_family}; font-size: 10pt; color: {p.muted};
        background: transparent; border: none; border-radius: 7px; padding: 5px;
        min-width: 18px; min-height: 18px;
    }}
    QToolButton#iconButton:hover {{ background: {rgba(p.accent, 38)}; color: {p.text}; }}
    QToolButton#iconButton:pressed {{ background: {rgba(p.accent, 64)}; }}
    QToolButton#iconButton:disabled {{ color: {rgba(p.muted, 80)}; }}
    QToolButton#iconButton::menu-indicator {{ image: none; width: 0; }}

    QPushButton#revealButton {{
        background: {rgba(p.accent, 40)}; color: {p.accent_text};
        border: 1px solid {rgba(p.accent, 110)}; border-radius: 10px;
        padding: 6px 14px; font-size: 9.5pt;
    }}
    QPushButton#revealButton:hover {{ background: {rgba(p.accent, 72)}; }}

    QPushButton#rateUnknown, QPushButton#rateDifficult, QPushButton#rateKnown {{
        border-radius: 9px; padding: 5px 4px; font-size: 9pt; font-weight: 500;
    }}
    QPushButton#rateUnknown {{ background: {rgba(RATE_COLORS[0], 34)}; color: {rate_text[0]}; border: 1px solid {rgba(RATE_COLORS[0], 90)}; }}
    QPushButton#rateDifficult {{ background: {rgba(RATE_COLORS[1], 34)}; color: {rate_text[1]}; border: 1px solid {rgba(RATE_COLORS[1], 90)}; }}
    QPushButton#rateKnown {{ background: {rgba(RATE_COLORS[2], 34)}; color: {rate_text[2]}; border: 1px solid {rgba(RATE_COLORS[2], 90)}; }}
    QPushButton#rateUnknown:hover {{ background: {rgba(RATE_COLORS[0], 70)}; }}
    QPushButton#rateDifficult:hover {{ background: {rgba(RATE_COLORS[1], 70)}; }}
    QPushButton#rateKnown:hover {{ background: {rgba(RATE_COLORS[2], 70)}; }}

    QLabel#goal {{ color: {p.muted}; font-size: 8pt; padding-right: 6px; }}
    QLabel#goal[done="true"] {{ color: {p.accent}; font-weight: 600; }}

    QDialog#statsDialog {{ background: {p.bg_bottom}; }}
    QLabel#statValue {{ font-size: 18pt; font-weight: 600; color: {p.heading}; }}
    QLabel#statLabel {{ color: {p.muted}; font-size: 8.5pt; }}
    QLabel#statTitle {{ color: {p.faint}; font-size: 8pt; letter-spacing: 0.5px; }}

    QProgressBar#countdown {{ background: {rgba(p.text, 20)}; border: none; border-radius: 1px; }}
    QProgressBar#countdown::chunk {{ background: {p.accent}; border-radius: 1px; }}
    QProgressBar#countdown[paused="true"]::chunk {{ background: {rgba(p.accent, 80)}; }}

    QMenu {{ background: {p.menu_bg}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px 6px 22px; border-radius: 5px; color: {p.text}; }}
    QMenu::item:selected {{ background: {rgba(p.accent, 70)}; }}
    QMenu::item:disabled {{ color: {p.faint}; }}
    QMenu::separator {{ height: 1px; background: {rgba(p.text, 26)}; margin: 4px 8px; }}
    QMenu::indicator {{ width: 12px; height: 12px; left: 6px; }}

    QToolTip {{ background: {p.menu_bg}; color: {p.text}; border: 1px solid {p.border}; padding: 4px 6px; }}
    """


def app_icon(korean_font: str) -> QIcon:
    """A lavender rounded square with '한', drawn in code so no image files are needed."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0.0, QColor("#A78BFA"))
        gradient.setColorAt(1.0, QColor("#6D28D9"))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(0, 0, size, size)
        painter.drawRoundedRect(rect, size * 0.24, size * 0.24)
        font = QFont(korean_font)
        font.setPixelSize(max(9, int(size * 0.62)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "한")
        painter.end()
        icon.addPixmap(pixmap)
    return icon
