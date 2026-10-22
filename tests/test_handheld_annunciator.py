"""AUTO-V LoZ: the AC annunciator is a separate yes/no confirmation on the AC point only; the DC point is judged on the reading."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tk_stub
_tk_stub.install()
import handheld_dmm as h  # noqa: E402


class Annunciator(unittest.TestCase):
    def points(self):
        pts = {p['id']: p for p in h.points_for(h.load_spec(), '117')}
        return pts['3-38'], pts['3-39']

    def test_only_the_ac_point_asks(self):
        ac, dc = self.points()
        self.assertTrue(ac.get('annunciator'))
        self.assertFalse(dc.get('annunciator'))

    def test_ac_point_judgement(self):
        ac, _ = self.points()
        self.assertEqual(h.judge_numeric(ac, '0.500', True)[0], 'PASS')
        self.assertEqual(h.judge_numeric(ac, '0.500', False)[0], 'FAIL')
        self.assertEqual(h.judge_numeric(ac, '0.900', True)[0], 'FAIL')

    def test_dc_point_judged_on_reading_alone(self):
        _, dc = self.points()
        self.assertEqual(h.judge_numeric(dc, '0.500', False)[0], 'PASS')
        self.assertEqual(h.judge_numeric(dc, '0.900', False)[0], 'FAIL')

    def test_reading_dialog_has_no_tick_box(self):
        src = Path(h.__file__).read_text(encoding='utf-8')
        self.assertIn("annunciator=False, validate=validate", src)
        self.assertIn("askyesno('AC annunciator'", src)


if __name__ == '__main__':
    unittest.main()
