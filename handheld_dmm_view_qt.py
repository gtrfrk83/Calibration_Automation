"""Handheld meter engine (handheld_dmm.App, iflex_option.App and the user-built datasheets): the Qt window code.  The twin of handheld_dmm_view_tk.py with the same
public functions, so the engine reaches either through `ui_port.ui.view('handheld_dmm_view')`:

    setup_window(self) / finish_window(self) / build_ui(self) / sync_buttons(self, busy)         the main window (qtui.shell.Shell: header, strip, drawer, results table)
    table_selection / table_has / table_select / table_set_rows / table_update_row / set_choices   the results table and the address box
    ask_reading(parent, p, total, ...)  /  ask_ir_problem(parent, p, total, problems, shown)  /  ask_range(parent, p, total, dial, standby_text)      the three modal windows

`self` is the engine's App.  Every label, button name, default button, keyboard shortcut, validation message and answer of the Tk windows is kept; only the look is the Qt
design system's (cards, tokens, high-DPI).  The modal windows are classes (ReadingDialog, IrProblemDialog, RangeDialog) a test can build, drive and read without a
modal loop; the functions build one, run it modally on the UI thread (also when an engine calls from a worker) and return its answer.  Nothing here decides anything
about a calibration, and nothing talks to an instrument.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, QPointF, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import calibrator_fit
import datamode
import labregistry
import virtualbench
from handheld_dmm import HERE, OUTPUT_ON_NOTE, READING_WIDTH, describe, limit_line
from qtui import prompts, theme
from qtui.bench_view import DetailBox, fit_wrapped, share_columns
from qtui import shell_helpers as H
from qtui.screens import common
from qtui.shell import Shell, results_table, small_window
from qtui.vars import QtVar, bind
from qtui.widgets import Card, ModalDialog, label

import ui_theme_core as core


# ============================================================================================================ main window
class _After:
    """The `root.after(ms, fn)` / `root.after_cancel(handle)` pair labregistry.attach uses, on Qt timers owned by the main window."""

    def __init__(self, root):
        self.root = root

    def after(self, ms, fn, *args):
        timer = QTimer(self.root)
        timer.setSingleShot(True)

        def fire():
            timer.deleteLater()
            fn(*args)
        timer.timeout.connect(fire)
        timer.start(max(0, int(ms)))
        return timer

    def after_cancel(self, handle):
        try:
            handle.stop()
            handle.deleteLater()
        except RuntimeError:
            pass


class QueueChip(H.Pill):
    """The 'Run queue: n meters' chip.  The engine shows and hides it with the Tk calls winfo_manager() / pack() / pack_forget(); here they show and hide the badge."""

    MAX_W = 230                                    # a long queue description may not squeeze the window title (the full text is the tooltip)

    def __init__(self, text='', kind='info'):
        super().__init__(None, text, kind)
        self._packed = False
        self._full = text
        self.setVisible(False)

    def setText(self, text):
        self._full = str(text)
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, self.MAX_W - 24))
        self.setToolTip(self._full if fm.horizontalAdvance(self._full) > self.MAX_W - 24 else '')

    def text_full(self):
        return self._full

    def winfo_manager(self):
        return 'pack' if self._packed else ''

    def pack(self, **_kw):
        self._packed = True
        self.setVisible(True)

    def pack_forget(self):
        self._packed = False
        self.setVisible(False)


def setup_window(self):
    """Theme, title and size of the main window (the first window statements of the engine's former App.__init__)."""
    root = self.root
    H.apply_theme(root)
    root.setWindowTitle(f'{self.info["name"]} | Performance Verification' + (' [DEMO]' if self.demo else ''))
    H.fit_window(root, 1320, 800, min_w=1000, min_h=640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statement of the engine's former App.__init__)."""
    labregistry.attach(_After(self.root), self.asset, self.serial, self.status.set)


def _note(text, role='sub'):
    lab = label(text, role, wrap=True)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    return lab                                  # no maximum width: a grid computes the row height for the cell width, so a narrower label would be clipped


def _scrolling_note(lab, max_lines=3):
    """The spec's long note under the table (the 376 family's runs to six lines): at most `max_lines` high, the rest scrolls, so it never pushes over the table."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setStyleSheet('QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }')
    area.viewport().setAutoFillBackground(False)
    area.setWidget(lab)
    area.setMaximumHeight(max_lines * lab.fontMetrics().lineSpacing() + 4)
    area.setAccessibleName('Procedure note')
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return area


def build_ui(self):
    from handheld_dmm import READ_TYPED, READ_IR                    # the engine's constants, read at call time
    root = self.root
    src = self.spec['source']
    sh = self.shell = Shell(root, f'{self.info["name"]}  -  Performance Verification',
                            f'Manual-reading procedure: the calibrator output is set for you, you read the meter  |  {len(self.points)} points  |  {src["document"]}',
                            demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    if self.queue_supported():
        self.queue_pill = QueueChip()                              # 'Run queue: n meters', shown only while a queue of two or more is set
        sh._chips.addWidget(self.queue_pill)
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo:
        sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else:
        extra = ' You are prompted to turn the dial to each range and to change cables, with a hook-up diagram.' if self.spec.get('options', {}).get('range_prompt') else ''
        sh.notice('For each point the calibrator is programmed and enabled, then you read the meter and type the value exactly as displayed (without the unit). '
                  'Wiring and high-voltage confirmations are required.' + extra + ' Check the meter fuses and battery before starting.', 'info')

    d = sh.drawer_body
    W = Qt.AlignmentFlag
    lay = d.layout()
    lay.addWidget(H.label_(None, 'Model'), 0, 0, W.AlignLeft)
    lay.addWidget(H.label_(None, self.info['name'], 'Bold.TLabel'), 0, 1, W.AlignLeft)
    lay.addWidget(_note(self.info.get('model_note', 'the "C" version uses the same steps')), 1, 0, 1, 2)
    lay.addWidget(H.separator(), 2, 0, 1, 2)
    lay.setRowMinimumHeight(2, 20)
    lay.addWidget(H.label_(None, 'Calibrator'), 3, 0, W.AlignLeft | W.AlignTop)
    calbox = H.frame(None, 'v')
    self.cal_combo = H.combobox(None, self.cal_mode, values=self.cal_choices(), state='readonly', width=34)
    self.cal_combo.setAccessibleName('Calibrator')
    calbox.layout().addWidget(self.cal_combo)
    calibrator_fit.attach_note(calbox, self.cal_offer, None, widgets=(self.cal_combo,), wrap=250).setMaximumWidth(16777215)         # (same reason)
    lay.addWidget(calbox, 3, 1)
    lay.addWidget(H.label_(None, 'Address'), 4, 0, W.AlignLeft)
    self.cal_entry = H.combobox(None, self.cal_addr, state='normal', width=34)
    self.cal_entry.setAccessibleName('Calibrator address')
    lay.addWidget(self.cal_entry, 4, 1)
    lay.addWidget(H.label_(None, 'Baud'), 5, 0, W.AlignLeft)
    baud = H.combobox(None, self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly')
    baud.setAccessibleName('Baud')
    lay.addWidget(baud, 5, 1, W.AlignLeft)
    lay.addWidget(_note('Examples: COM9   ASRL9::INSTR   GPIB0::6::INSTR.  In Manual mode the program tells you what to set and you press OPERATE yourself.'), 6, 0, 1, 2)
    if self.ir:
        lay.addWidget(H.separator(), 7, 0, 1, 2)
        lay.setRowMinimumHeight(7, 24)
        lay.addWidget(H.label_(None, 'Meter reading'), 8, 0, W.AlignLeft)
        mode = H.combobox(None, self.read_mode, values=[READ_TYPED, READ_IR], state='readonly', width=34)
        mode.setAccessibleName('Meter reading')
        lay.addWidget(mode, 8, 1)
        lay.addWidget(H.label_(None, 'IR cable port'), 9, 0, W.AlignLeft)
        irrow = H.frame(None, 'h', spacing=8)
        ir_entry = H.entry(None, self.ir_addr, width=9)
        ir_entry.setFixedWidth(100)
        ir_entry.setAccessibleName('IR cable port')
        irrow.layout().addWidget(ir_entry)
        self.btn_ir = H.button(None, 'Test IR', self.test_ir)
        irrow.layout().addWidget(self.btn_ir)
        irrow.layout().addStretch(1)
        lay.addWidget(irrow, 9, 1, W.AlignLeft)
        lay.addWidget(_note('Read over IR needs the Fluke IR-to-USB cable on the meter\'s IR port (115200 baud). Without it, choose Type the reading.'), 10, 0, 1, 2)
    if self.virtual:
        lay.addWidget(H.separator(), 11, 0, 1, 2)
        lay.setRowMinimumHeight(11, 24)
        self.demo_failures = QtVar(False, 'bool')
        lay.addWidget(H.checkbutton(None, 'Demo: include some failures in the simulated fill', self.demo_failures), 12, 0, 1, 2)
        lay.addWidget(_note('The calibrator is a virtual 5522A / 5560A (simulated). Press Test connection to connect it; no cable or address is needed. '
                            'The "Fill with a simulated reading" button in the reading window enters a made-up value; you may type your own.'), 13, 0, 1, 2)
    if self.queue_supported():
        self.build_queue_drawer(d, 14)
    foot = sh.drawer_footer_layout
    self.btn_find = H.button(None, 'Find instruments', self.find_instruments)
    self.btn_test = H.button(None, 'Test connection', self.test_connection, style='Accent.TButton')
    foot.insertWidget(0, self.btn_find)
    foot.insertWidget(1, self.btn_test)

    self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
    self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
    self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
    self.btn_rerun_from = sh.add_action('Rerun From Selected', self.rerun_from, short='From here')
    self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
    sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
    self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
    sh.add_action('Save progress', self.save, side='right', short='Save')
    self.pm_live_attach(sh)                                    # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well, usable during a run

    body = sh.content
    filt = H.frame(None, 'h', spacing=8)
    self.filter_bar = filt
    fl = filt.layout()
    fl.addWidget(H.label_(None, 'Test points', 'Bold.TLabel'))
    picker = sh.build_section_picker(filt)                     # the small-window drop-down stands where the sidebar is
    fl.addStretch(1)
    fl.addWidget(H.label_(None, 'Show', 'Muted.TLabel'))
    c2 = H.combobox(None, self.show_status, values=datamode.STATUS_FILTERS, width=14, state='readonly', command=self.refresh)
    c2.setAccessibleName('Show')
    fl.addWidget(c2)
    body.layout().addWidget(filt)
    body.layout().addSpacing(6)
    self.tree = results_table(self, body, name_width=330, nominal_title='Calibrator output', error=False)
    self.tree.column('nominal', width=150)
    small_window(self, self.tree, filt, picker=picker)
    self.tree.setMinimumHeight(theme.M.header_h + 3 * theme.M.row_h)          # the table gives way first when the window is small
    share_columns(self.tree, sh, nominal=150)
    info = H.frame(None, 'v', spacing=4)
    detail = H.label_(None, '', 'Muted.TLabel', textvariable=self.detail, wraplength=1000)
    detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    note = H.label_(None, src['note'], 'Small.TLabel', wraplength=1000)
    note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    info.layout().addWidget(fit_wrapped(detail, self.detail))
    info.layout().addWidget(fit_wrapped(note))
    box = DetailBox(info)                                         # the long 376 note scrolls inside its own box: at the 1000 x 640 minimum it can no longer paint over the table
    box.setAccessibleName('Procedure note')
    body.layout().addSpacing(8)
    body.layout().addWidget(box)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    self.refresh()
    H.polish(root)


def sync_buttons(self, value):
    """The run buttons while a run is active (the engine's former `busy` setter body)."""
    for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_rerun_from, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
        common.set_button_state(b, not value)
    common.set_button_state(self.btn_stop, bool(value))


# ---- results table and address box
def table_selection(self):
    return self.tree.selection()


def table_has(self, iid):
    return self.tree.exists(iid)


def table_select(self, iid, see=False):
    self.tree.selection_set(iid)
    if see:
        self.tree.see(iid)


def table_set_rows(self, rows, keep):
    """rows: iterable of (iid, values, tags); keep: the selection before the refresh (the first row of it is selected again if it is still there)."""
    self.tree.set_all(list(rows), tuple(keep[:1]) if keep else ())


def table_update_row(self, iid, values, tags):
    self.tree.item(iid, values=values, tags=tags)


def set_choices(self, which, values):
    """The drop-down values of the calibrator address box ('cal')."""
    self.cal_entry.configure(values=values)


# ============================================================================================================ shared bits of the modal windows
def _demo_suffix() -> str:
    return getattr(core, 'DEMO_SUFFIX', '') or ''


class _ToneText(common.ToneLabel):
    """A plain-text label whose colour is a theme token and whose size / weight / family are set in its own style sheet (the application style sheet's
    `* { font-size }` rule would override a QWidget.setFont())."""
    _size, _bold, _mono = None, False, False

    def __init__(self, tone, text, size=None, bold=False, mono=False):
        super().__init__(tone, text)
        self._size, self._bold, self._mono = size, bold, mono
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._retone()

    def _retone(self, *_):
        try:
            css = f'color: {theme.tokens()[self._tone]};'
            if self._size:
                css += f' font-size: {self._size}px;'
            if self._bold:
                css += ' font-weight: 700;'
            if self._mono:
                css += f" font-family: '{theme.mono_family()}';"
            self.setStyleSheet(css)
        except RuntimeError:
            pass


def _caps(text, tone='muted'):
    """The small bold caption above a block ('ACCEPT IF', 'METER SHOULD BE' ...)."""
    return _ToneText(tone, text, size=theme.M.font_small, bold=True)


def _bold(text, tone='text', size=None, mono=False):
    return _ToneText(tone, text, size=size, bold=True, mono=mono)


def _big_edit(edit, size):
    edit.setStyleSheet(f"font-size: {size}px; font-weight: 700; font-family: '{theme.mono_family()}';")


def _plain(text, role=None, wrap=True):
    return prompts.plain_label(text, role, wrap=wrap)


def _marker(done: bool) -> QLabel:
    """The round marker of a card: a green tick circle (done) or an empty circle."""
    mark = QLabel()
    t = theme.tokens()
    mark.setPixmap(theme.pixmap('good' if done else 'dot', t['good' if done else 'muted'], 22))
    mark.setFixedSize(22, 22)
    mark.setAccessibleName('done' if done else 'not done yet')
    return mark


def _stop_left(dlg: ModalDialog) -> None:
    """The Tk windows put 'Stop run' at the left edge and the other buttons at the right: drop the base class's leading stretch, re-add it after Stop."""
    dlg._button_row.takeAt(0)


# ============================================================================================================ the reading dialog
class ReadingDialog(ModalDialog):
    """One modal window for one point: mode 'numeric' (type the display) or 'yesno' (answer a question).  `answer` = dict(action='record'|'skip'|'stop', text=, ann=, yes=).
    Enter records; closing the window (or Esc) is Stop run; a record with an unusable entry shows the reason and stays open."""

    def __init__(self, parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                 limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None):
        super().__init__(common.qparent(parent), f'Point {p["n"]} of {total}{_demo_suffix()}', width=READING_WIDTH + 2 * theme.M.xl)
        self.title_label.hide()
        self.answer = dict(action='stop', text='', ann=False, yes=None)
        self.mode, self.validate, self.on_expire, self.demo_fill = mode, validate, on_expire, demo_fill
        self.p = p
        self._expired = False
        self.body.addWidget(_plain(f'Point {p["n"]} of {total}  -  {p["section"]}' + (f'  -  {phase}' if phase else ''), 'hint'))
        self.heading_label = _plain(describe(p), 'h2')
        self.body.addWidget(self.heading_label)

        meter = p.get('dsb_device') or (f'Rotary switch / function: {p["switch"]}' + (f'\nRange: {p["range"]}' if p['range'] else ''))
        self.device_card = self._row_card(device, meter, p.get('note'), True)                  # the operator has just confirmed the meter set-up (function / hook-up prompts)
        self.source_card = None
        if p.get('applied') or p['group'] != 'NONE':
            self.source_card = self._row_card(source, out_text, out_note, str(out_note).startswith(OUTPUT_ON_NOTE), metric=True)

        self.counter = common.ToneLabel('bad')
        self.counter.setTextFormat(Qt.TextFormat.PlainText)
        self.counter.setVisible(limit_s is not None)
        self.body.addWidget(self.counter)
        self._end = None
        self._clock = None
        if limit_s is not None:
            self._end = time.monotonic() + max(0.0, limit_s)
            self._clock = QTimer(self)
            self._clock.setInterval(250)
            self._clock.timeout.connect(self._tick)
            self._tick()
            self._clock.start()
            self.finished.connect(lambda _r: self._clock.stop())

        # ---- the reading card (outlined in the accent colour)
        self.entry = None
        self.ann_box = None
        self.yes = QtVar('')
        self.radios = {}
        card = QFrame()
        card.setObjectName('readingCard')
        card.setStyleSheet(common.tone_css('QFrame#readingCard', border='2px solid {primary}', border_radius='10px', background='{card}'))
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(4)
        if mode == 'numeric':
            cl.addWidget(_caps(f'WHAT DOES THE {device} SHOW?', 'primary'))
            row = QHBoxLayout()
            row.setSpacing(10)
            self.entry = QLineEdit()
            _big_edit(self.entry, 22)
            self.entry.setFixedWidth(210)
            self.entry.setAccessibleName(f'Reading of the {device.lower()}')
            self.entry.textChanged.connect(lambda _t: self.error.setText(''))
            row.addWidget(self.entry)
            self.unit_label = _plain(unit, 'h2', wrap=False)
            row.addWidget(self.unit_label)
            row.addStretch(1)
            cl.addLayout(row)
            if annunciator:
                self.ann_box = QCheckBox('The AC annunciator is ON')
                cl.addWidget(self.ann_box)
        else:
            cl.addWidget(_caps('YOUR ANSWER', 'primary'))
            cl.addWidget(_bold(question or '', size=theme.M.font_base + 1))
            row = QHBoxLayout()
            row.setSpacing(16)
            for value, text in (('y', 'Yes - as stated'), ('n', 'No - it does not')):
                r = QRadioButton(text)
                bind(r, self.yes, value=value)
                r.toggled.connect(lambda _on: self.error.setText(''))
                self.radios[value] = r
                row.addWidget(r)
            row.addStretch(1)
            cl.addLayout(row)
        self.error = common.ToneLabel('bad')
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        cl.addWidget(self.error)
        cl.addWidget(_caps('ACCEPT IF'))
        self.accept_label = _bold(accept)
        cl.addWidget(self.accept_label)
        self.limit_label = None
        if p.get('tol_text'):
            self.limit_label = _plain('Limit: ' + limit_line(p), 'hint')
            cl.addWidget(self.limit_label)
        self.fill_button = None
        if demo_fill is not None:                   # demo only: a clearly marked helper; the operator may type anything instead
            self.fill_button = QPushButton(virtualbench.FILL_TEXT)
            self.fill_button.setAutoDefault(False)
            self.fill_button.clicked.connect(self.fill)
            fr = QHBoxLayout()
            fr.addWidget(self.fill_button)
            fr.addStretch(1)
            cl.addSpacing(6)
            cl.addLayout(fr)
            cl.addWidget(common.ToneLabel('warn', 'DEMO: this value is made up by the program; you may type any reading you like. Nothing here is calibration evidence.'))
        self.body.addWidget(card)

        _stop_left(self)
        self.stop_button = self.add_button('Stop run', role='danger', result='stop', cancel=True, callback=self._stop)
        self._button_row.addStretch(1)
        self.skip_button = self.add_button('Skip point', result='skip', callback=self._skip)
        self.record_button = self.add_button('Record  (Enter)', role='primary', result='record', default=True, callback=self._record)
        self.initial_focus = self.entry or self.record_button
        prompts.fit_dialog(self, READING_WIDTH + 2 * theme.M.xl)

    # ---- cards
    def _row_card(self, caption, big, note, done, metric=False):
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_marker(done), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_caps(caption))
        big_label = _bold(big, size=22 if metric else None, mono=metric)
        col.addWidget(big_label)
        note_label = None
        if note:
            note_label = common.hint(str(note))
            note_label.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(note_label)
        row.addLayout(col, 1)
        card.body.addLayout(row)
        card.big_label, card.note_label = big_label, note_label
        self.body.addWidget(card)
        return card

    # ---- the clock
    def _tick(self):
        left = self._end - time.monotonic()
        if left <= 0:
            if not self._expired:
                self._expired = True
                if self.on_expire:
                    self.on_expire()
            self.counter.setText('Time limit reached - the output has been switched off. Enter the reading you saw.' if self.on_expire
                                 else 'Time limit reached - put the calibrator in STANDBY now, then enter the reading.')
            if self._clock is not None:
                self._clock.stop()
            return
        self.counter.setText(f'Take the reading within {left:.0f} s - the output switches off automatically.' if self.on_expire
                             else f'Take the reading within {left:.0f} s, then put the calibrator in STANDBY.')

    # ---- demo
    def fill(self):
        value = self.demo_fill()
        if self.mode == 'numeric':
            self.entry.setText(value)
            self.entry.setFocus()
        else:
            self.yes.set('y' if value else 'n')

    # ---- the answers
    def reject(self):                      # Esc / the window's close button: Stop run (also after a refused Record, which had set the action)
        self.answer['action'] = 'stop'
        super().reject()

    def _stop(self):
        self.answer['action'] = 'stop'

    def _skip(self):
        self.answer['action'] = 'skip'

    def _record(self):
        self.answer['action'] = 'record'
        if self.mode == 'numeric':
            text = self.entry.text()
            try:
                if self.validate:
                    self.validate(text)
            except ValueError as exc:
                self.error.setText(str(exc))
                self.entry.setFocus()
                return False
            self.answer.update(text=text, ann=bool(self.ann_box.isChecked()) if self.ann_box is not None else False)
        else:
            if not self.yes.get():
                self.error.setText('Choose Yes or No.')
                return False
            self.answer['yes'] = self.yes.get() == 'y'
        return True


def ask_reading(parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None):
    """One modal dialog. mode 'numeric' (type the display) or 'yesno' (answer a question).
    Returns dict(action='record'|'skip'|'stop', text=, ann=, yes=)."""
    def run():
        dlg = ReadingDialog(parent, p, total, out_text, out_note, accept, mode, question, unit, annunciator, validate, phase, limit_s, on_expire, device, source, demo_fill)
        dlg.run()
        return dlg.answer
    return common.on_ui(run)


# ============================================================================================================ the IR set-up / reading problem dialog
class IrProblemDialog(ModalDialog):
    """The meter (read over IR) is not set up as the point needs, or the reading did not settle.  `answer` = 'retry' | 'type' | 'skip' | 'stop' (Enter = Re-check)."""

    def __init__(self, parent, p, total, problems, shown):
        super().__init__(common.qparent(parent), f'Point {p["n"]} of {total} - check the meter{_demo_suffix()}', width=560 + 2 * theme.M.xl)
        self.title_label.hide()
        self.answer = 'stop'
        self.body.addWidget(_plain(f'Point {p["n"]} of {total}  -  {p["section"]}', 'hint'))
        self.body.addWidget(_plain('The meter is not ready for this point', 'h2'))
        self.problem_labels = []
        for line in problems:
            lab = _bold('•  ' + line)
            self.problem_labels.append(lab)
            self.body.addWidget(lab)
        self.body.addSpacing(6)
        self.body.addWidget(_caps('METER SHOULD BE'))
        self.should_label = _plain(f'{p["switch"]}' + (f', range {p["range"]}' if p['range'] else ''))
        self.body.addWidget(self.should_label)
        self.reports_label = None
        if shown:
            self.body.addSpacing(4)
            self.body.addWidget(_caps('METER REPORTS'))
            self.reports_label = _plain(shown, 'hint')
            self.body.addWidget(self.reports_label)
        self.body.addSpacing(6)
        self.body.addWidget(_plain('The calibrator is in STANDBY. Fix the meter and press Re-check: the output is set again and the meter re-read.', 'hint'))
        _stop_left(self)
        self.stop_button = self.add_button('Stop run', role='danger', result='stop', cancel=True, callback=lambda: self._set('stop'))
        self._button_row.addStretch(1)
        self.skip_button = self.add_button('Skip point', result='skip', callback=lambda: self._set('skip'))
        self.type_button = self.add_button('Type the reading instead', result='type', callback=lambda: self._set('type'))
        self.retry_button = self.add_button('Re-check  (Enter)', role='primary', result='retry', default=True, callback=lambda: self._set('retry'))
        self.initial_focus = self.retry_button
        prompts.fit_dialog(self, 560 + 2 * theme.M.xl)

    def reject(self):
        self.answer = 'stop'
        super().reject()

    def _set(self, value):
        self.answer = value


def ask_ir_problem(parent, p, total, problems, shown):
    """The meter (read over IR) is not set up as the point needs, or the reading did not settle.
    Returns 'retry', 'type' (type this reading instead), 'skip' or 'stop'."""
    def run():
        dlg = IrProblemDialog(parent, p, total, problems, shown)
        dlg.run()
        return dlg.answer
    return common.on_ui(run)


# ============================================================================================================ the range-selection dialog
class DialPicture(QWidget):
    """The meter's dial with the target position marked: the spec's picture, the knob turned to the position (dark disc, amber pointer, hub) and an amber box round the
    selected position's label.  Coordinates are those of the picture (the spec's `dial` block), in pixels of the picture."""

    def __init__(self, dial, position, parent=None):
        super().__init__(parent)
        self.dial, self.pos = dial, position
        width, height = dial['size']
        self.setFixedSize(QSize(int(width), int(height)))
        self.pixmap = QPixmap(str(HERE / dial['image']))
        self.setAccessibleName('Dial picture')

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.tokens()['bg']))
        if not self.pixmap.isNull():
            p.drawPixmap(0, 0, self.pixmap)
        pos = self.pos
        if not pos:
            return
        cx, cy = self.dial['center']
        radius = self.dial['knob_radius']
        p.setPen(QPen(QColor('#9aa0aa'), 3))
        p.setBrush(QColor('#1b1d21'))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        theta = math.radians(pos['angle'])
        ux, uy = math.sin(theta), -math.cos(theta)           # unit vector from the centre toward the selected position
        nx, ny = -uy, ux
        tip = QPointF(cx + ux * (radius - 6), cy + uy * (radius - 6))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#ffb300'))
        p.drawPolygon(QPolygonF([tip, QPointF(cx + nx * 14 - ux * 8, cy + ny * 14 - uy * 8), QPointF(cx - nx * 14 - ux * 8, cy - ny * 14 - uy * 8)]))
        p.setBrush(QColor('#55606e'))
        p.drawEllipse(QPointF(cx, cy), 7, 7)
        p.setPen(QPen(QColor('#ffb300'), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(pos['x'] - 30, pos['y'] - 17, 60, 34))


RANGE_TEXT_W = 360                  # width of the text column beside the dial picture (the Tk window wraps its texts at 360)


class RangeDialog(ModalDialog):
    """'Turn the dial to ...' with a picture of the dial and the target position marked.  `answer` = 'ok' | 'skip' | 'stop' (Enter = continue)."""

    def __init__(self, parent, p, total, dial, standby_text):
        super().__init__(common.qparent(parent), f'Point {p["n"]} of {total} - select the range{_demo_suffix()}')
        self.title_label.hide()
        self.answer = 'stop'
        main = QHBoxLayout()
        main.setSpacing(20)
        self.picture = DialPicture(dial, dial['positions'].get(p.get('dial')))
        main.addWidget(self.picture, 0, Qt.AlignmentFlag.AlignTop)
        textbox = QWidget()
        textbox.setMinimumWidth(RANGE_TEXT_W)
        col = QVBoxLayout(textbox)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(_plain(f'Point {p["n"]} of {total}  -  {p["section"]}', 'hint'))
        col.addSpacing(8)
        col.addWidget(_caps('Turn the dial to'.upper()))
        self.dial_label = _plain(p.get('dial_text') or p['switch'], 'h2')
        col.addWidget(self.dial_label)
        col.addSpacing(8)
        col.addWidget(_caps('Range'.upper()))
        self.range_label = _bold(p['range'], size=22, mono=True)
        col.addWidget(self.range_label)
        self.note_label = None
        if p.get('note'):
            col.addSpacing(6)
            self.note_label = _plain(p['note'], 'hint')
            col.addWidget(self.note_label)
        col.addSpacing(8)
        self.standby_label = _plain(standby_text, 'hint')
        col.addWidget(self.standby_label)
        col.addStretch(1)
        main.addWidget(textbox, 1)
        self.body.addLayout(main)
        _stop_left(self)
        self.stop_button = self.add_button('Stop run', role='danger', result='stop', cancel=True, callback=lambda: self._set('stop'))
        self._button_row.addStretch(1)
        self.skip_button = self.add_button('Skip point', result='skip', callback=lambda: self._set('skip'))
        self.ok_button = self.add_button('Range selected - continue  (Enter)', role='primary', result='ok', default=True, callback=lambda: self._set('ok'))
        self.initial_focus = self.ok_button
        self.setMinimumWidth(self.picture.width() + 20 + RANGE_TEXT_W + 2 * theme.M.xl)
        prompts.fit_dialog(self)

    def reject(self):
        self.answer = 'stop'
        super().reject()

    def _set(self, value):
        self.answer = value


def ask_range(parent, p, total, dial, standby_text):
    """'Turn the dial to ...' with a picture of the dial and the target position marked.
    Returns 'ok' (continue), 'skip' (skip the point) or 'stop'."""
    def run():
        dlg = RangeDialog(parent, p, total, dial, standby_text)
        dlg.run()
        return dlg.answer
    return common.on_ui(run)
