"""Records tests/qt_ref/genscope_rows.json from the REAL Tk windows (fgen_view_tk / mdo4000c_view_tk / tds2000c_view_tk) running the simulated bench.  Not a test module.

    xvfb-run -a <python with tkinter, 3.13> tests/record_tk_genscope.py [scenario ...]          (all scenarios by default; the MDO runs take about a minute each)

Dialogs are scripted like the Tk-level harness does (the first answer of tests/ui_prompt_capture_wpg: a typed reading box answers with its pre-filled value);
the toolkit is real Tk 9: real Shell, real Treeview, real variables.  The Qt side is tests/test_qt_views_genscope.py::Rows."""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

HOME = tempfile.mkdtemp()
os.environ.update(HOME=HOME, USERPROFILE=HOME, CALSUITE_DATA=str(Path(HOME) / 'data'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import genscope_rows as G  # noqa: E402

import tkinter as tk  # noqa: E402

import ui_port  # noqa: E402
import ui_port_tk  # noqa: E402
from ui_port import Answers, ScriptedUiPort  # noqa: E402

_SCRIPTED = ('message', 'ask_yes_no', 'ask_ok_cancel', 'ask_retry_cancel', 'ask_yes_no_cancel', 'ask_text', 'ask_number', 'choose_file', 'save_file', 'choose_dir',
             'operator_prompt', 'report_details', 'ask_value')


def accept_initial(rec):
    return rec.get('initial') if rec['kind'] in ('ask_number', 'ask_text') else None


class TkScriptedPort(ui_port_tk.TkUiPort):
    def __init__(self):
        super().__init__()
        self.answers = Answers([accept_initial])
        self.prompts = []
        self.events = []
    _ask = ScriptedUiPort._ask


for _n in _SCRIPTED:
    setattr(TkScriptedPort, _n, getattr(ScriptedUiPort, _n))


def workers():
    return [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon and t.is_alive()]


def patch_speed():
    import tds2000c_verification as tds
    import handheld_dmm as hh
    import drivers.fluke_5790b as f5790
    tds.SLEEP_SCALE = 0
    hh.IO._wait = staticmethod(lambda seconds, cancel=None: None)
    f5790.time.sleep = lambda s: None


def record(key):
    ui_port.set_ui(TkScriptedPort())
    root = tk.Tk()
    root.geometry('1320x840+0+0')
    app = G.build(key, root)
    app.settle = lambda: None

    def run(start):
        """Real Tk: the worker threads post through root.after, which needs the main thread in mainloop (like the app: Run All is a button click inside it); a poll quits
        the loop when the run is over."""
        end = time.time() + 600
        state = {'quiet': 0, 'ok': False}

        def poll():
            if not app.busy and not workers():
                state['quiet'] += 1
                if state['quiet'] > 3:
                    state['ok'] = True
                    root.quit()
                    return
            else:
                state['quiet'] = 0
            if time.time() > end:
                root.quit()
                return
            root.after(10, poll)
        root.after(10, start)
        root.after(60, poll)
        root.mainloop()
        return state['ok']
    snap = G.snapshot(app, root.title(), run, root.update)
    app.stop = True
    root.destroy()
    return snap


def main(keys):
    patch_speed()
    out = json.loads(G.REF.read_text(encoding='utf-8')) if G.REF.exists() else {}
    for key in keys or G.SCENARIOS:
        t = time.time()
        out[key] = record(key)
        print(key, 'recorded', round(time.time() - t, 1), 's,', len(out[key]['rows']), 'rows', flush=True)
    G.REF.parent.mkdir(exist_ok=True)
    body = ',\n'.join(f'{json.dumps(k)}: {json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))}' for k, v in sorted(out.items()))
    G.REF.write_text('{\n' + body + '\n}\n', encoding='utf-8')                  # one scenario per line


if __name__ == '__main__':
    main(sys.argv[1:])
