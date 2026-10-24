"""Frequency / time base points of the scope and generator engines use the lab's 'Frequency - Measure' CMC (branch uncertainty-engines, frequency work).  Run:
    python -m unittest tests.test_freq_cmc_scope_gen

Owner: all frequency interfaces are tied to the GPS-referenced lab standard, so the A2LA 'Frequency - Measure' line (7.1e-12 of the frequency, 10 Hz to
26.5 GHz) is the uncertainty of every frequency / time base point whose instrument takes the external 10 MHz reference.  The CMC is already the
expanded figure (k = 2): no calibrator-sheet divisor is applied and nothing is added to it.  Hand-worked values: 7.1e-12 x f, rounded UP to 2 s.f."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
_spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
_stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stub)
_stub.install()

import uncertainty  # noqa: E402

SC = uncertainty.load()


class Mdo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mdo4000c_verification as M
        cls.M = M

    def point(self, pid):
        return next(p for p in self.M.POINTS if p['id'] == pid)

    def test_dvm_frequency_is_the_frequency_measure_cmc(self):
        p = self.point(1284)                                              # DVM frequency, 10 Hz from the 5560A
        self.assertEqual(self.M.uncertainty_text(p, {'reading': 10.0}), '71 pHz')           # 7.1e-11 Hz
        value, unit, style = self.M.uncertainty_parts(p, {'reading': 10.0})
        self.assertAlmostEqual(value, 7.1e-11, 20)
        self.assertEqual((unit, style), ('Hz', 'si'))
        # the whole DVM frequency family: 7.1e-12 x nominal, rounded up, never blank
        for q in (x for x in self.M.POINTS if x['kind'] == 'DVMFREQ'):
            self.assertAlmostEqual(self.M.uncertainty_parts(q, {'reading': q['nominal']})[0], 7.1e-12 * q['nominal'], 20, q['id'])

    def test_afg_frequency_is_the_frequency_measure_cmc_although_it_has_no_stimulus(self):
        p = self.point(1220)                                              # AFG 10 kHz read on the lab counter
        self.assertEqual(p['stim'], 'none')
        self.assertEqual(self.M.uncertainty_text(p, {'reading': 10000.0}), '71 nHz')        # 7.1e-8 Hz
        f = self.M.tar_tur_fields(p, {'raw': {'reading': 10000.0}})
        self.assertEqual((f['TAR'], f['TUR']), ('', '>1000:1'))           # tolerance 1.3 Hz, no calibrator frequency accuracy: TAR blank
        # the AFG amplitude / offset points (no stimulus, other quantities) stay N/A
        for kind in ('AFGAMP', 'AFGOFF'):
            q = next(x for x in self.M.POINTS if x['kind'] == kind)
            self.assertEqual(self.M.uncertainty_text(q, {'reading': q['nominal'] or 1.0}), 'N/A', kind)

    def test_time_quantities_stay_cmc_free(self):
        """REFFREQ (time error in s) and DELTA (time delta in s) are time intervals, not frequencies: unchanged (N/A without a reference-file value)."""
        for kind in ('REFFREQ', 'DELTA'):
            q = next(x for x in self.M.POINTS if x['kind'] == kind)
            self.assertEqual(self.M.uncertainty_text(q, {'reading': 1e-9}), 'N/A', kind)

    def test_a_reference_file_value_is_floored_by_the_cmc(self):
        p = self.point(1284)
        saved = self.M._REF.get('v')
        try:
            self.M._REF['v'] = {'DVMFREQ': {'rel': 0.0, 'abs': 1e-12, 'unit': 'Hz'}}       # below the CMC (7.1e-11)
            parts = self.M.uncertainty_parts(p, {'reading': 10.0})
            self.assertAlmostEqual(parts[0], 7.1e-11, 20)
            self.M._REF['v'] = {'DVMFREQ': {'rel': 0.0, 'abs': 1e-3, 'unit': 'Hz'}}        # above it: the editable value wins
            self.assertAlmostEqual(self.M.uncertainty_parts(p, {'reading': 10.0})[0], 1e-3, 15)
        finally:
            self.M._REF['v'] = saved if saved is not None else {}


class WaveSurfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import WaveSurfer_WS4104HD as W
        cls.W = W
        cls.app = W.RMSNoiseApp.__new__(W.RMSNoiseApp)

    def test_timebase_is_the_frequency_measure_cmc(self):
        a = self.app
        r = dict(nominal_hz=1e5, lower_hz=-0.35, upper_hz=0.35)            # the 10 us marker
        value, unit = a.scope_uncertainty_value('timebase', r)
        self.assertAlmostEqual(value, 7.1e-7, 15)
        self.assertEqual(unit, 'Hz')
        self.assertEqual(a.scope_uncertainty('timebase', r), '710 nHz')
        f = a.tar_tur_fields('timebase', r)
        self.assertEqual((f['TAR'], f['TUR']), ('', '>1000:1'))            # +-0.35 Hz over 7.1e-7 Hz; no calibrator frequency accuracy: TAR blank
        # another marker period: linear in the frequency
        self.assertEqual(a.scope_uncertainty('timebase', dict(r, nominal_hz=1e6)), '7.1 µHz')

    def test_a_bad_row_gives_nothing(self):
        self.assertIsNone(self.app.scope_uncertainty_value('timebase', {}))


class Fgen(unittest.TestCase):
    """The generators already printed the Frequency - Measure CMC for their time base: pinned here."""
    @classmethod
    def setUpClass(cls):
        import fgen_verification as F
        F.configure('33220A')
        cls.F = F

    def test_timebase_is_the_frequency_measure_cmc_and_not_the_5790b(self):
        tb = next(p for p in self.F.POINTS if p['kind'] == 'TIMEBASE')
        value, unit, source = self.F.uncertainty_value(tb)
        self.assertEqual((unit, source), ('Hz', 'scope'))
        self.assertAlmostEqual(value, 7.1e-12 * tb['nominal'], 20)
        self.assertIsNone(self.F.measure_budget(tb))


if __name__ == '__main__':
    unittest.main()
