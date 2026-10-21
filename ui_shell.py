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
    | status message                                                              v70 Beta 1|   status bar
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
        self.sidebar = tk.Frame(self.body, background=C['bg'], width=ui.px(206))
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        tk.Frame(self.body, width=1, background=C['border']).pack(side='left', fill='y')
        self._side_title = tk.Label(self.sidebar, text='SECTIONS', background=C['bg'], foreground=C['faint'], anchor='w',
                                    font=('TkDefaultFont', max(7, int(ui.SCALE * 8)), 'bold'))
        self._side_title.pack(fill='x', padx=ui.px(16), pady=(ui.px(14), ui.px(6)))
        self._side_list = tk.Frame(self.sidebar, background=C['bg'])
        self._side_list.pack(fill='both', expand=True)
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
        self.drawer_body = ttk.Frame(self.drawer, padding=(ui.px(16), ui.px(10)))
        self.drawer_body.pack(fill='both', expand=True)
        root.bind('<Escape>', lambda _e: self.close_drawer(), add='+')
        root.bind('<Configure>', self._on_configure, add='+')
        root.after(60, self._apply_layout)

    # ------------------------------------------------------------------ header / strip
    def add_chip(self, text, kind='neutral'):
        pill = ui.Pill(self.chip_frame, text, kind)
        pill.pack(side='left', padx=(8, 0))
        return pill

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
        self.summary = ui.Summary(self.strip)
        self.summary.pack(side='right', fill='x', expand=True, padx=(14, 0))
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
        if self.current not in names:
            self.current = 'All sections'
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
            label = tk.Label(row, text=name, background=bg, anchor='w',
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
            for pill in (summary.rem, summary.fail, summary.ok):
                pill.pack_forget() if compact else pill.pack(side='right', padx=(6, 0))
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
