"""Builds specs/standards/fluke_96270a_standard.json from the Fluke 96000 Series (96270A / 96040A) Operators Manual.

    python specs/build_96270a_standard_from_manual.py            # writes specs/standards/fluke_96270a_standard.json

RESULT OF THE READ: the supplied manual ('96270 Operator Manual.pdf', 146 PDF pages, printed chapters 1-3 only) contains NO accuracy
specification.  Printed p.1-2 (PDF p.8) says: "Complete specifications for the Product are at www.fluke.com."  There is no level
accuracy, level flatness, frequency accuracy, reference-oscillator aging / stability, harmonic or spurious table, and no 90-day /
1-year / 2-year column anywhere in the manual (all 146 PDF pages were rendered at 110 dpi / text-searched; the manual ends at printed
p.3-120).  Calibration limits are in the separate 96000 Series Service Manual, which is not supplied.

Nothing is guessed, so this file carries NO spec rows (functions = []).  What the manual does print, and is useful to the person who
will transcribe the specification sheet later, is kept in 'notes' (operating limits and the reference-frequency connector data)
with printed + PDF page numbers, and every gap is listed in 'problems'.

Page numbers: printed chapter-1 page 1-N is PDF page N + 6; printed chapter-3 page 3-N is PDF page N + 26.
Values below were read from RENDERED PAGE IMAGES (pdftoppm -r 110): PDF pp. 8, 51, 55, 93, 115.

When the specification sheet (www.fluke.com) is supplied, add its tables here in the same way as build_5790b_standard_from_manual.py:
functions[] -> ranges[] with kind 'ACV'-style kinds are NOT suitable for RF level; use kind 'OTHER' (or a new kind such as 'RFLEVEL' /
'FREQ' / 'FLAT') with unit 'dBm' stored as written or converted, and say which in the note.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402

NOTES = {
    '1': 'Manual p.1-2 (PDF p.8): "Complete specifications for the Product are at www.fluke.com." The Operators Manual prints no accuracy, flatness, '
         'stability, harmonic, spurious or 90 d / 1 yr / 2 yr specification. No confidence level / coverage factor is printed anywhere.',
    '2': 'Operating limits, NOT accuracy (Table 3-22, p.3-67, PDF p.93; Table 3-29, p.3-89, PDF p.115). Leveling Head output: frequency 0.001 Hz to '
         '4.024 GHz, level -130.000 to +24 dBm (50 ohm) with 20 dBm max above 125.75 MHz and 14 dBm max above 1.4084 GHz; -136.000 to +18 dBm (75 ohm) '
         'with 14 dBm max above 125.75 MHz and 8 dBm max above 1.4084 GHz. Level units printed: dBm, Vp-p and Vrms (uV, mV, V), W (nW, uW, mW, W), dBuV. '
         'Level step 0.001 dB to 130 dB.',
    '3': 'Operating limits, NOT accuracy (Table 3-29, p.3-89, PDF p.115): 96270A Microwave O/P Direct: frequency 0.001 Hz to 27 GHz; level -4 dBm to +24 dBm, '
         '20 dBm max above 1.4048 GHz, [-100 dBm minimum, above 20 GHz +18 dBm max] (the bracket is printed for the Extended Low Level Microwave Output option).',
    '4': 'Reference Frequency Output connector (Table 3-2, p.3-25, PDF p.51): BNC, 1 MHz or 10 MHz user selectable, 1.5 V pk-pk nominal into 50 ohm (-0.4 V to 1.1 V), '
         '3.0 V pk-pk nominal into 1 kohm (-0.4 V to 2.6 V, TTL or 3 V compatible). No frequency accuracy or aging is printed.',
    '5': 'Reference Frequency Input connector (Table 3-3, p.3-25, PDF p.51): BNC, 1 MHz to 20 MHz in 1 MHz steps (phase-noise specification holds only for 10 MHz or '
         '20 MHz), "Lock Range +/-0.3 ppm" (on-screen lock indicator), 1 V pk nominal (+/-5 V pk max), 50 ohm, lock bandwidth 0.5 Hz nominal. The lock range is the '
         'capture window of the external-reference input, not an output-frequency accuracy; it is not stored as a specification.',
}


def build():
    data = dict(schema=1, standard=dict(
        manufacturer='Fluke', model='96270A', description='RF Reference Source (96000 Series; 96270A with microwave output, 96040A leveling head)',
        confidence_text='[Not Specified] - not printed in the Operators Manual',
        confidence_pct=None,
        reference='Fluke 96000 Series Operators Manual, Chapters 1-3 (printed pp.1-1 to 3-120). Accuracy specifications are NOT in this manual (p.1-2 refers to www.fluke.com).',
        revision='', author='built from the manual page images by specs/build_96270a_standard_from_manual.py', approved_by='', approve_date='',
        source_pdf='96270 Operator Manual.pdf', sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=NOTES, functions=[])
    problems = []

    def w(where, what, level='error'):
        problems.append(dict(level=level, where=where, what=what))
    w('standard', 'NO SPECIFICATION ROWS: the Operators Manual has no specifications chapter. Printed p.1-2 (PDF p.8) says complete specifications are at www.fluke.com. '
                  'Needed and absent: RF level accuracy and flatness by frequency and level (leveling head and microwave output), frequency accuracy / reference oscillator '
                  '(aging, temperature stability), harmonics, spurious, phase noise, and any 90 d / 1 yr / 2 yr columns. Supply the specification sheet (or the 96000 Series '
                  'Service Manual) and extend this builder.')
    w('standard', 'Confidence level / coverage factor is not printed in the Operators Manual. specmanager divisor() falls back to k = 2 for an unspecified level; '
                  'set the divisor in the manager once the sheet states it.', 'warn')
    w('standard', 'Direction would be "output". Level unit printed on the instrument is dBm (also W, Vrms, Vp-p, dBuV); no accuracy is printed in any unit, so nothing '
                  'is stored. A level accuracy stored in dB or % would need a dBm-to-V/W conversion that depends on the 50 / 75 ohm load: decide the storage convention '
                  'when the sheet arrives.', 'warn')
    w('Operating limits', 'Level / frequency limits (notes 2, 3) and the reference-frequency connector data (notes 4, 5) are kept as notes only; the schema has no '
                          'field for operating limits.', 'warn')
    w('Reference frequency', 'Lock Range +/-0.3 ppm (p.3-25) is an input capture range, not an output accuracy; the 96270A time base (internal 10 MHz) accuracy is not printed '
                             'in this manual.', 'warn')
    problems.extend(sm.validate_data(data))
    data['problems'] = problems
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'fluke_96270a_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{len(data['functions'])} functions, 0 rows, {len(data['problems'])} problems -> {out}")


if __name__ == '__main__':
    main()
