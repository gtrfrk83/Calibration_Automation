"""Qt twin of manual_grid.py: typed readings straight into the test point grid of a run window (manual calibrations, and any user datasheet whose every point
is done by hand).

    from qtui.screens import manual_grid
    app.grid_entry = manual_grid.GridEntry(app, app.tree)            # app.tree: the engine's results table, a qtui.table.DataTable whose row_key is the point id

The grid is the engine's own results table.  This adds a cell editor on top of it; it is a convenience, not a second engine: a typed reading goes through
`app.type_reading(point, text)` (dsb_runtime.DsbApp), which is the engine's typed-reading path (handheld_dmm.pad_reading to the point's resolution,
handheld_dmm.judge_numeric, DsbApp._store: the same limits, As Found / As Left set, checkpoint and report row as a reading typed in the reading window of
Run All Pending).  `columns` maps the two data sets to the table's column keys (default: the keys 'found' and 'left').

Keys (the box sits over the As Found cell, or the As Left cell while As Left is being collected):
    click a row, press Enter / F2, or start typing   open the box on the selected point
    Enter / Tab                                       save the reading and open the next point (an empty box just moves on)
    Up / Down / Shift+Tab                             save a typed reading and move to the previous / next point
    Esc                                               close the box, nothing saved
    F9 (demo only)                                    fill a simulated reading (marked DEMO; the report is marked DEMO)
A reading that is not a number (empty is fine; letters, NaN, infinity, a comma, a unit) is refused with the reason in the status line and the box stays open.
Nothing is typed while a run is in progress (Run All Pending asks for the readings itself).  A second click on the reading cell of the selected row opens the box.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLineEdit

from qtui.widgets import set_prop

FOUND, LEFT = 'found', 'left'


class _CellEdit(QLineEdit):
    """The box over a reading cell.  Its keys call back into the GridEntry (so a test can press them with QTest)."""

    def __init__(self, grid, parent):
        super().__init__(parent)
        self.grid = grid
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setAccessibleName('Reading')
        self.textEdited.connect(lambda _t: set_prop(self, 'invalid', False))

    def keyPressEvent(self, ev):
        k, g = ev.key(), self.grid
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, Qt.Key.Key_Down):
            ev.accept()
            g.commit(+1)
        elif k in (Qt.Key.Key_Backtab, Qt.Key.Key_Up):
            ev.accept()
            g.commit(-1)
        elif k == Qt.Key.Key_Escape:
            ev.accept()
            g.cancel()
        elif k == Qt.Key.Key_F9:
            ev.accept()
            g.fill_demo()
        else:
            super().keyPressEvent(ev)

    def focusNextPrevChild(self, nxt):                        # Tab / Shift+Tab are the grid's keys, not the dialog's focus chain
        return False

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if self.grid.entry is self:
            self.grid.lost_focus()


class _EntryVar:
    """The box's text as a get / set pair (the Tk build's StringVar `var`)."""

    def __init__(self, grid):
        self.grid = grid

    def get(self):
        return self.grid.entry.text() if self.grid.entry is not None else ''

    def set(self, value):
        if self.grid.entry is not None:
            self.grid.entry.setText('' if value is None else str(value))


class GridEntry(QObject):
    def __init__(self, app, view, columns=None):
        super().__init__(view)
        self.app, self.view = app, view
        self.columns = dict(columns or {FOUND: FOUND, LEFT: LEFT})
        self.entry = None
        self.iid = None
        self.var = _EntryVar(self)
        self._armed = None                      # the row clicked last: a click on an already clicked row opens the box
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)
        view.verticalScrollBar().valueChanged.connect(lambda _v: self.close())
        view.horizontalScrollBar().valueChanged.connect(lambda _v: self.close())

    # ---- helpers --------------------------------------------------------------------------------------------------------
    @property
    def column(self):
        return LEFT if self.app.is_left else FOUND

    def rows(self):
        return [self.view.row_key(r) for r in self.view.visible_rows()]

    def say(self, text):
        self.app.status.set(text)

    def point(self, iid):
        return self.app.by_id.get(iid)

    def is_open(self):
        return self.entry is not None

    def _row_index(self, iid):
        proxy, model = self.view.proxy, self.view.source_model
        for i in range(proxy.rowCount()):
            if self.view.row_key(model.row_at(proxy.mapToSource(proxy.index(i, 0)).row())) == iid:
                return i
        return -1

    def _cell_rect(self, iid):
        i = self._row_index(iid)
        if i < 0:
            return None
        try:
            col = self.view.column_index(self.columns[self.column])
        except KeyError:
            return None
        if self.view.isColumnHidden(col):
            return None
        rect = self.view.visualRect(self.view.proxy.index(i, col))
        return rect if rect.width() > 4 and rect.height() > 4 else None

    # ---- opening / closing -----------------------------------------------------------------------------------------------------
    def open(self, iid, first=''):
        """Put the box over the reading cell of point `iid` (selecting it).  `first` = a character already typed.  Returns True when the box is open."""
        if getattr(self.app, 'busy', False):
            self.say('A run is in progress: the readings are asked for in its windows. Stop it to type into the grid.')
            return False
        p = self.point(iid)
        if p is None:
            return False
        allows = getattr(self.app, 'grid_allows', None)            # an app may allow typing for some points only (user-built datasheets: a section set to Typed by hand)
        if allows is not None:
            ok, why = allows(p)
            if not ok:
                self.say(why)
                return False
        self.close()
        row = next((r for r in self.view.visible_rows() if self.view.row_key(r) == iid), None)
        if row is None:
            return False
        self.view.select_rows([row])
        self.view.scroll_to_row(row)
        rect = self._cell_rect(iid)
        if rect is None:
            self.say('That reading column is not shown at this window size: widen the window.')
            return False
        self.iid = iid
        self.entry = _CellEdit(self, self.view.viewport())
        self.entry.setGeometry(rect)
        rec = self.app.results.get(iid) or {}
        self.entry.setText(first or '')
        if not first and rec.get('entered') not in (None, '') and p['test'] == 'numeric':
            self.entry.setText(str(rec['entered']))                  # an existing reading: shown selected, typing over it replaces it
            self.entry.selectAll()
        self.entry.show()
        self.entry.setFocus()
        if first:
            self.entry.end(False)
        self.say(self.prompt(p))
        return True

    def prompt(self, p):
        """The line in the status bar while the box is open: which point, in which unit, what is accepted."""
        n, total = p['n'], len(self.app.points)
        mode = self.app.mode_label
        if p['test'] == 'numeric':
            text = f'Point {n}/{total} ({mode}): type the reading in {p["display_unit"]}; accept {p["low"]} to {p["high"]} {p["display_unit"]}.'
        else:
            text = f'Point {n}/{total} ({mode}): type Y (pass) or N (fail).'
        text += ' Enter = save and next, Esc = close.'
        if getattr(self.app, 'virtual', False):
            text += ' DEMO: F9 fills a simulated reading.'
        return text

    def close(self):
        e, self.entry, self.iid = self.entry, None, None
        if e is not None:
            e.hide()
            e.deleteLater()

    def cancel(self):
        self.close()
        self.view.setFocus()
        self.say('Reading box closed; nothing was saved for that point.')
        return 'break'

    def lost_focus(self):
        if self.entry is not None and self.entry.text().strip() and self.iid is not None:
            self.say('The reading you were typing was not saved (the box lost the keyboard). Click the point and type it again.')
        self.close()

    # ---- saving ---------------------------------------------------------------------------------------------------------------------
    def commit(self, step=+1):
        """Save the typed reading (an empty box saves nothing) and open the point `step` rows away.  Returns 'break' for the key binding."""
        if self.entry is None or self.iid is None:
            return 'break'
        iid, text = self.iid, self.entry.text()
        p = self.point(iid)
        if text.strip() and p is not None:
            try:
                self.app.type_reading(p, text)
            except ValueError as exc:                               # not a reading: the box stays, the reason is shown
                set_prop(self.entry, 'invalid', True)
                self.say(f'Point {p["n"]}: {exc}')
                return 'break'
            except RuntimeError as exc:
                self.close()
                self.say(str(exc))
                return 'break'
            rec = self.app.results.get(iid) or {}
            saved = f'Point {p["n"]} saved: {rec.get("entered", "")} {p["display_unit"] if p["test"] == "numeric" else ""} {rec.get("result", "")}'.rstrip()
        else:
            saved = ''
        rows = self.rows()
        nxt = rows[rows.index(iid) + step] if iid in rows and 0 <= rows.index(iid) + step < len(rows) else None
        self.close()
        if nxt is not None:
            self.open(nxt)
            if saved:
                self.say(saved + '.  ' + self.prompt(self.point(nxt)))
        else:
            self.view.setFocus()
            self.say((saved + '. ' if saved else '') + ('That was the last point.' if step > 0 else 'That is the first point.'))
        return 'break'

    def fill_demo(self):
        """Demo only: a simulated reading in the box (virtualbench.plausible_text), exactly like the button in the reading window."""
        if self.entry is None or not getattr(self.app, 'virtual', False):
            return 'break'
        import virtualbench
        p = self.point(self.iid)
        if p['test'] == 'numeric':
            self.entry.setText(virtualbench.plausible_text(p['low'], p['high'], p['n'], self.app.virtual_failures()))
        else:
            self.entry.setText('y' if virtualbench.plausible_answer(p['n'], self.app.virtual_failures()) else 'n')
        self.entry.selectAll()
        return 'break'

    # ---- table events ----------------------------------------------------------------------------------------------------------------------
    def selected_iid(self):
        keys = self.view.selected_keys()
        return keys[0] if keys else None

    def on_return(self):
        sel = self.selected_iid()
        if sel is not None and self.entry is None:
            self.open(sel)
        return 'break'

    def on_key(self, text, modifiers=Qt.KeyboardModifier.NoModifier):
        ch = text or ''
        if self.entry is not None or not ch or not (ch.isalnum() or ch in '-+.'):
            return None
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return None
        sel = self.selected_iid()
        allows = getattr(self.app, 'grid_allows', None)
        q = self.point(sel) if sel is not None else None
        if allows is not None and q is not None and not allows(q)[0]:
            return None                                               # typing on a row that cannot take a reading is not a command: no message for every key
        if sel is not None and self.open(sel, first=ch):
            return 'break'
        return None

    def on_click(self, pos):
        """A click on the reading cell of a point that was already clicked opens the box (a first click only selects, as in every list)."""
        index = self.view.indexAt(pos)
        if not index.isValid():
            self._armed = None
            return None
        row = self.view.row_of(index)
        iid = self.view.row_key(row) if row is not None else None
        name = self.view.source_model.columns[index.column()].key
        if iid is not None and name == self.columns[self.column] and self._armed == iid and self.entry is None:
            self.open(iid)
        self._armed = iid or None
        return None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.view:
            if t == QEvent.Type.KeyPress and self.entry is None:
                k = ev.key()
                if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2):
                    self.on_return()
                    return True
                if self.on_key(ev.text(), ev.modifiers()) == 'break':
                    return True
            elif t in (QEvent.Type.Resize, QEvent.Type.Wheel):
                self.close()
        elif obj is self.view.viewport():
            if t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
                self.on_click(ev.position().toPoint())
            elif t in (QEvent.Type.Resize, QEvent.Type.Wheel):
                self.close()
        return False
