"""The in-run procedure editor in every engine that supports procedure modifications (see test_beta_live_editor.py for the rules in depth).

Each engine's real App runs on its simulated bench.  While the first point is being measured the scripted technician uses the editor
(procmods_ui_model, built by the engine's pm_live_context) to skip the third point and add a note for the second.  Proved per engine:
the 'Edit point' action is attached, the edit reaches the point after the one in flight (before_point), the skipped point is never
measured, the note is shown once, nothing is applied to the point in flight, and the reset-to-defaults sequence is not repeated.
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402

import dsb_run_harness as DH  # noqa: E402  (the handheld engine's harness)
import drivers  # noqa: E402
import procmods  # noqa: E402
import procmods_engine as pe  # noqa: E402
import procmods_live as live  # noqa: E402
import dacq_verification as D  # noqa: E402
import fgen_verification as F  # noqa: E402
import handheld_dmm as HH  # noqa: E402
import mdo4000c_verification as M  # noqa: E402
import truevolt_verification as T  # noqa: E402
import Agilent_34401A as A  # noqa: E402
import Fluke_8846A_Verification as V  # noqa: E402
import WaveSurfer_WS4104HD as W  # noqa: E402
from drivers.simulated import SimFlukeTransport, make_bench, make_dacq_bench, make_dmm_bench  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402
from drivers.simulated_mdo import make_mdo_bench  # noqa: E402


def key_of(model, pid):
    keys = procmods.point_keys(model.ctx.points)
    return keys[[p.get('id', p.get('n')) for p in model.ctx.points].index(pid)]


class EngineLive:
    """Mixin: subclasses build `self.app`, `self.points` and `self.install(hook)` (the hook runs at the start of each measured point)."""
    NOTE = 'Use the short leads for this one'

    def scenario(self, run):
        app, pts = self.app, self.points
        done = {}

        def hook(n):
            if n == 1:
                m = self.model()
                self.assertTrue(m.live_mode)
                self.assertTrue(m.editable, m.read_only_reason)
                self.assertEqual(m.stage_skip(key_of(m, self.pid(pts[2])), True), [])
                self.assertEqual(m.stage_text('note:' + key_of(m, self.pid(pts[1])), self.NOTE), [])
                res = self.edit(m)
                self.assertTrue(res.ok, res.errors)
                done['dirty_in_flight'] = app.pm_state.live.dirty
                done['skip_in_effect_in_flight'] = bool(self.live_point(pts[2]).get('skip'))
        self.install(hook)
        run()
        self.assertTrue(done['dirty_in_flight'], 'saved but not applied while the point is in flight')
        self.assertFalse(done['skip_in_effect_in_flight'])
        ev = app.pm_state.live.events
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]['before_point'], self.pid(pts[1]))
        self.assertEqual({c['kind'] for c in ev[0]['changes']}, {'point', 'text'})
        self.assertEqual(self.measured_ids(), [self.pid(pts[0]), self.pid(pts[1]), self.pid(pts[3])], 'the skipped point was not measured')
        self.assertFalse(app.busy)
        self.assertEqual(len(pe.applied_modifications(app)), 2)
        self.assertEqual(len(app.pm_checkpoint_fields()['live_edits']), 1)
        self.check_note_shown(pts[1])
        self.check_reset_once()

    def live_point(self, p):
        return self.app._pm_live_lookup(self.pid(p))

    @staticmethod
    def pid(p):
        return p.get('id', p.get('n'))

    def edit(self, model):
        return self.h.edit(model, 'live test')

    def check_edit_action(self):
        calls = [c for c in self.app.shell.add_action.call_args_list if c.args and c.args[0] == 'Edit point']
        self.assertEqual(len(calls), 1, 'every window has exactly one Edit point control')
        self.assertIsNotNone(self.app.__dict__.get('_pm_live_hook'))
        self.assertEqual(calls[0].kwargs.get('short'), 'Edit')


class Plain(EngineLive):
    """Engines tested with the live_editor_harness."""

    def setUp(self):
        self.h = H.EngineHarness().start(*self.MODULES)
        self.addCleanup(self.h.stop)
        p = mock.patch('time.sleep', side_effect=lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.build()
        st = self.app.pm_state
        st.store, st.devmode = self.h.env.store, self.h.env.dm

    def model(self):
        return self.h.model(self.app)

    def measured_ids(self):
        order = [self.pid(p) for p in self.points]
        return [i for i in order if str(i) in self.app.results]

    def check_note_shown(self, p):
        notes = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'showinfo' and d[2].startswith('Note for point') and self.NOTE in d[3]]
        self.assertEqual(len(notes), 1)
        self.assertIn(str(self.pid(p)), notes[0][2])

    def check_reset_once(self):
        log = self.app.io.log
        text = [t for _ts, _i, d, t in log.entries if d == '>>']
        self.assertEqual(sum(1 for t in text if t == '*RST'), len(set(i for _ts, i, d, t in log.entries if d == '>>' and t == '*RST')),
                         'one reset per instrument, none repeated by an edit')

    def test_live_edit(self):
        self.check_edit_action()
        self.scenario(self.go)

    def go(self):
        self.app.execute(self.points)
        self.assertTrue(self.h.pump(60))


class DacqLive(Plain, unittest.TestCase):
    MODULES = (D,)

    def build(self):
        D.configure('34970A')
        app = self.app = D.App(self.h.root, '34970A', demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        _b, ft, dt = make_dacq_bench('34970A')
        app.io = D.IO('sim', 'sim', cal_model='Fluke 5560A', module='34901A', slot=2, transports=(dt, ft), mods=app.pm_state)
        self.points = [p for p in D.POINTS if p['kind'] == 'DCV' and p['source'] == 'calibrator'][:4]

    def install(self, hook):
        self.wrap(self.app.io, 'measure', hook)

    @staticmethod
    def wrap(obj, name, hook):
        orig, n = getattr(obj, name), {'n': 0}

        def f(*a, **k):
            n['n'] += 1
            hook(n['n'])
            return orig(*a, **k)
        setattr(obj, name, f)


class FgenLive(Plain, unittest.TestCase):
    MODULES = (F,)

    def build(self):
        F.configure('33220A')
        app = self.app = F.App(self.h.root, '33220A', demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        bench, t = make_fgen_bench('33220A')
        bench.connected = 'std'
        app.io = F.IO({}, transports=t, ask_number=lambda prompt, unit: 0.0, mods=app.pm_state)
        self.points = [p for p in F.POINTS if p['kind'] == 'ACAMP'][:4]

    install = DacqLive.install

    def wrap(self, obj, name, hook):
        DacqLive.wrap(obj, name, hook)


class HandheldLive(EngineLive, unittest.TestCase):
    """handheld_dmm.App (readings typed by the scripted operator) with the Datasheet Builder harness."""

    def setUp(self):
        self.h = DH.Harness().start()
        self.addCleanup(self.h.stop)
        self.env = H.Env()
        self.addCleanup(self.env.close)
        bench, _a, _b = make_bench()
        app = self.app = HH.App(self.h.root, '115', demo=False)
        self.h.app = app
        st = app.pm_state
        st.store, st.devmode = self.env.store, self.env.dm
        app.asset.set('A-100')
        app.serial.set('S')
        app.io = HH.IO('Fluke 5522A', 'sim', transport=SimFlukeTransport(bench, '5522A'), mods=st)
        self.points = [p for p in app.points if p.get('applied') and p['kind'] == 'DCV' and abs(p['applied']['value']) < 100][:4]
        self.h.default_reading = DH.typed_nominal

    def model(self):
        ctx = self.app.pm_live_context()
        ctx.store = self.env.store
        import procmods_ui_model as M_
        return M_.ProcModsModel(ctx, self.env.lock)

    def edit(self, model):
        model.set_scope('run')
        for kind, target in list(model.drafts):
            model.set_reason(kind, target, 'live test')
        return model.apply(confirmed=True)

    def install(self, hook):
        DacqLive.wrap(self.app.io, 'apply', hook)

    def measured_ids(self):
        return [p['id'] for p in self.points if p['id'] in self.app.found]

    def check_note_shown(self, p):
        notes = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'showinfo' and d[2].startswith('Note for point') and self.NOTE in d[3]]
        self.assertEqual(len(notes), 1)

    def check_reset_once(self):
        text = [t for _ts, i, d, t in self.app.io.log.entries if d == '>>']
        self.assertEqual(sum(1 for t in text if t == '*RST'), 1)

    def test_live_edit(self):
        self.check_edit_action()

        def go():
            self.app.execute(self.points)
            self.assertTrue(self.h.pump(60))
        self.scenario(go)


class A34401Live(Plain, unittest.TestCase):
    MODULES = (A,)
    MOD = A

    def build(self):
        mod = self.MOD
        rp = mock.patch.object(mod.App, 'refresh_ports', lambda self_: None)   # the Combobox stub has no item assignment
        rp.start()
        self.addCleanup(rp.stop)
        app = self.app = mod.App(self.h.root, demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        _b, ft, dt = make_dmm_bench(self.MODEL)
        queue_ = [dt, ft]
        with mock.patch.object(drivers, 'open_visa', lambda *a, **k: queue_.pop(0)):
            app.io = mod.IO('1', '2', 9600, 'None', 8, mods=app.pm_state)
        self.points = [p for p in mod.POINTS if p['kind'] == 'DCV' and not p.get('zero_offset')][:4]

    MODEL = '34401A'
    install = DacqLive.install

    def wrap(self, obj, name, hook):
        DacqLive.wrap(obj, name, hook)


class F8846Live(A34401Live):
    MODULES = (V,)
    MOD = V
    MODEL = '8846A'


class MdoLive(Plain, unittest.TestCase):
    MODULES = (M,)

    def build(self):
        app = self.app = M.App(self.h.root, demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        _b, t = make_mdo_bench()
        app.io = M.IO(dict(cal_baud=9600), transports=t, mods=app.pm_state)
        app._manual_dialog = lambda payload: payload['p']['nominal']
        app.read_cfg()
        self.points = [p for p in M.POINTS if app.cfg.applies(p) and p['kind'] == 'IMP'][:4]

    def install(self, hook):
        orig, n = M.Runner.run_point, {'n': 0}

        def run_point(runner, p):
            n['n'] += 1
            hook(n['n'])
            return orig(runner, p)
        p = mock.patch.object(M.Runner, 'run_point', run_point)
        p.start()
        self.addCleanup(p.stop)

    def go(self):
        self.app.execute(self.points)
        self.assertTrue(self.h.pump(60, until=lambda: not self.app.busy and self.app.q.empty()))

    def check_note_shown(self, p):
        notes = [d for d in self.h.dialogs if d[0] == 'confirm' and d[1].startswith('Note for point') and self.NOTE in ' '.join(d[3])]
        self.assertEqual(len(notes), 1, 'the worker thread asks the main thread to show the note')

    def test_live_edit(self):
        self.check_edit_action()
        self.scenario(self.go)


class WaveSurferLive(unittest.TestCase):
    """The WaveSurfer has no point list: edits are applied between two points of a section (next_* heads) by swapping the override set."""

    def setUp(self):
        self.env = H.Env()
        self.addCleanup(self.env.close)
        import tempfile
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        p = mock.patch.dict('os.environ', {'CALSUITE_DATA': self.home.name, 'HOME': self.home.name, 'USERPROFILE': self.home.name})
        p.start()
        self.addCleanup(p.stop)
        app = self.app = object.__new__(W.RMSNoiseApp)
        app.tb_period_us = H._tk_stub._Var(value='10')
        app.instrument_id = H._tk_stub._Var(value='WS-1')
        app.pm_init('ws', 'WS4104HD', demo=False, store=self.env.store, devmode=self.env.dm)
        for name in ('dc_rows', 'imp_rows', 'offset_rows', 'bw_rows', 'tb_rows', 'trig_rows'):
            setattr(app, name, [])
        for name in ('dc_running', 'imp_running', 'offset_running', 'bw_running', 'tb_running', 'trig_running', 'running'):
            setattr(app, name, False)
        app._batch_busy = lambda: self.running
        self.running = False
        for var, _n, _d, text in W.PM_VARS:
            setattr(app, var, H._tk_stub._Var(value=text))
        app._pm_ws_last = {v: getattr(app, v).get() for v, *_r in W.PM_VARS}
        app._pm_write_sidecar = lambda: None
        app.root = mock.MagicMock()
        type(app).busy = property(lambda self_: self.running)
        self.addCleanup(lambda: delattr(type(app), 'busy') if 'busy' in vars(type(app)) and False else None)

    def model(self):
        ctx = self.app.pm_live_context()
        ctx.store = self.env.store
        import procmods_ui_model as M_
        return M_.ProcModsModel(ctx, self.env.lock)

    def test_context(self):
        m = self.model()
        self.assertTrue(m.live_mode)
        self.assertEqual(len(m.ctx.points), 80 + 28 + 16 + 24 + 1 + 24)
        self.assertNotIn('Points', m.visible_tabs(), 'WaveSurfer sections save results by position: no skip')
        self.assertIn('Tolerances', m.visible_tabs())
        self.assertIn('Settings', m.visible_tabs())
        self.assertIn('WaveSurfer4104HD', m.ctx.registries)
        self.assertTrue(m.stage_skip(procmods.point_keys(m.ctx.points)[0], True))                   # refused with a message

    def test_tolerance_of_an_unmeasured_point_is_applied_between_points(self):
        self.running = True                                                                  # a DC voltage batch is running
        self.app.dc_running = True
        self.app.dc_rows = [object()] * 2                                                    # points 0 and 1 have readings, 2 is in flight
        m = self.model()
        keys = procmods.point_keys(m.ctx.points)
        fac = self.app._pm_factory('dcv')
        j = 5
        self.assertEqual(m.stage_limit(keys[j], low=fac[j]['lower_v'] - 0.001, high=fac[j]['upper_v'] + 0.001), [])
        self.assertEqual(m.limit_redo_needed(), [])
        self.h_edit(m)
        self.assertTrue(self.app.pm_state.live.dirty)
        self.assertEqual(self.app.dcv_points()[j]['lower_v'], fac[j]['lower_v'], 'not applied while a point is in flight')
        self.assertTrue(self.app._pm_boundary('DC voltage'))
        self.assertAlmostEqual(self.app.dcv_points()[j]['lower_v'], fac[j]['lower_v'] - 0.001)
        self.assertTrue(self.app.dcv_points()[j]['limit_modified'])
        ev = self.app.pm_state.live.events
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]['changes'][0]['kind'], 'limit')

    def test_tolerance_of_a_measured_point_cannot_be_changed_in_place(self):
        self.running = True
        self.app.dc_rows = [object()] * 3
        m = self.model()
        keys = procmods.point_keys(m.ctx.points)
        fac = self.app._pm_factory('dcv')
        self.assertEqual(m.stage_limit(keys[0], low=fac[0]['lower_v'] - 0.01, high=fac[0]['upper_v'] + 0.01), [])
        self.assertEqual([k for k, _l in m.limit_redo_needed()], [keys[0]])
        self.assertIn('cannot redo', m.limit_blocked())
        m.set_reason('limit', keys[0], 'r')
        with self.assertRaises(procmods.OverrideError):
            m.apply(confirmed=True, redo=[keys[0]])
        self.assertEqual(self.env.store.entries(), [])

    def test_settings_boxes_follow_a_live_settle_edit(self):
        self.running = True
        m = self.model()
        self.assertEqual(m.stage_param('ws.dcv_settle', 6.0), [])
        self.h_edit(m)
        self.assertEqual(self.app.dc_settle.get(), '3.0')
        self.assertTrue(self.app._pm_boundary('DC voltage'))
        self.assertEqual(self.app.dc_settle.get(), '6.0')

    def test_failed_standby_stops_the_section(self):
        self.running = True
        m = self.model()
        self.assertEqual(m.stage_param('ws.dcv_settle', 6.0), [])
        self.h_edit(m)
        self.app.io = type('IO', (), {'standby': lambda s: (_ for _ in ()).throw(RuntimeError('x'))})()
        import tkinter.messagebox as tk_messagebox                     # the WaveSurfer prompts through ui_port (TkUiPort -> tkinter.messagebox)
        with mock.patch.object(tk_messagebox, 'showerror') as err:
            self.assertFalse(self.app._pm_boundary('DC voltage'))
        self.assertTrue(err.called)
        self.assertEqual(self.app.dc_settle.get(), '3.0')

    def h_edit(self, m):
        m.set_scope('run')
        for kind, target in list(m.drafts):
            m.set_reason(kind, target, 'live test')
        res = m.apply(confirmed=True)
        self.assertTrue(res.ok, res.errors)


class Coverage(unittest.TestCase):
    """Every launcher either runs an engine with the in-run editor or is listed here as not wired (a new launcher forces a decision)."""
    NOT_WIRED = {
        'Tektronix_TDS2000C_Verification.py': 'tds2000c_verification has no procedure-modification layer at all (no mixin, no command registry)',
        'Tektronix_TBS1000C_Verification.py': 'the shared tds2000c_verification engine (TBS1000C family) has no procedure-modification layer, as the TDS2000C',
        'Tektronix_TBS1000_Verification.py': 'the shared tds2000c_verification engine (TBS1000 family) has no procedure-modification layer, as the TDS2000C',
        'Tektronix_TBS2000B_Verification.py': 'tbs2000b_verification (own engine, branch tektronix-tbs2000b) has no procedure-modification layer, as the TDS2000C',
        'Fluke_8846A_Adjustment.py': 'an adjustment procedure (stores calibration constants), not a verification: never editable while running',
        'Keithley_2000_Adjustment.py': 'an adjustment procedure (stores calibration constants), not a verification: never editable while running',
        'Fluke_8808A_Adjustment.py': 'an adjustment procedure (changes the calibration of the meter), not a verification: never editable while running',
    }

    def test_every_launcher_is_covered_or_listed(self):
        for path in sorted((ROOT / 'Procedures').glob('*.py')):
            src = path.read_text(encoding='utf-8')
            if path.name in self.NOT_WIRED:
                self.assertNotIn('pm_live_attach', src)
                for mod in re.findall(r'^import (\w+_verification|handheld_dmm)\s*$', src, re.M):
                    self.assertNotIn('pm_live_attach', (ROOT / f'{mod}.py').read_text(encoding='utf-8'), path.name)
                continue
            mods = re.findall(r'^import (\w+_verification|handheld_dmm|dsb_runtime)\s*$', src, re.M)
            texts = [src] + [(ROOT / f'{m}.py').read_text(encoding='utf-8') for m in mods]
            for t in list(texts):                                        # a ported engine keeps its window code in <VIEW>_tk.py (ui_port.py)
                texts += [(ROOT / f'{v}_tk.py').read_text(encoding='utf-8') for v in re.findall(r"^\s+VIEW = '(\w+)'", t, re.M)]
            if path.name == 'User_Datasheet.py':
                texts.append((ROOT / 'handheld_dmm.py').read_text(encoding='utf-8'))
                texts.append((ROOT / 'handheld_dmm_view_tk.py').read_text(encoding='utf-8'))        # its window code (ui_port.py)
            self.assertTrue(any('pm_live_attach(' in t for t in texts), f'{path.name}: no in-run editor and not listed in NOT_WIRED')


if __name__ == '__main__':
    unittest.main()
