"""UiPort: the one seam between the calibration engines and the GUI toolkit.  No toolkit is imported here (tkinter lives in ui_port_tk.py only).

An engine never imports tkinter / PySide6 and never calls a message box itself: it asks the port.

    from ui_port import ui as port            # a proxy: every call goes to the port the host installed (set_ui), Tk unless told otherwise

    if not port.ask_yes_no('HIGH VOLTAGE', 'This point outputs 1000 V. ... Enable output?'):
        return
    port.message('error', 'Measurement stopped', str(exc))
    ok = port.operator_prompt('Rewire / verify', 'Connect for DC volts', steps, facts=facts, caution=caution, ok='Connections verified', image=png)
    port.post(self.root, self._done, points, i)        # from a worker thread: run on the UI thread

The host picks the implementation once, before any window exists:   ui_port.set_ui(TkUiPort())  (the default, created on first use)  /  a Qt port later /
ScriptedUiPort in tests.  What each implementation must do is the contract below; TkUiPort (ui_port_tk.py) is the existing Tk behaviour moved, not redesigned.

CONTRACT (every method is called on the UI thread unless the text says otherwise; `win` / `parent` is whatever the host's main window object is: opaque to the engine)
  Messages and questions (modal, blocking, return after the operator answered):
    message(kind, title, text, *, parent=None)        kind 'info' | 'warning' | 'error'; one OK button
    ask_yes_no(title, text, *, icon=None, default=None, parent=None) -> bool        default 'yes' | 'no' = the preselected button
    ask_ok_cancel(title, text, *, icon=None, parent=None) -> bool
    ask_retry_cancel(title, text, *, icon=None, parent=None) -> bool
    ask_yes_no_cancel(title, text, *, icon=None, parent=None) -> bool | None          Yes True, No False, Cancel None
    ask_text(title, prompt, *, initial=None, show=None, parent=None) -> str | None     None = cancelled
    ask_number(title, prompt, *, initial=None, minvalue=None, maxvalue=None, integer=False, parent=None) -> float | int | None
    choose_file(*, parent=None, **opts) -> str                  '' = cancelled; opts: filetypes, title, initialdir
    save_file(*, parent=None, **opts) -> str                    '' = cancelled; opts: defaultextension, filetypes, initialfile, title, initialdir
    choose_dir(*, parent=None, **opts) -> str                   '' = cancelled
    operator_prompt(title, heading, steps, *, parent=None, **opts) -> bool    the confirm-the-hook-up / safety prompt; steps = [(lead, detail)] or [str];
                                        opts: facts, caution, ok, cancel, image (PNG path or None), layout, card.  This is also how a hook-up picture is shown.
    report_details(procedure='', *, parent=None) -> dict | None                the report details / review window (report_dialog.ask_details)
  Threads and time:
    post(win, fn, *args)                      THREAD-SAFE.  Run fn on the UI thread soon (a worker thread's way to touch the UI); fire and forget
    after(win, ms, fn, *args) -> handle       UI thread only.  Run fn on the UI thread after ms
    call_from_worker(win, fn, *args) -> result  WORKER thread only.  Run fn on the UI thread, block until it ran, return its result (the fgen 'ask a number' pattern)
  Window and variables:
    run_app(factory)                          create the toolkit's application / main window, call factory(win) to build the app, run the event loop until it closes
    set_title(win, text) / on_close(win, fn) / bind_key(win, sequence, fn) / close(win) / flush(win)       window chrome the engines touch
    var(value='', kind='str') -> object with get() / set(v) / trace_add('write', fn)       kind 'str' | 'bool' | 'int' | 'float'
    surprise_handler(win) -> handler          the Stop / Continue dialog of surprise.py, made ON the UI thread (see surprise.tk_handler)
    view(name) -> module                      the toolkit's window code for an engine: module `<name>_<toolkit>` (agilent34410a_view -> agilent34410a_view_tk)

  Handheld reading windows (handheld_dmm.py; modal, blocking, UI thread; `parent` as everywhere is never part of the recorded prompt):
    ask_reading(p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='', limit_s=None, on_expire=None,
                device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, *, parent=None) -> dict(action='record'|'skip'|'stop', text=, ann=, yes=)
                                        the reading window for point `p` (a handheld_dmm point dict): mode 'numeric' (type the display; `validate(text)` raises ValueError for
                                        an unusable entry, which the window shows and stays open) or 'yesno' (answer `question`); `accept` is the 'ACCEPT IF' line;
                                        `limit_s` / `on_expire`: a countdown after which `on_expire()` is called once; `demo_fill()` (virtual bench only) is the
                                        'Fill with a simulated reading' button; closing the window = 'stop'.  Tk: handheld_dmm_view_tk.ask_reading
    ask_readings(p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT',
                 demo_fill=None, tol_text='', phase='', heading='', *, parent=None) -> dict(action=, texts={key: text|None}, no_reading=[keys])
                                        the run-queue window: one box per meter (`meters` = [(key, asset label, serial)]), each judged live by judge(key, text) ->
                                        (state, padded_text, note) (ValueError = not a reading); demo_fill(index) fills a box.  Tk: run_queue_ui.ask_readings
    ask_range(p, total, dial, standby_text, *, parent=None) -> 'ok' | 'skip' | 'stop'
                                        'Turn the dial to ...' with the dial picture (`dial` = the spec's dial block) and the target position marked
    ask_ir_problem(p, total, problems, shown, *, parent=None) -> 'retry' | 'type' | 'skip' | 'stop'
                                        the meter (read over IR) is not set up as the point needs
    progress_window(win, title='Queue progress', on_show=None, on_export=None) -> object with update(heading, fraction, rows, finished=False, note=''), close(), alive()
                                        the non-modal run-queue progress window (Tk: run_queue_ui.QueueProgress).  Added to the interface; run_queue_engine still builds it
                                        through its own `queue_progress_factory` until the shared-helpers package routes that through this method.

NOT in the interface yet (each has real call sites; the work package that ports them adds the method AND a ScriptedUiPort implementation, then a line here):
    (ask_reading / ask_readings / ask_range / ask_ir_problem / progress_window are in the interface now: see 'Handheld reading windows' below)
    result / table windows                    ui_shell.results_table, ui_theme.make_table: today part of the engine's own window (see 'view')
    custom dialogs                            ui_theme.dialog + Toplevel in Fluke_8808A_Adjustment / Keithley_2000_Adjustment / WaveSurfer; surprise.py's own Toplevel
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

# ----------------------------------------------------------------------------------------------------------------------------------------------------
# canonical prompt record (what ScriptedUiPort keeps; tests/ui_prompt_capture.py records the same form from the Tk calls of an unported engine)
# ----------------------------------------------------------------------------------------------------------------------------------------------------
BUTTONS = {
    'info': ['OK'], 'warning': ['OK'], 'error': ['OK'],
    'ask_yes_no': ['Yes', 'No'], 'ask_ok_cancel': ['OK', 'Cancel'], 'ask_retry_cancel': ['Retry', 'Cancel'],
    'ask_yes_no_cancel': ['Yes', 'No', 'Cancel'],
}
_DATE = re.compile(r'\d{1,2}-\d{1,2}-\d{4}')                 # report file names carry today's date


def plain(x):
    """JSON-able, stable: tuples -> lists, paths -> their file name, dates masked, anything odd -> repr."""
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    if isinstance(x, Path):
        return x.name
    if isinstance(x, str):
        return _DATE.sub('<date>', x)
    if isinstance(x, (int, float, bool)) or x is None:
        return x
    return repr(x)


def record(kind, title='', text='', answer=None, **extra):
    r = dict(kind=kind, title=title, text=text, buttons=BUTTONS.get(kind), answer=plain(answer))
    r.update({k: plain(v) for k, v in extra.items()})
    return {k: v for k, v in r.items() if v is not None}


def operator_record(title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None, answer=None, **layout):
    return record('operator_prompt', title, heading, answer, steps=[s if isinstance(s, str) else list(s) for s in steps], facts=facts, caution=caution,
                  buttons=[ok, cancel], image=(Path(image).name if image else None), layout=layout or None)


class Answers:
    """The scripted operator.  `rules` are callables record -> answer (None = no opinion; the first rule that answers wins); otherwise the default:
    yes / OK / True for questions and operator prompts, cancelled (None) for text / number / report details, `save_path` / `open_path` for file choosers."""

    def __init__(self, rules=(), save_path='', open_path=''):
        self.rules = list(rules)
        self.save_path, self.open_path = save_path, open_path

    def for_(self, rec, default):
        for rule in self.rules:
            got = rule(rec)
            if got is not None:
                return got
        return default


class ScriptedVar:
    """get / set / trace_add like a Tk variable, no toolkit."""
    CAST = {'str': str, 'bool': bool, 'int': int, 'float': float}

    def __init__(self, value='', kind='str'):
        self._v, self._cbs = value, []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in list(self._cbs):
            cb('', '', 'write')

    def trace_add(self, mode, callback):
        self._cbs.append(callback)
        return str(len(self._cbs))


class ScriptedProgress:
    """The non-modal progress window of a test: keeps every update() (heading, fraction, rows, finished, note)."""

    def __init__(self):
        self.updates, self.closed = [], False

    def update(self, heading, fraction, rows, finished=False, note=''):
        self.updates.append((heading, fraction, [dict(r) for r in rows], finished, note))

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True


class ScriptedUiPort:
    """A port for tests: shows nothing, records every prompt in the canonical form (`.prompts`), answers from `answers` (an Answers, or None for the defaults).

    Scheduling: post / after hand the call to `win.after(ms, fn, *args)` when the window object has one (the tests' FakeRoot queues it for their pump),
    otherwise it is kept in `.scheduled` and run by `run_scheduled()`.  call_from_worker runs fn at once on the calling thread (there is no UI thread)."""

    def __init__(self, answers=None):
        self.answers = answers or Answers()
        self.prompts = []
        self.scheduled = []
        self.events = []                              # non-prompt window calls, in order: (name, args)

    # ---- bookkeeping
    def _ask(self, rec, default):
        ans = self.answers.for_(rec, default)
        self.prompts.append(dict(rec, answer=plain(ans)))
        return ans

    def run_scheduled(self):
        while self.scheduled:
            fn, args = self.scheduled.pop(0)
            fn(*args)

    # ---- messages and questions
    def message(self, kind, title, text, *, parent=None):
        self.prompts.append(record(kind, title, text))

    def ask_yes_no(self, title, text, *, icon=None, default=None, parent=None):
        return self._ask(record('ask_yes_no', title, text, icon=icon, default=default), True)

    def ask_ok_cancel(self, title, text, *, icon=None, parent=None):
        return self._ask(record('ask_ok_cancel', title, text, icon=icon), True)

    def ask_retry_cancel(self, title, text, *, icon=None, parent=None):
        return self._ask(record('ask_retry_cancel', title, text, icon=icon), True)

    def ask_yes_no_cancel(self, title, text, *, icon=None, parent=None):
        return self._ask(record('ask_yes_no_cancel', title, text, icon=icon), True)

    def ask_text(self, title, prompt, *, initial=None, show=None, parent=None):
        rec = record('ask_text', title, prompt, initial=initial, masked=True if show else None)
        ans = self.answers.for_(rec, None)
        self.prompts.append(dict(rec, answer=('<masked>' if show and ans else plain(ans))))          # a typed secret (show='*') is never recorded
        return ans

    def ask_number(self, title, prompt, *, initial=None, minvalue=None, maxvalue=None, integer=False, parent=None):
        return self._ask(record('ask_number', title, prompt, initial=initial), None)

    def choose_file(self, *, parent=None, **opts):
        return self._ask(record('choose_file', options={k: v for k, v in opts.items() if v is not None}), self.answers.open_path)

    def save_file(self, *, parent=None, **opts):
        return self._ask(record('save_file', options={k: v for k, v in opts.items() if v is not None}), self.answers.save_path)

    def choose_dir(self, *, parent=None, **opts):
        return self._ask(record('choose_dir', options={k: v for k, v in opts.items() if v is not None}), '')

    def operator_prompt(self, title, heading, steps, *, parent=None, **opts):
        known = ('facts', 'caution', 'ok', 'cancel', 'image')
        rec = operator_record(title, heading, steps, opts.get('facts'), opts.get('caution'), opts.get('ok', 'OK'), opts.get('cancel', 'Cancel'), opts.get('image'),
                              **{k: v for k, v in opts.items() if k not in known})
        return self._ask(rec, True)

    def report_details(self, procedure='', *, parent=None):
        return self._ask(record('report_details', procedure, ''), None)

    # ---- threads and time
    def post(self, win, fn, *args):
        self.after(win, 0, fn, *args)

    def after(self, win, ms, fn, *args):
        if hasattr(win, 'after'):
            return win.after(ms, fn, *args)
        self.scheduled.append((fn, args))
        return len(self.scheduled)

    def call_from_worker(self, win, fn, *args):
        return fn(*args)

    # ---- window and variables
    def run_app(self, factory):
        factory(None)

    def set_title(self, win, text):
        self.events.append(('set_title', (text,)))

    def on_close(self, win, fn):
        self.events.append(('on_close', ()))

    def bind_key(self, win, sequence, fn):
        self.events.append(('bind_key', (sequence,)))

    def close(self, win):
        self.events.append(('close', ()))
        if hasattr(win, 'destroy'):
            win.destroy()

    def flush(self, win):
        self.events.append(('flush', ()))

    def var(self, value='', kind='str'):
        return ScriptedVar(value, kind)

    def surprise_handler(self, win):
        return None                                    # headless: a surprise is a Stop (surprise.py)

    def view(self, name):
        import importlib
        return importlib.import_module(f'{name}_tk')   # the scripted port builds nothing itself: tests that need a window use the Tk view over the stub


    # ==== APPEND-ONLY BLOCK, WP-H (handheld): the reading windows and the progress window ======================================================
    # The scripted operator answers like tests/virtual_harness.VHarness did: a rule of `answers` (record -> answer) wins; otherwise the 'Fill with a simulated
    # reading' button when the engine offers it (virtual bench), otherwise the window is closed ('stop').  Records: kinds ask_reading / ask_readings / ask_range /
    # ask_ir_problem (ui_prompt_capture records the same form from the Tk-level harness).
    def ask_reading(self, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                    limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, *, parent=None):
        rec = record('ask_reading', f'point {p["id"]}', out_text, None, mode=mode, device=device, source=source, unit=unit, phase=phase or None,
                     question=question, annunciator=bool(annunciator), fill_offered=demo_fill is not None, note=out_note)
        ans = self.answers.for_(rec, None)
        if ans is None:
            typed = demo_fill() if demo_fill is not None else None
            if mode == 'numeric':
                if typed is None:
                    ans = dict(action='stop', text='', ann=False, yes=None)
                else:
                    if validate:
                        validate(typed)
                    ans = dict(action='record', text=typed, ann=False, yes=None)
            else:
                ans = dict(action='record', text='', ann=False, yes=bool(True if typed is None else typed))
        self.prompts.append(dict(rec, answer=plain(ans)))
        return ans

    def ask_readings(self, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None, device='METER',
                     source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading='', *, parent=None):
        rec = record('ask_readings', f'point {p["id"]}', out_text, None, device=device, source=source, unit=unit, phase=phase or None, heading=heading or None,
                     meters=[list(m) for m in meters], fill_offered=demo_fill is not None, note=out_note, tol_text=tol_text or None)
        ans = self.answers.for_(rec, None)
        if ans is None:
            texts, ans = {}, dict(action='stop', texts={}, no_reading=[])
            for idx, (key, _label, _serial) in enumerate(meters):
                val = demo_fill(idx) if demo_fill is not None else None
                if val is None:
                    break
                judge(key, val)
                texts[key] = val
            else:
                ans = dict(action='record', texts=texts, no_reading=[])
        self.prompts.append(dict(rec, answer=plain(ans)))
        return ans

    def ask_range(self, p, total, dial, standby_text, *, parent=None):
        return self._ask(record('ask_range', f'point {p["id"]}', p.get('dial_text') or p['switch'], range=p['range'], standby=standby_text), 'ok')

    def ask_ir_problem(self, p, total, problems, shown, *, parent=None):
        return self._ask(record('ask_ir_problem', f'point {p["id"]}', '; '.join(problems), shown=shown or None), 'stop')

    def progress_window(self, win, title='Queue progress', on_show=None, on_export=None):
        self.events.append(('progress_window', (title,)))
        return ScriptedProgress()


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------------------------------------------------------------------------------------
_ui = None
_lock = threading.Lock()


def get_ui():
    """The installed port; the Tk one is created on first use if the host installed none."""
    global _ui
    if _ui is None:
        with _lock:
            if _ui is None:
                import ui_port_tk
                _ui = ui_port_tk.TkUiPort()
    return _ui


def set_ui(port):
    """Install `port` (None = back to the default); returns the one that was installed (None if the default had not been created)."""
    global _ui
    old, _ui = _ui, port
    return old


class _Proxy:
    """`from ui_port import ui as port`: attribute access is resolved at call time, so set_ui() after an engine was imported still takes effect."""

    def __getattr__(self, name):
        return getattr(get_ui(), name)

    def __repr__(self):
        return f'<ui_port.ui -> {get_ui()!r}>'


ui = _Proxy()
