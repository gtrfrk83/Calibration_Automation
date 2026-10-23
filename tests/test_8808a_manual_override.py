"""Fluke 8808A: manual override of a reading (owner request: 'a way to manually override a reading ... no need to annotate it on the report').

The meter is read back automatically; the technician may type the reading for the point being measured, for a point already stored, or when the
automatic reading failed (the run goes on). Checked on the simulated bench (the real App, tkinter stubbed): the typed value replaces the automatic
one, the procedure's own limit logic judges it, bad input is rejected, the report is identical with and without an override, the command log has
'MANUAL OVERRIDE point N: ...', the run survives a failed reading, demo mode stays synthetic, and only the 8808A App opts in.
The Tk dialog itself is viewed on a real Tk under Xvfb (tests/real_tk_checks.py is not extended; see NOTES.md).
"""
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402  (installs the tkinter stub)

import manual_override as MO  # noqa: E402
import fluke8808a_verification as E  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.simulated_8808a import make_8808a_bench  # noqa: E402


def point(pid):
    return E.POINTS[pid - 1]


class Parse(unittest.TestCase):
    def setUp(self):
        E.configure()
        E.apply_period(E.POINTS, '1y')

    def test_padded_to_the_points_resolution_and_kept_in_base_units(self):
        p = point(30)                                                     # 190 V dc, limits 189.966 .. 190.034 V (3 decimals)
        e = MO.parse_reading(p, '190')
        self.assertEqual((e.text, e.unit, e.value, e.shown), ('190.000', 'V', 190.0, '190.000 V'))
        self.assertEqual(MO.parse_reading(p, '190.01').text, '190.010')
        self.assertEqual(MO.parse_reading(p, '190.0123').text, '190.0123')       # more decimals than the resolution: kept as typed (pad_reading)
        self.assertEqual(MO.parse_reading(p, '190.0123').value, 190.0123)

    def test_millivolt_point_is_typed_in_mv_and_stored_in_volts(self):
        p = point(22)                                                     # 190 mV, limits 189.964 .. 190.037 mV
        e = MO.parse_reading(p, '190.0')
        self.assertEqual((e.unit, e.text), ('mV', '190.000'))
        self.assertAlmostEqual(e.value, 0.19, places=12)
        self.assertEqual(MO.parse_reading(p, '189.9641').value, 0.1899641)

    def test_zero_offset_point_is_typed_in_microvolts(self):
        p = point(1)                                                      # limits -8 .. 8 uV
        e = MO.parse_reading(p, '-0.3')
        self.assertEqual((e.text, e.unit), ('-0.3', '\u00b5V'))
        self.assertAlmostEqual(e.value, -3e-7, places=15)

    def test_the_text_of_the_confirmation_names_the_value_and_unit(self):
        p = next(x for x in E.POINTS if x['kind'] == 'OHM2' and x['range'] == 2000.0 and x['nominal'] > 0)
        e = MO.parse_reading(p, '1.9')
        self.assertTrue(e.unit.endswith('\u03a9'), e.unit)
        self.assertEqual(e.shown.split()[0], e.text)

    def test_bad_input_is_rejected(self):
        p = point(31)
        for bad in ('', '  ', 'abc', 'nan', 'NaN', 'inf', '-inf', 'Infinity', '1..2', '1-2', '--1', '5 V', '1,2,x', 'OL', '0L', 'O.L.', 'overload', '1e999', '1e12', '0x10'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                MO.parse_reading(p, bad)

    def test_sign_and_exponent_are_taken_as_the_existing_manual_entry_takes_them(self):
        p = point(31)                                                     # -190 V dc
        self.assertEqual(MO.parse_reading(p, '-190.0010').value, -190.001)
        self.assertEqual(MO.parse_reading(p, '+190.0010').value, 190.001)  # the sign is the operator's; the limits decide pass / fail
        self.assertEqual(MO.parse_reading(p, '1.9e2').value, 190.0)       # pad_reading leaves exponent notation as typed

    def test_the_padding_is_the_existing_pad_reading(self):
        from handheld_dmm import pad_reading
        p = point(30)
        vals, _unit, _scale = MO.entry_scale(p)
        self.assertEqual(MO.parse_reading(p, '1').text, pad_reading({'low': vals[0], 'high': vals[1]}, '1'))
        self.assertEqual(MO.parse_reading(p, '1').text, '1.000')

    def test_log_text(self):
        p = point(31)
        e = MO.parse_reading(p, '-190.0010')
        self.assertEqual(MO.log_text(p, e, 190.1234), f'MANUAL OVERRIDE point 31: auto reading 190.1234 V, entered {e.shown} = -190.001 V')
        self.assertIn('auto reading none (overload reading', MO.log_text(p, e, None, 'overload reading 1E+9'))
        self.assertTrue(MO.log_text(p, e, None).startswith('MANUAL OVERRIDE point 31: auto reading none, entered '))
        self.assertTrue(MO.log_text(p, e, None, mode='As Found, demo').endswith('[As Found, demo]'))


class Base(unittest.TestCase):
    def setUp(self):
        self.h = H.EngineHarness().start(E)
        self.addCleanup(self.h.stop)
        pa = mock.patch('time.sleep', side_effect=lambda s: None)
        pa.start()
        self.addCleanup(pa.stop)
        self.answers = []          # what the (patched) entry window returns, in order
        self.asked = []

    def ask(self, p, reason='', cancel_text='Cancel', stored=''):
        self.asked.append(dict(id=p['id'], reason=reason, cancel=cancel_text, stored=stored))
        v = self.answers.pop(0) if self.answers else None
        return MO.parse_reading(p, v) if isinstance(v, str) else v

    def build(self, demo=False):
        E.configure()
        app = self.app = E.App(self.h.root, '8808A', demo=demo)
        self.h.app = app
        app.asset.set('A-8808'); app.serial.set('SN'); app.warm_confirmed = True
        app.mo_ask = self.ask
        if not demo:
            bench, ct, dt = make_8808a_bench('5522A', True)
            self.bench = bench
            io = E.IO('sim', 'sim', 'Fluke 5522A', 9600, transports=(dt, ct), mods=app.pm_state)
            io.is_manual = app.is_manual
            app.io = io
            st = app.pm_state
            st.store, st.devmode = self.h.env.store, self.h.env.dm
        return app

    def run_points(self, *ids):
        n = len(self.h.dialogs)
        self.app.execute([E.POINTS[i - 1] for i in ids])
        self.assertTrue(self.h.pump(60), 'the run did not finish')
        return self.h.dialogs[n:]

    def log(self):
        return self.app.io.log.lines()

    def cal_sent(self, start=0):
        out = []
        for line in self.log()[start:]:
            parts = line.split(None, 3)
            if len(parts) > 3 and parts[1] == '5522A' and parts[2] == '>>':
                out.append(parts[3])
        return out

    def overrides(self):
        return [l.split('  ', 2)[-1].strip() for l in self.log() if 'MANUAL OVERRIDE' in l]


class Overrides(Base):
    def test_a_stored_point_is_replaced_and_judged_with_the_existing_limits(self):
        app = self.build()
        self.run_points(31)
        auto = app.found['31']['reading']
        self.assertEqual(app.found['31']['result'], 'PASS')
        self.answers = ['-190.0500']                                       # outside -190.034 .. -189.966
        app.tree.selection = lambda: ['31']
        app.mo_button_clicked()
        self.assertEqual(app.found['31']['reading'], -190.05)
        self.assertEqual(app.found['31']['result'], 'FAIL')
        self.assertEqual(app.found['31']['auto_reading'], auto)
        self.assertEqual(self.asked[-1]['id'], 31)
        self.assertIn('V', self.asked[-1]['stored'])                      # the window shows the stored reading it replaces
        self.answers = ['-190.0200']                                       # back inside
        app.mo_button_clicked()
        self.assertEqual((app.found['31']['reading'], app.found['31']['result']), (-190.02, 'PASS'))
        self.assertEqual(app.found['31']['auto_reading'], auto)            # the instrument's reading, not the earlier typed one
        lines = self.overrides()
        self.assertEqual(len(lines), 2)
        self.assertIn(f'MANUAL OVERRIDE point 31: auto reading {auto:.9g} V, entered -190.0500 V = -190.05 V', lines[0])
        self.assertIn(f'auto reading {auto:.9g} V, entered -190.0200', lines[1])

    def test_limits_are_inclusive_and_exact(self):
        app = self.build()
        p = point(31)
        for text, result in (('-190.034', 'PASS'), ('-189.966', 'PASS'), ('-190.0341', 'FAIL'), ('-189.9659', 'FAIL'), ('-190', 'PASS')):
            self.answers = [text]
            app.tree.selection = lambda: ['31']
            app.mo_button_clicked()
            self.assertEqual(app.found['31']['result'], result, text)
            self.assertEqual(app.found['31']['result'], 'PASS' if E.judge(p, app.found['31']['reading']) else 'FAIL')

    def test_a_point_not_measured_yet_can_be_entered(self):
        app = self.build()
        self.answers = ['1']
        app.tree.selection = lambda: ['1']
        app.mo_button_clicked()
        self.assertEqual(app.found['1']['result'], 'PASS')
        self.assertIsNone(app.found['1']['auto_reading'])
        self.assertIn('auto reading none (point not measured)', self.overrides()[0])

    def test_cancel_changes_nothing_and_logs_nothing(self):
        app = self.build()
        self.run_points(31)
        before = dict(app.found['31'])
        self.answers = [None]
        app.tree.selection = lambda: ['31']
        app.mo_button_clicked()
        self.assertEqual(app.found['31'], before)
        self.assertEqual(self.overrides(), [])

    def test_no_selection_and_no_asset(self):
        app = self.build()
        app.tree.selection = lambda: []
        n = len(self.h.dialogs)
        app.mo_button_clicked()
        self.assertEqual(self.h.dialogs[n][1:3], ('showinfo', 'Enter reading manually'))
        app.tree.selection = lambda: ['1']
        app.asset.set('')
        app.mo_button_clicked()
        self.assertEqual(self.h.dialogs[-1][1:3], ('showwarning', 'Instrument ID'))
        self.assertEqual(self.asked, [])

    def test_while_running_only_the_point_being_measured_is_offered(self):
        app = self.build()
        app.busy = True
        self.assertEqual(app.mo_state(point(5))[0], False)
        app._mo_current = point(5)
        self.assertEqual(app.mo_state(point(5)), (True, ''))
        self.assertEqual(app.mo_state(point(6))[0], False)
        self.assertIn('only the point being measured', app.mo_state(point(6))[1])
        menu = app.tree_menu_extras('5')
        self.assertEqual([(m[0], m[2]) for m in menu], [('Enter reading manually...', True)])
        self.assertFalse(app.tree_menu_extras('6')[0][2])

    def test_typed_while_the_point_is_measured_replaces_the_automatic_reading(self):
        app = self.build()
        real = app.io.measure
        armed = threading.Event()

        def measure(p):
            if p['id'] == 31:
                self.answers = ['-190.0100']
                app.root.after(0, lambda: (app.mo_button_clicked(), armed.set()))          # the technician clicks on the main thread during the measurement
                self.assertTrue(armed.wait(10))
            return real(p)
        app.io.measure = measure
        self.run_points(30, 31, 32)
        self.assertEqual(app.found['31']['reading'], -190.01)
        self.assertEqual(app.found['31']['result'], 'PASS')
        self.assertIsNotNone(app.found['31']['auto_reading'])
        self.assertNotIn('overridden', app.found['30'])
        self.assertNotIn('overridden', app.found['32'])
        self.assertEqual(len(self.overrides()), 1)
        self.assertIn('MANUAL OVERRIDE point 31: auto reading -190.0', self.overrides()[0])
        self.assertEqual(self.asked[0]['id'], 31)
        self.assertEqual(self.cal_sent()[-1], 'STBY')                        # outputs still go to standby after the points

    def test_outputs_go_to_standby_after_the_overridden_point(self):
        app = self.build()
        self.run_points(31)
        app.tree.selection = lambda: ['31']
        self.answers = ['-190.0100']
        n = len(self.log())
        app.mo_button_clicked()
        sent = self.cal_sent(n)
        self.assertEqual(sent[-1], 'STBY')
        self.assertNotIn('OPER', sent)

    def test_the_stored_record_carries_the_override_only_in_the_progress_file(self):
        app = self.build()
        self.answers = ['1']
        app.tree.selection = lambda: ['1']
        app.mo_button_clicked()
        saved = (Path(app._checkpoint_path())).read_text()
        self.assertIn('"overridden": true', saved)
        self.assertNotIn('MANUAL', saved)


class FailedReading(Base):
    def test_overload_does_not_stop_the_run(self):
        app = self.build()
        real = app.io.dmm.read
        calls = []

        def read():
            calls.append(1)
            if len(calls) == 1:
                raise InstrumentError('Fluke 8808A: overload reading +1.000000E+9 (input not connected, wrong range or wrong function)')
            return real()
        app.io.dmm.read = read
        self.answers = ['2']                                               # uV
        d = self.run_points(1, 2, 3)
        self.assertEqual([x for x in d if x[0] == 'box' and x[1] == 'showerror'], [])
        self.assertEqual([app.found[str(i)]['result'] for i in (1, 2, 3)], ['PASS'] * 3)
        self.assertEqual(app.found['1']['reading'], 2e-6)
        self.assertIn('overload', self.asked[0]['reason'])
        self.assertEqual(self.asked[0]['cancel'], 'Stop run')
        self.assertIn('MANUAL OVERRIDE point 1: auto reading none (Fluke 8808A: overload reading', self.overrides()[0])
        self.assertTrue(any('reading failed (' in l and '!!' in l for l in self.log()))
        self.assertFalse(app.busy)

    def test_a_timeout_does_not_stop_the_run(self):
        app = self.build()
        self.bench.fail_next = 'MEAS1?'
        self.answers = ['2']
        d = self.run_points(1, 2)
        self.assertEqual([x for x in d if x[0] == 'box' and x[1] == 'showerror'], [])
        self.assertEqual(app.found['1']['reading'], 2e-6)
        self.assertEqual(app.found['2']['result'], 'PASS')
        self.assertIn('simulated timeout', self.overrides()[0])
        self.assertTrue(any('input buffer cleared after a failed reading' in l for l in self.log()))

    def test_unreadable_reply_on_a_calibrator_point_ends_in_standby_and_goes_on(self):
        app = self.build()
        real = app.io.dmm.read
        state = {'n': 0}

        def read():
            state['n'] += 1
            if state['n'] == 1:
                raise InstrumentError("Fluke 8808A: unreadable reading 'xx'")
            return real()
        app.io.dmm.read = read
        self.answers = ['190.0010']
        self.run_points(30, 31)
        self.assertEqual(app.found['30']['reading'], 190.001)
        self.assertEqual(app.found['31']['result'], 'PASS')
        cal = self.cal_sent()
        i = max(i for i, t in enumerate(cal) if t == 'OPER')
        self.assertIn('STBY', cal[i:])
        stby_after_fail = [l for l in self.log() if 'reading failed (' in l]
        self.assertEqual(len(stby_after_fail), 1)

    def test_stop_run_in_the_window_stops_as_before(self):
        app = self.build()
        app.io.dmm.read = mock.Mock(side_effect=InstrumentError('Fluke 8808A: unreadable reading'))
        self.answers = [None]
        d = self.run_points(1, 2)
        self.assertEqual(len([x for x in d if x[0] == 'box' and x[1] == 'showerror']), 1)
        self.assertNotIn('1', app.found)
        self.assertNotIn('2', app.found)
        self.assertFalse(app.busy)
        self.assertEqual(self.overrides(), [])

    def test_a_failure_that_is_not_a_reading_still_stops(self):
        app = self.build()
        app.io.dmm.check_errors = mock.Mock(side_effect=InstrumentError('Fluke 8808A reported execution error after configuring'))
        d = self.run_points(1)
        self.assertEqual(len([x for x in d if x[0] == 'box' and x[1] == 'showerror']), 1)
        self.assertEqual(self.asked, [])


class Report(Base):
    def rows_and_pdf(self, app):
        out = tempfile.mkdtemp() + '/x.pdf'
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '',
             'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), \
                mock.patch.object(E.filedialog, 'asksaveasfilename', lambda **k: out), mock.patch('report_pdf.record_history', create=True):
            app.export_pdf()
        text = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
        return app.certificate_rows(), re.sub(r'\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d)?|\b\d{1,2}[:.]\d\d\b', '<time>', text)

    def test_report_is_identical_with_and_without_an_override(self):
        app = self.build()
        self.run_points(31, 32)
        rows_a, text_a = self.rows_and_pdf(app)
        value = app.found['31']['reading']
        self.answers = [f'{value:.4f}']
        app.tree.selection = lambda: ['31']
        app.mo_button_clicked()
        self.assertTrue(app.found['31']['overridden'])
        self.assertEqual(app.found['31']['reading'], round(value, 4))
        # same numbers on both sides: put the automatic value back through the same record path and compare with the override of the same value
        rows_b, text_b = self.rows_and_pdf(app)
        app2 = self.app
        app2.found['31'] = dict(app2.found['31'])
        for k in ('overridden', 'auto_reading'):
            app2.found['31'].pop(k)
        rows_c, text_c = self.rows_and_pdf(app2)
        self.assertEqual(rows_b, rows_c)
        self.assertEqual(text_b, text_c)
        self.assertIn('Calibration Data', text_b)
        self.assertIn('190', text_b)
        self.assertNotIn('override', text_b.lower())
        self.assertNotIn('manual', text_b.lower())
        self.assertNotIn('typed', text_b.lower())
        self.assertEqual(len(rows_a), len(rows_b))

    def test_row_data_ignores_the_override_fields(self):
        app = self.build()
        self.run_points(31)
        rec = app.found['31']
        row_before = app.certificate_rows()
        rec['overridden'] = True
        rec['auto_reading'] = 1.234
        self.assertEqual(app.certificate_rows(), row_before)

    def test_the_own_standard_flag_is_kept_for_an_overridden_point(self):
        app = self.build()
        own = next(p for p in E.POINTS if app.is_manual(p))
        self.answers = [f'{own["nominal"]}']
        app.tree.selection = lambda: [str(own['id'])]
        app.mo_button_clicked()
        self.assertTrue(app.found[str(own['id'])]['manual'])
        self.assertEqual(app.certificate_rows()[0]['Uncertainty'], '')


class NotConnected(Base):
    def test_idle_not_connected_appends_one_line_to_the_shared_log_and_never_a_password(self):
        app = self.build()
        app.io = None
        self.answers = ['1']
        app.tree.selection = lambda: ['1']
        with mock.patch('drivers.CommandLog.append_default') as wrote:
            app.mo_button_clicked()
        wrote.assert_called_once()
        self.assertTrue(app.mo_events[0].startswith('MANUAL OVERRIDE point 1: auto reading none (point not measured), entered 1 '))
        self.assertEqual(app.found['1']['result'], 'PASS')
        self.assertNotIn('password', ' '.join(app.mo_events).lower())


class Demo(Base):
    def test_demo_override_is_synthetic_and_writes_no_log_file(self):
        app = self.build(demo=True)
        self.assertIsNone(app.io)
        app.execute([point(31)])
        self.assertTrue(self.h.pump(30))
        self.assertTrue(app.found['31']['synthetic'])
        self.answers = ['-190.0100']
        app.tree.selection = lambda: ['31']
        with mock.patch('drivers.CommandLog.append_default') as wrote:
            app.mo_button_clicked()
        wrote.assert_not_called()
        rec = app.found['31']
        self.assertEqual((rec['reading'], rec['result'], rec['synthetic']), (-190.01, 'PASS', True))
        self.assertTrue(app.any_synthetic())
        self.assertTrue(app.mo_events[0].startswith('MANUAL OVERRIDE point 31: auto reading '))
        self.assertTrue(app.mo_events[0].endswith('[As Found, demo]'))


class OnlyThe8808A(unittest.TestCase):
    def test_default_is_off_and_only_the_8808a_app_and_the_datasheet_runtime_turn_it_on(self):
        self.assertIs(MO.ManualOverrideMixin.MANUAL_OVERRIDE, False)
        self.assertIs(E.App.MANUAL_OVERRIDE, True)
        hits = sorted(str(p.relative_to(ROOT)) for p in list(ROOT.glob('*.py')) + list((ROOT / 'Procedures').glob('*.py'))
                      if re.search(r'^\s*MANUAL_OVERRIDE\s*=\s*True', p.read_text(encoding='utf-8'), re.M))
        self.assertEqual(hits, ['dsb_override.py', 'dsb_runtime.py', 'fluke8808a_verification.py'], 'the 8808A and the user-built datasheet runtime (dsb_*) only')

    def test_an_app_without_the_flag_adds_no_button_and_no_menu_entry(self):
        class Plain(MO.ManualOverrideMixin):
            pass
        shell = mock.Mock()
        self.assertIsNone(Plain().mo_add_button(shell))
        shell.add_action.assert_not_called()
        self.assertEqual(Plain().tree_menu_extras('1'), [])

    def test_the_menu_hook_is_inert_for_an_app_without_extras(self):
        src = (ROOT / 'procmods_point_ui.py').read_text(encoding='utf-8')
        self.assertIn("getattr(app, 'tree_menu_extras', None)", src)


class Wiring(Base):
    def test_the_button_is_added_between_rerun_and_stop(self):
        E.configure()
        shell = mock.MagicMock()
        with mock.patch.object(E.ui_shell, 'Shell', return_value=shell):
            app = E.App(self.h.root, '8808A', demo=True)
        texts = [c.args[0] for c in shell.add_action.call_args_list]
        self.assertLess(texts.index('Rerun Selected'), texts.index('Enter reading manually'))
        self.assertLess(texts.index('Enter reading manually'), texts.index('\u25a0  Stop'))
        self.assertIsNotNone(app.btn_manual)


if __name__ == '__main__':
    unittest.main()
