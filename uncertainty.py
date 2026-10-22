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
    def dmm(self, kind, nominal, range_value=None, frequency=None, basis='generate'):
        """basis 'generate' (default): the CMC of the SOURCE that applies the stimulus (calibrator), which is how a DMM
        verification is performed. 'measure': the lab's measuring-instrument CMC. Kinds with no Generate entry
        (frequency) fall back to Measure."""
        kind = 'OHM' if kind in ('OHM2', 'OHM4') else kind
        entry = self.entries.get((basis, kind)) or self.entries.get(('measure', kind))
        if entry is None:
            return None
        if entry.get('basis') == 'generate':
            range_value = None            # Generate bands are by the generated value, never by the DMM range
        value = abs(nominal)
        if kind == 'ACV':
            return self._ac(entry, value, value, frequency, by_range=False)
        if kind == 'ACI':
            return self._ac(entry, value, value if range_value is None else range_value, frequency, by_range=range_value is not None)
        hits = [_u(b, value) for b in entry['bands'] if _inside(value, b['lo'], b['hi'])]
        return max(hits) if hits else None

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
            for row in block['rows']:
                if _inside(frequency, row['f_lo'], row['f_hi']):
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
    import ui_theme as ui
    number, symbol = ui.si_one(value, 'Ω' if unit == 'ohm' else unit, sig=sig)
    return f'{number} {symbol}'.replace('Ω', 'Ohm')
