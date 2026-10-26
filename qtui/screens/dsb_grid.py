"""Datasheet Builder (Qt): the spreadsheet-like sheet.  A qtui DataTable (uniform rows, fast) whose delegate paints the cells the way the Tk SheetCanvas does:
number column, section heading rows spanning every column, the selected row tinted and the selected cell in the primary colour, red / amber cells where the model
says a cell is wrong, muted rows that are switched off and the small 'typed' marker beside a stored (typed) Low / High limit.

The model (datasheet_builder_ui_model.GridModel) owns the selection and every key: this view only draws, and hands clicks and keys to the window
(`on_click(row_index, col_index)`, `on_key(keysym, char, shift, ctrl)`, `on_edit()`), exactly like the Tk canvas.  No Tk import."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPen
from PySide6.QtWidgets import QAbstractItemView, QWidget

import datasheet_builder_ui_model as M
from qtui import theme
from qtui.table import CellDelegate, Column, DataTable

SHEET_ROW_H = 28
STD_C = M.COL_KEYS.index('standard') + 1          # table column (the number column is 0) of the STANDARD cell; the UNCERTAINTY cell is the next one
KEYSYMS = {Qt.Key.Key_Up: 'Up', Qt.Key.Key_Down: 'Down', Qt.Key.Key_Left: 'Left', Qt.Key.Key_Right: 'Right', Qt.Key.Key_PageUp: 'Prior', Qt.Key.Key_PageDown: 'Next',
           Qt.Key.Key_Tab: 'Tab', Qt.Key.Key_Backtab: 'ISO_Left_Tab', Qt.Key.Key_Home: 'Home', Qt.Key.Key_End: 'End', Qt.Key.Key_Return: 'Return',
           Qt.Key.Key_Enter: 'KP_Enter', Qt.Key.Key_F2: 'F2', Qt.Key.Key_Delete: 'Delete', Qt.Key.Key_Backspace: 'BackSpace', Qt.Key.Key_Escape: 'Escape'}


def _standard_tip(row):
    if row['kind'] == 'header':
        return 'Click to set the standard for the whole section.'
    return row.get('standard_tip', '') if row['kind'] == 'point' else ''


def _function_tip(row):
    return row.get('function', '') if row['kind'] == 'point' and len(row.get('function', '')) > 28 else ''      # a long name (with the temperature sensor) is cut by the column: the whole of it here


def _unc_tip(row):
    return row.get('unc_tip', '') if row['kind'] == 'point' else ''


class SheetDelegate(CellDelegate):
    """Paints every cell of the sheet itself (no row tint from the table: the cell state comes from the model's row dict)."""

    def __init__(self, grid: 'SheetGrid'):
        super().__init__(grid)
        self.grid = grid

    def paint(self, painter, opt, index):
        row = self.grid.row_of(index)
        if row is None:
            return
        t = theme.tokens()
        r = opt.rect
        c = index.column()
        sel_row = row['key'] == self.grid.sel_key
        painter.save()
        border = QPen(QColor(t['border_strong']), 1)
        base = QFont(opt.font)
        bold = QFont(base)
        bold.setBold(True)
        if c == 0:
            painter.fillRect(r, QColor(t['select'] if sel_row else t['head']))
            painter.setPen(border)
            painter.drawRect(r.adjusted(0, 0, -1, -1))
            painter.setPen(QColor(t['muted']))
            painter.setFont(bold)
            painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), str(row['n']))
            status = row.get('status')
            if status:                                    # the strip on the left edge: green ready, amber to look at, red a problem, grey switched off
                colour = {'good': t['good_dot'], 'warn': t['warn_dot'], 'bad': t['bad_dot'], 'off': t['muted']}.get(status)
                if colour:
                    painter.fillRect(QRect(r.left() + 1, r.top() + 1, 5, r.height() - 2), QColor(colour))
            painter.restore()
            return
        if row['kind'] == 'header':
            painter.fillRect(r, QColor(t['head_hi']))
            painter.setPen(border)
            painter.drawRect(r.adjusted(0, 0, -1, -1))
            if c >= STD_C:                                # a heading shows nothing in the STANDARD / UNCERTAINTY cells (the STANDARD one opens the whole-section drop-down)
                if c == STD_C and sel_row and self.grid.sel_c == c:
                    painter.setPen(QPen(QColor(t['primary']), 2))
                    painter.drawRect(r.adjusted(1, 1, -2, -2))
                painter.restore()
                return
            bad = bool(row['problem']) and row['level'] == 'error'
            label = row['function'] + (f'   - {row["problem"]}' if bad else '')
            painter.setPen(QColor(t['bad'] if bad else t['text']))
            painter.setFont(bold)
            text = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, r.width() - 20)
            painter.drawText(r.adjusted(10, 0, -10, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
            if sel_row:
                painter.setPen(QPen(QColor(t['primary']), 2))
                painter.drawRect(r.adjusted(1, 1, -2, -2))
            painter.restore()
            return
        col = M.VIEW_COLUMNS[c - 1]
        key = col['key']
        sel_cell = sel_row and c == self.grid.sel_c
        bad_cell = key in row['bad']
        fill = (t['primary'] if sel_cell else t['bad_bg'] if bad_cell and row['level'] == 'error' else t['warn_bg'] if bad_cell else t['select'] if sel_row else t['table'])
        painter.fillRect(r, QColor(fill))
        painter.setPen(border)
        painter.drawRect(r.adjusted(0, 0, -1, -1))
        marked = key in ('low', 'high') and row.get('limits_from') == 'typed'
        quiet = key == 'standard' and (row.get('standard', '') in ('MANUAL', 'none covers it'))
        fg = t['on_primary'] if sel_cell else t['muted'] if ((not row['enabled'] and row['kind'] == 'point') or quiet) else t['text']
        painter.setFont(base)
        painter.setPen(QColor(fg))
        fm = painter.fontMetrics()
        arrow = key == 'standard' and row['kind'] == 'point' and bool(row.get('standard'))
        room = r.width() - 16 - (44 if marked else 0) - (14 if arrow else 0)
        text = fm.elidedText(str(row.get(key, '') or ''), Qt.TextElideMode.ElideRight, max(10, room))
        if text:
            if col['align'] == 'center':
                painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), text)
            else:
                painter.drawText(r.adjusted(8, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        if arrow:                                          # it is a drop-down
            painter.setPen(QColor(t['on_primary'] if sel_cell else t['muted']))
            painter.drawText(r.adjusted(0, 0, -6, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), '\u25be')
        if marked:
            painter.setPen(QColor(t['on_primary'] if sel_cell else t['muted']))
            painter.drawText(r.adjusted(0, 0, -6, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), 'typed')
        painter.restore()


class _ShareSheet(QObject):
    """A wide sheet no longer becomes one huge FUNCTION TESTED column with the numbers squeezed at the right: the width beyond the columns' own widths is shared
    (the same idea as the Manager list), the function column keeping the largest part.  Narrower than that, the function column takes what is left, as before."""
    WEIGHTS = (0.0, 0.38, 0.14, 0.10, 0.10, 0.17, 0.11)      # '#', function, nominal, low, high, standard, uncertainty

    def __init__(self, grid):
        super().__init__(grid)
        self.grid = grid
        grid.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.apply)
        return False

    def apply(self):
        try:
            g = self.grid
            base = [44] + [c['width'] for c in M.VIEW_COLUMNS]
            hh = g.horizontalHeader()
            vp = g.viewport().width() - 2
            extra = max(0, vp - sum(base))
            for i, (w, k) in enumerate(zip(base, self.WEIGHTS)):
                hh.resizeSection(i, int(w + extra * k))
            if vp < sum(base):                                # narrow: the function column gives way first (as the stretching column did)
                hh.resizeSection(1, max(120, vp - (sum(base) - base[1])))
        except RuntimeError:
            pass                                              # the grid went away


class SheetGrid(DataTable):
    def __init__(self, model, on_click, on_key, on_edit, parent=None):
        cols = [Column('n', '#', 44, align='center')]
        for c in M.VIEW_COLUMNS:
            tip = {'standard': _standard_tip, 'unc': _unc_tip, 'function': _function_tip}.get(c['key'])           # the reason behind a STANDARD / UNCERTAINTY cell (also why an UNCERTAINTY cell is blank)
            cols.append(Column(c['key'], c['title'], c['width'], align='center' if c['align'] == 'center' else 'left', stretch=c['key'] == 'function', tooltip=tip))
        super().__init__(cols, [], row_key=lambda r: r['key'], multi=False, alternating=False, empty_text='', parent=parent)
        self.model, self.on_click, self.on_key, self.on_edit = model, on_click, on_key, on_edit
        self.sel_key, self.sel_c = None, 1
        self._rows_obj = None
        self.setObjectName('sheet')
        self.setItemDelegate(SheetDelegate(self))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setShowGrid(False)
        hh = self.horizontalHeader()
        hh.setSectionsClickable(False)
        hh.setSortIndicatorShown(False)
        hh.setSectionResizeMode(0, hh.ResizeMode.Fixed)
        hh.setMinimumSectionSize(40)
        self.verticalHeader().setDefaultSectionSize(SHEET_ROW_H)
        self.setAccessibleName('Datasheet test point sheet')
        hh.setSectionResizeMode(1, hh.ResizeMode.Interactive)          # the function column is sized by _ShareSheet (it used to take every spare pixel)
        self._share = _ShareSheet(self)

    # ---- showing the model
    def reload(self) -> None:
        """Take the model's rows (only when the datasheet changed since the last time) and show its selection."""
        rows = self.model.rows()
        if rows is not self._rows_obj:
            self._rows_obj = rows
            self.set_rows(rows, keep_selection=False)
            self.clearSpans()
            for i, r in enumerate(rows):
                if r['kind'] == 'header':
                    self.setSpan(i, 1, 1, STD_C - 1)                # the heading spans FUNCTION..HIGH; its STANDARD cell stays separate
        self.show_selection()

    def show_selection(self) -> None:
        m = self.model
        i = m.row_index()
        if i is None:
            return
        self.sel_key = m.sel_key
        self.sel_c = M.COL_KEYS.index(m.sel_col) + 1
        ix = self.proxy.index(i, self.sel_c)
        self.selectionModel().setCurrentIndex(ix, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        self.scrollTo(ix, QAbstractItemView.ScrollHint.EnsureVisible)
        self.viewport().update()

    def cell_rect(self, r: int, c: int) -> QRect:
        """Pixel box of a cell (row index, VIEW column index) in viewport coordinates."""
        return self.visualRect(self.proxy.index(r, c + 1))

    # ---- mouse
    def _click(self, ev) -> bool:
        pos = ev.position().toPoint()
        ix = self.indexAt(pos)
        if not ix.isValid():
            return False
        c = self.columnAt(pos.x())
        self.setFocus()
        self.on_click(ix.row(), max(0, c - 1))
        return True

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._click(ev)
            return
        super().mousePressEvent(ev)

    on_context = None                                          # set by the editor: (row_index, view_col_index, global_pos)

    def contextMenuEvent(self, ev):
        pos = ev.pos()
        ix = self.indexAt(pos)
        if self.on_context is None or not ix.isValid():
            return
        self.setFocus()
        self.on_context(ix.row(), max(0, self.columnAt(pos.x()) - 1), ev.globalPos())
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self._click(ev):
            self.on_edit()

    # ---- keys
    _leaving = False

    def focusNextPrevChild(self, nxt):
        if self._leaving:
            return QWidget.focusNextPrevChild(self, nxt)
        return False                                           # Tab / Shift+Tab move between cells (Ctrl+Tab leaves the sheet)

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        key = ev.key()
        if ctrl and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self._leaving = True
            try:
                self.focusNextPrevChild(key == Qt.Key.Key_Tab)
            finally:
                self._leaving = False
            return
        if ctrl:
            if ev.matches(QKeySequence.StandardKey.Copy):
                self._copy_cell()
                return
            ev.ignore()                                        # Ctrl+Z / Y / S / P / I belong to the window
            return
        if key == Qt.Key.Key_Backtab:
            shift = True
        keysym = KEYSYMS.get(key, '')
        char = ev.text()
        if not keysym and not char:
            super(DataTable, self).keyPressEvent(ev)
            return
        if self.on_key(keysym, char, shift, ctrl) == 'break':
            ev.accept()
        else:
            ev.ignore()

    def _copy_cell(self) -> None:
        QGuiApplication.clipboard().setText(self.model.cell_text())
