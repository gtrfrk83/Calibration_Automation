"""Fluke 8808A performance verification: the spec, the driver, the simulator and the engine on the simulated bench.

* Spec: 105 points by table; every limit pinned for the points the builder corrected; every other limit agrees with the manual's own accuracy formula
  (the builder refuses to run otherwise); the JSON on disk is what the builder makes now.
* Driver: every command has a manual reference; the unverified ones are exactly the listed ones; reset order; set / read back / compare; no write is
  retried; error bits; echo refusal; the calibration (*TER) interface is forbidden.
* Engine (the real App on the simulated bench, tests/live_editor_harness.py): all 105 points, DC outputs carry ,0Hz, outputs go to standby, the reset
  comes first, points the 5522A cannot make use the technician's standard, demo mode records only synthetic, marked data.
The Tk windows are never constructed here (tkinter is stubbed): they have not been looked at on a screen.
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
import fluke8808a_verification as E  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.fluke_8808a import COMMANDS, Fluke8808A, range_number  # noqa: E402
from drivers.simulated_8808a import Sim8808ATransport, make_8808a_bench  # noqa: E402
from drivers.simulated import SimBench  # noqa: E402

SPEC = json.loads((ROOT / 'specs' / 'fluke_8808a_pv.json').read_text(encoding='utf-8'))


def builder():
    spec = importlib.util.spec_from_file_location('build_8808a_spec', ROOT / 'specs' / 'build_8808a_spec.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def points():
    return [p for s in SPEC['sections'] for p in s['points']]


def by_ref(ref):
    return next(p for p in points() if p['ref'] == ref)


class SpecTests(unittest.TestCase):
    def test_counts_by_table(self):
        counts = {}
        for p in points():
            counts[p['table']] = counts.get(p['table'], 0) + 1
        self.assertEqual(counts, {'3-2': 17, '3-3': 28, '3-4': 6, '3-5': 14, '3-6': 18, '3-7': 16, '3-8': 6})
        self.assertEqual(len(points()), 105)

    def test_run_order_and_sections(self):
        got = [(s['id'], len(s['points'])) for s in SPEC['sections']]
        self.assertEqual(got, [('ZERO_SHORT', 15), ('ZERO_OPEN', 6), ('DCV', 12), ('ACV', 28), ('FREQ', 6), ('OHM4', 3), ('OHM2', 7), ('DCI', 12), ('ACI', 16)])
        for s in SPEC['sections']:
            if s['id'].startswith('ZERO'):
                self.assertTrue(all(p['source'] == 'none' and p['nominal'] == 0 for p in s['points']), s['id'])
            else:
                self.assertTrue(all(p['source'] == 'calibrator' for p in s['points']), s['id'])

    def test_json_is_what_the_builder_makes(self):
        self.assertEqual(json.loads(json.dumps(builder().build_spec())), SPEC)

    def test_every_nominal_is_inside_its_limits_and_90_days_inside_1_year(self):
        for p in points():
            for period in ('90d', '1y'):
                lim = p['limits'][period]
                self.assertLess(lim['low'], lim['high'], p['ref'])
                self.assertTrue(lim['low'] <= p['nominal'] <= lim['high'], (p['ref'], period))
            a, b = p['limits']['90d'], p['limits']['1y']
            self.assertTrue(b['low'] <= a['low'] and a['high'] <= b['high'], p['ref'])

    def test_pinned_limits_of_the_corrected_points(self):
        """(ref, period): (low, high) after the correction; the printed text is kept in printed_limits."""
        want = {
            ('T3-2 #11', '1y'): (-19.0037, -18.9963),            # printed 19.0037 (minus sign missing)
            ('T3-3 #1', '90d'): (0.009885, 0.010115),            # printed 9.890 / 10.120 mV (looser than the formula)
            ('T3-3 #10', '90d'): (1.89615, 1.90385),             # printed 1.903985
            ('T3-3 #27', '90d'): (747.38, 752.63),               # printed 747.48
            ('T3-5 #4', '1y'): (1899.56, 1900.44),               # printed STD +/- 0.0044 kohm
            ('T3-6 #9', '1y'): (-0.0190116, -0.0189884),         # printed -190.0116 mA
            ('T3-6 #10', '1y'): (-0.000016, 0.000016),           # printed +/-0.020 mA (looser than the formula)
            ('T3-6 #12', '90d'): (-0.190048, -0.189952),         # printed 190.048 mA (minus sign missing)
            ('T3-7 #13', '1y'): (0.4855, 0.5145),                # printed 04855
        }
        for (ref, period), (low, high) in want.items():
            p = by_ref(ref)
            self.assertEqual((p['limits'][period]['low'], p['limits'][period]['high']), (low, high), (ref, period))
            self.assertTrue(p.get('flags'), ref)
            self.assertIn('printed_limits', p, ref)

    def test_structure_corrections(self):
        p = by_ref('T3-3 #24')
        self.assertEqual((p['nominal'], p['range']), (30.0, 750.0))
        self.assertEqual(by_ref('T3-7 #15')['frequency'], 45.0)
        for n in (4, 5, 6):
            self.assertEqual(by_ref(f'T3-8 #{n}')['unit'], 'Hz')
        self.assertEqual(by_ref('T3-8 #4')['nominal'], 19000.0)
        self.assertEqual(by_ref('T3-8 #6')['nominal'], 1000000.0)

    def test_printed_tighter_limits_are_kept_and_flagged(self):
        for ref in ('T3-8 #2', 'T3-8 #3'):
            self.assertTrue(any(f['code'] == 'tighter' for f in by_ref(ref)['flags']), ref)
        self.assertEqual(by_ref('T3-8 #2')['limits']['1y'], {'low': 50.0, 'high': 50.01})

    def test_spot_values_from_the_manual(self):
        self.assertEqual(by_ref('T3-2 #2')['limits']['1y'], {'low': 0.189964, 'high': 0.190037})
        self.assertEqual(by_ref('T3-3 #28')['limits']['1y'], {'low': 742.88, 'high': 757.13})
        self.assertEqual(by_ref('T3-5 #14')['limits']['90d'], {'low': 98.496e6, 'high': 101.504e6})
        self.assertEqual(by_ref('T3-6 #17')['limits']['1y'], {'low': 9.979, 'high': 10.021})
        self.assertEqual(by_ref('T3-7 #14')['limits']['1y'], {'low': 9.863, 'high': 10.137})
        self.assertEqual(by_ref('T3-8 #6')['limits']['90d'], {'low': 999860.0, 'high': 1000140.0})

    def test_ohms_limits_are_relative_to_the_calibrator_setting(self):
        for p in points():
            if p['kind'] in ('OHM2', 'OHM4') and p['nominal'] != 0:
                self.assertTrue(p['std_relative'], p['ref'])
                self.assertEqual(round(p['limits']['1y']['high'] - p['nominal'], 9), round(p['nominal'] - p['limits']['1y']['low'], 9), p['ref'])

    def test_calibrator_limits_are_the_five_known_points(self):
        self.assertEqual(sorted(p['ref'] for p in points() if p.get('cal_limits')), ['T3-3 #26', 'T3-3 #27', 'T3-3 #28', 'T3-7 #14', 'T3-8 #6'])
        self.assertEqual({p['ref']: sorted(p['cal_limits']) for p in points() if p.get('cal_limits')},
                         {'T3-3 #26': ['5522A', '5560A'], 'T3-3 #27': ['5522A', '5560A'], 'T3-3 #28': ['5522A', '5560A'], 'T3-7 #14': ['5522A'], 'T3-8 #6': ['5522A', '5560A']})

    def test_every_range_exists_on_the_meter(self):
        for p in points():
            self.assertIn(range_number(p['kind'], p['range']), range(1, 8), p['ref'])

    def test_loader_refuses_a_bad_spec(self):
        bad = json.loads(json.dumps(SPEC))
        bad['sections'][2]['points'][0]['limits']['1y']['high'] = bad['sections'][2]['points'][0]['limits']['1y']['low']
        path = Path(H.tempfile.mkdtemp()) / 'bad.json'
        path.write_text(json.dumps(bad))
        with self.assertRaises(E.SpecError):
            E.load_spec(path)

    def test_judge_is_decimal_and_inclusive(self):
        E.configure()
        p = next(q for q in E.POINTS if q['ref'] == 'T3-2 #2')
        E.apply_period(E.POINTS, '1y')
        self.assertTrue(E.judge(p, 0.190037))
        self.assertTrue(E.judge(p, 0.189964))
        self.assertFalse(E.judge(p, 0.1900371))
        self.assertFalse(E.judge(p, 0.1899639))


class DriverTests(unittest.TestCase):
    def make(self, **kw):
        bench, ct, dt = make_8808a_bench()
        log = drivers.CommandLog()
        d = Fluke8808A(dt, log, label='8808A')
        return bench, ct, dt, d, log

    @staticmethod
    def logged(log, who='8808A'):
        """Commands written to `who`, as the command log recorded them (a command is logged before it goes on the wire)."""
        out = []
        for line in log.lines():
            parts = line.split(None, 3)
            if parts[1] == who and parts[2] == '>>':
                out.append(parts[3])
        return out

    def sent(self, dt):
        return list(dt.sent)

    def test_registry_is_clean_and_referenced(self):
        reg = cmdreg.merge_commands(Fluke8808A)
        self.assertEqual(cmdreg.lint_registry(reg), [])
        for key, cmd in reg.items():
            self.assertTrue(cmd.ref, key)

    def test_unverified_commands_are_exactly_the_listed_ones(self):
        self.assertEqual(sorted(k for k, c in COMMANDS.items() if not c.verified), ['func.query'])

    def test_locked_commands(self):
        for key in ('reset', 'status.clear', 'err.query', 'opc.query'):
            self.assertEqual(COMMANDS[key].risk, 'locked', key)
        self.assertEqual(COMMANDS['reset'].template, '*RST')
        self.assertTrue(COMMANDS['reset'].verified)

    def test_calibration_interface_is_forbidden_and_absent(self):
        for key, cmd in COMMANDS.items():
            self.assertNotIn('*TER', cmd.template, key)
            self.assertNotIn('CALREF', cmd.template, key)
        probs = cmdreg.validate('*TER', COMMANDS['rate.set'], 'Fluke8808A')
        self.assertTrue(probs)

    def test_serial_settings_are_the_factory_ones(self):
        s = Fluke8808A.SERIAL
        self.assertEqual((s.baud, s.data_bits, s.parity, s.stop_bits), (9600, 8, 'none', 1))

    def test_connect_identifies_enters_remote_and_clears_status(self):
        _b, _ct, dt, d, log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
        self.assertEqual(self.sent(dt), ['*IDN?', 'REMS', '*CLS'])
        self.assertIn('8808A', d.idn)
        self.assertTrue(dt.remote)

    def test_wrong_model_is_refused(self):
        _b, _ct, dt, d, _log = self.make()
        dt.handle = lambda cmd: 'FLUKE, 8846A, 1, 1.0' if cmd == '*IDN?' else None
        with mock.patch('time.sleep'), self.assertRaises(InstrumentError):
            d.connect()

    def test_echo_on_is_refused(self):
        _b, _ct, dt, d, _log = self.make()
        orig = dt.handle
        dt.handle = lambda cmd: '=> FLUKE, 8808A, 1, 1.0' if cmd == '*IDN?' else orig(cmd)
        with mock.patch('time.sleep'), self.assertRaisesRegex(InstrumentError, 'Echo is ON'):
            d.connect()

    def test_reset_order_and_known_state(self):
        _b, _ct, dt, d, log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            dt.sent.clear()
            rep = d.reset_to_defaults()
        self.assertTrue(rep.ok, rep.text())
        self.assertEqual(dt.sent, ['*RST', '*CLS', '*OPC?', '*ESR?', 'REMS', 'FORMAT 1', 'FORMAT?', 'TRIGGER 1', 'TRIGGER?', 'RATE S', 'RATE?', '*ESR?'])
        self.assertEqual((dt.format, dt.trigger, dt.rate), (1, 1, 'S'))

    def test_reset_waits_after_the_reset_command_and_paces_commands(self):
        _b, _ct, dt, d, _log = self.make()
        sleeps = []
        with mock.patch('time.sleep', side_effect=sleeps.append):
            d.connect()
            sleeps.clear()
            d.reset_to_defaults()
        self.assertIn(d.RESET_SETTLE_S, sleeps)
        self.assertGreaterEqual(sleeps.count(d.COMMAND_GAP_S), 12)

    def test_reset_failure_stops_the_sequence(self):
        _b, _ct, dt, d, log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            mark = len(self.logged(log))
            dt.bench.fail_next = '*CLS'
            rep = d.reset_to_defaults()
        self.assertFalse(rep.ok)
        self.assertEqual(self.logged(log)[mark:], ['*RST', '*CLS'])       # *CLS tried once; nothing after the failed step

    def test_configure_point_sets_reads_back_and_checks(self):
        _b, _ct, dt, d, _log = self.make()
        p = dict(kind='ACI', range=0.2)
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            dt.sent.clear()
            d.configure_point(p)
            d.check_errors('test')
        self.assertEqual(dt.sent, ['AAC', 'FUNC1?', 'FIXED', 'AUTO?', 'RANGE 2', 'RANGE1?', 'RATE S', 'RATE?', 'FORMAT?', 'TRIGGER?', '*OPC?', '*ESR?'])

    def test_ohms_wire_modes_and_frequency_has_no_rate(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            dt.sent.clear()
            d.configure_point(dict(kind='OHM4', range=2000.0))
            self.assertIn('WIRE4', dt.sent)
            self.assertEqual(dt.wire, 4)
            d.configure_point(dict(kind='OHM2', range=2000.0))
            self.assertEqual(dt.wire, 2)
            dt.sent.clear()
            d.configure_point(dict(kind='FREQ', range=20000.0))
        self.assertNotIn('RATE S', dt.sent)
        self.assertIn('FREQ', dt.sent)

    def test_a_failed_read_back_raises_and_the_write_is_not_repeated(self):
        _b, _ct, dt, d, log = self.make()
        orig = dt.handle
        dt.handle = lambda cmd: None if cmd.upper().startswith('RANGE ') and not cmd.upper().startswith('RANGE1') else orig(cmd)
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            mark = len(self.logged(log))
            with self.assertRaisesRegex(InstrumentError, 'range 3 was not accepted'):
                d.configure_point(dict(kind='DCV', range=20.0))
        self.assertEqual(self.logged(log)[mark:].count('RANGE 3'), 1)

    def test_a_write_that_times_out_is_not_retried(self):
        _b, _ct, dt, d, log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            mark = len(self.logged(log))
            dt.bench.fail_next = 'FIXED'
            with self.assertRaises(Exception):
                d.configure_point(dict(kind='DCV', range=20.0))
        sent = self.logged(log)[mark:]
        self.assertEqual(sent.count('FIXED'), 1)             # tried once, never repeated
        self.assertNotIn('RANGE 3', sent)

    def test_error_bits_are_reported_and_cleared(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.send('func.vdc')
            d.write('NOTACOMMAND')
            with self.assertRaisesRegex(InstrumentError, 'command error'):
                d.check_errors('test')
            d.check_errors('again')                            # *ESR? cleared the register: no error now

    def test_a_command_sent_with_a_reply_pending_is_a_query_error(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.write('FUNC1?')                                  # a query written but never read
            d.write('VDC')
            with self.assertRaisesRegex(InstrumentError, 'query error'):
                d.check_errors('test')

    def test_overload_and_unreadable_replies_are_rejected(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.configure_point(dict(kind='DCV', range=0.2))
            bench = dt.bench
            bench.fluke.update(operate=True, volts=1.0, unit='V', freq=0.0)      # 1 V into the 200 mV range
            with self.assertRaisesRegex(InstrumentError, 'overload'):
                d.read()

    def test_reading_is_the_second_meas1(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.reset_to_defaults()
            d.configure_point(dict(kind='DCV', range=2.0))
            dt.sent.clear()
            d.read()
        self.assertEqual(dt.sent, ['MEAS1?', 'MEAS1?'])

    def test_the_default_format_is_not_assumed(self):
        """The simulator's power-up format is 2 (a simulation choice): without the explicit FORMAT 1 the reading would not parse."""
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            dt.handle('*RST')
            self.assertEqual(dt.format, 2)
            d.reset_to_defaults()
            self.assertEqual(dt.format, 1)

    def test_cleanup_returns_to_local(self):
        _b, _ct, dt, d, _log = self.make()
        with mock.patch('time.sleep'):
            d.connect()
            d.cleanup()
        self.assertFalse(dt.remote)

    def test_range_numbers_follow_table_4_11a(self):
        self.assertEqual([range_number('DCV', r) for r in (0.2, 2, 20, 200, 1000)], [1, 2, 3, 4, 5])
        self.assertEqual([range_number('ACV', r) for r in (0.2, 2, 20, 200, 750)], [1, 2, 3, 4, 5])
        self.assertEqual([range_number('OHM2', r) for r in (200, 2e3, 20e3, 200e3, 2e6, 20e6, 100e6)], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([range_number('DCI', r) for r in (200e-6, 2000e-6, 20e-3, 200e-3, 2, 10)], [1, 2, 3, 4, 5, 6])
        self.assertEqual([range_number('ACI', r) for r in (20e-3, 200e-3, 2, 10)], [1, 2, 3, 4])
        self.assertEqual([range_number('FREQ', r) for r in (2e3, 20e3, 200e3, 1e6)], [1, 2, 3, 4])
        with self.assertRaises(InstrumentError):
            range_number('DCV', 100.0)


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
        app = self.app = E.App(self.h.root, '8808A', demo=demo)
        self.h.app = app
        app.asset.set('A-8808')
        app.serial.set('SN')
        app.cal_model.set(cal)
        if not demo:
            self.bench, ct, self.dt = make_8808a_bench(E.CALIBRATORS[cal][0], enforce)
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
                self.bench.external = ({'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A'}[p['kind']], p['nominal'], p.get('frequency') or 0.0)
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

    def test_all_105_points_run_and_pass_on_the_5522A(self):
        app = self.build()
        self.run_all()
        self.assertEqual(len(app.found), 105)
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        self.assertFalse(any(r['synthetic'] for r in app.found.values()))
        manual = sorted(p['ref'] for p in E.POINTS if app.found[str(p['id'])]['manual'])
        self.assertEqual(manual, ['T3-3 #26', 'T3-3 #27', 'T3-3 #28', 'T3-7 #14', 'T3-8 #6'])

    def test_reset_comes_first_for_both_instruments(self):
        self.build()
        self.run_all()
        lines = self.log_lines()
        first_use = next(i for i, (_w, d, t) in enumerate(lines) if d == '>>' and (t.startswith('OUT') or t in ('VDC', 'OPER')))
        resets = [i for i, (_w, d, t) in enumerate(lines) if d == '>>' and t == '*RST']
        self.assertEqual(len(resets), 2)
        self.assertTrue(all(i < first_use for i in resets))

    def test_dc_outputs_carry_0hz_and_ac_outputs_a_frequency(self):
        self.build()
        self.run_all()
        outs = [t for w, d, t in self.log_lines() if w == '5522A' and d == '>>' and t.startswith('OUT ')]
        dc = [t for t in outs if t.endswith(',0Hz')]
        self.assertEqual(len(dc), 24)                                  # 12 DC volts + 12 DC current points
        for t in outs:
            if re.match(r'OUT [-+0-9.eE]+(V|A)$', t):
                self.fail('an output without a frequency: ' + t)

    def test_zero_points_never_turn_the_calibrator_on_and_every_output_goes_to_standby(self):
        self.build()
        self.run_all()
        cal = [t for w, d, t in self.log_lines() if w == '5522A' and d == '>>' and t in ('OPER', 'STBY')]
        self.assertEqual(cal.count('OPER'), 79)                        # 105 - 21 zero points - 5 manual points
        for a, b in zip(cal, cal[1:]):
            self.assertFalse(a == 'OPER' and b == 'OPER', 'OPER twice without STBY between')
        self.assertEqual(cal[-1], 'STBY')

    def test_the_calibrator_is_not_asked_for_what_it_cannot_make(self):
        self.build()
        self.run_all()
        outs = ' '.join(t for w, d, t in self.log_lines() if w == '5522A' and d == '>>')
        self.assertNotRegex(outs, r'OUT 750V,(20|50|100)')
        self.assertNotRegex(outs, r'OUT -?1000V,[1-9]')
        self.assertNotIn('1MHz', outs)

    def test_a_point_the_5522A_refuses_stops_before_the_output_is_enabled(self):
        app = self.build()
        p = next(q for q in E.POINTS if q['ref'] == 'T3-3 #28')
        app.io.is_manual = lambda q: False
        with mock.patch('time.sleep'):
            app.io.reset_at_start()
        with self.assertRaisesRegex(InstrumentError, 'rejected the setting'):
            app.io.measure(p)
        sent = [t for w, d, t in self.log_lines() if w == '5522A' and d == '>>']
        self.assertNotIn('OPER', sent)
        self.assertEqual(sent[-1], 'ERR?')

    def test_the_5560a_drives_the_10_a_40_hz_point_and_uses_the_operator_standard_for_the_four_it_cannot_make(self):
        # 5560A Product Specifications (Rev. 8, 6/26): ACV 1020 V range 3 Hz - 10 kHz only (printed p. 4), ACV stops at 500 kHz (pp. 3-4), ACI 12 A range 3 Hz - 45 Hz (p. 8)
        app = self.build(cal='Fluke 5560A', enforce=False)
        refs = sorted(p['ref'] for p in E.POINTS if app.is_manual(p))
        self.assertEqual(refs, ['T3-3 #26', 'T3-3 #27', 'T3-3 #28', 'T3-8 #6'])
        p = next(q for q in E.POINTS if q['ref'] == 'T3-7 #14')
        self.assertFalse(app.is_manual(p))
        self.assertEqual(app.manual_reason(p), '')
        for ref in refs:
            self.assertIn('5560A Product Specifications', app.manual_reason(next(q for q in E.POINTS if q['ref'] == ref)))
        app.cal_model.set('Fluke 5522A')                                  # the 5522A is unchanged: the same five points are manual
        self.assertEqual(sorted(q['ref'] for q in E.POINTS if app.is_manual(q)), ['T3-3 #26', 'T3-3 #27', 'T3-3 #28', 'T3-7 #14', 'T3-8 #6'])
        self.assertFalse(hasattr(app, 'try_5560a'))

    def test_the_5560a_run_sources_10_a_at_40_hz_and_not_the_four_manual_points(self):
        self.build(cal='Fluke 5560A', enforce=False)
        self.run_all()
        sent = [t for w, d, t in self.log_lines() if w == '5560A' and d == '>>']
        outs = ' '.join(sent)
        self.assertRegex(outs, r'OUT 10A,40')
        self.assertNotRegex(outs, r'OUT 750V,(20|50|100)')
        self.assertNotIn('1MHz', outs)
        self.assertEqual(sent.count('OPER'), 80)                          # 105 - 21 zero points - 4 manual points
        self.assertEqual(sent[-1], 'STBY')

    def test_5560a_uncertainty_and_tar_for_10_a_40_hz_use_the_5560a_12_a_range_spec(self):
        import os
        import tempfile
        import specmanager as sm
        import report_pdf
        import tartur_wiring
        import uncertainty_budget
        db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=db)
        std = sm.standard('5560A', db)
        h = std.lookup('ACI', 10.0, frequency=40.0)
        self.assertEqual(h.row['label'], '12A @ 3 - 45 Hz')
        self.assertAlmostEqual(h.limit, 0.00029 * 10 + 0.001, 12)                       # 290 uA/A + 1 mA (1 year, 95 %, 5560A printed p. 8)
        E.configure()
        p = next(q for q in E.POINTS if q['ref'] == 'T3-7 #14')
        b = uncertainty_budget.build('ACI', 10.0, 'A', standard=std, frequency=40.0, scope=report_pdf.scope(), range_value=10.0)
        self.assertEqual(b.hit.row['label'], '12A @ 3 - 45 Hz')
        self.assertEqual(b.components[0].name, '5560A Calibrator')
        self.assertNotEqual(report_pdf.point_uncertainty(p, '5560A'), '')
        self.assertNotEqual(tartur_wiring.point_fields(p, '5560A')['TAR'], '')            # the 5522A has no spec at 40 Hz here: its TAR stays blank
        self.assertEqual(tartur_wiring.point_fields(p, '5522A')['TAR'], '')

    def test_high_voltage_points_ask_first_and_a_refusal_stops_the_run(self):
        app = self.build()
        self.h.box_answer['askyesno'] = False
        app.warm_confirmed = True
        points_ = [p for p in E.POINTS if p['ref'] == 'T3-2 #16']
        app.execute(points_)
        self.h.pump(30)
        self.assertTrue(any(d[0] == 'box' and d[2] == 'HIGH VOLTAGE' for d in self.h.dialogs))
        self.assertEqual(app.found, {})
        self.assertNotIn('OPER', [t for w, d, t in self.log_lines() if w == '5522A'])

    def test_the_warm_up_question_is_asked_once(self):
        app = self.build()
        self.run_all()
        asks = [d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'Warm-up']
        self.assertEqual(len(asks), 1)

    def test_ohms_prompt_names_the_annunciator(self):
        self.build()
        self.run_all()
        steps = [' '.join(d[3]) for d in self.h.dialogs if d[0] == 'confirm']
        self.assertTrue(any('4W annunciator' in s for s in steps))
        self.assertTrue(any('2W annunciator' in s for s in steps))

    def test_period_90_days_changes_the_limits_and_rejudges(self):
        app = self.build()
        self.run_all()
        app.period.set('90 days')
        app.on_period(save=False)
        p = E.POINTS[1]
        self.assertEqual((p['low'], p['high']), (p['limits']['90d']['low'], p['limits']['90d']['high']))
        app.period.set('1 year')
        app.on_period(save=False)
        self.assertEqual((p['low'], p['high']), (p['limits']['1y']['low'], p['limits']['1y']['high']))

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
        self.assertEqual(len(app.found), 105)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertTrue(all(r['result'] == 'PASS' for r in app.found.values()))

    def test_demo_report_is_marked(self):
        try:
            import reportlab  # noqa: F401
        except Exception:
            self.skipTest('reportlab not installed')
        import report_dialog
        import report_pdf
        app = self.build(demo=True)
        app.execute(app.active_points())
        self.h.pump(60)
        out = Path(self.h.home) / 'demo.pdf'
        with mock.patch.object(report_dialog, 'ask_details', lambda *a, **k: {'technician': 'T', 'temperature': '23', 'humidity': '40', 'standards': [], 'show_tar_tur': True}), \
                mock.patch.object(E.filedialog, 'asksaveasfilename', lambda **k: str(out)):
            app.export_pdf()
        self.assertTrue(out.exists())
        rows = app.certificate_rows()
        self.assertEqual(len(rows), 105)
        import subprocess
        if Path('/usr/bin/pdftotext').exists():
            text = subprocess.run(['pdftotext', str(out), '-'], capture_output=True, text=True).stdout
            self.assertIn('DEMO DATA - NOT CALIBRATION EVIDENCE', text)
            self.assertIn('Calibration Data', text)

    def test_the_real_report_has_uncertainty_for_calibrator_points_and_none_for_manual_ones(self):
        try:
            import reportlab  # noqa: F401
        except Exception:
            self.skipTest('reportlab not installed')
        app = self.build()
        self.run_all()
        rows, pts = app.certificate_rows_and_points()
        by = {p['ref']: r for p, r in zip(pts, rows)}
        self.assertTrue(by['T3-2 #2']['Uncertainty'])
        self.assertEqual(by['T3-3 #28']['Uncertainty'], '')
        self.assertEqual(by['T3-8 #6']['Uncertainty'], '')

    def test_report_file_name_is_asset_and_date(self):
        import ui_theme as ui
        self.assertRegex(ui.report_filename('A-8808'), r'^A-8808-\d{2}-\d{2}-\d{4}\.pdf$')

    def test_checkpoint_round_trip_keeps_the_manual_flag(self):
        app = self.build()
        p = next(q for q in E.POINTS if q['ref'] == 'T3-3 #28')
        app._record(p, 750.0, False, manual=True)
        data = json.loads(json.dumps(app.save_fields()))
        self.assertTrue(data['results'][str(p['id'])]['manual'])


class SourceGuards(unittest.TestCase):
    def test_engine_never_retries_a_write_or_sends_adjustment_commands(self):
        for rel in ('fluke8808a_verification.py', 'drivers/fluke_8808a.py'):
            src = (ROOT / rel).read_text(encoding='utf-8')
            self.assertNotIn('query_retry(\'meas1', src)
            self.assertNotRegex(src, r"send\('cal|'\*TER'|CALREF", rel)
        self.assertNotIn('password', (ROOT / 'drivers/fluke_8808a.py').read_text(encoding='utf-8').lower())

    def test_launcher_and_manager_registration(self):
        launcher = (ROOT / 'Procedures' / 'Fluke_8808A_Verification.py').read_text(encoding='utf-8')
        self.assertIn('fluke8808a_verification.main()', launcher)
        mgr = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        self.assertEqual(mgr.count('Fluke_8808A_Verification.py'), 3)

    def test_the_unit_of_work_is_exported(self):
        self.assertIs(drivers.Fluke8808A, Fluke8808A)


if __name__ == '__main__':
    unittest.main()
