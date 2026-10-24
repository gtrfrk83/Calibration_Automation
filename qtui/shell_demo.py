"""A Shell filled with the sample rows of the 34410A demo bench (what the 34410A window shows in demo mode), for looking at the shell and for the screenshot tests.

    python -m qtui.shell_demo                        # open the window
    python -m qtui.shell_demo --shot out.png         # render it offscreen to a PNG and exit   (--size 1320x820, --drawer to show the connections drawer)

The rows come from the engine's own POINTS and DataModeMixin.shell_cells, so they are exactly the strings the real window shows; with no engine importable a few
synthetic rows are used.  Nothing is sent to an instrument.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow

from . import app as qapp
from . import shell_helpers as H
from .shell import Shell, results_table, small_window
from .vars import QtVar


class _FakeApp:
    """Just enough of the engine App for DataModeMixin.shell_cells / update_shell_progress / update_shell_sections."""

    def __init__(self, points, shell):
        import datamode
        self.is_left = False
        self.results, self.found, self.left = {}, {}, {}
        self.shell = shell
        for name in ('shell_cells', 'update_shell_progress', 'update_shell_sections'):
            setattr(self, name, getattr(datamode.DataModeMixin, name).__get__(self))
        self.points = points

    def row(self, p):
        cells, tags = self.shell_cells(p['id'], p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error'], p['unit'])
        return str(p['id']), (p['id'], p['description'], *cells), tags


def sample_points():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import agilent34410a_verification as E
        return list(E.POINTS), 'Keysight 34410A', E.SPEC['source']['note']
    except Exception:
        pts = [dict(id=i + 1, description=f'Sample point {i + 1}', nominal=float(i), error=0.01, unit='V', section_title='Sample') for i in range(30)]
        return pts, 'Keysight 34410A', 'Sample rows (the engine could not be imported).'


def build(win: QMainWindow, tested: int = 34, fail_at=(7,)) -> tuple[Shell, _FakeApp]:
    points, model, note = sample_points()
    sh = Shell(win, f'{model}  -  Performance Verification',
               f'Test points from the 34410A/11A/L4411A Service Guide, pp. 68-87  |  {len(points)} points in the spec  |  GPIB or USB',
               demo=True, on_section=lambda name: None, version='spec v1', virtual=True)
    app = _FakeApp(points, sh)
    sh.conn_pill = sh.add_chip('Demo - virtual instruments', 'neutral')
    asset, serial = QtVar('A-1234'), QtVar('MY5400123')
    sh.build_identity(asset, serial, focus=False)
    mode = QtVar('found')
    box = H.frame(None, 'h', spacing=8)
    box.layout().addWidget(H.label_(None, 'Collecting'))
    from .widgets import SegmentedFilter
    seg = SegmentedFilter([('found', 'As Found'), ('left', 'As Left')])
    seg.set_current('found')
    box.layout().addWidget(seg)
    sh.strip_layout.addWidget(box)
    app.summary = sh.build_progress()
    sh.notice('Demo mode: Virtual instruments are connected; commands go through the real drivers to simulated instruments, and every window of a real run appears. '
              'Nothing here is calibration evidence; reports are marked as demo data and are not recorded in Asset History.', 'warn', title='Demo mode')

    d = sh.drawer_body
    lay = d.layout()
    for r, (text, values) in enumerate((('Limits to apply', ['1 year (18 to 28 C)', '90 day', '24 hour']), ('Test set', ['Full verification', 'Quick check (Q points only)']))):
        lay.addWidget(H.label_(None, text), r, 0)
        lay.addWidget(H.combobox(None, None, values, width=22), r, 1)
    lay.addWidget(H.checkbutton(None, 'Include the optional tests (extra AC volts, AC current, capacitance)', QtVar(False, 'bool')), 2, 0, 1, 2)
    lay.addWidget(H.label_(None, f'{model} address / resource'), 3, 0)
    lay.addWidget(H.combobox(None, QtVar('USB0::0x2A8D::0x0101::MY54000123::INSTR'), ['GPIB0::22::INSTR'], width=30, state='normal'), 3, 1)
    note_l = H.label_(None, 'GPIB: the factory address is 22. USB: nothing to set on the meter; the resource is USB0::<mfgID>::<modID>::<serial>::INSTR. The IDs in the example '
                      'are not verified for your bench.', 'Muted.TLabel', wraplength=340)
    lay.addWidget(note_l, 4, 0, 1, 2)
    sh.drawer_footer_layout.insertWidget(0, H.button(None, 'Find instruments', lambda: None))
    sh.drawer_footer_layout.insertWidget(1, H.button(None, 'Test connections', lambda: None, style='Accent.TButton'))

    sh.btn_run = sh.add_action('▶  Run All Pending', lambda: None, accent=True, short='▶  Run')
    sh.add_action('Run Shown Section', lambda: None, short='Section')
    sh.add_action('Rerun Selected', lambda: None, short='Rerun')
    sh.btn_stop = sh.add_action('■  Stop', lambda: None, danger=True, short='■ Stop', state='disabled')
    sh.add_action('Export Report (PDF)', lambda: None, side='right', short='PDF')
    sh.add_action('Load progress', lambda: None, side='right', short='Load')
    sh.add_action('Save progress', lambda: None, side='right', short='Save')
    sh.status_var.set('DEMO MODE (virtual instruments): the windows of a real run appear and commands go to simulated instruments. Enter an Instrument ID, then press Run All.')

    body = sh.content
    filt = H.frame(None, 'h', spacing=8)
    pack_l = filt.layout()
    pack_l.addWidget(H.label_(None, 'Test points', 'Bold.TLabel'))
    pack_l.addStretch(1)
    pack_l.addWidget(H.label_(None, 'Show', 'Muted.TLabel'))
    pack_l.addWidget(H.combobox(None, QtVar('All points'), ['All points', 'Pending', 'Failed'], width=14))
    body.layout().addWidget(filt)
    body.layout().addSpacing(6)
    app.tree = results_table(app, body)
    small_window(app, app.tree, filt)
    info = H.frame(None, 'v', spacing=4)
    det = QtVar(f'{points[0]["description"]}\nAcceptable reading: -25 nA to 25 nA  (1 year limit)  |  Manual page 70')
    il = info.layout()
    il.addWidget(H.label_(None, '', 'Muted.TLabel', textvariable=det, wraplength=1000))
    il.addWidget(H.label_(None, note, 'Small.TLabel', wraplength=1000))
    body.layout().addSpacing(8)
    body.layout().addWidget(info)
    for n, p in enumerate(points[:tested]):
        res = 'FAIL' if n in fail_at else 'PASS'
        app.results[str(p['id'])] = app.found[str(p['id'])] = dict(reading=str(p['nominal'] + (p['error'] * 1.5 if res == 'FAIL' else p['error'] * 0.2)), result=res)
    app.tree.set_all([app.row(p) for p in points])
    app.update_shell_progress(points)
    app.update_shell_sections(points, lambda p: p['section_title'])
    return sh, app


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--shot', help='render offscreen to this PNG and exit')
    ap.add_argument('--size', default='1320x820')
    ap.add_argument('--drawer', action='store_true')
    a = ap.parse_args(argv)
    if a.shot:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    qapp.create_app()
    w, h = (int(x) for x in a.size.split('x'))
    win = QMainWindow()
    win.setWindowTitle('Keysight 34410A | Performance Verification [DEMO]')
    sh, _app = build(win)
    win.resize(w, h)
    win.show()
    for _ in range(5):
        QApplication.processEvents()
    if a.drawer:
        sh.open_drawer()
        QApplication.processEvents()
    if a.shot:
        QApplication.processEvents()
        win.grab().save(a.shot)
        return 0
    return QApplication.instance().exec()


if __name__ == '__main__':
    sys.exit(main())
