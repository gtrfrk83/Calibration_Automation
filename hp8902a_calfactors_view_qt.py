"""HP 8902A cal-factor entry: the Qt window code (the launcher reaches it through `ui_port.ui.view('hp8902a_calfactors_view')`).

Every function takes the launcher's App as `self` and keeps its widgets as attributes of it (`btn_*`, `pill_*`, `grid`, `tree`, `log_table`, `log_box`).  `self.root` is the QMainWindow made by
run_app.  Nothing here decides anything about the table or the instrument: layout only.  No Tk."""
import sys

from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem

from qtui import adjust_window as aw
from qtui import shell_helpers as ui
from qtui.theme import M
from qtui.vars import QtVar


def _eng(self):
    return sys.modules[type(self).__module__]


def setup_window(self):
    E = _eng(self)
    aw.setup_window(self.root, E.TITLE.replace('  -  ', ' | ') + (' [DEMO]' if self.demo else ''), 1200, 900, 960, 680)


def build_ui(self):
    E = _eng(self)
    banner = ui.Banner(None, E.TITLE, 'Enter the power sensor calibration factors  |  8902A Operating and Calibration Manual pp. 3-75 to 3-78, 3-82, 3-87  |  HP-IB')
    if self.demo:
        banner.add_pill('DEMO MODE  -  virtual instruments, nothing saved', 'warn')
    self.pill_rx = banner.add_pill('8902A: not connected', 'neutral')
    self.pill_run = banner.add_pill('No record', 'neutral')
    body = aw.new_page(self.root, banner, ui.StatusBar(None, self.status, right='v1'))
    body.addWidget(aw.notice(E.NOTICE, 'bad', 'This changes the cal-factor table stored in the 8902A'))

    top = QHBoxLayout()
    top.setSpacing(M.lg)
    who, wg, nxt = aw.who_card(self)
    aw.put(wg, aw.plain('Sensor model *'), nxt, 0)
    aw.put(wg, aw.entry(self.sensor_model, 20), nxt, 1)
    aw.put(wg, aw.plain('Sensor serial *'), nxt + 1, 0)
    aw.put(wg, aw.entry(self.sensor_serial, 20), nxt + 1, 1)
    top.addWidget(who)
    link, f = aw.link_card('2  Connect the 8902A', 2)
    f.field('GPIB address', aw.entry(self.addr, 16))
    f.full(ui.label_(None, 'The sensor must be on the SENSOR input. Reading the table changes nothing.', 'Muted.TLabel', wraplength=1))
    top.addWidget(link, 1)
    body.addLayout(top)

    body.addLayout(aw.hint_row(self))

    edit, g = aw.card('3  Cal-factor table from the sensor label (type MHz and %; a unit such as 2 GHz is accepted)')
    aw.put(g, aw.plain('Reference cal factor, 50 MHz (%)'), 0, 0)
    aw.put(g, aw.entry(self.reference, 10), 0, 1)
    g.addWidget(ui.checkbutton(None, 'Remove entries of the 8902A that are not in my list (entered as 0 %)', self.remove_stale), 0, 2)
    self.grid = QTableWidget(16, 2)
    self.grid.setHorizontalHeaderLabels(['Frequency (MHz)', 'Cal factor (%)'])
    self.grid.setVerticalHeaderLabels([str(i) for i in range(1, 17)])
    self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    self.grid.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
    self.grid.setMinimumHeight(M.row_h * 6)
    for r in range(16):
        for c in range(2):
            self.grid.setItem(r, c, QTableWidgetItem(''))
    g.addWidget(self.grid, 1, 0, 1, 3)
    g.setColumnStretch(2, 1)
    top2 = QHBoxLayout()
    top2.setSpacing(M.lg)
    top2.addWidget(edit, 1)

    self.tree = aw.step_table(('n', 'mhz', 'pct', 'read', 'state'), ('#', 'Frequency (MHz)', 'Entered (%)', 'Read back (%)', 'Result'), (40, 130, 110, 110, 220),
                              {'n': 'w', 'mhz': 'w', 'pct': 'w', 'read': 'w', 'state': 'w'}, {'n': False, 'state': False}, 8)
    side, sg = aw.card('4  Table in the 8902A')
    sg.addWidget(self.tree, 0, 0)
    top2.addWidget(side, 1)
    body.addLayout(top2, 1)

    self.btn_connect = ui.button(None, 'Connect', self.connect)
    self.btn_start = ui.button(None, 'Start record and read table', self.start_record)
    self.btn_check = ui.button(None, 'Check my list', self.check_list)
    self.btn_enter = ui.button(None, 'Enter table into the 8902A', self.enter_table, 'Accent.TButton')
    self.btn_load = ui.button(None, 'Load saved table', self.load_saved)
    self.btn_save = ui.button(None, 'Save my list', self.save_list)
    self.btn_abort = ui.button(None, 'Abort', self.abort, 'Danger.TButton')
    self.btn_close = ui.button(None, 'Disconnect', self.disconnect)
    self.show_log = QtVar(True, 'bool')
    body.addLayout(aw.button_bar((self.btn_connect, self.btn_start, self.btn_check, self.btn_enter, self.btn_load, self.btn_save), (self.btn_close, self.btn_abort), self.show_log, self._toggle_log))

    self.log_table = aw.log_table(('time', 'step', 'action', 'outcome', 'detail'), ('Time', 'Entry', 'Action', 'Outcome', 'Detail'), (170, 70, 130, 130, 640),
                                  {'detail': 'w', 'action': 'w', 'time': 'w', 'step': 'w'}, {'time': False, 'step': False, 'action': False, 'outcome': False}, 6)
    self.log_box = aw.log_card('Audit log (this record)', self.log_table, bool(self.show_log.get()))
    body.addWidget(self.log_box)


def toggle_log(self):
    self.log_box.setVisible(bool(self.show_log.get()))


def rows_get(self):
    """[(frequency text, cal-factor text)] of the 16 rows as typed."""
    out = []
    for r in range(self.grid.rowCount()):
        a, b = self.grid.item(r, 0), self.grid.item(r, 1)
        out.append(((a.text() if a else ''), (b.text() if b else '')))
    return out


def rows_set(self, rows):
    for r in range(self.grid.rowCount()):
        f, c = rows[r] if r < len(rows) else ('', '')
        self.grid.item(r, 0).setText(str(f))
        self.grid.item(r, 1).setText(str(c))


def rows_lock(self, locked):
    self.grid.setEnabled(not locked)


def sync_pills(self, live):
    self.pill_rx.set(('8902A: DEMO (simulated)' if self.demo else '8902A: connected') if live else '8902A: not connected', 'warn' if (live and self.demo) else 'good' if live else 'neutral')
    rid = self.audit.run_id
    self.pill_run.set(('DEMO record (not saved)' if self.demo else f'Record #{rid}') if rid else 'No record', 'info' if rid else 'neutral')


def sync_buttons(self, connect, start, check, enter, load, save, abort, close):
    aw.enable(self.btn_connect, connect)
    aw.enable(self.btn_start, start)
    aw.enable(self.btn_check, check)
    aw.enable(self.btn_enter, enter)
    aw.enable(self.btn_load, load)
    aw.enable(self.btn_save, save)
    self.btn_abort.configure(state='normal' if abort else 'disabled')
    aw.enable(self.btn_close, close)


def table_clear(self):
    self.tree.delete(*self.tree.get_children())


def table_add(self, iid, values, tags):
    self.tree.insert('', 'end', iid=iid, values=values, tags=tags)


def log_add(self, values, tags):
    self.log_table.prepend(values, tags)


def log_clear(self):
    self.log_table.clear()
