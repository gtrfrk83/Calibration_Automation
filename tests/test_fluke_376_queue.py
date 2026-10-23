"""Run queue for the Fluke 374 / 375 / 376 / 376-II clamp meter procedures with the PER-METER iFlex setting (iflex_option.py on run_queue*.py).

Every queue meter carries its own 'iFlex supplied' value (default ON).  The real App code runs on the simulated bench (tkinter is stubbed in setUpModule, as in
tests/test_beta_run_queue.py); only the modal windows are scripted.  The real windows are viewed on a real Tk under Xvfb in tests/real_tk_checks.py::checks_fluke_376.
"""
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import run_queue as RQ  # noqa: E402  (Tk-free)

h = VH = X = None
SPEC_NAME = 'fluke_376_pv.json'
MODELS = ('374', '375', '376', '376-II')


def setUpModule():
    global h, VH, X
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import iflex_option as _x
    import virtual_harness as _vh
    h, VH, X = _h, _vh, _x


def typed_nominal(p):
    return VH.DH.typed_nominal(p) if p['test'] == 'numeric' and p.get('nominal') is not None else None


class Base(unittest.TestCase):
    MODEL = '376'

    def setUp(self):
        self.hn = VH.VHarness().start()
        self.hn.fill = False
        self.home = self.hn.home
        tag = uuid.uuid4().hex[:6]                                   # Asset History is one database per process: every test uses assets of its own
        self.A, self.B, self.C = f'{tag}-1', f'{tag}-2', f'{tag}-3'

    def tearDown(self):
        self.hn.stop()

    def real(self, assets=None, mode=RQ.POINT_BY_POINT, model=None, off=()):
        """A REAL (not demo) run on the simulated calibrator, typed readings.  `off`: assets whose iFlex setting is OFF."""
        from drivers.simulated import make_bench
        from test_handheld_options import Spy
        bench, _a, _b = make_bench()
        io = h.IO('Fluke 5522A', 'sim', transport=Spy(bench, '5522A'))
        io.auto_ramp = False
        io._wait = lambda *a, **k: None
        app = X.App(self.hn.root, model or self.MODEL, demo=False, spec=h.load_spec(SPEC_NAME), io_factory=lambda: io)
        app.cal_mode.set(h.CAL_CHOICES[1])
        app.io = io
        self.hn.app = app
        self.io = io
        self.hn.default_reading = typed_nominal
        assets = assets or (self.A, self.B)
        app.apply_queue([(a, 'S-' + a, 'Tech ' + a) for a in assets], mode)
        for a in off:
            self.assertTrue(app.set_include('iflex', False, ask=False, meter=app.queue.find(a)))
        return app

    def demo(self, assets=None, off=(), fast=False):
        app = X.App(self.hn.root, self.MODEL, demo=True, spec=h.load_spec(SPEC_NAME), fast_demo=fast)
        app.demo_failures = None
        app.demo_failures_on = False
        self.hn.app = app
        self.hn.fill = True
        assets = assets or (self.A, self.B)
        app.apply_queue([(a, 'S-' + a, 'Tech ' + a) for a in assets], RQ.POINT_BY_POINT)
        for a in off:
            app.set_include('iflex', False, ask=False, meter=app.queue.find(a))
        return app

    def windows(self, kind):
        return [d for d in self.hn.dialogs if d[0] == kind]

    def wire(self):
        return [t for _i, t in VH.wire(self.io)]

    def counts(self):
        titles = [d[1] for d in self.hn.dialogs if d[0] == 'confirm']
        return dict(cable=titles.count('Change the cables'), function=titles.count('Change the function'), setup=titles.count('Meter setup'),
                    next_meter=titles.count('Next meter') + titles.count('One meter at a time'), hv=sum(1 for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE'),
                    readings=len(self.windows('readings')) + len(self.windows('reading')))

    def export(self, app):
        out = tempfile.mkdtemp()
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '',
             'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), \
                mock.patch.object(h.filedialog, 'askdirectory', lambda **k: out, create=True):
            written = app.queue_export_pdfs()
        return out, written


def iflex_ids(app):
    return {p['id'] for p in app._all_points if p.get('include') == 'iflex'}


# ===================================================================================================================== the setting itself
class PerMeterSetting(Base):
    def test_default_is_on_for_every_meter_and_shown_everywhere(self):
        app = self.real()
        self.assertTrue(app.queue.active())
        self.assertTrue(app.queue_supported())
        for m in app.queue.meters:
            self.assertEqual(m.extra['include'], {'iflex': True})
        self.assertEqual(len(app.points), 38)
        self.assertIn('iFlex ON for all', app.queue_chip_text())
        self.assertIn('iFlex ON', app.queue_status_text(self.A))
        self.assertIn('iFlex ON', app.queue_status_text(self.B))
        self.assertIn('iFlex ON for all', app.queue_label.get())

    def test_each_meter_has_its_own_value_shown_in_chip_list_and_drawer(self):
        app = self.real(off=(self.B,))
        a, b = app.queue.meters
        self.assertTrue(a.extra['include']['iflex'])
        self.assertFalse(b.extra['include']['iflex'])
        self.assertEqual(len(app.points), 38)                                  # the window lists the union: any meter takes part
        self.assertEqual((app.queue_total(a), app.queue_total(b)), (38, 29))
        self.assertIn('ON for 1 of 2', app.queue_chip_text())
        self.assertIn('iFlex ON', app.queue_status_text(self.A))
        self.assertIn('iFlex OFF', app.queue_status_text(self.B))
        self.assertTrue(app.queue_status_text(self.B).startswith('Ready'))
        self.assertEqual(set(app._inc_row_vars), {self.A, self.B})             # one check box per meter in the Connections drawer
        self.assertTrue(app._inc_row_vars[self.A].get())
        self.assertFalse(app._inc_row_vars[self.B].get())
        self.assertIn('not tested', app._meter_include_note(b, app.include_defs()[0]))

    def test_the_window_box_is_the_setting_of_the_meter_shown(self):
        app = self.real(off=(self.B,))
        app.queue_show(self.A)
        self.assertTrue(app._include_vars['iflex'].get())
        self.assertIn(f'Asset {self.A}', app.include_text(short=True))
        app.queue_show(self.B)
        self.assertFalse(app._include_vars['iflex'].get())
        self.assertFalse(app.include_is_on())
        shown = [p for p in app.points if app._visible(p)]
        self.assertEqual(len(shown), 29)                                       # the iFlex points are not shown as pending for the meter that does not take part
        self.assertEqual(sum(1 for p in app.points if p.get('include') == 'iflex' and app._visible(p)), 0)
        app._on_include_click('iflex')                                         # the box is the shown meter's: switching it back ON
        app._include_vars['iflex'].set(True)
        app._on_include_click('iflex')
        self.assertTrue(app.queue.find(self.B).extra['include']['iflex'])
        self.assertTrue(app.queue.find(self.A).extra['include']['iflex'])

    def test_turning_off_asks_and_names_the_asset(self):
        app = self.real()
        self.assertTrue(app.set_include('iflex', False, meter=app.queue.find(self.B)))
        q = [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'Skip the iFlex tests']
        self.assertEqual(len(q), 1)
        self.assertIn(f'Asset {self.B}', q[0][3])
        self.assertIn('9 iFlex point(s) will not be run', q[0][3])
        self.assertTrue(app.queue.find(self.A).extra['include']['iflex'])

    def test_declining_keeps_it_on_and_the_drawer_box_snaps_back(self):
        app = self.real()
        self.hn.box_answer['askyesno'] = False
        b = app.queue.find(self.B)
        app._inc_row_vars[self.B].set(False)
        app._on_meter_include_click(b, app._inc_row_vars[self.B])
        self.assertTrue(b.extra['include']['iflex'])
        self.assertTrue(app._inc_row_vars[self.B].get())

    def test_not_while_a_run_is_active(self):
        app = self.real()
        app.busy = True
        self.assertFalse(app.set_include('iflex', False, ask=False, meter=app.queue.find(self.B)))
        self.assertTrue(app.queue.find(self.B).extra['include']['iflex'])
        self.assertIn('cannot be changed while a run is active', app.status.set.call_args[0][0])
        app.busy = False
        self.assertTrue(app.set_include('iflex', False, ask=False, meter=app.queue.find(self.B)))

    def test_a_recorded_reading_is_never_discarded(self):
        app = self.real()
        a, b = app.queue.meters
        b.found['1-31'] = dict(result='PASS', entered='1000', reading=1000.0, data='As Found', synthetic=False, source='typed')
        self.assertTrue(app.set_include('iflex', False, ask=False, meter=b))
        self.assertIn('1-31', b.found)                                          # kept
        self.assertTrue(b.wants(app.by_id['1-31']))                             # and still part of this meter's list
        self.assertFalse(b.wants(app.by_id['1-30']))
        self.assertEqual(app.queue_total(b), 30)
        self.assertEqual(app.queue_total(a), 38)

    def test_all_meters_off_shortens_the_window_list(self):
        app = self.real(off=(self.A, self.B))
        self.assertEqual(len(app.points), 29)
        self.assertIn('iFlex OFF for all', app.queue_chip_text())
        self.assertEqual({p['n'] for p in app.points}, set(range(1, 30)))

    def test_single_meter_runs_are_unchanged(self):
        app = self.real(assets=(self.A,))
        self.assertFalse(app.queue.active())
        self.assertEqual(len(app.points), 38)
        self.assertEqual(app.queue_chip_text(), '')
        app.set_include('iflex', False, ask=False)
        self.assertEqual(len(app.points), 29)
        self.assertFalse(app.queue.meters[0].extra['include']['iflex'])         # the one meter in the list carries it too


# ===================================================================================================================== planning
class Planning(Base):
    def units(self, app, **kw):
        return RQ.plan(list(app.points), app.queue, app.queue_options(), mode=kw.pop('mode', RQ.POINT_BY_POINT), **kw)

    def test_a_meter_without_the_iflex_tests_is_never_planned_for_them(self):
        app = self.real(off=(self.B,))
        units = self.units(app)
        a, b = app.queue.meters
        got = {a.asset: [], b.asset: []}
        for u in units:
            for p in u.points:
                for m in (u.needs.get(str(p['id'])) or u.meters):
                    got[m.asset].append(p['id'])
        self.assertEqual(sorted(got[self.A]), sorted(p['id'] for p in app.points))
        self.assertEqual(sorted(got[self.B]), sorted(p['id'] for p in app.points if p.get('include') != 'iflex'))
        self.assertEqual(len(got[self.A]), 38)
        self.assertEqual(len(got[self.B]), 29)
        for u in units:
            if any(p.get('include') == 'iflex' for p in u.points):
                self.assertEqual([m.asset for m in u.meters], [self.A])         # the iFlex points: a unit for the meter that has them
                self.assertFalse(u.shared)                                       # only one meter needs them: they are not a shared unit
                self.assertTrue(u.prompt)                                        # 'connect only meter A' before them

    def test_on_and_on_is_the_plan_it_always_was(self):
        app = self.real()
        units = self.units(app)
        for u in units:
            self.assertTrue(all(m in u.needs.get(str(p['id']), u.meters) for p in u.points for m in u.meters if u.shared) or not u.shared)
        shared = [p['id'] for u in units if u.shared for p in u.points]
        self.assertIn('1-30', shared)                                            # the iFlex simulation points are volts: shared when both meters have them
        self.assertEqual(len([1 for u in units for p in u.points for m in u.meters]), sum(len(u.points) * len(u.meters) for u in units))

    def test_three_meters_two_with_iflex_name_only_the_wired_meters(self):
        app = self.real(assets=(self.A, self.B, self.C), off=(self.C,))
        units = self.units(app)
        for u in units:
            ids = {p['id'] for p in u.points}
            if u.shared and ids & {'1-30', '1-31'}:
                self.assertEqual([m.asset for m in u.needs['1-30']], [self.A, self.B])
        self.assertEqual({m.asset for u in units for m in u.meters if any(p.get('include') == 'iflex' for p in u.points)}, {self.A, self.B})

    def test_the_setup_summary_counts_only_the_points_each_meter_takes_part_in(self):
        app = self.real(off=(self.B,))
        info = RQ.summary(app.points, app.queue, app.queue_options())
        self.assertEqual((info['points'], info['meters'], info['alone']), (38, 2, 38 + 29))
        text = app.queue_summary([(self.A, '', ''), (self.B, '', '')], RQ.POINT_BY_POINT)       # the set-up window: B's saved setting (OFF) is used
        self.assertIn('= 67 settings one meter at a time', text['body'])
        self.assertIn('needs 55 (12 shared', text['body'])                                       # 12 shared voltage points + 17 other points x 2 meters + 9 iFlex points for A alone
        other = self.real(assets=(self.A + 'x', self.B + 'x'))
        info_on = RQ.summary(other.points, other.queue, other.queue_options())
        self.assertEqual(info_on['alone'], 76)

    def test_progress_totals_are_per_meter(self):
        app = self.real(off=(self.B,))
        rows = RQ.progress(app.queue, app.points)
        self.assertEqual([r['total'] for r in rows], [38, 29])

    def test_lacking_ignores_the_points_a_meter_does_not_take_part_in(self):
        app = self.real(off=(self.B,))
        a, b = app.queue.meters
        for p in app.points:
            if p.get('include') != 'iflex':
                a.found[str(p['id'])] = b.found[str(p['id'])] = dict(result='PASS')
        pend = app.queue_pending(app.points)
        self.assertEqual({p['id'] for p in pend}, iflex_ids(app))               # only meter A still lacks the iFlex points
        for p in app.points:
            if p.get('include') == 'iflex':
                a.found[str(p['id'])] = dict(result='PASS')
        self.assertEqual(app.queue_pending(app.points), [])                      # B is complete with 29 points


# ===================================================================================================================== running
class Running(Base):
    def test_on_off_queue_end_to_end_on_the_bench(self):
        app = self.real(off=(self.B,))
        self.assertTrue(self.hn.run_all())
        self.assertFalse(self.hn.boxes('showerror'))
        a, b = app.queue.meters
        self.assertEqual((len(a.found), len(b.found)), (38, 29))
        self.assertFalse(set(b.found) & iflex_ids(app))                          # no iFlex reading was asked for meter B
        self.assertEqual(set(a.found) & iflex_ids(app), iflex_ids(app))
        for m in (a, b):
            self.assertEqual({r['result'] for r in m.found.values()}, {'PASS'})
            self.assertTrue(all(not r['synthetic'] for r in m.found.values()))
        self.assertEqual((a.status, b.status), ('Done', 'Done'))                 # B is complete with its 29 points
        # the iFlex points were read in single-meter windows (asset A only), never in a window that names B
        for d in self.windows('readings'):
            if d[1] in iflex_ids(app):
                self.assertEqual(d[2], [self.A])
        cal = [t for t in self.wire() if t.startswith('OUT ') and not t.endswith('?')]
        shared_pts = [p for p in app.points if p.get('include') != 'iflex' and RQ.share_reason(p, app.queue_options()) is None]
        single_pts = [p for p in app.points if p.get('include') != 'iflex' and RQ.share_reason(p, app.queue_options()) is not None]
        want = len([p for p in shared_pts if p.get('applied')]) + 2 * len([p for p in single_pts if p.get('applied')]) + len([p for p in app.points if p.get('include') == 'iflex' and p.get('applied')])
        self.assertEqual(len(cal), want)
        self.assertEqual(self.wire()[-1], 'STBY')                                # outputs go to standby after the run

    def test_outputs_go_to_standby_after_each_point(self):
        app = self.real(off=(self.B,))
        self.hn.run_all()
        last_oper = None
        for n, t in enumerate(self.wire()):
            if t.startswith('OUT ') and not t.endswith('?'):
                self.assertIsNone(last_oper, f'an OUT at {n} while the previous output was still on')
                last_oper = n
            if t == 'STBY':
                last_oper = None

    def test_prompt_counts_on_on_versus_on_off(self):
        got = {}
        for label, off in (('on_on', ()), ('on_off', (self.B,))):
            self.hn.stop()
            self.hn = VH.VHarness().start()
            self.hn.fill = False
            app = self.real(off=off)
            self.assertTrue(self.hn.run_all())
            got[label] = self.counts()
        # point by point, two meters: the shared part (voltage) is prompted once for both; resistance, capacitance and current are one meter at a time (a cable / function
        # prompt per meter and a swap prompt between them).  Meter B without the iFlex tests skips the iFlex-loop cable prompts and the coil iFlex reading windows.
        self.assertEqual(got['on_on'], dict(cable=16, function=14, setup=0, next_meter=4, hv=1, readings=59))
        self.assertEqual(got['on_off'], dict(cable=14, function=12, setup=0, next_meter=2, hv=1, readings=55))
        # the same flow without any iFlex point at all (both OFF) is the shortest
        self.hn.stop()
        self.hn = VH.VHarness().start()
        self.hn.fill = False
        self.real(off=(self.A, self.B))
        self.assertTrue(self.hn.run_all())
        both_off = self.counts()
        self.assertEqual(both_off['readings'], 12 + 2 * 17)                      # 12 shared voltage windows + the 17 other points once per meter (no iFlex point at all)
        self.assertLessEqual(both_off['cable'], got['on_off']['cable'])

    def test_prompts_name_only_the_meters_wired_for_the_point(self):
        app = self.real(assets=(self.A, self.B, self.C), off=(self.C,))
        self.assertTrue(self.hn.run_all())
        texts = [(d[1], ' '.join(map(str, d[3:]))) for d in self.hn.dialogs if d[0] == 'confirm']
        first = [t for title, t in texts if title in ('Change the cables', 'Change the function') and f'{self.A}, {self.B}, {self.C}' in t]
        self.assertTrue(first)                                                    # the shared part names all three
        tail = [t for title, t in texts if title in ('Change the cables', 'Change the function') and ('iFlex' in t)]
        self.assertTrue(tail)
        for t in tail:
            self.assertNotIn(self.C, t)                                          # the iFlex prompts never name the meter without the iFlex tests

    def test_one_meter_at_a_time_gives_each_meter_its_own_list(self):
        app = self.real(mode=RQ.ONE_AT_A_TIME, off=(self.B,))
        self.assertTrue(self.hn.run_all())
        a, b = app.queue.meters
        self.assertEqual((len(a.found), len(b.found)), (38, 29))
        self.assertEqual(self.counts()['readings'], 38 + 29)

    def test_run_all_pending_again_asks_for_nothing_when_every_meter_is_complete(self):
        app = self.real(off=(self.B,))
        self.hn.run_all()
        before = self.counts()['readings']
        self.hn.run_all()
        self.assertEqual(self.counts()['readings'], before)
        self.assertEqual(app.queue_pending(app.points), [])

    def test_rerun_selected_respects_the_setting(self):
        app = self.real(off=(self.B,))
        self.hn.run_all()
        p = app.by_id['1-30']
        app._queue_force = True
        self.hn.default_reading = typed_nominal
        app.set_data_mode('left')
        app._queue_force = True
        app.execute([p])
        self.hn.pump()
        a, b = app.queue.meters
        self.assertIn('1-30', a.left)
        self.assertNotIn('1-30', b.left)


# ===================================================================================================================== checkpoint, queue file, resume
class Persistence(Base):
    def test_checkpoint_and_queue_file_carry_the_setting(self):
        app = self.real(off=(self.B,))
        self.hn.run_all()
        a, b = app.queue.meters
        for m, want in ((a, True), (b, False)):
            data = json.loads(Path(app._checkpoint_path(m.asset)).read_text())
            self.assertEqual(data['include'], {'iflex': want}, m.asset)
            self.assertEqual(data['asset'], m.asset)
        data = json.loads(Path(app._queue_path()).read_text())
        by = {row['asset']: row for row in data['meters']}
        self.assertEqual(by[self.A]['include'], {'iflex': True})
        self.assertEqual(by[self.B]['include'], {'iflex': False})
        self.assertEqual(data['meters'][0].keys() - {'include'}, {'asset', 'serial', 'tech'})
        log = json.loads(Path(app._checkpoint_path(self.B)).read_text())['include_log']
        self.assertEqual([e['value'] for e in log], [False])                      # B's own audit entry; A has none
        self.assertEqual(json.loads(Path(app._checkpoint_path(self.A)).read_text())['include_log'], [])

    def test_a_new_window_restores_the_setting_and_resumes_each_meter(self):
        app = self.real(off=(self.B,))
        stop_at = app.by_id['1-33']                                              # stop inside the iFlex points: A has 32 readings, B has 29
        self.hn.queue_action[stop_at['id']] = 'stop'
        self.hn.run_all()
        a, b = app.queue.meters
        done = {m.asset: set(m.found) for m in (a, b)}
        self.assertEqual(len(done[self.B]), 29)
        self.assertTrue(len(done[self.A]) >= 30)
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        self.hn.fill = False
        app2 = self.real()                                                        # the same assets; nobody touches the setting
        a2, b2 = app2.queue.meters
        self.assertTrue(a2.extra['include']['iflex'])
        self.assertFalse(b2.extra['include']['iflex'])                           # restored from B's own checkpoint
        self.assertIn('iFlex OFF', app2.queue_status_text(self.B))
        self.assertEqual(app2.queue_total(b2), 29)
        self.assertIn('Saved progress: 29 of 29', app2.queue_status_text(self.B))
        self.hn.box_answer['askyesnocancel'] = True
        self.hn.run_all()
        asked = [d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'askyesnocancel']
        self.assertEqual(len(asked), 1)
        self.assertEqual((len(a2.found), len(b2.found)), (38, 29))
        measured = {d[1] for d in self.windows('readings')} | {d[1] for d in self.windows('reading')}
        self.assertFalse(measured & done[self.A])                                 # points already recorded are not measured again
        self.assertFalse(measured & set(b2.found))                                 # nothing was asked for meter B at all
        self.assertFalse(set(b2.found) & iflex_ids(app2))

    def test_the_queue_file_alone_restores_the_setting_for_a_meter_without_progress(self):
        app = self.real(off=(self.B,))
        self.assertTrue(Path(app._queue_path()).exists())
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        app2 = self.real()
        self.assertFalse(app2.queue.find(self.B).extra['include']['iflex'])
        self.assertTrue(app2.queue.find(self.A).extra['include']['iflex'])

    def test_a_change_made_after_the_checkpoint_wins_and_is_saved(self):
        app = self.real()
        stop_at = app.by_id['1-12']
        self.hn.queue_action[stop_at['id']] = 'stop'
        self.hn.run_all()
        self.assertTrue(app.set_include('iflex', False, ask=False, meter=app.queue.find(self.B)))      # B has readings: the change is saved with them
        data = json.loads(Path(app._checkpoint_path(self.B)).read_text())
        self.assertEqual(data['include'], {'iflex': False})
        self.assertEqual([e['value'] for e in data['include_log']], [False])
        self.assertGreaterEqual(data['include_log'][0]['recorded'], 1)
        self.assertEqual(json.loads(Path(app._checkpoint_path(self.A)).read_text())['include'], {'iflex': True})

    def test_declining_the_resume_starts_over_with_the_setting_unchanged(self):
        app = self.real(off=(self.B,))
        self.hn.queue_action[app.by_id['1-9']['id']] = 'stop'
        self.hn.run_all()
        self.hn.stop()
        self.hn = VH.VHarness(home=self.home).start()
        self.hn.fill = False
        app2 = self.real()
        self.hn.box_answer['askyesnocancel'] = False
        self.hn.run_all()
        a2, b2 = app2.queue.meters
        self.assertEqual((len(a2.found), len(b2.found)), (38, 29))
        self.assertFalse(b2.extra['include']['iflex'])

    def test_load_progress_brings_the_setting_of_that_file(self):
        app = self.real(off=(self.B,))
        self.hn.queue_action[app.by_id['1-9']['id']] = 'stop'
        self.hn.run_all()
        path = app._checkpoint_path(self.B)
        data = json.loads(Path(path).read_text())
        app.queue_show(self.B)
        app.set_include('iflex', True, ask=False, meter=app.queue.find(self.B))
        self.assertTrue(app.queue.find(self.B).extra['include']['iflex'])
        with mock.patch.object(h.filedialog, 'askopenfilename', lambda **k: str(path)):
            data['include'] = {'iflex': False}
            Path(path).write_text(json.dumps(data))
            app.load()
        self.assertFalse(app.queue.find(self.B).extra['include']['iflex'])
        self.assertTrue(app.queue.find(self.A).extra['include']['iflex'])


# ===================================================================================================================== reports
class Reports(Base):
    def text(self, path):
        return subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout

    def test_each_meter_report_carries_its_own_iflex_line(self):
        app = self.real(off=(self.B,))
        self.hn.run_all()
        out, written = self.export(app)
        by = {}
        for w in written:
            by[Path(w).name] = self.text(w)
        import ui_theme as ui
        ta, tb = by[ui.report_filename(self.A)], by[ui.report_filename(self.B)]
        self.assertIn('iFlex tests', ta)
        self.assertIn('Tested (iFlex supplied)', ' '.join(ta.split()))
        self.assertNotIn('Not tested (no iFlex supplied)', ' '.join(ta.split()))
        self.assertIn('iFlex tests', tb)
        self.assertIn('Not tested (no iFlex supplied)', ' '.join(tb.split()))
        self.assertNotIn('Tested (iFlex supplied)', ' '.join(tb.split()))
        self.assertIn('iFlex simulated', ta)                                      # A has the iFlex rows
        self.assertNotIn('iFlex simulated', tb)                                   # B has none
        self.assertNotIn('iFlex with coil', tb)

    def test_row_counts_match_the_points_each_meter_took_part_in(self):
        app = self.real(off=(self.B,))
        self.hn.run_all()
        for m, n in zip(app.queue.meters, (38, 29)):
            app._queue_activate(m)
            rows, _pts = app.certificate_rows_and_points()
            self.assertEqual(len(rows), n, m.asset)
        import labregistry
        self.export(app)
        self.assertEqual([labregistry.runs_for(a)[0]['total'] for a in (self.A, self.B)], [38, 29])

    def test_a_reading_recorded_before_turning_it_off_stays_in_the_report(self):
        app = self.real()
        a, b = app.queue.meters
        self.hn.queue_action['1-32'] = 'stop'
        self.hn.run_all()
        self.assertIn('1-31', b.found)
        app.set_include('iflex', False, ask=False, meter=b)
        app._queue_activate(b)
        header = dict(app.report_header(app.spec['source']))
        self.assertIn('Not tested', header['iFlex tests'])
        self.assertIn('recorded before it was turned off are included', header['iFlex tests'])
        rows, pts = app.certificate_rows_and_points()
        self.assertEqual(len(rows), 31)                                          # 29 plus the two iFlex readings taken before it was turned off (1-30, 1-31)
        self.assertIn('1-31', [p['id'] for p in pts])
        self.assertEqual(sum(1 for p in pts if p.get('include') == 'iflex'), 2)


class Demo(Base):
    def test_demo_marking_is_unchanged_and_a_demo_queue_runs_with_mixed_settings(self):
        app = self.demo(off=(self.B,))
        self.assertTrue(app.virtual)
        self.assertTrue(self.hn.run_all())
        a, b = app.queue.meters
        self.assertEqual((len(a.found), len(b.found)), (38, 29))
        for m in (a, b):
            self.assertTrue(all(r['synthetic'] for r in m.found.values()), m.asset)
        self.assertTrue(app.any_synthetic())
        data = json.loads(Path(app._checkpoint_path(self.B)).read_text())
        self.assertTrue(data['demo'])
        self.assertEqual(data['include'], {'iflex': False})
        out, written = self.export(app)
        for w in written:
            self.assertIn('DEMO', subprocess.run(['pdftotext', str(w), '-'], capture_output=True, text=True).stdout.upper())

    def test_a_demo_queue_is_never_a_real_one(self):
        app = self.demo(off=(self.B,))
        probe = RQ.RunQueue()
        self.assertFalse(probe.load_dict(RQ.read_queue(app._queue_path()), app.model, False))
        self.assertTrue(probe.load_dict(RQ.read_queue(app._queue_path()), app.model, True))

    def test_fast_demo(self):
        app = self.demo(off=(self.B,), fast=True)
        self.assertTrue(self.hn.run_all())
        a, b = app.queue.meters
        self.assertEqual((len(a.found), len(b.found)), (38, 29))


class Models(Base):
    def test_every_model_runs_a_mixed_queue(self):
        for model in MODELS:
            self.hn.stop()
            self.hn = VH.VHarness().start()
            self.hn.fill = False
            app = self.real(model=model, off=(self.B,))
            full = len(app.points)
            self.assertTrue(self.hn.run_all(), model)
            a, b = app.queue.meters
            self.assertEqual((len(a.found), len(b.found)), (full, full - 9), model)
            self.assertEqual({r['result'] for m in (a, b) for r in m.found.values()}, {'PASS'}, model)


class SharedFilesStayNeutral(unittest.TestCase):
    """The additive hooks in run_queue.py / run_queue_engine.py change nothing for a queue that does not use them."""
    def test_default_meter_takes_part_in_everything(self):
        m = RQ.QueueMeter('X1')
        self.assertTrue(m.wants({'id': '1-1'}))
        self.assertEqual(m.extra, {})
        q = RQ.RunQueue()
        q.add('X1', 'S', 'T')
        q.add('X2')
        d = q.to_dict('m', False)
        self.assertEqual(d['meters'][0], dict(asset='X1', serial='S', tech='T'))        # the queue file of every other procedure is byte-for-byte what it was

    def test_extra_roundtrips_through_the_queue_file(self):
        q = RQ.RunQueue()
        m = q.add('X1', 'S', 'T')
        m.extra['include'] = {'iflex': False}
        q.add('X2')
        r = RQ.RunQueue()
        self.assertTrue(r.load_dict(q.to_dict('m', False), 'm', False))
        self.assertEqual(r.meters[0].extra, {'include': {'iflex': False}})
        self.assertEqual(r.meters[1].extra, {})

    def test_skip_filter_is_honoured_by_plan_summary_and_progress(self):
        pts = [dict(id=f'1-{n}', n=n, kind='DCV', group='VOHM', test='numeric') for n in range(1, 6)]
        q = RQ.RunQueue()
        a, b = q.add('A'), q.add('B')
        b.skip = lambda p: p['n'] > 3
        units = RQ.plan(pts, q, {})
        flat = [(p['id'], tuple(m.asset for m in (u.needs.get(str(p['id'])) or u.meters))) for u in units for p in u.points]
        self.assertEqual(flat, [('1-1', ('A', 'B')), ('1-2', ('A', 'B')), ('1-3', ('A', 'B')), ('1-4', ('A',)), ('1-5', ('A',))])
        self.assertEqual(RQ.summary(pts, q, {})['alone'], 8)
        self.assertEqual([r['total'] for r in RQ.progress(q, pts)], [5, 3])
        b.skip = None
        self.assertEqual(RQ.summary(pts, q, {})['alone'], 10)


if __name__ == '__main__':
    unittest.main()
