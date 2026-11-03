"""Measurement uncertainty of the Fluke 6060A procedures' points (GIDEP T.O. 33K3-4-911-1 and the Instruction Manual), built from the published
specifications of the standards that MEASURE the generator (specs/standards: HP 8902A, Agilent 8563E sheets) and checked against the laboratory's
A2LA scope of accreditation (section XII Frequency - Measure in specs/a2la_1888_03_cmc.json; sections V / VI RF lines in specs/a2la_1888_03_rf.json).

    import fluke6060a_uncertainty as fu
    r = fu.evaluate(point, reading=None)      # reading None: the uncertainty at the point's nominal (or at its limit for one-sided limits)
    r.reported, r.unit                        # expanded uncertainty (k = 2) rounded UP to 2 figures, in the point's unit; None when not available
    r.scope                                   # 'in' / 'out' / 'undecided' (owner decision pending) / None
    r.status                                  # OK / NEEDS_INPUT / NEEDS_DECISION / NO_SPEC / NOT_APPLICABLE, with r.reason

Method (the suite's, uncertainty_budget.py): u = printed limit / coverage divisor of the standard's sheet (2 when no confidence level is printed),
RSS, EMU = 2 x RSS; reported = max(EMU, scope CMC) rounded UP when the scope covers the point, the EMU alone (marked 'not covered') when it does not.
Every assumption the budget makes is listed on the result (r.assumptions), never hidden. Nothing is extrapolated outside a printed row.

NOT wired into the report yet: the owner reviews the results first (2026-11-02). DECISIONS holds the owner's open choices (None = undecided).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import specmanager as sm
import uncertainty
from uncertainty_budget import ceil_sig

RF_SCOPE_PATH = Path(__file__).resolve().parent / 'specs' / 'a2la_1888_03_rf.json'

OK, NEEDS_INPUT, NEEDS_DECISION, NO_SPEC, NOT_APPLICABLE = 'OK', 'NEEDS INPUT', 'NEEDS DECISION', 'NO SPEC', 'N/A'
IN, OUT, UNDECIDED = 'in', 'out', 'undecided'

# Owner decisions still open (None = undecided). The review page lists them; nothing is assumed for them.
DECISIONS = {
    'scope.DEVMETER': None,     # deviation meter (6060A measures FM the 96270A generates): FM - Measure through footnote 9?  'in' / 'out'
    'scope.THD': None,          # AM distortion through the 8902A audio distortion: section V 'Distortion - Measure'?           'in' / 'out'
    'scope.RESFM': None,        # residual FM: FM - Measure 'Dev <= 4.0 kHz peak' line?                                         'in' / 'out'
    'rf_pct_basis': None,       # RF Power - Measure (-70 to -30) dBm '0.8 %': 'power' (of the power in W) / 'reading' (of the dBm reading)
}

AGING_MONTHS = 12               # 8902A internal time base aging (< 1E-6 / month) taken over a 12-month interval (assumption, listed on the result)


class Component:
    def __init__(self, name, limit, divisor, source):
        self.name, self.limit, self.divisor, self.source = name, float(limit), float(divisor), source

    @property
    def u(self):
        return self.limit / self.divisor

    def as_dict(self):
        return {'name': self.name, 'limit': self.limit, 'divisor': self.divisor, 'u': self.u, 'source': self.source}


class Result:
    def __init__(self, p, unit):
        self.point, self.unit = p, unit
        self.standard = ''
        self.components, self.assumptions = [], []
        self.status, self.reason = OK, ''
        self.cmc, self.scope, self.scope_text = None, None, ''
        self.cmc_if_in = None           # the CMC the scope line would give, for an UNDECIDED point
        self.evaluated_at = None        # the value the budget was worked out at (point unit)
        self.info = ''                  # extra text for the reviewer

    def add(self, name, limit, divisor, source):
        self.components.append(Component(name, limit, divisor, source))

    @property
    def emu(self):
        if not self.components:
            return None
        return 2.0 * math.sqrt(sum(c.u ** 2 for c in self.components))

    @property
    def value(self):
        if self.status != OK or self.emu is None:
            return None
        return max(self.emu, self.cmc or 0.0) if self.scope == IN else self.emu

    @property
    def reported(self):
        v = self.value
        return ceil_sig(v) if v else None

    @property
    def covered(self):
        return self.scope == IN

    def tur(self):
        """+/- tolerance / reported, for limits symmetric about the nominal only (one-sided dBc / residual limits and record-only rows have no TUR)."""
        p, r = self.point, self.reported
        if not r or p.get('low') is None or p.get('high') is None or p['high'] <= p['low']:
            return None
        below, above = p['nominal'] - p['low'], p['high'] - p['nominal']
        if below <= 0 or above <= 0 or abs(below - above) > 1e-6 * max(1.0, abs(p['nominal'])):
            return None
        return above / r

    def as_dict(self):
        return {'status': self.status, 'reason': self.reason, 'unit': self.unit, 'standard': self.standard, 'emu': self.emu, 'cmc': self.cmc,
                'cmc_if_in': self.cmc_if_in, 'scope': self.scope, 'scope_text': self.scope_text, 'reported': self.reported, 'tur': self.tur(),
                'evaluated_at': self.evaluated_at, 'components': [c.as_dict() for c in self.components], 'assumptions': list(self.assumptions), 'info': self.info}


# ------------------------------------------------------------------------------------------------------------------------------- standards sheets
def _standard(model, path=None):
    std = sm.standard(model, path)
    if std is None:                     # first use on this machine: load the shipped sheets into lab_registry.sqlite3 (as uncertainty_budget.build does)
        sm.seed(path=path)
        std = sm.standard(model, path)
    if std is None:
        raise LookupError(f'standards sheet {model} is not loaded')
    return std


def _rows(std, function, label=''):
    return [r for r in std.rows if function in r['function'] and label in r['label']]


def _spec(row, period):
    s = next((x for x in row['specs'] if x['period'] == period and not x.get('error')), None)
    if s is None:
        raise LookupError(f"{row['function']} / {row['label']}: no '{period}' specification")
    return s


def _one(std, function, label, period):
    rows = _rows(std, function, label)
    if len(rows) != 1:
        raise LookupError(f'{std.model}: {len(rows)} rows match {function!r} / {label!r} (expected 1)')
    return rows[0], _spec(rows[0], period)


def _qual(row, tag, value):
    q = [x for x in row.get('qualifiers') or [] if x['tag'].lower() == tag]
    return all(x['lo'] <= value <= x['hi'] for x in q)


def _cite(std, row):
    return f"{std.model} sheet: {row['function']} / {row['label']} (PDF p. {row['page']})"


# ------------------------------------------------------------------------------------------------------------------------------- the scope
_RF = None


def rf_scope():
    global _RF
    if _RF is None:
        _RF = {e['kind']: e for e in json.loads(RF_SCOPE_PATH.read_text(encoding='utf-8'))['entries']}
    return _RF


def _in_band(x, lo, hi, lo_open=False):
    return (lo < x if lo_open else lo <= x) and x <= hi


def scope_freq(hz):
    """Section XII Frequency - Measure (absolute Hz) or None."""
    e = uncertainty.load().entries.get(('measure', 'FREQ'))
    for b in (e or {}).get('bands', []):
        if b['lo'] <= hz <= b['hi']:
            return b['rel'] * hz + b['abs']
    return None


def _most_specific(hits):
    """Of the scope lines whose printed conditions all hold, the one with the narrowest modulation-rate band (the lines mirror the 8902A rows: the wider rate band carries
    the larger CMC, the same rule as the 8902A row choice); on a tie the larger CMC. hits: [(line, cmc)]."""
    return max(hits, key=lambda h: (-(h[0]['rate_hi'] - h[0]['rate_lo']), h[1]))[1] if hits else None


def scope_am(fc, rate, depth_pct):
    hits = [(b, b['pct']) for b in rf_scope()['AM']['bands']
            if b['f_lo'] <= fc <= b['f_hi'] and b['rate_lo'] <= rate <= b['rate_hi'] and b['depth_lo'] <= depth_pct <= b['depth_hi']]
    return _most_specific(hits)                 # % of reading


def scope_fm(fc, rate, dev_hz):
    hits = [(b, b['pct']) for b in rf_scope()['FM']['bands'] if b['f_lo'] <= fc <= b['f_hi'] and b['rate_lo'] <= rate <= b['rate_hi'] and dev_hz <= b['dev_max']]
    return _most_specific(hits)                 # % of reading


def scope_atten(fc, delta_db):
    e = rf_scope()['RFATTEN']
    if not (e['f_lo'] <= fc <= e['f_hi']):
        return None
    hits = [b['db'] for b in e['bands'] if b['db_lo'] <= delta_db <= b['db_hi']]
    return max(hits) if hits else None          # dB; on a shared edge the larger


def scope_rf_power(fc, level_dbm):
    """(CMC dB or None, line text) of RF Power - Measure; the '%' line needs DECISIONS['rf_pct_basis']."""
    for b in rf_scope()['RFPOWER']['bands']:
        if b['lv_lo'] <= level_dbm <= b['lv_hi'] and _in_band(fc, b['f_lo'], b['f_hi'], b.get('lo_open')):
            if 'db' in b:
                return b['db'], f"RF Power - Measure ({b['lv_lo']} to {b['lv_hi']}) dBm: {b['db']} dB"
            basis = DECISIONS['rf_pct_basis']
            text = f"RF Power - Measure ({b['lv_lo']} to {b['lv_hi']}) dBm: {b['pct']} % ({b['comment']})"
            if basis == 'power':
                return 10 * math.log10(1 + b['pct'] / 100.0), text + ' of the power'
            if basis == 'reading':
                return b['pct'] / 100.0 * abs(level_dbm), text + ' of the dBm reading'
            return None, text + ': basis of the % not decided'
    return None, ''


def scope_dist(tone_hz, thd_pct):
    db = 20 * math.log10(max(thd_pct, 1e-9) / 100.0)
    hits = [b['db'] for b in rf_scope()['DIST']['bands'] if b['f_lo'] <= tone_hz <= b['f_hi'] and b['db_lo'] <= db <= b['db_hi']]
    return max(hits) if hits else None          # dB of reading


def _set_scope(r, cmc, text, decision_key=None):
    """cmc None and no decision key: OUT. A decision key: the owner's choice (UNDECIDED until made)."""
    if decision_key:
        choice = DECISIONS.get(decision_key)
        r.cmc_if_in = cmc
        r.scope_text = text
        if choice == IN and cmc is not None:
            r.scope, r.cmc = IN, cmc
        elif choice == OUT:
            r.scope = OUT
        else:
            r.scope = UNDECIDED
        return
    if cmc is None:
        r.scope, r.scope_text = OUT, text or 'no line of the scope covers this measurement'
    else:
        r.scope, r.cmc, r.scope_text = IN, cmc, text


# ------------------------------------------------------------------------------------------------------------------------------- per point kind
def _freq_mhz(p):
    g = p.get('gen') or {}
    if g.get('freq_mhz') is not None:
        return float(g['freq_mhz'])
    m = re.search(r'at ([\d.]+) (kHz|MHz)', p.get('description', ''))
    return float(m.group(1)) * (1e-3 if m.group(2) == 'kHz' else 1.0) if m else None


def _at(p, reading, default):
    return float(reading) if reading is not None else float(default)


def evaluate(p, reading=None, path=None):
    """Uncertainty of one 6060A point (a spec point as fluke6060a_verification.flatten() makes it, or a raw spec point)."""
    func, meas = p.get('func'), p.get('meas')
    unit = {'kHz': 'kHz', 'Hz': 'Hz', '%': '%', 'dB': 'dB', 'dBm': 'dB', 'dBc': 'dB'}.get(p.get('unit'), p.get('unit') or '')
    r = Result(p, unit)
    if p.get('not_tested') or func == 'SELFTEST':
        r.status, r.reason = NOT_APPLICABLE, 'pass / fail self test' if func == 'SELFTEST' else 'not tested'
        return r
    try:
        handler = HANDLERS.get(func)
        if handler is None:
            r.status, r.reason = NO_SPEC, f'no uncertainty method for {func}'
            return r
        handler(r, p, reading, path)
    except LookupError as exc:
        r.status, r.reason = NO_SPEC, str(exc)
    return r


def _freq(r, p, reading, path):
    std = _standard('8902A', path)
    r.standard = 'HP 8902A frequency counter'
    fc = p['gen']['freq_mhz'] * 1e6
    res = float(p['rx']['resolution_hz'])
    limit = max(3 * res, 30.0) if fc >= 100e6 else 3 * res
    div, why = std.divisor()
    r.add('8902A frequency counter accuracy', limit, div,
          '8902A manual p. 1-21 (sheet note "Frequency Counter", not a sheet row): +/- reference accuracy +/- 3 counts of the least-significant digit'
          + (', or 30 Hz, whichever is larger (fc >= 100 MHz)' if fc >= 100e6 else '') + f'; {res:g} Hz resolution. Divisor {div:g} ({why})')
    r.assumptions.append('Reference accuracy term left out: in G-4.1b the 8902A runs on the 6060A\'s own 10 MHz (setup text), so the reference error is common to both and cancels.')
    r.evaluated_at = _at(p, reading, p['nominal'])
    cmc = scope_freq(r.evaluated_at)
    _set_scope(r, cmc, 'XII Frequency - Measure, 10 Hz to 26.5 GHz: 7.1 pHz/Hz')


def _reffreq(r, p, reading, path):
    r.status, r.reason = NO_SPEC, 'Typed counter reading: no counter specification on file (specs/standards/agilent_53131a_53132a_NOTE.txt)'
    _set_scope(r, scope_freq(p['nominal']), 'XII Frequency - Measure, 10 Hz to 26.5 GHz: 7.1 pHz/Hz')


def _modrate(r, p, reading, path):
    std = _standard('8902A', path)
    r.standard = 'HP 8902A audio frequency counter'
    rate = _at(p, reading, p['nominal'])
    r.evaluated_at = rate
    if rate > 1000.0 * 1.0001:
        raise LookupError('8902A audio counter: only the <= 1 kHz row is on the sheet')
    row, spec = _one(std, 'Audio Frequency Counter', 'demodulated signals, frequency <=1 kHz', 'spec')
    aging_row, aging = _one(std, 'Internal Time Base Reference [Aging]', 'standard: aging rate', '1 month')
    div, why = std.divisor()
    ref = aging['rel'] * AGING_MONTHS * rate if aging['rel'] else 1e-6 * AGING_MONTHS * rate
    r.add('8902A audio counter', spec['abs'], div, f'{_cite(std, row)}: +/-{spec["abs"]:g} Hz. Divisor {div:g} ({why})')
    r.add('8902A internal reference', ref, div, f'{_cite(std, aging_row)}: < 1E-6 / month x {AGING_MONTHS} months x {rate:g} Hz')
    r.assumptions.append(f'The 8902A is on its internal time base, aged {AGING_MONTHS} months since adjustment (the setup does not lock it to a reference for this step).')
    _set_scope(r, scope_freq(rate), 'XII Frequency - Measure, 10 Hz to 26.5 GHz: 7.1 pHz/Hz')


def _am_rows(std, fc, rate, depth_ratio):
    out = []
    for row in _rows(std, 'Modulation, AM [Accuracy]'):
        if row['freq_lo'] <= fc <= row['freq_hi'] and _qual(row, 'rate', rate) and row['amp_lo'] <= depth_ratio <= row['amp_hi']:
            out.append((row, _spec(row, 'spec')))
    return out


def _amdepth(r, p, reading, path):
    std = _standard('8902A', path)
    r.standard = 'HP 8902A AM'
    g = p['gen']
    fc = g['freq_mhz'] * 1e6
    resid = p['func'] == 'RESAM'
    x = _at(p, reading, p['high'] if resid else p['nominal'])          # % depth: residual AM at its limit when no reading
    r.evaluated_at = x
    rate = (g.get('am') or {}).get('rate_hz') or 1000.0                 # residual AM: no modulation; the 50 Hz - 15 kHz band, judged at 1 kHz
    if resid:
        _set_scope(r, None, 'Amplitude Modulation - Measure: no line for residual AM, and no AM line between 10 MHz and 1.3 GHz')
    else:
        pct = scope_am(fc, rate, x)
        _set_scope(r, None if pct is None else pct / 100.0 * x,
                   'Amplitude Modulation - Measure: no line covers this carrier (lines: 0.15-10 MHz, 1.3-26.5 GHz)' if pct is None else f'Amplitude Modulation - Measure: {pct} % of reading')
    if fc < 150e3:
        raise LookupError(f'8902A: carrier {fc / 1e3:g} kHz is below its 150 kHz RF input range: AM accuracy not specified')
    rows = _am_rows(std, fc, rate, x / 100.0)
    if not rows:
        raise LookupError(f'8902A AM accuracy: no row covers {fc / 1e6:g} MHz, rate {rate:g} Hz, depth {x:g} %')
    row, spec = min(rows, key=lambda t: t[1]['rel'])
    div, why = std.divisor()
    r.add('8902A AM accuracy', spec['rel'] * x, div, f'{_cite(std, row)}: +/-{spec["rel"] * 100:g} % of reading. Divisor {div:g} ({why})')
    if len(rows) > 1:
        r.assumptions.append(f'{len(rows)} overlapping AM rows cover this point; the tightest whose printed conditions are all met is used ({row["label"]}).')
    if (p.get('rx') or {}).get('detector') == 8:
        r.add('8902A rms detector', 0.03 * x, div, '8902A manual pp. 1-20/1-21 (sheet note): "For rms detector add +/-3 % of reading"')
    if resid:
        rrow, rspec = _one(std, 'Modulation, AM [Residual AM]', 'Residual AM', 'spec')
        r.add('8902A residual AM', rspec['abs'] * 100.0, div, f'{_cite(std, rrow)}: < 0.01 % rms (the receiver\'s own residual)')
    r.assumptions.append('The printed "+/- 1 digit" is not included (the sheet does not store the display resolution).')


def _thd(r, p, reading, path):
    if p.get('meas') != 'thd':
        r.status, r.reason = NO_SPEC, 'Typed distortion reading from the technician\'s own analyzer: no specification on file'
        return
    std = _standard('8902A', path)
    r.standard = 'HP 8902A audio distortion'
    g = p['gen']
    fc = g['freq_mhz'] * 1e6
    x = _at(p, reading, p['high'])
    r.evaluated_at = x
    tone = (p.get('rx') or {}).get('tone_hz') or 1000
    db = scope_dist(tone, x)
    _set_scope(r, None if db is None else x * (10 ** (db / 20.0) - 1), f'V Distortion - Measure, 20 Hz to 20 kHz: {db} dB (an audio distortion line, applied to demodulated AM)' if db else '', 'scope.THD')
    if fc < 150e3:
        raise LookupError(f'8902A: carrier {fc / 1e3:g} kHz is below its 150 kHz RF input range: demodulated distortion not specified')
    lbl = 'fundamental 1 kHz' if abs(tone - 1000) <= 50 else 'fundamental 400 Hz'
    row, spec = _one(std, 'Audio Distortion', f'Audio distortion accuracy, {lbl}', 'spec')
    rrow, rspec = _one(std, 'Audio Distortion', f'residual noise and distortion, {lbl}', 'spec')
    depth = (g.get('am') or {}).get('pct', 50)
    drow, dspec = _one(std, 'Modulation, AM [Demodulated Output Distortion]', 'depth <=50 %' if depth <= 50 else 'depth <=95 %', 'spec')
    div, why = std.divisor()
    r.add('8902A distortion accuracy', x * (10 ** (spec['abs'] / 20.0) - 1), div, f'{_cite(std, row)}: +/-{spec["abs"]:g} dB of reading = {(10 ** (spec["abs"] / 20) - 1) * 100:.1f} % of reading. Divisor {div:g} ({why})')
    r.add('8902A distortion residual', rspec['abs'] * 100.0, div, f'{_cite(std, rrow)}: {rspec["abs"] * 100:g} % (the analyzer\'s own noise and distortion)')
    r.add('8902A AM demodulator distortion', dspec['abs'] * 100.0, div, f'{_cite(std, drow)}: < {dspec["abs"] * 100:g} % THD')


def _fm_rows(std, fc, rate, dev):
    out = []
    for row in _rows(std, 'Modulation, FM [Accuracy]'):
        if row['freq_lo'] <= fc <= row['freq_hi'] and _qual(row, 'rate', rate) and row['amp_lo'] <= dev <= row['amp_hi']:
            out.append((row, _spec(row, 'spec')))
    return out


def _fmdev(r, p, reading, path):
    std = _standard('8902A', path)
    g = p['gen']
    fc = g['freq_mhz'] * 1e6
    if p['func'] == 'RESFM':
        r.standard = 'HP 8902A FM'
        x = _at(p, reading, p['high'])
        r.evaluated_at = x
        f_mhz = g['freq_mhz']
        rows = _rows(std, 'Modulation, FM [Residual FM]')
        resid = 1.0 if f_mhz <= 100 else 1.0 + (8.0 - 1.0) * (f_mhz - 100.0) / 1200.0
        r.status = NEEDS_DECISION
        r.reason = ('8902A residual FM is printed in Hz RMS over a 50 Hz - 3 kHz band; the GIDEP limit is PEAK over 20 Hz - 23 kHz (this procedure: 50 Hz - >20 kHz). '
                    'There is no printed way to convert one into the other.')
        r.info = (f'For reference: 8902A residual FM at {f_mhz:g} MHz = {resid:.2f} Hz rms (printed < 8 Hz at 1300 MHz, linear to < 1 Hz at 100 MHz; '
                  f'{len(rows)} sheet rows); 8902A FM accuracy 1 % of reading = {0.01 * x:g} Hz at {x:g} Hz.')
        _set_scope(r, 0.059 * x, 'Frequency Modulation - Measure, Dev <= 4.0 kHz peak, 0.02-1.3 GHz: 5.9 %', 'scope.RESFM')
        return
    r.standard = 'HP 8902A FM'
    rate = (g.get('fm') or {}).get('rate_hz') or 1000.0
    x = _at(p, reading, p['nominal'])
    r.evaluated_at = x
    pct = scope_fm(fc, rate, x)
    _set_scope(r, None if pct is None else pct / 100.0 * x, f'Frequency Modulation - Measure: {pct} % of reading' if pct else 'Frequency Modulation - Measure: no line (deviation above 40 kHz below 10 MHz)')
    rows = _fm_rows(std, fc, rate, x)
    if not rows:
        raise LookupError(f'8902A FM accuracy: no row covers {fc / 1e6:g} MHz, rate {rate:g} Hz, deviation {x / 1e3:g} kHz (rows: <= 40 kHz below 10 MHz)')
    row, spec = min(rows, key=lambda t: t[1]['rel'])
    div, why = std.divisor()
    r.add('8902A FM accuracy', spec['rel'] * x, div, f'{_cite(std, row)}: +/-{spec["rel"] * 100:g} % of reading. Divisor {div:g} ({why})')
    if len(rows) > 1:
        r.assumptions.append(f'{len(rows)} overlapping FM rows cover this point; the tightest whose printed conditions are all met is used ({row["label"]}).')
    r.assumptions.append('The printed "+/- 1 digit" is not included (the sheet does not store the display resolution).')


TUNED_RES_DB = 0.01             # tuned RF level display resolution in dB (assumption, listed)


def _if_changes(delta):
    """(number of IF range changes, ranges) for a change of `delta` dB: one IF range per 10 dB (assumption); the first four at the 'ranges 1 through 5'
    figure, the rest at the 'ranges 6 and 7' figure (the most sensitive ranges hold the lowest levels; assumption)."""
    n = int(math.floor(delta / 10.0 + 1e-9))
    return min(n, 4), max(0, n - 4)


def _level_rel(r, p, reading, path):
    std = _standard('8902A', path)
    r.standard = 'HP 8902A tuned RF level (relative)'
    f_mhz = _freq_mhz(p)
    fc = (f_mhz or 0) * 1e6
    delta = abs(float(p['nominal']))
    r.evaluated_at = float(p['nominal'])
    cmc = scope_atten(fc, delta)
    _set_scope(r, cmc, f'RF Attenuation - Measure, 10 MHz to 1.3 GHz: {cmc} dB' if cmc is not None else
               ('RF Attenuation - Measure: covers 0 to 120 dB only' if delta > 120 else 'RF Attenuation - Measure: covers 10 MHz to 1.3 GHz only'))
    if fc < 150e3:
        raise LookupError(f'8902A: carrier {fc / 1e3:g} kHz is below its 150 kHz RF input range: tuned RF level not specified')
    div, why = std.divisor()
    lin_row, lin = _one(std, 'Tuned RF Level [Relative', 'Detector linearity, IF synchronous detector', 'spec')
    per10 = _spec(lin_row, 'spec, per 10 dB')['abs']
    lin_limit = min(lin['abs'] * delta, per10) if delta <= 10 else per10 * delta / 10.0
    r.add('8902A detector linearity (sync)', lin_limit, div,
          f'{_cite(std, lin_row)}: +/-{lin["abs"]:g} dB/dB, not more than +/-{per10:g} dB per 10 dB change -> {lin_limit:.3g} dB over {delta:g} dB. Divisor {div:g} ({why})')
    n15, n67 = _if_changes(delta)
    if n15:
        row, s = _one(std, 'Tuned RF Level [Relative', 'IF range-to-range error, IF ranges 1 through 5', 'spec')
        for i in range(n15):
            r.add(f'8902A IF range change {i + 1}', s['abs'], div, f'{_cite(std, row)}: +/-{s["abs"]:g} dB per IF range change')
    if n67:
        row, s = _one(std, 'Tuned RF Level [Relative', 'IF range-to-range error, IF ranges 6 and 7', 'spec')
        for i in range(n67):
            r.add(f'8902A IF range change {n15 + i + 1}', s['abs'], div, f'{_cite(std, row)}: +/-{s["abs"]:g} dB per IF range change')
    n_rf = 1 if delta <= 10 else 2
    row, s = _one(std, 'Tuned RF Level [Relative', 'RF range-to-range error, Tuned RF Level only', 'spec')
    for i in range(n_rf):
        r.add(f'8902A RF range change {i + 1} (RECAL)', s['abs'], div, f'{_cite(std, row)}: +/-{s["abs"]:g} dB per RF range change')
    if float(p['nominal']) < -120:
        row, s = _one(std, 'Tuned RF Level [Relative', 'Noise error, levels below -120 dBm', 'spec')
        r.add('8902A noise error', s['abs'], div, f'{_cite(std, row)}: +/-{s["abs"]:g} dB below -120 dBm')
    r.add('Display resolution', TUNED_RES_DB, math.sqrt(12), f'{TUNED_RES_DB:g} dB / sqrt(12) (resolution assumed, not on the sheet)')
    r.assumptions += [
        'No Option 050 (owner, 2026-11-02): the relative-accuracy COMPONENTS of p. 1-24 are combined (RSS of limit / 2), not the Option 050 figure.',
        'Range structure (UNVERIFIED, not printed on the sheet): one IF range change per 10 dB of level change (the first four at the ranges 1-5 figure, the rest at '
        'the ranges 6-7 figure) and two RF range changes (RECAL) for any change above 10 dB, one for 10 dB.',
        'Left out: frequency drift error (0.05 dB/kHz; the 6060A and 8902A share the reference, drift taken as 0), the 6060A output mismatch change between levels '
        '(no 6060A output SWR on file), and the repeatability of the reference reading.',
    ]


def _level(r, p, reading, path):
    f_mhz = _freq_mhz(p)
    fc = (f_mhz or 0) * 1e6
    lv = float(p['gen']['level_dbm'])
    r.evaluated_at = lv
    cmc, text = scope_rf_power(fc, lv)
    if p['meas'] == 'level_pm':
        r.standard = 'Fluke 96270A + R&S NRP40T (power meter)'
        r.status, r.reason = NO_SPEC, 'No NRP40T sheet and no 96270A power-meter readout specification on file'
    elif (p.get('rx') or {}).get('mode') == 'power':
        r.standard = 'HP 8902A RF power (11722A sensor)'
        r.status = NEEDS_INPUT
        r.reason = ('Needs the 11722A sensor\'s cal-factor uncertainty at this frequency (its calibration certificate) and the 6060A output SWR (mismatch). '
                    'On the sheet: power reference 1.2 %, range linearity 0.02 dB, range-to-range 0.02 dB, sensor SWR 1.15.')
    elif fc < 150e3:
        r.standard = 'HP 8902A tuned RF level'
        r.status, r.reason = NO_SPEC, f'8902A: carrier {fc / 1e3:g} kHz is below its 150 kHz RF input range: tuned RF level not specified'
    else:
        r.standard = 'HP 8902A tuned RF level (absolute)'
        r.status = NEEDS_INPUT
        r.reason = ('Absolute tuned level = the RF power reference (11722A cal-factor uncertainty and 6060A output SWR needed) + 0.06 dB (RF power to tuned level) '
                    '+ the relative terms. Recorded rows only (limits -140 to +5 dBm); the judged Table 5 rows are the relative ones.')
    if p['meas'] == 'level_pm' or fc >= 150e3 or (p.get('rx') or {}).get('mode') == 'power':
        if cmc is not None:
            r.scope, r.cmc, r.scope_text = IN, cmc, text
        elif text:
            r.scope, r.scope_text = UNDECIDED, text
        else:
            r.scope, r.scope_text = OUT, 'RF Power - Measure: covers -70 to +20 dBm (and -70 to -30 dBm from 10 MHz) only'
    else:
        r.scope, r.scope_text = OUT, 'RF Power - Measure: -70 to -30 dBm starts at 10 MHz' if lv < -30 else text


def _devmeter(r, p, reading, path):
    r.standard = 'Fluke 96270A FM output'
    r.status, r.reason = NO_SPEC, 'The 96270A sheet has no FM deviation accuracy row (Operator Manual FM specifications not transcribed)'
    m = re.search(r'meter ([\d.]+) MHz, rate (\d+) Hz, ([\d.]+) kHz', p.get('description', ''))
    if m:
        fc, rate, dev = float(m.group(1)) * 1e6, float(m.group(2)), float(m.group(3)) * 1e3
        pct = scope_fm(fc, rate, dev)
        _set_scope(r, None if pct is None else pct / 100.0 * dev / 1e3, f'Frequency Modulation - Measure via footnote 9: {pct} % of reading' if pct else '', 'scope.DEVMETER')


# ---- 8563E: relative amplitude (dBc) ----------------------------------------------------------------------------------------------------------
SA_PERIOD = '2 yr'


def _sa_settings(p):
    """(ref level, attenuation, carrier rbw, signal rbw, frequencies seen) exactly as fluke6060a_verification._harmonic / _spur set the 8563E."""
    g = p['gen']
    level = g['level_dbm']
    ref, att = (20.0, 30) if level > 7 else (10.0, 20)
    f = g['freq_mhz'] * 1e6
    if p['meas'] == 'harmonic':
        span = min(1e6, f / 4.0)
        rbw = 30e3 if span >= 1e6 else 3e3
        return ref, att, rbw, rbw, [f * n for n in range(1, p['sa']['n_max'] + 1)]
    s = p['sa']
    c_rbw = 30e3 if f >= 4e6 else 3e3
    span = min(max(s['target_hz'] / 2.0, 10e3), 2e6) if s['kind'] == 'off' else 1e6
    s_rbw = 1e3 if span <= 20e3 else 3e3 if span <= 300e3 else 30e3
    freqs = [f] + ([f - s['target_hz'], f + s['target_hz']] if s['kind'] == 'off' else [s['target_hz']])
    return ref, att, c_rbw, s_rbw, freqs


def _dbc(r, p, reading, path):
    if p['meas'] == 'manual':
        r.standard = 'typed reading'
        r.status, r.reason = NO_SPEC, 'Typed reading (no instrument is named for it): no specification to build a budget from'
        _set_scope(r, None, 'no line of the scope covers harmonics or spurious (dBc)')
        return
    std = _standard('8563E', path)
    r.standard = 'Agilent 8563E'
    g = p['gen']
    ref, att, c_rbw, s_rbw, freqs = _sa_settings(p)
    h = _at(p, reading, p['high'])                                 # dBc; at the limit when there is no reading
    r.evaluated_at = h
    div, why = std.divisor()
    if not all(9e3 <= f <= 2.9e9 for f in freqs):
        raise LookupError('8563E: a frequency of this point is outside 9 kHz - 2.9 GHz (band switching not handled)')
    row, s = _one(std, 'Flatness [Frequency Response, Relative', '9 kHz to 2.9 GHz (Non-Option 006)', SA_PERIOD)
    r.add('8563E relative frequency response', s['abs'], div, f'{_cite(std, row)}: +/-{s["abs"]:g} dB ({SA_PERIOD}). Divisor {div:g} ({why})')
    depth = ref - (g['level_dbm'] + h)
    row, s = _one(std, 'Scale Fidelity [LOG, Cumulative', '0 to -90 dB range, RES BW >= 300 Hz', SA_PERIOD)
    if depth > 90:
        r.assumptions.append(f'The signal is {depth:.0f} dB below the reference level: scale fidelity is specified to -90 dB only; the 0 to -90 dB figure is used.')
    r.add('8563E log scale fidelity', s['abs'], div, f'{_cite(std, row)}: +/-{s["abs"]:g} dB maximum')
    if c_rbw != s_rbw:
        row, s = _one(std, 'Amplitude Uncertainty [Resolution Bandwidth Switching', 'Referenced to 300 kHz', SA_PERIOD)
        r.add('8563E RBW switching', s['abs'], div, f'{_cite(std, row)}: +/-{s["abs"]:g} dB (carrier {c_rbw / 1e3:g} kHz, signal {s_rbw / 1e3:g} kHz RBW)')
    mixer = g['level_dbm'] - att
    if p['meas'] == 'harmonic':
        f0 = g['freq_mhz'] * 1e6
        rows = [x for x in _rows(std, 'Spurious Responses [Second Harmonic', 'serial prefix <3645A') if x['freq_lo'] <= f0 <= x['freq_hi']]
        if rows:
            row = rows[0]
            s = _spec(row, SA_PERIOD)
            ref_mixer = row['amp_lo']
            d2 = s['abs'] + (mixer - ref_mixer)                     # second harmonic distortion rises 1 dB per dB of mixer level
            err = 20 * math.log10(1 + 10 ** ((d2 - h) / 20.0))
            r.add('8563E own second harmonic', err, div,
                  f'{_cite(std, row)}: {s["abs"]:g} dBc at {ref_mixer:g} dBm mixer -> {d2:.0f} dBc at {mixer:g} dBm mixer ({g["level_dbm"]:g} dBm, {att} dB attenuation); '
                  f'in-phase worst case on a {h:g} dBc reading: {err:.2f} dB')
            r.assumptions.append('Second harmonic: serial prefix unknown, the older (< 3645A, -72 dBc) row is used. The analyzer\'s own 3rd / 4th harmonics are not specified.')
        else:
            r.assumptions.append(f'No 8563E second-harmonic row at {f0 / 1e6:g} MHz (rows from 1 MHz): the analyzer\'s own harmonic is not included.')
    else:
        row, s = _one(std, 'Spurious Responses [Image, Multiple', 'mixer level -10 dBm', SA_PERIOD)
        err = 20 * math.log10(1 + 10 ** ((s['abs'] - h) / 20.0))
        r.add('8563E own spurious responses', err, div, f'{_cite(std, row)}: {s["abs"]:g} dBc at -10 dBm mixer (here {mixer:g} dBm); on a {h:g} dBc reading: {err:.2f} dB')
    r.assumptions.append('Same reference level and input attenuation for the carrier and the signal (as the program sets them): no IF gain / attenuator terms.')
    _set_scope(r, None, 'no line of the scope covers harmonics or spurious (dBc)')


HANDLERS = {'FREQ': _freq, 'REFFREQ': _reffreq, 'MODRATE': _modrate, 'AMDEPTH': _amdepth, 'RESAM': _amdepth, 'THD': _thd,
            'FMDEV': _fmdev, 'RESFM': _fmdev, 'LEVEL': _level, 'LEVEL_REL': _level_rel, 'DEVMETER': _devmeter, 'HARMONIC': _dbc, 'SPUR': _dbc}


def format_value(r):
    """'0.15 dB', '31 Hz', '0.75 %'; '' when there is none."""
    v = r.reported
    if not v:
        return ''
    return f'{v:g} {r.unit}'.strip()
