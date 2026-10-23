"""Fluke 8808A: (1) the hook-up wording for the open-input current points on the 2 A and 10 A ranges, (2) the reset to defaults runs once per session.

(1) Users Manual p. 3-14 (Automatic Input Terminal Detection, read from the rendered page): with a lead only in the mA jack only the 200 uA to 200 mA ranges
    are selectable, the 2 A and 10 A ranges need a test lead in the 10 A jack. Only the wording (and when the prompt is shown again) changed.
(2) AppResetMixin.RESET_ONCE_PER_SESSION (default False = every Run resets) is True for the 8808A App only: the first Run resets, later Runs log
    'reset skipped: already reset this session' and do the safe parts (calibrator STANDBY confirmed, both instruments answer, REMS / FORMAT 1 /
    TRIGGER 1 / RATE S guaranteed, error status read once). A failed reset, a reconnect and a settings change make the next Run reset again.
Simulated bench only (the tkinter stub): never run on hardware or on a screen.
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402  (installs the tkinter stub)

import reset_startup  # noqa: E402
import fluke8808a_verification as E  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.fluke_8808a import Fluke8808A  # noqa: E402
from drivers.simulated import SimBench  # noqa: E402
from drivers.simulated_8808a import make_8808a_bench  # noqa: E402

OLD_OPEN_TEXT = 'Leave the current inputs (mA and 10 A terminals) OPEN with nothing connected. The calibrator stays in STANDBY.'


def zero_open():
    return [p for p in E.POINTS if p['group'] == 'ZERO_OPEN']


class HookupWording(unittest.TestCase):
    def setUp(self):
        self.h = H.EngineHarness().start(E)
        self.addCleanup(self.h.stop)
        E.configure()
        self.app = E.App(self.h.root, '8808A', demo=True)

    def test_the_six_open_points_and_their_ranges(self):
        self.assertEqual([(p['id'], p['range']) for p in zero_open()], [(16, 0.0002), (17, 0.002), (18, 0.02), (19, 0.2), (20, 2.0), (21, 10.0)])

    def test_ranges_up_to_200_mA_keep_the_existing_text_word_for_word(self):
        for p in zero_open()[:4]:
            self.assertEqual(self.app.setup_text(p), OLD_OPEN_TEXT, p['description'])
            self.assertFalse(E.needs_10a_lead(p))

    def test_2_A_and_10_A_say_a_lead_in_the_10_A_terminal_with_its_free_end_open_and_cite_the_page(self):
        for p in zero_open()[4:]:
            text = self.app.setup_text(p)
            self.assertTrue(E.needs_10a_lead(p), p['description'])
            self.assertIn('Insert a test lead into the 10 A terminal', text)
            self.assertIn('free end OPEN', text)
            self.assertIn('nothing connected to the other end', text)
            self.assertIn('only allows the 2 A and 10 A ranges when a test lead is in the 10 A jack', text)
            self.assertIn('Users Manual p. 3-14', text)
            self.assertIn('Automatic Input Terminal Detection', text)
            self.assertIn('The calibrator stays in STANDBY.', text)
            self.assertNotIn('Leave the current inputs', text)

    def test_the_calibrator_choice_does_not_change_the_wording(self):
        want = [self.app.setup_text(p) for p in zero_open()]
        self.app.cal_model.set('Fluke 5560A')
        self.assertEqual([self.app.setup_text(p) for p in zero_open()], want)

    def test_no_other_point_needs_the_lead_and_no_other_wording_changed(self):
        self.assertEqual([p['id'] for p in E.POINTS if E.needs_10a_lead(p)], [20, 21])
        for p in E.POINTS:                                   # the AC current points are sourced by the calibrator: their text is the existing I2A / I10A text
            if p['group'] != 'ZERO_OPEN':
                self.assertNotIn('free end', self.app.setup_text(p), p['description'])
        self.assertIn('4-wire short', self.app.setup_text(next(p for p in E.POINTS if p['group'] == 'ZERO_SHORT')))

    def test_the_point_detail_shows_the_per_point_wording(self):
        self.app.tree.selection = lambda: ['20']
        self.app.on_select()
        self.assertIn('Insert a test lead into the 10 A terminal', self.app.detail.get())
        self.app.tree.selection = lambda: ['19']
        self.app.on_select()
        self.assertIn(OLD_OPEN_TEXT, self.app.detail.get())

    def test_prompt_key_splits_the_open_group_only_at_2_A(self):
        keys = [E.prompt_key(p) for p in zero_open()]
        self.assertEqual(keys, ['ZERO_OPEN'] * 4 + ['ZERO_OPEN_LEAD'] * 2)
        self.assertEqual(E.prompt_key(next(p for p in E.POINTS if p['group'] == 'VOLT')), 'VOLT')


class Bench(unittest.TestCase):
    """The real App on the simulated bench (as tests/test_beta_8808a.py), Run clicked more than once."""

    def setUp(self):
        self.h = H.EngineHarness().start(E)
        self.addCleanup(self.h.stop)
        p = mock.patch('time.sleep', side_effect=lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.prompts = []

    def make_io(self):
        bench, ct, dt = make_8808a_bench('5522A', True)
        io = E.IO('sim', 'sim', 'Fluke 5522A', 9600, transports=(dt, ct), mods=self.app.pm_state)
        io.is_manual = self.app.is_manual
        return io, bench, dt

    def build(self):
        E.configure()
        app = self.app = E.App(self.h.root, '8808A', demo=False)
        self.h.app = app
        app.asset.set('A-8808'); app.serial.set('SN'); app.warm_confirmed = True
        app.io, self.bench, self.dt = self.make_io()
        self.h.on_confirm = lambda title, heading, steps, facts: self.prompts.append((title, heading, [s if isinstance(s, str) else ' '.join(s) for s in steps])) or True
        st = app.pm_state
        st.store, st.devmode = self.h.env.store, self.h.env.dm
        return app

    def points(self, *ids):
        return [E.POINTS[i - 1] for i in ids]

    def click_run(self, *ids):
        n = len(self.h.dialogs)
        self.app.execute(self.points(*ids))
        self.assertTrue(self.h.pump(60), 'the run did not finish')
        return self.h.dialogs[n:]

    def log(self):
        out = []
        for line in self.app.io.log.lines():
            parts = line.split(None, 3)
            out.append((parts[1], parts[2], parts[3] if len(parts) > 3 else ''))
        return out

    def statuses(self):
        return [str(c.args[0]) for c in self.app.status.set.call_args_list]

    def sent(self, who):
        return [t for w, d, t in self.log() if w == who and d == '>>']

    def resets(self):
        return sum(1 for _w, d, t in self.log() if d == '>>' and t == '*RST')

    def errors(self, dialogs):
        return [d for d in dialogs if d[0] == 'box' and d[1] == 'showerror']

    # ---- hook-up prompt per point
    def test_the_zero_open_run_prompts_again_before_the_2_A_point_with_the_lead_wording(self):
        self.build()
        self.click_run(16, 17, 18, 19, 20, 21)
        zero = [(h, s) for t, h, s in self.prompts if t.startswith('Zero offset')]
        self.assertEqual(len(zero), 2)
        self.assertEqual(zero[0][1], ['Set up the input ' + OLD_OPEN_TEXT])
        self.assertIn('Insert a test lead into the 10 A terminal', zero[1][1][0])
        self.assertEqual(self.app.found['20']['result'], 'PASS')

    def test_a_single_2_A_point_gets_the_lead_wording_in_its_one_prompt(self):
        self.build()
        self.click_run(20)
        zero = [s for t, _h, s in self.prompts if t.startswith('Zero offset')]
        self.assertEqual(len(zero), 1)
        self.assertIn('free end OPEN', zero[0][0])

    def test_going_back_from_2_A_to_200_mA_prompts_with_the_old_text(self):
        self.build()
        self.click_run(20, 19)
        zero = [s[0] for t, _h, s in self.prompts if t.startswith('Zero offset')]
        self.assertEqual(len(zero), 2)
        self.assertIn('free end OPEN', zero[0])
        self.assertEqual(zero[1], 'Set up the input ' + OLD_OPEN_TEXT)

    # ---- high-voltage confirmation once per hook-up group (owner request)
    @staticmethod
    def hv(dialogs):
        return [d for d in dialogs if d[0] == 'box' and d[1] == 'askyesno' and d[2] == 'HIGH VOLTAGE']

    def test_consecutive_high_voltage_points_ask_once(self):
        self.build()
        d = self.click_run(30, 31, 32, 33, 53, 54)               # 190 V and 1000 V dc, 190 V ac: all on the same wiring
        self.assertEqual(len(self.hv(d)), 1)
        self.assertIn('This point puts 190 V on the meter input', self.hv(d)[0][3])           # the text is unchanged
        self.assertEqual({self.app.found[str(i)]['result'] for i in (30, 31, 32, 33, 53, 54)}, {'PASS'})
        self.assertEqual(self.sent('5522A')[-1], 'STBY')                                       # every point still ends in standby
        cal = self.sent('5522A')
        for a, b in zip(cal, cal[1:]):
            self.assertFalse(a == 'OPER' and b == 'OPER')

    def test_a_different_hook_up_group_asks_again(self):
        self.build()
        d = self.click_run(30, 1, 31)                              # high voltage, 4-wire short (zero offset), high voltage again
        self.assertEqual(len(self.hv(d)), 2)

    def test_stop_then_run_again_asks_again(self):
        self.build()
        self.assertEqual(len(self.hv(self.click_run(30, 31))), 1)
        self.assertEqual(len(self.hv(self.click_run(32))), 1)

    def test_declining_stops_before_the_output_and_the_next_run_asks_again(self):
        app = self.build()
        with mock.patch.object(self.h, '_box', side_effect=lambda n, a: False if a and a[0] == 'HIGH VOLTAGE' else True):
            self.click_run(30, 31)
        self.assertNotIn('30', app.found)
        self.assertNotIn('OPER', self.sent('5522A'))
        self.assertEqual(len(self.hv(self.click_run(30))), 1)

    def test_full_run_asks_four_times_instead_of_twelve(self):
        self.build()
        d = self.click_run(*[p['id'] for p in E.POINTS])
        self.assertEqual(len(self.hv(d)), 4)          # was 12: the VOLT group (9 points: 4 dc, 5 ac) once, then each of the three 750 V ac points on the operator's own standard
        self.assertEqual(len([1 for _t, h, _s in self.prompts if 'Point' in h and 'standard' in _t.lower()]), 5)

    # ---- reset once
    def test_only_the_8808a_app_and_the_datasheet_runtime_opt_in(self):
        self.assertIs(reset_startup.AppResetMixin.RESET_ONCE_PER_SESSION, False)
        self.assertIs(E.App.RESET_ONCE_PER_SESSION, True)
        hits = [str(p.relative_to(ROOT)) for p in list(ROOT.glob('*.py')) + list((ROOT / 'Procedures').glob('*.py'))
                if re.search(r'^\s*RESET_ONCE_PER_SESSION\s*=\s*True', p.read_text(encoding='utf-8'), re.M)]
        self.assertEqual(sorted(hits), ['dsb_runtime.py', 'fluke8808a_verification.py'], 'the 8808A and, for rule 10, the user-built datasheet runtime only')

    def test_first_run_resets_second_run_skips_the_reset_and_runs(self):
        self.build()
        d1 = self.click_run(1, 2)
        self.assertEqual(self.resets(), 2)                                   # 5522A and 8808A
        self.assertEqual(len([d for d in d1 if d[0] == 'box' and d[1] == 'askokcancel']), 1)    # the unit-under-test notice
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t.startswith('Instruments reset to default settings at start')), 1)
        before = len(self.log())
        d2 = self.click_run(3, 4)
        self.assertEqual(self.errors(d2), [])
        self.assertEqual(self.resets(), 2)                                   # no second *RST
        self.assertEqual([d for d in d2 if d[0] == 'box' and d[1] == 'askokcancel'], [])          # nothing is erased, so nothing to confirm
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t == 'reset skipped: already reset this session'), 1)
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t.startswith('Instruments reset to default settings at start')), 1)
        self.assertEqual({self.app.found[k]['result'] for k in ('1', '2', '3', '4')}, {'PASS'})
        self.assertTrue(any(x.startswith('Running 4/105') for x in self.statuses()))
        self.assertTrue(any(x.startswith('Reset skipped: the instruments were already reset this session') for x in self.statuses()))

    def test_the_skip_does_the_safe_parts_before_the_first_point_and_no_defaults(self):
        self.build()
        self.click_run(1)
        start = len(self.log())
        self.click_run(2)
        lines = self.log()[start:]
        cal = [t for w, d, t in lines if w == '5522A' and d == '>>']
        dmm = [t for w, d, t in lines if w == '8808A' and d == '>>']
        skip = next(i for i, (_w, _d, t) in enumerate(lines) if t == 'reset skipped: already reset this session')
        first_point = next(i for i, (w, d, t) in enumerate(lines) if w == '8808A' and d == '>>' and t == 'VDC')
        self.assertLess(skip, first_point)
        self.assertEqual(cal[:3], ['STBY', 'OPER?', '*IDN?'])                 # standby, confirmed, the calibrator still answers
        self.assertNotIn('*RST', cal + dmm)
        self.assertNotIn('*CLS', cal + dmm[:dmm.index('VDC')])
        pre = dmm[:dmm.index('VDC')]
        self.assertEqual(pre, ['*IDN?'] * 0 + pre)                              # (shape below)
        self.assertEqual(pre[0], 'REMS')
        self.assertIn('*IDN?', pre)
        self.assertIn('*ESR?', pre)
        self.assertEqual([t for t in pre if t in ('FORMAT 1', 'TRIGGER 1', 'RATE S')], [])   # all three already right: read, not written
        self.assertTrue(all(t != 'OPER' for t in cal[:cal.index('OUT 0V,0Hz')] if 'OUT 0V,0Hz' in cal) if 'OUT 0V,0Hz' in cal else True)

    def test_the_skip_sets_again_what_the_reset_set_if_it_was_lost(self):
        self.build()
        self.click_run(1)
        self.dt.remote, self.dt.format, self.dt.trigger, self.dt.rate = False, 2, 2, 'M'     # as if the front panel had been touched between the Runs
        start = len(self.log())
        d = self.click_run(2)
        self.assertEqual(self.errors(d), [])
        pre = [t for w, dd, t in self.log()[start:] if w == '8808A' and dd == '>>']
        pre = pre[:pre.index('VDC')]
        for want in ('REMS', 'FORMAT 1', 'TRIGGER 1', 'RATE S'):
            self.assertEqual(pre.count(want), 1, want)                         # each written exactly once, never retried
        self.assertEqual((self.dt.remote, self.dt.format, self.dt.trigger, self.dt.rate), (True, 1, 1, 'S'))
        self.assertEqual(self.resets(), 2)

    def test_a_failed_reset_leaves_the_next_run_to_reset_again(self):
        self.build()
        self.bench.fail_next = '*RST'                                          # the calibrator's *RST times out
        d1 = self.click_run(1)
        self.assertEqual(len(self.errors(d1)), 1)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.found, {})
        self.assertIsNone(self.app._reset_done_for)
        self.assertEqual(self.resets(), 1)
        d2 = self.click_run(1)
        self.assertEqual(self.errors(d2), [])
        self.assertEqual(self.resets(), 3)                                     # 1 failed + both instruments on the second Run
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t == 'reset skipped: already reset this session'), 0)
        self.click_run(2)                                                      # and now the session counts as reset
        self.assertEqual(self.resets(), 3)
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t == 'reset skipped: already reset this session'), 1)

    def test_a_reconnect_resets_again(self):
        app = self.build()
        self.click_run(1)
        self.assertEqual(self.resets(), 2)
        app.disconnect()
        self.assertIsNone(app.io)
        app.io, self.bench, self.dt = self.make_io()                           # test_connections() builds a new IO
        self.click_run(2)
        self.assertEqual(self.resets(), 2)                                     # a new log: both instruments of the new connection were reset
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t == 'reset skipped: already reset this session'), 0)
        self.click_run(3)
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t == 'reset skipped: already reset this session'), 1)

    def test_changing_the_calibrator_or_interface_in_the_settings_resets_again(self):
        for var, value in (('cal_model', 'Fluke 5560A'), ('cal_addr', 'COM12'), ('cal_baud', '19200'), ('dmm_addr', 'COM3'), ('dmm_baud', '19200'),
                           ('dmm_format', '7 data bits, even parity')):
            with self.subTest(var):
                app = self.build()
                self.click_run(1)
                self.assertTrue(app.reset_done_this_session())
                getattr(app, var).set(value)
                self.assertFalse(app.reset_done_this_session())
                app.cal_model.set('Fluke 5522A')

    def test_a_failed_skip_check_stops_before_any_point_and_the_next_run_resets(self):
        app = self.build()
        self.click_run(1)
        with mock.patch.object(Fluke8808A, 'ensure_run_state', side_effect=InstrumentError('FORMAT 1 was not accepted')):
            d = self.click_run(2)
        self.assertEqual(len(self.errors(d)), 1)
        self.assertIn('check before the run failed', self.errors(d)[0][3])
        self.assertTrue(any(x.startswith('Connection / status check failed - run not started') for x in self.statuses()))
        self.assertFalse(app.busy)
        self.assertNotIn('2', app.found)
        self.assertEqual(self.sent('5522A')[-3:], ['STBY', 'OPER?', '*IDN?'])    # the calibrator was put in standby (confirmed) first
        self.click_run(2)
        self.assertEqual(self.resets(), 4)                                     # the second Run after the failed check reset again

    def test_a_calibrator_that_does_not_confirm_standby_stops_the_run(self):
        app = self.build()
        self.click_run(1)
        with mock.patch.object(type(app.io.cal), 'ask', side_effect=lambda key, **v: '1' if key == 'oper.query' else '0'):
            d = self.click_run(2)
        self.assertEqual(len(self.errors(d)), 1)
        self.assertNotIn('2', app.found)

    def test_every_run_resets_when_the_option_is_off(self):
        self.build()
        with mock.patch.object(E.App, 'RESET_ONCE_PER_SESSION', False):
            self.click_run(1)
            self.click_run(2)
        self.assertEqual(self.resets(), 4)
        self.assertEqual(sum(1 for _w, _d, t in self.log() if t == 'reset skipped: already reset this session'), 0)

    def test_demo_runs_send_nothing_and_never_skip(self):
        E.configure()
        app = E.App(self.h.root, '8808A', demo=True)
        app.asset.set('D1')
        app.execute(app.active_points()[:2])
        self.h.pump(30)
        self.assertIsNone(app.io)
        self.assertFalse(app.reset_done_this_session())


class DriverGuarantees(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch('time.sleep', side_effect=lambda s: None)
        self.p.start()
        self.addCleanup(self.p.stop)
        _b, _ct, self.t = make_8808a_bench('5522A', False)
        self.d = Fluke8808A(self.t, label='8808A')
        self.d.connect()

    def writes(self, fn):
        n = len(self.d.log.lines())
        out = fn()
        return out, [l.split(None, 3)[3] for l in self.d.log.lines()[n:] if l.split(None, 3)[2] == '>>']

    def test_after_connect_the_simulated_format_is_2_so_it_is_set_once_and_read_back(self):
        _s, sent = self.writes(self.d.ensure_run_state)
        self.assertEqual(sent, ['REMS', 'FORMAT?', 'FORMAT 1', 'FORMAT?', 'TRIGGER?', 'RATE?'])
        self.assertEqual(self.t.format, 1)

    def test_nothing_is_written_when_the_meter_is_already_as_needed(self):
        self.d.ensure_run_state()
        _s, sent = self.writes(self.d.ensure_run_state)
        self.assertEqual(sent, ['REMS', 'FORMAT?', 'TRIGGER?', 'RATE?'])

    def test_a_setting_the_meter_refuses_raises_after_one_write(self):
        self.t.format = 2
        with mock.patch.object(type(self.t), 'format', new=2, create=True):
            pass
        orig = self.d._set_check
        calls = []

        def refuse(key, query_key, expected, what, **vals):
            calls.append(key)
            self.d.send(key, **vals)
            raise InstrumentError('refused')
        self.d._set_check = refuse
        with self.assertRaises(InstrumentError):
            self.d.ensure_run_state()
        self.assertEqual(calls, ['format.set'])                                # one attempt, no retry, nothing after it

    def test_session_check_reads_esr_once_and_logs_error_bits_without_stopping(self):
        self.t.esr |= 0x10
        n = len(self.d.log.lines())
        flags = self.d.session_check()
        sent = [l.split(None, 3)[3] for l in self.d.log.lines()[n:] if l.split(None, 3)[2] == '>>']
        self.assertEqual(sent, ['*IDN?', '*ESR?'])
        self.assertEqual(flags, ['execution error'])
        self.assertTrue(any('event status before the run: execution error' in l for l in self.d.log.lines()[n:]))

    def test_session_check_refuses_another_model(self):
        self.d.IDN_MATCH = ('9999',)
        with self.assertRaises(InstrumentError):
            self.d.session_check()


class MixinDefault(unittest.TestCase):
    """The shared mixin with the option off behaves as before: every call resets."""

    def test_default_resets_on_every_call(self):
        calls = []

        class Log:
            def add(self, *a): calls.append(a)

        class Var:
            def set(self, v): self.v = v

        class Root:
            def after(self, ms, fn): fn()

        class App(reset_startup.AppResetMixin):
            demo = False; busy = False; io = object()
            root = Root(); status = Var()
            def reset_roles(self): return [], []
            def reset_log(self): return Log()
            def reset_run(self): calls.append('reset')

        import threading
        app = App()
        done = []
        for _ in range(2):
            ev = threading.Event()
            app.reset_then(lambda: (done.append(1), ev.set()))
            self.assertTrue(ev.wait(5))
        self.assertEqual([c for c in calls if c == 'reset'], ['reset', 'reset'])
        self.assertFalse(app.reset_done_this_session())

    def test_opt_in_without_reset_skip_run_is_an_error_not_a_silent_skip(self):
        class App(reset_startup.AppResetMixin):
            RESET_ONCE_PER_SESSION = True
        with self.assertRaises(NotImplementedError):
            App().reset_skip_run()


if __name__ == '__main__':
    unittest.main()
