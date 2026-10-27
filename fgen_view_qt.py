"""Function-generator performance verification (33220A / 33250A / 33210A): the Qt window code, the port of the removed Tk view fgen_view_tk.py (package QT-G2a).

Same functions, same arguments, same attributes on the engine's App (`self.tree`, `self.btn_run`, `self.entries`, `self.period_combo` ...) as the Tk view; the engine reaches
it through `ui_port.ui.view('fgen_view')`, which the Qt port resolves to this module.  Every label, button name, order and default is the Tk view's; only the look is
the Qt design system's (qtui.shell: header, section sidebar, Connections drawer, action bar, status bar).  Nothing here decides anything about a calibration.
No Tk import.
"""
from __future__ import annotations

import datamode
import virtualbench
from qtui import shell_helpers as H
from genscope_support_view_qt import (action_bar, address_box, attach_history, detail_panel, drawer_buttons, drawer_note, drawer_row, drawer_separator, filter_bar,
                                   set_choices_for, table_has, table_select, table_selection, table_set_rows, table_update_row, widen_columns, share_table)  # noqa: F401  (the table_* names are the view's API)
from qtui.shell import Shell, results_table, small_window


def setup_window(self):
    """Title and size of the main window (the Qt twin of the Tk statements)."""
    import fgen_verification as E
    root, demo = self.root, self.demo
    MODEL, SPEC = E.MODEL, E.SPEC
    H.apply_theme(root)
    root.setWindowTitle(f'{SPEC["manufacturer"]} {MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
    H.fit_window(root, 1320, 840, min_w=900, min_h=640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last window statement of the engine's former App.__init__)."""
    attach_history(self)


def build_ui(self):
    import fgen_verification as E                      # the engine's module state (configure(model) rebinds MODEL / POINTS / SPEC), read at call time
    MODEL, SPEC, POINTS, PERIODS, STD_INPUTS, COUNTER_REFS, FLAT_METHODS = E.MODEL, E.SPEC, E.POINTS, E.PERIODS, E.STD_INPUTS, E.COUNTER_REFS, E.FLAT_METHODS
    root = self.root
    src = SPEC['source']
    sh = self.shell = Shell(root, f'{SPEC["manufacturer"]} {MODEL}  -  Performance Verification',
                            f'Test points from the {MODEL} Service Guide, {src["chapter"]}, pp. {src["pages"]}  |  {len(POINTS)} points in the spec',
                            demo=self.demo, on_section=self.pick_section, version='spec v4', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice('The program switches the generator output OFF after every point and asks you to confirm the wiring before every new setup. '
                    'Power-meter flatness: the +20 dB range needs the -20 dB attenuator in front of the sensor.', 'info')

    d = sh.drawer_body
    r = 0
    self.period_combo = drawer_row(d, r, 'Limits to apply', H.combobox(None, self.period, list(PERIODS), width=20, command=self.on_period), left=True); r += 1
    self.set_combo = drawer_row(d, r, 'Test set', H.combobox(None, self.test_set, ['Full verification', 'Quick check (Q points only)'], width=26, command=self.refresh), left=True); r += 1
    drawer_separator(d, r); r += 1
    self.entries = {}
    rows = (('uut', f'{MODEL} (under test)'), ('std', 'Fluke 5790B'), ('counter', 'Frequency counter'), ('power', 'Power meter'))
    for key, label in rows:
        self.entries[key] = drawer_row(d, r, label, address_box(self.addr[key])); r += 1
    drawer_row(d, r, '5790B input', H.combobox(None, self.std_input, list(STD_INPUTS), width=22), left=True); r += 1
    drawer_row(d, r, '5790B baud', H.combobox(None, self.addr['std_baud'], ['9600', '19200', '38400', '57600', '115200'], width=9), left=True); r += 1
    self.ref_combo = drawer_row(d, r, 'Timebase', H.combobox(None, self.counter_ref, list(COUNTER_REFS), width=24, command=self.on_counter_ref), left=True); r += 1
    if len(SPEC.get('flatness_methods', ['POWER'])) > 1:
        self.method_combo = drawer_row(d, r, 'Flatness with', H.combobox(None, self.flat_method, [FLAT_METHODS[m] for m in SPEC['flatness_methods']], width=36,
                                                                          command=self.on_method), left=True); r += 1
    drawer_note(d, r, 'Leave the counter or power meter blank to type its readings. Examples: USB0::0x0957::0x0407::<serial>::INSTR   '
                      'GPIB0::10::INSTR   TCPIP0::192.168.1.20::INSTR   COM9')
    drawer_buttons(self, sh)

    action_bar(self, sh)
    self.pm_live_attach(sh)                                    # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well, usable during a run

    body = sh.content
    filt = filter_bar(self, body, datamode.STATUS_FILTERS)
    self.tree = results_table(self, body)
    widen_columns(self.tree)
    small_window(self, self.tree, filt)
    share_table(self)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    detail_panel(self, body, src['note'])
    self.update_shell_sections(POINTS, lambda p: p['section_title'])
    H.polish(root)


def sync_buttons(self):
    from genscope_support_view_qt import sync_buttons as _sync
    _sync(self, (self.period_combo, self.set_combo, self.ref_combo) + ((self.method_combo,) if hasattr(self, 'method_combo') else ()))


def set_choices(self, values):
    """The drop-down values of every instrument address box."""
    set_choices_for(self.entries.values(), values)
