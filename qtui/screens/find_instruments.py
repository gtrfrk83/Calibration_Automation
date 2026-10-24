"""The 'Find instruments' window (Qt twin of instrument_scan_ui.py; the rules and the scan are in instrument_scan.py).

    open_find_instruments(parent)          the Manager tool: scan, look at the results, copy a resource string, Remember
    ask_resource(parent, model=None)       the same window as a chooser: returns the resource the technician accepted, or ''

Read-only identity queries only (see instrument_scan.py); nothing is connected for use; a result is remembered only when 'Accept and remember' is pressed.  The scan
runs in a worker thread (instrument_scan.ScanJob); this window polls it from a timer.  RS-232 ports are listed but only checked when the instrument type is named.
No Tk import."""
from __future__ import annotations

import queue
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

import instrument_scan as S
from qtui import theme
from qtui.table import Column, DataTable
from qtui.theme import M
from qtui.widgets import Banner, PrimaryButton, SecondaryButton, label

INTRO = ('Asks each GPIB, USB and LAN instrument who it is, with read-only identity queries (*IDN? and, on GPIB, ID? for the 3458A). Nothing is changed on the '
         'instruments and nothing is connected for use. Serial (RS-232) ports are listed but are not asked unless you pick the instrument type for a port below.')

TAG_TONE = {'pass': 'pass', 'error': 'fail', 'pending': None}


class _Row:
    __slots__ = ('values', 'tag', 'hit')

    def __init__(self, values, tag, hit):
        self.values, self.tag, self.hit = values, tag, hit


class FindInstrumentsWindow(QDialog):
    def __init__(self, parent, memory=None, scanner_factory=None, serial_checker=None, serial_ports=None, model=None, choose=False):
        super().__init__(parent)
        self.memory = memory if memory is not None else S.ResourceMemory()
        self.scanner_factory = scanner_factory or (lambda probe_all, go_local: S.Scanner(probe_all_gpib=probe_all, go_local=go_local, preferred=self._preferred()))
        self.serial_checker = serial_checker or S.serial_hit
        self.serial_ports_source = serial_ports or S.system_serial_ports
        self.model, self.choose = model, choose
        self.result = ''
        self.job = None
        self.report = None
        self.rows = {}
        self.extra_hits = []                                  # serial checks asked for by hand
        self.setWindowTitle('Find instruments')
        self.setModal(choose)
        self.resize(1120, 700)
        self.setMinimumSize(760, 520)
        body = QVBoxLayout(self)
        body.setContentsMargins(M.xl, M.lg, M.xl, M.lg)
        body.setSpacing(M.sm + 2)
        body.addWidget(label('Find instruments', 'h2'))
        body.addWidget(Banner(INTRO, 'info'))

        bar = QHBoxLayout()
        self.btn_scan = PrimaryButton('Scan instruments', on_click=self.start_scan)
        self.btn_cancel = SecondaryButton('Cancel', on_click=self.cancel_scan)
        self.btn_cancel.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(240)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_text = label('', 'sub')
        for w in (self.btn_scan, self.btn_cancel, self.progress, self.progress_text):
            bar.addWidget(w)
        bar.addStretch(1)
        body.addLayout(bar)

        opts = QHBoxLayout()
        self.probe_all = QCheckBox('Ask every GPIB address 0-30 (for adapters that do not list their instruments)')
        self.go_local = QCheckBox('Send GTL (back to front panel) afterwards')
        opts.addWidget(self.probe_all)
        opts.addSpacing(M.lg)
        opts.addWidget(self.go_local)
        opts.addStretch(1)
        body.addLayout(opts)

        self.backend = label('', 'hint', wrap=True)
        body.addWidget(self.backend)
        self.problem = Banner('', 'warn')
        self.problem.hide()                                   # shown only when there is something to say
        body.addWidget(self.problem)

        cols = [Column(key, title, width, getter=lambda r, i=i: r.values[i], stretch=key == 'idn')
                for i, (key, title, width) in enumerate((('resource', 'Resource', 280), ('idn', 'Instrument (its own reply)', 300), ('key', 'Model key', 90),
                                                         ('serial', 'Serial', 110), ('state', 'Status', 270)))]
        self.table = DataTable(cols, [], row_tone=lambda r: TAG_TONE.get(r.tag), row_key=lambda r: id(r.hit), tone_style='text', empty_text='Press "Scan instruments".')
        self.table.selectionChangedRows.connect(lambda _rows: self.selection_changed())
        body.addWidget(self.table, 1)

        self.detail = label('', 'hint', wrap=True)
        body.addWidget(self.detail)
        actions = QHBoxLayout()
        self.btn_copy = SecondaryButton('Copy resource', on_click=self.copy_resource)
        self.btn_remember = PrimaryButton('Accept and remember', on_click=self.remember_selected)
        self.btn_forget = SecondaryButton('Forget', on_click=self.forget_selected)
        for b in (self.btn_copy, self.btn_remember, self.btn_forget):
            b.setEnabled(False)
            actions.addWidget(b)
        actions.addStretch(1)
        self.btn_use = None
        if choose:
            self.btn_use = PrimaryButton('Use this resource', on_click=self.use_selected)
            self.btn_use.setEnabled(False)
            actions.addWidget(self.btn_use)
        body.addLayout(actions)

        self.serial_frame = QFrame()
        self.serial_frame.setProperty('surface', 'card')
        sv = QVBoxLayout(self.serial_frame)
        sv.setContentsMargins(M.md, M.md, M.md, M.md)
        sv.addWidget(label('Serial (RS-232) ports: never asked automatically', 'section'))
        row = QHBoxLayout()
        row.addWidget(label('Port'))
        self.port_box = QComboBox()
        self.port_box.setEditable(True)
        self.port_box.setMinimumWidth(220)
        row.addWidget(self.port_box)
        row.addSpacing(M.md)
        row.addWidget(label('Instrument type'))
        self.family_box = QComboBox()
        choices = S.serial_family_choices()
        self.family_labels = {f'{k}  {lab}': k for k, lab in choices}
        self.family_box.addItem('')
        self.family_box.addItems(list(self.family_labels))
        self.family_box.setMinimumWidth(340)
        row.addWidget(self.family_box, 1)
        self.btn_serial = SecondaryButton('Check this port', on_click=self.check_port)
        row.addWidget(self.btn_serial)
        sv.addLayout(row)
        sv.addWidget(label("The check uses that instrument driver's own identity code and sends nothing else. Pick the type of the instrument you connected to the port.",
                           'hint', wrap=True))
        body.addWidget(self.serial_frame)
        self.refresh_ports()

        foot = QHBoxLayout()
        self.log_visible = False
        self.btn_log = SecondaryButton('Show what was sent', on_click=self.toggle_log)
        self.status = label('', 'sub')
        btn_close = SecondaryButton('Close', on_click=self.close)
        foot.addWidget(self.btn_log)
        foot.addWidget(self.status, 1)
        foot.addWidget(btn_close)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(130)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {M.font_mono}px;")
        self.log_text.hide()
        body.addWidget(self.log_text)
        body.addLayout(foot)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.poll)
        self._serial_q = None
        self._serial_timer = QTimer(self)
        self._serial_timer.setInterval(100)
        self._serial_timer.timeout.connect(self._serial_wait)

    # ------------------------------------------------------------------------------------------------ helpers
    def show_problem(self, text):
        self.problem.set_text(text)
        self.problem.setVisible(bool(text))

    def _preferred(self):
        """A remembered resource is asked with its family's own query first (a remembered 3458A with ID?, so no *IDN? is sent to it)."""
        out = {}
        try:
            for r in self.memory.remembered():
                fam = S.FAMILY.get(r.model)
                if fam is not None and fam.probe != '*IDN?':
                    out[r.resource] = fam.probe
        except Exception:
            pass
        return out

    # ------------------------------------------------------------------------------------------------ scan
    def start_scan(self):
        if self.job is not None and not self.job.finished and not self.job.abandoned:
            return
        self.clear_results()
        self.show_problem('')
        self.backend.setText('')
        self.btn_scan.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress_text.setText('Listing the VISA resources ...')
        self.status.setText('')
        try:
            scanner = self.scanner_factory(self.probe_all.isChecked(), self.go_local.isChecked())
        except Exception as exc:
            self.scan_failed(str(exc))
            return
        self.job = S.ScanJob(scanner).start()
        self._timer.start()

    def poll(self):
        job = self.job
        if job is None or job.abandoned:
            self._timer.stop()
            return
        for kind, payload in job.poll():
            if kind == 'progress':
                i, n, msg = payload
                self.progress.setRange(0, max(1, n))
                self.progress.setValue(i)
                self.progress_text.setText(f'{msg}  ({i}/{n})' if n else msg)
            elif kind == 'done':
                self._timer.stop()
                self.scan_done(payload)
                return
            elif kind == 'error':
                self._timer.stop()
                self.scan_failed(payload)
                return

    def cancel_scan(self):
        if self.job is not None:
            self.job.cancel()
        self._timer.stop()
        self.btn_scan.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_text.setText('Cancelled.')
        self.status.setText('Scan cancelled. A query already sent is allowed to finish; its answer is ignored.')

    def scan_failed(self, text):
        self.btn_scan.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_text.setText('')
        self.backend.setText('')
        self.show_problem(text)
        self.table.empty_text = 'The scan could not run.'
        self.table.viewport().update()
        self.status.setText('The scan could not run.')

    def scan_done(self, report):
        self.report = report
        self.btn_scan.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        self.progress_text.setText('Cancelled.' if report.cancelled else 'Done.')
        info = f'{report.backend}' + (f' ({report.backend_path})' if report.backend_path else '')
        notes = [f'Serial ports listed, not asked: {", ".join(report.serial_ports)}.'] if report.serial_ports else []
        self.backend.setText('  '.join([info + '.'] + notes))
        self.show_problem(' '.join(report.warnings))
        self.show_rows()
        ports = self.refresh_ports(extra=report.serial_ports)
        n = len(report.identified())
        text = (f'{n} instrument{"" if n == 1 else "s"} identified; {report.probed} resource{"" if report.probed == 1 else "s"} asked'
                + (f'; {report.empty_gpib} empty GPIB address(es) skipped' if report.empty_gpib else '') + '.')
        if not ports and not report.hits:
            text += ' Nothing found: check the cable, the adapter software and the instrument\'s GPIB address.'
        self.status.setText(text)

    # ------------------------------------------------------------------------------------------------ results
    def clear_results(self):
        self.table.set_rows([], keep_selection=False)
        self.rows.clear()
        self.extra_hits.clear()
        self.report = None
        self.detail.setText('')
        self.table.empty_text = 'Press "Scan instruments".'
        self.table.viewport().update()
        self.selection_changed()

    def show_rows(self):
        keep = {id(h) for h in self.selected_hits()}                 # the table is rebuilt (status column): the selection stays
        hits = (self.report.hits if self.report else []) + self.extra_hits
        rows = [_Row(values, tag, hit) for values, tag, hit in S.result_rows(hits, self.memory)]
        self.rows = {id(r.hit): r.hit for r in rows}
        self.table.empty_text = 'No instrument answered.' if self.report is not None or self.extra_hits else 'Press "Scan instruments".'
        self.table.set_rows(rows, keep_selection=False)
        self.table.select_rows([r for r in rows if id(r.hit) in keep])
        self.selection_changed()

    def selected_hits(self):
        return [r.hit for r in self.table.selected_rows()]

    def selection_changed(self):
        hits = self.selected_hits()
        ident = [h for h in hits if h.status == 'identified' and not h.alias_of]
        self.btn_copy.setEnabled(len(hits) == 1)
        self.btn_remember.setEnabled(bool(ident))
        self.btn_forget.setEnabled(any(self.memory.status_of(h).startswith('remembered') for h in ident))
        if self.btn_use is not None:
            self.btn_use.setEnabled(len(ident) == 1 and len(hits) == 1)
        if len(hits) == 1:
            h = hits[0]
            text = f'{h.resource}: {h.idn or h.error or h.status}'
            if h.needs_serial:
                text += '   Another instrument of this model was found: choose by serial number.'
            if h.status == 'identified' and not h.serial:
                text += '   (This model does not report a serial number.)'
            self.detail.setText(text)
        else:
            self.detail.setText('')

    def copy_resource(self):
        hits = self.selected_hits()
        if len(hits) != 1:
            return
        QGuiApplication.clipboard().setText(hits[0].resource)
        self.status.setText(f'Copied {hits[0].resource}')

    def remember_selected(self):
        done = []
        for h in self.selected_hits():
            if h.status == 'identified' and not h.alias_of:
                try:
                    self.memory.remember(h)
                    done.append(h.resource)
                except Exception as exc:
                    self.status.setText(f'Could not save: {exc}')
                    return
        self.show_rows()
        self.status.setText('Remembered ' + ', '.join(done) + ' for this workstation. It is checked again before it is offered.' if done else 'Nothing to remember.')

    def forget_selected(self):
        for h in self.selected_hits():
            if h.status == 'identified':
                self.memory.forget(h.key, h.serial)
        self.show_rows()
        self.status.setText('Forgotten.')

    def use_selected(self):
        hits = [h for h in self.selected_hits() if h.status == 'identified' and not h.alias_of]
        if len(hits) == 1:
            self.result = hits[0].resource
            self.remember_selected()
            self.close()

    # ------------------------------------------------------------------------------------------------ serial
    def refresh_ports(self, extra=()):
        ports = []
        for p in list(extra) + list(self.serial_ports_source()):
            if p not in ports:
                ports.append(p)
        current = self.port_box.currentText()
        self.port_box.clear()
        self.port_box.addItems(ports)
        self.port_box.setEditText(current)
        return ports

    def check_port(self):
        port, label_ = self.port_box.currentText().strip(), self.family_box.currentText()
        if not port or not label_:
            self.status.setText('Pick the port and the type of instrument connected to it first.')
            return
        key = self.family_labels.get(label_)
        if '::' not in port:
            port = (S.serial_resource_names([port]) or [port])[0]
        self.btn_serial.setEnabled(False)
        self.status.setText(f'Asking {port} as a {key} ...')
        q = self._serial_q = queue.Queue()

        def run():
            try:
                q.put(self.serial_checker(port, key))
            except Exception as exc:
                q.put(S.Hit(port, 'ASRL', 'error', error=str(exc)))
        threading.Thread(target=run, daemon=True, name='serial-check').start()
        self._serial_port = port
        self._serial_timer.start()

    def _serial_wait(self):
        try:
            hit = self._serial_q.get_nowait()
        except (queue.Empty, AttributeError):
            return
        self._serial_timer.stop()
        port = self._serial_port
        self.btn_serial.setEnabled(True)
        self.extra_hits = [h for h in self.extra_hits if h.resource != hit.resource] + [hit]
        self.show_rows()
        self.status.setText(f'{port}: {hit.idn}' if hit.idn else f'{port}: {S.state_text(hit)}')

    # ------------------------------------------------------------------------------------------------ the log
    def toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            lines = [f'{d}  {name:34s} {text}' for d, name, text in (self.report.log if self.report else [])] or ['(nothing sent yet)']
            self.log_text.setPlainText('\n'.join(lines))
            self.log_text.show()
            self.btn_log.setText('Hide what was sent')
        else:
            self.log_text.hide()
            self.btn_log.setText('Show what was sent')

    # ------------------------------------------------------------------------------------------------ window
    def closeEvent(self, ev):
        if self.job is not None and not self.job.finished:
            self.job.cancel()
        self._timer.stop()
        self._serial_timer.stop()
        super().closeEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(ev)


def open_find_instruments(parent, **kw):
    """The Manager's tool window (not modal, so a resource can be copied into a procedure window beside it)."""
    w = FindInstrumentsWindow(parent, **kw)
    w.show()
    return w


def ask_resource(parent, model=None, **kw):
    """The same window as a chooser; returns the accepted resource, '' when closed without choosing."""
    w = FindInstrumentsWindow(parent, model=model, choose=True, **kw)
    w.exec()
    return w.result
