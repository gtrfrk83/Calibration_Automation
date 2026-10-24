"""Qt twin of report_dialog.py: the report details window (technician, temperature, humidity, standards used, TAR / TUR) and the `ask_details` entry.

    from qtui.screens.report_details import ask_details
    details = ask_details(parent, 'Keysight 34470A performance verification')      # dict for report_pdf.write_calibration_pdf(details=...), or None if cancelled

Same call contract as report_dialog.ask_details(parent, procedure): the review window (qtui.screens.report_review: every point with its uncertainty,
standard changeable per row) is shown for the engines it covers; for any other engine, or when it cannot be built, the plain popup
(ask_details_plain) appears.  The returned dict has exactly the keys of the Tk dialog and the entries are remembered per user in the same
~/.calibration_suite/report_details.json (ui_theme_core.Settings), so the Tk and the Qt build share them.

`parent` is whatever the engine calls its root: a QWidget in the Qt build (the engine is found by `app.root is parent`, see report_review_flow.find_app).
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGridLayout, QLineEdit

import report_pdf
import ui_theme_core as core

from ..theme import M
from ..widgets import ModalDialog, label

USE_REVIEW = True          # False = always the plain popup below (as report_dialog.USE_REVIEW)
STANDARD_FIELDS = ('description', 'serial', 'due')
STANDARD_HEADS = ('Standard (model)', 'Serial number', 'Calibration due')
STANDARD_WIDTHS = (28, 16, 14)          # the Tk entry widths (characters); here the relative column stretch


def demo_title(title: str) -> str:
    """Every popup of a demo run says so (ui_theme.dialog does the same in Tk)."""
    return title + core.DEMO_SUFFIX


def ask_details(parent, procedure=''):
    """Returns a dict for report_pdf.write_calibration_pdf(details=...), or None if cancelled.  Review window first, plain popup otherwise."""
    if USE_REVIEW:
        try:
            from . import report_review
            from report_review_flow import UNAVAILABLE
        except Exception:
            report_review = None
        if report_review is not None:
            out = report_review.ask(parent, procedure)           # never raises; UNAVAILABLE = not covered / cannot be built
            if out is not UNAVAILABLE:
                return out
    return ask_details_plain(parent, procedure)


class StandardsGrid:
    """Three rows of (description, serial, due) line edits, as the Tk dialogs build them; shared by the plain popup and the review window's 'Standards used'."""

    def __init__(self, saved=()):
        self.layout = QGridLayout()
        self.layout.setHorizontalSpacing(M.sm)
        self.layout.setVerticalSpacing(M.xs + 2)
        for c, h in enumerate(STANDARD_HEADS):
            self.layout.addWidget(label(h, 'sub'), 0, c)
        self.edits = []
        saved = list(saved or [])
        for r in range(1, 4):
            prior = saved[r - 1] if r - 1 < len(saved) else {}
            trio = []
            for c, key in enumerate(STANDARD_FIELDS):
                e = QLineEdit(str(prior.get(key, '') or ''))
                e.setAccessibleName(f'{STANDARD_HEADS[c]} {r}')
                self.layout.addWidget(e, r, c)
                trio.append(e)
            self.edits.append(trio)
        for c, w in enumerate(STANDARD_WIDTHS):
            self.layout.setColumnStretch(c, w)

    def values(self) -> list:
        return [dict(zip(STANDARD_FIELDS, (e.text().strip() for e in trio))) for trio in self.edits]


def ask_details_plain(parent, procedure=''):
    """The original details popup (technician, conditions, standards used, TAR / TUR)."""
    store = core.Settings('report_details')
    dlg = ModalDialog(parent, 'Report details', width=640)
    dlg.setWindowTitle(demo_title('Report details'))
    dlg.sub_label.setText('Printed on the report. Everything is optional; entries are remembered for next time.')
    dlg.sub_label.show()
    grid = QGridLayout()
    grid.setHorizontalSpacing(M.md)
    grid.setVerticalSpacing(M.xs + 2)
    fields = {}
    for r, (key, text, hint) in enumerate((('technician', 'Technician', ''), ('temperature', 'Temperature', 'e.g. 23.1 °C'), ('humidity', 'Humidity', 'e.g. 45 %RH'))):
        grid.addWidget(label(text), r, 0)
        e = QLineEdit(str(store.get(key, '') or ''))
        e.setMinimumWidth(220)
        e.setAccessibleName(text)
        fields[key] = e
        grid.addWidget(e, r, 1)
        grid.addWidget(label(hint, 'sub'), r, 2)
    grid.setColumnStretch(3, 1)
    dlg.body.addLayout(grid)
    dlg.body.addSpacing(M.xs)
    dlg.body.addWidget(label('Standards used', 'section'))
    standards = StandardsGrid(store.get('standards', []) or [])
    dlg.body.addLayout(standards.layout)
    remembered = report_pdf.remembered_show_tar_tur()                        # first run: both off
    tar = QCheckBox('Show TAR on the data file')
    tar.setChecked(bool(remembered.tar))
    tur = QCheckBox('Show TUR on the data file')
    tur.setChecked(bool(remembered.tur))
    dlg.body.addSpacing(M.xs)
    dlg.body.addWidget(tar)
    dlg.body.addWidget(tur)
    result = {'ok': None}

    def done():
        details = {k: e.text().strip() for k, e in fields.items()}
        details['standards'] = standards.values()
        details['procedure'] = procedure
        details['show_tar'], details['show_tur'] = bool(tar.isChecked()), bool(tur.isChecked())
        details['show_tar_tur'] = report_pdf.TarTur(details['show_tar'], details['show_tur'])      # truthy if either is on
        report_pdf.remember_show_tar_tur(details['show_tar_tur'])
        for k in ('technician', 'temperature', 'humidity'):
            store.set(k, details[k])
        store.set('standards', details['standards'])
        store.save()
        result['ok'] = details

    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('Create report', role='primary', default=True, callback=done)
    dlg.initial_focus = fields['technician']
    dlg.run()
    return result['ok']
