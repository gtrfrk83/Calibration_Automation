"""34401A one-year verification (Agilent 34401A): the Qt window code (port of the removed Tk view a34401a_view_tk.py: same functions, same widgets as attributes of the App, same texts, same
busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('a34401a_view')`, which resolves to `a34401a_view_qt` under the Qt port.  Every function takes the engine's App
as `self`.  The engine module (`E`) is found through the App's class, because the launcher may run as __main__.  The parts the bench windows share are
qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
import sys

from qtui import bench_view as B
from qtui import shell as S
from qtui import shell_helpers as H
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window (statements of the engine's former App.__init__)."""
    B.setup_window(self, 'Agilent 34401A | Performance Verification v54' + (' [DEMO]' if self.demo else ''), 1280, 800, 900, 620)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's former App.__init__)."""
    B.finish_window(self)


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_refresh_ports),
                   [(self.dmm_combo, 'normal'), (self.fluke_combo, 'normal')])


def build_ui(self):
    E = sys.modules[type(self).__module__]                      # the engine's own module (it may run as __main__, so it is not imported by name)
    POINTS = E.POINTS
    root = self.root
    sh = self.shell = S.Shell(root, 'Agilent 34401A  -  Performance Verification', 'One-year gain and zero-offset verification  |  Keysight 34401A Service Guide, Ch. 4, pp. 67-71',
                              demo=self.demo, on_section=self.pick_section, version='v54', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    B.notice(sh, self, 'The program pauses and asks you to confirm the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.')

    f = Form(sh.drawer_body)
    self.dmm_combo = f.row('34401A port', f.combo(self.dmm_port, (), 10, state='normal'))
    self.fluke_combo = f.row('Fluke 5560A port', f.combo(self.fluke_port, (), 10, state='normal'))
    for text, var, values in (('Baud', self.baud, ['9600', '4800', '2400', '1200', '600', '300']), ('Parity', self.parity, ['Even', 'Odd', 'None']), ('Data bits', self.bits, ['7', '8'])):
        f.row(text, f.combo(var, values, 10))
    f.note('Match the DMM front-panel RS-232 settings (2 stop bits).')
    self.btn_refresh_ports = H.button(None, 'Refresh ports', self.refresh_ports)
    self.btn_test = H.button(None, 'Test connections', self.test_connections, style='Accent.TButton')
    B.drawer_footer(sh, self.btn_refresh_ports, self.btn_test)

    B.action_bar(self, sh)
    B.build_results(self, sh, 'Zero offsets are verified on BOTH the FRONT and REAR terminals. Optional AC tests are not included.', detail_wrap=900)
    self.update_shell_sections(POINTS, self._section)


def set_choices(self, which, values):
    """The drop-down values of the DMM port ('dmm') or Fluke port ('fluke') box."""
    (self.dmm_combo if which == 'dmm' else self.fluke_combo).configure(values=values)
