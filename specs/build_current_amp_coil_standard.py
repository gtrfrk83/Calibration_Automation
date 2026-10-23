"""Builds specs/standards/a2la_current_amp_coil_standard.json: the lab's own A2LA scope CMC for AC current generated with a transconductance amplifier and coil, as a standards sheet.

    python specs/build_current_amp_coil_standard.py            # writes specs/standards/a2la_current_amp_coil_standard.json

SOURCE: Calibration Scope of Accreditation, A2LA certificate 1888.03 (revised 07/07/2026), section V. Electrical - DC/Low Frequency, printed p. 30 of 47,
'AC Current - Generate (cont)' (column header "Parameter/Range | Frequency | CMC 2, 5, 9 (+/-) | Comments"), the last range above 'Clamp-On Only':
        (20.5 to 3000) A     (16 to 850) Hz      0.7 % + 0.84 A       comment: Transconductance amplifier/coil
                             (0.85 to 6) kHz     0.8 % + 0.84 A
VERIFICATION STATUS: VERIFIED against the rendered page.  Printed p. 30 was rendered with pdftoppm and the two lines were read from the images twice (a 170 dpi and a 260 dpi
crop, 2026-10-23); no other line of the AC Current - Generate block (pp. 29-30) carries the word coil (the extracted text was used only to find them: 'coil' occurs only on
pp. 9, 10 and 30).  Set VERIFIED_AGAINST_IMAGE = False if the scope is revised until the page has been read the same way.

Same pattern as specs/build_coil_standard.py (A2LA-5500A-COIL, whose make_row is reused: terms in Decimal, nearest float, cross-checked against parse_spec).  Two rows, kind ACI,
period '1 yr' only, direction 'output', 95 % (k = 2) from footnote 2.  Frequency bands are stored in Hz: (0.85 to 6) kHz is 850 to 6000 Hz (the label keeps the printed kHz text).
The 5500A/COIL's clamp / coil interaction uncertainty is NOT part of this sheet (this is a transconductance amplifier, not the 5500A/COIL) and nothing is combined.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import build_coil_standard as bc  # noqa: E402
import specmanager as sm  # noqa: E402

VERIFIED_AGAINST_IMAGE = True
MODEL = 'A2LA-CURRENT-AMP-COIL'
FUNCTION = 'Current, AC [Transconductance amplifier/coil]'
PAGE = 30
# (printed range, lo, hi, (f lo Hz, f hi Hz), printed frequency, printed CMC, % of reading, fixed term)
ROWS = [('(20.5 to 3000) A', '20.5', '3000', ('16', '850'), '(16 to 850) Hz', '0.7 % + 0.84 A', D('0.7'), ('0.84', 'A')),
        ('(20.5 to 3000) A', '20.5', '3000', ('850', '6000'), '(0.85 to 6) kHz', '0.8 % + 0.84 A', D('0.8'), ('0.84', 'A'))]

NOTES = {
    '1': 'SOURCE: the laboratory\'s own A2LA scope of accreditation, certificate 1888.03 (revised 07/07/2026), section V. Electrical - DC/Low Frequency, printed p. 30 of 47, "AC Current - Generate (cont)", '
         'range (20.5 to 3000) A, comment "Transconductance amplifier/coil": (16 to 850) Hz 0.7 % + 0.84 A; (0.85 to 6) kHz 0.8 % + 0.84 A. Built by specs/build_current_amp_coil_standard.py.',
    '2': 'VERIFICATION: ' + ('both lines (column header CMC 2, 5, 9 (+/-), Frequency column) were read from the RENDERED PAGE IMAGE of p. 30 of 47, twice (170 dpi and 260 dpi crops), on 2026-10-23; '
                             'the page carries "(A2LA Cert. No. 1888.03) Revised 07/07/2026". No other AC Current - Generate line mentions a coil. ' if VERIFIED_AGAINST_IMAGE else
                             'UNVERIFIED AGAINST THE RENDERED PAGE: TODO render p. 30, read the two lines and set VERIFIED_AGAINST_IMAGE in the builder. ')
         + 'The extracted text was used only to find the page.',
    '3': 'CONFIDENCE: footnote 2 of the scope: a CMC is an EXPANDED uncertainty at approximately the 95 % level of confidence, usually using a coverage factor of k = 2. '
         'Stored as confidence_pct 95, so the coverage divisor is 2.0 (u of the standard = CMC / 2).',
    '4': 'TERMS: footnote 5: the first percentage is a percentage of the READING; footnote 9: a percent of the reading plus a fixed floor. Stored as rel (0.007 and 0.008 of reading) and abs (0.84 A), '
         'computed in Decimal. No 90 day / 1 yr columns: each row is stored once, under the period "1 yr".',
    '5': 'ROWS: kind ACI, direction "output" (the lab generates the current), amperes as printed. The frequency band of the second row is printed (0.85 to 6) kHz and stored as 850 to 6000 Hz; '
         'the two bands meet at 850 Hz, where the larger limit is used (the scope CMC rule). An AC point needs a frequency inside a band; below 16 Hz or above 6 kHz nothing is covered.',
    '6': 'NOT PART OF THIS SHEET: the 5500A/COIL lines of the scope (sheet A2LA-5500A-COIL) and the coil datasheet\'s clamp / coil interaction uncertainty, which is not combined into anything here. '
         'Not wired into any calibrator picker (the pickers choose the instrument that is commanded); found by model id (uncertainty_budget.build(..., standard="A2LA-CURRENT-AMP-COIL"), tartur).',
}
LIMITS = [dict(function=FUNCTION, limit='(20.5 to 3000) A: (16 to 850) Hz 0.7 % + 0.84 A; (0.85 to 6) kHz 0.8 % + 0.84 A.', page='30')]


def build_rows():
    rows = []
    for printed, lo, hi, freq, pfreq, cmc, pct, fixed in ROWS:
        r = bc.make_row(FUNCTION, printed, lo, hi, freq, cmc, None, pct, fixed, PAGE, (4, 5))
        r['label'] = f'{printed}, {pfreq}'
        r['printed'] = f'{printed}  {pfreq}  {cmc}'
        rows.append(r)
    return rows


def problems_for(data):
    probs = list(sm.validate_data(data))
    if not VERIFIED_AGAINST_IMAGE:
        probs.append(dict(level='warn', where='standard', what='UNVERIFIED against the rendered page: p. 30 of the A2LA scope was not read from a page image. Check the two lines, then rebuild.'))
    probs.append(dict(level='warn', where='standard', what='This is the laboratory\'s own CMC (expanded, approximately 95 %, usually k = 2), not a manufacturer specification. '
                                                          'No 90 day / 1 yr columns; stored under the period "1 yr".'))
    return probs


def build():
    data = dict(schema=1, standard=dict(
        manufacturer='Applied Technical Services, LLC. (A2LA 1888.03)', model=MODEL,
        description='Transconductance amplifier/coil (A2LA scope, AC current)',
        confidence_text=bc.CONFIDENCE_TEXT, confidence_pct=95.0,
        reference='Calibration Scope of Accreditation, A2LA 1888.03, rev. 07/07/2026, section V, printed p. 30 of 47 (AC Current - Generate (cont), (20.5 to 3000) A, Transconductance amplifier/coil)',
        revision='07/07/2026', author='written by specs/build_current_amp_coil_standard.py from the scope page' + ('' if VERIFIED_AGAINST_IMAGE else ' (UNVERIFIED against the rendered page)'),
        approved_by='', approve_date='', source_pdf=bc.SOURCE_PDF, sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=NOTES, limits=LIMITS, functions=[dict(name=FUNCTION, direction='output', page=PAGE, ranges=build_rows())])
    data['problems'] = problems_for(data)
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'a2la_current_amp_coil_standard.json'
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{MODEL}: {len(data['functions'])} function, {sum(len(f['ranges']) for f in data['functions'])} ranges, {len(data['problems'])} flagged -> {out}")


if __name__ == '__main__':
    main()
