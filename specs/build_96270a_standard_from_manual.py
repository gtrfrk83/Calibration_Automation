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


SHEET = 'specification table supplied as a screenshot (document, revision and date unknown)'
PERIOD = '1 yr'     # the table prints no calibration period; stored under the default period so the manager finds it (flagged in problems)

NOTES.update({
    '6': 'SOURCE OF THE ROWS BELOW: ' + SHEET + '. Not read from a manual page. Specified values are as printed; "typical" values are marked in the row label. '
         'No confidence level or coverage factor is printed on the table.',
    '7': 'Printed on the same table, NOT accuracy and not stored as rows: Frequency / level range: Leveling Head O/P [50 ohm] 1 mHz to 4 GHz, -130 to +24 dBm to 125 MHz, '
         '+14 dBm at 4 GHz; Microwave O/P Direct 1 mHz to 27 GHz [with LL option], -4 [-100] to +24 dBm, above 1.4 GHz +20 dBm [above 20 GHz +18 dBm]; Microwave O/P with HF option '
         '1 kHz to 27 GHz [with LL option], -10 [-35] to +18 dBm, above 1.4 GHz +14 dBm [above 20 GHz +12 dBm]. Resolution 10 uHz and 0.001 dB.',
    '8': 'Printed, not stored (limits that are not an uncertainty of the output): VSWR (Leveling Head O/P, 50 ohm): <= 1.05 to 100 MHz, <= 1.1 to 2 GHz, 1.0 + 0.05 x f(GHz) from 2 to 4 GHz; '
         'Microwave O/P direct <= 2.0 (typical), HF option splitter device <= 1.22. Harmonics <= 1 GHz: -60 dBc, > 1 GHz: -55 dBc; sub-harmonics <= 4 GHz: none, > 4 GHz: -60 dBc. '
         'Spurious >= 3 kHz offset: <= -84 dBc at 500 MHz, <= -78 dBc at 1 GHz, <= -66 dBc at 4 GHz, <= -48 dBc at 27 GHz. Phase noise at 1 GHz: -144 dBc/Hz typical, 10 kHz to 100 kHz offset.',
    '9': 'Printed, not stored: modulation AM, FM, PM internal/external to 4 GHz; frequency sweep 1 mHz to 4 GHz (Leveling Head) and 1 mHz to 27 GHz (Microwave O/P), linear or log; '
         'internal 300 MHz frequency counter; power meter readout for Rohde & Schwarz NRP-Z series thermal sensors (list cut off in the screenshot).',
})


def _spec(abs_=0.0, rel=0.0, unit='dB', note=''):
    return dict(period=PERIOD, rel=rel, fs_rel=0.0, fs_value=0.0, abs=abs_, unit=unit, le=False,
                raw=f'[{PERIOD}] Accuracy: +/-({rel:g} of value + {abs_:g} {unit}) ' + note)


def _row(label, spec, unit, freq=None, level_text='', kind='OTHER', amp=(None, None), resolution=None, notes=()):
    params = []
    if level_text:
        params.append(dict(tag='', lo=None, hi=None, unit='dBm', text=level_text, annot='', notes=list(notes)))
    if freq:
        params.append(dict(tag='', lo=freq[0], hi=freq[1], unit='Hz', text='', annot='', notes=[]))
    return dict(label=label, page=None, params=params, specs=[spec], raw_other=[], kind=kind, variant='', amp_lo=amp[0], amp_hi=amp[1], unit=unit,
                freq_lo=freq[0] if freq else None, freq_hi=freq[1] if freq else None, qualifiers=[], range_max=None,
                resolution=resolution, res_src='printed' if resolution else '')


def build():
    functions = []
    # frequency accuracy: FREQ kind, so Scope-style lookups by frequency work like the other standards
    r = _row('Frequency 1 mHz to 27 GHz', None, 'Hz', kind='FREQ', amp=(1e-3, 27e9), resolution=1e-5)
    r['specs'] = [sm.parse_spec(f'[{PERIOD}] Accuracy: +/-(0.05 ppm I.V. + 5e-06 Hz)')]
    r['params'] = [dict(tag='', lo=1e-3, hi=27e9, unit='Hz', text='1 mHz to 27 GHz', annot='', notes=[])]
    functions.append(dict(name='Frequency', direction='output', page=None, ranges=[r]))

    D = lambda v: _spec(abs_=v)
    lh = [
        _row('Leveling Head, down to -48 dBm, 0 to 100 kHz', D(0.03), 'dB', (0.0, 100e3), 'down to -48 dBm'),
        _row('Leveling Head, down to -48 dBm, to 128 MHz', D(0.05), 'dB', (100e3, 128e6), 'down to -48 dBm'),
        _row('Leveling Head, down to -48 dBm, at 4 GHz', D(0.3), 'dB', (4e9, 4e9), 'down to -48 dBm'),
        _row('Leveling Head, 10 MHz to 128 MHz, to -48 dBm', D(0.05), 'dB', (10e6, 128e6), 'to -48 dBm'),
        _row('Leveling Head, 10 MHz to 128 MHz, to -84 dBm', D(0.1), 'dB', (10e6, 128e6), 'to -84 dBm'),
        _row('Leveling Head, 10 MHz to 128 MHz, at -130 dBm', D(0.7), 'dB', (10e6, 128e6), 'at -130 dBm'),
    ]
    functions.append(dict(name='RF Level Accuracy (into 50 ohm) [Leveling Head O/P]', direction='output', page=None, ranges=lh))
    mw = [
        _row('Microwave O/P Direct, to 4 GHz (typical)', _spec(abs_=0.5, note='typical'), 'dB', (0.0, 4e9), 'typical'),
        _row('Microwave O/P Direct, to 26.5 GHz (typical)', _spec(abs_=0.5, note='typical'), 'dB', (0.0, 26.5e9), 'typical'),
    ]
    functions.append(dict(name='RF Level Accuracy (into 50 ohm) [Microwave O/P Direct, typical]', direction='output', page=None, ranges=mw))
    fl = [_row(f'Microwave O/P with HF option, power flatness uncertainty at {t}', D(v), 'dB', (f, f), 'after self-characterization')
          for t, f, v in (('100 MHz', 100e6, 0.05), ('1 GHz', 1e9, 0.07), ('12 GHz', 12e9, 0.1), ('26.5 GHz', 26.5e9, 0.16))]
    functions.append(dict(name='RF Power Flatness Uncertainty [Microwave O/P with HF option]', direction='output', page=None, ranges=fl))
    pw = []
    for kind_txt, vals in (('factory calibration', (0.0106, 0.0142, 0.0352)),
                           ('reference sensor calibrated with typical state-of-the-art uncertainty and vector corrections for mismatches at the splitter output port', (0.0037, 0.0049, 0.0218))):
        for t, f, v in zip(('100 MHz', '1 GHz', '26.5 GHz'), (100e6, 1e9, 26.5e9), vals):
            pw.append(_row(f'% Power (Cal Factor) uncertainty, {kind_txt[:40]}..., at {t}' if len(kind_txt) > 40 else f'% Power (Cal Factor) uncertainty, {kind_txt}, at {t}',
                           _spec(rel=v, unit='W'), 'W', (f, f), kind_txt))
    functions.append(dict(name='% Power (Cal Factor) Uncertainty [Microwave O/P with HF option]', direction='output', page=None, ranges=pw))
    att = [_row('Attenuation, to 49 dB (relative to +10 dBm, 10 Hz to 128 MHz)', D(0.02), 'dB', (10.0, 128e6), 'relative to +10 dBm, to 49 dB'),
           _row('Attenuation, at 110 dB (relative to +10 dBm, 10 Hz to 128 MHz)', D(0.15), 'dB', (10.0, 128e6), 'relative to +10 dBm, at 110 dB')]
    functions.append(dict(name='Attenuation Accuracy (into 50 ohm) [Leveling Head O/P]', direction='output', page=None, ranges=att))

    data = dict(schema=1, standard=dict(
        manufacturer='Fluke', model='96270A', description='RF Reference Source (96000 Series; 96270A with microwave output, 96040A leveling head)',
        confidence_text='[Not Specified] - not printed on the specification table',
        confidence_pct=None,
        reference='Fluke 96270A specification table: ' + SHEET + '. The Operators Manual (chapters 1-3) prints no accuracy specification (p.1-2 refers to www.fluke.com).',
        revision='', author='rows typed from the supplied table by specs/build_96270a_standard_from_manual.py; operating limits read from the manual page images',
        approved_by='', approve_date='', source_pdf='96270 Operator Manual.pdf (operating limits only); specification table: screenshot', sheet_generated='',
        built=datetime.now().isoformat(timespec='seconds')), notes=NOTES, functions=functions)
    problems = []

    def w(where, what, level='warn'):
        problems.append(dict(level=level, where=where, what=what))
    w('standard', 'Rows come from a screenshot of the specification table, not from a manual page or a dated sheet. Check them against the current Fluke 96270A datasheet '
                  '(www.fluke.com) before relying on them for an uncertainty budget.')
    w('standard', 'Confidence level / coverage factor is not printed on the table. specmanager divisor() falls back to k = 2 for an unspecified level; set the divisor in the manager once known.')
    w('standard', f'The table prints no calibration period. Every row is stored under "{PERIOD}" only so the manager finds it; that is a placeholder, not a printed value.')
    w('RF level rows', 'Level accuracy is stored in dB as printed (kind OTHER, unit dB, 50 ohm). The uncertainty budget does not use kind OTHER, so nothing reads these rows yet; '
                       'a dB-to-volts (or % of power) conversion convention must be decided before they feed a budget.')
    w('Leveling Head, down to -48 dBm', 'Printed: "+/-0.03 dB to 100 kHz, +/-0.05 dB to 128 MHz, +/-0.3 dB at 4 GHz". Stored as bands 0-100 kHz, 100 kHz-128 MHz and the single point 4 GHz; '
                                        'nothing is printed between 128 MHz and 4 GHz and the lower band edge of 0 Hz is assumed.')
    w('Leveling Head, 10 MHz to 128 MHz', 'Printed levels "to -48 dBm / to -84 dBm / at -130 dBm" are kept in the label; the level bands are not split into numeric ranges because the table gives only the upper bound of each.')
    w('Microwave O/P Direct', 'Printed: "Typically +/-0.5 dB to 4 GHz, +/-0.5 dB to 26.5 GHz". Typical values, not guaranteed, and the two lines are stored as printed (the two bands overlap).')
    w('% Power (Cal Factor)', 'Percent of power stored as a fraction of reading (1.06 % = 0.0106). The second set uses the printed assumption of a reference sensor with typical state-of-the-art uncertainty.')
    w('Frequency', '+/-0.05 ppm +/- 5 uHz stored for the full 1 mHz to 27 GHz; the table does not tie it to a period or to a temperature. Resolution 10 uHz taken from the table and stored on this row; '
                   'the budget would add it as u(resolution) = 10 uHz / sqrt(12).')
    w('Attenuation', 'Printed "10 Hz to 128 MHz", relative to +10 dBm; at 110 dB the value is 0.15 dB. Stored as two rows by attenuation, not by a numeric amplitude range.')
    w('Operating limits', 'Level / frequency limits (notes 2, 3, 7), connector data (notes 4, 5) and the VSWR / harmonics / spurious / phase-noise data (note 8) are notes only; the schema has no field for them.')
    problems.extend(sm.validate_data(data))
    data['problems'] = problems
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'fluke_96270a_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{len(data['functions'])} functions, {sum(len(f['ranges']) for f in data['functions'])} rows, {len(data['problems'])} problems -> {out}")


if __name__ == '__main__':
    main()
