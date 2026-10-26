"""The converter against an EXCERPT of the real Fluke 87 Series V Cal Processor .MDD (tests/fixtures/fluke87v_points_excerpt.MDD: 28 of its 51 test points, the
header replaced; the file as received holds U+FFFD where the micro / degree / plus-minus signs were).  Compared with the existing 87V spec (specs/fluke_87v_pv.json).
Run:  python -m unittest tests.test_mdd_real_excerpt"""
import json
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import mdd_convert as mc  # noqa: E402
import mdd_importer_v49 as imp  # noqa: E402

KEEP = [1, 2, 3, 4, 11, 13, 15, 16, 17, 18, 21, 23, 24, 29, 30, 31, 32, 34, 36, 39, 41, 43, 45, 46, 48, 49, 50, 51]       # row numbers in the full file
FIX = HERE / 'fixtures' / 'fluke87v_points_excerpt.MDD'


class Excerpt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = imp.parse_mdd(FIX)
        cls.conv = mc.convert(cls.parsed)
        cls.pts = {str(KEEP[int(p.id.rsplit('.p', 1)[1]) - 1]): (fn, p) for fn, p in cls.conv.sheet.all_points()}      # key = row number in the full file

    def test_every_point_converts(self):
        self.assertEqual((self.conv.total, self.conv.converted, self.conv.skipped), (28, 28, 0))

    def test_continuation_rows_share_the_section(self):
        names = [fn.name for fn in self.conv.sheet.functions]
        self.assertEqual(names.count('AC Volts Accuracy'), 1)           # '|' and bare '6V Range' rows continue it
        self.assertIn('DC Voltage Accuracy', names)
        self.assertIn('Resistance', names)

    def test_lost_micro_and_degree_signs_are_restored_and_flagged(self):
        by_tp = {r['tp_id']: r for r in self.conv.rows}
        micro = [r for r in self.conv.rows if 'lost micro' in r['message']]
        self.assertTrue(micro)
        for r in micro:
            self.assertEqual(r['status'], 'uncertain', r)
        units = {r['tp_id']: r['unit'] for r in micro}
        self.assertTrue(all(u in ('µA', 'µF', '°F') for u in units.values()), units)
        self.assertIn('°F', units.values())          # Temperature: Type K
        self.assertIn('µF', units.values())          # 100µF Range
        self.assertIn('µA', units.values())
        p = next(p for k, (f, p) in self.pts.items() if f.kind == 'TEMPF')
        self.assertEqual(p.overrides['365d'], {'low': '30.2', 'high': '33.8'})      # limits exactly as printed (degF)

    def test_limits_nominals_and_frequencies_as_printed(self):
        spec = {s['step']: s for s in json.loads((ROOT / 'specs' / 'fluke_87v_pv.json').read_text(encoding='utf-8'))['steps']}
        checked = 0
        for tp, (fn, p) in self.pts.items():
            s = spec[int(tp)] if int(tp) in spec else None
            if s is None or s['kind'] in ('SQUARE', 'TEMP', 'NONE', 'DUTY'):
                continue
            fac = D(str(s['factor']))
            ov = p.overrides.get('365d')
            if ov:
                self.assertEqual((D(ov['low']), D(ov['high'])), (D(str(s['low'])) * fac, D(str(s['high'])) * fac), tp)
                checked += 1
            if fn.kind in ('ACV', 'ACI') and s['applied'].get('frequency') is not None:
                self.assertEqual(p.frequency, D(str(s['applied']['frequency'])), tp)
        self.assertGreater(checked, 15)

    def test_display_unit_is_the_printed_unit_not_a_guess_from_the_largest_value(self):
        """Found on the real file: a base-unit range holding 1014 V was shown in kV (3.3 V as 0.0033 kV)."""
        import datasheet_builder_specs as dsp
        steps = dsp.export_spec(self.conv.sheet).spec['steps']
        pairs = [(r['unit'], st['display_unit']) for r, st in zip([r for r in self.conv.rows if r['status'] != 'skipped'], steps) if st['test'] == 'numeric']
        self.assertTrue(pairs)
        for printed, shown in pairs:
            self.assertEqual(printed.replace('\u03a9', '\u03a9'), shown.replace('ohm', '\u03a9'), (printed, shown))
        volts = [st for st in steps if st['display_unit'] == 'V' and st['test'] == 'numeric']
        self.assertTrue(volts and all(float(st['high']) < 1100 for st in volts))

    def test_pass_fail_rows(self):
        cap = next((f, p) for k, (f, p) in self.pts.items() if p.label.startswith('0.21 to 31 nF'))
        self.assertEqual(cap[0].kind, 'CAP')
        self.assertEqual(cap[1].overrides['365d'], {'low': '0.00000000021', 'high': '0.000000031'})
        low = [p for k, (f, p) in self.pts.items() if p.label.startswith('372 to 408 V')]
        self.assertTrue(low)
        self.assertEqual(self.conv.rows[[r['tp_id'] for r in self.conv.rows].index(low[0].origin.partition(':')[2])]['status'], 'uncertain')

    def test_peak_min_max_follows_the_section_above_and_is_flagged(self):
        r = next(r for r in self.conv.rows if r['nominal'].startswith('-2.000'))
        self.assertEqual(r['kind'], 'DCV')

    def test_nothing_in_the_excerpt_is_a_secret(self):
        text = FIX.read_text(encoding='utf-8')
        for word in ('Myers', 'Miles', 'MTYLER', 'COM9', 'Author', '{'):
            self.assertNotIn(word, text)


class ExcerptStandard(unittest.TestCase):
    """The real 87V excerpt with a standard chosen for the uncertainty: the figures are the standard's own, the rest is waived point by point."""

    @classmethod
    def setUpClass(cls):
        cls.parsed = imp.parse_mdd(FIX)
        cls.conv = mc.convert(cls.parsed)

    def register(self, standard):
        import tempfile
        d = Path(tempfile.mkdtemp())
        res = mc.register(self.conv, self.parsed, 'tester', registry=d / 'reg.sqlite3', root=d / 'us', archive_to=d / 'arch', standard=standard)
        self.assertTrue(res.ok, res.message)
        import datasheet_builder as db
        return db.load(res.uid, root=d / 'us', db=d / 'reg.sqlite3'), res

    def test_the_preview_preselects_a_handheld_calibrator_and_counts_what_it_covers(self):
        ch = mc.StandardChoice(self.conv.sheet)
        self.assertEqual(ch.default, '5522A')
        plan, rows, text = ch.preview('5522A')
        c = plan.counts()
        self.assertEqual(c['points'], 28)
        self.assertEqual((c['sourced'], c['waived'], c['by_design']), (18, 4, 6))            # 3 frequency rows + 1 AC current row with no frequency are waived; diode / cond / degF ... carry none by design
        self.assertEqual(sum(1 for v in rows.values() if v.endswith('(5522A)')), 18)
        self.assertIn('18 point(s) will show the uncertainty of the 5522A', text)

    def test_registered_with_the_5522a_every_covered_point_carries_its_figure_and_the_rest_a_waiver(self):
        import datasheet_builder_rules as rules
        ds, res = self.register('5522A')
        self.assertEqual(res.status, 'ready')
        named = {pid: s for pid, s in ds.assignments.items() if s != 'MANUAL'}
        self.assertEqual(len(named), 18)
        self.assertEqual(set(named.values()), {'5522A'})
        w = rules.waivers(ds)
        self.assertEqual(len(w), 4)
        self.assertNotIn(rules.WHOLE_SHEET, w)
        chk = rules.check(ds, dry_run_on=False)
        self.assertEqual(chk.errors(), [])
        self.assertEqual(sum(1 for s in chk.sources.values() if s.has_source and s.standard == '5522A'), 18)
        self.assertEqual(sum(1 for s in chk.sources.values() if s.waived), 4)
        for pid in named:                                                       # a point's figure is the standard's own spec row: positive, never zero
            self.assertIn('5522A standards sheet', chk.sources[pid].text)

    def test_limits_nominals_and_kinds_are_the_same_with_or_without_a_standard(self):
        a, _ = self.register('5522A')
        b, _ = self.register('')
        key = lambda ds: [(fn.kind, p.nominal, p.frequency, p.overrides) for fn, p in ds.all_points()]      # noqa: E731
        self.assertEqual(key(a), key(b))
        self.assertEqual(key(a), key(self.conv.sheet))


if __name__ == '__main__':
    unittest.main()
