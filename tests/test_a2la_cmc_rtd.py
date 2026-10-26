"""The RTD lines of the lab CMC table (TEMP entry of specs/a2la_1888_03_cmc.json, added by specs/build_a2la_cmc_rtd.py): every type the scope prints
('Electrical Calibration of RTDs', printed pp. 14-15 of 47) is there with its bands, the edges follow the thermocouple convention, an unknown key / a point outside the
bands returns None, and the thermocouple bands are unchanged.   Run:  python -m unittest tests.test_a2la_cmc_rtd"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_a2la_cmc_rtd as br  # noqa: E402
import uncertainty  # noqa: E402

PATH = os.path.join(HERE, 'specs', 'a2la_1888_03_cmc.json')

# Independent transcription of the printed lines: key -> [(printed range text, CMC)], page.  '(-200 to 0)' = closed lowest band, '(>a to b)' = lower-exclusive.
PRINTED = {
    'Pt385-100': (14, [('-200 to 0', 0.041), ('>0 to 100', 0.052), ('>100 to 300', 0.073), ('>300 to 400', 0.083), ('>400 to 630', 0.095), ('>630 to 800', 0.18)]),
    'Pt3926-100': (14, [('-200 to 0', 0.041), ('>0 to 100', 0.052), ('>100 to 300', 0.073), ('>300 to 400', 0.083), ('>400 to 630', 0.095)]),
    'Pt3916-100': (14, [('-200 to 0', 0.041), ('>0 to 100', 0.052), ('>100 to 300', 0.073), ('>300 to 400', 0.083), ('>400 to 630', 0.095)]),
    'Pt385-200': (14, [('-200 to 0', 0.031), ('>0 to 100', 0.032), ('>100 to 260', 0.043), ('>260 to 300', 0.092), ('>300 to 400', 0.10), ('>400 to 600', 0.11),
                       ('>600 to 630', 0.12)]),
    'Pt385-500': (15, [('-200 to 0', 0.031), ('>0 to 100', 0.032), ('>100 to 260', 0.042), ('>260 to 300', 0.091), ('>300 to 400', 0.10), ('>400 to 600', 0.12),
                       ('>600 to 630', 0.13)]),
    'Pt385-1000': (15, [('-200 to 0', 0.021), ('>0 to 100', 0.033), ('>100 to 260', 0.044), ('>260 to 300', 0.054), ('>300 to 400', 0.055), ('>400 to 600', 0.058),
                        ('>600 to 630', 0.18)]),
    'PtNi385-120': (15, [('-80 to 0', 0.021), ('>0 to 100', 0.031), ('>100 to 260', 0.042)]),          # printed 'Ni 672, 120 ohm'
    'Cu427-10': (15, [('-80 to 260', 0.25)]),
}
TC_KEYS = ['B', 'C', 'D', 'E', 'J', 'K', 'L', 'N', 'R', 'S', 'T', 'U']


def parse(text):
    gt = text.startswith('>')
    lo, hi = text.lstrip('>').split(' to ')
    return float(lo), float(hi), gt


def load():
    with open(PATH, encoding='utf-8') as fh:
        return json.load(fh)


class Transcription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()
        cls.entry = next(e for e in cls.data['entries'] if e['kind'] == 'TEMP')
        cls.scope = uncertainty.load()

    def test_every_printed_type_has_exactly_the_printed_bands(self):
        for key, (page, rows) in PRINTED.items():
            got = self.entry['types'][key]
            self.assertEqual(len(got), len(rows), key)
            for b, (text, cmc) in zip(got, rows):
                lo, hi, gt = parse(text)
                self.assertEqual((b['lo'], b['hi'], b['gt'], b['abs'], b['rel'], b['rng']), (lo, hi, gt, cmc, 0.0, 0.0), (key, text))
            self.assertEqual(br.RTDS[key][0], page, key)
            self.assertEqual([b['gt'] for b in got], [False] + [True] * (len(rows) - 1), key)

    def test_bands_are_contiguous_and_the_same_shape_as_the_thermocouples(self):
        for key in PRINTED:
            got = self.entry['types'][key]
            for a, b in zip(got, got[1:]):
                self.assertEqual(a['hi'], b['lo'], key)
            for b in got:
                self.assertEqual(set(b), {'lo', 'hi', 'rel', 'abs', 'rng', 'gt'})
                self.assertLess(b['lo'], b['hi'])
        self.assertEqual(set(self.entry['types'][TC_KEYS[0]][0]), set(self.entry['types']['Pt385-100'][0]))

    def test_keys(self):
        self.assertEqual(list(self.entry['types']), TC_KEYS + ['Pt385-100', 'Pt385-200', 'Pt385-500', 'Pt385-1000', 'Pt3926-100', 'Pt3916-100', 'Cu427-10', 'PtNi385-120'])
        self.assertEqual(br.RTD_ORDER, ('Pt385-100', 'Pt385-200', 'Pt385-500', 'Pt385-1000', 'Pt3926-100', 'Pt3916-100', 'Pt395-100', 'Cu427-10', 'PtNi385-120'))
        self.assertNotIn('Pt395-100', self.entry['types'])          # the scope does not print Pt 395

    def test_notes_name_the_pages(self):
        self.assertIn('pp. 14-15', self.entry['notes'])
        self.assertIn('rendered page images', self.entry['notes'])

    def test_entry_count_and_kinds_unchanged(self):
        self.assertEqual(len(self.data['entries']), 15)
        self.assertEqual([e['kind'] for e in self.data['entries']].count('TEMP'), 1)


class Lookups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = uncertainty.load()

    def test_each_type_inside_each_band_and_on_each_edge(self):
        for key, (page, rows) in PRINTED.items():
            for text, cmc in rows:
                lo, hi, gt = parse(text)
                mid = (lo + hi) / 2
                self.assertAlmostEqual(self.scope.temperature(mid, key), cmc, 9, (key, text))
                self.assertAlmostEqual(self.scope.dmm('TEMP', mid, tc=key), cmc, 9, (key, text))
                self.assertAlmostEqual(self.scope.temperature(hi, key), cmc, 9, (key, 'upper edge in the band', text))       # upper edge belongs to the band
                if gt:
                    below = [c for t, c in rows if parse(t)[1] == lo][0]
                    self.assertAlmostEqual(self.scope.temperature(lo, key), below, 9, (key, 'lower edge in the band below', text))
                    self.assertAlmostEqual(self.scope.temperature(lo + 1e-6, key), cmc, 9, (key, text))
                else:
                    self.assertAlmostEqual(self.scope.temperature(lo, key), cmc, 9, (key, 'lowest band includes its lower edge'))

    def test_outside_the_printed_range_is_none(self):
        for key, (page, rows) in PRINTED.items():
            lo, hi = parse(rows[0][0])[0], parse(rows[-1][0])[1]
            self.assertIsNone(self.scope.temperature(lo - 0.01, key), key)
            self.assertIsNone(self.scope.temperature(hi + 0.01, key), key)

    def test_unknown_key_is_none_never_a_guess(self):
        for key in ('Pt395-100', 'Pt385-2000', 'pt385-100', 'Pt 385, 100', 'Ni120', 'BP', 'XK', 'Z', 'PT100'):
            self.assertIsNone(self.scope.temperature(100.0, key), key)
            self.assertIsNone(self.scope.dmm('TEMP', 100.0, tc=key), key)
            self.assertEqual(self.scope.dmm_text('TEMP', 100.0, tc=key), '', key)

    def test_spot_values_from_the_page(self):
        s = self.scope
        self.assertAlmostEqual(s.temperature(-200, 'Pt385-100'), 0.041, 9)
        self.assertAlmostEqual(s.temperature(0, 'Pt385-100'), 0.041, 9)               # '(>0 to 100)': 0 belongs to the band below
        self.assertAlmostEqual(s.temperature(0.001, 'Pt385-100'), 0.052, 9)
        self.assertAlmostEqual(s.temperature(630, 'Pt385-100'), 0.095, 9)
        self.assertAlmostEqual(s.temperature(800, 'Pt385-100'), 0.18, 9)
        self.assertIsNone(s.temperature(630.5, 'Pt3926-100'))
        self.assertIsNone(s.temperature(630.5, 'Pt3916-100'))
        self.assertAlmostEqual(s.temperature(100, 'Pt385-200'), 0.032, 9)
        self.assertAlmostEqual(s.temperature(260, 'Pt385-500'), 0.042, 9)
        self.assertAlmostEqual(s.temperature(500, 'Pt385-1000'), 0.058, 9)
        self.assertAlmostEqual(s.temperature(-80, 'PtNi385-120'), 0.021, 9)
        self.assertAlmostEqual(s.temperature(260, 'PtNi385-120'), 0.042, 9)
        self.assertAlmostEqual(s.temperature(-80, 'Cu427-10'), 0.25, 9)
        self.assertAlmostEqual(s.temperature(260, 'Cu427-10'), 0.25, 9)
        self.assertIsNone(s.temperature(261, 'Cu427-10'))

    def test_dmm_text_shows_the_band(self):
        self.assertEqual(self.scope.dmm_text('TEMP', 50.0, tc='Pt385-100'), '0.05 °C')

    def test_thermocouples_unchanged(self):
        s = self.scope
        self.assertAlmostEqual(s.dmm('TEMP', 100.0), 0.10, 9)                         # default Type K, no tc argument
        self.assertAlmostEqual(s.dmm('TEMP', 100.0, tc='K'), 0.10, 9)
        self.assertAlmostEqual(s.dmm('TEMP', 120.0), 0.10, 9)
        self.assertAlmostEqual(s.dmm('TEMP', 120.5), 0.16, 9)
        self.assertAlmostEqual(s.dmm('TEMP', -200.0), 0.22, 9)
        self.assertIsNone(s.dmm('TEMP', 1372.5))
        self.assertAlmostEqual(s.temperature(100.0), 0.10, 9)
        self.assertAlmostEqual(s.temperature(900.0, 'B'), 0.26, 9)
        self.assertAlmostEqual(s.temperature(-249, 'E'), 0.31, 9)
        self.assertAlmostEqual(s.temperature(2000, 'C'), 0.61, 9)
        self.assertAlmostEqual(s.temperature(1767, 'R'), 0.26, 9)
        self.assertAlmostEqual(s.temperature(-1, 'U'), 0.31, 9)
        self.assertAlmostEqual(s.temperature(0, 'N'), 0.10, 9)

    def test_thermocouple_bands_hash_unchanged(self):
        """The thermocouple band lists (all twelve types and the Type K 'bands') are exactly the ones specs/build_a2la_cmc_temperature.py writes."""
        import build_a2la_cmc_temperature as bt
        entry = next(e for e in load()['entries'] if e['kind'] == 'TEMP')
        for t in TC_KEYS:
            self.assertEqual(entry['types'][t], bt.bands(bt.TYPES[t]), t)
        self.assertEqual(entry['bands'], bt.bands(bt.TYPES['K']))


class SensorTypes(unittest.TestCase):
    def test_order_and_labels(self):
        got = uncertainty.sensor_types()
        keys = [k for k, _ in got]
        self.assertEqual(keys, TC_KEYS + ['Pt385-100', 'Pt385-200', 'Pt385-500', 'Pt385-1000', 'Pt3926-100', 'Pt3916-100', 'Cu427-10', 'PtNi385-120'])
        labels = dict(got)
        self.assertEqual(labels['K'], 'Type K')
        self.assertEqual(labels['Pt385-100'], 'Pt 385, 100 Ω')
        self.assertEqual(labels['PtNi385-120'], 'Ni 672, 120 Ω')
        self.assertTrue(all(isinstance(lb, str) and lb for lb in labels.values()))

    def test_every_listed_key_resolves_somewhere(self):
        s = uncertainty.load()
        for key, _ in uncertainty.sensor_types():
            entry = s.entries[('generate', 'TEMP')]['types'][key]
            self.assertIsNotNone(s.temperature(entry[0]['hi'], key), key)

    def test_a_scope_without_rtd_lists_only_what_it_has(self):
        d = load()
        for e in d['entries']:
            if e['kind'] == 'TEMP':
                for k in list(e['types']):
                    if k.startswith(('Pt', 'Cu')):
                        del e['types'][k]
        keys = [k for k, _ in uncertainty.sensor_types(uncertainty.Scope(d))]
        self.assertEqual(keys, TC_KEYS)


class Builder(unittest.TestCase):
    def test_idempotent_and_keeps_the_file_format(self):
        with open(PATH, encoding='utf-8') as fh:
            raw = fh.read()
        self.assertEqual(br.dumps(json.loads(raw)), raw)
        self.assertEqual(br.dumps(br.apply(json.loads(raw))), raw)

    def test_temperature_builder_rerun_keeps_the_rtd_keys_and_the_entry_place(self):
        import shutil
        import tempfile
        from pathlib import Path
        import build_a2la_cmc_temperature as bt
        with open(PATH, encoding='utf-8') as fh:
            raw = fh.read()
        tmp = Path(tempfile.mkdtemp()) / 'cmc.json'
        shutil.copyfile(PATH, tmp)
        old, bt.PATH = bt.PATH, tmp
        try:
            bt.main()
        finally:
            bt.PATH = old
        self.assertEqual(tmp.read_text(encoding='utf-8'), raw)           # same bytes: RTD keys, notes and the entry's place in the file are kept


if __name__ == '__main__':
    unittest.main()
