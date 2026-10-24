"""Every qtui widget on one page, for looking at (and for the screenshots in the design review).

    python -m qtui.gallery                        # open the window
    python -m qtui.gallery --shots DIR            # headless: write gallery_*.png into DIR (QT_QPA_PLATFORM=offscreen)
"""
from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QMainWindow, QMenuBar, QPushButton, QRadioButton, QVBoxLayout, QWidget

from . import app, theme
from .table import Column, DataTable
from .widgets import (Badge, Banner, Card, DangerButton, EmptyState, GhostButton, InfoButton, KeyValueStrip, MessageDialog, ModalDialog, PrimaryButton,
                      ProgressDialog, SearchField, SecondaryButton, SectionHeader, SegmentedFilter, StatusLine, Toast, label, make_tab_bar, rule)

PROCS = [('WaveSurfer WS4104HD Verification', 'Teledyne LeCroy', 'WS4104HD', 'Oscilloscope', 'Ready'), ('Tektronix TDS2000C / TDS1000C-EDU', 'Tektronix', 'TDS2000C', 'Oscilloscope', 'Ready'),
         ('Klein Tools MM325 Performance Verification', 'Klein Tools', 'MM325', 'Digital Multimeter', 'Ready'), ('Keysight 34972A Performance Verification', 'Keysight', '34972A', 'Data Acquisition', 'Needs review'),
         ('Fluke 8846A Performance Verification', 'Fluke', '8846A', 'Digital Multimeter', 'Failed'), ('Keithley 2000 Guided Adjustment', 'Keithley', '2000', 'Digital Multimeter', 'Ready'),
         ('Fluke 117 Performance Verification', 'Fluke', '117', 'Handheld DMM', 'Running')]
BADGES = {'Ready': 'good', 'Needs review': 'warn', 'Failed': 'bad', 'Running': 'info'}


def demo_rows(n: int = 60) -> list[dict]:
    rows = []
    for i in range(n):
        p = PROCS[i % len(PROCS)]
        rows.append(dict(id=i, name=p[0] if i < len(PROCS) else f'{p[0]} (copy {i // len(PROCS)})', mfr=p[1], model=p[2], cat=p[3], status=p[4], reading=(i * 37 % 1000) / 7 * 1e-3,
                         std=['Fluke 5560A', 'Fluke 5522A', 'Fluke 5790B'][i % 3], pick=i % 4 == 0, done=((i * 13) % 101) / 100))
    return rows


def demo_columns() -> list[Column]:
    return [Column('pick', '', 44, kind='checkbox', editable=True, align='center'), Column('name', 'Procedure', 330, stretch=True), Column('mfr', 'Manufacturer', 130),
            Column('model', 'Model', 100, mono=True), Column('cat', 'Category', 150), Column('status', 'Status', 130, kind='badge', badge_map=BADGES),
            Column('reading', 'Reading (V)', 110, align='right', mono=True, fmt=lambda v: f'{v:.6f}'),
            Column('std', 'Standard', 150, kind='combo', editable=True, choices=['Fluke 5560A', 'Fluke 5522A', 'Fluke 5790B']), Column('done', 'Progress', 150, kind='progress')]


def build_window() -> QMainWindow:
    win = QMainWindow()
    win.setWindowTitle('qtui gallery')
    root = QWidget()
    root.setObjectName('root')
    win.setCentralWidget(root)
    mb = QMenuBar()
    m = mb.addMenu('File')
    m.addAction('Open...')
    m.addAction('Quit')
    mb.addMenu('Help').addAction('About')
    win.setMenuBar(mb)
    v = QVBoxLayout(root)
    v.setContentsMargins(24, 16, 24, 8)
    v.setSpacing(14)

    v.addWidget(SectionHeader('Calibration Procedure Manager', 'Run, document and maintain your calibration procedures.',
                              trailing=[label('Database: calibration_procedures.sqlite3', 'chip')]))
    v.addWidget(make_tab_bar(['Procedures', 'Asset History', 'Standards Specs', 'Datasheet Builder']))
    v.addWidget(make_tab_bar(['Automated Calibrations', 'Manual Calibrations', 'Adjustments'], sub=True))

    row = QHBoxLayout()
    row.setSpacing(10)
    row.addWidget(label('Find'))
    sf = SearchField('Search procedures')
    sf.setFixedWidth(240)
    row.addWidget(sf)
    cb = QComboBox()
    cb.addItems(['All categories', 'Oscilloscope', 'Digital Multimeter'])
    cb.setFixedWidth(200)
    row.addWidget(cb)
    row.addWidget(SecondaryButton('Clear'))
    row.addSpacing(16)
    row.addWidget(SegmentedFilter([('all', 'All', 31), ('attn', 'Needs attention', 6), ('mine', 'Changed by me', 1)]))
    row.addStretch(1)
    v.addLayout(row)

    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(14)
    v.addLayout(grid)

    # buttons
    c = Card('Buttons')
    r1 = QHBoxLayout()
    r1.setSpacing(10)
    r1.addWidget(PrimaryButton('Run'))
    r1.addWidget(SecondaryButton('Try in demo mode'))
    r1.addWidget(DangerButton('Delete run'))
    r1.addWidget(GhostButton('Learn more'))
    r1.addWidget(InfoButton('Run uses real instruments. Demo uses virtual instruments; nothing from a demo is calibration evidence.'))
    r1.addStretch(1)
    c.body.addLayout(r1)
    r2 = QHBoxLayout()
    r2.setSpacing(10)
    for cls, t in ((PrimaryButton, 'Run'), (SecondaryButton, 'Unlock...'), (DangerButton, 'Delete run'), (GhostButton, 'Learn more')):
        b = cls(t)
        b.setEnabled(False)
        r2.addWidget(b)
    r2.addWidget(label('disabled', 'hint'))
    r2.addStretch(1)
    c.body.addLayout(r2)
    r3 = QHBoxLayout()
    r3.setSpacing(10)
    foc = PrimaryButton('Focused')
    foc2 = SecondaryButton('Focused')
    foc3 = DangerButton('Focused')
    for b in (foc, foc2, foc3):
        r3.addWidget(b)
    r3.addWidget(label('focus ring (Tab)', 'hint'))
    r3.addStretch(1)
    c.body.addLayout(r3)
    grid.addWidget(c, 0, 0)
    win._focus_demo = foc2

    # badges + checks + fields
    c = Card('Badges, fields, checks')
    br = QHBoxLayout()
    br.setSpacing(8)
    for t, k in (('Ready to run', 'good'), ('Raised to scope', 'warn'), ('Not in scope', 'bad'), ('Standard changed', 'info'), ('NOT VERIFIED', 'neutral')):
        br.addWidget(Badge(t, k))
    br.addStretch(1)
    c.body.addLayout(br)
    br = QHBoxLayout()
    br.setSpacing(8)
    for t, k in (('24', 'good'), ('5', 'warn'), ('1', 'bad'), ('3', 'info'), ('0', 'neutral')):
        br.addWidget(Badge(t, k, small=True))
    br.addWidget(label('small', 'hint'))
    br.addStretch(1)
    c.body.addLayout(br)
    fr = QHBoxLayout()
    fr.setSpacing(10)
    e = QLineEdit('Asset 004512')
    f2 = QLineEdit()
    f2.setPlaceholderText('Placeholder text')
    f3 = QLineEdit('Disabled field')
    f3.setEnabled(False)
    f4 = QLineEdit('bad value')
    f4.setProperty('invalid', True)
    for w in (e, f2, f3, f4):
        fr.addWidget(w)
    c.body.addLayout(fr)
    kr = QHBoxLayout()
    kr.setSpacing(16)
    a1, a2, a3, a4 = QCheckBox('Fast demo (no windows)'), QCheckBox('Checked'), QCheckBox('Disabled'), QRadioButton('Radio')
    a2.setChecked(True)
    a3.setEnabled(False)
    a4.setChecked(True)
    for w in (a1, a2, a3, a4):
        kr.addWidget(w)
    kr.addStretch(1)
    c.body.addLayout(kr)
    grid.addWidget(c, 0, 1)

    # banners
    c = Card('Banners')
    c.body.addWidget(Banner('Run uses real instruments. Demo uses virtual instruments.', 'info'))
    c.body.addWidget(Banner('The scope minimum can never be undercut. Changing the standard recalculates the budget.', 'warn', title='Check the standard'))
    c.body.addWidget(Banner('<b>Step 1-17 is not in the lab scope.</b> The PDF will print "not covered by scope" for this point.', 'error', closable=True))
    c.body.addWidget(Banner('Report saved to C:/Reports/004512-10-24-2026.pdf', 'good'))
    grid.addWidget(c, 1, 0)

    c = Card('Key / value strip, empty state, status')
    c.body.addWidget(KeyValueStrip([('Technician', 'Mike'), ('Temperature', '22.4 C'), ('Humidity', '41 %'), ('Default standard', 'Fluke 5560A')], margin=12))
    es = EmptyState('No runs yet', 'Run a procedure and its results will be listed here.', action='Open Procedures')
    es.setMinimumHeight(170)
    c.body.addWidget(es)
    sl = []
    for t in ('Saved progress to disk', 'Measurement failed: timeout', 'Demo mode: results are not evidence', 'Select a procedure, then press Run.'):
        w = StatusLine(t)
        sl.append(w)
        c.body.addWidget(w)
    grid.addWidget(c, 1, 1)

    t = DataTable(demo_columns(), demo_rows(60), row_key=lambda r: r['id'],
                  row_tone=lambda r: {'Failed': 'fail', 'Needs review': 'warn'}.get(r['status']), frozen=False)
    t.setMinimumHeight(330)
    t.sort_by('name')
    t.select_rows([t.rows()[3]])
    win._table = t
    v.addWidget(t, 1)
    win._status = StatusLine('Select a procedure, then press Run (or Try in demo mode).')
    win.statusBar().addWidget(win._status)
    win.resize(1400, 1180)
    return win


def build_dialogs(parent) -> dict:
    out = {}
    d = ModalDialog(parent, 'Mark as verified', subtitle='Record that this procedure was checked against real hardware.')
    d.body.addWidget(label('Technician'))
    d.body.addWidget(QLineEdit('Mike'))
    d.body.addWidget(label('Notes'))
    d.body.addWidget(QLineEdit())
    d.add_button('Cancel', cancel=True)
    d.add_button('Mark verified', role='primary', default=True)
    out['dialog'] = d
    m = MessageDialog(parent, 'error', 'Measurement stopped', 'The multimeter did not answer. The calibrator output has been set to standby.', buttons=(('OK', 'ok', 'primary'),))
    out['message'] = m
    q = MessageDialog(parent, 'warning', 'HIGH VOLTAGE', 'This point outputs 1000 V. Make sure the leads are rated and nobody touches the connections. Enable output?',
                      buttons=(('Cancel', 'cancel', None), ('Enable output', 'yes', 'danger')), cancel_key='cancel')
    out['danger'] = q
    p = ProgressDialog(parent, 'Generating PDF', 'Rendering page 3 of 8...', maximum=8)
    p.set_progress(3, detail='Fluke 117, asset 004512')
    out['progress'] = p
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--shots', help='write PNGs into this folder and exit')
    ap.add_argument('--theme', default=None)
    a = ap.parse_args(argv)
    if a.shots:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    qa = app.create_app()
    if a.theme:
        theme.set_theme(a.theme)
    win = build_window()
    win.show()
    qa.processEvents()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
        win._focus_demo.setFocus(Qt.FocusReason.TabFocusReason)
        qa.processEvents()
        win.grab().save(os.path.join(a.shots, f'gallery_{theme.name()}.png'))
        for k, d in build_dialogs(win).items():
            d.show()
            qa.processEvents()
            d.grab().save(os.path.join(a.shots, f'dialog_{k}_{theme.name()}.png'))
            d.close()
        Toast.notify(win, 'Report saved', 'good', 5000)
        qa.processEvents()
        win.grab().save(os.path.join(a.shots, f'gallery_toast_{theme.name()}.png'))
        return 0
    return qa.exec()


if __name__ == '__main__':
    sys.exit(main())
