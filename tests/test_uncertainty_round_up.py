"""A reported uncertainty must never be below the A2LA scope CMC: displayed text is rounded UP, never to nearest."""
import random
import re
import unittest

import uncertainty

try:
    import ui_theme  # noqa: F401  (needs tkinter)
    HAVE_UI = True
except Exception:
    HAVE_UI = False

PREFIX = {'n': 1e-9, 'µ': 1e-6, 'm': 1e-3, 'k': 1e3, 'M': 1e6, 'G': 1e9}


def shown_value(text):
    m = re.match(r'([\d.]+)\s*(\S*)', text.replace('Ohm', 'Ω'))
    sym = m.group(2)
    return float(m.group(1)) * (PREFIX.get(sym[0], 1) if len(sym) > 1 else 1)


class RoundUp(unittest.TestCase):
    def test_round_up_is_never_below(self):
        random.seed(7)
        for _ in range(20000):
            v = 10 ** random.uniform(-12, 6)
            for sig in (2, 3):
                self.assertGreaterEqual(uncertainty.round_up(v, sig), v)
        self.assertEqual(uncertainty.round_up(153.4), 160)
        self.assertEqual(uncertainty.round_up(1.7309e-3), 1.8e-3)
        self.assertEqual(uncertainty.round_up(0), 0.0)

    @unittest.skipUnless(HAVE_UI, 'tkinter not available')
    def test_displayed_cmc_never_below_scope(self):
        scope = uncertainty.load()
        random.seed(3)
        checked = 0
        for kind, unit in (('DCV', 'V'), ('DCI', 'A'), ('OHM', 'ohm'), ('ACV', 'V')):
            for _ in range(2000):
                nominal = 10 ** random.uniform(-3, 2.5)
                freq = random.choice([50, 1e3, 1e4, 1e5]) if kind == 'ACV' else None
                cmc = scope.dmm(kind, nominal, None, freq)
                if cmc is None:
                    continue
                checked += 1
                self.assertGreaterEqual(shown_value(uncertainty.format_value(cmc, unit)), cmc * (1 - 1e-12), (kind, nominal, cmc))
        self.assertGreater(checked, 1000)


class ReferenceFloor(unittest.TestCase):
    """An editable reference value may never be reported below the A2LA scope."""

    def setUp(self):
        import sys
        from unittest import mock
        names = ('tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.filedialog', 'tkinter.font', 'tkinter.scrolledtext')
        self._saved = {n: sys.modules.get(n) for n in names}
        if not HAVE_UI:
            for n in names:
                sys.modules[n] = mock.MagicMock()
        import fgen_verification
        self.fg = fgen_verification
        self._orig = fgen_verification._ref_cmc

    def tearDown(self):
        import sys
        self.fg._ref_cmc = self._orig
        if not HAVE_UI:
            for n, m in self._saved.items():
                sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)

    def test_tiny_reference_value_is_raised_to_scope(self):
        p = {'kind': 'TIMEBASE', 'nominal': 10e6, 'unit': 'Hz'}
        self.fg._ref_cmc = lambda: {'TIMEBASE': {'rel': 0, 'abs': 1e-9, 'unit': 'Hz'}}
        text, _ = self.fg.point_uncertainty(p)
        self.assertEqual(text, '71 µHz')              # scope: 7.1e-12 x 10 MHz

    def test_larger_reference_value_is_kept(self):
        p = {'kind': 'ACAMP', 'nominal': 1.0, 'frequency': 1000.0, 'unit': 'V'}
        self.fg._ref_cmc = lambda: {'ACAMP': {'rel': 0, 'abs': 1.0, 'unit': 'V'}}
        text, _ = self.fg.point_uncertainty(p)
        self.assertEqual(text, '1.0 V')


if __name__ == '__main__':
    unittest.main()
