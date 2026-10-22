"""Rule: a manually typed handheld reading is padded with zeros to the test point's resolution (NOTES.md standing rules)."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tk_stub
_tk_stub.install()
import handheld_dmm as h  # noqa: E402


class PadReading(unittest.TestCase):
    P = {'low': '4.990', 'high': '5.010'}

    def test_examples(self):
        for typed, want in [('5', '5.000'), ('5.0', '5.000'), ('5.01', '5.010'), (' 4.99 ', '4.990'), ('-5', '-5.000'),
                            ('5.0123', '5.0123'), ('OL', 'OL')]:
            self.assertEqual(h.pad_reading(self.P, typed), want, typed)

    def test_integer_resolution_untouched(self):
        self.assertEqual(h.pad_reading({'low': '589', 'high': '611'}, '600'), '600')

    def test_judgement_unchanged_on_every_spec_point(self):
        for model in ('113', '117', '87V', '287', '289', 'MM325'):
            try:
                spec = h.load_spec()
                pts = h.points_for(spec, model)
            except Exception:
                continue
            for p in pts:
                if p.get('test') != 'numeric':
                    continue
                typed = str(Decimal(p['low']).normalize()) if 'E' not in str(Decimal(p['low']).normalize()) else p['low']
                self.assertEqual(h.judge_numeric(p, h.pad_reading(p, typed)), h.judge_numeric(p, typed), p['id'])


if __name__ == '__main__':
    unittest.main()
