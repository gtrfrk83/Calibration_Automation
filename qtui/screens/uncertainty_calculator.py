"""The Uncertainty Calculator tab: a GUM / ILAC-P14 style budget from spot readings (repeatability and reproducibility) and Type B components, on screen, with an Excel
export that carries the same numbers as live formulas.  Stand-alone: it is not tied to a procedure, a report or a database, and it changes nothing.

    UncertaintyCalculatorPanel(parent, status=None)

All the arithmetic is in uncertainty_calc.py (tested on its own); this file only collects what is typed and shows the working.  Everything typed is in ONE unit (the
measurand's); the divisor of each component and the sensitivity coefficient are shown in the table so the working can be checked line by line.
Dialogs go through the module functions `_info`, `_error`, `_save_file` (a test replaces them)."""
from __future__ import annotations

import math
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QMenu, QPlainTextEdit, QScrollArea,
                               QSpinBox, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

import uncertainty_calc as uc
import uncertainty_calc_xlsx as xl

from ..table import Column, DataTable
from ..theme import M
from ..widgets import Banner, Card, MessageDialog, PrimaryButton, SecondaryButton, label

PRESETS = (                                            # (menu text, component name, distribution)
    ('Resolution of the unit under test (half the last digit)', 'Resolution (UUT)', 'rect'),
    ('Standard / calibrator accuracy (certificate, k = 2)', 'Standard accuracy', 'k2'),
    ('Resolution of the standard (half the last digit)', 'Resolution (standard)', 'rect'),
    ('Temperature effect', 'Temperature effect', 'rect'),
    ('Drift since last calibration', 'Drift', 'rect'),
    ('Other component...', 'Other', 'std'),
)
SHORT_DIST = {'k2': 'Normal k=2', 'k3': 'Normal k=3', 'std': 'Std. unc. (k=1)', 'rect': 'Rectangular', 'tri': 'Triangular', 'u': 'U-shaped'}
GROUP_ROWS = 8
START_GROUPS = 3


def _info(parent, title, text):
    MessageDialog(parent, 'info', title, text).run()


def _error(parent, title, text):
    MessageDialog(parent, 'error', title, text).run()


def _save_file(parent, title, directory, filters):
    return QFileDialog.getSaveFileName(parent, title, directory, filters)[0]


def fmt(x, unit=''):
    if x is None:
        return ''
    if x == uc.INF:
        return 'infinite'
    text = f'{x:.6g}'
    return f'{text} {unit}'.strip() if unit else text


class UncertaintyCalculatorPanel(QWidget):
    def __init__(self, parent=None, status=None):
        super().__init__(parent)
        self.status = status
        self.result = None
        self.error = ''
        self.inputs_ok = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self.recalc)
        root = QHBoxLayout(self)
        root.setContentsMargins(M.page_margin, M.sm, M.page_margin, M.page_margin)
        root.setSpacing(M.lg)
        root.addWidget(self._build_inputs(), 5)
        root.addWidget(self._build_results(), 6)
        for _ in range(START_GROUPS):
            self.add_group()
        self.recalc()

    # ------------------------------------------------------------------------------------------------------------------------------ building
    def _build_inputs(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, M.sm, 0)
        lay.setSpacing(M.md)
        scroll.setWidget(body)

        card = Card('What is being measured')
        form = QFormLayout()
        self.title_e = QLineEdit()
        self.title_e.setPlaceholderText('e.g. DC voltage, 10 V point')
        self.nominal_e = QLineEdit()
        self.nominal_e.setPlaceholderText('e.g. 10 V')
        self.unit_e = QLineEdit()
        self.unit_e.setPlaceholderText('V')
        self.unit_e.setMaximumWidth(120)
        form.addRow('Measurand', self.title_e)
        form.addRow('Nominal', self.nominal_e)
        form.addRow('Unit of everything below', self.unit_e)
        card.body.addLayout(form) if hasattr(card, 'body') else card.layout().addLayout(form)
        lay.addWidget(card)
        for e in (self.title_e, self.nominal_e, self.unit_e):
            e.textChanged.connect(self.changed)

        rep = Card('Repeatability: spot readings under the same conditions')
        rep_lay = rep.body if hasattr(rep, 'body') else rep.layout()
        rep_lay.addWidget(label('Type or paste the readings, one per line (commas and spaces work too). Same operator, same set-up, same day.', 'hint', wrap=True))
        self.rep_text = QPlainTextEdit()
        self.rep_text.setPlaceholderText('10.0001\n10.0003\n9.9999')
        self.rep_text.setMinimumHeight(110)
        self.rep_text.textChanged.connect(self.changed)
        rep_lay.addWidget(self.rep_text)
        row = QHBoxLayout()
        row.addWidget(label('Readings averaged in the reported result'))
        self.avg_spin = QSpinBox()
        self.avg_spin.setRange(0, 1000)
        self.avg_spin.setSpecialValueText('all of them')
        self.avg_spin.setToolTip('The uncertainty of a mean is s / sqrt(m). Use 1 when the reported result is a single reading.')
        self.avg_spin.valueChanged.connect(self.changed)
        row.addWidget(self.avg_spin)
        row.addStretch(1)
        rep_lay.addLayout(row)
        self.rep_stats = label('', 'hint', wrap=True)
        rep_lay.addWidget(self.rep_stats)
        lay.addWidget(rep)

        rpr = Card('Reproducibility: spot readings on different days, operators or set-ups')
        rpr_lay = rpr.body if hasattr(rpr, 'body') else rpr.layout()
        rpr_lay.addWidget(label('One column per group; the first row is the group name (Day 1, Operator B ...). Readings go underneath.', 'hint', wrap=True))
        self.groups = QTableWidget(GROUP_ROWS + 1, 0)
        self.groups.setMinimumHeight(250)
        self.groups.horizontalHeader().setVisible(False)
        self.groups.verticalHeader().setVisible(False)
        self.groups.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.groups.itemChanged.connect(self.changed)
        rpr_lay.addWidget(self.groups)
        btns = QHBoxLayout()
        for text, fn in (('Add group', self.add_group), ('Remove last group', self.remove_group), ('Add reading row', self.add_reading_row)):
            b = SecondaryButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            btns.addWidget(b)
        btns.addStretch(1)
        rpr_lay.addLayout(btns)
        self.rpr_stats = label('', 'hint', wrap=True)
        rpr_lay.addWidget(self.rpr_stats)
        lay.addWidget(rpr)

        tb = Card('Other components (Type B)')
        tb_lay = tb.body if hasattr(tb, 'body') else tb.layout()
        tb_lay.addWidget(label('Value = the quoted limit or uncertainty in the unit above. The distribution sets the divisor; sensitivity c converts to the measurand '
                               '(1 when the units are the same). Leave degrees of freedom empty for infinite.', 'hint', wrap=True))
        self.typeb = QTableWidget(0, 5)
        self.typeb.setHorizontalHeaderLabels(['Component', 'Value', 'Distribution', 'Sensitivity c', 'Degrees of freedom'])
        self.typeb.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.typeb.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.typeb.verticalHeader().setVisible(False)
        self.typeb.setMinimumHeight(180)
        self.typeb.itemChanged.connect(self.changed)
        tb_lay.addWidget(self.typeb)
        row = QHBoxLayout()
        self.add_b = QToolButton()
        self.add_b.setText('Add component')
        self.add_b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.add_b)
        for text, name, dist in PRESETS:
            menu.addAction(text).triggered.connect(lambda _c=False, n=name, d=dist: self.add_type_b(n, '', d))
        self.add_b.setMenu(menu)
        row.addWidget(self.add_b)
        rb = SecondaryButton('Remove selected')
        rb.clicked.connect(self.remove_type_b)
        row.addWidget(rb)
        row.addStretch(1)
        tb_lay.addLayout(row)
        lay.addWidget(tb)

        opt = Card('Coverage, CMC and tolerance')
        opt_lay = opt.body if hasattr(opt, 'body') else opt.layout()
        f2 = QFormLayout()
        self.k_mode = QComboBox()
        self.k_mode.addItem('Student t at the effective degrees of freedom (95.45 %)', 'auto')
        self.k_mode.addItem('Fixed coverage factor', 'fixed')
        self.k_mode.currentIndexChanged.connect(self.changed)
        self.k_fixed = QLineEdit('2')
        self.k_fixed.setMaximumWidth(80)
        self.k_fixed.textChanged.connect(self.changed)
        self.cmc_e = QLineEdit()
        self.cmc_e.setPlaceholderText('optional: the scope CMC for this point')
        self.cmc_e.textChanged.connect(self.changed)
        self.tol_e = QLineEdit()
        self.tol_e.setPlaceholderText('optional: the tolerance of the unit under test (+/-)')
        self.tol_e.textChanged.connect(self.changed)
        f2.addRow('Coverage factor', self.k_mode)
        f2.addRow('Fixed k', self.k_fixed)
        f2.addRow('CMC (never reported below)', self.cmc_e)
        f2.addRow('Tolerance for TUR', self.tol_e)
        opt_lay.addLayout(f2)
        lay.addWidget(opt)
        lay.addStretch(1)
        return scroll

    def _build_results(self):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(M.md)
        top = Card('Result')
        top_lay = top.body if hasattr(top, 'body') else top.layout()
        self.headline = label('', 'title', wrap=True)
        self.headline.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top_lay.addWidget(self.headline)
        self.detail = label('', 'sub', wrap=True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top_lay.addWidget(self.detail)
        lay.addWidget(top)
        self.banner = Banner('', 'warn')
        self.banner.hide()
        lay.addWidget(self.banner)
        self.table = DataTable([
            Column('name', 'Component', width=150, stretch=True),
            Column('type', 'Type', width=44),
            Column('value', 'Value', width=84, align='right', mono=True),
            Column('dist', 'Distribution', width=100),
            Column('divisor', 'Divisor', width=60, align='right', mono=True),
            Column('c', 'c', width=36, align='right', mono=True),
            Column('u', 'u', width=84, align='right', mono=True),
            Column('cu', '|c| u', width=84, align='right', mono=True),
            Column('dof', 'dof', width=44, align='right', mono=True),
            Column('share', '% var.', width=60, align='right', mono=True),
        ], row_key=lambda r: r['name'], multi=False, empty_text='Add readings or components to see the budget')
        self.table.setAccessibleName('Uncertainty budget')
        lay.addWidget(self.table, 1)
        self.notes = label('', 'hint', wrap=True)
        lay.addWidget(self.notes)
        row = QHBoxLayout()
        self.export_b = PrimaryButton('Export to Excel...')
        self.export_b.clicked.connect(self.export_excel)
        self.copy_b = SecondaryButton('Copy summary')
        self.copy_b.clicked.connect(self.copy_summary)
        self.clear_b = SecondaryButton('Clear all')
        self.clear_b.clicked.connect(self.clear_all)
        for b in (self.export_b, self.copy_b, self.clear_b):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return host

    # ------------------------------------------------------------------------------------------------------------------------------ the groups table
    def add_group(self, name=None, values=()):
        col = self.groups.columnCount()
        self.groups.blockSignals(True)
        self.groups.insertColumn(col)
        head = QTableWidgetItem(name or f'Group {col + 1}')
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        self.groups.setItem(0, col, head)
        for i, v in enumerate(values):
            if i + 1 >= self.groups.rowCount():
                self.groups.insertRow(self.groups.rowCount())
            self.groups.setItem(1 + i, col, QTableWidgetItem(str(v)))
        self.groups.setColumnWidth(col, 110)
        self.groups.blockSignals(False)
        self.changed()

    def remove_group(self):
        if self.groups.columnCount():
            self.groups.removeColumn(self.groups.columnCount() - 1)
            self.changed()

    def add_reading_row(self):
        self.groups.insertRow(self.groups.rowCount())
        self.changed()

    def group_data(self):
        out = {}
        for c in range(self.groups.columnCount()):
            head = self.groups.item(0, c)
            name = (head.text().strip() if head else '') or f'Group {c + 1}'
            vals = []
            for r in range(1, self.groups.rowCount()):
                it = self.groups.item(r, c)
                if it is not None and it.text().strip():
                    vals.append(it.text().strip())
            if vals:
                key, n = name, 2
                while key in out:
                    key, n = f'{name} ({n})', n + 1
                out[key] = vals
        return out

    # ------------------------------------------------------------------------------------------------------------------------------ the Type B table
    def add_type_b(self, name='', value='', dist='k2', sensitivity='1', dof=''):
        r = self.typeb.rowCount()
        self.typeb.blockSignals(True)
        self.typeb.insertRow(r)
        self.typeb.setItem(r, 0, QTableWidgetItem(name))
        self.typeb.setItem(r, 1, QTableWidgetItem(str(value)))
        combo = QComboBox()
        for key, (text, _d) in uc.DISTRIBUTIONS.items():
            combo.addItem(text, key)
        combo.setCurrentIndex(max(0, combo.findData(dist)))
        combo.currentIndexChanged.connect(self.changed)
        self.typeb.setCellWidget(r, 2, combo)
        self.typeb.setItem(r, 3, QTableWidgetItem(str(sensitivity)))
        self.typeb.setItem(r, 4, QTableWidgetItem(str(dof)))
        self.typeb.blockSignals(False)
        self.typeb.resizeColumnToContents(2)
        self.changed()
        return r

    def remove_type_b(self):
        rows = sorted({i.row() for i in self.typeb.selectedIndexes()}, reverse=True)
        for r in rows:
            self.typeb.removeRow(r)
        if rows:
            self.changed()

    def type_b_components(self):
        out = []
        for r in range(self.typeb.rowCount()):
            def cell(c):
                it = self.typeb.item(r, c)
                return it.text().strip() if it else ''
            if not cell(1):
                continue                                         # a row without a value is not part of the budget yet
            dist = self.typeb.cellWidget(r, 2).currentData()
            out.append(uc.component(cell(0) or f'Component {r + 1}', cell(1), dist, cell(3) or 1.0, cell(4) or uc.INF))
        return out

    # ------------------------------------------------------------------------------------------------------------------------------ the calculation
    def changed(self, *_):
        self._timer.start()

    def inputs(self):
        """The xl.Inputs of what is on screen (raises uc.CalcError for a number that cannot be used)."""
        mode = self.k_mode.currentData()
        return xl.Inputs(title='Uncertainty budget' + (f': {self.title_e.text().strip()}' if self.title_e.text().strip() else ''),
                         measurand=self.title_e.text().strip(), unit=self.unit_e.text().strip(), nominal=self.nominal_e.text().strip(),
                         repeat_values=uc.parse_readings(self.rep_text.toPlainText()), repeat_averaged=self.avg_spin.value() or None,
                         groups=self.group_data(), type_b=self.type_b_components(), k_mode=mode,
                         fixed_k=self.k_fixed.text().strip() or 2.0 if mode == 'fixed' else 2.0,
                         tolerance=self.tol_e.text().strip() or None, cmc=self.cmc_e.text().strip() or None)

    def recalc(self):
        unit = self.unit_e.text().strip()
        self.result, self.error, self.inputs_ok = None, '', None
        rep = rpr = None
        try:
            inp = self.inputs()
            self.rep_stats.setText('')
            self.rpr_stats.setText('')
            if len(inp.repeat_values) >= 1:
                if len(inp.repeat_values) < 2:
                    self.rep_stats.setText('Add at least 2 readings to get a standard deviation.')
                else:
                    rep = uc.repeatability(inp.repeat_values, inp.repeat_averaged)
                    self.rep_stats.setText(f'n = {rep.n}   mean = {fmt(rep.mean, unit)}   s = {fmt(rep.s, unit)}   m = {rep.averaged}   '
                                           f'u = s / sqrt(m) = {fmt(rep.u, unit)}   dof = {rep.dof:g}')
            if inp.groups:
                if len(inp.groups) < 2:
                    self.rpr_stats.setText('Add readings in at least 2 groups to see the reproducibility.')
                else:
                    rpr = uc.reproducibility(inp.groups)
                    means = ', '.join(f'{k}: {fmt(v)}' for k, v in rpr.group_means.items())
                    self.rpr_stats.setText(f'{rpr.g} groups, {rpr.N} readings.  Group means: {means}.  Between-group u = {fmt(rpr.sigma_b, unit)}   '
                                           f'pooled within-group s = {fmt(rpr.s_within, unit)}   (dof {rpr.dof_between} / {rpr.dof_within})')
            inp.fixed_k = float(inp.fixed_k)
            res = uc.budget(inp.type_b, rep=rep, rpr=rpr, k_mode=inp.k_mode, fixed_k=inp.fixed_k, tolerance=inp.tolerance, cmc=inp.cmc)
            self.result, self.inputs_ok = res, inp
        except (uc.CalcError, ValueError) as exc:
            self.error = str(exc)
        self.show_result()

    def show_result(self):
        res, unit = self.result, self.unit_e.text().strip()
        self.export_b.setEnabled(res is not None)
        self.copy_b.setEnabled(res is not None)
        if res is None:
            self.headline.setText('')
            self.detail.setText('Enter spot readings and/or components on the left; the budget is worked out as you type.')
            self.table.set_rows([])
            self.notes.setText('')
            self.banner.setVisible(bool(self.error))
            if self.error:
                self.banner.set_text(self.error) if hasattr(self.banner, 'set_text') else self.banner.setText(self.error)
            return
        self.banner.hide()
        self.headline.setText(f'U = ± {fmt(res.reported, unit)}   (k = {res.k:.2f})')
        bits = [f'u_c = {fmt(res.u_c, unit)}', f'effective dof = {"infinite" if res.dof_eff == uc.INF else f"{res.dof_eff:.1f}"}',
                f'U = k u_c = {fmt(res.U, unit)} ({res.reported_note})']
        if res.mean_value is not None:
            bits.insert(0, f'mean = {fmt(res.mean_value, unit)}')
        if res.tur is not None:
            bits.append(f'TUR = {res.tur:.2f}')
        self.detail.setText('   |   '.join(bits))
        rows = []
        for c, share in res.shares():
            rows.append(dict(name=c.name, type=c.kind, value=fmt(c.value), dist=SHORT_DIST[c.dist], divisor=fmt(c.divisor), c=fmt(c.sensitivity),
                             u=fmt(c.u), cu=fmt(c.contribution), dof='inf' if c.dof == uc.INF else f'{c.dof:g}', share=f'{share:.1f}'))
        self.table.set_rows(rows)
        self.notes.setText(' '.join([f'Coverage: {res.k_mode}.'] + res.notes))

    # ------------------------------------------------------------------------------------------------------------------------------ actions
    def summary_text(self):
        res, unit = self.result, self.unit_e.text().strip()
        if res is None:
            return ''
        lines = [f'Uncertainty budget{": " + self.title_e.text().strip() if self.title_e.text().strip() else ""}',
                 f'Nominal: {self.nominal_e.text().strip() or "-"}   Unit: {unit or "-"}']
        for c, share in res.shares():
            lines.append(f'  {c.name} ({c.kind}): value {fmt(c.value)}, {uc.DISTRIBUTIONS[c.dist][0]}, divisor {fmt(c.divisor)}, c {fmt(c.sensitivity)}, '
                         f'u {fmt(c.u)}, |c|u {fmt(c.contribution)}, dof {"inf" if c.dof == uc.INF else f"{c.dof:g}"}, {share:.1f} %')
        lines += [f'Combined standard uncertainty u_c = {fmt(res.u_c, unit)}',
                  f'Effective degrees of freedom = {"infinite" if res.dof_eff == uc.INF else f"{res.dof_eff:.2f}"}',
                  f'k = {res.k:.3f} ({res.k_mode})', f'Expanded uncertainty U = {fmt(res.U, unit)}', f'Reported U = {fmt(res.reported, unit)} ({res.reported_note})']
        if res.tur is not None:
            lines.append(f'TUR = {res.tur:.2f}')
        return '\n'.join(lines)

    def copy_summary(self):
        text = self.summary_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self._say('Copied the budget summary to the clipboard.')

    def export_excel(self):
        if self.result is None or self.inputs_ok is None:
            return None
        name = f'Uncertainty budget-{date.today().isoformat()}.xlsx'
        path = _save_file(self, 'Export the uncertainty work to Excel', name, 'Excel workbook (*.xlsx)')
        if not path:
            return None
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        try:
            xl.export(path, self.inputs_ok)
        except ImportError:
            _error(self, 'Export to Excel', 'Excel export needs the openpyxl package.\n\nInstall it with:  py -m pip install openpyxl')
            return None
        except (uc.CalcError, OSError) as exc:
            _error(self, 'Export to Excel', f'The workbook could not be written:\n{exc}')
            return None
        self._say(f'Exported the uncertainty work to {path}')
        return path

    def clear_all(self):
        for e in (self.title_e, self.nominal_e, self.unit_e, self.cmc_e, self.tol_e):
            e.clear()
        self.rep_text.clear()
        self.avg_spin.setValue(0)
        self.k_mode.setCurrentIndex(0)
        self.k_fixed.setText('2')
        self.groups.setColumnCount(0)
        for _ in range(START_GROUPS):
            self.add_group()
        self.typeb.setRowCount(0)
        self.recalc()

    def _say(self, text):
        if self.status is not None and hasattr(self.status, 'set'):
            self.status.set(text)
