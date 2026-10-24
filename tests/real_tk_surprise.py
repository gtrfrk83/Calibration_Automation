"""Real-Tk check of the stop-on-surprise dialog (run by tests/test_surprise.py in a subprocess; not a test module).

    python tests/real_tk_surprise.py

A worker thread (like an engine's) hits a surprise; the dialog must appear on the Tk thread with the command, reply, expected and the last log lines,
and Continue / Stop / closing the window must give the right answer.  Prints 'CHECK <name> ok' lines and 'ALL OK'."""
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

import tkinter as tk  # noqa: E402

import surprise  # noqa: E402
from test_surprise import make  # noqa: E402


def check(name, cond, detail=''):
    if not cond:
        raise AssertionError(f'{name}: {detail}')
    print(f'CHECK {name} ok')


def toplevels(root):
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


def run_case(root, how, setup):
    """Run set_checked on a worker thread with the Tk handler; when the dialog shows, press `how` ('cont' | 'stop' | 'close'). Returns (outcome, text, dev)."""
    dev, bus, _seen, _h = make()
    dev.enable_surprise(surprise.tk_handler(root))
    setup(bus)
    for i in range(30):
        dev.log.add('>>', f'earlier line {i}', 'FAKE')
    out = {}

    def work():
        try:
            dev.set_checked('set', 3.0)
            out['r'] = 'continued'
        except surprise.SurpriseStop:
            out['r'] = 'stopped'
        except Exception as exc:
            out['r'] = f'error {exc!r}'

    state = {'text': '', 'pressed': False}

    def poll():
        tops = toplevels(root)
        if tops and not state['pressed']:
            w = tops[0]
            parts = []
            for c in _walk(w):
                if isinstance(c, tk.Text):
                    parts.append(c.get('1.0', 'end'))
                else:
                    try:
                        parts.append(str(c.cget('text')))
                    except (tk.TclError, AttributeError):
                        pass
            state['text'] = '\n'.join(parts)
            state['pressed'] = True
            info = w._surprise
            if how == 'cont':
                info['cont'].invoke()
            elif how == 'stop':
                info['stop'].invoke()
            else:
                root.tk.call(w.protocol('WM_DELETE_WINDOW'))      # what the window manager's close button runs
        if not th.is_alive() and not toplevels(root):
            root.quit()
        elif time.time() > end:
            root.quit()
        else:
            root.after(20, poll)

    th = threading.Thread(target=work)
    end = time.time() + 10
    th.start()
    root.after(20, poll)
    root.mainloop()                                      # like the Manager: the worker thread asks the Tk thread through root.after
    text = state['text']
    th.join(5)
    return out.get('r', 'timeout'), text, dev, len(toplevels(root))


def _walk(w):
    for c in w.winfo_children():
        yield c
        yield from _walk(c)


def main():
    root = tk.Tk()
    root.geometry('300x200+0+0')
    root.update()

    r, text, dev, left = run_case(root, 'cont', lambda b: setattr(b, 'no_apply', True))
    check('readback: Continue lets the run go on', r == 'continued', r)
    check('dialog names the command', 'SET 3' in text, text)
    check('dialog shows the reply and the expected value', "Reply:       '0'" in text and 'Expected:    3.0' in text, text)
    check('dialog shows at most 20 log lines and the newest', 'earlier line 29' in text and 'earlier line 5' not in text, text[-400:])
    check('dialog has Stop and Continue', 'Stop' in text and 'Continue' in text)
    check('dialog closed after the answer', left == 0, left)
    check('one dialog only', len([l for l in dev.log.lines() if 'SURPRISE readback' in l]) == 1)
    check('the write was sent once', sum(1 for t in dev.t.sent if t.startswith('SET ')) == 1, dev.t.sent)

    r, text, dev, left = run_case(root, 'stop', lambda b: setattr(b, 'get_reply', '=>'))
    check('bad reply: Stop raises SurpriseStop', r == 'stopped', r)
    check('bad reply text', 'prompt character' in text, text)

    r, text, dev, left = run_case(root, 'stop', lambda b: b.errors.append('-222,"Data out of range"'))
    check('error queue: Stop', r == 'stopped', r)
    check('error queue text', '-222' in text and 'Error queue not empty' in text, text)

    r, text, dev, left = run_case(root, 'close', lambda b: setattr(b, 'get_reply', ''))
    check('closing the window counts as Stop', r in ('stopped',), r)

    # a clean run never shows a dialog
    dev, bus, _s, _h = make()
    dev.enable_surprise(surprise.tk_handler(root))
    for v in (1.0, 2.0):
        dev.set_checked('set', v)
        root.update()
    check('clean run: no dialog', not toplevels(root))
    root.destroy()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print('ALL OK')
