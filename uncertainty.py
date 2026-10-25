"""Measurement uncertainty for calibration reports, from the laboratory's A2LA scope of accreditation.

    import uncertainty
    scope = uncertainty.load()                      # specs/a2la_1888_03_cmc.json (Applied Technical Services, A2LA 1888.03)
    u = scope.dmm('DCV', nominal=10, range_value=10)          # absolute, in volts, or None when the scope does not cover the point
    u = scope.dmm('ACV', nominal=1, range_value=1, frequency=1e3)
    u, unit, note = scope.oscilloscope('dcv', volts=0.05)     # see the method for each oscilloscope test

The value returned is the laboratory's CMC (expanded uncertainty, k ~ 2) for that point. Where a point lies exactly on the
boundary of two bands, the LARGER CMC is used. Points the scope does not cover return None; they are listed, never guessed.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / 'specs' / 'a2la_1888_03_cmc.json'


def load(path=DEFAULT):
    return Scope(json.loads(Path(path).read_text(encoding='utf-8')))


def _inside(value, lo, hi):
    """Closed interval: a value on the boundary of two bands matches both, and the larger CMC is used."""
    return lo <= value <= hi


def _temp_in(t, band, first_lo=None):
    """Thermocouple bands: printed '(> lo to hi)' (gt) = lower edge belongs to the band below; a band printed without '>' is a closed interval."""
    return band['lo'] < t <= band['hi'] if band.get('gt') else band['lo'] <= t <= band['hi']


def _src(source):
    """'5522A' / '5560A' from a calibrator model (text or a standard sheet), or None: which of the scope's calibrator-specific lines applies."""
    text = str(getattr(source, 'model', source) or '')
    return '5560A' if '5560' in text else '5522A' if ('5522' in text or '5520' in text) else None


def _tc_bands(entry, tc):
    """The bands of one thermocouple type of the TEMP entry (Type K when none is named)."""
    return (entry.get('types') or {}).get(tc or 'K') or ([] if entry.get('types') else entry['bands'])


def _in_row(frequency, row, first_lo, half_open=True):
    """A frequency row of an AC table is printed '(> lo to hi) Hz': the lower edge belongs to the row below, the upper edge to this row (only the
    lowest row of the block, 'lo to hi', includes its lower edge)."""
    if not half_open or row['f_lo'] == first_lo:
        return row['f_lo'] <= frequency <= row['f_hi']
    return row['f_lo'] < frequency <= row['f_hi']


def _u(band, reading, rng=0.0):
    return band['rel'] * abs(reading) + band['abs'] + band.get('rng', 0.0) * rng


class Scope:
    def __init__(self, data):
        self.data = data
        self.entries = {}
        for e in data['entries']:
            self.entries[(e.get('basis', 'measure'), e['kind'])] = e
        self.osc = data['oscilloscope']

    # ---- text for the report footer -----------------------------------------------------------
    @property
    def citation(self):
        d = self.data
        return (f"Uncertainty: laboratory CMC from the {d['accreditor']} scope of accreditation, certificate {d['certificate']} "
                f"(revised {d['revised']}), expanded uncertainty at approximately 95 % confidence (k = 2). "
                "Based on the laboratory's source (Generate) CMC for the applied stimulus; it does not include contributions from the unit under test.")

    # ---- measuring instruments (DMMs): value in the measurand's base unit ------------------------
    def dmm(self, kind, nominal, range_value=None, frequency=None, basis='generate', tc='K', source=None):
        """basis 'generate' (default): the CMC of the SOURCE that applies the stimulus (calibrator), which is how a DMM
        verification is performed. 'measure': the lab's measuring-instrument CMC. Kinds with no Generate entry
        (frequency) fall back to Measure."""
        kind = 'OHM' if kind in ('OHM2', 'OHM4') else kind
        entry = self.entries.get((basis, kind)) or self.entries.get(('measure', kind))
        if entry is None:
            return None
        if entry.get('basis') == 'generate':
            range_value = None            # Generate bands are by the generated value, never by the DMM range
        if kind == 'TEMP':      # signed bands in degC (the scope's thermocouple lines, Type K by default); None outside them (nothing is assumed)
            hits = [_u(b, 0.0) for b in _tc_bands(entry, tc) if _temp_in(nominal, b)]       # '(> lo to hi)' bands: an edge belongs to the lower band
            return max(hits) if hits else None
        value = abs(nominal)
        if kind == 'ACV':
            return self._ac(entry, value, value, frequency, by_range=False)
        if kind == 'ACI':
            return self._ac(entry, value, value if range_value is None else range_value, frequency, by_range=range_value is not None)
        src = _src(source)
        hits = [_u(b, value) for b in entry['bands'] if _inside(value, b['lo'], b['hi']) and (not src or b.get('src') in (None, src))]
        return max(hits) if hits else None

    def dmm_text(self, kind, nominal, range_value=None, frequency=None, basis='generate', tc='K', source=None):
        """The scope's own expression for the band that `dmm` uses, e.g. '8.9 µV/V + 0.8 µV' ('' when the scope does not cover the point).
        Rebuilt from the stored relative / absolute / range terms (the scope file keeps numbers, not the printed text): the relative term is shown per
        unit of the measurand (µV/V), the absolute term in the measurand's unit.  Display only: it never feeds a limit or an uncertainty."""
        kind = 'OHM' if kind in ('OHM2', 'OHM4') else kind
        entry = self.entries.get((basis, kind)) or self.entries.get(('measure', kind))
        if entry is None:
            return ''
        if kind == 'TEMP':
            hits = [b for b in _tc_bands(entry, tc) if _temp_in(nominal, b)]
            return f"{max(b['abs'] for b in hits):.2f} °C" if hits else ''
        if entry.get('basis') == 'generate':
            range_value = None
        unit = _SCOPE_UNIT.get(kind, '')
        value = abs(nominal)
        best = None
        if kind in ('ACV', 'ACI'):
            if frequency is None:
                return ''
            selector = value if (kind == 'ACV' or range_value is None) else range_value
            by_range = kind == 'ACI' and range_value is not None
            for block in entry['ranges']:
                if (block['lo'] <= selector <= block['hi']):
                    first = min(r['f_lo'] for r in block['rows'])
                    for row in block['rows']:
                        if _in_row(frequency, row, first):
                            u = _u(row, value, selector if by_range else 0.0)
                            if best is None or u > best[0]:
                                best = (u, row)
        else:
            src = _src(source)
            for b in entry['bands']:
                if _inside(value, b['lo'], b['hi']) and (not src or b.get('src') in (None, src)):
                    u = _u(b, value)
                    if best is None or u > best[0]:
                        best = (u, b)
        if best is None:
            return ''
        band = best[1]
        parts = []
        as_percent = kind in ('ACV', 'ACI', 'CAP')           # the AC tables are printed in % of reading (0.39 % + 80 nA); the DC ones per unit (8.9 µV/V + 0.8 µV)
        if band.get('rel'):
            parts.append(f"{float(band['rel']) * 100:.6g} %" if as_percent else _si_text(band['rel'], f'{unit}/{unit}' if unit else ''))
        if band.get('abs'):
            parts.append(_si_text(band['abs'], unit))
        if band.get('rng'):
            parts.append((f"{float(band['rng']) * 100:.6g} %" if as_percent else _si_text(band['rng'], f'{unit}/{unit}')) + ' of range')
        return ' + '.join(parts)

    def _ac(self, entry, value, selector, frequency, by_range):
        if frequency is None:
            return None
        out = []
        for block in entry['ranges']:
            if by_range:
                match = block['lo'] <= selector <= block['hi']
            else:
                match = selector >= block['lo'] and selector <= block['hi']
            if not match:
                continue
            first = min(r['f_lo'] for r in block['rows'])
            for row in block['rows']:
                if _in_row(frequency, row, first):
                    out.append(_u(row, value, selector if by_range else 0.0))
        return max(out) if out else None

    # ---- oscilloscopes -------------------------------------------------------------------------
    def oscilloscope(self, test, **k):
        """Returns (value, unit, note) or (None, '', reason).

        dcv / offset  volts=<applied DC level>, impedance='1M'|'50'  -> % of the applied level (gain) or volts (offset)
        impedance     ohms=<nominal>                                  -> ohms   (scope: Resistance - Measure)
        bandwidth     volts_pp=<amplitude>, frequency=<Hz>            -> dB     (scope: level sine flatness, 50 kHz reference)
        """
        if test in ('dcv', 'offset'):
            volts, imp = abs(k.get('volts', 0.0)), str(k.get('impedance', '1M'))
            band = next((b for b in self.osc['dc'] if b['impedance'] == imp), None)
            if band is None or volts > band['hi']:
                return None, '', 'outside the DC range of the scope'
            absolute = _u(band, volts)
            if test == 'offset' or volts == 0:
                return absolute, 'V', 'oscilloscope DC CMC'
            return 100.0 * absolute / volts, '%', 'oscilloscope DC CMC as a percentage of the applied level'
        if test == 'impedance':
            value = self.dmm('OHM', k['ohms'], basis='measure')
            return (value, 'ohm', 'Resistance - Measure CMC') if value is not None else (None, '', 'outside the resistance scope')
        if test == 'bandwidth':
            f, vpp = k['frequency'], k['volts_pp']
            hits = []
            for row in self.osc['flatness']:
                if _inside(f, row['f_lo'], row['f_hi']):
                    hits.append(row['rel'] + row['abs'] / vpp)
            if hits:
                return 20 * math.log10(1 + max(hits)), 'dB', 'oscilloscope level-sine flatness CMC converted to dB'
            return None, '', 'frequency outside the flatness scope'
        return None, '', 'no scope entry for this test (e.g. RMS noise)'


_SCOPE_UNIT = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'Ohm', 'CAP': 'F', 'FREQ': 'Hz'}


def _si_text(value, unit):
    """3 significant figures with the first SI prefix that gives 0.1 to 1000 (micro first, as the scope prints): 8.9 µV/V, 0.8 µV, 1.1 mOhm."""
    for prefix, scale in (('µ', 1e6), ('n', 1e9), ('m', 1e3), ('', 1.0), ('p', 1e12)):
        m = value * scale
        if 0.1 <= m < 1000:
            first, _, rest = unit.partition('/')
            return f'{m:.3g} {prefix}{first}' + (f'/{rest}' if rest else '')
    return f'{value:.3g} {unit}'


def round_up(value, sig=2):
    """Round a magnitude UP to `sig` significant figures. A reported uncertainty must never be smaller than the scope CMC or the budget,
    so every uncertainty shown on a report goes through this and never through round-to-nearest."""
    if not value or value <= 0:
        return 0.0
    step = 10 ** (math.floor(math.log10(value)) - sig + 1)
    out = round(math.ceil(round(value / step, 9)) * step, 15)
    return out if out >= value else value


def format_value(value, unit, sig=2):
    """Uncertainty text with SI prefix and two significant figures: 153 Ohm, 0.16 %, 40 µV.  Always rounded UP, never to nearest."""
    if value is None:
        return ''
    value = round_up(value, sig)
    if unit == '%':
        return f'{value:.{max(sig - 1 - int(math.floor(math.log10(abs(value)))), 0)}f} %' if value else '0 %'
    if unit == 'dB':
        return f'{value:.{max(sig - 1 - int(math.floor(math.log10(abs(value)))), 0)}f} dB' if value else '0 dB'
    if unit in ('C', 'degC', '\u00b0C'):       # temperatures are never SI-prefixed (no 'm\u00b0C'): 0.17 \u00b0C
        return f'{value:.{max(sig - 1 - int(math.floor(math.log10(abs(value)))), 0)}f} \u00b0C' if value else '0 \u00b0C'
    import ui_theme as ui
    number, symbol = ui.si_one(value, 'Ω' if unit == 'ohm' else unit, sig=sig)
    return f'{number} {symbol}'.replace('Ω', 'Ohm')
