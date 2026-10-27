"""Fluke 8846A guided adjustment: the Qt window code.  The Qt port of the removed Tk view fluke8846a_adjust_view_tk.py (same functions, same texts, same step order, same button and pill
states); the launcher reaches it through `ui_port.ui.view('fluke8846a_adjust_view')`, which QtUiPort resolves to this module.

Every function takes the launcher's App as `self` and keeps its widgets as attributes of it.  The calibration password is asked by the launcher with ask_text(show='*')
(unlock and relock: masked, never logged); nothing here sees it.  Nothing here decides anything about a calibration.  No Tk.
"""
import sys

from PySide6.QtWidgets import QHBoxLayout, QWidget

from qtui import adjust_window as aw
from qtui import shell_helpers as ui
from qtui import widgets as W
from qtui.theme import M
from qtui.vars import QtVar


def _eng(self):
    """The launcher's own module (it may be __main__ when run as a script): STEPS lives there."""
    return sys.modules[type(self).__module__]


def setup_window(self):
    """Theme, title and size of the main window."""
    aw.setup_window(self.root, 'Fluke 8846A | Guided Adjustment v57' + (' [DEMO]' if self.demo else ''), 1280, 860, 1060, 680)


def build_ui(self):
    E = _eng(self)
    banner = ui.Banner(None, 'Fluke 8846A  -  Guided Adjustment',
                       'Changes calibration coefficients. Authorised technicians only. Every action is written to the audit log.')
    if self.demo:
        banner.add_pill('DEMO MODE  -  commands simulated', 'warn')
    self.pill_meter = banner.add_pill('Meter: not connected', 'neutral')
    self.pill_run = banner.add_pill('No adjustment record', 'neutral')
    self.pill_lock = banner.add_pill('Calibration LOCKED', 'good')
    body = aw.new_page(self.root, banner, ui.StatusBar(None, self.status, right='v57'))

    body.addWidget(aw.notice('Live adjustment can change calibration coefficients and CAL:REC writes them to non-volatile memory. '
                             'Only the validated open steps can be executed in this version; all other stages are guided review.', 'bad'))

    top = QHBoxLayout()
    top.setSpacing(M.lg)
    who, _wg, _n = aw.who_card(self, 22)
    top.addWidget(who)

    link, f = aw.link_card('2  Connect to the meter', 4)
    self.port_combo = f.field('8846A port', aw.combo(self.port, [], 10, 'normal'))
    self.port_combo.setFixedWidth(150)                 # COM3 ... COM256, /dev/ttyUSB0: the list is filled later
    for text, var, values in (('Baud', self.baud, ['9600', '19200', '38400', '115200', '4800', '2400']), ('Parity', self.parity, ['None', 'Even', 'Odd']),
                              ('Bits', self.bits, ['7', '8'])):
        f.field(text, aw.combo(var, values, 7), muted=True)
    self.btn_refresh = ui.button(None, 'Refresh ports', self.refresh_ports)
    self.btn_connect = ui.button(None, 'Connect / verify 8846A', self.connect, 'Accent.TButton')
    self.btn_start = ui.button(None, 'Start new adjustment record', self.start)
    self.btn_resume = ui.button(None, 'Resume existing record', self.resume)
    f.full(aw.FlowRow((self.btn_refresh, self.btn_connect, self.btn_start, self.btn_resume)))
    top.addWidget(link, 1)
    body.addLayout(top)

    row = aw.hint_row(self)
    row.itemAt(0).widget().setText('NEXT STEP')
    body.addLayout(row)

    self.tree = aw.step_table(('n', 'phase', 'step', 'setup', 'state'), ('#', 'Phase', 'Step', 'Setup', 'Status'), (40, 80, 260, 560, 150),
                              {'step': 'w', 'setup': 'w', 'phase': 'w'}, {'n': False, 'phase': False, 'step': False, 'state': False}, 14)
    for i, (phase, name, setup, _, _, enabled) in enumerate(E.STEPS):
        self.tree.insert('', 'end', iid=str(i), values=(i + 1, phase, name, setup, 'Open-step eligible' if enabled else 'Guided review'),
                         tags=('eligible',) if enabled else ())
    self.tree.bind('<<TreeviewSelect>>', lambda _e: self._on_select())
    body.addWidget(self.tree, 1)

    info = W.Card('Selected step', padding=M.md)
    info.body.addWidget(ui.label_(None, '', None, textvariable=self.detail, wraplength=1))
    body.addWidget(info)

    self.btn_review = ui.button(None, 'Mark setup reviewed', self.mark_reviewed)
    self.btn_unlock = ui.button(None, 'Unlock adjustment (authorised)', self.unlock)
    self.btn_exec = ui.button(None, 'Execute selected verified open step', self.execute, 'Accent.TButton')
    self.btn_commit = ui.button(None, 'Commit coefficients (CAL:REC)', self.commit)
    self.btn_relock = ui.button(None, 'Relock and disconnect', self.disconnect, 'Danger.TButton')
    self.show_log = QtVar(False, 'bool')
    body.addLayout(aw.button_bar((self.btn_review, self.btn_unlock, self.btn_exec, self.btn_commit), (self.btn_relock,), self.show_log, self._toggle_log))

    self.log_table = aw.log_table(('time', 'action', 'outcome', 'detail'), ('Time', 'Action', 'Outcome', 'Detail'), (170, 150, 110, 600),
                                  {'detail': 'w', 'action': 'w', 'time': 'w'}, {'time': False, 'action': False, 'outcome': False}, 5)
    self.log_box = aw.log_card('Audit log (this record)', self.log_table, bool(self.show_log.get()))
    body.addWidget(self.log_box)


def toggle_log(self):
    self.log_box.setVisible(bool(self.show_log.get()))


def table_set_state(self, idx, text, tags):
    """The status cell and row tags of one step."""
    iid = str(idx)
    vals = list(self.tree.item(iid, 'values'))
    vals[4] = text                                    # the 'state' column
    self.tree.item(iid, values=vals, tags=tags)


def table_selection(self):
    return self.tree.selection()


def set_ports(self, ports):
    """The serial-port picker's values."""
    self.port_combo.configure(values=ports)


def sync_pills(self, live, unlocked):
    """The status pills."""
    self.pill_meter.set('Meter: DEMO (simulated)' if self.demo else ('Meter: connected' if live else 'Meter: not connected'),
                        'warn' if self.demo else 'good' if live else 'neutral')
    self.pill_run.set(f'Record #{self.run_id}' if self.run_id else 'No adjustment record', 'info' if self.run_id else 'neutral')
    self.pill_lock.set('Calibration UNLOCKED' if unlocked else 'Calibration LOCKED', 'bad' if unlocked else 'good')


def sync_buttons(self, connect, start, resume, review, unlock, execute, commit, relock):
    """Button states."""
    aw.enable(self.btn_connect, connect)
    aw.enable(self.btn_start, start)
    aw.enable(self.btn_resume, resume)
    aw.enable(self.btn_review, review)
    aw.enable(self.btn_unlock, unlock)
    aw.enable(self.btn_exec, execute)
    aw.enable(self.btn_commit, commit)
    aw.enable(self.btn_relock, relock)


def log_add(self, values, tags):
    self.log_table.prepend(values, tags)


def log_clear(self):
    self.log_table.clear()
