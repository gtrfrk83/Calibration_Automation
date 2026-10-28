"""Owner request 2026-10-27: an imported .MDD multimeter sheet can DRIVE the calibrator (the technician types the reading) instead of being a pure manual calibration.
Simulated bench, synthetic .MDD (tests/mdd_synth.py).  Run:  python -m unittest tests.test_mdd_drive_calibrator"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import dsb_run_harness as H  # noqa: E402
import mdd_synth  # noqa: E402
import mdd_importer_v49 as imp  # noqa: E402
import mdd_convert as mc  # noqa: E402
import datasheet_builder as db  # noqa: E402
from test_dsb_runtime_bench import cal_io  # noqa: E402


class Drive(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.path = mdd_synth.write_mdd(self.d / 'Synth 87V.MDD')
        self.parsed = imp.parse_mdd(self.path)
        self.conv = mc.convert(self.parsed)
        self.reg, self.us, self.arch = self.d / 'reg.sqlite3', self.d / 'us', self.d / 'arch'
        self.h = None

    def tearDown(self):
        if self.h is not None:
            self.h.stop()

    def give_ac_points_a_frequency(self):
        for fn, pt in self.conv.sheet.all_points():
            if fn.kind == 'ACV' and not pt.frequency:
                pt.frequency = 1000.0                                           # a driven sheet needs one (a manual calibration does not)

    def register(self, **kw):
        return mc.register(self.conv, self.parsed, 'tester', registry=self.reg, root=self.us, archive_to=self.arch, **kw)

    def test_default_is_still_a_manual_calibration(self):
        r = self.register(standard='5522A')
        self.assertTrue(r.ok, r.message)
        ds = db.load(r.uid, root=self.us, db=self.reg)
        self.assertTrue(ds.options['manual_entry'])
        self.assertNotIn('drive_calibrator', ds.options)
        self.assertEqual(r.kind, 'manual')

    def test_a_driven_import_names_the_point_that_cannot_be_sourced(self):
        r = self.register(standard='5522A', drive_calibrator=True)               # owner 2026-10-28: an AC point with no frequency no longer blocks the sheet; it stays hand-done
        self.assertTrue(r.ok, r.message)
        ds = db.load(r.uid, root=self.us, db=self.reg)
        no_f = [q.id for f, q in ds.all_points() if f.kind == 'ACV' and not q.frequency]
        self.assertTrue(no_f)
        self.assertTrue(all(ds.assignments[i] == 'MANUAL' for i in no_f))        # none of them is sourced at an invented frequency

    def test_drive_is_an_automated_sheet_with_the_standard_as_calibrator(self):
        self.give_ac_points_a_frequency()
        r = self.register(standard='5522A', drive_calibrator=True)
        self.assertTrue(r.ok, r.message)
        self.assertEqual(r.kind, 'verification')
        ds = db.load(r.uid, root=self.us, db=self.reg)
        self.assertFalse(ds.options['manual_entry'])
        self.assertTrue(ds.options['drive_calibrator'])
        self.assertIn('5522A', set(ds.assignments.values()))
        self.assertTrue(set(ds.assignments.values()) <= {'5522A', 'MANUAL'})

    def run_bench(self):
        self.give_ac_points_a_frequency()
        r = self.register(standard='5522A', drive_calibrator=True)
        self.assertTrue(r.ok, r.message)
        spec = json.loads((self.us / (r.uid + '.json')).read_text())
        self.h = H.Harness().start()
        io = cal_io()
        app = self.h.make_app(spec, io=io)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        return app, H.wire(io)

    def test_the_calibrator_is_driven_readings_are_typed_and_it_goes_to_standby(self):
        app, wire = self.run_bench()
        self.assertFalse(app.manual_entry)
        outs = [i for i, (_inst, t) in enumerate(wire) if t.startswith('OUT ') and not t.endswith('?')]
        self.assertTrue(outs)                                                   # the calibrator is programmed
        texts = [t for _inst, t in wire]
        self.assertIn('OPER', texts)
        self.assertEqual(texts[-1][:4] in ('STBY', 'ERR?') or 'STBY' in texts[-6:], True)   # left in standby when the run ends
        self.assertTrue(app.found)                                              # every reading came from the typed value
        rows, _pts = app.certificate_rows_and_points()
        self.assertTrue(any(r['Uncertainty'] for r in rows))
        self.assertTrue(any('[5522A]' in r['Description'] for r in rows))

    def test_an_ac_point_with_no_frequency_stays_hand_done_and_does_not_block_the_driven_sheet(self):
        """Owner 2026-10-28 (Fluke 29 II .MDD): a '0.0 mV' AC zero check has no frequency; it used to make the whole driven import a draft, so nothing was automated."""
        self.give_ac_points_a_frequency()
        fn, pt = next((f, q) for f, q in self.conv.sheet.all_points() if f.kind == 'ACV')
        pt.frequency = None
        r = self.register(standard='5522A', drive_calibrator=True)
        self.assertTrue(r.ok, r.message)
        ds = db.load(r.uid, root=self.us, db=self.reg)
        self.assertEqual(ds.assignments[pt.id], 'MANUAL')
        self.assertIn('5522A', set(ds.assignments.values()))                    # the rest is still driven
        self.assertFalse(ds.options['manual_entry'])

    def test_a_manual_import_is_unchanged_by_the_hand_done_rule(self):
        fn, pt = next((f, q) for f, q in self.conv.sheet.all_points() if f.kind == 'ACV')
        pt.frequency = None
        r = self.register(standard='5522A')
        self.assertTrue(r.ok, r.message)


if __name__ == '__main__':
    unittest.main()
