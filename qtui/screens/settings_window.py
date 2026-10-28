"""File > Settings...: the person's program settings (app_settings.py).  Today: manual data entry.  OK saves, Cancel changes nothing.  No Tk import."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLineEdit, QMainWindow, QTabWidget, QWidget, QVBoxLayout

import app_settings
from qtui.widgets import ModalDialog, label


class SettingsDialog(ModalDialog):
    def __init__(self, parent=None):
        super().__init__(parent, 'Settings', subtitle='Saved for you on this computer. They change how the program behaves, never a limit or an instrument command.', width=700)
        self.boxes = {}
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs)
        self.tabs.addTab(self._general_tab(), 'General')
        self.tabs.addTab(self._addresses_tab(), 'Instrument addresses')
        self.add_button('Cancel', cancel=True)
        self.add_button('OK', role='primary', result='ok', default=True, callback=self.save, close=True)

    def _general_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        group = None
        for key, grp, text, why, _default in app_settings.OPTIONS:
            if grp != group:
                group = grp
                lay.addWidget(label(grp, 'section'))
            box = QCheckBox(text)
            box.setChecked(app_settings.get(key))
            box.setAccessibleName(text)
            self.boxes[key] = box
            lay.addWidget(box)
            lay.addWidget(label(why, 'sub', wrap=True))
        lay.addStretch(1)
        return page

    def _addresses_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(label('Default address of each standard', 'section'))
        lay.addWidget(label('A VISA resource (GPIB0::5::INSTR, USB0::...::INSTR, TCPIP0::...::INSTR) or a serial port (COM9). Leave blank for a standard you do not have. '
                            'Procedures start with these; the box inside a procedure can still be changed. The instrument under test keeps its own address in its procedure.',
                            'sub', wrap=True))
        form = QFormLayout()
        self.addr_edits = {}
        saved = app_settings.addresses()
        for model in app_settings.STANDARD_MODELS:
            e = QLineEdit(saved.get(model, ''))
            e.setAccessibleName(f'{model} address')
            e.setPlaceholderText('not set')
            self.addr_edits[model] = e
            form.addRow(model, e)
        lay.addLayout(form)
        self.first_box = QCheckBox('Use these every time a procedure opens (replace the address a procedure remembered)')
        self.first_box.setChecked(app_settings.address_first())
        lay.addWidget(self.first_box)
        lay.addWidget(label("Off: a procedure uses these only until it has saved an address of its own. Calibrator boxes take the address of the calibrator model chosen in "
                            "the procedure. The 'Find instruments...' button in the Manager finds them.", 'sub', wrap=True))
        lay.addStretch(1)
        return page

    def save(self):
        app_settings.set_many({k: b.isChecked() for k, b in self.boxes.items()})
        app_settings.set_addresses({m: e.text() for m, e in self.addr_edits.items()}, self.first_box.isChecked())


def open_settings(window=None):
    dlg = SettingsDialog(window)
    return dlg.run()


def add_settings_action(window: QMainWindow):
    """File > Settings... : in the File menu the window already has (the Manager's, before Exit), else a File menu is made first in the bar."""
    from PySide6.QtGui import QAction
    bar = window.menuBar()
    menu = next((a.menu() for a in bar.actions() if a.menu() is not None and a.text().replace('&', '') == 'File'), None)
    if menu is None:
        menu = bar.addMenu('&File')
        if len(bar.actions()) > 1:
            bar.removeAction(menu.menuAction())
            bar.insertMenu(bar.actions()[0], menu)
    act = QAction('&Settings...', window)
    act.triggered.connect(lambda _c=False: open_settings(window))
    exit_act = getattr(window, 'act_exit', None)
    if exit_act is not None and exit_act in menu.actions():
        menu.insertAction(exit_act, act)
        menu.insertSeparator(exit_act)
    else:
        menu.addAction(act)
    window.act_settings = act
    return act
