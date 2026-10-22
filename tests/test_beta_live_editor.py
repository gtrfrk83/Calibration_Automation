"""The procedure editor INSIDE a running procedure (procmods_live, ProcModsMixin.pm_step / pm_live_*, procmods_ui_model live mode).

Named test_beta_* so it sorts after test_beta (which needs a real tkinter and is the one known error of the suite).  The engine used for the
deep behaviour tests is the Keysight Truevolt procedure (real App on the simulated bench; the other engines are covered in
test_beta_live_editor_engines.py).  The operator is scripted: while a point is being measured by the worker thread, `hook(point)` plays the
technician using the editor model exactly as procmods_ui.LiveHook builds it.

What is proved
  * an edit saved during point N does not touch point N (same sleep, same commands, same limits) and starts at point N+1;
  * the standby is sent before the edit is applied, the reset-to-defaults sequence is not sent again, a failed standby applies nothing;
  * the edit is in the run's modifications list / snapshot / checkpoint / report context with who, when, reason, old, new;
  * redo, skip, limit, note, command rules (see procmods_live), demo marking, persistence of the saved scopes.
"""
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402

import procmods  # noqa: E402
import procmods_engine as pe  # noqa: E402
import procmods_live as live  # noqa: E402
import procmods_ui_model as M  # noqa: E402
import truevolt_verification as T  # noqa: E402
from drivers.simulated import make_dmm_bench  # noqa: E402


def sleeps_of(calls):
    return [c for c in calls if c >= 0.1]


class TruevoltLive(unittest.TestCase):
    MODEL = '34470A'

    def setUp(self):
        self.h = H.EngineHarness().start(T)
        self.addCleanup(self.h.stop)
        self.slept = []
        p = mock.patch('time.sleep', side_effect=lambda s: self.slept.append(s))
        p.start()
        self.addCleanup(p.stop)

    # ---- helpers -----------------------------------------------------------------------------------------------------------------
    def make(self, demo=False, n=4, kinds=('DCV',)):
        h = self.h
        app = T.App(h.root, self.MODEL, demo=demo)
        h.app = app
        st = app.pm_state
        st.store, st.devmode = h.env.store, h.env.dm
        app.asset.set('A-100')
        app.serial.set('S-1')
        self.bench, ft, dt = make_dmm_bench(self.MODEL)
        if not demo:
            app.io = T.IO('sim', 'sim', transports=(dt, ft), mods=st)
            dt.terminals = 'FRON'
        self.dt, self.ft = dt, ft
        self.points = [p for p in T.POINTS if p['kind'] in kinds and p['source'] == 'calibrator'][:n]
        return app

    def hook_measure(self, app, hook):
        """hook(point, number_of_calls_so_far) runs on the worker thread at the start of each point (the technician editing meanwhile)."""
        orig = app.io.measure
        count = {'n': 0}

        def measure(p):
            count['n'] += 1
            hook(p, count['n'])
            return orig(p)
        app.io.measure = measure
        return count

    def go(self, app, points=None):
        app.execute(points or self.points)
        self.assertTrue(self.h.pump(60), 'the run did not finish')

    def wire(self, app):
        return [(i, t) for _ts, i, d, t in app.io.log.entries if d == '>>']

    def stage_param(self, model, name, value, point_key=None):
        probs = model.stage_param(name, value, point_key)
        self.assertEqual(probs, [])

    # ---- the core rule: the next point, never this one -----------------------------------------------------------------------------
    def test_setting_edit_reaches_next_point_not_the_one_in_flight(self):
        app = self.make()
        edited = []

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                self.assertTrue(m.editable, m.read_only_reason)
                self.stage_param(m, 'truevolt.settle.default', 7.0)
                res = self.h.edit(m, 'DMM needs longer to settle', scope='run')
                self.assertTrue(res.ok, res.errors)
                edited.append(p['id'])
                self.assertTrue(app.pm_state.live.dirty)                       # saved, NOT in effect
                self.assertEqual(app.pm_state.param('truevolt.settle.default', 2.0), 2.0)
        self.hook_measure(app, hook)
        self.go(app)
        settles = sleeps_of(self.slept)
        self.assertEqual(settles[0], 2.0, 'the point in flight keeps the settle it started with')
        self.assertEqual(settles[1:4], [7.0, 7.0, 7.0], 'the following points use the edit')
        r = [app.results[str(p['id'])] for p in self.points]
        self.assertNotIn('ovrev', r[0])
        self.assertEqual([x.get('ovrev') for x in r[1:]], [1, 1, 1], 'results taken under the edit carry its revision')
        ev = app.pm_state.live.events
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]['before_point'], self.points[1]['id'])
        self.assertEqual(ev[0]['changes'][0]['kind'], 'param')
        self.assertEqual(ev[0]['changes'][0]['new'], '7.0')
        self.assertEqual(ev[0]['changes'][0]['reason'], 'DMM needs longer to settle')
        self.assertTrue(ev[0]['changes'][0]['author'])
        self.assertFalse(ev[0]['demo'])

    def test_standby_before_apply_and_no_second_reset(self):
        app = self.make()

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                self.stage_param(m, 'truevolt.settle.default', 3.0)
                self.h.edit(m)
        self.hook_measure(app, hook)
        self.go(app)
        lines = [t for _ts, _i, _d, t in app.io.log.entries]
        live_at = next(i for i, t in enumerate(lines) if t.startswith('LIVE EDIT'))
        self.assertIn('STBY', ' '.join(lines[max(0, live_at - 12):live_at]), 'outputs go to standby before the edit is applied')
        wire = self.wire(app)
        self.assertEqual([t for i, t in wire if t == '*RST' and i == '5560A'], ['*RST'], 'the reset is sent once per run, not again by an edit')
        self.assertEqual([t for i, t in wire if t == '*RST' and i == self.MODEL], ['*RST'])

    def test_failed_standby_applies_nothing_and_stops_the_run(self):
        app = self.make()

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                self.stage_param(m, 'truevolt.settle.default', 9.0)
                self.h.edit(m)
        self.hook_measure(app, hook)
        real = app.io.cal.standby_quiet
        state = {'fail': False}

        def standby():
            if state['fail']:
                raise RuntimeError('cannot confirm standby')
            return real()
        app.io.cal.standby_quiet = standby
        orig_measure = app.io.measure

        def arm(p):
            r = orig_measure(p)
            state['fail'] = True                                   # the boundary standby (after point 1) fails
            return r
        app.io.measure = arm
        app.execute(self.points)
        self.h.pump(60)
        self.assertFalse(app.busy)
        self.assertEqual(app.pm_state.param('truevolt.settle.default', 2.0), 2.0, 'nothing was applied')
        self.assertTrue(app.pm_state.live.dirty, 'the edit stays saved for the next point / Run')
        self.assertEqual(len(app.results), 1)
        errors = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'showerror']
        self.assertTrue(errors and 'NOT applied' in errors[0][3], errors)
        self.assertTrue(any('NOT applied' in w for w in app.pm_state.warnings))

    # ---- audit trail -----------------------------------------------------------------------------------------------------------------
    def test_edit_is_in_modifications_snapshot_checkpoint_and_report_context(self):
        app = self.make()

        def hook(p, n):
            if n == 2:
                m = self.h.model(app)
                self.stage_param(m, 'truevolt.settle.default', 6.0)
                self.h.edit(m, 'noisy lab')
        self.hook_measure(app, hook)
        self.go(app)
        mods = pe.applied_modifications(app)
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0]['reason'], 'noisy lab')
        self.assertTrue(mods[0]['author'])
        self.assertTrue(mods[0]['date'])
        self.assertEqual(mods[0]['applies_to'], 'this run only')
        info = pe.applied_info(app)
        self.assertEqual(info['rev'], 1)
        self.assertEqual(len(info['live_edits']), 1)
        fields = app.pm_checkpoint_fields()
        self.assertEqual(len(fields['overrides']['revs']), 1)
        self.assertEqual(fields['live_edits'][0]['before_point'], self.points[2]['id'])
        self.assertTrue(procmods.verify_snapshot(fields['overrides']))
        import report_snapshot
        ctx = report_snapshot.context_for(app)
        self.assertEqual(len(ctx['procedure_modifications']['live_edits']), 1)
        text = '\n'.join(t for _ts, _i, _d, t in app.io.log.entries)
        self.assertIn(f'LIVE EDIT rev 1 applied before point {self.points[2]["id"]}', text)

    def test_unmodified_run_records_nothing_new(self):
        app = self.make()
        self.go(app)
        self.assertEqual(app.pm_checkpoint_fields(), {})
        self.assertEqual(app.pm_result_fields(), {})
        self.assertEqual(app.pm_state.live.events, [])
        self.assertNotIn('live_edits', pe.applied_info(app))

    def test_saved_scope_persists_run_scope_does_not(self):
        app = self.make()

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                self.stage_param(m, 'truevolt.settle.freq', 5.0)
                self.h.edit(m, 'kept', scope='asset')
                m2 = self.h.model(app)
                self.stage_param(m2, 'truevolt.settle.zero', 3.0)
                self.h.edit(m2, 'once', scope='run')
        self.hook_measure(app, hook)
        self.go(app)
        rows = self.h.env.store.entries()
        self.assertEqual([(r['target'], r['scope'], r['asset_id']) for r in rows], [('truevolt.settle.freq', 'asset', 'A-100')])
        later = procmods.resolve(self.MODEL, 'A-100', store=self.h.env.store)
        self.assertEqual(later.param('truevolt.settle.freq', 3.0), 5.0)
        self.assertEqual(later.param('truevolt.settle.zero', 1.5), 1.5, 'a this-run-only edit is never stored')
        other = procmods.resolve(self.MODEL, 'B-200', store=self.h.env.store)
        self.assertEqual(other.param('truevolt.settle.freq', 3.0), 3.0)

    # ---- commands ---------------------------------------------------------------------------------------------------------------------
    def test_command_edit_starts_next_point_and_is_marked_in_the_log(self):
        app = self.make()
        target = 'Keysight34470A:conf.dcv'

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                self.assertIn('Keysight34470A', m.ctx.registries)
                chk = m.stage_command(target, 'CONF:VOLT:DC {range:.9g},MIN')
                self.assertTrue(chk.valid, chk.problems)
                self.h.edit(m, 'try MIN resolution')
        self.hook_measure(app, hook)
        self.go(app)
        confs = [t for i, t in self.wire(app) if t.startswith('CONF:VOLT:DC')]
        self.assertNotIn(',MIN', confs[0], 'point 1 was configured with the factory command')
        self.assertTrue(all(',MIN' in c for c in confs[1:]), confs)
        marked = [t for _ts, i, d, t in app.io.log.entries if 'OVERRIDE' in t and 'CONF:VOLT:DC' in t]
        self.assertTrue(marked)
        self.assertEqual(sum(1 for t in app.pm_state.oset.active('command')), 1)

    def test_locked_and_output_commands_are_not_editable_live(self):
        app = self.make()
        m = self.h.model(app)
        for target in ('Fluke5560A:oper.on', 'Fluke5560A:oper.stby', 'Keysight34470A:reset', 'Fluke5560A:reset'):
            d = m.command_detail(target)
            self.assertTrue(d['found'])
            self.assertFalse(d['editable'], target)
            chk = m.stage_command(target, 'STBY;OPER')
            self.assertTrue(chk.problems, target)                     # refused, whatever the text
        self.assertEqual(m.drafts, {})

    def test_command_tests_are_off_during_a_run(self):
        app = self.make()
        seen = []

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                seen.append(m.can_test('Keysight34470A:read'))
        self.hook_measure(app, hook)
        self.go(app, self.points[:1])
        self.assertFalse(seen[0][0])

    # ---- gates that must not move ---------------------------------------------------------------------------------------------------
    def test_devmode_gate_stays_in_front_of_every_live_edit(self):
        app = self.make()
        self.h.env.lock.lock()
        m = self.h.model(app)
        self.assertFalse(m.editable)
        self.assertIn('Unlock developer mode', m.read_only_reason)
        with self.assertRaises(procmods.OverrideError):
            m.stage_param('truevolt.settle.default', 4.0)
        self.assertEqual(self.h.env.store.entries(), [])

    def test_store_refuses_without_session_even_if_the_ui_were_bypassed(self):
        with self.assertRaises(procmods.OverrideError):
            self.h.env.store.add('param', 'truevolt.settle.default', {'value': 5.0}, 'asset', 'x', model=self.MODEL, asset_id='A-100', session=None)

    def test_safety_prompt_text_stays_locked(self):
        app = self.make()
        m = self.h.model(app)
        self.assertTrue(m.stage_text('prompt:safety_hv', 'ignore this'))                    # problems returned, nothing staged
        self.assertEqual(m.drafts, {})

    def test_stale_run_blocked_when_pinned_or_factory(self):
        app = self.make()
        app.pm_state.pinned = True
        m = self.h.model(app)
        self.assertFalse(m.editable)
        self.assertIn('progress file', m.read_only_reason)
        app.pm_state.pinned = False
        app.pm_state.factory_only, app.pm_state.suppressed = True, 2
        m = self.h.model(app)
        self.assertFalse(m.editable)
        self.assertIn('FACTORY', m.read_only_reason)

    # ---- where the change applies from ----------------------------------------------------------------------------------------------
    def test_editor_tells_which_point_the_change_starts_at(self):
        app = self.make()
        texts = []

        def hook(p, n):
            if n == 2:
                m = self.h.model(app)
                w = m.where()
                texts.append((w, m.applies_from_text()))
        self.hook_measure(app, hook)
        self.go(app)
        w, text = texts[0]
        self.assertTrue(w['running'])
        self.assertEqual(w['current']['id'], self.points[1]['id'])
        self.assertEqual(w['next']['id'], self.points[2]['id'])
        self.assertIn(f'Point {self.points[1]["id"]}', text)
        self.assertIn(f'start at point {self.points[2]["id"]}', text)

    def test_no_run_means_edits_apply_now_and_say_so(self):
        app = self.make()
        m = self.h.model(app)
        self.assertIn('next Run', m.applies_from_text())
        self.stage_param(m, 'truevolt.settle.default', 8.0)
        self.h.edit(m, 'idle edit', scope='asset')
        self.assertEqual(app.pm_state.param('truevolt.settle.default', 2.0), 8.0)
        self.assertFalse(app.pm_state.live.dirty)
        self.assertEqual(app.pm_state.live.events[0]['before_point'], None)

    # ---- skip, note, limits, redo ------------------------------------------------------------------------------------------------------
    def test_skip_next_point_but_never_a_point_with_a_reading(self):
        app = self.make()
        refused = []

        def hook(p, n):
            if n == 2:
                m = self.h.model(app)
                keys = dict(zip(procmods.point_keys(m.ctx.points), m.ctx.points))
                key_of = {pt['id']: k for k, pt in keys.items()}
                refused.append(m.stage_skip(key_of[self.points[0]['id']], True))      # has a reading
                refused.append(m.stage_skip(key_of[self.points[1]['id']], True))      # in flight
                self.assertEqual(m.stage_skip(key_of[self.points[3]['id']], True), [])
                self.h.edit(m, 'lead not available')
        self.hook_measure(app, hook)
        self.go(app)
        self.assertTrue(refused[0] and refused[1])
        self.assertIn('already has a reading', refused[0][0])
        self.assertEqual(sorted(app.results), sorted(str(p['id']) for p in self.points[:3]), 'the skipped point was not measured')

    def test_note_is_shown_once_when_its_point_is_reached(self):
        app = self.make()

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                key = procmods.point_keys(m.ctx.points)[m.ctx.points.index(next(q for q in m.ctx.points if q['id'] == self.points[2]['id']))]
                self.assertEqual(m.stage_text('note:' + key, 'Use the short low-thermal leads here'), [])
                self.h.edit(m, 'lab note')
        self.hook_measure(app, hook)
        self.go(app)
        notes = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'showinfo' and str(self.points[2]['id']) in d[2]]
        self.assertEqual(len(notes), 1)
        self.assertIn('low-thermal', notes[0][3])
        mods = pe.applied_modifications(app)
        self.assertEqual(len(mods), 1)

    def test_limit_edit_next_point_is_judged_against_it_and_listed_as_modified(self):
        app = self.make()
        target = self.points[2]

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                key = procmods.point_keys(m.ctx.points)[[q['id'] for q in m.ctx.points].index(target['id'])]
                fac = procmods.limit_factory(next(q for q in m.ctx.points if q['id'] == target['id']))
                self.assertEqual(m.stage_limit(key, error=fac['error'] * 0.001), [])
                self.assertEqual(m.limit_redo_needed(), [], 'a point not yet measured needs no redo')
                self.h.edit(m, 'customer tolerance', scope='run')
        self.hook_measure(app, hook)
        self.go(app)
        rec = app.results[str(target['id'])]
        live_pt = next(q for q in T.POINTS if q['id'] == target['id'])
        self.assertTrue(live_pt.get('limit_modified'))
        self.assertEqual(rec['result'], 'FAIL', 'judged against the tolerance used')
        info = pe.applied_info(app)
        self.assertTrue(info['tolerances_modified'])
        self.assertTrue(app.results[str(self.points[0]['id'])]['result'] in ('PASS', 'FAIL'))
        self.assertNotIn('ovrev', app.results[str(self.points[0]['id'])])

    def test_limit_edit_on_a_measured_point_needs_a_redo(self):
        app = self.make()
        outcome = {}

        def hook(p, n):
            if n == 2:
                m = self.h.model(app)
                first = self.points[0]
                key = procmods.point_keys(m.ctx.points)[[q['id'] for q in m.ctx.points].index(first['id'])]
                fac = procmods.limit_factory(next(q for q in m.ctx.points if q['id'] == first['id']))
                self.assertEqual(m.stage_limit(key, error=fac['error'] * 0.001), [])
                self.assertEqual([k for k, _l in m.limit_redo_needed()], [key])
                m.set_reason('limit', key, 'tighter')
                with self.assertRaises(procmods.OverrideError) as cm:
                    m.apply(confirmed=True)
                outcome['refused'] = str(cm.exception)
                self.assertEqual(self.h.env.store.entries(), [])
                res = m.apply(confirmed=True, redo=[key])
                outcome['ok'] = res.ok
        self.hook_measure(app, hook)
        app.execute(self.points[:3])
        self.assertTrue(self.h.pump(60))
        self.assertIn('redo', outcome['refused'])
        self.assertTrue(outcome['ok'])
        first = self.points[0]
        log = [t for _ts, _i, d, t in app.io.log.entries if d != '>>' or True]
        self.assertTrue(any('LIVE EDIT redo' in t for t in log))
        self.assertEqual(app.results[str(first['id'])].get('ovrev'), 1, 'the redone reading was taken under the new tolerance')
        self.assertEqual(app.results[str(first['id'])]['result'], 'FAIL')

    def test_redo_in_flight_point_measures_it_again_with_the_new_setting(self):
        app = self.make()
        first = self.points[0]

        def hook(p, n):
            if n == 1:
                m = self.h.model(app)
                self.stage_param(m, 'truevolt.settle.default', 6.0)
                self.h.edit(m, 'was too short')
                offer = m.redo_offer()
                self.assertEqual(offer['id'], first['id'])
                m.ctx.live.request_redo([offer['key']])
        self.hook_measure(app, hook)
        app.execute(self.points[:2])
        self.assertTrue(self.h.pump(60))
        measured = [t for i, t in self.wire(app) if t.startswith('CONF:VOLT:DC')]
        self.assertEqual(len(measured), 3, 'point 1, point 1 again, point 2')
        settles = sleeps_of(self.slept)
        self.assertEqual(settles[0], 2.0)
        self.assertEqual(settles[1:3], [6.0, 6.0])
        rewire = [d for d in self.h.dialogs if d[0] == 'confirm' and 'Rewire' in d[1]]
        self.assertEqual(len(rewire), 2, 'the setup prompt is shown again before a redone point')
        self.assertEqual(app.results[str(first['id'])].get('ovrev'), 1)
        self.assertEqual(sorted(app.results), sorted(str(p['id']) for p in self.points[:2]))

    # ---- demo ---------------------------------------------------------------------------------------------------------------------------
    def test_demo_edits_are_run_only_marked_and_never_stored(self):
        app = self.make(demo=True)
        did = []
        orig = app._record

        def record(p, reading, synthetic):
            orig(p, reading, synthetic)
            if not did:
                did.append(1)
                m = self.h.model(app)
                with self.assertRaises(ValueError):
                    m.set_scope('asset')
                with self.assertRaises(ValueError):
                    m.set_scope('model')
                self.stage_param(m, 'truevolt.settle.default', 5.0)
                self.h.edit(m, 'demo tweak', scope='run')
        app._record = record
        app.execute(self.points)
        self.assertTrue(self.h.pump(30))
        self.assertEqual(self.h.env.store.entries(), [])
        ev = app.pm_state.live.events
        self.assertEqual(len(ev), 1)
        self.assertTrue(ev[0]['demo'])
        self.assertIn('[DEMO]', live.event_line(ev[0]))
        self.assertTrue(all(r['synthetic'] for r in app.results.values()))
        self.assertIn('DEMO', self.h.model(app).ctx.title + ('DEMO' if self.h.model(app).ctx.demo else ''))
        self.assertFalse(app.pm_record_run(1), 'a demo run is never recorded with its modifications')

    # ---- run state preserved --------------------------------------------------------------------------------------------------------------
    def test_run_state_is_kept_across_edits_and_a_stop_and_resume(self):
        app = self.make()

        def hook(p, n):
            if n == 2:
                m = self.h.model(app)
                self.stage_param(m, 'truevolt.settle.default', 4.5)
                self.h.edit(m, 'longer')
                app.request_stop()                                    # the operator stops after this point
        self.hook_measure(app, hook)
        app.execute(self.points)
        self.assertTrue(self.h.pump(60))
        self.assertEqual(len(app.results), 2)
        first_readings = {k: dict(v) for k, v in app.results.items()}
        app.io.measure = app.io.__class__.measure.__get__(app.io)         # no more hooks
        self.slept.clear()
        app.execute([p for p in self.points if str(p['id']) not in app.results])
        self.assertTrue(self.h.pump(60))
        self.assertEqual(len(app.results), 4)
        for k, v in first_readings.items():
            self.assertEqual(app.results[k]['reading'], v['reading'], 'readings already entered are untouched')
        self.assertEqual(sleeps_of(self.slept)[:2], [4.5, 4.5], 'the run-only edit is still in effect after a stop and resume')
        self.assertEqual(len(app.pm_state.live.events), 1)
        data = app.pm_checkpoint_fields()
        self.assertEqual(len(data['live_edits']), 1)

    def test_changing_the_instrument_id_drops_run_only_edits(self):
        app = self.make()
        m = self.h.model(app)
        self.stage_param(m, 'truevolt.settle.default', 8.0)
        self.h.edit(m, 'x', scope='run')
        self.assertEqual(len(app.pm_state.run_entries), 1)
        app.pm_state.load(asset='B-200')
        self.assertEqual(app.pm_state.run_entries, [])
        self.assertEqual(app.pm_state.param('truevolt.settle.default', 2.0), 2.0)


class BoundaryUnit(unittest.TestCase):
    """pm_step on a minimal engine (no Tk at all)."""

    class Eng(pe.ProcModsMixin):
        def __init__(self, env):
            self.busy = True
            self.demo = False
            self.io = None
            self.pts = [{'id': i, 'description': f'p{i}', 'section': 's', 'kind': 'DCV', 'nominal': float(i), 'range': 10.0, 'unit': 'V', 'error': 0.1,
                         'setup': 'wire it'} for i in range(1, 5)]
            self.pm_init('truevolt', 'TEST', lists=[self.pts], store=env.store, devmode=env.dm)
            self.standby_calls = 0

        def pm_standby(self):
            self.standby_calls += 1

        def refresh(self):
            pass

    def setUp(self):
        self.env = H.Env()
        self.addCleanup(self.env.close)
        self.e = self.Eng(self.env)

    def test_reentry_does_not_apply_and_new_index_does(self):
        e = self.e
        run = e.pm_begin_run(list(e.pts), 'A1')
        p, prev = e.pm_step(run, 0, None)
        e.pm_state.live.mark_saved('x')
        again, _ = e.pm_step(run, 0, None)                               # same point again (a prompt stage): nothing happens
        self.assertTrue(e.pm_state.live.dirty)
        self.assertEqual(e.standby_calls, 0)
        e.pm_step(run, 1, None)
        self.assertFalse(e.pm_state.live.dirty)
        self.assertEqual(e.standby_calls, 1)

    def test_idle_commit_runs_standby_once_and_never_retries(self):
        e = self.e
        e.busy = False
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError('no')
        e.pm_standby = boom
        e.pm_state.live.mark_saved('x')
        with self.assertRaises(live.LiveApplyError):
            e._pm_commit(None)
        self.assertEqual(len(calls), 1)
        e.pm_live_saved(['y'])                                           # idle path swallows the error (the next Run applies it)
        self.assertEqual(len(calls), 2)
        self.assertTrue(e.pm_state.live.dirty)

    def test_diff_describes_added_changed_removed(self):
        e = self.e
        s = self.env.store
        sess = self.env.session
        a = s.add('param', 'truevolt.settle.default', {'value': 5.0}, 'model', 'r1', model='TEST', session=sess)
        o1 = procmods.resolve('TEST', 'A1', store=s)
        b = s.edit(a['uid'], value={'value': 6.0}, reason='r2', session=sess)
        o2 = procmods.resolve('TEST', 'A1', store=s)
        d = live.diff_sets(o1, o2)
        self.assertEqual([x['action'] for x in d], ['changed'])
        self.assertEqual((d[0]['old'], d[0]['new']), ('5.0', '6.0'))
        d = live.diff_sets(o2, procmods.resolve('TEST', 'A1', factory_only=True, store=s))
        self.assertEqual([x['action'] for x in d], ['removed'])
        self.assertEqual(live.diff_sets(o2, o2), [])

    def test_bridge_never_raises(self):
        br = live.LiveBridge(where=lambda: 1 / 0, locked_keys=lambda: 1 / 0, blocked=lambda: 1 / 0, saved=lambda t: None,
                             redo=lambda k: None, running=lambda: 1 / 0)
        self.assertEqual(br.locked_keys(), set())
        self.assertTrue(br.blocked_reason())
        self.assertTrue(br.running())
        self.assertEqual(br.pending(), [])


if __name__ == '__main__':
    unittest.main()
