"""The Minolta T-10A standards sheet (white light fc / lux, flat 5 % black light)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'specs'))
import specmanager as sm  # noqa: E402
import build_minolta_t10a_standard as bm  # noqa: E402

SHEET = ROOT / 'specs' / 'standards' / 'minolta_t10a_standard.json'


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(SHEET.read_text(encoding='utf-8'))
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)

    def test_builder_reproduces_the_shipped_sheet(self):
        fresh = bm.build()
        for d in (fresh, self.data):
            d['standard'].pop('built')
        self.assertEqual(fresh, self.data)

    def test_ranges_as_read_from_the_tree(self):
        rows = {f['name']: [(r['amp_lo'], r['amp_hi'], r['specs'][0]['rel'], r['specs'][0]['abs']) for r in f['ranges']] for f in self.data['functions']}
        self.assertEqual(rows['Light [White] (FC)'], [(0, 2.999, .02, .001), (3, 29.99, .02, .01), (30, 299.9, .02, .1), (300, 2999, .02, 1), (3000, 29990, .02, 10)])
        self.assertEqual(rows['Light [White] (lux)'], [(0, 29.99, .02, .01), (30, 299.9, .02, .1), (300, 2999, .02, 1), (3000, 29990, .02, 10), (30000, 299900, .02, 100)])
        self.assertEqual(rows['Light [Black @ 365 nm] (uW/cm2)'], [(0, 3000, .05, 0)])

    def test_loaded_and_looked_up(self):
        std = sm.standard('T-10A', self.db)
        self.assertEqual(std.model, 'T-10A')
        self.assertEqual(next(x for x in sm.standards(self.db) if x['model'] == 'T-10A')['rows'], 11)
        self.assertNotEqual(sm.standard('A2LA-LIGHT', self.db).model, 'T-10A')            # the lab's CMC sheet is untouched

    def test_black_light_is_flat_five_percent_and_flagged(self):
        self.assertTrue(any('assumed' in p['what'] for p in self.data['problems']))
        self.assertIn('ASSUMED', self.data['notes']['3'])


if __name__ == '__main__':
    unittest.main()
