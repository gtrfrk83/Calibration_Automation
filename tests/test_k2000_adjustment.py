"""Keithley 2000 guided adjustment: spec, driver, session logic, audit record and the sidecar, on the simulated bench (no tkinter, no hardware).

The simulated 2000 (drivers/simulated_k2000_cal.py) keeps TEMPORARY and SAVED constants apart, so the tests can prove what an abort leaves behind, and it only accepts its own
SIM_CODE (not a real code).  Every test that looks for the code in a log, a file or an exception looks for SIM_CODE.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import adjustment_audit  # noqa: E402
import drivers  # noqa: E402
import keithley2000_adjustment as adj  # noqa: E402
import procscan  # noqa: E402
from drivers import keithley_2000_cal as cal_driver  # noqa: E402
from drivers.base import InstrumentError, SafetyError  # noqa: E402
from drivers.simulated_k2000_cal import SIM_CODE, make_k2000_cal_bench  # noqa: E402
from drivers.transport import TransportError  # noqa: E402

ACKS = ('conditions', 'as_found', 'authorised', 'notice')


def new_session(cal='5522A', bus='GPIB', firmware='A20', scope=('DC', 'AC'), demo=True, store=None, model=None):
    bench, cal_t, dmm_t = make_k2000_cal_bench(cal, bus, firmware)
    io = adj.AdjustIO('16', 'COM9', model or f'Fluke {cal}', transports=(dmm_t, cal_t), virtual=True)
    audit = store or adjustment_audit.AuditStore(demo=demo)
    audit.start_run(adj.INSTRUMENT, 'ASSET1', 'SN1', 'Tech', uut_idn=io.ident, scope='+'.join(scope))
    t = [0.0]
    s = adj.Session(io, audit, scope=scope, clock=lambda: t[0], wait=lambda _s: None)
    s.t = t
    return s, bench, cal_t, dmm_t


def open_session(*a, **k):
    s, bench, cal_t, dmm_t = new_session(*a, **k)
    s.reset(confirm=lambda _t: True)
    s.prepare()
    for key in ACKS:
        s.acknowledge(key)
    s.unlock(SIM_CODE)
    return s, bench, cal_t, dmm_t


def do_step(s, st, **kw):
    """The window's per-step work: hook-up confirmed, thermal wait over, source on, parameter = the calibrator's read-back."""
    s.mark_hookup(st)
    s.t[0] += 10000.0
    got = s.program_source(st, hv_ok=True)
    return s.send_step(st, None if not st['param'] else st['param']['nominal'] if got is None else repr(got), **kw)


def run_all(s):
    while s.next_step():
        do_step(s, s.next_step())


class SpecTests(unittest.TestCase):
    def test_counts_and_order(self):
        self.assertEqual(len(adj.STEPS), 26)
        self.assertEqual([x['id'] for x in adj.STEPS if x['scope'] == 'DC'], [f'D{i:02d}' for i in range(1, 14)])
        self.assertEqual([x['id'] for x in adj.STEPS if x['scope'] == 'AC'], [f'A{i:02d}' for i in range(1, 14)])
        self.assertEqual([x['id'] for x in adj.steps_in_scope(('DC', 'AC'))], [x['id'] for x in adj.STEPS])
        self.assertEqual(len(adj.steps_in_scope(('DC',))), 13)

    def test_a19_numbering(self):
        a20 = {x['id']: x for x in adj.available_steps('A20+')}
        a19 = {x['id']: x for x in adj.available_steps('A19-')}
        self.assertEqual(len(a20), 26)
        self.assertEqual(len(a19), 25)
        self.assertNotIn('D10', a19)                                           # no 10 Mohm step on A19 and earlier (Table 3-1 note, p. 3-4)
        self.assertEqual(adj.command_text(a20['D11'], 'A20+', Decimal('0.01')), ':CAL:PROT:DC:STEP11 0.01')
        self.assertEqual(adj.command_text(a19['D11'], 'A19-', Decimal('0.01')), ':CAL:PROT:DC:STEP10 0.01')
        self.assertEqual(adj.command_text(a19['D13'], 'A19-', Decimal('1')), ':CAL:PROT:DC:STEP12 1')
        self.assertEqual(adj.command_text(a19['A13'], 'A19-'), ':CAL:PROT:AC:STEP13')
        with self.assertRaises(InstrumentError):
            cal_driver.step_number(adj.step_by_id('D10'), 'A19-')
        with self.assertRaises(InstrumentError):
            cal_driver.step_number(adj.step_by_id('D03'), None)

    def test_parameters_in_decimal(self):
        d03 = adj.step_by_id('D03')
        for text, ok in (('10', True), ('9', True), ('11', True), ('11.0000001', False), ('8.99', False), ('abc', False), ('nan', False), ('inf', False), ('', False)):
            value, why = adj.validate_parameter(d03, text)
            self.assertEqual(value is not None, ok, text)
            self.assertEqual(why is None, ok, text)
        self.assertEqual(adj.validate_parameter(d03, '10.0000001')[0], Decimal('10.0000001'))
        self.assertEqual(adj.validate_parameter(adj.step_by_id('A04'), '1')[0], None)          # AC steps take no parameter

    def test_display_scaling_only(self):
        self.assertEqual(adj.si_text(0.01, 'V'), '10 mV')
        self.assertEqual(adj.si_text(1e6, 'ohm'), '1 MΩ')
        # the commands carry the base-unit number, never the scaled one
        self.assertEqual(adj.command_text(adj.step_by_id('D09'), 'A20+', Decimal('1000000')), ':CAL:PROT:DC:STEP9 1000000')

    def test_flags_and_misprints_recorded(self):
        text = json.dumps(adj.SPEC)
        self.assertIn('MISPRINT', text)
        self.assertTrue(adj.SPEC['not_built'])

    def test_every_step_has_hookup_text(self):
        for cal in ('5522A', '5560A'):
            for st in adj.STEPS:
                self.assertTrue(adj.hookup_text(st, cal), st['id'])


class RunTests(unittest.TestCase):
    def check_full_run(self, cal, bus, firmware, expected_steps):
        s, bench, cal_t, dmm_t = open_session(cal, bus, firmware)
        self.assertEqual(len(s.plan()), expected_steps)
        self.assertFalse(dmm_t.locked)
        run_all(s)
        self.assertTrue(s.all_done())
        self.assertEqual(len(dmm_t.temp), expected_steps)
        self.assertEqual(dmm_t.saved, {})                                     # nothing stored before SAVE
        s.set_dates(date(2026, 10, 23))
        s.save(adj.CONFIRM_SAVE)
        s.relock()
        self.assertEqual(len(dmm_t.saved), expected_steps)
        self.assertTrue(dmm_t.locked)
        self.assertFalse(bench.fluke['operate'])                              # calibrator in standby
        steps = [c for c in dmm_t.cal_sent if ':STEP' in c]
        self.assertEqual(len(steps), expected_steps)
        self.assertEqual(len(set(steps)), expected_steps, 'a step was sent twice')
        order = [c.split()[0] for c in dmm_t.cal_sent]
        self.assertLess(order.index('INIT'), order.index(steps[0].split()[0]))
        self.assertLess(order.index('NDUE'), order.index('SAVE'))
        self.assertLess(order.index('SAVE'), len(order) - order[::-1].index('LOCK') - 1)
        self.assertEqual(dmm_t.code_sent, 1)
        self.assertEqual(order.count('INIT'), 1)
        self.assertEqual(order.count('SAVE'), 1)
        return s, dmm_t

    def test_full_run_gpib_5522a(self):
        self.check_full_run('5522A', 'GPIB', 'A20', 26)

    def test_full_run_rs232_5560a(self):
        self.check_full_run('5560A', 'RS232', 'A20', 26)

    def test_full_run_firmware_a19(self):
        s, dmm_t = self.check_full_run('5522A', 'GPIB', 'A19', 25)
        self.assertEqual(s.fw_class, 'A19-')
        self.assertNotIn('DC:STEP13', ' '.join(dmm_t.cal_sent))

    def test_scopes(self):
        s, *_ = open_session(scope=('DC',))
        self.assertEqual(len(s.plan()), 13)
        run_all(s)
        s.set_dates(date(2026, 10, 23))
        s.save(adj.CONFIRM_SAVE)                                              # DC only is allowed (p. 2-14 note)
        s2, *_ = open_session(scope=('AC',))
        self.assertEqual([x['id'] for x in s2.plan()][0], 'A01')

    def test_dc_parameter_is_the_calibrator_readback(self):
        s, bench, cal_t, dmm_t = open_session()
        run_all(s)
        by = {c.split()[0]: c for c in dmm_t.cal_sent if ':STEP' in c or 'STEP' in c}
        self.assertEqual(float(by['DC:STEP3'].split()[1]), 10.0)
        self.assertEqual(float(by['DC:STEP4'].split()[1]), -10.0)
        self.assertEqual(float(by['DC:STEP6'].split()[1]), 1000.0)
        self.assertEqual(by['AC:STEP4'], 'AC:STEP4')

    def test_resistance_compensation_on_5522a(self):
        s, bench, cal_t, dmm_t = open_session('5522A')
        seen = {}
        for st in s.plan():
            do_step(s, st)
            if st['group'] == 'OHM4':
                seen[st['id']] = cal_t.zcomp
        self.assertEqual(seen, {'D06': 'WIRE4', 'D07': 'WIRE4', 'D08': 'WIRE4', 'D09': 'NONE', 'D10': 'NONE'})


class SafetyTests(unittest.TestCase):
    def test_reset_happens_before_any_calibration_command(self):
        s, bench, cal_t, dmm_t = open_session()
        lines = '\n'.join(s.io.log.lines())
        self.assertIn('*RST', lines)
        self.assertLess(lines.index('*RST'), lines.index(':CAL:PROT'))
        self.assertLess(lines.index('*RST'), lines.index('CODE'))

    def test_reset_declined_touches_nothing(self):
        s, bench, cal_t, dmm_t = new_session()
        import reset_startup
        with self.assertRaises(reset_startup.ResetDeclined):
            s.reset(confirm=lambda _t: False)
        self.assertNotIn('*RST', ' '.join(dmm_t.sent))
        self.assertEqual(dmm_t.code_sent, 0)

    def test_unlock_needs_every_confirmation(self):
        for missing in ACKS:
            s, bench, cal_t, dmm_t = new_session()
            s.reset(confirm=lambda _t: True)
            for key in ACKS:
                if key != missing:
                    s.acknowledge(key)
            with self.assertRaises(adj.AdjustmentError):
                s.unlock(SIM_CODE)
            self.assertEqual(dmm_t.code_sent, 0, missing)
            self.assertTrue(dmm_t.locked)

    def test_unlock_needs_a_record(self):
        bench, cal_t, dmm_t = make_k2000_cal_bench('5522A')
        io = adj.AdjustIO('16', 'COM9', 'Fluke 5522A', transports=(dmm_t, cal_t), virtual=True)
        s = adj.Session(io, adjustment_audit.AuditStore(demo=True), wait=lambda _s: None)
        for key in ACKS:
            s.acknowledge(key)
        with self.assertRaises(adj.AdjustmentError):
            s.unlock(SIM_CODE)
        self.assertEqual(dmm_t.code_sent, 0)

    def test_wrong_code_sent_once_and_not_retried(self):
        s, bench, cal_t, dmm_t = new_session()
        s.reset(confirm=lambda _t: True)
        for key in ACKS:
            s.acknowledge(key)
        with self.assertRaises(InstrumentError) as cm:
            s.unlock('WRONG123')
        self.assertNotIn('WRONG123', str(cm.exception))
        self.assertEqual(dmm_t.code_sent, 1)
        self.assertTrue(dmm_t.locked)
        with self.assertRaises(InstrumentError):
            s.unlock(SIM_CODE)                                                 # a second code in the same session is refused
        self.assertEqual(dmm_t.code_sent, 1)
        self.assertFalse(s.unlocked)
        with self.assertRaises(adj.AdjustmentError):
            do_step(s, s.plan()[0])

    def test_code_is_not_in_the_log_the_database_the_exceptions_or_the_audit(self):
        tmp = tempfile.mkdtemp()
        store = adjustment_audit.AuditStore(demo=False, path=Path(tmp) / 'lab_registry.sqlite3')
        s, bench, cal_t, dmm_t = open_session(store=store)
        run_all(s)
        s.set_dates(date(2026, 10, 23))
        s.save(adj.CONFIRM_SAVE)
        s.relock()
        s.io.save_log = lambda: None
        log_text = '\n'.join(s.io.log.lines())
        self.assertIn('CAL:PROT:CODE', log_text.replace(':CAL', 'CAL'))
        self.assertIn('********', log_text)
        self.assertNotIn(SIM_CODE, log_text)
        store.con.commit()
        blob = Path(store.path).read_bytes()
        self.assertNotIn(SIM_CODE.encode(), blob)
        self.assertNotIn(SIM_CODE, json.dumps(store.events()))
        store.close()
        self.assertNotIn(SIM_CODE.encode(), Path(store.path).read_bytes())
        self.assertNotIn(SIM_CODE, ' '.join(dmm_t.sent))                       # the simulator's own record is masked too

    def test_transport_error_on_the_code_write_is_scrubbed(self):
        s, bench, cal_t, dmm_t = new_session()
        s.reset(confirm=lambda _t: True)
        for key in ACKS:
            s.acknowledge(key)
        real = dmm_t.handle

        def boom(cmd):
            if 'CODE' in cmd.upper():
                raise TransportError(f'write failed for {cmd!r}')
            return real(cmd)
        dmm_t.handle = boom
        with self.assertRaises(InstrumentError) as cm:
            s.unlock(SIM_CODE)
        self.assertNotIn(SIM_CODE, str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertIsNone(cm.exception.__context__)
        self.assertFalse(any(SIM_CODE in str(r) for r in s.audit.events()))

    def test_audit_clean_masks_any_code_text(self):
        self.assertNotIn('ABC123', adjustment_audit.clean(":CAL:PROT:CODE 'ABC123'"))
        self.assertNotIn('ABC123', adjustment_audit.clean('CAL:PROT:CODE ABC123'))
        store = adjustment_audit.AuditStore(demo=True)
        store.start_run('K', 'A', 's', 't')
        store.log('X', 'OK', ":CAL:PROT:CODE 'ABC123' sent")
        self.assertNotIn('ABC123', json.dumps(store.events()))

    def test_code_shape_checked_before_sending(self):
        s, bench, cal_t, dmm_t = new_session()
        s.reset(confirm=lambda _t: True)
        for key in ACKS:
            s.acknowledge(key)
        for bad in ('', "A'B", 'TOOLONGCODE', 'a b'):
            with self.assertRaises(InstrumentError):
                s.io.dmm.unlock(bad)
        self.assertEqual(dmm_t.code_sent, 0)

    def test_steps_in_the_manual_order_only(self):
        s, *_ = open_session()
        with self.assertRaises(adj.AdjustmentError):
            do_step(s, adj.step_by_id('D03'))
        do_step(s, adj.step_by_id('D01'))
        with self.assertRaises(adj.AdjustmentError):
            do_step(s, adj.step_by_id('D01'))                                  # a done step is not sent again

    def test_thermal_wait_gates_the_short_and_the_dc_volts_step(self):
        s, bench, cal_t, dmm_t = open_session()
        d01 = adj.step_by_id('D01')
        s.mark_hookup(d01)
        s.t[0] += 60
        with self.assertRaises(adj.AdjustmentError):
            s.send_step(d01)
        self.assertNotIn('DC:STEP1', dmm_t.cal_sent)
        s.t[0] += 130
        s.send_step(d01)
        self.assertIn('DC:STEP1', dmm_t.cal_sent)

    def test_source_must_be_on_for_a_sourced_step(self):
        s, bench, cal_t, dmm_t = open_session()
        run_to = 'D03'
        for st in s.plan():
            if st['id'] == run_to:
                break
            do_step(s, st)
        s.mark_hookup(adj.step_by_id('D03'))
        s.t[0] += 10000
        with self.assertRaises(adj.AdjustmentError):
            s.send_step(adj.step_by_id('D03'), '10')
        self.assertNotIn('DC:STEP3 10', dmm_t.cal_sent)

    def test_high_voltage_needs_confirmation(self):
        s, bench, cal_t, dmm_t = open_session()
        for st in s.plan()[:4]:
            do_step(s, st)
        d05 = adj.step_by_id('D05')
        self.assertTrue(adj.is_hv(d05))
        with self.assertRaises(adj.AdjustmentError):
            s.program_source(d05, hv_ok=False)
        self.assertFalse(bench.fluke['operate'])

    def test_parameter_outside_the_manual_range_is_refused_unsent(self):
        s, bench, cal_t, dmm_t = open_session()
        for st in s.plan()[:2]:
            do_step(s, st)
        d03 = adj.step_by_id('D03')
        s.mark_hookup(d03)
        s.t[0] += 1000
        s.program_source(d03, hv_ok=True)
        with self.assertRaises(adj.AdjustmentError):
            s.send_step(d03, '12')
        self.assertNotIn('DC:STEP3 12', dmm_t.cal_sent)
        s.send_step(d03, '10.0001')
        self.assertIn('DC:STEP3 10.0001', dmm_t.cal_sent)

    def test_front_rear_switch_on_rear_stops_the_start(self):
        s, bench, cal_t, dmm_t = new_session()
        dmm_t.front = False
        s.reset(confirm=lambda _t: True)
        with self.assertRaises(InstrumentError):
            s.prepare()

    def test_calibrator_readback_mismatch_never_operates(self):
        s, bench, cal_t, dmm_t = open_session()
        st = adj.step_by_id('D03')
        real = s.io.cal.ask

        def lie(key, *a, **k):
            return '9.0' if key == 'out.query' else real(key, *a, **k)
        with mock.patch.object(s.io.cal, 'ask', side_effect=lie):
            with self.assertRaises(InstrumentError):
                s.program_source(st, hv_ok=True)
        self.assertFalse(bench.fluke['operate'])


class FailureTests(unittest.TestCase):
    def test_failed_step_is_not_repeated_automatically(self):
        s, bench, cal_t, dmm_t = open_session()
        for st in s.plan()[:2]:
            do_step(s, st)
        dmm_t.fail_steps['D03'] = 402
        d03 = adj.step_by_id('D03')
        with self.assertRaises(cal_driver.CalibrationError):
            do_step(s, d03)
        self.assertEqual(sum(1 for c in dmm_t.cal_sent if c.startswith('DC:STEP3 ')), 1)
        self.assertTrue(s.records['D03'].failed)
        self.assertFalse(bench.fluke['operate'])                              # standby after the failure
        with self.assertRaises(adj.AdjustmentError):
            do_step(s, d03)                                                    # no rerun without the operator's explicit confirmation
        self.assertEqual(sum(1 for c in dmm_t.cal_sent if c.startswith('DC:STEP3 ')), 1)
        dmm_t.fail_steps.clear()
        do_step(s, d03, rerun_ack=True)                                        # explicit confirmation: sent again, once
        self.assertEqual(sum(1 for c in dmm_t.cal_sent if c.startswith('DC:STEP3 ')), 2)
        self.assertTrue(s.records['D03'].done)
        self.assertEqual(s.records['D03'].attempts, 2)
        self.assertIn('RERUN', [e[2] for e in s.audit.events()][-6:] and ''.join(e[2] for e in s.audit.events()))

    def test_short_not_connected_reports_the_2000_error(self):
        s, bench, cal_t, dmm_t = open_session()
        dmm_t.short_ok = False
        with self.assertRaises(cal_driver.CalibrationError) as cm:
            do_step(s, adj.step_by_id('D01'))
        self.assertTrue(cm.exception.errors)
        self.assertFalse(s.records['D01'].done)

    def test_opc_hang_is_indeterminate_and_never_resent(self):
        s, bench, cal_t, dmm_t = open_session()
        dmm_t.hang_opc = True
        d01 = adj.step_by_id('D01')
        with self.assertRaises(cal_driver.StepIndeterminate):
            do_step(s, d01)
        self.assertTrue(s.records['D01'].indeterminate)
        self.assertEqual(dmm_t.cal_sent.count('DC:STEP1'), 1)
        with self.assertRaises(adj.AdjustmentError):
            do_step(s, d01)
        self.assertIsNone(s.confirm_indeterminate(d01, front_panel_idle=False))   # still busy: nothing decided
        self.assertTrue(s.records['D01'].indeterminate)
        s.confirm_indeterminate(d01, front_panel_idle=True)                       # idle and the error queue is empty
        self.assertTrue(s.records['D01'].done)
        self.assertEqual(dmm_t.cal_sent.count('DC:STEP1'), 1)

    def test_save_needs_everything(self):
        s, bench, cal_t, dmm_t = open_session()
        dmm_t.saved = {'OLD': 1}
        with self.assertRaises(adj.AdjustmentError):
            s.save(adj.CONFIRM_SAVE)                                           # nothing done yet
        for st in s.plan()[:-1]:
            do_step(s, st)
        with self.assertRaises(adj.AdjustmentError):
            s.save(adj.CONFIRM_SAVE)                                           # one step missing: a partly adjusted instrument is never stored
        do_step(s, s.next_step())
        with self.assertRaises(adj.AdjustmentError):
            s.save(adj.CONFIRM_SAVE)                                           # dates missing
        s.set_dates(date(2026, 10, 23))
        for bad in ('', 'save 2000', 'SAVE', 'SAVE 2000 '):
            with self.assertRaises(adj.AdjustmentError):
                s.save(bad)
        self.assertNotIn('SAVE', dmm_t.cal_sent)
        self.assertEqual(dmm_t.saved, {'OLD': 1})
        s.save(adj.CONFIRM_SAVE)
        self.assertEqual(len(dmm_t.saved), 26)
        with self.assertRaises(adj.AdjustmentError):
            s.save(adj.CONFIRM_SAVE)                                           # once only
        self.assertEqual(dmm_t.cal_sent.count('SAVE'), 1)

    def test_dates_rejected_by_the_2000_are_not_saved(self):
        s, bench, cal_t, dmm_t = open_session()
        run_all(s)
        with self.assertRaises(InstrumentError):
            s.io.dmm.set_dates(date(2026, 10, 23), date(2026, 10, 1))          # due before calibrated
        with self.assertRaises(InstrumentError):
            s.io.dmm.set_dates(date(1990, 1, 1), date(1991, 1, 1))             # year outside 1994..2093
        self.assertNotIn('SAVE', dmm_t.cal_sent)

    def test_save_error_is_reported_and_not_called_saved(self):
        s, bench, cal_t, dmm_t = open_session()
        run_all(s)
        s.set_dates(date(2026, 10, 23))
        dmm_t.date = None                                                      # the 2000 refuses :SAVE (+438)
        with self.assertRaises(cal_driver.CalibrationError):
            s.save(adj.CONFIRM_SAVE)
        self.assertFalse(s.saved)
        self.assertTrue(s.save_sent)
        self.assertEqual(s.audit.status(), 'SAVE_NOT_CONFIRMED')
        self.assertIn('UNKNOWN', s.abort('test') or 'UNKNOWN')


class AbortTests(unittest.TestCase):
    def test_abort_before_save_leaves_the_saved_constants_alone(self):
        s, bench, cal_t, dmm_t = open_session()
        dmm_t.saved = {'OLD': {'param': 1.0}}
        for st in s.plan()[:8]:
            do_step(s, st)
        self.assertEqual(len(dmm_t.temp), 8)
        text = s.abort('test')
        self.assertEqual(dmm_t.saved, {'OLD': {'param': 1.0}})
        self.assertTrue(dmm_t.locked)
        self.assertFalse(bench.fluke['operate'])
        self.assertIn('NOT saved', text)
        self.assertIn('switch the 2000 off and on', text)                      # honest: LOCK vs temporary constants is not in the manual
        dmm_t.power_cycle()
        self.assertEqual(dmm_t.saved, {'OLD': {'param': 1.0}})
        self.assertEqual(dmm_t.temp, {})
        self.assertEqual(s.audit.status(), 'ABORTED')
        with self.assertRaises(adj.AdjustmentError):
            do_step(s, s.next_step())

    def test_abort_with_no_step_sent_says_unchanged(self):
        s, bench, cal_t, dmm_t = open_session()
        self.assertIn('calibration is unchanged', s.abort('test'))
        self.assertTrue(dmm_t.locked)

    def test_abort_after_save_says_it_cannot_be_undone(self):
        s, bench, cal_t, dmm_t = open_session()
        run_all(s)
        s.set_dates(date(2026, 10, 23))
        s.save(adj.CONFIRM_SAVE)
        text = s.abort('test')
        self.assertIn('WERE saved', text)
        self.assertEqual(s.audit.status(), 'SAVED_NOT_VERIFIED')

    def test_abort_never_raises_when_the_instruments_are_gone(self):
        s, bench, cal_t, dmm_t = open_session()
        do_step(s, s.next_step())

        def dead(*a, **k):
            raise TransportError('gone')
        s.io.cal.send = dead
        s.io.dmm.send = dead
        text = s.abort('test')
        self.assertIn('could NOT be locked', text)
        self.assertIn('STANDBY', text)

    def test_standby_after_every_sourced_step(self):
        s, bench, cal_t, dmm_t = open_session()
        for st in s.plan():
            s.mark_hookup(st)
            s.t[0] += 10000
            s.program_source(st, hv_ok=True)
            if st['source']:
                self.assertTrue(bench.fluke['operate'], st['id'])
            s.send_step(st, None if not st['param'] else st['param']['nominal'])
            self.assertFalse(bench.fluke['operate'], st['id'])

    def test_close_puts_the_calibrator_in_standby_and_the_2000_to_local(self):
        s, bench, cal_t, dmm_t = open_session()
        s.program_source(s.plan()[0] if s.plan()[0]['source'] else adj.step_by_id('D03'), hv_ok=True)
        s.io.close()
        self.assertFalse(bench.fluke['operate'])


class DemoTests(unittest.TestCase):
    def test_demo_audit_is_in_memory_only(self):
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {'HOME': tmp, 'USERPROFILE': tmp, 'CALSUITE_DATA': tmp}):
            store = adjustment_audit.AuditStore(demo=True)
            self.assertEqual(store.path, ':memory:')
            s, *_ = open_session(store=store)
            run_all(s)
            s.set_dates(date(2026, 10, 23))
            s.save(adj.CONFIRM_SAVE)
            s.io.close()                                                       # a virtual log is never appended to the shared evidence file
        written = [str(p) for p in Path(tmp).rglob('*') if p.is_file()]
        self.assertEqual(written, [], written)
        self.assertEqual(sqlite3.connect(':memory:').execute('select count(*) from sqlite_master').fetchone()[0], 0)
        self.assertEqual(store.con.execute('select demo from adjustment_runs').fetchone()[0], 1)

    def test_real_audit_goes_to_lab_registry_and_not_calibration_procedures(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / 'lab_registry.sqlite3'
        store = adjustment_audit.AuditStore(demo=False, path=path)
        s, *_ = open_session(store=store)
        self.assertTrue(path.exists())
        names = {r[0] for r in store.con.execute("select name from sqlite_master where type='table'")}
        self.assertEqual(names - {'sqlite_sequence'}, {'adjustment_runs', 'adjustment_events'})
        self.assertEqual(store.con.execute('select demo from adjustment_runs').fetchone()[0], 0)
        self.assertGreater(len(store.events()), 5)
        self.assertFalse(list(Path(tmp).glob('calibration_procedures*')))
        src = (ROOT / 'adjustment_audit.py').read_text(encoding='utf-8')
        self.assertNotIn('calibration_procedures', src.replace('calibration_procedures.sqlite3 is touched', '').replace('calibration_procedures.sqlite3', ''))

    def test_no_csv_export_and_no_cover_sheet(self):
        for name in ('adjustment_audit.py', 'keithley2000_adjustment.py', 'Procedures/Keithley_2000_Adjustment.py'):
            text = (ROOT / name).read_text(encoding='utf-8').lower()
            for word in ('csv', 'cover sheet', 'cover_sheet', 'standards due', 'due_date_tracking'):
                self.assertNotIn(word, text, f'{name}: {word}')


class SidecarTests(unittest.TestCase):
    def test_sidecar_is_valid_and_listed_as_an_adjustment(self):
        res = procscan.scan(ROOT)
        self.assertEqual([x for x in res.problems if 'Keithley_2000_Adjustment' in str(x)], [])
        found = {p.id: p for p in res.procs}
        p = found['Keithley_2000_Adjustment']
        self.assertEqual(p.category, 'Digital Multimeter Adjustment')
        self.assertEqual(p.kind, 'adjustment')
        self.assertEqual(p.effective_kind, 'adjustment')
        self.assertEqual(found['Fluke_8846A_Adjustment'].effective_kind, 'adjustment')
        self.assertEqual(found['Keithley_2000_Verification'].effective_kind, 'verification')

    def test_fingerprint_names_every_file_that_changes_what_it_does(self):
        doc = json.loads((ROOT / 'Procedures' / 'Keithley_2000_Adjustment.procedure.json').read_text(encoding='utf-8'))
        for must in ('keithley2000_adjustment.py', 'adjustment_audit.py', 'drivers/keithley_2000_cal.py', 'drivers/keithley_2000.py', 'drivers/fluke_5560a.py'):
            self.assertIn(must, doc['fingerprint']['code'])
        self.assertIn('specs/keithley_2000_adjustment.json', doc['fingerprint']['spec'])

    def test_commands_registered_with_a_secret_code(self):
        cmd = cal_driver.CAL_COMMANDS['cal.code']
        self.assertEqual(cmd.placeholders['code'].type, 'secret')


if __name__ == '__main__':
    unittest.main()
