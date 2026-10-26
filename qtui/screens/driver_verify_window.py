"""File > 'Driver verification...': connect to an instrument and check every command its driver declares (the engine is driver_verify.py).

    open_driver_verify(parent, **kw) -> DriverVerifyWindow

Pick the driver, give the VISA address (and the baud rate for RS-232), Connect, tick the commands to test and press Run.  Queries are ticked for you;
set / output / reset commands are never ticked by default and are listed in a confirmation (outputs need the word OUTPUT typed) before any of them is sent.
The instrument is put back to standby / off after every output command.  Results can be saved as a record in lab_registry.sqlite3 and exported as CSV;
the driver `verified` flags in the code are never edited here: the Findings list shows where the bench and the flag disagree.
A run on the simulated bench is labelled SIMULATED and cannot be saved.  No Tk import."""
from __future__ import annotations

import getpass
import queue
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget, QDialog

import driver_verify as V
from qtui.table import Column, DataTable
from qtui.theme import M
from qtui.widgets import Banner, MessageDialog, PrimaryButton, SecondaryButton, label

INTRO = ('Sends the commands your drivers declare to a real instrument and checks the answers. Queries run on their own. Set, output and reset commands are '
         'sent only after you confirm the list, once each and never retried; outputs go back to standby/off afterwards. Calibration, security and service '
         'commands are never sent. Results are a record only: the driver verified flags are not changed.')
SIM_DRIVERS = {'Fluke5560A', 'Fluke5522A', 'Fluke5520A'}
BADGES = {'pass': 'good', 'check': 'warn', 'fail': 'bad', 'skipped': 'neutral', '': 'neutral'}


class _Row:
    def __init__(self, step, flag):
        self.step, self.pick, self.flag = step, step.default_on, flag
        self.result = None

    @property
    def status(self):
        if self.result is None:
            return 'skipped' if self.step.skip_reason else ''
        return self.result.status + (' ✓' if self.result.confirmed_by_tester else '')

    @property
    def detail(self):
        r = self.result
        if r is None:
            return self.step.skip_reason
        return r.error or r.note or r.reply


class DriverVerifyWindow(QDialog):
    def __init__(self, parent=None, transport_factory=None, catalog=None, db=None):
        super().__init__(parent)
        self.setWindowTitle('Driver verification')
        self.resize(1180, 760)
        self.setMinimumSize(820, 560)
        self.setModal(False)
        self.transport_factory = transport_factory or self._default_transport
        self.catalog = catalog if catalog is not None else V.driver_catalog()
        self.db = db
        self.driver = self.verifier = None
        self.simulated = False
        self.results = []
        self.rows = []
        self.plan = []
        self.events = queue.Queue()
        self.thread = None
        self.last_run_id = ''

        body = QVBoxLayout(self)
        body.setContentsMargins(M.xl, M.lg, M.xl, M.lg)
        body.setSpacing(M.sm + 2)
        body.addWidget(label('Driver verification', 'h2'))
        body.addWidget(Banner(INTRO, 'info'))

        bar = QHBoxLayout()
        self.driver_box = QComboBox()
        self.driver_box.addItems([c[0] for c in self.catalog])
        self.address_e = QLineEdit()
        self.address_e.setPlaceholderText('VISA address, e.g. GPIB0::4::INSTR or ASRL9::INSTR')
        self.address_e.setMinimumWidth(280)
        self.baud_e = QLineEdit('9600')
        self.baud_e.setMaximumWidth(70)
        self.sim_cb = QCheckBox('Simulated bench')
        self.tester_e = QLineEdit(getpass.getuser())
        self.tester_e.setMaximumWidth(150)
        self.btn_connect = PrimaryButton('Connect', on_click=self.connect_driver)
        for w, s in ((label('Driver'), 0), (self.driver_box, 2), (label('Address'), 0), (self.address_e, 3), (label('Baud'), 0), (self.baud_e, 0),
                     (self.sim_cb, 0), (label('Tester'), 0), (self.tester_e, 0), (self.btn_connect, 0)):
            bar.addWidget(w, s)
        body.addLayout(bar)
        self.driver_box.currentIndexChanged.connect(self._driver_changed)
        self.state = label('Not connected.', 'muted')
        body.addWidget(self.state)

        cols = [Column('pick', 'Test', width=48, kind='checkbox', editable=lambda r: r.step.sendable, getter=lambda r: r.pick, setter=self._set_pick),
                Column('key', 'Command', width=190, getter=lambda r: r.step.key),
                Column('wire', 'Sent as', width=250, mono=True, getter=lambda r: r.step.wire, stretch=True),
                Column('mode', 'Kind', width=64, getter=lambda r: r.step.mode),
                Column('flag', 'Driver says', width=104, getter=lambda r: 'verified' if r.flag else 'unverified',
                       tone=lambda r: 'good' if r.flag else 'muted'),
                Column('status', 'Result', width=84, kind='badge', badge=lambda v, r: BADGES.get(str(v).split()[0] if v else '', 'neutral'), getter=lambda r: r.status),
                Column('detail', 'Reply / note', width=330, getter=lambda r: r.detail)]
        self.table = DataTable(cols, [], row_key=id, empty_text='Connect to an instrument to list its commands.')
        body.addWidget(self.table, 1)

        pick_bar = QHBoxLayout()
        self.btn_queries = SecondaryButton('Tick all queries', on_click=lambda: self.tick('query'))
        self.btn_sets = SecondaryButton('Tick set commands', on_click=lambda: self.tick('set'))
        self.btn_none = SecondaryButton('Untick all', on_click=lambda: self.tick(None))
        self.btn_ok = SecondaryButton('Mark selected "check" as OK', on_click=lambda: self.settle(True))
        self.btn_bad = SecondaryButton('Mark selected "check" as failed', on_click=lambda: self.settle(False))
        for b in (self.btn_queries, self.btn_sets, self.btn_none):
            pick_bar.addWidget(b)
        pick_bar.addStretch(1)
        for b in (self.btn_ok, self.btn_bad):
            pick_bar.addWidget(b)
        body.addLayout(pick_bar)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        body.addWidget(self.progress)
        body.addWidget(label('Findings', 'h3'))
        self.findings = QPlainTextEdit()
        self.findings.setReadOnly(True)
        self.findings.setMaximumHeight(110)
        body.addWidget(self.findings)

        foot = QHBoxLayout()
        self.btn_run = PrimaryButton('Run ticked commands', on_click=self.run_ticked)
        self.btn_stop = SecondaryButton('Stop', on_click=self.stop)
        self.btn_save = SecondaryButton('Save record', on_click=self.save_record)
        self.btn_csv = SecondaryButton('Export CSV...', on_click=self.export_csv)
        self.btn_disc = SecondaryButton('Disconnect', on_click=self.disconnect_driver)
        foot.addWidget(self.btn_run)
        foot.addWidget(self.btn_stop)
        foot.addStretch(1)
        for b in (self.btn_save, self.btn_csv, self.btn_disc):
            foot.addWidget(b)
        body.addLayout(foot)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self._driver_changed()
        self._buttons()

    # ------------------------------------------------------------------ connection
    @property
    def driver_class(self):
        return self.catalog[self.driver_box.currentIndex()][1] if self.catalog else None

    def _driver_changed(self, *_):
        cls = self.driver_class
        if cls is None:
            return
        self.sim_cb.setEnabled(cls.__name__ in SIM_DRIVERS)
        if cls.__name__ not in SIM_DRIVERS:
            self.sim_cb.setChecked(False)
        self.baud_e.setEnabled(True)

    def _default_transport(self, cls, address, baud, simulated):
        if simulated:
            from drivers.simulated import make_bench
            return make_bench()[1]
        import drivers
        return drivers.open_visa(address, baud=int(baud)) if address.upper().startswith('ASRL') else drivers.open_visa(address)

    def connect_driver(self):
        cls = self.driver_class
        if cls is None or self.driver is not None:
            return
        sim = self.sim_cb.isChecked()
        address = self.address_e.text().strip()
        if not sim and not address:
            self._say('Type the instrument address first.')
            return
        try:
            transport = self.transport_factory(cls, address, self.baud_e.text().strip() or '9600', sim)
            drv = cls(transport)
            drv.open(verify_model=not sim)
        except Exception as exc:
            self._say(f'Could not connect: {type(exc).__name__}: {exc}')
            return
        self.driver, self.simulated = drv, sim
        self.verifier = V.Verifier(drv, confirm=self._approved, simulated=sim)
        self.plan = V.build_plan(drv)
        saved = V.last_status(cls.__name__, self.db) if not sim else {}
        self.rows = [_Row(s, bool(s.cmd.verified)) for s in self.plan]
        self.results = []
        self.table.set_rows(self.rows, keep_selection=False)
        c = V.counts(self.plan)
        self._say(('SIMULATED - ' if sim else '') + f'Connected: {drv.idn or cls.MODEL}.  {c["query"]} queries, {c["set"]} set, {c["output"]} output, '
                  f'{c["locked"]} reset, {c["skipped"]} cannot be sent.' + (f'  {len(saved)} commands have an earlier saved result.' if saved else ''))
        self._buttons()

    def disconnect_driver(self):
        if self.thread is not None and self.thread.is_alive():
            return
        if self.driver is not None:
            try:
                self.driver.cleanup()
                self.driver.close()
            except Exception:
                pass
        self.driver = self.verifier = None
        self._say('Not connected.')
        self._buttons()

    # ------------------------------------------------------------------ ticking
    def _set_pick(self, row, value):
        row.pick = bool(value)

    def tick(self, mode):
        wanted = {'query': ('query',), 'set': ('set', 'output')}.get(mode, ())
        for r in self.rows:
            r.pick = r.step.sendable and r.step.mode in wanted
        self.table.refresh()

    def settle(self, ok):
        for r in self.table.selected_rows():
            if r.result is not None and r.result.status == 'check':
                r.result.confirmed_by_tester = True
                if not ok:
                    r.result.status, r.result.error = 'fail', 'judged wrong by the tester'
                    r.result.confirmed_by_tester = False
                else:
                    r.result.status = 'pass'
                    r.result.confirmed_by_tester = True
        self.table.refresh()
        self._findings()

    # ------------------------------------------------------------------ running
    def _confirm_list(self, steps) -> bool:
        """The one confirmation before any non-query command is sent. Tests replace this."""
        lines = [f'{s.key:28s} {s.wire}   [{s.mode}]' for s in steps]
        dlg = MessageDialog(self, 'warning', 'Send these commands?',
                            f'{len(steps)} command(s) will be sent to {self.driver.idn or self.driver.label}, once each, never retried. They can change the '
                            'instrument\'s state; outputs are put to standby/off afterwards.',
                            buttons=(('Send them', 'go', 'primary'), ('Cancel', 'cancel', 'secondary')), cancel_key='cancel', detail='\n'.join(lines))
        if dlg.run() != 'go':
            return False
        if any(s.mode in ('output', 'locked') for s in steps):
            text, ok = QInputDialog.getText(self, 'Output / reset commands', 'The list includes output or reset commands. Type OUTPUT to go on:')
            return bool(ok and text.strip().upper() == 'OUTPUT')
        return True

    def _approved(self, step) -> bool:
        return step.key in self._approved_keys

    def run_ticked(self):
        if self.driver is None or (self.thread is not None and self.thread.is_alive()):
            return
        steps = [r.step for r in self.rows if r.pick and r.step.sendable]
        if not steps:
            self._say('Tick at least one command.')
            return
        risky = [s for s in steps if s.mode != 'query']
        self._approved_keys = set()
        if risky:
            if not self._confirm_list(risky):
                self._say('Cancelled: nothing was sent.')
                return
            self._approved_keys = {s.key for s in risky}
        self.verifier.stop = False
        self._run_steps = steps
        self.progress.setRange(0, len(steps))
        self.progress.setValue(0)

        def work():
            try:
                self.verifier.run_plan(steps, progress=lambda i, st, r: self.events.put(('step', i, st, r)))
            finally:
                self.events.put(('done',))
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self.timer.start(80)
        self._buttons()

    def stop(self):
        if self.verifier is not None:
            self.verifier.stop = True

    def _poll(self):
        by_key = {r.step.key: r for r in self.rows}
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            if ev[0] == 'step':
                _t, i, st, res = ev
                by_key[st.key].result = res
                self.progress.setValue(i + 1)
            else:
                self.timer.stop()
                self._buttons()
                self._findings()
        self.table.refresh()

    def wait(self, timeout=60.0):
        """Block (processing events) until the running thread has finished - for tests."""
        from PySide6.QtWidgets import QApplication
        import time
        t0 = time.monotonic()
        while self.thread is not None and (self.thread.is_alive() or not self.events.empty()) and time.monotonic() - t0 < timeout:
            QApplication.processEvents()
            self._poll()
            time.sleep(0.01)
        self._poll()

    def _findings(self):
        results = [r.result for r in self.rows if r.result is not None]
        self.results = results
        notes = V.compare_flags(self.plan, results)
        c = {s: sum(1 for r in results if r.status == s) for s in ('pass', 'check', 'fail')}
        head = ('SIMULATED - NOT EVIDENCE.  ' if self.simulated else '') + f'{c["pass"]} passed, {c["check"]} to check, {c["fail"]} failed.'
        self.findings.setPlainText('\n'.join([head] + [f'{f.level.upper():5s} {f.text}' for f in notes]))

    # ------------------------------------------------------------------ records
    def save_record(self):
        if not self.results:
            self._say('Run some commands first.')
            return
        try:
            self.last_run_id = V.save_results(self.plan, self.results, driver_name=type(self.driver).__name__, model=getattr(self.driver, 'MODEL', ''),
                                              idn=self.driver.idn, address=self.address_e.text().strip(), tester=self.tester_e.text().strip(),
                                              simulated=self.simulated, db=self.db)
        except V.SimulatedError as exc:
            self._say(str(exc))
            return
        self._say(f'Saved as {self.last_run_id}.')

    def _csv_path(self):
        path, _f = QFileDialog.getSaveFileName(self, 'Export results', f'driver_verification_{type(self.driver).__name__}.csv', 'CSV (*.csv)')
        return path

    def export_csv(self):
        if not self.results:
            self._say('Run some commands first.')
            return
        path = self._csv_path()
        if path:
            V.write_csv(path, self.plan, self.results, driver_name=type(self.driver).__name__, model=getattr(self.driver, 'MODEL', ''), idn=self.driver.idn,
                        address=self.address_e.text().strip(), tester=self.tester_e.text().strip(), simulated=self.simulated)
            self._say(f'Exported {path}.')

    # ------------------------------------------------------------------ small things
    def _say(self, text):
        self.state.setText(text)

    def _buttons(self):
        connected = self.driver is not None
        running = self.thread is not None and self.thread.is_alive()
        self.btn_connect.setEnabled(not connected)
        self.btn_run.setEnabled(connected and not running)
        self.btn_stop.setEnabled(running)
        self.btn_disc.setEnabled(connected and not running)
        for b in (self.btn_save, self.btn_csv, self.btn_queries, self.btn_sets, self.btn_none, self.btn_ok, self.btn_bad):
            b.setEnabled(connected and not running)
        self.driver_box.setEnabled(not connected)
        self.address_e.setEnabled(not connected)

    def closeEvent(self, ev):
        if self.thread is not None and self.thread.is_alive():
            self.stop()
            self.thread.join(5)
        self.disconnect_driver()
        super().closeEvent(ev)


def open_driver_verify(parent, **kw):
    w = DriverVerifyWindow(parent, **kw)
    w.show()
    return w
