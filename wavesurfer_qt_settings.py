"""WaveSurfer 4104HD Qt window: the 'Test settings' dialog (Qt twin of `show_settings_dialog` of wavesurfer_view_tk.py).

Same title, same section headings and row labels in the same order, same variables, the same two notes and one 'Close' button (Esc closes too).  The entries are bound to
the engine's variables, so a change is in effect at once (as in Tk).  Modal: the engine's ask runs it as `self.root.wait_window(win)` did.  The 23 rows can be taller than a
small screen, so the form scrolls inside the dialog instead of running off the screen."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QScrollArea, QWidget

import qtui.shell_helpers as H
from qtui.prompts import fit_dialog

import wavesurfer_qt_common as K

NOTE_TOP = 'Used by Run Pending. Changing the RMS-noise settings after a run has started requires clearing that function first.'
NOTE_BOTTOM = ('RMS noise: P1 StdDev and source are set automatically. Formula: 20 log10((factor x V/div) / RMS). The 2.75-division factor is user-reported as verified '
               'with Teledyne; confirm limits and decision rule before release.')


def rows(self):
    """(label, variable, kind) in the order of the Tk dialog; kind None = a section heading."""
    return (('RMS noise', None, None),
            ('  Channel', self.channel, 'combo'), ('  Test all 4 channels', self.all_channels, 'check'), ('  Settle (s)', self.delay, 'entry'),
            ('  Samples per range', self.samples, 'entry'), ('  dB factor (div)', self.ref_factor, 'entry'), ('  Minimum limits (dB), 9 values', self.limit_text, 'wide'),
            ('DC voltage', None, None),
            ('  Settle after OPER (s)', self.dc_settle, 'entry'), ('  Automatic Fluke output', self.dc_auto_fluke, 'check'), ('  Scope P1 MEAN acquisition', self.dc_p1_mode, 'check'),
            ('Input impedance', None, None), ('  Settle (s)', self.imp_settle, 'entry'), ('  Samples', self.imp_samples, 'entry'),
            ('Offset', None, None), ('  Settle (s)', self.offset_settle, 'entry'),
            ('Bandwidth', None, None), ('  Settle (s)', self.bw_settle, 'entry'),
            ('Time base', None, None), ('  Marker period (µs)', self.tb_period_us, 'entry'), ('  Settle after OPER (s)', self.tb_settle, 'entry'),
            ('  P1 Freq readings', self.tb_samples, 'entry'),
            ('Trigger level', None, None), ('  Settle after each step (s)', self.trig_settle, 'entry'))


def build(self, parent=None):
    """The dialog, not yet shown (tests drive it; show_settings_dialog runs it)."""
    dlg = H.dialog(parent if parent is not None else self.root, 'Test settings', width=620)
    dlg.add_text(NOTE_TOP, 'sub')
    form = QWidget()
    grid = QGridLayout(form)
    grid.setContentsMargins(0, 0, 8, 0)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(4)
    grid.setColumnStretch(2, 1)
    dlg.fields = {}                                   # 'Section: label' -> the widget (a label such as 'Settle (s)' occurs in several sections)
    section = ''
    for r, (label_, var, kind) in enumerate(rows(self)):
        if kind is None:
            section = label_
            head = H.label_(None, label_, 'Bold.TLabel')
            grid.addWidget(head, r, 0, 1, 3)
            grid.setRowMinimumHeight(r, 26)
            continue
        grid.addWidget(H.label_(None, label_), r, 0)
        if kind == 'entry':
            w = H.entry(None, var, width=10)
            w.setFixedWidth(110)
        elif kind == 'wide':
            w = H.entry(None, var, width=34)
            w.setMinimumWidth(300)
        elif kind == 'combo':
            w = H.combobox(None, var, ['1', '2', '3', '4'], width=6, state='readonly')
            w.setFixedWidth(110)
        else:
            w = H.checkbutton(None, '', var)
        w.setAccessibleName(label_.strip())
        grid.addWidget(w, r, 1, 1, 2, Qt.AlignmentFlag.AlignLeft)
        dlg.fields[f'{section}: {label_.strip()}'] = w
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)                 # the fields take the focus, not the scroll area
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(form)
    screen = (dlg.screen() or QApplication.primaryScreen()).availableGeometry()
    scroll.setMinimumHeight(max(150, min(form.sizeHint().height() + 4, screen.height() - 330)))      # leaves room for the title, the two notes and the button
    dlg.body.addWidget(scroll)
    dlg.add_text(NOTE_BOTTOM, 'sub')
    dlg.initial_focus = next(iter(dlg.fields.values()))
    dlg.add_button('Close', role='primary', result='close', default=True, cancel=True)
    fit_dialog(dlg, 620)                                          # the height the wrapped notes need at this width (else the bottom note overlaps the form)
    return dlg


def show_settings_dialog(self):
    K.need(self.root)
    build(self).run()
