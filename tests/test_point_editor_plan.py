"""'The commands that apply to this point': the dry run of each engine's own point routine (procmods_plan) against the golden transcripts of the
real routines, and the promises of the dry run (nothing live is touched, other threads keep their clock, a failure is reported not raised)."""
import json
import re
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import point_editor_harness as PH  # noqa: E402
import cmdreg  # noqa: E402
import drivers  # noqa: E402
import procmods_plan  # noqa: E402
import procmods_pointdef as pdef  # noqa: E402

GOLDEN = ROOT / 'tests' / 'golden'


def golden(name, pattern):
    """[(case, point id, [wire commands the real routine sent])] from a golden transcript."""
    out = []
    for e in json.loads((GOLDEN / name).read_text(encoding='utf-8'))['entries']:
        if not re.search(pattern, e['case']):
            continue
        m = re.search(r'#([\w-]+)\]', e['case'])
        pid = m.group(1)
        pid = int(pid) if pid.isdigit() else pid
        out.append((e['case'], pid, [line.split('|', 2)[2] for line in e['log'] if line.split('|')[1] == '>>']))
    return out


class GoldenAgreement(unittest.TestCase):
    """The plan IS the real routine run on the simulated bench, so it must equal what the golden transcript recorded for the same point."""

    def agree(self, built, name, pattern, only=None, trim=lambda w: w, strict=True):
        self.addCleanup(built.stop)
        n = 0
        for case, pid, want in golden(name, pattern):
            if only and not only(case):
                continue
            live = built.app.pm_find_point(pid)
            self.assertIsNotNone(live, case)
            plan = built.app.pm_plan_point(live)
            if strict:
                self.assertEqual(plan.error, '', case)
            self.assertEqual(trim([e.wire for e in plan.entries]), want, case)
            n += 1
        self.assertGreater(n, 3)

    def test_truevolt(self):
        self.agree(PH.truevolt(), 'engine_truevolt_34470A.json', r'IO\.measure')

    def test_dacq(self):
        self.agree(PH.dacq('34970A'), 'engine_dacq_34970A.json', r'IO\.measure')

    def test_dacq_34972a(self):
        self.agree(PH.dacq('34972A'), 'engine_dacq_34972A.json', r'IO\.measure')

    def test_34401a(self):
        self.agree(PH.a34401(), 'engine_agilent_34401a.json', r'IO\.measure')

    def test_8846a(self):
        self.agree(PH.f8846(), 'engine_fluke_8846a.json', r'IO\.measure', strict=False)      # AC / frequency / capacitance are not automated: the commands up to the refusal agree

    def test_function_generator(self):
        self.agree(PH.fgen(), 'engine_fgen_33220A.json', r'IO\.measure\[(SELFTEST|ACAMP|LFFLAT)#')

    def test_mdo4000c_points_that_start_a_group(self):
        """The plan is the point as the FIRST of its group (the scope default setup is shown); the golden cases that start a group agree."""
        b = PH.mdo()
        self.addCleanup(b.stop)
        agreed = 0
        for case, pid, want in golden('engine_mdo4000c.json', r'Runner\.run_point'):
            plan = b.app.pm_plan_point(b.app.pm_find_point(pid))
            got = [e.wire for e in plan.entries]
            if got == want:
                agreed += 1
        self.assertGreaterEqual(agreed, 20)

    def test_handheld_calibrator_output_then_the_standby_after_the_reading(self):
        b = PH.handheld('115')
        self.addCleanup(b.stop)
        n = 0
        for case, pid, want in golden('engine_handheld_5522a.json', r'IO\.apply\[115 '):
            live = next(q for q in b.app.points if str(q['n']) == str(pid) or str(q['id']) == str(pid))
            plan = b.app.pm_plan_point(live)
            wires = [e.wire for e in plan.entries]
            self.assertEqual(wires[:-1], want, case)
            self.assertEqual(wires[-1], 'STBY', 'the run puts the calibrator in standby once the reading is typed')
            n += 1
        self.assertGreater(n, 3)


class Entries(unittest.TestCase):
    def setUp(self):
        self.b = PH.truevolt()
        self.addCleanup(self.b.stop)
        self.p = next(q for q in self.b.points if q['kind'] == 'ACV' and q['id'] == 68)

    def test_every_entry_carries_registry_key_risk_verified_and_the_read_back_pairing(self):
        plan = self.b.app.pm_plan_point(self.p)
        by = {e.key: e for e in plan.entries}
        self.assertEqual(by['conf.acv'].wire, 'CONF:VOLT:AC 0.1')
        self.assertEqual((by['conf.acv'].risk, by['conf.acv'].kind, by['conf.acv'].how), ('normal', 'set', 'send'))
        self.assertEqual(by['oper.on'].risk, 'output')
        self.assertEqual(by['err.query'].risk, 'locked')
        self.assertTrue(any(e.verified is False for e in plan.entries), 'an unverified command is flagged as such')
        self.assertEqual(by['conf.acv'].factory_wire, by['conf.acv'].wire)
        self.assertFalse(by['conf.acv'].changed)
        self.assertEqual(plan.entries[-1].wire, 'STBY', 'outputs go to standby after the point')

    def test_a_saved_point_override_shows_on_that_point_only(self):
        app = self.b.app
        key = app.pm_point_key(self.p)
        reg = cmdreg.merge_commands(drivers.Keysight34470A)
        self.b.h.env.store.add('command', pdef.point_command_target('Keysight34470A', 'conf.acv', key),
                               {'template': 'CONF:VOLT:AC {range:g}'}, 'model', 'trial', model='34470A', cmd=reg['conf.acv'],
                               driver_name='Keysight34470A', session=self.b.h.env.session)
        app.pm_state.load('')
        plan = app.pm_plan_point(self.p)
        row = next(e for e in plan.entries if e.key == 'conf.acv')
        self.assertEqual(row.wire, 'CONF:VOLT:AC 0.1')
        self.assertTrue(row.changed or row.override_uid, 'a changed command is marked')
        self.assertTrue(row.override_uid)
        other = next(q for q in self.b.points if q['kind'] == 'ACV' and q['id'] != 68)
        plan2 = app.pm_plan_point(other)
        self.assertFalse(any(e.override_uid for e in plan2.entries), 'another point is unchanged')

    def test_a_saved_extra_line_is_in_the_plan_where_it_will_be_sent(self):
        app = self.b.app
        key = app.pm_point_key(self.p)
        env = self.b.h.env
        env.store.add('command', pdef.extra_command_target('Keysight34470A', 'after', 1, key),
                      {'template': 'SENS:VOLT:AC:BAND 20', 'readback': 'SENS:VOLT:AC:BAND?', 'expect': '20'}, 'model', 'trial', model='34470A',
                      driver_name='Keysight34470A', session=env.session)
        env.store.add('command', pdef.extra_command_target('Fluke5560A', 'before', 1, key), {'template': 'FOO?'}, 'model', 'trial', model='34470A',
                      driver_name='Fluke5560A', session=env.session)
        app.pm_state.load('')
        plan = app.pm_plan_point(self.p)
        self.assertEqual(plan.entries[0].wire, 'FOO?', 'a before-line comes first')
        self.assertEqual(plan.entries[0].extra['phase'], 'before')
        self.assertEqual([e.wire for e in plan.entries[-2:]], ['SENS:VOLT:AC:BAND 20', 'SENS:VOLT:AC:BAND?'])
        self.assertTrue(all(e.verified is False for e in plan.entries if e.extra))

    def test_the_dry_run_never_touches_the_live_state(self):
        app = self.b.app
        st = app.pm_state
        before = (st.live.dirty, list(st.live.events), len(st.run_entries), app.io, id(st.oset))
        sleep0, mono0, wall0 = time.sleep, time.monotonic, time.time
        app.pm_plan_point(self.p)
        self.assertEqual((st.live.dirty, list(st.live.events), len(st.run_entries), app.io, id(st.oset)), before)
        self.assertIs(time.sleep, sleep0)
        self.assertIs(time.monotonic, mono0)
        self.assertIs(time.time, wall0)

    def test_the_plan_is_fast_because_waits_are_skipped(self):
        t0 = time.perf_counter()
        app = self.b.app
        for _ in range(5):
            app.pm_plan_point(self.p)
        self.assertLess(time.perf_counter() - t0, 10.0)


class DryClock(unittest.TestCase):
    def test_only_the_planning_thread_skips_its_waits(self):
        seen = {}

        def other():
            t = time.perf_counter()
            time.sleep(0.15)
            seen['slept'] = time.perf_counter() - t

        with procmods_plan.dry_clock():
            th = threading.Thread(target=other)
            th.start()
            t0, m0 = time.perf_counter(), time.monotonic()
            time.sleep(30)
            self.assertLess(time.perf_counter() - t0, 1.0)
            self.assertGreater(time.monotonic() - m0, 29.0, 'monotonic advances by the skipped time so busy-wait loops end')
            th.join()
        self.assertGreaterEqual(seen['slept'], 0.14, 'another thread really waits')

    def test_it_nests_and_always_restores(self):
        s0 = time.sleep
        with procmods_plan.dry_clock():
            with procmods_plan.dry_clock():
                time.sleep(5)
            time.sleep(5)
        self.assertIs(time.sleep, s0)
        with self.assertRaises(RuntimeError):
            with procmods_plan.dry_clock():
                raise RuntimeError('x')
        self.assertIs(time.sleep, s0)


class WhenThePlanCannotBeComplete(unittest.TestCase):
    def test_a_point_the_procedure_does_not_automate_says_so_and_keeps_what_was_recorded(self):
        b = PH.f8846()
        self.addCleanup(b.stop)
        ac = next(q for q in b.points if q['kind'] == 'ACV')
        plan = b.app.pm_plan_point(ac)
        self.assertIn('lab-verified', plan.error)
        self.assertFalse(plan.complete)
        self.assertTrue(plan.entries and plan.entries[0].wire == 'STBY')

    def test_the_default_for_an_engine_with_no_headless_routine_is_an_error_not_a_crash(self):
        class Bare:
            pass
        import procmods_engine
        plan = procmods_engine.ProcModsMixin.pm_plan_point(Bare(), {})
        self.assertFalse(plan.complete)

    def test_a_failing_build_is_reported_not_raised(self):
        b = PH.truevolt()
        self.addCleanup(b.stop)

        def build(_mods):
            raise RuntimeError('no bench')
        plan = procmods_plan.run_plan(b.app.pm_state, build, lambda io: None)
        self.assertIn('no bench', plan.error)

    def test_handheld_points_without_output_or_with_a_manual_calibrator_have_no_commands(self):
        import handheld_dmm as HH
        b = PH.handheld('115')
        self.addCleanup(b.stop)
        visual = next(q for q in b.points if not q.get('applied'))
        plan = b.app.pm_plan_point(visual)
        self.assertEqual(plan.entries, [])
        self.assertIn('no calibrator output', plan.note)
        sourced = next(q for q in b.points if q.get('applied'))
        b.app.cal_mode.set(HH.CAL_CHOICES[2])
        plan = b.app.pm_plan_point(sourced)
        self.assertEqual(plan.entries, [])
        self.assertIn('Manual', plan.note)

    def test_wavesurfer_shows_no_commands_and_says_why(self):
        b = PH.wavesurfer()
        self.addCleanup(b.stop)
        plan = b.app.pm_plan_point(b.app.pm_find_point('dcv:0'))
        self.assertFalse(plan.complete)
        self.assertEqual(plan.entries, [])
        self.assertIn('section', plan.error)


if __name__ == '__main__':
    unittest.main()
