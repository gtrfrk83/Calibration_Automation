"""The redesigned test-window shell ("Mission Control" layout), shared by the verification procedures.

    +---------------------------------------------------------------------------------------+
    | title / subtitle                              [DEMO] [Connected]        [Connections] |   header
    | Instrument ID [      ] Serial [      ]  Collecting [As Found|As Left]   x of y  ====   |   strip
    +----------+----------------------------------------------------------------------------+
    | Sections |  table (full width)                                                        |   body
    | * Volts  |                                                         +-----------------+|
    | * Ohms   |                                                         | Connections &   ||   drawer (slides in)
    +----------+--------------------------------------------------------------------- ------+
    | [Run All Pending] [Run Shown Section] [Rerun] [Stop]            [Save][Load][Export]  |   action bar
    | status message                                                              v70 Beta 2|   status bar
    +---------------------------------------------------------------------------------------+

Below ~1100 px wide the sidebar folds into a Section drop-down and the strip tightens, so the window still works at 900 x 700.
Nothing here talks to an instrument: it only arranges widgets the procedure creates and gives the procedure somewhere to put them.

Typical use (see Procedures/Fluke_8846A_Verification.py):

    shell = ui_shell.Shell(root, 'Fluke 8846A', 'subtitle', demo=self.demo, on_section=self.pick_section)
    shell.build_identity(self.asset, self.serial)               # ID / serial entries
    self.build_mode_segment(shell.strip)                        # As Found | As Left   (datamode)
    shell.build_progress()                                      # x of y tested + bar + pills       -> shell.summary
    ... create the connection widgets inside shell.drawer_body ...
    shell.content                                               # the frame for the table
    shell.add_action('Run All Pending', cmd, accent=True)       # left of the action bar;   side='right' for file actions
    shell.set_sections([(name, passed, failed, total), ...])    # sidebar rows with status dots and counts
    shell.set_verified('VERIFIED ON HARDWARE - LOCKED') # green chip while the procedure is locked (verified.py)
    shell.set_modified(3) / shell.set_devmode(True)             # amber 'MODIFIED (3)' / 'DEVELOPER MODE' header chips (procmods_ui.attach_to_shell calls these)
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_theme as ui

COMPACT_BELOW = 1100            # window width (96-dpi px) under which the sidebar folds into a drop-down


def segment_styles(root):
    """ttk styles for the As Found | As Left switch (call after ui.apply_theme)."""
    s = ttk.Style(root)
    C = ui.C
    on_amber = C['bg'] if ui.is_dark() else '#FFFFFF'
    for name, fill, fg in (('Seg', C['primary'], C['on_primary']), ('SegLeft', C['warn'], on_amber)):
        s.configure(f'{name}.Toolbutton', background=C['field'], foreground=C['muted'], padding=(ui.px(14), ui.px(5)), relief='flat',
                    borderwidth=0, focusthickness=0, focuscolor=C['field'], anchor='center')
        s.map(f'{name}.Toolbutton', background=[('selected', fill), ('disabled', C['field']), ('active', C['head_hi'])],
              foreground=[('selected', fg), ('disabled', C['faint'])])


class ProgressPanel(ttk.Frame):
    """Progress ring + headline + badges.  Same update_counts() as ui.Summary, plus set_rerun() for As Left runs:

        As Found:  (81/135 tested)   81 of 135 tested     [58 pass] [23 fail] [54 remaining]
        As Left:   (  1/1  re-run)   1 of 1 re-run done   [1 now in limits] [0 still out]
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.size = ui.px(68)
        self.canvas = tk.Canvas(self, width=self.size, height=self.size, background=ui.C['bg'], highlightthickness=0, borderwidth=0)
        self.canvas.pack(side='left', padx=(0, 12))
        col = ttk.Frame(self)
        col.pack(side='left', fill='x', expand=True)
        self.text = tk.StringVar(value='Nothing tested yet')
        ttk.Label(col, textvariable=self.text, style='Bold.TLabel').pack(anchor='w')
        self.badges = ttk.Frame(col)
        self.badges.pack(anchor='w', pady=(4, 0))
        self.ok = ui.Pill(self.badges, '0 pass', 'neutral')
        self.fail = ui.Pill(self.badges, '0 fail', 'neutral')
        self.rem = ui.Pill(self.badges, '0 remaining', 'neutral')
        for pill in (self.ok, self.fail, self.rem):
            pill.pack(side='left', padx=(0, 6))
        self._draw(0, 1, '0/0', 'tested', ui.C['primary'])

    def _draw(self, done, total, big, small, color):
        c = self.canvas
        c.delete('all')
        c.configure(background=ui.C['bg'])
        w = ui.px(6)
        box = (w, w, self.size - w, self.size - w)
        c.create_oval(*box, outline=ui.C['border_strong'], width=w)
        frac = (done / total) if total else 0
        if frac >= 0.999:
            c.create_oval(*box, outline=color, width=w)
        elif frac > 0:
            c.create_arc(*box, start=90, extent=-360 * frac, style='arc', outline=color, width=w)
        mid = self.size / 2
        c.create_text(mid, mid - ui.px(5), text=big, fill=ui.C['text'], font=('TkDefaultFont', max(8, int(ui.SCALE * 11)), 'bold'))
        c.create_text(mid, mid + ui.px(10), text=small, fill=ui.C['muted'], font=('TkDefaultFont', max(6, int(ui.SCALE * 7))))

    def update_counts(self, total, passed, failed):
        done = passed + failed
        left = total - done
        self.text.set(f'{done} of {total} tested')
        self.ok.set(f'{passed} pass', 'good' if passed else 'neutral')
        self.fail.set(f'{failed} fail', 'bad' if failed else 'neutral')
        self.rem.set('All points tested' if left == 0 and total else f'{left} remaining', 'good' if left == 0 and total and not failed else 'neutral')
        self._draw(done, total, f'{done}/{total}', 'tested', ui.C['bad'] if failed and not left else ui.C['primary'])

    def set_rerun(self, total, done, in_limits, still_out):
        """As Left: the points to re-measure are the ones that failed As Found."""
        self.text.set(f'{done} of {total} re-run done' if total else 'Nothing failed As Found: nothing to re-run')
        self.ok.set(f'{in_limits} now in limits', 'good' if in_limits else 'neutral')
        self.fail.set(f'{still_out} still out', 'bad' if still_out else 'neutral')
        self.rem.set(f'{total - done} to re-run' if total - done else 'All re-run', 'neutral' if total - done else 'good')
        self._draw(done, total, f'{done}/{total}', 're-run', ui.C['warn'])


class Shell:
    def __init__(self, root, title, subtitle='', demo=False, on_section=None, version=''):
        self.root = root
        self.demo = demo
        self.on_section = on_section
        self.sections = []                 # [(name, passed, failed, total)]
        self._action_texts = []
        self.current = 'All sections'
        self._compact = None
        self._rows = {}
        self._drawer_open = False
        segment_styles(root)
        C = ui.C

        # ---- header -----------------------------------------------------------------------------------
        head = ttk.Frame(root, style='Banner.TFrame', padding=(ui.px(20), ui.px(10), ui.px(20), ui.px(8)))
        head.pack(fill='x')
        self.header = head
        right = ttk.Frame(head, style='Banner.TFrame')
        right.pack(side='right', anchor='n')
        self.btn_drawer = ttk.Button(right, text='⚙  Connections', command=self.toggle_drawer)
        self.btn_drawer.pack(side='right', padx=(10, 0))
        self.chip_frame = ttk.Frame(right, style='Banner.TFrame')
        self.chip_frame.pack(side='right')
        left = ttk.Frame(head, style='Banner.TFrame')
        left.pack(side='left', fill='x', expand=True)
        ttk.Label(left, text=title, style='BannerTitle.TLabel').pack(anchor='w')
        self.subtitle = tk.StringVar(value=subtitle)
        self._sub = ttk.Label(left, textvariable=self.subtitle, style='BannerSub.TLabel', justify='left')
        self._sub.pack(anchor='w')
        left.bind('<Configure>', lambda e: self._sub.configure(wraplength=max(ui.px(200), e.width - ui.px(8))), add='+')
        self.mode_chip = self.add_chip('DEMO MODE  -  simulated readings', 'warn') if demo else self.add_chip('HARDWARE MODE', 'info')
        tk.Frame(root, height=1, background=C['border']).pack(fill='x')

        # ---- strip (ID, serial, As Found / As Left, progress) ---------------------------------------------
        self.strip_holder = ttk.Frame(root, padding=(ui.px(20), ui.px(8), ui.px(20), ui.px(4)))
        self.strip_holder.pack(fill='x')
        self.strip = ttk.Frame(self.strip_holder)
        self.strip.pack(fill='x')
        self.notice_holder = ttk.Frame(self.strip_holder)           # As Left / demo / hardware notices
        self.notice_holder.pack(fill='x')
        self.section_picker = None
        self.layout_hook = None            # called with True/False when the window crosses the small-window width

        # ---- bottom bars are packed before the body so they are never squeezed out -------------------------
        self.status_var = tk.StringVar()
        self.statusbar = ui.StatusBar(root, self.status_var, right=version)
        self.statusbar.pack(side='bottom', fill='x')
        self.actions = ttk.Frame(root, padding=(ui.px(20), ui.px(7)))
        self.actions.pack(side='bottom', fill='x')
        tk.Frame(root, height=1, background=C['border']).pack(side='bottom', fill='x')
        self.actions_left = ttk.Frame(self.actions)
        self.actions_right = ttk.Frame(self.actions)
        self.actions_right.pack(side='right')                       # packed first: the file buttons never get pushed off
        self.actions_left.pack(side='left')

        # ---- body: sidebar | content -------------------------------------------------------------------------
        self.body = ttk.Frame(root)
        self.body.pack(fill='both', expand=True)
        self.sidebar = tk.Frame(self.body, background=C['bg'], width=ui.px(224))
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        tk.Frame(self.body, width=1, background=C['border']).pack(side='left', fill='y')
        self._side_title = tk.Label(self.sidebar, text='SECTIONS', background=C['bg'], foreground=C['faint'], anchor='w',
                                    font=('TkDefaultFont', max(7, int(ui.SCALE * 8)), 'bold'))
        self._side_title.pack(fill='x', padx=ui.px(16), pady=(ui.px(14), ui.px(6)))
        self._side_canvas = tk.Canvas(self.sidebar, background=C['bg'], highlightthickness=0, borderwidth=0)
        self._side_canvas.pack(fill='both', expand=True)
        self._side_list = tk.Frame(self._side_canvas, background=C['bg'])               # many sections: the list scrolls
        side_win = self._side_canvas.create_window(0, 0, window=self._side_list, anchor='nw')
        self._side_list.bind('<Configure>', lambda e: self._side_canvas.configure(scrollregion=self._side_canvas.bbox('all')))
        self._side_canvas.bind('<Configure>', lambda e: self._side_canvas.itemconfigure(side_win, width=e.width))
        self._side_canvas.bind('<Enter>', lambda e: self._side_canvas.bind_all('<MouseWheel>', self._side_wheel))
        self._side_canvas.bind('<Leave>', lambda e: self._side_canvas.unbind_all('<MouseWheel>'))
        self.content = ttk.Frame(self.body, padding=(ui.px(16), ui.px(8), ui.px(16), ui.px(8)))
        self.content.pack(side='left', fill='both', expand=True)

        # ---- drawer ----------------------------------------------------------------------------------------
        self.drawer = tk.Frame(self.body, background=C['card'], highlightthickness=1, highlightbackground=C['border_strong'])
        top = tk.Frame(self.drawer, background=C['card'])
        top.pack(fill='x', padx=ui.px(16), pady=(ui.px(12), ui.px(6)))
        tk.Label(top, text='Connections & settings', background=C['card'], foreground=C['text'],
                 font=('TkDefaultFont', max(9, int(ui.SCALE * 11)), 'bold')).pack(side='left')
        tk.Button(top, text='Close', command=self.close_drawer, relief='flat', borderwidth=0, background=C['card'], foreground=C['muted'],
                  activebackground=C['head_hi'], activeforeground=C['text'], cursor='hand2').pack(side='right')
        tk.Frame(self.drawer, height=1, background=C['border']).pack(fill='x')
        self.drawer_footer = ttk.Frame(self.drawer, padding=(ui.px(16), ui.px(10)))         # pinned: Test connections stays in reach however long the form is
        self.drawer_footer.pack(side='bottom', fill='x')
        tk.Frame(self.drawer, height=1, background=C['border']).pack(side='bottom', fill='x')
        holder = tk.Frame(self.drawer, background=C['card'])
        holder.pack(fill='both', expand=True)
        self._dcanvas = tk.Canvas(holder, background=C['card'], highlightthickness=0, borderwidth=0)
        dscroll = ttk.Scrollbar(holder, orient='vertical', command=self._dcanvas.yview)
        self._dcanvas.configure(yscrollcommand=lambda lo, hi: (dscroll.set(lo, hi), dscroll.pack_forget() if float(lo) <= 0 and float(hi) >= 1
                                                               else dscroll.pack(side='right', fill='y', before=self._dcanvas)))
        self._dcanvas.pack(side='left', fill='both', expand=True)
        self.drawer_body = ttk.Frame(self._dcanvas, padding=(ui.px(16), ui.px(10)))      # the connection widgets go in here; it scrolls if the window is short
        win = self._dcanvas.create_window(0, 0, window=self.drawer_body, anchor='nw')
        self.drawer_body.bind('<Configure>', lambda e: self._dcanvas.configure(scrollregion=self._dcanvas.bbox('all')))
        self._dcanvas.bind('<Configure>', lambda e: self._dcanvas.itemconfigure(win, width=e.width))
        self._dcanvas.bind('<MouseWheel>', lambda e: self._dcanvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        root.bind('<Escape>', lambda _e: self.close_drawer(), add='+')
        root.bind('<Configure>', self._on_configure, add='+')
        root.after(60, self._apply_layout)

    # ------------------------------------------------------------------ header / strip
    def add_chip(self, text, kind='neutral'):
        pill = ui.Pill(self.chip_frame, text, kind)
        pill.pack(side='left', padx=(8, 0))
        return pill

    def set_modified(self, count):
        """Amber 'MODIFIED (n)' chip in the header while procedure modifications are in effect (nothing when there are none)."""
        text = f'MODIFIED ({int(count)})' if count else ''
        chip = getattr(self, 'modified_chip', None)
        if chip is None:
            if not text:
                return None
            chip = self.modified_chip = ui.Pill(self.chip_frame, text, 'warn')
            chip.pack(side='left', padx=(8, 0))
        if text:
            chip.set(text, 'warn')
            if not chip.winfo_manager():
                chip.pack(side='left', padx=(8, 0))
        else:
            chip.pack_forget()
        return chip

    def set_verified(self, text):
        """Green chip (e.g. 'VERIFIED ON HARDWARE - LOCKED') while the procedure is verified and locked (verified.py); '' removes it."""
        chip = getattr(self, 'verified_chip', None)
        if chip is None:
            if not text:
                return None
            chip = self.verified_chip = ui.Pill(self.chip_frame, text, 'good')
            chip.pack(side='left', padx=(8, 0))
        if text:
            chip.set(text, 'good')
            if not chip.winfo_manager():
                chip.pack(side='left', padx=(8, 0))
        else:
            chip.pack_forget()
        return chip

    def set_devmode(self, on):
        """Amber 'DEVELOPER MODE' chip while the developer-mode session is unlocked."""
        chip = getattr(self, 'devmode_chip', None)
        if chip is None:
            if not on:
                return None
            chip = self.devmode_chip = ui.Pill(self.chip_frame, 'DEVELOPER MODE', 'warn')
        if on:
            if not chip.winfo_manager():
                chip.pack(side='left', padx=(8, 0))
        else:
            chip.pack_forget()
        return chip

    def build_identity(self, asset_var, serial_var, focus=True):
        box = ttk.Frame(self.strip)
        box.pack(side='left')
        ttk.Label(box, text='Instrument ID *').pack(side='left')
        self.id_entry = ttk.Entry(box, textvariable=asset_var, width=16)
        self.id_entry.pack(side='left', padx=(6, 12))
        ttk.Label(box, text='Serial').pack(side='left')
        self.serial_entry = ttk.Entry(box, textvariable=serial_var, width=14)
        self.serial_entry.pack(side='left', padx=(6, 14))
        if focus:
            self.id_entry.focus_set()

    def build_progress(self):
        self.summary = ProgressPanel(self.strip)
        self.summary.pack(side='right', padx=(14, 0))
        return self.summary

    def notice(self, text, kind='info', title=None):
        n = ui.Notice(self.notice_holder, (f'{title}:  ' if title else '') + text, kind)
        n.pack(fill='x', pady=(6, 0))
        return n

    # ------------------------------------------------------------------ action bar
    def add_action(self, text, command, accent=False, danger=False, side='left', short=None, **kw):
        style = 'Danger.TButton' if danger else ('Accent.TButton' if accent else 'TButton')
        parent = self.actions_right if side == 'right' else self.actions_left
        b = ttk.Button(parent, text=text, command=command, style=style, **kw)
        b.pack(side='left', padx=(0 if side == 'left' and not parent.winfo_children()[:-1] else 8, 0))
        self._action_texts.append((b, text, short or text))
        if self._compact:
            b.configure(text=short or text)
            if style == 'TButton':
                b.configure(style='Compact.TButton')
        return b

    # ------------------------------------------------------------------ sections (sidebar / drop-down)
    def set_sections(self, rows):
        """rows: [(name, passed, failed, total)] for the real sections; 'All sections' is added on top."""
        self.sections = list(rows)
        names = ['All sections'] + [r[0] for r in rows]
        if self.current not in names:                      # the section went away (options changed): fall back to all, and tell the procedure
            self.current = 'All sections'
            if self.on_section:
                self.root.after_idle(lambda: self.on_section('All sections'))
        total = sum(r[3] for r in rows)
        passed = sum(r[1] for r in rows)
        failed = sum(r[2] for r in rows)
        entries = [('All sections', passed, failed, total)] + list(rows)
        C = ui.C
        for child in self._side_list.winfo_children():
            child.destroy()
        self._rows = {}
        for name, ok, bad, tot in entries:
            sel = (name == self.current)
            bg = C['select'] if sel else C['bg']
            row = tk.Frame(self._side_list, background=bg, cursor='hand2')
            row.pack(fill='x', padx=ui.px(8), pady=1)
            dotc = C['bad_dot'] if bad else (C['good_dot'] if tot and ok == tot else (C['info_dot'] if ok else C['neutral_dot']))
            d = ui.px(9)
            dot = tk.Canvas(row, width=d + 2, height=d + 2, background=bg, highlightthickness=0, borderwidth=0)
            dot.create_oval(1, 1, d, d, fill=dotc, outline='')                   # drawn, not a font glyph, so it looks the same everywhere
            dot.pack(side='left', padx=(ui.px(10), ui.px(8)), pady=ui.px(7))
            label = tk.Label(row, text=self._fit(name), background=bg, anchor='w',
                             foreground=C['text'] if sel else C['muted'])
            label.pack(side='left', fill='x', expand=True)
            count = tk.Label(row, text=f'{ok + bad}/{tot}', background=bg, foreground=C['bad'] if bad else C['faint'])
            count.pack(side='right', padx=(4, ui.px(8)))
            for w in (row, dot, label, count):
                w.bind('<Button-1>', lambda _e, n=name: self.choose_section(n))
            self._rows[name] = row
        if self.section_picker is not None:
            self.section_picker.configure(values=names)
            self.section_picker.set(self.current)

    def _side_wheel(self, event):
        lo, hi = self._side_canvas.yview()
        if lo > 0 or hi < 1:
            self._side_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')

    def _fit(self, text):
        """Shorten a long section name with an ellipsis so it never runs into the x/y count."""
        import tkinter.font as tkfont
        font = tkfont.nametofont('TkDefaultFont')
        room = ui.px(224) - ui.px(16) - ui.px(30) - ui.px(58)
        if font.measure(text) <= room:
            return text
        while text and font.measure(text + '…') > room:
            text = text[:-1]
        return text.rstrip() + '…'

    def choose_section(self, name, notify=True):
        self.current = name
        self.set_sections(self.sections)
        if notify and self.on_section:
            self.on_section(name)

    def build_section_picker(self, parent):
        """The drop-down that stands in for the sidebar in a small window.  Returns the Combobox (already placed by the caller)."""
        self.section_picker = ttk.Combobox(parent, values=['All sections'] + [r[0] for r in self.sections], state='readonly', width=16)
        self.section_picker.set(self.current)
        self.section_picker.bind('<<ComboboxSelected>>', lambda _e: self.choose_section(self.section_picker.get()))
        return self.section_picker

    # ------------------------------------------------------------------ drawer
    def toggle_drawer(self):
        self.close_drawer() if self._drawer_open else self.open_drawer()

    def open_drawer(self):
        width = min(ui.px(420), max(ui.px(300), self.root.winfo_width() - ui.px(40)))
        self.drawer.place(relx=1.0, rely=0.0, anchor='ne', relheight=1.0, width=width)
        self.drawer.lift()
        self._drawer_open = True

    def close_drawer(self):
        if self._drawer_open:
            self.drawer.place_forget()
            self._drawer_open = False

    # ------------------------------------------------------------------ small window
    def _on_configure(self, event):
        if event.widget is self.root:
            self.root.after_idle(self._apply_layout)

    @property
    def compact(self):
        return bool(self._compact)

    def _apply_layout(self):
        try:
            width = self.root.winfo_width()
        except tk.TclError:
            return
        if width <= 1:
            return
        compact = width < ui.px(COMPACT_BELOW)
        if compact == self._compact:
            return
        self._compact = compact
        if compact:
            self.sidebar.pack_forget()
            self._side_sep_hide(True)
        else:
            self._side_sep_hide(False)
            self.sidebar.pack(side='left', fill='y', before=self.content)
        for b, full, short in self._action_texts:           # shorter button texts in a small window
            b.configure(text=short if compact else full)
            if str(b.cget('style')) == 'TButton':
                b.configure(style='Compact.TButton' if compact else 'TButton')
        summary = getattr(self, 'summary', None)
        if summary is not None:                              # the pass / fail / remaining badges give way to the bar
            summary.badges.pack_forget() if compact else summary.badges.pack(anchor='w', pady=(4, 0))
        if self.layout_hook:
            self.layout_hook(compact)

    def _side_sep_hide(self, hide):
        for w in self.body.winfo_children():
            if isinstance(w, tk.Frame) and w is not self.sidebar and int(w.cget('width') or 0) == 1 and w.winfo_manager() == 'pack':
                if hide:
                    w.pack_forget()
                    self._sep = w
        if not hide and getattr(self, '_sep', None) is not None:
            self._sep.pack(side='left', fill='y', before=self.content)
            self._sep = None


# ---------------------------------------------------------------------------------------------- results table
FULL_COLUMNS = ('n', 'description', 'nominal', 'low', 'high', 'found', 'error', 'left', 'result')
SMALL_COLUMNS = ('n', 'description', 'nominal', 'limits', 'found', 'left', 'result')


def results_table(app, parent, name_width=300, nominal_title='Nominal', error=True):
    """The full-width results table shared by the procedures.  Row cells come from DataModeMixin.shell_cells(); the first cell is the
    point number and the second the description:   values = (id, description, *app.shell_cells(...))
    Wires the small-window layout (merged Limits column) and the 'As Found / As Left' headings.  Returns the Treeview."""
    cols = ('n', 'description', 'nominal', 'low', 'high', 'limits', 'found', 'error', 'left', 'result')
    heads = ('#', 'Description', nominal_title, 'Low limit', 'High limit', 'Limits', 'As Found', 'Error', 'As Left', 'Result')
    tree = ui.make_table(parent, cols, heads, (44, name_width, 100, 100, 100, 170, 110, 100, 110, 90), height=12,
                         anchors={'description': 'w', 'nominal': 'e', 'low': 'e', 'high': 'e', 'limits': 'e', 'found': 'e', 'error': 'e', 'left': 'e'},
                         stretch={c: False for c in cols if c != 'description'})
    tree._cols_full = FULL_COLUMNS if error else tuple(c for c in FULL_COLUMNS if c != 'error')
    tree._cols_small = SMALL_COLUMNS
    tree.configure(displaycolumns=tree._cols_full)
    tree.tag_configure('pending', foreground=ui.C['muted'])
    tree._shell_name_width = name_width

    def relabel():
        tree.heading('found', text='As Found' if app.is_left else '● As Found')
        tree.heading('left', text='● As Left' if app.is_left else 'As Left')
    app._relabel_reading_column = relabel
    relabel()
    return tree


def small_window(app, tree, filter_bar, picker=None, extra=None):
    """Hook the small-window behaviour: merged Limits column, section drop-down in filter_bar, then extra(compact) if given."""
    picker = picker or app.shell.build_section_picker(filter_bar)

    def layout(compact):
        tree.configure(displaycolumns=tree._cols_small if compact else tree._cols_full)
        tree.column('description', width=ui.px(200 if compact else tree._shell_name_width))
        tree.column('limits', width=ui.px(160))
        for col in ('found', 'left'):
            tree.column(col, width=ui.px(100 if compact else 110))
        if compact:
            picker.pack(side='right', padx=(0, 14))
        else:
            picker.pack_forget()
        if extra:
            extra(compact)
    app.shell.layout_hook = layout
    return picker
