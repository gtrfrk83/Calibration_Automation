"""Shared engine of the Keysight Truevolt DMM standards builders (build_34461a_standard.py, build_34465a_standard.py).

Not run by itself.  Each model builder holds its own printed tables (one transcription per model, read from the rendered page images) and calls
build(cfg) / main(cfg).  The row construction reuses the helpers of build_3458a_standard.py (make_spec, make_range, amp_param, ...), so a Truevolt sheet has the
same stored form as the 3458A sheet: a bipolar value range per range name, 'rel' = % of reading, 'fs_rel' x 'fs_value' = % of range against the range NAME,
direction 'input' (the DMM measures), AC rows carry the frequency band, periods are free text.

SOURCE of both sheets: Keysight 'Digital Multimeters 34460A, 34461A, 34465A (6 1/2 digit), 34470A (7 1/2 digit)' data sheet 5991-1983EN, published USA
June 10, 2026 (PDF, 28 pages; the printed page numbers equal the PDF page numbers): 34461A specifications pp. 13-14, 34465A specifications pp. 15-17.

PERIODS stored: '90 day', '1 yr', '2 yr' (free text period labels, the repository's convention; '2 yr' is simply a third label, no schema change).  The printed 24 hour
column is NOT stored (the owner asked for 90 day / 1 year / 2 year).  The default period of every sheet is '1 yr' (StandardSpec.period defaults to '1 yr'), so the plain
lookup used by the uncertainty assignment (specmanager.StandardSpec.lookup, tartur.standard_accuracy, uncertainty_budget.build) returns the 1 year figure.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402
from build_3458a_standard import (amp_param, freq_param, hz_text, make_range, make_spec, make_spec_pct, num, si_range_text, split_terms)  # noqa: E402,F401

PERIODS = ['90 day', '1 yr', '2 yr']
SOURCE_PDF = 'Digital_Multimeters_34460A_34461A_34465A_6__digit_34470A_7__digit.pdf'
PUBLICATION = '5991-1983EN'
REVISION = '5991-1983EN (published in USA, June 10, 2026)'
CONFIDENCE_TEXT = ('95 % (k = 2): the data sheet prints "These specifications are compliant to ISO/IEC 17025 for k = 2" at the head of each model\'s specification '
                   'table (5991-1983EN printed p. 13 for the 34461A, p. 15 for the 34465A); it prints no percentage, so 95 % is the coverage probability that goes with k = 2')

HZ_SYM = {'Hz': 1, 'kHz': 1000}


def _fsd(x):
    return D(x)


def dc_function(name, kind, unit, page, rows, notes_fn, label_unit_text):
    """rows: (range name text, range name SI, full scale text, (90 day, 1 yr, 2 yr) cells 'reading + range' in percent, typical flag)."""
    f = dict(name=name, direction='input', page=page, ranges=[])
    for rname, rsi, fs, cells, typical in rows:
        specs = []
        for per, cell in zip(PERIODS, cells):
            reading, _o, rng = split_terms(cell)
            specs.append(make_spec_pct(per, reading, rng, rname, D(rsi)))
        fsd = D(fs)
        label = f'{rname} range' + (' (typical)' if typical else '')
        txt = f'-{si_range_text(fsd, label_unit_text)} to {si_range_text(fsd, label_unit_text)}' if label_unit_text != 'ohm' else f'-{si_range_text(fsd, "ohm")} to {si_range_text(fsd, "ohm")}'
        f['ranges'].append(make_range(name, label, rname, kind, [amp_param(fs, unit, txt, notes=notes_fn(rname, typical))], specs, page))
    return f


def ohm_variant(name, page, rows, notes_fn, extra_abs=None, skip=()):
    """Resistance rows; extra_abs = 0.2 (ohm) for the 2-wire function without math null; skip = range names left out."""
    f = dict(name=name, direction='input', page=page, ranges=[])
    for rname, rsi, fs, cells, typical in rows:
        if rname in skip:
            continue
        specs = []
        for per, cell in zip(PERIODS, cells):
            reading, _o, rng = split_terms(cell)
            specs.append(make_spec(per, reading + '%', rng, rname, D(rsi), range_pct=True, abs_term=extra_abs, abs_unit='ohm' if extra_abs else ''))
        fsd = D(fs)
        f['ranges'].append(make_range(name, f'{rname} range', rname, 'OHM', [amp_param(fs, 'ohm', f'-{si_range_text(fsd, "ohm")} to {si_range_text(fsd, "ohm")}',
                                                                                        notes=notes_fn(rname, typical))], specs, page))
    return f


def ac_function(name, kind, unit, page, ranges, bands, notes, label_unit_text):
    """ranges: (range name text, range name SI, full scale text); bands: (lo Hz, hi Hz, label suffix, (3 cells), typical flag, hi_for_lookup)."""
    f = dict(name=name, direction='input', page=page, ranges=[])
    for rname, rsi, fs in ranges:
        fsd = D(fs)
        for lo, hi, suffix, cells, typical in bands:
            specs = []
            for per, cell in zip(PERIODS, cells):
                reading, _o, rng = split_terms(cell)
                specs.append(make_spec_pct(per, reading, rng, rname, D(rsi)))
            label = f'{rname} range @ {hz_text(lo)} to {hz_text(hi)}' + (f' ({suffix})' if suffix else '')
            f['ranges'].append(make_range(name, label, rname, kind,
                                          [amp_param(fs, unit, f'-{si_range_text(fsd, label_unit_text)} to {si_range_text(fsd, label_unit_text)}', notes=notes), freq_param(lo, hi)],
                                          specs, page, freq=(float(D(repr(float(lo)))), float(D(repr(float(hi)))))))
    return f


def freq_function(name, page, bands, notes):
    """bands: (lo Hz, hi Hz, label text, (3 percent-of-reading strings))."""
    f = dict(name=name, direction='input', page=page, ranges=[])
    for lo, hi, text, vals in bands:
        specs = [make_spec(per, v + '%', None, '', D(0)) for per, v in zip(PERIODS, vals)]
        param = dict(tag='', lo=float(D(repr(float(lo)))), hi=float(D(repr(float(hi)))), unit='Hz', text=f'{hz_text(lo)} to {hz_text(hi)}', annot='', notes=list(notes))
        f['ranges'].append(make_range(name, text, text, 'FREQ', [param], specs, page))
    return f


def build(cfg):
    model = cfg['model']
    functions = cfg['functions']()
    data = dict(schema=1, standard=dict(
        manufacturer='Keysight Technologies (Agilent)', model=model, description=cfg['description'],
        confidence_text=CONFIDENCE_TEXT, confidence_pct=95.0,
        reference=cfg['reference'], revision=REVISION,
        author=f'written by specs/{cfg["builder"]} from the rendered page images of the data sheet' + ('' if cfg['verified'] else ' (UNVERIFIED against the rendered pages)'),
        approved_by='', approve_date='', source_pdf=SOURCE_PDF, sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=cfg['notes'], limits=cfg['limits'], functions=functions)
    probs = list(sm.validate_data(data))
    if not cfg['verified']:
        probs.append(dict(level='warn', where='standard', what='UNVERIFIED against the rendered pages: re-read the tables from page images and rebuild.'))
    probs.extend(cfg['problems'])
    data['problems'] = probs
    return data


def main(cfg):
    data = build(cfg)
    out = HERE / 'standards' / cfg['json']
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    errs = [p for p in data['problems'] if p['level'] == 'error']
    print(f"{cfg['model']}: {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} flagged ({len(errs)} errors) -> {out}")
    for f in data['functions']:
        print(f"  {f['name']}: {len(f['ranges'])} rows")
    for p in data['problems']:
        print(p['level'].upper(), p['where'], '-', p['what'][:160])


def common_notes(model, pages, scope_text, default_check):
    """Notes shared by both sheets (numbered 1-8); the model builder adds its own from 9 on."""
    return {
        '1': f'SOURCE: Keysight Digital Multimeters 34460A, 34461A, 34465A (6 1/2 digit), 34470A (7 1/2 digit) data sheet {PUBLICATION}, published in USA June 10, 2026 (PDF of 28 pages, '
             f'supplied by the owner as {SOURCE_PDF}; printed page numbers equal the PDF page numbers). {model} specifications: {pages}. Built by the specs builder of this model '
             '(shared engine specs/build_truevolt_standard.py).',
        '2': 'VERIFICATION: every stored number was read from RENDERED PAGE IMAGES (pdftoppm, 150 dpi for the whole page and 250 dpi for a crop of each table), never from the extracted '
             'text, and each stored table was read twice (whole page, then the crop); the two readings agree. The independent second transcription is in the model\'s test file. '
             'Read once only (information in the notes, no lookup uses them): temperature coefficients, gate-time errors, burden voltages, the temperature / continuity / diode / DC ratio lines.',
        '3': 'CONFIDENCE LEVEL: the data sheet prints "These specifications are compliant to ISO/IEC 17025 for k = 2" at the head of the specification table, and "specifications include '
             'measurement uncertainty and were created in compliance with ISO-17025" (p. 28). It prints NO percentage. Stored as confidence_pct 95.0 (k = 2, the coverage probability that '
             'belongs to k = 2; repository rule: 95 % -> divisor 2.0, see NOTES.md "Confidence level rule"). The inference k = 2 -> 95 % is the repository\'s, not a printed figure: FLAG.',
        '4': 'PERIODS: "90 day", "1 yr" and "2 yr" are stored (three period labels in the free-text period field; no schema change). The printed 24 hour column (relative to calibration standards, '
             'footnote 3) is NOT stored. Conditions of the stored columns: 90 day / 1 year / 2 year at the TCAL +/- 5 degC the table heads print' + scope_text,
        '5': 'DEFAULT PERIOD = "1 yr" (owner: the uncertainty assignment uses the 1 year column). StandardSpec.period defaults to "1 yr" for this sheet, so the plain lookup used by the budget '
             f'(specmanager lookup, tartur.standard_accuracy, uncertainty_budget.build) returns the 1 year figure; {default_check} The 90 day and 2 year figures are reachable with period="90 day" / "2 yr". '
             'A test (tests/test_standard_' + model.lower() + '.py) fails if the default lookup stops returning the 1 yr figure.',
        '6': 'ACCURACY FORM: +/-(% of reading + % of range). The data sheet does not define "range" for the % of range term; it is taken against the range NAME (100 mV range -> 0.1 V, 10 V -> 10 V, '
             '1 kohm -> 1000 ohm, 100 uA -> 1e-4 A), the Keysight convention and the one the 3458A sheet follows; UNVERIFIED for these data sheets. The value range of each row runs from -full scale to +full '
             'scale; footnote 2 of the data sheet: the ranges run 20 % over range (full scale 120 mV, 1.2 V, 12 V, 120 V, 120 ohm ... 1.2 uA ... 1.2 A, 1.2 nF ... 120 uF) EXCEPT 1000 V DC, 750 V AC, '
             'the 3 A and 10 A current ranges and the diode test (0 %): those rows end at the range name itself (1000 V, 750 V, 3 A, 10 A).',
        '7': 'DIRECTION: "input" - the DMM measures (same as the 3458A, 5790B, 8563E and 8902A sheets). specmanager.StandardSpec.lookup defaults to direction "output" and the budget '
             '(uncertainty_budget.build) must be asked with direction "input"; tartur.standard_accuracy has the argument. The Datasheet Builder matcher uses the row direction itself.',
        '8': 'RESOLUTION: no row carries a resolution (the specification tables print none; reading resolution depends on the aperture / NPLC setting). The budget therefore has NO resolution term '
             'for this standard; the Standards Specs tab can record one. Reading noise, the gate-time errors and the temperature coefficients are NOT in any stored row.',
    }
