"""Qt twin of run_queue_ui.py: the three windows of the handheld run queue: the queue set-up window, the one-window reading entry for all meters, and the
progress window.  The module-level functions keep the Tk names, arguments and return values (handheld_dmm.ask_readings and run_queue_engine call them):

    ask_readings(parent, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None, device='METER',
                 source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading='')
        -> dict(action='record' | 'skip' | 'stop', texts={key: text or None}, no_reading=[keys])
    ask_meter(parent, title, asset='', serial='', tech='', candidates=(), default_tech='')            -> (asset, serial, tech) | None
    ask_queue_setup(parent, title, meters, mode, summarize, status_of=None, candidates=(), default_tech='', ir_only=False)
        -> dict(action='start' | 'save', meters=[(asset, serial, tech)], mode=...) | None
    QueueProgress(parent, title='Queue progress', on_show=None, on_export=None)      .update(heading, fraction, rows, finished=False, note='') / .close() / .alive()

Presentation only: nothing here talks to an instrument or judges a reading.  The reading window is given a `judge(key, text)` callable by the engine, which
answers with the engine's own judging code (handheld_dmm.judge_numeric / pad_reading), so a meter is judged against the same limits as in a single-meter
run.  Each window is a class (ReadingsDialog, MeterDialog, QueueSetupDialog) that a test can build, drive and read without a modal loop; the functions only
build it, run it modally (on the UI thread, also when an engine calls from a worker) and return its result.  Colours come from the theme tokens.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton,
                               QVBoxLayout)

import run_queue as RQ
import ui_theme_core
import virtualbench
from qtui import theme
from qtui.screens import common
from qtui.table import Column, DataTable
from qtui.widgets import Card, ModalDialog, label

WIDTH = 760                       # content width of the reading window, device-independent px


def _now():
    return time.monotonic()


def _label_of(meters, key):
    return next((m[1] for m in meters if m[0] == key), key)


def _demo_suffix() -> str:
    return getattr(ui_theme_core, 'DEMO_SUFFIX', '') or ''


def _caps(text, tone='muted'):
    """The small bold caption above a block ('ACCEPT IF', 'METERS IN THIS QUEUE' ...)."""
    lab = common.ToneLabel(tone, text)
    f = lab.font()
    f.setBold(True)
    f.setPixelSize(theme.M.font_small)
    lab.setFont(f)
    return lab


def _bold(text, tone='text', size=None):
    lab = common.ToneLabel(tone, text)
    f = lab.font()
    f.setBold(True)
    if size:
        f.setPixelSize(size)
    lab.setFont(f)
    return lab


def _box_style(object_name, border='border', width=1, background='card'):
    return common.tone_css(f'QFrame#{object_name}', border=f'{width}px solid {{{border}}}', border_radius='8px', background=f'{{{background}}}')


# ============================================================================================================ reading window
class _ReadingEdit(QLineEdit):
    """The reading box of one meter: Enter is the window's 'next box / record' (not a dialog default-button press)."""
    entered = Signal()
    gotFocus = Signal()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            ev.accept()
            self.entered.emit()
            return
        super().keyPressEvent(ev)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.gotFocus.emit()


class _MeterRow(QFrame):
    """One meter of the reading window: who, a reading box with its unit, the live state and note, and 'No reading'."""

    def __init__(self, index, key, asset, unit):
        super().__init__()
        self.index, self.key = index, key
        self.setObjectName('meterRow')
        self.set_focused(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)
        who = QVBoxLayout()
        who.setSpacing(0)
        who.addWidget(_caps(f'Meter {index + 1}'))
        self.asset_label = label(f'Asset {asset}', 'section', wrap=True)
        self.asset_label.setMinimumWidth(130)
        who.addWidget(self.asset_label)
        row.addLayout(who)
        self.entry = _ReadingEdit()
        self.entry.setFont(theme.ui_font(size=20, weight=QFont.Weight.Bold, mono=True))
        self.entry.setFixedWidth(150)
        self.entry.setAccessibleName(f'Reading of asset {asset}')
        row.addWidget(self.entry)
        self.unit_label = label(unit, 'h2')
        self.unit_label.setProperty('role', 'sub')
        row.addWidget(self.unit_label)
        side = QVBoxLayout()
        side.setSpacing(0)
        self.state = _bold('waiting', 'muted')
        self.note = common.ToneLabel('muted', '')
        side.addWidget(self.state)
        side.addWidget(self.note)
        row.addLayout(side, 1)
        self.skip = QCheckBox('No reading')
        row.addWidget(self.skip)

    def set_focused(self, on):
        self.setStyleSheet(_box_style('meterRow', 'primary' if on else 'border', 2 if on else 1, 'bg'))


class ReadingsDialog(ModalDialog):
    """One modal window for ONE point and SEVERAL meters: a reading box per meter (asset number on the row), each judged live.

    meters      list of (key, asset label, serial) in queue order
    judge       judge(key, text) -> (state, padded_text, note): state 'PASS' | 'FAIL'; raises ValueError for text that is not a reading
    demo_fill   None, or demo_fill(index) -> text for the 'Fill with a simulated reading' button (fills every box)
    `answer` = dict(action='record'|'skip'|'stop', texts={key: text or None}, no_reading=[keys]).  Enter moves to the next box; Enter in the last box records."""

    def __init__(self, parent, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None,
                 device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading=''):
        super().__init__(common.qparent(parent), f'Point {p["n"]} of {total}{_demo_suffix()}', width=WIDTH + 60)
        self.title_label.hide()
        self.answer = dict(action='stop', texts={}, no_reading=[])
        self.meters, self.judge, self.on_expire = meters, judge, on_expire
        self.rows: list[_MeterRow] = []
        self._expired = False
        self.body.addWidget(label(f'Point {p["n"]} of {total}  -  {p["section"]}' + (f'  -  {phase}' if phase else '') + f'  -  {len(meters)} meters', 'hint', wrap=True))
        head = label(heading, 'h2', wrap=True)
        self.body.addWidget(head)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        out = Card()
        orow = QHBoxLayout()
        ocol = QVBoxLayout()
        ocol.setSpacing(2)
        ocol.addWidget(_caps(source))
        self.out_label = label(out_text, wrap=True)
        self.out_label.setFont(theme.ui_font(size=22, weight=QFont.Weight.Bold, mono=True))
        ocol.addWidget(self.out_label)
        if out_note:
            ocol.addWidget(common.hint(out_note))
        orow.addLayout(ocol, 1)
        mark = QLabel()
        done = str(out_note).startswith('Output is ON')
        mark.setPixmap(theme.pixmap('good' if done else 'dot', theme.tokens()['good' if done else 'muted'], 22))
        mark.setAccessibleName('Output is on' if done else 'Output is not on yet')
        orow.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        out.body.addLayout(orow)
        acc = Card()
        acc.body.addWidget(_caps('ACCEPT IF'))
        self.accept_label = label(accept, 'section', wrap=True)
        acc.body.addWidget(self.accept_label)
        acc.body.addWidget(common.hint('on every meter' + (f'  -  limit: {tol_text}' if tol_text else '')))
        cards.addWidget(out, 1)
        cards.addWidget(acc, 1)
        self.body.addLayout(cards)

        self.counter = common.ToneLabel('bad')
        self.counter.setVisible(limit_s is not None)
        self.body.addWidget(self.counter)
        self._end = None
        self._clock = None
        if limit_s is not None:
            self._end = _now() + max(0.0, limit_s)
            self._clock = QTimer(self)
            self._clock.setInterval(250)
            self._clock.timeout.connect(self._tick)
            self._tick()
            self.finished.connect(lambda _r: self._clock.stop())

        self.body.addWidget(_caps(f'WHAT DOES EACH {device} SHOW?', 'primary'))
        card = QFrame()
        card.setObjectName('meterBox')
        card.setStyleSheet(_box_style('meterBox', 'primary', 2, 'card'))
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 6)
        cl.setSpacing(6)
        for n, (key, label_, serial) in enumerate(meters):
            r = _MeterRow(n, key, label_, unit)
            self.rows.append(r)
            cl.addWidget(r)
            r.entry.textChanged.connect(lambda _t, _r=r: (self.refresh_row(_r), self.error.setText('')))
            r.skip.toggled.connect(lambda _c, _r=r: self.refresh_row(_r))
            r.entry.entered.connect(lambda _r=r: self._enter(_r.index))
            r.entry.gotFocus.connect(lambda _r=r: self.focus_row(_r.index))
        self.body.addWidget(card)
        self.error = common.ToneLabel('bad')
        self.body.addWidget(self.error)

        self.fill_button = None
        if demo_fill is not None:
            self.demo_fill = demo_fill
            self.fill_button = QPushButton(virtualbench.FILL_TEXT)
            self.fill_button.setAutoDefault(False)
            self.fill_button.clicked.connect(self.fill)
            fr = QHBoxLayout()
            fr.addWidget(self.fill_button)
            fr.addStretch(1)
            self.body.addLayout(fr)
            self.body.addWidget(common.ToneLabel('warn', 'DEMO: these values are made up by the program; you may type any reading you like. '
                                                         'Nothing here is calibration evidence.'))

        self._button_row.takeAt(0)                                    # Stop run sits at the left, Skip point and Record all at the right
        self.stop_button = self.add_button('Stop run', role='danger', result='stop', cancel=True, callback=self._stop)
        self._button_row.addStretch(1)
        self.skip_button = self.add_button('Skip point', result='skip', callback=self._skip)
        self.record_button = self.add_button('Record all  (Enter)', role='primary', result='record', default=True, callback=self._record)
        self.initial_focus = self.rows[0].entry if self.rows else None

    # ---- the clock
    def _tick(self):
        left = self._end - _now()
        if left <= 0:
            if not self._expired:
                self._expired = True
                if self.on_expire:
                    self.on_expire()
            self.counter.setText('Time limit reached - the output has been switched off. Enter the readings you saw.' if self.on_expire
                                 else 'Time limit reached - put the calibrator in STANDBY now, then enter the readings.')
            if self._clock is not None:
                self._clock.stop()
            return
        self.counter.setText(f'Take the readings within {left:.0f} s - the output switches off automatically.' if self.on_expire
                             else f'Take the readings within {left:.0f} s, then put the calibrator in STANDBY.')

    # ---- rows
    def refresh_row(self, r):
        text = r.entry.text().strip()
        r.entry.setEnabled(not r.skip.isChecked())
        if r.skip.isChecked():
            r.state.setText('no reading')
            r.state.set_tone('muted')
            r.note.setText('nothing is recorded for this meter at this point')
            return
        if not text:
            r.state.setText('waiting')
            r.state.set_tone('muted')
            r.note.setText('')
            return
        try:
            state, padded, note = self.judge(r.key, text)
        except ValueError as exc:
            r.state.setText('not a reading')
            r.state.set_tone('bad')
            r.note.setText(str(exc))
            return
        good = state == 'PASS'
        r.state.setText('✓ PASS' if good else '✗ FAIL')
        r.state.set_tone('good' if good else 'bad')
        bits = ([f'padded to {padded}'] if padded != text else []) + ([note] if note else [])
        r.note.setText('   '.join(bits))

    def focus_row(self, i):
        for r in self.rows:
            r.set_focused(r.index == i)

    def collect(self):
        texts, none = {}, []
        for r in self.rows:
            if r.skip.isChecked():
                texts[r.key] = None
                none.append(r.key)
                continue
            text = r.entry.text().strip()
            if not text:
                return None, f'Enter the reading of Asset {_label_of(self.meters, r.key)}, or tick "No reading" for it.', r
            try:
                self.judge(r.key, text)
            except ValueError as exc:
                return None, f'Asset {_label_of(self.meters, r.key)}: {exc}', r
            texts[r.key] = text
        if len(none) == len(self.rows):
            return None, 'Every meter is marked "No reading": use Skip point instead.', None
        return (texts, none), '', None

    def _enter(self, i):
        nxt = next((r for r in self.rows[i + 1:] if not r.skip.isChecked()), None)
        if nxt is not None:
            nxt.entry.setFocus()
        else:
            self.record_button.click()

    def fill(self):
        for r in self.rows:
            if not r.skip.isChecked():
                r.entry.setText(self.demo_fill(r.index))
        if self.rows:
            self.rows[0].entry.setFocus()

    # ---- the three answers
    def _stop(self):
        self.answer['action'] = 'stop'

    def _skip(self):
        self.answer['action'] = 'skip'

    def _record(self):
        self.answer['action'] = 'record'
        got, msg, bad = self.collect()
        if got is None:
            self.error.setText(msg)
            if bad is not None:
                bad.entry.setFocus()
            self.answer['action'] = 'stop'
            return False
        self.answer.update(texts=got[0], no_reading=got[1])
        return True


def ask_readings(parent, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None,
                 device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading=''):
    """One modal window for ONE point and SEVERAL meters (see ReadingsDialog).  Returns dict(action, texts, no_reading)."""
    def run():
        dlg = ReadingsDialog(parent, p, total, out_text, out_note, accept, meters, unit, judge, limit_s, on_expire, device, source, demo_fill, tol_text, phase, heading)
        dlg.run()
        return dlg.answer
    return common.on_ui(run)


# ============================================================================================================ set-up window
class MeterDialog(ModalDialog):
    """Add / edit one meter: asset number (typed, or chosen from Asset History), serial, technician.  `value` = (asset, serial, tech) after OK."""

    def __init__(self, parent, title, asset='', serial='', tech='', candidates=(), default_tech=''):
        super().__init__(common.qparent(parent), title + _demo_suffix(), width=460)
        self.title_label.hide()
        self.value = None
        self.serials = {x: y for x, y in candidates}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label('Asset number'), 0, 0)
        self.asset = QComboBox()
        self.asset.setEditable(True)
        self.asset.addItems([x for x, _ in candidates])
        self.asset.setCurrentText(asset)
        self.asset.setAccessibleName('Asset number')
        grid.addWidget(self.asset, 0, 1)
        grid.addWidget(label('Serial number'), 1, 0)
        self.serial = QLineEdit(serial)
        self.serial.setAccessibleName('Serial number')
        grid.addWidget(self.serial, 1, 1)
        grid.addWidget(label('Technician'), 2, 0)
        self.tech = QLineEdit(tech or default_tech)
        self.tech.setAccessibleName('Technician')
        grid.addWidget(self.tech, 2, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        self.body.addWidget(common.hint('Choose an asset from Asset History or type one. The serial is filled in from the history when it is known.'))
        self.msg = common.ToneLabel('bad')
        self.body.addWidget(self.msg)
        self.asset.activated.connect(lambda _i: self.pick())
        self.asset.lineEdit().editingFinished.connect(self.pick)
        self.add_button('Cancel', cancel=True)
        self.add_button('OK', role='primary', default=True, result='ok', callback=self.ok)
        self.initial_focus = self.asset

    def pick(self):
        a = self.asset.currentText()
        if a in self.serials and not self.serial.text().strip():
            self.serial.setText(self.serials[a])

    def ok(self):
        if not self.asset.currentText().strip():
            self.msg.setText('Enter the asset number.')
            return False
        self.pick()
        self.value = (self.asset.currentText().strip(), self.serial.text().strip(), self.tech.text().strip())
        return True


def ask_meter(parent, title, asset='', serial='', tech='', candidates=(), default_tech=''):
    """Add / edit one meter.  Returns (asset, serial, tech) or None.  candidates: [(asset, serial)] from Asset History / the instrument list."""
    def run():
        dlg = MeterDialog(parent, title, asset, serial, tech, candidates, default_tech)
        dlg.run()
        return dlg.value
    return common.on_ui(run)


class _ModeCard(QFrame):
    """A clickable card with a radio button and its description."""
    chosen = Signal(str)

    def __init__(self, value, head, text):
        super().__init__()
        self.value = value
        self.setObjectName('modeCard')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        self.radio = QRadioButton(head)
        self.radio.setAutoExclusive(False)
        self.radio.clicked.connect(lambda _c=False: self.chosen.emit(self.value))
        lay.addWidget(self.radio)
        self.text = common.hint(text)
        self.text.setContentsMargins(26, 0, 0, 0)
        lay.addWidget(self.text)
        self.set_selected(False)

    def set_selected(self, on):
        self.radio.setChecked(on)
        self.setStyleSheet(_box_style('modeCard', 'primary' if on else 'border', 2, 'card'))

    def mousePressEvent(self, ev):
        self.chosen.emit(self.value)
        super().mousePressEvent(ev)


class QueueSetupDialog(ModalDialog):
    """The 'Run queue' window.  meters: [(asset, serial, tech)] to start from.  summarize(meters, mode) -> dict(title, body, warnings=[], ok=bool, kind='good'|'warn'|'bad')
    (the engine decides what the choice saves and what blocks it).  status_of(asset) -> text for the Status column.
    `answer` = dict(action='start'|'save', meters=[...], mode=...) or None (Cancel / closed)."""

    def __init__(self, parent, title, meters, mode, summarize, status_of=None, candidates=(), default_tech='', ir_only=False):
        super().__init__(common.qparent(parent), title + _demo_suffix(), width=WIDTH - 20)
        self.title_label.hide()
        self.base_title = title
        self.summarize, self.status_of, self.candidates, self.default_tech, self.ir_only = summarize, status_of, candidates, default_tech, ir_only
        self.state = {'meters': [tuple(m) for m in meters], 'mode': mode}
        self.answer = None
        self.body.addWidget(_caps('METERS IN THIS QUEUE'))
        cols = [Column('n', '#', width=44, getter=lambda r: r['n']), Column('asset', 'Asset', width=140, getter=lambda r: r['asset']),
                Column('serial', 'Serial', width=150, getter=lambda r: r['serial']), Column('status', 'Status', width=190, stretch=True, getter=lambda r: r['status']),
                Column('tech', 'Tech', width=170, getter=lambda r: r['tech'])]
        self.table = DataTable(cols, [], row_key=lambda r: r['i'], multi=False, empty_text='No meters yet')
        self.table.setFixedHeight(theme.M.header_h + theme.M.row_h * 5 + 4)
        self.table.rowActivated.connect(lambda _r: self.edit())
        self.body.addWidget(self.table)
        btns = QHBoxLayout()
        self.buttons = {}
        for text, cmd in (('+ Add meter', self.add), ('Edit', self.edit), ('Remove', self.remove), ('Move up', lambda: self.move(-1)), ('Move down', lambda: self.move(1))):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _c=False, c=cmd: c())
            btns.addWidget(b)
            self.buttons[text] = b
        btns.addStretch(1)
        self.body.addLayout(btns)
        self.note = common.ToneLabel('bad')
        self.body.addWidget(self.note)

        self.body.addWidget(_caps('HOW TO RUN THEM'))
        self.cards = {}
        for value, head, text in (
                (RQ.POINT_BY_POINT, 'Point by point  (recommended)',
                 'All meters are wired to the calibrator together. Each point is set once, then you read meter 1, 2, 3 in one window. '
                 'Points that cannot be shared (current, 4-wire ...) are done one meter at a time, with a prompt that says why.'),
                (RQ.ONE_AT_A_TIME, 'One meter at a time',
                 'Finish meter 1, swap in meter 2, and so on. Each meter runs the normal single-meter procedure. Use when the meters cannot share the leads.')):
            c = _ModeCard(value, head, text)
            c.chosen.connect(self.choose)
            self.cards[value] = c
            self.body.addWidget(c)
        self.sum_frame = QFrame()
        self.sum_frame.setObjectName('summaryCard')
        sl = QVBoxLayout(self.sum_frame)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(2)
        self.sum_head = common.ToneLabel('text')
        f = self.sum_head.font()
        f.setBold(True)
        self.sum_head.setFont(f)
        self.sum_body = common.ToneLabel('muted')
        sl.addWidget(self.sum_head)
        sl.addWidget(self.sum_body)
        self.body.addWidget(self.sum_frame)

        self.add_button('Cancel', cancel=True)
        self.save = self.add_button('Save (do not start)', result='save', callback=lambda: self.finish('save'))
        self.start = self.add_button('Start queue', role='primary', result='start', callback=lambda: self.finish('start'))     # no default: Enter does nothing here (as in Tk)
        if ir_only:
            self.state['mode'] = RQ.ONE_AT_A_TIME
        self.refresh_all()

    # ---- state -> widgets
    def fill(self):
        sel = self.selected()
        rows = [dict(i=i, n=i + 1, asset=a, serial=s, status=self.status_of(a) if self.status_of else 'Ready', tech=t)
                for i, (a, s, t) in enumerate(self.state['meters'])]
        self._rows = rows
        self.table.set_rows(rows, keep_selection=False)
        if sel is not None and sel < len(rows):
            self.table.select_rows([rows[sel]])
        n = len(self.state['meters'])
        self.setWindowTitle(f'{self.base_title}  ({n} meter{"s" if n != 1 else ""})' + _demo_suffix())

    def selected(self):
        rows = self.table.selected_rows()
        return rows[0]['i'] if rows else None

    def select(self, i):
        self.table.select_rows([self._rows[i]] if i is not None and 0 <= i < len(self._rows) else [])

    def recompute(self):
        info = self.summarize(list(self.state['meters']), self.state['mode'])
        kind = info.get('kind', 'good')
        edge = {'good': 'good_dot', 'warn': 'warn_dot', 'bad': 'bad_dot'}.get(kind, 'border')
        self.sum_frame.setStyleSheet(_box_style('summaryCard', edge, 2, 'card'))
        self.sum_head.setText(info.get('title', ''))
        self.sum_head.set_tone({'good': 'good', 'warn': 'warn', 'bad': 'bad'}.get(kind, 'text'))
        self.sum_body.setText(info.get('body', '') + ''.join('\n' + w for w in info.get('warnings', [])))
        for v, c in self.cards.items():
            c.set_selected(v == self.state['mode'])
        self.start.setEnabled(bool(info.get('ok', True) and self.state['meters']))
        self.save.setEnabled(bool(self.state['meters']))
        self.start.setText('Start queue' if len(self.state['meters']) >= 2 else 'Run this meter')

    def choose(self, value):
        if self.ir_only and value == RQ.POINT_BY_POINT:
            self.note.setText(RQ.IR_REASON[0].upper() + RQ.IR_REASON[1:] + '.')
            value = RQ.ONE_AT_A_TIME
        self.state['mode'] = value
        self.recompute()

    def refresh_all(self):
        self.fill()
        self.recompute()

    # ---- the meter buttons
    def add(self):
        got = ask_meter(self, 'Add meter', candidates=[c for c in self.candidates if c[0] not in {m[0] for m in self.state['meters']}], default_tech=self.default_tech)
        if got:
            if got[0].casefold() in {m[0].casefold() for m in self.state['meters']}:
                self.note.setText(f'Asset {got[0]} is already in the queue.')
                return
            if len(self.state['meters']) >= RQ.MAX_METERS:
                self.note.setText(f'A queue holds at most {RQ.MAX_METERS} meters.')
                return
            self.note.setText('')
            self.state['meters'].append(got)
            self.refresh_all()

    def edit(self):
        i = self.selected()
        if i is None:
            return
        old = self.state['meters'][i]
        got = ask_meter(self, 'Edit meter', *old, candidates=self.candidates, default_tech=self.default_tech)
        if got:
            if got[0].casefold() != old[0].casefold() and got[0].casefold() in {m[0].casefold() for k, m in enumerate(self.state['meters']) if k != i}:
                self.note.setText(f'Asset {got[0]} is already in the queue.')
                return
            self.note.setText('')
            self.state['meters'][i] = got
            self.refresh_all()
            self.select(i)

    def remove(self):
        i = self.selected()
        if i is not None:
            self.state['meters'].pop(i)
            self.note.setText('')
            self.refresh_all()

    def move(self, delta):
        i = self.selected()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.state['meters']):
            self.state['meters'][i], self.state['meters'][j] = self.state['meters'][j], self.state['meters'][i]
            self.refresh_all()
            self.select(j)

    def finish(self, action):
        self.answer = dict(action=action, meters=list(self.state['meters']), mode=self.state['mode'])
        return True


def ask_queue_setup(parent, title, meters, mode, summarize, status_of=None, candidates=(), default_tech='', ir_only=False):
    """The 'Run queue' window (see QueueSetupDialog).  Returns dict(action='start'|'save', meters=[(asset, serial, tech)], mode=...) or None (Cancel / closed)."""
    def run():
        dlg = QueueSetupDialog(parent, title, meters, mode, summarize, status_of, candidates, default_tech, ir_only)
        dlg.run()
        return dlg.answer
    return common.on_ui(run)


# ============================================================================================================ progress window
class QueueProgress:
    """Non-modal progress window (queue_progress mockup): the point being run, a bar, and per meter 'n recorded, n fail'.  The engine calls update() as
    the run goes; when the run has ended it calls update(..., finished=True) and the window offers Show / Export all reports / Close."""

    FOOT = 'Each meter still gets its own report (asset#-date) and its own Asset History record.'

    def __init__(self, parent, title='Queue progress', on_show=None, on_export=None):
        self.parent, self.on_show, self.on_export = parent, on_show, on_export
        self.win = None
        self.closed = False
        self.rows = []
        try:
            win = self.win = ModalDialog(common.qparent(parent), title + _demo_suffix(), width=600, modal=False)
            win.title_label.hide()
            win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            win.finished.connect(lambda _r: self._on_closed())
            self.head = label('', 'h2', wrap=True)
            win.body.addWidget(self.head)
            self.bar = QProgressBar()
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            win.body.addWidget(self.bar)
            self.cards = QVBoxLayout()
            self.cards.setSpacing(8)
            win.body.addLayout(self.cards)
            self.foot = common.hint(self.FOOT)
            win.body.addWidget(self.foot)
            self.close_button = self.export_button = None
            self.show_buttons = {}
            win.show()
        except Exception:
            self.win = None

    def alive(self):
        if self.win is None or self.closed:
            return False
        return common.alive(self.win)

    def update(self, heading, fraction, rows, finished=False, note=''):
        """rows: run_queue.progress() dicts.  Safe to call from the engine's worker thread (the work is moved to the UI thread)."""
        if not self.alive():
            return
        common.post_ui(self._update, heading, fraction, rows, finished, note)

    def _update(self, heading, fraction, rows, finished, note):
        if not self.alive():
            return
        self.head.setText(heading)
        self.bar.setValue(int(round(max(0.0, min(1.0, fraction)) * 100)))
        while self.cards.count():
            it = self.cards.takeAt(0)
            if it.widget() is not None:
                it.widget().setParent(None)
                it.widget().deleteLater()
        self.rows = list(rows)
        self.show_buttons = {}
        for row in rows:
            bad = row['failed'] > 0
            fr = QFrame()
            fr.setObjectName('progressRow')
            fr.setStyleSheet(_box_style('progressRow', 'bad_dot' if bad else 'border', 2, 'card'))
            lay = QHBoxLayout(fr)
            lay.setContentsMargins(12, 10, 12, 10)
            who = label(f'Asset {row["asset"]}', 'section')
            who.setMinimumWidth(130)
            lay.addWidget(who)
            text = f'{row["recorded"]} recorded   ' + (f'{row["failed"]} FAIL' + (f' at point {row["first_fail"]}' if row['first_fail'] else '') if bad else '0 fail')
            if row.get('status') and row['status'] not in ('Ready', 'Running'):
                text += f'   -   {row["status"]}'
            lay.addWidget(common.ToneLabel('bad' if bad else 'muted', text), 1)
            if finished and self.on_show:
                b = QPushButton('Show')
                b.setAutoDefault(False)
                b.clicked.connect(lambda _c=False, a=row['asset']: self.on_show(a))
                lay.addWidget(b)
                self.show_buttons[row['asset']] = b
            self.cards.addWidget(fr)
        self.foot.setText(note or self.FOOT)
        self._set_buttons(finished)
        self.win.adjustSize()

    def _set_buttons(self, finished):
        """Nothing while the queue runs; Export all reports (PDF)... and Close once it has ended (rebuilt at every update, like the Tk window)."""
        row = self.win._button_row
        for b in (self.export_button, self.close_button):
            if b is not None:
                row.removeWidget(b)
                b.setParent(None)
                b.deleteLater()
        self.close_button = self.export_button = None
        if not finished:
            return
        if self.on_export:
            self.export_button = QPushButton('Export all reports (PDF)...')
            self.export_button.setProperty('role', 'primary')
            self.export_button.setAutoDefault(False)
            self.export_button.clicked.connect(lambda _c=False: self.on_export())
            row.addWidget(self.export_button)
        self.close_button = QPushButton('Close')
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(lambda _c=False: self.close())
        row.addWidget(self.close_button)

    def _on_closed(self):
        self.closed = True

    def close(self):
        self.closed = True
        try:
            if self.win is not None:
                self.win.hide()
                self.win.close()
        except RuntimeError:
            pass
        return False
