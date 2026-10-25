"""Screenshots (dark) of the bench verification windows for review, QT-G1a.  Not a test module.

    QT_QPA_PLATFORM=offscreen python tests/qt_bench_shots.py OUT_DIR [engine key ...]       (keys: see qt_bench_dump.engines(); default: one per engine module)

Per window: <key>_idle.png, <key>_drawer.png (connections drawer open), <key>_running.png (a run in progress: the Stop button live, the rest locked, the first points tested),
<key>_failures.png (finished, a few points out of limits), <key>_small.png (900 x 700: sidebar folded, short button texts), <key>_surprise.png (the Stop / Continue window
over the run window).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import qt_bench_harness as QH  # noqa: E402
import qt_bench_dump as D  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

DEFAULT = ('truevolt_34470A', 'dacq_34970A', 'dacq_34972A', 'k2000', 'f8808a', 'a34401a', 'f8846a', 'a34410a_34410A')


def surprise_shot(win, path):
    import surprise
    import surprise_view_qt
    s = surprise.Surprise('empty reply', 'DMM', 'READ?', '', 'a number', 'the meter did not answer', log_tail=['>> CONF:VOLT:DC 10,0.001', '>> READ?', '<< '], stop_only=False)
    dlg = surprise_view_qt.build(win, 'Stop on surprise', s)
    dlg.show()
    QTest.qWait(80)
    base = win.grab()
    top = dlg.grab()
    p = QPainter(base)
    p.fillRect(base.rect(), QColor(0, 0, 0, 110))
    p.drawPixmap((base.width() - top.width()) // 2, max(10, (base.height() - top.height()) // 3), top)
    p.end()
    base.save(str(path))
    dlg.close()


def main(out, keys):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    makers = dict(D.engines())
    for key in keys:
        hn = QH.QtHarness().start()
        try:
            app = makers[key](hn.root, True)
            app.asset.set('A-1234')
            app.serial.set('MY54001234')
            hn.app = app
            QH.show(hn.root)
            QH.shot(hn.root, out / f'{key}_idle.png')
            app.shell.open_drawer()
            QH.shot(hn.root, out / f'{key}_drawer.png')
            app.shell.close_drawer()
            pts = QH.points_of(app)
            for p in pts[:24]:                                              # a run in progress: the first points tested, the next one selected
                app._record(p, p['nominal'] + 0.2 * p['error'], True)
            app.tree.selection_set(str(pts[24]['id']))
            app._busy = True
            app._sync_buttons()
            app.status.set(f'Running point {pts[24]["id"]} of {len(pts)} ...')
            QH.shot(hn.root, out / f'{key}_running.png')
            app._busy = False
            app._sync_buttons()
            hn.run_all()
            QH.record_failures(app)
            app.tree.selection_set(str(pts[11]['id']))
            QH.shot(hn.root, out / f'{key}_failures.png')
            hn.root.resize(900, 700)
            QH.shot(hn.root, out / f'{key}_small.png')
            hn.root.resize(1320, 840)
            QTest.qWait(60)
            surprise_shot(hn.root, out / f'{key}_surprise.png')
            print('shots', key)
        finally:
            hn.stop()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:] or DEFAULT)
