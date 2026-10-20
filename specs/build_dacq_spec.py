"""Writes specs/keysight_34970a_pv.json and specs/keysight_34972a_pv.json.

Source: Keysight 34970A/34972A Data Acquisition / Switch Unit Service Guide, Chapter 4 "Calibration Procedures",
Internal DMM Verification Tests, pp. 80-87 (limit tables read from the rendered page images, not from extracted text).
Both models share the same internal DMM and the same tables; only the interface differs (RS-232 / USB), so one table feeds both files.

Each point carries a 'role' that the procedure turns into a channel for the plug-in module in use:
    short    channel with the low-thermal short (34901A ch 9, 34902A ch 7); 4-wire pairs use the partner channel (+10 / +8)
    input    channel the calibrator is connected to (34901A ch 10, 34902A ch 8)
    current  34901A ch 21 (current input); the 34902A has none, so current points are skipped with that module
and a 'group' = the hook-up (diagram) key.

Run:  python specs/build_dacq_spec.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERIODS = ['24h', '90d', '1y']
U, M = 1e-6, 1e-3


def lim(a, b, c):
    return dict(zip(PERIODS, (a, b, c)))


def pt(kind, nominal, rng, limits, group, role, **extra):
    p = dict(kind=kind, nominal=nominal, range=rng, limits=lim(*limits), quick=False, group=group, role=role)
    p.update(extra)
    return p


# ---- zero offset (p. 80-81): copper short on the input channel, calibrator NOT used ------------------------------
ZERO_V = [(0.1, (3.5 * U, 4 * U, 4 * U)), (1, (6 * U, 7 * U, 7 * U)), (10, (40 * U, 50 * U, 50 * U)),
          (100, (600 * U, 600 * U, 600 * U)), (300, (6 * M, 9 * M, 9 * M))]
ZERO_R = [(100, (3.5 * M, 4 * M, 4 * M)), (1e3, (6 * M, 10 * M, 10 * M)), (1e4, (50 * M, 100 * M, 100 * M)),
          (1e5, (500 * M, 1, 1)), (1e6, (10, 10, 10)), (1e7, (100, 100, 100)), (1e8, (1e4, 1e4, 1e4))]
ZERO_I = [(0.01, (1 * U, 2 * U, 2 * U)), (0.1, (4 * U, 5 * U, 5 * U)), (1, (60 * U, 100 * U, 100 * U))]

# ---- gain (p. 82-83) -----------------------------------------------------------------------------------------------
GAIN_V = [(-10, 10, (190 * U, 250 * U, 400 * U)), (0.1, 0.1, (6.5 * U, 8 * U, 9 * U)), (1, 1, (26 * U, 37 * U, 47 * U)),
          (10, 10, (190 * U, 250 * U, 400 * U)), (100, 100, (2.6 * M, 4.1 * M, 5.1 * M)), (300, 300, (12 * M, 19.5 * M, 22.5 * M))]
GAIN_R = [(100, (6.5 * M, 12 * M, 14 * M)), (1e3, (26 * M, 90 * M, 110 * M)), (1e4, (250 * M, 900 * M, 1.1)),
          (1e5, (2.5, 9, 11)), (1e6, (30, 90, 110)), (1e7, (1.6e3, 2.1e3, 4.1e3)), (1e8, (310e3, 810e3, 810e3))]
GAIN_I = [(0.01, (1.5 * U, 5 * U, 7 * U)), (0.1, (14 * U, 35 * U, 55 * U)), (1, (560 * U, 900 * U, 1.1 * M))]

# ---- AC volts (p. 84): V rms, Hz, range, limits -------------------------------------------------------------------
AC_V = [(0.1, 1e3, 0.1, (70 * U, 90 * U, 100 * U)), (0.1, 50e3, 0.1, (150 * U, 160 * U, 170 * U)),
        (1, 1e3, 1, (700 * U, 900 * U, 1 * M)), (1, 50e3, 1, (1.5 * M, 1.6 * M, 1.7 * M)),
        (10, 1e3, 10, (7 * M, 9 * M, 10 * M)), (10, 50e3, 10, (15 * M, 16 * M, 17 * M)), (10, 10, 10, (7 * M, 9 * M, 10 * M)),
        (0.01, 1e3, 0.1, (34 * U, 45 * U, 46 * U)),
        (100, 1e3, 100, (70 * M, 90 * M, 100 * M)), (100, 50e3, 100, (150 * M, 160 * M, 170 * M)),
        (300, 1e3, 300, (270 * M, 390 * M, 420 * M)), (300, 50e3, 300, (600 * M, 690 * M, 720 * M))]
AC_V_NOTE = {(0.01, 1e3): 'Isolate the calibrator output from earth ground for this point (manual footnote b).',
             (300, 50e3): 'Some calibrators struggle to drive the DMM and cable load at this V-Hz product; use short, low-capacitance cable. '
                          'The manual says verification can be done at >195 V rms and new limits computed from the Chapter 1 specification.'}

# ---- AC current (p. 85): A, Hz, range ------------------------------------------------------------------------------
AC_I = [(0.01, 1e3, 0.01, (14 * U, 14 * U, 14 * U)), (0.1, 1e3, 0.1, (600 * U, 600 * U, 600 * U)),
        (0.01, 1e3, 1, (1.41 * M, 1.41 * M, 1.41 * M)), (1, 1e3, 1, (1.4 * M, 1.4 * M, 1.4 * M))]

# ---- frequency (p. 86): V rms, Hz, voltage range -------------------------------------------------------------------
FREQ = [(0.01, 100, 0.1, (0.06, 0.1, 0.1)), (1, 100e3, 1, (6, 10, 10))]

# ---- optional AC tests (p. 87): V rms, Hz, range --------------------------------------------------------------------
OPT_AC = [(1, 20, 1, (700 * U, 900 * U, 1 * M)), (1, 20e3, 1, (700 * U, 900 * U, 1 * M)), (1, 100e3, 1, (6.3 * M, 6.8 * M, 6.8 * M)),
          (1, 200e3, 1, (45 * M, 45 * M, 45 * M)), (1, 250e3, 1, (45 * M, 45 * M, 45 * M)), (1, 300e3, 1, (45 * M, 45 * M, 45 * M)),
          (10, 1e3, 10, (7 * M, 9 * M, 10 * M)), (1, 1e3, 10, (3.4 * M, 4.5 * M, 4.6 * M)), (0.1, 1e3, 10, (13 * M, 14 * M, 14.06 * M))]


def plus(limits, extra):
    return tuple(v + extra for v in limits)


def sections():
    z_short = [pt('DCV', 0.0, r, l, 'ZERO_SHORT', 'short', input='short', plc=10) for r, l in ZERO_V]
    z_short += [pt('OHM4', 0.0, r, l, 'ZERO_SHORT', 'short', input='short', plc=10) for r, l in ZERO_R]
    z_open = [pt('DCI', 0.0, r, l, 'ZERO_OPEN', 'current', input='open', plc=10) for r, l in ZERO_I]
    z2w = [pt('OHM2', 0.0, r, plus(l, 4.0), 'ZERO_SHORT', 'short', input='short', plc=10,
              note='2-wire: the manual says to add 4 ohm of error (footnote c); applied to the limit.') for r, l in ZERO_R]
    gain_v = [pt('DCV', n, r, l, 'DCV', 'input', plc=10) for n, r, l in GAIN_V]
    gain_r4 = [pt('OHM4', r, r, l, 'OHM4', 'input', plc=10, **({'note': 'Verify only, no adjustment required (manual footnote c).'} if r == 1e8 else {}))
               for r, l in GAIN_R]
    gain_i = [pt('DCI', r, r, l, 'DCI', 'current', plc=10) for r, l in GAIN_I]
    gain_r2 = [pt('OHM2', r, r, plus(l, 1.0), 'OHM2', 'input', plc=10,
                  note='2-wire: the manual says to add 1 ohm of error (footnote d) and to use a 1 s channel delay with the 5700 in 2-wire compensated mode.')
               for r, l in GAIN_R]
    acv = [pt('ACV', v, rng, l, 'ACV', 'input', frequency=f, filter_hz=3, **({'note': AC_V_NOTE[(v, f)]} if (v, f) in AC_V_NOTE else {}))
           for v, f, rng, l in AC_V]
    aci = [pt('ACI', a, rng, l, 'ACI', 'current', frequency=f, filter_hz=3) for a, f, rng, l in AC_I]
    freq = [pt('FREQ', f, rng, l, 'FREQ', 'input', amplitude=v,
               **({'note': 'Isolate the calibrator output from earth ground for this point (manual footnote b).'} if v == 0.01 else {}))
            for v, f, rng, l in [(a, b, c, d) for a, b, c, d in FREQ]]
    opt_ac = [pt('ACV', v, rng, l, 'ACV', 'input', frequency=f, filter_hz=3, opt='ac') for v, f, rng, l in OPT_AC]
    for p in z2w + gain_r2:
        p['opt'] = 'ohm2'

    def sec(id_, title, page, setup, points, source='calibrator', optional=False):
        s = dict(id=id_, title=title, page=page, setup=setup, source=source, points=points)
        if optional:
            s['optional'] = True
        return s

    return [
        sec('zero_short', 'Zero offset: shorted input', '80-81', 'Low-thermal copper short on the input channel (and its 4-wire partner channel). The calibrator is not used.',
            z_short, source='none'),
        sec('zero_open', 'Zero offset: current open', '80', 'Current input channel left OPEN. The calibrator is not used.', z_open, source='none'),
        sec('dcv', 'DC volts gain', '82', 'Calibrator voltage output to the input channel HI / LO.', gain_v),
        sec('ohm4', '4-wire ohms gain', '82', 'Calibrator resistance output, 4-wire: force to the input channel, sense to its 4-wire partner channel.', gain_r4),
        sec('dci', 'DC current gain', '83', 'Calibrator current output to the current input channel.', gain_i),
        sec('acv', 'AC volts gain', '84', 'Calibrator AC voltage output to the input channel HI / LO. 3 Hz AC filter (7 s per reading).', acv),
        sec('aci', 'AC current gain', '85', 'Calibrator AC current output to the current input channel. 3 Hz AC filter (7 s per reading).', aci),
        sec('freq', 'Frequency gain', '86', 'Calibrator AC voltage at the stated level and frequency to the input channel HI / LO.', freq),
        sec('zero_ohm2', '2-wire ohms zero (optional)', '81', 'Short on the input channel. The calibrator is not used.', z2w[:], source='none', optional=True),
        sec('ohm2', '2-wire ohms gain (optional)', '83', 'Calibrator resistance output, 2-wire, to the input channel HI / LO (34901A channel 10 / 34902A channel 8 recommended).', gain_r2, optional=True),
        sec('opt_ac', 'Optional AC tests', '87', 'Calibrator AC voltage output to the input channel HI / LO.', opt_ac, optional=True),
    ]


def spec(model, interface):
    return {
        'schema': 1, 'manufacturer': 'Keysight', 'model': model, 'title': f'{model} Internal DMM Performance Verification',
        'idn_match': [model], 'interface': interface,
        'source': {'document': 'Keysight 34970A/34972A Data Acquisition / Switch Unit Service Guide', 'pages': '80-87 (Internal DMM Verification Tests)',
                   'note': 'Limits are the published error from nominal. The default is the 1-year limit (calibration interval). The 24-hour limits apply only within 24 hours of an adjustment.'},
        'periods': PERIODS, 'default_period': '1y',
        'equipment': {'multiplexer': 'Keysight 34901A 20-channel multiplexer in slot 200 (34902A: no current tests)', 'calibrator': 'Fluke 5560A or 5522A (manual lists the 5700A)',
                      'zero': 'Low-thermal copper shorts on the input channels'},
        'channels': {'34901A': {'short': 9, 'input': 10, 'current': 21, 'pair_offset': 10},
                     '34902A': {'short': 7, 'input': 8, 'current': None, 'pair_offset': 8}},
        'general': ['Ambient 18-28 C (ideally 23 +/- 1 C), humidity below 80 %.',
                    'Warm up 2 hours with a copper short connected and the multiplexer installed before verification.',
                    'Use shielded twisted-pair PTFE cable, as short as possible; connect the shield to the source LO and the calibrator LO to earth ground except where noted.',
                    'Select 6.5 digit resolution (10 PLC) for DC, resistance and frequency tests; AC tests use the 3 Hz slow filter.',
                    'Allow source settling before every reading.'],
        'sections': sections(),
    }


if __name__ == '__main__':
    for model, interface in (('34970A', 'rs232'), ('34972A', 'usb')):
        path = HERE / f'keysight_{model.lower()}_pv.json'
        s = spec(model, interface)
        path.write_text(json.dumps(s, indent=1), encoding='utf-8')
        n = sum(len(x['points']) for x in s['sections'])
        print(f'{path.name}: {n} points')
