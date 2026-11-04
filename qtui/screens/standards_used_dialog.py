"""The review window's 'Standards from the run' dialogs (standards_used.py holds the model; nothing here changes a number by itself).

    StandardsListDialog(parent, current).run()      # StandardsUsed | None   the candidate list: model number, optional asset number, role; bench profiles load / save
    WhyStandardDialog(parent, model, idx=None).run() the selected row's assignment (observed / assumed, spec row, band, confidence, tie-break) and the coverage-gap list
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QGridLayout, QLineEdit, QWidget

import standards_used as su

import report_review_model as RM
from ..theme import M
from ..widgets import ModalDialog, SecondaryButton, label

ROWS = 8


class StandardsListDialog:
    def __init__(self, parent, current=None):
        self.parent, self.current = parent, current if current is not None else su.StandardsUsed()
        self.result = None

    def run(self):
        dlg = ModalDialog(self.parent, 'Standards from the run', width=700)
        dlg.title_label.setText('Standards you have on the bench (the run decides which one touched each point)')
        grid = QGridLayout()
        grid.setHorizontalSpacing(M.sm)
        for c, h in enumerate(('Model number', 'Asset number (optional)', 'Role')):
            grid.addWidget(label(h, 'sub'), 0, c)
        items = list(self.current)
        edits = []
        for r in range(1, ROWS + 1):
            it = items[r - 1] if r - 1 < len(items) else None
            model, asset, role = QLineEdit(it.model if it else ''), QLineEdit(it.asset if it else ''), QComboBox()
            role.addItems(su.ROLES)
            role.setCurrentText(it.role if it else 'source')
            model.setAccessibleName(f'Model number {r}')
            asset.setAccessibleName(f'Asset number {r}')
            role.setAccessibleName(f'Role {r}')
            for c, w in enumerate((model, asset, role)):
                grid.addWidget(w, r, c)
            edits.append((model, asset, role))
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        dlg.body.addLayout(grid)
        dlg.body.addWidget(label('Order = tie-break order. Leave it empty to turn this off. A role of measure / monitor / amplifier / coil is only used as a second standard when the run shows it was touched.', 'sub'))
        prow = QWidget()
        pl = QGridLayout(prow)
        pl.setContentsMargins(0, 0, 0, 0)
        profiles, pname = QComboBox(), QLineEdit()
        profiles.addItems([''] + su.profile_names())
        pname.setPlaceholderText('Bench profile name')
        pname.setText(self.current.profile)
        pl.addWidget(label('Bench profile', 'sub'), 0, 0)
        pl.addWidget(profiles, 0, 1)
        load, save = SecondaryButton('Load'), SecondaryButton('Save as')
        pl.addWidget(load, 0, 2)
        pl.addWidget(pname, 0, 3)
        pl.addWidget(save, 0, 4)
        dlg.body.addWidget(prow)

        def read() -> su.StandardsUsed:
            out = su.StandardsUsed(profile=pname.text().strip())
            for model, asset, role in edits:
                if model.text().strip():
                    out.add(model.text().strip().upper(), asset.text().strip(), role.currentText())
            return out

        def fill(lst):
            for (model, asset, role), it in zip(edits, list(lst) + [None] * ROWS):
                model.setText(it.model if it else '')
                asset.setText(it.asset if it else '')
                role.setCurrentText(it.role if it else 'source')
            pname.setText(lst.profile)

        def on_load():
            lst = su.load_profile(profiles.currentText()) if profiles.currentText() else None
            if lst is not None:
                fill(lst)

        def on_save():
            if su.save_profile(pname.text().strip(), read()):
                profiles.clear()
                profiles.addItems([''] + su.profile_names())
                profiles.setCurrentText(pname.text().strip())

        load.clicked.connect(on_load)
        save.clicked.connect(on_save)

        def ok():
            self.result = read()
        dlg.add_button('Cancel', cancel=True)
        dlg.add_button('OK', role='primary', default=True, callback=ok)
        dlg.run()
        return self.result


class WhyStandardDialog:
    def __init__(self, parent, model, idx=None):
        self.parent, self.model, self.idx = parent, model, idx
        self.text = RM.why_text(model, idx)

    def run(self):
        dlg = ModalDialog(self.parent, 'Why this standard?', width=720)
        dlg.title_label.setText('Why this standard?')
        body = label(self.text, 'body')
        body.setWordWrap(True)
        dlg.body.addWidget(body)
        dlg.add_button('Close', role='primary', default=True)
        dlg.run()
