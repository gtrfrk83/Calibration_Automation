"""A real-Qt harness for the handheld engines (handheld_dmm.App, iflex_option.App, dsb_runtime.DsbApp) and anything else that prompts through the UiPort.  Not a test
module (tests/test_qt_views_handheld.py and tests/test_qt_dsb_runtime.py use it).  Needs PySide6 (import it only after checking).

`QtHarness` has the surface of tests/virtual_harness.VHarness that the scenario functions of tests/ui_prompt_capture.py use (`start`, `stop`, `root`, `app`, `run_all`,
`pump`, `answers`, `fill`, `readings`, `default_reading`, `range_answer`, `box_answer`, `patches`, `port.prompts`), but the root is a real QMainWindow, the window is the real
Qt view and every prompt is a REAL Qt dialog:

  * `ProofPort` (a QtUiPort) builds the canonical record of each prompt exactly as ui_port.ScriptedUiPort does, asks the scripted operator (`answers`, with the same
    defaults the Tk-level harness gave) what to answer, then shows the real dialog and drives it (types, ticks, presses buttons) from inside its own event loop.  What
    the dialog returned is the recorded answer; what it SHOWED (title, text, button names, steps, entry contents) is checked against the record on the spot, and kept in
    `port.shown` (one dict per prompt) for the tests.
  * a modal window nobody expected (for instance the exception dialog of qtui.app) fails the run.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QTimer                       # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QLabel, QLineEdit, QMainWindow, QPushButton, QRadioButton, QWidget)  # noqa: E402

import ui_port                                          # noqa: E402
import ui_port_qt                                       # noqa: E402
from qtui import app as qapp                            # noqa: E402
from qtui import prompts                                # noqa: E402
from ui_port import Answers, operator_record, plain, record   # noqa: E402

BOX_NAME = {'ask_yes_no': 'askyesno', 'ask_ok_cancel': 'askokcancel', 'ask_retry_cancel': 'askretrycancel', 'ask_yes_no_cancel': 'askyesnocancel'}


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# reading what a window shows, pressing what an operator presses
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def button_texts(dlg):
    return [b.text() for b in dlg.findChildren(QPushButton) if b.isVisibleTo(dlg) and b.text()]


def label_texts(dlg):
    return [lab.text() for lab in dlg.findChildren(QLabel) if lab.isVisibleTo(dlg) and lab.text()]


def press(dlg, text):
    for b in dlg.findChildren(QPushButton):
        if b.text() == text and b.isVisibleTo(dlg):
            b.click()
            return
    raise AssertionError(f'no button {text!r} in {button_texts(dlg)}')


def settle(n=6):
    for _ in range(n):
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)          # the widgets closed with deleteLater() go now


class Operator:
    """The scripted operator: `handler(dialog)` runs once, inside the dialog's own event loop, as soon as a modal window is active."""

    def __init__(self):
        self.error = None

    def run(self, call, handler, timeout=60.0):
        done = {'handled': False}
        t0 = time.time()
        timer = QTimer()
        timer.setInterval(4)

        def poll():
            w = QApplication.activeModalWidget()
            if w is None or done['handled']:
                if w is not None and time.time() - t0 > timeout:
                    done['handled'] = True
                    self.error = self.error or 'timeout'
                    w.reject()
                return
            done['handled'] = True
            try:
                handler(w)
            except BaseException as exc:                 # noqa: BLE001 - a failing check must close the dialog, or the run hangs
                self.error = self.error or exc
                try:
                    w.reject()
                except RuntimeError:
                    pass
        timer.timeout.connect(poll)
        timer.start()
        try:
            out = call()
        finally:
            timer.stop()
        if self.error is not None:
            err, self.error = self.error, None
            if isinstance(err, BaseException):
                raise err
            raise AssertionError(err)
        if not done['handled']:
            raise AssertionError('no dialog was shown')
        return out


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the port
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class ProofPort(ui_port_qt.QtUiPort):
    """QtUiPort whose every prompt is answered by a scripted operator through the REAL Qt dialog; see the module doc.  `prompts` = the canonical records (ScriptedUiPort's form),
    `shown` = what each dialog displayed: dict(kind, title, body (visible label texts), buttons, entry)."""

    def __init__(self, answers, hn):
        super().__init__()
        self.answers, self.hn = answers, hn
        self.prompts, self.shown = [], []
        self.op = Operator()

    # ---- helpers
    def _seen(self, rec, dlg, **extra):
        info = dict(kind=rec['kind'], title=dlg.windowTitle(), body=label_texts(dlg), buttons=button_texts(dlg), **extra)
        self.shown.append(info)
        return info

    def _same(self, got, want, what):
        if got != want:
            raise AssertionError(f'{what}: the window shows {got!r}, the record says {want!r}')

    def _title_ok(self, shown, title):
        self._same(shown.replace(prompts._title(''), ''), title, 'window title')

    def _body_ok(self, info, text):
        if not any(text in b or b == text for b in info['body']):
            raise AssertionError(f'text {text!r} is not on the window: {info["body"]!r}')

    # ---- messages and questions
    def message(self, kind, title, text, *, parent=None):
        rec = record(kind, title, text)

        def handler(dlg):
            info = self._seen(rec, dlg)
            self._title_ok(info['title'], title)
            self._body_ok(info, text)
            self._same(info['buttons'], ['OK'], 'buttons')
            press(dlg, 'OK')
        self.op.run(lambda: super(ProofPort, self).message(kind, title, text, parent=parent), handler)
        self.prompts.append(rec)

    def _box(self, kind, title, text, icon, default, call, picks):
        rec = record(kind, title, text, None, icon=icon, default=default) if kind == 'ask_yes_no' else record(kind, title, text, None, icon=icon)
        ans = self.answers.for_(rec, self.hn.box_answer.get(BOX_NAME[kind], True))

        def handler(dlg):
            info = self._seen(rec, dlg)
            self._title_ok(info['title'], title)
            self._body_ok(info, text)
            self._same(info['buttons'], rec['buttons'], 'buttons')
            press(dlg, picks(ans))
        got = self.op.run(call, handler)
        if got != ans:
            raise AssertionError(f'{kind} {title!r}: the window returned {got!r}, the operator answered {ans!r}')
        self.prompts.append(dict(rec, answer=plain(got)))
        return got

    def ask_yes_no(self, title, text, *, icon=None, default=None, parent=None):
        return self._box('ask_yes_no', title, text, icon, default, lambda: super(ProofPort, self).ask_yes_no(title, text, icon=icon, default=default, parent=parent),
                         lambda a: 'Yes' if a else 'No')

    def ask_ok_cancel(self, title, text, *, icon=None, parent=None):
        return self._box('ask_ok_cancel', title, text, icon, None, lambda: super(ProofPort, self).ask_ok_cancel(title, text, icon=icon, parent=parent),
                         lambda a: 'OK' if a else 'Cancel')

    def ask_retry_cancel(self, title, text, *, icon=None, parent=None):
        return self._box('ask_retry_cancel', title, text, icon, None, lambda: super(ProofPort, self).ask_retry_cancel(title, text, icon=icon, parent=parent),
                         lambda a: 'Retry' if a else 'Cancel')

    def ask_yes_no_cancel(self, title, text, *, icon=None, parent=None):
        return self._box('ask_yes_no_cancel', title, text, icon, None, lambda: super(ProofPort, self).ask_yes_no_cancel(title, text, icon=icon, parent=parent),
                         lambda a: 'Cancel' if a is None else ('Yes' if a else 'No'))

    def ask_text(self, title, prompt, *, initial=None, show=None, parent=None):
        rec = record('ask_text', title, prompt, initial=initial, masked=True if show else None)
        ans = self.answers.for_(rec, None)

        def handler(dlg):
            info = self._seen(rec, dlg)
            self._title_ok(info['title'], title)
            self._body_ok(info, prompt)
            entry = dlg.findChild(QLineEdit)
            if ans is None:
                press(dlg, 'Cancel')
            else:
                entry.setText(ans)
                press(dlg, 'OK')
        got = self.op.run(lambda: super(ProofPort, self).ask_text(title, prompt, initial=initial, show=show, parent=parent), handler)
        self.prompts.append(dict(rec, answer=('<masked>' if show and got else plain(got))))
        return got

    def choose_file(self, *, parent=None, **opts):
        return self._file('choose_file', self.answers.open_path, lambda: super(ProofPort, self).choose_file(parent=parent, **opts), opts)

    def save_file(self, *, parent=None, **opts):
        return self._file('save_file', self.answers.save_path, lambda: super(ProofPort, self).save_file(parent=parent, **opts), opts)

    def _file(self, kind, default, call, opts):
        prompts.native_file_dialogs = False
        rec = record(kind, options={k: v for k, v in opts.items() if v is not None})
        ans = self.answers.for_(rec, default)
        if ans:
            raise AssertionError('this harness only cancels file choosers (a chosen file needs a real path)')

        def handler(dlg):
            self._seen(rec, dlg)
            if not isinstance(dlg, QFileDialog):
                raise AssertionError(f'a file chooser was expected, got {type(dlg).__name__}')
            dlg.reject()
        got = self.op.run(call, handler)
        self.prompts.append(dict(rec, answer=plain(got)))
        return got

    def operator_prompt(self, title, heading, steps, *, parent=None, **opts):
        known = ('facts', 'caution', 'ok', 'cancel', 'image')
        rec = operator_record(title, heading, steps, opts.get('facts'), opts.get('caution'), opts.get('ok', 'OK'), opts.get('cancel', 'Cancel'), opts.get('image'),
                              **{k: v for k, v in opts.items() if k not in known})
        ans = self.answers.for_(rec, True)
        ok, cancel = rec['buttons']

        def handler(dlg):
            info = self._seen(rec, dlg)
            self._title_ok(info['title'], title)
            if opts.get('layout') != 'function_change':
                self._body_ok(info, heading)
                for step in steps:
                    for part in (step if isinstance(step, (list, tuple)) else [step]):
                        if part:
                            self._body_ok(info, part)
                for k, v in opts.get('facts') or []:
                    self._body_ok(info, str(k))
                    self._body_ok(info, str(v))
                if opts.get('caution'):
                    self._body_ok(info, opts['caution'])
                if opts.get('image'):
                    pic = dlg.findChild(QLabel, 'hookup_picture')
                    if Path(opts['image']).is_file() and (pic is None or pic.pixmap().isNull()):
                        raise AssertionError('the hook-up picture is not on the window')
            else:
                card = opts['card']
                for part in (card['test'], card['meter_line'], *[x for s in card['steps'] for x in s[:2] if x]):
                    self._body_ok(info, part)
            self._same(info['buttons'], [cancel, ok], 'buttons')                 # Cancel left of OK, as the Tk window packs them
            press(dlg, ok if ans else cancel)
        got = self.op.run(lambda: super(ProofPort, self).operator_prompt(title, heading, steps, parent=parent, **opts), handler)
        if got != ans:
            raise AssertionError(f'operator_prompt {title!r}: the window returned {got!r}, the operator answered {ans!r}')
        self.prompts.append(dict(rec, answer=plain(got)))
        return got

    def report_details(self, procedure='', *, parent=None):
        rec = record('report_details', procedure, '')
        ans = self.answers.for_(rec, None)
        if ans is None:                                   # cancelled: through the real window
            def handler(dlg):
                self._seen(rec, dlg)
                dlg.reject()
            got = self.op.run(lambda: super(ProofPort, self).report_details(procedure, parent=parent), handler)
            if got is not None:
                raise AssertionError(f'report details cancelled but returned {got!r}')
        else:
            got = ans                                     # details given: no window is driven (the scripted answer is returned as the Tk harness did)
            self.shown.append(dict(kind='report_details', title='', body=[], buttons=[], driven=False))
        self.prompts.append(dict(rec, answer=plain(got)))
        return got

    # ---- the handheld windows
    def ask_range(self, p, total, dial, standby_text, *, parent=None):
        rec = record('ask_range', f'point {p["id"]}', p.get('dial_text') or p['switch'], None, range=p['range'], standby=standby_text)
        ans = self.answers.for_(rec, self.hn.range_answer)
        pick = {'ok': 'Range selected - continue  (Enter)', 'skip': 'Skip point', 'stop': 'Stop run'}[ans]

        def handler(dlg):
            info = self._seen(rec, dlg)
            self._same(info['title'].replace(prompts._title(''), ''), f'Point {p["n"]} of {total} - select the range', 'window title')
            for part in (f'Point {p["n"]} of {total}  -  {p["section"]}', p.get('dial_text') or p['switch'], p['range'], standby_text, p.get('note')):
                if part:
                    self._body_ok(info, part)
            self._same(info['buttons'], ['Stop run', 'Skip point', 'Range selected - continue  (Enter)'], 'buttons')
            press(dlg, pick)
        got = self.op.run(lambda: super(ProofPort, self).ask_range(p, total, dial, standby_text, parent=parent), handler)
        if got != ans:
            raise AssertionError(f'ask_range point {p["id"]}: the window returned {got!r}, the operator answered {ans!r}')
        self.prompts.append(dict(rec, answer=plain(got)))
        return got

    def ask_ir_problem(self, p, total, problems, shown, *, parent=None):
        rec = record('ask_ir_problem', f'point {p["id"]}', '; '.join(problems), None, shown=shown or None)
        ans = self.answers.for_(rec, 'stop')
        pick = {'retry': 'Re-check  (Enter)', 'type': 'Type the reading instead', 'skip': 'Skip point', 'stop': 'Stop run'}[ans]

        def handler(dlg):
            info = self._seen(rec, dlg)
            self._same(info['title'].replace(prompts._title(''), ''), f'Point {p["n"]} of {total} - check the meter', 'window title')
            for part in ('•  ' + x for x in problems):
                self._body_ok(info, part)
            self._body_ok(info, p['switch'])
            if shown:
                self._body_ok(info, shown)
            self._same(info['buttons'], ['Stop run', 'Skip point', 'Type the reading instead', 'Re-check  (Enter)'], 'buttons')
            press(dlg, pick)
        got = self.op.run(lambda: super(ProofPort, self).ask_ir_problem(p, total, problems, shown, parent=parent), handler)
        if got != ans:
            raise AssertionError(f'ask_ir_problem point {p["id"]}: the window returned {got!r}, the operator answered {ans!r}')
        self.prompts.append(dict(rec, answer=plain(got)))
        return got

    def _typed(self, p):
        hn = self.hn
        typed = hn.readings.get(p['id']) if p['id'] in hn.readings else None
        if typed is None and hn.default_reading:
            typed = hn.default_reading(p)
        if callable(typed):
            typed = typed(p)
        return typed

    def ask_reading(self, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                    limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, *, parent=None):
        hn = self.hn
        rec = record('ask_reading', f'point {p["id"]}', out_text, None, mode=mode, device=device, source=source, unit=unit, phase=phase or None,
                     question=question, annunciator=bool(annunciator), fill_offered=demo_fill is not None, note=out_note)
        rule = self.answers.for_(rec, None)
        if demo_fill is not None:
            hn.fills.append(p['id'])
        hn.dialogs.append(('reading', p['id'], mode, device))
        typed = None if rule is not None else self._typed(p)
        use_fill = rule is None and typed is None and hn.fill and demo_fill is not None

        def handler(dlg):
            info = self._seen(rec, dlg)
            self._same(info['title'].replace(prompts._title(''), ''), f'Point {p["n"]} of {total}', 'window title')
            import handheld_dmm as hh
            head = f'Point {p["n"]} of {total}  -  {p["section"]}' + (f'  -  {phase}' if phase else '')
            for part in (head, hh.describe(p), device, accept, f'WHAT DOES THE {device} SHOW?' if mode == 'numeric' else 'YOUR ANSWER'):
                self._body_ok(info, part)
            if p.get('applied') or p['group'] != 'NONE':
                self._body_ok(info, source)
                self._body_ok(info, out_text)
                if out_note:
                    self._body_ok(info, str(out_note))
            if mode == 'yesno':
                self._body_ok(info, question)
            if mode == 'numeric' and unit:
                self._body_ok(info, unit)
            want_buttons = ['Stop run', 'Skip point'] + (['Record  (Enter)'] if mode == 'numeric' else ['No', 'Yes  (Enter)']) + ([hh.virtualbench.FILL_TEXT] if demo_fill is not None else [])
            self._same(sorted(info['buttons']), sorted(want_buttons), 'buttons')
            ann_box = next((c for c in dlg.findChildren(QCheckBox) if c.text() == 'The AC annunciator is ON' and c.isVisibleTo(dlg)), None)
            if (ann_box is not None) != bool(annunciator and mode == 'numeric'):
                raise AssertionError('the AC annunciator box is shown only when the engine asks for it')
            info['has_fill'] = demo_fill is not None
            entry = next((e for e in dlg.findChildren(QLineEdit) if e.isVisibleTo(dlg)), None)
            if rule is not None:                                                  # an explicit answer: a dict(action, text, ann, yes)
                act = rule['action']
                if act == 'record':
                    if mode == 'numeric':
                        entry.setText(rule['text'])
                        if ann_box is not None and rule.get('ann'):
                            ann_box.setChecked(True)
                    else:
                        press(dlg, 'Yes  (Enter)' if rule['yes'] else 'No')
                        return
                press(dlg, {'record': 'Record  (Enter)', 'skip': 'Skip point', 'stop': 'Stop run'}[act])
                return
            if use_fill:
                press(dlg, hh.virtualbench.FILL_TEXT)
                if mode == 'numeric':
                    info['filled'] = entry.text()
                    press(dlg, 'Record  (Enter)')
                return                                                         # yes / no: the demo fill answers by itself
            if typed is None:
                press(dlg, 'Stop run')
                return
            if mode == 'numeric':
                entry.setText(typed)
                if ann_box is not None and hn.annunciator_on:
                    ann_box.setChecked(True)
                press(dlg, 'Record  (Enter)')
            else:
                press(dlg, 'Yes  (Enter)' if typed else 'No')
        got = self.op.run(lambda: super(ProofPort, self).ask_reading(p, total, out_text, out_note, accept, mode, question, unit, annunciator, validate, phase,
                                                                    limit_s, on_expire, device, source, demo_fill, parent=parent), handler)
        self.prompts.append(dict(rec, answer=plain(got)))
        return got

    def ask_readings(self, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None, device='METER',
                     source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading='', *, parent=None):
        hn = self.hn
        rec = record('ask_readings', f'point {p["id"]}', out_text, None, device=device, source=source, unit=unit, phase=phase or None, heading=heading or None,
                     meters=[list(m) for m in meters], fill_offered=demo_fill is not None, note=out_note, tol_text=tol_text or None)
        rule = self.answers.for_(rec, None)
        if demo_fill is not None:
            hn.fills.append(p['id'])
        hn.dialogs.append(('readings', p['id'], [m[0] for m in meters]))

        def handler(dlg):
            import handheld_dmm as hh
            info = self._seen(rec, dlg)
            self._same(info['title'].replace(prompts._title(''), ''), f'Point {p["n"]} of {total}', 'window title')
            for part in (heading, accept, out_text):
                if part:
                    self._body_ok(info, part)
            for _key, label_, _serial in meters:
                self._body_ok(info, f'Asset {label_}')
            edits = [e for e in dlg.findChildren(QLineEdit) if e.isVisibleTo(dlg)]
            self._same(len(edits), len(meters), 'one reading box per meter')
            if rule is not None:
                act = rule['action']
                if act == 'record':
                    for e, (key, _l, _s) in zip(edits, meters):
                        e.setText(rule['texts'][key])
                press(dlg, {'record': 'Record all  (Enter)', 'skip': 'Skip point', 'stop': 'Stop run'}[act])
                return
            action = hn.queue_action.get(p['id'])
            if action:
                press(dlg, {'skip': 'Skip point', 'stop': 'Stop run'}[action])
                return
            for idx, (e, (key, _l, _s)) in enumerate(zip(edits, meters)):
                if (key, p['id']) in hn.queue_no_reading:
                    next(c for c in dlg.findChildren(QCheckBox) if c.isVisibleTo(dlg) and c.text() == 'No reading' and
                         c.parentWidget() is e.parentWidget()).setChecked(True)
                    continue
                val = hn.queue_readings.get((key, p['id']))
                if val is None and hn.queue_default:
                    val = hn.queue_default(p, key)
                if val is None:
                    val = self._typed(p)
                if val is None and hn.fill and demo_fill is not None:
                    press(dlg, hh.virtualbench.FILL_TEXT)
                    break
                if val is None:
                    press(dlg, 'Stop run')
                    return
                e.setText(val)
            press(dlg, 'Record all  (Enter)')
        got = self.op.run(lambda: super(ProofPort, self).ask_readings(p, total, out_text, out_note, accept, meters, unit, judge, limit_s, on_expire, device, source,
                                                                      demo_fill, tol_text, phase, heading, parent=parent), handler)
        self.prompts.append(dict(rec, answer=plain(got)))
        return got


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the harness
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class _SelectionHook:
    """tree.selection.return_value = ... as the scenario functions do on the stubbed tree: the tree answers that until it is unset."""
    _UNSET = object()

    def __init__(self, tree):
        self.tree, self.return_value = tree, self._UNSET

    def __call__(self):
        return self.tree._real_selection() if self.return_value is self._UNSET else self.return_value


class QtHarness:
    def __init__(self, answers=None, home=None):
        self.home = Path(home or tempfile.mkdtemp())
        self.answers = answers or Answers()
        self.patches = []
        self.dialogs, self.fills = [], []
        self.readings, self.default_reading = {}, None
        self.fill, self.annunciator_on = True, False
        self.range_answer = 'ok'
        self.box_answer = {}
        self.queue_readings, self.queue_default, self.queue_no_reading, self.queue_action = {}, None, set(), {}
        self.prompts = []                                   # Tk-level prompts: none can happen here
        self.root, self.app, self.port = None, None, None
        self.errors = []

    def start(self):
        import run_queue_engine
        import tds2000c_verification as tds
        import handheld_dmm as hh
        import qtui.shell_helpers as SH
        qapp.create_app()
        prompts.native_file_dialogs = False
        env = mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.home / 'data'), 'HOME': str(self.home), 'USERPROFILE': str(self.home)})
        env.start()
        self.patches.append(env)
        real_selection = SH.ResultsTree.selection
        for obj, name, val in ((tds, 'SLEEP_SCALE', 0), (hh.IO, '_wait', staticmethod(lambda seconds, cancel=None: None)),
                               (SH.ResultsTree, '_real_selection', real_selection),
                               (SH.ResultsTree, 'selection', property(lambda tree: tree.__dict__.setdefault('_sel_hook', _SelectionHook(tree))))):
            p = mock.patch.object(obj, name, val, create=True)
            p.start()
            self.patches.append(p)
        try:
            import drivers.fluke_5790b as f5790
            p = mock.patch.object(f5790.time, 'sleep', lambda s: None)
            p.start()
            self.patches.append(p)
        except ImportError:
            pass
        self.root = QMainWindow()
        self.root.resize(1320, 820)
        self.port = ProofPort(self.answers, self)
        self._old_ui = ui_port.set_ui(self.port)
        return self

    def stop(self):
        try:
            app = self.app
            if app is not None:
                app.stop = True
                prog = getattr(getattr(app, '_q', None), 'progress', None)
                if prog is not None:
                    prog.close()
        except Exception:
            pass
        if self.root is not None:
            self.root.setProperty('_calsuite_closing', True)
            self.root.close()
            self.root.deleteLater()
        for w in QApplication.topLevelWidgets():          # a dialog left over from this run would stay QApplication.activeWindow() (offscreen) and become the parent of the next run's prompts
            if isinstance(w, (QDialog, QMainWindow)):
                try:
                    w.setProperty('_calsuite_closing', True)
                    w.close()
                    w.deleteLater()
                except RuntimeError:
                    pass
        settle()
        for p in reversed(self.patches):
            p.stop()
        self.patches = []
        ui_port.set_ui(self._old_ui)
        prompts.native_file_dialogs = None

    # ---- the user-built datasheet runtime (tests/ui_prompt_capture_dsb.py)
    def make_app(self, spec, demo=False, io=None, period=None):
        import dsb_runtime as rt
        self.app = rt.DsbApp(self.root, spec, demo=demo, io_factory=(lambda: io) if io is not None else None, period=period)
        self.app.asset.set('A-100')
        self.app.serial.set('S-1')
        if io is not None:
            self.app.io = io
        return self.app

    # ---- the pump
    def pump(self, seconds=120):
        end = time.time() + seconds
        app = self.app
        idle = 0
        while time.time() < end:
            QApplication.processEvents()
            workers = [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon]
            if not app.busy and not workers:
                idle += 1
                if idle > 25:
                    break
            else:
                idle = 0
            time.sleep(0.002)
        return not app.busy

    def run_all(self):
        self.app.run_all()
        return self.pump()
