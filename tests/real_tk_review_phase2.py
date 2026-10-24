"""Real-Tk checks of the review window on the phase-2 engines (not a test module; needs a display).

    python tests/real_tk_review_phase2.py <light|dark> <shots dir> [engines, e.g. mdo,fgen,tds,ws]

The engine Apps come from tests/phase2_apps.py (simulated benches); the window is found through report_review.find_app exactly as in production
(app.root is the real root).  Drives: open, fits the screen, locked rows have no drop-down, a changeable row's drop-down (MDO / WaveSurfer), typing an
uncertainty into a Not-in-scope row, an in-scope row refuses typing, Reset, Generate.  Prints one 'CHECK <name> ok' line per check."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures'), str(ROOT / 'tests')]
THEME = sys.argv[1] if len(sys.argv) > 1 else 'light'
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp())
ONLY = sys.argv[3].split(',') if len(sys.argv) > 3 else ['mdo', 'fgen', 'tds', 'ws']
os.environ['CALSUITE_THEME'] = THEME
HOME = tempfile.mkdtemp()
os.environ['HOME'] = HOME
os.environ['CALSUITE_DATA'] = HOME + '/data'
SHOTS.mkdir(parents=True, exist_ok=True)

import tkinter as tk  # noqa: E402

import phase2_apps as P  # noqa: E402
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


def run(tag):
    app, mod = P.BUILDERS[tag]()
    root = tk.Tk()
    root.report_callback_exception = lambda *a: errors.append(a)
    ui.apply_theme(root)
    app.root = root

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
            shot(root, f'{tag}_1_open')
            w.filter.set('Needs attention'); w.refresh()
            check(f'{tag} attention filter', len(w.tree.get_children()) == m.counts()['attention'], len(w.tree.get_children()))
            attention_only = all(m.rows[int(i)].needs_attention for i in w.tree.get_children())
            check(f'{tag} attention = not-in-scope or manual only', attention_only)
            shot(root, f'{tag}_2_attention')
            w.filter.set('All'); w.refresh()
            locked = [r.spec.idx for r in m.rows if r.spec.locked]
            if locked:
                click_cell(w.tree, str(locked[0]), '#4'); root.update()
                check(f'{tag} locked row has no editor', w.editor is None)
            free = [r.spec.idx for r in m.rows if not r.spec.locked and len(m.options(r.spec.idx)) > 1]
            if free:
                i = free[0]
                click_cell(w.tree, str(i), '#4'); root.update(); root.update()
                check(f'{tag} drop-down opens', w.editor is not None and w.editor.winfo_exists())
                new = [k for k in m.options(i) if k != m.rows[i].spec.default_std][0]
                w.editor.set(M.label(new)); w.editor.event_generate('<<ComboboxSelected>>'); root.update()
                r = m.rows[i]
                check(f'{tag} standard changed', r.std_changed and r.cur.standard == new, (r.status, r.cur.standard))
                check(f'{tag} reported never below scope', r.cur.cmc is None or r.cur.reported is None or r.cur.reported >= r.cur.cmc)
                shot(root, f'{tag}_3_changed')
            oos = [r.spec.idx for r in m.rows if r.can_type()]
            if oos:
                i = oos[0]
                w.filter.set('Needs attention'); w.refresh()
                click_cell(w.tree, str(i), '#7'); root.update(); root.update()
                check(f'{tag} typed editor opens', isinstance(w.editor, tk.Widget) and w.editor.winfo_class() == 'TEntry')
                w.editor.delete(0, 'end'); w.editor.insert(0, 'junk'); w.editor.event_generate('<Return>'); root.update()
                check(f'{tag} bad entry refused', m.rows[i].typed is None)
                w.editor.delete(0, 'end'); w.editor.insert(0, '0.5'); w.editor.event_generate('<Return>'); root.update()
                check(f'{tag} typed kept', m.rows[i].typed is not None and m.rows[i].status == M.MANUAL, m.rows[i].status)
                shot(root, f'{tag}_4_manual')
                w.filter.set('All'); w.refresh()
            ins = [r.spec.idx for r in m.rows if not r.can_type() and (r.spec.locked or r.cur.status != M.NOT_IN_SCOPE)]
            click_cell(w.tree, str(ins[0]), '#7'); root.update()
            check(f'{tag} in-scope reported not editable', w.editor is None)
            w.vars['technician'].set('Mike')
            n = m.counts()['changed']
            w.reset()
            check(f'{tag} reset', m.counts()['changed'] == 0)
            if free:
                m.set_standard(free[0], new); w.refresh()
            elif oos:
                m.set_typed(oos[0], '0.5'); w.refresh()
            shot(root, f'{tag}_5_final')
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
    details = RR.ask(root, f'{tag} performance verification', app=app)
    check(f'{tag} generate returns details', isinstance(details, dict) and details['technician'] == 'Mike' and 'uncertainty_review' in details,
          details and list(details))
    rev = details['uncertainty_review']['reviews'][0]
    check(f'{tag} record', rev['changed'] >= 1 and rev['table'], rev['changed'])
    check(f'{tag} no callback errors', not errors, errors)
    root.destroy()


P.BUILDERS = {'mdo': P.mdo_app, 'fgen': P.fgen_app, 'tds': P.tds_app, 'ws': P.wavesurfer_app}
if __name__ == '__main__':
    for t in ONLY:
        run(t)
    print('ALL OK')
