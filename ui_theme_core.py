"""Toolkit-free part of the shared look-and-feel: the palettes (LIGHT / DARK, the live palette `C`), the theme choice, SI / number formatting for display,
the per-user Settings store and the report file name.  Nothing here imports a GUI toolkit, so the Tk theme (ui_theme.py), a Qt theme and the engines can all use it.

ui_theme.py re-exports every name below (`ui_theme.si_row`, `ui_theme.C`, ...), so existing callers do not change.  The three values that get REBOUND at run time
live here and are read through `ui_theme` by attribute (ui_theme.SCALE / THEME / DEMO_SUFFIX are module-level __getattr__ forwards to this module): set them here
(ui_theme_core.DEMO_SUFFIX = ..., or use_palette(name)); apply_theme() sets SCALE.
"""
import json
from pathlib import Path

# ----------------------------------------------------------------------------- palette
LIGHT = dict(
    bg='#F5F5F7', card='#FFFFFF', bar='#EDEDF2', border='#D8D8DE', border_strong='#C7C7CC',
    text='#1D1D1F', muted='#6E6E73', faint='#A1A1A6',
    navy='#1D1D1F', navy_hi='#3A3A3C', accent_line='#007AFF',
    primary='#007AFF', primary_hi='#0A6EE6', primary_lo='#0058C0',
    select='#D2E4FF', row_alt='#FAFAFC', head='#FAFAFC', head_hi='#EFEFF4',
    good='#1F7A3A', good_bg='#E4F6E9', good_dot='#34C759',
    bad='#C4121F', bad_bg='#FFE9EA', bad_dot='#FF3B30',
    warn='#9A5B00', warn_bg='#FFF3DC', warn_dot='#FF9500',
    info='#0A5FD6', info_bg='#E5F0FF', info_dot='#007AFF',
    neutral='#55555A', neutral_bg='#E8E8ED', neutral_dot='#A1A1A6',
    field='#FFFFFF', table='#FFFFFF', on_primary='#FFFFFF', primary_off='#A9CFFF',
    btn=('#FFFFFF', '#D2D2D7'), btn_hi=('#F0F0F5', '#C7C7CC'), btn_lo=('#E3E3E8', '#BCBCC2'), btn_off=('#F5F5F7', '#E3E3E8'),
    danger='#FF3B30', danger_hi='#E0281D', danger_lo='#C21A10', danger_off='#FFB3AE',
    combo_btn='#EAEFF5', combo_btn_hi='#DCE5F0', trough='#E3E3E8', scroll='#D1D1D6', scroll_hi='#A1A1A6', scroll_lo='#8E8E93',
    tip='#3A3A3C', row_even='#FFFFFF',
    row_pass='#FFFFFF', row_pass_fg='#1F7A3A', row_fail='#FFFFFF', row_fail_fg='#B3261E', row_warn='#FFFFFF', row_warn_fg='#8A5A00',
)

# Flat warm-charcoal dark theme with one blue accent (the beta's default look).
DARK = dict(
    bg='#262624', card='#2B2A28', bar='#262624', border='#3B3A37', border_strong='#4A4945',
    text='#ECE9E1', muted='#A09D95', faint='#6F6D67',
    navy='#ECE9E1', navy_hi='#BFBCB4', accent_line='#4C9BF5',
    primary='#4C9BF5', primary_hi='#6AAEF7', primary_lo='#3B82E0',
    select='#2A3A52', row_alt='#2F2E2B', head='#262624', head_hi='#33322F',
    good='#34D399', good_bg='#08301F', good_dot='#34D399',
    bad='#F87171', bad_bg='#3A1010', bad_dot='#F87171',
    warn='#FBBF24', warn_bg='#2A2108', warn_dot='#FBBF24',
    info='#9CC7FB', info_bg='#1D3556', info_dot='#4C9BF5',
    neutral='#A09D95', neutral_bg='#33322F', neutral_dot='#6F6D67',
    field='#1F1E1D', table='#2B2A28', on_primary='#FFFFFF', primary_off='#2B4766',
    btn=('#2D2C2A', '#44433F'), btn_hi=('#363532', '#555450'), btn_lo=('#262624', '#555450'), btn_off=('#262624', '#33322F'),
    danger='#C0392B', danger_hi='#D64535', danger_lo='#A12F23', danger_off='#4A2522',
    combo_btn='#33322F', combo_btn_hi='#3B3A37', trough='#33322F', scroll='#555450', scroll_hi='#6F6D67', scroll_lo='#8A8780',
    tip='#44433F', row_even='#2B2A28',
    row_pass='#2B2A28', row_pass_fg='#34D399', row_fail='#2B2A28', row_fail_fg='#F87171', row_warn='#2B2A28', row_warn_fg='#FBBF24',
)
PALETTES = {'light': LIGHT, 'dark': DARK}
C = dict(LIGHT)                    # the live palette: modules read ui.C at use time; use_palette() changes it in place
THEME = 'light'


def theme_choice() -> str:
    """Which palette to use: CALSUITE_THEME, else the person's saved choice (Help > Appearance), else the edition's default."""
    import os
    name = os.environ.get('CALSUITE_THEME', '').strip().lower()
    if name not in PALETTES:
        try:
            name = str(Settings('appearance').get('theme', '')).lower()
        except Exception:
            name = ''
    if name not in PALETTES:
        try:
            import suite_info
            name = getattr(suite_info, 'DEFAULT_THEME', 'light')
        except ImportError:
            name = 'light'
    return name if name in PALETTES else 'light'


def use_palette(name: str):
    global THEME
    THEME = name if name in PALETTES else 'light'
    C.clear()
    C.update(PALETTES[THEME])


def is_dark() -> bool:
    return THEME == 'dark'


KINDS = ('good', 'bad', 'warn', 'info', 'neutral')

SCALE = 1.0          # screen scale vs. 96 dpi (1.0, 1.25, 1.5 ...)


def px(n):
    """Scale a pixel size for high-DPI screens."""
    return int(round(n * SCALE))


_SI_STEPS = ((1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, '\u00b5'), (1e-9, 'n'), (1e-12, 'p'))


def si_scale(ref, unit=''):
    """Pick the SI prefix for a reference magnitude. Returns (divisor, unit_text) e.g. (1e-3, 'mV')."""
    sym = {'ohm': '\u03a9'}.get(unit, unit)
    try:
        a = abs(float(ref))
    except (TypeError, ValueError):
        return 1.0, sym
    if a == 0:
        return 1.0, sym
    for scale, prefix in _SI_STEPS:
        if a >= scale * 0.9999999:
            return scale, prefix + sym
    return 1e-12, 'p' + sym


def _decimals_needed(x, sig=7):
    t = f'{x:.{sig}g}'
    if 'e' in t.lower():
        t = f'{float(t):.12f}'.rstrip('0')
    return len(t.split('.')[1]) if '.' in t else 0


def si_one(value, unit='', sig=4):
    """Single value -> (number_text, unit_text) with `sig` significant digits, e.g. 0.00037 V -> ('370.0', '\u00b5V')."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '', {'ohm': '\u03a9'}.get(unit, unit)
    scale, unit_text = si_scale(v, unit)
    x = v / scale
    if x == 0:
        return '0', unit_text
    import math
    dec = max(0, sig - 1 - int(math.floor(math.log10(abs(x)))))
    return f'{x:.{dec}f}', unit_text


def si_row(values, unit='', readings=(), extra=2, ref=None, max_decimals=9):
    """Format one row of related values (nominal, limits ...) with a shared prefix and resolution.

    Returns (value_texts, reading_texts, unit_text). Display only - callers keep base-unit numbers.
    Limits use just enough decimals to show every value exactly (so 0.006 V -> '6' mV, 5.947 mV
    stays '5.947'); readings get `extra` more decimals so small deviations remain visible."""
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            nums.append(None)
    good = [n for n in nums if n is not None]
    if ref is None:
        ref = max((abs(n) for n in good), default=0)
    scale, unit_text = si_scale(ref, unit)
    dec = max((_decimals_needed(n / scale) for n in good), default=0)
    dec = min(dec, max_decimals)

    def fmt(n, d):
        if n is None:
            return ''
        t = f'{n / scale:.{d}f}'
        return '0' if float(t) == 0 and d == 0 else ('0' if t.lstrip('-0.') == '' else t)

    vals = [fmt(n, dec) for n in nums]
    reads = []
    for r in readings:
        try:
            reads.append(fmt(float(r), min(dec + extra, max_decimals + extra)))
        except (TypeError, ValueError):
            reads.append('')
    return vals, reads, unit_text


def si(value, unit=''):
    """12500 -> '12.5 k' + unit; 0.0001 -> '100 \u00b5' + unit. Ohm shows as the omega sign."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    sym = {'ohm': '\u03a9'}.get(unit, unit)
    if v == 0:
        return f'0 {sym}'.strip()
    a = abs(v)
    for scale, prefix in ((1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, '\u00b5'),
                          (1e-9, 'n'), (1e-12, 'p')):
        if a >= scale * 0.9999999:
            return f'{v / scale:.6g} {prefix}{sym}'.strip()
    return f'{v:.3g} {sym}'.strip()


def fmt_num(value, digits=9):
    try:
        return f'{float(value):.{digits}g}'
    except (TypeError, ValueError):
        return str(value)


def status_kind(text):
    """Pick a colour for a status message from its wording."""
    t = (text or '').lower()
    if not t:
        return 'neutral'
    if 'disconnected' in t or 'not connected' in t or 'no datasheet' in t:
        return 'neutral'
    if any(k in t for k in ('error', 'failed', 'cannot', 'refus', 'invalid', 'could not', 'mismatch')):
        return 'bad'
    if any(k in t for k in ('demo', 'stopp', 'paus', 'caution', 'warning', 'unlocked', 'interrupted')):
        return 'warn'
    if any(k in t for k in ('saved', 'exported', 'connected', 'complete', 'restored', 'loaded', 'launched',
                            'recorded', 'resumed', 'installed', 'ready')):
        return 'good'
    return 'info'


# ----------------------------------------------------------------------------- widgets


ADDRESS_KEYS = ('cal_addr', 'cal', 'cal_baud', 'std', 'counter', 'rf_addr', 'rf1', 'rf2', 'gen_addr', 'gen')      # app_settings.address_for decides which apply
_NO_ADDRESS_DEFAULTS = ('settings', 'appearance', 'report_details', 'packages')      # stores that are not a procedure's


class Settings:
    """Tiny per-user JSON store (ports, window sizes ...). Never raises."""

    def __init__(self, name):
        self.name_ = name
        self.path = Path.home() / '.calibration_suite' / f'{name}.json'
        try:
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            self.data = {}

    def get(self, key, default=None):
        if self.name_ not in _NO_ADDRESS_DEFAULTS and (key.startswith('addr_') or key in ADDRESS_KEYS):
            try:                                               # File > Settings > Instrument addresses: the default address of a standard (app_settings.address_for)
                import app_settings
                hit = app_settings.address_for(key, self.data, self.name_)
                if hit and (key not in self.data or app_settings.address_first()):
                    return hit
            except Exception:
                pass
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        except Exception:
            pass


def report_filename(asset, ext='.pdf', tag='', when=None):
    """Default report name: <asset>-MM-DD-YYYY.pdf  (a slash cannot be used in a Windows file name, so dashes separate the date)."""
    from datetime import datetime
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in str(asset or '')) or 'UNASSIGNED'
    return f"{safe}{'-' + tag if tag else ''}-{(when or datetime.now()):%m-%d-%Y}{ext}"


DEMO_SUFFIX = ''          # ' [DEMO]' while a demo runs on the virtual bench (virtualbench.VirtualMixin): every popup window says so
