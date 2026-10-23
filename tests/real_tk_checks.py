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
    win.model.select(key, 'tol')
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
        g.select(key, 'tol')
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
        check(f'{tag}: four grid columns', len(win.sheet.geo.widths) == 4 and DM.COL_KEYS == ('step', 'function', 'nominal', 'tol'))
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
        before = g.cell_text(key, 'tol')
        box.v['fs'].set('0.01')
        e = next(x for x in box.entries if str(x.cget('textvariable')) == str(box.v['iv']))
        box.types['iv'].set(True), box.v['iv'].set('0.05')
        e.focus_force()
        pump(root, 5)
        e.event_generate('<Return>')
        pump(root, 10)
        check(f'{tag}: Enter in a box applies', g.cell_text(key, 'tol') != before or 'calculated' in win.status.get().lower() or win.note.get() != '', (before, g.cell_text(key, 'tol'), win.note.get()))
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


if __name__ == '__main__':
    try:
        checks_handheld_dialogs()
        checks_point_window()
        checks_edit_point_button()
        checks_manager_windows()
        checks_import_package()
        checks_run_queue()
        checks_dsb_layout()
        checks_dsb_auto_collapse()
        checks_dsb_dialogs_fit()
        checks_run_queue_app()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print('ALL OK')
