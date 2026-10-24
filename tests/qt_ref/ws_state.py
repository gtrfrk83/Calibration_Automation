"""The widget-state record of the WaveSurfer window, taken the same way on both toolkits (toolkit-free: the adapter does the widget reads).

`collect(app, ad)` drives the App through the same statements on Tk and on Qt (idle, a function busy, the RMS-noise run busy, demo data loaded, a row selected, the
filters) and records what the technician could see or press: the enabled state and text of every button the engine switches, the notebook's tab titles, each table's
headings / row count / rows / tags, the progress bars, the status texts, the chip, the section list, the title.  tests/qt_ref/make_tk_state.py writes the Tk record
(real Tk 9 under Xvfb) to wavesurfer_tk_state.json; tests/test_qt_view_wavesurfer.py takes the Qt record and requires the two to be equal.

Adapter `ad` (toolkit side): enabled(w) -> bool, text(w) -> str, title(app) -> str, tabs(app) -> [str], heading(tree, key) -> str, columns(tree) -> [key],
rows(tree) -> [(values, tags)], progress(bar) -> (value, maximum), combo_values(w) -> [str].
"""
from __future__ import annotations

BUTTONS = ('btn_run', 'btn_section', 'btn_rerun', 'btn_stop', 'btn_clear', 'btn_scope', 'start_button', 'stop_button', 'resume_button', 'retest_button', 'connect_button',
           'channel_select', 'dc_next_button', 'imp_next_button')
TREES = ('utree', 'tree', 'dc_tree', 'imp_tree', 'offset_tree', 'bw_tree', 'tb_tree', 'trig_tree')
BARS = ('progress', 'dc_progress', 'imp_progress', 'offset_progress', 'bw_progress')
STATUS = ('status', 'dc_status', 'imp_status', 'offset_status', 'bw_status', 'tb_status', 'trig_status', 'progress_text', 'detail')


def buttons(app, ad):
    out = {}
    for name in BUTTONS:
        w = getattr(app, name)
        out[name] = {'enabled': ad.enabled(w)}
        if name != 'channel_select':
            out[name]['text'] = ad.text(w)
    out['mode_buttons'] = [ad.enabled(b) for b in app.mode_buttons]
    return out


def tree_info(tree, ad, head=3, tail=2):
    cols = ad.columns(tree)
    rows = ad.rows(tree)
    norm = [([str(v) for v in values], sorted(tags)) for values, tags in rows]
    return dict(columns=cols, headings=[ad.heading(tree, c) for c in cols], n=len(rows), head=norm[:head], tail=norm[-tail:] if len(norm) > head else [])


def snapshot(app, ad, label):
    return dict(label=label, title=ad.title(app), buttons=buttons(app, ad), tabs=ad.tabs(app), chip=ad.text(app.conn_pill), msg=app.msg.get(),
                status={k: getattr(app, k).get() for k in STATUS},
                bars={k: [round(float(x)) for x in ad.progress(getattr(app, k))] for k in BARS},
                sections=[list(r) for r in app.shell.sections], show=[app.show_function.get(), app.show_status.get()],
                trees={k: tree_info(getattr(app, k), ad) for k in TREES})


def collect(app, ad):
    snaps = []
    app._unified_tick()
    snaps.append(snapshot(app, ad, 'idle'))
    app.dc_running = True                                   # a function is busy: the table's run buttons are off, Stop is on
    app._unified_tick()
    snaps.append(snapshot(app, ad, 'dcv busy'))
    app.dc_running = False
    app._unified_tick()
    app.set_running(True)                                   # the RMS-noise page while its run is going
    snaps.append(snapshot(app, ad, 'noise running'))
    app.set_running(False)
    app.load_demo_data()
    app.update_tab_titles()
    app._unified_tick()
    snaps.append(snapshot(app, ad, 'demo data'))
    for fn in ('RMS noise', 'DC voltage', 'Input impedance', 'Offset (P1 mean)', 'Bandwidth (LEVSINE)', 'Time base', 'Trigger level'):
        app._pick_function(fn)
        snaps.append(snapshot(app, ad, 'function ' + fn))
    app._pick_function('All functions')
    app.show_status.set('Failed (OOT)')
    app.refresh_unified(force=True)
    snaps.append(snapshot(app, ad, 'failed only'))
    app.show_status.set('All points')
    app.refresh_unified(force=True)
    return snaps
