"""TAR / TUR on the oscilloscope and function generator exports (MDO4000C, function generators, WaveSurfer 4104HD).
Run:  python -m unittest tests.test_tartur_wiring_scopes     (no tkinter needed: tests/_tk_stub.py stands in for it)

Off must leave every PDF byte-for-byte as on origin/tartur-integration (checked by running both trees through
tests/tartur_scopes_harness.py).  On: TUR only where tolerance and the printed uncertainty share a unit; TAR only for a 5560A / 5790B
specification row in the same unit."""
import ast
import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))

spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_stub)
_stub.install()

import tartur  # noqa: E402
import uncertainty  # noqa: E402

BASE_REF = 'origin/tartur-integration'


def git_show(path, ref=BASE_REF):
    r = subprocess.run(['git', 'show', f'{ref}:{path}'], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def pdftext(path):
    return subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout


def func_sources(src, names):
    tree = ast.parse(src)
    return {n.name: ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names}


class TarTurCoreUnchanged(unittest.TestCase):
    # '_compute' is excluded on purpose: it gained the natural-unit guard (NATURAL_UNITS) after the verifier found Hz tolerances divided by volts.
    NAMES = ('compute', 'format_ratio', 'definition_text', 'row_fields', '_blank', '_num', '_scope')

    def test_existing_functions_identical_to_integration(self):
        old = git_show('tartur.py')
        if old is None:
            self.skipTest(f'{BASE_REF} not available')
        new = (ROOT / 'tartur.py').read_text(encoding='utf-8')
        a, b = func_sources(old, self.NAMES), func_sources(new, self.NAMES)
        self.assertEqual(set(a), set(self.NAMES))
        self.assertEqual(a, b)
        self.assertTrue(new.startswith(old.split('\n\n# ----', 1)[0][:200]))           # header untouched

    def test_existing_behaviour_unchanged(self):
        old = git_show('tartur.py')
        if old is None:
            self.skipTest(f'{BASE_REF} not available')
        ns = {}
        exec(compile(old, 'tartur_old', 'exec'), ns)
        pts = [dict(kind='DCV', nominal=10.0, unit='V', range=10.0), dict(kind='ACV', nominal=1.0, unit='V', range=2.2, frequency=1000.0),
               dict(kind='OHM2', nominal=1000.0, unit='ohm', range=1100.0), dict(kind='DCV', nominal=0.0, unit='V', range=1.0, zero_offset=True)]
        for p in pts:
            for lo, hi in ((p['nominal'] - 1e-3, p['nominal'] + 1e-3), (None, 1.0), (1.0, 1.0)):
                for std in (None, '5560A'):
                    self.assertEqual(ns['compute'](p, lo, hi, std), tartur.compute(p, lo, hi, std))
                    self.assertEqual(ns['row_fields'](p, lo, hi, std), tartur.row_fields(p, lo, hi, std))
        for x in (None, 0, -1, 0.05, 4.1999999, 4.2, 999.9, 1001, float('nan'), float('inf')):
            self.assertEqual(ns['format_ratio'](x), tartur.format_ratio(x))
        self.assertEqual(ns['definition_text'](), tartur.definition_text())


class FromValues(unittest.TestCase):
    def test_ratios_round_down(self):
        r = tartur.from_values(0.0047, 'V', 6.76e-6, 'V', 2.4e-3, 'V')
        self.assertAlmostEqual(r['tur'], 0.0047 / 2.4e-3)
        self.assertAlmostEqual(r['tar'], 0.0047 / 6.76e-6)
        f = tartur.ratio_fields(r)
        self.assertEqual(f, dict(TAR='695.2:1', TUR='1.9:1'))                  # 1.9583 rounds DOWN

    def test_different_units_never_converted(self):
        r = tartur.from_values(2.0, '%', 6.76e-6, 'V', 0.82, 'V')
        self.assertIsNone(r['tar'])
        self.assertIsNone(r['tur'])
        self.assertEqual(tartur.ratio_fields(r), dict(TAR='', TUR=''))
        self.assertIsNone(tartur.from_values(1.0, 'ohm', uncertainty=160, uncertainty_unit='Ohm')['tur'])    # unit strings must match exactly

    def test_blank_rules(self):
        for tol in (None, 0, -1, float('nan'), float('inf'), True):
            self.assertEqual(tartur.ratio_fields(tartur.from_values(tol, 'V', 1, 'V', 1, 'V')), dict(TAR='', TUR=''))
        self.assertEqual(tartur.ratio_fields(tartur.from_values(1.0, '', 1, '', 1, '')), dict(TAR='', TUR=''))
        r = tartur.from_values(1.0, 'V', 0, 'V', 0, 'V')
        self.assertIsNone(r['tar']); self.assertIsNone(r['tur'])
        r = tartur.from_values(1.0, 'V', None, None, 0.5, 'V')
        self.assertEqual((r['tar'], r['tur']), (None, 2.0))
        self.assertIn('TAR blank', r['reason'])
        self.assertEqual(set(r), set(tartur.compute(dict(kind='DCV', nominal=1, unit='V', range=1), 0.9, 1.1)))   # same keys as compute

    def test_never_raises(self):
        self.assertEqual(tartur.ratio_fields(tartur.from_values('x', 'V', 'y', 'V', object(), 'V')), dict(TAR='', TUR=''))
        self.assertEqual(tartur.ratio_fields(None), dict(TAR='', TUR=''))

    def test_half_width(self):
        self.assertEqual(tartur.half_width(9, 11), 1.0)
        for lo, hi in ((None, 1), (1, None), (1, 1), (2, 1), (float('nan'), 1)):
            self.assertIsNone(tartur.half_width(lo, hi))

    def test_standard_accuracy(self):
        lim, unit = tartur.standard_accuracy('5560A', 'DCV', 5)
        self.assertEqual(unit, 'V')
        self.assertAlmostEqual(lim, 4.1e-5, 9)                                    # 12 V range, 1 yr
        self.assertEqual(tartur.standard_accuracy('5560A', 'NOSUCHKIND', 5), (None, None))
        self.assertEqual(tartur.standard_accuracy('NOSUCHMODEL', 'DCV', 5), (None, None))
        self.assertEqual(tartur.standard_accuracy('5560A', 'DCV', 1e9), (None, None))      # no row covers it


class Mdo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mdo4000c_verification as M
        cls.M = M

    def point(self, kind, **match):
        return next(p for p in self.M.POINTS if p['kind'] == kind and all(p.get(k) == v for k, v in match.items()))

    def rec(self, p, reading):
        raw = dict(reading=reading)
        return dict(reading=reading, raw=raw, result=self.M.judge(p, reading), uncertainty=self.M.uncertainty_text(p, raw))

    def test_text_identical_to_original(self):
        src = git_show('mdo4000c_verification.py')
        if src is None:
            self.skipTest(f'{BASE_REF} not available')
        fn = func_sources(src, ('uncertainty_text',))['uncertainty_text']
        ns = dict(vars(self.M))
        exec(fn, ns)
        n = 0
        for p in self.M.POINTS:
            for reading in (p['nominal'] or 1.0, 0.5, 0.9, 1.0 + 1e-3):
                raw = dict(reading=reading, gain=reading)
                self.assertEqual(ns['uncertainty_text'](p, raw), self.M.uncertainty_text(p, raw), p)
                n += 1
        self.assertGreater(n, 1000)

    def test_dvmdc_hand_values(self):
        p = self.point('DVMDC', nominal=-5)
        r = self.rec(p, -5.001)
        text = r['uncertainty']
        self.assertRegex(text, r'^\d+(\.\d+)? m?V$')
        parts = self.M.uncertainty_parts(p, r['raw'])
        u = uncertainty.round_up(parts[0])
        f = self.M.tar_tur_fields(p, r)
        self.assertEqual(f['TUR'], tartur.format_ratio(0.125 / u))
        lim, unit = tartur.standard_accuracy('5560A', 'DCV', 5)
        self.assertEqual(f['TAR'], tartur.format_ratio(0.125 / lim))
        self.assertEqual(f['TAR'], '>1000:1')

    def test_offset_tar_tur(self):
        p = self.point('OFFSET', offset=0.9)
        r = self.rec(p, 0.9)
        u = uncertainty.round_up(self.M.uncertainty_parts(p, r['raw'])[0])
        lim, _ = tartur.standard_accuracy('5560A', 'DCV', 0.9)
        tol = (p['high'] - p['low']) / 2
        f = self.M.tar_tur_fields(p, r)
        self.assertEqual(f, dict(TAR=tartur.format_ratio(tol / lim), TUR=tartur.format_ratio(tol / u)))
        self.assertNotEqual(f['TUR'], '')

    def test_imp_and_gain_tur_only(self):
        for kind in ('IMP', 'GAIN'):
            p = self.point(kind)
            f = self.M.tar_tur_fields(p, self.rec(p, p['nominal']))
            self.assertEqual(f['TAR'], '', kind)          # a measurement / a percentage: no matching 5560A specification row in the same unit
            self.assertNotEqual(f['TUR'], '', kind)
        p = self.point('GAIN')
        tol = (p['high'] - p['low']) / 2
        parts = self.M.uncertainty_parts(p, {})
        self.assertEqual(parts[1], '%')
        self.assertEqual(self.M.tar_tur_fields(p, self.rec(p, 0.0))['TUR'], tartur.format_ratio(tol / uncertainty.round_up(parts[0])))

    def test_blank_kinds(self):
        for kind in ('BW', 'NOISE', 'BAL', 'DELTA', 'PHASE', 'DANL', 'XTALK', 'DVMAC', 'DVMFREQ', 'SELFTEST', 'SPC', 'TRIGOUT', 'DIGITAL'):
            p = self.point(kind)
            f = self.M.tar_tur_fields(p, self.rec(p, p['nominal'] or 1.0))
            self.assertEqual(f, dict(TAR='', TUR=''), kind)       # no printed uncertainty (N/A), one-sided limits, or no matching specification

    def test_reference_file_entry_gives_tur_only_in_same_unit(self):
        M = self.M
        p = self.point('DVMAC')
        saved = dict(M._REF.get('v') or {})
        try:
            M._REF['v'] = dict(M.reference_cmc(), DVMAC={'rel': 0.001, 'abs': 1e-5, 'unit': 'V'})
            r = self.rec(p, 0.01)
            tol = (p['high'] - p['low']) / 2
            u = uncertainty.round_up(0.001 * 0.01 + 1e-5)
            f = M.tar_tur_fields(p, r)
            self.assertEqual(f['TUR'], tartur.format_ratio(tol / u))
            self.assertEqual(f['TAR'], '')                          # square-wave stimulus: no matching specification row
            M._REF['v'] = dict(M.reference_cmc(), DVMAC={'rel': 0.001, 'abs': 1e-5, 'unit': 'dB'})
            r = self.rec(p, 0.01)
            self.assertEqual(M.tar_tur_fields(p, r)['TUR'], '')    # unit differs from the tolerance's: never converted
        finally:
            M._REF['v'] = saved

    def test_stored_text_that_differs_gives_blank_tur(self):
        p = self.point('IMP')
        r = self.rec(p, p['nominal'])
        self.assertNotEqual(self.M.tar_tur_fields(p, r)['TUR'], '')
        self.assertEqual(self.M.tar_tur_fields(p, dict(r, uncertainty='999 Ohm'))['TUR'], '')
        self.assertEqual(self.M.tar_tur_fields(p, dict(r, uncertainty='N/A'))['TUR'], '')

    def test_no_csv_export_left(self):
        self.assertFalse(hasattr(self.M.App, 'export_csv'))
        self.assertNotIn('export_csv', (ROOT / 'mdo4000c_verification.py').read_text(encoding='utf-8'))


class Fgen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fgen_verification as F
        F.configure('33220A')
        cls.F = F

    def points(self, kind):
        return [p for p in self.F.POINTS if p['kind'] == kind]

    def test_text_identical_to_original(self):
        src = git_show('fgen_verification.py')
        if src is None:
            self.skipTest(f'{BASE_REF} not available')
        ns = dict(vars(self.F))
        exec(func_sources(src, ('point_uncertainty',))['point_uncertainty'], ns)
        for p in self.F.POINTS:
            self.assertEqual(ns['point_uncertainty'](p), self.F.point_uncertainty(p), p['id'])
        self.assertEqual(len(self.F.POINTS), 54)

    def test_acamp_sine(self):
        p = next(x for x in self.points('ACAMP') if x['function'] == 'SIN')
        text, _ = self.F.point_uncertainty(p)
        value, unit, _src = self.F.uncertainty_value(p)
        self.assertEqual(unit, 'V')
        u = uncertainty.round_up(value)
        lim, lunit = tartur.standard_accuracy('5790B', 'ACV', p['nominal'], frequency=p['frequency'], direction='input')
        self.assertEqual(lunit, 'V')
        f = self.F.tar_tur_fields(p)
        self.assertEqual(f, dict(TAR=tartur.format_ratio(p['error'] / lim), TUR=tartur.format_ratio(p['error'] / u)))
        self.assertNotEqual(f['TAR'], '')

    def test_square_wave_has_no_tar(self):
        sq = [x for x in self.points('ACAMP') if x['function'] != 'SIN']
        self.assertTrue(sq)
        for p in sq:
            f = self.F.tar_tur_fields(p)
            self.assertEqual(f['TAR'], '')
            self.assertNotEqual(f['TUR'], '')

    def test_timebase_tur_only_and_flat_blank(self):
        p = self.points('TIMEBASE')[0]
        value, unit, _ = self.F.uncertainty_value(p)
        self.assertEqual(unit, 'Hz')
        f = self.F.tar_tur_fields(p)
        self.assertEqual(f, dict(TAR='', TUR=tartur.format_ratio(p['error'] / uncertainty.round_up(value))))
        for p in self.points('FLAT') + self.points('SELFTEST'):
            self.assertEqual(self.F.tar_tur_fields(p), dict(TAR='', TUR=''))      # no reference-file value / no spec row in dB

    def test_flat_with_reference_value_gives_tur_in_db(self):
        F = self.F
        orig = F._ref_cmc
        F._ref_cmc = lambda: {'FLAT': {'rel': None, 'abs': 0.02, 'unit': 'dB'}}
        try:
            p = self.points('FLAT')[0]
            f = F.tar_tur_fields(p)
            self.assertEqual(f, dict(TAR='', TUR=tartur.format_ratio(p['error'] / 0.02)))
        finally:
            F._ref_cmc = orig

    def test_no_csv_export_left(self):
        self.assertFalse(hasattr(self.F.App, 'export_csv'))
        self.assertNotIn('export_csv', (ROOT / 'fgen_verification.py').read_text(encoding='utf-8'))


class WaveSurfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import WaveSurfer_WS4104HD as W
        cls.W = W
        cls.app = W.RMSNoiseApp.__new__(W.RMSNoiseApp)

    def test_scope_uncertainty_text_identical_to_original(self):
        src = git_show('Procedures/WaveSurfer_WS4104HD.py')
        if src is None:
            self.skipTest(f'{BASE_REF} not available')
        tree = ast.parse(src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RMSNoiseApp')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'scope_uncertainty')
        ns = dict(vars(self.W))
        exec(ast.get_source_segment(src, fn).replace('\n    ', '\n').lstrip(), ns)
        rows = [('dcv', dict(nominal_v=v)) for v in (0.006, -0.015, 0.3, 1.5, -6.0, 0.0)]
        rows += [('impedance', dict(nominal_ohm=v)) for v in (50., 1e6, 1.2e6)]
        rows += [('offset', dict(nominal_v=v)) for v in (0.0, 0.5, 10.0)]
        rows += [('bandwidth', dict(amplitude_vpp=a, high_hz=f)) for a in (0.016, 0.8) for f in (1e8, 1e9, 5e9)]
        rows += [('trigger', dict(level_v=v)) for v in (0.0, 0.3)] + [('trigger', dict(level_v=0.3, short_v=0.28, past_v=0.32))]
        rows += [('noise', {}), ('timebase', {}), ('dcv', {})]                 # no scope entry / KeyError paths
        for kind, r in rows:
            self.assertEqual(ns['scope_uncertainty'](self.app, kind, r), self.app.scope_uncertainty(kind, r), (kind, r))

    def test_per_kind(self):
        a, W = self.app, self.W
        dcv = dict(nominal_v=0.3, lower_v=0.291, upper_v=0.309)
        f = a.tar_tur_fields('dcv', dcv)
        value, unit = a.scope_uncertainty_value('dcv', dcv)
        lim, _ = tartur.standard_accuracy('5560A', 'DCV', 0.3)
        self.assertEqual(f, dict(TAR=tartur.format_ratio(0.009 / lim), TUR=tartur.format_ratio(0.009 / uncertainty.round_up(value))))
        imp = dict(nominal_ohm=1e6, lower_ohm=980000., upper_ohm=1020000.)
        value, unit = a.scope_uncertainty_value('impedance', imp)
        self.assertEqual(unit, 'ohm')
        self.assertEqual(a.tar_tur_fields('impedance', imp), dict(TAR='', TUR=tartur.format_ratio(20000. / uncertainty.round_up(value))))
        bw = dict(amplitude_vpp=0.8, high_hz=1e9, lower_db=-3.0, upper_db=3.0)
        value, unit = a.scope_uncertainty_value('bandwidth', bw)
        self.assertEqual(unit, 'dB')
        self.assertEqual(a.tar_tur_fields('bandwidth', bw), dict(TAR='', TUR=tartur.format_ratio(3.0 / uncertainty.round_up(value))))
        trig = dict(level_v=0.3, short_v=0.28, past_v=0.32, lower_v=0.28, upper_v=0.32)
        ft = a.tar_tur_fields('trigger', trig)
        lim, _ = tartur.standard_accuracy('5560A', 'DCV', 0.32)
        self.assertEqual(ft['TAR'], tartur.format_ratio(0.02 / lim))
        self.assertNotEqual(ft['TUR'], '')
        off = dict(nominal_v=0.5, lower_v=0.49, upper_v=0.51)
        self.assertNotEqual(a.tar_tur_fields('offset', off)['TAR'], '')

    def test_blank_kinds_and_bad_rows(self):
        a = self.app
        self.assertEqual(a.tar_tur_fields('noise', dict(minimum_db=30)), dict(TAR='', TUR=''))
        self.assertEqual(a.tar_tur_fields('timebase', dict(lower_hz=-1, upper_hz=1, nominal_hz=1e5)), dict(TAR='', TUR=''))
        self.assertEqual(a.tar_tur_fields('dcv', {}), dict(TAR='', TUR=''))
        self.assertEqual(a.tar_tur_fields('nonsense', {}), dict(TAR='', TUR=''))

    def test_every_export_path_goes_through_write_certificate_pdf(self):
        src = (ROOT / 'Procedures' / 'WaveSurfer_WS4104HD.py').read_text(encoding='utf-8')
        self.assertEqual(src.count('write_calibration_pdf('), 1)
        self.assertEqual(src.count('apply_tar_tur('), 1)
        self.assertNotIn('export_csv', src)


@unittest.skipUnless(Path('/usr/bin/pdftotext').exists(), 'pdftotext not available')
class PdfExports(unittest.TestCase):
    """Whole-export runs through tests/tartur_scopes_harness.py (real export_pdf code, stubbed GUI, simulated benches)."""
    PDFS = ('mdo.pdf', 'fgen.pdf', 'ws_all.pdf', 'ws_dcv.pdf', 'ws_impedance.pdf', 'ws_offset.pdf', 'ws_bandwidth.pdf', 'ws_noise.pdf')

    @classmethod
    def setUpClass(cls):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('reportlab not installed')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = None
        base_dir = Path(cls.tmp.name) / 'base'
        base_dir.mkdir()
        r = subprocess.run(f'git archive {BASE_REF} | tar -x -C "{base_dir}"', shell=True, cwd=ROOT, capture_output=True)
        if r.returncode == 0 and (base_dir / 'tartur.py').exists():
            cls.base = base_dir
        cls.out = {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def run_harness(cls, root, name, show):
        key = (str(root), show)
        if key not in cls.out:
            out = Path(cls.tmp.name) / name
            r = subprocess.run([sys.executable, str(ROOT / 'tests' / 'tartur_scopes_harness.py'), str(root), str(out), show, '2'],
                               capture_output=True, text=True, timeout=900)
            assert r.returncode == 0 and 'errors []' in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
            cls.out[key] = out
        return cls.out[key]

    def test_off_is_byte_identical_to_integration(self):
        if self.base is None:
            self.skipTest(f'{BASE_REF} not available')
        a = self.run_harness(self.base, 'base_off', 'off')
        b = self.run_harness(ROOT, 'new_off', 'off')
        for name in self.PDFS:
            self.assertGreater((a / name).stat().st_size, 1000, name)
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)

    def test_on_adds_columns_and_values(self):
        out = self.run_harness(ROOT, 'new_on', 'on')
        for name in self.PDFS:
            text = pdftext(out / name)
            head = next(l for l in text.splitlines() if l.startswith('Description'))
            if name == 'ws_noise.pdf':                      # no printed uncertainty, nothing to show: the report layer drops the empty columns
                self.assertNotIn('TUR', head)
                continue
            self.assertTrue(head.rstrip().endswith('TUR'), name)
            if name in ('ws_impedance.pdf', 'ws_bandwidth.pdf'):
                self.assertNotIn('TAR', head, name)         # a measurement / a leveled sine in dB: no matching specification row
            else:
                self.assertIn('TAR', head, name)
            self.assertRegex(text, r'\d:1', name)
        self.assertIn(':1', pdftext(out / 'ws_dcv.pdf'))

    def test_tar_only_and_tur_only(self):
        tar = pdftext(self.run_harness(ROOT, 'new_tar', 'tar') / 'mdo.pdf')
        tur = pdftext(self.run_harness(ROOT, 'new_tur', 'tur') / 'mdo.pdf')
        head = lambda t: next(l for l in t.splitlines() if l.startswith('Description'))
        self.assertTrue(head(tar).rstrip().endswith('TAR'))
        self.assertTrue(head(tur).rstrip().endswith('TUR'))


if __name__ == '__main__':
    unittest.main()
