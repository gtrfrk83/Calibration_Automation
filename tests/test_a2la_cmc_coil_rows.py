"""The coil lines in the lab CMC table (specs/a2la_1888_03_cmc.json, added by specs/build_a2la_cmc_coil_rows.py): every pre-existing row is unchanged, the new rows are the scope's
(printed pp. 9 and 30 of 47), scope-CMC lookups above 30.2 A are covered, and no shipped procedure point changes its CMC.   Run:  python -m unittest tests.test_a2la_cmc_coil_rows"""
import copy
import glob
import hashlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_a2la_cmc_coil_rows as br  # noqa: E402
import uncertainty  # noqa: E402

PATH = os.path.join(HERE, 'specs', 'a2la_1888_03_cmc.json')
# sha256 (first 16 hex) of json.dumps(x, sort_keys=True) of every pre-existing entry (without its notes / standard text) in the file as it was before the coil rows were added
OLD = {('measure', 'DCV'): '2f6ecb7b77ece853', ('measure', 'DCI'): 'f738c298567bc59e', ('measure', 'OHM'): 'e6c8b97bc2650cd5', ('measure', 'CAP'): '0cf69e7b58657bb6',
       ('measure', 'ACI'): '40bcc80fc592d8c7', ('measure', 'ACV'): '56f6a86a4b604645', ('measure', 'FREQ'): 'a2c4d1040a3ebb57', ('generate', 'DCV'): 'a6ebbc5b737c1f7f',
       ('generate', 'OHM'): '76589971ffb968a9', ('generate', 'CAP'): '6195642a21c56354', ('generate', 'ACV'): '8905064f7b96ef9d'}
OLD_DCI_BANDS, OLD_ACI_RANGES = ('e80243af76dd48c5', 15), ('0936d09f317c901f', 16)
OLD_OSC, OLD_TOP = 'e6f95fba3cbdb715', 'e8c2bf5ccaddecc7'


def h(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True).encode()).hexdigest()[:16]


def load():
    with open(PATH, encoding='utf-8') as fh:
        return json.load(fh)


def old_version(data):
    """The table with the coil rows taken out again (the rows that were there before)."""
    d = copy.deepcopy(data)
    dc = next(e for e in d['entries'] if e['basis'] == 'generate' and e['kind'] == 'DCI')
    ac = next(e for e in d['entries'] if e['basis'] == 'generate' and e['kind'] == 'ACI')
    del dc['bands'][OLD_DCI_BANDS[1]:]
    del ac['ranges'][OLD_ACI_RANGES[1]:]
    dc['notes'] = dc['notes'].replace(br.DC_NOTE.strip(), '').strip()
    ac['notes'] = ac['notes'].replace(br.AC_NOTE.strip(), '').strip()
    return d


class Table(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()
        cls.new = uncertainty.Scope(cls.data)
        cls.old = uncertainty.Scope(old_version(cls.data))

    def test_every_existing_row_is_unchanged(self):
        for e in self.data['entries']:
            k = (e['basis'], e['kind'])
            body = {x: y for x, y in e.items() if x not in ('notes', 'standard')}
            if k == ('generate', 'DCI'):
                self.assertEqual(h(e['bands'][:OLD_DCI_BANDS[1]]), OLD_DCI_BANDS[0])
                self.assertEqual(len(e['bands']), OLD_DCI_BANDS[1] + 3)
            elif k == ('generate', 'ACI'):
                self.assertEqual(h(e['ranges'][:OLD_ACI_RANGES[1]]), OLD_ACI_RANGES[0])
                self.assertEqual(len(e['ranges']), OLD_ACI_RANGES[1] + 2)
            elif k == ('generate', 'TEMP'):
                pass                                               # the Type K line, added later (specs/build_a2la_cmc_temperature.py)
            else:
                self.assertEqual(h(body), OLD[k], k)
        self.assertEqual(len(self.data['entries']), 14)
        self.assertEqual(h(self.data['oscilloscope']), OLD_OSC)
        self.assertEqual(h({k: v for k, v in self.data.items() if k not in ('entries', 'oscilloscope', 'source')}), OLD_TOP)

    def test_new_rows_are_the_scope_lines(self):
        dc = next(e for e in self.data['entries'] if e['basis'] == 'generate' and e['kind'] == 'DCI')
        self.assertEqual(dc['bands'][OLD_DCI_BANDS[1]:], [dict(lo=2, hi=20, rel=9e-05, abs=1e-04, rng=0.0), dict(lo=20, hi=120, rel=8e-05, abs=0.008, rng=0.0),
                                                           dict(lo=120, hi=3000, rel=0.008, abs=0.08, rng=0.0)])
        ac = next(e for e in self.data['entries'] if e['basis'] == 'generate' and e['kind'] == 'ACI')
        self.assertEqual(ac['ranges'][OLD_ACI_RANGES[1]:], [
            dict(lo=20.5, hi=1025.0, rows=[dict(f_lo=45.0, f_hi=65.0, rel=0.008, abs=0.0, rng=0.0), dict(f_lo=65.0, f_hi=440.0, rel=0.0099, abs=0.0, rng=0.0)]),
            dict(lo=20.5, hi=3000.0, rows=[dict(f_lo=16.0, f_hi=850.0, rel=0.007, abs=0.84, rng=0.0), dict(f_lo=850.0, f_hi=6000.0, rel=0.008, abs=0.84, rng=0.0)])])

    def test_builder_is_idempotent_and_keeps_the_file_format(self):
        with open(PATH, encoding='utf-8') as fh:
            raw = fh.read()
        self.assertEqual(br.dumps(br.apply(json.loads(raw))), raw)          # applying again changes nothing, byte for byte
        self.assertEqual(br.dumps(json.loads(raw)), raw)
        fresh = br.apply(old_version(json.loads(raw)))
        self.assertEqual(fresh['entries'][8]['bands'][15:], self.data['entries'][8]['bands'][15:])

    def test_lookups_above_30_2_A_are_now_covered(self):
        self.assertIsNone(self.old.dmm('DCI', 100.0))
        self.assertAlmostEqual(self.new.dmm('DCI', 100.0), 80e-6 * 100 + 0.008, 12)
        self.assertAlmostEqual(self.new.dmm('DCI', 3000.0), 0.008 * 3000 + 0.08, 9)
        self.assertIsNone(self.new.dmm('DCI', 3000.1))
        self.assertIsNone(self.old.dmm('ACI', 500.0, None, 50.0))
        self.assertAlmostEqual(self.new.dmm('ACI', 500.0, None, 50.0), 0.007 * 500 + 0.84, 9)   # the larger of the clamp-on 0.8 % (4.0 A) and the amplifier/coil row (4.34 A)
        self.assertAlmostEqual(self.new.dmm('ACI', 500.0, None, 400.0), 0.0099 * 500, 9)       # 0.99 % clamp-on 4.95 A beats 0.7 % + 0.84 A = 4.34 A
        self.assertAlmostEqual(self.new.dmm('ACI', 2000.0, None, 5000.0), 0.008 * 2000 + 0.84, 9)
        self.assertIsNone(self.new.dmm('ACI', 500.0, None, 7000.0))
        self.assertIsNone(self.new.dmm('ACI', 500.0))                                           # no frequency: not covered, as before

    def test_nothing_below_the_coil_ranges_changes_on_a_dense_grid(self):
        freqs = [None, 0, 3, 10, 16, 20, 45, 50, 60, 65, 100, 400, 440, 850, 1000, 3000, 5000, 6000, 10000, 30000]
        n = 0
        for v in [x / 100 for x in range(0, 2050)] + [20.5, 20.4999]:                   # 0 to 20.5 A
            for f in freqs:
                if v >= 20.5:
                    continue
                for kind in ('ACI', 'DCI'):
                    self.assertEqual(self.old.dmm(kind, v, None, f), self.new.dmm(kind, v, None, f), (kind, v, f))
                    n += 1
        for v in [x / 10 for x in range(205, 303)]:                                      # DC 20.5 to 30.2 A: the calibrator CMC stays the larger one
            self.assertEqual(self.old.dmm('DCI', v), self.new.dmm('DCI', v), v)
            self.assertEqual(self.old.dmm('DCI', -v), self.new.dmm('DCI', -v), v)
        for v in (2.0, 2.2, 5.0, 11.0, 12.0, 20.0, 20.5, 25.0, 30.2):
            self.assertGreaterEqual(self.old.dmm('DCI', v), 80e-6 * v + 0.008 if v > 20 else 90e-6 * v + 1e-4)    # the coil DC row never exceeds the calibrator CMC it overlaps
        for other in ('DCV', 'ACV', 'OHM', 'CAP', 'FREQ'):
            for v in (0.001, 1.0, 10.0, 100.0, 1000.0):
                self.assertEqual(self.old.dmm(other, v, v, 1000.0), self.new.dmm(other, v, v, 1000.0))
        self.assertGreater(n, 50000)

    def test_overlap_is_confined_to_ac_20_5_to_120_A(self):
        changed = []
        for v in [20.5, 21.0, 25.0, 30.2, 50.0, 100.0, 120.0, 120.1]:
            for f in (10, 16, 50, 65, 400, 850, 1000, 5000, 6000):
                if self.old.dmm('ACI', v, None, f) != self.new.dmm('ACI', v, None, f):
                    changed.append((v, f))
        self.assertTrue(changed)                                                             # documented consequence: the larger CMC of overlapping sets is used
        self.assertTrue(all(20.5 <= v <= 120.1 for v, _ in changed))
        self.assertEqual(self.old.dmm('ACI', 20.0, None, 50.0), self.new.dmm('ACI', 20.0, None, 50.0))

    def test_no_shipped_procedure_point_changes(self):
        """Every ACI / DCI point of every shipped spec (the applied value, i.e. what the calibrator outputs, and its frequency) has the same CMC before and after."""
        seen = 0
        bad = []

        def walk(o):
            nonlocal seen
            if isinstance(o, dict):
                if str(o.get('kind', '')).upper() in ('ACI', 'DCI'):
                    a = o.get('applied') if isinstance(o.get('applied'), dict) else {}
                    for v in (a.get('value'), o.get('nominal')):
                        try:
                            v = float(v)
                        except (TypeError, ValueError):
                            continue
                        f = a.get('frequency') if a.get('frequency') is not None else o.get('frequency')
                        f = float(f) if isinstance(f, (int, float)) else None
                        rng = o.get('range') if isinstance(o.get('range'), (int, float)) else None
                        seen += 1
                        k = str(o['kind']).upper()
                        if a.get('value') is not None and v != float(a['value']):
                            continue                       # the nominal of a coil point (the meter's reading) is not what the calibrator outputs
                        if self.old.dmm(k, v, rng, f) != self.new.dmm(k, v, rng, f):
                            bad.append((k, v, f))
                for x in o.values():
                    walk(x)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        for f in glob.glob(os.path.join(HERE, 'specs', '*.json')):
            if 'cmc' in f:
                continue
            try:
                with open(f, encoding='utf-8') as fh:
                    walk(json.load(fh))
            except (OSError, ValueError):
                continue
        self.assertGreater(seen, 100)
        self.assertEqual(bad, [])

    def test_fluke_365_current_points_use_the_calibrator_current_unscaled(self):
        """Fluke 365 coil points: the calibrator drives 0.5 / 5 / 9.5 A (x 20 turns = 10 / 100 / 190 A on the meter); the uncertainty is that of the calibrator output, so the
        CMC lookups are at the applied current and are unchanged, and never at the meter's 100 / 190 A."""
        with open(os.path.join(HERE, 'specs', 'fluke_365_pv.json'), encoding='utf-8') as fh:
            spec = json.load(fh)
        pts = []

        def walk(o):
            if isinstance(o, dict):
                if str(o.get('kind', '')).upper() in ('ACI', 'DCI') and isinstance(o.get('applied'), dict):
                    pts.append((o['kind'].upper(), float(o['applied']['value']), o['applied'].get('frequency')))
                for x in o.values():
                    walk(x)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(spec)
        self.assertTrue(pts)
        self.assertLess(max(abs(v) for _k, v, _f in pts), 20.5)                              # 9.5 A at most is applied
        for k, v, f in pts:
            self.assertEqual(self.old.dmm(k, v, None, f), self.new.dmm(k, v, None, f), (k, v, f))
            self.assertIsNotNone(self.new.dmm(k, v, None, f))


if __name__ == '__main__':
    unittest.main()
