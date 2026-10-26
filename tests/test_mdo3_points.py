"""Tektronix 3 Series MDO (MDO32 / MDO34) procedure: the spec against a second reading of the manual, the builder, the per-model flags, the driver registry,
the shared engine's MDO3 family (and that the MDO4000C family is untouched), every point on the simulated bench, the review-window rows, a whole
virtual (demo) run with the PDF, and the Qt window (skipped without PySide6).  tkinter is stubbed in setUpModule.

Manual: 3 Series MDO Specifications and Performance Verification 077-1499-10 (test record pp. 48-89, procedures pp. 90-130); programmer manual 077-1498-06.
Run:  python -m unittest tests.test_mdo3_points
"""
import collections
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / 'tests'), str(ROOT / 'Procedures')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SPEC = json.loads((ROOT / 'specs' / 'tektronix_mdo3_pv.json').read_text(encoding='utf-8'))
POINTS = SPEC['points']
MODELS = ['32-100', '34-100', '32-200', '34-200', '32-350', '34-350', '32-500', '34-500', '32-1000', '34-1000']
M = None


def setUpModule():
    global M
    import _tk_stub
    _tk_stub.install()
    import mdo4000c_verification as _m
    M = _m


def tearDownModule():
    if M is not None:
        M.configure('MDO4000C')


def models_of(p):
    return p.get('models') or MODELS


def applies(p, model, sa='SA3', afg=True, dvm=True, tpa=False):
    if model not in models_of(p):
        return False
    ok = {'SA3': sa == 'SA3', 'noSA3': sa != 'SA3', 'AFG': afg, 'DVM': dvm, 'TPA': tpa, 'noTPA': not tpa}
    return all(ok[t] for t in p.get('req') or [])


def find(section, desc, ch=None, model=None):
    hits = [p for p in POINTS if p['section'] == section and p['desc'] == desc and (ch is None or p['ch'] == ch) and (model is None or model in models_of(p))]
    assert len(hits) >= 1, (section, desc, ch, model)
    return hits


def f(text):
    """'707.3 mV' -> float, Decimal on the way (the second reading is typed as printed)."""
    num, _, unit = text.replace('–', '-').partition(' ')
    scale = {'p': D('1e-12'), 'n': D('1e-9'), 'µ': D('1e-6'), 'm': D('1e-3'), 'k': D('1e3'), 'M': D('1e6'), 'G': D('1e9')}
    base = unit.rstrip('VsHzΩ')
    return float(D(num) * (scale[base] if base else 1))


# ======================================================================================================================================================
# the spec: a second reading of the printed tables (typed again from the page images, independently of specs/build_mdo3_spec.py)
# ======================================================================================================================================================
class SecondReading(unittest.TestCase):
    def test_sections_and_pages(self):
        got = [(s['id'], s['page'], s['record_page']) for s in SPEC['sections']]
        self.assertEqual(got, [('selftest', 90, 48), ('imp', 91, 49), ('bal', 92, 50), ('bw', 94, 56), ('gain', 97, 57), ('off', 101, 60), ('srate', 103, 63),
                               ('noise', 104, 64), ('dt', 105, 67), ('danl', 110, 80), ('spur', 113, 80), ('level', 114, 81), ('tpa', 117, 82), ('tpadanl', 119, 82),
                               ('trig', 122, 82), ('afgf', 123, 83), ('afga', 125, 83), ('afgo', 126, 83), ('dvmdc', 127, 84), ('dvmac', 129, 86), ('dvmf', 130, 88)])

    def test_input_impedance_p49(self):
        for ch in (1, 2, 3, 4):
            for vs in ('10 mV', '100 mV'):
                (p,) = find('imp', f'CH{ch} 1 MΩ, {vs}/div', ch)
                self.assertEqual((p['low'], p['high']), (990e3, 1.01e6))
                (p,) = find('imp', f'CH{ch} 50 Ω, {vs}/div', ch)
                self.assertEqual((p['low'], p['high']), (49.5, 50.5))

    def test_dc_balance_pp50_55_in_divisions(self):
        rows = {'50 Ω': {'1 mV': '0.500', '2 mV': '0.250', '10 mV': '0.200', '100 mV': '0.200', '1 V': '0.200'},
                '1 MΩ': {'1 mV': '0.300', '2 mV': '0.200', '10 mV': '0.200', '100 mV': '0.200', '1 V': '0.200'}}
        n = 0
        for ch in (1, 2, 3, 4):
            for bw in ('20 MHz BW', '250 MHz BW', 'Full BW'):
                for term, lims in rows.items():
                    for vs, lim in lims.items():
                        (p,) = find('bal', f'CH{ch} {term}, {bw}, {vs}/div', ch)
                        self.assertEqual((p['low'], p['high'], p['unit'], p['per_div']), (-float(lim), float(lim), 'div', True))
                        self.assertEqual(p['stim'], 'none')
                        n += 1
        self.assertEqual(n, 120)

    def test_gain_pp57_59_and_worksheet_pp98_100(self):
        rows = [('1 mV', '7 mV', '2.5'), ('2 mV', '14 mV', '2.0'), ('4.98 mV', '34.86 mV', '3.0'), ('5 mV', '35 mV', '1.5'), ('10 mV', '70 mV', '1.5'),
                ('20 mV', '140 mV', '1.5'), ('49.8 mV', '348.6 mV', '3.0'), ('50 mV', '350 mV', '1.5'), ('100 mV', '700 mV', '1.5'), ('200 mV', '1400 mV', '1.5'),
                ('500 mV', '3500 mV', '1.5'), ('1 V', '7000 mV', '1.5')]
        for ch in (1, 2, 3, 4):
            for vs, vd, lim in rows:
                (p,) = find('gain', f'CH{ch} 1 MΩ, 20 MHz BW, {vs}/div', ch)
                self.assertEqual((p['low'], p['high'], p['term'], p['bw']), (-float(lim), float(lim), '1M', 'TWEnty'))
                self.assertAlmostEqual(p['vdiff'], f(vd), places=12)
                self.assertAlmostEqual(p['vpos'], f(vd) / 2, places=12)
                self.assertAlmostEqual(p['vneg'], -f(vd) / 2, places=12)

    def test_offset_pp60_63(self):
        rows = [('1 mV', '700 mV', '692.7 mV', '707.3 mV'), ('2 mV', '700 mV', '692.6 mV', '707.4 mV'), ('10 mV', '1 V', '988 mV', '1012 mV'),
                ('100 mV', '10 V', '9.88 V', '10.12 V'), ('1 V', '100 V', '98.80 V', '101.2 V'), ('1.01 V', '100 V', '98.80 V', '101.2 V')]
        for ch in (1, 2, 3, 4):
            for vs, off, lo, hi in rows:
                pos = [p for p in POINTS if p['section'] == 'off' and p['ch'] == ch and p['desc'].startswith(f'CH{ch} 1 MΩ, 20 MHz BW, {vs}/div,')]
                self.assertEqual(len(pos), 2)
                plus = next(p for p in pos if p['offset'] > 0)
                minus = next(p for p in pos if p['offset'] < 0)
                self.assertAlmostEqual(plus['offset'], f(off), places=12)
                self.assertAlmostEqual(plus['low'], f(lo), places=12); self.assertAlmostEqual(plus['high'], f(hi), places=12)
                self.assertAlmostEqual(minus['low'], -f(hi), places=12); self.assertAlmostEqual(minus['high'], -f(lo), places=12)
                self.assertEqual(plus['hscale'], 0.02)

    def test_bandwidth_frequencies_worksheet_pp95_96_and_specification_p15(self):
        want = {100: ['100 MHz'] * 4, 200: ['200 MHz', '200 MHz', '200 MHz', '150 MHz'], 350: ['350 MHz', '350 MHz', '350 MHz', '150 MHz'],
                500: ['500 MHz', '500 MHz', '350 MHz', '150 MHz'], 1000: ['1 GHz', '500 MHz', '350 MHz', '150 MHz']}
        for bw, freqs in want.items():
            for ch in (1, 2, 3, 4):
                for vs, fr in zip(('10 mV', '5 mV', '2 mV', '1 mV'), freqs):
                    (p,) = find('bw', f'CH{ch} 50 Ω, {vs}/div, {fr}', ch, model=f'34-{bw}')
                    self.assertEqual(p['freq'], f(fr))
                    self.assertEqual((p['low'], p['high'], p['ref_hz'], p['hscale']), (0.707, None, 10e6, 4e-9))
                    self.assertAlmostEqual(p['vin_pp'], 8 * f(vs), places=12)
                    self.assertEqual(set(models_of(p)), {f'32-{bw}', f'34-{bw}'} if ch < 3 else {f'34-{bw}'})

    def test_random_noise_pp64_66(self):
        want = {1000: {'Full BW': ['3.1', '3.1', '3.1', '3.4'], '250 MHz BW': ['3.4'] * 4, '20 MHz BW': ['3.4'] * 4},
                500: {'Full BW': ['3.1'] * 4, '250 MHz BW': ['3.3'] * 4, '20 MHz BW': ['3.25'] * 4},
                350: {'Full BW': ['3.3'] * 4, '250 MHz BW': ['3.3'] * 4, '20 MHz BW': ['3.25'] * 4},
                200: {'Full BW': ['3.25'] * 4, '20 MHz BW': ['3.25'] * 4}, 100: {'Full BW': ['2.85'] * 4, '20 MHz BW': ['3.25'] * 4}}
        for bw, rows in want.items():
            pts = [p for p in POINTS if p['section'] == 'noise' and f'34-{bw}' in models_of(p)]
            self.assertEqual(len(pts), 4 * len(rows))
            for name, lims in rows.items():
                for ch, lim in zip((1, 2, 3, 4), lims):
                    (p,) = find('noise', f'CH{ch} 50 Ω, {name}, 100 mV/div', ch, model=f'34-{bw}')
                    self.assertAlmostEqual(p['high'], float(lim) / 1000, places=12)
                    self.assertEqual((p['term'], p['vscale'], p['method'], p['low']), ('50', 0.1, 'rms_mean', None))
        (p,) = find('noise', 'CH4 50 Ω, Full BW, 100 mV/div', 4, model='34-1000')
        self.assertIn('3.4 mV', p['note'])

    def test_sample_rate_p63(self):
        (p,) = [p for p in POINTS if p['section'] == 'srate']
        self.assertEqual((p['low'], p['high'], p['unit'], p['period'], p['vpp'], p['coarse_hscale'], p['fine_hscale']), (-2.0, 2.0, 'div', 0.08, 1.0, 0.02, 4e-7))

    def test_delta_time_pp67_77(self):
        lt1g = [('4 ns', '240 MHz', [('100 mV', '800 mV', '233 ps'), ('500 mV', '4 V', '233 ps'), ('1 V', '4 V', '237 ps')]),
                ('40 ns', '24 MHz', [('5 mV', '40 mV', '435 ps'), ('100 mV', '800 mV', '359 ps'), ('500 mV', '4 V', '356 ps'), ('1 V', '4 V', '583 ps')]),
                ('400 ns', '2.4 MHz', [('5 mV', '40 mV', '3.69 ns'), ('100 mV', '800 mV', '2.75 ns'), ('500 mV', '4 V', '2.71 ns'), ('1 V', '4 V', '5.36 ns')]),
                ('4 µs', '240 kHz', [('5 mV', '40 mV', '36.8 ns'), ('100 mV', '800 mV', '27.4 ns'), ('500 mV', '4 V', '27.0 ns'), ('1 V', '4 V', '53.5 ns')]),
                ('40 µs', '24 kHz', [('5 mV', '40 mV', '368 ns'), ('100 mV', '800 mV', '274 ns'), ('500 mV', '4 V', '270 ns'), ('1 V', '4 V', '535 ns')]),
                ('400 µs', '2.4 kHz', [('5 mV', '40 mV', '3.68 µs'), ('100 mV', '800 mV', '2.74 µs'), ('500 mV', '4 V', '2.70 µs'), ('1 V', '4 V', '5.35 µs')])]
        g1 = {('4 ns', '100 mV'): '119 ps', ('4 ns', '500 mV'): '119 ps', ('4 ns', '1 V'): '128 ps', ('40 ns', '5 mV'): '386 ps', ('40 ns', '100 mV'): '298 ps',
              ('40 ns', '500 mV'): '294 ps', ('40 ns', '1 V'): '584 ps'}
        for model in ('34-350', '34-1000'):
            for ch in (1, 2, 3, 4):
                for hs, fr, rows in lt1g:
                    for vs, vpp, hi in rows:
                        want = g1.get((hs, vs), hi) if model == '34-1000' else hi
                        (p,) = find('dt', f'CH{ch} {hs}/div, {fr}, {vs}/div ({vpp} p-p)', ch, model=model)
                        self.assertAlmostEqual(p['high'], f(want), places=20)
                        self.assertAlmostEqual(p['vpp'], f(vpp), places=12)
        four_ns = [p for p in POINTS if p['section'] == 'dt' and p['hscale'] == 4e-9]
        for p in four_ns:
            self.assertFalse(set(models_of(p)) & {'32-100', '34-100', '32-200', '34-200'}, p['desc'])   # 'does not apply to 100 and 200 MHz models'
        self.assertEqual(sum(1 for p in POINTS if p['section'] == 'dt' and '34-200' in models_of(p)), 4 * 20)
        self.assertEqual(sum(1 for p in POINTS if p['section'] == 'dt' and '34-1000' in models_of(p)), 4 * 23)

    def test_rf_tables_pp80_82(self):
        danl = [(p['desc'], p['high'], p.get('req')) for p in POINTS if p['section'] == 'danl']
        self.assertEqual(danl, [('9 kHz to 50 kHz', -109, ['noTPA']), ('50 kHz to 5 MHz', -126, ['noTPA']),
                                ('5 MHz to 1 GHz (3-SA3 not installed)', -136, ['noSA3', 'noTPA']),
                                ('5 MHz to 2 GHz (3-SA3 installed)', -136, ['SA3', 'noTPA']), ('2 GHz to 3 GHz (3-SA3 installed)', -126, ['SA3', 'noTPA'])])
        tdanl = [p['high'] for p in POINTS if p['section'] == 'tpadanl']
        self.assertEqual(tdanl, [-117, -138, -148, -148, -138])
        for p in POINTS:
            if p['kind'] == 'DANL':
                self.assertEqual((p['ref_level'], p['detection']), (-30.0 if p.get('tpa') else -15.0, 'AVErage'))
        spurs = [(p['desc'], p['high']) for p in POINTS if p['section'] == 'spur']
        self.assertEqual([h for _d, h in spurs], [-78, -78, -78, -78, -76, -78, -62])
        level = [(p['level_dbm'], p['f_start'], p['f_stop'], p['high']) for p in POINTS if p['section'] == 'level']
        self.assertEqual(len(level), 24)
        for lvl in (10.0, 0.0, -15.0):
            rows = [(a, b, h) for L, a, b, h in level if L == lvl]
            self.assertEqual(rows, [(50e3, 50e3, 1.0), (100e3, 900e3, 1.0), (1e6, 9e6, 1.0), (10e6, 90e6, 1.0), (100e6, 1e9, 1.0), (100e6, 1.5e9, 1.0),
                                    (1.6e9, 2.5e9, 1.3), (2.6e9, 3e9, 1.5)])
        tpa = [(p['freq'], p['level_dbm'], p['ref_level'], p['low'], p['high'], p['req']) for p in POINTS if p['section'] == 'tpa']
        self.assertEqual(tpa, [(1.7e9, -20.0, -15.0, -1.5, 1.5, ['SA3', 'TPA']), (1.7e9, -35.0, -30.0, -1.5, 1.5, ['SA3', 'TPA']),
                               (2.9e9, -20.0, -15.0, -1.5, 1.5, ['SA3', 'TPA']), (2.9e9, -35.0, -30.0, -1.5, 1.5, ['SA3', 'TPA'])])
        trig = [(p['desc'], p['low'], p['high']) for p in POINTS if p['section'] == 'trig']
        self.assertEqual(trig, [('Aux out HIGH, 1 MΩ', 2.25, None), ('Aux out LOW, 1 MΩ', None, 0.7), ('Aux out HIGH, 50 Ω', 0.9, None), ('Aux out LOW, 50 Ω', None, 0.25)])

    def test_afg_p83(self):
        got = [(p['kind'], p['nominal'], p['low'], p['high']) for p in POINTS if p['section'] in ('afgf', 'afga', 'afgo')]
        want = [('AFGFREQ', 10e3, 9998.7, 10001.3), ('AFGFREQ', 50e6, 49.9975e6, 50.0025e6), ('AFGFREQ', 25e3, 24998.75, 25001.25),
                ('AFGFREQ', 25e6, 24.99875e6, 25.00125e6), ('AFGAMP', 0.01, 0.00935, 0.01065), ('AFGAMP', 0.5, 0.4905, 0.5095),
                ('AFGOFF', 0.02, 0.0187, 0.0213), ('AFGOFF', 1.0, 0.984, 1.016), ('AFGOFF', -1.0, -1.016, -0.984)]
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            self.assertEqual(g[0], w[0])
            for a, b in zip(g[1:], w[1:]):
                self.assertAlmostEqual(a, b, places=9)

    def test_dvm_pp84_89(self):
        dc = [('1', '-5', '-5', '-5.117', '-4.883'), ('0.5', '-2', '-2', '-2.052', '-1.948'), ('0.5', '-1', '-0.5', '-1.0345', '-0.9655'),
              ('0.2', '-0.5', '-0.5', '-0.5175', '-0.4825'), ('0.01', '0.002', '0', '-0.00042', '0.00442'), ('0.2', '0.5', '0.5', '0.4825', '0.5175'),
              ('0.5', '1', '0.5', '0.9655', '1.0345'), ('0.5', '2', '2', '1.948', '2.052'), ('1', '5', '5', '4.883', '5.117')]
        for ch in (1, 2, 3, 4):
            pts = [p for p in POINTS if p['section'] == 'dvmdc' and p['ch'] == ch]
            self.assertEqual(len(pts), 9)
            for p, (vs, vin, off, lo, hi) in zip(pts, dc):
                self.assertEqual((p['vscale'], p['nominal'], p['offset']), (float(vs), float(vin), float(off)))
                self.assertAlmostEqual(p['low'], float(lo), places=12); self.assertAlmostEqual(p['high'], float(hi), places=12)
            self.assertIn('-0.00042 V is applied', pts[4]['note'])            # the printed 0.00042 (sign lost) is CORRECTED with a visible note
            ac = [(p['vpp'], p['low'], p['high']) for p in POINTS if p['section'] == 'dvmac' and p['ch'] == ch]
            self.assertEqual(ac, [(0.02, 0.0098, 0.0102), (0.05, 0.0245, 0.0255), (0.5, 0.245, 0.255), (1.0, 0.49, 0.51), (5.0, 2.45, 2.55)])
            fr = [(p['nominal'], p['low'], p['high']) for p in POINTS if p['section'] == 'dvmf' and p['ch'] == ch]
            self.assertEqual(fr, [(9.0, 8.9998, 9.0002), (99.0, 98.998, 99.002), (999.0, 998.98, 999.02), (99e3, 98.998e3, 99.002e3), (999e3, 998.98e3, 999.02e3),
                                  (150e6, 149.99e6, 150.01e6)])
        (p,) = [p for p in POINTS if p['section'] == 'dvmac' and p['ch'] == 1 and p['vpp'] == 5.0]
        self.assertIn('2.450 V to 2.550 V', p['note'])
        p150 = [p for p in POINTS if p['section'] == 'dvmf' and p['nominal'] == 150e6]
        for p in p150:
            self.assertFalse({'32-100', '34-100'} & set(models_of(p)))       # specification p. 46: counter maximum 100 MHz on 100 MHz models
            self.assertEqual((p['counter'], p['vscale'], p['hscale'], p['vpp']), ('trigger', 0.2, 0.02, 1.0))

    def test_discrepancies_are_listed(self):
        text = '\n'.join(SPEC['discrepancies'])
        for needle in ('0.00042', '2.450 mV', 'CH4 Full BW', '150 MHz bandwidth limit', '900 mV', '1.202 V', '50 Ω first', 'worksheet', '50 kHz - 1 GHz',
                       '5 MHz to 2 GHz', '11.5 kHz'):
            self.assertIn(needle, text)


class Builder(unittest.TestCase):
    def test_the_builder_writes_exactly_the_committed_spec(self):
        spec = importlib.util.spec_from_file_location('build_mdo3_spec', ROOT / 'specs' / 'build_mdo3_spec.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)                                                         # builds in memory; writes only under __main__
        self.assertEqual(json.loads(json.dumps(mod.spec, ensure_ascii=False)), SPEC)


class ModelsAndOptions(unittest.TestCase):
    def test_model_flags(self):
        self.assertEqual(SPEC['models'], MODELS)
        info = SPEC['model_info']
        self.assertEqual({m: (i['channels'], i['bandwidth_hz']) for m, i in info.items()},
                         {m: (int(m[1]), float(m.split('-')[1]) * 1e6) for m in MODELS})
        self.assertEqual(info['34-200']['bw_limits'], ['TWEnty'])
        self.assertEqual(info['32-350']['bw_limits'], ['TWEnty', 'TWOFifty'])
        self.assertEqual((info['32-100']['counter_max_hz'], info['34-500']['counter_max_hz']), (100e6, 150e6))

    def test_points_per_model(self):
        counts = {m: sum(applies(p, m, 'SA3', True, True, False) for p in POINTS) for m in MODELS}
        # by hand, MDO34-1000 with 3-SA3 / AFG / DVM: self test 2 + impedance 16 + balance 120 + bandwidth 16 + gain 48 + offset 48 + sample rate 1 + noise 12
        # + delta time 92 + DANL 4 + spurs 6 + level 21 + aux out 4 + AFG 9 + DVM DC 36 + DVM AC 20 + DVM freq 24 = 479.  200 / 100 MHz: no 250 MHz filter
        # (-40 balance, -4 noise), no 4 ns delta-time block (-12); 100 MHz: no 150 MHz counter point (-4).  MDO32: channels 1-2 only.
        self.assertEqual(counts, {'32-100': 233, '34-100': 419, '32-200': 235, '34-200': 423, '32-350': 263, '34-350': 479,
                                  '32-500': 263, '34-500': 479, '32-1000': 263, '34-1000': 479})

    def test_channels_three_and_four_only_on_the_mdo34(self):
        for p in POINTS:
            if p.get('ch') in (3, 4):
                self.assertFalse([m for m in models_of(p) if m.startswith('32')], p['desc'])

    def test_250_mhz_filter_only_on_350_mhz_and_above(self):
        for p in POINTS:
            if p.get('bw') == 'TWOFifty':
                self.assertFalse(set(models_of(p)) & {'32-100', '34-100', '32-200', '34-200'}, p['desc'])

    def test_option_tokens(self):
        tokens = {t for p in POINTS for t in p.get('req') or []}
        self.assertEqual(tokens, {'SA3', 'noSA3', 'AFG', 'DVM', 'TPA', 'noTPA'})
        self.assertEqual([p['id'] for p in POINTS], list(range(1, len(POINTS) + 1)))


# ======================================================================================================================================================
# driver
# ======================================================================================================================================================
class Driver(unittest.TestCase):
    def test_every_command_is_verified_with_a_page(self):
        from drivers.tektronix_mdo3 import COMMANDS
        for key, cmd in COMMANDS.items():
            self.assertTrue(cmd.verified, key)
            self.assertRegex(cmd.ref, r'^3 Series MDO Programmer Manual 077-1498-06 p\. 2-\d{3}', key)
        self.assertEqual((COMMANDS['reset'].template, COMMANDS['reset'].risk), ('*RST', 'locked'))

    def test_the_3_series_command_forms(self):
        from drivers.tektronix_mdo3 import COMMANDS
        t = {k: c.template for k, c in COMMANDS.items()}
        self.assertEqual(t['diag.select'], 'DIAg:SELect ALL')                       # not DIAg:SELect:ALL (p. 2-261)
        self.assertEqual(t['trig.level'], 'TRIGger:A:LEVel:CH{n} {level:.9g}')      # per channel (p. 2-778)
        self.assertEqual(t['dvm.style'], 'DVM:DISPLAYSTYle MINimum')
        self.assertEqual(t['meas.gating.off'], 'MEASUrement:GATing OFF')
        self.assertNotIn('DIAg:STATE?', t.values())                                 # no query form on the 3 Series (p. 2-262)
        self.assertFalse([v for v in t.values() if 'TWEnty' in v or 'TWOFifty' in v])

    def test_driver_is_its_own_and_refuses_other_scopes(self):
        import drivers
        from drivers.tektronix_mdo3 import TektronixMDO3
        self.assertIs(drivers.TektronixMDO3, TektronixMDO3)
        self.assertFalse(issubclass(TektronixMDO3, drivers.TektronixMDO4000C))
        self.assertEqual(TektronixMDO3._model_from_idn('TEKTRONIX,MDO34,C01,CF:91.1CT FV:v1.0'), '34')
        self.assertEqual(TektronixMDO3._model_from_idn('TEKTRONIX,MDO3104,C01,CF:91.1CT FV:v1.0'), '')     # the older MDO3000 series is not this procedure


# ======================================================================================================================================================
# the shared engine
# ======================================================================================================================================================
class EngineFamilies(unittest.TestCase):
    def tearDown(self):
        M.configure('MDO4000C')

    def test_mdo4000c_family_is_the_module_default(self):
        self.assertEqual(M.FAMILY_NAME, 'MDO4000C')
        self.assertEqual(M.SPEC_PATH.name, 'tektronix_mdo4000c_pv.json')
        self.assertEqual(M.App.VIEW, 'mdo4000c_view')
        self.assertEqual(M.MODEL_INFO, {})
        fam = M.FAMILIES['MDO4000C']
        self.assertEqual((fam['label'], fam['settings'], fam['default_model'], fam['scope_addr'], fam['hv_max'], fam['trig_out']),
                         ('MDO4000C', 'MDO4000C', '4104C', 'USB0::0x0699::0x0415::C000000::INSTR', 99.5, 'TRIGGER OUT'))
        optional = {'OFFSET': {'hscale'}, 'SPUR': {'ref_level'}, 'DVMFREQ': {'vscale', 'hscale', 'vpp'}, 'REFFREQ': {'vpp'}}
        for p in M.POINTS:                                         # the optional MDO3 point parameters never appear on an MDO4000C point
            self.assertFalse({'per_div', 'method', 'coarse_hscale', 'fine_hscale', 'detection', 'counter'} & set(p), p['desc'])
            self.assertFalse(optional.get(p['kind'], set()) & set(p), p['desc'])

    def test_configure_round_trip(self):
        before = (M.SPEC_PATH, len(M.POINTS), dict(M.SECTION_PAGE), list(M.MODELS), M.REF_CMC_PATH, M.App.VIEW)
        M.configure('MDO3')
        self.assertEqual((M.SPEC_PATH.name, len(M.POINTS), M.App.VIEW, M.REF_CMC_PATH.name), ('tektronix_mdo3_pv.json', len(POINTS), 'mdo3_view', 'mdo3_reference_cmc.json'))
        self.assertEqual(M.MODELS, MODELS)
        M.configure('MDO4000C')
        self.assertEqual((M.SPEC_PATH, len(M.POINTS), dict(M.SECTION_PAGE), list(M.MODELS), M.REF_CMC_PATH, M.App.VIEW), before)

    def test_launcher(self):
        text = (ROOT / 'Procedures' / 'Tektronix_MDO3_Verification.py').read_text(encoding='utf-8')
        self.assertIn("FAMILY = 'MDO3'", text)
        self.assertIn('mdo4000c_verification.main(family=FAMILY)', text)
        side = json.loads((ROOT / 'Procedures' / 'Tektronix_MDO3_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((side['name'], side['seed_verified'], side['category']), ('Tektronix 3 Series MDO Performance Verification', False, 'Oscilloscope'))


def _fake_app(io, cfg):
    class FakeApp:
        stop = False

        def __init__(s):
            s.io, s.cfg = io, cfg

        def request(s, kind, payload=None):
            if kind == 'manual':
                return payload['p']['nominal']
            if kind == 'reconnect_scope':
                return io.reconnect_scope(attempts=1, wait=0)
            return True

        def post(s, *a, **k):
            pass
    return FakeApp()


def run_all_points(model, sa, afg, dvm, tpa):
    """Every applicable point of one configuration through the real driver over the simulated bench: {id: (reading, raw, result)}, the IO."""
    from drivers.simulated_mdo3 import make_mdo3_bench
    M.SLEEP_SCALE = 0
    bench, t = make_mdo3_bench(model)
    io = M.IO(dict(cal_baud=9600), transports=t)
    cfg = M.Config(model, sa, afg, dvm, tpa)
    io.reset_at_start()
    runner = M.Runner(_fake_app(io, cfg))
    out = {}
    for p in M.POINTS:
        if cfg.applies(p):
            reading, raw = runner.run_point(p)
            out[p['id']] = (reading, dict(raw, reading=reading), M.judge(p, reading))
    return out, io


class SimulatedBench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        M.configure('MDO3')
        cls._sleep = mock.patch('time.sleep', lambda s: None)
        cls._sleep.start()

    @classmethod
    def tearDownClass(cls):
        cls._sleep.stop()
        M.SLEEP_SCALE = 1.0
        M.configure('MDO4000C')

    def test_every_point_of_four_configurations_passes(self):
        for model, sa, afg, dvm, tpa in (('34-1000', 'SA3', True, True, False), ('34-1000', 'SA3', True, True, True), ('32-100', 'None', False, True, False),
                                        ('32-200', 'None', True, False, True)):
            res, io = run_all_points(model, sa, afg, dvm, tpa)
            want = sum(applies(p, model, sa, afg, dvm, tpa) for p in POINTS)
            self.assertEqual(len(res), want, model)
            self.assertEqual(collections.Counter(r for _v, _raw, r in res.values()), {'PASS': want}, model)
            lines = '\n'.join(io.log.lines())
            if model.startswith('32'):
                self.assertNotIn('CH3', lines); self.assertNotIn('CH4', lines)
            io.close()

    def test_outputs_go_off_after_every_point(self):
        res, io = run_all_points('32-200', 'None', True, True, False)
        lines = io.log.lines()
        self.assertGreaterEqual(sum('5560A' in l and '>>  STBY' in l for l in lines), len(res))
        self.assertGreaterEqual(sum('AFG:OUTPut:STATE OFF' in l for l in lines), len(res))
        io.close()

    def test_uncertainty_and_ratios_use_the_mdo4000c_mechanism(self):
        res, io = run_all_points('34-1000', 'SA3', True, True, False)
        by = {p['id']: p for p in M.POINTS}
        texts = collections.defaultdict(set)
        for pid, (_v, raw, _r) in res.items():
            texts[by[pid]['kind']].add(M.uncertainty_text(by[pid], raw))
        for kind in ('GAIN', 'OFFSET', 'DVMDC', 'IMP', 'BW', 'ABSAMP'):         # 5560A budget vs scope CMC / CMC / 96270A sheet
            self.assertTrue(texts[kind] - {'N/A'}, kind)
        for kind in ('BAL', 'NOISE', 'DANL', 'SPUR', 'TRIGOUT', 'SELFTEST', 'SPC'):  # no stimulus: never an uncertainty
            self.assertEqual(texts[kind], {'N/A'}, kind)
        p = next(p for p in M.POINTS if p['kind'] == 'OFFSET' and p['id'] in res)
        self.assertTrue(M.tar_tur_fields(p, dict(raw=res[p['id']][1]))['TUR'])
        io.close()

    def test_failures_are_judged(self):
        p = next(p for p in M.POINTS if p['kind'] == 'BAL')
        self.assertEqual(M.judge(p, 0.6), 'FAIL')
        self.assertEqual(M.judge(p, -0.49), 'PASS')
        p = next(p for p in M.POINTS if p['kind'] == 'REFFREQ')
        self.assertEqual((M.judge(p, 2.01), M.judge(p, -1.9)), ('FAIL', 'PASS'))


# ======================================================================================================================================================
# the review window rows (report_review_adapters: the MDO adapter, found through the engine's CAL_MODEL)
# ======================================================================================================================================================
class ReviewRows(unittest.TestCase):
    def tearDown(self):
        M.configure('MDO4000C')

    def test_one_spec_per_row_default_equals_printed_and_standards(self):
        import report_review_model as RM
        M.configure('MDO3')
        with mock.patch('time.sleep', lambda s: None):
            res, io = run_all_points('34-1000', 'SA3', True, True, False)
        io.close()
        M.SLEEP_SCALE = 1.0
        by = {p['id']: p for p in M.POINTS}
        found = {str(pid): dict(reading=v, raw=raw, result=r, synthetic=False, uncertainty=M.uncertainty_text(by[pid], raw), timestamp='2026-10-25T10:00:00',
                                data='As Found') for pid, (v, raw, r) in res.items()}

        class Var:
            def __init__(s, v=''): s.v = v
            def get(s): return s.v
            def set(s, v): s.v = v

        app = M.App.__new__(M.App)
        app.cfg = M.Config('34-1000', 'SA3', True, True, False)
        app._found, app._left = found, {}
        app.asset, app.serial, app.status, app.root = Var('A-300'), Var('S1'), Var(), object()
        app.any_synthetic = lambda: False
        pairs = app.certificate_pairs()
        self.assertEqual(len(pairs), len(res))
        specs, default = RM.specs_for(app)
        self.assertEqual(len(specs), len(pairs))
        for s, (_p, row) in zip(specs, pairs):
            e = RM.evaluate(s, s.default_std)
            want = row.get('Uncertainty', '')
            self.assertEqual(e.unc_text, '' if want == 'N/A' else want, s.description)
        kinds = {p['id']: p['kind'] for p, _r in pairs}
        dc = [s for s, (p, _r) in zip(specs, pairs) if p['kind'] in ('GAIN', 'OFFSET', 'DVMDC')]
        self.assertTrue(dc and all(s.default_std == '5560A' and '5522A' in s.options for s in dc))
        import uncertainty_budget
        rf = [(s, p) for s, (p, _r) in zip(specs, pairs) if p['kind'] == 'ABSAMP']
        covered = [s for s, p in rf if uncertainty_budget.rf_level_sweep(p) is not None]
        self.assertEqual(len(covered), 12)                         # 50 kHz - 90 MHz at each level: the 96270A sheet; 100 MHz - 3 GHz: no sheet row, N/A as on the MDO4000C
        self.assertTrue(all(s.default_std == '96270A' for s in covered))
        self.assertTrue(all(s.default_std != '96270A' for s, p in rf if uncertainty_budget.rf_level_sweep(p) is None))
        self.assertTrue(kinds)


# ======================================================================================================================================================
# a whole virtual (demo) run in the Tk-stub harness, and the report
# ======================================================================================================================================================
class VirtualRun(unittest.TestCase):
    def setUp(self):
        import virtual_harness as VH
        M.configure('MDO3')
        self.hn = VH.VHarness().start()

    def tearDown(self):
        self.hn.stop()
        M.configure('MDO4000C')

    def test_demo_run_records_every_point_marks_it_synthetic_and_the_pdf_is_demo(self):
        from tkinter import simpledialog
        import ui_port
        app = M.App(self.hn.root, demo=True)
        self.assertTrue(app.virtual)
        app.v_model.set('32-200'); app.v_sa.set('None'); app.v_afg.set(True); app.v_dvm.set(True); app.v_tpa.set(False)
        app.on_config(save=False)
        app.asset.set('A-77'); app.serial.set('S-77')
        self.hn.app = app
        with mock.patch.object(simpledialog, 'askstring', lambda *a, **k: k.get('initialvalue'), create=True):
            app.run_all()
            self.assertTrue(self.hn.pump_poll(600))
        self.assertFalse(self.hn.boxes('showerror'), self.hn.boxes('showerror'))
        want = sum(applies(p, '32-200', 'None', True, True, False) for p in POINTS)
        self.assertEqual(len(app.results), want)
        self.assertFalse([k for k, r in app.results.items() if r.get('result') != 'PASS'])
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))
        self.assertTrue(app.any_synthetic())
        import virtualbench
        self.assertTrue(virtualbench.log_is_virtual(app.io.log) if app.io else True)
        # the report: 'Calibration Data', named asset#-date, DEMO on the page
        try:
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest('reportlab not installed')
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        import ui_theme_core
        name = ui_theme_core.report_filename('A-77')
        self.assertTrue(name.startswith('A-77-') and name.endswith('.pdf'), name)
        out = d / name
        port = ui_port.get_ui()
        with mock.patch.object(port, 'report_details', lambda *a, **k: dict(technician='T', temperature='23', humidity='45', standards=[]), create=True), \
                mock.patch.object(port, 'save_file', lambda *a, **k: str(out), create=True):
            app.export_pdf()
        self.assertTrue(out.is_file(), app.status.get())
        if shutil.which('pdftotext'):
            text = subprocess.run(['pdftotext', '-layout', str(out), '-'], capture_output=True, text=True, timeout=60).stdout
            self.assertIn('Calibration Data', text)
            self.assertIn('DEMO', text)
            self.assertIn('Tektronix MDO32 200 MHz', text)
            self.assertIn('RESULT: PASS', text)


# ======================================================================================================================================================
# the Qt window (offscreen)
# ======================================================================================================================================================
try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QtWindow(unittest.TestCase):
    def setUp(self):
        import qt_genscope_harness as Q
        self.Q = Q
        M.configure('MDO3')
        self.hn = Q.QtHarness().start()
        self.addCleanup(self.hn.stop)
        self.addCleanup(M.configure, 'MDO4000C')

    def test_window_texts_and_a_virtual_run(self):
        from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel
        app = M.App(self.hn.root, demo=True)
        self.hn.app = app
        app.asset.set('A-1'); app.serial.set('S-1')
        self.Q.settle(6)
        win = self.hn.root
        self.assertTrue(win.windowTitle().startswith('Tektronix 3 Series MDO | Performance Verification'))
        combos = [[c.itemText(i) for i in range(c.count())] for c in win.findChildren(QComboBox)]
        self.assertIn(['MDO' + m for m in MODELS], combos)
        self.assertIn(['None', 'SA3'], combos)
        texts = {w.text() for w in win.findChildren(QLabel) + win.findChildren(QAbstractButton)}
        for t in ('AFG (3-AFG)', 'DVM (3-DVM)', 'TPA-N-PRE attached', '3 Series MDO (USB)', 'Fluke 5560A', 'Fluke 96270A (RF)', 'Read options from scope'):
            self.assertIn(t, texts)
        self.assertEqual(app.v_model.get(), '34-1000')
        row = app.uut_options_row                                     # model and options sit on the main window (as the MDO4000C view), addresses only in the drawer
        self.assertTrue(row.isVisibleTo(win))
        for w in app.cfg_widgets + [app.btn_read_opts]:
            self.assertTrue(row.isAncestorOf(w), w)
            self.assertFalse(app.shell.drawer_body.isAncestorOf(w), w)
        app.run_all()
        self.assertTrue(self.hn.pump(600))
        want = sum(applies(p, '34-1000', 'None', False, False, False) for p in POINTS)
        self.assertEqual(len(app.results), want)
        self.assertFalse([k for k, r in app.results.items() if r.get('result') != 'PASS'])


class Goldens(unittest.TestCase):
    def test_the_mdo3_fixtures_exist_and_are_separate_from_the_mdo4000c_ones(self):
        eng = json.loads((ROOT / 'tests' / 'golden' / 'engine_mdo3.json').read_text(encoding='utf-8'))
        drv = json.loads((ROOT / 'tests' / 'golden' / 'tektronix_mdo3.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(eng['entries']), 20)
        self.assertTrue(all(e['method'].startswith('TektronixMDO3.') for e in drv['entries']))
        mdo = json.loads((ROOT / 'tests' / 'golden' / 'engine_mdo4000c.json').read_text(encoding='utf-8'))
        self.assertFalse([e for e in mdo['entries'] if 'MDO3' in json.dumps(e)])


if __name__ == '__main__':
    unittest.main()
