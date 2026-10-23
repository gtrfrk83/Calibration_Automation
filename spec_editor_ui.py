"""Standards spec editor: the windows (Tk).  The data work is in spec_editor.py (model), spec_edit_io.py (files / database) and spec_edit_log.py (log).

    open_editor(parent, model)    from the Standards Specs tab ('Edit spec...')

Editor: sheet list on the left, tabs Rows / Notes / Standard info / Limits / Sheet issues in the middle, 'Pending changes' and the checks before save on the
right.  A double-click edits a cell; changed cells are amber; a row, note or field with a validation ERROR is shown in red text (with a red cross mark and a
tooltip with the reason), a WARNING in amber (with a triangle mark).  Nothing is written until 'Document & save edit...' (reason, source, name required).
Edit history: a second window with the documented edits of the sheet, compare with the current file, restore (itself a documented edit), export.

Colours come from the ui_theme tokens (light and dark); the marks are drawn images, so no symbol font is needed.
"""
from __future__ import annotations

import json
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

import spec_edit_io as eio
import spec_edit_log as elog
import spec_editor as se
import specmanager_ui as smu
import ui_theme as ui

COLS = [  # id, heading, width (96-dpi px), anchor
    ('function', 'FUNCTION', 88, 'w'), ('label', 'RANGE', 80, 'w'), ('freq', 'FREQUENCY', 74, 'w'), ('period', 'PERIOD', 46, 'w'),
    ('rel', 'READING', 70, 'e'), ('fs_rel', 'FS (REL)', 66, 'e'), ('fs_value', 'FS VALUE', 74, 'e'), ('abs', 'FLOOR', 70, 'e'),
    ('res', 'RESOLUTION', 88, 'e'), ('notes', 'NOTES', 44, 'w'), ('page', 'PAGE', 40, 'e'), ('span', 'SPAN (VALUE RANGE)', 150, 'w')]
RANGE_LEVEL = ('label', 'span', 'freq', 'res', 'notes', 'page')
HINT = 'Double-click a cell to edit. Changed cells turn amber and are listed on the right. Nothing is written to the sheet until you document and save.'


def _fonts():
    base = tkfont.nametofont('TkDefaultFont')

    def make(size, weight='normal', **kw):
        f = base.copy()
        f.configure(size=size, weight=weight, **kw)
        return f
    mono = tkfont.nametofont('TkFixedFont').copy()
    mono.configure(size=9)
    return dict(normal=make(10), bold=make(10, 'bold'), small=make(9), smallb=make(9, 'bold'), title=make(14, 'bold'), mono=mono, strike=make(9, overstrike=1), h2=make(11, 'bold'))


def amber():
    """(background, text) of a changed cell: stronger than the palette's warn_bg so it shows on both themes."""
    return ('#5A4310', ui.C['warn']) if ui.is_dark() else ('#FFE6A8', ui.C['warn'])


def grid_style(master):
    """A Treeview style whose selected rows keep the colour of their tag (so a red row stays red when it is selected)."""
    s = ttk.Style(master)
    C = ui.C
    s.configure('SpecEd.Treeview', background=C['table'], fieldbackground=C['table'], foreground=C['text'])
    s.map('SpecEd.Treeview', foreground=[('disabled', C['faint'])], background=[('selected', C['select'])])
    return 'SpecEd.Treeview'


class Icons:
    """Small marks drawn pixel by pixel (no symbol font needed): error cross, warning triangle, ok check, new plus, changed dot."""

    def __init__(self, master):
        n = max(11, ui.px(11))
        self.n = n
        C = ui.C
        self.images = {k: self._draw(master, n, k, C) for k in ('error', 'warn', 'ok', 'new', 'changed', 'info')}

    @staticmethod
    def _draw(master, n, kind, C):
        img = tk.PhotoImage(master=master, width=n, height=n)
        col = {'error': C['bad'], 'warn': C['warn'], 'ok': C['good'], 'new': C['good'], 'changed': C['warn'], 'info': C['muted']}[kind]

        def px_(x, y, w=1):
            for dx in range(w):
                for dy in range(w):
                    if 0 <= x + dx < n and 0 <= y + dy < n:
                        img.put(col, to=(x + dx, y + dy, x + dx + 1, y + dy + 1))
        m = n // 2
        if kind == 'error':
            for i in range(1, n - 1):
                px_(i, i, 2)
                px_(n - 2 - i, i, 2)
        elif kind == 'warn':
            for y in range(1, n - 1):
                half = max(0, (y * m) // (n - 2))
                for x in range(m - half, m + half + 1):
                    px_(x, y)
            for y in range(m, n - 4):                           # the exclamation mark is a gap in the fill
                img.put(C['card'], to=(m, y, m + 1, y + 1))
            img.put(C['card'], to=(m, n - 3, m + 1, n - 2))
        elif kind == 'ok':
            for i in range(0, m - 1):
                px_(1 + i, m + i - 1, 2)
            for i in range(0, m + 2):
                px_(m - 1 + i, n - 4 - i, 2)
        elif kind == 'new':
            for i in range(2, n - 2):
                px_(i, m - 1, 2)
                px_(m - 1, i, 2)
        elif kind == 'changed':
            r = max(2, n // 4)
            for x in range(m - r, m + r + 1):
                for y in range(m - r, m + r + 1):
                    if (x - m) ** 2 + (y - m) ** 2 <= r * r:
                        px_(x, y)
        else:
            for y in range(2, n - 2):
                px_(m, y)
        return img

    def __getitem__(self, k):
        return self.images[k]


def _text_dialog(parent, title, initial, readonly=False, width=90, height=14):
    """Multi-line text in a modal window; returns the new text or None when cancelled."""
    win = ui.dialog(parent, title, modal=True)
    result = {'v': None}
    txt = tk.Text(win, width=width, height=height, wrap='word', background=ui.C['field'], foreground=ui.C['text'], insertbackground=ui.C['text'], relief='flat', padx=10, pady=8,
                  borderwidth=0, highlightthickness=1, highlightbackground=ui.C['border'])
    txt.pack(fill='both', expand=True, padx=ui.px(12), pady=(ui.px(12), ui.px(6)))
    txt.insert('1.0', initial)
    if readonly:
        txt.configure(state='disabled')
    bar = ttk.Frame(win)
    bar.pack(fill='x', padx=ui.px(12), pady=(0, ui.px(12)))

    def ok():
        result['v'] = txt.get('1.0', 'end-1c')
        win.destroy()
    ttk.Button(bar, text='Close' if readonly else 'Cancel', command=win.destroy).pack(side='right')
    if not readonly:
        ttk.Button(bar, text='OK', style='Accent.TButton', command=ok).pack(side='right', padx=(0, ui.px(8)))
    txt.focus_set()
    win.text = txt
    win.ok = ok
    win.wait_window()
    return result['v']


# ------------------------------------------------------------------------------------------------------------ a table with inline editing and amber cells
class Grid:
    """A Treeview with (a) in-cell editing on double-click, (b) amber marks over the changed cells, (c) red / amber rows with a tooltip for validation issues."""

    def __init__(self, parent, editor, columns, show_flag=True, height=12, hscroll=True):
        self.ed = editor
        self.cols = columns
        self.holder = ttk.Frame(parent)
        self.holder.rowconfigure(0, weight=1)
        self.holder.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(self.holder, columns=[c[0] for c in columns], show='tree headings', selectmode='browse', height=height, style=grid_style(parent))
        self.tree.heading('#0', text='')
        self.tree.column('#0', width=ui.px(26), minwidth=ui.px(26), stretch=False, anchor='center')
        for cid, head, width, anchor in columns:
            self.tree.heading(cid, text=head, anchor='w' if anchor == 'w' else 'e')
            self.tree.column(cid, width=ui.px(width), minwidth=ui.px(40), anchor=anchor, stretch=False)
        self.ys = ttk.Scrollbar(self.holder, orient='vertical', command=self.tree.yview)
        self.xs = ttk.Scrollbar(self.holder, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=self._yset, xscrollcommand=self._xset)
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.ys.grid(row=0, column=1, sticky='ns')
        if hscroll:
            self.xs.grid(row=1, column=0, sticky='ew')
        C = ui.C
        t = self.tree
        t.tag_configure('odd', background=C['row_alt'])
        t.tag_configure('even', background=C['card'])
        t.tag_configure('cont', foreground=C['muted'])
        t.tag_configure('new', background=amber()[0])
        t.tag_configure('warn', foreground=C['warn'])
        t.tag_configure('err', foreground=C['bad'])
        self.marks = {}
        self.entry = None
        self.on_edit = None          # (iid, column id, text) -> None; raises se.EditError
        self.initial = None          # (iid, column id) -> text for the editor, or None when the cell is not editable
        self.long_text = None        # (iid, column id) -> True to edit in the multi-line window
        self.tip_for = None          # (iid, column id) -> tooltip text
        self.selected_col = None
        t.bind('<Double-1>', self._double, add='+')
        t.bind('<Button-1>', self._click, add='+')
        t.bind('<Return>', self._enter, add='+')
        t.bind('<Configure>', lambda _e: self._remark(), add='+')
        t.bind('<ButtonRelease-1>', lambda _e: self._remark(), add='+')
        t.bind('<<TreeviewSelect>>', lambda _e: self.ed._selection_changed(self), add='+')
        smu.CellTip(t, lambda iid, col: self.tip_for(iid, col) if self.tip_for else '')
        self._job = None
        self.changed = set()
        self.cell_text = lambda iid, col: ''

    # ---- scrolling keeps the amber marks on their cells
    def _yset(self, lo, hi):
        self.ys.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.ys.grid_remove()
        else:
            self.ys.grid()
        self._remark()

    def _xset(self, lo, hi):
        self.xs.set(lo, hi)
        self._remark()

    def names(self):
        disp = self.tree['displaycolumns']
        return list(self.tree['columns']) if tuple(disp) == ('#all',) else list(disp)

    def column_at(self, x):
        k = self.tree.identify_column(x)
        try:
            i = int(k[1:])
        except ValueError:
            return None
        return None if i == 0 else self.names()[i - 1]

    # ---- amber marks
    def set_changed(self, cells, text_of):
        self.changed, self.cell_text = set(cells), text_of
        self._remark()

    def _remark(self):
        if self._job is None:
            self._job = self.tree.after_idle(self._place_marks)

    def _place_marks(self):
        self._job = None
        for lab in self.marks.values():
            lab.destroy()
        self.marks = {}
        t = self.tree
        C = ui.C
        for iid, col in self.changed:
            if not t.exists(iid) or col not in self.names():
                continue
            box = t.bbox(iid, col)
            if not box:
                continue
            x, y, w, h = box
            tags = t.item(iid, 'tags')
            fg = C['bad'] if 'err' in tags else C['warn']
            anchor = dict((c[0], c[3]) for c in self.cols).get(col, 'w')
            lab = tk.Label(t, text=self.cell_text(iid, col), background=amber()[0], foreground=fg, anchor=anchor, borderwidth=0, padx=ui.px(4), font=self.ed.fonts['normal'])
            lab.place(x=x, y=y, width=w, height=h)
            lab.bind('<Button-1>', lambda e, i=iid, c=col: self._forward_click(e, i, c))
            lab.bind('<Double-1>', lambda e, i=iid, c=col: self.begin_edit(i, c))
            lab.bind('<MouseWheel>', lambda e: t.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
            lab.bind('<Button-4>', lambda e: t.yview_scroll(-1, 'units'))
            lab.bind('<Button-5>', lambda e: t.yview_scroll(1, 'units'))
            self.marks[(iid, col)] = lab

    def _forward_click(self, e, iid, col):
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.selected_col = col
        self.ed._selection_changed(self)

    # ---- editing
    def _click(self, e):
        col = self.column_at(e.x)
        if col:
            self.selected_col = col
        self._close_entry(commit=True)

    def _double(self, e):
        if self.tree.identify_region(e.x, e.y) != 'cell':
            return
        iid, col = self.tree.identify_row(e.y), self.column_at(e.x)
        if iid and col:
            self.begin_edit(iid, col)
        return 'break'

    def _enter(self, _e):
        sel = self.tree.selection()
        if sel and self.selected_col:
            self.begin_edit(sel[0], self.selected_col)

    def begin_edit(self, iid, col):
        self._close_entry(commit=False)
        text = self.initial(iid, col) if self.initial else None
        if text is None:
            return
        if self.long_text and self.long_text(iid, col):
            new = _text_dialog(self.tree, f'Edit {col}', text)
            if new is not None:
                self._apply(iid, col, new)
            return
        box = self.tree.bbox(iid, col)
        if not box:
            self.tree.see(iid)
            box = self.tree.bbox(iid, col)
            if not box:
                return
        x, y, w, h = box
        var = tk.StringVar(value=text)
        ent = ttk.Entry(self.tree, textvariable=var)
        ent.place(x=x, y=y, width=max(w, ui.px(70)), height=h)
        ent.focus_set()
        ent.selection_range(0, 'end')
        ent.bind('<Return>', lambda _e: self._close_entry(commit=True))
        ent.bind('<Escape>', lambda _e: self._close_entry(commit=False))
        ent.bind('<FocusOut>', lambda _e: self._close_entry(commit=True))
        self.entry = (ent, var, iid, col, text)

    def _close_entry(self, commit):
        if not self.entry:
            return
        ent, var, iid, col, old = self.entry
        self.entry = None
        value = var.get()
        try:
            ent.destroy()
        except tk.TclError:
            pass
        if commit and value != old:
            self._apply(iid, col, value)

    def commit_text(self, iid, col, text):
        """Type `text` into a cell the way the person would (used by tests and by the entry)."""
        self._apply(iid, col, text)

    def _apply(self, iid, col, text):
        try:
            self.on_edit(iid, col, text)
        except se.EditError as e:
            self.ed.say(str(e), 'error')
            return False
        self.ed.say('', '')
        return True


# ------------------------------------------------------------------------------------------------------------ the editor window
class EditorWindow:
    def __init__(self, parent, model=None, on_saved=None, spec_dir=None, db_path=None, backup_dir=None, width=1180, height=760):
        self.parent, self.on_saved, self.spec_dir, self.db_path, self.backup_dir = parent, on_saved, spec_dir, db_path, backup_dir
        self.win = ui.dialog(parent, 'Edit standards spec', modal=False)
        self.win.transient(None)
        self.fonts = _fonts()
        self.icons = Icons(self.win)
        self.docs, self.errors_of_load = {}, {}
        self.sheets = se.list_sheets(spec_dir)
        self.cur = None            # file name
        self.report = None
        self.history_window = None
        self.detail_text = ''
        self._build()
        ui.fit_window(self.win, width, height, min_w=1000, min_h=620)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        target = None
        if model:
            f = se.sheet_for_model(model, spec_dir)
            target = f.name if f else None
        if target is None and self.sheets:
            target = self.sheets[0][0].name
        if target:
            self.select_sheet(target)
        if model and not se.sheet_for_model(model, spec_dir):
            self.say(f'{model} has no sheet file in specs/standards/ (it was imported from elsewhere); pick a sheet on the left.', 'warn')
        ui.polish(self.win)

    # ---- layout
    def _build(self):
        C, f = ui.C, self.fonts
        w = self.win
        w.columnconfigure(0, weight=1)
        w.rowconfigure(2, weight=1)
        head = tk.Frame(w, background=C['card'])
        head.grid(row=0, column=0, sticky='ew')
        tk.Label(head, text='Edit standards spec', font=f['title'], foreground=C['text'], background=C['card']).pack(side='left', padx=(ui.px(16), ui.px(12)), pady=ui.px(10))
        self.path_label = tk.Label(head, text='', font=f['mono'], foreground=C['muted'], background=C['card'], anchor='w')
        self.path_label.pack(side='left', fill='x', expand=True)
        self.pill = tk.Label(head, text='', font=f['smallb'], padx=ui.px(10), pady=ui.px(2))
        self.pill.pack(side='right', padx=ui.px(16))
        tk.Frame(w, height=1, background=C['border']).grid(row=0, column=0, sticky='sew')
        outer = ttk.Frame(w, padding=(ui.px(16), ui.px(8)))
        outer.grid(row=1, column=0, sticky='ew')
        bar = ttk.Frame(outer)
        bar.pack(fill='x')
        self.btn = {}
        for key, text, cmd, style in (
                ('save', 'Document & save edit...', self.document_and_save, 'Accent.TButton'), ('discard', 'Discard all', self.discard_all, ''),
                ('revert', 'Revert selected cell', self.revert_selected, ''), ('add', 'Add row', self.add_row, ''), ('delete', 'Delete row', self.delete_row, ''),
                ('addp', 'Add period', self.add_period, ''), ('delp', 'Delete period', self.delete_period, ''), ('details', 'Row details...', self.row_details, '')):
            b = ttk.Button(bar, text=text, command=cmd, style=style or 'Compact.TButton')
            b.pack(side='left', padx=(0, ui.px(8)))
            self.btn[key] = b
        self.btn['history'] = ttk.Button(bar, text='Edit history', command=self.open_history, style='Compact.TButton')
        self.btn['history'].pack(side='right')
        body = tk.Frame(w, background=C['bg'])
        body.grid(row=2, column=0, sticky='nsew')
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        # left: sheets
        left = tk.Frame(body, background=C['card'], width=ui.px(150))
        left.grid(row=0, column=0, sticky='ns')
        left.grid_propagate(False)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        tk.Label(left, text='STANDARDS SHEETS', font=f['smallb'], foreground=C['muted'], background=C['card'], anchor='w').grid(row=0, column=0, sticky='ew', padx=ui.px(12), pady=(ui.px(10), ui.px(4)))
        self.sheet_list = ttk.Treeview(left, show='tree', selectmode='browse')
        self.sheet_list.column('#0', width=ui.px(130), stretch=True)
        self.sheet_list.grid(row=1, column=0, sticky='nsew')
        self.sheet_list.tag_configure('dirty', foreground=C['warn'])
        self.sheet_list.tag_configure('hand', foreground=C['info'])
        for path, model, desc in self.sheets:
            self.sheet_list.insert('', 'end', iid=path.name, text=model or path.name)
        self.sheet_list.bind('<<TreeviewSelect>>', lambda _e: self._sheet_picked())
        tk.Label(left, text='\u25cf = unsaved edits\n(edited) = edited by hand since built', font=f['small'], foreground=C['muted'], background=C['card'], anchor='w', justify='left', wraplength=ui.px(130)).grid(
            row=2, column=0, sticky='ew', padx=ui.px(12), pady=ui.px(8))
        tk.Frame(body, width=1, background=C['border']).grid(row=0, column=0, sticky='nse')
        # centre: tabs
        mid = tk.Frame(body, background=C['bg'])
        mid.grid(row=0, column=1, sticky='nsew')
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        self.nb = ttk.Notebook(mid)
        self.nb.grid(row=0, column=0, sticky='nsew', padx=(ui.px(10), 0), pady=(ui.px(6), 0))
        self.tab_rows = ttk.Frame(self.nb)
        self.tab_notes = ttk.Frame(self.nb)
        self.tab_info = ttk.Frame(self.nb)
        self.tab_limits = ttk.Frame(self.nb)
        self.tab_issues = ttk.Frame(self.nb)
        for fr, name in ((self.tab_rows, 'Rows'), (self.tab_notes, 'Notes'), (self.tab_info, 'Standard info'), (self.tab_limits, 'Limits'), (self.tab_issues, 'Sheet issues')):
            self.nb.add(fr, text=name)
        self._build_rows_tab()
        self._build_notes_tab()
        self._build_info_tab()
        self._build_list_tab(self.tab_limits, 'limits', (('function', 'FUNCTION', 260, 'w'), ('limit', 'LIMIT TEXT', 420, 'w'), ('page', 'PAGE', 60, 'w')), 'limit')
        self._build_list_tab(self.tab_issues, 'issues', (('level', 'LEVEL', 60, 'w'), ('where', 'WHERE', 300, 'w'), ('what', 'WHAT', 480, 'w')), 'problem')
        self.msg = tk.Label(mid, text='', font=f['normal'], foreground=C['bad'], background=C['bg'], anchor='w', justify='left')
        self.msg.grid(row=1, column=0, sticky='ew', padx=ui.px(12), pady=(ui.px(2), 0))
        self.msg.bind('<Configure>', lambda e: self.msg.configure(wraplength=max(200, e.width - 20)))
        # right: pending
        right = tk.Frame(body, background=C['card'], width=ui.px(280))
        right.grid(row=0, column=2, sticky='ns')
        right.grid_propagate(False)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        tk.Frame(body, width=1, background=C['border']).grid(row=0, column=2, sticky='nsw')
        self.pending = tk.Text(right, wrap='word', background=C['card'], foreground=C['text'], relief='flat', borderwidth=0, highlightthickness=0, padx=ui.px(14), pady=ui.px(10),
                               width=10, cursor='arrow', spacing1=1, spacing3=1)
        ps = ttk.Scrollbar(right, orient='vertical', command=self.pending.yview)
        self.pending.configure(yscrollcommand=ps.set, state='disabled')
        self.pending.grid(row=0, column=0, sticky='nsew')
        ps.grid(row=0, column=1, sticky='ns')
        p = self.pending
        p.tag_configure('h', font=f['h2'], spacing1=6, spacing3=4)
        p.tag_configure('where', font=f['small'], foreground=C['muted'], spacing1=6)
        p.tag_configure('field', font=f['small'], foreground=C['muted'])
        p.tag_configure('old', font=self.fonts['strike'], foreground=C['bad'])
        p.tag_configure('new', font=f['mono'], foreground=C['good'])
        p.tag_configure('arrow', foreground=C['muted'])
        p.tag_configure('ok', foreground=C['good'], font=f['small'], lmargin1=ui.px(18), lmargin2=ui.px(18))
        p.tag_configure('warnline', foreground=C['warn'], font=f['small'], lmargin1=ui.px(18), lmargin2=ui.px(18))
        p.tag_configure('errline', foreground=C['bad'], font=f['small'], lmargin1=ui.px(18), lmargin2=ui.px(18))
        p.tag_configure('infoline', foreground=C['muted'], font=f['small'], lmargin1=ui.px(18), lmargin2=ui.px(18))
        p.tag_configure('muted', foreground=C['muted'], font=f['small'])
        p.tag_configure('link', foreground=C['primary'], font=f['smallb'])
        # status
        self.status = tk.Label(w, text='', font=f['small'], foreground=C['muted'], background=C['card'], anchor='w', padx=ui.px(16), pady=ui.px(5))
        self.status.grid(row=3, column=0, sticky='ew')
        tk.Frame(w, height=1, background=C['border']).grid(row=3, column=0, sticky='new')

    def _build_rows_tab(self):
        tab = self.tab_rows
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.grid_rows = Grid(tab, self, COLS, height=14)
        self.grid_rows.holder.grid(row=0, column=0, sticky='nsew', padx=ui.px(6), pady=ui.px(6))
        g = self.grid_rows
        g.initial = self._rows_initial
        g.on_edit = lambda iid, col, text: self._edit_row_cell(iid, col, text)
        g.tip_for = self._rows_tip
        self.row_issue = tk.Label(tab, text='', font=self.fonts['small'], foreground=ui.C['muted'], background=ui.C['bg'], anchor='w', justify='left')
        self.row_issue.grid(row=1, column=0, sticky='ew', padx=ui.px(10))
        self.row_issue.bind('<Configure>', lambda e: self.row_issue.configure(wraplength=max(200, e.width - 20)))
        hint = tk.Label(tab, text=HINT, font=self.fonts['small'], foreground=ui.C['muted'], background=ui.C['bg'], anchor='w', justify='left')
        hint.grid(row=2, column=0, sticky='ew', padx=ui.px(10), pady=(0, ui.px(6)))
        hint.bind('<Configure>', lambda e: hint.configure(wraplength=max(200, e.width - 20)))

    def _build_notes_tab(self):
        tab = self.tab_notes
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.grid_notes = Grid(tab, self, (('no', 'NO.', 46, 'w'), ('text', 'NOTE', 560, 'w'), ('used', 'USED BY', 90, 'w')), height=12)
        self.grid_notes.holder.grid(row=0, column=0, sticky='nsew', padx=ui.px(6), pady=ui.px(6))
        g = self.grid_notes
        g.initial = lambda iid, col: self.doc.current['notes'][iid[1:]] if col == 'text' and iid[1:] in self.doc.current.get('notes', {}) else None
        g.long_text = lambda iid, col: True
        g.on_edit = lambda iid, col, text: (self.doc.edit_note(iid[1:], text), self.refresh())
        g.tip_for = lambda iid, col: self.report.text_for('notes', iid[1:]) if self.report else ''
        bar = ttk.Frame(tab)
        bar.grid(row=1, column=0, sticky='ew', padx=ui.px(6), pady=(0, ui.px(6)))
        ttk.Button(bar, text='Add note', command=self.add_note).pack(side='left', padx=(0, ui.px(8)))
        ttk.Button(bar, text='Delete note', command=self.delete_note).pack(side='left')
        self.notes_hint = tk.Label(bar, text='Double-click a note to edit its text. A row that points at a deleted note turns red.', font=self.fonts['small'], foreground=ui.C['muted'], background=ui.C['bg'])
        self.notes_hint.pack(side='left', padx=ui.px(12))

    def _build_info_tab(self):
        tab = self.tab_info
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)
        self.info_notice = tk.Frame(tab, background=ui.C['bg'])
        self.info_notice.grid(row=0, column=0, sticky='ew', padx=ui.px(6), pady=(ui.px(6), 0))
        self.grid_info = Grid(tab, self, (('field', 'FIELD', 150, 'w'), ('value', 'VALUE', 640, 'w')), height=12, hscroll=False)
        self.grid_info.holder.grid(row=1, column=0, sticky='nsew', padx=ui.px(6), pady=ui.px(6))
        g = self.grid_info
        g.initial = self._info_initial
        g.long_text = lambda iid, col: len(str(self.doc.current['standard'].get(iid[1:], '') or '')) > 70
        g.on_edit = lambda iid, col, text: (self.doc.edit_info(iid[1:], text), self.refresh())
        g.tip_for = lambda iid, col: self.report.text_for('info', iid[1:]) if self.report else ''
        self.info_derived = tk.Label(tab, text='', font=self.fonts['small'], foreground=ui.C['muted'], background=ui.C['bg'], anchor='w', justify='left')
        self.info_derived.grid(row=2, column=0, sticky='ew', padx=ui.px(10), pady=(0, ui.px(6)))
        self.info_derived.bind('<Configure>', lambda e: self.info_derived.configure(wraplength=max(200, e.width - 20)))

    def _build_list_tab(self, tab, area, columns, node):
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        g = Grid(tab, self, columns, height=10)
        g.holder.grid(row=0, column=0, sticky='nsew', padx=ui.px(6), pady=ui.px(6))
        setattr(self, 'grid_' + area, g)
        g.initial = lambda iid, col, a=area: self._list_initial(a, iid, col)
        g.long_text = lambda iid, col, a=area: col in ('limit', 'what')
        g.on_edit = lambda iid, col, text, a=area: self._list_edit(a, iid, col, text)
        g.tip_for = lambda iid, col, a=area: self.report.text_for(a, int(iid[1:])) if self.report else ''
        bar = ttk.Frame(tab)
        bar.grid(row=1, column=0, sticky='ew', padx=ui.px(6), pady=(0, ui.px(6)))
        ttk.Button(bar, text='Add entry', command=lambda a=area: self.add_list(a)).pack(side='left', padx=(0, ui.px(8)))
        ttk.Button(bar, text='Delete entry', command=lambda a=area: self.delete_list(a)).pack(side='left')
        hint = ('The limits written on the sheet (page, text); information for the reader of the sheet.' if area == 'limits' else
                'Problems found when the sheet was read (level, where, what). They are not recomputed by an edit; see the checks on the right for new ones.')
        tk.Label(bar, text=hint, font=self.fonts['small'], foreground=ui.C['muted'], background=ui.C['bg']).pack(side='left', padx=ui.px(12))

    # ---- state helpers
    @property
    def doc(self):
        return self.docs.get(self.cur)

    def say(self, text, kind=''):
        self.msg.configure(text=('x  ' if kind == 'error' else '') + text, foreground=ui.C['bad'] if kind == 'error' else (ui.C['warn'] if kind == 'warn' else ui.C['muted']))

    def select_sheet(self, name):
        if name not in [p.name for p, _, _ in self.sheets]:
            return
        self.sheet_list.selection_set(name)
        self.sheet_list.see(name)
        self._sheet_picked()

    def _sheet_picked(self):
        sel = self.sheet_list.selection()
        if not sel or sel[0] == self.cur:
            return
        self.cur = sel[0]
        if self.cur not in self.docs:
            path = next(p for p, _, _ in self.sheets if p.name == self.cur)
            try:
                self.docs[self.cur] = se.SpecDoc.load(path)
                self.errors_of_load.pop(self.cur, None)
            except (se.SpecFileError, OSError) as e:
                self.errors_of_load[self.cur] = str(e)
        self.refresh()

    # ---- refreshing everything from the document
    def refresh(self):
        doc = self.doc
        for g in (self.grid_rows, self.grid_notes, self.grid_info, self.grid_limits, self.grid_issues):
            g._close_entry(commit=False)
        if doc is None:
            self.report = None
            self.path_label.configure(text=self.errors_of_load.get(self.cur, ''))
            for b in self.btn.values():
                b.state(['disabled'])
            self._fill_pending()
            return
        self.report = se.validate(doc)
        self.path_label.configure(text=f'specs/standards/{doc.name}')
        self._fill_rows()
        self._fill_notes()
        self._fill_info()
        self._fill_list('limits', self.grid_limits, 'limit')
        self._fill_list('issues', self.grid_issues, 'problem')
        self._fill_pending()
        self._tab_titles()
        self._buttons()
        self._status_line()
        self._sheet_marks()
        self._selection_changed(self.grid_rows)

    def _unsaved(self):
        return sum(d.change_count() for d in self.docs.values())

    def _buttons(self):
        doc = self.doc
        n = doc.change_count()
        ok = self.report.can_save and n > 0
        self.btn['save'].state(['!disabled'] if ok else ['disabled'])
        for k in ('discard',):
            self.btn[k].state(['!disabled'] if n else ['disabled'])
        self.btn['history'].configure(text=f'Edit history ({elog.count(doc.name, self.db_path)})')
        c = ui.C
        total = self._unsaved()
        if total:
            self.pill.configure(text=f'{total} unsaved change{"s" if total != 1 else ""}' + ('' if n == total else f' ({n} in this sheet)'), background=c['warn_bg'], foreground=c['warn'])
        else:
            self.pill.configure(text='No unsaved changes', background=c['neutral_bg'], foreground=c['neutral'])
        self.btn['save'].configure(text='Document & save edit...')

    def _sheet_marks(self):
        for path, model, _ in self.sheets:
            d = self.docs.get(path.name)
            dirty = bool(d and d.change_count())
            st = eio.sheet_state(path, self.db_path)
            hand = st['state'] in ('edited by hand', 'changed outside')
            self.sheet_list.item(path.name, text=(model or path.name) + ('  ●' if dirty else '') + ('  (edited)' if hand else ''),
                                 tags=('dirty',) if dirty else (('hand',) if hand else ()))

    def _tab_titles(self):
        doc, rep = self.doc, self.report

        def mark(area, base):
            worst = ''
            for i in rep.issues:
                if i.area == area:
                    if i.level == 'error':
                        worst = 'error'
                        break
                    if i.level == 'warn':
                        worst = 'warn'
            return base + ('  (!)' if worst == 'error' else ('  (?)' if worst == 'warn' else ''))
        self.nb.tab(self.tab_rows, text=mark('rows', f'Rows ({len(doc.ranges())})'))
        self.nb.tab(self.tab_notes, text=mark('notes', f'Notes ({len(doc.current.get("notes") or {})})'))
        self.nb.tab(self.tab_info, text=mark('info', 'Standard info'))
        self.nb.tab(self.tab_limits, text=mark('limits', f'Limits ({len(doc.list_nodes("limits"))})'))
        self.nb.tab(self.tab_issues, text=mark('issues', f'Sheet issues ({len(doc.list_nodes("issues"))})'))

    def _status_line(self):
        doc = self.doc
        std = doc.current.get('standard', {})
        pct = std.get('confidence_pct')
        div = f'{se.divisor_for(pct)[0]:g}' if isinstance(pct, (int, float)) else '2 (assumed)'
        st = eio.sheet_state(doc, self.db_path)
        last = st['last']
        built = ', '.join(n for n, _ in st.get('builders') or [])
        parts = [f'Confidence {pct:g} %' if isinstance(pct, (int, float)) else 'Confidence not specified', f'divisor {div}', f'revision {std.get("revision", "") or "-"}',
                 f'last saved edit: {last["at"][:10]}' if last else 'no documented edit yet']
        if built:
            parts.append(f'built by specs/{built}')
        self.status.configure(text='  ·  '.join(parts) + ('   [edited by hand since built]' if st['state'] == 'edited by hand' else ''))

    # ---- rows tab
    def _display_cols(self):
        doc = self.doc
        has_fs = any((s.get('fs_rel') or s.get('fs_value')) for _, r in doc.ranges() for s in r.get('specs') or [] if isinstance(s, dict))
        cols = [c[0] for c in COLS if has_fs or c[0] not in ('fs_rel', 'fs_value')]
        return cols

    def _fill_rows(self):
        g, doc, rep = self.grid_rows, self.doc, self.report
        t = g.tree
        sel = t.selection()
        y0 = t.yview()[0]
        t['displaycolumns'] = self._display_cols()
        t.delete(*t.get_children())
        changed = doc.changed_cells()
        new_uids = doc.new_range_uids()
        changed_iids = {i for i, _ in changed}
        shade = 0
        last_r = None
        for ln in doc.lines():
            ru = doc.uid(ln.rng)
            if ru != last_r:
                shade += 1
                last_r = ru
            worst = rep.worst('rows', ru)
            tags = ['odd' if shade % 2 else 'even']
            if ru in new_uids:
                tags.append('new')
            if worst == 'error':
                tags.append('err')
            elif worst == 'warn':
                tags.append('warn')
            elif not ln.first:
                tags.append('cont')
            icon = self.icons['error'] if worst == 'error' else (self.icons['warn'] if worst == 'warn' else (
                self.icons['new'] if ru in new_uids else (self.icons['changed'] if ln.iid in changed_iids else '')))
            t.insert('', 'end', iid=ln.iid, image=icon, values=[doc.cell_text(ln, c[0]) for c in COLS], tags=tuple(tags))
        g.set_changed(changed, lambda iid, col: t.set(iid, col) if t.exists(iid) else '')
        keep = [s for s in sel if t.exists(s)]
        if keep:
            t.selection_set(keep)
        elif t.get_children():
            t.selection_set(t.get_children()[0])
        t.yview_moveto(y0)

    def _rows_initial(self, iid, col):
        doc = self.doc
        ln = doc.line(iid)
        if ln is None or col not in [c[0] for c in COLS]:
            return None
        if col in RANGE_LEVEL and not ln.first:
            self.say('That column belongs to the whole row: edit it on the first line of the row.', 'warn')
            return None
        if col in ('period', 'rel', 'fs_rel', 'fs_value', 'abs') and ln.spec is None:
            self.say('This row has no specification line; use "Add period line".', 'warn')
            return None
        return doc.cell_text(ln, col)

    def _edit_row_cell(self, iid, col, text):
        keys = self.doc.edit_cell(iid, col, text)
        self.refresh()
        if self.grid_rows.tree.exists(iid):
            self.grid_rows.tree.selection_set(iid)
        return keys

    def _rows_tip(self, iid, col):
        doc, rep = self.doc, self.report
        ln = doc.line(iid) if doc else None
        if ln is None or rep is None:
            return ''
        issue = rep.text_for('rows', doc.uid(ln.rng))
        return issue or (doc.cell_text(ln, col) if col in [c[0] for c in COLS] and len(doc.cell_text(ln, col)) > 9 else '')

    def _selected_line(self):
        sel = self.grid_rows.tree.selection()
        return self.doc.line(sel[0]) if sel and self.doc else None

    def _selection_changed(self, grid):
        if grid is not self.grid_rows or not self.doc:
            return
        ln = self._selected_line()
        has = ln is not None
        for k in ('delete', 'addp', 'details', 'add'):
            self.btn[k].state(['!disabled'] if has else ['disabled'])
        self.btn['delp'].state(['!disabled'] if has and ln.spec is not None and len(ln.rng.get('specs') or []) > 1 else ['disabled'])
        self.btn['revert'].state(['!disabled'] if has else ['disabled'])
        text, bad = '', False
        if has and self.report:
            text = self.report.text_for('rows', self.doc.uid(ln.rng))
            bad = any(i.level == 'error' for i in self.report.row_issues(self.doc.uid(ln.rng)))
        self.row_issue.configure(text=text, foreground=ui.C['bad'] if bad else ui.C['warn'])
        self.detail_text = text

    # ---- notes tab
    def _note_usage(self):
        use = {}
        for _, r in self.doc.ranges():
            for n in self.doc.range_notes(r):
                use[str(n)] = use.get(str(n), 0) + 1
        return use

    def _fill_notes(self):
        g, doc, rep = self.grid_notes, self.doc, self.report
        t = g.tree
        sel = t.selection()
        t.delete(*t.get_children())
        use = self._note_usage()
        changed = {(f'n{c.uid}', 'text') for c in doc.changes_of('notes') if c.op == 'set'}
        added = {f'n{c.uid}' for c in doc.changes_of('notes') if c.op == 'add'}
        for k in sorted(doc.current.get('notes') or {}, key=lambda x: (0, int(x)) if str(x).isdigit() else (1, 0)):
            worst = rep.worst('notes', str(k))
            tags = ['err'] if worst == 'error' else (['warn'] if worst == 'warn' else [])
            if f'n{k}' in added:
                tags.append('new')
            icon = self.icons['error'] if worst == 'error' else (self.icons['warn'] if worst == 'warn' else (self.icons['new'] if f'n{k}' in added else (
                self.icons['changed'] if (f'n{k}', 'text') in changed else '')))
            text = str(doc.current['notes'][k]).replace('\n', ' ')
            t.insert('', 'end', iid=f'n{k}', image=icon, values=(k, text, f'{use.get(str(k), 0)} rows'), tags=tuple(tags))
        g.set_changed(changed | {(i, 'text') for i in added}, lambda iid, col: t.set(iid, col) if t.exists(iid) else '')
        keep = [s for s in sel if t.exists(s)]
        if keep:
            t.selection_set(keep)

    def add_note(self):
        if not self.doc:
            return
        k = self.doc.add_note('')
        self.refresh()
        self.nb.select(self.tab_notes)
        self.grid_notes.tree.selection_set(f'n{k}')
        self.grid_notes.tree.see(f'n{k}')
        self.grid_notes.begin_edit(f'n{k}', 'text')

    def delete_note(self):
        sel = self.grid_notes.tree.selection()
        if not sel or not self.doc:
            return
        n = self._note_usage().get(sel[0][1:], 0)
        if n and not messagebox.askyesno('Delete note', f'Note {sel[0][1:]} is used by {n} row(s); they will show a missing-note error until fixed.\n\nDelete it?', parent=self.win):
            return
        self.doc.delete_note(sel[0][1:])
        self.refresh()

    # ---- standard info tab
    def _info_keys(self):
        std = self.doc.current.get('standard') or {}
        return list(se.INFO_FIELDS) + [k for k in std if k not in se.INFO_FIELDS]

    def _fill_info(self):
        g, doc, rep = self.grid_info, self.doc, self.report
        t = g.tree
        sel = t.selection()
        t.delete(*t.get_children())
        std = doc.current.get('standard') or {}
        changed = {(f'i{c.uid}', 'value') for c in doc.changes_of('info') if c.node == 'info'}
        for k in self._info_keys():
            v = std.get(k)
            worst = rep.worst('info', k)
            tags = ['err'] if worst == 'error' else (['warn'] if worst == 'warn' else [])
            icon = self.icons['error'] if worst == 'error' else (self.icons['warn'] if worst == 'warn' else (self.icons['changed'] if (f'i{k}', 'value') in changed else ''))
            shown = '' if v is None else str(v)
            if k in se.READ_ONLY_INFO:
                shown += '   (read-only: it identifies the sheet)'
            t.insert('', 'end', iid=f'i{k}', image=icon, values=(k, shown.replace('\n', ' ')), tags=tuple(tags))
        g.set_changed(changed, lambda iid, col: t.set(iid, col) if t.exists(iid) else '')
        keep = [s for s in sel if t.exists(s)]
        if keep:
            t.selection_set(keep)
        st = eio.sheet_state(doc, self.db_path)
        for w in self.info_notice.winfo_children():
            w.destroy()
        kind = 'warn' if st['state'] in ('edited by hand', 'changed outside') else 'info'
        ui.Notice(self.info_notice, eio.state_text(st), kind=kind).pack(fill='x')
        pct = std.get('confidence_pct')
        div = se.divisor_for(pct) if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None
        lines = [f'Coverage divisor from the confidence level: {div[0]:g}' + ('' if div[1] else ' (nearest standard level)') if div else
                 'No confidence level: the divisor is 2 (k = 2 assumed); an explicit divisor set in Standards Specs wins over the sheet.']
        lines.append(f'Procedures whose fingerprint lists this file: ' + (', '.join(se.procedures_listing(doc.name)) or 'none'))
        lines.append(f'Current file SHA-256: {doc.sha}')
        self.info_derived.configure(text='\n'.join(lines))

    def _info_initial(self, iid, col):
        k = iid[1:]
        if col != 'value':
            return None
        if k in se.READ_ONLY_INFO:
            self.say('The model identifies the sheet in the database and cannot be edited here.', 'warn')
            return None
        v = self.doc.current['standard'].get(k)
        return '' if v is None else str(v)

    # ---- limits / issues tabs
    def _list_nodes(self, area):
        return self.doc.list_nodes('limits' if area == 'limits' else 'issues')

    def _fill_list(self, area, g, node):
        doc, rep = self.doc, self.report
        t = g.tree
        sel = t.selection()
        t.delete(*t.get_children())
        cols = [c[0] for c in g.cols]
        changes = doc.changes_of(area)
        changed = {(f'x{c.uid}', c.key) for c in changes if c.op == 'set'}
        added = {f'x{c.uid}' for c in changes if c.op == 'add'}
        for x in self._list_nodes(area):
            u = doc.uid(x)
            worst = rep.worst(area, u)
            tags = ['err'] if worst == 'error' else (['warn'] if worst == 'warn' else [])
            if f'x{u}' in added:
                tags.append('new')
            icon = self.icons['error'] if worst == 'error' else (self.icons['new'] if f'x{u}' in added else (self.icons['changed'] if any(i == f'x{u}' for i, _ in changed) else ''))
            t.insert('', 'end', iid=f'x{u}', image=icon, values=[str(x.get(c, '')).replace('\n', ' ') for c in cols], tags=tuple(tags))
        g.set_changed(changed | {(i, cols[0]) for i in added}, lambda iid, col: t.set(iid, col) if t.exists(iid) else '')
        keep = [s for s in sel if t.exists(s)]
        if keep:
            t.selection_set(keep)

    def _list_node(self, iid):
        u = int(iid[1:])
        return next((x for x in self.doc.list_nodes('limits') + self.doc.list_nodes('issues') if self.doc.uid(x) == u), None)

    def _list_initial(self, area, iid, col):
        x = self._list_node(iid)
        return None if x is None else str(x.get(col, ''))

    def _list_edit(self, area, iid, col, text):
        x = self._list_node(iid)
        if x is None:
            raise se.EditError('that entry no longer exists')
        self.doc.edit_field(x, col, text)
        self.refresh()

    def add_list(self, area):
        if not self.doc:
            return
        x = self.doc.add_list_item(area)
        self.refresh()
        g = self.grid_limits if area == 'limits' else self.grid_issues
        g.tree.selection_set(f'x{self.doc.uid(x)}')

    def delete_list(self, area):
        g = self.grid_limits if area == 'limits' else self.grid_issues
        sel = g.tree.selection()
        if not sel:
            return
        x = self._list_node(sel[0])
        if x is not None:
            self.doc.delete_list_item(area, x)
            self.refresh()

    # ---- pending panel
    def _fill_pending(self):
        p, doc, rep = self.pending, self.doc, self.report
        p.configure(state='normal')
        p.delete('1.0', 'end')
        self._links = {}
        for t in p.tag_names():
            if t.startswith('rv') or t.startswith('go'):
                p.tag_delete(t)
        if doc is None:
            p.insert('end', self.errors_of_load.get(self.cur, 'Pick a sheet on the left.'), 'errline')
            p.configure(state='disabled')
            return
        changes = doc.diff()
        p.insert('end', f'Pending changes ({len(changes)})\n', 'h')
        if not changes:
            p.insert('end', 'Nothing changed yet. Double-click a cell to edit it.\n', 'muted')
        for n, c in enumerate(changes[:300]):
            p.insert('end', f'{c.where}\n', 'where')
            p.insert('end', f'{c.label}\n', 'field')
            if c.op == 'set':
                p.insert('end', c.old_text or '(blank)', 'old')
                p.insert('end', '  →  ', 'arrow')
                p.insert('end', c.new_text or '(blank)', 'new')
            elif c.op == 'add':
                p.insert('end', '+ ' + (c.new_text or 'added'), 'new')
            else:
                p.insert('end', '- ' + (c.old_text or 'removed'), 'old')
            tag = f'rv{n}'
            p.insert('end', '   ')
            p.insert('end', 'revert', ('link', tag))
            p.insert('end', '\n')
            p.tag_bind(tag, '<Button-1>', lambda _e, ch=c: self._revert(ch))
            p.tag_bind(tag, '<Enter>', lambda _e: p.configure(cursor='hand2'))
            p.tag_bind(tag, '<Leave>', lambda _e: p.configure(cursor='arrow'))
        if len(changes) > 300:
            p.insert('end', f'... and {len(changes) - 300} more (all are saved and listed in the history)\n', 'muted')
        p.insert('end', '\nChecks before save\n', 'h')
        for level, text in rep.checks:
            img = {'ok': 'ok', 'warn': 'warn', 'error': 'error', 'info': 'info'}[level]
            p.image_create('end', image=self.icons[img], padx=2)
            p.insert('end', ' ' + text + '\n', {'ok': 'ok', 'warn': 'warnline', 'error': 'errline', 'info': 'infoline'}[level])
        shown = 0
        for i in rep.issues:
            if i.level not in ('error', 'warn') or i.code in ('budget',):
                continue
            shown += 1
            if shown > 40:
                break
            img = 'error' if i.level == 'error' else 'warn'
            p.image_create('end', image=self.icons[img], padx=2)
            tag = f'go{shown}'
            p.insert('end', ' ' + (i.message.rstrip('.') + ' (blocks saving)' if i.level == 'error' else i.message) + '\n', ('errline' if i.level == 'error' else 'warnline', tag))
            if i.area == 'rows' and i.target is not None:
                p.tag_bind(tag, '<Button-1>', lambda _e, u=i.target: self.goto_row(u))
                p.tag_bind(tag, '<Enter>', lambda _e: p.configure(cursor='hand2'))
                p.tag_bind(tag, '<Leave>', lambda _e: p.configure(cursor='arrow'))
            elif i.area in ('notes', 'info', 'limits', 'issues'):
                p.tag_bind(tag, '<Button-1>', lambda _e, a=i.area: self.nb.select({'notes': self.tab_notes, 'info': self.tab_info, 'limits': self.tab_limits, 'issues': self.tab_issues}[a]))
        for i in rep.issues:
            if i.code == 'budget':
                p.image_create('end', image=self.icons['warn'], padx=2)
                p.insert('end', ' ' + i.message + '\n', 'warnline')
        listed = se.procedures_listing(doc.name)
        if doc.change_count():
            p.image_create('end', image=self.icons['warn' if listed else 'info'], padx=2)
            if listed:
                p.insert('end', ' Procedures that list this file in their fingerprint will show "Changed since verification": ' + ', '.join(listed) + '. Only you mark them verified again.\n', 'warnline')
            else:
                p.insert('end', ' Verified status: no procedure fingerprint lists this file, so no procedure flips to "Changed since verification" from saving it. Only you mark a procedure verified.\n', 'infoline')
            for level, text in eio.database_notes(doc, self.db_path):
                p.image_create('end', image=self.icons['warn' if level == 'warn' else 'info'], padx=2)
                p.insert('end', ' ' + text + '\n', 'warnline' if level == 'warn' else 'infoline')
        p.insert('end', '\nA reason, your name and the source are required before the edit can be saved.\n', 'muted')
        p.configure(state='disabled')

    def pending_text(self):
        return self.pending.get('1.0', 'end-1c')

    def goto_row(self, range_uid):
        self.nb.select(self.tab_rows)
        for ln in self.doc.lines():
            if self.doc.uid(ln.rng) == range_uid:
                self.grid_rows.tree.selection_set(ln.iid)
                self.grid_rows.tree.focus(ln.iid)
                self.grid_rows.tree.see(ln.iid)
                return

    # ---- actions
    def _revert(self, change):
        try:
            self.doc.revert(change)
        except se.EditError as e:
            self.say(str(e), 'error')
        self.refresh()

    def revert_selected(self):
        ln = self._selected_line()
        g = self.grid_rows
        col = g.selected_col
        if ln is None or not col:
            self.say('Select a cell first.', 'warn')
            return
        n = 0
        cols_keys = {'label': ('label',), 'span': ('amp_lo', 'amp_hi'), 'freq': ('freq_lo', 'freq_hi'), 'res': ('resolution', 'res_src'), 'page': ('page',),
                     'period': ('period',), 'rel': ('rel',), 'fs_rel': ('fs_rel',), 'fs_value': ('fs_value',), 'abs': ('abs',), 'function': ('name',), 'notes': ('notes',)}
        keys = cols_keys.get(col, ())
        ru = self.doc.uid(ln.rng)
        for c in list(self.doc.diff()):
            if c.area != 'rows' or c.op != 'set' or c.key not in keys:
                continue
            if c.node in ('range',) and c.uid == ru or c.node == 'param' and c.range_uid == ru or c.node == 'function' and c.uid == self.doc.uid(ln.fn) or (
                    c.node == 'spec' and ln.spec is not None and c.uid == self.doc.uid(ln.spec)):
                self.doc.revert(c)
                n += 1
        if not n:
            self.say('That cell has not been changed.', 'warn')
        self.refresh()

    def discard_all(self):
        if not self.doc or not self.doc.change_count():
            return
        if not messagebox.askyesno('Discard all changes', f'Throw away the {self.doc.change_count()} pending change(s) of this sheet?', parent=self.win):
            return
        self.doc.discard_all()
        self.refresh()

    def add_row(self):
        ln = self._selected_line()
        if ln is None:
            return
        new = self.doc.add_range_after(ln.rng)
        self.refresh()
        self.goto_row(self.doc.uid(new))
        self.say('A copy of the row was added after it: change its values (the red / amber marks say what is still the same).', 'warn')

    def delete_row(self):
        ln = self._selected_line()
        if ln is None:
            return
        label = ln.rng.get('label', '')
        if not messagebox.askyesno('Delete row', f'Delete the row "{label}" of "{ln.fn.get("name", "")}"?\n\nIt stays in the file until you document and save; the deletion is listed on the right and can be reverted.', parent=self.win):
            return
        self.doc.delete_range(ln.rng)
        self.refresh()

    def add_period(self):
        ln = self._selected_line()
        if ln is None:
            return
        self.doc.add_spec_line(ln.rng)
        self.refresh()
        self.say('A period line was added with an empty period: type it in the PERIOD cell.', 'warn')

    def delete_period(self):
        ln = self._selected_line()
        if ln is None or ln.spec is None:
            return
        try:
            self.doc.delete_spec_line(ln.rng, ln.spec)
        except se.EditError as e:
            self.say(str(e), 'error')
            return
        self.refresh()

    def row_details(self):
        ln = self._selected_line()
        if ln is None:
            return
        DetailsDialog(self, ln)

    def document_and_save(self):
        if not self.doc or not self.doc.change_count():
            return None
        if not self.report.can_save:
            self.say(f'{len(self.report.errors)} error(s) must be fixed first (red rows).', 'error')
            return None
        dlg = SaveDialog(self)
        return dlg

    def saved(self, result):
        self.refresh()
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass

    def open_history(self):
        if not self.doc:
            return None
        if self.history_window is not None and self.history_window.alive():
            self.history_window.win.lift()
            return self.history_window
        self.history_window = HistoryWindow(self.win, self.doc.name, self.doc.model, db_path=self.db_path, spec_dir=self.spec_dir, backup_dir=self.backup_dir, editor=self)
        return self.history_window

    def close(self):
        n = self._unsaved()
        if n and not messagebox.askyesno('Close the editor', f'{n} change(s) have not been saved and will be lost.\n\nClose anyway?', parent=self.win):
            return False
        for g in (self.grid_rows, self.grid_notes, self.grid_info, self.grid_limits, self.grid_issues):
            g._close_entry(commit=False)
        if self.history_window is not None and self.history_window.alive():
            self.history_window.win.destroy()
        self.win.destroy()
        return True


# ------------------------------------------------------------------------------------------------------------ row details
class DetailsDialog:
    """Every field of one row (range, its period lines, its value-range blocks, its function) as typed text; applied through the same checks as a cell."""

    def __init__(self, editor: EditorWindow, line):
        self.ed, self.doc = editor, editor.doc
        self.line = line
        self.win = ui.dialog(editor.win, f'Row details: {line.rng.get("label", "")}', modal=True)
        ui.fit_window(self.win, 760, 640, min_w=560, min_h=400)
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)
        cv = tk.Canvas(self.win, background=ui.C['bg'], highlightthickness=0)
        sb = ttk.Scrollbar(self.win, orient='vertical', command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        cv.grid(row=0, column=0, sticky='nsew')
        sb.grid(row=0, column=1, sticky='ns')
        self.body = ttk.Frame(cv, padding=ui.px(12))
        win_id = cv.create_window(0, 0, window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda _e: cv.configure(scrollregion=cv.bbox('all')))
        cv.bind('<Configure>', lambda e: cv.itemconfigure(win_id, width=e.width))
        self.body.columnconfigure(1, weight=1)
        self.fields = []        # (node, key, StringVar, original text, error label)
        self.row = 0
        self._section('Function (shared by every row of it)')
        self._node_fields(line.fn, se.FUNCTION_FIELDS)
        self._section('Row')
        self._node_fields(line.rng, se.RANGE_FIELDS, optional=se.OPTIONAL_RANGE_KEYS)
        for i, p in enumerate([x for x in line.rng.get('params') or [] if isinstance(x, dict)], 1):
            self._section(f'Value range {i} (the raw parse of the printed range; its note references are what the application uses)')
            self._node_fields(p, se.PARAM_FIELDS)
        for s in [x for x in line.rng.get('specs') or [] if isinstance(x, dict)]:
            self._section(f'Period line "{s.get("period", "")}"')
            self._node_fields(s, se.SPEC_FIELDS)
        bar = ttk.Frame(self.win)
        bar.grid(row=1, column=0, columnspan=2, sticky='ew', padx=ui.px(12), pady=ui.px(10))
        self.error = tk.Label(bar, text='', foreground=ui.C['bad'], font=editor.fonts['small'], anchor='w')
        self.error.pack(side='left', fill='x', expand=True)
        ttk.Button(bar, text='Close', command=self.win.destroy).pack(side='right')
        ttk.Button(bar, text='Apply', style='Accent.TButton', command=self.apply).pack(side='right', padx=(0, ui.px(8)))

    def _section(self, text):
        tk.Label(self.body, text=text, font=self.ed.fonts['bold'], foreground=ui.C['text'], background=ui.C['bg'], anchor='w').grid(row=self.row, column=0, columnspan=3, sticky='ew', pady=(ui.px(10), ui.px(2)))
        self.row += 1

    def _text(self, node, key, typ, unit):
        v = node.get(key)
        if v is None:
            return ''
        if typ in ('ratio',):
            return se.fmt_ratio(v)
        if typ in ('qty?', 'sqty', 'pqty?'):
            return se.fmt_quantity(v, unit)
        if typ == 'hz?':
            return se.fmt_quantity(v, 'Hz')
        if typ == 'json':
            return json.dumps(v, ensure_ascii=False)
        if typ == 'ints':
            return ', '.join(str(x) for x in v)
        if typ == 'bool':
            return 'true' if v else 'false'
        return str(v)

    def _node_fields(self, node, table, optional=()):
        unit = node.get('unit') or ''
        if table is se.SPEC_FIELDS:
            unit = node.get('unit') or self.line.rng.get('unit') or ''
        for key, typ in table.items():
            if key not in node and key not in optional and key not in ('page',):
                continue
            var = tk.StringVar(value=self._text(node, key, typ, unit))
            tk.Label(self.body, text=se.KEY_LABEL.get(key, key), background=ui.C['bg'], foreground=ui.C['muted'], font=self.ed.fonts['small'], anchor='w').grid(row=self.row, column=0, sticky='w', padx=(0, ui.px(10)))
            ent = ttk.Entry(self.body, textvariable=var)
            ent.grid(row=self.row, column=1, sticky='ew', pady=1)
            err = tk.Label(self.body, text='', foreground=ui.C['bad'], background=ui.C['bg'], font=self.ed.fonts['small'], anchor='w')
            err.grid(row=self.row, column=2, sticky='w', padx=(ui.px(8), 0))
            self.fields.append((node, key, var, var.get(), err))
            self.row += 1

    def apply(self):
        bad = 0
        for node, key, var, orig, err in self.fields:
            err.configure(text='')
            if var.get() == orig:
                continue
            try:
                self.doc.edit_field(node, key, var.get())
            except se.EditError as e:
                err.configure(text=str(e))
                bad += 1
        self.error.configure(text=f'{bad} field(s) not applied (see the red text).' if bad else '')
        self.ed.refresh()
        if not bad:
            self.win.destroy()
        return not bad


# ------------------------------------------------------------------------------------------------------------ document & save
def _diff_preview(text_widget, changes, fonts, limit=200):
    C = ui.C
    t = text_widget
    t.configure(state='normal')
    t.delete('1.0', 'end')
    t.tag_configure('where', foreground=C['muted'])
    t.tag_configure('del', foreground=C['bad'])
    t.tag_configure('add', foreground=C['good'])
    for c in changes[:limit]:
        t.insert('end', f'{c.where if hasattr(c, "where") else c.get("where", "")}\n', 'where')
        label = c.label if hasattr(c, 'label') else c.get('field', '')
        op = c.op if hasattr(c, 'op') else c.get('op')
        old = c.old_text if hasattr(c, 'old_text') else c.get('old_text', '')
        new = c.new_text if hasattr(c, 'new_text') else c.get('new_text', '')
        if op == 'set':
            t.insert('end', f'- {label}: {old or "(blank)"}\n', 'del')
            t.insert('end', f'+ {label}: {new or "(blank)"}\n', 'add')
        elif op == 'add':
            t.insert('end', f'+ {label}: {new}\n', 'add')
        else:
            t.insert('end', f'- {label}: {old}\n', 'del')
    if len(changes) > limit:
        t.insert('end', f'... and {len(changes) - limit} more changes (all are saved and listed in the history)\n', 'where')
    if not changes:
        t.insert('end', '(no changes)\n', 'where')
    t.configure(state='disabled')


class SaveDialog:
    """'Document this edit': reason, source and name are required; a diff preview; backup and rebuild options."""

    def __init__(self, editor: EditorWindow):
        self.ed, self.doc = editor, editor.doc
        C, f = ui.C, editor.fonts
        self.win = ui.dialog(editor.win, 'Document this edit', modal=True)
        w = self.win
        w.columnconfigure(0, weight=1)
        w.rowconfigure(2, weight=1)
        n = self.doc.change_count()
        tk.Label(w, text='Document this edit', font=f['title'], foreground=C['text'], background=C['bg'], anchor='w').grid(row=0, column=0, sticky='ew', padx=ui.px(20), pady=(ui.px(16), 0))
        sub = tk.Label(w, text=f'{self.doc.model or self.doc.name}  ·  {self.doc.summary()}. This is saved with the log and printed in the edit history.', font=f['normal'],
                       foreground=C['muted'], background=C['bg'], anchor='w', justify='left')
        sub.grid(row=1, column=0, sticky='ew', padx=ui.px(20))
        sub.bind('<Configure>', lambda e: sub.configure(wraplength=max(200, e.width - 10)))
        self.preview = tk.Text(w, height=9, wrap='none', background=C['table'], foreground=C['text'], font=f['mono'], relief='flat', borderwidth=0, highlightthickness=1,
                               highlightbackground=C['border'], padx=10, pady=8)
        self.preview.grid(row=2, column=0, sticky='nsew', padx=ui.px(20), pady=(ui.px(10), 0))
        _diff_preview(self.preview, self.doc.diff(), f)
        form = ttk.Frame(w)
        form.grid(row=3, column=0, sticky='ew', padx=ui.px(20), pady=(ui.px(10), 0))
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=0)
        tk.Label(form, text='Reason for the change *', font=f['bold'], foreground=C['text'], background=C['bg']).grid(row=0, column=0, sticky='w')
        self.reason = tk.Text(form, height=3, wrap='word', background=C['field'], foreground=C['text'], insertbackground=C['text'], relief='flat', highlightthickness=1,
                              highlightbackground=C['border_strong'], highlightcolor=C['primary'], padx=8, pady=6, font=f['normal'])
        self.reason.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(2, ui.px(8)))
        tk.Label(form, text='Source / reference *', font=f['bold'], foreground=C['text'], background=C['bg']).grid(row=2, column=0, sticky='w')
        tk.Label(form, text='Edited by *', font=f['bold'], foreground=C['text'], background=C['bg']).grid(row=2, column=1, sticky='w', padx=(ui.px(12), 0))
        self.source_var = tk.StringVar()
        self.who_var = tk.StringVar(value=elog.last_editor(editor.db_path) or self._login())
        self.source = ttk.Entry(form, textvariable=self.source_var)
        self.source.grid(row=3, column=0, sticky='ew', pady=(2, 0))
        self.who = ttk.Entry(form, textvariable=self.who_var, width=22)
        self.who.grid(row=3, column=1, sticky='ew', padx=(ui.px(12), 0), pady=(2, 0))
        opts = ttk.Frame(w)
        opts.grid(row=4, column=0, sticky='ew', padx=ui.px(20), pady=(ui.px(10), 0))
        backup_name = eio.next_backup(self.doc.name, editor.backup_dir).name
        self.backup_var = tk.BooleanVar(value=True)
        self.rebuild_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text=f'Save a backup of the previous spec file ({backup_name})', variable=self.backup_var).pack(anchor='w')
        self.rebuild_cb = ttk.Checkbutton(opts, text='Rebuild the standards sheet from the edited spec (keeps assets, divisor and Standards Specs edits)',
                                          variable=self.rebuild_var)
        self.rebuild_cb.pack(anchor='w', pady=(4, 0))
        notes = []
        listed = se.procedures_listing(self.doc.name)
        if listed:
            notes.append('Procedures that list this file in their fingerprint will show "Changed since verification": ' + ', '.join(listed) + '. Only you mark them verified again.')
        else:
            notes.append('Procedures that use this standard: no procedure fingerprint lists this file, so none flips to "Changed since verification" from this save. Only you mark a procedure verified.')
        builders = se.builders_for(self.doc.name)
        if builders:
            notes.append('Running ' + ', '.join(n for n, _ in builders) + ' again will overwrite this edit (the builder rewrites the whole file). The history marks the sheet as edited by hand.')
        for level, text in eio.database_notes(self.doc, editor.db_path):
            notes.append(text)
        ui.Notice(w, ' '.join(notes), kind='warn').grid(row=5, column=0, sticky='ew', padx=ui.px(20), pady=(ui.px(10), 0))
        self.error_var = tk.StringVar()
        self.error = tk.Label(w, textvariable=self.error_var, foreground=C['bad'], background=C['bg'], font=f['normal'], anchor='w', justify='left')
        self.error.grid(row=6, column=0, sticky='ew', padx=ui.px(20), pady=(ui.px(6), 0))
        self.error.bind('<Configure>', lambda e: self.error.configure(wraplength=max(200, e.width - 10)))
        bar = ttk.Frame(w)
        bar.grid(row=7, column=0, sticky='ew', padx=ui.px(20), pady=ui.px(14))
        ttk.Button(bar, text='Cancel', command=self.win.destroy).pack(side='right')
        self.save_btn = ttk.Button(bar, text='Save edit', style='Accent.TButton', command=self.save)
        self.save_btn.pack(side='right', padx=(0, ui.px(8)))
        ui.fit_window(w, 700, 700, min_w=620, min_h=560)
        self.reason.focus_set()
        self.result = None

    @staticmethod
    def _login():
        import verified
        return verified.default_who()

    def save(self):
        reason = self.reason.get('1.0', 'end-1c').strip()
        source, who = self.source_var.get().strip(), self.who_var.get().strip()
        missing = [n for n, v in (('a reason', reason), ('a source / reference', source), ('your name', who)) if not v]
        if missing:
            self.error_var.set('Cannot save yet: ' + ', '.join(missing) + (' is required.' if len(missing) == 1 else ' are required.'))
            (self.reason if not reason else (self.source if not source else self.who)).focus_set()
            return None
        self.error_var.set('')
        self.save_btn.state(['disabled'])
        try:
            res = eio.save_edit(self.doc, edited_by=who, reason=reason, source=source, backup=self.backup_var.get(), rebuild=self.rebuild_var.get(),
                                db_path=self.ed.db_path, backup_dir=self.ed.backup_dir)
        except eio.SaveError as e:
            self.win.destroy()
            messagebox.showerror('Edit not saved', str(e) + ('' if e.file_changed else '\n\nNothing was written; the pending changes are still in the editor.'), parent=self.ed.win)
            self.ed.refresh()
            return None
        self.result = res
        self.win.destroy()
        messagebox.showinfo('Edit saved', '\n\n'.join(res.messages), parent=self.ed.win)
        self.ed.saved(res)
        return res


# ------------------------------------------------------------------------------------------------------------ history
class HistoryWindow:
    def __init__(self, parent, spec_file, model, db_path=None, spec_dir=None, backup_dir=None, editor=None):
        self.spec_file, self.model, self.db_path, self.spec_dir, self.backup_dir, self.editor = spec_file, model, db_path, spec_dir, backup_dir, editor
        C, f = ui.C, _fonts()
        self.fonts = f
        self.win = ui.dialog(parent, 'Edit history', modal=False)
        self.win.transient(None)
        w = self.win
        w.columnconfigure(0, weight=1)
        w.rowconfigure(1, weight=1)
        head = tk.Frame(w, background=C['card'])
        head.grid(row=0, column=0, sticky='ew')
        tk.Label(head, text='Edit history', font=f['title'], foreground=C['text'], background=C['card']).pack(side='left', padx=ui.px(16), pady=ui.px(10))
        self.head_label = tk.Label(head, text='', font=f['normal'], foreground=C['muted'], background=C['card'])
        self.head_label.pack(side='left')
        ttk.Button(head, text='Back to editor', command=self.win.destroy).pack(side='right', padx=ui.px(12))
        self.export_btn = ttk.Button(head, text='Export history (PDF)' if eio.pdf_available() else 'Export history (CSV)', command=self.export)
        self.export_btn.pack(side='right', padx=ui.px(4))
        body = tk.Frame(w, background=C['bg'])
        body.grid(row=1, column=0, sticky='nsew')
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        left = tk.Frame(body, background=C['card'], width=ui.px(430))
        left.grid(row=0, column=0, sticky='ns')
        left.grid_propagate(False)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=('when', 'who', 'reason'), show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='EDIT')
        self.tree.heading('when', text='WHEN')
        self.tree.heading('who', text='BY')
        self.tree.heading('reason', text='REASON')
        self.tree.column('#0', width=ui.px(66), stretch=False)
        self.tree.column('when', width=ui.px(112), stretch=False)
        self.tree.column('who', width=ui.px(70), stretch=False)
        self.tree.column('reason', width=ui.px(160), stretch=True)
        self.tree.grid(row=0, column=0, sticky='nsew')
        ys = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        ys.grid(row=0, column=1, sticky='ns')
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self.show())
        right = tk.Frame(body, background=C['bg'])
        right.grid(row=0, column=1, sticky='nsew')
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        self.title = tk.Label(right, text='', font=f['h2'], foreground=C['text'], background=C['bg'], anchor='w')
        self.title.grid(row=0, column=0, sticky='ew', padx=ui.px(16), pady=(ui.px(12), ui.px(4)))
        self.detail = tk.Text(right, wrap='word', background=C['bg'], foreground=C['text'], relief='flat', borderwidth=0, highlightthickness=0, padx=ui.px(16), pady=ui.px(4), font=f['normal'])
        self.detail.grid(row=1, column=0, sticky='nsew')
        self.detail.tag_configure('key', foreground=C['muted'], font=f['small'])
        self.detail.tag_configure('mono', font=f['mono'])
        self.detail.tag_configure('h', font=f['bold'], spacing1=10)
        self.detail.tag_configure('where', foreground=C['muted'], font=f['mono'])
        self.detail.tag_configure('del', foreground=C['bad'], font=f['mono'])
        self.detail.tag_configure('add', foreground=C['good'], font=f['mono'])
        self.detail.tag_configure('warn', foreground=C['warn'])
        self.detail.configure(state='disabled')
        bar = ttk.Frame(right)
        bar.grid(row=2, column=0, sticky='ew', padx=ui.px(16), pady=ui.px(8))
        self.compare_btn = ttk.Button(bar, text='Compare with current file', command=self.compare)
        self.compare_btn.pack(side='left', padx=(0, ui.px(8)))
        self.restore_btn = ttk.Button(bar, text='Restore the file as it was before this edit...', command=self.restore)
        self.restore_btn.pack(side='left')
        self.note = tk.Label(right, text='Restoring is itself a documented edit: it asks for a reason and adds a new entry. Entries are never removed or rewritten. '
                                         'Running a builder script again overwrites hand edits; the state line above says whether that has happened.',
                             font=f['small'], foreground=C['muted'], background=C['bg'], anchor='w', justify='left')
        self.note.grid(row=3, column=0, sticky='ew', padx=ui.px(16), pady=(0, ui.px(10)))
        self.note.bind('<Configure>', lambda e: self.note.configure(wraplength=max(200, e.width - 20)))
        ui.fit_window(w, 1100, 640, min_w=900, min_h=480)
        self.entries = []
        self.reload()

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    @property
    def path(self):
        from pathlib import Path
        return Path(self.spec_dir or se.STANDARDS_DIR) / self.spec_file

    def state(self):
        return eio.sheet_state(self.path, self.db_path)

    def reload(self):
        self.entries = elog.entries(self.spec_file, self.db_path)
        self.tree.delete(*self.tree.get_children())
        for e in self.entries:
            kind = 'Restore' if e['kind'] == 'restore' else 'Edit'
            self.tree.insert('', 'end', iid=str(e['id']), text=f'{kind} {e["id"]}', values=(e['at'].replace('T', ' ')[:16], e['edited_by'], e['reason'].replace('\n', ' ')))
        st = self.state()
        self.head_label.configure(text=f'{self.model or self.spec_file}  ·  {len(self.entries)} documented edit{"s" if len(self.entries) != 1 else ""}')
        self.state_text = eio.state_text(st)
        if self.entries:
            self.tree.selection_set(str(self.entries[0]['id']))
        else:
            self.show()

    def selected(self):
        sel = self.tree.selection()
        return elog.entry(int(sel[0]), self.db_path) if sel else None

    def show(self):
        e = self.selected()
        d = self.detail
        d.configure(state='normal')
        d.delete('1.0', 'end')
        st = self.state()
        d.insert('end', eio.state_text(st) + '\n', 'warn' if st['state'] in ('edited by hand', 'changed outside') else 'key')
        if e is None:
            self.title.configure(text='No documented edits yet')
            d.insert('end', '\nThis sheet has not been edited with the editor.', 'key')
            d.configure(state='disabled')
            self.compare_btn.state(['disabled'])
            self.restore_btn.state(['disabled'])
            return
        self.title.configure(text=f'{"Restore" if e["kind"] == "restore" else "Edit"} {e["id"]}  ·  {e["at"].replace("T", " ")}')
        for key, val, mono in (('Edited by', e['edited_by'], False), ('Reason', e['reason'], False), ('Source', e['source'], False),
                               ('Kind', e['kind'] + (f' (put the file back as it was before edit {e["restored_from"]})' if e['restored_from'] else ''), False),
                               ('Backup file', e['backup_file'] or '(none made)', True), ('SHA-256 before', e['sha_before'], True), ('SHA-256 after', e['sha_after'], True),
                               ('Summary', e['summary'], False)):
            d.insert('end', f'\n{key}: ', 'key')
            d.insert('end', val, 'mono' if mono else ())
        for ev in elog.events(e['id'], self.db_path):
            d.insert('end', f'\n{ev["event"]}: ', 'key')
            d.insert('end', ev['detail'])
        d.insert('end', '\n\nChanges\n', 'h')
        for c in e['diff'][:400]:
            d.insert('end', c.get('where', '') + '\n', 'where')
            if c.get('op') == 'set':
                d.insert('end', f'- {c.get("field", "")}: {c.get("old_text", "") or "(blank)"}\n', 'del')
                d.insert('end', f'+ {c.get("field", "")}: {c.get("new_text", "") or "(blank)"}\n', 'add')
            elif c.get('op') == 'add':
                d.insert('end', f'+ {c.get("field", "")}: {c.get("new_text", "")}\n', 'add')
            else:
                d.insert('end', f'- {c.get("field", "")}: {c.get("old_text", "")}\n', 'del')
        if len(e['diff']) > 400:
            d.insert('end', f'... and {len(e["diff"]) - 400} more\n', 'key')
        d.configure(state='disabled')
        self.compare_btn.state(['!disabled'])
        self.restore_btn.state(['!disabled'] if elog.before_bytes(e['id'], self.db_path) else ['disabled'])

    def compare(self):
        """The file as it was before the selected edit against the file now: everything that changed since (and including) that edit."""
        e = self.selected()
        if e is None:
            return None
        before = elog.before_bytes(e['id'], self.db_path)
        if before is None:
            messagebox.showwarning('Compare', 'The earlier file is not stored for this edit.', parent=self.win)
            return None
        try:
            now = self.path.read_bytes()
            changes = se.compare_data(json.loads(before.decode('utf-8')), json.loads(now.decode('utf-8')))
        except (OSError, ValueError) as ex:
            messagebox.showerror('Compare', f'The current file cannot be read: {ex}', parent=self.win)
            return None
        same = se.sha256_bytes(now) == e['sha_after']
        win = ui.dialog(self.win, f'Compare: before edit {e["id"]} and the current file', modal=False)
        ui.fit_window(win, 880, 560, min_w=600, min_h=360)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        tk.Label(win, text=('The current file is exactly what edit %d wrote.' % e['id'] if same else 'The current file differs from what edit %d wrote (later edits, a restore, or a rebuild by a builder script).' % e['id']) +
                 f'  {len(changes)} difference(s) between the file before edit {e["id"]} and the file now.', font=self.fonts['normal'], background=ui.C['bg'], foreground=ui.C['text'], anchor='w',
                 justify='left', wraplength=ui.px(820)).grid(row=0, column=0, sticky='ew', padx=ui.px(12), pady=ui.px(8))
        t = tk.Text(win, wrap='none', background=ui.C['table'], foreground=ui.C['text'], font=self.fonts['mono'], relief='flat', borderwidth=0, highlightthickness=1,
                    highlightbackground=ui.C['border'], padx=10, pady=8)
        t.grid(row=1, column=0, sticky='nsew', padx=ui.px(12), pady=(0, ui.px(12)))
        _diff_preview(t, changes, self.fonts, limit=1000)
        self.compare_window = win
        return changes

    def restore(self):
        e = self.selected()
        if e is None:
            return None
        dlg = RestoreDialog(self, e)
        return dlg

    def export(self):
        from tkinter import filedialog
        from datetime import datetime
        pdf = eio.pdf_available()
        stem = self.spec_file.rsplit('.', 1)[0]
        dest = filedialog.asksaveasfilename(parent=self.win, defaultextension='.pdf' if pdf else '.csv', initialfile=f'spec_edit_history_{stem}-{datetime.now():%m-%d-%Y}' + ('.pdf' if pdf else '.csv'),
                                            filetypes=[('PDF', '*.pdf')] if pdf else [('CSV', '*.csv')])
        if not dest:
            return None
        try:
            n = eio.export_history_pdf(self.spec_file, dest, self.db_path, self.model, eio.state_text(self.state())) if pdf else eio.export_history_csv(self.spec_file, dest, self.db_path)
        except Exception as ex:                      # reportlab / file problems: say so, nothing else is affected
            messagebox.showerror('Export history', f'The history could not be exported: {ex}', parent=self.win)
            return None
        messagebox.showinfo('Export history', f'{n} edit(s) exported to {dest}.', parent=self.win)
        return dest


class RestoreDialog:
    def __init__(self, hist: HistoryWindow, entry):
        self.hist, self.entry = hist, entry
        C, f = ui.C, hist.fonts
        self.win = ui.dialog(hist.win, 'Restore the file', modal=True)
        w = self.win
        w.columnconfigure(0, weight=1)
        tk.Label(w, text=f'Restore the file as it was before edit {entry["id"]}', font=f['title'], foreground=C['text'], background=C['bg'], anchor='w').grid(row=0, column=0, sticky='ew', padx=ui.px(20), pady=(ui.px(16), 0))
        msg = tk.Label(w, text='The sheet file is replaced by the earlier version (SHA-256 %s...). This is a new documented edit; the log keeps every entry, including this one.' % entry['sha_before'][:12],
                       font=f['normal'], foreground=C['muted'], background=C['bg'], anchor='w', justify='left', wraplength=ui.px(560))
        msg.grid(row=1, column=0, sticky='ew', padx=ui.px(20), pady=(2, ui.px(8)))
        tk.Label(w, text='Reason *', font=f['bold'], foreground=C['text'], background=C['bg']).grid(row=2, column=0, sticky='w', padx=ui.px(20))
        self.reason = tk.Text(w, height=3, wrap='word', background=C['field'], foreground=C['text'], insertbackground=C['text'], relief='flat', highlightthickness=1,
                              highlightbackground=C['border_strong'], highlightcolor=C['primary'], padx=8, pady=6, font=f['normal'])
        self.reason.grid(row=3, column=0, sticky='ew', padx=ui.px(20), pady=(2, ui.px(8)))
        row = ttk.Frame(w)
        row.grid(row=4, column=0, sticky='ew', padx=ui.px(20))
        row.columnconfigure(0, weight=1)
        tk.Label(row, text='Source / reference *', font=f['bold'], foreground=C['text'], background=C['bg']).grid(row=0, column=0, sticky='w')
        tk.Label(row, text='Edited by *', font=f['bold'], foreground=C['text'], background=C['bg']).grid(row=0, column=1, sticky='w', padx=(ui.px(12), 0))
        self.source_var = tk.StringVar(value=f'{eio.RESTORE_SOURCE} {entry["id"]}')
        self.who_var = tk.StringVar(value=elog.last_editor(hist.db_path) or SaveDialog._login())
        ttk.Entry(row, textvariable=self.source_var).grid(row=1, column=0, sticky='ew')
        ttk.Entry(row, textvariable=self.who_var, width=22).grid(row=1, column=1, padx=(ui.px(12), 0))
        self.backup_var, self.rebuild_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        ttk.Checkbutton(w, text='Save a backup of the file as it is now', variable=self.backup_var).grid(row=5, column=0, sticky='w', padx=ui.px(20), pady=(ui.px(10), 0))
        ttk.Checkbutton(w, text='Rebuild the standards sheet in the database from the restored file', variable=self.rebuild_var).grid(row=6, column=0, sticky='w', padx=ui.px(20))
        self.error_var = tk.StringVar()
        tk.Label(w, textvariable=self.error_var, foreground=C['bad'], background=C['bg'], anchor='w', justify='left', wraplength=ui.px(560)).grid(row=7, column=0, sticky='ew', padx=ui.px(20), pady=(6, 0))
        bar = ttk.Frame(w)
        bar.grid(row=8, column=0, sticky='ew', padx=ui.px(20), pady=ui.px(14))
        ttk.Button(bar, text='Cancel', command=self.win.destroy).pack(side='right')
        ttk.Button(bar, text='Restore', style='Accent.TButton', command=self.restore).pack(side='right', padx=(0, ui.px(8)))
        ui.fit_window(w, 640, 480, min_w=560, min_h=400)
        self.reason.focus_set()
        self.result = None

    def restore(self):
        reason, source, who = self.reason.get('1.0', 'end-1c').strip(), self.source_var.get().strip(), self.who_var.get().strip()
        missing = [n for n, v in (('a reason', reason), ('a source / reference', source), ('your name', who)) if not v]
        if missing:
            self.error_var.set('Cannot restore yet: ' + ', '.join(missing) + (' is required.' if len(missing) == 1 else ' are required.'))
            return None
        try:
            res = eio.restore_edit(self.entry['id'], spec_dir=self.hist.spec_dir, edited_by=who, reason=reason, source=source, backup=self.backup_var.get(), rebuild=self.rebuild_var.get(),
                                   db_path=self.hist.db_path, backup_dir=self.hist.backup_dir)
        except eio.SaveError as e:
            self.win.destroy()
            messagebox.showerror('Not restored', str(e), parent=self.hist.win)
            return None
        self.result = res
        self.win.destroy()
        messagebox.showinfo('Restored', '\n\n'.join(res.messages), parent=self.hist.win)
        self.hist.reload()
        ed = self.hist.editor
        if ed is not None:
            d = ed.docs.get(self.hist.spec_file)
            if d is not None:
                try:
                    d.rebase(d.path.read_bytes())
                except (OSError, ValueError):
                    ed.docs.pop(self.hist.spec_file, None)
            ed.refresh()
            ed.saved(res)
        return res


_OPEN = {}


def open_editor(parent, model=None, on_saved=None, spec_dir=None, db_path=None, backup_dir=None):
    """Open (or raise) the editor on the sheet of `model`."""
    ed = _OPEN.get(id(parent))
    if ed is not None:
        try:
            if ed.win.winfo_exists():
                ed.win.lift()
                if model:
                    f = se.sheet_for_model(model, ed.spec_dir)
                    if f:
                        ed.select_sheet(f.name)
                return ed
        except tk.TclError:
            pass
    ed = EditorWindow(parent, model, on_saved=on_saved, spec_dir=spec_dir, db_path=db_path, backup_dir=backup_dir)
    _OPEN[id(parent)] = ed
    return ed
