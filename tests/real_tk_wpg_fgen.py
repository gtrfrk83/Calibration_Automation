"""Real-Tk check of ui_port.call_from_worker through the function-generator engine (run by tests/test_wpg_real_tk.py in a subprocess; not a test module).

    python tests/real_tk_wpg_fgen.py <scenario>        scenario: answer | cancel | raise

The real fgen window (real Tk, a worker thread, mainloop) runs two demo points (SELFTEST, TIMEBASE) on the simulated bench.  The TIMEBASE point makes the WORKER ask
for a typed counter reading (`App.ask_number_threadsafe` -> `port.call_from_worker` -> Tk askfloat).  The real simpledialog window is answered from the UI thread:
  answer   OK on the box (it holds the simulated reading): the dialog was created on the Tk thread, the worker waited, the point is recorded with the typed value
  cancel   Cancel: the worker gets None -> 'Reading not entered; run stopped.' error dialog, the point is not recorded
  raise    askfloat raises on the UI thread: the app's Tk exception handler reports it, the worker still gets None and the run ends with the same error dialog
Prints 'CHECK <name> ok' lines and 'ALL OK'."""
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

_HOME = tempfile.mkdtemp()
os.environ.update(HOME=_HOME, USERPROFILE=_HOME, CALSUITE_DATA=str(Path(_HOME) / 'data'))
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'Procedures')]

import tkinter as tk  # noqa: E402
from tkinter import messagebox, simpledialog  # noqa: E402


def check(name, cond, detail=''):
    if not cond:
        raise AssertionError(f'{name}: {detail}')
    print(f'CHECK {name} ok')


def main(scenario):
    import fgen_verification as F
    import ui_theme
    import ui_port
    check('the engine is ported (TkUiPort answers)', type(ui_port.get_ui()).__name__ == 'TkUiPort')
    boxes, seen = [], {}
    for name in ('showinfo', 'showwarning', 'showerror'):
        setattr(messagebox, name, lambda *a, _n=name, **k: boxes.append((_n, a[:2])))
    for name in ('askyesno', 'askokcancel', 'askyesnocancel'):
        setattr(messagebox, name, lambda *a, **k: True)
    ui_theme.confirm_steps = lambda *a, **k: True                      # the hook-up / safety prompts are not what is tested here
    time.sleep = lambda s: None
    real_askfloat = simpledialog.askfloat

    def askfloat(*a, **k):
        seen['thread_is_main'] = threading.current_thread() is threading.main_thread()
        seen['title'], seen['worker_alive'] = a[0], any(t.daemon and t.is_alive() for t in threading.enumerate())
        if scenario == 'raise':
            raise RuntimeError('askfloat failed on the UI thread')
        return real_askfloat(*a, **k)
    simpledialog.askfloat = askfloat

    F.configure('33220A')
    root = tk.Tk()
    root.geometry('1200x800+0+0')
    app = F.App(root, '33220A', demo=True)
    app.asset.set('A1')
    app.serial.set('S1')
    points = [p for p in F.POINTS if p['kind'] in ('SELFTEST', 'TIMEBASE')][:2]
    check('two points to run, the second asks for a typed reading', [p['kind'] for p in points] == ['SELFTEST', 'TIMEBASE'], points)
    state = {'pressed': False, 'started': False}
    end = time.monotonic() + 90

    def dialogs():
        return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and hasattr(w, 'entry') and hasattr(w, 'ok')]

    def poll():
        tops = dialogs()
        if tops and not state['pressed']:
            state['pressed'] = True
            state['title'] = tops[0].title()
            state['entry'] = tops[0].entry.get()
            state['worker_waiting'] = not app.results.get(str(points[1]['id']))
            (tops[0].ok if scenario == 'answer' else tops[0].cancel)()
        if state['started'] and not app.busy and not dialogs():
            root.quit()
        elif time.monotonic() > end:
            root.quit()
        else:
            root.after(20, poll)

    app.execute(points)
    state['started'] = True
    root.after(20, poll)
    root.mainloop()
    check('the run ended (not hung)', not app.busy)
    rec = app.results.get(str(points[1]['id']))
    errs = [b for b in boxes if b[0] == 'showerror']
    check('the first point is recorded', str(points[0]['id']) in app.results)
    check('the reading box was created on the Tk thread', seen.get('thread_is_main') is True, seen)
    check('the worker was alive and waiting while the box was open', seen.get('worker_alive') is True, seen)
    check('the box carries the demo title', seen.get('title') == 'Type the reading [DEMO]', seen)
    if scenario == 'answer':
        check('a real dialog window was answered', state['pressed'] and state['title'] == 'Type the reading [DEMO]', state)
        check('the box held the simulated reading', state['entry'] not in ('', None), state)
        check('the worker waited for the answer (point not yet recorded when OK was pressed)', state['worker_waiting'])
        check('the typed value is the recorded reading', rec is not None and abs(rec['reading'] - float(state['entry'])) < 1e-9 * max(1.0, abs(rec['reading'])), (rec, state))
        check('no error dialog', not errs, errs)
    else:
        titles = [b[1][0] for b in errs]
        check('the point is not recorded', rec is None, rec)
        check('the engine shows its own error dialog', 'Measurement stopped' in titles and any('Reading not entered' in b[1][1] for b in errs), errs)
        if scenario == 'cancel':
            check('a real dialog window was cancelled', state['pressed'], state)
            check('no other error dialog', titles == ['Measurement stopped'], errs)
        else:
            check('the app reported the exception raised on the UI thread (its unexpected-error dialog)',
                  any(b[1][0] == 'Something went wrong' and 'RuntimeError: askfloat failed on the UI thread' in b[1][1] for b in errs), errs)
    app.stop = True
    root.destroy()


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print('ALL OK')
