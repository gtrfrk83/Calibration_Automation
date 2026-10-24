"""Object-tree / state dump of a bench verification window, the same shape for the Tk window and the Qt window (QT-G1a).  Not a test module.

    dump(kind, root, app)  ->  {'title', 'buttons', 'checks', 'modes', 'combos', 'headings', 'idle' / 'busy' states ...}

`kind` is 'tk' or 'qt'.  The Tk dump was made ONCE from the real Tk window (Python 3.12 / Tk 9 under Xvfb) with `python tests/qt_bench_dump.py --tk OUT.json` and is stored in
tests/golden_ui/qt_views_bench_widgets_tk.json; tests/test_qt_views_bench.py compares the Qt window against it.  What is compared: the title, every button / check box /
combo box with its text (or its drop-down values), its enabled state while idle and while a run is busy (the engine's own `_sync_buttons`), and the table headings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))

MODE_TEXTS = ('As Found', 'As Left')


def engines():
    """[(key, factory(root, demo) -> app)]: every window of this package, as the engine's tests build them (no instrument is touched)."""
    from unittest import mock

    def truevolt(model):
        def make(root, demo):
            import truevolt_verification as E
            return E.App(root, model, demo=demo, fast_demo=False)
        return make

    def dacq(model):
        def make(root, demo):
            import dacq_verification as E
            E.configure(model)
            return E.App(root, model, demo=demo, fast_demo=False)
        return make

    def k2000(root, demo):
        import keithley2000_verification as E
        return E.App(root, demo=demo, fast_demo=False)

    def f8808a(root, demo):
        import fluke8808a_verification as E
        E.configure()
        return E.App(root, '8808A', demo=demo)

    def a34401a(root, demo):
        import Agilent_34401A as E
        with mock.patch.object(E.App, 'refresh_ports', lambda s: None):
            return E.App(root, demo=demo)

    def f8846a(root, demo):
        import Fluke_8846A_Verification as E
        with mock.patch.object(E.App, 'refresh_ports', lambda s: None):
            return E.App(root, demo=demo)

    def a34410a(model):
        def make(root, demo):
            import agilent34410a_verification as E
            E.configure(model)
            return E.App(root, demo=demo, fast_demo=False)
        return make

    return [('truevolt_34470A', truevolt('34470A')), ('truevolt_34461A', truevolt('34461A')), ('dacq_34970A', dacq('34970A')), ('dacq_34972A', dacq('34972A')),
            ('k2000', k2000), ('f8808a', f8808a), ('a34401a', a34401a), ('f8846a', f8846a), ('a34410a_34410A', a34410a('34410A')), ('a34410a_34411A', a34410a('34411A'))]


# ---------------------------------------------------------------------------------------------------------------------------------------
def _walk_tk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk_tk(c)


def _tk_items(root):
    out = {'buttons': [], 'checks': [], 'modes': [], 'combos': []}
    for w in _walk_tk(root):
        cls = w.winfo_class()
        if cls in ('TButton', 'Button'):
            out['buttons'].append((str(w.cget('text')), w))
        elif cls in ('TCheckbutton', 'Checkbutton'):
            out['checks'].append((str(w.cget('text')), w))
        elif cls in ('TRadiobutton', 'Radiobutton'):
            out['modes'].append((str(w.cget('text')), w))
        elif cls == 'TCombobox':
            out['combos'].append((tuple(str(v) for v in w.cget('values')), w))
    return out


def _qt_items(root):
    from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton, QRadioButton, QAbstractButton
    out = {'buttons': [], 'checks': [], 'modes': [], 'combos': []}
    for w in root.findChildren(QAbstractButton):
        text = w.text()
        if isinstance(w, QCheckBox):
            out['checks'].append((text, w))
        elif text in MODE_TEXTS or isinstance(w, QRadioButton):
            out['modes'].append((text, w))
        elif isinstance(w, QPushButton):
            out['buttons'].append((text, w))
    for w in root.findChildren(QComboBox):
        out['combos'].append((tuple(w.itemText(i) for i in range(w.count())), w))
    return out


def _state(kind, w):
    if kind == 'tk':
        s = str(w.cget('state'))
        return 'disabled' if s == 'disabled' else ('readonly' if s == 'readonly' else 'normal')
    from PySide6.QtWidgets import QComboBox
    if not w.isEnabled():
        return 'disabled'
    return 'readonly' if isinstance(w, QComboBox) and not w.isEditable() else 'normal'


def _headings(kind, app):
    if kind == 'tk':
        t = app.tree
        return [str(t.heading(c, 'text')) for c in t['columns']]
    m = app.tree.source_model
    return [c.title for c in m.columns]


def dump(kind, root, app, update=None):
    """The window's widgets and their states idle / busy.  `update()` lets the toolkit process pending events (Tk: root.update())."""
    items = _tk_items if kind == 'tk' else _qt_items
    res = {'title': root.title() if kind == 'tk' else root.windowTitle(), 'headings': _headings(kind, app)}
    for busy in (False, True):
        app._busy = busy
        app._sync_buttons()
        if update:
            update()
        key = 'busy' if busy else 'idle'
        got = items(root)
        for group, rows in got.items():
            res.setdefault(group, {})[key] = sorted([[name if isinstance(name, str) else list(name), _state(kind, w)] for name, w in rows], key=lambda r: json.dumps(r[0]))
    app._busy = False
    app._sync_buttons()
    return res


def main_tk(out_path):
    """Run under the real Tk (xvfb-run python3.12 tests/qt_bench_dump.py --tk out.json)."""
    import tkinter as tk
    import tkinter.messagebox as mb
    import ui_port
    ui_port.select_toolkit('tk')
    mb.showinfo = mb.showwarning = mb.showerror = lambda *a, **k: None
    res = {}
    for key, make in engines():
        for demo in (True, False):
            root = tk.Tk()
            root.geometry('1320x840+0+0')
            app = make(root, demo)
            root.update()
            res[f'{key}|{"demo" if demo else "hardware"}'] = dump('tk', root, app, update=root.update)
            root.destroy()
    Path(out_path).write_text(json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    print('wrote', out_path, len(res), 'windows')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--tk':
        main_tk(sys.argv[2])
    else:
        print(__doc__)
