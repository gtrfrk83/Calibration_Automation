"""File > Settings...: the person's program settings (app_settings.py).  Today: manual data entry.  OK saves, Cancel changes nothing.  No Tk import."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLineEdit, QMainWindow, QPushButton, QTabWidget, QWidget, QVBoxLayout

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
        self.tabs.addTab(self._reports_tab(), 'Reports')
        self.tabs.addTab(self._appearance_tab(), 'Appearance')
        self.add_button('Cancel', cancel=True)
        self.add_button('OK', role='primary', result='ok', default=True, callback=self.save, close=True)

    def _general_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        group = None
        for key, grp, text, why, _default in app_settings.OPTIONS:
            if grp == 'Reports':
                continue                                           # the Reports tab
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
        baud_form = QFormLayout()
        self.baud_box = QComboBox()
        self.baud_box.addItem('not set (each procedure keeps its own)', '')
        for b in app_settings.BAUDS:
            self.baud_box.addItem(b, b)
        self.baud_box.setCurrentIndex(max(0, self.baud_box.findData(str(app_settings.get(app_settings.CAL_BAUD) or ''))))
        self.baud_box.setAccessibleName('Calibrator baud rate')
        baud_form.addRow('Calibrator serial baud rate', self.baud_box)
        lay.addLayout(baud_form)
        self.first_box = QCheckBox('Use these every time a procedure opens (replace the address a procedure remembered)')
        self.first_box.setChecked(app_settings.address_first())
        lay.addWidget(self.first_box)
        lay.addWidget(label("Off: a procedure uses these only until it has saved an address of its own. Calibrator boxes take the address of the calibrator model chosen in "
                            "the procedure. The 'Find instruments...' button in the Manager finds them.", 'sub', wrap=True))
        lay.addStretch(1)
        return page

    def _reports_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(label('Reports', 'section'))
        for key, grp, text, why, _default in app_settings.OPTIONS:
            if grp != 'Reports':
                continue
            box = QCheckBox(text)
            box.setChecked(app_settings.get(key))
            box.setAccessibleName(text)
            self.boxes[key] = box
            lay.addWidget(box)
            lay.addWidget(label(why, 'sub', wrap=True))
        lay.addWidget(label('Folder the report Save window opens in', 'section'))
        row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(app_settings.get(app_settings.REPORT_FOLDER) or ''))
        self.folder_edit.setPlaceholderText("not set: the Save window's own choice")
        self.folder_edit.setAccessibleName('Report folder')
        row.addWidget(self.folder_edit, 1)
        browse = QPushButton('Browse...')
        browse.clicked.connect(self._browse_folder)
        row.addWidget(browse)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _browse_folder(self):
        from qtui import prompts
        path = prompts.choose_dir(self, title='Folder for reports')
        if path:
            self.folder_edit.setText(path)

    def _appearance_tab(self):
        from qtui import theme
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(label('Appearance', 'section'))
        lay.addWidget(label('These take effect at once and are remembered (the same as the Appearance menu).', 'sub', wrap=True))
        form = QFormLayout()
        self.theme_box = QComboBox()
        for key in theme.ENABLED_THEMES:
            self.theme_box.addItem(key.title(), key)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(theme.name())))
        self.theme_box.currentIndexChanged.connect(lambda _i: theme.set_theme(self.theme_box.currentData(), save=True))
        form.addRow('Theme', self.theme_box)
        lay.addLayout(form)
        size = QPushButton('Text size...')
        size.clicked.connect(self._text_size)
        lay.addWidget(size)
        lay.addStretch(1)
        return page

    def _text_size(self):
        from qtui.screens.help_menu import TextSizeDialog
        TextSizeDialog(self).exec()

    def save(self):
        values = {k: b.isChecked() for k, b in self.boxes.items()}
        values[app_settings.REPORT_FOLDER] = self.folder_edit.text()
        values[app_settings.CAL_BAUD] = self.baud_box.currentData() or ''
        app_settings.set_many(values)
        app_settings.set_addresses({m: e.text() for m, e in self.addr_edits.items()}, self.first_box.isChecked())


def open_settings(window=None):
    dlg = SettingsDialog(window)
    out = dlg.run()
    if out == 'ok' and hasattr(window, 'apply_settings'):
        window.apply_settings()                                    # the Manager shows or hides its demo buttons
    return out


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
