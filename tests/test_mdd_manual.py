"""Mudcats .MDD import -> Datasheet Builder sheet -> registered MANUAL procedure -> typed readings in the run window (simulated bench, no instruments)
-> Calibration Data PDF.  The .MDD is SYNTHETIC (tests/mdd_synth.py); the real Fluke 87V file's quirks are unverified.
Run:  python -m unittest tests.test_mdd_manual"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import dsb_run_harness as H  # noqa: E402
import mdd_synth  # noqa: E402
import mdd_importer_v49 as imp  # noqa: E402
import mdd_convert as mc  # noqa: E402
import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import dsb_manager  # noqa: E402
import procscan  # noqa: E402
import report_dialog  # noqa: E402
import dsb_runtime as rt  # noqa: E402


class Fix(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.path = mdd_synth.write_mdd(self.d / 'Synth 87V.MDD')
        self.parsed = imp.parse_mdd(self.path)
        self.conv = mc.convert(self.parsed)
        self.reg, self.us, self.arch = self.d / 'reg.sqlite3', self.d / 'us', self.d / 'arch'

    def register(self, **kw):
        return mc.register(self.conv, self.parsed, 'tester', registry=self.reg, root=self.us, archive_to=self.arch, **kw)


class Convert(Fix):
    def test_counts_and_unconvertible_points_are_listed(self):
        c = self.conv
        self.assertEqual((c.total, c.converted, c.skipped), (17, 14, 3))
        skipped = {r['no']: r['message'] for r in c.rows if r['status'] == 'skipped'}
        self.assertEqual(set(skipped), {15, 16, 17})
        self.assertIn('furlong', skipped[15])
        self.assertIn('above', skipped[16])
        self.assertIn('not numbers', skipped[17])
        self.assertEqual(sorted(i.point for i in c.issues if i.level == 'error'), [15, 16, 17])

    def test_uncertain_points_are_flagged_not_hidden(self):
        codes = {(i.point, i.code) for i in self.conv.issues if i.level == 'warn'}
        self.assertIn((6, 'kind_guessed'), codes)          # neither AC nor DC named
        self.assertIn((9, 'nominal_midpoint'), codes)      # a range printed as the nominal
        self.assertEqual(self.conv.uncertain, 2)

    def test_kinds_units_frequency_and_limits_as_printed(self):
        pts = {int(p.id.rsplit('.p', 1)[1]): (fn, p) for fn, p in self.conv.sheet.all_points()}
        self.assertEqual([pts[n][0].kind for n in (1, 4, 6, 7, 9, 10, 11, 12, 13, 14)],
                         ['DCV', 'ACV', 'DCV', 'OHM2', 'CAP', 'CHECK', 'FREQ', 'TEMPF', 'PCT', 'COND'])
        fn, p = pts[4]
        self.assertEqual(str(p.frequency), '60')
        fn, p = pts[11]
        self.assertEqual(db.fmt(p.amplitude), '0.6')                              # '@ 600 mV' is the input level of a frequency reading
        fn, p = pts[7]
        self.assertEqual(p.overrides['365d'], {'low': '997', 'high': '1003'})     # 0.997 kOhm as printed, exact SI
        self.assertEqual(db.fmt(p.nominal), '1000')
        self.assertEqual(p.settings['decimals'], 3)
        fn, p = pts[1]
        self.assertEqual(p.overrides['365d'], {'low': '0.099', 'high': '0.101'})  # tolerance unit mV
        self.assertEqual(self.conv.sheet.periods[0].label, '365 Days')

    def test_sheet_validates_and_every_point_is_manual(self):
        self.assertEqual(db.errors(db.validate(self.conv.sheet)), [])
        self.assertTrue(self.conv.sheet.options['manual_entry'])
        res = dm.match_datasheet(self.conv.sheet)
        self.assertFalse(any(a.can_automate for a in res.assignments.values()))
        self.assertTrue(all(v == 'MANUAL' for v in self.conv.sheet.assignments.values()))

    def test_readings_already_in_the_mdd_are_not_imported(self):
        p = mdd_synth.write_mdd(self.d / 'withreadings.MDD', with_readings=True)
        c = mc.convert(imp.parse_mdd(p))
        self.assertTrue(any(i.code == 'readings_present' for i in c.issues))
        self.assertNotIn('1.0001', c.sheet.to_json())

    def test_no_point_converted_raises(self):
        p = mdd_synth.write_mdd(self.d / 'bad.MDD', rows=[('X', '1 V', '[x] furlong', '', '1', '2')])
        with self.assertRaises(ValueError):
            mc.convert(imp.parse_mdd(p))

    def test_text_fields_are_cleaned(self):
        self.assertEqual(mc.clean('a\x00b\x07\tc  d'), 'a b c d')
        self.assertEqual(len(mc.clean('x' * 5000)), mc.MAX_TEXT)

    def test_too_many_points_refused(self):
        with self.assertRaises(ValueError):
            mc.convert({'header': {}, 'points': [{}] * (mc.MAX_POINTS + 1), 'sha256': ''})


class Safety(Fix):
    def test_embedded_script_is_never_executed(self):
        marker = Path('/tmp/mdd_executed_marker')
        marker.unlink(missing_ok=True)
        mc.convert(imp.parse_mdd(self.path))
        self.register()
        self.assertFalse(marker.exists())
        self.assertNotIn('os.system', json.dumps(self.conv.sheet.to_dict()))

    def test_size_and_table_checks_unchanged(self):
        big = self.d / 'big.MDD'
        with open(big, 'wb') as f:
            f.truncate(imp.MAX_FILE_SIZE + 1)
        with self.assertRaises(ValueError):
            imp.parse_mdd(big)
        other = self.d / 'other.MDD'
        other.write_bytes(mdd_synth.mdd_text().replace('Cal Processor', 'Something Else').encode('cp1252'))
        with self.assertRaises(ValueError):
            imp.parse_mdd(other)

    def test_archive_is_immutable_and_named_by_checksum(self):
        a = imp.archive_mdd(self.parsed, self.arch)
        self.assertEqual(a.name, self.parsed['sha256'] + '.MDD')
        self.assertEqual(a.read_bytes(), self.path.read_bytes())
        a.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            imp.archive_mdd(self.parsed, self.arch)


class Register(Fix):
    def test_registered_as_manual_procedure_in_lab_registry_only(self):
        r = self.register()
        self.assertTrue(r.ok, r.message)
        self.assertEqual((r.status, r.kind, r.version), ('ready', 'manual', 1))
        self.assertTrue(Path(r.archive).exists())
        row = next(x for x in db.list_datasheets(root=self.us, db=self.reg) if x['uid'] == r.uid)
        self.assertEqual(row['kind'], 'manual')
        ent = next(e for e in db.procedure_entries(root=self.us, db=self.reg) if e['uid'] == r.uid) if 'uid' in db.procedure_entries(root=self.us, db=self.reg)[0] else None
        if ent:
            self.assertEqual(ent['kind'], 'manual')

    def test_existing_procedure_is_found_and_never_overwritten(self):
        self.assertEqual(mc.find_existing(self.conv, self.reg, self.us), [])
        r1 = self.register()
        ex = mc.find_existing(self.conv, self.reg, self.us)
        self.assertEqual([(e.uid, e.reason) for e in ex], [(r1.uid, 'same_file')])
        r2 = self.register()                                   # a second NEW copy gets its own name
        self.assertNotEqual(r2.uid, r1.uid)
        r3 = self.register(replace_uid=r1.uid)                 # a new VERSION: the old one stays on disk
        self.assertEqual((r3.uid, r3.version), (r1.uid, 2))
        self.assertTrue((self.us / 'versions' / r1.uid / 'v0001.datasheet.json').exists())

    def test_procscan_knows_manual(self):
        self.assertIn('manual', procscan.KINDS)

    def test_dsb_with_automation_stays_automated(self):
        import dsb_fixtures as fx
        ds = fx.dmm_34461a_like()
        self.assertEqual(db.classify_kind(ds), 'verification')
        ds.options['manual_entry'] = True
        self.assertEqual(db.classify_kind(ds), 'manual')


class ManualRun(Fix):
    def setUp(self):
        super().setUp()
        r = self.register()
        self.spec = json.loads((self.us / (r.uid + '.json')).read_text())
        self.h = H.Harness().start()
        self.app = self.h.make_app(self.spec)

    def tearDown(self):
        self.h.stop()

    def pdf_text(self, app, name='A-100-2026-10-23.pdf'):
        out = str(Path(tempfile.mkdtemp()) / name)
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}],
             'procedure': '', 'show_tar_tur': True}
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), \
                mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        return subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout

    def test_window_is_manual_with_the_grid_entry(self):
        a = self.app
        self.assertTrue(a.manual_entry)
        self.assertIsNotNone(a.grid_entry)
        self.assertFalse(a.wants_connection())
        self.assertEqual(len(a.points), 14)

    def test_typed_readings_are_padded_judged_and_rejected_when_not_numbers(self):
        a = self.app
        p = a.points[1]                                        # 1.000 V +/- 0.001 V, 4 decimals printed in the limits
        a.type_reading(p, '1')
        rec = a.results[p['id']]
        self.assertEqual((rec['entered'], rec['result'], rec['source'], rec['synthetic']), ('1.0000', 'PASS', 'typed', False))
        a.type_reading(p, '1.0050')
        self.assertEqual(a.results[p['id']]['result'], 'FAIL')
        for bad in ('nan', 'inf', '-inf', 'abc', '1,5', '', '1 V'):
            with self.assertRaises(ValueError, msg=bad):
                a.type_reading(p, bad)
        self.assertEqual(a.results[p['id']]['entered'], '1.0050')       # a refused entry leaves the stored one alone

    def test_functional_check_takes_yes_no(self):
        a = self.app
        chk = next(p for p in a.points if p['test'] != 'numeric')
        a.type_reading(chk, 'y')
        self.assertEqual(a.results[chk['id']]['result'], 'PASS')
        a.type_reading(chk, 'n')
        self.assertEqual(a.results[chk['id']]['result'], 'FAIL')
        with self.assertRaises(ValueError):
            a.type_reading(chk, '3.2')

    def test_as_left_is_kept_apart(self):
        a = self.app
        p = a.points[2]
        a.type_reading(p, '10.05')
        self.assertEqual(a.found[p['id']]['result'], 'FAIL')
        import datamode
        a.set_data_mode(datamode.LEFT)
        a.type_reading(p, '10.000')
        self.assertEqual(a.left[p['id']]['result'], 'PASS')
        self.assertEqual(a.found[p['id']]['result'], 'FAIL')
        self.assertEqual(a.left[p['id']]['data'], 'As Left')

    def test_run_all_pending_uses_the_same_path(self):
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(self.app.found), 14)

    def test_pdf_is_calibration_data_with_the_typed_readings(self):
        a = self.app
        for p in a.points:
            a.type_reading(p, 'y') if p['test'] != 'numeric' else a.type_reading(p, H.typed_nominal(p))
        txt = self.pdf_text(a)
        self.assertIn('Calibration Data', txt)
        self.assertNotIn('standards due', txt.lower())

    def test_demo_mode_is_marked_everywhere_and_synthetic(self):
        self.h.stop()
        self.h = H.Harness().start()
        a = self.h.make_app(self.spec, demo=True)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertTrue(all(r['synthetic'] for r in a.found.values()))
        self.assertIn('DEMO', self.pdf_text(a).upper())


class OwnerFlag(unittest.TestCase):
    def test_builder_flag_makes_a_sheet_manual_and_back(self):
        import datasheet_builder_ui_model as M
        import dsb_fixtures as fx
        ed = M.EditorModel(M.Storage(root=Path(tempfile.mkdtemp()), db_path=Path(tempfile.mkdtemp()) / 'r.sqlite3'), fx.dmm_34461a_like())
        ed.set_manual_entry(True)
        self.assertEqual(db.classify_kind(ed.ds), 'manual')
        ed.set_manual_entry(False)
        self.assertEqual(db.classify_kind(ed.ds), 'verification')


class GridEntryLogic(unittest.TestCase):
    """manual_grid.GridEntry with a fake tree and app (the real-Tk behaviour is checked in tests/real_tk_checks.py)."""

    def test_module_has_the_keys(self):
        import manual_grid
        src = Path(manual_grid.__file__).read_text()
        for key in ("'<Return>'", "'<Escape>'", "'<Tab>'", "'<F9>'"):
            self.assertIn(key, src)


if __name__ == '__main__':
    unittest.main()
