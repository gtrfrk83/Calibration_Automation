"""Builds specs/fluke_i400_pv.json for the i400 engine (i400_verification.py) from the Fluke i400 AC Current Clamp "Calibration Information" (part 2414311, 8 PDF pages).

    python3 specs/build_fluke_i400_spec.py

Source (printed page numbers = PDF page numbers):
  Table 3 "Accuracy Tests", p. 6: three steps (the table's own column names in brackets):
      step  nominal value   5520A output   LCOMP   UUT nominal output   multimeter reading limits
      1     1 A, 45 Hz      1 A, 45 Hz     OFF     1 mA, 45 Hz          0.920 mA ... 1.080 mA
      2     100 A, 400 Hz   2.0 A, 400 Hz  ON      100 mA, 400 Hz       97.94 mA ... 102.06 mA
      3     400 A, 60 Hz    8.0 A, 60 Hz   ON      400 mA, 60 Hz        391.94 mA ... 408.06 mA
  Current Accuracy Tests procedure, p. 6 (step 1: the UUT jaws round the single-turn #14 gauge wire, Figure 2; steps 2 and 3: the jaws round the 5500A coil, Figure 3, p. 7);
  Table 2 "Required Test Equipment", p. 5 (calibrator 0 - 8 A, 0.15 %, 45 - 400 Hz, recommended 5520A; multimeter 1 - 400 mA ac, 0.5 %, Fluke 189 in mA ac;
  copper wire loop, single > #14 gauge, 6 in diameter; toroid coil, 50 turns, Fluke 5500A/Coil);
  Electrical Specifications, p. 3: range 1 A to 400 A ac rms, output 1 mA/A, accuracy 2 % + 0.06 A (45 - 400 Hz), load impedance < 10 ohm.
Every nominal, frequency and limit was read from the RENDERED PAGE IMAGES (pdftoppm, 150 dpi), twice, never from extracted text.

Cross-check against the published specification: each printed limit is exactly the full specification at that point, limit (mA) = 1 mA/A x (2 % of the clamp reading + 0.06 A):
    1 A -> 0.02 + 0.06 = 0.08 A -> +/-0.080 mA;  100 A -> 2 + 0.06 = 2.06 A -> +/-2.06 mA;  400 A -> 8 + 0.06 = 8.06 A -> +/-8.06 mA.
The builder recomputes them in Decimal and aborts on a disagreement (there is none: the table and the specification agree).

What the engine does with the table (owner decisions, 2026-10-26): the calibrator is selectable (5560A / 5522A / 5520A); the multimeter that reads the clamp's output is read by the
program (no typed reading); the 50-turn coil points (steps 2 and 3) use the shared 50-turn coil rule (coil_rule.py).  The ranges the multimeter is set to (0.01 A / 1 A / 1 A) are
ENGINEERING CHOICES, not printed in the manual (the manual's Fluke 189 uses its own mA ac autorange): 1 mA on the 10 mA range, 100 mA and 400 mA on the 1 A range.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_i400_pv.json'
DOCUMENT = 'Fluke i400 AC Current Clamp - Calibration Information (part 2414311)'
PERIOD = 'printed'                         # the manual prints ONE set of limits (no 24 hour / 90 day / 1 year split)

# (step, clamp reading A, frequency Hz, calibrator output A, turns, LCOMP, printed lower mA, printed upper mA, DMM range A)
STEPS = [
    (1, '1', 45, '1', 1, 'OFF', '0.920', '1.080', '0.01'),
    (2, '100', 400, '2.0', 50, 'ON', '97.94', '102.06', '1'),
    (3, '400', 60, '8.0', 50, 'ON', '391.94', '408.06', '1'),
]
# hook-up group by calibrator output: the 5522A / 5520A low-current (AUX) output covers up to 2.99999 A, the 20 A output the rest; the 5560A has VI AUX and 30A (as the 376 / 365 specs)
GROUP = {'1': 'WIRE_1T', '2.0': 'COIL_AUX', '8.0': 'COIL_20A'}
OUTPUT_PER_AMP = D('0.001')                # 1 mA per ampere (Electrical Specifications, p. 3)
ACC_REL, ACC_ABS = D('0.02'), D('0.06')    # 2 % + 0.06 A (p. 3), 45 Hz to 400 Hz

SETUP_WIRE = ('Calibrator output (5560A: VI AUX / OUTPUT LO; 5522A / 5520A: AUX HI / AUX LO) through a single-turn copper wire loop (larger than #14 gauge, about 6 in diameter) '
              '- the clamp jaws closed round the wire, centred (Figure 2, p. 6).  The clamp output cable goes to the multimeter mA ac input and COM.  Calibrator LCOMP OFF.')
SETUP_COIL = ('Calibrator current output (below 3 A: 5560A VI AUX / OUTPUT LO, 5522A / 5520A AUX HI / AUX LO; 3 A and above: 5560A 30A / OUTPUT LO, 5522A / 5520A 20 A / AUX LO) through the 50-turn coil '
              '(Fluke 5500A/Coil) - the clamp jaws closed round the coil, centred (Figure 3, p. 7).  The clamp output cable goes to the multimeter mA ac input and COM.  Calibrator LCOMP ON.')


def build() -> dict:
    points = []
    for step, clamp, hz, applied, turns, lcomp, lo_text, hi_text, rng in STEPS:
        clamp_d, applied_d = D(clamp), D(applied)
        nominal_ma = clamp_d * OUTPUT_PER_AMP * 1000                       # mA the clamp should give
        half = (ACC_REL * clamp_d + ACC_ABS) * OUTPUT_PER_AMP * 1000       # mA, full specification
        lo, hi = D(lo_text), D(hi_text)
        if abs((lo + hi) / 2 - nominal_ma) > D('0.0000001') or abs((hi - lo) / 2 - half) > D('0.0000001'):
            raise SystemExit(f'step {step}: printed limits {lo_text} .. {hi_text} mA disagree with {nominal_ma} mA +/- {half} mA (2 % + 0.06 A)')
        if applied_d * turns != clamp_d:
            raise SystemExit(f'step {step}: {applied} A x {turns} turns is not {clamp} A')
        points.append({
            'step': step,
            'kind': 'ACI',
            'nominal': float(nominal_ma / 1000),                           # amps at the clamp's output
            'range': float(rng),
            'frequency': float(hz),
            'limits': {PERIOD: float(half / 1000)},                        # +/- half-width, amps
            'printed_limits': {PERIOD: f'{lo_text} mA to {hi_text} mA'},
            'quick': True,
            'plc': None,
            'clamp_amps': float(clamp_d),
            'applied': {'value': float(applied_d), 'frequency': float(hz), 'unit': 'A'},
            'turns': turns,
            'lcomp': lcomp,
            'group': GROUP[applied],
            'ref': f'Table 3 step {step}',
        })
    wire, coil = [p for p in points if p['turns'] == 1], [p for p in points if p['turns'] == 50]
    assert all(p['group'] for p in points)
    return {
        'schema': 1,
        'manufacturer': 'Fluke',
        'model': 'i400',
        'title': 'i400 AC Current Clamp - Current Accuracy Tests',
        'idn_match': [],
        'source': {'document': DOCUMENT, 'tables': 'Table 3 (p. 6), Figures 2 and 3 (pp. 6 - 7), Table 2 (p. 5), Electrical Specifications (p. 3)',
                   'note': 'Fluke i400 Calibration Information 2414311, Table 3 Accuracy Tests (p. 6)'},
        'periods': [PERIOD],
        'default_period': PERIOD,
        'front_rear_switch': False,
        'equipment': {
            'calibrator': 'AC current 0 - 8 A, 0.15 %, 45 - 400 Hz (recommended: Fluke 5520A; the program also offers the 5560A and 5522A)',
            'multimeter': 'AC current 1 mA - 400 mA, 0.5 %, 45 - 400 Hz (recommended: Fluke 189 in mA ac)',
            'wire_loop': 'single-turn copper wire loop, larger than #14 gauge, 6 in diameter',
            'coil': 'toroid coil, 50 turns, Fluke 5500A/Coil',
        },
        'general': ['The multimeter is pre-calibrated at each step with the calibrator (LCOMP OFF) and its error is added to the clamp reading (Table 3 footnote, p. 6): '
                    'the program does this when the pre-calibration option is on.'],
        'measure': {'ac_bandwidth': 20, 'note': 'AC current function of the reading multimeter; the manual states no filter or speed (UNVERIFIED engineering choice: 20 Hz AC filter on the 34410A / 34411A).'},
        'accuracy': {'text': '2 % + 0.06 A, 45 Hz to 400 Hz', 'output': '1 mA/A', 'range': '1 A to 400 A ac rms', 'page': 3,
                     'rel': str(ACC_REL), 'abs_a': str(ACC_ABS)},
        'sections': [
            {'id': 'wire', 'title': 'Current accuracy - single-turn wire', 'page': '6 (Table 3 step 1, Figure 2)', 'source': 'calibrator', 'setup': SETUP_WIRE, 'points': wire},
            {'id': 'coil', 'title': 'Current accuracy - 50-turn coil', 'page': '6 - 7 (Table 3 steps 2 - 3, Figure 3)', 'source': 'calibrator', 'setup': SETUP_COIL, 'points': coil},
        ],
    }


if __name__ == '__main__':
    spec = build()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {OUT.name}: {n} points, limits agree with 2 % + 0.06 A at every step')
