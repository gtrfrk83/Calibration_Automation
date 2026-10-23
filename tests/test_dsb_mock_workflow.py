"""The technician workflow of the Claude Doc 'Datasheet Creator: technician workflow (handheld multimeters)', run headless: a MOCK handheld multimeter
datasheet ('Mock 8000', invented numbers, nothing from a manual) is built through the same model calls the Datasheet Builder window makes (template,
remove sections, ranges, rows, tolerances, review, standards / automation summary, save), then run in demo on the simulated bench through to the
'Calibration Data' PDF.  Also pins the behaviours that workflow doc describes (rows are sorted, the cursor moves to the next section's empty row,
Lock Status is not stored in the saved sheet, a forgotten frequency blocks saving as runnable).  The same steps were driven on a REAL Tk under Xvfb
(see NOTES.md, 'Datasheet Builder workflow test'); this file needs no tkinter (tests/_tk_stub.py stands in, as for the other engine tests).
Run:  python -m unittest tests.test_dsb_mock_workflow"""
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
import datasheet_builder_ui_model as DM  # noqa: E402
import dsb_runtime as rt  # noqa: E402
import labregistry  # noqa: E402
import report_dialog  # noqa: E402
import ui_theme as ui  # noqa: E402

RANGES = {'dcv': [('6 V', '1 mV'), ('60 V', '10 mV'), ('600 V', '100 mV')],
          'acv': [('6 V', '1 mV'), ('60 V', '10 mV'), ('600 V', '100 mV')],
          'dci': [('60 mA', '10 uA'), ('600 mA', '100 uA')],
          'ohm2': [('600 ohm', '0.1 ohm'), ('6 kohm', '1 ohm'), ('60 kohm', '10 ohm')],
          'temp': [('1000 C', '0.1 C')]}
# (section id, rows typed in this order, tolerance of the first row: '% of reading' and Floor in the row's units; Floor only for temperature)
PLAN = [('dcv', ['5 V', '50 V', '500 V'], dict(iv='0.5', floor='0.005')),
        ('acv', ['5 V @ 1 kHz', '50 V @ 1 kHz', '5 V @ 20 kHz'], dict(iv='1.5', floor='0.05')),
        ('dci', ['10 mA', '50 mA', '500 mA'], dict(iv='1.0', floor='0.0001')),
        ('ohm2', ['100 ohm', '1 kohm', '10 kohm'], dict(iv='0.5', floor='0.2')),
        ('temp', ['0 C', '100 C'], dict(floor='1.5'))]
NOT_ON_MOCK = ('aci', 'cont', 'cap', 'freq', 'diode')


class Sheet:
    """Drives a GridModel like the window does: select a cell, type, Calc."""

    def __init__(self, tmp):
        self.storage = DM.Storage(Path(tmp) / 'user_specs', Path(tmp) / 'lab_registry.sqlite3', who='mock')
        self.lst = DM.DatasheetList(self.storage)
        self.g = self.lst.new(handheld=True)               # New... with 'Start from a handheld template' ticked

    def blank_key(self, fid):
        return next(r['key'] for r in self.g.rows() if r['kind'] == 'blank' and r['fid'] == fid)

    def trailing_blank(self):
        return next(r['key'] for r in self.g.rows() if r['kind'] == 'blank' and r['key'].startswith('b:'))

    def points(self, fid=None):
        return [r for r in self.g.rows() if r['kind'] == 'point' and (fid is None or r['fid'] == fid)]

    def type_cell(self, key, col, text):
        self.g.select(key, col)
        return self.g.commit_cell(text)

    def calc(self, key, iv=None, floor=None):
        """Select the row's tolerance cell, tick the chips, fill the boxes, press Calc."""
        self.g.select(key, 'low')
        form = self.g.panel_state(key)['form']
        form['types'] = [t for t, v in (('iv', iv), ('floor', floor)) if v is not None]
        form['plus'].update(iv=iv or '', floor=floor or '')
        return self.g.calc_row(key, form)

    def add_row(self, section_name, text):
        """The 2nd, 3rd ... row of a section: click the empty row at the bottom, pick the function in 'This row tests', type the value."""
        self.g.select(self.trailing_blank(), 'nominal')
        res = self.g.set_target_function(section_name)
        self.assertOk(res)
        return self.g.commit_cell(text)

    @staticmethod
    def assertOk(res):
        if not res.ok:
            raise AssertionError(res.message)
        return res

    def build(self):
        g = self.g
        self.assertOk(g.set_header(make='MOCK Acme', model='Mock 8000', title='MOCK Mock 8000 handheld'))
        for fid in NOT_ON_MOCK:                              # step 3: remove the sections the mock does not have
            self.assertOk(g.remove_function(fid))
        for fid, rl in RANGES.items():                       # step 4: ranges first (More > Ranges...)
            for fs, res in rl:
                self.assertOk(g.add_range(fid, fs, res))
        for fid, values, tol in PLAN:
            name = g.ds.function(fid).name
            self.assertOk(self.type_cell(self.blank_key(fid), 'nominal', values[0]))
            self.assertOk(self.calc(self.points(fid)[0]['key'], **tol))
            for v in values[1:]:
                self.assertOk(self.add_row(name, v))
        return g


class MockWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.sheet = Sheet(cls.tmp)
        cls.g = cls.sheet.build()

    # ---- steps 2 to 6
    def test_template_gives_the_ten_handheld_sections_then_the_mock_keeps_five(self):
        fresh = Sheet(tempfile.mkdtemp()).g
        self.assertEqual([f.id for f in fresh.ds.functions], ['dcv', 'acv', 'dci', 'aci', 'ohm2', 'cont', 'cap', 'freq', 'temp', 'diode'])
        self.assertEqual([f.id for f in self.g.ds.functions], ['dcv', 'acv', 'dci', 'ohm2', 'temp'])

    def test_fourteen_rows_no_problems_and_every_row_has_a_tolerance(self):
        pts = self.sheet.points()
        self.assertEqual(len(pts), 14)
        self.assertEqual(self.g.problem_counts(), dict(errors=0, warnings=0))
        self.assertTrue(all(r['low'] and r['high'] and r['low'] != 'open' and r['high'] != 'open' for r in pts), [(r['low'], r['high']) for r in pts])
        self.assertFalse(any('±' in r['low'] + r['high'] for r in pts))
        self.assertEqual(self.g.problems(), [])

    def test_rows_land_on_the_predefined_ranges_and_check_against_hand_arithmetic(self):
        rows = {(r['fid'], r['nominal']): r for r in self.sheet.points()}
        self.assertIn('6 V range', rows[('dcv', '+5.000 V')]['function'])
        self.assertIn('600 V range', rows[('dcv', '+500.0 V')]['function'])
        self.assertIn('600 mA range', rows[('dci', '+500.0 mA')]['function'])
        # 0.5 % of 5 V + 5 mV = 30 mV; 0.5 % of 50 V + 5 mV = 255 mV (the inherited tolerance is worked out again for each row's own value)
        # ... shown as the two absolute limits (nominal -/+ that), padded to the range's resolution
        self.assertEqual((rows[('dcv', '+5.000 V')]['low'], rows[('dcv', '+5.000 V')]['high']), ('4.970 V', '5.030 V'))
        self.assertEqual((rows[('dcv', '+50.00 V')]['low'], rows[('dcv', '+50.00 V')]['high']), ('49.745 V', '50.255 V'))
        # the Floor box is in the row's units: 0.0001 on a mA row is 0.0001 mA = 100 nA (1 % of 10 mA = 100 uA, plus 0.1 uA)
        self.assertEqual((rows[('dci', '+10.00 mA')]['low'], rows[('dci', '+10.00 mA')]['high']), ('9.8999 mA', '10.1001 mA'))

    def test_rows_are_sorted_by_range_then_frequency_not_in_the_order_typed(self):
        """The doc: 'Keep the order the manual uses' cannot be done by typing order: AC rows typed 5 V@1k, 50 V@1k, 5 V@20k are listed 5@1k, 5@20k, 50@1k."""
        self.assertEqual([r['nominal'] for r in self.sheet.points('acv')], ['+5.000 V @ 1 kHz', '+5.000 V @ 20 kHz', '+50.00 V @ 1 kHz'])

    def test_after_a_first_row_the_cursor_goes_to_the_next_sections_empty_row(self):
        """The doc: typing the next value straight away lands in the NEXT section (here AC volts), so the 2nd row of a section is added from the empty row at the bottom."""
        s = Sheet(tempfile.mkdtemp())
        s.assertOk(s.g.set_header(make='MOCK', model='M', title='t'))
        s.assertOk(s.g.add_range('dcv', '6 V', '1 mV'))
        s.assertOk(s.type_cell(s.blank_key('dcv'), 'nominal', '5 V'))
        self.assertEqual(s.g.sel_key, 'e:acv')
        s.assertOk(s.g.commit_cell('10 V'))                  # silently an AC volts row
        self.assertEqual([(r['fid'], r['nominal']) for r in s.points()], [('dcv', '+5.000 V'), ('acv', '+10 V')])

    def test_forgotten_frequency_on_an_ac_row_is_an_error_that_blocks_saving_as_runnable(self):
        s = Sheet(tempfile.mkdtemp())
        s.build()
        s.assertOk(s.add_row('AC volts', '5 V'))
        self.assertEqual(s.g.problem_counts()['errors'], 1)
        self.assertIn('needs a frequency', s.g.problem_rows()[0]['text'])
        res = s.g.save_sheet()
        self.assertFalse(res.ok)
        self.assertTrue(res.detail.get('needs_draft'))

    def test_empty_template_sections_are_warnings_not_errors(self):
        fresh = Sheet(tempfile.mkdtemp())
        fresh.g.set_header(make='MOCK', model='M', title='t')
        c = fresh.g.problem_counts()
        self.assertEqual(c['errors'], 1, 'a sheet of only empty sections cannot be saved as runnable (no_test_rows)')
        self.assertGreaterEqual(c['warnings'], 1)

    def test_recalc_all_checks_every_row(self):
        res = self.g.recalc_all()
        self.assertTrue(res.ok)
        self.assertIn('Checked 14 rows: all fine.', res.message)

    # ---- step 6 / 7: preview, standards, automation summary
    def test_preview_is_a_blank_template_with_empty_as_found_and_as_left(self):
        view = self.g.print_view()
        self.assertIn('BLANK', view['notice'].upper())
        self.assertEqual(len([r for r in view['rows'] if r['kind'] != 'header']), 14)
        out = Path(self.tmp) / 'blank.pdf'
        self.assertTrue(self.g.write_sheet_pdf(str(out)).ok)
        self.assertGreater(out.stat().st_size, 1000)

    def test_standards_summary_every_point_covered_temperature_unverified(self):
        res = self.g.run_match()
        self.assertTrue(res.ok, res.message)
        text = self.g.match_summary_text()
        self.assertIn('14 of 14 points have a standard', text)
        self.assertIn('2 with commands not yet verified on hardware', text)
        line = self.g.automation_line()
        self.assertIn('of 14 points', line)
        self.assertIn('not yet verified', line)
        temp = [r for r in self.g.match_rows('temp')]
        self.assertEqual(len(temp), 2)
        self.assertTrue(all('not verified' in (r['automation'] + r['message']) for r in temp))


class MockSaveAndDemo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sheet = Sheet(self.tmp)
        self.g = self.sheet.build()

    # ---- step 8
    def test_save_makes_a_runnable_user_built_procedure_and_lock_is_not_stored(self):
        self.g.set_locked(True)
        res = self.g.save_sheet()
        self.assertTrue(res.ok, res.message)
        uid = self.g.ds.uid
        entry = next(e for e in self.sheet.storage.entries() if e['uid'] == uid)
        self.assertTrue(Path(entry['spec_path']).exists())
        self.assertEqual(entry['name'], 'MOCK Acme Mock 8000 - MOCK Mock 8000 handheld')
        again = self.sheet.lst.open(uid)
        self.assertFalse(again.locked, 'Lock Status is a per-window safeguard: a reopened sheet is in Edit Mode (the real lock is Mark verified on hardware)')
        res2 = again.set_locked(True)
        self.assertTrue(again.cell_editable(again.rows()[1]['key'], 'nominal')[0] is False)
        self.assertTrue(res2.ok)

    # ---- step 9: Try in demo
    def run_sheet(self, demo=True):
        self.assertTrue(self.g.save_sheet().ok)
        entry = next(e for e in self.sheet.storage.entries() if e['uid'] == self.g.ds.uid)
        spec = rt.load_spec(entry['spec_path'])              # what Try in demo starts: the generic launcher with the saved spec file
        h = H.Harness().start()
        self.addCleanup(h.stop)
        app = h.make_app(spec, demo=demo)
        app.asset.set('MOCK-0001')
        if not demo:
            app.cal_mode.set(rt.hh.CAL_CHOICES[2])           # Manual: no instrument on this machine
        h.default_reading = H.typed_nominal
        self.assertTrue(h.run_all())
        return h, app

    def export(self, app):
        """Export Report (PDF) like the button: details dialog, save dialog; returns (pdf text, save-dialog kwargs, the Asset History writer's mock)."""
        out = tempfile.mkdtemp() + '/ask.pdf'
        asked = {}

        def save_as(**k):
            asked.update(k)
            return out
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [], 'procedure': '', 'show_tar_tur': False}
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', save_as), \
                mock.patch.object(labregistry, 'record_run') as rec:
            app.export_pdf()
        text = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
        return text, asked, rec

    def test_demo_runs_all_fourteen_points_synthetic_and_marks_the_report(self):
        h, app = self.run_sheet(demo=True)
        self.assertEqual(len(app.points), 14)
        self.assertEqual(len(app.found), 14)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        # the 500 V point asks the high-voltage question
        self.assertTrue(any(d[0] == 'box' and d[2] == 'HIGH VOLTAGE' and '500 V' in d[3] for d in h.dialogs))
        text, asked, _rec = self.export(app)
        self.assertEqual(asked['initialfile'], ui.report_filename('MOCK-0001'), 'asset number - date')
        self.assertIn('DEMO - synthetic data, not calibration evidence', text)
        self.assertIn('MOCK Acme Mock 8000', text)
        self.assertIn('RESULT: PASS', text)
        self.assertEqual(text.count('[demo]'), 14)

    def test_demo_report_is_never_recorded_in_asset_history_but_a_real_one_is(self):
        _h, demo_app = self.run_sheet(demo=True)
        _text, _asked, rec = self.export(demo_app)
        rec.assert_not_called()
        self.assertFalse(demo_app.any_synthetic() is False)
        _h2, real_app = self.run_sheet(demo=False)
        self.assertFalse(real_app.any_synthetic())
        _text, _asked, rec = self.export(real_app)
        rec.assert_called_once()                              # the contrast: the check above is not vacuous


if __name__ == '__main__':
    unittest.main()
