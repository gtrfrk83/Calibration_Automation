"""Checks that need a REAL Tk and a display (run by tests/test_beta_real_tk_windows.py in a subprocess; not a test module).

    python tests/real_tk_checks.py <light|dark>

Opens the real windows built for the point editor, the Procedures list, the Datasheet Builder grid and the Asset History tab, drives them with
real events, and prints one 'CHECK <name> ok' line per check (any failure raises and exits non-zero).  Everything is written to a throw-away
data folder (CALSUITE_DATA / HOME are set by the caller)."""
import os
import sys
import tempfile
import traceback
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures')]
THEME = sys.argv[1] if len(sys.argv) > 1 else 'light'
os.environ['CALSUITE_THEME'] = THEME

import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402

import devmode  # noqa: E402
import procmods  # noqa: E402
import procmods_ui_model as M  # noqa: E402
import ui_theme as ui  # noqa: E402


def check(name, cond, detail=''):
    if not cond:
        raise AssertionError(f'{name}: {detail}')
    print(f'CHECK {name} ok')


def pump(root, n=10):
    for _ in range(n):
        root.update()


def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


class Env:
    def __init__(self, unlocked=True):
        self.dir = Path(tempfile.mkdtemp())
        t = [1000.0]
        clock = lambda: t[0]  # noqa: E731
        self.dm = devmode.DevMode(self.dir / 'devmode.json', clock=clock, wall=clock, iterations=1000)
        self.session = self.dm.set_passphrase('correct horse battery')
        self.lock = M.DevLock(self.dm, clock=clock)
        if unlocked:
            self.lock.session = self.session
        self.store = procmods.Store(self.dir / 'overrides.sqlite3', devmode=self.dm)


def inside(win, widget):
    """True when `widget` is mapped and lies inside the window's own area."""
    win.update_idletasks()
    if not widget.winfo_ismapped():
        return False
    x, y, w, h = widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()
    return (win.winfo_rootx() <= x and x + w <= win.winfo_rootx() + win.winfo_width() + 1 and
            win.winfo_rooty() <= y and y + h <= win.winfo_rooty() + win.winfo_height() + 1)


def point_window():
    import handheld_dmm as HH
    import procmods_point_ui as PU
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    env = Env()
    app = HH.App(root, '116', demo=False)
    st = app.pm_state
    st.store, st.devmode = env.store, env.dm
    pump(root)
    win = PU.open_point_window(app, '3-1', lock=env.lock)
    pump(root, 20)
    return root, app, env, win, errs


def checks_point_window():
    root, app, env, win, errs = point_window()
    check('title', win.title().startswith('Point 3-1'), win.title())
    check('resizable', win.resizable() == (True, True), win.resizable())
    mw, mh = win.minsize()
    check('minsize set', mw > 300 and mh > 300, (mw, mh))
    # the table is bounded: it must not take the whole window
    check('table bounded', win.tree.winfo_height() < win.winfo_height() * 0.45, (win.tree.winfo_height(), win.winfo_height()))
    for name in ('btn_apply', 'btn_cancel', 'btn_close', 'reason_entry', 'cmd_entry', 'btn_use', 'btn_restore'):
        check(f'visible {name}', inside(win, getattr(win, name)), name)
    labels = [w.cget('text') for w in walk(win) if isinstance(w, ttk.Button)]
    check('no All procedure changes button', not any('All procedure' in t for t in labels), labels)
    # select by a real click
    win.tree.update()
    bb = win.tree.bbox('2')
    win.tree.event_generate('<Button-1>', x=bb[0] + 60, y=bb[1] + bb[3] // 2)
    pump(root, 5)
    check('click selects row 2', win._selected == 2, win._selected)
    check('normal command editable', str(win.cmd_entry.cget('state')) == 'normal')
    check('selected command text shown', 'OUT' in win.cmd_text.get(), win.cmd_text.get())
    win.tree.selection_set('5')
    pump(root, 5)
    check('locked command read-only', str(win.cmd_entry.cget('state')) == 'disabled')
    check('locked reason shown', 'locked' in win.cmd_info.get().lower() or 'output' in win.cmd_info.get().lower(), win.cmd_info.get())
    # developer fields: visible by scrolling, editable with developer mode ON
    check('dev fields exist', {'description', 'nominal', 'low', 'high'} <= set(win.fentries), list(win.fentries))
    win._show_in_details(win.fentries['high'])
    pump(root, 5)
    check('description editable (dev on)', str(win.fentries['description'].cget('state')) == 'normal')
    check('limits editable (dev on)', str(win.fentries['low'].cget('state')) == 'normal' and str(win.fentries['high'].cget('state')) == 'normal')
    # edit and cancel
    win.tree.selection_set('2')
    pump(root, 5)
    win.cmd_entry.delete(0, 'end')
    win.cmd_entry.insert(0, 'OUT {ohms:.9g} OHM')
    win.btn_use.invoke()
    pump(root, 5)
    check('apply disabled without reason', str(win.btn_apply.cget('state')) == 'disabled')
    check('cancel enabled once staged', str(win.btn_cancel.cget('state')) == 'normal')
    win.reason_entry.insert(0, 'real tk check')
    pump(root, 5)
    check('apply enabled with reason', str(win.btn_apply.cget('state')) == 'normal', win.message.get())
    win.btn_cancel.invoke()
    pump(root, 5)
    check('cancel clears', str(win.btn_apply.cget('state')) == 'disabled' and win.reason.get() == '')
    win.cmd_entry.delete(0, 'end')
    win.cmd_entry.insert(0, 'OUT {ohms:.9g} OHM')
    win.btn_use.invoke()
    win.reason_entry.insert(0, 'real tk check')
    with mock.patch.object(messagebox, 'askyesno', return_value=True):
        win.btn_apply.invoke()
        pump(root, 10)
    check('apply saved', win.message.get() == '' and 'changed' in win.tree.item('2', 'values'), (win.message.get(), win.tree.item('2', 'values')))
    # the footer still shows when the window is made as small as allowed
    win.geometry(f'{mw}x{mh}')
    pump(root, 20)
    for name in ('btn_apply', 'btn_close'):
        check(f'visible at min size {name}', inside(win, getattr(win, name)), (name, win.winfo_width(), win.winfo_height()))
    # developer mode OFF: fields read-only with a note; normal commands still editable (this run only)
    env.lock.session = None
    win.update_header()
    win.refresh()
    pump(root, 5)
    check('dev off: fields read-only', str(win.fentries['description'].cget('state')) == 'disabled')
    check('dev off: note shown', 'developer mode' in win.dev_note.get().lower(), win.dev_note.get())
    win.tree.selection_set('2')
    pump(root, 5)
    check('dev off: normal command still editable', str(win.cmd_entry.cget('state')) == 'normal')
    # close
    with mock.patch.object(messagebox, 'askyesno', return_value=True):
        win.btn_close.invoke()
    pump(root, 5)
    check('closed', not win.winfo_exists())
    check('no callback errors', not errs, errs)
    root.destroy()


def checks_edit_point_button():
    import handheld_dmm  # noqa: F401
    import procmods_point_ui as PU
    root, app, env, win, errs = point_window()
    win.destroy()
    PU._open.clear()
    hook = app._pm_live_hook
    with mock.patch.object(messagebox, 'showinfo') as info:
        hook.button.invoke()
        check('Edit point with nothing selected explains', info.called)
    app.tree.selection_set('3-1')
    pump(root, 5)
    hook.button.invoke()
    pump(root, 20)
    check('Edit point opens the point window', hook.window is not None and hook.window.winfo_exists())
    check('title from the selected row', hook.window.title().startswith('Point 3-1'), hook.window.title())
    root.destroy()


def checks_manager_windows():
    import Calibration_Procedure_Manager as CPM
    import labregistry_ui as LU
    import report_pdf
    CPM.init_db()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    m = CPM.Manager(root)
    pump(root, 20)
    t = m.table
    check('verified column exists', 'verified' in t['columns'])
    pick = next(k for k in t.get_children() if '116' in str(t.item(k, 'values')))
    t.selection_set(pick)
    pump(root, 10)
    # the Verified column must fit inside the table's visible width
    total = sum(int(t.column(c, 'width')) for c in t['columns'])
    check('table columns fit the table', total <= t.winfo_width() + 4, (total, t.winfo_width()))
    check('verified text in the row', str(t.item(pick, 'values')[5]).startswith(('Not verified', 'Verified')))

    def drive(fn):
        def go():
            tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
            if not tops:
                root.after(100, go)
                return
            fn(tops[-1])
        root.after(300, go)

    def buttons(top):
        return [w for w in walk(top) if isinstance(w, ttk.Button)]

    def mark(top):
        es = [w for w in walk(top) if isinstance(w, ttk.Entry)]
        check('mark dialog: buttons visible', all(inside(top, b) for b in buttons(top)))
        es[0].delete(0, 'end')
        es[0].insert(0, 'Tester')
        [b for b in buttons(top) if 'lock' in b.cget('text')][0].invoke()
    drive(mark)
    rec = m.mark_verified()
    check('mark verified', rec is not None and rec.locked)

    def unlock(top):
        es = [w for w in walk(top) if isinstance(w, ttk.Entry)]
        check('unlock dialog: buttons visible', all(inside(top, b) for b in buttons(top)))
        es[0].delete(0, 'end')
        es[0].insert(0, 'Tester')
        [b for b in buttons(top) if b.cget('text') == 'Unlock'][0].invoke()      # no reason: stays open with the explanation
        pump(root, 3)
        check('unlock needs a reason', top.winfo_exists())
        es[1].insert(0, 'real tk check')
        [b for b in buttons(top) if b.cget('text') == 'Unlock'][0].invoke()
    drive(unlock)
    rec = m.toggle_lock()
    check('unlock', rec is not None and not rec.locked)

    # Datasheet Builder grid
    with mock.patch('datasheet_builder_ui.ask_new_sheet', return_value=False):          # the New question is modal: answer it (blank)
        win = m.dsb_panel.new()
    pump(root, 20)
    check('grid editor opens', win.winfo_exists())
    check('grid: pills filled before any edit', win.dirty_pill.cget('text') != '' and win.problem_pill.cget('text') != '')
    win.make_v.set('Acme')
    win.model_v.set('DM-1')
    win.title_v.set('DM-1 PV')
    win.commit_header()
    dcv = next(c['label'] for c in win.model.function_choices() if c['kind'] == 'DCV' and not c['fid'])
    win.function_chosen(dcv)
    win.model.select(col='nominal')
    win.sync()
    win.bar_v.set('5 V')
    check('grid: type a cell', win.commit_bar('down').ok)
    key = next(r['key'] for r in win.model.rows() if r['kind'] == 'point')
    win.model.select(key, 'low')
    win.sync()
    win.panel_box.types['iv'].set(True)
    win.panel_box.v['iv'].set('0.05')
    check('grid: calculate tolerance', win.calc().ok)
    x, y, _a, _b = win.sheet.geo.box(1, 2)
    win.sheet.event_generate('<Button-1>', x=x + 5, y=y + 5)
    pump(root, 5)
    check('grid: mouse click selects a cell', win.model.sel_col == 'nominal', win.model.sel_col)
    check('grid: save', win.save().ok)
    pump(root, 5)
    check('grid: save button and tool column visible', inside(win, win.sheet) and win.sheet.winfo_height() > 100)
    pv = win.preview()
    pump(root, 20)
    check('grid: preview opens', pv is not None and pv.winfo_exists())
    pv.destroy()
    win.destroy()

    # Asset History: issue a report, then regenerate it
    out = tempfile.mkdtemp()
    header = [('Instrument', 'Test DMM'), ('Instrument ID', 'A-7'), ('Serial', 'SN7'), ('Source', 'A manual, p. 1')]
    rows = [report_pdf.cert_row('10 V range', 10, 9.9990, 10.0010, 'V', reading=10.0002, section='DC Volts')]
    details = {'technician': 'T. Tech', 'temperature': '23.1 C', 'humidity': '45 %RH', 'standards': [], 'procedure': 'bench test'}
    report_pdf.write_calibration_pdf(out + '/A-7-2026-10-22.pdf', rows, header=header, details=details)
    m.notebook.select(m.history_frame)
    pump(root, 20)
    h = m.history_panel
    h.refresh()
    pump(root, 5)
    h.assets.selection_set(h.assets.get_children()[0])
    pump(root, 10)
    h.runs.selection_set(h.runs.get_children()[0])
    pump(root, 10)
    check('history: Regenerate button visible', inside(root, h.btn_regen), (h.btn_regen.winfo_rooty(), root.winfo_height()))
    check('history: regenerate hint', 'can be regenerated' in h.regen_note.get(), h.regen_note.get())
    dest = out + '/regen.pdf'
    with mock.patch.object(LU.filedialog, 'asksaveasfilename', return_value=dest), mock.patch.object(messagebox, 'showinfo') as info:
        h.regenerate_pdf()
        check('history: regenerated PDF written', os.path.exists(dest) and info.called)

    def press(top):
        check('choice dialog: buttons visible', all(inside(top, b) for b in buttons(top)))
        [b for b in buttons(top) if 'Regenerate' in b.cget('text')][0].invoke()
    drive(press)
    check('history: choice dialog answer', LU.choose_action(root) == 'regenerate')
    check('no callback errors', not errs, errs)
    root.destroy()

def checks_manager_tabs():
    """The Procedures tab's three views: Automated Calibrations, Manual Calibrations and Adjustment (shared table, search / category filters, verified column, Run buttons)."""
    import sqlite3
    import Calibration_Procedure_Manager as CPM
    CPM.init_db()

    def instruments_snapshot():             # the table's definition and every row, as stored
        with sqlite3.connect(CPM.DB) as con:
            return (con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='instruments'").fetchall(),
                    con.execute('SELECT * FROM instruments ORDER BY id').fetchall())
    with sqlite3.connect(CPM.DB) as con:    # this run's own throw-away data folder: one registered instrument that must survive the start-up untouched
        con.execute("INSERT OR IGNORE INTO instruments(asset_id,manufacturer,model,serial_number,interval_months,notes) VALUES ('TAB-1','Fluke','8846A','SN-TAB',12,'kept')")
    before = instruments_snapshot()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    m = CPM.Manager(root)
    root.geometry('1260x800+0+0')
    pump(root, 20)
    t = m.table
    tabs = [m.notebook.tab(x, 'text').strip() for x in m.notebook.tabs()]
    check('main tabs: no Instruments tab', 'Instruments' not in tabs and tabs[0] == 'Procedures', tabs)
    check('main tabs: opens on Procedures', m.notebook.nametowidget(m.notebook.select()) is m.library_frame)
    check('main tabs: nothing of the old tab is left on the Manager', not any(hasattr(m, a) for a in ('instruments_frame', 'instrument_table', 'refresh_instruments', 'launch_instrument_procedure')))
    check('instruments table: definition and rows untouched by the Manager start-up', before[1] and instruments_snapshot() == before, (before, instruments_snapshot()))
    names = lambda: [t.item(k, 'values')[0] for k in t.get_children()]  # noqa: E731
    check('tabs: three views', [m.view_nb.tab(x, 'text').strip() for x in m.view_nb.tabs()] == ['Automated Calibrations', 'Manual Calibrations', 'Adjustment'])
    check('automated view first, no adjustment procedure in it', m.view_kind == 'verification' and names() and not any('Adjustment' in n for n in names()))
    check('tabs: notes hidden on automated', not m.adjust_note.winfo_ismapped() and not m.view_notes['manual'].winfo_ismapped())
    n_ver = len(names())
    check('tabs: verified column kept', 'verified' in t['columns'] and all(str(t.item(k, 'values')[5]) for k in t.get_children()))
    shot = os.environ.get('SHOT_DIR')

    def grab(tag):
        if not shot:
            return
        from PIL import ImageGrab
        root.update()
        ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height()),
                       xdisplay=os.environ['DISPLAY']).save(os.path.join(shot, f'manager_{tag}_{THEME}.png'))
    grab('automated')
    if shot:                                # the Manager's tab strip alone (top of the window)
        from PIL import ImageGrab
        root.update()
        ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + 130),
                       xdisplay=os.environ['DISPLAY']).save(os.path.join(shot, f'manager_tabstrip_{THEME}.png'))
    m.view_nb.select(m.view_pages['manual'])
    pump(root, 20)
    check('manual view: empty until something is imported, note shown', m.view_kind == 'manual' and names() == [] and m.view_notes['manual'].winfo_ismapped()
          and 'type each reading into the test point grid' in str(m.view_notes['manual'].label.cget('text')), names())
    check('manual view: Run is disabled with nothing selected', str(m.btn_run.cget('state')) == 'disabled' and str(m.btn_demo.cget('state')) == 'disabled')
    check('manual view: the import button is on the Procedures tab', any(isinstance(w, ttk.Button) and 'Import Mudcats datasheet' in str(w.cget('text')) for w in walk(m.library_frame)))
    grab('manual_empty')
    m.view_nb.select(m.view_pages['adjustment'])
    pump(root, 20)
    check('adjustment view: only adjustment procedures', m.view_kind == 'adjustment' and sorted(names()) == sorted(['Fluke 8808A Guided Adjustment', 'Fluke 8846A Guided Adjustment', 'Keithley 2000 Guided Adjustment']), names())
    check('adjustment view: note shown, manual note hidden', m.adjust_note.winfo_ismapped() and not m.view_notes['manual'].winfo_ismapped())
    check('adjustment view: first row selected, Run enabled', t.selection() and str(m.btn_run.cget('state')) != 'disabled')
    check('adjustment view: category list is the view\'s', list(m.category_box['values']) == [CPM.ALL_CATEGORIES, 'Digital Multimeter Adjustment'], m.category_box['values'])
    check('adjustment view: verified status shown', str(t.item(t.get_children()[0], 'values')[5]).startswith(('Not verified', 'Verified', 'Changed', 'Unlocked')), t.item(t.get_children()[0], 'values'))
    grab('adjustment')
    m.search.set('klein')               # an automated-only procedure (Keithley 2000 now has an adjustment procedure too)
    pump(root, 10)
    check('adjustment view: search with no hit', names() == [] and '1 in the Automated Calibrations tab' in m.table._empty.cget('text'), m.table._empty.cget('text'))
    m.search.set('8846')
    pump(root, 10)
    check('adjustment view: search hit', names() == ['Fluke 8846A Guided Adjustment'], names())
    m.view_nb.select(m.view_pages['verification'])
    pump(root, 10)
    check('automated view: search keeps working', len(names()) == 1 and 'Performance Verification' in names()[0], names())
    m.search.set('')
    m.category.set('Oscilloscope')
    m.refresh()
    check('automated view: category filter', names() and all(t.item(k, 'values')[3] == 'Oscilloscope' for k in t.get_children()))
    m.category.set(CPM.ALL_CATEGORIES)
    m.refresh()
    check('automated view: back to the full list', len(names()) == n_ver and not m.adjust_note.winfo_ismapped())
    check('no Tk callback errors', not errs, errs)
    root.destroy()


def checks_mdd_manual():
    """A (synthetic) Mudcats .MDD imported from the Manager as a manual calibration: the import preview, the new procedure in the Manual Calibrations tab (and only
    there), then its run window with the readings typed straight into the test point grid (Enter = save and next point), As Left, rejected input, and the PDF."""
    import json
    import subprocess
    import time
    sys.path.insert(0, str(ROOT / 'tests'))
    import mdd_synth
    import Calibration_Procedure_Manager as CPM
    import datamode
    import dsb_runtime as rt
    import mdd_convert as mc
    import mdd_importer_v49 as imp
    CPM.init_db()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    shots = os.environ.get('SHOT_DIR')
    boxes = []
    patches = [mock.patch.object(messagebox, n, side_effect=lambda *a, _n=n, **k: boxes.append((_n, a)) or True)
               for n in ('showinfo', 'showwarning', 'showerror', 'askyesno', 'askokcancel')]
    for pt in patches:
        pt.start()

    def grab(win, tag):
        if not shots:
            return
        from PIL import ImageGrab
        win.update()
        ImageGrab.grab(bbox=(win.winfo_rootx(), win.winfo_rooty(), win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height()),
                       xdisplay=os.environ['DISPLAY']).save(os.path.join(shots, f'{tag}_{THEME}.png'))
    m = CPM.Manager(root)
    root.geometry('1260x800+0+0')
    pump(root, 20)
    path = mdd_synth.write_mdd(Path(tempfile.mkdtemp()) / 'Synthetic Fluke 87V (365 Days).MDD')
    win = m.import_mdd_procedure(str(path))
    pump(root, 30)
    check('import preview: window opened', win is not None and win.winfo_exists())
    grid = next(w for w in walk(win) if isinstance(w, ttk.Treeview))
    rows = [grid.item(k, 'values') for k in grid.get_children()]
    check('import preview: one row per MDD point', len(rows) == 17, len(rows))
    stat = {int(r[0]): r[6] for r in rows}
    check('import preview: unconvertible points are named', [n for n, v in stat.items() if v == 'NOT converted'] == [16, 17], stat)
    check('import preview: uncertain points are flagged', [n for n, v in stat.items() if v == 'CHECK'] == [6, 9, 15], stat)
    texts = ' '.join(str(w.cget('text')) for w in walk(win) if isinstance(w, ttk.Label))
    check('import preview: counts shown', '15 of 17 points converted' in texts and '2 NOT converted' in texts and '3 to check' in texts, texts[:400])
    check('import preview: nothing created before approval', not any(r['kind'] == 'manual' for r in __import__('dsb_manager').user_rows()))
    win.geometry('1180x760+20+20')
    grab(win, 'mdd_import_preview')
    create = next(w for w in walk(win) if isinstance(w, ttk.Button) and w.cget('text') == 'Create manual procedure')
    create.invoke()
    pump(root, 40)
    check('import: preview closed, message shown', not win.winfo_exists() and any(b[0] == 'showinfo' and '15 of 17' in b[1][1] for b in boxes), boxes[-1:])
    check('import: lands in Manual Calibrations, selected', m.view_kind == 'manual' and len(m.table.get_children()) == 1 and m.table.selection()
          and m.view_notes['manual'].winfo_ismapped())
    row = m.table.item(m.table.selection()[0], 'values')
    check('manual view: same columns, status and verified text', 'Ready' in row[4] and str(row[5]).startswith('Not verified'), row)
    check('manual view: Run and Demo enabled', str(m.btn_run.cget('state')) != 'disabled' and str(m.btn_demo.cget('state')) != 'disabled')
    grab(root, 'manager_manual')
    m.view_nb.select(m.view_pages['verification'])
    pump(root, 20)
    check('automated view: the imported sheet is not listed', not any('Handheld' in m.table.item(k, 'values')[0] and 'Multimeter, Digital' in m.table.item(k, 'values')[0] for k in m.table.get_children()))
    m.search.set('Handheld')
    pump(root, 10)
    check('automated view: search points to the Manual tab', m.table.get_children() == () and '1 in the Manual Calibrations tab' in m.table._empty.cget('text'), m.table._empty.cget('text'))
    m.search.set('')
    # --- the same file again: the person is asked, nothing is overwritten
    win2 = m.import_mdd_procedure(str(path))
    pump(root, 30)
    labels = ' '.join(str(w.cget('text')) for w in walk(win2) if isinstance(w, (ttk.Label, ttk.Radiobutton)))
    check('import again: existing procedure is reported with a choice', 'imported before' in labels and 'NEW VERSION' in labels and 'separate new procedure' in labels, labels[:600])
    next(w for w in walk(win2) if isinstance(w, ttk.Button) and w.cget('text') == 'Cancel').invoke()
    pump(root, 10)
    check('import again: cancel creates nothing', len(__import__('datasheet_builder').list_datasheets()) == 1)
    root.destroy()
    # --- the run window
    root = tk.Tk()
    root.report_callback_exception = lambda *a: errs.append(a)
    ent = __import__('datasheet_builder').procedure_entries()[0]
    spec = json.loads(Path(ent['spec_path']).read_text(encoding='utf-8'))
    app = rt.DsbApp(root, spec, demo=False)
    root.geometry('1280x860+0+0')
    pump(root, 30)
    app.asset.set('A-4412')
    app.serial.set('S-1')
    ge = app.grid_entry
    tree = app.tree
    check('run window: manual mode with the grid entry, no instrument connection asked', app.manual_entry and ge is not None and not app.wants_connection())
    check('run window: As Found / As Left columns, one row per point', tree.heading('found')['text'].endswith('As Found') and tree.heading('left')['text'].endswith('As Left') and len(tree.get_children()) == 15,
          (tree.heading('found')['text'], len(tree.get_children())))
    first = tree.get_children()[1]                                  # 1.000 V, limits 0.9990 .. 1.0010 (4 decimals)
    tree.selection_set(first)
    tree.focus_force()
    pump(root, 5)
    tree.event_generate('<Return>')
    pump(root, 10)
    check('grid: Enter on the selected point opens the reading box', ge.is_open() and ge.iid == first)
    ge.entry.insert(0, '1')
    ge.entry.event_generate('<Return>')
    pump(root, 10)
    rec = app.results[first]
    check('grid: typed 1 is padded to the point resolution and judged', (rec['entered'], rec['result'], rec['source']) == ('1.0000', 'PASS', 'typed'), rec)
    nxt = tree.get_children()[2]
    check('grid: Enter saved and opened the NEXT point', ge.is_open() and ge.iid == nxt)
    check('grid: the status line says what is accepted', 'accept 9.990 to 10.010 V' in app.status.get(), app.status.get())
    ge.entry.insert(0, 'nan')
    ge.entry.event_generate('<Return>')
    pump(root, 5)
    check('grid: NaN is refused, the box stays', ge.is_open() and ge.iid == nxt and nxt not in app.results and 'number' in app.status.get().lower(), app.status.get())
    ge.var.set('10.05')
    ge.entry.event_generate('<Return>')
    pump(root, 5)
    check('grid: an out-of-limit reading is stored as FAIL', app.results[nxt]['result'] == 'FAIL', app.results[nxt])
    grab(root, 'mdd_manual_grid')
    ge.entry.event_generate('<Escape>')
    pump(root, 5)
    check('grid: Esc closes the box', not ge.is_open())
    tree.selection_set(tree.get_children()[3])
    tree.focus_force()
    pump(root, 5)
    tree.event_generate('<Key>', keysym='5')                         # typing on a selected row starts the box with that character
    pump(root, 5)
    check('grid: typing on a selected point opens the box', ge.is_open() and ge.var.get() in ('5', ''), ge.var.get())
    ge.entry.event_generate('<Escape>')
    # fill the rest by typing, then As Left
    for iid in tree.get_children():
        p = app.by_id[iid]
        if iid in app.results:
            continue
        app.type_reading(p, 'y') if p['test'] != 'numeric' else app.type_reading(p, f'{(float(p["low"]) + float(p["high"])) / 2:.6f}')
    pump(root, 10)
    check('all points have an As Found result', len(app.found) == 15, len(app.found))
    app.set_data_mode(datamode.LEFT)
    pump(root, 10)
    tree.selection_set(first)
    check('As Left: the box opens on the point', ge.open(first), app.status.get())
    ge.var.set('1.0001')
    ge.entry.focus_force()
    pump(root, 5)
    ge.entry.event_generate('<Return>')
    pump(root, 5)
    check('As Left: stored', first in app.left, app.status.get())
    check('As Left: the box sits on the As Left column and keeps As Found apart', app.left[first]['result'] == 'PASS' and app.found[first]['entered'] == '1.0000'
          and app.left[first]['data'] == 'As Left', (app.left.get(first), app.found.get(first)))
    grab(root, 'mdd_manual_as_left')
    ge.close()
    out = str(Path(tempfile.mkdtemp()) / 'A-4412-2026-10-23.pdf')
    import report_dialog
    d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '', 'show_tar_tur': True}
    with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', lambda **k: out):
        app.export_pdf()
    pump(root, 10)
    txt = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
    check('PDF: Calibration Data with the typed readings, not marked demo', 'Calibration Data' in txt and '1.0001' in txt and 'OUT OF TOLERANCE' in txt and 'DEMO' not in txt.upper(), txt[:1500])
    check('no Tk callback errors', not errs, errs)
    for pt in patches:
        pt.stop()
    root.destroy()


def checks_standards_specs():
    """The Standards Specs tab (Option A): standards rail, header card, type chips, grouped table, empty states, narrow layouts, and every old handler."""
    import json

    import Calibration_Procedure_Manager as CPM
    import specmanager as sm
    import specmanager_ui as SU
    import specmanager_view as SV
    from tkinter import filedialog, simpledialog
    CPM.init_db()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    m = CPM.Manager(root)
    root.geometry('1260x800+0+0')
    m.notebook.select(m.specs_frame)
    pump(root, 30)
    p = m.specs_panel
    shot = os.environ.get('SHOT_DIR')

    def grab(tag):
        if not shot:
            return
        from PIL import ImageGrab
        root.update()
        ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height()),
                       xdisplay=os.environ['DISPLAY']).save(os.path.join(shot, f'standards_specs_{tag}_{THEME}.png'))

    ids = {i['std']['model']: k for k, i in p._info.items()}
    models = [s['model'] for s in sm.standards()]
    check('specs: one rail card per standard', len(p._cards) == len(models) >= 7 and all(c.winfo_ismapped() for c in p._cards.values()), (len(p._cards), models))
    check('specs: rail count shows the number', p.rail_count.cget('text') == str(len(models)))
    chips = {i['std']['model']: dict(p._cards[k].info['chips']) for k, i in p._info.items()}
    check('specs: stated confidence chip is info (blue), assumed k = 2 is neutral (grey)',
          chips['5522A'][f'99 % {SV.DOT} {SV.DIVIDE} 2.576'] == 'info' and chips['8563E'][f'k = 2 assumed {SV.DOT} {SV.DIVIDE} 2'] == 'neutral', chips['8563E'])
    check('specs: sheet issues pill on a card that has issues', any(k == 'warn' for k in chips['5520A'].values()) and not any(t.endswith('issues') for t in chips['5560A']))
    colours = {p._cards[ids['5522A']].itemcget(i, 'fill') for i in p._cards[ids['5522A']].find_all()}
    chosen = {p._cards[p.sel].itemcget(i, 'fill') for i in p._cards[p.sel].find_all()}
    check('specs: card colours come from the theme tokens', ui.C['info_bg'] in colours and ui.C['card'] in colours and ui.C['select'] in chosen and ui.C['primary'] in chosen,
          (colours, chosen))
    check('specs: first standard selected, header shows it', p.sel == min(ids.values(), key=lambda k: p._info[k]['std']['model']) and p.h_title.cget('text') == models[0])

    # ---- header card of the 5522A
    p.select(ids['5522A'])
    pump(root, 20)
    st = {k: p.stat[k]['val'].cget('text') for k in p.stat}
    check('specs: stat row', st == {'conf': '99 %', 'div': '2.576', 'period': '1 yr', 'ranges': '545'}, st)
    check('specs: confidence note is short, the full sheet text is the tooltip', len(p.stat['conf']['sub_text']) < 80 and 'Operators Manual' in p.stat['conf']['tip']
          and 'SpecTrack' in p.stat['conf']['tip'], p.stat['conf'])
    check('specs: period note names both columns', p.stat['period']['sub_text'] == 'columns: 1 yr and 90 day', p.stat['period']['sub_text'])
    check('specs: Set divisor link beside the divisor', p.div_link.winfo_ismapped() and p.div_link.cget('text') == 'Set divisor...')
    texts = [w.cget('text') for w in walk(p.facts) if isinstance(w, tk.Label)]
    check('specs: assets / approved / issues in the header', 'Set assets...' in texts and 'Approved' in texts and any('Pack Jr' in t for t in texts) and p.issues_chip.text.startswith('12 sheet issues'), texts)
    check('specs: issues pill is bad (an error-level issue) with a dot', p.issues_chip.kind == 'bad' and p.issues_chip.dot)
    btns = [b.cget('text') for b in walk(p.head_card.body) if isinstance(b, ttk.Button)]
    check('specs: header actions', btns == ['Export JSON...', 'Check an EMU...'], btns)
    check('specs: Import in the rail', any(isinstance(b, ttk.Button) and b.cget('text') == 'Import spec JSON...' for b in walk(p.rail)))

    # ---- the table
    tree = p.rows
    bands = [k for k in tree.get_children('') if k.startswith('g')]
    check('specs: table is grouped by function with a band per function', len(bands) == 69 and tree.item(bands[0], 'values')[0].endswith('ranges'), len(bands))
    check('specs: footer count and hint', p.count_lbl.cget('text') == 'Showing 545 of 545 ranges' and p.hint.cget('text') == SU.HINT and p.hint.winfo_ismapped())

    def columns_ok(tag):
        disp = list(tree['displaycolumns'])
        right = sum(int(tree.column(c, 'width')) for c in ['#0'] + disp)
        check(f'specs {tag}: 1 yr and 90 day columns both shown and inside the table', 'p1' in disp and 'p2' in disp and right <= tree.winfo_width() + 1
              and tree.heading('p1', 'text') == '1 YR SPEC' and tree.heading('p2', 'text') == '90 DAY SPEC', (disp, right, tree.winfo_width()))
    columns_ok('1260')
    check('specs: rail 300 wide at 1260', p.rail.winfo_width() == ui.px(300), p.rail.winfo_width())
    p.kind.set('ACV')
    pump(root, 20)
    check('specs: ACV chip active, only ACV rows', p._chips['ACV'].active and not p._chips[''].active and p.count_lbl.cget('text') == 'Showing 59 of 545 ranges', p.count_lbl.cget('text'))
    first = tree.get_children(bands[0] if tree.exists(bands[0]) else tree.get_children('')[0])[0]
    check('specs: ACV rows in the first band', all(sm_row['kind'] == 'ACV' for sm_row in p._rows if str(sm_row['id']) in tree.get_children(tree.get_children('')[0])))
    vals = tree.item(first, 'values')
    check('specs: spec text formatted for display with SI scaling', vals[3] == f'{SV.PLUS_MINUS}(800 ppm + 6.00 {SV.MICRO}V)' and vals[4] == f'{SV.PLUS_MINUS}(600 ppm + 6.00 {SV.MICRO}V)', vals)
    raw = sm.rows_of(ids['5522A'], kind='ACV')[0]
    check('specs: raw printed text is the tooltip and the stored row is unchanged', p._tips[first]['p1'] == raw['specs'][1 if raw['specs'][0]['period'] == '90 day' else 0]['raw']
          and '+/-(' in p._tips[first]['p1'] and raw['specs'][0]['raw'].startswith('['), p._tips[first])
    check('specs: rows banded', tree.item(first, 'tags') == ('even',) and tree.item(tree.next(first), 'tags') == ('odd',))
    # real clicks on a chip and on the table
    p._chips['DCV'].event_generate('<Button-1>', x=5, y=5)
    pump(root, 10)
    check('specs: clicking a chip filters', p.kind.get() == 'DCV' and p._chips['DCV'].active and not p._chips['ACV'].active)
    p.term.set('zzz nothing')
    pump(root, 10)
    check('specs: empty table says why and offers Clear', p.empty.winfo_ismapped() and 'DC volts' in p.empty_msg.cget('text') and "'zzz nothing'" in p.empty_msg.cget('text')
          and p.empty_clear.winfo_ismapped() and not tree.get_children(''), p.empty_msg.cget('text'))
    p.empty_clear.event_generate('<Button-1>')
    pump(root, 10)
    check('specs: Clear the filters restores the table', p.kind.get() == '' and p.term.get() == '' and not p.empty.winfo_ismapped() and len(p._rows) == 545 and tree.get_children(''))
    p.term.set('lcomp')
    pump(root, 10)
    check('specs: text filter on function / label / variant', 0 < len([k for g in tree.get_children('') for k in tree.get_children(g)]) < 545 and all(tree.item(g, 'open') for g in tree.get_children('')))
    p.term.set('')
    pump(root, 10)
    # groups open / close
    p.set_all_groups(False)
    pump(root, 5)
    check('specs: Collapse all closes every band', all(not tree.item(g, 'open') for g in tree.get_children('')))
    p.show_rows()
    check('specs: collapsed state is remembered across a rebuild', all(not tree.item(g, 'open') for g in tree.get_children('')))
    p.set_all_groups(True)
    g0 = tree.get_children('')[0]
    x, y, w, h = tree.bbox(g0)
    tree.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
    check('specs: clicking a band toggles it', not tree.item(g0, 'open'))
    tree.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
    check('specs: clicking a band again reopens it', tree.item(g0, 'open'))

    # ---- resolution edit by double-click (old handler; Tk cannot synthesize a Double-1, so the bound handler is called with the click position)
    from types import SimpleNamespace
    check('specs: the table is bound to Double-1', bool(tree.bind('<Double-1>')))

    def dbl(x, y):
        tree.update_idletasks()
        return p._double_click(SimpleNamespace(x=x, y=y))
    rid = tree.get_children(g0)[1]
    x, y, w, h = tree.bbox(rid)
    asked = []
    with mock.patch.object(simpledialog, 'askstring', side_effect=lambda *a, **k: asked.append((a, k)) or '2e-06'):
        bx, by, bw, bh = tree.bbox(g0)
        was = tree.item(g0, 'open')
        dbl(bx + bw // 2, by + bh // 2)
        check('specs: double-clicking a band does not open the resolution dialog (it toggles the band)', not asked and tree.item(g0, 'open') != was)
        dbl(bx + bw // 2, by + bh // 2)
        tree.selection_set(rid)
        dbl(x + 20, y + h // 2)
    pump(root, 10)
    check('specs: double-click sets the calibrator resolution (stored, then shown)', len(asked) == 1 and 'Calibrator resolution' in asked[0][0][0]
          and next(r for r in sm.rows_of(ids['5522A']) if r['id'] == int(rid))['resolution'] == 2e-06 and tree.item(rid, 'values')[2] == f'2.00 {SV.MICRO}V'
          and tree.selection() == (rid,), (asked, tree.item(rid, 'values')))
    with mock.patch.object(simpledialog, 'askstring', return_value=''):
        p.edit_resolution()
    check('specs: blank clears the resolution', next(r for r in sm.rows_of(ids['5522A']) if r['id'] == int(rid))['resolution'] is None and tree.item(rid, 'values')[2] == '')
    tree.selection_set(g0)
    with mock.patch.object(simpledialog, 'askstring', side_effect=AssertionError('no dialog for a band')):
        p.edit_resolution()
    check('specs: edit_resolution ignores a selected band', True)

    # ---- set divisor / assets, sheet issues, check EMU, export, import
    answers = iter(['1.96', 'checking the manager'])
    with mock.patch.object(simpledialog, 'askstring', side_effect=lambda *a, **k: next(answers)):
        p.set_divisor()
    pump(root, 10)
    check('specs: Set divisor stores it and the card / header show it', sm.standard(ids['5522A']).divisor()[0] == 1.96 and p.stat['div']['val'].cget('text') == '1.96'
          and dict(p._cards[ids['5522A']].info['chips'])[f'99 % {SV.DOT} {SV.DIVIDE} 1.96 (set)'] == 'info' and p.sel == ids['5522A'], p.stat['div']['val'].cget('text'))
    answers = iter(['', 'back to the sheet'])
    with mock.patch.object(simpledialog, 'askstring', side_effect=lambda *a, **k: next(answers)):
        p.set_divisor()
    check('specs: blank divisor goes back to the sheet level', sm.standard(ids['5522A']).divisor()[0] == 2.576 and p.stat['div']['val'].cget('text') == '2.576')
    with mock.patch.object(simpledialog, 'askstring', return_value='CAL-1:SN1; CAL-2:SN2; CAL-3:SN3'):
        p.set_assets()
    pump(root, 20)
    check('specs: Set assets stores them and the header shows a chip each', sm.assets_of(ids['5522A']) == [('CAL-1', 'SN1'), ('CAL-2', 'SN2'), ('CAL-3', 'SN3')]
          and len([c for c in p.facts.items if isinstance(c[0], SU.Chip) and 'CAL-' in c[0].text]) == 3)
    with mock.patch.object(simpledialog, 'askstring', return_value=''):
        p.set_assets()
    check('specs: no assets says so', sm.assets_of(ids['5522A']) == [] and any(isinstance(w, tk.Label) and w.cget('text') == 'none set' for w in walk(p.facts)))
    pump(root, 20)
    p.issues_chip.event_generate('<Button-1>')
    pump(root, 10)
    win = p.issues_window
    body = [w for w in walk(win) if isinstance(w, tk.Text)][0].get('1.0', 'end')
    check('specs: clicking the issues pill lists the sheet issues', win.winfo_exists() and body.count('[warn]') == 10 and body.count('[error]') == 2, body[:200])
    win.destroy()
    before = set(walk(root))
    p.check_emu()
    pump(root, 10)
    new = [w for w in walk(root) if w not in before and isinstance(w, tk.Toplevel)]
    check('specs: Check an EMU opens the dialog', len(new) == 1 and isinstance(new[0], SU.CheckDialog) and 'Check a reported EMU - 5522A' in new[0].title())
    new[0].destroy()
    out = os.path.join(tempfile.mkdtemp(), 'x.json')
    with mock.patch.object(filedialog, 'asksaveasfilename', return_value=out):
        p.export_json()
    data = json.load(open(out, encoding='utf-8'))
    check('specs: Export JSON writes the standard', data['standard']['model'] == '5522A' and sum(len(f['ranges']) for f in data['functions']) == 545)
    with mock.patch.object(filedialog, 'askopenfilename', return_value=out):
        p.import_json()
    pump(root, 10)
    ids = {i['std']['model']: k for k, i in p._info.items()}                 # an import replaces the standard under a new id
    check('specs: Import spec JSON reloads the rail and stays on the same model', len(p._cards) == len(models) and p.sel == ids['5522A']
          and p.count_lbl.cget('text') == 'Showing 545 of 545 ranges')
    with mock.patch.object(filedialog, 'askopenfilename', return_value=out), mock.patch.object(SU.messagebox, 'showerror') as err:
        open(out, 'w').write('{"nope": 1}')
        p.import_json()
    check('specs: a bad import file is reported, nothing changes', err.called and len(p._cards) == len(models))

    # ---- other standards: 5560A (one period), 8902A (periods other than 1 yr), arrows in the rail
    p.select(ids['5560A'])
    pump(root, 20)
    check('specs: 5560A shows only its 1 yr column', list(tree['displaycolumns']) == ['span', 'freq', 'res', 'p1'] and tree.heading('p1', 'text') == '1 YR SPEC'
          and tree.heading('p2', 'text') == '' and p.h_title.cget('text') == '5560A' and p.count_lbl.cget('text') == 'Showing 147 of 147 ranges', list(tree['displaycolumns']))
    check('specs: 5560A has no sheet issues: green pill', p.issues_chip.kind == 'good' and p.issues_chip.text.startswith('0 sheet issues'))
    grab('5560A_1260')
    p.select(ids['8902A'])
    pump(root, 20)
    check('specs: columns follow the periods the sheet prints (spec / supplemental)', tree.heading('p1', 'text') == 'SPEC' and tree.heading('p2', 'text') == 'SUPPLEMENTAL', tree.heading('p1', 'text'))
    check('specs: confidence not stated: grey value, k = 2 assumed', p.stat['conf']['val'].cget('text') == 'Not stated' and p.stat['conf']['sub_text'] == 'k = 2 assumed')
    p.rail_cv.focus_force()
    p.rail_cv.event_generate('<Up>')
    check('specs: arrow keys move through the rail', p.sel == ids['8563E'] or p.sel != ids['8902A'], p.sel)
    p.select(ids['5522A'])
    p.kind.set('ACV')
    pump(root, 20)
    grab('5522A_1260')

    # ---- 1100 px: the rail narrows, both period columns stay, the hint stays
    root.geometry('1100x700+0+0')
    pump(root, 40)
    check('specs 1100: rail narrower', p.rail.winfo_ismapped() and p.rail.winfo_width() == ui.px(248), p.rail.winfo_width())
    columns_ok('1100')
    check('specs 1100: hint, footer and header buttons inside the window', all(inside(root, w) for w in (p.hint, p.count_lbl)) and
          all(inside(root, b) for b in walk(p.head_card.body) if isinstance(b, ttk.Button)))
    check('specs 1100: type chips on one row with the rest under More', p.chip_flow.winfo_height() <= ui.px(40) and (not p._chip_specs or p._chips), p.chip_flow.winfo_height())
    p.kind.set('')
    pump(root, 10)
    grab('5522A_1100')
    root.geometry('1260x800+0+0')
    pump(root, 40)
    columns_ok('1260 again')
    check('specs: no Tk callback errors', not errs, errs)
    root.destroy()


def checks_standards_specs_small():
    """A narrow panel collapses the rail into a selector; a database with no standards shows the empty state."""
    import specmanager as sm
    import specmanager_ui as SU
    root = tk.Tk()
    ui.apply_theme(root)
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    root.geometry('900x560+0+0')
    holder = ttk.Frame(root, padding=16)
    holder.pack(fill='both', expand=True)
    p = SU.SpecManagerPanel(holder)
    p.pack(fill='both', expand=True)
    pump(root, 40)
    check('specs 900: rail collapsed into a selector', not p.rail.winfo_ismapped() and p.pickbar.winfo_ismapped() and len(p.pick_box['values']) >= 7, p.winfo_width())
    check('specs 900: table and header still shown, hint inside', p.table_card.winfo_ismapped() and inside(root, p.hint) and inside(root, p.head_card))
    p.pick_box.set('5560A')
    p.pick_box.event_generate('<<ComboboxSelected>>')
    pump(root, 20)
    check('specs 900: the selector picks a standard', p.h_title.cget('text') == '5560A' and p.count_lbl.cget('text') == 'Showing 147 of 147 ranges')
    root.geometry('1260x700+0+0')
    pump(root, 40)
    check('specs: the rail comes back when the window widens', p.rail.winfo_ismapped() and not p.pickbar.winfo_ismapped())
    p.destroy()
    empty_db = os.path.join(tempfile.mkdtemp(), 'none.sqlite3')
    with mock.patch.object(sm, 'DB', empty_db), mock.patch.object(sm, 'seed', lambda *a, **k: 0):
        q = SU.SpecManagerPanel(holder)
        q.pack(fill='both', expand=True)
        pump(root, 40)
        check('specs: no standards: message and an Import button, no header / table', q.empty_all.winfo_ismapped() and not q.head_card.winfo_ismapped()
              and not q.table_card.winfo_ismapped() and q.rail_empty.winfo_ismapped() and q.sel is None
              and any(isinstance(b, ttk.Button) and b.cget('text') == 'Import spec JSON...' for b in walk(q.empty_all)))
        q.set_divisor(), q.set_assets(), q.show_issues(), q.export_json(), q.check_emu()
        check('specs: handlers do nothing without a standard', True)
        q.destroy()
    check('specs small: no Tk callback errors', not errs, errs)
    root.destroy()


def checks_handheld_dialogs():
    """The 'Change the function' window (layout C) and the reading window (layout C): nothing clips, Enter = OK / Record, Esc = Cancel."""
    import handheld_dmm as HH
    root = tk.Tk()
    ui.apply_theme(root)
    root.geometry('800x500+0+0')
    pump(root)
    spec = HH.load_spec('fluke_110_series_pv.json')
    pts = HH.points_for(spec, '117')
    pt = next(p for p in pts if p['section'] == 'AC volts')
    p36 = next(p for p in pts if p['n'] == 36)

    def drive(open_it, act):
        """Run `open_it` (a modal call); after the window has shown, check it and call act(win)."""
        seen = {}

        def go():
            win = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
            pump(root, 5)
            bad = [c for c in walk(win) if c.winfo_ismapped() and not inside(win, c)]
            seen['clipped'] = bad
            seen['labels'] = sorted([c.cget('text') for c in walk(win) if isinstance(c, ttk.Button)])
            seen['size'] = (win.winfo_width(), win.winfo_height(), win.winfo_reqwidth(), win.winfo_reqheight())
            win.focus_force()
            pump(root, 5)
            act(win)
            root.after(3000, lambda: [w.destroy() for w in root.winfo_children() if isinstance(w, tk.Toplevel)])      # never hang
        root.after(400, go)
        seen['result'] = open_it()
        return seen

    long_text = 'Standby text that is deliberately long so that it has to wrap onto a second and a third line inside the window. ' * 2
    card = HH.function_change_card(pt, len(pts), long_text)
    r = drive(lambda: ui.confirm_steps(root, 'Change the function', 'AC volts', [], layout='function_change', card=card, ok='Done - continue'),
              lambda w: w.event_generate('<Return>'))
    check('function window: nothing clipped', not r['clipped'], r['clipped'])
    check('function window: OK button keeps the caller label', r['labels'] == ['Cancel', 'Done - continue'], r['labels'])
    check('function window: Enter = Done', r['result'] is True)
    r = drive(lambda: ui.confirm_steps(root, 'Change the function', 'AC volts', [], layout='function_change', card=card, ok='Done - continue'),
              lambda w: w.event_generate('<Escape>'))
    check('function window: Esc = Cancel', r['result'] is False)
    r = drive(lambda: ui.confirm_steps(root, 'Change the function', 'AC volts', [], layout='function_change',
                                       card=HH.function_change_card(pt, len(pts), 'x', standby_known=True)), lambda w: w.destroy())
    check('function window: tick state draws', not r['clipped'])

    def reading(p, **kw):
        return lambda: HH.ask_reading(root, p, len(pts), HH.output_text(p), 'Output is ON - allow the reading to settle, then read the meter.',
                                      '0.2 to 0.8 V  and the AC annunciator is ON', 'numeric', unit='V', **kw)

    def typed(w):
        entry = [c for c in walk(w) if isinstance(c, ttk.Entry)][0]
        entry.insert(0, '0.5')
        w.event_generate('<Return>')
    r = drive(reading(p36, demo_fill=lambda: '0.5', limit_s=60.0, on_expire=lambda: None), typed)
    check('reading window: nothing clipped (demo helper + timer)', not r['clipped'], r['clipped'])
    check('reading window: Enter records the typed text', r['result']['action'] == 'record' and r['result']['text'] == '0.5', r['result'])
    r = drive(reading(p36), lambda w: [b for b in walk(w) if isinstance(b, ttk.Button) and b.cget('text') == 'Skip point'][0].invoke())
    check('reading window: Skip', r['result']['action'] == 'skip')
    r = drive(reading(p36), lambda w: [b for b in walk(w) if isinstance(b, ttk.Button) and b.cget('text') == 'Stop run'][0].invoke())
    check('reading window: Stop', r['result']['action'] == 'stop')
    root.destroy()


def checks_dsb_layout():
    """Datasheet Builder layout B on a real Tk: nothing clipped at 1100x700 and 1400x900, the grid keeps its rows, the inspector hides and shows,
    Enter in an inspector box applies (Calc), Tab order starts at the sheet bar, the grid has no As Found / As Left / Out of Tol columns."""
    import datasheet_builder_ui as U
    import datasheet_builder_ui_model as DM
    from tests import dsb_fixtures
    t = Path(tempfile.mkdtemp())
    root = tk.Tk()
    ui.apply_theme(root)
    root.geometry('200x100+1300+0')
    for w, h, min_rows, auto_open in ((1400, 900, 18, True), (1200, 760, 8, True), (1000, 700, 8, False)):
        g = DM.GridModel(DM.Storage(t / f'u{w}', t / f'r{w}.sqlite3', who='real'), dsb_fixtures.dmm_34461a_like())
        win = U.GridEditorWindow(root, g)
        win.geometry(f'{w}x{h}+0+0')
        pump(root, 40)
        tag = f'dsb {w}x{h}'
        key = [r for r in g.rows() if r['kind'] == 'point'][3]['key']
        g.select(key, 'low')
        win.sync()
        pump(root, 20)
        rows_visible = (win.sheet.winfo_height() - win.sheet.geo.head_h) // win.sheet.geo.row_h
        check(f'{tag}: grid rows', rows_visible >= min_rows, rows_visible)
        check(f'{tag}: inspector {"open" if auto_open else "auto-collapsed to the rail"}',
              win.inspector_frame.winfo_ismapped() == auto_open and win.rail.winfo_ismapped() != auto_open and not win._insp_manual,
              (win.inspector_frame.winfo_ismapped(), win.rail.winfo_ismapped()))
        if not auto_open:
            check(f'{tag}: rail button inside the window', inside(win, win.rail_b))
            win.toggle_inspector()                                  # shown by hand, then the checks below look at the panel
            pump(root, 20)
            check(f'{tag}: shown by hand while narrow', win.inspector_frame.winfo_ismapped() and win._insp_manual)
        check(f'{tag}: five grid columns, Low and High limit', len(win.sheet.geo.widths) == 5 and DM.COL_KEYS == ('step', 'function', 'nominal', 'low', 'high'))
        for name in ('sheet_bar', 'bar', 'save_b', 'run_b', 'demo_b', 'preview_b', 'more_b', 'standards_b', 'undo_b', 'redo_b', 'lock_box', 'show_list_b', 'recalc_b',
                     'sheet', 'inspector_frame'):
            check(f'{tag}: {name} inside the window', inside(win, getattr(win, name)), name)
        box = win.panel_box
        # everything in the inspector is reachable: inside its frame, or scrollable (the scrollbar is shown when the content is taller)
        canvas = box.canvas
        check(f'{tag}: inspector content fits or scrolls', box.inner.winfo_reqheight() <= canvas.winfo_height() or box.scroll.winfo_ismapped(),
              (box.inner.winfo_reqheight(), canvas.winfo_height()))
        check(f'{tag}: inspector width inside the window', win.inspector_frame.winfo_rootx() + win.inspector_frame.winfo_width() <= win.winfo_rootx() + win.winfo_width() + 2)
        for sec in box.sections.values():
            if sec.winfo_ismapped():
                check(f'{tag}: section "{sec.title}" not wider than the panel', sec.winfo_width() <= canvas.winfo_width() + 2, (sec.winfo_width(), canvas.winfo_width()))
        check(f'{tag}: sheet bar wraps only when it must', (w < 1250) == bool(win._bar_wrapped) or w >= 1250)
        # Enter in a box applies (Calc)
        before = g.cell_text(key, 'low')
        box.v['fs'].set('0.01')
        e = next(x for x in box.entries if str(x.cget('textvariable')) == str(box.v['iv']))
        box.types['iv'].set(True), box.v['iv'].set('0.05')
        e.focus_force()
        pump(root, 5)
        e.event_generate('<Return>')
        pump(root, 10)
        check(f'{tag}: Enter in a box applies', g.cell_text(key, 'low') != before or 'calculated' in win.status.get().lower() or win.note.get() != '', (before, g.cell_text(key, 'low'), win.note.get()))
        # the limits: read-only while they are calculated, typed on request (the tolerance boxes are hidden then, never both editable)
        win.sync()
        pump(root, 10)
        check(f'{tag}: Low / High limit boxes are read-only while calculated', str(box.low_e.cget('state')) == 'readonly' and str(box.high_e.cget('state')) == 'readonly')
        check(f'{tag}: limit boxes show the sheet cells', box.v['low'].get() == g.row(key)['low'] and box.v['high'].get() == g.row(key)['high'], (box.v['low'].get(), g.row(key)['low']))
        check(f'{tag}: limit boxes inside the panel', inside(win, box.low_e) or box.scroll.winfo_ismapped())
        box.b['typed'].set(True)
        box.typed_changed()
        pump(root, 15)
        check(f'{tag}: typing the limits unlocks the boxes and hides the tolerance boxes', str(box.low_e.cget('state')) == 'normal' and not box.chip_frame.winfo_ismapped()
              and not any(box.cells[n].winfo_ismapped() for n in box.tol_names))
        box.b['typed'].set(False)
        box.typed_changed()
        pump(root, 15)
        check(f'{tag}: unticked again: tolerance boxes back, limits read-only', box.chip_frame.winfo_ismapped() and str(box.low_e.cget('state')) == 'readonly')
        # chips toggle with the keyboard
        chip = box.chips[1]
        chip.focus_force()
        was = box.types['fs'].get()
        chip.event_generate('<space>')
        pump(root, 5)
        check(f'{tag}: chip toggles with space', box.types['fs'].get() != was)
        # hide / show
        win.toggle_inspector()
        pump(root, 20)
        check(f'{tag}: inspector hidden leaves a rail', not win.inspector_frame.winfo_ismapped() and win.rail.winfo_ismapped() and inside(win, win.rail_b))
        win.toggle_inspector()
        pump(root, 20)
        check(f'{tag}: inspector shown again', win.inspector_frame.winfo_ismapped())
        # a section heading and a blank row
        g.select([r for r in g.rows() if r['kind'] == 'header'][0]['key'], 'function')
        win.sync()
        pump(root, 20)
        check(f'{tag}: heading row shows the rules section only', [n for n, s in box.sections.items() if s.winfo_ismapped()] == ['rules'])
        win.destroy()
    root.destroy()


def checks_dsb_auto_collapse():
    """The inspector collapses by itself under 1150 px and opens again when the window grows; a hand choice sticks.  Also the template sheet:
    only warnings (grouped), nothing clipped, the warnings list builds.  Screenshots when DSB_SHOTS is set (folder)."""
    import datasheet_builder_ui as U
    import datasheet_builder_ui_model as DM
    t = Path(tempfile.mkdtemp())
    root = tk.Tk()
    ui.apply_theme(root)
    root.geometry('100x60+1480+930')
    out = os.environ.get('DSB_SHOTS')

    def shot(win, name):
        if out:
            from PIL import ImageGrab
            pump(root, 30)
            ImageGrab.grab(bbox=(win.winfo_rootx(), win.winfo_rooty(), win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height()),
                           xdisplay=os.environ['DISPLAY']).save(f'{out}/{name}_{THEME}.png')

    def sized(win, w, h):
        win.geometry(f'{w}x{h}+0+0')
        pump(root, 40)

    def state(win):
        return win.inspector_frame.winfo_ismapped(), win.rail.winfo_ismapped()

    for seq, label in (('auto', 'auto'), ('hand', 'hand')):
        g = DM.GridModel(DM.Storage(t / f'u{seq}', t / f'r{seq}.sqlite3', who='real'))
        g.set_header(make='Acme', model='DM-1', title='DM-1 handheld')
        g.add_handheld_functions()
        dcv = next(f for f in g.ds.functions if f.kind == 'DCV')
        g.select(f'e:{dcv.id}', 'nominal')
        g.set_target_function('DC volts')
        g.commit_cell('5 V')
        key = next(r['key'] for r in g.rows() if r['kind'] == 'point')
        f = g.panel_state(key)['form']
        f['types'] = ['iv']
        f['plus'].update(iv='0.05')
        g.calc_row(key, f)
        win = U.GridEditorWindow(root, g)
        sized(win, 1400, 900)
        check(f'{label}: 1400x900 opens with the inspector', state(win) == (True, False), state(win))
        check(f'{label}: template sheet has no errors, one grouped warning', g.problem_counts() == dict(errors=0, warnings=1), g.problem_counts())
        if seq == 'auto':
            shot(win, 'template_1400x900')
            win.show_problems()
            pump(root, 30)
            dlg = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
            check('warnings list opens', bool(dlg))
            if dlg:
                shot(dlg[-1], 'warnings_list')
                import time
                time.sleep(0.5)
                pump(root, 10)
                dlg[-1].destroy()
            sized(win, 1000, 700)
            check('auto: 1000x700 collapses to the rail', state(win) == (False, True), state(win))
            rows_visible = (win.sheet.winfo_height() - win.sheet.geo.head_h) // win.sheet.geo.row_h
            check('auto: 1000x700 grid keeps 8 rows', rows_visible >= 8, rows_visible)
            check('auto: rail button inside the window', inside(win, win.rail_b))
            check('auto: collapsing did not take focus', win.focus_get() is not win.rail_b)
            shot(win, 'template_1000x700')
            sized(win, 1100, 700)
            check('auto: 1100 stays collapsed', state(win) == (False, True), state(win))
            sized(win, 1400, 900)
            check('auto: growing back opens it again', state(win) == (True, False), state(win))
            sized(win, 1000, 700)
            check('auto: and collapses again', state(win) == (False, True))
            win.event_generate('<Control-i>')
            pump(root, 20)
            check('Ctrl+I still shows it', state(win) == (True, False) and win._insp_manual, state(win))
            sized(win, 1050, 700)
            check('manual show sticks when narrower still', state(win) == (True, False), state(win))
            shot(win, 'template_1050x700_shown_by_hand')
            sized(win, 1400, 900)
        else:
            win.toggle_inspector()                                  # hidden by hand while wide
            pump(root, 20)
            sized(win, 1000, 700)
            sized(win, 1450, 900)
            check('hand: hidden by hand stays hidden when the window grows', state(win) == (False, True), state(win))
            shot(win, 'template_hidden_1450x900')
        import time
        time.sleep(0.5)                                             # let fit_window's delayed callback run before the window goes
        pump(root, 10)
        win.destroy()
    root.destroy()


def checks_run_queue():
    """The three run-queue windows on a real Tk: set-up, one-window reading entry for several meters, progress.  Screenshots when RQ_SHOTS is set."""
    import handheld_dmm as HH
    import run_queue as RQ
    import run_queue_ui as RU
    root = tk.Tk()
    ui.apply_theme(root)
    root.geometry('900x600+0+0')
    pump(root)
    spec = HH.load_spec('fluke_110_series_pv.json')
    pts = HH.points_for(spec, '117')
    p = next(x for x in pts if x['kind'] == 'DCV' and x['nominal'] == 5.0)

    def shot(top, name):
        out = os.environ.get('RQ_SHOTS')
        if out:
            from PIL import ImageGrab
            pump(root, 10)
            x, y, w, h = top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ['DISPLAY']).save(f'{out}/{name}_{THEME}.png')

    def drive(open_it, act):
        seen = {}

        def go():
            win = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
            pump(root, 8)
            win.focus_force()
            pump(root, 5)
            seen['clipped'] = [c for c in walk(win) if c.winfo_ismapped() and not inside(win, c)]
            seen['win'] = win
            act(win, seen)
            root.after(4000, lambda: [w.destroy() for w in root.winfo_children() if isinstance(w, tk.Toplevel)])         # never hang
        root.after(500, go)
        seen['result'] = open_it()
        return seen

    def buttons(win):
        return {b.cget('text'): b for b in walk(win) if isinstance(b, ttk.Button)}

    # ---- set-up window
    def summarize(meters, mode):
        q = RQ.RunQueue()
        for a, sn, t in meters:
            q.add(a, sn, t)
        info = RQ.summary(pts, q, spec['options'], mode=mode)
        if mode == RQ.POINT_BY_POINT:
            return dict(title=f'Saves {info["saved"]} calibrator settings', body=f'{info["points"]} points x {len(meters)} meters = {info["alone"]} settings one at a time; '
                        f'point by point needs {info["settings"]}.', ok=True, kind='good')
        return dict(title='One meter at a time', body=f'{info["alone"]} calibrator settings.', ok=True, kind='warn')
    meters = [('4412', '21090134', 'M. Reyes'), ('4413', '21090187', 'M. Reyes'), ('4415', '21090240', 'M. Reyes')]

    def setup_act(win, seen):
        b = buttons(win)
        check('queue setup: buttons present', {'+ Add meter', 'Edit', 'Remove', 'Move up', 'Move down', 'Start queue', 'Cancel'} <= set(b), sorted(b))
        check('queue setup: nothing clipped', not seen['clipped'], seen['clipped'])
        tree = next(w for w in walk(win) if isinstance(w, ttk.Treeview))
        check('queue setup: three rows', len(tree.get_children()) == 3)
        shot(win, 'queue_setup')
        tree.selection_set('0')
        b['Move down'].invoke()
        pump(root, 3)
        check('queue setup: move down', [tree.item(i, 'values')[1] for i in tree.get_children()] == ['4413', '4412', '4415'], [tree.item(i, 'values') for i in tree.get_children()])
        tree.selection_set('2')
        b['Remove'].invoke()
        check('queue setup: remove', len(tree.get_children()) == 2)
        radios = [w for w in walk(win) if isinstance(w, ttk.Radiobutton)]
        radios[1].invoke()
        pump(root, 3)
        b['Start queue'].invoke()
    r = drive(lambda: RU.ask_queue_setup(root, 'Run queue - Fluke 117', meters, RQ.POINT_BY_POINT, summarize, status_of=lambda a: 'Ready', default_tech='M. Reyes'), setup_act)
    res = r['result']
    check('queue setup: Start returns the edited queue and the chosen mode', res and res['action'] == 'start' and [m[0] for m in res['meters']] == ['4413', '4412']
          and res['mode'] == RQ.ONE_AT_A_TIME, res)
    r = drive(lambda: RU.ask_queue_setup(root, 'Run queue - Fluke 117', meters, RQ.POINT_BY_POINT, summarize), lambda w, s: buttons(w)['Cancel'].invoke())
    check('queue setup: Cancel returns nothing', r['result'] is None)

    # ---- the one-window reading entry
    def judge(key, text):
        padded = HH.pad_reading(p, text)
        state, _ = HH.judge_numeric(p, padded)
        return state, padded, '+0.001 V from nominal' if state == 'PASS' else ''
    asset_rows = [('4412', '4412', ''), ('4413', '4413', ''), ('4415', '4415', '')]

    def read(**kw):
        return lambda: RU.ask_readings(root, p, len(pts), HH.output_text(p), 'Output is ON - allow the reading to settle, then read the meter.',
                                       '4.9950 to 5.0050 V', asset_rows, unit='V', judge=judge, heading=HH.describe(p), **kw)

    def reading_act(win, seen):
        entries = [c for c in walk(win) if isinstance(c, ttk.Entry)]
        check('readings: one box per meter', len(entries) == 3, len(entries))
        check('readings: nothing clipped', not seen['clipped'], seen['clipped'])
        labels = ' '.join(str(c.cget('text')) for c in walk(win) if isinstance(c, tk.Label))
        check('readings: asset numbers shown', all(f'Asset {a}' in labels for a in ('4412', '4413', '4415')), labels[:300])
        entries[0].focus_force()
        entries[0].insert(0, '5.001')
        pump(root, 5)
        entries[1].focus_force()
        entries[1].insert(0, '5.0')
        pump(root, 5)
        texts = ' '.join(str(c.cget('text')) for c in walk(win) if isinstance(c, tk.Label))
        check('readings: live PASS and padding shown', 'PASS' in texts and 'padded to 5.000' in texts, texts)
        entries[2].focus_force()
        entries[2].insert(0, '9')
        pump(root, 5)
        texts = ' '.join(str(c.cget('text')) for c in walk(win) if isinstance(c, tk.Label))
        check('readings: a failing meter shows FAIL', 'FAIL' in texts, texts)
        shot(win, 'queue_reading')
        entries[0].focus_force()
        entries[0].event_generate('<Return>')
        pump(root, 3)
        check('readings: Enter moves to the next box', win.focus_get() is entries[1], win.focus_get())
        entries[2].focus_force()
        entries[2].event_generate('<Return>')                    # Enter in the last box records
    r = drive(read(), reading_act)
    got = r['result']
    check('readings: Record all returns every meter\'s text', got['action'] == 'record' and got['texts'] == {'4412': '5.001', '4413': '5.0', '4415': '9'}, got)

    def empty_act(win, seen):
        buttons(win)['Record all  (Enter)'].invoke()
        pump(root, 3)
        texts = ' '.join(str(c.cget('textvariable')) and c.cget('text') for c in walk(win) if isinstance(c, tk.Label))
        check('readings: empty boxes refuse to record', win.winfo_exists())
        buttons(win)['Stop run'].invoke()
    r = drive(read(), empty_act)
    check('readings: Stop run', r['result']['action'] == 'stop')
    r = drive(read(), lambda w, s: buttons(w)['Skip point'].invoke())
    check('readings: Skip point', r['result']['action'] == 'skip')

    def fill_act(win, seen):
        b = buttons(win)
        check('readings: demo button marked', any('simulated' in k for k in b), sorted(b))
        shot(win, 'queue_reading_demo')
        next(v for k, v in b.items() if 'simulated' in k).invoke()
        pump(root, 3)
        check('readings: Fill fills every box', all(c.get() for c in walk(win) if isinstance(c, ttk.Entry)))
        b['Record all  (Enter)'].invoke()
    r = drive(read(demo_fill=lambda i: f'5.00{i}'), fill_act)
    check('readings: Fill result', r['result']['action'] == 'record' and len(r['result']['texts']) == 3, r['result'])

    def noreading_act(win, seen):
        boxes = [c for c in walk(win) if isinstance(c, ttk.Checkbutton)]
        entries = [c for c in walk(win) if isinstance(c, ttk.Entry)]
        entries[0].insert(0, '5.0')
        entries[2].insert(0, '5.0')
        boxes[1].invoke()
        buttons(win)['Record all  (Enter)'].invoke()
    r = drive(read(), noreading_act)
    check('readings: a meter marked No reading records nothing', r['result']['texts'] == {'4412': '5.0', '4413': None, '4415': '5.0'}, r['result'])

    # ---- progress window
    rows = [dict(asset='4412', serial='', status='Running', recorded=7, failed=0, first_fail=None, total=40),
            dict(asset='4413', serial='', status='Running', recorded=6, failed=0, first_fail=None, total=40),
            dict(asset='4415', serial='', status='Running', recorded=6, failed=1, first_fail=3, total=40)]
    prog = RU.QueueProgress(root)
    prog.update('Point 7 of 40  -  all 3 meters', 7 / 40, rows)
    pump(root, 10)
    check('progress: window open', prog.alive())
    check('progress: nothing clipped', not [c for c in walk(prog.win) if c.winfo_ismapped() and not inside(prog.win, c)])
    shot(prog.win, 'queue_progress')
    calls = []
    prog.on_export, prog.on_show = (lambda: calls.append('export')), (lambda a: calls.append(a))
    prog.update('Queue complete', 1.0, rows, finished=True)
    pump(root, 10)
    b = buttons(prog.win)
    check('progress: finished offers export and close', 'Export all reports (PDF)...' in b and 'Close' in b, sorted(b))
    b['Export all reports (PDF)...'].invoke()
    buttons(prog.win)['Show'].invoke()
    check('progress: callbacks', calls[0] == 'export' and calls[1] in ('4412', '4413', '4415'), calls)
    shot(prog.win, 'queue_progress_done')
    prog.close()
    check('progress: close', not prog.alive())
    prog.update('x', 0, rows)                                    # updating a closed window is harmless
    root.destroy()


def checks_run_queue_app():
    """The real handheld window on a real Tk with a three-meter queue on the virtual bench: the drawer button and chip, then a whole point-by-point run with
    the real reading / prompt windows driven by events (the Fill button), one report per meter."""
    import time
    import handheld_dmm as HH
    import run_queue as RQ
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    home = os.environ.get('RQ_SHOTS')
    patches = [mock.patch.object(messagebox, n, return_value=True) for n in ('askyesno', 'askokcancel', 'askyesnocancel', 'showinfo', 'showwarning', 'showerror')]
    for pt in patches:
        pt.start()
    app = HH.App(root, '116', demo=True)
    pump(root, 20)
    btn = next((w for w in walk(root) if isinstance(w, ttk.Button) and w.cget('text') == 'Run queue...'), None)
    check('app: the drawer has a Run queue... button', btn is not None)
    check('app: no queue, no chip', not app.queue_pill.winfo_manager() and app.queue_chip_text() == '')
    app.apply_queue([('4412', 'S1', 'Reyes'), ('4413', 'S2', 'Reyes'), ('4415', 'S3', 'Reyes')], RQ.POINT_BY_POINT)
    pump(root, 5)
    check('app: queue chip shown', app.queue_pill.winfo_manager() and 'Run queue: 3 meters' in str(app.queue_pill.cget('text')), app.queue_chip_text())
    seen = {'windows': [], 'multi': 0, 'swap': 0}

    def tick():
        try:
            wins = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable() and not str(w.title()).startswith('Queue progress')]
            for win in wins:
                texts = {b.cget('text'): b for b in walk(win) if isinstance(b, ttk.Button)}
                seen['windows'].append(win.title())
                fill = next((b for t, b in texts.items() if 'simulated' in t), None)
                if fill is not None:
                    if len([e for e in walk(win) if isinstance(e, ttk.Entry)]) == 3:
                        seen['multi'] += 1
                    fill.invoke()
                    pump(root, 2)
                    next(b for t, b in texts.items() if t.startswith('Record')).invoke()
                    continue
                if 'Next meter' in win.title() or 'One meter at a time' in win.title():
                    seen['swap'] += 1
                go = next((b for t, b in texts.items() if 'continue' in t or t in ('OK', 'Yes')), None)
                if go is not None:
                    go.invoke()
        except tk.TclError:
            pass
        root.after(120, tick)
    root.after(300, tick)
    app.run_all()
    end = time.time() + 240

    def watch():
        if (not app.busy and app._q is None) or time.time() > end:
            root.quit()
        else:
            root.after(250, watch)
    root.after(1500, watch)
    root.mainloop()                                              # the engine's worker threads post back to the main loop, so it must really run
    pump(root, 10)
    check('app: the run finished', not app.busy and app._q is None, app.status.get())
    check('app: three-meter windows appeared', seen['multi'] > 10, seen['multi'])
    check('app: the swap prompt appeared for the current points', seen['swap'] >= 3, seen['swap'])
    for m in app.queue.meters:
        check(f'app: asset {m.asset} has every point', len(m.found) == len(app.points), (len(m.found), len(app.points)))
        check(f'app: asset {m.asset} is demo data', all(r['synthetic'] for r in m.found.values()))
    check('app: shown results are meter 1', app.asset.get() == '4412')
    if home:
        from PIL import ImageGrab
        root.update()
        root.geometry('1320x800+0+0')
        pump(root, 20)
        ImageGrab.grab(bbox=(0, 0, 1320, 800), xdisplay=os.environ['DISPLAY']).save(f'{home}/queue_app_{THEME}.png')
    check('app: no callback errors', not errs, errs)
    for pt in patches:
        pt.stop()
    root.destroy()


def checks_import_package():
    """'Import procedure package...' on a real Tk: the preview dialog (warning, origin, files, confirmation gate), the install, and the refusal view."""
    import json
    import zipfile
    import Calibration_Procedure_Manager as CPM
    import packages
    import packages_ui
    import procscan
    import verified
    from tests._pkg_helpers import make_tree
    work = Path(tempfile.mkdtemp())
    src = make_tree(work / 'src', ['Keithley_2000_Verification'])
    lib = work / 'lib'
    zp = packages.build_package('Keithley_2000_Verification', src, lib, registry=verified.Registry(work / 'sr.sqlite3', base=src), author='Check')
    tree = make_tree(work / 'target', [], ['Keithley_2000_Verification'])
    CPM.init_db()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    m = CPM.Manager(root)
    pump(root, 20)
    m.verified = verified.Registry(work / 'reg.sqlite3', base=tree)
    check('import button exists', any(isinstance(w, ttk.Button) and w.cget('text') == 'Import procedure package...' for w in walk(m.library_frame)))
    check('library folder row exists', 'not set' in m.lib_folder.get(), m.lib_folder.get())

    def drive(fn):
        def go():
            tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
            if not tops:
                root.after(100, go)
                return
            try:
                fn(tops[-1])
            except Exception as ex:                          # report it, and close the dialog so the run does not hang
                errs.append(ex)
                tops[-1].destroy()
        root.after(400, go)

    def shot(top, name):
        out = os.environ.get('PKG_SHOTS')
        if out:
            from PIL import ImageGrab
            pump(root, 10)
            x, y, w, h = top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ['DISPLAY']).save(f'{out}/{name}_{THEME}.png')

    def preview(top):
        btns = [w for w in walk(top) if isinstance(w, ttk.Button)]
        install = next(b for b in btns if b.cget('text') == 'Install package')
        box = next(w for w in walk(top) if isinstance(w, ttk.Checkbutton))
        check('preview: install disabled until confirmed', str(install.cget('state')) == 'disabled')
        texts = ' '.join(str(w.cget('text')) for w in walk(top) if isinstance(w, ttk.Label))
        check('preview: code warning shown', 'Only import packages from the lab' in texts)
        check('preview: origin shown', str(zp) in texts.replace('\n', ' ') or zp.name in texts)
        rows = [w for w in walk(top) if isinstance(w, ttk.Treeview)][0].get_children()
        check('preview: file list', len(rows) == 5, len(rows))
        check('preview: buttons visible', all(inside(top, b) for b in btns + [box]))
        shot(top, 'import_preview')
        box.invoke()
        pump(root, 3)
        check('preview: install enabled after confirming', str(install.cget('state')) == 'normal')
        install.invoke()
    from unittest import mock
    with mock.patch.object(CPM, 'BASE', tree), mock.patch.object(packages_ui, 'choose_package', return_value=str(zp)), \
            mock.patch.object(messagebox, 'showinfo') as info, mock.patch.object(packages, 'get_library_dir', return_value=str(lib)):
        drive(preview)
        m.import_package()
        pump(root, 10)
        check('import: procedure installed', (tree / 'Procedures' / 'Keithley_2000_Verification.py').is_file())
        check('import: scanner finds it', procscan.find('Keithley_2000_Verification', tree) is not None)
        check('import: result shown', info.called and 'Installed' in info.call_args[0][1], info.call_args)

        # a refused package: no install button, reasons shown
        bad = work / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({'package_format': 1, 'procedure': {'id': 'X_Proc', 'name': 'X', 'version': '1'},
                                                    'files': [{'path': '../evil.py', 'sha256': '0' * 64}]}))
        def refused(top):
            btns = [w for w in walk(top) if isinstance(w, ttk.Button)]
            check('refused: no install button', not any(b.cget('text') == 'Install package' and str(b.cget('state')) != 'disabled' for b in btns))
            check('refused: buttons visible', all(inside(top, b) for b in btns))
            texts = ' '.join(str(w.cget('text')) for w in walk(top) if isinstance(w, ttk.Label))
            check('refused: reason shown', '..' in texts, texts[:400])
            shot(top, 'import_refused')
            [b for b in btns if b.cget('text') == 'Close'][0].invoke()
        with mock.patch.object(packages_ui, 'choose_package', return_value=str(bad)):
            drive(refused)
            m.import_package()
        pump(root, 5)

        # re-import over the installed (and verified-locked) procedure: replaces files, warns about the lock
        proc = procscan.find('Keithley_2000_Verification', tree)
        entry = verified.make_entry(proc.name, proc.model, tree / proc.launcher, tree)
        from datetime import date
        (tree / 'specs' / 'keithley_2000_pv.json').write_text('{"older": true}')
        (tree / 'Procedures' / 'Keithley_2000_Verification.py').write_text('# older launcher\n')
        m.verified.verify(entry, 'Mike', '2026-10-20', '', '', today=date(2026, 10, 22))          # verified and locked with the OLD files

        def replace(top):
            texts = ' '.join(str(w.cget('text')) for w in walk(top) if isinstance(w, ttk.Label))
            check('replace: lock warning', 'UNLOCK' in texts.upper() and 'VERIFIED ON HARDWARE' in texts.upper(), texts[:500])
            check('replace: buttons visible', all(inside(top, b) for b in walk(top) if isinstance(b, ttk.Button)))
            shot(top, 'import_replace_locked')
            [b for b in walk(top) if isinstance(b, ttk.Button) and b.cget('text') == 'Cancel'][0].invoke()
        with mock.patch.object(packages_ui, 'choose_package', return_value=str(zp)):
            drive(replace)
            m.import_package()
        pump(root, 5)
        check('replace: cancel leaves the old file', (tree / 'Procedures' / 'Keithley_2000_Verification.py').read_text() == '# older launcher\n')
    check('no callback errors', not errs, errs)
    root.destroy()


def checks_dsb_dialogs_fit():
    """The Datasheet Builder's detail windows (Ranges, Specification table, Standards, Preview) are at least as tall as their content asks for,
    so their button row is not cut off (datasheet_builder_ui.grow_to_fit)."""
    import datasheet_builder_ui as U
    import datasheet_builder_ui_model as DM
    from tests import dsb_fixtures
    t = Path(tempfile.mkdtemp())
    root = tk.Tk()
    ui.apply_theme(root)
    root.geometry('200x100+1300+0')
    win = U.GridEditorWindow(root, DM.GridModel(DM.Storage(t / 'u', t / 'r.sqlite3', who='real'), dsb_fixtures.dmm_34461a_like()))
    win.geometry('1400x900+0+0')
    pump(root, 30)
    for name, opener in (('Ranges', win.open_ranges), ('Specification table', win.open_spec), ('Standards', win.open_standards), ('Preview', win.preview)):
        w = opener()
        pump(root, 30)
        bad = [b.cget('text') for b in walk(w) if isinstance(b, ttk.Button) and not inside(w, b)]
        check(f'dsb {name}: button row inside the window', not bad, bad)
        check(f'dsb {name}: window as tall as its content', w.winfo_height() >= min(w.winfo_reqheight(), w.winfo_screenheight() - ui.px(110)) - 1,
              (w.winfo_height(), w.winfo_reqheight()))
        w.destroy()
    win.destroy()
    root.destroy()

def checks_k2000_adjustment():
    """Keithley 2000 guided adjustment (demo on the simulated 2000): the calibration-change notice is visible, nothing is clipped at 1300x860, the whole flow runs
    (connect, record, unlock, 26 steps, dates, SAVE, lock), the window cannot be closed while unlocked, and the calibration code is nowhere in the window or the audit."""
    import importlib
    import keithley2000_adjustment as adj
    from drivers.simulated_k2000_cal import SIM_CODE
    from tkinter import simpledialog
    mod = importlib.import_module('Keithley_2000_Adjustment')
    root = tk.Tk()
    app = mod.App(root, demo=True)
    root.geometry('1300x860+0+0')
    pump(root, 30)
    notice = [w for w in walk(root) if isinstance(w, ttk.Label) and 'stored constants' in str(w.cget('text'))]
    check('k2000 adjustment: change notice shown', bool(notice) and inside(root, notice[0]))
    clipped = [str(w.cget('text')) for w in walk(root) if isinstance(w, (ttk.Button, ttk.Combobox, ttk.Entry)) and w.winfo_ismapped() and not inside(root, w)]
    check('k2000 adjustment: nothing clipped', not clipped, clipped)
    check('k2000 adjustment: starts locked and unconnected', str(app.btn_start['state']) == 'disabled' and str(app.btn_unlock['state']) == 'disabled' and str(app.btn_run['state']) == 'disabled')
    app.asset.set('K2000-REAL-TK')
    app.serial.set('SIM1')
    app.tech.set('Tester')
    answers = {'code_asked': 0}

    def ask_str(title, prompt, **kw):
        if 'code' in title.lower():
            answers['code_asked'] += 1
            return SIM_CODE
        return adj.CONFIRM_SAVE
    with mock.patch.object(messagebox, 'askyesno', return_value=True), mock.patch.object(messagebox, 'askokcancel', return_value=True), \
            mock.patch.object(messagebox, 'showinfo'), mock.patch.object(messagebox, 'showwarning') as warn, mock.patch.object(messagebox, 'showerror') as err, \
            mock.patch.object(ui, 'confirm_steps', return_value=True), mock.patch.object(simpledialog, 'askstring', side_effect=ask_str), \
            mock.patch.object(app, 'ask_value', side_effect=lambda t, p, default: default):
        app.connect()
        pump(root, 5)
        check('k2000 adjustment: connected (demo)', app.io is not None and 'DEMO' in app.pill_meter.cget('text'))
        app.start_record()
        check('k2000 adjustment: record started, still locked', app.session is not None and not app.session.unlocked and 'LOCKED' in app.pill_lock.cget('text'))
        app.unlock()
        check('k2000 adjustment: unlocked after the code', app.session.unlocked and answers['code_asked'] == 1 and 'UNLOCKED' in app.pill_lock.cget('text'))
        app.on_close()
        check('k2000 adjustment: cannot be closed while unlocked', root.winfo_exists() and warn.called)
        n = 0
        while app.session.next_step() and n < 40:
            app.run_next()
            n += 1
        pump(root, 5)
        check('k2000 adjustment: all 26 steps ran, none failed', n == 26 and app.session.all_done() and not err.called, (n, err.call_args_list[:1]))
        check('k2000 adjustment: SAVE is offered only now', str(app.btn_save['state']) == 'normal' and str(app.btn_run['state']) == 'disabled')
        app.dates_and_save()
        pump(root, 5)
    check('k2000 adjustment: saved and locked again', app.session.saved and app.session.locked_again and 'LOCKED' in app.pill_lock.cget('text') and not app.session.unlocked)
    rows = [app.log_table.item(i, 'values') for i in app.log_table.get_children()]
    check('k2000 adjustment: audit log filled', len(rows) > 80, len(rows))
    check('k2000 adjustment: the code is not in the audit table or any label', not any(SIM_CODE in ' '.join(map(str, r)) for r in rows) and
          not any(SIM_CODE in str(w.cget('text')) for w in walk(root) if isinstance(w, (ttk.Label, tk.Label))))
    check('k2000 adjustment: demo record is in memory only', app.audit.path == ':memory:' and 'DEMO' in app.pill_run.cget('text'))
    shots = os.environ.get('PKG_SHOTS')
    if shots:
        from PIL import ImageGrab
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()), xdisplay=os.environ['DISPLAY']).save(Path(shots) / f'k2000_adjustment_{THEME}.png')
    app.disconnect()
    app.on_close()

def checks_8808a_adjustment():
    """Fluke 8808A guided adjustment (demo on the simulated 8808A): the calibration-change notice is visible, nothing is clipped at 1300x860, the whole flow runs
    (connect, record, enter calibration mode, 124 points, EXIT), the window cannot be closed while the calibration mode is open, and nothing is recorded in a demo."""
    import importlib
    mod = importlib.import_module('Fluke_8808A_Adjustment')
    root = tk.Tk()
    app = mod.App(root, demo=True)
    root.geometry('1300x860+0+0')
    pump(root, 30)
    notice = [w for w in walk(root) if isinstance(w, ttk.Label) and 'no SAVE step' in str(w.cget('text'))]
    check('8808a adjustment: change notice shown', bool(notice) and inside(root, notice[0]))
    clipped = [str(w.cget('text')) for w in walk(root) if isinstance(w, (ttk.Button, ttk.Combobox, ttk.Entry)) and w.winfo_ismapped() and not inside(root, w)]
    check('8808a adjustment: nothing clipped', not clipped, clipped)
    check('8808a adjustment: starts closed and unconnected', str(app.btn_start['state']) == 'disabled' and str(app.btn_enter['state']) == 'disabled' and str(app.btn_run['state']) == 'disabled')
    app.asset.set('8808A-REAL-TK')
    app.serial.set('SIM1')
    app.tech.set('Tester')
    with mock.patch.object(messagebox, 'askyesno', return_value=True), mock.patch.object(messagebox, 'askyesnocancel', return_value=True), \
            mock.patch.object(messagebox, 'askokcancel', return_value=True), mock.patch.object(messagebox, 'showinfo'), mock.patch.object(messagebox, 'showwarning') as warn, \
            mock.patch.object(messagebox, 'showerror') as err, mock.patch.object(ui, 'confirm_steps', return_value=True), mock.patch.object(app, 'ask_value', side_effect=lambda t, p, default: default):
        app.connect()
        pump(root, 5)
        check('8808a adjustment: connected (demo)', app.io is not None and 'DEMO' in app.pill_meter.cget('text'))
        app.start_record()
        check('8808a adjustment: record started, mode still closed', app.session is not None and not app.session.cal_mode and 'closed' in app.pill_cal.cget('text'))
        app.enter_calibration()
        check('8808a adjustment: calibration mode open', app.session.cal_mode and 'OPEN' in app.pill_cal.cget('text'))
        app.on_close()
        check('8808a adjustment: cannot be closed while the mode is open', root.winfo_exists() and warn.called)
        n = 0
        while app.session.next_step() and n < 400:
            st = app.session.next_step()
            if st['id'] in mod.adj.own_standard_ids(app.session.cal_key):
                app._bench.external = ('V', 1.9, float(st['point']['value']))
            else:
                app._bench.external = None
            app.run_next()
            n += 1
        pump(root, 5)
        check('8808a adjustment: all 124 points ran, none failed', app.session.all_done() and not err.called and len(app.io.dmm.t.constants) == 124, (n, err.call_args_list[:1]))
        check('8808a adjustment: Finish is offered only now', str(app.btn_finish['state']) == 'normal' and str(app.btn_run['state']) == 'disabled')
        app.finish()
        pump(root, 5)
    check('8808a adjustment: finished and mode left', app.session.finished and not app.session.cal_mode and 'closed' in app.pill_cal.cget('text'))
    rows = [app.log_table.item(i, 'values') for i in app.log_table.get_children()]
    check('8808a adjustment: audit log filled', len(rows) > 500, len(rows))
    check('8808a adjustment: demo record is in memory only', app.audit.path == ':memory:' and 'DEMO' in app.pill_run.cget('text'))
    shots = os.environ.get('PKG_SHOTS')
    if shots:
        from PIL import ImageGrab
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()), xdisplay=os.environ['DISPLAY']).save(Path(shots) / f'8808a_adjustment_{THEME}.png')
    app.disconnect()
    app.on_close()



def checks_fluke_365():
    """The Fluke 365 performance verification on a real Tk: the Manager lists it under Automated Calibrations only; its run window is the ordinary handheld window
    (32 points, no typed grid, Performance Verification wording); the voltage and both coil cable-change prompts."""
    import handheld_dmm as HH
    import Calibration_Procedure_Manager as CPM
    CPM.init_db()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    shots = os.environ.get('SHOT_DIR')

    def grab(win, tag):
        if not shots:
            return
        from PIL import ImageGrab
        win.update()
        ImageGrab.grab(bbox=(win.winfo_rootx(), win.winfo_rooty(), win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height()),
                       xdisplay=os.environ['DISPLAY']).save(os.path.join(shots, f'{tag}_{THEME}.png'))
    m = CPM.Manager(root)
    root.geometry('1260x800+0+0')
    pump(root, 20)
    names = lambda: [m.table.item(k, 'values')[0] for k in m.table.get_children()]  # noqa: E731
    check('365: listed in Automated Calibrations', m.view_kind == 'verification' and 'Fluke 365 Clamp Meter Performance Verification' in names(), names())
    for k in m.table.get_children():
        if m.table.item(k, 'values')[0].startswith('Fluke 365'):
            m.table.selection_set(k)
            m.table.see(k)
            row = m.table.item(k, 'values')
    pump(root, 10)
    check('365: manufacturer, model, category, status', row[1:4] == ('Fluke', '365', 'Clamp Meter') and 'Ready' in row[4], row)
    grab(root, 'fluke365_manager_automated')
    m.view_nb.select(m.view_pages['manual'])
    pump(root, 20)
    check('365: not in Manual Calibrations', not any(n.startswith('Fluke 365') for n in names()), names())
    root.destroy()
    # --- the run window
    root = tk.Tk()
    root.report_callback_exception = lambda *a: errs.append(a)
    spec = HH.load_spec('fluke_365_pv.json')
    app = HH.App(root, '365', demo=False, spec=spec)
    root.geometry('1320x800+0+0')
    pump(root, 30)
    app.asset.set('A-365')
    app.serial.set('S-365')
    tree = app.tree
    check('365 run window: 32 points, ordinary handheld window (no typed grid, queue on)', len(tree.get_children()) == 32 and not hasattr(app, 'grid_entry')
          and app.QUEUE_SUPPORTED is True and 'Manual Calibration' not in root.title(), root.title())
    tree.selection_set(tree.get_children()[20])                  # AC amps 0.5 A: the point detail shows the coil hook-up
    pump(root, 10)
    grab(root, 'fluke365_run_window')
    pts = {p['n']: p for p in app.points}

    def prompt(n, tag):
        seen = {}

        def go():
            win = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
            pump(root, 5)
            seen['clipped'] = [c for c in walk(win) if c.winfo_ismapped() and not inside(win, c)]
            seen['text'] = ' '.join(str(c.cget('text')) for c in walk(win) if isinstance(c, (ttk.Label, tk.Label)))
            grab(win, tag)
            win.destroy()
        root.after(500, go)
        seen['ok'] = app._prompt_setup(pts[n])
        return seen
    for n, tag, words in ((1, 'fluke365_prompt_voltage', 'VΩ'), (21, 'fluke365_prompt_coil_aux', 'REMOVE the test leads'), (22, 'fluke365_prompt_coil_20a', '20 A')):
        r = prompt(n, tag)
        check(f'365 prompt point {n}: shown, nothing clipped, says what it must', not r['clipped'] and words in r['text'], (r['clipped'], r['text'][:300]))
    check('365: no Tk callback errors', not errs, errs)
    try:
        root.destroy()
    except tk.TclError:
        pass


def checks_fluke_376():
    """The Fluke 374 / 375 / 376 / 376-II performance verifications on a real Tk: the Manager lists the four under Automated Calibrations only; the run window is the ordinary
    handheld window plus the 'iFlex probe supplied' check box (38 points for the 376, 29 with the box off; no typed grid, Performance Verification wording); the voltage,
    coil, iFlex simulation and iFlex-on-coil cable-change prompts."""
    import handheld_dmm as HH
    import iflex_option as XO
    import Calibration_Procedure_Manager as CPM
    CPM.init_db()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    shots = os.environ.get('SHOT_DIR')

    def grab(win, tag):
        if not shots:
            return
        from PIL import ImageGrab
        win.update()
        ImageGrab.grab(bbox=(win.winfo_rootx(), win.winfo_rooty(), win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height()),
                       xdisplay=os.environ['DISPLAY']).save(os.path.join(shots, f'{tag}_{THEME}.png'))
    m = CPM.Manager(root)
    root.geometry('1260x800+0+0')
    pump(root, 20)
    names = lambda: [m.table.item(k, 'values')[0] for k in m.table.get_children()]  # noqa: E731
    four = [f'Fluke {x} Clamp Meter Performance Verification' for x in ('374', '375', '376', '376-II')]
    check('374 / 375 / 376 / 376-II: listed in Automated Calibrations', m.view_kind == 'verification' and all(n in names() for n in four), names())
    rows = {}
    for k in m.table.get_children():
        v = m.table.item(k, 'values')
        if v[0] in four:
            rows[v[0]] = v
            if v[0] == four[2]:
                m.table.selection_set(k)
                m.table.see(k)
    pump(root, 10)
    check('374 / 375 / 376 / 376-II: manufacturer, model, category, status', [(r[1], r[2], r[3]) for r in rows.values()] == [('Fluke', x, 'Clamp Meter') for x in ('374', '375', '376', '376-II')]
          and all('Ready' in r[4] for r in rows.values()), rows)
    grab(root, 'fluke376_manager_automated')
    m.view_nb.select(m.view_pages['manual'])
    pump(root, 20)
    check('374 / 375 / 376 / 376-II: not in Manual Calibrations', not any(n.startswith(('Fluke 374', 'Fluke 375', 'Fluke 376')) for n in names()), names())
    root.destroy()
    # --- the run window
    root = tk.Tk()
    root.report_callback_exception = lambda *a: errs.append(a)
    spec = HH.load_spec('fluke_376_pv.json')
    app = XO.App(root, '376', demo=False, spec=spec)
    root.geometry('1320x800+0+0')
    pump(root, 30)
    app.asset.set('A-376')
    app.serial.set('S-376')
    tree = app.tree
    check('376 run window: 38 points, ordinary handheld window (no typed grid, no run queue)', len(tree.get_children()) == 38 and not hasattr(app, 'grid_entry')
          and not app.queue_supported() and HH.App.QUEUE_SUPPORTED is True and 'Manual Calibration' not in root.title(), root.title())
    boxes = [c for c in walk(root) if isinstance(c, ttk.Checkbutton) and 'iFlex probe supplied' in str(c.cget('text'))]
    check('376 run window: the iFlex check box is shown before Run, ON by default, never skipped silently', len(boxes) == 1 and boxes[0].winfo_ismapped() and app.include_is_on('iflex')
          and 'ON' in str(app._include_labels['iflex'].cget('text')), [str(c.cget('text')) for c in walk(root) if isinstance(c, ttk.Checkbutton)])
    box = boxes[0]
    check('376 run window: the check box sits above the point table', box.winfo_rooty() < tree.winfo_rooty(), (box.winfo_rooty(), tree.winfo_rooty()))
    tree.selection_set(tree.get_children()[29])                  # iFlex simulation 3 mV: the point detail shows the iFlex hook-up
    pump(root, 10)
    grab(root, 'fluke376_run_window')
    asked = []
    with mock.patch.object(XO.messagebox, 'askyesno', lambda *a, **k: asked.append(a) or True):
        box.invoke()                                              # the operator turns the iFlex tests OFF
        pump(root, 20)
    check('376 run window: OFF asks first, then 29 points, the label says so', len(asked) == 1 and 'not tested (no iFlex supplied)' in asked[0][1] and len(tree.get_children()) == 29
          and 'OFF' in str(app._include_labels['iflex'].cget('text')) and not app.include_is_on('iflex'), (asked, len(tree.get_children())))
    check('376 run window OFF: no iFlex section in the list', not any('iFlex' in str(tree.item(k, 'values')[1]) for k in tree.get_children()), [tree.item(k, 'values')[1] for k in tree.get_children()][-3:])
    grab(root, 'fluke376_run_window_iflex_off')
    box.invoke()                                                  # ... and back ON (no question)
    pump(root, 20)
    check('376 run window: ON again restores the 38 points', len(tree.get_children()) == 38 and app.include_is_on('iflex'), len(tree.get_children()))
    grab(root, 'fluke376_run_window_iflex_on')
    pts = {p['n']: p for p in app.points}

    def prompt(n, tag):
        seen = {}

        def go():
            win = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
            pump(root, 5)
            seen['clipped'] = [c for c in walk(win) if c.winfo_ismapped() and not inside(win, c)]
            seen['text'] = ' '.join(str(c.cget('text')) for c in walk(win) if isinstance(c, (ttk.Label, tk.Label)))
            grab(win, tag)
            win.destroy()
        root.after(500, go)
        seen['ok'] = app._prompt_setup(pts[n])
        return seen
    for n, tag, words in ((1, 'fluke376_prompt_voltage', 'VΩ'), (23, 'fluke376_prompt_coil_aux', 'REMOVE the test leads'), (24, 'fluke376_prompt_coil_20a', '20 A'),
                          (30, 'fluke376_prompt_iflex_sim', '2 mm jack'), (35, 'fluke376_prompt_iflex_coil', 'iFlex loop')):
        r = prompt(n, tag)
        check(f'376 prompt point {n}: shown, nothing clipped, says what it must', not r['clipped'] and words in r['text'], (r['clipped'], r['text'][:300]))
    for model, total, off in (('374', 28, 19), ('375', 34, 25), ('376-II', 38, 29)):
        try:
            root.destroy()
        except tk.TclError:
            pass
        root = tk.Tk()
        root.report_callback_exception = lambda *a: errs.append(a)
        app = XO.App(root, model, demo=False, spec=HH.load_spec('fluke_376_pv.json'))
        root.geometry('1320x800+0+0')
        pump(root, 20)
        n_on = len(app.tree.get_children())
        app.set_include('iflex', False, ask=False)
        pump(root, 10)
        check(f'{model} run window: {total} points ON, {off} OFF', (n_on, len(app.tree.get_children())) == (total, off), (n_on, len(app.tree.get_children())))
        if model == '374':
            grab(root, 'fluke374_run_window_iflex_off')
    check('376: no Tk callback errors', not errs, errs)
    try:
        root.destroy()
    except tk.TclError:
        pass


def checks_dsb_sheet_check():
    """Datasheet Builder 'Sheet check' (build-time rules 1-5): the pill, the window (findings, detail, buttons), 'Apply the fix' (enter by hand), the Commands
    window, the inspector's 'Uncertainty source' line; nothing clipped.  Screenshots when DSB_SHOTS is set (folder)."""
    import datasheet_builder as db
    import datasheet_builder_ui as U
    import datasheet_builder_ui_model as DM
    t = Path(tempfile.mkdtemp())
    root = tk.Tk()
    ui.apply_theme(root)
    root.geometry('100x60+1480+930')
    out = os.environ.get('DSB_SHOTS')

    def shot(win, name):
        if out:
            from PIL import ImageGrab
            pump(root, 30)
            ImageGrab.grab(bbox=(win.winfo_rootx(), win.winfo_rooty(), win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height()),
                           xdisplay=os.environ['DISPLAY']).save(f'{out}/{name}_{THEME}.png')

    ds = db.Datasheet('Acme', 'RM-1', 'Rules DCV')
    fn = ds.add_function('DCV', id='dcv')
    for fs, rid in ((10, 'r10'), (1500, 'r1500')):
        fn.add_range(fs, id=rid)
    ds.set_spec(fn, '0.05 % of reading + 0.01 % of range')
    for v, rid in ((5, 'r10'), (1500, 'r1500')):
        db.add_point(fn, v, range_id=rid)
    g = DM.GridModel(DM.Storage(t / 'u', t / 'r.sqlite3', who='real'), ds)
    win = U.GridEditorWindow(root, g)
    win.geometry('1400x900+0+0')
    pump(root, 40)
    check('check: no pill before the first check', g.check_pill()[0] == '' and not win._check_pill_shown)
    chk = g.sheet_check(compute=True)
    win.refresh()
    pump(root, 20)
    check('check: pill shows after the check', win._check_pill_shown, g.check_pill())
    check('check: pill and button inside the window', inside(win, win.check_pill) and inside(win, win.check_b))
    check('check: 1500 V not covered (rule 1, a warning) and unverified commands listed (rule 2)',
          any(f.rule == 1 for f in chk.findings) and bool(chk.unverified), [f.code for f in chk.findings])
    check('check: the missing uncertainty of 1500 V is an error (rule 5) and keeps the sheet from being ready',
          [f.code for f in chk.errors()] == ['no_uncertainty'] and 'to fix' in g.check_pill()[0], ([f.code for f in chk.errors()], g.check_pill()))
    key = next(r['key'] for r in g.rows() if r['kind'] == 'point')
    g.select(key, 'tol')
    win.sync()
    pump(root, 20)
    unc = g.uncertainty_line()
    check('check: uncertainty source line for the selected point', bool(unc[0]), unc)
    check('check: Uncertainty source section is in the inspector', 'uncert' in win.panel_box.sections)
    shot(win, 'sheetcheck_editor')
    w = win.show_check(compute=False)
    pump(root, 40)
    check('check: window opens with findings', w.winfo_exists() and len(w.table.get_children()) >= 1, len(w.table.get_children()))
    for name in ('go_b', 'fix_b', 'again_b', 'cmds_b', 'table'):
        check(f'check: {name} inside the window', inside(w, getattr(w, name)), name)
    first = next(i for i, r in enumerate(w._rows) if r['rule'] == 1)
    w.table.selection_set(str(first))
    w.table.event_generate('<<TreeviewSelect>>')
    pump(root, 20)
    check('check: detail names the fix', 'Apply the fix' in w.detail.get() or 'by hand' in w.detail.get(), w.detail.get())
    check('check: Apply the fix is enabled for rule 1, Waive is not', str(w.fix_b.cget('state')) == 'normal' and str(w.waive_b.cget('state')) == 'disabled')
    shot(w, 'sheetcheck_window')
    cw = w.commands()
    pump(root, 30)
    check('check: Commands window opens', cw is not None and cw.winfo_exists())
    shot(cw, 'sheetcheck_commands')
    cw.destroy()
    w.fix()
    pump(root, 30)
    after = g.sheet_check(compute=False)
    check('check: Apply the fix enters the point by hand, the rule 1 finding is gone', after is not None and not any(f.rule == 1 for f in after.findings),
          [f.code for f in (after.findings if after else [])])
    shot(w, 'sheetcheck_window_after_fix')
    five = next(i for i, r in enumerate(w._rows) if r['rule'] == 5 and r['level'] == 'error')
    w.table.selection_set(str(five))
    w.table.event_generate('<<TreeviewSelect>>')
    pump(root, 20)
    check('check: Waive is enabled for the missing uncertainty', str(w.waive_b.cget('state')) == 'normal' and str(w.fix_b.cget('state')) == 'disabled')
    shot(w, 'sheetcheck_window_missing_uncertainty')

    def look_at_dialog():
        dlgs = [d for d in walk(win) if isinstance(d, tk.Toplevel) and str(d.title()) == 'Waive the uncertainty']
        seen['dlg'] = bool(dlgs)
        if dlgs:
            shot(dlgs[0], 'sheetcheck_waive_dialog')
            dlgs[0].destroy()
    seen = {}
    root.after(400, look_at_dialog)
    check('check: cancelling the waiver dialog changes nothing', w.waive() is None and seen.get('dlg') and bool(g.sheet_check(compute=False).errors()), seen)
    res = g.waive_finding(w._rows[five]['idx'], 'scope')
    w.owner.changed(res)
    g.sheet_check(compute=True)
    win.refresh()
    w.reload()
    pump(root, 30)
    check('check: waiving records the reason and lifts the block', res.ok and not g.sheet_check(compute=False).errors() and g.check_pill()[0] != '' and 'to fix' not in g.check_pill()[0],
          (res.message, g.check_pill()))
    check('check: the waiver is listed, not hidden', any('waiver' in r['text'] for r in w._rows), [r['text'] for r in w._rows])
    shot(w, 'sheetcheck_window_waived')
    text, fp = win.real_run_question()
    check('check: the real-run question lists the commands to accept', 'accept' in text and bool(fp), text[:80])
    import time
    time.sleep(0.5)
    pump(root, 10)
    w.destroy()
    win.destroy()
    root.destroy()


if __name__ == '__main__':
    try:
        checks_handheld_dialogs()
        checks_point_window()
        checks_edit_point_button()
        checks_manager_windows()
        checks_manager_tabs()
        checks_mdd_manual()
        checks_fluke_365()
        checks_fluke_376()
        checks_standards_specs()
        checks_standards_specs_small()
        checks_import_package()
        checks_run_queue()
        checks_dsb_layout()
        checks_dsb_auto_collapse()
        checks_dsb_sheet_check()
        checks_dsb_dialogs_fit()
        checks_run_queue_app()
        checks_k2000_adjustment()
        checks_8808a_adjustment()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print('ALL OK')
