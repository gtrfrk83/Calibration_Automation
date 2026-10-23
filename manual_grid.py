"""Typed readings straight into the test point grid of a run window (manual calibrations, and any user datasheet whose every point is done by hand).

    import manual_grid
    app.grid_entry = manual_grid.GridEntry(app, app.tree)

The grid is the engine's own results table (ui_shell.results_table, a Treeview).  This adds a cell editor on top of it; it is a convenience, not a second
engine: a typed reading goes through `app.type_reading(point, text)` (dsb_runtime.DsbApp), which is the engine's typed-reading path (handheld_dmm.pad_reading
to the point's resolution, handheld_dmm.judge_numeric, DsbApp._store: the same limits, As Found / As Left set, checkpoint and report row as a reading typed
in the reading window of Run All Pending).

Keys (the box sits over the As Found cell, or the As Left cell while As Left is being collected):
    click a row, press Enter / F2, or start typing   open the box on the selected point
    Enter / Tab                                       save the reading and open the next point (an empty box just moves on)
    Up / Down / Shift+Tab                             save a typed reading and move to the previous / next point
    Esc                                               close the box, nothing saved
    F9 (demo only)                                    fill a simulated reading (marked DEMO; the report is marked DEMO)
A reading that is not a number (empty is fine; letters, NaN, infinity, a comma, a unit) is refused with the reason in the status line and the box stays open.
Nothing is typed while a run is in progress (Run All Pending asks for the readings itself).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_theme as ui

FOUND, LEFT = 'found', 'left'


class GridEntry:
    def __init__(self, app, tree):
        self.app, self.tree = app, tree
        self.entry = None
        self.iid = None
        self.var = tk.StringVar()
        self.var.trace_add('write', self._typing)
        self._style()
        tree.bind('<Return>', self.on_return, add='+')
        tree.bind('<KP_Enter>', self.on_return, add='+')
        tree.bind('<F2>', self.on_return, add='+')
        tree.bind('<Key>', self.on_key, add='+')
        tree.bind('<ButtonRelease-1>', self.on_click, add='+')
        tree.bind('<Configure>', lambda _e: self.close(), add='+')
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            tree.bind(seq, lambda _e: self.close(), add='+')
        self._armed = None                      # the row that was selected before the click: a click on an already selected row opens the box

    # ---- helpers --------------------------------------------------------------------------------------------------------
    @staticmethod
    def _style():
        try:
            st = ttk.Style()
            st.configure('GridEntry.TEntry', padding=(2, 0))
            st.configure('GridEntryBad.TEntry', padding=(2, 0), foreground=ui.C.get('bad', '#B3261E'))
        except tk.TclError:
            pass

    @property
    def column(self):
        return LEFT if self.app.is_left else FOUND

    def rows(self):
        return list(self.tree.get_children())

    def say(self, text):
        self.app.status.set(text)

    def point(self, iid):
        return self.app.by_id.get(iid)

    def is_open(self):
        return self.entry is not None

    # ---- opening / closing -----------------------------------------------------------------------------------------------------
    def open(self, iid, first=''):
        """Put the box over the reading cell of point `iid` (selecting it).  `first` = a character already typed.  Returns True when the box is open."""
        if getattr(self.app, 'busy', False):
            self.say('A run is in progress: the readings are asked for in its windows. Stop it to type into the grid.')
            return False
        p = self.point(iid)
        if p is None:
            return False
        self.close()
        try:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self.tree.update_idletasks()
            box = self.tree.bbox(iid, self.column)
        except tk.TclError:
            return False
        if not box:
            self.say('That reading column is not shown at this window size: widen the window.')
            return False
        x, y, w, h = box
        self.iid = iid
        self.entry = ttk.Entry(self.tree, textvariable=self.var, justify='right', style='GridEntry.TEntry')
        self.entry.place(x=x, y=y, width=w, height=h)
        rec = self.app.results.get(iid) or {}
        self.var.set(first or '')
        if not first and rec.get('entered') not in (None, '') and p['test'] == 'numeric':
            self.var.set(str(rec['entered']))                       # an existing reading: shown selected, typing over it replaces it
            self.entry.after_idle(lambda: self._select_all())
        for seq, fn in (('<Return>', lambda e: self.commit(+1)), ('<KP_Enter>', lambda e: self.commit(+1)), ('<Tab>', lambda e: self.commit(+1)),
                        ('<ISO_Left_Tab>', lambda e: self.commit(-1)), ('<Up>', lambda e: self.commit(-1)), ('<Down>', lambda e: self.commit(+1)),
                        ('<Escape>', lambda e: self.cancel()), ('<FocusOut>', lambda e: self.lost_focus()), ('<F9>', lambda e: self.fill_demo())):
            self.entry.bind(seq, fn)
        self.entry.focus_set()
        self.entry.icursor('end')
        self.say(self.prompt(p))
        return True

    def _select_all(self):
        try:
            self.entry.select_range(0, 'end')
            self.entry.icursor('end')
        except (tk.TclError, AttributeError):
            pass

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

    def _typing(self, *_):
        if self.entry is not None:
            try:
                self.entry.configure(style='GridEntry.TEntry')
            except tk.TclError:
                pass

    def close(self):
        if self.entry is not None:
            try:
                self.entry.destroy()
            except tk.TclError:
                pass
        self.entry, self.iid = None, None

    def cancel(self):
        self.close()
        self.tree.focus_set()
        self.say('Reading box closed; nothing was saved for that point.')
        return 'break'

    def lost_focus(self):
        if self.entry is not None and self.var.get().strip() and self.iid is not None:
            self.say('The reading you were typing was not saved (the box lost the keyboard). Click the point and type it again.')
        self.close()

    # ---- saving ---------------------------------------------------------------------------------------------------------------------
    def commit(self, step=+1):
        """Save the typed reading (an empty box saves nothing) and open the point `step` rows away.  Returns 'break' for the key binding."""
        if self.entry is None or self.iid is None:
            return 'break'
        iid, text = self.iid, self.var.get()
        p = self.point(iid)
        if text.strip() and p is not None:
            try:
                self.app.type_reading(p, text)
            except ValueError as exc:                               # not a reading: the box stays, the reason is shown
                self.entry.configure(style='GridEntryBad.TEntry')
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
            self.tree.focus_set()
            self.say((saved + '. ' if saved else '') + ('That was the last point.' if step > 0 else 'That is the first point.'))
        return 'break'

    def fill_demo(self):
        """Demo only: a simulated reading in the box (virtualbench.plausible_text), exactly like the button in the reading window."""
        if self.entry is None or not getattr(self.app, 'virtual', False):
            return 'break'
        import virtualbench
        p = self.point(self.iid)
        if p['test'] == 'numeric':
            self.var.set(virtualbench.plausible_text(p['low'], p['high'], p['n'], self.app.virtual_failures()))
        else:
            self.var.set('y' if virtualbench.plausible_answer(p['n'], self.app.virtual_failures()) else 'n')
        self._select_all()
        return 'break'

    # ---- tree events ----------------------------------------------------------------------------------------------------------------------
    def on_return(self, _event=None):
        sel = self.tree.selection()
        if sel and self.entry is None:
            self.open(sel[0])
        return 'break'

    def on_key(self, event):
        ch = getattr(event, 'char', '') or ''
        if self.entry is not None or not ch or not (ch.isalnum() or ch in '-+.'):
            return None
        sel = self.tree.selection()
        if sel and self.open(sel[0], first=ch):
            self.entry.icursor('end')
            return 'break'
        return None

    def on_click(self, event):
        """A click on the reading cell of a point that was already selected opens the box (a first click only selects, as in every list)."""
        try:
            iid = self.tree.identify_row(event.y)
            col = self.tree.identify_column(event.x)
            shown = list(self.tree['displaycolumns']) if self.tree['displaycolumns'] else list(self.tree['columns'])
            name = shown[int(col.lstrip('#')) - 1] if col.startswith('#') else ''
        except (tk.TclError, ValueError, IndexError):
            return None
        if iid and name == self.column and self._armed == iid and self.entry is None:
            self.open(iid)
        self._armed = iid or None
        return None
