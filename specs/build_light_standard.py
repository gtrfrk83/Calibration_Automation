"""Builds specs/standards/a2la_light_standard.json: the laboratory's own A2LA scope CMC for light measurement, used as a standards sheet.

    python specs/build_light_standard.py            # writes specs/standards/a2la_light_standard.json

SOURCE: Calibration Scope of Accreditation, A2LA certificate 1888.03 (revised 07/07/2026), printed page 45 of 47, section X. Optical Quantities
('1888-03.pdf').  The row, as extracted from the PDF text:
    Light - Measure;  White:  (0 to 3000) FC, (0 to 35 000) lux, (0 to 100 000) La, each CMC 2.9 %;
                      Black @ 365 nm:  (0 to 3000) uW/cm2, CMC 5.0 %;   Comments: Radiometer standards.
Footnotes used: 2 (CMC = smallest uncertainty the lab can achieve; expanded uncertainty, approximately the 95 % level, usually k = 2),
5 (the first percentage is a percentage of the reading unless otherwise noted), 12 (the parameter defines the type of instrument calibrated).

VERIFICATION STATUS: VERIFIED against the rendered page.  Page 45 of 47 was rendered (the scope PDF, 1888-03.pdf, staged locally) and the Light row read from the
image on 2026-10-23: column header "CMC 2, 5, 12 (+/-)"; Light - Measure; White (0 to 3000) FC / (0 to 35 000) lux / (0 to 100 000) La, 2.9 % each; Black @ 365 nm
(0 to 3000) micro-W/cm2 (micro sign, superscript 2), 5.0 %; Comments "Radiometer standards".  The same page carries "(A2LA Cert. No. 1888.03) Revised 07/07/2026".
Set VERIFIED_AGAINST_IMAGE = False if the scope is revised until the new page has been read the same way.

How the sheet is used: the lab's CMC is the uncertainty of the lab's own standard for that parameter, so each range is one row whose accuracy is the CMC as a
percentage of reading ('+/-(2.9 % I.V.)').  It is stored as an expanded uncertainty at approximately 95 % (confidence_pct 95, divisor 2, k = 2).  A CMC has
no 90 day / 1 yr column; it is stored once under the period '1 yr', which is the default period of every standard, so the default lookup finds it.

Units: stored exactly as the scope lists them, each as its own unit and kind; nothing is converted (a percentage of reading does not depend on the unit):
    FC     foot-candle, kind FC        (1 FC = 10.763910416709722 lux; for information only)
    lux    illuminance, kind LUX       (the SI unit)
    La     lambert, kind LAMBERT       (1 La = 10000/pi cd/m2; not an illuminance unit; for information only)
    uW/cm2 UV irradiance at 365 nm, kind UVIRR   (printed with the micro sign and a superscript 2; the stored unit is ASCII, specmanager_view shows it as printed)
Display-only SI scaling: none of these units is prefix-scaled by the Standards Specs view (it scales V, A, F, Hz, W, H, S, s, ohm only).
The percentage is converted with Decimal (2.9 % -> 0.029, 5.0 % -> 0.05) so that the stored figure is the nearest float to the printed one.
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

VERIFIED_AGAINST_IMAGE = True           # the Light row of p. 45 was read from a rendered page image on 2026-10-23 (see the docstring); False re-adds the warnings
PDF_PAGE = 45                           # printed page 45 of 47 (the scope's own numbering)
SOURCE_PDF = '1888-03.pdf'
CONFIDENCE_TEXT = 'approximately the 95 % level, usually k = 2 (A2LA scope, footnote 2)'

# (function name, direction, printed range, upper limit text, unit, printed unit, CMC %, kind)
ROWS = [
    ('Light [White] (FC)', '(0 to 3000) FC', '3000', 'FC', 'FC', '2.9', 'FC'),
    ('Light [White] (lux)', '(0 to 35 000) lux', '35000', 'lux', 'lux', '2.9', 'LUX'),
    ('Light [White] (La)', '(0 to 100 000) La', '100000', 'La', 'La', '2.9', 'LAMBERT'),
    ('Light [Black @ 365 nm] (uW/cm2)', '(0 to 3000) µW/cm²', '3000', 'uW/cm2', 'µW/cm²', '5.0', 'UVIRR'),
]

NOTES = {
    '1': 'SOURCE: the laboratory\'s own A2LA scope of accreditation, certificate 1888.03 (revised 07/07/2026), printed p. 45 of 47, section X. Optical Quantities, parameter "Light - Measure": '
         'White (0 to 3000) FC, (0 to 35 000) lux, (0 to 100 000) La, each CMC 2.9 %; Black @ 365 nm (0 to 3000) uW/cm2, CMC 5.0 %. Comments: "Radiometer standards." '
         'Page 45 of 47 is the scope\'s own page numbering. Built by specs/build_light_standard.py.',
    '2': 'VERIFICATION: ' + ('the Light row (column header CMC 2, 5, 12 (+/-), four ranges, 2.9 % / 2.9 % / 2.9 % / 5.0 %, units FC, lux, La, micro-W/cm2) was read from the RENDERED PAGE IMAGE of p. 45 of 47 (cert. 1888.03, revised 07/07/2026) on 2026-10-23.' if VERIFIED_AGAINST_IMAGE else
         'UNVERIFIED AGAINST THE RENDERED PAGE. The numbers and unit signs come from the text extracted from 1888-03.pdf by the Claude project, not from a rendered page image '
         '(standing rule: limits are read from page images because the micro and omega signs are corrupted by extraction). '
         'TODO: render p. 45, check the four ranges, the 2.9 % / 5.0 % figures and the units, then set VERIFIED_AGAINST_IMAGE in the builder and rebuild.'),
    '3': 'CONFIDENCE: footnote 2 of the scope: the CMC is the smallest uncertainty the laboratory can achieve, an EXPANDED uncertainty at approximately the 95 % level, usually k = 2. '
         'Stored as confidence_pct 95, so the coverage divisor is 2.0 (u of the standard = CMC / 2). Wording kept in confidence_text.',
    '4': 'PERCENTAGE: footnote 5 of the scope: the first percentage is a percentage of the READING unless otherwise noted. Each row is +/-(CMC % I.V.) with no fixed term and no full-scale term, '
         'so the uncertainty is CMC x |reading| (2.9 % of 10 000 lux = 290 lux). The figure is not a floor-limited value: nothing is added at the bottom of a range.',
    '5': 'INSTRUMENT TYPE: footnote 12 of the scope: the parameter defines the type of instrument calibrated (light meters / radiometers). The scope comment is "Radiometer standards": '
         'the laboratory\'s reference is a radiometer-based standard, so this CMC is the uncertainty of the lab\'s standard for the light level it applies to the unit under test.',
    '6': 'UNITS (as listed on the scope, each its own unit, nothing converted): FC, lux, La, uW/cm2 (printed with the micro sign and a superscript 2; the stored unit is ASCII "uW/cm2"). '
         'For information only, never used in a calculation: 1 FC = 10.763910416709722 lux (lux is the SI unit of illuminance); 1 La = 10000/pi cd/m2 (a luminance unit, not an illuminance). '
         'The three white-light rows are the same CMC (2.9 %) on three different scales, so a lux value is never looked up in the FC or La rows.',
    '7': 'DIRECTION AND PERIOD: the scope parameter is "Measure"; the sheet stores direction "output" (the light level the lab\'s standard establishes at the unit under test), which is what the default '
         'lookup (specmanager, tartur.standard_accuracy) asks for. A CMC has no 90 day / 1 yr column: it is stored once, under the period "1 yr" (the default period of every standard).',
    '8': 'NOT STORED: stability, non-uniformity, spectral mismatch or distance-dependent terms of the radiometer standard, and the unit under test (resolution, repeatability, drift). '
         'The CMC excludes the unit under test; a certificate value may be larger. No other wavelength, no spectral irradiance and no radiometric unit other than uW/cm2 at 365 nm is on the scope.',
}

LIMITS = [
    dict(function='Light [White]', limit='FC 0 to 3000; lux 0 to 35 000; La 0 to 100 000; CMC 2.9 % of reading on each scale.', page='45'),
    dict(function='Light [Black @ 365 nm]', limit='0 to 3000 uW/cm2 at 365 nm; CMC 5.0 % of reading.', page='45'),
]


def pct_to_rel(pct_text):
    """'2.9' (percent) -> 0.029 as the float nearest to the decimal value (Decimal arithmetic: 2.9 * 0.01 in binary gives 0.028999999999999998)."""
    return float(Decimal(pct_text) / Decimal(100))


def make_row(name, printed, hi_text, unit, printed_unit, pct, kind):
    param = sm.parse_param(f'0 {unit} to {hi_text} {unit}')
    if param is None:
        raise ValueError(f'cannot parse value range for {name}')
    spec = sm.parse_spec(f'[1 yr] Accuracy: +/-({pct} % I.V.)')
    if spec.get('error'):
        raise ValueError(spec['error'])
    spec['rel'] = pct_to_rel(pct)                    # exact decimal conversion (parse_spec multiplies in binary)
    lab_kind, variant = sm.classify(name)
    if lab_kind != kind:
        raise ValueError(f'{name}: specmanager.classify gives {lab_kind}, expected {kind}')
    rng = dict(label=f'0 to {hi_text} {unit}', page=PDF_PAGE, params=[param], specs=[spec], raw_other=[], printed=printed,
               kind=kind, variant=variant, amp_lo=param['lo'], amp_hi=param['hi'], unit=param['unit'], freq_lo=None, freq_hi=None,
               qualifiers=[], range_max=None, resolution=None, res_src='')
    return rng


def problems_for(data):
    probs = list(sm.validate_data(data))
    if not VERIFIED_AGAINST_IMAGE:
        probs.append(dict(level='warn', where='standard', what='UNVERIFIED against the rendered page: the Light row of the A2LA scope (p. 45 of 47) was taken from extracted text, not read from a '
                                                              'page image. Check the four ranges, 2.9 % / 5.0 % and the unit signs, then rebuild (NOTES.md TODO).'))
    probs.append(dict(level='warn', where='standard', what='This is the laboratory\'s own CMC (expanded, approximately 95 %, usually k = 2), not a manufacturer specification. '
                                                          'No fixed term and no period columns; stored under the period "1 yr".'))
    probs.append(dict(level='warn', where='Light [White] (FC) / (La)', what='FC and La are not SI illuminance units; they are kept as the scope lists them and not converted to lux (the CMC is a percentage, '
                                                                          'so no conversion is needed).'))
    return probs


def build():
    functions = [dict(name=name, direction='output', page=PDF_PAGE, ranges=[make_row(name, *rest)]) for name, *rest in ROWS]
    data = dict(schema=1, standard=dict(
        manufacturer='Applied Technical Services, LLC. (A2LA 1888.03)', model='A2LA-LIGHT',
        description='Light measurement (A2LA scope CMC, radiometer standards)',
        confidence_text=CONFIDENCE_TEXT, confidence_pct=95.0,
        reference='Calibration Scope of Accreditation, A2LA 1888.03, rev. 07/07/2026, printed p. 45 of 47, section X. Optical Quantities (Light - Measure)',
        revision='07/07/2026', author='written by specs/build_light_standard.py from the scope text' + ('' if VERIFIED_AGAINST_IMAGE else ' (UNVERIFIED against the rendered page)'),
        approved_by='', approve_date='', source_pdf=SOURCE_PDF, sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=NOTES, limits=LIMITS, functions=functions)
    data['problems'] = problems_for(data)
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'a2la_light_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    errs = [p for p in data['problems'] if p['level'] == 'error']
    print(f"A2LA-LIGHT: {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} flagged ({len(errs)} errors) -> {out}")
    for p in data['problems']:
        print(p['level'].upper(), p['where'], '-', p['what'])


if __name__ == '__main__':
    main()
