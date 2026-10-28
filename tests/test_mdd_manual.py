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
from tests import _tk_stub as _boot  # noqa: E402  (test-only stand-ins for the removed Tk modules)
_boot.install()  # noqa: E402
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
        self.assertEqual((c.total, c.converted, c.skipped), (17, 15, 2))
        skipped = {r['no']: r['message'] for r in c.rows if r['status'] == 'skipped'}
        self.assertEqual(set(skipped), {16, 17})
        self.assertIn('above', skipped[16])
        self.assertIn('not numbers', skipped[17])
        self.assertEqual(sorted(i.point for i in c.issues if i.level == 'error'), [16, 17])

    def test_uncertain_points_are_flagged_not_hidden(self):
        codes = {(i.point, i.code) for i in self.conv.issues if i.level == 'warn'}
        self.assertIn((6, 'kind_inherited'), codes)        # neither AC nor DC named: taken from the section above, flagged
        self.assertIn((9, 'nominal_midpoint'), codes)      # a range printed as the nominal
        self.assertIn((15, 'limit_unit_unknown'), codes)   # unrecognised limit unit: kept as a pass / fail check
        self.assertEqual(self.conv.uncertain, 3)         # 6 (AC/DC inherited), 9 (range as nominal), 15 (unit not recognised)

    def test_at_sign_is_stripped_from_the_label_but_the_condition_is_kept(self):
        pts = {int(p.id.rsplit('.p', 1)[1]): p for fn, p in self.conv.sheet.all_points()}
        self.assertNotIn('@', ''.join(p.label for p in pts.values()))
        self.assertTrue(pts[4].label.startswith('1.000 V 60 Hz'))
        self.assertTrue(pts[11].label.startswith('1.000 kHz 600 mV'))
        self.assertEqual(str(pts[4].frequency), '60')                            # the frequency still comes from the condition

    def test_kinds_units_frequency_and_limits_as_printed(self):
        pts = {int(p.id.rsplit('.p', 1)[1]): (fn, p) for fn, p in self.conv.sheet.all_points()}
        self.assertEqual([pts[n][0].kind for n in (1, 4, 6, 7, 9, 10, 11, 12, 13, 14)],
                         ['DCV', 'ACV', 'ACV', 'OHM2', 'CAP', 'CHECK', 'FREQ', 'TEMPF', 'PCT', 'COND'])
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

    def test_unrecognised_limit_unit_becomes_a_check_with_the_limits_in_the_note(self):
        row = self.conv.rows[14]
        self.assertEqual((row['status'], row['kind']), ('uncertain', 'CHECK'))
        fn, p = next((f, p) for f, p in self.conv.sheet.all_points() if p.id.endswith('.p0015'))
        self.assertEqual(fn.kind, 'CHECK')
        self.assertIn('0.99 to 1.01', p.note)
        self.assertIn('furlong', p.note)

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
        p = mdd_synth.write_mdd(self.d / 'bad.MDD', rows=[('X', '1 V', '[x] V', '', '2', '1')])
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
        self.assertEqual(len(a.points), 15)

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
        self.assertEqual(len(self.app.found), 15)

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
        shown, said = [], []
        with mock.patch.object(rt.port, 'report_details', lambda *x, **k: shown.append(1) or {}), mock.patch.object(rt.port, 'message', lambda *x, **k: said.append(x)):
            a.export_pdf()                                                             # a demo run never exports: the review is shown, then the export is refused
        self.assertEqual((len(shown), len(said)), (1, 1))
        self.assertIn('no PDF is exported', said[0][2])


class OwnerFlag(unittest.TestCase):
    def test_builder_flag_makes_a_sheet_manual_and_back(self):
        import datasheet_builder_ui_model as M
        import dsb_fixtures as fx
        ed = M.EditorModel(M.Storage(root=Path(tempfile.mkdtemp()), db_path=Path(tempfile.mkdtemp()) / 'r.sqlite3'), fx.dmm_34461a_like())
        ed.set_manual_entry(True)
        self.assertEqual(db.classify_kind(ed.ds), 'manual')
        ed.set_manual_entry(False)
        self.assertEqual(db.classify_kind(ed.ds), 'verification')


class ReportTag(ManualRun):
    def test_manual_calibration_rows_have_no_manual_tag(self):
        a = self.app
        for p in a.points:
            a.type_reading(p, 'y') if p['test'] != 'numeric' else a.type_reading(p, H.typed_nominal(p))
        txt = self.pdf_text(a)
        self.assertNotIn('[manual]', txt)
        self.assertNotIn('set up / read by the operator', txt)

    def test_automated_datasheet_keeps_its_manual_tag(self):
        import dsb_fixtures as fx
        import datasheet_builder_specs as dsp
        spec = dsp.export_spec(fx.dmm_34461a_like(), plan=dm.match_datasheet(fx.dmm_34461a_like())).spec
        h = H.Harness().start()
        try:
            a = h.make_app(spec)
            a.cal_mode.set(rt.hh.CAL_CHOICES[2])
            h.default_reading = H.typed_nominal
            self.assertTrue(h.run_all())
            row = a.certificate_row(a.points[0], a.found[a.points[0]['id']])
            self.assertIn('[manual]', row['Description'])         # not a manual calibration: unchanged
        finally:
            h.stop()


class StandardChoicePreview(Fix):
    """The import preview's 'Standard for the uncertainty' (mdd_convert.StandardChoice; the Tk and Qt previews both use it)."""

    def test_the_best_fit_standard_is_preselected_and_none_waive_is_offered_first(self):
        ch = mc.StandardChoice(self.conv.sheet)
        self.assertEqual(ch.labels[0], mc.NONE_LABEL)
        self.assertEqual(ch.models[0], '')
        self.assertEqual(ch.default, '5522A')                         # handheld DMM functions: 5522A / 5520A / 5560A tie on coverage, the 5522A is preferred
        self.assertEqual(ch.models[1:4], ['5522A', '5520A', '5560A'])
        self.assertTrue(ch.labels[1].startswith('5522A  (covers '))
        self.assertEqual(ch.model_of(ch.label_of('5560A')), '5560A')
        self.assertEqual(ch.model_of('nonsense'), '')

    def test_the_preview_shows_the_uncertainty_and_where_it_comes_from(self):
        ch = mc.StandardChoice(self.conv.sheet)
        plan, rows, text = ch.preview('5522A')
        self.assertIn('5522A', text)
        self.assertEqual(plan.counts()['sourced'] + plan.counts()['waived'] + plan.counts()['by_design'], plan.points)
        self.assertTrue(rows[2].endswith('(5522A)'), rows[2])                 # 1.000 V DC: '11 µV (5522A)'
        self.assertEqual(rows[6], 'none: waived')                             # AC point with no frequency: nothing covers it
        self.assertTrue(rows[11].endswith('Hz (5522A)'), rows[11])            # Frequency: the lab's Frequency - Measure CMC, the 5522A covers the frequency
        self.assertEqual(rows[12], 'none by design')                          # degF
        none_plan, none_rows, none_text = ch.preview('')
        self.assertEqual(none_plan.sourced, {})
        self.assertIn('No standard chosen', none_text)
        self.assertNotIn('(5522A)', ' '.join(none_rows.values()))
        self.assertIs(ch.preview('5522A')[0], plan)                           # worked out once

    def test_nothing_is_saved_by_previewing(self):
        before = json.dumps(self.conv.sheet.to_dict(), sort_keys=True)
        mc.StandardChoice(self.conv.sheet).preview('5522A')
        self.assertEqual(json.dumps(self.conv.sheet.to_dict(), sort_keys=True), before)

    def test_qt_preview_preselects_shows_and_registers_the_standard(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest('PySide6 is not installed')
        app = QApplication.instance() or QApplication([])
        from qtui.screens import manager_dialogs as dialogs
        parent = __import__('PySide6.QtWidgets', fromlist=['QWidget']).QWidget()
        pv = dialogs.MddPreview(parent, self.parsed, self.conv, None, None, self.reg, self.us, self.arch)
        self.assertEqual(pv.selected_standard(), '5522A')
        self.assertTrue(pv.std_box.currentText().startswith('5522A'))
        self.assertEqual(pv.std_box.itemText(0), mc.NONE_LABEL)
        unc_col = next(c for c in pv.grid.source_model.columns if c.key == 'unc')
        shown = {r['no']: unc_col.getter(r) for r in pv.grid.rows()}
        self.assertTrue(shown[2].endswith('(5522A)'), shown[2])
        self.assertEqual(shown[16], '')                                       # a point that was not converted shows nothing
        self.assertIn('5522A', pv.std_text.text())
        pv.std_box.setCurrentIndex(0)                                         # None: waive
        self.assertEqual(pv.selected_standard(), '')
        self.assertFalse(any('(5522A)' in unc_col.getter(r) for r in pv.grid.rows()))
        pv.std_box.setCurrentIndex(pv.std.models.index('5560A'))
        self.assertTrue(unc_col.getter(next(r for r in pv.grid.rows() if r['no'] == 2)).endswith('(5560A)'))
        with mock.patch.object(dialogs, 'message') as box:                       # the 'Created ...' box is modal
            pv.create()
        self.assertIn('5560A', box.call_args[0][3])                               # the confirmation says which standard the uncertainties are from
        row = next(x for x in db.list_datasheets(root=self.us, db=self.reg))
        ds = db.load(row['uid'], root=self.us, db=self.reg)
        self.assertEqual(ds.options['manual_standard'], '5560A')
        self.assertEqual(ds.assignments[next(p.id for fn, p in ds.all_points() if p.nominal == 1 and fn.kind == 'DCV')], '5560A')
        pv.dialog.close()


class StandardUncertainty(Fix):
    """A registered manual calibration carries the uncertainty of the standard the author chose; the run window and the PDF print it and say where it is from."""

    def setUp(self):
        super().setUp()
        self.h = None

    def tearDown(self):
        if self.h is not None:
            self.h.stop()

    def app(self, standard, demo=False):
        r = self.register(standard=standard)
        self.assertTrue(r.ok, r.message)
        self.uid = r.uid
        self.spec = json.loads((self.us / (r.uid + '.json')).read_text())
        if self.h is not None:
            self.h.stop()
        self.h = H.Harness().start()
        a = self.h.make_app(self.spec, demo=demo)
        for p in a.points:
            a.type_reading(p, 'y') if p['test'] != 'numeric' else a.type_reading(p, H.typed_nominal(p))
        return a

    def pdf_text(self, app, name='A-100-2026-10-25.pdf', tar_tur=True):
        out = str(Path(tempfile.mkdtemp()) / name)
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [], 'procedure': '', 'show_tar_tur': tar_tur}
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        self.pdf_path = out
        return subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout

    def row_of(self, app, tag):
        p = next(p for p in app.points if p['id'].endswith(tag))
        return app.certificate_row(p, app.found[p['id']])

    def test_registered_sheet_names_the_standard_per_point_and_waives_the_rest_per_point(self):
        import datasheet_builder_rules as rules
        r = self.register(standard='5522A')
        self.assertTrue(r.ok, r.message)
        ds = db.load(r.uid, root=self.us, db=self.reg)
        self.assertEqual(ds.options['manual_standard'], '5522A')
        self.assertTrue(ds.options['manual_entry'])
        by_n = {int(p.id.rsplit('.p', 1)[1]): (fn, p) for fn, p in ds.all_points()}
        self.assertEqual(ds.assignments[by_n[2][1].id], '5522A')
        self.assertEqual(ds.assignments[by_n[11][1].id], '5522A')                 # Frequency: resolved now (the lab's Frequency - Measure CMC)
        w = rules.waivers(ds)
        self.assertNotIn(rules.WHOLE_SHEET, w)
        self.assertNotIn(by_n[11][1].id, w)
        self.assertIn(by_n[6][1].id, w)
        self.assertNotIn(by_n[2][1].id, w)
        self.assertIn('uncertainty waivers', db.versions(r.uid, root=self.us, db=self.reg)[0]['note'])
        eng = json.loads((self.us / (r.uid + '.json')).read_text())['dsb']['engine']['check']
        self.assertEqual((eng['errors'], eng['missing_uncertainties']), (0, 0))

    def test_registered_sheet_with_none_waive_is_waived_per_point(self):
        import datasheet_builder_rules as rules
        r = self.register(standard='')
        ds = db.load(r.uid, root=self.us, db=self.reg)
        self.assertTrue(all(v == 'MANUAL' for v in ds.assignments.values()))
        self.assertEqual(ds.options['manual_standard'], '')
        self.assertNotIn(rules.WHOLE_SHEET, rules.waivers(ds))
        self.assertEqual({k for k in rules.waivers(ds)}, {p.id for fn, p in ds.all_points() if rules.should_have(fn, p)})

    def test_the_report_prints_the_standards_uncertainty_and_says_which_standard(self):
        import report_pdf
        a = self.app('5522A')
        row = self.row_of(a, 'p0001')                                              # 100 mV DC
        self.assertEqual(row['Uncertainty'], report_pdf.point_uncertainty(dict(kind='DCV', nominal=0.1, frequency=None, unit='V', range=None), '5522A'))
        self.assertTrue(row['Uncertainty'].endswith('V') and row['Uncertainty'][0].isdigit())
        self.assertTrue(row['Description'].endswith('[5522A]'), row['Description'])
        self.assertEqual(self.row_of(a, 'p0006')['Uncertainty'], '')                  # the AC point the 5522A does not cover: blank (printed N/A), never zero
        self.assertNotIn('[5522A]', self.row_of(a, 'p0006')['Description'])
        self.assertNotIn('[manual]', self.row_of(a, 'p0001')['Description'])
        txt = self.pdf_text(a)
        self.assertIn('Calibration Data', txt)
        self.assertIn('Uncertainty: 5522A', txt)                                   # the header line names the standard
        self.assertIn('k = 2', txt)
        self.assertIn(row['Uncertainty'].split()[0], txt)
        self.assertIn('N/A', txt)                                                  # waived points print N/A, not 0
        self.assertNotIn('standards due', txt.lower())
        self.assertTrue(Path(self.pdf_path).name.startswith('A-100-2026'))

    def test_no_printed_uncertainty_is_zero_and_the_ratios_follow_the_uncertainty(self):
        a = self.app('5522A')
        rows, pts = a.certificate_rows_and_points()
        printed = [r['Uncertainty'] for r in rows if r['Uncertainty']]
        self.assertTrue(printed)
        for u in printed:
            self.assertGreater(float(u.split()[0]), 0, u)
        p = next(p for p in pts if p['id'].endswith('p0001'))
        f = a.certificate_fields(p)
        self.assertTrue(f['TAR'] and f['TUR'], f)
        self.assertEqual(a.certificate_fields(next(p for p in pts if p['id'].endswith('p0006'))), dict(TAR='', TUR=''))

    def test_none_waive_prints_what_the_report_always_printed(self):
        a = self.app('')
        rows, _pts = a.certificate_rows_and_points()
        self.assertEqual([r['Uncertainty'] for r in rows], [''] * len(rows))
        self.assertFalse(any('[5522A]' in r['Description'] or '[manual]' in r['Description'] for r in rows))
        txt = self.pdf_text(a)
        self.assertNotIn('Uncertainty:', txt)
        self.assertIn('Calibration Data', txt)

    def test_readings_limits_and_pass_fail_do_not_depend_on_the_standard(self):
        a = self.app('5522A')
        found_a = {k: (v['entered'], v['result'], v['reading']) for k, v in a.found.items()}
        lims_a = [(p.get('low'), p.get('high'), p.get('nominal')) for p in a.points]
        b = self.app('')
        self.assertEqual(found_a, {k: (v['entered'], v['result'], v['reading']) for k, v in b.found.items()})
        self.assertEqual(lims_a, [(p.get('low'), p.get('high'), p.get('nominal')) for p in b.points])
        self.assertTrue(all(v['standard'] == 'manual' for v in b.found.values()))        # the record still says the technician did it by hand

    def test_demo_mode_shows_the_uncertainties_for_review_but_never_exports(self):
        a = self.app('5522A', demo=True)
        rows, _pts = a.certificate_rows_and_points()
        self.assertTrue(any(r['Uncertainty'] for r in rows))                           # shown in the review window ...
        self.assertTrue(all(r['synthetic'] for r in a.found.values()))
        self.assertTrue(all('[demo, 5522A]' in r['Description'] for r in rows if r['Uncertainty']))
        out = Path(tempfile.mkdtemp()) / 'x.pdf'
        with mock.patch.object(rt.port, 'report_details', lambda *x, **k: {}), mock.patch.object(rt.port, 'message', lambda *x, **k: None), \
                mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', lambda **k: str(out)):
            a.export_pdf()
        self.assertFalse(out.exists())                                                 # ... and no PDF is ever written
        self.assertEqual(a.manual_uncertainty_line(), '')

    def test_a_loaded_demo_result_is_not_given_a_real_uncertainty_either(self):
        a = self.app('5522A')
        p = a.points[0]
        rec = dict(a.found[p['id']], standard='demo', synthetic=True)
        row = a.certificate_row(p, rec)
        self.assertEqual(row['Uncertainty'], '')
        self.assertIn('[demo]', row['Description'])

    def test_nothing_is_driven_and_routing_is_unchanged_by_the_standard(self):
        a = self.app('5522A')
        self.assertTrue(a.manual_entry)
        self.assertFalse(a.wants_connection())
        self.assertEqual(a.standards_needed(), [])
        self.assertTrue(all(((p.get('dsb') or {}).get('assignment') or {}).get('status') == 'manual' for p in a.points))
        self.assertTrue(all(rt._assigned(p) == '' for p in a.points))

    def test_the_review_window_can_change_the_standard_of_a_manual_row(self):
        import report_review_model as RM
        a = self.app('5522A')
        specs, default = RM.specs_for(a)
        self.assertEqual(default, '5522A')
        rows, _pts = a.certificate_rows_and_points()
        changeable = [s for s in specs if not s.locked]
        self.assertTrue(changeable)
        for s in changeable:
            self.assertEqual(RM.evaluate(s, s.default_std).unc_text, rows[s.idx]['Uncertainty'], s.description)         # the default is exactly what the report prints
        locked = [s for s in specs if s.locked]
        self.assertTrue(all(not rows[s.idx]['Uncertainty'] or s.locked for s in locked))
        m = RM.ReviewModel(specs, default, asset='A-100')
        first = changeable[0].idx
        self.assertIn('5560A', m.options(first))
        m.set_standard(first, '5560A')
        self.assertEqual(m.rows[first].cur.standard, '5560A')
        self.assertTrue(m.rows[first].changed)

    def test_existing_whole_sheet_waiver_procedures_run_as_before(self):
        import datasheet_builder_rules as rules
        r = self.register(standard='')
        ds = db.load(r.uid, root=self.us, db=self.reg)
        old = ds.copy()
        old.options.pop('manual_standard', None)
        old.uid = ''
        old.options[rules.WAIVER_KEY] = {rules.WHOLE_SHEET: dict(code='manual_calibration', reason='manual calibration: imported from .MDD, no automation', by='import (x)', at='2026-10-01T00:00:00')}
        old.assignments = {p.id: 'MANUAL' for _f, p in old.all_points()}
        res = db.save(old, who='x', root=self.us / 'old', db=self.d / 'old.sqlite3')
        self.assertEqual(res.status, 'ready')
        spec = json.loads((self.us / 'old' / (res.uid + '.json')).read_text())
        if self.h is not None:
            self.h.stop()
        self.h = H.Harness().start()
        a = self.h.make_app(spec)
        for p in a.points:
            a.type_reading(p, 'y') if p['test'] != 'numeric' else a.type_reading(p, H.typed_nominal(p))
        rows, _pts = a.certificate_rows_and_points()
        self.assertEqual([r['Uncertainty'] for r in rows], [''] * len(rows))
        self.assertEqual(a.manual_uncertainty_line(), '')

    # ---- the per-point chooser inside the run window (right-click a point > Uncertainty standard) ----------------------------------------------------
    def entries(self, a, tag):
        p = next(p for p in a.points if p['id'].endswith(tag))
        return p, a.unc_menu(p)

    def labels(self, a, tag):
        return [e[0] for e in self.entries(a, tag)[1]]

    def test_the_point_menu_offers_automatic_and_every_standard_that_covers_the_point(self):
        a = self.app('5522A')
        labels = self.labels(a, 'p0001')                                           # 100 mV DC
        self.assertEqual(labels[0], 'Uncertainty standard: Automatic (5522A)  (selected)')
        self.assertEqual([x.split(': ')[1].split('  ')[0] for x in labels[1:]], sorted(x.split(': ')[1].split('  ')[0] for x in labels[1:]))
        self.assertIn('Uncertainty standard: 5560A', labels)
        self.assertIn('Uncertainty standard: 5520A', labels)
        self.assertTrue(all(e[2] for e in self.entries(a, 'p0001')[1]))
        # the right-click menu of the engine carries them after 'Enter reading manually...'
        p = next(p for p in a.points if p['id'].endswith('p0001'))
        full = [e[0] for e in a.tree_menu_extras(p['id'])]
        self.assertEqual(full[0], 'Enter reading manually...')
        self.assertIn('Uncertainty standard: 5560A', full)
        # a point no standard gives an uncertainty for: one disabled line that says why; a diode / functional check: none
        _p, none = self.entries(a, 'p0006')
        self.assertEqual(none[0][0], 'Uncertainty standard...')
        self.assertFalse(none[0][2])
        self.assertIn('No standard', none[0][3])

    def test_choosing_a_standard_changes_that_rows_uncertainty_tar_tur_and_tag(self):
        import report_pdf
        a = self.app('5522A')
        p = next(p for p in a.points if p['id'].endswith('p0001'))
        before = a.certificate_row(p, a.found[p['id']])
        other = a.certificate_row(next(q for q in a.points if q['id'].endswith('p0002')), a.found[next(q for q in a.points if q['id'].endswith('p0002'))['id']])
        a.set_unc_choice(p, '5560A')
        row = a.certificate_row(p, a.found[p['id']])
        self.assertEqual(row['Uncertainty'], report_pdf.point_uncertainty(dict(kind='DCV', nominal=0.1, frequency=None, unit='V', range=None), '5560A'))
        self.assertNotEqual(row['Uncertainty'], before['Uncertainty'])
        self.assertTrue(row['Description'].endswith('[5560A]'), row['Description'])
        # TAR / TUR are the chosen standard's own (the same call the Builder's picker resolves through)
        figs = rt.manual_uncertainties(self.spec, None, None, {a._unc_pid(p): '5560A'}, only=a._unc_pid(p))[a._unc_pid(p)]
        import tartur
        f = a.certificate_fields(p)
        self.assertEqual((f['TAR'], f['TUR']), (tartur.format_ratio(figs['tar']), tartur.format_ratio(figs['tur'])))
        self.assertEqual(a.unc_figures(p)['unc_standard'], '5560A')
        # the menu marks the pick; the other rows are untouched
        self.assertIn('Uncertainty standard: 5560A  (selected)', self.labels(a, 'p0001'))
        self.assertEqual(a.certificate_row(next(q for q in a.points if q['id'].endswith('p0002')), a.found[next(q for q in a.points if q['id'].endswith('p0002'))['id']]), other)
        # Automatic puts the procedure's own standard back
        a.set_unc_choice(p, '')
        self.assertEqual(a.certificate_row(p, a.found[p['id']]), before)

    def test_it_is_the_builders_assignment_mechanism_and_no_second_code_path(self):
        import datasheet_builder_rules as rules
        a = self.app('5522A')
        p = next(p for p in a.points if p['id'].endswith('p0001'))
        pid = a._unc_pid(p)
        a.set_unc_choice(p, '5520A')
        ds = db.load(self.uid, root=self.us, db=self.reg)
        ds.assignments[pid] = '5520A'                                                # what the Builder's picker does (set_assignment)
        res, _why = rules.match_manual(ds, ds.default_period, None, None)
        want = rules.manual_figures(res.assignments[pid])
        self.assertEqual(a.unc_figures(p), want)

    def test_the_choice_is_recorded_saved_with_the_run_and_reported(self):
        a = self.app('5522A')
        p = next(p for p in a.points if p['id'].endswith('p0001'))
        a.set_unc_choice(p, '5560A')
        data = a.save_fields()
        self.assertEqual(data['dsb']['uncertainty_standards'], {p['id']: '5560A'})
        unc = a.manual_uncertainty_line()
        self.assertIn('5560A (1)', unc)
        self.assertIn('5522A (', unc)
        txt = self.pdf_text(a)
        self.assertIn('[5560A]', txt)
        self.assertIn('5560A (1)', txt)
        # a run loaded from that progress gets the same choice back; a file without it clears it
        b = self.app('5522A')
        b.load_results(dict(data))
        self.assertEqual(b.unc_choice, {p['id']: '5560A'})
        c = dict(data)
        c['dsb'] = {k: v for k, v in data['dsb'].items() if k != 'uncertainty_standards'}
        b.load_results(c)
        self.assertEqual(b.unc_choice, {})
        # without a pick nothing extra is saved
        self.assertNotIn('uncertainty_standards', self.app('5522A').save_fields()['dsb'])

    def test_the_command_log_gets_a_line_but_the_record_and_pass_fail_are_unchanged(self):
        a = self.app('5522A')
        p = next(p for p in a.points if p['id'].endswith('p0001'))
        found = dict(a.found[p['id']])
        notes = []
        a._log_note = notes.append
        a.set_unc_choice(p, '5560A')
        self.assertEqual(notes, [f'Uncertainty standard for point {p["id"]}: 5560A (was 5522A)'])
        self.assertEqual(a.found[p['id']], found)                                    # reading, result and the 'manual' standard of the record
        self.assertEqual(a.found[p['id']]['standard'], 'manual')

    def test_a_demo_run_offers_no_choice_menu_and_a_forced_choice_is_review_only(self):
        a = self.app('5522A', demo=True)
        p, entries = self.entries(a, 'p0001')
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0][2])
        self.assertIn('demo', entries[0][3].lower())
        a.set_unc_choice(p, '5560A')                                                   # a forced choice is shown for review too, never exported
        rows, _pts = a.certificate_rows_and_points()
        self.assertTrue(any(r['Uncertainty'] for r in rows))
        self.assertEqual(a.manual_uncertainty_line(), '')

    def test_a_frequency_point_carries_the_lab_cmc_and_can_be_changed_to_another_covering_standard(self):
        import report_pdf
        a = self.app('5522A')
        p = next(p for p in a.points if (p.get('dsb') or {}).get('kind') == 'FREQ')
        hz = float(p['run']['nominal'])
        want = report_pdf.point_uncertainty(dict(kind='FREQ', nominal=hz, frequency=None, unit='Hz', range=1.0, source='x'), '5522A')
        row = a.certificate_row(p, a.found[p['id']])
        self.assertEqual(row['Uncertainty'], want)
        self.assertTrue(row['Description'].endswith('[5522A]'), row['Description'])
        self.assertIn('Uncertainty standard: 5560A', [e[0] for e in a.unc_menu(p)])
        a.set_unc_choice(p, '5560A')
        row2 = a.certificate_row(p, a.found[p['id']])
        self.assertEqual(row2['Uncertainty'], want)                                    # the figure is the CMC alone, so the standard changes the tag, not the figure
        self.assertTrue(row2['Description'].endswith('[5560A]'), row2['Description'])
        self.assertIn('Frequency - Measure CMC alone', a.manual_uncertainty_line())

    def test_the_review_window_follows_a_picked_standard(self):
        import report_review_model as RM
        a = self.app('5522A')
        p = next(p for p in a.points if p['id'].endswith('p0001'))
        a.set_unc_choice(p, '5560A')
        specs, _default = RM.specs_for(a)
        rows, _pts = a.certificate_rows_and_points()
        s = next(s for s in specs if s.step == p['id'])
        self.assertEqual(s.default_std, '5560A')
        self.assertEqual(RM.evaluate(s, s.default_std).unc_text, rows[s.idx]['Uncertainty'])


if __name__ == '__main__':
    unittest.main()


class LightMeterUnits(unittest.TestCase):
    """Gould-Bass DLM-1000 radiometer set: foot-candle and uW/cm2 points are light-meter points in their own units, not pass / fail checks
    (the file lost the micro and square signs of 'uW/cm2': U+FFFD, read as uW/cm2 and flagged)."""

    def setUp(self):
        import mdd_importer_v49 as imp
        self.conv = mc.convert(imp.parse_mdd(Path(__file__).resolve().parent / 'fixtures' / 'mdd_dlm1000_light_meter.mdd'))

    def test_units_are_kept_not_pass_fail(self):
        kinds = {}
        for f in self.conv.sheet.functions:
            kinds[f.kind] = kinds.get(f.kind, 0) + len(f.points)
        self.assertEqual(kinds, {'CHECK': 1, 'DCV': 4, 'FC': 6, 'UVIRR': 5})
        self.assertEqual([i.point for i in self.conv.issues if i.code == 'limit_unit_unknown'], [1])      # only the 'Zero Reference' point stays a check

    def test_the_lost_characters_are_flagged_and_shown_as_the_unit(self):
        self.assertTrue(any(i.code == 'unit_note' and 'Check the unit' in i.message for i in self.conv.issues))
        labels = [p.label for f in self.conv.sheet.functions if f.kind == 'UVIRR' for p in f.points]
        self.assertTrue(labels and all('�' not in x and 'µW/cm²' in x for x in labels))


class LightMeterUncertainty(unittest.TestCase):
    """The light points of the DLM-1000 set get an uncertainty from the A2LA light scope (A2LA-LIGHT, 2.9 % white / 5.0 % black light of reading, k = 2), no longer 'none by design'."""

    def setUp(self):
        import mdd_importer_v49 as imp
        self.conv = mc.convert(imp.parse_mdd(Path(__file__).resolve().parent / 'fixtures' / 'mdd_dlm1000_light_meter.mdd'))

    def test_light_points_are_sourced(self):
        plan, rows, text = mc.uncertainty_preview(self.conv.sheet, 'A2LA-LIGHT')
        self.assertEqual(plan.counts()['sourced'], 11)
        self.assertEqual(rows[9], '2.9 FC (A2LA-LIGHT)')                  # 100 fc x 2.9 %
        self.assertEqual(rows[12], '5.0 uW/cm2 (A2LA-LIGHT)')             # 100 uW/cm2 x 5.0 %
        self.assertFalse(any(v == 'none by design' for n, v in rows.items() if n > 1))

    def test_best_fit_is_a_light_standard(self):
        fits = mc.standard_fits(self.conv.sheet)
        self.assertIn(mc.best_standard(fits), ('A2LA-LIGHT', 'T-10A'))


class LightMeterReport(Fix):
    """The registered DLM-1000 light-meter sheet exports its PDF (the row builder had no symbol for FC / lux / µW/cm²: KeyError 'FC') with the A2LA-LIGHT uncertainties."""

    def setUp(self):
        super().setUp()
        self.path = Path(__file__).resolve().parent / 'fixtures' / 'mdd_dlm1000_light_meter.mdd'
        self.parsed = imp.parse_mdd(self.path)
        self.conv = mc.convert(self.parsed)
        self.h = None

    def tearDown(self):
        if self.h is not None:
            self.h.stop()

    def test_pdf_exports_with_light_units_and_uncertainty(self):
        r = self.register(standard='A2LA-LIGHT')
        self.assertTrue(r.ok, r.message)
        spec = json.loads((self.us / (r.uid + '.json')).read_text())
        self.h = H.Harness().start()
        a = self.h.make_app(spec)
        for p in a.points:
            a.type_reading(p, 'y') if p['test'] != 'numeric' else a.type_reading(p, H.typed_nominal(p))
        import report_review_model as RM
        specs, default = RM.specs_for(a)                            # the review window: the light rows are covered by the lab's light CMC, not 'Not in scope'
        model = RM.ReviewModel(specs, default, asset='A-100')
        light = [r for r in model.rows if r.spec.unit in ('FC', 'uW/cm2', '\u00b5W/cm\u00b2')]
        self.assertEqual(len(light), 11)
        for r in light:
            self.assertNotEqual(r.status, RM.NOT_IN_SCOPE, r.spec.description)
            self.assertIsNotNone(r.cur.cmc, r.spec.description)
        out = str(Path(tempfile.mkdtemp()) / 'A-100-2026-10-27.pdf')
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [], 'procedure': '', 'show_tar_tur': True}
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', lambda **k: out):
            a.export_pdf()
        txt = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
        self.assertIn('Calibration Data', txt)
        self.assertIn('FC', txt)
        self.assertIn('2.9', txt)                                   # 100 fc x 2.9 %
