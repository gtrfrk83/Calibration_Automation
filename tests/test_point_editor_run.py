"""The per-point editor in a RUNNING procedure: the real Truevolt App on the simulated bench, a scripted technician using the point model while the
worker thread measures.  Proved: commands and extra lines reach the point they were typed for and no other, an unmodified run is byte-identical,
an edit made during a point reaches the next point (never the one in flight), the point in flight cannot be edited, a failed read-back stops the
point and is never retried."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402

import cmdreg  # noqa: E402
import drivers  # noqa: E402
import procmods_point_model as PM  # noqa: E402
import procmods_pointdef as pdef  # noqa: E402
import truevolt_verification as T  # noqa: E402
from drivers.simulated import make_dmm_bench  # noqa: E402


class Run(unittest.TestCase):
    MODEL = '34470A'

    def setUp(self):
        self.h = H.EngineHarness().start(T)
        self.addCleanup(self.h.stop)
        p = mock.patch('time.sleep', side_effect=lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.reg = cmdreg.merge_commands(drivers.Keysight34470A)

    def make(self, n=3):
        h = self.h
        app = T.App(h.root, self.MODEL, demo=False)
        h.app = app
        st = app.pm_state
        st.store, st.devmode = h.env.store, h.env.dm
        app.asset.set('A-100')
        app.serial.set('S-1')
        _b, ft, dt = make_dmm_bench(self.MODEL)
        app.io = T.IO('sim', 'sim', transports=(dt, ft), mods=st)
        dt.terminals = 'FRON'
        self.marks = []
        orig = app.io.measure

        def measure(p):
            self.marks.append(len(self.wire(app)))
            return orig(p)
        app.io.measure = measure
        self.points = [p for p in T.POINTS if p['kind'] == 'DCV' and p['source'] == 'calibrator'][:n]
        return app

    def go(self, app):
        app.execute(self.points)
        self.assertTrue(self.h.pump(60), 'the run did not finish')

    def wire(self, app):
        return [t for _ts, _i, d, t in app.io.log.entries if d == '>>']

    def per_point(self, app):
        """One list of wire lines per point, cut where each io.measure call began."""
        w, marks = self.wire(app), self.marks + [None]
        return [w[marks[i]:marks[i + 1]] for i in range(len(self.marks))]

    def save(self, kind, target, value, **kw):
        env = self.h.env
        return env.store.add(kind, target, value, 'model', 'test', model=self.MODEL, session=env.session, **kw)

    def key(self, p):
        return self.h.app.pm_point_key(p)

    # ---------------------------------------------------------------------------------------------------------------------------------
    def test_an_unmodified_run_is_byte_identical_whatever_is_saved_for_other_points(self):
        app = self.make()
        self.go(app)
        base = self.wire(app)
        self.h.stop()
        self.setUp()
        app2 = self.make()
        other = next(p for p in T.POINTS if p['kind'] == 'ACV')                           # a point this run does not measure
        self.save('command', pdef.point_command_target('Keysight34470A', 'conf.acv', self.key(other)), {'template': 'CONF:VOLT:AC {range:g}'},
                  cmd=self.reg['conf.acv'], driver_name='Keysight34470A')
        self.save('command', pdef.extra_command_target('Keysight34470A', 'after', 1, self.key(other)), {'template': 'FOO?'}, driver_name='Keysight34470A')
        app2.pm_state.load('A-100')
        self.go(app2)
        self.assertEqual(self.wire(app2), base)

    def test_a_command_typed_for_one_point_is_sent_for_that_point_only(self):
        app = self.make()
        pts = self.points
        self.save('command', pdef.point_command_target('Keysight34470A', 'conf.dcv', self.key(pts[1])), {'template': 'CONF:VOLT:DC {range:.3g},DEF'},
                  cmd=self.reg['conf.dcv'], driver_name='Keysight34470A')
        app.pm_state.load('A-100')
        self.go(app)
        per = self.per_point(app)
        confs = [[t.split('  [')[0] for t in lines if t.startswith('CONF:VOLT:DC')] for lines in per]
        self.assertEqual(len(confs), 3)
        self.assertTrue(confs[1][0].endswith(',DEF'), confs[1])
        self.assertFalse(confs[0][0].endswith(',DEF') or confs[2][0].endswith(',DEF'))
        tagged = [t for _ts, _i, d, t in app.io.log.entries if d == '>>' and '[OVERRIDE' in t]
        self.assertEqual(len(tagged), 1)

    def test_extra_lines_are_sent_once_before_and_after_the_points_own_commands(self):
        app = self.make()
        pts = self.points
        env = self.h.env
        env.store.add('command', pdef.extra_command_target('Keysight34470A', 'before', 1, self.key(pts[1])),
                      {'template': 'VOLT:DC:NPLC 1', 'readback': 'ROUT:TERM?', 'expect': 'FRON'}, 'model', 'look', model=self.MODEL,
                      driver_name='Keysight34470A', session=env.session)
        env.store.add('command', pdef.extra_command_target('Keysight34470A', 'after', 1, self.key(pts[1])),
                      {'template': '*OPC?'}, 'model', 'look', model=self.MODEL, driver_name='Keysight34470A', session=env.session)
        app.pm_state.load('A-100')
        self.go(app)
        per = self.per_point(app)
        mid = per[1]
        extra = [i for i, t in enumerate(mid) if 'EXTRA' in t]
        self.assertEqual(len(extra), 3, mid)
        self.assertTrue(all('UNVERIFIED' in mid[i] for i in extra))
        self.assertEqual([mid[i].split('  [')[0] for i in extra], ['VOLT:DC:NPLC 1', 'ROUT:TERM?', '*OPC?'], 'in order: write, its read-back, the after-line')
        read = next(i for i, t in enumerate(mid) if t.startswith('READ?'))
        self.assertLess(extra[1], read, 'a before-line precedes the measurement')
        self.assertGreater(extra[2], read, 'an after-line follows it')
        self.assertFalse(any('EXTRA' in t for t in per[0] + per[2]), 'no other point carries them')

    def test_a_failed_read_back_stops_the_point_nothing_is_retried_and_outputs_go_to_standby(self):
        app = self.make()
        pts = self.points
        env = self.h.env
        env.store.add('command', pdef.extra_command_target('Keysight34470A', 'before', 1, self.key(pts[0])),
                      {'template': 'VOLT:DC:NPLC 1', 'readback': 'ROUT:TERM?', 'expect': 'REAR'}, 'model', 'trial', model=self.MODEL,
                      driver_name='Keysight34470A', session=env.session)
        app.pm_state.load('A-100')
        with self.assertRaises(Exception) as cm:                         # the engine's own error path reports it; here the point routine is run directly
            app.io.measure(pts[0])
        self.assertIn('not confirmed', str(cm.exception))
        try:
            app.io.standby()
        except Exception:
            pass
        wire = [t.split('  [')[0] for t in self.wire(app)]
        self.assertEqual(wire.count('VOLT:DC:NPLC 1'), 1, 'sent once')
        self.assertEqual(wire.count('ROUT:TERM?'), 1, 'read back once, not retried')
        self.assertNotIn('READ?', wire, 'the point did not go on to take a reading')
        self.assertEqual(wire[-1], 'STBY')

    def test_an_edit_made_during_a_point_reaches_the_next_points_not_the_one_in_flight(self):
        app = self.make(n=4)
        pts = self.points
        seen = {}
        orig = app.io.measure

        def measure(p):
            seen['n'] = seen.get('n', 0) + 1
            if seen['n'] == 1:
                busy = PM.PointEditModel(app, p['id'], self.h.env.lock, store=self.h.env.store)
                seen['busy_reason'] = busy.blocked_reason
                m = PM.PointEditModel(app, pts[2]['id'], self.h.env.lock, store=self.h.env.store)
                seen['rows'] = len(m.rows)
                seen['probs'] = m.stage_command(next(r.seq for r in m.rows if r.key == 'conf.dcv'), 'CONF:VOLT:DC {range:.3g},DEF')
                m.set_reason('technician trial')
                res = m.apply()
                seen['ok'] = res.ok
                seen['dirty'] = app.pm_state.live.dirty
            return orig(p)
        app.io.measure = measure
        self.go(app)
        self.assertIn('being measured now', seen['busy_reason'])
        self.assertEqual(seen['probs'], [])
        self.assertTrue(seen['ok'])
        self.assertTrue(seen['dirty'], 'saved, waiting for the next point boundary')
        per = self.per_point(app)
        confs = [any(t.startswith('CONF:VOLT:DC') and ',DEF' in t for t in lines) for lines in per]
        self.assertEqual(confs, [False, False, True, False], 'only the point it was typed for')
        ev = app.pm_state.live.events
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]['before_point'], pts[1]['id'])
        self.assertEqual((ev[0]['changes'][0]['point_id'], ev[0]['changes'][0]['reason']), (pts[2]['id'], 'technician trial'))

    def test_a_tolerance_change_with_a_redo_measures_the_point_again_against_the_new_limit(self):
        app = self.make(n=3)
        pts = self.points
        orig = app.io.measure
        seen = {}

        def measure(p):
            seen['n'] = seen.get('n', 0) + 1
            if seen['n'] == 2:                                     # point 0 has its reading; change its tolerance now
                m = PM.PointEditModel(app, pts[0]['id'], self.h.env.lock, store=self.h.env.store)
                seen['reading'] = m.has_reading
                m.stage_field('error', '0.5')
                m.acknowledge(True)
                m.set_reason('customer limit')
                seen['redo'] = m.redo_required
                seen['ok'] = m.apply().ok
            return orig(p)
        app.io.measure = measure
        self.go(app)
        self.assertTrue(seen['reading'] and seen['redo'] and seen['ok'])
        self.assertEqual(len(self.marks), 4, 'three points plus the redo of the first')
        self.assertEqual(app.results[str(pts[0]['id'])].get('ovrev'), 1, 'the new reading carries the revision of the change')
        self.assertTrue(any(ev.get('redo') == [pts[0]['id']] for ev in app.pm_state.live.events))


if __name__ == '__main__':
    unittest.main()
