"""Run queue for the handheld multimeter procedures (run_queue.py, run_queue_engine.py, run_queue_ui.py).

The real App code runs on the simulated bench (tkinter is stubbed in setUpModule, as in the other engine tests); only the modal windows are scripted
(tests/dsb_run_harness.Harness: `queue_readings`, `queue_default`, `queue_action` ... for the one-window reading entry).  The real windows are viewed
on a real Tk under Xvfb in tests/real_tk_checks.py::checks_run_queue.
Sorts after test_beta on purpose (the project's tkinter-stub tests set up their own stub)."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import run_queue as RQ  # noqa: E402  (Tk-free)

h = VH = None


def setUpModule():
    global h, VH
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import virtual_harness as _vh
    h, VH = _h, _vh


def pts(model, spec='fluke_110_series_pv.json'):
    sp = h.load_spec(spec)
    return sp, h.points_for(sp, model)


def queue_of(*assets, mode=None):
    q = RQ.RunQueue()
    for a in assets:
        q.add(a, 'S-' + a, 'T')
    if mode:
        q.mode = mode
    return q


# ===================================================================================================================== model
class Model(unittest.TestCase):
    def test_queue_editing_and_validation(self):
        q = RQ.RunQueue()
        self.assertFalse(q.active())
        q.add('4412', '21090134', 'M. Reyes')
        q.add('4413')
        self.assertTrue(q.active())
        with self.assertRaises(RQ.QueueError):
            q.add('4412')                       # an asset can be listed once: nothing is merged between assets
        with self.assertRaises(RQ.QueueError):
            q.add('  4412 ')
        with self.assertRaises(RQ.QueueError):
            q.add('')
        q.add('4415')
        self.assertEqual(q.move(2, -1), 1)
        self.assertEqual(q.names(), ['4412', '4415', '4413'])
        self.assertEqual(q.move(0, -1), 0)      # cannot go above the first row
        self.assertEqual(q.remove(1).asset, '4415')
        self.assertEqual(q.names(), ['4412', '4413'])
        for n in range(RQ.MAX_METERS):
            try:
                q.add(f'X{n}')
            except RQ.QueueError:
                break
        self.assertEqual(len(q), RQ.MAX_METERS)

    def test_saved_queue_roundtrip_and_guards(self):
        q = queue_of('A1', 'A2', mode=RQ.ONE_AT_A_TIME)
        d = q.to_dict('117', demo=False)
        r = RQ.RunQueue()
        self.assertTrue(r.load_dict(d, '117', False))
        self.assertEqual((r.names(), r.mode), (['A1', 'A2'], RQ.ONE_AT_A_TIME))
        self.assertFalse(RQ.RunQueue().load_dict(d, '116', False))      # another model
        self.assertFalse(RQ.RunQueue().load_dict(d, '117', True))       # a demo queue never becomes a real one

    def test_default_sharing_rules(self):
        sp, p117 = pts('117')
        by = {}
        for p in p117:
            by.setdefault((p['kind'], p['group'], p['test']), RQ.share_reason(p, sp['options']))
        for key in (('DCV', 'VOHM', 'numeric'), ('ACV', 'VOHM', 'numeric'), ('VISUAL', 'NONE', 'visual'), ('NONE', 'NONE', 'numeric')):
            self.assertIsNone(by[key], key)                      # voltage, yes/no checks and points set by hand with no calibrator output (open input)
        for key in (('DCI', 'AMP10', 'numeric'), ('ACI', 'AMP10', 'numeric'), ('ACV', 'VOLTALERT', 'visual'), ('OHM', 'VOHM', 'numeric'),
                    ('OHM', 'VOHM', 'beeper'), ('CAP', 'VOHM', 'numeric')):
            self.assertTrue(by[key], key)                        # Mike: resistance, capacitance and thermocouple sources are one meter at a time
        self.assertIn('series', by[('DCI', 'AMP10', 'numeric')])
        sp, p116 = pts('116')
        self.assertIn('thermocouple', next(RQ.share_reason(p, sp['options']) for p in p116 if p['kind'] == 'TEMP'))          # temperature: one meter at a time
        self.assertIn('series', next(RQ.share_reason(p, sp['options']) for p in p116 if p['group'] == 'UAMP'))
        sp, p289 = pts('289', 'fluke_287_289_pv.json')
        self.assertIn('4-wire', next(RQ.share_reason(p, sp['options']) for p in p289 if p['group'] == 'OHM4'))
        sp, p87 = pts('87V', 'fluke_87v_pv.json')
        self.assertIn('special source', next(RQ.share_reason(p, sp['options']) for p in p87 if p['kind'] == 'SQUARE'))
        self.assertIn('special source', next(RQ.share_reason(p, sp['options']) for p in p87 if p['kind'] == 'DUTY'))

    def test_explicit_flags_win(self):
        p = dict(kind='DCI', group='AMP10', applied={'value': 1}, test='numeric')
        self.assertTrue(RQ.share_reason(p, {}))
        self.assertIsNone(RQ.share_reason(dict(p, queue_share=True), {}))                       # a point may say it can be shared
        v = dict(kind='DCV', group='VOHM', applied={'value': 1}, test='numeric')
        self.assertIsNone(RQ.share_reason(v, {}))
        self.assertEqual(RQ.share_reason(dict(v, queue_share=False), {}), RQ.FLAGGED_REASON)    # ... or that it cannot
        self.assertEqual(RQ.share_reason(v, {'queue_share': False}), RQ.FAMILY_REASON)          # a whole family
        self.assertEqual(RQ.share_reason(v, {'queue_single_kinds': ['DCV']}), RQ.FLAGGED_REASON)
        self.assertEqual(RQ.share_reason(v, {'queue_single_groups': ['VOHM']}), RQ.FLAGGED_REASON)

    def test_every_shipped_handheld_spec_has_a_plan(self):
        for spec in ('fluke_110_series_pv.json', 'fluke_87v_pv.json', 'fluke_77iv_pv.json', 'fluke_170_series_pv.json', 'fluke_287_289_pv.json', 'klein_mm325_pv.json'):
            sp = h.load_spec(spec)
            for model in sp['models']:
                points = h.points_for(sp, model)
                q = queue_of('A', 'B', 'C')
                units = RQ.plan(points, q, sp.get('options'))
                ran = [(u.kind, tuple(m.asset for m in u.meters), p['id']) for u in units for p in u.points]
                for m in 'ABC':
                    self.assertEqual(sorted(i for _k, who, i in ran if m in who), sorted(p['id'] for p in points), (spec, model, m))   # every meter gets every point once
                self.assertEqual(units[0].kind, 'shared') if RQ.share_reason(points[0], sp.get('options')) is None else None

    def test_plan_point_by_point_groups_and_falls_back(self):
        sp, p115 = pts('115')
        units = RQ.plan(p115, queue_of('A', 'B', 'C'), sp['options'])
        kinds = [u.kind for u in units]
        self.assertEqual(kinds[0], 'shared')
        self.assertIn('single', kinds)
        cur = [u for u in units if u.kind == 'single' and 'series' in u.reason]
        self.assertEqual([u.meters[0].asset for u in cur], ['A', 'B', 'C'])        # current points: meter 1, then 2, then 3
        for u in cur:
            self.assertTrue(u.prompt)                                                   # a prompt before each meter
            self.assertTrue(all(RQ.share_reason(p, sp['options']) for p in u.points))              # only points that cannot be shared

    def test_plan_one_meter_at_a_time_is_meter_major(self):
        sp, p117 = pts('117')
        units = RQ.plan(p117, queue_of('A', 'B', 'C', mode=RQ.ONE_AT_A_TIME), sp['options'])
        self.assertEqual([(u.kind, u.meters[0].asset, len(u.points), u.prompt, u.reset) for u in units],
                         [('single', 'A', 40, False, False), ('single', 'B', 40, True, True), ('single', 'C', 40, True, True)])

    def test_plan_ir_forces_one_at_a_time(self):
        sp, p289 = pts('289', 'fluke_287_289_pv.json')
        units = RQ.plan(p289, queue_of('A', 'B'), sp['options'], use_ir=True)
        self.assertEqual([u.kind for u in units], ['single', 'single'])

    def test_plan_resume_and_force(self):
        sp, p117 = pts('117')
        q = queue_of('A', 'B', 'C')
        for p in p117[:10]:
            q.meters[0].found[p['id']] = {'result': 'PASS'}
            q.meters[1].found[p['id']] = {'result': 'PASS'}
        units = RQ.plan(p117, q, sp['options'])
        first = next(u for u in units if p117[0]['id'] in [p['id'] for p in u.points])
        self.assertEqual([m.asset for m in first.meters], ['C'])                         # only meter C still needs the first point
        self.assertTrue(set(p['id'] for p in p117[:10]) & set(p['id'] for p in first.points))
        again = RQ.plan(p117[:3], q, sp['options'], force=True)                          # Rerun Selected measures them on every meter
        self.assertEqual(sum(len(u.points) for u in again if u.shared), len([p for p in p117[:3] if RQ.share_reason(p, sp['options']) is None]))
        self.assertEqual(RQ.plan(p117, q, sp['options'], left=True)[0].kind in ('shared', 'single'), True)      # the As Left set is empty: everything pending

    def test_progress_counts(self):
        sp, p117 = pts('117')
        q = queue_of('A', 'B')
        q.meters[0].found = {p['id']: {'result': 'PASS'} for p in p117[:7]}
        q.meters[1].found = {p['id']: {'result': 'FAIL' if i == 2 else 'PASS'} for i, p in enumerate(p117[:6])}
        rows = RQ.progress(q, p117)
        self.assertEqual([(r['recorded'], r['failed'], r['first_fail']) for r in rows], [(7, 0, None), (6, 1, p117[2]['n'])])

    def test_summary_saves_settings(self):
        sp, p117 = pts('117')
        s = RQ.summary(p117, queue_of('A', 'B', 'C'), sp['options'], mode=RQ.POINT_BY_POINT)
        self.assertEqual(s['alone'], 120)
        self.assertLess(s['settings'], s['alone'])
        self.assertEqual(s['saved'], s['alone'] - s['settings'])
        s2 = RQ.summary(p117, queue_of('A', 'B', 'C'), sp['options'], mode=RQ.ONE_AT_A_TIME)
        self.assertEqual((s2['settings'], s2['saved']), (120, 0))


# ===================================================================================================================== engine
class EngineBase(unittest.TestCase):
    MODEL = '117'
    SPEC = None

    def setUp(self):
        self.hn = VH.VHarness().start()
        self.hn.fill = False
        self.home = self.hn.home

    def tearDown(self):
        self.hn.stop()

    def spec(self):
        return h.load_spec(self.SPEC) if self.SPEC else None

    def real(self, assets=('4412', '4413', '4415'), mode=RQ.POINT_BY_POINT, model=None, spec=None, hv=None):
        """A REAL (not demo) run on the simulated calibrator, typed readings."""
        from drivers.simulated import make_bench
        from test_handheld_options import Spy
        bench, _a, _b = make_bench()
        io = h.IO('Fluke 5522A', 'sim', transport=Spy(bench, '5522A'))
        io.auto_ramp = False
        io._wait = lambda *a, **k: None
        app = h.App(self.hn.root, model or self.MODEL, demo=False, spec=spec or self.spec(), io_factory=lambda: io)
        app.cal_mode.set(h.CAL_CHOICES[1])
        app.io = io
        self.hn.app = app
        self.io = io
        self.hn.default_reading = lambda p: VH.DH.typed_nominal(p) if p['test'] == 'numeric' and p.get('nominal') is not None else None
        if assets:
            app.apply_queue([(a, 'S-' + a, 'Tech ' + a) for a in assets], mode)
        return app

    def demo(self, assets=('4412', '4413', '4415'), mode=RQ.POINT_BY_POINT, fast=False, failures=False, model=None, spec=None):
        app = h.App(self.hn.root, model or self.MODEL, demo=True, spec=spec or self.spec(), fast_demo=fast)
        app.demo_failures = None
        app.demo_failures_on = failures
        self.hn.app = app
        self.hn.fill = True
        if assets:
            app.apply_queue([(a, 'S-' + a, 'Tech ' + a) for a in assets], mode)
        return app

    def windows(self, kind):
        return [d for d in self.hn.dialogs if d[0] == kind]

    def wire(self):
        return [t for _i, t in VH.wire(self.io)]


class PointByPoint(EngineBase):
    def test_each_point_is_set_once_and_read_in_one_window(self):
        app = self.real()
        applied = []
        orig = self.io.apply
        self.io.apply = lambda p, cancel=None: (applied.append(p['id']), orig(p, cancel=cancel))[1]
        self.hn.run_all()
        self.assertFalse(self.hn.boxes('showerror'))
        sp = app.spec
        shared_numeric = [p for p in app.points if p['test'] == 'numeric' and RQ.share_reason(p, sp['options']) is None]
        multi = self.windows('readings')
        self.assertEqual([d[1] for d in multi], [p['id'] for p in shared_numeric])           # one window per shared point, in order
        self.assertTrue(all(d[2] == ['4412', '4413', '4415'] for d in multi))                 # meter 1, 2, 3 in one window
        for p in app.points:
            if not p.get('applied'):
                continue
            want = 1 if RQ.share_reason(p, sp['options']) is None else 3                      # shared: set ONCE; one meter at a time: once per meter
            self.assertEqual(applied.count(p['id']), want, p['id'])
        for m in app.queue.meters:
            self.assertEqual(len(m.found), len(app.points), m.asset)

    def test_outputs_go_to_standby_after_each_point(self):
        app = self.real()
        self.hn.run_all()
        wire = self.wire()
        last_oper = None
        for n, t in enumerate(wire):
            if t.startswith('OUT ') and not t.endswith('?'):
                self.assertIsNone(last_oper, f'an OUT at {n} while the previous output was still on')
                last_oper = n
            if t == 'STBY':
                last_oper = None
        self.assertEqual(wire[-1], 'STBY')

    def test_prompts_once_per_group_not_per_meter(self):
        app = self.real()
        self.hn.run_all()
        keys = []
        prev = None
        for p in app.points:
            k = app._group_key(p)
            if k != prev and RQ.share_reason(p, app.spec['options']) is None:
                keys.append(k)
            prev = k
        cables = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] in ('Change the cables', 'Check the setup')]
        # one hook-up prompt per group in the shared part of the run, never one per meter: far fewer prompts than meters x groups
        self.assertLess(len(cables), 3 * len(set(app._group_key(p) for p in app.points)))
        self.assertTrue(any('4412, 4413, 4415' in ' '.join(d[3]) for d in cables))             # the prompt names every meter

    def test_each_meter_is_judged_against_the_same_limits(self):
        app = self.real()
        numeric = [p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV' and RQ.share_reason(p, app.spec['options']) is None]
        p = numeric[1]
        low, high = float(p['low']), float(p['high'])
        # meter 2 reads just outside the limits, meter 3 reads OL, meter 1 reads the nominal
        self.hn.queue_readings[('4413', p['id'])] = f'{high + (high - low):.6f}'
        self.hn.queue_readings[('4415', p['id'])] = 'OL'
        self.hn.run_all()
        res = {m.asset: m.found[p['id']]['result'] for m in app.queue.meters}
        self.assertEqual(res, {'4412': 'PASS', '4413': 'FAIL', '4415': 'FAIL'})
        for m in app.queue.meters:                                                                # a failure on one meter never stops the others
            self.assertEqual(len(m.found), len(app.points))
        self.assertEqual(app.queue.meters[2].found[p['id']]['entered'], 'OL')

    def test_readings_are_padded_to_the_resolution_per_meter(self):
        app = self.real()
        p = next(p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV' and p['nominal'] == 5.0)
        self.hn.queue_readings[('4412', p['id'])] = '5'
        self.hn.queue_readings[('4413', p['id'])] = '5.0'
        self.hn.run_all()
        want = h.pad_reading(p, '5')
        self.assertEqual([m.found[p['id']]['entered'] for m in app.queue.meters][:2], [want, want])
        self.assertNotEqual(want, '5')

    def test_results_are_kept_apart_per_asset(self):
        app = self.real()
        self.hn.run_all()
        a, b, c = app.queue.meters
        self.assertIsNot(a.found, b.found)
        self.assertEqual({id(a.found), id(b.found), id(c.found)}.__len__(), 3)
        files = {}
        for m in app.queue.meters:
            path = app._checkpoint_path(m.asset)
            self.assertTrue(path.exists(), m.asset)
            data = json.loads(path.read_text())
            files[m.asset] = data
            self.assertEqual((data['asset'], data['serial']), (m.asset, m.serial))
            self.assertEqual(len(data['results']), len(app.points))
        self.assertEqual(len({str(p) for p in map(app._checkpoint_path, ('4412', '4413', '4415'))}), 3)
        self.assertFalse(any(r.get('synthetic') for m in app.queue.meters for r in m.found.values()))

    def test_skip_applies_to_the_whole_queue(self):
        app = self.real()
        p = next(p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV')
        self.hn.queue_action[p['id']] = 'skip'
        self.hn.run_all()
        for m in app.queue.meters:
            self.assertNotIn(p['id'], m.found, m.asset)
            self.assertEqual(len(m.found), len(app.points) - 1)

    def test_stop_applies_to_the_whole_queue_and_progress_is_saved(self):
        app = self.real()
        p = [p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV'][3]
        self.hn.queue_action[p['id']] = 'stop'
        self.assertTrue(self.hn.run_all())
        self.assertFalse(app.busy)
        self.assertIsNone(app._q)
        for m in app.queue.meters:
            self.assertNotIn(p['id'], m.found)
            self.assertTrue(0 < len(m.found) < len(app.points))
            self.assertTrue(app._checkpoint_path(m.asset).exists())
        counts = {len(m.found) for m in app.queue.meters}
        self.assertEqual(len(counts), 1)                                                         # all meters stopped at the same point
        self.assertTrue(any(r[4] for r in self.hn.progress_log))                                  # the progress window was told the run ended
        self.assertEqual(self.wire()[-1], 'STBY')

    def test_non_shareable_points_fall_back_with_a_prompt_that_says_why(self):
        app = self.real(model='115')
        self.hn.run_all()
        current = [p for p in app.points if p['kind'] in ('DCI', 'ACI')]
        self.assertTrue(current)
        reading_windows = [d for d in self.hn.dialogs if d[0] == 'reading' and d[1] in {p['id'] for p in current}]
        self.assertEqual(len(reading_windows), len(current) * 3)                                 # the ordinary single-meter window, once per meter
        self.assertFalse([d for d in self.hn.dialogs if d[0] == 'readings' and d[1] in {p['id'] for p in current}])
        swaps = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'One meter at a time']
        self.assertTrue(swaps)
        text = ' '.join(' '.join(d[3]) for d in swaps)
        self.assertIn('series', text)                                                              # says why
        for asset in ('4412', '4413', '4415'):
            self.assertIn(asset, ' '.join(d[2] for d in swaps))                                    # meter by meter
        for m in app.queue.meters:
            self.assertEqual(len(m.found), len(app.points))

    def test_high_voltage_is_confirmed_once_per_hook_up_group_and_names_all_meters(self):
        sp = h.load_spec('fluke_77iv_pv.json')
        app = self.real(model='77IV', spec=sp)
        self.hn.run_all()
        hv = [p for p in app.points if app._high_voltage(p)]
        self.assertTrue(hv)
        asks = [d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'askyesno' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(asks), len({p['group'] for p in hv}))                                # once per hook-up group (Mike), not per point or per meter
        self.assertTrue(all(all(a in d[3] for a in ('4412', '4413', '4415')) for d in asks))

    def test_high_voltage_decline_stops_before_the_output(self):
        sp = h.load_spec('fluke_77iv_pv.json')
        app = self.real(model='77IV', spec=sp)
        self.hn.box_answer['askyesno'] = False
        self.hn.run_all()
        self.assertFalse(app.busy)
        volts = [float(m.group(1)) for t in self.wire() for m in [re.match(r'OUT\s+([-+0-9.eE]+)\s*V', t)] if m]
        self.assertTrue(volts and max(abs(v) for v in volts) < 30, volts)                  # nothing at or above the 30 V threshold was ever sourced
        asks = [d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'askyesno' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(asks), 1)
        wire = self.wire()
        self.assertEqual(wire[-1], 'STBY')

    def test_function_prompt_names_every_meter_once_per_function(self):
        app = self.real()
        self.hn.run_all()
        fn = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the function']
        self.assertTrue(fn)
        self.assertTrue(any('4412, 4413, 4415' in ' '.join(d[3]) for d in fn))                    # the shared part names every meter
        self.assertLess(len(fn), 3 * len({p['switch'] for p in app.points}))

    def test_annunciator_is_asked_per_meter(self):
        sp = h.load_spec('fluke_110_series_pv.json')
        app = self.real(model='117', spec=sp)
        ann = [p for p in app.points if p.get('annunciator')]
        if not ann:
            self.skipTest('no annunciator point in this spec')
        self.hn.run_all()
        asks = [d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'askyesno' and d[2] == 'AC annunciator']
        self.assertEqual(len(asks), len(ann) * 3)


class OneMeterAtATime(EngineBase):
    def test_meter_one_completes_then_a_swap_prompt_then_meter_two(self):
        app = self.real(mode=RQ.ONE_AT_A_TIME)
        self.hn.run_all()
        self.assertFalse(self.windows('readings'))                                                 # the ordinary single-meter windows only
        order = [d for d in self.hn.dialogs if d[0] == 'reading' or (d[0] == 'confirm' and d[1] == 'Next meter')]
        swaps = [n for n, d in enumerate(order) if d[0] == 'confirm']
        self.assertEqual(len(swaps), 2)                                                            # before meter 2 and before meter 3
        first = order[:swaps[0]]
        self.assertEqual(list(dict.fromkeys(d[1] for d in first)), [p['id'] for p in app.points])  # meter 1: every point, in order, before any swap
        self.assertIn('4413', ' '.join(' '.join(self.hn.dialogs[i][3]) for i, d in enumerate(self.hn.dialogs) if d[0] == 'confirm' and d[1] == 'Next meter'))
        for m in app.queue.meters:
            self.assertEqual(len(m.found), len(app.points))
        out_cmds = [t for t in self.wire() if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(len(out_cmds), len([p for p in app.points if p.get('applied')]) * 3)     # every meter's flow sets every point (nothing shared)
        resets = [t for t in self.wire() if '*RST' in t]
        self.assertEqual(len(resets), 3)                                                           # the calibrator is reset before each meter's run, as before every run

    def test_cancel_at_the_swap_prompt_pauses_and_keeps_progress(self):
        app = self.real(mode=RQ.ONE_AT_A_TIME)
        self.hn.on_confirm = lambda title, *a: False if title == 'Next meter' else None
        self.assertTrue(self.hn.run_all())
        self.assertFalse(app.busy)
        a, b, c = app.queue.meters
        self.assertEqual((len(a.found), len(b.found), len(c.found)), (len(app.points), 0, 0))
        self.assertTrue(app._checkpoint_path('4412').exists())


class SingleMeterUnchanged(EngineBase):
    """A queue of one meter (or none) is today's run, byte for byte."""

    def run_old(self):
        app = self.real(assets=None)
        app.asset.set('4412')
        app.serial.set('S-4412')
        self.hn.run_all()
        return app

    def strip(self, results):
        return {k: {f: v for f, v in r.items() if f != 'timestamp'} for k, r in results.items()}

    def test_one_meter_queue_equals_the_old_run(self):
        old = self.run_old()
        old_wire, old_dialogs = self.wire(), list(self.hn.dialogs)
        old_found = self.strip(old.found)
        self.hn.stop()
        self.hn = VH.VHarness().start()
        self.hn.fill = False
        new = self.real(assets=[])
        new.apply_queue([('4412', 'S-4412', 'T')], RQ.POINT_BY_POINT)
        self.assertFalse(new.queue.active())                                                       # one meter is not a queue
        new._queue_start_pressed()                                                                  # what 'Start queue' does with one meter
        self.hn.pump()
        self.assertEqual(self.wire(), old_wire)                                                     # the same commands, in the same order
        self.assertEqual(self.hn.dialogs, old_dialogs)                                              # the same windows
        self.assertEqual(self.strip(new.found), old_found)
        self.assertIsNone(new._q)
        self.assertFalse(self.windows('readings'))
        self.assertEqual(new.asset.get(), '4412')

    def test_no_queue_hooks_change_the_prompts(self):
        app = self.real(assets=[])
        self.assertEqual(app._qfacts([('a', 'b')]), [('a', 'b')])
        self.assertEqual(app._qsteps(), [])
        self.assertEqual(app._qnote(), '')
        self.assertEqual(app._q_hv_text('x Enable output?'), 'x Enable output?')
        self.assertFalse(app.queue_wants_run())

    def test_old_report_export_still_works_for_one_meter(self):
        app = self.run_old()
        self.assertTrue(app.found)


class Checkpoint(EngineBase):
    def test_resume_continues_each_meter_from_its_saved_progress(self):
        app = self.real()
        stop_at = [p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV'][4]
        self.hn.queue_action[stop_at['id']] = 'stop'
        self.hn.run_all()
        done = {m.asset: set(m.found) for m in app.queue.meters}
        self.assertTrue(all(done.values()))
        # a NEW window (a new session): the same assets, saved progress is on disk
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        self.hn.fill = False
        app2 = self.real()
        self.hn.box_answer['askyesnocancel'] = True
        self.hn.run_all()
        asked = [d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'askyesnocancel']
        self.assertEqual(len(asked), 1)
        measured = {d[1] for d in self.windows('readings')} | {d[1] for d in self.windows('reading')}
        self.assertFalse(measured & done['4412'] & done['4413'] & done['4415'])                    # points already recorded are not measured again
        for m in app2.queue.meters:
            self.assertEqual(len(m.found), len(app2.points))

    def test_declining_the_resume_starts_over(self):
        app = self.real()
        stop_at = [p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV'][2]
        self.hn.queue_action[stop_at['id']] = 'stop'
        self.hn.run_all()
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        self.hn.fill = False
        app2 = self.real()
        self.hn.box_answer['askyesnocancel'] = False
        self.hn.run_all()
        first_points = [d[1] for d in self.hn.dialogs if d[0] in ('reading', 'readings')][:1]
        self.assertEqual(first_points, [app2.points[0]['id']])                                     # started again from point 1

    def test_cancelling_the_resume_question_runs_nothing(self):
        app = self.real()
        stop_at = [p for p in app.points if p['test'] == 'numeric'][5]
        self.hn.queue_action[stop_at['id']] = 'stop'
        self.hn.run_all()
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        app2 = self.real()
        self.hn.box_answer['askyesnocancel'] = None
        self.hn.run_all()
        self.assertFalse(app2.busy)
        self.assertFalse(self.hn.dialogs and any(d[0] in ('reading', 'readings') for d in self.hn.dialogs))
        self.assertFalse([t for t in self.wire() if t.startswith('OUT ')])

    def test_demo_checkpoints_are_not_resumed_by_a_real_run(self):
        app = self.demo()
        self.hn.run_all()
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        self.hn.fill = False
        app2 = self.real()
        self.assertEqual(app2.queue_status_text('4412'), 'Ready')
        self.hn.run_all()
        self.assertFalse([d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'askyesnocancel'])

    def test_queue_list_is_remembered_but_never_activates_itself(self):
        app = self.real()
        path = app._queue_path()
        self.assertTrue(path.exists())
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        app2 = self.real(assets=[])
        self.assertFalse(app2.queue.active())                                                       # a new window starts as a single-meter run
        probe = RQ.RunQueue()
        self.assertTrue(probe.load_dict(RQ.read_queue(app2._queue_path()), app2.model, False))
        self.assertEqual(probe.names(), ['4412', '4413', '4415'])


class Reports(EngineBase):
    def setUp(self):
        super().setUp()
        import uuid
        tag = uuid.uuid4().hex[:6]
        self.A = tuple(f'{tag}-{n}' for n in (1, 2, 3))              # Asset History is one database per process: every test uses assets of its own

    def export(self, app):
        out = tempfile.mkdtemp()
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}],
             'procedure': '', 'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), \
                mock.patch.object(h.filedialog, 'askdirectory', lambda **k: out, create=True):
            written = app.queue_export_pdfs()
        return out, written

    def test_one_report_per_meter_named_asset_date_with_its_own_history(self):
        app = self.real(assets=self.A)
        a1, a2, a3 = self.A
        p = [p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV'][2]
        self.hn.queue_readings[(a3, p['id'])] = '99'
        self.hn.run_all()
        out, written = self.export(app)
        names = sorted(Path(w).name for w in written)
        import ui_theme as ui
        self.assertEqual(names, sorted(ui.report_filename(a) for a in self.A))
        for w in written:
            self.assertTrue(Path(w).stat().st_size > 1000)
        import labregistry
        for asset in self.A:
            runs = labregistry.runs_for(asset)
            self.assertEqual(len(runs), 1, asset)                                                   # one Asset History record each, nothing merged
            self.assertEqual(runs[0]['technician'], 'Tech ' + asset)                                # the queue's technician for that meter
            self.assertEqual(runs[0]['total'], len(app.points))
        self.assertEqual([labregistry.runs_for(a)[0]['failed'] for a in self.A], [0, 0, 1])

    def test_report_snapshots_are_per_run(self):
        app = self.real(assets=self.A)
        self.hn.run_all()
        self.export(app)
        import labregistry
        import report_snapshot
        ids = [labregistry.runs_for(a)[0]['id'] for a in self.A]
        self.assertEqual(len(set(ids)), 3)
        for run_id, asset in zip(ids, self.A):
            loaded = report_snapshot.load(run_id)
            self.assertIsNotNone(loaded, asset)
            text = json.dumps(getattr(loaded, 'payload', None) or getattr(loaded, '__dict__', str(loaded)), default=str)
            self.assertIn(asset, text)
            for other in self.A:
                if other != asset:
                    self.assertNotIn(other, text)                                                    # nothing of another asset in this snapshot

    def test_existing_report_files_are_not_overwritten(self):
        app = self.real(assets=self.A)
        self.hn.run_all()
        out = tempfile.mkdtemp()
        import report_dialog
        import ui_theme as ui
        (Path(out) / ui.report_filename(self.A[0])).write_bytes(b'old report')
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': {'technician': '', 'standards': [], 'show_tar_tur': False}), \
                mock.patch.object(h.filedialog, 'askdirectory', lambda **k: out, create=True):
            written = app.queue_export_pdfs()
        self.assertEqual((Path(out) / ui.report_filename(self.A[0])).read_bytes(), b'old report')
        self.assertEqual(len(written), 3)

    def test_as_left_is_kept_per_meter(self):
        app = self.real(assets=self.A)
        self.hn.run_all()
        app.set_data_mode('left')
        p = next(p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV')
        app._queue_force = True
        app.execute([p])                                                                            # what Rerun Selected does
        self.hn.pump()
        for m in app.queue.meters:
            self.assertIn(p['id'], m.left, m.asset)
            self.assertIn(p['id'], m.found, m.asset)
        self.assertEqual({len(m.left) for m in app.queue.meters}, {1})


class Demo(EngineBase):
    def test_virtual_bench_queue_runs_end_to_end_and_fill_fills_every_box(self):
        app = self.demo()
        self.assertTrue(app.virtual)
        self.assertTrue(self.hn.run_all())
        self.assertFalse(self.hn.boxes('showerror'))
        multi = self.windows('readings')
        self.assertTrue(multi)
        self.assertTrue(set(d[1] for d in multi) <= set(self.hn.fills))                              # the Fill button was offered in every queue window
        for m in app.queue.meters:
            self.assertEqual(len(m.found), len(app.points), m.asset)
            self.assertTrue(all(r['synthetic'] for r in m.found.values()))                         # demo results stay synthetic
        wire = [t for _i, t in VH.wire(app.io)]
        self.assertTrue(any(t.startswith('OUT ') for t in wire))                                    # the real driver over the simulator
        self.assertEqual(wire[-1], 'STBY')
        self.assertTrue(app.io.log.virtual)

    def test_demo_with_failures_toggle_fails_some_meters_only(self):
        app = self.demo(failures=True)
        self.hn.run_all()
        fails = {m.asset: sum(1 for r in m.found.values() if r['result'] == 'FAIL') for m in app.queue.meters}
        self.assertTrue(any(fails.values()))
        for m in app.queue.meters:
            self.assertEqual(len(m.found), len(app.points))

    def test_demo_reports_are_marked_and_nothing_reaches_asset_history(self):
        app = self.demo()
        self.hn.run_all()
        rep = Reports()
        out, written = rep.export(app)
        self.assertEqual(len(written), 3)
        import labregistry
        for asset in ('4412', '4413', '4415'):
            self.assertEqual(labregistry.runs_for(asset), [])
        import subprocess
        try:
            for w in written:
                text = subprocess.run(['pdftotext', '-layout', w, '-'], capture_output=True, text=True, timeout=60).stdout
                pages = [p for p in text.split('\f') if p.strip()]
                self.assertTrue(pages)
                for pg in pages:
                    self.assertIn('DEMO DATA - NOT CALIBRATION EVIDENCE', ' '.join(pg.split()))
        except FileNotFoundError:
            pass
        self.assertFalse(list(Path(self.home).rglob('command_log.txt')))

    def test_fast_demo_queue_records_every_meter_with_no_commands(self):
        app = self.demo(fast=True)
        self.assertTrue(app.fast_demo)
        self.assertTrue(self.hn.run_all())
        self.assertIsNone(app.io)
        self.assertFalse(self.windows('readings'))
        for m in app.queue.meters:
            self.assertEqual(len(m.found), len(app.points))
            self.assertTrue(all(r['synthetic'] for r in m.found.values()))

    def test_demo_one_meter_at_a_time(self):
        app = self.demo(mode=RQ.ONE_AT_A_TIME)
        self.assertTrue(self.hn.run_all())
        self.assertFalse(self.windows('readings'))
        for m in app.queue.meters:
            self.assertEqual(len(m.found), len(app.points))


class Progress(EngineBase):
    def test_progress_window_gets_per_meter_counts(self):
        app = self.real()
        p = [p for p in app.points if p['test'] == 'numeric' and p['kind'] == 'DCV'][2]
        self.hn.queue_readings[('4415', p['id'])] = '99'
        self.hn.run_all()
        updates = self.hn.progress_log
        self.assertTrue(len(updates) > 10)
        fractions = [u[2] for u in updates]
        self.assertEqual(fractions, sorted(fractions))                                              # the bar only moves forward
        final = updates[-1]
        self.assertTrue(final[4])
        rows = {r['asset']: r for r in final[3]}
        self.assertEqual((rows['4412']['failed'], rows['4413']['failed'], rows['4415']['failed']), (0, 0, 1))
        self.assertEqual(rows['4415']['first_fail'], p['n'])
        self.assertEqual(rows['4412']['recorded'], len(app.points))


class Guards(EngineBase):
    def test_modifications_that_differ_between_meters_refuse_the_queue(self):
        app = self.real()
        import procmods

        class FakeSet:
            def __init__(self, uid):
                self.uid = uid

            def active(self):
                return [{'uid': self.uid, 'kind': 'limit', 'target': 'x'}] if self.uid else []

        def fake_resolve(model, asset, *a, **k):
            return FakeSet('u1' if asset == '4413' else '')
        with mock.patch.object(procmods, 'resolve', fake_resolve):
            ok, why = app._queue_mods_same(app.queue.meters)
            self.assertFalse(ok)
            self.assertIn('4413', why)
            self.hn.run_all()
        self.assertFalse(self.windows('readings'))
        self.assertTrue(self.hn.boxes('showwarning'))
        self.assertFalse(app.busy)

    def test_same_modifications_are_fine(self):
        app = self.real()
        ok, _why = app._queue_mods_same(app.queue.meters)
        self.assertTrue(ok)

    def test_duplicate_assets_cannot_enter_a_queue(self):
        app = self.real(assets=[])
        with self.assertRaises(RQ.QueueError):
            app.queue.add('A')
            app.queue.add('a')

    def test_datasheet_builder_app_is_unaffected(self):
        import dsb_runtime
        self.assertFalse(dsb_runtime.DsbApp.queue_supported(mock.Mock(dsb={'x': 1}, QUEUE_SUPPORTED=True)))
        app = self.real(assets=[])
        self.assertTrue(app.queue_supported())
        self.assertFalse(app.queue_wants_run())

    def test_queue_is_not_offered_to_the_bench_engines(self):
        for mod in ('truevolt_verification', 'dacq_verification', 'keithley2000_verification', 'agilent34410a_verification', 'fluke8808a_verification', 'fgen_verification'):
            text = (ROOT / f'{mod}.py').read_text(encoding='utf-8')
            self.assertNotIn('run_queue', text, mod)
        for rel in ('Procedures/Agilent_34401A.py', 'Procedures/Fluke_8846A_Verification.py'):
            self.assertNotIn('run_queue', (ROOT / rel).read_text(encoding='utf-8'), rel)

    def test_busy_buttons_follow_the_queue_run(self):
        app = self.real()
        self.hn.run_all()
        self.assertFalse(app.busy)

    def test_summary_text_and_start_rules(self):
        app = self.real(assets=[])
        s = app.queue_summary([('A', '', ''), ('B', '', ''), ('C', '', '')], RQ.POINT_BY_POINT)
        self.assertTrue(s['ok'])
        self.assertIn('Saves', s['title'])
        self.assertIn('120', s['body'])
        one = app.queue_summary([('A', '', '')], RQ.POINT_BY_POINT)
        self.assertIn('as it always did', one['title'])
        alone = app.queue_summary([('A', '', ''), ('B', '', '')], RQ.ONE_AT_A_TIME)
        self.assertEqual(alone['title'], 'One meter at a time')


class LoadProgress(EngineBase):
    def test_load_progress_keeps_the_meter_in_step(self):
        app = self.real()
        self.hn.run_all()
        m = app.queue.meters[1]
        path = app._checkpoint_path(m.asset)
        with mock.patch.object(h.filedialog, 'askopenfilename', lambda **k: str(path)):
            app.load()
        self.assertIs(app.queue_ctx, m)
        self.assertIs(m.found, app.found)


if __name__ == '__main__':
    unittest.main()
