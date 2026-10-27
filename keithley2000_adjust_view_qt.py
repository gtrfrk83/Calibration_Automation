"""Keithley Model 2000 guided adjustment: the Qt window code.  The Qt port of the removed Tk view keithley2000_adjust_view_tk.py (same functions, same texts, same step order, same button
and pill states); the launcher reaches it through `ui_port.ui.view('keithley2000_adjust_view')`, which QtUiPort resolves to this module.

Every function takes the launcher's App as `self` and keeps its widgets as attributes of it (`btn_*`, `pill_*`, `tree`, `log_table`, `log_box`, `scope_combo`).  `self.root`
is the QMainWindow made by run_app.  The calibration code is asked by the launcher with ask_text(show='*') (a masked prompt, never logged); nothing here sees it.
Nothing here decides anything about a calibration.  No Tk.
"""
import sys

import drivers
import keithley2000_adjustment as adj
from PySide6.QtWidgets import QHBoxLayout

from qtui import adjust_window as aw
from qtui import shell_helpers as ui
from qtui.theme import M
from qtui.vars import QtVar


def _eng(self):
    """The launcher's own module (it may be __main__ when run as a script): TITLE / NOTICE live there."""
    return sys.modules[type(self).__module__]


def setup_window(self):
    """Theme, title and size of the main window."""
    E = _eng(self)
    aw.setup_window(self.root, E.TITLE.replace('  -  ', ' | ') + (' [DEMO]' if self.demo else ''), 1320, 900, 1000, 680)


def build_ui(self):
    E = _eng(self)
    banner = ui.Banner(None, E.TITLE, 'Remote :CAL:PROT command calibration, Calibration Manual 2000-905-01 Rev. F, pp. 2-14 to 2-19  |  GPIB or RS-232')
    if self.demo:
        banner.add_pill('DEMO MODE  -  virtual instruments, nothing saved', 'warn')
    self.pill_meter = banner.add_pill('2000: not connected', 'neutral')
    self.pill_run = banner.add_pill('No adjustment record', 'neutral')
    self.pill_lock = banner.add_pill('Calibration LOCKED', 'good')
    body = aw.new_page(self.root, banner, ui.StatusBar(None, self.status, right='spec v1'))
    body.addWidget(aw.notice(E.NOTICE, 'bad', 'This changes the instrument calibration'))

    top = QHBoxLayout()
    top.setSpacing(M.lg)
    who, wg, nxt = aw.who_card(self)
    aw.put(wg, aw.plain('Scope'), nxt, 0)
    self.scope_combo = aw.combo(self.scope, list(adj.SCOPES), 34, command=lambda: (self._fill_table(), self._sync()))
    aw.put(wg, self.scope_combo, nxt, 1)
    top.addWidget(who)

    link, f = aw.link_card('2  Connect: the 2000 and the calibrator', 3)
    f.field('2000 interface', aw.combo(self.interface, list(adj.INTERFACES), 8))
    f.field('GPIB address / COM port', aw.entry(self.dmm_addr, 16))
    f.field('RS-232 baud', aw.combo(self.dmm_baud, ['19200', '9600', '4800', '2400', '1200', '600', '300'], 7), muted=True)
    f.field('TX TERM', aw.combo(self.dmm_term, list(drivers.keithley_2000.TX_TERM), 6), muted=True)
    f.field('Flow control', aw.combo(self.dmm_flow, list(adj.FLOW), 10), muted=True)
    cm = f.field('Calibrator', aw.combo(self.cal_model, self.cal_choices(), 14, command=lambda: self.on_cal_model()))
    ui.Tooltip(cm, self.cal_offer.tooltip)
    f.field('Interface', aw.combo(self.cal_interface, list(adj.CAL_INTERFACES), 8, command=lambda: self.cal_addr.set(adj.CAL_PORT_DEFAULT[self.cal_interface.get()])))
    f.field('Address / port', aw.entry(self.cal_addr, 14), muted=True)
    f.field('Baud', aw.combo(self.cal_baud, ['9600', '19200', '38400', '4800', '2400'], 7), muted=True)
    f.full(ui.label_(None, '', 'Muted.TLabel', textvariable=self.cal_note, wraplength=1))
    top.addWidget(link, 1)
    body.addLayout(top)

    body.addLayout(aw.hint_row(self))

    self.tree = aw.step_table(('id', 'step', 'output', 'command', 'param', 'state'), ('ID', 'Step', 'Calibrator output', 'Command', 'Parameter', 'Status'),
                              (50, 230, 250, 230, 110, 150), {'step': 'w', 'output': 'w', 'command': 'w', 'id': 'w', 'param': 'w'}, {'id': False, 'step': False, 'state': False}, 12)
    body.addWidget(self.tree, 1)

    self.btn_connect = ui.button(None, 'Connect', self.connect)
    self.btn_start = ui.button(None, 'Start adjustment record', self.start_record)
    self.btn_unlock = ui.button(None, 'Unlock calibration', self.unlock)
    self.btn_run = ui.button(None, 'Run next step', self.run_next, 'Accent.TButton')
    self.btn_save = ui.button(None, 'Dates and SAVE', self.dates_and_save)
    self.btn_abort = ui.button(None, 'Abort and lock', self.abort, 'Danger.TButton')
    self.btn_close = ui.button(None, 'Lock and disconnect', self.disconnect)
    self.show_log = QtVar(True, 'bool')
    body.addLayout(aw.button_bar((self.btn_connect, self.btn_start, self.btn_unlock, self.btn_run, self.btn_save), (self.btn_close, self.btn_abort), self.show_log, self._toggle_log))

    self.log_table = aw.log_table(('time', 'step', 'action', 'outcome', 'detail'), ('Time', 'Step', 'Action', 'Outcome', 'Detail'), (170, 70, 110, 120, 720),
                                  {'detail': 'w', 'action': 'w', 'time': 'w', 'step': 'w'}, {'time': False, 'step': False, 'action': False, 'outcome': False}, 6)
    self.log_box = aw.log_card('Audit log (this record; no calibration code is ever written)', self.log_table, bool(self.show_log.get()))
    body.addWidget(self.log_box)


def toggle_log(self):
    self.log_box.setVisible(bool(self.show_log.get()))


def sync_pills(self, live, unlocked):
    """The three status pills."""
    self.pill_meter.set(('2000: DEMO (simulated)' if self.demo else '2000: connected') if live else '2000: not connected', 'warn' if (live and self.demo) else 'good' if live else 'neutral')
    rid = self.audit.run_id
    self.pill_run.set(('DEMO record (not saved)' if self.demo else f'Record #{rid}') if rid else 'No adjustment record', 'info' if rid else 'neutral')
    self.pill_lock.set('Calibration UNLOCKED' if unlocked else 'Calibration LOCKED', 'bad' if unlocked else 'good')


def sync_buttons(self, connect, start, unlock, run, save, abort, close, scope_locked):
    """Button states (`connect` ... `close` already include 'not busy', `abort` does not)."""
    aw.enable(self.btn_connect, connect)
    aw.enable(self.btn_start, start)
    aw.enable(self.btn_unlock, unlock)
    aw.enable(self.btn_run, run)
    aw.enable(self.btn_save, save)
    self.btn_abort.configure(state='normal' if abort else 'disabled')
    aw.enable(self.btn_close, close)
    self.scope_combo.configure(state='disabled' if scope_locked else 'readonly')


def table_clear(self):
    self.tree.delete(*self.tree.get_children())


def table_add(self, iid, values, tags):
    self.tree.insert('', 'end', iid=iid, values=values, tags=tags)
    if 'next' in tags:
        self.tree.see(iid)                            # keep the step to run next in view (the Tk list left it wherever it was)


def log_add(self, values, tags):
    self.log_table.prepend(values, tags)


def log_clear(self):
    self.log_table.clear()
