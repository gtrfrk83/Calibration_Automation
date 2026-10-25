"""Writes tests/qt_ref/wavesurfer_tk_state.json: the widget-state record of the WaveSurfer window on the REAL Tk build (ws_state.collect).

    xvfb-run -a <python 3.12 with tkinter> tests/qt_ref/make_tk_state.py [out.json]

Run it on a checkout whose wavesurfer window is the Tk one (the engine, wavesurfer_view_tk).  Never run on hardware; the message boxes are answered by stubs."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
home = tempfile.mkdtemp()
os.environ.update(HOME=home, USERPROFILE=home, CALSUITE_DATA=str(Path(home) / 'data'), CALSUITE_THEME='dark')
sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures'), str(ROOT / 'tests' / 'qt_ref')]
os.chdir(ROOT)
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

import ui_theme_core
ui_theme_core.use_palette('dark')
for n in ('showinfo', 'showwarning', 'showerror'):
    setattr(mb, n, lambda *a, **k: None)
for n in ('askyesno', 'askokcancel', 'askyesnocancel', 'askretrycancel'):
    setattr(mb, n, lambda *a, **k: True)
import ws_state
import WaveSurfer_WS4104HD as W


class TkAdapter:
    def enabled(self, w):
        return str(w.cget('state')) != 'disabled'

    def text(self, w):
        return str(w.cget('text'))

    def title(self, app):
        return app.root.title()

    def tabs(self, app):
        return [app.tabs.tab(t, 'text') for t in app.tabs.tabs()]

    def columns(self, tree):
        return list(tree['columns'])

    def heading(self, tree, key):
        return str(tree.heading(key, 'text'))

    def rows(self, tree):
        out = []
        for iid in tree.get_children():
            tags = tree.item(iid, 'tags')
            out.append((list(tree.item(iid, 'values')), [tags] if isinstance(tags, str) else list(tags)))
        return out

    def progress(self, bar):
        return float(bar['value']), float(bar['maximum'])


root = tk.Tk()
root.geometry('1320x860+0+0')
app = W.RMSNoiseApp(root)
app.instrument_id.set('WS-1')
app.serial.set('S-1')
app.sync_asset()
root.update()
snaps = ws_state.collect(app, TkAdapter())
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'tests' / 'qt_ref' / 'wavesurfer_tk_state.json'
out.write_text(json.dumps(snaps, indent=1, sort_keys=True, ensure_ascii=False), encoding='utf-8')
print('wrote', out, len(snaps), 'snapshots')
root.destroy()
