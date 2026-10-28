"""B&K Precision 5491B performance verification: the spec, the driver, the simulator and the engine on the simulated bench.

* Spec: 55 points from the lab datasheet (MDD); every limit reproduces from the MDD's own formula (the builder refuses to run otherwise); the six points where the datasheet and the
  manual's Chapter 7 tables disagree are pinned, with both limit sets; the JSON on disk is what the builder makes now.
* Driver: every command has a manual reference; the unverified ones are exactly the listed ones; reset order; set / read back / compare; no write is retried; the error queue;
  echo tolerance; no calibration command exists.
* Engine (the real App on the simulated bench, tests/live_editor_harness.py): all 55 points, DC outputs carry ,0Hz, outputs go to standby, the reset comes first, points the selected
  calibrator cannot make use the technician's standard, demo mode records only synthetic, marked data.
Nothing here has run on a real meter or been looked at on a screen.
"""
import importlib.util
import json
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

import cmdreg  # noqa: E402
import drivers  # noqa: E402
import bk5491b_verification as E  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.bk_5491b import BK5491B, COMMANDS, range_value  # noqa: E402
from drivers.simulated_5491b import Sim5491BTransport, make_5491b_bench  # noqa: E402

SPEC = json.loads((ROOT / 'specs' / 'bk_5491b_pv.json').read_text(encoding='utf-8'))
UNVERIFIED = ['func.query', 'range.query.ACI', 'range.query.ACV', 'range.query.DCI', 'range.query.DCV', 'range.query.OHM2', 'thr.query', 'trig.query']


def builder():
    spec = importlib.util.spec_from_file_location('build_bk_5491b_spec', ROOT / 'specs' / 'build_bk_5491b_spec.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def points():
    return [p for s in SPEC['sections'] for p in s['points']]


def by_ref(ref):
    return next(p for p in points() if p['ref'] == ref)


class SpecTests(unittest.TestCase):
    def test_counts_and_sections(self):
        self.assertEqual(len(points()), 55)
        got = [(s['id'], len(s['points'])) for s in SPEC['sections']]
        self.assertEqual(got, [('DCV', 5), ('ACV', 16), ('FREQ', 4), ('OHM2', 6), ('CONT', 1), ('DCI_MA', 3), ('ACI_MA', 11), ('DCI_A', 3), ('ACI_A', 6)])
        self.assertEqual({p['group'] for p in points()}, {'VOLT', 'OHM2', 'IMA', 'I20A'})
        self.assertTrue(all(p['source'] == 'calibrator' for p in points()))

    def test_json_is_what_the_builder_makes(self):
        self.assertEqual(json.loads(json.dumps(builder().build_spec())), SPEC)

    def test_every_mdd_limit_is_the_mdd_formula_and_the_nominal_is_inside_both_sets(self):
        for p in points():
            for period in ('mdd', 'mfr'):
                lim = p['limits'][period]
                self.assertLess(lim['low'], lim['high'], p['ref'])
                self.assertTrue(lim['low'] <= p['nominal'] <= lim['high'], (p['ref'], period))

    def test_the_two_limit_sets_differ_only_at_the_six_listed_points(self):
        diff = sorted(p['ref'] for p in points() if p['limits']['mdd'] != p['limits']['mfr'])
        self.assertEqual(diff, ['MDD #2', 'MDD #21', 'MDD #3', 'MDD #4', 'MDD #5', 'MDD #8'])
        self.assertEqual(diff, sorted(p['ref'] for p in points() if p.get('flags')))

    def test_pinned_limits_where_the_datasheet_and_the_manual_disagree(self):
        want = {
            'MDD #2': ((4.895, 4.905), (4.8986, 4.9014)),          # 5 V DC: 0.08 % of range (MDD) against 0.008 % (manual p. 68)
            'MDD #5': ((899.0, 901.0), (899.7, 900.3)),            # 1000 V DC
            'MDD #8': ((0.4868, 0.4932), (0.48725, 0.49275)),      # 500 mV AC at 20 kHz: 0.15 % of range (MDD) against 0.06 % (manual p. 69)
            'MDD #21': ((696.3, 703.7), (696.2, 703.8)),           # 700 V AC: the 750 V range, not the 500 V range
        }
        for ref, (mdd, mfr) in want.items():
            lim = by_ref(ref)['limits']
            self.assertEqual((lim['mdd']['low'], lim['mdd']['high']), mdd, ref)
            self.assertEqual((lim['mfr']['low'], lim['mfr']['high']), mfr, ref)
        self.assertEqual(by_ref('MDD #21')['range'], 750.0)

    def test_limits_printed_in_the_mdd_are_unchanged(self):
        self.assertEqual(by_ref('MDD #1')['limits']['mdd'], {'low': 0.48982, 'high': 0.49018})
        self.assertEqual(by_ref('MDD #28')['limits']['mdd'], {'low': 489.31, 'high': 490.69})          # continuity
        self.assertEqual(by_ref('MDD #28')['function'], 'CONT')
        self.assertEqual(by_ref('MDD #32')['limits']['mdd'], {'low': 899830.0, 'high': 900170.0})
        self.assertEqual(by_ref('MDD #55')['limits']['mdd'], {'low': 18.885, 'high': 19.115})

    def test_frequency_points_carry_the_amplitude_and_the_nominal_in_hz(self):
        for p in points():
            if p['kind'] == 'FREQ':
                self.assertEqual((p['unit'], p['amplitude']), ('Hz', 0.5), p['ref'])
        self.assertEqual([p['nominal'] for p in points() if p['kind'] == 'FREQ'], [9.0, 90.0, 90000.0, 900000.0])

    def test_every_range_exists_on_the_meter(self):
        for p in points():
            self.assertEqual(range_value(p['kind'], p['range']), p['range'], p['ref'])

    def test_loader_refuses_a_bad_spec(self):
        bad = json.loads(json.dumps(SPEC))
        bad['sections'][0]['points'][0]['limits']['mdd']['high'] = bad['sections'][0]['points'][0]['limits']['mdd']['low']
        path = Path(H.tempfile.mkdtemp()) / 'bad.json'
        path.write_text(json.dumps(bad))
        with self.assertRaises(E.SpecError):
            E.load_spec(path)

    def test_judge_is_decimal_and_inclusive(self):
        E.configure()
        p = next(q for q in E.POINTS if q['ref'] == 'MDD #1')
        E.apply_period(E.POINTS, 'mdd')
        self.assertTrue(E.judge(p, 0.49018))
        self.assertTrue(E.judge(p, 0.48982))
        self.assertFalse(E.judge(p, 0.490181))
        self.assertFalse(E.judge(p, 0.489819))


class DriverTests(unittest.TestCase):
    def make(self):
        bench, ct, dt = make_5491b_bench()
        log = drivers.CommandLog()
        d = BK5491B(dt, log, label='5491B')
        return bench, ct, dt, d, log

    @staticmethod
    def logged(log, who='5491B'):
        out = []
        for line in log.lines():
            parts = line.split(None, 3)
            if parts[1] == who and parts[2] == '>>':
                out.append(parts[3])
        return out

    def test_registry_is_clean_and_referenced(self):
        reg = cmdreg.merge_commands(BK5491B)
        self.assertEqual(cmdreg.lint_registry(reg), [])
        for key, cmd in reg.items():
            self.assertTrue(cmd.ref, key)

    def test_unverified_commands_are_exactly_the_listed_ones(self):
        self.assertEqual(sorted(k for k, c in COMMANDS.items() if not c.verified), UNVERIFIED)

    def test_locked_commands(self):
        for key in ('reset', 'err.query'):
            self.assertEqual(COMMANDS[key].risk, 'locked', key)
        self.assertEqual(COMMANDS['reset'].template, '*RST')

    def test_no_calibration_or_adjustment_command_exists(self):
        for key, cmd in COMMANDS.items():
            self.assertNotRegex(cmd.template.upper(), r'CAL|ZERO|ADJ', key)

    def test_serial_settings_are_the_factory_ones(self):
        s = BK5491B.SERIAL
        self.assertEqual((s.baud, s.data_bits, s.parity, s.stop_bits), (9600, 8, 'none', 1))

    def test_connect_identifies_and_sends_nothing_else(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
        self.assertEqual(dt.sent, ['*IDN?'])
        self.assertIn('5491B', d.idn)

    def test_wrong_model_is_refused(self):
        _b, _ct, dt, d, _log = self.make()
        dt.handle = lambda cmd: '2831E Multimeter,Ver1.0' if cmd == '*IDN?' else None
        with mock.patch('time.sleep'), self.assertRaises(InstrumentError):
            d.connect()

    def test_reset_order_and_known_state(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            dt.sent.clear()
            rep = d.reset_to_defaults()
        self.assertTrue(rep.ok, rep.text())
        self.assertEqual(dt.sent, ['*RST', 'SYST:ERR?', 'TRIG:SOUR IMM', 'TRIG:SOUR?'])

    def test_reset_waits_after_the_reset_command_and_paces_commands(self):
        _b, _ct, dt, d, _log = self.make()
        sleeps = []
        with mock.patch('time.sleep', side_effect=sleeps.append):
            d.connect()
            sleeps.clear()
            d.reset_to_defaults()
        self.assertIn(d.RESET_SETTLE_S, sleeps)
        self.assertGreaterEqual(sleeps.count(d.COMMAND_GAP_S), 3)

    def test_configure_point_sends_the_expected_reading_and_reads_everything_back(self):
        _b, _ct, dt, d, _log = self.make()
        p = dict(kind='ACI', range=0.05, nominal=0.049, frequency=2000.0)
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            dt.sent.clear()
            d.configure_point(p)
            d.check_errors('test')
        self.assertEqual(dt.sent, ['FUNC CURR:AC', 'FUNC?', 'CURR:AC:RANG:AUTO OFF', 'CURR:AC:RANG:AUTO?', 'CURR:AC:RANG 0.05', 'CURR:AC:RANG?',
                                   'CURR:AC:NPLC 10', 'CURR:AC:NPLC?', 'TRIG:SOUR IMM', 'TRIG:SOUR?', 'SYST:ERR?'])
        self.assertEqual((dt.func, dt.range_no, dt.nplc), ('ACI', 2, 10.0))

    def test_continuity_and_frequency_have_no_range_or_rate_command(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            dt.sent.clear()
            d.configure_point(dict(kind='OHM2', function='CONT', range=500.0, nominal=490.0))
            self.assertEqual(dt.sent[:2], ['FUNC CONT', 'FUNC?'])
            self.assertFalse(any('RANG' in c or 'NPLC' in c for c in dt.sent))
            dt.sent.clear()
            d.configure_point(dict(kind='FREQ', range=100.0, nominal=90.0, amplitude=0.5))
        self.assertEqual(dt.sent[:4], ['FUNC FREQ', 'FUNC?', 'FREQ:THR:VOLT:RANG 0.5', 'FREQ:THR:VOLT:RANG?'])
        self.assertFalse(any('NPLC' in c for c in dt.sent))

    def test_a_failed_read_back_raises_and_the_write_is_not_repeated(self):
        _b, _ct, dt, d, log = self.make()
        orig = dt.handle
        dt.handle = lambda cmd: None if cmd.upper().startswith('VOLT:DC:RANG ') else orig(cmd)       # the range write is lost (a busy meter ignores characters)
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            mark = len(self.logged(log))
            with self.assertRaisesRegex(InstrumentError, 'range 5 was not accepted'):
                d.configure_point(dict(kind='DCV', range=5.0, nominal=4.9))
        self.assertEqual(self.logged(log)[mark:].count('VOLT:DC:RANG 5'), 1)

    def test_a_write_that_times_out_is_not_retried(self):
        _b, _ct, dt, d, log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            mark = len(self.logged(log))
            dt.bench.fail_next = 'RANG:AUTO'
            with self.assertRaises(Exception):
                d.configure_point(dict(kind='DCV', range=5.0, nominal=4.9))
        sent = self.logged(log)[mark:]
        self.assertEqual(sum('RANG:AUTO' in c for c in sent), 1)
        self.assertFalse(any(c.startswith('VOLT:DC:RANG 5') for c in sent))

    def test_the_error_queue_is_read_once_and_a_message_raises(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.write('NOTACOMMAND')
            with self.assertRaisesRegex(InstrumentError, 'BAD COMMAND'):
                d.check_errors('test')
            d.check_errors('again')                            # the entry was removed by reading it: no error now

    def test_overload_and_unreadable_replies_are_rejected(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.configure_point(dict(kind='DCV', range=0.5, nominal=0.49))
            dt.bench.fluke.update(operate=True, volts=1.0, unit='V', freq=0.0)      # 1 V into the 500 mV range
            with self.assertRaisesRegex(InstrumentError, 'overload'):
                d.read()
            orig = dt.handle
            dt.handle = lambda cmd: 'OVLD' if cmd == 'FETC?' else orig(cmd)
            with self.assertRaisesRegex(InstrumentError, 'unreadable'):
                d.read()

    def test_a_reading_is_the_second_fetch(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.configure_point(dict(kind='DCV', range=5.0, nominal=4.9))
            dt.sent.clear()
            d.read()
        self.assertEqual(dt.sent, ['FETC?', 'FETC?'])

    def test_slow_functions_wait_longer_between_the_two_fetches(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
        sleeps = []
        with mock.patch('time.sleep', side_effect=sleeps.append):
            d.read(dict(kind='FREQ', range=100.0))
            d.read(dict(kind='DCV', range=5.0))
        self.assertIn(d.READ_GAP_SLOW_S, sleeps)
        self.assertIn(d.READ_GAP_S, sleeps)

    def test_echo_of_each_command_on_its_own_line_is_skipped(self):
        _b, _ct, dt, d, log = self.make()
        dt.echo = 'line'
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.configure_point(dict(kind='DCV', range=5.0, nominal=4.9))
            value = d.read()
        self.assertEqual(value, 0.0)
        self.assertGreater(d.echo_seen, 0)
        self.assertTrue(any('[echo of a command, skipped]' in t for _w, _d, t in [(l.split(None, 3) + ['', ''])[1:4] for l in log.lines()]))

    def test_command_text_run_into_the_reply_is_cut_off(self):
        _b, _ct, dt, d, _log = self.make()
        dt.echo = 'run'
        with mock.patch('time.sleep'):
            d.connect()
            self.assertIn('5491B', d.idn)
            self.assertNotIn('*IDN?', d.idn)

    def test_range_values_follow_the_5491b_tables(self):
        self.assertEqual([range_value('DCV', r) for r in (0.5, 5, 50, 500, 1000)], [0.5, 5.0, 50.0, 500.0, 1000.0])
        self.assertEqual([range_value('ACV', r) for r in (0.5, 5, 50, 500, 750)], [0.5, 5.0, 50.0, 500.0, 750.0])
        self.assertEqual([range_value('OHM2', r) for r in (500, 5e3, 50e3, 500e3, 5e6, 50e6)], [500.0, 5e3, 50e3, 500e3, 5e6, 50e6])
        with self.assertRaises(InstrumentError):
            range_value('DCV', 200.0)             # the 2831E range, not a 5491B one


class EngineRunTests(unittest.TestCase):
    """The real App on the simulated bench."""

    def setUp(self):
        self.h = H.EngineHarness().start(E)
        self.addCleanup(self.h.stop)
        p = mock.patch('time.sleep', side_effect=lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def build(self, cal='Fluke 5522A', demo=False, enforce=True):
        E.configure()
        app = self.app = E.App(self.h.root, '5491B', demo=demo)
        self.h.app = app
        app.asset.set('A-5491')
        app.serial.set('SN')
        app.cal_model.set(cal)
        if not demo:
            self.bench, ct, self.dt = make_5491b_bench(E.CALIBRATORS[cal][0], enforce)
            app.io = E.IO('sim', 'sim', cal, 9600, transports=(self.dt, ct), mods=app.pm_state)
            app.io.is_manual = app.is_manual
            self.h.on_confirm = self.operator
        st = app.pm_state
        st.store, st.devmode = self.h.env.store, self.h.env.dm
        return app

    def operator(self, title, heading, steps, facts):
        """The technician: connects the stated standard for a 'Your own standard' prompt, otherwise removes any."""
        if title.startswith('Your own standard'):
            p = E.POINTS[int(re.search(r'Point (\d+)', heading).group(1)) - 1]
            if p['kind'] == 'FREQ':
                self.bench.external = ('V', p['amplitude'], p['nominal'])
            else:
                self.bench.external = ({'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM2': 'OHM'}[p['kind']], p['nominal'], p.get('frequency') or 0.0)
        else:
            self.bench.external = None
        return True

    def run_all(self):
        self.app.execute(self.app.active_points())
        self.assertTrue(self.h.pump(120), 'the run did not finish')
        errors = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'showerror']
        self.assertEqual(errors, [])

    def log_lines(self):
        out = []
        for line in self.app.io.log.lines():
            parts = line.split(None, 3)
            out.append((parts[1], parts[2], parts[3] if len(parts) > 3 else ''))
        return out

    def test_all_55_points_run_and_pass_on_the_5522a(self):
        app = self.build()
        self.run_all()
        self.assertEqual(len(app.found), 55)
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        self.assertFalse(any(r['synthetic'] for r in app.found.values()))
        manual = sorted(p['ref'] for p in E.POINTS if app.found[str(p['id'])]['manual'])
        self.assertEqual(manual, ['MDD #29', 'MDD #32', 'MDD #49'])

    def test_reset_comes_first_for_both_instruments(self):
        self.build()
        self.run_all()
        lines = self.log_lines()
        first_use = next(i for i, (_w, d, t) in enumerate(lines) if d == '>>' and (t.startswith('OUT') or t.startswith('FUNC ')))
        resets = [i for i, (_w, d, t) in enumerate(lines) if d == '>>' and t == '*RST']
        self.assertEqual(len(resets), 2)
        self.assertTrue(all(i < first_use for i in resets))

    def test_dc_outputs_carry_0hz_and_ac_outputs_a_frequency(self):
        self.build()
        self.run_all()
        outs = [t for w, d, t in self.log_lines() if w == '5522A' and d == '>>' and t.startswith('OUT ')]
        dc = [t for t in outs if t.endswith(',0Hz')]
        self.assertEqual(len(dc), 11)                                  # 5 DC volts + 3 mA + 3 A DC current points (resistance has no frequency)
        for t in outs:
            if re.match(r'OUT [-+0-9.eE]+(V|A)$', t):
                self.fail('an output without a frequency: ' + t)

    def test_every_output_goes_to_standby_and_the_run_ends_in_standby(self):
        self.build()
        self.run_all()
        cal = [t for w, d, t in self.log_lines() if w == '5522A' and d == '>>' and t in ('OPER', 'STBY')]
        self.assertEqual(cal.count('OPER'), 52)                        # 55 - 3 manual points
        for a, b in zip(cal, cal[1:]):
            self.assertFalse(a == 'OPER' and b == 'OPER', 'OPER twice without STBY between')
        self.assertEqual(cal[-1], 'STBY')

    def test_the_calibrator_is_not_asked_for_what_it_cannot_make(self):
        self.build()
        self.run_all()
        outs = ' '.join(t for w, d, t in self.log_lines() if w == '5522A' and d == '>>')
        self.assertNotIn('900kHz', outs)
        self.assertNotRegex(outs, r'OUT 0\.5V,9Hz')

    def test_the_5560a_makes_the_9_hz_and_the_19_a_points_and_not_900_khz(self):
        # calibrator_fit, from the 5560A sheet (specs/standards/fluke_5560a_standard.json): 3 Hz up, a 30.2 A range, ac voltage to 500 kHz
        app = self.build(cal='Fluke 5560A', enforce=False)
        refs = sorted(p['ref'] for p in E.POINTS if app.is_manual(p))
        self.assertEqual(refs, ['MDD #32'])
        for ref in refs:
            self.assertIn('5560A', app.manual_reason(next(q for q in E.POINTS if q['ref'] == ref)))
        app.cal_model.set('Fluke 5522A')
        self.assertEqual(sorted(q['ref'] for q in E.POINTS if app.is_manual(q)), ['MDD #29', 'MDD #32', 'MDD #49'])

    def test_the_5560a_run_uses_the_technicians_standard_for_its_one_point(self):
        app = self.build(cal='Fluke 5560A', enforce=False)
        self.run_all()
        sent = [t for w, d, t in self.log_lines() if w == '5560A' and d == '>>']
        self.assertEqual(sent.count('OPER'), 54)                       # 55 - 1 manual point
        self.assertEqual(sent[-1], 'STBY')
        self.assertEqual(len(app.found), 55)

    def test_high_voltage_points_ask_first_and_a_refusal_stops_the_run(self):
        app = self.build()
        self.h.box_answer['askyesno'] = False
        app.warm_confirmed = True
        app.execute([p for p in E.POINTS if p['ref'] == 'MDD #4'])
        self.h.pump(30)
        self.assertTrue(any(d[0] == 'box' and d[2] == 'HIGH VOLTAGE' for d in self.h.dialogs))
        self.assertEqual(app.found, {})
        self.assertNotIn('OPER', [t for w, d, t in self.log_lines() if w == '5522A'])

    def test_the_warm_up_question_is_asked_once(self):
        self.build()
        self.run_all()
        asks = [d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'Warm-up']
        self.assertEqual(len(asks), 1)

    def test_a_hookup_prompt_for_every_wiring_group_and_again_after_a_standard_of_your_own(self):
        self.build()
        self.run_all()
        prompts = [d for d in self.h.dialogs if d[0] == 'confirm' and d[1].startswith('Rewire')]
        self.assertEqual({d[2] for d in prompts}, {'Connect for ' + t for t in E.GROUP_TITLE.values()})
        own = [d for d in self.h.dialogs if d[0] == 'confirm' and d[1].startswith('Your own standard')]
        self.assertEqual(len(own), 3)                                       # 9 Hz, 20 kHz mA, 900 kHz: the 5522A cannot make them
        self.assertEqual(len(prompts), 4 + 1)                               # one per group, one more for the voltage group after the 9 Hz point (the mA group's 20 kHz point is its last)

    def test_the_limit_set_changes_the_limits_and_rejudges(self):
        app = self.build()
        self.run_all()
        app.period.set('Manufacturer specification')
        app.on_period(save=False)
        p = next(q for q in E.POINTS if q['ref'] == 'MDD #2')
        self.assertEqual((p['low'], p['high']), (4.8986, 4.9014))
        app.period.set('Lab datasheet (MDD)')
        app.on_period(save=False)
        self.assertEqual((p['low'], p['high']), (4.895, 4.905))

    def test_a_reading_outside_the_limits_fails(self):
        app = self.build()
        p = E.POINTS[1]
        app._record(p, p['high'] * 1.001 + 1e-3, False)
        self.assertEqual(app.found[str(p['id'])]['result'], 'FAIL')
        app._record(p, p['high'], False)
        self.assertEqual(app.found[str(p['id'])]['result'], 'PASS')

    def test_demo_mode_sends_nothing_and_records_only_marked_synthetic_data(self):
        app = self.build(demo=True)
        app.execute(app.active_points())
        self.h.pump(60)
        self.assertIsNone(app.io)
        self.assertEqual(len(app.found), 55)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertTrue(all(r['result'] == 'PASS' for r in app.found.values()))

    def test_the_real_report_has_uncertainty_for_calibrator_points_and_none_for_manual_ones(self):
        try:
            import reportlab  # noqa: F401
        except Exception:
            self.skipTest('reportlab not installed')
        app = self.build()
        self.run_all()
        rows, pts = app.certificate_rows_and_points()
        by = {p['ref']: r for p, r in zip(pts, rows)}
        self.assertTrue(by['MDD #1']['Uncertainty'])
        self.assertEqual(by['MDD #32']['Uncertainty'], '')

    def test_report_file_name_is_asset_and_date(self):
        import ui_theme as ui
        self.assertRegex(ui.report_filename('A-5491'), r'^A-5491-\d{2}-\d{2}-\d{4}\.pdf$')

    def test_checkpoint_round_trip_keeps_the_manual_flag(self):
        app = self.build()
        p = next(q for q in E.POINTS if q['ref'] == 'MDD #32')
        app._record(p, 900000.0, False, manual=True)
        data = json.loads(json.dumps(app.save_fields()))
        self.assertTrue(data['results'][str(p['id'])]['manual'])


class SourceGuards(unittest.TestCase):
    def test_no_write_is_retried_and_no_secret_is_logged(self):
        for rel in ('bk5491b_verification.py', 'drivers/bk_5491b.py'):
            src = (ROOT / rel).read_text(encoding='utf-8')
            self.assertNotIn("query_retry('fetch", src)
            self.assertNotIn("query_retry('err.query", src)
        self.assertNotIn('password', (ROOT / 'drivers/bk_5491b.py').read_text(encoding='utf-8').lower())

    def test_launcher_and_sidecar(self):
        launcher = (ROOT / 'Procedures' / 'BK_5491B_Verification.py').read_text(encoding='utf-8')
        self.assertIn('bk5491b_verification.main()', launcher)
        side = json.loads((ROOT / 'Procedures' / 'BK_5491B_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((side['id'], side['model'], side['launcher']), ('BK_5491B_Verification', '5491B', 'Procedures/BK_5491B_Verification.py'))
        for rel in side['fingerprint']['code'] + side['fingerprint']['spec'] + side['own_files']:
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_the_driver_is_exported(self):
        self.assertIs(drivers.BK5491B, BK5491B)


class RawLineReading(unittest.TestCase):
    """Owner 2026-10-28: over VISA the first run timed out ('read failed: VI_ERROR_TMO') although the log showed the echoes and the reply. Lines now end at CR or LF, and a
    line with no end character is returned after a short silence."""

    class _Res:
        def __init__(self, data):
            self.d, self.timeout, self.echo = bytearray(data), 20000, bytearray()

        def write_raw(self, b):
            self.echo += b                                          # the meter echoes each character it receives, the end character too

        def read_bytes(self, n):
            if self.echo:
                b = bytes(self.echo[:n])
                del self.echo[:n]
                return b
            if not self.d:
                raise OSError('VI_ERROR_TMO')
            b = bytes(self.d[:n])
            del self.d[:n]
            return b

    class _T:
        timeout = 20.0

        def __init__(self, data):
            self._res = RawLineReading._Res(data)

        def write(self, text):
            pass

        def clear(self):
            pass

    def ident(self, data):
        from drivers import CommandLog
        from drivers.bk_5491b import BK5491B
        d = BK5491B(self._T(data), CommandLog(), label='t')
        d.COMMAND_GAP_S, d.IDLE_END_S = 0, 0.01
        return d.identify(), d.t._res.timeout

    def test_crlf_cr_only_and_unterminated_replies_all_identify(self):
        for data in (b'*IDN?\r\n*IDN?\r\n5491B  Multimeter,Ver1.4.14\r\n', b'*IDN?\n*IDN?\r5491B  Multimeter,Ver1.4.14\r', b'*IDN?\r\n*IDN?\r\n5491B  Multimeter,Ver1.4.14'):
            reply, timeout = self.ident(data)
            self.assertEqual(reply, '5491B  Multimeter,Ver1.4.14')
            self.assertEqual(timeout, 20000)                                    # the full timeout is restored

    def test_silence_raises_the_transport_error_with_the_wait(self):
        from drivers.base import InstrumentError
        with self.assertRaises(InstrumentError) as cm:
            self.ident(b'*IDN?\r\n')
        self.assertIn('no byte at all', str(cm.exception))
        self.assertIn("['*IDN?']", str(cm.exception))                            # the lines that did arrive are named


class CharacterHandshake(unittest.TestCase):
    """Owner 2026-10-28, real meter: sending '*IDN?' in one piece got only the echo and no reply. Manual 5.2.4 item 3: the next character is sent only after the last was echoed."""

    class _Res:
        def __init__(self, drop=None, silent=False):
            self.out, self.sent, self.timeout, self.drop, self.silent = bytearray(), [], 20000, drop, silent

        def write_raw(self, b):
            self.sent.append(b)
            if self.silent:
                return
            if b == b'\n':
                self.out += b'\n*IDN?\r\n5491B  Multimeter,Ver1\r\n'      # the end character's echo, the menu echo, the reply
                return
            if self.drop and b == self.drop:
                self.drop = None                                    # this copy of the character is lost: no echo
                return
            self.out += b

        def read_bytes(self, n):
            if not self.out:
                raise OSError('VI_ERROR_TMO')
            b = bytes(self.out[:n])
            del self.out[:n]
            return b

    class _T:
        timeout = 20.0

        class serial:
            write_termination = '\n'

        def __init__(self, res):
            self._res = res

        def write(self, text):
            raise AssertionError('the whole line must not be sent in one piece')

        def clear(self):
            pass

    def make(self, res):
        from drivers import CommandLog
        from drivers.bk_5491b import BK5491B
        d = BK5491B(self._T(res), CommandLog(), label='t')
        d.COMMAND_GAP_S = 0
        d.ECHO_WAIT_S = 0.01
        return d

    def test_one_character_at_a_time_then_the_end_character(self):
        res = self._Res()
        self.assertEqual(self.make(res).identify(), '5491B  Multimeter,Ver1')
        self.assertEqual(res.sent, [b'*', b'I', b'D', b'N', b'?', b'\n'])
        self.assertEqual(res.timeout, 20000)

    def test_a_character_without_an_echo_is_sent_again_and_only_that_one(self):
        res = self._Res(drop=b'D')
        self.assertEqual(self.make(res).identify(), '5491B  Multimeter,Ver1')
        self.assertEqual(res.sent, [b'*', b'I', b'D', b'D', b'N', b'?', b'\n'])

    def test_a_meter_that_never_echoes_fails_after_the_bounded_resends(self):
        from drivers.base import InstrumentError
        res = self._Res(silent=True)
        with self.assertRaises(InstrumentError) as cm:
            self.make(res).identify()
        self.assertEqual(len(res.sent), 4)                                      # the first character, three more tries
        self.assertIn('did not echo', str(cm.exception))


class EchoFragments(unittest.TestCase):
    def test_a_left_over_piece_of_the_command_is_not_taken_as_the_reply(self):
        from drivers.bk_5491b import BK5491B
        self.assertTrue(BK5491B._is_echo('?', '*IDN?', []))
        self.assertTrue(BK5491B._is_echo('IDN?', '*IDN?', []))
        self.assertFalse(BK5491B._is_echo('5491B  Multimeter,Ver1', '*IDN?', []))
        self.assertFalse(BK5491B._is_echo('+5.000000E+00', 'VOLT:DC:RANG?', []))
        self.assertFalse(BK5491B._is_echo('NO ERROR!', 'SYST:ERR?', []))


def _serial_shim():
    """pyserial is not installed in every test environment: a minimal stand-in (read / write / flush / timeout over a file descriptor) lets the pyserial branch of the driver run."""
    import os
    import select
    import types

    class Serial:
        def __init__(self, port, baudrate=9600, timeout=None, write_timeout=None, **kw):
            self.fd, self.timeout, self.dtr, self.rts = os.open(port, os.O_RDWR | os.O_NOCTTY), timeout, None, None

        def read(self, n=1):
            out = b''
            while len(out) < n:
                if not select.select([self.fd], [], [], self.timeout)[0]:
                    break
                out += os.read(self.fd, n - len(out))
            return out

        def write(self, data):
            os.write(self.fd, data)

        def flush(self):
            pass

        def reset_input_buffer(self):
            while select.select([self.fd], [], [], 0)[0]:
                os.read(self.fd, 256)

        def close(self):
            os.close(self.fd)
    mod = types.ModuleType('serial')
    mod.Serial = Serial
    return mod


@unittest.skipUnless(sys.platform.startswith('linux'), 'needs a pseudo-terminal')
class RealSerialPort(unittest.TestCase):
    """The driver over a real pyserial port (a pseudo-terminal) against a thread that behaves like the 5491B in the owner's probe: every character echoed, the end character
    echoed, then the reply ending in LF."""

    def test_identify_and_a_query_over_pyserial(self):
        import os
        import pty
        import threading
        from drivers import CommandLog
        from drivers.bk_5491b import BK5491B
        from drivers.transport import SerialSettings, SerialTransport
        import tty
        master, slave = pty.openpty()
        tty.setraw(slave)
        tty.setraw(master)
        saved = sys.modules.get('serial')
        try:
            import serial  # noqa: F401
        except ImportError:
            sys.modules['serial'] = _serial_shim()
        stop = threading.Event()

        def meter():
            line = b''
            while not stop.is_set():
                import select
                if not select.select([master], [], [], 0.05)[0]:
                    continue
                for b in os.read(master, 1):
                    os.write(master, bytes([b]))
                    if bytes([b]) == b'\n':
                        cmd = line.decode()
                        line = b''
                        if cmd == '*IDN?':
                            os.write(master, b'5491B  Multimeter,Ver1.4.14.06.18,124J23117\n')
                        elif cmd == 'SYST:ERR?':
                            os.write(master, b'NO ERROR!\n')
                        elif cmd == 'TRIG:SOUR?':
                            os.write(master, b'IMM\n')
                    else:
                        line += bytes([b])
        th = threading.Thread(target=meter, daemon=True)
        th.start()
        try:
            t = SerialTransport(os.ttyname(slave), SerialSettings(baud=9600, write_termination='\n', read_termination='\n'), timeout=3)
            d = BK5491B(t, CommandLog(), label='pty')
            d.COMMAND_GAP_S, d.OPEN_SETTLE_S = 0, 0
            d.connect()
            self.assertIn('5491B', d.idn)
            self.assertEqual(d.query('SYST:ERR?').strip(), 'NO ERROR!')
            d.write('TRIG:SOUR IMM')                                             # owner 2026-10-28: the end character's echo of a set command was read as the next command's first echo
            self.assertEqual(d.query('TRIG:SOUR?').strip(), 'IMM')
            self.assertEqual(d.query('TRIG:SOUR?').strip(), 'IMM')
            d.close()
        finally:
            stop.set()
            th.join(1)
            if saved is None and 'serial' in sys.modules and getattr(sys.modules['serial'], '__file__', None) is None:
                del sys.modules['serial']


class RangeText(unittest.TestCase):
    def test_ranges_are_written_as_the_meter_takes_them(self):
        """Owner probe 2026-10-28: 0.5 / 5 / 50 / 1000 accepted; 0.49, 4.9, 5.0 and 5E+00 refused."""
        from drivers.bk_5491b import RANGES, range_text
        self.assertEqual([range_text(v) for v in RANGES['DCV']], ['0.5', '5', '50', '500', '1000'])
        self.assertEqual([range_text(v) for v in RANGES['DCI']], ['0.005', '0.05', '0.5', '5', '20'])
        self.assertEqual(range_text(50000000.0), '50000000')
        self.assertEqual(range_text(750), '750')

    def test_the_simulated_meter_refuses_what_the_real_one_refused(self):
        from drivers.simulated_5491b import make_5491b_bench
        _b, _c, m = make_5491b_bench()
        for bad in ('VOLT:DC:RANG 0.49', 'VOLT:DC:RANG 5.0', 'VOLT:DC:RANG 2'):
            m.handle(bad)
        self.assertEqual(m.errors, ['BUS:ERROR PARAMETER.'] * 3)
        m.handle('VOLT:DC:RANG 5')
        self.assertEqual(m.handle('VOLT:DC:RANG?'), '5.000000E+00')


if __name__ == '__main__':
    unittest.main()
