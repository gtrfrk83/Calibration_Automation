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


if __name__ == '__main__':
    try:
        checks_point_window()
        checks_edit_point_button()
        checks_manager_windows()
        checks_import_package()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print('ALL OK')
