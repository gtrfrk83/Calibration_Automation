"""Tektronix MDO4000C performance verification: the Qt window code, the twin of mdo4000c_view_tk.py (package QT-G2a).

Same functions, arguments and App attributes as the Tk view (`self.tree`, `self.btn_run`, `self.cfg_widgets`, `self.addr_boxes`, `self.btn_read_opts` ...); the engine reaches it
through `ui_port.ui.view('mdo4000c_view')`.  The engine's request queue and 50 ms pump are the engine's own and unchanged: this view only builds the window.  Every label,
button name, order and default is the Tk view's; only the look is the Qt design system's.  Nothing here decides anything about a calibration.  No Tk import.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

import datamode
import virtualbench
from qtui import shell_helpers as H
from genscope_support_view_qt import (action_bar, address_box, attach_history, detail_panel, drawer_buttons, drawer_check, drawer_note, drawer_row, drawer_separator, filter_bar, follow_prefixed,
                                   set_choices_for, table_has, table_select, table_selection, table_set_rows, table_update_row, widen_columns)  # noqa: F401  (the table_* names are the view's API)
from qtui.shell import Shell, results_table, small_window


def setup_window(self):
    """Title and size of the main window (the Qt twin of the Tk statements)."""
    root, demo = self.root, self.demo
    H.apply_theme(root)
    root.setWindowTitle('Tektronix MDO4000C | Performance Verification' + (' [DEMO]' if demo else ''))
    H.fit_window(root, 1380, 880, min_w=900, min_h=680)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last window statement of the engine's former App.__init__)."""
    attach_history(self)


def build_ui(self):
    import mdo4000c_verification as E                      # the engine's module state (configure(model) rebinds MODEL / POINTS / SPEC), read at call time
    MODELS, POINTS, SPEC = E.MODELS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = Shell(root, 'Tektronix MDO4000C  -  Performance Verification',
                            f'MDO4024C / 4034C / 4054C / 4104C  |  {SPEC["source"]["document"]}  |  {len(POINTS)} points in the spec',
                            demo=self.demo, on_section=self.pick_section, version='spec v2', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice('The program stops and asks you to confirm every cable, terminator, instrument or front-panel change before the next point. '
                    'Stay at the bench: high-voltage DC points (to 99.5 V) and RF outputs are enabled only after you confirm.', 'info')

    d = sh.drawer_body
    m = drawer_row(d, 0, 'Model', H.combobox(None, self.v_model, ['MDO' + x for x in MODELS], width=10), left=True)
    self.v_model.set('MDO' + self.v_model.get().replace('MDO', ''))
    follow_prefixed(m, self.v_model, 'MDO')                  # the engine strips the prefix from the variable again (on_config)
    sa = drawer_row(d, 1, 'Spectrum analyzer', H.combobox(None, self.v_sa, ['None', 'SA3', 'SA6'], width=10), left=True)
    checks = [drawer_check(d, 2, 'AFG (MDO4AFG)', self.v_afg, self.on_config),
              drawer_check(d, 3, 'DVM', self.v_dvm, self.on_config),
              drawer_check(d, 4, 'TPA-N-PRE attached', self.v_tpa, self.on_config)]
    self.btn_read_opts = H.button(None, 'Read options from scope', self.read_options)
    d.layout().addWidget(self.btn_read_opts, 5, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
    self.cfg_widgets = [m, sa] + checks
    for w in (m, sa): w.activated.connect(lambda _i=0: self.on_config())
    drawer_separator(d, 6)
    rows = [('scope', 'MDO4000C (USB)'), ('cal', 'Fluke 5560A'), ('rf1', 'Fluke 96270A (RF)'), ('rf2', 'RF source 2 (IMD only)'),
            ('gen', 'Agilent 33220A / 33250A'), ('dmm', 'Reference DMM (AFG)'), ('counter', 'Counter (AFG freq)'), ('power', 'Power meter (optional)')]
    self.addr_boxes = {}
    for i, (key, label) in enumerate(rows):
        self.addr_boxes[key] = drawer_row(d, 7 + i, label, address_box(self.addr[key]))
    drawer_row(d, 7 + len(rows), '5560A baud', H.combobox(None, self.addr['cal_baud'], ['9600', '19200', '4800', '2400', '1200'], width=9), left=True)
    drawer_note(d, 8 + len(rows), 'Leave an address blank if that instrument is not used. Without a reference DMM / counter the AFG readings are typed in.')
    drawer_buttons(self, sh)

    action_bar(self, sh)
    self.pm_live_attach(sh)                                    # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well, usable during a run

    body = sh.content
    filt = filter_bar(self, body, datamode.STATUS_FILTERS + ['Skipped'])
    self.tree = results_table(self, body)
    widen_columns(self.tree)
    small_window(self, self.tree, filt)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    detail_panel(self, body)
    H.polish(root)


def sync_buttons(self):
    from genscope_support_view_qt import sync_buttons as _sync
    _sync(self, self.cfg_widgets)


def set_choices(self, values):
    """The drop-down values of every instrument address box."""
    set_choices_for(self.addr_boxes.values(), values)
