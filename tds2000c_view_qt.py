"""Tektronix TDS2000C performance verification: the Qt window code, the twin of tds2000c_view_tk.py (package QT-G2a).

Same functions, arguments and App attributes as the Tk view (`self.tree`, `self.btn_run`, `self.cfg_widgets`, `self.addr_boxes`, `self.btn_read_model` ...); the engine reaches it
through `ui_port.ui.view('tds2000c_view')`.  The engine's request queue and 50 ms pump are the engine's own and unchanged.  Every label, button name, order and default is
the Tk view's (the TDS window has no 'Edit point' action, as in Tk); only the look is the Qt design system's.  Nothing here decides anything about a calibration.  No Tk import.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

import datamode
import virtualbench
from qtui import shell_helpers as H
from genscope_support_view_qt import (action_bar, address_box, attach_history, detail_panel, drawer_buttons, drawer_note, drawer_row, drawer_separator, filter_bar, follow_prefixed,
                                   table_has, table_select, table_selection, table_set_rows, table_update_row, widen_columns, share_table)  # noqa: F401  (the table_* names are the view's API)
from qtui.shell import Shell, results_table, small_window


def setup_window(self):
    """Title and size of the main window (the Qt twin of the Tk statements)."""
    import tds2000c_verification as E
    fam = getattr(self, 'fam', None) or E.TDS_FAMILY
    root, demo = self.root, self.demo
    H.apply_theme(root)
    root.setWindowTitle(f'Tektronix {fam.name} | Performance Verification' + (' [DEMO]' if demo else ''))
    H.fit_window(root, 1380, 880, min_w=900, min_h=680)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last window statement of the engine's former App.__init__)."""
    attach_history(self)


def build_ui(self):
    import tds2000c_verification as E                      # the engine's module state (configure(model) rebinds MODEL / POINTS / SPEC), read at call time
    fam = getattr(self, 'fam', None) or E.TDS_FAMILY             # the family this window runs (TDS2000C, or a TBS family of tbs1000_verification.py)
    CAL_CHOICES, MODELS, POINTS, SPEC = E.CAL_CHOICES, fam.models, fam.points, fam.spec
    root = self.root
    sh = self.shell = Shell(root, f'{fam.title}  -  Performance Verification',
                            f'{SPEC["source"]["document"]}  |  {len(POINTS)} points in the spec',
                            demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice('The program stops and asks you to confirm every cable, terminator and splitter change before the next point. '
                    'Stay at the bench; the calibrator is returned to STANDBY after every point.', 'info')

    d = sh.drawer_body
    m = drawer_row(d, 0, 'Model', H.combobox(None, self.v_model, [fam.prefix + x for x in MODELS], width=14), left=True)
    self.v_model.set(fam.prefix + self.v_model.get().replace(fam.prefix, ''))
    follow_prefixed(m, self.v_model, fam.prefix)                  # the engine strips the prefix from the variable again (on_config)
    self.btn_read_model = H.button(None, 'Read model from scope', self.read_model)
    d.layout().addWidget(self.btn_read_model, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
    self.cfg_widgets = [m]
    m.activated.connect(lambda _i=0: self.on_config())
    drawer_separator(d, 2)
    self.addr_boxes = {}
    for i, (key, label) in enumerate([('scope', fam.addr_label), ('cal', 'Calibrator (COM or GPIB)')]):
        self.addr_boxes[key] = drawer_row(d, 3 + i, label, address_box(self.addr[key]))
    drawer_row(d, 5, 'Calibrator', H.combobox(None, self.addr['cal_model'], CAL_CHOICES, width=14), left=True)
    drawer_row(d, 6, 'Calibrator baud', H.combobox(None, self.addr['cal_baud'], ['9600', '19200', '4800', '2400', '1200'], width=9), left=True)
    drawer_note(d, 7, 'The oscilloscope is connected by USB. All outputs (DC volts, leveled sine, time marker) come from the calibrator scope option.')
    drawer_buttons(self, sh)

    action_bar(self, sh)

    body = sh.content
    filt = filter_bar(self, body, datamode.STATUS_FILTERS + ['Skipped'])
    self.tree = results_table(self, body)
    widen_columns(self.tree)
    small_window(self, self.tree, filt)
    share_table(self)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    detail_panel(self, body)
    H.polish(root)


def sync_buttons(self):
    from genscope_support_view_qt import sync_buttons as _sync
    _sync(self, self.cfg_widgets)

