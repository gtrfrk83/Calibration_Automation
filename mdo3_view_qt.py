"""Tektronix 3 Series MDO (MDO32 / MDO34) performance verification: the Qt window code.

The engine is the shared mdo4000c_verification.py configured for the 'MDO3' family (configure('MDO3') sets App.VIEW = 'mdo3_view'); this view is the
MDO4000C Qt view (mdo4000c_view_qt.py) with the 3 Series model list, option names and texts.  Same App attributes (`self.tree`, `self.btn_run`,
`self.cfg_widgets`, `self.addr_boxes`, `self.btn_read_opts` ...), the same shared helpers (genscope_support_view_qt).  Nothing here decides anything
about a calibration.  No Tk import.  No front-panel photo and no hook-up diagrams are supplied for the 3 Series MDO (the prompts are text only).
"""
from __future__ import annotations

from PySide6.QtCore import Qt

import datamode
import virtualbench
from qtui import shell_helpers as H
from genscope_support_view_qt import (action_bar, address_box, attach_history, detail_panel, drawer_buttons, drawer_check, drawer_note, drawer_row, drawer_separator, filter_bar, follow_prefixed,
                                   set_choices_for, table_has, table_select, table_selection, table_set_rows, table_update_row, widen_columns, share_table)  # noqa: F401  (the table_* names are the view's API)
from qtui.shell import Shell, results_table, small_window

TITLE = 'Tektronix 3 Series MDO'
ADDRESS_ROWS = [('scope', '3 Series MDO (USB)'), ('cal', 'Fluke 5560A'), ('rf1', 'Fluke 96270A (RF)'),     # no second RF source: the 3 Series has no IMD test
                ('gen', 'Agilent 33220A / 33250A'), ('dmm', 'Reference DMM (AFG)'), ('counter', 'Counter (AFG freq)'), ('power', 'Power meter (optional)')]
NOTICE = ('The program stops and asks you to confirm every cable, terminator, instrument or front-panel change before the next point. '
          'Stay at the bench: high-voltage DC points (to 100 V) and RF outputs are enabled only after you confirm.')
MODEL_NOTE = ('Model = MDO32 / MDO34 and its bandwidth (3-BW option, MHz). The 1 GHz spectrum analyzer is standard; choose SA3 when 3-SA3 is installed. '
              'Leave an address blank if that instrument is not used. Without a reference DMM / counter the AFG readings are typed in.')


def setup_window(self):
    root, demo = self.root, self.demo
    H.apply_theme(root)
    root.setWindowTitle(f'{TITLE} | Performance Verification' + (' [DEMO]' if demo else ''))
    H.fit_window(root, 1380, 880, min_w=900, min_h=680)


def finish_window(self):
    attach_history(self)


def build_ui(self):
    import mdo4000c_verification as E                      # the engine's module state (configure('MDO3') rebinds MODELS / POINTS / SPEC), read at call time
    MODELS, POINTS, SPEC = E.MODELS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = Shell(root, f'{TITLE}  -  Performance Verification',
                            f'MDO32 / MDO34, 100 MHz - 1 GHz  |  {SPEC["source"]["document"]}  |  {len(POINTS)} points in the spec',
                            demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice(NOTICE, 'info')

    d = sh.drawer_body
    m = drawer_row(d, 0, 'Model', H.combobox(None, self.v_model, ['MDO' + x for x in MODELS], width=12), left=True)
    self.v_model.set('MDO' + self.v_model.get().replace('MDO', ''))
    follow_prefixed(m, self.v_model, 'MDO')                  # the engine strips the prefix from the variable again (on_config)
    sa = drawer_row(d, 1, 'Spectrum analyzer', H.combobox(None, self.v_sa, ['None', 'SA3'], width=10), left=True)
    checks = [drawer_check(d, 2, 'AFG (3-AFG)', self.v_afg, self.on_config),
              drawer_check(d, 3, 'DVM (3-DVM)', self.v_dvm, self.on_config),
              drawer_check(d, 4, 'TPA-N-PRE attached', self.v_tpa, self.on_config)]
    self.btn_read_opts = H.button(None, 'Read options from scope', self.read_options)
    d.layout().addWidget(self.btn_read_opts, 5, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
    self.cfg_widgets = [m, sa] + checks
    for w in (m, sa): w.activated.connect(lambda _i=0: self.on_config())
    drawer_separator(d, 6)
    self.addr_boxes = {}
    for i, (key, label) in enumerate(ADDRESS_ROWS):
        self.addr_boxes[key] = drawer_row(d, 7 + i, label, address_box(self.addr[key]))
    drawer_row(d, 7 + len(ADDRESS_ROWS), '5560A baud', H.combobox(None, self.addr['cal_baud'], ['9600', '19200', '4800', '2400', '1200'], width=9), left=True)
    drawer_note(d, 8 + len(ADDRESS_ROWS), MODEL_NOTE)
    drawer_buttons(self, sh)

    action_bar(self, sh)
    self.pm_live_attach(sh)

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


def set_choices(self, values):
    set_choices_for(self.addr_boxes.values(), values)
