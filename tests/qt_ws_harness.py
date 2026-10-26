"""Harness for tests/test_qt_view_wavesurfer.py (not a test module): the REAL WaveSurfer App on the Qt view (wavesurfer_view_qt) behind an OperatorPort, a QtUiPort
whose every prompt opens the REAL Qt dialog and is answered by a scripted operator that presses the buttons / types the text of the answer.

What is checked while it runs: each dialog's title, body text, button names (and the steps / facts / caution of an operator prompt) are what the engine asked for, the
dialog's return value equals the scripted answer, and the canonical record of every prompt (ui_port.record, the form of tests/golden_ui/*.json) is kept in `.prompts`.
The scenarios are the ones of tests/ui_prompt_capture_ws.py (8 scenarios, 225 prompts of the Tk build): the same method calls, with the Tk widget mocks (`a.dc_tree.selection.
return_value = ...`) replaced by `TreeShim` (what the engine reads from a table through the view) and the real Qt tables behind everything else.  The report writers are
fakes (nothing is written), `threading.Thread` is synchronous inside the engine module and the worker threads' events are the fakes' of the Tk scenarios, exactly as there.
The one prompt this does not open for real is report_details (QtUiPort shows the plain popup for it; its window is another package's): it is recorded and answered.

PySide6 required (imported lazily by the test module, which skips without it).
"""
from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / 'Procedures', ROOT / 'tests'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import _tk_stub  # noqa: E402

_tk_stub.install()

import ui_port  # noqa: E402
from ui_port import Answers, operator_record, plain, record  # noqa: E402
from ui_prompt_capture_ws import _SyncThread, _periodic  # noqa: E402

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QMainWindow, QPushButton  # noqa: E402

import ui_port_qt  # noqa: E402
from qtui import app as qapp, prompts  # noqa: E402
from tests.test_ui_port_qt import Driver, button_texts, label_texts, press  # noqa: E402


class OperatorPort(ui_port_qt.QtUiPort):
    """QtUiPort that shows every prompt for real and answers it the way `answers` says; `.prompts` is the canonical record, `.q` the queued after() calls."""

    def __init__(self, answers, tmp):
        super().__init__()
        self.answers = answers
        self.prompts = []
        self.q = []
        self.tmp = Path(tmp)
        self.d = Driver()
        self.events = []
        self.on_dialog = None                             # optional hook(dialog), called with each dialog on screen before the operator answers it (screenshots)

    # ---- scheduling: kept for the scenario's pump (the Tk harness's FakeRoot queue)
    def after(self, win, ms, fn, *args):
        self.q.append((fn, args))
        return len(self.q)

    def cancel_after(self, win, handle):
        return None

    def post(self, win, fn, *args):
        self.q.append((fn, args))

    def close(self, win):
        self.events.append(('close', ()))                 # the scenarios never close the window for real

    # ---- helpers
    def _norm(self, rec):
        """The record without the temp folder the scenario's save-as dialog chose in (the Tk scenarios answered with a bare file name)."""
        return {k: (v.replace(str(self.tmp) + os.sep, '') if isinstance(v, str) else v) for k, v in rec.items()}

    def _done(self, rec, ans):
        self.prompts.append(dict(self._norm(rec), answer=plain(ans)))

    def _check_text(self, shown, title, text):
        assert shown['title'].replace(' [DEMO]', '') == title, (shown['title'], title)
        assert text in shown['body'], f'text of {title!r} not on screen: {shown["body"]}'

    # ---- prompts
    def message(self, kind, title, text, *, parent=None):
        rec = record(kind, title, text)
        shown = {}

        def handler(dlg):
            shown.update(title=dlg.windowTitle(), body=label_texts(dlg), buttons=button_texts(dlg))
            if self.on_dialog:
                self.on_dialog(dlg)
            self._check_text(shown, title, text)
            assert shown['buttons'] == rec['buttons'], shown['buttons']
            press(dlg, 'OK')
        self.d.run(lambda: super(OperatorPort, self).message(kind, title, text, parent=parent), handler)
        self.prompts.append(self._norm(rec))

    def _question(self, kind, title, text, default, extra, call):
        rec = record(kind, title, text, **extra)
        ans = self.answers.for_(rec, default)
        shown = {}

        def handler(dlg):
            shown.update(title=dlg.windowTitle(), body=label_texts(dlg), buttons=button_texts(dlg))
            if self.on_dialog:
                self.on_dialog(dlg)
            self._check_text(shown, title, text)
            assert shown['buttons'] == rec['buttons'], (shown['buttons'], rec['buttons'])
            if kind == 'ask_yes_no':
                pick = 'Yes' if ans else 'No'
            elif kind == 'ask_ok_cancel':
                pick = 'OK' if ans else 'Cancel'
            elif kind == 'ask_retry_cancel':
                pick = 'Retry' if ans else 'Cancel'
            else:
                pick = 'Cancel' if ans is None else ('Yes' if ans else 'No')
            press(dlg, pick)
        out = self.d.run(call, handler)
        assert out == ans, (kind, title, out, ans)
        self._done(rec, ans)
        return out

    def ask_yes_no(self, title, text, *, icon=None, default=None, parent=None):
        return self._question('ask_yes_no', title, text, True, dict(icon=icon, default=default),
                              lambda: super(OperatorPort, self).ask_yes_no(title, text, icon=icon, default=default, parent=parent))

    def ask_ok_cancel(self, title, text, *, icon=None, parent=None):
        return self._question('ask_ok_cancel', title, text, True, dict(icon=icon), lambda: super(OperatorPort, self).ask_ok_cancel(title, text, icon=icon, parent=parent))

    def ask_retry_cancel(self, title, text, *, icon=None, parent=None):
        return self._question('ask_retry_cancel', title, text, True, dict(icon=icon),
                              lambda: super(OperatorPort, self).ask_retry_cancel(title, text, icon=icon, parent=parent))

    def ask_yes_no_cancel(self, title, text, *, icon=None, parent=None):
        return self._question('ask_yes_no_cancel', title, text, True, dict(icon=icon),
                              lambda: super(OperatorPort, self).ask_yes_no_cancel(title, text, icon=icon, parent=parent))

    def ask_number(self, title, prompt, *, initial=None, minvalue=None, maxvalue=None, integer=False, parent=None):
        rec = record('ask_number', title, prompt, initial=initial)
        ans = self.answers.for_(rec, None)
        shown = {}

        def handler(dlg):
            shown.update(title=dlg.windowTitle(), body=label_texts(dlg))
            self._check_text(shown, title, prompt)
            entry = dlg.findChild(QLineEdit)
            if ans is None:
                press(dlg, 'Cancel')
            else:
                entry.setText(repr(float(ans)))
                press(dlg, 'OK')
        out = self.d.run(lambda: super(OperatorPort, self).ask_number(title, prompt, initial=initial, minvalue=minvalue, maxvalue=maxvalue, integer=integer, parent=parent), handler)
        if isinstance(ans, float) and ans != ans:
            assert out != out, out
        else:
            assert out == ans, (title, out, ans)
        self._done(rec, ans)
        return out

    def operator_prompt(self, title, heading, steps, *, parent=None, **opts):
        known = ('facts', 'caution', 'ok', 'cancel', 'image')
        rec = operator_record(title, heading, steps, opts.get('facts'), opts.get('caution'), opts.get('ok', 'OK'), opts.get('cancel', 'Cancel'), opts.get('image'),
                              **{k: v for k, v in opts.items() if k not in known})
        ans = self.answers.for_(rec, True)
        shown = {}

        def handler(dlg):
            shown.update(title=dlg.windowTitle(), body=label_texts(dlg), buttons=button_texts(dlg))
            if self.on_dialog:
                self.on_dialog(dlg)
            self._check_text(shown, title, heading)
            for step in steps:
                for part in (step if isinstance(step, (list, tuple)) else [step]):
                    if part:
                        assert part in shown['body'], f'step text missing in {title!r}: {part!r}'
            for k, v in opts.get('facts') or []:
                assert str(k) in shown['body'] and str(v) in shown['body'], (k, v)
            if opts.get('caution'):
                assert opts['caution'] in shown['body'], opts['caution']
            ok, cancel = opts.get('ok', 'OK'), opts.get('cancel', 'Cancel')
            assert shown['buttons'] == [cancel, ok], shown['buttons']          # Cancel left of OK
            press(dlg, ok if ans else cancel)
        out = self.d.run(lambda: super(OperatorPort, self).operator_prompt(title, heading, steps, parent=parent, **opts), handler)
        assert out == ans, (title, out, ans)
        self._done(rec, ans)
        return out

    def _file(self, kind, opts, call):
        rec = record(kind, options={k: v for k, v in opts.items() if v is not None})
        ans = self.answers.for_(rec, self.answers.save_path if kind == 'save_file' else self.answers.open_path)
        shown = {}

        def handler(dlg):
            assert isinstance(dlg, QFileDialog)
            shown['filters'] = dlg.nameFilters()
            if ans:
                dlg.selectFile(str(self.tmp / ans))
                dlg.accept()
            else:
                dlg.reject()
        out = self.d.run(call, handler)
        assert (Path(out).name if out else '') == (ans or ''), (out, ans)
        self._done(rec, ans)
        return out

    def save_file(self, *, parent=None, **opts):
        opts = {**opts, 'initialdir': str(self.tmp)}
        return self._file('save_file', {k: v for k, v in opts.items() if k != 'initialdir'}, lambda: super(OperatorPort, self).save_file(parent=parent, **opts))

    def choose_file(self, *, parent=None, **opts):
        return self._file('choose_file', opts, lambda: super(OperatorPort, self).choose_file(parent=parent, **opts))

    def report_details(self, procedure='', *, parent=None):
        rec = record('report_details', procedure, '')
        ans = self.answers.for_(rec, None)
        self._done(rec, ans)
        return ans


class TreeShim:
    """What the Tk scenarios did with `tree.selection.return_value = ...` / `.index.return_value` / `.get_children.return_value`: the engine reads a table only through
    the view's selection / row_index / children, so those three are answered from here for a table the scenario programmed and from the real table otherwise."""

    def __init__(self, view):
        self.view, self.sel, self.idx, self.kids = view, {}, {}, {}
        self.real = (view.selection, view.row_index, view.children)
        self.patches = [mock.patch.object(view, 'selection', self._selection), mock.patch.object(view, 'row_index', self._index),
                        mock.patch.object(view, 'children', self._children)]

    def start(self):
        for p in self.patches:
            p.start()

    def stop(self):
        for p in self.patches:
            p.stop()

    def set(self, tree, selection=None, index=None, children=None):
        if selection is not None:
            self.sel[id(tree)] = tuple(selection)
        if index is not None:
            self.idx[id(tree)] = index
        if children is not None:
            self.kids[id(tree)] = tuple(children)

    def _selection(self, t):
        return self.sel[id(t)] if id(t) in self.sel else self.real[0](t)

    def _index(self, t, iid):
        return self.idx[id(t)] if id(t) in self.idx else self.real[1](t, iid)

    def _children(self, t):
        return self.kids[id(t)] if id(t) in self.kids else self.real[2](t)


class Harness:
    """A fresh App (own HOME / data dir, synchronous workers, queued after() calls) on a QMainWindow."""

    def __init__(self, answers=None, sim_bench=False):
        import WaveSurfer_WS4104HD as W
        import wavesurfer_view_qt as V
        self.W, self.V = W, V
        self.home = Path(tempfile.mkdtemp(prefix='ws_qt_'))
        self.answers = answers or Answers()
        self.patches = []
        env = mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.home / 'data'), 'HOME': str(self.home), 'USERPROFILE': str(self.home)})
        env.start()
        self.patches.append(env)
        thread_ns = types.SimpleNamespace(**{k: getattr(threading, k) for k in dir(threading) if not k.startswith('__')})
        thread_ns.Thread = _SyncThread
        for obj, name, val in ((W, 'threading', thread_ns), (sys.modules['time'], 'sleep', lambda s: None)):
            p = mock.patch.object(obj, name, val, create=True)
            p.start()
            self.patches.append(p)
        qapp.create_app()
        prompts.native_file_dialogs = False
        self.port = OperatorPort(self.answers, self.home)
        self.old_ui = ui_port.set_ui(self.port)
        self.shim = TreeShim(V)
        self.shim.start()
        self.win = QMainWindow()
        self.app = a = W.RMSNoiseApp(self.win)
        self.win.resize(1480, 860)
        self.win.show()                                  # a dialog with no parent window is parented to the active window: keep this one real and active
        self.win.activateWindow()
        QApplication.processEvents()
        a.instrument_id.set('WS-1')
        a.serial.set('S-1')
        a.sync_asset()
        a.visa_address.set('sim')
        a.fluke_address.set('sim')
        if sim_bench:
            import drivers
            from drivers.simulated import make_bench
            bench, ft, st = make_bench()
            transports = {'fluke': ft, 'scope': st}

            def open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=10):
                fluke = drivers.Fluke5560A(transports['fluke'], log) if fluke_addr else None
                scope = drivers.WaveSurfer4104HD(transports['scope'], log) if scope_addr else None
                return fluke, scope
            a.open_bench = open_bench
            a._reset_notice = lambda text: True

    def rule(self, fn):
        self.answers.rules.append(fn)

    def clear_rules(self):
        self.answers.rules.clear()

    def pump(self, limit=4000):
        """Run what the Qt loop would: the event queue (process_events) and the one-shot after() calls, never the periodic ticks."""
        a = self.app
        skip = _periodic(a)
        for _ in range(limit):
            a.process_events()
            todo = [(fn, args) for fn, args in self.port.q if getattr(fn, '__func__', None) not in skip]
            self.port.q[:] = []
            if not todo and a.events.empty():
                return True
            for fn, args in todo:
                fn(*args)
        return False

    def stop(self):
        self.shim.stop()
        ui_port.set_ui(self.old_ui)
        self.win.setProperty('_calsuite_closing', True)
        self.win.close()
        self.win.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        for p in reversed(self.patches):
            p.stop()
        prompts.native_file_dialogs = None


def title_is(*titles, answer=False):
    return lambda r: answer if r.get('title') in titles else None


def _fake_report_writers(W, report_pdf):
    return mock.patch.object(report_pdf, 'write_calibration_pdf', lambda filename, rows, **k: len(rows))


def run_scenarios(only=None):
    """The 8 scenarios of tests/ui_prompt_capture_ws.py through the Qt window; returns {scenario: [canonical records]}."""
    import datamode
    import procmods_engine
    import WaveSurfer_WS4104HD as W
    out = {}

    def done(name, hn):
        out[name] = list(hn.port.prompts)
        hn.stop()

    def want(name):
        return only is None or name in only

    # ---- 1. the table buttons
    if want('table_buttons'):
        hn = Harness()
        a, sh = hn.app, hn.shim
        a.show_function.set('All functions')
        a.run_section()
        a.dc_running = True
        a.run_pending()
        a.instrument_id.set('OTHER')
        a.sync_asset()
        a.dc_running = False
        a.instrument_id.set('WS-1')
        a.instrument_id.set('')
        a.run_pending()
        a.instrument_id.set('WS-1')
        a.sync_asset()
        a.rerun_selected()
        sh.set(a.utree, selection=('r1',))
        a._entries_cache = {'r1': dict(kind='dcv', done=False, idx=0)}
        a.rerun_selected()
        a._entries_cache = {'r1': dict(kind='dcv', done=True, idx=0)}
        sh.set(a.dc_tree, children=('i0',))
        a._mode_sets = {datamode.LEFT: dict({k: [] for k in W.RMSNoiseApp._SET_ATTRS}, dc_rows=[{}])}
        hn.rule(title_is('Replace the As Found reading?'))
        a.rerun_selected()
        hn.clear_rules()
        a.show_function.set('All functions')
        a.clear_function()
        a.show_function.set('DC voltage')
        hn.rule(title_is('Clear results'))
        a.clear_function()
        hn.clear_rules()
        a.clear_function()
        a.show_function.set('Offset (P1 mean)')
        a.clear_function()
        a._mode_sets = {}
        done('table_buttons', hn)

    # ---- 2. demo data, an edit that cannot be applied, earlier results from an old version
    if want('demo_data_and_pm'):
        hn = Harness()
        a = hn.app
        a.load_demo_data()
        a.load_demo_data()
        a.show_function.set('All functions')
        a.run_pending()
        with mock.patch.object(a, 'pm_live_boundary', side_effect=procmods_engine.LiveApplyError('cannot apply')):
            a._pm_boundary('DC voltage')
        tmp = Path(tempfile.mkdtemp())
        for base in W.RMSNoiseApp.CKPT_BASE.values():
            (tmp / f'{base}.json').write_text('{}', encoding='utf-8')

        class _Path(type(Path())):
            def with_name(self, name):
                return tmp / name
        with mock.patch.object(W, 'Path', _Path):
            a._ckpt_id = 'LEGACY-1'
            hn.rule(title_is('Earlier results found'))
            a._adopt_legacy_results('LEGACY-1')
            hn.clear_rules()
        done('demo_data_and_pm', hn)

    # ---- 3. RMS noise
    if want('noise'):
        hn = Harness()
        a, sh = hn.app, hn.shim

        def fake_worker(address, channel, delay, samples, factor, limits, start_index=0, stop_index=None):
            a.events.put(('status', f'Connected: sim CH{channel}'))
            for idx in range(start_index, len(W.SCALES) if stop_index is None else stop_index):
                scale, limit = W.SCALES[idx], limits[idx]
                db = limit + 2.0
                a.events.put(('row', dict(timestamp='t', instrument='sim', channel=channel, scale_v_div=scale, rms_volts=1e-3, db=db, minimum_db=limit,
                                          margin_db=2.0, result='PASS', samples=samples, reference_factor_div=factor, note='')))
            a.events.put(('done', False))
        a.worker = fake_worker
        a.delay.set('0.0')
        a.start_test()
        a.delay.set('0.2')
        a.resume_test()
        hn.rule(title_is('New test'))
        a.start_test()
        hn.clear_rules()
        a.channel.set('1')
        a.all_channels.set(False)
        a.start_test()
        hn.pump()
        sh.set(a.tree, selection=())                                       # the run leaves its last point highlighted; the Tk scenario had nothing selected
        a.retest_noise()
        sh.set(a.tree, selection=('i0',), index=0)
        a.retest_noise()
        hn.pump()
        a.run_config = None
        a.retest_noise()
        a.run_config = a.get_config()
        a.rows = a.rows[:1]
        a.limit_text.set('1,2,3')
        a.resume_test()
        a.limit_text.set(','.join(map(str, W.LIMITS)))
        a.delay.set('0.3')
        a.resume_test()
        a.delay.set('0.2')
        hn.rule(title_is('Prepare channel'))
        a.resume_test()
        hn.pump()
        a.rows = []
        a.resume_test()
        hn.clear_rules()
        a.running = False
        a.events.queue.clear()
        a.events.put(('error', 'scope lost'))
        hn.pump()
        a.noise_retest_index = 0
        a.events.put(('error', 'scope lost'))
        hn.pump()
        a.events.put(('connection', True, 'LECROY,WS4104HD'))
        a.events.put(('fluke', True, '5560A'))
        a.events.put(('fluke', False, 'no reply'))
        hn.pump()
        done('noise', hn)

    # ---- 4. DC voltage on the simulated bench
    if want('dcv'):
        hn = Harness(sim_bench=True)
        a, sh = hn.app, hn.shim
        a.dc_settle.set('0.5')
        a.dc_auto_fluke.set(False)
        a.start_dcv_batch()
        a.dc_auto_fluke.set(True)
        a.dc_p1_mode.set(False)
        a.start_dcv_batch()
        a.next_dcv()
        a.dc_p1_mode.set(True)
        a.dc_settle.set('99')
        a.next_dcv()
        a.dc_settle.set('0.5')
        a.running = True
        a.next_dcv()
        a.start_dcv_batch()
        a.resume_dcv()
        a.running = False
        hn.rule(title_is('Connect DCV cable — CH1'))
        a.start_dcv_batch()
        hn.clear_rules()
        a.start_dcv_batch()
        hn.pump(limit=6000)
        a.next_dcv()
        a.resume_dcv()
        a.start_dcv_batch()
        sh.set(a.dc_tree, selection=())
        a.retest_selected_dcv()
        sh.set(a.dc_tree, selection=('i0', 'i1'))
        a.retest_selected_dcv()
        sh.set(a.dc_tree, selection=('i3',), index=3)
        a.dc_auto_fluke.set(False)
        a.retest_selected_dcv()
        a.dc_auto_fluke.set(True)
        a.dc_settle.set('0')
        a.retest_selected_dcv()
        a.dc_settle.set('0.5')
        hn.rule(title_is('Confirm DCV retest connection'))
        a.retest_selected_dcv()
        hn.clear_rules()
        a.retest_selected_dcv()
        hn.pump()
        a.dc_running = True
        a.retest_selected_dcv()
        a.dc_running = False
        sh.set(a.dc_tree, index=200)
        a.retest_selected_dcv()
        a.dc_rows = a.dc_rows[:2]
        sh.set(a.dc_tree, index=5)
        a.retest_selected_dcv()
        a.dc_batch = False
        a.dc_auto_fluke.set(False)
        a.dc_p1_mode.set(False)
        hn.rule(lambda r: 0.99 if r['kind'] == 'ask_number' and r['title'] == 'Measured DC voltage' else None)
        a.next_dcv()
        hn.clear_rules()
        hn.rule(lambda r: float('nan') if r['kind'] == 'ask_number' else None)
        a.next_dcv()
        hn.clear_rules()
        a.next_dcv()
        a.dc_p1_mode.set(True)
        a.next_dcv()
        hn.pump()
        a.dc_auto_fluke.set(True)
        a.dc_batch = False
        a.next_dcv()
        hn.pump()
        hn.rule(title_is('Confirm DCV test setup'))
        a.next_dcv()
        hn.clear_rules()
        a.events.put(('dc_error', 'DCV communication failed'))
        a.events.put(('dc_safety', 'Fluke standby was NOT confirmed'))
        hn.pump()
        a.dc_rows = [dict(a.dcv_points()[0], measured_v=float('inf'))]
        a.record_dcv(a.dcv_points()[1], float('inf'), 'manual')
        hn.rule(title_is('Clear DCV results'))
        a.clear_dcv()
        hn.clear_rules()
        done('dcv', hn)

    # ---- 5. impedance, offset, bandwidth, time base, trigger level
    if want('sections'):
        hn = Harness()
        a, sh = hn.app, hn.shim

        def put_idle(kind, *results):
            for r in results:
                a.events.put(r)
            a.events.put((f'{kind}_idle',))

        def imp_worker(point, settle, samples, scope_address, fluke_address, baud):
            put_idle('imp', ('imp_result', point, point['nominal_ohm'], [point['nominal_ohm']] * 3))

        def offset_worker(point, settle, fluke_addr, baud, scope_addr):
            put_idle('offset', ('offset_result', point, point['nominal_v'], point['nominal_v']))

        def bw_worker(point, settle, fluke_addr, baud, scope_addr):
            put_idle('bw', ('bw_result', point, point['amplitude_vpp'], point['amplitude_vpp'] * 0.9))

        def tb_worker(point, settle, samples, fluke_addr, baud, scope_addr):
            put_idle('tb', ('tb_result', point, [point['nominal_hz']] * 3, ()))

        def trig_worker(point, settle, fluke_addr, baud, scope_addr):
            reply = queue.Queue()
            a.events.put(('ask', 'Trigger before the level?', f'Did the scope trigger at {point["level_v"]}?', reply))
            put_idle('trig', ('trig_result', point, dict(triggered_short=False, triggered_past=True)))
        a.impedance_worker, a.offset_worker, a.bandwidth_worker, a.timebase_worker, a.trigger_worker = imp_worker, offset_worker, bw_worker, tb_worker, trig_worker

        a.running = True
        a.resume_impedance(); a.start_impedance_batch(); a.next_impedance()
        a.running = False
        a.imp_settle.set('99')
        a.next_impedance()
        a.imp_settle.set('2.0')
        hn.rule(title_is('Confirm impedance connection'))
        a.next_impedance()
        hn.clear_rules()
        a.start_impedance_batch()
        hn.pump(limit=6000)
        a.next_impedance()
        a.start_impedance_batch()
        a.resume_impedance()
        sh.set(a.imp_tree, selection=())
        a.retest_impedance()
        a.running = True
        a.retest_impedance()
        a.running = False
        sh.set(a.imp_tree, selection=('i1',), index=99)
        a.retest_impedance()
        sh.set(a.imp_tree, index=2)
        hn.rule(title_is('Confirm impedance retest'))
        a.retest_impedance()
        hn.clear_rules()
        a.imp_samples.set('0')
        a.retest_impedance()
        a.imp_samples.set('3')
        a.retest_impedance()
        hn.pump()
        a.events.put(('imp_error', 'Fluke SCOPE MEASR failed'))
        a.events.put(('imp_safety', 'Fluke is not in SCOPE mode'))
        hn.pump()
        a.clear_impedance()
        a.imp_retest_index = None
        for pt in a.impedance_points()[:25]:
            a.record_impedance(pt, pt['nominal_ohm'], [pt['nominal_ohm']])
        a.imp_batch = False
        a.imp_connection_confirmed = True
        hn.rule(title_is('Confirm external trigger impedance'))
        a.next_impedance()
        hn.clear_rules()
        hn.rule(title_is('Clear impedance'))
        a.clear_impedance()
        hn.clear_rules()
        a.clear_impedance()

        a.running = True
        a.start_offset()
        a.running = False
        a.offset_settle.set('99')
        a.start_offset()
        a.offset_settle.set('3.0')
        hn.rule(title_is('Confirm offset test method'))
        a.start_offset()
        hn.clear_rules()
        hn.rule(title_is('Offset cable connection'))
        a.start_offset()
        hn.clear_rules()
        a.start_offset()
        hn.pump(limit=6000)
        a.start_offset()
        a.offset_batch = True
        a.offset_running = False
        a.next_offset()
        sh.set(a.offset_tree, selection=('i1',), index=2)
        hn.rule(title_is('Confirm offset retest'))
        a.retest_offset()
        hn.clear_rules()
        a.offset_settle.set('0')
        a.retest_offset()
        a.offset_settle.set('3.0')
        a.retest_offset()
        hn.pump()
        a.events.put(('offset_error', 'scope P1 failed'))
        a.events.put(('offset_safety', 'Fluke standby not confirmed'))
        hn.pump()

        a.offset_running = True
        a.start_bandwidth()
        a.offset_running = False
        a.bw_settle.set('99')
        a.start_bandwidth()
        a.bw_settle.set('3.0')
        hn.rule(title_is('Confirm high-frequency test'))
        a.start_bandwidth()
        hn.clear_rules()
        hn.rule(title_is('Move 50 Ω signal cable'))
        a.start_bandwidth()
        hn.clear_rules()
        a.start_bandwidth()
        hn.pump()
        a.start_bandwidth()
        hn.pump(limit=6000)
        a.start_bandwidth()
        a.bw_batch = True
        a.bw_running = False
        a.next_bandwidth()
        sh.set(a.bw_tree, selection=('i1',), index=2)
        hn.rule(title_is('Confirm bandwidth retest'))
        a.retest_bandwidth()
        hn.clear_rules()
        a.bw_settle.set('0')
        a.retest_bandwidth()
        a.bw_settle.set('3.0')
        a.retest_bandwidth()
        hn.pump()
        a.events.put(('bw_error', 'P1 PkPk failed'))
        a.events.put(('bw_safety', 'Fluke standby not confirmed'))
        hn.pump()

        a.tb_running = True
        a.start_timebase()
        a.tb_running = False
        a.tb_settle.set('99')
        a.start_timebase()
        a.tb_settle.set('3.0')
        hn.rule(title_is('Time base accuracy'))
        a.start_timebase()
        hn.clear_rules()
        a.start_timebase()
        hn.pump()
        a.start_timebase()
        sh.set(a.tb_tree, selection=('i0',), index=0)
        hn.rule(title_is('Confirm time base retest'))
        a.retest_timebase()
        hn.clear_rules()
        a.retest_timebase()
        hn.pump()
        a.events.put(('tb_error', 'marker rejected'))
        a.events.put(('tb_safety', 'Fluke standby not confirmed'))
        hn.pump()

        a.trig_running = True
        a.start_trigger()
        a.trig_running = False
        a.trig_settle.set('99')
        a.start_trigger()
        a.trig_settle.set('1.0')
        hn.rule(title_is('Trigger level test method'))
        a.start_trigger()
        hn.clear_rules()
        hn.rule(title_is('Trigger level cable connection'))
        a.start_trigger()
        hn.clear_rules()
        hn.rule(lambda r: None if r['kind'] != 'ask_yes_no_cancel' else False)
        a.start_trigger()
        hn.pump(limit=6000)
        a.start_trigger()
        a.trig_batch = True
        a.trig_running = False
        a.next_trigger()
        sh.set(a.trig_tree, selection=('i1',), index=2)
        hn.rule(title_is('Confirm trigger level retest'))
        a.retest_trigger()
        hn.clear_rules()
        a.trig_settle.set('0')
        a.retest_trigger()
        a.trig_settle.set('1.0')
        a.retest_trigger()
        hn.pump()
        a.events.put(('trig_error', 'trigger did not arm'))
        a.events.put(('trig_safety', 'Fluke standby not confirmed'))
        a.events.put(('trig_cancel', 'Point abandoned'))
        hn.pump()
        done('sections', hn)

    # ---- 5b. saved results that do not match the procedure
    if want('bad_checkpoints'):
        hn = Harness()
        a = hn.app
        for attr, loader in (('offset_checkpoint', a.load_offset_checkpoint), ('bw_checkpoint', a.load_bandwidth_checkpoint), ('tb_checkpoint', a.load_timebase_checkpoint),
                             ('trig_checkpoint', a.load_trigger_checkpoint)):
            getattr(a, attr).write_text('[1]', encoding='utf-8')
            loader()
        done('bad_checkpoints', hn)

    # ---- 6. exports and closing
    if want('exports'):
        import report_pdf
        hn = Harness()
        a = hn.app
        with mock.patch.object(report_pdf, 'write_calibration_pdf', lambda filename, rows, **k: len(rows)):
            a.export_pdf_report()
            a.export_calibration_section('dcv')
            a.write_certificate_pdf('x.pdf', [])
            a.load_demo_data()
            a.export_pdf_report()
            a.export_calibration_section('dcv')
            hn.rule(lambda r: {} if r['kind'] == 'report_details' else None)
            a.export_pdf_report()
            a.export_calibration_section('noise')
            hn.answers.save_path = 'Calibration Data WS-1.pdf'
            a.export_pdf_report()
            a.export_calibration_section('trigger')
            with mock.patch.object(report_pdf, 'write_calibration_pdf', side_effect=RuntimeError('disk full')):
                a.export_pdf_report()
            with mock.patch.object(report_pdf, 'write_calibration_pdf', side_effect=ImportError('reportlab')):
                a.export_pdf_report()
            hn.clear_rules()
        done('exports', hn)

    if want('close_window'):
        hn = Harness()
        a = hn.app
        for flag in ('tb_running', 'trig_running', 'bw_running', 'offset_running', 'imp_running', 'dc_running'):
            setattr(a, flag, True)
            a.on_close()
            setattr(a, flag, False)
        a.running = True
        hn.rule(title_is('Test running'))
        a.on_close()
        hn.clear_rules()
        done('close_window', hn)
    return out
