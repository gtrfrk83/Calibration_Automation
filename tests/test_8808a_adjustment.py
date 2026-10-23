"""Fluke 8808A guided adjustment: spec, driver, session logic, audit record and the sidecar, on the simulated bench (no tkinter, no hardware).

The simulated 8808A (drivers/simulated_8808a_cal.py) records every calibration line it receives (.events), the constants per point (.constants) and what an EXIT inside a
function leaves behind (.cal_error, .incomplete), so the tests can prove what each action sent and what an abort leaves.  Its reply formats are SIMULATION CHOICES, not facts
about the real meter (the manual does not print them).
"""
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import adjustment_audit  # noqa: E402
import drivers  # noqa: E402
import fluke8808a_adjustment as adj  # noqa: E402
import procscan  # noqa: E402
from drivers import fluke_8808a_cal as cal_driver  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.simulated_8808a_cal import make_8808a_cal_bench  # noqa: E402

ACKS = ('conditions', 'as_found', 'authorised', 'notice', 'ready')
CAL_NAME = {'5522A': 'Fluke 5522A', '5560A': 'Fluke 5560A', '5520A': 'Fluke 5520A'}


def new_session(cal='5522A', scope=adj.ALL_FUNCTIONS, demo=True, store=None, **dmm_kw):
    bench, cal_t, dmm_t = make_8808a_cal_bench(cal, **dmm_kw)
    io = adj.AdjustIO('COM3', 'COM9', CAL_NAME[cal], transports=(dmm_t, cal_t), virtual=True)
    audit = store or adjustment_audit.AuditStore(demo=demo)
    audit.start_run(adj.INSTRUMENT, 'ASSET1', 'SN1', 'Tech', uut_idn=io.ident, scope='+'.join(scope))
    s = adj.Session(io, audit, scope=scope, wait=lambda _s: None)
    return s, bench, cal_t, dmm_t


def open_session(*a, **k):
    s, bench, cal_t, dmm_t = new_session(*a, **k)
    s.reset(confirm=lambda _t: True)
    s.prepare()
    for key in ACKS:
        s.acknowledge(key)
    s.enter_calibration()
    return s, bench, cal_t, dmm_t


def do_point(s, bench, st, **kw):
    """The window's per-point work: function start, value, hook-up, safety, source, point."""
    if not s.active_function:
        s.start_function(confirmed=True)
    if s.dmm.state == 'VALUE':
        if st['characterize'] and 'characterized' not in kw:
            kw['waive'] = True
        s.set_reference(st, **kw)
    s.mark_hookup(st)
    own = st['id'] in adj.own_standard_ids(s.cal_key)
    bench.external = ('V', 1.9, float(st['point']['value'])) if own else None
    if own:
        s.acknowledge_own_standard(st)
    if adj.is_hv(st) or adj.is_high_current(st):
        s.acknowledge_hv(st)
    s.program_source(st)
    return s.send_point(st, confirmed=True)


def run_all(s, bench):
    while s.next_step():
        do_point(s, bench, s.next_step())


def enters(dmm_t, n):
    return [e for e in dmm_t.events if e[0] == 'ENTER' and e[1] == n]


class SpecTests(unittest.TestCase):
    def test_counts_and_order(self):
        self.assertEqual(len(adj.STEPS), 124)
        self.assertEqual([s['id'] for s in adj.STEPS], [f'S{i:03d}' for i in range(1, 125)])
        counts = {f['id']: len(f['steps']) for f in adj.FUNCTIONS}
        self.assertEqual(counts, {'VDC': 21, 'VAC': 21, 'FREQ': 12, 'OHMS': 28, 'AAC': 17, 'ADC': 25})
        self.assertEqual([f['id'] for f in adj.FUNCTIONS], ['VDC', 'VAC', 'FREQ', 'OHMS', 'AAC', 'ADC'])      # Table 3-9's order
        self.assertEqual(len(adj.steps_in_scope(('FREQ',))), 12)

    def test_ohms_wires(self):
        wires = [s['wire'] for s in adj.function_steps('OHMS')]
        self.assertEqual(wires, [4] * 12 + [2] * 16)

    def test_the_seven_table_vs_list_discrepancies_are_flagged(self):
        self.assertEqual({s['n'] for s in adj.STEPS if s['conflict']}, {23, 27, 31, 35, 39, 92, 96})
        self.assertEqual(sorted(adj.SPEC['discrepancies'][0]['steps']), ['S023', 'S027', 'S031', 'S035', 'S039', 'S092', 'S096'])
        for s in adj.STEPS:
            if s['conflict']:
                self.assertIsNotNone(s['list_value'])
                self.assertFalse(adj.match(adj.point_value(s), float(Decimal(s['list_value']))))

    def test_characterized_ranges(self):
        self.assertEqual({s['n'] for s in adj.STEPS if s['characterize']}, set(range(101, 109)) | set(range(113, 121)))

    def test_zero_points_need_no_output_except_ohms(self):
        zeros = [s for s in adj.STEPS if s['zero']]
        self.assertEqual({s['function'] for s in zeros}, {'VDC', 'VAC', 'OHMS', 'AAC', 'ADC'})
        for s in zeros:
            self.assertEqual(s['source'] is None, s['function'] != 'OHMS')
        self.assertEqual(sum(1 for s in adj.STEPS if s['source']), 120)

    def test_frequency_steps_source_1v9(self):
        for s in adj.function_steps('FREQ'):
            self.assertEqual((s['source']['kind'], float(s['source']['value'])), ('ACV', 1.9))

    def test_si_text_is_display_only(self):
        self.assertEqual(adj.si_text(0.01, 'V'), '10 mV')
        self.assertEqual(adj.si_text(1e6, 'ohm'), '1 MΩ')
        self.assertEqual(adj.si_text(2e-4, 'A'), '200 µA')
        self.assertEqual(adj.point_value(adj.STEP_BY_ID['S002']), -0.1999)       # the spec keeps the base-unit number

    def test_hookup_groups_have_text_and_known_titles(self):
        for s in adj.STEPS:
            self.assertIn(s['group'], adj.GROUP_TITLE)
            for cal in ('5522A', '5560A', '5520A'):
                self.assertTrue(adj.hookup_text(s, cal))


class DriverTests(unittest.TestCase):
    def test_parse_recommended(self):
        r = cal_driver.parse_lines(['0.1999 V, 0 HZ'])
        self.assertAlmostEqual(r.recommended.value, 0.1999)
        r = cal_driver.parse_lines(['190 MV, 1000 HZ'])
        self.assertAlmostEqual(r.recommended.value, 0.19)
        r = cal_driver.parse_lines(['1000 OHM, 0 HZ W4'])
        self.assertTrue(r.recommended.w4)
        r = cal_driver.parse_lines(['Select a Function or input EXIT to QUIT!'])
        self.assertTrue(r.idle)
        self.assertEqual(cal_driver.parse_lines(['!>']).error_prompt, '!>')
        self.assertTrue(cal_driver.parse_lines(['=>']).accepted)

    def test_reference_text_is_six_digits(self):
        rec = cal_driver.parse_lines(['0.1999 V, 0 HZ']).recommended
        self.assertEqual(cal_driver.reference_text(Decimal('0.199912'), rec), '0.199912')
        with self.assertRaises(InstrumentError):
            cal_driver.reference_text(Decimal('0.199912345'), rec)            # never rounded silently
        self.assertEqual(cal_driver.reference_text(Decimal('10'), rec), '10')

    def test_registry_flags_and_pages(self):
        cmds = cal_driver.CAL_COMMANDS
        for key in ('cal.enter', 'cal.func.vdc', 'cal.func.vac', 'cal.func.adc', 'cal.func.aac', 'cal.func.ohms', 'cal.func.freq', 'cal.exit'):
            self.assertTrue(cmds[key].verified, key)
        self.assertFalse(cmds['cal.calref'].verified)              # the number format is not printed
        self.assertFalse(cmds['cal.enter_key'].verified)           # the Enter key encoding is not printed
        self.assertEqual(cmds['cal.enter'].template, '*TER')
        for cmd in cmds.values():
            self.assertEqual(cmd.risk, 'locked')                   # never overridable
        self.assertTrue(all(c.ref for c in cmds.values()))

    def test_exactly_one_star_ter_and_enter_dialog(self):
        s, bench, cal_t, dmm_t = open_session()
        s.start_function(confirmed=True)
        self.assertEqual([e for e in dmm_t.events if e[0] == 'TER'], [('TER',)])
        with self.assertRaises(InstrumentError):
            s.dmm.enter_cal_mode()

    def test_unknown_function_and_wrong_state_refused_without_sending(self):
        s, bench, cal_t, dmm_t = open_session()
        n = len(dmm_t.events)
        with self.assertRaises(InstrumentError):
            s.dmm.select_function('XYZ')
        with self.assertRaises(InstrumentError):
            s.dmm.confirm_value()
        self.assertEqual(len(dmm_t.events), n)


class RunTests(unittest.TestCase):
    def full_run(self, cal):
        s, bench, cal_t, dmm_t = open_session(cal)
        standby_after = []
        orig = s.send_point

        def spy(st, **kw):
            r = orig(st, **kw)
            standby_after.append(bool(bench.fluke['operate']))
            return r
        s.send_point = spy
        run_all(s, bench)
        return s, bench, cal_t, dmm_t, standby_after

    def test_full_run_every_calibrator(self):
        for cal in ('5522A', '5560A', '5520A'):
            with self.subTest(cal=cal):
                s, bench, cal_t, dmm_t, standby_after = self.full_run(cal)
                self.assertTrue(s.all_done())
                self.assertEqual(len(dmm_t.constants), 124)
                self.assertEqual(dmm_t.completed, set(adj.ALL_FUNCTIONS))
                self.assertEqual(len(enters(dmm_t, 1)), 124)
                self.assertEqual(len(enters(dmm_t, 2)), 124)            # the second Enter is sent once per point, never repeated
                self.assertFalse(any(standby_after))                    # the calibrator is in standby after every point
                s.finish()
                self.assertTrue(s.finished and not s.cal_mode)
                self.assertEqual(dmm_t.events[-1], ('EXIT',))
                self.assertFalse(dmm_t.cal_error)
                self.assertEqual(s.audit.status(), 'COMPLETED_NOT_VERIFIED')

    def test_one_function_scope(self):
        s, bench, cal_t, dmm_t = open_session(scope=('FREQ',))
        run_all(s, bench)
        self.assertEqual(set(dmm_t.constants), {f'S{n:03d}' for n in range(43, 55)})
        s.finish()

    def test_input_checked_by_the_simulated_meter(self):
        """The calibrator really outputs what each step asks (the simulated meter rejects an input more than 1 % off), so a wrong output could not pass."""
        s, bench, cal_t, dmm_t = open_session()
        s.start_function(confirmed=True)
        st = s.next_step()
        s.set_reference(st)
        s.mark_hookup(st)
        s.program_source(st)                                           # S001: zero, standby
        s.send_point(st, confirmed=True)
        st = s.next_step()
        s.set_reference(st)
        s.mark_hookup(st)
        bench.fluke.update(operate=True, volts=-0.15, unit='V', freq=0.0)      # not -0.1999 V
        s.source_on = st['id']
        with self.assertRaises(cal_driver.CalibrationError):
            s.send_point(st, confirmed=True)
        self.assertFalse(bench.fluke['operate'])                        # standby after the error

    def test_values_in_each_function_match_table(self):
        s, bench, cal_t, dmm_t, _ = self.full_run('5522A')
        for st in adj.STEPS:
            ref = dmm_t.constants[st['id']]['ref']
            self.assertTrue(adj.match(ref, adj.point_value(st)), (st['id'], ref))


class ConfirmationTests(unittest.TestCase):
    def test_enter_calibration_needs_every_confirmation(self):
        s, bench, cal_t, dmm_t = new_session()
        s.reset(confirm=lambda _t: True)
        for key in ACKS:
            with self.assertRaises(adj.AdjustmentError):
                s.enter_calibration()
            s.acknowledge(key)
        self.assertEqual([e for e in dmm_t.events if e[0] == 'TER'], [])
        s.enter_calibration()
        self.assertEqual(len([e for e in dmm_t.events if e[0] == 'TER']), 1)

    def test_function_start_needs_confirmation(self):
        s, bench, cal_t, dmm_t = open_session()
        with self.assertRaises(adj.AdjustmentError):
            s.start_function()
        self.assertFalse([e for e in dmm_t.events if e[0] == 'FUNC'])

    def test_point_needs_confirmation_and_order(self):
        s, bench, cal_t, dmm_t = open_session()
        s.start_function(confirmed=True)
        st = s.next_step()
        s.set_reference(st)
        with self.assertRaises(adj.AdjustmentError):
            s.send_point(st, confirmed=False)
        self.assertEqual(enters(dmm_t, 2), [])
        with self.assertRaises(adj.AdjustmentError):
            s.send_point(adj.STEP_BY_ID['S005'], confirmed=True)       # not the next step
        self.assertEqual(enters(dmm_t, 2), [])

    def test_source_must_be_on_before_the_point(self):
        s, bench, cal_t, dmm_t = open_session()
        s.start_function(confirmed=True)
        run_to = adj.STEP_BY_ID['S002']
        do_point(s, bench, s.next_step())
        s.set_reference(run_to)
        with self.assertRaises(adj.AdjustmentError):
            s.send_point(run_to, confirmed=True)
        self.assertEqual(len(enters(dmm_t, 2)), 1)

    def test_high_voltage_is_asked_once_per_hookup_group(self):
        s, bench, cal_t, dmm_t = open_session(scope=('VDC',))
        hv = [st for st in adj.function_steps('VDC') if adj.is_hv(st)]
        self.assertGreaterEqual(len(hv), 1)
        # run up to the first high-voltage step
        s.start_function(confirmed=True)
        while s.next_step() and not adj.is_hv(s.next_step()):
            do_point(s, bench, s.next_step())
        st = s.next_step()
        s.set_reference(st)
        s.mark_hookup(st)
        with self.assertRaises(adj.AdjustmentError):
            s.program_source(st)                                         # not confirmed: nothing is output
        self.assertFalse(bench.fluke['operate'])
        s.acknowledge_hv(st)
        s.program_source(st)
        self.assertTrue(bench.fluke['operate'])
        s.send_point(st, confirmed=True)
        self.assertEqual(s.hv_group, st['group'])
        # the same group: no second question
        nxt = s.next_step()
        if nxt and nxt['group'] == st['group'] and adj.is_hv(nxt):
            s.set_reference(nxt)
            s.mark_hookup(nxt)
            s.program_source(nxt)

    def test_own_standard_needs_confirmation_and_keeps_calibrator_in_standby(self):
        s, bench, cal_t, dmm_t = open_session(scope=('FREQ',))
        st = adj.STEP_BY_ID['S054']
        for _ in range(11):
            do_point(s, bench, s.next_step())
        self.assertEqual(s.next_step()['id'], 'S054')
        s.set_reference(st)
        with self.assertRaises(adj.AdjustmentError):
            s.program_source(st)
        s.acknowledge_own_standard(st)
        s.program_source(st)
        self.assertFalse(bench.fluke['operate'])
        self.assertTrue(s.records['S054'].own_standard)

    def test_calibrator_picker_offers_only_s054_as_own_standard(self):
        for cal in ('5522A', '5520A', '5560A'):
            self.assertEqual(adj.own_standard_ids(cal), {'S054'})


class ValueDecisionTests(unittest.TestCase):
    def test_meter_value_equal_to_table_sends_no_calref(self):
        s, bench, cal_t, dmm_t = open_session()
        s.start_function(confirmed=True)
        st = s.next_step()
        info = s.review(st)
        self.assertEqual(info['verdict'], 'table')
        s.set_reference(st)
        self.assertFalse([e for e in dmm_t.events if e[0] == 'CALREF'])

    def test_conflict_follow_the_meter(self):
        s, bench, cal_t, dmm_t = open_session(scope=('VAC',))
        dmm_t.use_list_values = True
        s.start_function(confirmed=True)
        while s.next_step()['n'] != 23:
            do_point(s, bench, s.next_step())
        st = s.next_step()
        info = s.review(st)
        self.assertEqual(info['verdict'], 'list')
        self.assertIn('differ', info['text'])
        out = s.set_reference(st, choose='meter')
        self.assertAlmostEqual(out, float(Decimal(st['list_value'])))
        self.assertFalse([e for e in dmm_t.events if e[0] == 'CALREF'])
        s.mark_hookup(st)
        s.acknowledge_hv(st)
        s.program_source(st)
        s.send_point(st, confirmed=True)

    def test_conflict_use_table_value_sends_calref(self):
        s, bench, cal_t, dmm_t = open_session(scope=('VAC',))
        dmm_t.use_list_values = True
        s.start_function(confirmed=True)
        while s.next_step()['n'] != 23:
            do_point(s, bench, s.next_step())
        st = s.next_step()
        out = s.set_reference(st, choose='table')
        self.assertAlmostEqual(out, adj.point_value(st))
        self.assertEqual([e for e in dmm_t.events if e[0] == 'CALREF'], [('CALREF', '0.01')])
        s.mark_hookup(st)
        s.program_source(st)
        s.send_point(st, confirmed=True)
        self.assertAlmostEqual(dmm_t.constants[st['id']]['ref'], 0.01)

    def test_table_choice_refused_when_meter_agrees_with_table(self):
        s, bench, cal_t, dmm_t = open_session()
        s.start_function(confirmed=True)
        with self.assertRaises(adj.AdjustmentError):
            s.set_reference(s.next_step(), choose='table')
        self.assertEqual(enters(dmm_t, 1), [])

    def test_unexpected_recommendation_needs_acknowledgement(self):
        s, bench, cal_t, dmm_t = open_session()
        dmm_t.recommend['S001'] = 0.15
        s.start_function(confirmed=True)
        st = s.next_step()
        self.assertEqual(s.review(st)['verdict'], 'other')
        with self.assertRaises(adj.AdjustmentError):
            s.set_reference(st)
        self.assertEqual(enters(dmm_t, 1), [])
        s.set_reference(st, unexpected_ack=True)
        self.assertEqual(len(enters(dmm_t, 1)), 1)

    def test_characterized_step_needs_value_or_explicit_waiver(self):
        s, bench, cal_t, dmm_t = open_session(scope=('ADC',))
        s.start_function(confirmed=True)
        while not s.next_step()['characterize']:
            do_point(s, bench, s.next_step())
        st = s.next_step()
        with self.assertRaises(adj.AdjustmentError):
            s.set_reference(st)
        self.assertEqual(len(enters(dmm_t, 1)), st['n'] - 100)
        with self.assertRaises(adj.AdjustmentError):
            s.set_reference(st, characterized='0.123456789')            # more than six digits
        want = float(Decimal(s.review(st)['meter']))
        with self.assertRaises(adj.AdjustmentError):
            s.set_reference(st, characterized=f'{want * 1.5:.5g}')      # far from the recommended value
        s.set_reference(st, characterized=f'{want * 1.0001:.6g}')
        self.assertTrue(s.records[st['id']].characterized)
        self.assertEqual(len([e for e in dmm_t.events if e[0] == 'CALREF']), 1)
        self.assertTrue(s.records[st['id']].calref)

    def test_waiver_is_logged(self):
        s, bench, cal_t, dmm_t = open_session(scope=('ADC',))
        s.start_function(confirmed=True)
        while not s.next_step()['characterize']:
            do_point(s, bench, s.next_step())
        st = s.next_step()
        s.set_reference(st, waive=True)
        self.assertTrue(s.records[st['id']].waived)
        self.assertIn('WAIVED', [r[3] for r in s.audit.events()])

    def test_calref_without_prompt_needs_display_confirmation(self):
        s, bench, cal_t, dmm_t = open_session(scope=('ADC',))
        dmm_t.cal_prompts = False
        s.start_function(confirmed=True)
        while not s.next_step()['characterize']:
            st0 = s.next_step()
            dmm_t.cal_prompts = True
            do_point(s, bench, st0)
            dmm_t.cal_prompts = False
        st = s.next_step()
        meter = s.review(st)['meter']
        with self.assertRaises(adj.NeedsDisplayConfirmation):
            s.set_reference(st, characterized=f'{meter:.6g}')
        self.assertEqual(enters(dmm_t, 1)[-1][2] if enters(dmm_t, 1) else None, enters(dmm_t, 1)[-1][2] if enters(dmm_t, 1) else None)
        before = len(enters(dmm_t, 1))
        self.assertEqual(before, st['n'] - 100)                         # the first Enter of THIS point was not sent
        s.dmm.state                                                     # still waiting
        with self.assertRaises(adj.AdjustmentError):
            s.send_point(st, confirmed=True)
        self.assertTrue(s.confirm_calref_display(st, True))
        self.assertEqual(len(enters(dmm_t, 1)), before + 1)

    def test_calref_display_declined_sends_nothing(self):
        s, bench, cal_t, dmm_t = open_session(scope=('ADC',))
        s.start_function(confirmed=True)
        while not s.next_step()['characterize']:
            do_point(s, bench, s.next_step())
        st = s.next_step()
        dmm_t.cal_prompts = False
        meter = s.review(st)['meter']
        with self.assertRaises(adj.NeedsDisplayConfirmation):
            s.set_reference(st, characterized=f'{meter:.6g}')
        before = len(enters(dmm_t, 1))
        self.assertFalse(s.confirm_calref_display(st, False))
        self.assertEqual(len(enters(dmm_t, 1)), before)


class FailureTests(unittest.TestCase):
    def test_meter_refuses_a_point_nothing_is_repeated(self):
        s, bench, cal_t, dmm_t = open_session()
        dmm_t.fail_points['S003'] = '!>'
        run_two = [adj.STEP_BY_ID['S001'], adj.STEP_BY_ID['S002']]
        for st in run_two:
            do_point(s, bench, st)
        st = s.next_step()
        with self.assertRaises(cal_driver.CalibrationError):
            do_point(s, bench, st)
        self.assertEqual(len(enters(dmm_t, 2)), 3)
        self.assertFalse(bench.fluke['operate'])                        # standby after the error
        rec = s.records['S003']
        self.assertTrue(rec.failed and not rec.done)
        self.assertIn('!>', ' '.join(rec.errors))
        with self.assertRaises(adj.AdjustmentError):
            s.send_point(st, confirmed=True)                            # a rerun needs an explicit acknowledgement
        self.assertEqual(len(enters(dmm_t, 2)), 3)
        dmm_t.fail_points.clear()
        s.program_source(st)
        s.send_point(st, confirmed=True, rerun_ack=True)
        self.assertEqual(len(enters(dmm_t, 2)), 4)
        self.assertTrue(rec.done)

    def test_no_completion_is_indeterminate_and_never_resent(self):
        s, bench, cal_t, dmm_t = open_session()
        s.io.dmm.POINT_TIMEOUT_S = 0.1
        dmm_t.hang_points.add('S001')
        s.start_function(confirmed=True)
        st = s.next_step()
        s.set_reference(st)
        s.mark_hookup(st)
        s.program_source(st)
        with self.assertRaises(cal_driver.StepIndeterminate):
            s.send_point(st, confirmed=True)
        rec = s.records['S001']
        self.assertTrue(rec.indeterminate and not rec.done)
        self.assertEqual(len(enters(dmm_t, 2)), 1)
        self.assertFalse(bench.fluke['operate'])
        self.assertFalse(s.recheck_indeterminate(st))                   # read-only: nothing new arrives
        self.assertEqual(len(enters(dmm_t, 2)), 1)

    def test_star_ter_refused(self):
        for mode in ('silent', 'error'):
            with self.subTest(mode=mode):
                s, bench, cal_t, dmm_t = new_session()
                dmm_t.refuse_ter = mode
                s.reset(confirm=lambda _t: True)
                for key in ACKS:
                    s.acknowledge(key)
                with self.assertRaises(Exception):
                    s.enter_calibration()
                self.assertFalse(s.cal_mode)
                self.assertFalse(dmm_t.cal_mode)
                self.assertIn('FAILED', [r[3] for r in s.audit.events() if r[2] == 'ENTER CAL'])

    def test_wrong_terminal_message_is_warned(self):
        s, bench, cal_t, dmm_t = open_session(scope=('ADC',))
        s.start_function(confirmed=True)
        while s.next_step()['group'] != 'I10A':
            do_point(s, bench, s.next_step())
        st = s.next_step()
        s.set_reference(st)
        self.assertEqual(s.message_warning(st), '')
        s.records[st['id']].messages = ['MA']
        self.assertIn('check the terminal', s.message_warning(st))


class AbortTests(unittest.TestCase):
    def test_abort_inside_a_function_sends_exit_and_says_cal_error(self):
        s, bench, cal_t, dmm_t = open_session()
        for _ in range(3):
            do_point(s, bench, s.next_step())
        text = s.abort('test')
        self.assertEqual(dmm_t.events[-1], ('EXIT',))
        self.assertTrue(dmm_t.cal_error)
        self.assertEqual(dmm_t.incomplete, ['VDC'])
        self.assertIn('NOT completed (3 of 21', text)
        self.assertIn('CAL ERROR', text)
        self.assertIn('does not say', text)
        self.assertFalse(bench.fluke['operate'])
        self.assertTrue(s.aborted and not s.cal_mode)
        self.assertEqual(s.audit.status(), 'ABORTED_INCOMPLETE_FUNCTION')

    def test_abort_before_any_point_leaves_calibration_unchanged(self):
        s, bench, cal_t, dmm_t = open_session()
        text = s.abort('test')
        self.assertIn('calibration is unchanged', text)
        self.assertEqual(dmm_t.constants, {})

    def test_abort_with_a_hot_calibrator_goes_to_standby(self):
        s, bench, cal_t, dmm_t = open_session()
        s.start_function(confirmed=True)
        bench.fluke['operate'] = True
        s.abort('test')
        self.assertFalse(bench.fluke['operate'])

    def test_abort_between_functions_names_the_complete_ones(self):
        s, bench, cal_t, dmm_t = open_session(scope=('VDC', 'VAC'))
        while s.next_step()['function'] == 'VDC':
            do_point(s, bench, s.next_step())
        text = s.abort('test')
        self.assertIn('VDC', text)
        self.assertFalse(dmm_t.cal_error)

    def test_close_leaves_the_calibration_mode(self):
        s, bench, cal_t, dmm_t = open_session()
        s.io.close()
        self.assertEqual([e for e in dmm_t.events if e == ('EXIT',)], [('EXIT',)])
        self.assertFalse(bench.fluke['operate'])

    def test_finish_needs_every_step(self):
        s, bench, cal_t, dmm_t = open_session(scope=('FREQ',))
        with self.assertRaises(adj.AdjustmentError):
            s.finish()
        self.assertNotIn(('EXIT',), dmm_t.events)


class ResetTests(unittest.TestCase):
    def test_reset_once_per_connection(self):
        s, bench, cal_t, dmm_t = new_session()
        rep = s.reset(confirm=lambda _t: True)
        self.assertIsNotNone(rep)
        self.assertTrue(s.io.reset_done)
        s2 = adj.Session(s.io, s.audit, wait=lambda _s: None)
        self.assertIsNone(s2.reset(confirm=lambda _t: self.fail('no second UUT notice')))
        outcomes = [(r[2], r[3]) for r in s.audit.events()]
        self.assertIn(('RESET', 'SKIPPED'), outcomes)

    def test_declined_reset_touches_nothing(self):
        import reset_startup
        s, bench, cal_t, dmm_t = new_session()
        with self.assertRaises(reset_startup.ResetDeclined):
            s.reset(confirm=lambda _t: False)
        self.assertFalse(s.io.reset_done)
        self.assertEqual(dmm_t.events, [])


class DemoTests(unittest.TestCase):
    def test_demo_is_in_memory_and_virtual_logs_nothing(self):
        s, bench, cal_t, dmm_t = open_session(demo=True)
        self.assertEqual(s.audit.path, ':memory:')
        self.assertTrue(s.io.log.virtual)
        self.assertEqual(s.audit.con.execute('select demo from adjustment_runs').fetchone()[0], 1)

    def test_real_audit_goes_to_lab_registry_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = adjustment_audit.AuditStore(demo=False, path=Path(tmp) / 'lab_registry.sqlite3')
            s, bench, cal_t, dmm_t = open_session(demo=False, store=store, scope=('FREQ',))
            run_all(s, bench)
            s.finish()
            self.assertEqual(store.con.execute('select demo from adjustment_runs').fetchone()[0], 0)
            self.assertGreater(len(store.events()), 50)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir() if not p.name.endswith('-journal')), ['lab_registry.sqlite3'])
            store.close()

    def test_no_password_cover_sheet_csv_or_due_tracking_in_the_sources(self):
        for name in ('fluke8808a_adjustment.py', 'Procedures/Fluke_8808A_Adjustment.py', 'drivers/fluke_8808a_cal.py'):
            text = (ROOT / name).read_text(encoding='utf-8').lower()
            for word in ('csv', 'cover sheet', 'cover_sheet', 'standards due', 'getpass', 'askstring'):
                self.assertNotIn(word, text, f'{name}: {word}')

    def test_no_pdf_record_is_claimed(self):
        text = (ROOT / 'Procedures/Fluke_8808A_Adjustment.py').read_text(encoding='utf-8')
        self.assertNotIn('reportlab', text)


class SidecarTests(unittest.TestCase):
    def test_sidecar_is_valid_and_listed_as_an_adjustment(self):
        res = procscan.scan(ROOT)
        self.assertEqual([x for x in res.problems if 'Fluke_8808A_Adjustment' in str(x)], [])
        found = {p.id: p for p in res.procs}
        p = found['Fluke_8808A_Adjustment']
        self.assertEqual(p.category, 'Digital Multimeter Adjustment')
        self.assertEqual(p.kind, 'adjustment')
        self.assertEqual(p.effective_kind, 'adjustment')
        self.assertEqual(found['Fluke_8808A_Verification'].effective_kind, 'verification')

    def test_fingerprint_names_every_file_that_changes_what_it_does(self):
        doc = json.loads((ROOT / 'Procedures' / 'Fluke_8808A_Adjustment.procedure.json').read_text(encoding='utf-8'))
        for must in ('fluke8808a_adjustment.py', 'adjustment_audit.py', 'drivers/fluke_8808a_cal.py', 'drivers/fluke_8808a.py', 'drivers/fluke_5560a.py'):
            self.assertIn(must, doc['fingerprint']['code'])
        self.assertIn('specs/fluke_8808a_adjustment.json', doc['fingerprint']['spec'])
        self.assertEqual(doc['hookup']['diagram_prefixes'], ['hook_8808A'])

    def test_verification_fingerprint_does_not_include_the_new_driver(self):
        doc = json.loads((ROOT / 'Procedures' / 'Fluke_8808A_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertNotIn('drivers/fluke_8808a_cal.py', doc['fingerprint']['code'])

    def test_driver_exported(self):
        self.assertIs(drivers.Fluke8808ACal, cal_driver.Fluke8808ACal)


if __name__ == '__main__':
    unittest.main()
