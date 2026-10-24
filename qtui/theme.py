"""Theme for the Qt UI: palettes (from the toolkit-free ui_theme_core), sizes / spacing / typography, fonts, the application QSS and live switching.

The palette tokens are exactly the ones the Tk theme uses (`ui_theme_core.LIGHT` / `DARK`), so both toolkits show the same colours and the same
`CALSUITE_THEME` / saved 'Help > Appearance' choice (`ui_theme_core.theme_choice()`).  Everything else in qtui reads colours through `tokens()` / `color()`
at paint time and sizes through `M`; nothing hard-codes a colour or a pixel size.

    theme.set_theme('dark')                  # live: re-styles every open window, emits theme.manager().changed('dark')
    theme.manager().changed.connect(slot)    # custom-painted widgets repaint here
    theme.tokens()['good_bg']                # str '#rrggbb'

Sizes are in Qt device-independent pixels: Qt 6 scales them for the screen (see app.create_app for the HiDPI policy), so core `px()` is NOT used here.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu

import ui_theme_core as core

# ----------------------------------------------------------------------------------------------------------------------------------------------------
# tokens
# ----------------------------------------------------------------------------------------------------------------------------------------------------
# Every ui_theme_core palette key the Qt theme reads.  tests/test_qtui_theme.py checks that REQUIRED + TK_ONLY covers every key of both palettes, so adding
# a key to ui_theme_core forces a decision here.
REQUIRED_KEYS = (
    'bg', 'card', 'bar', 'border', 'border_strong', 'text', 'muted', 'faint', 'primary', 'primary_hi', 'primary_lo', 'select', 'row_alt', 'head', 'head_hi',
    'good', 'good_bg', 'good_dot', 'bad', 'bad_bg', 'bad_dot', 'warn', 'warn_bg', 'warn_dot', 'info', 'info_bg', 'info_dot', 'neutral', 'neutral_bg',
    'neutral_dot', 'field', 'table', 'on_primary', 'primary_off', 'btn', 'btn_hi', 'btn_lo', 'btn_off', 'danger', 'danger_hi', 'danger_lo', 'danger_off',
    'trough', 'scroll', 'scroll_hi', 'scroll_lo', 'tip', 'row_even', 'row_pass', 'row_pass_fg', 'row_fail', 'row_fail_fg', 'row_warn', 'row_warn_fg',
    'accent_line',
)
# Tk-only decorations with no Qt counterpart (Qt styles these through the tokens above)
TK_ONLY = ('navy', 'navy_hi', 'combo_btn', 'combo_btn_hi')
# Mike's scope decision: the Qt UI ships DARK ONLY for now.  The light palette, the QSS and the switching are all still token-driven, but light is not offered,
# not chosen at start-up (CALSUITE_THEME=light and a saved 'light' are ignored here) and not polished or tested.  To enable it later: add 'light' to
# ENABLED_THEMES, review every screen / the gallery in light, and add light cases to the tests (see NOTES.md 'Qt design system').
ENABLED_THEMES = ('dark', 'light')              # light enabled 2026-10-24 (Mike); dark stays the default; Help > Appearance switches live
DEFAULT_THEME = 'dark'
KINDS = core.KINDS                                   # 'good', 'bad', 'warn', 'info', 'neutral'


def _rgb(c: str):
    c = c.lstrip('#')
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def blend(a: str, b: str, t: float) -> str:
    """Colour `t` of the way from a to b ('#rrggbb' strings)."""
    ra, rb = _rgb(a), _rgb(b)
    return '#%02x%02x%02x' % tuple(int(round(x + (y - x) * t)) for x, y in zip(ra, rb))


def luminance(c: str) -> float:
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in _rgb(c))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def build_tokens(name: str) -> dict:
    """The Qt token dict for a palette name: the core palette (tuples split into fill / border) plus derived colours."""
    pal = core.PALETTES[name if name in core.PALETTES else 'light']
    t = dict(pal)
    for k in ('btn', 'btn_hi', 'btn_lo', 'btn_off'):          # core stores (fill, border) pairs for the Tk buttons
        t[k], t[k + '_border'] = pal[k]
    dark = name == 'dark'
    t['name'] = name if name in core.PALETTES else 'light'
    t['is_dark'] = dark
    if dark:                                                   # the light blue of the dark theme reads with dark text (white on it is 2.9:1)
        t['on_primary'] = t['bg']
    else:
        t['info'] = '#0958C8' if contrast(t['info'], t['select']) < 4.6 else t['info']
    t['faint'] = t.get('faint', t['muted'])
    while contrast(t['faint'], t['bg']) < 3.0 or contrast(t['faint'], t['card']) < 3.0:        # 'faint' is decoration / disabled text: at least 3:1
        t['faint'] = blend(t['faint'], t['muted'], 0.1)
    if not dark:                                               # light only: the blue is darkened until button text and links on it / on the page read (>= 4.5:1)
        k = 0.0
        while k < 0.5 and min(contrast(t['on_primary'], t['primary']), contrast(t['primary'], t['bg']), contrast(t['primary'], t['card'])) < 4.5:
            k += 0.02
            t['primary'] = blend(pal['primary'], '#000000', k)
        if k:
            t['primary_hi'], t['primary_lo'] = blend(t['primary'], '#000000', 0.10), blend(t['primary'], '#000000', 0.22)
        k = 0.0
        while k < 0.5 and contrast('#FFFFFF', t['danger']) < 4.5:      # the danger button's text is white
            k += 0.02
            t['danger'] = blend(pal['danger'], '#000000', k)
        if k:
            t['danger_hi'], t['danger_lo'] = blend(t['danger'], '#000000', 0.10), blend(t['danger'], '#000000', 0.22)
    t['focus'] = t['primary']
    t['focus_ring'] = blend(t['primary'], t['bg'], 0.35)       # the soft halo drawn around a focused field
    t['disabled_fg'] = blend(t['muted'], t['btn_off'], 0.30 if dark else 0.12)
    t['disabled_bg'] = t['btn_off']
    t['placeholder'] = blend(t['muted'], t['field'], 0.08 if dark else 0.0)
    # disabled primary button: pick whichever of white / body text reads better on the pale primary_off, then soften it
    best = max((t['on_primary'], t['text']), key=lambda c: contrast(c, t['primary_off']))
    t['primary_off_fg'] = blend(best, t['primary_off'], 0.25)
    t['danger_off_fg'] = blend(max((t['on_primary'], t['text']), key=lambda c: contrast(c, t['danger_off'])), t['danger_off'], 0.25)
    t['tooltip_fg'] = '#FFFFFF' if luminance(t['tip']) < 0.3 else t['text']
    t['shadow'] = '#000000'
    t['overlay'] = blend(t['bg'], '#000000', 0.45 if dark else 0.30)
    return t


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# sizes, spacing, typography: the one place
# ----------------------------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Metrics:
    # spacing scale (4 px grid)
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    page_margin: int = 24            # window content margin
    # shape
    radius_sm: int = 4
    radius: int = 6                  # buttons, fields
    radius_md: int = 8               # tables, banners
    radius_lg: int = 10              # cards
    border: int = 1
    # controls
    control_h: int = 32              # buttons, fields, combo boxes
    row_h: int = 34                  # table rows
    header_h: int = 36
    badge_h: int = 22
    badge_h_sm: int = 20
    icon: int = 16
    scrollbar: int = 12
    dialog_w: int = 460
    # type (pixels)
    font_base: int = 13
    font_small: int = 12
    font_tiny: int = 11
    font_h2: int = 16
    font_h1: int = 22
    font_mono: int = 12


M = Metrics()

_SANS = {
    'win32': ('Segoe UI Variable Text', 'Segoe UI', 'Inter', 'Noto Sans', 'DejaVu Sans', 'Arial'),
    'darwin': ('SF Pro Text', '.AppleSystemUIFont', 'Helvetica Neue', 'Inter', 'Arial'),
}
_SANS_OTHER = ('Inter', 'Noto Sans', 'Ubuntu', 'Cantarell', 'DejaVu Sans', 'Liberation Sans', 'Arial')
_MONO = {
    'win32': ('Cascadia Mono', 'Consolas', 'Lucida Console', 'Courier New'),
    'darwin': ('SF Mono', 'Menlo', 'Monaco', 'Courier New'),
}
_MONO_OTHER = ('JetBrains Mono', 'Noto Sans Mono', 'DejaVu Sans Mono', 'Liberation Mono', 'Courier New')

_fonts: dict = {}


def _first_available(prefs, fallback_fixed=False) -> str:
    have = {f.lower(): f for f in QFontDatabase.families()}
    for name in prefs:
        if name.lower() in have:
            return have[name.lower()]
    if fallback_fixed:
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()


def font_family() -> str:
    """The UI font: Segoe UI on Windows, Inter / Noto Sans / DejaVu Sans elsewhere (first one installed), else the system font."""
    if 'sans' not in _fonts:
        _fonts['sans'] = _first_available(_SANS.get(sys.platform, _SANS_OTHER))
    return _fonts['sans']


def mono_family() -> str:
    """The fixed-width font for readings, step numbers and codes."""
    if 'mono' not in _fonts:
        _fonts['mono'] = _first_available(_MONO.get(sys.platform, _MONO_OTHER), fallback_fixed=True)
    return _fonts['mono']


def ui_font(size: int | None = None, weight: QFont.Weight | None = None, mono: bool = False) -> QFont:
    f = QFont(mono_family() if mono else font_family())
    f.setPixelSize(size or (M.font_mono if mono else M.font_base))
    if weight is not None:
        f.setWeight(weight)
    return f


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# icons: drawn with QPainter in the current colours (no image files shipped); the QSS indicator images are written once to a cache folder
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def _draw(name: str, p: QPainter, s: float, col: QColor):
    pen = QPen(col, max(1.3, s / 11.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name == 'search':
        r = s * 0.30
        c = QPointF(s * 0.43, s * 0.43)
        p.drawEllipse(c, r, r)
        p.drawLine(QPointF(c.x() + r * 0.72, c.y() + r * 0.72), QPointF(s * 0.84, s * 0.84))
    elif name == 'clear':
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(s * 0.12, s * 0.12, s * 0.76, s * 0.76))
        p.setPen(QPen(QColor(255, 255, 255) if col.lightness() < 140 else QColor(30, 30, 30), max(1.3, s / 12.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        a, b = s * 0.36, s * 0.64
        p.drawLine(QPointF(a, a), QPointF(b, b))
        p.drawLine(QPointF(a, b), QPointF(b, a))
    elif name == 'close':
        a, b = s * 0.28, s * 0.72
        p.drawLine(QPointF(a, a), QPointF(b, b))
        p.drawLine(QPointF(a, b), QPointF(b, a))
    elif name == 'check':
        path = QPainterPath(QPointF(s * 0.24, s * 0.52))
        path.lineTo(QPointF(s * 0.43, s * 0.70))
        path.lineTo(QPointF(s * 0.76, s * 0.31))
        p.setPen(QPen(col, max(1.8, s / 8.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
    elif name == 'dash':
        p.setPen(QPen(col, max(1.8, s / 8.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * 0.28, s * 0.5), QPointF(s * 0.72, s * 0.5))
    elif name == 'dot':
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.40))
    elif name in ('chevron_down', 'chevron_up'):
        y0, y1 = (s * 0.38, s * 0.62) if name == 'chevron_down' else (s * 0.62, s * 0.38)
        path = QPainterPath(QPointF(s * 0.28, y0))
        path.lineTo(QPointF(s * 0.5, y1))
        path.lineTo(QPointF(s * 0.72, y0))
        p.drawPath(path)
    elif name == 'info':
        p.drawEllipse(QRectF(s * 0.12, s * 0.12, s * 0.76, s * 0.76))
        p.drawLine(QPointF(s * 0.5, s * 0.45), QPointF(s * 0.5, s * 0.68))
        p.setPen(QPen(col, max(1.8, s / 8.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPoint(QPointF(s * 0.5, s * 0.31))
    elif name == 'warn':
        path = QPainterPath(QPointF(s * 0.5, s * 0.14))
        path.lineTo(QPointF(s * 0.88, s * 0.80))
        path.lineTo(QPointF(s * 0.12, s * 0.80))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.5, s * 0.40), QPointF(s * 0.5, s * 0.58))
        p.setPen(QPen(col, max(1.8, s / 8.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPoint(QPointF(s * 0.5, s * 0.69))
    elif name == 'error':
        p.drawEllipse(QRectF(s * 0.12, s * 0.12, s * 0.76, s * 0.76))
        a, b = s * 0.36, s * 0.64
        p.drawLine(QPointF(a, a), QPointF(b, b))
        p.drawLine(QPointF(a, b), QPointF(b, a))
    elif name == 'good':
        p.drawEllipse(QRectF(s * 0.12, s * 0.12, s * 0.76, s * 0.76))
        path = QPainterPath(QPointF(s * 0.32, s * 0.52))
        path.lineTo(QPointF(s * 0.45, s * 0.65))
        path.lineTo(QPointF(s * 0.70, s * 0.36))
        p.drawPath(path)
    elif name == 'save':                                   # a floppy disk
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68), s * 0.08, s * 0.08)
        p.drawRect(QRectF(s * 0.32, s * 0.16, s * 0.34, s * 0.22))
        p.drawRect(QRectF(s * 0.30, s * 0.55, s * 0.40, s * 0.29))
    elif name == 'load':                                   # an open folder
        path = QPainterPath(QPointF(s * 0.12, s * 0.80))
        for x, y in ((0.12, 0.26), (0.40, 0.26), (0.48, 0.36), (0.86, 0.36), (0.86, 0.80)):
            path.lineTo(QPointF(s * x, s * y))
        path.closeSubpath()
        p.drawPath(path)
    elif name == 'export':                                 # a page with an arrow leaving it
        path = QPainterPath(QPointF(s * 0.56, s * 0.14))
        for x, y in ((0.20, 0.14), (0.20, 0.86), (0.72, 0.86), (0.72, 0.60)):
            path.lineTo(QPointF(s * x, s * y))
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.42, s * 0.58), QPointF(s * 0.84, s * 0.16))
        p.drawLine(QPointF(s * 0.60, s * 0.16), QPointF(s * 0.84, s * 0.16))
        p.drawLine(QPointF(s * 0.84, s * 0.16), QPointF(s * 0.84, s * 0.40))
    elif name == 'rerun':                                  # a circular arrow
        p.drawArc(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64), 60 * 16, 270 * 16)
        p.drawLine(QPointF(s * 0.68, s * 0.14), QPointF(s * 0.66, s * 0.32))
        p.drawLine(QPointF(s * 0.68, s * 0.14), QPointF(s * 0.84, s * 0.26))
    elif name == 'edit':                                   # a pencil
        path = QPainterPath(QPointF(s * 0.18, s * 0.82))
        for x, y in ((0.24, 0.62), (0.66, 0.20), (0.80, 0.34), (0.38, 0.76)):
            path.lineTo(QPointF(s * x, s * y))
        path.closeSubpath()
        p.drawPath(path)
    elif name == 'play':
        path = QPainterPath(QPointF(s * 0.30, s * 0.18))
        path.lineTo(QPointF(s * 0.82, s * 0.50))
        path.lineTo(QPointF(s * 0.30, s * 0.82))
        path.closeSubpath()
        p.drawPath(path)
    elif name == 'inbox':
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.22, s * 0.72, s * 0.56), s * 0.08, s * 0.08)
        p.drawLine(QPointF(s * 0.14, s * 0.56), QPointF(s * 0.38, s * 0.56))
        p.drawLine(QPointF(s * 0.62, s * 0.56), QPointF(s * 0.86, s * 0.56))
        p.drawLine(QPointF(s * 0.38, s * 0.56), QPointF(s * 0.42, s * 0.66))
        p.drawLine(QPointF(s * 0.62, s * 0.56), QPointF(s * 0.58, s * 0.66))
        p.drawLine(QPointF(s * 0.42, s * 0.66), QPointF(s * 0.58, s * 0.66))


ICON_NAMES = ('search', 'clear', 'close', 'check', 'dash', 'dot', 'chevron_down', 'chevron_up', 'info', 'warn', 'error', 'good', 'inbox', 'save', 'load', 'export', 'rerun', 'edit', 'play')


def pixmap(name: str, color: str, size: int = 16, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw(name, p, float(size), QColor(color))
    p.end()
    return pm


def icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    """A drawn icon in a token colour name ('muted', 'primary' ...) or a '#rrggbb' string (default: muted text)."""
    col = color or 'muted'
    col = tokens().get(col, col)
    return QIcon(pixmap(name, col, size))


def _icon_dir() -> Path:
    d = Path(tempfile.gettempdir()) / f'calsuite_qtui_icons_{hashlib.md5(os.path.expanduser("~").encode()).hexdigest()[:6]}'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _icon_file(name: str, color: str, size: int = 16) -> str:
    """A PNG (plus @2x) for a QSS `image: url(...)`; written once per (icon, colour)."""
    base = _icon_dir() / f'{name}_{color.lstrip("#")}.png'
    for scale, path in ((1, base), (2, base.with_name(base.stem + '@2x.png'))):
        if not path.exists():
            pm = pixmap(name, color, size * scale, dpr=1.0)          # drawn for size*scale device px
            pm.save(str(path), 'PNG')
    return base.as_posix()


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the application style sheet
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def build_qss(t: dict, m: Metrics = M, sans: str | None = None, mono: str | None = None) -> str:
    sans = sans or font_family()
    mono = mono or mono_family()
    r, rm, rl, rs = m.radius, m.radius_md, m.radius_lg, m.radius_sm
    chk = _icon_file('check', t['on_primary'])
    dot = _icon_file('dot', t['on_primary'])
    dash = _icon_file('dash', t['on_primary'])
    dn = _icon_file('chevron_down', t['muted'])
    dn_off = _icon_file('chevron_down', t['disabled_fg'])
    up = _icon_file('chevron_up', t['muted'])
    return f"""
* {{ font-family: '{sans}'; font-size: {m.font_base}px; color: {t['text']}; }}
QWidget {{ selection-background-color: {t['select']}; selection-color: {t['text']}; }}
QWidget:disabled {{ color: {t['disabled_fg']}; }}
QMainWindow, QDialog, QWidget#root {{ background: {t['bg']}; }}
QToolTip {{ background: {t['tip']}; color: {t['tooltip_fg']}; border: 1px solid {t['tip']}; border-radius: {rs}px; padding: 4px 8px; }}

/* labels: role property */
QLabel {{ background: transparent; border: none; }}
QLabel[role="title"] {{ font-size: {m.font_h1}px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: {m.font_h2}px; font-weight: 700; }}
QLabel[role="section"] {{ font-weight: 700; }}
QLabel[role="sub"] {{ color: {t['muted']}; }}
QLabel[role="hint"] {{ color: {t['muted']}; font-size: {m.font_small}px; }}
QLabel[role="kvkey"] {{ color: {t['muted']}; }}
QLabel[role="kvvalue"] {{ font-weight: 700; }}
QLabel[role="mono"] {{ font-family: '{mono}'; font-size: {m.font_mono}px; }}
QLabel[role="chip"] {{ background: {t['info_bg']}; color: {t['info']}; padding: 4px 12px; border-radius: 11px; font-weight: 600; font-size: {m.font_small}px; }}
QLabel:disabled {{ color: {t['disabled_fg']}; }}
QLabel[badge] {{ padding: 2px 10px; border-radius: {m.badge_h // 2}px; font-weight: 600; font-size: {m.font_small}px; min-height: {m.badge_h - 4}px; }}
QLabel[badge="good"] {{ background: {t['good_bg']}; color: {t['good']}; }}
QLabel[badge="bad"] {{ background: {t['bad_bg']}; color: {t['bad']}; }}
QLabel[badge="warn"] {{ background: {t['warn_bg']}; color: {t['warn']}; }}
QLabel[badge="info"] {{ background: {t['info_bg']}; color: {t['info']}; }}
QLabel[badge="neutral"] {{ background: {t['neutral_bg']}; color: {t['neutral']}; }}
QLabel[badge][small="true"] {{ font-size: {m.font_tiny}px; padding: 1px 8px; min-height: {m.badge_h_sm - 2}px; border-radius: {m.badge_h_sm // 2}px; }}

/* surfaces */
QFrame[surface="card"] {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: {rl}px; }}
QFrame[surface="bar"] {{ background: {t['bar']}; border: none; border-bottom: 1px solid {t['border']}; }}
QFrame[surface="barbottom"] {{ background: {t['card']}; border: none; border-top: 1px solid {t['border']}; }}
QFrame[surface="strip"] {{ background: {t['bar']}; border: none; border-bottom: 1px solid {t['border']}; }}
QFrame[surface="rule"] {{ background: {t['border']}; border: none; min-height: 1px; max-height: 1px; }}
QFrame[surface="vrule"] {{ background: {t['border']}; border: none; min-width: 1px; max-width: 1px; }}
QFrame[surface="segment"] {{ background: {t['bar']}; border: 1px solid {t['border']}; border-radius: {m.control_h // 2}px; }}
QFrame[surface="popover"] {{ background: {t['card']}; border: 1px solid {t['border_strong']}; border-radius: {rm}px; }}
QFrame[surface="empty"] {{ background: transparent; border: none; }}
QFrame[banner] {{ border-radius: {rm}px; border: 1px solid {t['border']}; }}
QFrame[banner="info"] {{ background: {t['info_bg']}; border-color: {blend(t['info'], t['info_bg'], 0.55)}; }}
QFrame[banner="warn"] {{ background: {t['warn_bg']}; border-color: {blend(t['warn'], t['warn_bg'], 0.55)}; }}
QFrame[banner="error"] {{ background: {t['bad_bg']}; border-color: {blend(t['bad'], t['bad_bg'], 0.55)}; }}
QFrame[banner="good"] {{ background: {t['good_bg']}; border-color: {blend(t['good'], t['good_bg'], 0.55)}; }}
QLabel[bannertitle="info"] {{ color: {t['info']}; font-weight: 700; }}
QLabel[bannertitle="warn"] {{ color: {t['warn']}; font-weight: 700; }}
QLabel[bannertitle="error"] {{ color: {t['bad']}; font-weight: 700; }}
QLabel[bannertitle="good"] {{ color: {t['good']}; font-weight: 700; }}
QFrame[toast] {{ background: {t['tip']}; border: 1px solid {t['border_strong']}; border-radius: {rm}px; }}
QFrame[toast] QLabel {{ color: {t['tooltip_fg']}; }}

/* menus */
QMenuBar {{ background: {t['card']}; border-bottom: 1px solid {t['border']}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: {rs}px; background: transparent; }}
QMenuBar::item:selected {{ background: {t['btn_hi']}; }}
QMenu {{ background: {t['card']}; border: 1px solid {t['border_strong']}; border-radius: {rm}px; padding: 5px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: {rs}px; }}
QMenu::item:selected {{ background: {t['select']}; }}
QMenu::item:disabled {{ color: {t['disabled_fg']}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 6px; }}

/* tabs */
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{ padding: 8px 16px; margin-right: 2px; color: {t['muted']}; border: none; border-bottom: 2px solid transparent; background: transparent; }}
QTabBar::tab:selected {{ color: {t['text']}; font-weight: 600; border-bottom: 2px solid {t['primary']}; }}
QTabBar::tab:hover:!selected {{ color: {t['text']}; }}
QTabBar::tab:focus {{ background: {t['select']}; border-top-left-radius: {rs}px; border-top-right-radius: {rs}px; }}
QTabBar::tab:disabled {{ color: {t['disabled_fg']}; }}
QTabBar[sub="true"]::tab {{ padding: 6px 14px; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {t['border']}; top: -1px; }}

/* fields */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t['field']}; border: 1px solid {t['border']}; border-radius: {r}px; padding: 5px 10px; min-height: {m.control_h - 12}px; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {t['border_strong']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QComboBox:on {{
    border: 2px solid {t['focus']}; padding: 4px 9px; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {t['disabled_bg']}; color: {t['disabled_fg']}; border-color: {t['border']}; }}
QLineEdit[readOnly="true"] {{ background: {t['bar']}; }}
QLineEdit[invalid="true"] {{ border: 2px solid {t['bad']}; padding: 4px 9px; }}
QLineEdit[mono="true"] {{ font-family: '{mono}'; font-size: {m.font_mono}px; }}
QLineEdit {{ placeholder-text-color: {t['placeholder']}; }}
QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({dn}); width: 16px; height: 16px; }}
QComboBox::down-arrow:disabled {{ image: url({dn_off}); }}
QComboBox QAbstractItemView {{ background: {t['card']}; border: 1px solid {t['border_strong']}; border-radius: {rs}px; outline: 0; padding: 4px;
    selection-background-color: {t['select']}; selection-color: {t['text']}; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: {rs}px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ border: none; width: 18px; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({up}); width: 12px; height: 12px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({dn}); width: 12px; height: 12px; }}

/* buttons (role property: none = secondary) */
QPushButton {{ background: {t['btn']}; border: 1px solid {t['btn_border']}; border-radius: {r}px; padding: 6px 14px; min-height: {m.control_h - 14}px; }}
QPushButton:hover {{ background: {t['btn_hi']}; border-color: {t['btn_hi_border']}; }}
QPushButton:pressed {{ background: {t['btn_lo']}; border-color: {t['btn_lo_border']}; }}
QPushButton:focus {{ border: 2px solid {t['focus']}; padding: 5px 13px; }}
QPushButton:disabled {{ background: {t['btn_off']}; border-color: {t['btn_off_border']}; color: {t['disabled_fg']}; }}
QPushButton[role="primary"] {{ background: {t['primary']}; border: 1px solid {t['primary']}; color: {t['on_primary']}; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: {t['primary_hi']}; border-color: {t['primary_hi']}; }}
QPushButton[role="primary"]:pressed {{ background: {t['primary_lo']}; border-color: {t['primary_lo']}; }}
QPushButton[role="primary"]:focus {{ border: 2px solid {t['text']}; padding: 5px 13px; }}
QPushButton[role="primary"]:disabled {{ background: {t['primary_off']}; border-color: {t['primary_off']}; color: {t['primary_off_fg']}; }}
QPushButton[role="danger"] {{ background: {t['danger']}; border: 1px solid {t['danger']}; color: #FFFFFF; font-weight: 600; }}
QPushButton[role="danger"]:hover {{ background: {t['danger_hi']}; border-color: {t['danger_hi']}; }}
QPushButton[role="danger"]:pressed {{ background: {t['danger_lo']}; border-color: {t['danger_lo']}; }}
QPushButton[role="danger"]:focus {{ border: 2px solid {t['text']}; padding: 5px 13px; }}
QPushButton[role="danger"]:disabled {{ background: {t['danger_off']}; border-color: {t['danger_off']}; color: {t['danger_off_fg']}; }}
QPushButton[role="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t['primary']}; font-weight: 600; }}
QPushButton[role="ghost"]:hover {{ background: {t['select']}; }}
QPushButton[role="ghost"]:focus {{ border: 2px solid {t['focus']}; padding: 5px 13px; }}
QPushButton[role="ghost"]:disabled {{ background: transparent; color: {t['disabled_fg']}; }}
QPushButton[role="seg"] {{ background: transparent; border: 1px solid transparent; border-radius: {(m.control_h - 8) // 2}px; padding: 4px 14px; min-height: {m.control_h - 14}px;
    color: {t['muted']}; }}
QPushButton[role="seg"]:hover:!checked {{ background: {t['btn_hi']}; color: {t['text']}; }}
QPushButton[role="seg"]:checked {{ background: {t['primary']}; color: {t['on_primary']}; font-weight: 600; }}
QPushButton[role="seg"]:focus {{ border: 2px solid {t['text']}; padding: 3px 13px; }}
QPushButton[role="seg"]:disabled {{ color: {t['disabled_fg']}; background: transparent; }}
QPushButton[role="info"] {{ border-radius: 12px; padding: 0; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; color: {t['primary']}; font-weight: 700;
    background: {t['info_bg']}; border: 1px solid transparent; }}
QPushButton[role="info"]:hover {{ background: {t['select']}; }}
QPushButton[role="info"]:focus {{ border: 2px solid {t['focus']}; padding: 0; }}
QPushButton[role="icon"] {{ background: transparent; border: 1px solid transparent; padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}
QPushButton[role="icon"]:hover {{ background: {t['btn_hi']}; }}
QPushButton[role="icon"]:focus {{ border: 2px solid {t['focus']}; padding: 0; }}

/* check / radio */
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t['disabled_fg']}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {t['border_strong']}; background: {t['field']}; }}
QCheckBox::indicator {{ border-radius: {rs}px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t['primary']}; }}
QCheckBox::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']}; image: url({chk}); }}
QCheckBox::indicator:indeterminate {{ background: {t['primary']}; border-color: {t['primary']}; image: url({dash}); }}
QRadioButton::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']}; image: url({dot}); }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background: {t['disabled_bg']}; border-color: {t['border']}; }}
QCheckBox::indicator:checked:disabled, QCheckBox::indicator:indeterminate:disabled, QRadioButton::indicator:checked:disabled {{
    background: {t['primary_off']}; border-color: {t['primary_off']}; }}
QCheckBox:focus {{ color: {t['text']}; }}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border: 2px solid {t['focus']}; }}

/* tables and lists */
QTableView, QTreeView, QListView {{ background: {t['table']}; alternate-background-color: {t['row_alt']}; border: 1px solid {t['border']}; border-radius: {rm}px;
    gridline-color: transparent; selection-background-color: {t['select']}; selection-color: {t['text']}; outline: 0; }}
QTableView:focus, QTreeView:focus, QListView:focus {{ border: 1px solid {t['focus']}; }}
QTableView:disabled {{ color: {t['disabled_fg']}; }}
QTableView::item, QTreeView::item, QListView::item {{ padding: 4px 8px; border: none; }}
QTableView::item:selected {{ background: {t['select']}; }}
QTableView#frozen {{ border: none; border-radius: 0; border-right: 1px solid {t['border_strong']}; border-top-left-radius: {rm}px; border-bottom-left-radius: {rm}px; }}
QTableView::item:selected:!active {{ background: {blend(t['select'], t['table'], 0.35)}; }}
QTableView QLineEdit {{ border-radius: {rs}px; padding: 2px 6px; min-height: 0; border: 2px solid {t['focus']}; }}
QTableView QComboBox {{ border-radius: {rs}px; padding: 2px 8px; min-height: 0; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {t['head']}; color: {t['muted']}; font-weight: 600; padding: 0 10px; border: none; border-bottom: 1px solid {t['border']};
    border-right: 1px solid transparent; }}
QHeaderView::section:hover {{ background: {t['head_hi']}; color: {t['text']}; }}
QHeaderView::section:horizontal:first {{ border-top-left-radius: {rm}px; }}
QHeaderView::section:horizontal:last {{ border-top-right-radius: {rm}px; }}
QTableCornerButton::section {{ background: {t['head']}; border: none; }}

/* scroll bars */
QScrollBar:vertical {{ background: transparent; width: {m.scrollbar}px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: {m.scrollbar}px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['scroll']}; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:horizontal {{ background: {t['scroll']}; border-radius: 4px; min-width: 32px; }}
QScrollBar::handle:hover {{ background: {t['scroll_hi']}; }}
QScrollBar::handle:pressed {{ background: {t['scroll_lo']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: none; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; }}

/* progress, status, misc */
QProgressBar {{ background: {t['trough']}; border: none; border-radius: 4px; height: 8px; max-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t['primary']}; border-radius: 4px; }}
QStatusBar {{ background: {t['card']}; border-top: 1px solid {t['border']}; color: {t['muted']}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {t['muted']}; }}
QSplitter::handle {{ background: transparent; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: {rm}px; margin-top: 12px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {t['muted']}; font-weight: 600; }}
QSlider::groove:horizontal {{ background: {t['trough']}; height: 6px; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t['primary']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t['card']}; border: 2px solid {t['primary']}; width: 14px; height: 14px; margin: -6px 0; border-radius: 9px; }}

/* pill toggles: a checkable QPushButton with role=chip is a tick box drawn as a pill (Datasheet Builder tolerance types) */
QPushButton[role="chip"] {{ background: {t['bar']}; border: 1px solid {t['border_strong']}; border-radius: 13px; padding: 3px 12px; color: {t['muted']}; min-height: 20px; }}
QPushButton[role="chip"]:hover {{ border-color: {t['primary']}; color: {t['text']}; }}
QPushButton[role="chip"]:checked {{ background: {t['info_bg']}; border: 1px solid {t['primary']}; color: {t['info']}; font-weight: 600; }}
QPushButton[role="chip"]:focus {{ border: 2px solid {t['focus']}; padding: 2px 11px; }}
QPushButton[role="chip"]:disabled {{ color: {t['disabled_fg']}; }}
"""


def build_palette(t: dict) -> QPalette:
    """QPalette for the native bits the style sheet does not paint (focus frames, message icons, third-party widgets)."""
    p = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    pairs = {R.Window: t['bg'], R.WindowText: t['text'], R.Base: t['field'], R.AlternateBase: t['row_alt'], R.Text: t['text'], R.Button: t['btn'],
             R.ButtonText: t['text'], R.Highlight: t['select'], R.HighlightedText: t['text'], R.ToolTipBase: t['tip'], R.ToolTipText: t['tooltip_fg'],
             R.PlaceholderText: t['placeholder'], R.Link: t['primary'], R.BrightText: t['bad'], R.Mid: t['border'], R.Midlight: t['border'],
             R.Dark: t['border_strong'], R.Light: t['card'], R.Shadow: t['shadow']}
    for role, col in pairs.items():
        p.setColor(role, QColor(col))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, role, QColor(t['disabled_fg']))
    p.setColor(G.Disabled, R.Base, QColor(t['disabled_bg']))
    return p


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the manager: current theme, live switching
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class ThemeManager(QObject):
    changed = Signal(str)                      # emitted after the application style sheet was replaced; the argument is 'light' | 'dark'

    def __init__(self):
        super().__init__()
        self._name = DEFAULT_THEME
        self._tokens = build_tokens(DEFAULT_THEME)
        self._applied_qss = ''

    @property
    def name(self) -> str:
        return self._name

    @property
    def tokens(self) -> dict:
        return self._tokens

    @property
    def qss(self) -> str:
        return self._applied_qss

    def set_theme(self, name: str, *, save: bool = False, app: QApplication | None = None) -> str:
        """Switch the whole application to `name` ('light' | 'dark') without a restart.  `save=True` remembers it as the person's choice (same file as the
        Tk 'Help > Appearance': ~/.calibration_suite/appearance.json)."""
        name = name if name in core.PALETTES else 'light'
        core.use_palette(name)                               # the toolkit-free code (ui_theme_core.C / THEME) follows
        self._name = name
        self._tokens = build_tokens(name)
        app = app or QApplication.instance()
        if app is not None:
            self._applied_qss = build_qss(self._tokens)
            app.setPalette(build_palette(self._tokens))
            app.setStyleSheet(self._applied_qss)
        if save:
            store = core.Settings('appearance')
            store.set('theme', name)
            store.save()
        self.changed.emit(name)
        return name

    def apply_initial(self, app: QApplication | None = None) -> str:
        """The start-up choice: CALSUITE_THEME, else the saved choice, else the edition default (ui_theme_core.theme_choice), limited to ENABLED_THEMES
        (dark only for now, so the others fall back to DEFAULT_THEME)."""
        choice = core.theme_choice()
        return self.set_theme(choice if choice in ENABLED_THEMES else DEFAULT_THEME, app=app)


_manager: ThemeManager | None = None


def manager() -> ThemeManager:
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def tokens() -> dict:
    return manager().tokens


def name() -> str:
    return manager().name


def is_dark() -> bool:
    return manager().name == 'dark'


def set_theme(theme_name: str, *, save: bool = False) -> str:
    return manager().set_theme(theme_name, save=save)


def color(key: str) -> QColor:
    """A token as a QColor ('good_bg', 'text' ...)."""
    return QColor(tokens()[key])


def tone_colors(kind: str) -> tuple[str, str]:
    """(foreground, background) of a status kind: 'good' | 'bad' | 'warn' | 'info' | 'neutral'."""
    t = tokens()
    kind = kind if kind in KINDS else 'neutral'
    return t[kind], t[kind + '_bg']


def build_appearance_menu(parent_menu: QMenu, on_change=None) -> QMenu | None:
    """'Appearance' submenu for the Help menu: one entry per ENABLED_THEMES (the current one checked), switches live and remembers the choice.
    While only dark is enabled, it returns None and adds nothing (a menu with a single choice is noise)."""
    from PySide6.QtGui import QActionGroup
    if len(ENABLED_THEMES) < 2:
        return None
    sub = parent_menu.addMenu('Appearance')
    group = QActionGroup(sub)
    group.setExclusive(True)
    acts = {}
    for key, label in ((k, k.title()) for k in ENABLED_THEMES):
        a = sub.addAction(label)
        a.setCheckable(True)
        a.setChecked(name() == key)
        group.addAction(a)
        acts[key] = a

        def pick(_checked=False, k=key):
            set_theme(k, save=True)
            if on_change:
                on_change(k)
        a.triggered.connect(pick)
    def _sync(n, acts=acts):
        try:
            if n in acts:
                acts[n].setChecked(True)
        except RuntimeError:
            pass                                                  # the menu went away with its window
    manager().changed.connect(_sync)
    return sub
