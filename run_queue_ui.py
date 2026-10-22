"""The three windows of the handheld run queue: the queue set-up window, the one-window reading entry for all meters, and the progress window.

Presentation only: nothing here talks to an instrument or judges a reading.  The reading window is given a `judge(key, text)` callable by the
engine, which answers with the engine's own judging code (handheld_dmm.judge_numeric / pad_reading), so a meter is judged against the same limits
as in a single-meter run.  Colours come from the theme tokens (ui_theme.C), so the windows follow light / dark.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import run_queue as RQ
import ui_theme as ui
import virtualbench

WIDTH = 760                       # content width of the reading window, 96-dpi units


def _label(parent, text='', fg=None, font=None, bg=None, wrap=None, **kw):
    C = ui.C
    return tk.Label(parent, text=text, background=bg or C['bg'], foreground=fg or C['text'], font=font or 'TkDefaultFont', anchor='w',
                    justify='left', **({'wraplength': wrap} if wrap else {}), **kw)


# ============================================================================================================ reading window
def ask_readings(parent, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None,
                 device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading=''):
    """One modal window for ONE point and SEVERAL meters: a reading box per meter (asset number on the row), each judged live.

    meters      list of (key, asset label, serial) in queue order
    judge       judge(key, text) -> (state, padded_text, note): state 'PASS' | 'FAIL'; raises ValueError for text that is not a reading
    demo_fill   None, or demo_fill(index) -> text for the 'Fill with a simulated reading' button (fills every box)
    Returns dict(action='record'|'skip'|'stop', texts={key: text or None}, no_reading=[keys]).  Enter moves to the next box; Enter in the last box records."""
    result = dict(action='stop', texts={}, no_reading=[])
    win = ui.dialog(parent, f'Point {p["n"]} of {total}')
    win.resizable(False, False)
    C = ui.C
    outer = tk.Frame(win, background=C['bg'])
    outer.pack(fill='both', expand=True, padx=ui.px(22), pady=(ui.px(16), ui.px(14)))
    outer.grid_columnconfigure(0, weight=1)
    width = ui.px(WIDTH)
    row_n = [0]

    def put(widget, pady=(0, 0)):
        widget.grid(row=row_n[0], column=0, sticky='ew', pady=pady)
        row_n[0] += 1

    put(_label(outer, f'Point {p["n"]} of {total}  -  {p["section"]}' + (f'  -  {phase}' if phase else '') + f'  -  {len(meters)} meters', fg=C['muted'], font='CalSmall', wrap=width))
    put(_label(outer, heading, font='CalH2', fg=C['navy'], wrap=width), pady=(2, 10))

    top = tk.Frame(outer, background=C['bg'])
    put(top, pady=(0, ui.px(8)))
    top.grid_columnconfigure(0, weight=1, uniform='cards')
    top.grid_columnconfigure(1, weight=1, uniform='cards')
    half = (width - ui.px(10)) // 2

    def card(col, build):
        cv = ui.rounded_card(top, half, build)
        cv.grid(row=0, column=col, sticky='nsew', padx=(0, ui.px(10)) if col == 0 else (0, 0))

    def out_card(inner, wrap):
        mark = ui.status_circle(inner, 'done' if str(out_note).startswith('Output is ON') else 'todo', background=C['card'])
        mark.grid(row=0, column=1, rowspan=2, sticky='ne')
        inner.grid_columnconfigure(0, weight=1)
        _label(inner, source, fg=C['muted'], font='CalSmallBold', bg=C['card'], wrap=wrap - ui.px(30)).grid(row=0, column=0, sticky='w')
        _label(inner, out_text, font='CalMetric', bg=C['card'], wrap=wrap - ui.px(30)).grid(row=1, column=0, sticky='w')
        if out_note:
            _label(inner, out_note, fg=C['muted'], font='CalSmall', bg=C['card'], wrap=wrap).grid(row=2, column=0, columnspan=2, sticky='w')

    def accept_card(inner, wrap):
        _label(inner, 'ACCEPT IF', fg=C['muted'], font='CalSmallBold', bg=C['card'], wrap=wrap).pack(anchor='w')
        _label(inner, accept, font='CalBold', bg=C['card'], wrap=wrap).pack(anchor='w')
        _label(inner, 'on every meter' + (f'  -  limit: {tol_text}' if tol_text else ''), fg=C['muted'], font='CalSmall', bg=C['card'], wrap=wrap).pack(anchor='w')
    card(0, out_card)
    card(1, accept_card)

    counter = tk.StringVar()
    clock = {'job': None, 'expired': False}
    if limit_s is not None:
        tk.Label(outer, textvariable=counter, foreground=C.get('bad', '#B3261E'), background=C['bg'], font='CalBold', anchor='w', wraplength=width,
                 justify='left').grid(row=row_n[0], column=0, sticky='ew', pady=(0, 8))
        row_n[0] += 1
        end = _now() + max(0.0, limit_s)

        def tick():
            try:
                left = end - _now()
                if left <= 0:
                    if not clock['expired']:
                        clock['expired'] = True
                        if on_expire:
                            on_expire()
                    counter.set('Time limit reached - the output has been switched off. Enter the readings you saw.' if on_expire
                                else 'Time limit reached - put the calibrator in STANDBY now, then enter the readings.')
                    return
                counter.set(f'Take the readings within {left:.0f} s - the output switches off automatically.' if on_expire
                            else f'Take the readings within {left:.0f} s, then put the calibrator in STANDBY.')
                clock['job'] = win.after(250, tick)
            except tk.TclError:
                pass
        tick()

    rows = []                                  # dicts: key, var, entry, state label, note label, skip var, frame
    put(_label(outer, f'WHAT DOES EACH {device} SHOW?', fg=C['primary'], font='CalSmallBold', wrap=width), pady=(ui.px(4), ui.px(4)))

    def box(inner, wrap):
        inner.grid_columnconfigure(0, weight=1)
        for n, (key, label, serial) in enumerate(meters):
            fr = tk.Frame(inner, background=C['bg'], highlightthickness=1, highlightbackground=C['border'], highlightcolor=C['primary'])
            fr.grid(row=n, column=0, sticky='ew', pady=(0, ui.px(6)))
            fr.grid_columnconfigure(3, weight=1)
            who = tk.Frame(fr, background=C['bg'])
            who.grid(row=0, column=0, sticky='w', padx=(ui.px(12), ui.px(10)), pady=ui.px(6))
            _label(who, f'Meter {n + 1}', fg=C['muted'], font='CalSmallBold').pack(anchor='w')
            _label(who, f'Asset {label}', font='CalBold', wrap=ui.px(170)).pack(anchor='w')
            var = tk.StringVar()
            skip = tk.BooleanVar(value=False)
            e = ttk.Entry(fr, textvariable=var, font='CalMetric', width=9)
            e.grid(row=0, column=1, padx=(0, ui.px(6)), pady=ui.px(6))
            _label(fr, unit, font='CalH2', fg=C['muted']).grid(row=0, column=2, sticky='w')
            side = tk.Frame(fr, background=C['bg'])
            side.grid(row=0, column=3, sticky='w', padx=(ui.px(14), ui.px(12)))
            state = _label(side, 'waiting', font='CalBold', fg=C['muted'], wrap=ui.px(230))
            state.pack(anchor='w')
            note = _label(side, '', font='CalSmall', fg=C['muted'], wrap=ui.px(230))
            note.pack(anchor='w')
            ck = ttk.Checkbutton(fr, text='No reading', variable=skip)
            ck.grid(row=0, column=4, padx=(0, ui.px(10)))
            rows.append(dict(key=key, var=var, entry=e, state=state, note=note, skip=skip, frame=fr, index=n))
        tk.Frame(inner, width=wrap, height=1, background=C['card']).grid(row=len(meters), column=0)         # the rows fill the card
    put(ui.rounded_card(outer, width, box, outline=C['primary'], outline_w=2, radius=10, pad=(14, 12)), pady=(0, 0))
    error = tk.StringVar(value='')
    err = tk.Label(outer, textvariable=error, foreground=C.get('bad', '#B3261E'), background=C['bg'], font='CalBold', anchor='w', wraplength=width, justify='left')
    put(err, pady=(ui.px(6), 0))

    def refresh_row(r):
        text = r['var'].get().strip()
        r['entry'].configure(state='disabled' if r['skip'].get() else 'normal')
        if r['skip'].get():
            r['state'].configure(text='no reading', fg=C['muted'])
            r['note'].configure(text='nothing is recorded for this meter at this point')
            return
        if not text:
            r['state'].configure(text='waiting', fg=C['muted'])
            r['note'].configure(text='')
            return
        try:
            state, padded, note = judge(r['key'], text)
        except ValueError as exc:
            r['state'].configure(text='not a reading', fg=C.get('bad', '#B3261E'))
            r['note'].configure(text=str(exc))
            return
        good = state == 'PASS'
        r['state'].configure(text=('✓ PASS' if good else '✗ FAIL'), fg=C['good'] if good else C.get('bad', '#B3261E'))
        bits = ([f'padded to {padded}'] if padded != text else []) + ([note] if note else [])
        r['note'].configure(text='   '.join(bits))

    def focus_row(i):
        for r in rows:
            r['frame'].configure(highlightbackground=C['primary'] if r['index'] == i else C['border'], highlightthickness=2 if r['index'] == i else 1)

    def collect():
        texts, none = {}, []
        for r in rows:
            if r['skip'].get():
                texts[r['key']] = None
                none.append(r['key'])
                continue
            text = r['var'].get().strip()
            if not text:
                return None, f'Enter the reading of Asset {_label_of(meters, r["key"])}, or tick "No reading" for it.', r
            try:
                judge(r['key'], text)
            except ValueError as exc:
                return None, f'Asset {_label_of(meters, r["key"])}: {exc}', r
            texts[r['key']] = text
        if len(none) == len(rows):
            return None, 'Every meter is marked "No reading": use Skip point instead.', None
        return (texts, none), '', None

    def done(action):
        result['action'] = action
        if clock['job']:
            try:
                win.after_cancel(clock['job'])
            except tk.TclError:
                pass
        if action == 'record':
            got, msg, bad = collect()
            if got is None:
                error.set(msg)
                if bad is not None:
                    bad['entry'].focus_set()
                result['action'] = 'stop'
                return
            result.update(texts=got[0], no_reading=got[1])
        win.destroy()

    def enter(i):
        def handler(_e=None):
            nxt = next((r for r in rows[i + 1:] if not r['skip'].get()), None)
            if nxt is not None:
                nxt['entry'].focus_set()
            else:
                done('record')
            return 'break'
        return handler

    for r in rows:
        r['var'].trace_add('write', lambda *_a, _r=r: (refresh_row(_r), error.set('')))
        r['skip'].trace_add('write', lambda *_a, _r=r: refresh_row(_r))
        r['entry'].bind('<Return>', enter(r['index']))
        r['entry'].bind('<FocusIn>', lambda _e, i=r['index']: focus_row(i))
    if demo_fill is not None:
        def fill():
            for r in rows:
                if not r['skip'].get():
                    r['var'].set(demo_fill(r['index']))
            rows[0]['entry'].focus_set()
        fr = tk.Frame(outer, background=C['bg'])
        put(fr, pady=(ui.px(10), 0))
        ttk.Button(fr, text=virtualbench.FILL_TEXT, command=fill).pack(anchor='w')
        _label(fr, 'DEMO: these values are made up by the program; you may type any reading you like. Nothing here is calibration evidence.',
               fg=C.get('warn', '#B26A00'), font='CalSmall', wrap=width).pack(anchor='w', pady=(4, 0))

    bar = tk.Frame(outer, background=C['bg'])
    bar.grid(row=row_n[0], column=0, sticky='ew', pady=(ui.px(16), 0))
    bar.grid_columnconfigure(1, weight=1)
    ok = ttk.Button(bar, text='Record all  (Enter)', style='Accent.TButton', command=lambda: done('record'))
    ok.grid(row=0, column=3)
    ttk.Button(bar, text='Skip point', command=lambda: done('skip')).grid(row=0, column=2, padx=(0, 8))
    ttk.Button(bar, text='Stop run', style='Danger.TButton', command=lambda: done('stop')).grid(row=0, column=0)
    win.bind('<Return>', lambda _e: done('record'))
    win.protocol('WM_DELETE_WINDOW', lambda: done('stop'))
    ui.center_on(win, parent.winfo_toplevel())
    rows[0]['entry'].focus_set()
    win.wait_window()
    return result


def _now():
    import time
    return time.monotonic()


def _label_of(meters, key):
    return next((m[1] for m in meters if m[0] == key), key)


# ============================================================================================================ set-up window
def ask_meter(parent, title, asset='', serial='', tech='', candidates=(), default_tech=''):
    """Add / edit one meter: asset number (typed, or chosen from Asset History), serial, technician.  Returns (asset, serial, tech) or None.
    candidates: [(asset, serial)] from Asset History / the instrument list."""
    win = ui.dialog(parent, title)
    win.resizable(False, False)
    out = ttk.Frame(win, padding=(ui.px(22), ui.px(18), ui.px(22), ui.px(16)))
    out.pack(fill='both', expand=True)
    a, s, t = tk.StringVar(value=asset), tk.StringVar(value=serial), tk.StringVar(value=tech or default_tech)
    serials = {x: y for x, y in candidates}
    ttk.Label(out, text='Asset number').grid(row=0, column=0, sticky='w', pady=4)
    box = ttk.Combobox(out, textvariable=a, values=[x for x, _ in candidates], width=26)
    box.grid(row=0, column=1, padx=(10, 0), pady=4)
    ttk.Label(out, text='Serial number').grid(row=1, column=0, sticky='w', pady=4)
    ttk.Entry(out, textvariable=s, width=28).grid(row=1, column=1, padx=(10, 0), pady=4)
    ttk.Label(out, text='Technician').grid(row=2, column=0, sticky='w', pady=4)
    ttk.Entry(out, textvariable=t, width=28).grid(row=2, column=1, padx=(10, 0), pady=4)
    ttk.Label(out, text='Choose an asset from Asset History or type one. The serial is filled in from the history when it is known.',
              style='Muted.TLabel', wraplength=ui.px(380), justify='left').grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))
    msg = tk.StringVar()
    tk.Label(out, textvariable=msg, foreground=ui.C.get('bad', '#B3261E'), background=ui.C['bg'], anchor='w', wraplength=ui.px(380), justify='left').grid(row=4, column=0, columnspan=2, sticky='w')
    result = {'v': None}

    def pick(_e=None):
        if a.get() in serials and not s.get().strip():
            s.set(serials[a.get()])
    box.bind('<<ComboboxSelected>>', pick)
    box.bind('<FocusOut>', pick)

    def ok():
        if not a.get().strip():
            msg.set('Enter the asset number.')
            return
        pick()
        result['v'] = (a.get().strip(), s.get().strip(), t.get().strip())
        win.destroy()
    bar = ttk.Frame(out)
    bar.grid(row=5, column=0, columnspan=2, sticky='e', pady=(14, 0))
    ttk.Button(bar, text='OK', style='Accent.TButton', command=ok).pack(side='right')
    ttk.Button(bar, text='Cancel', command=win.destroy).pack(side='right', padx=(0, 8))
    win.bind('<Return>', lambda _e: ok())
    ui.center_on(win, parent.winfo_toplevel())
    win.wait_window()
    return result['v']


def ask_queue_setup(parent, title, meters, mode, summarize, status_of=None, candidates=(), default_tech='', ir_only=False):
    """The 'Run queue' window.  meters: [(asset, serial, tech)] to start from.  summarize(meters, mode) -> dict(title, body, warnings=[], ok=bool, kind='good'|'warn'|'bad')
    (the engine decides what the choice saves and what blocks it).  status_of(asset) -> text for the Status column.
    Returns dict(action='start'|'save', meters=[(asset, serial, tech)], mode=...) or None (Cancel / closed)."""
    C = ui.C
    win = ui.dialog(parent, title)
    win.resizable(False, False)
    outer = tk.Frame(win, background=C['bg'])
    outer.pack(fill='both', expand=True, padx=ui.px(22), pady=(ui.px(16), ui.px(14)))
    outer.grid_columnconfigure(0, weight=1)
    width = ui.px(700)
    state = {'meters': [tuple(m) for m in meters], 'mode': mode, 'result': None}
    modevar = tk.StringVar(value=mode)
    r = [0]

    def put(w, pady=(0, 0)):
        w.grid(row=r[0], column=0, sticky='ew', pady=pady)
        r[0] += 1

    put(_label(outer, 'METERS IN THIS QUEUE', fg=C['muted'], font='CalSmallBold'), pady=(0, ui.px(4)))
    tfr = tk.Frame(outer, background=C['bg'], highlightthickness=1, highlightbackground=C['border'])
    put(tfr)
    cols = ('n', 'asset', 'serial', 'status', 'tech')
    tree = ttk.Treeview(tfr, columns=cols, show='headings', height=5, selectmode='browse')
    for col, head, w in (('n', '#', 36), ('asset', 'Asset', 130), ('serial', 'Serial', 140), ('status', 'Status', 190), ('tech', 'Tech', 170)):
        tree.heading(col, text=head)
        tree.column(col, width=ui.px(w), anchor='w', stretch=col in ('status', 'tech'))
    tree.pack(fill='x')
    btns = ttk.Frame(outer)
    put(btns, pady=(ui.px(6), ui.px(10)))
    note = tk.StringVar()
    put(tk.Label(outer, textvariable=note, foreground=C.get('bad', '#B3261E'), background=C['bg'], anchor='w', wraplength=width, justify='left'))

    put(_label(outer, 'HOW TO RUN THEM', fg=C['muted'], font='CalSmallBold'), pady=(ui.px(6), ui.px(4)))
    cards = {}

    def mode_card(value, head, text):
        fr = tk.Frame(outer, background=C['card'], highlightthickness=2, highlightbackground=C['border'])
        put(fr, pady=(0, ui.px(8)))
        rb = ttk.Radiobutton(fr, text=head, value=value, variable=modevar, command=lambda: choose(value))
        rb.grid(row=0, column=0, sticky='w', padx=(ui.px(12), 0), pady=(ui.px(8), 0))
        lbl = _label(fr, text, fg=C['muted'], font='CalSmall', bg=C['card'], wrap=width - ui.px(60))
        lbl.grid(row=1, column=0, sticky='w', padx=(ui.px(36), ui.px(12)), pady=(0, ui.px(8)))
        for w in (fr, lbl):
            w.bind('<Button-1>', lambda _e, v=value: choose(v))
        cards[value] = fr
    mode_card(RQ.POINT_BY_POINT, 'Point by point  (recommended)',
              'All meters are wired to the calibrator together. Each point is set once, then you read meter 1, 2, 3 in one window. '
              'Points that cannot be shared (current, 4-wire ...) are done one meter at a time, with a prompt that says why.')
    mode_card(RQ.ONE_AT_A_TIME, 'One meter at a time',
              'Finish meter 1, swap in meter 2, and so on. Each meter runs the normal single-meter procedure. Use when the meters cannot share the leads.')
    sumfr = tk.Frame(outer, background=C['card'], highlightthickness=2, highlightbackground=C['border'])
    put(sumfr, pady=(0, ui.px(10)))
    sum_head = _label(sumfr, '', font='CalBold', bg=C['card'], wrap=width - ui.px(24))
    sum_head.pack(anchor='w', padx=ui.px(12), pady=(ui.px(8), 0))
    sum_body = _label(sumfr, '', fg=C['muted'], font='CalSmall', bg=C['card'], wrap=width - ui.px(24))
    sum_body.pack(anchor='w', padx=ui.px(12), pady=(ui.px(2), ui.px(8)))

    bar = tk.Frame(outer, background=C['bg'])
    put(bar)
    bar.grid_columnconfigure(0, weight=1)
    start = ttk.Button(bar, text='Start queue', style='Accent.TButton', command=lambda: finish('start'))
    start.grid(row=0, column=3)
    save = ttk.Button(bar, text='Save (do not start)', command=lambda: finish('save'))
    save.grid(row=0, column=2, padx=(0, 8))
    ttk.Button(bar, text='Cancel', command=win.destroy).grid(row=0, column=1, padx=(0, 8))

    def fill():
        tree.delete(*tree.get_children())
        for n, (asset, serial, tech) in enumerate(state['meters'], 1):
            tree.insert('', 'end', iid=str(n - 1), values=(n, asset, serial, status_of(asset) if status_of else 'Ready', tech))
        win.title(f'{title}  ({len(state["meters"])} meter{"s" if len(state["meters"]) != 1 else ""})' + ui.DEMO_SUFFIX)

    def selected():
        sel = tree.selection()
        return int(sel[0]) if sel else None

    def recompute():
        info = summarize(list(state['meters']), state['mode'])
        kind = info.get('kind', 'good')
        edge = {'good': C['good_dot'], 'warn': C['warn_dot'], 'bad': C['bad_dot']}.get(kind, C['border'])
        sumfr.configure(highlightbackground=edge)
        sum_head.configure(text=info.get('title', ''), fg={'good': C['good'], 'warn': C['warn'], 'bad': C['bad']}.get(kind, C['text']))
        sum_body.configure(text=info.get('body', '') + ''.join('\n' + w for w in info.get('warnings', [])))
        for v, fr in cards.items():
            fr.configure(highlightbackground=C['primary'] if v == state['mode'] else C['border'])
        modevar.set(state['mode'])
        start.configure(state='normal' if info.get('ok', True) and state['meters'] else 'disabled')
        save.configure(state='normal' if state['meters'] else 'disabled')
        start.configure(text='Start queue' if len(state['meters']) >= 2 else 'Run this meter')

    def choose(value):
        if ir_only and value == RQ.POINT_BY_POINT:
            note.set(RQ.IR_REASON[0].upper() + RQ.IR_REASON[1:] + '.')
            value = RQ.ONE_AT_A_TIME
        state['mode'] = value
        recompute()

    def refresh_all():
        fill()
        recompute()

    def add():
        got = ask_meter(win, 'Add meter', candidates=[c for c in candidates if c[0] not in {m[0] for m in state['meters']}], default_tech=default_tech)
        if got:
            if got[0].casefold() in {m[0].casefold() for m in state['meters']}:
                note.set(f'Asset {got[0]} is already in the queue.')
                return
            if len(state['meters']) >= RQ.MAX_METERS:
                note.set(f'A queue holds at most {RQ.MAX_METERS} meters.')
                return
            note.set('')
            state['meters'].append(got)
            refresh_all()

    def edit(_e=None):
        i = selected()
        if i is None:
            return
        old = state['meters'][i]
        got = ask_meter(win, 'Edit meter', *old, candidates=candidates, default_tech=default_tech)
        if got:
            if got[0].casefold() != old[0].casefold() and got[0].casefold() in {m[0].casefold() for k, m in enumerate(state['meters']) if k != i}:
                note.set(f'Asset {got[0]} is already in the queue.')
                return
            note.set('')
            state['meters'][i] = got
            refresh_all()
            tree.selection_set(str(i))

    def remove():
        i = selected()
        if i is not None:
            state['meters'].pop(i)
            note.set('')
            refresh_all()

    def move(delta):
        i = selected()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(state['meters']):
            state['meters'][i], state['meters'][j] = state['meters'][j], state['meters'][i]
            refresh_all()
            tree.selection_set(str(j))

    for text, cmd in (('+ Add meter', add), ('Edit', edit), ('Remove', remove), ('Move up', lambda: move(-1)), ('Move down', lambda: move(1))):
        ttk.Button(btns, text=text, command=cmd, style='Compact.TButton').pack(side='left', padx=(0, 8))
    tree.bind('<Double-1>', edit)

    def finish(action):
        state['result'] = dict(action=action, meters=list(state['meters']), mode=state['mode'])
        win.destroy()

    if ir_only:
        state['mode'] = RQ.ONE_AT_A_TIME
    refresh_all()
    win.bind('<Return>', lambda _e: None)
    ui.center_on(win, parent.winfo_toplevel())
    win.wait_window()
    return state['result']


# ============================================================================================================ progress window
class QueueProgress:
    """Non-modal progress window (queue_progress mockup): the point being run, a bar, and per meter 'n recorded, n fail'.  The engine calls update() as
    the run goes; when the run has ended it calls update(..., finished=True) and the window offers Show / Export all reports / Close."""

    def __init__(self, parent, title='Queue progress', on_show=None, on_export=None):
        self.parent, self.on_show, self.on_export = parent, on_show, on_export
        self.win = None
        self.closed = False
        self.rows = []
        try:
            C = ui.C
            win = self.win = ui.dialog(parent, title, modal=False)
            win.resizable(False, False)
            win.protocol('WM_DELETE_WINDOW', self.close)
            self.outer = tk.Frame(win, background=C['bg'])
            self.outer.pack(fill='both', expand=True, padx=ui.px(22), pady=(ui.px(16), ui.px(14)))
            self.head = tk.StringVar()
            tk.Label(self.outer, textvariable=self.head, background=C['bg'], foreground=C['text'], font='CalH2', anchor='w').pack(fill='x')
            self.bar = ttk.Progressbar(self.outer, mode='determinate', maximum=100, length=ui.px(540))
            self.bar.pack(fill='x', pady=(ui.px(10), ui.px(12)))
            self.body = tk.Frame(self.outer, background=C['bg'])
            self.body.pack(fill='x')
            self.foot = tk.Label(self.outer, text='Each meter still gets its own report (asset#-date) and its own Asset History record.', background=C['bg'],
                                 foreground=C['muted'], font='CalSmall', anchor='w', wraplength=ui.px(540), justify='left')
            self.foot.pack(fill='x', pady=(ui.px(12), 0))
            self.buttons = ttk.Frame(self.outer)
            self.buttons.pack(fill='x', pady=(ui.px(10), 0))
            try:
                x = parent.winfo_rootx() + max(0, parent.winfo_width() - ui.px(600))
                win.geometry(f'+{x}+{parent.winfo_rooty() + ui.px(60)}')
            except tk.TclError:
                pass
        except Exception:
            self.win = None

    def alive(self):
        if self.win is None or self.closed:
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def update(self, heading, fraction, rows, finished=False, note=''):
        """rows: run_queue.progress() dicts."""
        if not self.alive():
            return
        C = ui.C
        try:
            self.head.set(heading)
            self.bar.configure(value=max(0.0, min(1.0, fraction)) * 100)
            for w in self.body.winfo_children():
                w.destroy()
            for row in rows:
                bad = row['failed'] > 0
                fr = tk.Frame(self.body, background=C['card'], highlightthickness=2, highlightbackground=C['bad_dot'] if bad else C['border'])
                fr.pack(fill='x', pady=(0, ui.px(8)))
                fr.grid_columnconfigure(1, weight=1)
                tk.Label(fr, text=f'Asset {row["asset"]}', background=C['card'], foreground=C['text'], font='CalBold', anchor='w', width=16).grid(row=0, column=0, sticky='w', padx=ui.px(12), pady=ui.px(10))
                text = f'{row["recorded"]} recorded   ' + (f'{row["failed"]} FAIL' + (f' at point {row["first_fail"]}' if row['first_fail'] else '') if bad else '0 fail')
                if row.get('status') and row['status'] not in ('Ready', 'Running'):
                    text += f'   -   {row["status"]}'
                tk.Label(fr, text=text, background=C['card'], foreground=C['bad'] if bad else C['muted'], anchor='w').grid(row=0, column=1, sticky='w')
                if finished and self.on_show:
                    ttk.Button(fr, text='Show', style='Compact.TButton', command=lambda a=row['asset']: self.on_show(a)).grid(row=0, column=2, padx=ui.px(10))
            self.foot.configure(text=note or 'Each meter still gets its own report (asset#-date) and its own Asset History record.')
            for w in self.buttons.winfo_children():
                w.destroy()
            if finished:
                ttk.Button(self.buttons, text='Close', command=self.close).pack(side='right')
                if self.on_export:
                    ttk.Button(self.buttons, text='Export all reports (PDF)...', style='Accent.TButton', command=self.on_export).pack(side='right', padx=(0, 8))
            self.win.update_idletasks()
        except tk.TclError:
            pass

    def close(self):
        self.closed = True
        try:
            if self.win is not None:
                self.win.destroy()
        except tk.TclError:
            pass
