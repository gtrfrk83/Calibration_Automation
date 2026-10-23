"""Builds specs/standards/a2la_5500a_coil_standard.json: the laboratory's own A2LA scope CMC lines that belong to the Fluke 5500A/COIL (50-turn current coil), as a standards sheet.

    python specs/build_coil_standard.py            # writes specs/standards/a2la_5500a_coil_standard.json

SOURCE: Calibration Scope of Accreditation, A2LA certificate 1888.03 (revised 07/07/2026), section V. Electrical - DC/Low Frequency ('1888-03.pdf', 47 printed pages):
  p. 9 of 47   'DC Current - Generate', the last block (column header "Parameter/Equipment | Range | CMC 2, 5, 9 (+/-) | Comments"; NO frequency column, this is DC):
                   (2 to 20) A       90 uA/A + 0.1 mA      comment: Transconductance amplifier/coil
                   (20 to 120) A     80 uA/A + 8 mA
                   (120 to 3000) A   0.8 % + 0.08 A
  p. 30 of 47  'AC Current - Generate (cont)', the last lines (column header "Parameter/Range | Frequency | CMC 2, 5, 9 (+/-) | Comments"):
                   Clamp-On Only
                   (20.5 to 1025) A  (45 to 65) Hz         0.8 %      comment: Multifunction calibrator/coil
                                     (65 to 440) Hz        0.99 %
  (The AC rows printed just above the Clamp-On Only lines on p. 30, (20.5 to 3000) A, (16 to 850) Hz 0.7 % + 0.84 A and (0.85 to 6) kHz 0.8 % + 0.84 A, comment
  'Transconductance amplifier/coil', were NOT asked for and are not stored: see NOTES.md.)
Footnotes used (p. 46-47): 2 (CMC = the smallest uncertainty the lab can achieve; expanded uncertainty at approximately the 95 % level of confidence, usually k = 2),
5 (the first percentage is a percentage of the reading unless otherwise noted; the second percentage or fraction is of the range), 9 (the stated values are determined
using the indicated instrument (see Comments); CMCs are a specific value or a percent or fraction of the reading plus a fixed floor specification).

VERIFICATION STATUS: VERIFIED against the rendered pages.  Pages 9 and 30 of 47 were rendered with pdftoppm and every value below was read from the images, twice
(full page at 130 dpi, then a 200 dpi crop of the coil lines), on 2026-10-23.  The extracted text was only used to locate the pages.  Both pages carry
"(A2LA Cert. No. 1888.03) Revised 07/07/2026".  Set VERIFIED_AGAINST_IMAGE = False if the scope is revised until the new pages have been read the same way.
The coil's own datasheet (Fluke '5500A/COIL | 50-Turn Current Coil' technical data, 4 pages, 10/2026, rendered and read from the images) supplies the facts in note 7.

Storage: one row per scope range.  A CMC has no 90 day / 1 yr column, so each row is stored once under the period '1 yr' (the default period of every standard).
The scope comment goes into the function name's bracket (the repo's 'variant' field, like '[Sinewave, LCOMP off]' on the 5522A sheet) and into the sheet notes:
    Current, DC [Transconductance amplifier/coil]                       kind DCI, no frequency (DC), three rows
    Current, AC [Clamp-On Only, Multifunction calibrator/coil]          kind ACI, two frequency bands, (20.5 to 1025) A
'Clamp-On Only' is therefore a qualifier of the row, visible in the Standards Specs view and searchable there; a plain lookup('ACI', 500, frequency=50) finds it, and
lookup(..., variant='Clamp-On Only') selects it explicitly.  (The repo's numeric 'qualifiers' list holds value ranges, e.g. power voltage / current, not words.)

Decimal storage of the terms (the repo's usual form: rel is a fraction of the reading, abs a fixed term in amperes):
    90 uA/A  = 90 ppm   -> rel 9e-05  (written '90 ppm I.V.');   80 uA/A -> 8e-05;   0.8 % -> 0.008;   0.99 % -> 0.0099
    0.1 mA -> 1e-04 A;   8 mA -> 0.008 A;   0.08 A -> 0.08 A
Each is computed with Decimal and stored as the nearest float (parse_spec multiplies in binary: 0.8 * 1e-2 and 0.1 * 1e-3 are not the nearest floats); the builder checks
that its Decimal figure agrees with parse_spec to 1e-12 and stops when it does not.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402

VERIFIED_AGAINST_IMAGE = True           # pp. 9 and 30 were read from rendered page images (twice) on 2026-10-23; False re-adds the warnings
SOURCE_PDF = '1888-03.pdf'
MODEL = 'A2LA-5500A-COIL'
CONFIDENCE_TEXT = 'approximately the 95 % level, usually k = 2 (A2LA scope, footnote 2)'

DC_FUNCTION = 'Current, DC [Transconductance amplifier/coil]'
AC_FUNCTION = 'Current, AC [Clamp-On Only, Multifunction calibrator/coil]'

# (function, printed range, lo text, hi text, (freq lo, freq hi) or None, printed CMC, ppm of reading, % of reading, fixed term in A (text), page, note refs)
# 'ppm' and 'pct' are exactly one of the two per row; the fixed term is (value, unit) as printed ('mA' or 'A'), None for none.
D = Decimal
ROWS = [
    (DC_FUNCTION, '(2 to 20) A',     '2',    '20',   None,         '90 µA/A + 0.1 mA', D('90'), None,      ('0.1', 'mA'), 9, (5, 7)),
    (DC_FUNCTION, '(20 to 120) A',   '20',   '120',  None,         '80 µA/A + 8 mA',   D('80'), None,      ('8', 'mA'),   9, (5, 7)),
    (DC_FUNCTION, '(120 to 3000) A', '120',  '3000', None,         '0.8 % + 0.08 A',   None,    D('0.8'),  ('0.08', 'A'),  9, (5, 7)),
    (AC_FUNCTION, '(20.5 to 1025) A', '20.5', '1025', ('45', '65'),  '0.8 %',          None,    D('0.8'),  None,           30, (6, 7, 8)),
    (AC_FUNCTION, '(20.5 to 1025) A', '20.5', '1025', ('65', '440'), '0.99 %',         None,    D('0.99'), None,           30, (6, 7, 8)),
]

NOTES = {
    '1': 'SOURCE: the laboratory\'s own A2LA scope of accreditation, certificate 1888.03 (revised 07/07/2026), section V. Electrical - DC/Low Frequency. '
         'DC rows: printed p. 9 of 47, "DC Current - Generate" (last block): (2 to 20) A 90 uA/A + 0.1 mA; (20 to 120) A 80 uA/A + 8 mA; (120 to 3000) A 0.8 % + 0.08 A; '
         'comment "Transconductance amplifier/coil". AC rows: printed p. 30 of 47, "AC Current - Generate (cont)", "Clamp-On Only", (20.5 to 1025) A: (45 to 65) Hz 0.8 %; '
         '(65 to 440) Hz 0.99 %; comment "Multifunction calibrator/coil". Built by specs/build_coil_standard.py.',
    '2': 'VERIFICATION: ' + ('the five lines above (and the column headers: CMC 2, 5, 9 (+/-); no frequency column on p. 9, a Frequency column on p. 30) were read from the RENDERED PAGE IMAGES '
                             'of pp. 9 and 30 of 47, each read twice (full page, then a 200 dpi crop), on 2026-10-23. Both pages carry "(A2LA Cert. No. 1888.03) Revised 07/07/2026". The coil '
                             'datasheet values in note 7 were also read from the rendered pages. ' if VERIFIED_AGAINST_IMAGE else
                             'UNVERIFIED AGAINST THE RENDERED PAGES: TODO render pp. 9 and 30, read the five lines and set VERIFIED_AGAINST_IMAGE in the builder. ')
         + 'The extracted text was used only to find the pages.',
    '3': 'CONFIDENCE: footnote 2 of the scope: a CMC is an EXPANDED uncertainty at approximately the 95 % level of confidence, usually using a coverage factor of k = 2. '
         'Stored as confidence_pct 95, so the coverage divisor is 2.0 (u of the standard = CMC / 2). Wording kept in confidence_text.',
    '4': 'TERMS: footnote 5: the first percentage is a percentage of the READING unless otherwise noted; footnote 9: a CMC is a percent or fraction of the reading plus a fixed floor. '
         'Stored in the repo\'s usual form: rel (fraction of the reading) and abs (fixed term, amperes), computed in Decimal: 90 uA/A = 90 ppm = 9e-05 and 80 uA/A = 8e-05 of reading, '
         '0.8 % = 0.008, 0.99 % = 0.0099; 0.1 mA = 1e-04 A, 8 mA = 0.008 A, 0.08 A. The two AC rows have no fixed term (the scope prints a bare percentage). '
         'A CMC has no 90 day / 1 yr column: each row is stored once, under the period "1 yr" (the default period of every standard).',
    '5': 'DC ROWS (p. 9 of 47): scope parameter "DC Current - Generate", comment "Transconductance amplifier/coil", column header "Parameter/Equipment | Range | CMC (+/-) | Comments" '
         '- there is NO frequency column, these are DC ranges (rows kind DCI). Stored with direction "output" (the lab generates the current) and no frequency. '
         'The comment says "Transconductance amplifier/coil", NOT "Multifunction calibrator/coil": see note 9 (OWNER QUESTION).',
    '6': 'AC ROWS (p. 30 of 47): scope parameter "AC Current - Generate (cont)", sub-heading "Clamp-On Only", range (20.5 to 1025) A, Frequency column (45 to 65) Hz 0.8 % and '
         '(65 to 440) Hz 0.99 % (percent of reading only), comment "Multifunction calibrator/coil". "Clamp-On Only" is kept as a qualifier of the row (the bracket of the function name, '
         'the repo\'s variant field). A frequency inside a band is required for a lookup; at 65 Hz both bands match and the larger limit is used (the scope CMC rule).',
    '7': 'COIL DATASHEET (Fluke 5500A/COIL | 50-Turn Current Coil, technical data 10/2026, read from the rendered pages; facts only, none is used in a calculation): number of turns 50; '
         'maximum current 11 A rms continuous, 20 A rms for 2 minutes; duty-cycle derating: below 11 A continuous, above 11 A 2 minutes ON / 8 minutes OFF; maximum voltage 3 V rms; '
         'frequency of operation DC, 45-440 Hz (should not exceed the rms voltage rating): for the 5500A current output DC and 45-65 Hz 0-11 A, 65-440 Hz 0-2.19999 A; for the 5520A '
         'current output DC and 45-65 Hz 0-20 A, 65-440 Hz 0-2.99999 A (assumes a Fluke 80i-600 clamp or equivalent; other clamps may limit the drive to less); minimum inside diameter of '
         'the clamp jaws 2.54 cm (1 in.); statement of calibration practices included, with a 17025 accredited report. The coil multiplies the calibrator current by 50 '
         '(effective output = 50 x calibrator current).',
    '8': 'COIL / CLAMP INTERACTION UNCERTAINTY (datasheet, NOT added to the scope rows): +/-(0.25 % of effective output + 0.5 A) for toroidal-wound current clamps such as the Fluke 80I and '
         '80I-1000; +/-(0.50 % of effective output + 0.5 A) for clamps like the Fluke 80i-kw, 80i-400, 80i-410, 80i-500, 80i-1010, Fluke 31, Fluke 33 or equivalent. It is a contribution of '
         'the clamp meter / coil pair, which the scope CMC excludes; the repo has no second-term mechanism for a standard, so it is recorded here only and combined with nothing '
         '(no combination rule is invented; whether and how it enters the uncertainty is an OWNER DECISION).',
    '9': 'EFFECTIVE CURRENT AND WHICH LINES BELONG TO THE COIL: the scope ranges are the current the clamp sees ("effective output" in the datasheet). The Clamp-On Only upper limit '
         '1025 A = 20.5 A x 50 turns (an inference: the maximum current of the scope\'s multifunction-calibrator ranges times the coil\'s turns, not stated by the scope). Observations for the owner: '
         '(a) the datasheet limits the 65-440 Hz current to 2.19999 A (5500A) or 2.99999 A (5520A), i.e. 110 A or 150 A effective, while the 65-440 Hz row is listed to 1025 A; '
         '(b) the DC rows run to 3000 A, beyond 50 x 20 A = 1000 A, and their comment is "Transconductance amplifier/coil". Both are stored as printed on the scope.',
    '10': 'NOT STORED: the scope\'s other coil-related lines (AC Current - Generate (20.5 to 3000) A, (16 to 850) Hz 0.7 % + 0.84 A and (0.85 to 6) kHz 0.8 % + 0.84 A, "Transconductance '
          'amplifier/coil"; DC Power - Generate, "Multifunction calibrator with current coil") because they were not asked for; and the clamp meter\'s own contribution (resolution, repeatability, '
          'positioning in the jaws). The CMC excludes the unit under test; a certificate value may be larger.',
    '11': 'USE: the lookups find this sheet by its model id (uncertainty_budget.build(kind, ..., standard="A2LA-5500A-COIL"), tartur.standard_accuracy, tartur.compute(..., standard=...)). '
          'It is NOT offered in any calibrator picker: those choose the instrument that is commanded, and the coil is not commanded. The Fluke 365 procedure uses a 20-turn coil '
          'and keeps the regular calibrator current uncertainty, unscaled (owner decision); nothing here changes it.',
}

LIMITS = [
    dict(function='Current, DC [Transconductance amplifier/coil]', limit='(2 to 20) A 90 uA/A + 0.1 mA; (20 to 120) A 80 uA/A + 8 mA; (120 to 3000) A 0.8 % + 0.08 A.', page='9'),
    dict(function='Current, AC [Clamp-On Only, Multifunction calibrator/coil]', limit='(20.5 to 1025) A: (45 to 65) Hz 0.8 %; (65 to 440) Hz 0.99 %.', page='30'),
    dict(function='5500A/COIL datasheet', limit='50 turns; 11 A rms continuous, 20 A rms 2 min; interaction +/-(0.25 % or 0.50 % of effective output + 0.5 A), not added; jaws >= 2.54 cm.', page='1-2'),
]


def _num(x):
    return f'{x.normalize():f}'


def make_row(function, printed, lo, hi, freq, cmc, ppm, pct, fixed, page, refs):
    """One range of the sheet; the terms come from Decimal (see the module docstring), parse_spec is only the cross-check."""
    kind_expect = 'DCI' if function.startswith('Current, DC') else 'ACI'
    lab_kind, variant = sm.classify(function)
    if lab_kind != kind_expect:
        raise ValueError(f'{function}: specmanager.classify gives {lab_kind}, expected {kind_expect}')
    params = [sm.parse_param(f'{lo} A to {hi} A')]
    if freq:
        params.append(sm.parse_param(f'{freq[0]} Hz to {freq[1]} Hz'))
    if None in params:
        raise ValueError(f'cannot parse value range for {function} {printed}')
    for p in params:
        p['notes'] = list(refs)
    rel = ppm / Decimal(1_000_000) if ppm is not None else pct / Decimal(100)
    text_rel = f'{_num(ppm)} ppm I.V.' if ppm is not None else f'{_num(pct)} % I.V.'
    fixed_a = D(fixed[0]) * {'A': D(1), 'mA': D('0.001')}[fixed[1]] if fixed else D(0)      # fixed term in amperes, exact
    fixed_text = f' + {fixed[0]} {fixed[1]}' if fixed else ''
    spec = sm.parse_spec(f'[1 yr] Accuracy: +/-({text_rel}{fixed_text})')
    if spec.get('error'):
        raise ValueError(spec['error'])
    for key, exact in (('rel', rel), ('abs', fixed_a)):
        if abs(spec[key] - float(exact)) > 1e-12 * max(1.0, abs(float(exact))):
            raise ValueError(f'{function} {printed}: {key} {spec[key]!r} disagrees with the Decimal figure {exact}')
    spec['rel'], spec['abs'] = float(rel), float(fixed_a)         # the nearest floats to the printed figures
    amp = params[0]
    label = printed + (f', {freq[0]} Hz to {freq[1]} Hz' if freq else '')
    return dict(label=label, page=page, params=params, specs=[spec], raw_other=[], printed=f'{printed}' + (f'  ({freq[0]} to {freq[1]}) Hz' if freq else '') + f'  {cmc}',
                kind=kind_expect, variant=variant, amp_lo=amp['lo'], amp_hi=amp['hi'], unit=amp['unit'],
                freq_lo=params[1]['lo'] if freq else None, freq_hi=params[1]['hi'] if freq else None,
                qualifiers=[], range_max=None, resolution=None, res_src='')


def problems_for(data):
    probs = list(sm.validate_data(data))
    if not VERIFIED_AGAINST_IMAGE:
        probs.append(dict(level='warn', where='standard', what='UNVERIFIED against the rendered pages: pp. 9 and 30 of the A2LA scope were not read from page images. Check the five lines, then rebuild.'))
    probs.append(dict(level='warn', where='standard', what='This is the laboratory\'s own CMC (expanded, approximately 95 %, usually k = 2), not a manufacturer specification. '
                                                          'No 90 day / 1 yr columns; stored under the period "1 yr".'))
    probs.append(dict(level='warn', where='Current, DC [Transconductance amplifier/coil]', what='Comment on the scope is "Transconductance amplifier/coil", not "Multifunction calibrator/coil"; '
                                                                                               'the three DC rows run to 3000 A, beyond 50 turns x 20 A. Stored as printed (note 9).'))
    probs.append(dict(level='warn', where='Current, AC [Clamp-On Only, Multifunction calibrator/coil] / (65 to 440) Hz', what='The datasheet limits 65-440 Hz drive to 2.19999 A (5500A) / 2.99999 A (5520A), '
                                                                                                                            'about 110 / 150 A effective, below the 1025 A of the scope row (note 9). Stored as printed.'))
    probs.append(dict(level='warn', where='standard', what='The datasheet\'s clamp/coil interaction uncertainty (0.25 % or 0.50 % of effective output + 0.5 A) is NOT added to these rows: '
                                                          'no second-term mechanism exists for a standard (note 8).'))
    return probs


def build():
    by = {}
    for row in ROWS:
        by.setdefault(row[0], []).append(make_row(*row))
    functions = [dict(name=name, direction='output', page=rngs[0]['page'], ranges=rngs) for name, rngs in by.items()]
    data = dict(schema=1, standard=dict(
        manufacturer='Applied Technical Services, LLC. (A2LA 1888.03)', model=MODEL,
        description='Fluke 5500A/COIL (A2LA scope)',
        confidence_text=CONFIDENCE_TEXT, confidence_pct=95.0,
        reference='Calibration Scope of Accreditation, A2LA 1888.03, rev. 07/07/2026, section V, printed p. 9 of 47 (DC Current - Generate, Transconductance amplifier/coil) and '
                  'p. 30 of 47 (AC Current - Generate (cont), Clamp-On Only, Multifunction calibrator/coil); Fluke 5500A/COIL technical data (10/2026)',
        revision='07/07/2026', author='written by specs/build_coil_standard.py from the scope pages' + ('' if VERIFIED_AGAINST_IMAGE else ' (UNVERIFIED against the rendered pages)'),
        approved_by='', approve_date='', source_pdf=SOURCE_PDF, sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=NOTES, limits=LIMITS, functions=functions)
    data['problems'] = problems_for(data)
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'a2la_5500a_coil_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    errs = [p for p in data['problems'] if p['level'] == 'error']
    print(f"{MODEL}: {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} flagged ({len(errs)} errors) -> {out}")
    for p in data['problems']:
        print(p['level'].upper(), p['where'], '-', p['what'])


if __name__ == '__main__':
    main()
