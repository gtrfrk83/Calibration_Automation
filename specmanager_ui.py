"""Specification Manager tab: the standards (calibrators) whose published specifications feed the uncertainty budgets, and the EMU check.

Layout (Option A of the Standards Specs study): a standards rail on the left (one card per standard), a header card for the selected standard on the
right (confidence, divisor, period, ranges, assets, approval, sheet issues, actions) and a card with the function-type chips and the table of ranges.
Presentation only: the stored rows, the printed sheet text, the limits and the uncertainty numbers are untouched; the text of a specification is
formatted for display (specmanager_view.format_spec) and the printed text is the tooltip of the cell.
"""
from __future__ import annotations

import json
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

import specmanager as sm
import specmanager_view as view
import ui_theme as ui
import uncertainty
import uncertainty_budget as ub

KINDS = ['', 'DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'COND', 'FREQ', 'TEMP', 'POWDC', 'POWAC', 'PHASE']
UNITS = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'ohm', 'OHM2': 'ohm', 'OHM4': 'ohm', 'CAP': 'F', 'FREQ': 'Hz'}
HINT = 'Double-click a row to set its calibrator resolution'
PLACEHOLDER = 'Filter by function / text'
PERIOD_IDS = ('p1', 'p2', 'p3')


def _si(value, unit):
    return uncertainty.format_value(value, unit, sig=3) if value is not None else ''


# ------------------------------------------------------------------------------------------------------------ small widgets
class Chip(tk.Canvas):
    """A rounded label (optionally clickable).  kind: good / bad / warn / info / neutral (colour tokens of ui_theme); filter chips use count + active."""

    def __init__(self, parent, text, kind='neutral', font=None, bg=None, command=None, dot=False, count=None, active=False, height=None):
        self.text, self.kind, self.font, self.command, self.dot, self.count, self.active = text, kind, font, command, dot, count, active
        self.hover = False
        self._ch = height or font.metrics('linespace') + ui.px(8)
        self._pad = ui.px(9)
        self._countfont = font
        self._cw = self._measure()
        super().__init__(parent, width=self._cw, height=self._ch, background=bg or ui.C['card'], highlightthickness=0, bd=0, cursor='hand2' if command else '')
        if command:
            self.bind('<Button-1>', lambda _e: command())
            self.bind('<Enter>', lambda _e: self._hover(True))
            self.bind('<Leave>', lambda _e: self._hover(False))
            self.bind('<Return>', lambda _e: command())
            self.bind('<space>', lambda _e: command())
            self.configure(takefocus=1)
        self.draw()

    def _measure(self):
        w = self.font.measure(self.text) + 2 * self._pad + (ui.px(12) if self.dot else 0)
        if self.count is not None:
            w += self.font.measure('  ' + str(self.count))
        return w

    def _hover(self, on):
        self.hover = on
        self.draw()

    def set_active(self, on):
        if on != self.active:
            self.active = on
            self.draw()

    def draw(self):
        C = ui.C
        self.delete('all')
        if self.count is not None:        # filter chip
            fill = C['primary'] if self.active else (C['border'] if self.hover else C['neutral_bg'])
            fg, cfg = (C['on_primary'], C['on_primary']) if self.active else (C['text'], C['muted'])
        else:
            fill, fg, cfg = C[self.kind + '_bg'], C[self.kind], C[self.kind]
            if self.command and self.hover:
                fill = C[self.kind + '_dot'] if self.kind != 'neutral' else C['border']
                fg = C['on_primary'] if self.kind != 'neutral' else C['text']
        ui._round_rect(self, 0, 0, self._cw, self._ch, self._ch // 2, fill=fill, outline='')
        x = self._pad
        if self.dot:
            r = ui.px(3)
            dotc = C[self.kind + '_dot'] if not (self.command and self.hover and self.kind != 'neutral') else fg
            self.create_oval(x, self._ch / 2 - r, x + 2 * r, self._ch / 2 + r, fill=dotc, outline='')
            x += ui.px(12)
        self.create_text(x, self._ch / 2, text=self.text, font=self.font, fill=fg, anchor='w')
        if self.count is not None:
            self.create_text(x + self.font.measure(self.text + '  '), self._ch / 2, text=str(self.count), font=self._countfont, fill=cfg, anchor='w')


class Link(tk.Label):
    """Text link (primary colour, underlined on hover, Enter / Space work)."""

    def __init__(self, parent, text, command, font, bg=None):
        super().__init__(parent, text=text, font=font, foreground=ui.C['primary'], background=bg or ui.C['card'], cursor='hand2', takefocus=1, borderwidth=0)
        self._font = font
        self._under = font.copy()
        self._under.configure(underline=True)
        self.bind('<Button-1>', lambda _e: command())
        self.bind('<Return>', lambda _e: command())
        self.bind('<space>', lambda _e: command())
        self.bind('<Enter>', lambda _e: self.configure(font=self._under, foreground=ui.C['primary_hi']))
        self.bind('<Leave>', lambda _e: self.configure(font=self._font, foreground=ui.C['primary']))


class Flow(tk.Frame):
    """A row of widgets that wraps onto more lines when it is narrower than they are (children are created with this frame as master)."""

    def __init__(self, parent, bg, hgap=6, vgap=6):
        super().__init__(parent, background=bg, width=1, height=1)
        self.items, self.hgap, self.vgap, self._width, self._job = [], hgap, vgap, 0, None
        self.bind('<Configure>', self._on_configure)

    def add(self, widget, gap=None):
        self.items.append((widget, self.hgap if gap is None else gap))
        self.relayout()
        if self._job is None:                      # a frame that holds other widgets only knows its size once Tk has laid it out
            self._job = self.after_idle(self._later)
        return widget

    def _later(self):
        self._job = None
        self.update_idletasks()
        self.relayout()

    def clear(self):
        for w, _g in self.items:
            w.destroy()
        self.items = []
        self.relayout()

    def _on_configure(self, e):
        if e.width != self._width:
            self._width = e.width
            self.relayout()

    def relayout(self):
        width = self._width or 10 ** 4
        rows, row, x = [], [], 0
        for w, gap in self.items:
            rw = w.winfo_reqwidth()
            if row and x + rw > width:
                rows.append(row)
                row, x = [], 0
            row.append((w, x, w.winfo_reqheight()))
            x += rw + gap
        if row:
            rows.append(row)
        y = 0
        for row in rows:
            rowh = max(h for _w, _x, h in row)
            for w, rx, h in row:
                w.place(x=rx, y=y + (rowh - h) // 2)
            y += rowh + self.vgap
        total = max(1, y - self.vgap if rows else 1)
        if int(self.cget('height')) != total:
            self.configure(height=total)


class Card(tk.Canvas):
    """A rounded panel (border + fill from the theme tokens).  Put widgets in `.body`.  fit=True: the card is as tall as its content."""

    def __init__(self, parent, fit=False, pad=0):
        super().__init__(parent, background=ui.C['bg'], highlightthickness=0, bd=0, width=10, height=10)
        self.fit, self.pad = fit, ui.px(pad)
        self.body = tk.Frame(self, background=ui.C['card'])
        self._win = self.create_window(1 + self.pad, 1 + self.pad, window=self.body, anchor='nw')
        self.bind('<Configure>', self._on_configure)
        if fit:
            self.body.bind('<Configure>', lambda _e: self._fit())

    def _fit(self):
        h = self.body.winfo_reqheight() + 2 + 2 * self.pad
        if int(self.cget('height')) != h:
            self.configure(height=h)

    def _on_configure(self, e):
        self.delete('bg')
        r = ui.px(10)
        ui._round_rect(self, 0, 0, e.width, e.height, r, fill=ui.C['border'], outline='', tags='bg')
        ui._round_rect(self, 1, 1, e.width - 1, e.height - 1, r - 1, fill=ui.C['card'], outline='', tags='bg')
        self.tag_lower('bg')
        opts = {'width': max(1, e.width - 2 - 2 * self.pad)}
        if not self.fit:
            opts['height'] = max(1, e.height - 2 - 2 * self.pad)
        self.itemconfigure(self._win, **opts)


def hline(parent, bg=None):
    return tk.Frame(parent, height=1, background=bg or ui.C['border'])


class CellTip:
    """Hover tip for table cells: text_for(iid, column name) -> str; shown after a short pause."""

    def __init__(self, tree, text_for):
        self.tree, self.text_for, self.key, self.tip, self.job = tree, text_for, None, None, None
        tree.bind('<Motion>', self._move, add='+')
        tree.bind('<Leave>', self._hide, add='+')
        tree.bind('<ButtonPress>', self._hide, add='+')
        tree.bind('<MouseWheel>', self._hide, add='+')

    def _move(self, e):
        iid, col = self.tree.identify_row(e.y), self.tree.identify_column(e.x)
        if (iid, col) == self.key:
            return
        self._hide()
        self.key = (iid, col)
        if not iid:
            return
        names = ['#0'] + list(self.tree['displaycolumns'] if self.tree['displaycolumns'] != ('#all',) else self.tree['columns'])
        try:
            name = names[int(col[1:])]
        except (ValueError, IndexError):
            return
        text = self.text_for(iid, name)
        if text:
            self.job = self.tree.after(550, lambda: self._show(text, e.x_root, e.y_root))

    def _show(self, text, x, y):
        self.job = None
        self.tip = tk.Toplevel(self.tree)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f'+{x + 14}+{y + 18}')
        tk.Label(self.tip, text=text, background=ui.C['tip'], foreground='#FFFFFF', padx=8, pady=4, font='TkDefaultFont', justify='left',
                 wraplength=ui.px(520)).pack()

    def _hide(self, _e=None):
        if self.job:
            self.tree.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None
        if _e is not None:
            self.key = None


class RailCard(tk.Canvas):
    """One standard in the rail: model + maker, description, the confidence / divisor chip, the range count and the sheet-issues pill."""

    def __init__(self, parent, panel, sid, info):
        super().__init__(parent, background=ui.C['card'], highlightthickness=0, bd=0, cursor='hand2', takefocus=0, height=ui.px(70))
        self.panel, self.sid, self.info = panel, sid, info
        self.selected, self.hover, self.width = False, False, 0
        self.bind('<Button-1>', lambda _e: panel.select(sid))
        self.bind('<Enter>', lambda _e: self._set_hover(True))
        self.bind('<Leave>', lambda _e: self._set_hover(False))
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.bind(seq, panel._rail_wheel)

    def _set_hover(self, on):
        self.hover = on
        self.draw()

    def set_selected(self, on):
        self.selected = on
        self.draw()

    def layout(self, width):
        self.width = width
        self.draw()

    def draw(self):
        w = self.width
        if w < 20:
            return
        C, f = ui.C, self.panel.fonts
        self.delete('all')
        fill = C['select'] if self.selected else (C['row_alt'] if self.hover else C['card'])
        self.create_rectangle(0, 0, w, 4000, fill=fill, outline='')
        padx, padt = ui.px(18), ui.px(11)
        info = self.info
        y = padt
        self.create_text(padx, y, text=info['model'], font=f['model'], fill=C['text'], anchor='nw')
        mw = f['model'].measure(info['model'])
        maker = view.ellipsize(info['maker'], max(0, w - padx - mw - ui.px(22) - ui.px(8)), f['small'].measure)
        if maker:
            self.create_text(padx + mw + ui.px(8), y + f['model'].metrics('linespace') - f['small'].metrics('linespace') - 1, text=maker, font=f['small'],
                             fill=C['muted'], anchor='nw')
        y += f['model'].metrics('linespace') + ui.px(1)
        desc = view.ellipsize(info['desc'], w - padx - ui.px(14), f['small'].measure)
        self.create_text(padx, y, text=desc, font=f['small'], fill=C['muted'], anchor='nw')
        y += f['small'].metrics('linespace') + ui.px(7)
        chip_h = f['chip'].metrics('linespace') + ui.px(6)
        x, avail = padx, w - padx - ui.px(12)
        for text, kind in info['chips']:
            cw = f['chip'].measure(text) + 2 * ui.px(8)
            if x > padx and x + cw > padx + avail:
                x, y = padx, y + chip_h + ui.px(4)
            ui._round_rect(self, x, y, x + cw, y + chip_h, chip_h // 2, fill=C[kind + '_bg'], outline='')
            self.create_text(x + ui.px(8), y + chip_h / 2, text=text, font=f['chip'], fill=C[kind], anchor='w')
            x += cw + ui.px(5)
        y += chip_h + ui.px(11)
        if self.selected:
            self.create_rectangle(0, 0, ui.px(4), y, fill=C['primary'], outline='')
        else:
            self.create_line(padx, y - 1, w - ui.px(16), y - 1, fill=C['border'])
        if int(self.cget('height')) != y:
            self.configure(height=y)


# ------------------------------------------------------------------------------------------------------------ the panel
class SpecManagerPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        sm.seed()
        self.sel = None
        self.kind = tk.StringVar()
        self.term = tk.StringVar()
        self._info, self._cards, self._rows, self._periods, self._closed = {}, {}, [], [], {}
        self._tips, self._chips, self._collapsed_rail, self._group_keys, self._other_periods = {}, {}, False, {}, []
        self._chip_specs, self._chip_width, self._full, self._last0, self._shown_n = [], 0, {}, 0, -1
        self._build_fonts()
        self._build_style()
        C = ui.C
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text='Standards whose published accuracy specifications are used to compute reported uncertainties', style='Muted.TLabel').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, ui.px(10)))
        self._build_rail()
        self.right = tk.Frame(self, background=C['bg'])
        self.right.grid(row=1, column=1, sticky='nsew', padx=(ui.px(16), 0))
        self.right.columnconfigure(0, weight=1)
        self.right.rowconfigure(2, weight=1)
        self._build_pickbar()
        self._build_header()
        self._build_table()
        self._build_empty_all()
        self.kind.trace_add('write', lambda *_: self._kind_changed())
        self.term.trace_add('write', lambda *_: self.show_rows())
        self.bind('<Configure>', self._on_configure)
        self.refresh()

    # ----------------------------------------------------------------------------------------------------
    def _build_fonts(self):
        base = tkfont.nametofont('TkDefaultFont')

        def make(size, weight='normal'):
            f = base.copy()
            f.configure(size=size, weight=weight)
            return f
        self.fonts = {'normal': make(10), 'bold': make(10, 'bold'), 'small': make(9), 'smallb': make(9, 'bold'), 'caps': make(8, 'bold'), 'model': make(12, 'bold'),
                      'chip': make(9, 'bold'), 'title': make(17, 'bold'), 'stat': make(17, 'bold'), 'filter': make(9, 'bold')}

    def _build_style(self):
        s = ttk.Style(self)
        s.configure('Specs.Treeview', indent=ui.px(16))
        s.layout('Specs.Treeview.Item', [('Treeitem.padding', {'sticky': 'nswe', 'children': [
            ('Treeitem.image', {'side': 'left', 'sticky': ''}), ('Treeitem.text', {'sticky': 'nswe'})]})])

    def _build_rail(self):
        C, f = ui.C, self.fonts
        self.rail = Card(self)
        self.rail.grid(row=1, column=0, sticky='ns')
        b = self.rail.body
        b.rowconfigure(1, weight=1)
        b.columnconfigure(0, weight=1)
        head = tk.Frame(b, background=C['card'])
        head.grid(row=0, column=0, columnspan=2, sticky='ew', padx=ui.px(18), pady=(ui.px(14), ui.px(6)))
        tk.Label(head, text='STANDARDS', font=f['caps'], foreground=C['muted'], background=C['card']).pack(side='left')
        self.rail_count = tk.Label(head, text='0', font=f['caps'], foreground=C['faint'], background=C['card'])
        self.rail_count.pack(side='right')
        self.rail_cv = tk.Canvas(b, background=C['card'], highlightthickness=0, bd=0, width=10, takefocus=1)
        self.rail_cv.grid(row=1, column=0, sticky='nsew')
        self.rail_sb = ttk.Scrollbar(b, orient='vertical', command=self.rail_cv.yview)
        self.rail_sb.grid(row=1, column=1, sticky='ns')
        self.rail_cv.configure(yscrollcommand=self._rail_yset)
        self.rail_inner = tk.Frame(self.rail_cv, background=C['card'])
        self._rail_win = self.rail_cv.create_window(0, 0, window=self.rail_inner, anchor='nw')
        self.rail_inner.bind('<Configure>', lambda _e: self.rail_cv.configure(scrollregion=self.rail_cv.bbox('all')))
        self.rail_cv.bind('<Configure>', self._rail_resized)
        for w in (self.rail_cv, self.rail_inner):
            for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                w.bind(seq, self._rail_wheel)
        self.rail_cv.bind('<Up>', lambda _e: self._step(-1))
        self.rail_cv.bind('<Down>', lambda _e: self._step(1))
        self.rail_empty = tk.Label(self.rail_inner, text='No standards loaded yet.', font=f['small'], foreground=C['muted'], background=C['card'], wraplength=ui.px(200))
        hline(b).grid(row=2, column=0, columnspan=2, sticky='ew')
        foot = tk.Frame(b, background=C['card'])
        foot.grid(row=3, column=0, columnspan=2, sticky='ew', padx=ui.px(16), pady=ui.px(12))
        foot.columnconfigure(0, weight=1)
        ttk.Button(foot, text='Import spec JSON...', style='Quiet.TButton', command=self.import_json).grid(row=0, column=0, sticky='ew')

    def _build_pickbar(self):
        """Shown instead of the rail when the window is too narrow for it: a selector of the standards."""
        C = ui.C
        self.pickbar = tk.Frame(self.right, background=C['bg'])
        self.pick_var = tk.StringVar()
        ttk.Label(self.pickbar, text='Standard').pack(side='left')
        self.pick_box = ttk.Combobox(self.pickbar, textvariable=self.pick_var, state='readonly', width=22)
        self.pick_box.pack(side='left', padx=8)
        self.pick_box.bind('<<ComboboxSelected>>', self._pick_chosen)
        ttk.Button(self.pickbar, text='Import spec JSON...', style='Quiet.TButton', command=self.import_json).pack(side='right')

    def _build_header(self):
        C, f = ui.C, self.fonts
        self.head_card = Card(self.right, fit=True)
        self.head_card.grid(row=1, column=0, sticky='ew', pady=(0, ui.px(14)))
        b = self.head_card.body
        b.columnconfigure(0, weight=1)
        top = tk.Frame(b, background=C['card'])
        top.grid(row=0, column=0, sticky='ew', padx=ui.px(20), pady=ui.px(10))
        btns = tk.Frame(top, background=C['card'])
        btns.pack(side='right')
        ttk.Button(btns, text='Export JSON...', command=self.export_json).pack(side='left', padx=(0, ui.px(8)))
        ttk.Button(btns, text='Check an EMU...', style='Accent.TButton', command=self.check_emu).pack(side='left')
        self.h_title = tk.Label(top, text='', font=f['title'], foreground=C['text'], background=C['card'])
        self.h_title.pack(side='left')
        self.h_desc = tk.Label(top, text='', font=f['normal'], foreground=C['muted'], background=C['card'], anchor='w')
        self.h_desc.pack(side='left', padx=(ui.px(10), 0), fill='x', expand=True)
        self.h_desc.bind('<Configure>', lambda _e: self._fit_text(self.h_desc, self._desc_full, f['normal']))
        self._desc_full = ''
        hline(b).grid(row=1, column=0, sticky='ew')
        stats = tk.Frame(b, background=C['card'])
        stats.grid(row=2, column=0, sticky='ew', padx=ui.px(20), pady=ui.px(8))
        self.stat = {}
        for i, (key, cap) in enumerate((('conf', 'CONFIDENCE ON SHEET'), ('div', 'DIVISOR'), ('period', 'PERIOD'), ('ranges', 'RANGES'))):
            col = i * 2
            stats.columnconfigure(col, weight=1, uniform='stat')
            if i:
                tk.Frame(stats, width=1, background=C['border']).grid(row=0, column=col - 1, sticky='ns', padx=ui.px(12))
            blk = tk.Frame(stats, background=C['card'])
            blk.grid(row=0, column=col, sticky='nsew')
            tk.Label(blk, text=cap, font=f['caps'], foreground=C['muted'], background=C['card']).grid(row=0, column=0, sticky='w', columnspan=2)
            val = tk.Label(blk, text='', font=f['stat'], foreground=C['text'], background=C['card'])
            val.grid(row=1, column=0, sticky='w')
            sub = tk.Label(blk, text='', font=f['small'], foreground=C['muted'], background=C['card'], anchor='w')
            sub.grid(row=2, column=0, columnspan=2, sticky='ew')
            blk.columnconfigure(1, weight=1)
            sub.bind('<Configure>', lambda _e, k=key: self._fit_stat(k))
            self.stat[key] = dict(val=val, sub=sub, sub_text='', tip='', blk=blk)
            ui.Tooltip(sub, lambda k=key: self.stat[k]['tip'])
            ui.Tooltip(val, lambda k=key: self.stat[k]['tip'])
        self.div_link = Link(self.stat['div']['blk'], 'Set divisor...', self.set_divisor, f['smallb'])
        self.div_link.grid(row=1, column=1, sticky='w', padx=(ui.px(10), 0), pady=(ui.px(5), 0))
        hline(b).grid(row=3, column=0, sticky='ew')
        self.facts = Flow(b, C['card'], hgap=ui.px(6), vgap=ui.px(6))
        self.facts.grid(row=4, column=0, sticky='ew', padx=ui.px(20), pady=ui.px(8))

    def _build_table(self):
        C, f = ui.C, self.fonts
        self.table_card = Card(self.right)
        self.table_card.grid(row=2, column=0, sticky='nsew')
        b = self.table_card.body
        b.columnconfigure(0, weight=1)
        b.rowconfigure(2, weight=1)
        bar = tk.Frame(b, background=C['card'])
        bar.grid(row=0, column=0, sticky='ew', padx=ui.px(16), pady=ui.px(10))
        bar.columnconfigure(0, weight=1)
        self.chip_flow = Flow(bar, C['card'], hgap=ui.px(5), vgap=ui.px(5))
        self.chip_flow.grid(row=0, column=0, sticky='ew', padx=(0, ui.px(12)))
        self.chip_flow.bind('<Configure>', self._chips_resized, add='+')
        holder = tk.Frame(bar, background=C['card'])
        holder.grid(row=0, column=1, sticky='ne')
        self.entry = ttk.Entry(holder, textvariable=self.term, width=26)
        self.entry.pack()
        self.ph = tk.Label(holder, text=PLACEHOLDER, font='TkDefaultFont', foreground=C['faint'], background=C['field'], cursor='xterm')
        self.ph.bind('<Button-1>', lambda _e: self.entry.focus_set())
        self.entry.bind('<FocusIn>', lambda _e: self._placeholder(), add='+')
        self.entry.bind('<FocusOut>', lambda _e: self._placeholder(), add='+')
        hline(b).grid(row=1, column=0, sticky='ew')
        self.rows = ui.make_table(b, ('span', 'freq', 'res') + PERIOD_IDS, ('VALUE SPAN', 'FREQUENCY', 'RESOLUTION', '', '', ''),
                                  (150, 150, 90, 170, 170, 170), height=12, pack=False,
                                  anchors={'span': 'w', 'freq': 'w', 'res': 'e', 'p1': 'w', 'p2': 'w', 'p3': 'w'},
                                  stretch={'res': False})
        self.rows.configure(show='tree headings', style='Specs.Treeview')
        self.rows.heading('#0', text='RANGE', anchor='w')
        self.rows.column('#0', width=ui.px(200), minwidth=ui.px(110), anchor='w', stretch=True)
        for c in ('span', 'freq', 'res', 'p1', 'p2', 'p3'):
            self.rows.heading(c, anchor='e' if c == 'res' else 'w')
        for c in ('span', 'freq') + PERIOD_IDS:
            self.rows.column(c, minwidth=ui.px(100))
        self.rows.column('res', minwidth=ui.px(70))
        self.rows_holder = self.rows.master
        self.rows_holder.grid(row=2, column=0, sticky='nsew', padx=1)
        self.rows.tag_configure('band', background=C['head_hi'], foreground=C['text'], font=f['bold'])
        self.rows.tag_configure('odd', background=C['row_alt'])
        self.rows.tag_configure('even', background=C['card'])
        self.rows.bind('<Double-1>', self._double_click)
        self.rows.bind('<Button-1>', self._click, add='+')
        self.rows.bind('<Return>', lambda _e: self.edit_resolution())
        self.rows.bind('<Configure>', lambda _e: self._fit_columns())
        CellTip(self.rows, lambda iid, col: self._tips.get(iid, {}).get(col, ''))
        self.empty = tk.Frame(self.rows_holder, background=C['card'])
        self.empty_msg = tk.Label(self.empty, text='', font=f['normal'], foreground=C['muted'], background=C['card'], wraplength=ui.px(420), justify='center')
        self.empty_msg.pack()
        self.empty_clear = Link(self.empty, 'Clear the filters', self.clear_filters, f['bold'])
        self.empty_clear.pack(pady=(ui.px(6), 0))
        hline(b).grid(row=3, column=0, sticky='ew')
        foot = tk.Frame(b, background=C['card'])
        foot.grid(row=4, column=0, sticky='ew', padx=ui.px(20), pady=ui.px(8))
        foot.columnconfigure(1, weight=1)
        self.count_lbl = tk.Label(foot, text='', font=f['smallb'], foreground=C['muted'], background=C['card'])
        self.count_lbl.grid(row=0, column=0, sticky='w')
        links = tk.Frame(foot, background=C['card'])
        links.grid(row=0, column=1, sticky='w', padx=ui.px(16))
        Link(links, 'Collapse all', lambda: self.set_all_groups(False), f['smallb']).pack(side='left')
        tk.Label(links, text=' / ', font=f['small'], foreground=C['faint'], background=C['card']).pack(side='left')
        Link(links, 'Expand all', lambda: self.set_all_groups(True), f['smallb']).pack(side='left')
        self.hint = tk.Label(foot, text=HINT, font=f['small'], foreground=C['muted'], background=C['card'], anchor='e')
        self.hint.grid(row=0, column=2, sticky='e')

    def _build_empty_all(self):
        C, f = ui.C, self.fonts
        self.empty_all = Card(self.right)
        box = tk.Frame(self.empty_all.body, background=C['card'])
        box.place(relx=0.5, rely=0.4, anchor='center')
        tk.Label(box, text='No standards loaded', font=f['title'], foreground=C['text'], background=C['card']).pack()
        tk.Label(box, text='Import a standard\'s published specification (a spec JSON file) to see its ranges here\nand to use it in the uncertainty budgets.',
                 font=f['normal'], foreground=C['muted'], background=C['card'], justify='center').pack(pady=(ui.px(8), ui.px(14)))
        ttk.Button(box, text='Import spec JSON...', style='Accent.TButton', command=self.import_json).pack()

    # ----------------------------------------------------------------------------------------------------
    def _fit_text(self, label, text, font):
        width = label.winfo_width()
        if width > 20:
            label.configure(text=view.ellipsize(text, width - 2, font.measure))

    def _fit_stat(self, key):
        st = self.stat[key]
        self._fit_text(st['sub'], st['sub_text'], self.fonts['small'])

    def _placeholder(self):
        show = not self.term.get() and self.focus_get() is not self.entry
        if show:
            self.ph.place(in_=self.entry, x=ui.px(8), rely=0.5, anchor='w')
        else:
            self.ph.place_forget()

    def _rail_yset(self, lo, hi):
        self.rail_sb.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.rail_sb.grid_remove()
        else:
            self.rail_sb.grid()

    def _rail_wheel(self, e):
        if self.rail_sb.winfo_ismapped():
            step = -1 if (getattr(e, 'num', 0) == 4 or getattr(e, 'delta', 0) > 0) else 1
            self.rail_cv.yview_scroll(step * 2, 'units')
        return 'break'

    def _rail_resized(self, e):
        self.rail_cv.itemconfigure(self._rail_win, width=e.width)
        for card in self._cards.values():
            if card.width != e.width:
                card.layout(e.width)

    def _on_configure(self, e):
        if e.widget is not self:
            return
        w = view.rail_width(e.width)
        if w is None:
            if not self._collapsed_rail:
                self._collapsed_rail = True
                self.rail.grid_remove()
                self.right.grid_configure(padx=0)
                self.pickbar.grid(row=0, column=0, sticky='ew', pady=(0, ui.px(10)))
        else:
            if self._collapsed_rail:
                self._collapsed_rail = False
                self.pickbar.grid_remove()
                self.right.grid_configure(padx=(ui.px(16), 0))
                self.rail.grid()
            if int(self.rail.cget('width')) != ui.px(w):
                self.rail.configure(width=ui.px(w))

    def _fit_columns(self):
        """Give the columns the width of the table: the period columns that fit (three in a wide table, two in a narrow one) share it with the others."""
        tree = self.rows
        avail = tree.winfo_width()
        if avail < 60:
            return
        n = len(view.shown_periods(self._periods, avail / max(1.0, ui.SCALE)))
        if n != self._shown_n and self.sel is not None:
            self._shown_n = n
            self._period_stat()
        want = ('span', 'freq', 'res') + PERIOD_IDS[:n]
        if tuple(tree['displaycolumns']) != want:
            tree.configure(displaycolumns=want)
        names = ['#0'] + list(want)
        weight = {'#0': 1.5, 'span': 1.2, 'freq': 1.3, 'res': 0.75, 'p1': 1.35, 'p2': 1.35, 'p3': 1.35}
        least = {'#0': 110, 'span': 110, 'freq': 110, 'res': 92, 'p1': 120, 'p2': 120, 'p3': 120}
        total = sum(weight[c] for c in names)
        width = {c: max(ui.px(least[c]), avail * weight[c] / total) for c in names}
        over = sum(width.values()) - avail
        if over > 0:                                       # take the excess from the columns that are wider than their minimum
            room = {c: width[c] - ui.px(least[c]) for c in names}
            tot = sum(room.values())
            if tot > 0:
                for c in names:
                    width[c] -= over * room[c] / tot
        for c in names:
            tree.column(c, width=int(width[c]), stretch=False)
        if int(width['#0']) != self._last0:
            self._last0 = int(width['#0'])
            self._retitle()

    def _cut(self, text, inset):
        """Text of the first column cut with an ellipsis to the column width (Tk clips a cell without a mark)."""
        return view.ellipsize(text, max(40, int(self.rows.column('#0', 'width')) - inset), self.fonts['bold'].measure)

    def _retitle(self):
        for iid, (text, inset) in self._full.items():
            if self.rows.exists(iid) and self.rows.item(iid, 'text'):
                self.rows.item(iid, text=self._cut(text, inset))

    # ----------------------------------------------------------------------------------------------------
    def refresh(self):
        """Reload the standards from the database (the rail, the header and the table keep the selection)."""
        stds = sm.standards()
        model = self._info[self.sel]['std']['model'] if self.sel in self._info else None
        self._info = {}
        for s in stds:
            div, why = sm.standard(s['id']).divisor()
            self._info[s['id']] = dict(std=s, div=div, why=why, assets=sm.assets_of(s['id']), problems=sm.problems_of(s['id']))
        for card in self._cards.values():
            card.destroy()
        self._cards = {}
        self.rail_empty.pack_forget()
        for s in stds:
            i = self._info[s['id']]
            chip_text, chip_kind = view.card_chip(s, i['div'])
            chips = [(chip_text, chip_kind), (f"{s['rows']} range{'' if s['rows'] == 1 else 's'}", 'neutral')]
            if i['problems']:
                chips.append((f"{len(i['problems'])} issue{'' if len(i['problems']) == 1 else 's'}", view.issues_kind(i['problems'])))
            card = RailCard(self.rail_inner, self, s['id'], dict(model=s['model'], maker=s['manufacturer'], desc=view.description_of(s), chips=chips))
            card.pack(fill='x')
            card.layout(max(self.rail_cv.winfo_width(), 10))
            self._cards[s['id']] = card
        if not stds:
            self.rail_empty.pack(padx=ui.px(18), pady=ui.px(12), anchor='w')
        self.rail_count.configure(text=str(len(stds)))
        self.pick_box.configure(values=[s['model'] for s in stds])
        if self.sel not in self._info:                       # an import replaces a standard under a new id: stay on the same model
            self.sel = next((i for i, v in self._info.items() if v['std']['model'] == model), stds[0]['id'] if stds else None)
        self.pick()

    def select(self, sid):
        if sid == self.sel or sid not in self._info:
            return
        self.sel = sid
        self.kind.set(self.kind.get() if self.kind.get() in {k for k, _t, _n, _f in view.kind_chips(sm.rows_of(sid))} else '')
        self.pick()

    def _step(self, d):
        ids = [s for s in self._info]
        if self.sel in ids:
            self.select(ids[max(0, min(len(ids) - 1, ids.index(self.sel) + d))])
        return 'break'

    def _pick_chosen(self, _e=None):
        model = self.pick_var.get()
        for sid, i in self._info.items():
            if i['std']['model'] == model:
                self.select(sid)

    def pick(self):
        """Show the selected standard: rail highlight, header, chips and table."""
        has = self.sel is not None
        for sid, card in self._cards.items():
            card.set_selected(sid == self.sel)
        if has:
            self.empty_all.grid_remove()
            self.head_card.grid()
            self.table_card.grid()
            self._load_rows()
            self.show_rows()
            self._fill_header()
            self.pick_var.set(self._info[self.sel]['std']['model'])
            self.after_idle(self._ensure_visible)
        else:
            self._rows, self._periods = [], []
            self.show_rows()
            self.head_card.grid_remove()
            self.table_card.grid_remove()
            self.empty_all.grid(row=1, column=0, rowspan=2, sticky='nsew')
        self._placeholder()

    def _ensure_visible(self):
        """Scroll the rail so the selected card is in view (does nothing before the rail has been laid out)."""
        card = self._cards.get(self.sel)
        view_h = self.rail_cv.winfo_height()
        if not card or view_h < 60:
            return
        self.update_idletasks()
        total = max(1, self.rail_inner.winfo_reqheight())
        top, bottom, cur = card.winfo_y(), card.winfo_y() + card.winfo_reqheight(), self.rail_cv.canvasy(0)
        if top < cur:
            self.rail_cv.yview_moveto(top / total)
        elif bottom > cur + view_h:
            self.rail_cv.yview_moveto((bottom - view_h) / total)

    def _load_rows(self):
        self._rows = sm.rows_of(self.sel)
        std = self._info[self.sel]['std']
        self._periods, self._other_periods = view.period_columns(self._rows, std.get('period') or '1 yr')
        for i, pid in enumerate(PERIOD_IDS):
            self.rows.heading(pid, text=(view.period_heading(self._periods[i]) if i < len(self._periods) else ''))
        self._fit_columns()
        self._build_chips()

    def _build_chips(self):
        self._chip_specs = view.kind_chips(self._rows)
        self._chip_width = 0
        self._render_chips()

    def _render_chips(self):
        """One row of function-type chips; the ones that do not fit go under a 'More' chip (a menu), the active one is always shown."""
        self.chip_flow.clear()
        self._chips = {}
        f = self.fonts['filter']
        width = self.chip_flow.winfo_width()
        if width < 60:
            width = 10 ** 4
        self._chip_width = width
        height = f.metrics('linespace') + ui.px(10)
        gap = ui.px(5)
        cw = lambda text, n: f.measure(text) + f.measure('  ' + str(n)) + 2 * ui.px(9)  # noqa: E731
        specs = self._chip_specs
        active = self.kind.get()
        more_w = f.measure('More  99') + 2 * ui.px(9) + ui.px(12)
        shown, used = [], 0
        for spec in specs:
            need = cw(spec[1], spec[2]) + gap
            if used + need + (more_w if len(shown) < len(specs) - 1 else 0) > width and shown:
                break
            shown.append(spec)
            used += need
        hidden = [sp for sp in specs if sp not in shown]
        if hidden and active and all(sp[0] != active for sp in shown):                 # keep the chosen type visible
            swap = next(sp for sp in hidden if sp[0] == active)
            hidden.remove(swap)
            hidden.append(shown.pop())
            shown.append(swap)
        for code, text, n, full in shown:
            chip = Chip(self.chip_flow, text, font=f, bg=ui.C['card'], count=n, active=(active == code), command=lambda c=code: self.kind.set(c), height=height)
            ui.Tooltip(chip, full)
            self._chips[code] = chip
            self.chip_flow.add(chip)
        if hidden:
            more = Chip(self.chip_flow, f'More  {len(hidden)}', font=f, bg=ui.C['card'], count=None, height=height, command=lambda: self._more_menu(hidden, more))
            self.chip_flow.add(more)

    def _more_menu(self, hidden, anchor):
        menu = tk.Menu(self, tearoff=False)
        for code, text, n, full in hidden:
            menu.add_command(label=f'{text}   {n}   ({full})', command=lambda c=code: self.kind.set(c))
        menu.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def _chips_resized(self, e):
        if abs(e.width - self._chip_width) > ui.px(6) and getattr(self, '_chip_specs', None):
            self.after_idle(self._render_chips)

    def _kind_changed(self):
        if self.kind.get() not in self._chips:                       # a type that sits under 'More' (or was set from outside): bring it into the row
            self._render_chips()
        for code, chip in self._chips.items():
            chip.set_active(code == self.kind.get())
        self.show_rows()

    def _fill_header(self):
        C, f = ui.C, self.fonts
        i = self._info[self.sel]
        s = i['std']
        self.h_title.configure(text=s['model'])
        maker = s['manufacturer']
        self._desc_full = ' \u00b7  '.join(x for x in (maker, view.description_of(s)) if x)
        self._fit_text(self.h_desc, self._desc_full, f['normal'])
        value, note, stated = view.confidence_summary(s['confidence_text'], s['confidence_pct'])
        full_conf = s['confidence_text'] or 'The sheet does not state a confidence level; k = 2 is assumed.'
        self._set_stat('conf', value, note, full_conf, C['text'] if stated else C['muted'])
        self._set_stat('div', view.divisor_text(i['div']), i['why'], i['why'], C['primary'])
        self._shown_n = -1
        self._period_stat()
        self._set_stat('ranges', str(len(self._rows)), view.ranges_note(self._rows), view.ranges_note(self._rows), C['text'])
        self.facts.clear()
        lab = lambda t, c=C['muted'], font=f['small']: tk.Label(self.facts, text=t, font=font, foreground=c, background=C['card'])  # noqa: E731
        self.facts.add(lab('Assets'), gap=ui.px(10))
        if i['assets']:
            for a, serial in i['assets']:
                self.facts.add(Chip(self.facts, f'{a}  {view.DOT}  {serial}' if serial else a, font=f['small'], bg=C['card'], height=f['small'].metrics('linespace') + ui.px(8)))
        else:
            self.facts.add(lab('none set'), gap=ui.px(4))
        self.facts.add(Link(self.facts, 'Set assets...', self.set_assets, f['smallb']), gap=ui.px(22))
        appr = tk.Frame(self.facts, background=C['card'])
        tk.Label(appr, text='Approved', font=f['small'], foreground=C['muted'], background=C['card']).pack(side='left', padx=(0, ui.px(8)))
        tk.Label(appr, text=view.approved_text(s), font=f['small'], foreground=C['text'], background=C['card']).pack(side='left')
        self.facts.add(appr, gap=ui.px(22))
        n = len(i['problems'])
        self.issues_chip = Chip(self.facts, view.issues_text(n) + '  \u203a', kind=view.issues_kind(i['problems']), font=f['small'], bg=C['card'], dot=True, command=self.show_issues,
                                height=f['small'].metrics('linespace') + ui.px(8))
        ui.Tooltip(self.issues_chip, 'Show what was found when the specification sheet was read')
        self.facts.add(self.issues_chip)

    def _period_stat(self):
        """The Period block: the default period, and which period columns the table shows (the rest are named, not hidden from the reader)."""
        n = len(view.shown_periods(self._periods, self.rows.winfo_width() / max(1.0, ui.SCALE))) if self.rows.winfo_width() > 60 else len(self._periods)
        self._shown_n = n
        note = view.period_note(self._periods[:n], self._periods[n:] + self._other_periods)
        self._set_stat('period', self._info[self.sel]['std']['period'] or '', note, note, ui.C['text'])

    def _set_stat(self, key, value, sub, full, colour):
        st = self.stat[key]
        st['val'].configure(text=value, foreground=colour)
        st['sub_text'], st['tip'] = sub, full
        st['sub'].configure(text=sub)
        self._fit_stat(key)

    # ----------------------------------------------------------------------------------------------------
    def show_rows(self):
        tree = self.rows
        tree.delete(*tree.get_children())
        self._tips, self._group_keys, self._full = {}, {}, {}
        if self.sel is None:
            self.empty.place_forget()
            self.count_lbl.configure(text='')
            return
        kind, term = self.kind.get(), self.term.get().strip()
        shown = [r for r in self._rows if view.matches(r, kind, term)]
        closed = self._closed.setdefault(self.sel, set())
        for gi, (key, title, rs) in enumerate(view.group_rows(shown)):
            gid = f'g{gi}'
            is_open = key not in closed or bool(term)
            tree.insert('', 'end', iid=gid, text=self._cut(title, ui.px(30)), image=self._chevrons()[is_open], open=is_open, tags=('band',),
                        values=(f"{len(rs)} range{'' if len(rs) == 1 else 's'}", '', '', '', '', ''))
            self._tips[gid] = {'range': title}
            self._group_keys[gid] = (key, title)
            self._full[gid] = (title, ui.px(30))
            last = None
            for n, r in enumerate(rs):
                rng, qual = view.split_label(r['label'])
                cells = [view.spec_cell(r, p) for p in self._periods]
                vals = [view.span_text(r), view.freq_text(r), view.resolution_text(r)] + [c[0] for c in cells] + [''] * (3 - len(cells))
                tree.insert(gid, 'end', iid=str(r['id']), text=self._cut(rng, ui.px(26)) if rng != last else '', values=vals, tags=('odd' if n % 2 else 'even',))
                self._full[str(r['id'])] = (rng, ui.px(26))
                tip = {'range': r['label'], 'freq': r['label'] if qual else ''}
                for pid, (_t, raw) in zip(PERIOD_IDS, cells):
                    tip[pid] = raw
                self._tips[str(r['id'])] = tip
                last = rng
        self.count_lbl.configure(text=view.shown_count_text(len(shown), len(self._rows)))
        if shown:
            self.empty.place_forget()
        else:
            msg, can_clear = view.empty_message(len(self._rows), kind, term)
            self.empty_msg.configure(text=msg)
            if can_clear:
                self.empty_clear.pack(pady=(ui.px(6), 0))
            else:
                self.empty_clear.pack_forget()
            self.empty.place(relx=0.5, rely=0.3, anchor='center')
            self.empty.lift()

    def _chevrons(self):
        """Open / closed marks of the group bands: small triangles drawn as images, so no font needs the glyphs."""
        if not hasattr(self, '_chev'):
            n = ui.px(9) | 1
            m = n // 2
            col = ui.C['muted']
            down, right = tk.PhotoImage(master=self, width=n, height=n), tk.PhotoImage(master=self, width=n, height=n)
            for i in range(m + 1):
                down.put(col, to=(i, i + 1, n - i, i + 2))                 # a row that narrows downwards
                right.put(col, to=(i + 1, i, i + 2, n - i))                # a column that narrows to the right
            self._chev = {True: down, False: right}
        return self._chev

    def _toggle_group(self, gid, state=None):
        tree = self.rows
        key = self._group_keys[gid][0]
        is_open = (not tree.item(gid, 'open')) if state is None else state
        tree.item(gid, open=is_open, image=self._chevrons()[is_open])
        closed = self._closed.setdefault(self.sel, set())
        (closed.discard if is_open else closed.add)(key)

    def set_all_groups(self, is_open):
        for gid in self.rows.get_children(''):
            if gid in self._group_keys:
                self._toggle_group(gid, is_open)

    def clear_filters(self):
        self.term.set('')
        self.kind.set('')

    def _click(self, e):
        iid = self.rows.identify_row(e.y)
        if iid and iid.startswith('g') and self.rows.identify_region(e.x, e.y) in ('tree', 'cell'):
            self._toggle_group(iid)
            return 'break'

    def _double_click(self, e):
        iid = self.rows.identify_row(e.y)
        if iid and iid.isdigit():
            self.rows.selection_set(iid)
            self.edit_resolution(int(iid))
        elif iid in self._group_keys:                  # a fast second click on a band is a double-click: it still toggles
            self._toggle_group(iid)
        return 'break'

    # ----------------------------------------------------------------------------------------------------
    def _who(self):
        import getpass
        try:
            return getpass.getuser()
        except Exception:
            return ''

    def set_divisor(self):
        if self.sel is None:
            return
        cur = sm.standard(self.sel).divisor()[0]
        txt = simpledialog.askstring('Coverage divisor', 'Divisor that turns the published accuracy into a standard uncertainty (k = 1).\n'
                                     'Common: 2 (95 % treated as k = 2), 1.96, 2.576 (99 %), 1.732 (rectangular).\nBlank = use the sheet\'s confidence level.',
                                     initialvalue=f'{cur:g}', parent=self)
        if txt is None:
            return
        try:
            val = float(txt) if txt.strip() else None
            if val is not None and not 1.0 <= val <= 4.0:
                raise ValueError
        except ValueError:
            messagebox.showerror('Divisor', 'Enter a number between 1 and 4.', parent=self)
            return
        reason = simpledialog.askstring('Reason', 'Reason for the change (kept in the change log):', parent=self) or ''
        sm.set_standard_field(self.sel, 'divisor', val, who=self._who(), reason=reason)
        self.refresh()

    def set_assets(self):
        if self.sel is None:
            return
        cur = '; '.join(f'{a}:{s}' for a, s in sm.assets_of(self.sel))
        txt = simpledialog.askstring('Assets', 'Instrument IDs of the units of this model used as standards.\nFormat  ID:serial; ID:serial', initialvalue=cur, parent=self)
        if txt is None:
            return
        pairs = []
        for part in txt.split(';'):
            if part.strip():
                a, _, s = part.partition(':')
                pairs.append((a.strip(), s.strip()))
        sm.set_assets(self.sel, pairs)
        self.refresh()

    def edit_resolution(self, rid=None):
        if rid is None:
            sel = self.rows.selection()
            if not sel or not sel[0].isdigit():            # nothing selected, or a function group band
                return
            rid = int(sel[0])
        row = next((r for r in sm.rows_of(self.sel) if r['id'] == rid), None)
        if not row:
            return
        txt = simpledialog.askstring('Calibrator resolution', f"Resolution of the calibrator on '{row['label']}' in {row['unit'] or 'SI base units'} "
                                     '(the last digit it can set).\nBlank = not recorded.', initialvalue=f"{row['resolution']:g}" if row['resolution'] else '', parent=self)
        if txt is None:
            return
        try:
            val = float(txt) if txt.strip() else None
            if val is not None and val <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('Resolution', 'Enter a positive number in SI base units (V, A, ohm, F, Hz).', parent=self)
            return
        sm.update_row(rid, {'resolution': val}, who=self._who(), reason='resolution entered in the manager')
        self._rows = sm.rows_of(self.sel)
        top = self.rows.yview()[0]
        self.show_rows()
        if self.rows.exists(str(rid)):
            self.rows.selection_set(str(rid))
            self.rows.yview_moveto(top)

    def show_issues(self):
        if self.sel is None:
            return
        probs = sm.problems_of(self.sel)
        model = self._info[self.sel]['std']['model'] if self.sel in self._info else ''
        win = ui.dialog(self, f'Sheet issues found when the {model} specification was read', modal=False)
        txt = tk.Text(win, width=130, height=28, wrap='word', background=ui.C['field'], foreground=ui.C['text'], insertbackground=ui.C['text'],
                      relief='flat', padx=12, pady=10, borderwidth=0, highlightthickness=0)
        txt.pack(fill='both', expand=True)
        txt.insert('end', '\n\n'.join(f"[{p.get('level', '')}] {p.get('where', '')}: {p.get('what', '')}" for p in probs) or 'None found.')
        txt.configure(state='disabled')
        self.issues_window = win

    def import_json(self):
        f = filedialog.askopenfilename(parent=self, filetypes=[('Spec JSON', '*.json')])
        if not f:
            return
        try:
            data = json.load(open(f, encoding='utf-8'))
            if not sm.import_data(data, who=self._who()):
                raise ValueError('not a specification file')
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror('Import', f'Could not import: {e}', parent=self)
            return
        self.refresh()

    def export_json(self):
        if self.sel is None:
            return
        f = filedialog.asksaveasfilename(parent=self, defaultextension='.json')
        if f:
            json.dump(sm.export_data(self.sel), open(f, 'w', encoding='utf-8'), indent=1)

    # ----------------------------------------------------------------------------------------------------
    def check_emu(self):
        if self.sel is None:
            return
        CheckDialog(self, sm.standard(self.sel))


class CheckDialog(tk.Toplevel):
    """Enter an applied point and the EMU that was reported; shows the budget and whether the report is below the scope CMC or the budget."""
    def __init__(self, parent, standard):
        super().__init__(parent)
        self.title(f'Check a reported EMU - {standard.model}')
        self.std = standard
        self.v = {k: tk.StringVar(value=d) for k, d in (('kind', 'DCV'), ('nominal', ''), ('freq', ''), ('reported', ''), ('res', ''), ('typea', ''))}
        g = ttk.Frame(self, padding=12)
        g.pack(fill='both', expand=True)
        for i, (lab, key, hint) in enumerate((('Function', 'kind', ''), ('Nominal (SI: V, A, ohm, F, Hz)', 'nominal', 'e.g. 0.1'), ('Frequency (Hz)', 'freq', 'AC only'),
                                              ('Reported EMU (SI units, k = 2)', 'reported', 'e.g. 3e-6'), ('Calibrator resolution (SI)', 'res', 'blank = from the sheet'),
                                              ('Type A std. uncertainty (SI, k = 1)', 'typea', 'repeatability, blank = none'))):
            ttk.Label(g, text=lab).grid(row=i, column=0, sticky='w', pady=2)
            if key == 'kind':
                ttk.Combobox(g, textvariable=self.v[key], values=[k for k in KINDS if k][:7] + ['FREQ'], width=10, state='readonly').grid(row=i, column=1, sticky='w')
            else:
                ttk.Entry(g, textvariable=self.v[key], width=16).grid(row=i, column=1, sticky='w')
            ttk.Label(g, text=hint, style='Small.TLabel').grid(row=i, column=2, sticky='w', padx=6)
        ttk.Button(g, text='Check', style='Accent.TButton', command=self.run).grid(row=7, column=0, pady=8, sticky='w')
        self.out = tk.Text(g, width=96, height=14, wrap='word')
        self.out.grid(row=8, column=0, columnspan=3)

    def _num(self, key, required=False):
        t = self.v[key].get().strip()
        if not t:
            if required:
                raise ValueError(key)
            return None
        return float(t)

    def run(self):
        try:
            nominal, reported = self._num('nominal', True), self._num('reported', True)
            freq, res, ta = self._num('freq'), self._num('res'), self._num('typea')
        except ValueError:
            messagebox.showerror('Check', 'Enter numbers (nominal and reported are required).', parent=self)
            return
        kind = self.v['kind'].get()
        b = ub.build(kind, nominal, UNITS.get(kind, ''), standard=self.std, frequency=freq, resolution=res, type_a=[('Type A', ta, 1.0)] if ta else [])
        status, text = ub.audit(reported, b)
        lines = [f'{status}: {text}', '']
        for c in b.components:
            lines.append(f'  {c.name:28s} u = {c.u:.4g}   ({c.source})')
        if b.emu is not None:
            lines.append(f'  Expanded (k = {b.k:g}): {b.emu:.4g}')
        lines.append(f'  Scope CMC: {b.cmc:.4g}' if b.cmc is not None else '  Scope CMC: not covered')
        if b.reported is not None:
            lines.append(f'  Smallest value that may be reported: {b.reported:.4g}')
        lines += [f'  Note: {n}' for n in b.notes]
        self.out.delete('1.0', 'end')
        self.out.insert('end', '\n'.join(lines))
