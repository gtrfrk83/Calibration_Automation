"""Handheld meter engine (handheld_dmm.App, iflex_option.App and the user-built datasheets): the Tk window code.

Moved out of handheld_dmm.py unchanged: the main window (`build_ui`, `sync_buttons`, the results-table helpers) and the four modal windows the technician works in
(`ask_reading` - the reading window, `ask_readings` is run_queue_ui's - `ask_ir_problem`, `ask_range`).  Only the small helper functions at the end of the window code are
new, each the exact statements the engine used to make on `self.tree` / `self.cal_entry`.  The engine reaches this module through `ui_port.ui.view('handheld_dmm_view')`
(window functions, first parameter the engine's App) and, for the modal windows, through `ui_port.ui.ask_reading / ask_range / ask_ir_problem`, which TkUiPort sends here;
a Qt port provides `handheld_dmm_view_qt` with the same functions.  Nothing here decides anything about a calibration.
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import ttk

import calibrator_fit
import datamode
import labregistry
import ui_shell
import ui_theme as ui
import virtualbench
from handheld_dmm import HERE, OUTPUT_ON_NOTE, READING_WIDTH, describe, limit_line


def setup_window(self):
    """Theme, title and size of the main window (the first window statements of the engine's former App.__init__)."""
    root = self.root
    ui.apply_theme(root)
    root.title(f'{self.info["name"]} | Performance Verification' + (' [DEMO]' if self.demo else ''))
    ui.fit_window(root, 1320, 800, min_w=1000, min_h=640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statement of the engine's former App.__init__)."""
    labregistry.attach(self.root, self.asset, self.serial, self.status.set)


def build_ui(self):
    from handheld_dmm import READ_TYPED, READ_IR                    # the engine's constants, read at call time
    root = self.root
    src = self.spec['source']
    sh = self.shell = ui_shell.Shell(root, f'{self.info["name"]}  -  Performance Verification',
                                     f'Manual-reading procedure: the calibrator output is set for you, you read the meter  |  {len(self.points)} points  |  {src["document"]}',
                                     demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    if self.queue_supported():
        self.queue_pill = ui.Pill(sh.chip_frame, '', 'info')           # 'Run queue: n meters', shown only while a queue of two or more is set
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo:
        sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else:
        extra = ' You are prompted to turn the dial to each range and to change cables, with a hook-up diagram.' if self.spec.get('options', {}).get('range_prompt') else ''
        sh.notice('For each point the calibrator is programmed and enabled, then you read the meter and type the value exactly as displayed (without the unit). '
                  'Wiring and high-voltage confirmations are required.' + extra + ' Check the meter fuses and battery before starting.', 'info')

    d = sh.drawer_body; d.columnconfigure(1, weight=1)
    ttk.Label(d, text='Model').grid(row=0, column=0, sticky='w', pady=4)
    ttk.Label(d, text=self.info['name'], style='Bold.TLabel').grid(row=0, column=1, sticky='w', padx=(10, 0))
    ttk.Label(d, text=self.info.get('model_note', 'the "C" version uses the same steps'), style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=1, column=0, columnspan=2, sticky='w')
    ttk.Separator(d).grid(row=2, column=0, columnspan=2, sticky='ew', pady=(10, 10))
    ttk.Label(d, text='Calibrator').grid(row=3, column=0, sticky='w', pady=4)
    calbox = ttk.Frame(d)
    calbox.grid(row=3, column=1, sticky='ew', padx=(10, 0), pady=4)
    self.cal_combo = ttk.Combobox(calbox, textvariable=self.cal_mode, values=self.cal_choices(), state='readonly', width=34)
    self.cal_combo.pack(fill='x')
    calibrator_fit.attach_note(calbox, self.cal_offer, ui, widgets=(self.cal_combo,), wrap=250)
    ttk.Label(d, text='Address').grid(row=4, column=0, sticky='w', pady=4)
    self.cal_entry = ttk.Combobox(d, textvariable=self.cal_addr, state='normal', width=34)
    self.cal_entry.grid(row=4, column=1, sticky='ew', padx=(10, 0), pady=4)
    ttk.Label(d, text='Baud').grid(row=5, column=0, sticky='w', pady=4)
    ttk.Combobox(d, textvariable=self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=5, column=1, sticky='w', padx=(10, 0), pady=4)
    ttk.Label(d, text='Examples: COM9   ASRL9::INSTR   GPIB0::6::INSTR.  In Manual mode the program tells you what to set and you press OPERATE yourself.',
              style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=6, column=0, columnspan=2, sticky='w', pady=(6, 0))
    if self.ir:
        ttk.Separator(d).grid(row=7, column=0, columnspan=2, sticky='ew', pady=(12, 10))
        ttk.Label(d, text='Meter reading').grid(row=8, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.read_mode, values=[READ_TYPED, READ_IR], state='readonly', width=34).grid(row=8, column=1, sticky='ew', padx=(10, 0), pady=4)
        ttk.Label(d, text='IR cable port').grid(row=9, column=0, sticky='w', pady=4)
        irrow = ttk.Frame(d); irrow.grid(row=9, column=1, sticky='w', padx=(10, 0))
        ttk.Entry(irrow, textvariable=self.ir_addr, width=9).pack(side='left', padx=(0, 8))
        self.btn_ir = ttk.Button(irrow, text='Test IR', command=self.test_ir); self.btn_ir.pack(side='left')
        ttk.Label(d, text='Read over IR needs the Fluke IR-to-USB cable on the meter\'s IR port (115200 baud). Without it, choose Type the reading.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=10, column=0, columnspan=2, sticky='w', pady=(6, 0))
    if self.virtual:
        ttk.Separator(d).grid(row=11, column=0, columnspan=2, sticky='ew', pady=(12, 10))
        self.demo_failures = tk.BooleanVar(value=False)
        ttk.Checkbutton(d, text='Demo: include some failures in the simulated fill', variable=self.demo_failures).grid(row=12, column=0, columnspan=2, sticky='w')
        ttk.Label(d, text='The calibrator is a virtual 5522A / 5560A (simulated). Press Test connection to connect it; no cable or address is needed. '
                          'The "Fill with a simulated reading" button in the reading window enters a made-up value; you may type your own.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=13, column=0, columnspan=2, sticky='w', pady=(6, 0))
    if self.queue_supported():
        self.build_queue_drawer(d, 14)
    btns = sh.drawer_footer
    self.btn_find = ttk.Button(btns, text='Find instruments', command=self.find_instruments); self.btn_find.pack(side='left', padx=(0, 8))
    self.btn_test = ttk.Button(btns, text='Test connection', command=self.test_connection, style='Accent.TButton'); self.btn_test.pack(side='left')

    self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
    self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
    self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
    self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
    sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
    self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
    sh.add_action('Save progress', self.save, side='right', short='Save')
    self.pm_live_attach(sh)                                    # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well, usable during a run

    body = sh.content
    info = ttk.Frame(body); info.pack(side='bottom', fill='x', pady=(8, 0))
    ttk.Label(info, textvariable=self.detail, wraplength=1000, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
    ttk.Label(info, text=src['note'], style='Small.TLabel', wraplength=1000, justify='left').pack(anchor='w', pady=(4, 0))
    filt = ttk.Frame(body); filt.pack(side='top', fill='x', pady=(0, 6))
    ttk.Label(filt, text='Test points', style='Bold.TLabel').pack(side='left')
    c2 = ttk.Combobox(filt, textvariable=self.show_status, values=datamode.STATUS_FILTERS, width=14, state='readonly'); c2.pack(side='right')
    ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='right', padx=(0, 6))
    c2.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
    self.tree = ui_shell.results_table(self, body, name_width=330, nominal_title='Calibrator output', error=False)
    self.tree.column('nominal', width=ui.px(150))
    ui_shell.small_window(self, self.tree, filt)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    self.refresh()
    ui.polish(root)


def sync_buttons(self, value):
    """The run buttons while a run is active (the engine's former `busy` setter body)."""
    idle = 'disabled' if value else 'normal'
    for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
        b.configure(state=idle)
    self.btn_stop.configure(state='normal' if value else 'disabled')


# ---- results table and address box: the exact statements the engine used to make on self.tree / self.cal_entry
def table_selection(self):
    return self.tree.selection()


def table_has(self, iid):
    return self.tree.exists(iid)


def table_select(self, iid, see=False):
    self.tree.selection_set(iid)
    if see:
        self.tree.see(iid)


def table_set_rows(self, rows, keep):
    """rows: iterable of (iid, values, tags); keep: the selection before the refresh (the first row of it is selected again if it is still there)."""
    self.tree.delete(*self.tree.get_children())
    for iid, values, tags in rows:
        self.tree.insert('', 'end', iid=iid, values=values, tags=tags)
    if keep and self.tree.exists(keep[0]):
        self.tree.selection_set(keep[0])


def table_update_row(self, iid, values, tags):
    self.tree.item(iid, values=values, tags=tags)


def set_choices(self, which, values):
    """The drop-down values of the calibrator address box ('cal')."""
    self.cal_entry['values'] = values


# ============================================================================ the reading dialog
def ask_reading(parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None):
    """One modal dialog. mode 'numeric' (type the display) or 'yesno' (answer a question).
    Returns dict(action='record'|'skip'|'stop', text=, ann=, yes=)."""
    result = dict(action='stop', text='', ann=False, yes=None)
    win = ui.dialog(parent, f'Point {p["n"]} of {total}')
    win.resizable(False, False)
    C = ui.C
    outer = tk.Frame(win, background=C['bg'])
    outer.pack(fill='both', expand=True, padx=ui.px(22), pady=(ui.px(16), ui.px(14)))
    outer.grid_columnconfigure(0, weight=1)
    width = ui.px(READING_WIDTH)
    wrap_all = width
    sty = ttk.Style(win)                       # ttk widgets inside the white cards take the card colour
    for name, base in (('ReadCard.TCheckbutton', 'TCheckbutton'), ('ReadCard.TRadiobutton', 'TRadiobutton')):
        sty.configure(name, background=C['card'])
    row_n = [0]

    def put(widget, pady=(0, 0)):
        widget.grid(row=row_n[0], column=0, sticky='ew', pady=pady)
        row_n[0] += 1

    def label(parent, text, fg=None, font=None, bg=None, wrap=None, **kw):
        return tk.Label(parent, text=text, background=bg or C['bg'], foreground=fg or C['text'], font=font or 'TkDefaultFont', anchor='w',
                        justify='left', wraplength=wrap or wrap_all, **kw)
    put(label(outer, f'Point {p["n"]} of {total}  -  {p["section"]}' + (f'  -  {phase}' if phase else ''), fg=C['muted'], font='CalSmall'))
    put(label(outer, describe(p), font='CalH2', fg=C['navy']), pady=(2, 10))

    def row_card(caption, big, note, kind, big_font='CalBold'):
        """A rounded card: a marker circle, the caption in muted capitals, the main text, an optional muted second text."""
        def build(inner, wrap):
            mark = ui.status_circle(inner, kind, background=C['card'])
            mark.grid(row=0, column=0, rowspan=3, sticky='n', padx=(0, ui.px(12)))
            tw = wrap - ui.px(22) - ui.px(12)
            label(inner, caption, fg=C['muted'], font='CalSmallBold', bg=C['card'], wrap=tw).grid(row=0, column=1, sticky='w')
            label(inner, big, font=big_font, bg=C['card'], wrap=tw).grid(row=1, column=1, sticky='w')
            if note:
                label(inner, note, fg=C['muted'], font='CalSmall', bg=C['card'], wrap=tw).grid(row=2, column=1, sticky='w')
        put(ui.rounded_card(outer, width, build), pady=(0, ui.px(8)))
    meter = p.get('dsb_device') or (f'Rotary switch / function: {p["switch"]}' + (f'\nRange: {p["range"]}' if p['range'] else ''))
    row_card(device, meter, p.get('note'), 'done')                  # the operator has just confirmed the meter set-up (function / hook-up prompts)
    if p.get('applied') or p['group'] != 'NONE':
        row_card(source, out_text, out_note, 'done' if str(out_note).startswith(OUTPUT_ON_NOTE) else 'todo', big_font='CalMetric')
    counter = tk.StringVar()
    clock = {'job': None, 'expired': False}
    if limit_s is not None:
        tk.Label(outer, textvariable=counter, foreground=C.get('bad', '#B3261E'), background=C['bg'], font='CalBold', anchor='w', wraplength=wrap_all,
                 justify='left').grid(row=row_n[0], column=0, sticky='ew', pady=(0, 8))
        row_n[0] += 1
        end = time.monotonic() + max(0.0, limit_s)

        def tick():
            try:
                left = end - time.monotonic()
                if left <= 0:
                    if not clock['expired']:
                        clock['expired'] = True
                        if on_expire:
                            on_expire()
                    counter.set('Time limit reached - the output has been switched off. Enter the reading you saw.' if on_expire
                                else 'Time limit reached - put the calibrator in STANDBY now, then enter the reading.')
                    return
                counter.set(f'Take the reading within {left:.0f} s - the output switches off automatically.' if on_expire
                            else f'Take the reading within {left:.0f} s, then put the calibrator in STANDBY.')
                clock['job'] = win.after(250, tick)
            except tk.TclError:
                pass
        tick()

    entry = None
    yes = tk.StringVar(value='')
    ann = tk.BooleanVar(value=False)
    error = tk.StringVar(value='')
    text = tk.StringVar()
    fillers = {}

    def reading_card(inner, wrap):
        nonlocal entry
        nonlocal_bg = C['card']
        if mode == 'numeric':
            label(inner, f'WHAT DOES THE {device} SHOW?', fg=C['primary'], font='CalSmallBold', bg=nonlocal_bg, wrap=wrap).pack(anchor='w')
            row = tk.Frame(inner, background=nonlocal_bg)
            row.pack(fill='x', pady=(6, 0))
            entry = ttk.Entry(row, textvariable=text, font='CalMetric', width=14)
            entry.pack(side='left')
            label(row, unit, font='CalH2', bg=nonlocal_bg, wrap=wrap).pack(side='left', padx=(10, 0))
            if annunciator:
                ttk.Checkbutton(inner, text='The AC annunciator is ON', variable=ann, style='ReadCard.TCheckbutton').pack(anchor='w', pady=(6, 0))
        else:
            label(inner, 'YOUR ANSWER', fg=C['primary'], font='CalSmallBold', bg=nonlocal_bg, wrap=wrap).pack(anchor='w')
            label(inner, question, font='CalBold', bg=nonlocal_bg, wrap=wrap).pack(anchor='w', pady=(6, 4))
            row = tk.Frame(inner, background=nonlocal_bg)
            row.pack(anchor='w')
            ttk.Radiobutton(row, text='Yes - as stated', variable=yes, value='y', style='ReadCard.TRadiobutton').pack(side='left')
            ttk.Radiobutton(row, text='No - it does not', variable=yes, value='n', style='ReadCard.TRadiobutton').pack(side='left', padx=(16, 0))
        label(inner, '', fg=C.get('bad', '#B3261E'), bg=nonlocal_bg, wrap=wrap, textvariable=error).pack(anchor='w')
        label(inner, 'ACCEPT IF', fg=C['muted'], font='CalSmallBold', bg=nonlocal_bg, wrap=wrap).pack(anchor='w', pady=(6, 0))
        label(inner, accept, font='CalBold', bg=nonlocal_bg, wrap=wrap).pack(anchor='w')
        if p.get('tol_text'):
            label(inner, 'Limit: ' + limit_line(p), fg=C['muted'], font='CalSmall', bg=nonlocal_bg, wrap=wrap).pack(anchor='w')
        if demo_fill is not None:                   # demo only: a clearly marked helper; the operator may type anything instead
            def fill():
                value = demo_fill()
                if mode == 'numeric':
                    text.set(value)
                    entry.focus_set()
                else:
                    yes.set('y' if value else 'n')
            ttk.Button(inner, text=virtualbench.FILL_TEXT, command=fill).pack(anchor='w', pady=(10, 0))
            label(inner, 'DEMO: this value is made up by the program; you may type any reading you like. Nothing here is calibration evidence.',
                  fg=C.get('warn', '#B26A00'), font='CalSmall', bg=nonlocal_bg, wrap=wrap).pack(anchor='w', pady=(4, 0))
    put(ui.rounded_card(outer, width, reading_card, outline=C['primary'], outline_w=2, radius=10, pad=(16, 12)), pady=(ui.px(4), 0))

    def done(action):
        result['action'] = action
        if clock['job']:
            try:
                win.after_cancel(clock['job'])
            except tk.TclError:
                pass
        if action == 'record':
            if mode == 'numeric':
                try:
                    if validate:
                        validate(text.get())
                except ValueError as exc:
                    error.set(str(exc))
                    return
                result.update(text=text.get(), ann=ann.get())
            else:
                if not yes.get():
                    error.set('Choose Yes or No.')
                    return
                result['yes'] = yes.get() == 'y'
        win.destroy()

    bar = tk.Frame(outer, background=C['bg'])
    bar.grid(row=row_n[0], column=0, sticky='ew', pady=(ui.px(16), 0))
    bar.grid_columnconfigure(1, weight=1)
    ok = ttk.Button(bar, text='Record  (Enter)', style='Accent.TButton', command=lambda: done('record'))
    ok.grid(row=0, column=3)
    ttk.Button(bar, text='Skip point', command=lambda: done('skip')).grid(row=0, column=2, padx=(0, 8))
    ttk.Button(bar, text='Stop run', style='Danger.TButton', command=lambda: done('stop')).grid(row=0, column=0)
    win.bind('<Return>', lambda _e: done('record'))
    win.protocol('WM_DELETE_WINDOW', lambda: done('stop'))
    ui.center_on(win, parent.winfo_toplevel())
    (entry or ok).focus_set()
    win.wait_window()
    return result


# ============================================================================ the IR set-up / reading problem dialog
def ask_ir_problem(parent, p, total, problems, shown):
    """The meter (read over IR) is not set up as the point needs, or the reading did not settle.
    Returns 'retry', 'type' (type this reading instead), 'skip' or 'stop'."""
    result = {'v': 'stop'}
    win = ui.dialog(parent, f'Point {p["n"]} of {total} - check the meter')
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(ui.px(22), ui.px(16), ui.px(22), ui.px(14)))
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=f'Point {p["n"]} of {total}  -  {p["section"]}', style='Small.TLabel').pack(anchor='w')
    ttk.Label(outer, text='The meter is not ready for this point', style='Section.TLabel').pack(anchor='w', pady=(2, 8))
    for line in problems:
        ttk.Label(outer, text='•  ' + line, style='Bold.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w')
    ttk.Label(outer, text='METER SHOULD BE', style='MetricCap.TLabel').pack(anchor='w', pady=(10, 0))
    ttk.Label(outer, text=f'{p["switch"]}' + (f', range {p["range"]}' if p['range'] else ''), wraplength=ui.px(520), justify='left').pack(anchor='w')
    if shown:
        ttk.Label(outer, text='METER REPORTS', style='MetricCap.TLabel').pack(anchor='w', pady=(8, 0))
        ttk.Label(outer, text=shown, style='Small.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w')
    ttk.Label(outer, text='The calibrator is in STANDBY. Fix the meter and press Re-check: the output is set again and the meter re-read.',
              style='Small.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w', pady=(10, 0))

    def done(value):
        result['v'] = value
        win.destroy()
    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(14, 0))
    ok = ttk.Button(bar, text='Re-check  (Enter)', style='Accent.TButton', command=lambda: done('retry'))
    ok.pack(side='right')
    ttk.Button(bar, text='Type the reading instead', command=lambda: done('type')).pack(side='right', padx=(0, 8))
    ttk.Button(bar, text='Skip point', command=lambda: done('skip')).pack(side='right', padx=(0, 8))
    ttk.Button(bar, text='Stop run', style='Danger.TButton', command=lambda: done('stop')).pack(side='left')
    win.bind('<Return>', lambda _e: done('retry'))
    win.protocol('WM_DELETE_WINDOW', lambda: done('stop'))
    ui.center_on(win, parent.winfo_toplevel())
    ok.focus_set()
    win.wait_window()
    return result['v']


# ============================================================================ the range-selection dialog
def ask_range(parent, p, total, dial, standby_text):
    """'Turn the dial to ...' with a picture of the dial and the target position marked.
    Returns 'ok' (continue), 'skip' (skip the point) or 'stop'."""
    result = {'v': 'stop'}
    win = ui.dialog(parent, f'Point {p["n"]} of {total} - select the range')
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(ui.px(22), ui.px(16), ui.px(22), ui.px(14)))
    outer.pack(fill='both', expand=True)
    main = ttk.Frame(outer)
    main.pack(fill='both', expand=True)
    width, height = dial['size']
    canvas = tk.Canvas(main, width=width, height=height, background=ui.C['bg'], highlightthickness=0)
    canvas.pack(side='left', anchor='n', padx=(0, ui.px(20)))
    try:
        photo = tk.PhotoImage(master=win, file=str(HERE / dial['image']))
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas.image = photo
    except tk.TclError:
        pass
    pos = dial['positions'].get(p.get('dial'))
    if pos:
        cx, cy = dial['center']
        radius = dial['knob_radius']
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill='#1b1d21', outline='#9aa0aa', width=3)
        theta = math.radians(pos['angle'])
        ux, uy = math.sin(theta), -math.cos(theta)           # unit vector from the centre toward the selected position
        nx, ny = -uy, ux
        tip = (cx + ux * (radius - 6), cy + uy * (radius - 6))
        canvas.create_polygon(tip[0], tip[1], cx + nx * 14 - ux * 8, cy + ny * 14 - uy * 8, cx - nx * 14 - ux * 8, cy - ny * 14 - uy * 8,
                              fill='#ffb300', outline='')
        canvas.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill='#55606e', outline='')
        canvas.create_rectangle(pos['x'] - 30, pos['y'] - 17, pos['x'] + 30, pos['y'] + 17, outline='#ffb300', width=3)
    box = ttk.Frame(main)
    box.pack(side='left', fill='both', expand=True, anchor='n')
    ttk.Label(box, text=f'Point {p["n"]} of {total}  -  {p["section"]}', style='Small.TLabel').pack(anchor='w')
    ttk.Label(box, text='Turn the dial to', style='MetricCap.TLabel').pack(anchor='w', pady=(10, 0))
    ttk.Label(box, text=p.get('dial_text') or p['switch'], style='Section.TLabel', wraplength=ui.px(360), justify='left').pack(anchor='w')
    ttk.Label(box, text='Range', style='MetricCap.TLabel').pack(anchor='w', pady=(10, 0))
    ttk.Label(box, text=p['range'], style='Reading.TLabel').pack(anchor='w')
    if p.get('note'):
        ttk.Label(box, text=p['note'], style='Small.TLabel', wraplength=ui.px(360), justify='left').pack(anchor='w', pady=(8, 0))
    ttk.Label(box, text=standby_text, style='Small.TLabel', wraplength=ui.px(360), justify='left').pack(anchor='w', pady=(10, 0))

    def done(value):
        result['v'] = value
        win.destroy()
    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(14, 0))
    ok = ttk.Button(bar, text='Range selected - continue  (Enter)', style='Accent.TButton', command=lambda: done('ok'))
    ok.pack(side='right')
    ttk.Button(bar, text='Skip point', command=lambda: done('skip')).pack(side='right', padx=(0, 8))
    ttk.Button(bar, text='Stop run', style='Danger.TButton', command=lambda: done('stop')).pack(side='left')
    win.bind('<Return>', lambda _e: done('ok'))
    win.protocol('WM_DELETE_WINDOW', lambda: done('stop'))
    ui.center_on(win, parent.winfo_toplevel())
    ok.focus_set()
    win.wait_window()
    return result['v']
