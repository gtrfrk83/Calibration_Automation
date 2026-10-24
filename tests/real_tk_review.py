"""Real-Tk checks of the review window (not a test module; needs a display).

    python tests/real_tk_review.py <light|dark> <shots dir> [demo]

Runs the window on the demo-filled Fluke 87V handheld engine and the Truevolt 34470A engine (dmm_export_harness.build_engine), drives it with real events
(row selection, bulk standard change, the per-row drop-down, filters, typing an uncertainty into a not-in-scope row, reset, Generate) and saves screenshots.
Prints one 'CHECK <name> ok' line per check."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures'), str(ROOT / 'tests')]
THEME = sys.argv[1] if len(sys.argv) > 1 else 'light'
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp())
DEMO = len(sys.argv) > 3 and sys.argv[3] == 'demo'
os.environ['CALSUITE_THEME'] = THEME
HOME = tempfile.mkdtemp()
os.environ['HOME'] = HOME
os.environ['CALSUITE_DATA'] = HOME + '/data'
SHOTS.mkdir(parents=True, exist_ok=True)

import tkinter as tk  # noqa: E402

import dmm_export_harness as D  # noqa: E402
import report_review as RR  # noqa: E402
import report_review_model as M  # noqa: E402
import ui_theme as ui  # noqa: E402

errors = []


def check(name, cond, detail=''):
    if not cond:
        raise AssertionError(f'{name}: {detail}')
    print(f'CHECK {name} ok')


def shot(root, name):
    root.update()
    subprocess.run(['import', '-window', 'root', str(SHOTS / f'{name}_{THEME}.png')], check=False)


def inside(win, w):
    win.update_idletasks()
    return w.winfo_ismapped() and win.winfo_rootx() <= w.winfo_rootx() and w.winfo_rootx() + w.winfo_width() <= win.winfo_rootx() + win.winfo_width() + 1 \
        and w.winfo_rooty() + w.winfo_height() <= win.winfo_rooty() + win.winfo_height() + 1


def click_cell(tree, iid, col):
    tree.see(iid)
    tree.update()
    bb = tree.bbox(iid, col)
    tree.event_generate('<Button-1>', x=bb[0] + 6, y=bb[1] + bb[3] // 2)
    tree.update()
    tree.update_idletasks()


def run(spec, tag):
    D.stub_tk()
    import ui_theme_core
    ui_theme_core.DEMO_SUFFIX = ' [DEMO]' if DEMO else ''          # the rebound values live in ui_theme_core (ui_theme.DEMO_SUFFIX reads through)
    root = tk.Tk()
    root.report_callback_exception = lambda *a: errors.append(a)
    ui.apply_theme(root)
    app, mod, pts = D.build_engine(spec, str(ROOT))
    app.root = root
    app.demo = DEMO
    for rec in list(app.found.values()) + list(app.left.values()):
        rec['synthetic'] = DEMO                                    # build_engine fills demo-labelled readings; a real-looking run is needed for the non-demo case
    for r in getattr(app, 'results', {}).values() if isinstance(getattr(app, 'results', None), dict) else []:
        if isinstance(r, dict):
            r['synthetic'] = DEMO
    out = {}

    def drive():
        try:
            w = RR.ReviewWindow.last
            win = w.win
            root.update()
            m = w.model
            check(f'{tag} window opens', win.winfo_exists() and str(win.title()).startswith('Review uncertainties'), win.title())
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            check(f'{tag} fits screen {sw}x{sh}', win.winfo_width() <= sw and win.winfo_height() <= sh, (win.winfo_width(), win.winfo_height()))
            for name in ('btn_ok', 'btn_reset', 'bulk_box', 'default_box'):
                check(f'{tag} visible {name}', inside(win, getattr(w, name)), name)
            check(f'{tag} grid rows', len(w.tree.get_children()) == len(m.rows), (len(w.tree.get_children()), len(m.rows)))
            def texts(wd):
                for c in wd.winfo_children():
                    yield str(c.cget('text')) if 'text' in c.keys() else ''
                    yield from texts(c)
            has = any('DEMO DATA - NOT CALIBRATION EVIDENCE' in t for t in texts(win))
            check(f'{tag} demo notice {"shown" if DEMO else "absent"}', has == DEMO and (not DEMO or 'DEMO' in win.title()), (has, win.title()))
            shot(root, f'{tag}_1_open')
            # filters
            w.filter.set('Changed by me'); w.refresh()
            check(f'{tag} changed filter empty', len(w.tree.get_children()) == 0)
            w.filter.set('Needs attention'); w.refresh()
            check(f'{tag} attention filter', len(w.tree.get_children()) == m.counts()['attention'], len(w.tree.get_children()))
            w.filter.set('All'); w.refresh()
            # select two free rows, bulk change
            free = [r.spec.idx for r in m.rows if not r.spec.locked and len(m.options(r.spec.idx)) > 1 and r.cur.status != M.NOT_IN_SCOPE][:2]
            check(f'{tag} two changeable rows', len(free) == 2, free)
            w.tree.selection_set([str(i) for i in free]); w.tree.update()
            check(f'{tag} bulk list offered', len(w.bulk_box.cget('values')) >= 2, w.bulk_box.cget('values'))
            other = [v for v in w.bulk_box.cget('values') if M.key_of(v) != m.rows[free[0]].spec.default_std][0]
            w.bulk_var.set(other); w.apply_bulk()
            check(f'{tag} bulk applied', m.counts()['changed'] == 2 and all(m.rows[i].changed for i in free), m.counts())
            check(f'{tag} changed badge', any(m.rows[i].status == M.CHANGED for i in free))
            check(f'{tag} pill text', w.pills['Standard changed'].cget('text').startswith('2 '), w.pills['Standard changed'].cget('text'))
            check(f'{tag} reported never below scope', all(r.cur.reported is None or r.cur.cmc is None or r.cur.reported >= r.cur.cmc for r in m.rows))
            shot(root, f'{tag}_2_bulk')
            # per-row drop-down by real click
            one = [r.spec.idx for r in m.rows if not r.spec.locked and len(m.options(r.spec.idx)) > 1 and not r.changed and r.cur.status != M.NOT_IN_SCOPE][0]
            click_cell(w.tree, str(one), '#4')
            root.update(); root.update()
            check(f'{tag} row editor opens', w.editor is not None and w.editor.winfo_exists())
            w.editor.set(M.label([k for k in m.options(one) if k != m.rows[one].spec.default_std][0]))
            w.editor.event_generate('<<ComboboxSelected>>'); root.update()
            check(f'{tag} row standard changed', m.rows[one].changed and m.counts()['changed'] == 3, m.counts())
            # locked rows have no editor
            locked = [r.spec.idx for r in m.rows if r.spec.locked]
            if locked:
                click_cell(w.tree, str(locked[0]), '#4'); root.update()
                check(f'{tag} locked row has no editor', w.editor is None)
            # not-in-scope row: typed uncertainty
            oos = [r.spec.idx for r in m.rows if r.can_type()]
            if oos:
                i = oos[0]
                w.filter.set('Needs attention'); w.refresh()
                click_cell(w.tree, str(i), '#7'); root.update(); root.update()
                check(f'{tag} typed editor opens', isinstance(w.editor, tk.Widget) and w.editor.winfo_exists() and w.editor.winfo_class() == 'TEntry', w.editor)
                check(f'{tag} hint shown', 'Type the uncertainty' in w.hint.get(), w.hint.get())
                w.editor.delete(0, 'end'); w.editor.insert(0, 'junk'); w.editor.event_generate('<Return>'); root.update()
                check(f'{tag} bad entry refused', m.rows[i].typed is None and w.hint.get() != '' and w.editor is not None, w.hint.get())
                w.editor.delete(0, 'end'); w.editor.insert(0, '12.5'); w.editor.event_generate('<Return>'); root.update()
                r = m.rows[i]
                check(f'{tag} typed kept', r.typed is not None and r.status == M.MANUAL, r.typed)
                shot(root, f'{tag}_3_manual')
                check(f'{tag} manual badge in grid', w.tree.set(str(i), 'status') == M.MANUAL, w.tree.set(str(i), 'status'))
                check(f'{tag} manual pill', w.pills[M.MANUAL].cget('text').startswith('1 '), w.pills[M.MANUAL].cget('text'))
                click_cell(w.tree, str(i), '#7'); root.update(); root.update()
                w.editor.delete(0, 'end'); w.editor.event_generate('<Return>'); root.update()
                check(f'{tag} cleared', r.typed is None and r.status == M.NOT_IN_SCOPE)
                click_cell(w.tree, str(i), '#7'); root.update(); root.update()
                w.editor.delete(0, 'end'); w.editor.insert(0, '12.5'); w.editor.event_generate('<Return>'); root.update()
                w.filter.set('All'); w.refresh()
            # in-scope row: reported cell is not editable
            ins = [r.spec.idx for r in m.rows if not r.spec.locked and not r.can_type()][0]
            click_cell(w.tree, str(ins), '#7'); root.update()
            check(f'{tag} in-scope reported not editable', w.editor is None)
            # default standard in the strip
            w.vars['technician'].set('Mike')
            shot(root, f'{tag}_4_final')
            # reset
            n = m.counts()['changed']
            w.reset()
            check(f'{tag} reset', m.counts()['changed'] == 0 and n >= 3)
            # redo one change and generate
            m.set_standard(free[0], other)
            w.refresh()
            w.btn_ok.invoke()
        except Exception as exc:                                    # noqa: BLE001
            import traceback
            traceback.print_exc()
            errors.append(exc)
            try:
                RR.ReviewWindow.last.win.destroy()
            except Exception:
                pass

    root.after(500, drive)
    details = RR.ask(root, f'{spec} performance verification', app=app)
    check(f'{tag} generate returns details', isinstance(details, dict) and details['technician'] == 'Mike' and 'uncertainty_review' in details, details and list(details))
    rev = details['uncertainty_review']['reviews'][0]
    check(f'{tag} record', rev['changed'] >= 1 and rev['changes'][0]['original_standard'] and rev['table'], rev['changed'])
    check(f'{tag} no callback errors', not errors, errors)
    root.destroy()


if __name__ == '__main__':
    run('handheld:Fluke 87V', 'hh')
    run('truevolt:34470A', 'tv')
    print('ALL OK')
