"""Manual-reading verification engine for handheld meters that have no remote interface.

The calibrator output is set automatically (Fluke 5560A or 5522A over RS-232, or by hand if you prefer);
the technician reads the meter display and types the value in. Test points and limits are NOT in this file:
they come from a spec JSON (specs/fluke_110_series_pv.json), extracted from the manufacturer's tables.

    import handheld_dmm
    handheld_dmm.main('117')          # what Procedures/Fluke_117_Verification.py does

Rules: the calibrator is put in STANDBY before every setup and after every reading; the calibrator's error
queue is read after each programmed output and the output is never enabled after a rejection; wiring and
high-voltage confirmations are required; readings are stored in base units, limits compared exactly (Decimal).
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import hookups
import ui_theme as ui
import drivers

SPEC_PATH = HERE / 'specs' / 'fluke_110_series_pv.json'
CAL_CHOICES = ['Fluke 5560A  (automatic output)', 'Fluke 5522A  (automatic output)', 'Manual  (5560A front panel)', 'Manual  (5522A front panel)']
OLD_CAL_CHOICES = {'Manual  (I set the calibrator)': 'Manual  (5560A front panel)'}

WIRING = {
    'VOHM': 'Calibrator NORMAL HI / LO output to the meter VΩ and COM input terminals.',
    'AMP10': 'Calibrator in STANDBY, then reconfigure: calibrator high-current output to the meter 10 A and COM terminals. Check the meter fuse and that the leads are rated for 10 A.',
    'UAMP': 'Calibrator in STANDBY, then reconfigure: calibrator current output to the meter µA / mA input and COM terminals.',
    'TEMP': 'K-type thermocouple (mini-plug on both ends) between the calibrator thermocouple output and the meter temperature input, using the Fluke 80AK adapter. Allow the junctions to stabilise.',
    'VOLTALERT': 'Double banana plug on the calibrator voltage output; the meter is held against the plug (see the point instructions).',
}
SYMBOL = {'ohm': 'Ω', 'V': 'V', 'A': 'A', 'F': 'F', 'Hz': 'Hz', 'C': '°C', 'degF': '°F', 'S': 'S', '%': '%'}


def load_spec(path=SPEC_PATH):
    """A spec JSON by absolute path, or by file name inside specs/ (e.g. 'klein_mm325_pv.json')."""
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = HERE / 'specs' / path
    return json.loads(path.read_text(encoding='utf-8'))


def points_for(spec, model):
    """The model's steps in manual order (functional checks first), numbered 1..n."""
    order = {'F': 0}
    chosen = [dict(s) for s in spec['steps'] if model in s['models']]
    chosen.sort(key=lambda s: (order.get(s['table'], 1), s['step']))
    for n, p in enumerate(chosen, 1):
        p['n'] = n
        p['group'] = p.get('group') or ('NONE' if p.get('applied') is None and p['test'] == 'visual' or p['kind'] == 'NONE' else 'VOHM')
    return chosen


def _fmt(value, unit):
    number, symbol = ui.si_one(value, SYMBOL.get(unit, unit), sig=6)
    if '.' in number:
        number = number.rstrip('0').rstrip('.')
    return f'{number} {symbol}'


def output_text(p):
    a = p.get('applied')
    if not a:
        return 'No calibrator output (STANDBY)'
    kind, v, f = p['kind'], a['value'], a.get('frequency')
    unit = {'ACV': 'V', 'DCV': 'V', 'ACI': 'A', 'DCI': 'A', 'OHM': 'ohm', 'CAP': 'F', 'TEMP': 'C'}[kind]
    text = _fmt(v, unit)
    if kind in ('ACV', 'ACI'):
        text += f' AC @ {_fmt(f, "Hz")}'
    elif kind in ('DCV', 'DCI'):
        text += ' DC'
    return text


def describe(p):
    if p['test'] == 'beeper':
        return f'Continuity, {output_text(p)}: beeper {p["expect"].upper()}'
    if p['test'] == 'visual':
        return p.get('title') or p['section'] + (' ' + p['switch'].split('(')[-1].strip(') ') if p['section'] == 'VoltAlert' else '')
    return f'{p["section"]}, {p["range"]} range' if p['range'] else p['section']


def judge_numeric(p, text, annunciator=True):
    """('PASS'|'FAIL', value_in_base_units or None). Raises ValueError for text that is not a reading."""
    t = text.strip().replace(',', '')
    if t.upper() in ('OL', '0L', 'O.L.'):
        return 'FAIL', None
    try:
        number = Decimal(t)
        low, high = Decimal(p['low']), Decimal(p['high'])
    except InvalidOperation:
        raise ValueError('Enter the number exactly as the meter shows it, without the unit (or OL for overload).')
    if not number.is_finite():
        raise ValueError('Enter a number.')
    ok = low <= number <= high and (annunciator or not p.get('annunciator'))
    return ('PASS' if ok else 'FAIL'), float(f'{float(number * Decimal(str(p["factor"]))):.9g}')


# ============================================================================ calibrator I/O
class Cancelled(Exception):
    pass


class IO:
    """The calibrator: set the output for a point, confirm it was accepted, and never leave it energised."""
    RAMP_ABOVE, RAMP_STEP, RAMP_DELAY = 100.0, 50.0, 5.0     # the manual's "ramp up in 50 V increments, 5 s apart"

    def __init__(self, model_name, address, baud=9600, transport=None):
        self.log = drivers.CommandLog()
        cls = drivers.Fluke5522A if '5522' in model_name else drivers.Fluke5560A
        t = transport or drivers.open_visa(address, timeout=20, baud=baud)
        self.cal = cls(t, self.log, label=cls.MODEL)
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
        except Exception:
            self.close()
            raise
        self.ident = self.cal.idn

    def standby(self):
        self.cal.standby_quiet()

    def close(self):
        try:
            self.standby()
        except Exception:
            pass
        try:
            self.cal.close()
        except Exception:
            pass
        self.save_log()

    def save_log(self):
        try:
            folder = Path.home() / '.calibration_suite'
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  handheld DMM session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    @staticmethod
    def _wait(seconds, cancel):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if cancel and cancel():
                raise Cancelled()
            time.sleep(min(0.25, max(0.0, end - time.monotonic())))

    def _volts(self, v, f, context, cancel):
        steps = [v]
        if abs(v) > self.RAMP_ABOVE:
            n = int(abs(v) // self.RAMP_STEP)
            steps = [math.copysign(self.RAMP_STEP * i, v) for i in range(1, n + 1)]
            if abs(steps[-1]) < abs(v):
                steps.append(v)
        for i, level in enumerate(steps):
            self.cal.set_output_volts(level, f)
            self.cal.check_error(context)
            if i == 0:
                self.cal.operate_unverified()
            if len(steps) > 1 and i < len(steps) - 1:
                self._wait(self.RAMP_DELAY, cancel)

    def apply(self, p, cancel=None):
        """Program and enable the output for point p, then wait for it to settle."""
        a = p['applied']
        kind, v, f = p['kind'], a['value'], a.get('frequency')
        context = describe(p)
        self.standby()
        if kind in ('DCV', 'ACV'):
            self._volts(v, f, context, cancel)
        else:
            if kind in ('DCI', 'ACI'):
                self.cal.set_output_amps(v, f)
            elif kind == 'OHM':
                self.cal.set_output_ohms(v)
            elif kind == 'CAP':
                self.cal.set_output_capacitance(v)
            elif kind == 'TEMP':
                self.cal.set_output_temperature(v)
            else:
                raise ValueError('No calibrator output for ' + kind)
            self.cal.check_error(context)      # the calibrator refuses outputs it cannot make; never operate then
            self.cal.operate_unverified()
        self.on_at = time.monotonic()
        self._wait(p.get('settle', 3.0), cancel)


# ============================================================================ the reading dialog
def ask_reading(parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                limit_s=None, on_expire=None):
    """One modal dialog. mode 'numeric' (type the display) or 'yesno' (answer a question).
    Returns dict(action='record'|'skip'|'stop', text=, ann=, yes=)."""
    result = dict(action='stop', text='', ann=False, yes=None)
    win = ui.dialog(parent, f'Point {p["n"]} of {total}')
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(ui.px(22), ui.px(16), ui.px(22), ui.px(14)))
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=f'Point {p["n"]} of {total}  -  {p["section"]}' + (f'  -  {phase}' if phase else ''), style='Small.TLabel').pack(anchor='w')
    ttk.Label(outer, text=describe(p), style='Section.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w', pady=(2, 10))
    if p.get('applied') or p['group'] != 'NONE':
        ttk.Label(outer, text='CALIBRATOR OUTPUT', style='MetricCap.TLabel').pack(anchor='w')
        ttk.Label(outer, text=out_text, style='Reading.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w')
        ttk.Label(outer, text=out_note, style='Small.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w', pady=(0, 10))
    counter = tk.StringVar()
    clock = {'job': None, 'expired': False}
    if limit_s is not None:
        ttk.Label(outer, textvariable=counter, foreground=ui.C.get('bad', '#B3261E'), style='Bold.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w', pady=(0, 8))
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
    ttk.Label(outer, text='METER', style='MetricCap.TLabel').pack(anchor='w')
    meter = f'Rotary switch / function: {p["switch"]}' + (f'\nRange: {p["range"]}' if p['range'] else '')
    ttk.Label(outer, text=meter, wraplength=ui.px(520), justify='left').pack(anchor='w')
    if p.get('note'):
        ttk.Label(outer, text=p['note'], style='Small.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w', pady=(2, 0))
    ttk.Label(outer, text='ACCEPT IF', style='MetricCap.TLabel').pack(anchor='w', pady=(10, 0))
    ttk.Label(outer, text=accept, style='Bold.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w')
    if p.get('tol_text'):
        ttk.Label(outer, text='Limit: ' + p['tol_text'], style='Small.TLabel', wraplength=ui.px(520), justify='left').pack(anchor='w')

    entry = None
    yes = tk.StringVar(value='')
    ann = tk.BooleanVar(value=False)
    error = tk.StringVar(value='')
    if mode == 'numeric':
        ttk.Label(outer, text='METER READING', style='MetricCap.TLabel').pack(anchor='w', pady=(10, 0))
        row = ttk.Frame(outer)
        row.pack(fill='x', pady=(2, 0))
        text = tk.StringVar()
        entry = ttk.Entry(row, textvariable=text, font='CalMetric', width=14)
        entry.pack(side='left')
        ttk.Label(row, text=unit, style='Section.TLabel').pack(side='left', padx=(8, 0))
        if annunciator:
            ttk.Checkbutton(outer, text='The AC annunciator is ON', variable=ann).pack(anchor='w', pady=(6, 0))
        ttk.Label(outer, textvariable=error, foreground=ui.C.get('bad', '#B3261E'), wraplength=ui.px(520), justify='left').pack(anchor='w')
    else:
        ttk.Label(outer, text=question, wraplength=ui.px(520), justify='left', style='Bold.TLabel').pack(anchor='w', pady=(12, 4))
        row = ttk.Frame(outer)
        row.pack(anchor='w')
        ttk.Radiobutton(row, text='Yes - as stated', variable=yes, value='y').pack(side='left')
        ttk.Radiobutton(row, text='No - it does not', variable=yes, value='n').pack(side='left', padx=(16, 0))
        ttk.Label(outer, textvariable=error, foreground=ui.C.get('bad', '#B3261E')).pack(anchor='w')

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

    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(14, 0))
    ok = ttk.Button(bar, text='Record  (Enter)', style='Accent.TButton', command=lambda: done('record'))
    ok.pack(side='right')
    ttk.Button(bar, text='Skip point', command=lambda: done('skip')).pack(side='right', padx=(0, 8))
    ttk.Button(bar, text='Stop run', style='Danger.TButton', command=lambda: done('stop')).pack(side='left')
    win.bind('<Return>', lambda _e: done('record'))
    win.protocol('WM_DELETE_WINDOW', lambda: done('stop'))
    ui.center_on(win, parent.winfo_toplevel())
    (entry or ok).focus_set()
    win.wait_window()
    return result


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


# ============================================================================ application
class App:
    def __init__(self, root, model, demo=False, spec=None, io_factory=None):
        self.root, self.model, self.demo = root, model, demo
        self.spec = spec or load_spec()
        self.info = self.spec['models'][model]
        self.points = points_for(self.spec, model)
        self.by_id = {p['id']: p for p in self.points}
        self.io, self._busy, self.stop = None, False, False
        self.io_factory = io_factory
        self.results = {}
        ui.apply_theme(root)
        root.title(f'{self.info["name"]} | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1320, 800, min_w=1080, min_h=640)
        self.brand = self.info.get('brand', 'Fluke')
        self.last_high_current = None
        self.settings = ui.Settings(f'{self.brand.lower()}{model}')
        self.asset, self.serial = tk.StringVar(), tk.StringVar()
        _saved = self.settings.get('cal_mode', CAL_CHOICES[0])
        self.cal_mode = tk.StringVar(value=OLD_CAL_CHOICES.get(_saved, _saved))
        self.cal_addr = tk.StringVar(value=self.settings.get('cal_addr', 'COM9'))
        self.cal_baud = tk.StringVar(value=self.settings.get('cal_baud', '9600'))
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        self.show_section, self.show_status = tk.StringVar(value='All sections'), tk.StringVar(value='All points')
        self._build_ui()
        self.status.set('DEMO MODE: no commands are sent and no readings are asked for. Enter an Instrument ID, then press Run All.' if demo else
                        'Step 1: enter the Instrument ID. Step 2: choose the calibrator and press Test connection (or choose Manual). Step 3: Run All.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)

    @property
    def busy(self):
        return self._busy

    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'):
            idle = 'disabled' if value else 'normal'
            for b in (self.btn_run, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find):
                b.configure(state=idle)
            self.btn_stop.configure(state='normal' if value else 'disabled')

    @property
    def manual_cal(self):
        return self.cal_mode.get().startswith('Manual')

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        src = self.spec['source']
        banner = ui.Banner(root, f'{self.info["name"]}  -  Performance Verification',
                           f'Manual-reading procedure: the calibrator output is set for you, you read the meter  |  {len(self.points)} points  |  {src["document"]}')
        banner.pack(fill='x')
        banner.add_pill('DEMO MODE  -  simulated readings' if self.demo else 'HARDWARE MODE', 'warn' if self.demo else 'info')
        self.conn_pill = banner.add_pill('Demo - no hardware' if self.demo else 'Not connected', 'neutral')
        ui.StatusBar(root, self.status, right='spec v1').pack(side='bottom', fill='x')
        body = ttk.Frame(root, padding=(18, 14, 18, 10))
        body.pack(fill='both', expand=True)

        top = ttk.Frame(body)
        top.pack(fill='x')
        top.columnconfigure(1, weight=1)
        dut = ttk.LabelFrame(top, text='Instrument under test', padding=12)
        dut.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        ttk.Label(dut, text='Instrument ID *').grid(row=0, column=0, sticky='w', pady=3)
        e = ttk.Entry(dut, textvariable=self.asset, width=22)
        e.grid(row=0, column=1, padx=(10, 0), pady=3)
        e.focus_set()
        ttk.Label(dut, text='Serial number').grid(row=1, column=0, sticky='w', pady=3)
        ttk.Entry(dut, textvariable=self.serial, width=22).grid(row=1, column=1, padx=(10, 0), pady=3)
        ttk.Label(dut, text='Model').grid(row=2, column=0, sticky='w', pady=3)
        ttk.Label(dut, text=self.info['name'] + '  (' + self.info.get('model_note', 'the "C" version uses the same steps') + ')', style='Bold.TLabel').grid(row=2, column=1, sticky='w', padx=(10, 0))

        conn = ttk.LabelFrame(top, text='Calibrator', padding=12)
        conn.grid(row=0, column=1, sticky='nsew')
        conn.columnconfigure(1, weight=1)
        ttk.Label(conn, text='Calibrator').grid(row=0, column=0, sticky='w', pady=3)
        ttk.Combobox(conn, textvariable=self.cal_mode, values=CAL_CHOICES, state='readonly', width=34).grid(row=0, column=1, sticky='w', padx=(8, 12), pady=3)
        self.btn_test = ttk.Button(conn, text='Test connection', command=self.test_connection)
        self.btn_test.grid(row=0, column=3)
        ttk.Label(conn, text='Address').grid(row=1, column=0, sticky='w', pady=3)
        self.cal_entry = ttk.Combobox(conn, textvariable=self.cal_addr, state='normal')
        self.cal_entry.grid(row=1, column=1, sticky='ew', padx=(8, 12), pady=3)
        self.btn_find = ttk.Button(conn, text='Find instruments', command=self.find_instruments)
        self.btn_find.grid(row=1, column=2, padx=(0, 8))
        row = ttk.Frame(conn)
        row.grid(row=1, column=3, sticky='w')
        ttk.Label(row, text='Baud', style='Muted.TLabel').pack(side='left')
        ttk.Combobox(row, textvariable=self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=7, state='readonly').pack(side='left', padx=(5, 0))
        ttk.Label(conn, text='Examples: COM9   ASRL9::INSTR   GPIB0::6::INSTR.  In Manual mode the program tells you what to set and you press OPERATE yourself.',
                  style='Muted.TLabel').grid(row=2, column=1, columnspan=3, sticky='w')

        if self.demo:
            ui.Notice(body, 'Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode').pack(fill='x', pady=(12, 0))
        else:
            extra = ' You are prompted to turn the dial to each range and to change cables, with a hook-up diagram.' if self.spec.get('options', {}).get('range_prompt') else ''
            ui.Notice(body, 'For each point the calibrator is programmed and enabled, then you read the meter and type the value exactly as displayed (without the unit). '
                            'Wiring and high-voltage confirmations are required.' + extra + ' Check the meter fuses and battery before starting.', 'info', title='Hardware mode').pack(fill='x', pady=(12, 0))
        ttk.Label(body, text=src['note'], style='Small.TLabel', wraplength=1100, justify='left').pack(anchor='w', pady=(6, 0))

        tools = ttk.Frame(body)
        tools.pack(fill='x', pady=(8, 6))
        self.btn_run = ttk.Button(tools, text='▶  Run All Pending', style='Accent.TButton', command=self.run_all)
        self.btn_run.pack(side='left')
        self.btn_rerun = ttk.Button(tools, text='Rerun Selected', command=self.rerun)
        self.btn_rerun.pack(side='left', padx=8)
        self.btn_stop = ttk.Button(tools, text='■  Stop After This Point', style='Danger.TButton', command=self.request_stop, state='disabled')
        self.btn_stop.pack(side='left')
        ttk.Button(tools, text='Export Report (PDF)', command=self.export_pdf).pack(side='right', padx=(8, 0))
        self.btn_load = ttk.Button(tools, text='Load progress', command=self.load)
        self.btn_load.pack(side='right', padx=(8, 0))
        ttk.Button(tools, text='Save progress', command=self.save).pack(side='right', padx=(8, 0))

        sumrow = ttk.Frame(body)
        sumrow.pack(fill='x', pady=(2, 8))
        self.summary = ui.Summary(sumrow)
        self.summary.pack(side='left', fill='x', expand=True)
        filt = ttk.Frame(sumrow)
        filt.pack(side='right', padx=(24, 0))
        ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='left')
        sections = ['All sections'] + list(dict.fromkeys(p['section'] for p in self.points))
        c1 = ttk.Combobox(filt, textvariable=self.show_section, values=sections, width=22, state='readonly')
        c1.pack(side='left', padx=6)
        c2 = ttk.Combobox(filt, textvariable=self.show_status, values=['All points', 'Not tested', 'Passed', 'Failed (OOT)'], width=13, state='readonly')
        c2.pack(side='left')
        for c in (c1, c2):
            c.bind('<<ComboboxSelected>>', lambda _e: self.refresh())

        info = ttk.LabelFrame(body, text='Selected test point', padding=(12, 8))
        info.pack(side='bottom', fill='x', pady=(10, 0))
        ttk.Label(info, textvariable=self.detail, wraplength=1000, justify='left').pack(anchor='w', fill='x')
        cols = ('n', 'step', 'section', 'description', 'output', 'low', 'high', 'reading', 'units', 'result')
        self.tree = ui.make_table(body, cols, ('#', 'Manual step', 'Section', 'Description', 'Calibrator output', 'Low limit', 'High limit', 'Reading', 'Units', 'Result'),
                                  (40, 84, 130, 270, 170, 84, 84, 90, 54, 84), height=12,
                                  anchors={'description': 'w', 'section': 'w', 'output': 'w', 'low': 'e', 'high': 'e', 'reading': 'e', 'units': 'w', 'step': 'w'},
                                  stretch={k: False for k in cols if k != 'description'})
        self.tree.tag_configure('pending', foreground=ui.C['muted'])
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        self.refresh()
        ui.polish(root)

    # ------------------------------------------------------------------ table
    def _visible(self, p):
        res = self.results.get(p['id'], {}).get('result', '')
        sec, st = self.show_section.get(), self.show_status.get()
        if sec != 'All sections' and p['section'] != sec:
            return False
        if st == 'Not tested' and res:
            return False
        if st == 'Passed' and res != 'PASS':
            return False
        if st == 'Failed (OOT)' and res != 'FAIL':
            return False
        return True

    def _row(self, p):
        rec = self.results.get(p['id'], {})
        res = rec.get('result', '')
        shown = {'PASS': '✔ PASS', 'FAIL': '✖ FAIL'}.get(res, '—')
        step = p.get('ref') or ('p. 7' if p['table'] == 'F' else f'T{p["table"]} #{p["step"]}')
        numeric = p['test'] == 'numeric'
        values = (p['n'], step, p['section'], describe(p), output_text(p) if p.get('applied') else '—',
                  p['low'] if numeric else '', p['high'] if numeric else '', rec.get('entered', ''), p['display_unit'] if numeric else '', shown)
        return values, (res.lower() or 'pending',)

    def refresh(self):
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for p in self.points:
            if self._visible(p):
                values, tags = self._row(p)
                self.tree.insert('', 'end', iid=p['id'], values=values, tags=tags)
        if keep and self.tree.exists(keep[0]):
            self.tree.selection_set(keep[0])
        self.update_summary()

    def _update_row(self, p):
        if self.tree.exists(p['id']):
            values, tags = self._row(p)
            self.tree.item(p['id'], values=values, tags=tags)
        self.update_summary()

    def update_summary(self):
        vals = [self.results.get(p['id'], {}).get('result', '') for p in self.points]
        self.summary.update_counts(len(self.points), vals.count('PASS'), vals.count('FAIL'))

    def accept_text(self, p):
        if p['test'] == 'numeric':
            extra = '  and the AC annunciator is ON' if p.get('annunciator') else ''
            return f'{p["low"]} to {p["high"]} {p["display_unit"]}{extra}'
        return p.get('question') or ' / '.join(c['question'] for c in p['checks'])

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        p = self.by_id[sel[0]]
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        limit = f'\nLimit: {p["tol_text"]}' if p.get('tol_text') else ''
        self.detail.set(f'{describe(p)}\nAccept: {self.accept_text(p)}  |  Meter: {p["switch"]}' + (f', {p["range"]} range' if p['range'] else '') + limit +
                        f'\nSetup: {self.setup_text(p)}{extra}')

    def hookup_meter(self):
        return self.spec.get('options', {}).get('hookup_meter')

    def group_spec(self, p):
        """Cable-change text and diagram for the point's group: from hookups.py (follows the calibrator choice) when the spec names a
        hookup_meter, else from the spec's own groups."""
        meter = self.hookup_meter()
        if meter and hookups.has(meter, p['group']):
            cal = hookups.calibrator_key(self.cal_mode.get())
            plan = hookups.plan(meter, cal, p['group'], self.manual_cal)
            plan['summary'] = hookups.summary(meter, cal, p['group'])
            plan['diagram'] = plan['image']
            return plan
        return self.spec.get('groups', {}).get(p['group'])

    def setup_text(self, p):
        if p.get('setup'):
            return p['setup']
        if p['group'] == 'NONE':
            return 'No calibrator output.'
        group = self.group_spec(p)
        if group:
            return group['summary']
        return WIRING.get(p['group'], WIRING['VOHM'])

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.')
            return
        self.cal_entry['values'] = found
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none'))

    def _address(self):
        t = self.cal_addr.get().strip()
        if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
            return t
        t = t.upper().replace('COM', '')
        if not t.isdigit():
            raise ValueError('Enter a COM port (COM9) or a full VISA address (ASRL9::INSTR, GPIB0::6::INSTR).')
        return f'ASRL{int(t)}::INSTR'

    def connect(self):
        self.disconnect()
        if self.io_factory:
            self.io = self.io_factory()
        else:
            self.io = IO(self.cal_mode.get(), self._address(), int(self.cal_baud.get()))
        self._set_conn(True)
        self._save_settings()

    def test_connection(self):
        if self.demo:
            messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.')
            return
        if self.manual_cal:
            messagebox.showinfo('Manual calibrator', 'Manual mode: no connection is needed. The program will tell you what to set on the calibrator.')
            return
        self.status.set('Connecting ...')
        self.root.update_idletasks()
        try:
            self.connect()
        except Exception as exc:
            self.disconnect()
            self._set_conn(False)
            self.status.set('Connection error: ' + str(exc))
            messagebox.showerror('Connection error', str(exc))
            return
        self.status.set('Connected: ' + self.io.ident + '. Calibrator output is NOT enabled.')
        messagebox.showinfo('Connected', f'{self.io.ident}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io:
            self.io.close()
            self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Demo - no hardware' if self.demo else 'Manual calibrator' if self.manual_cal else 'Not connected',
                           'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('cal_mode', self.cal_mode), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud)):
            self.settings.set(key, var.get())
        self.settings.save()

    # ------------------------------------------------------------------ running
    def request_stop(self):
        self.stop = True
        self.status.set('Stopping after the current test point.')

    def run_all(self):
        self.execute([p for p in self.points if p['id'] not in self.results])

    def rerun(self):
        sel = self.tree.selection()
        if sel:
            self.execute([self.by_id[sel[0]]])
        else:
            messagebox.showinfo('Selection', 'Select a test point first.')

    def execute(self, points):
        if self.busy or not points:
            return
        if not self.asset.get().strip():
            messagebox.showwarning('Instrument ID', 'Enter an instrument ID.')
            return
        if not self.demo and not self.manual_cal and self.io is None:
            self.test_connection()
            if self.io is None:
                return
        self.stop = False
        self.busy = True
        self._next(points, 0, None)

    def _group_key(self, p):
        return p['id'] if p['group'] == 'NONE' else p['group']

    def _prompt_setup(self, p):
        group = self.group_spec(p)
        if group:
            steps = [tuple(step) for step in group['steps']]
            if self.manual_cal:
                steps = [(lead, detail.replace('The program switches the output off after 30 s.', 'Switch the calibrator to STANDBY after 30 s.')) for lead, detail in steps]
            facts = [('Next point', f'{p["n"]} of {len(self.points)}'), ('Test', describe(p)), ('Meter', p['switch'] + (f', range {p["range"]}' if p['range'] else ''))]
            image = group['diagram'] if group.get('diagram') and Path(group['diagram']).is_absolute() else (HERE / group['diagram'] if group.get('diagram') else None)
            return ui.confirm_steps(self.root, 'Change the cables', group['title'], steps, facts=facts, caution=group.get('caution'),
                                    ok='Connections checked - continue', image=image if image and image.is_file() else None)
        steps = []
        if p['group'] == 'NONE':
            steps.append(('Set up', p['setup']))
        else:
            steps.append(('Standby', 'The calibrator is put in STANDBY before you rewire.' if not self.manual_cal else 'Put the calibrator in STANDBY before you rewire.'))
            steps.append(('Wiring', WIRING.get(p['group'], WIRING['VOHM'])))
            if p.get('setup'):
                steps.append(('This test', p['setup']))
        facts = [('Next point', f'{p["n"]} of {len(self.points)}'), ('Test', describe(p)), ('Meter', p['switch'] + (f', range {p["range"]}' if p['range'] else ''))]
        caution = None if p['group'] == 'NONE' else 'Continue only after physically verifying the connections.'
        return ui.confirm_steps(self.root, 'Check the setup', f'Set up for {p["section"]}', steps, facts=facts, caution=caution, ok='Done - continue')

    def _high_voltage(self, p):
        a = p.get('applied')
        threshold = self.spec.get('options', {}).get('hv_threshold_v', 500)
        return bool(a) and p['kind'] in ('DCV', 'ACV') and abs(a['value']) >= threshold

    def _prompt_range(self, p):
        """'ok' / 'skip' / 'stop' - only for specs that ask for range selection (options.range_prompt)."""
        if not self.spec.get('options', {}).get('range_prompt') or not p.get('dial'):
            return 'ok'
        text = ('Put the calibrator in STANDBY while you turn the dial. The program sets the output after you continue.' if self.manual_cal
                else 'The calibrator output is OFF (standby) while you turn the dial. The program sets the output after you continue.')
        return ask_range(self.root, p, len(self.points), self.spec['dial'], text)

    def _rest_remaining(self, p):
        """Seconds the meter must still rest before a high-current point (0 when none is needed)."""
        rest = p.get('recovery_s')
        if not rest or self.last_high_current is None:
            return 0.0
        return max(0.0, rest - (time.monotonic() - self.last_high_current))

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False
            self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.')
            return
        p = points[i]
        key = self._group_key(p)
        if self.tree.exists(p['id']):
            self.tree.selection_set(p['id'])
            self.tree.see(p['id'])
        if self.demo:
            self._record_demo(p)
            self.root.after(20, lambda: self._next(points, i + 1, key))
            return
        if self.io:
            self.io.standby()
        wait = self._rest_remaining(p)
        if wait > 0:
            self.busy = False
            self.status.set(f'Paused: the meter must rest {wait / 60:.1f} more minutes after a high-current point.')
            messagebox.showinfo('Meter rest period', f'The meter manual requires 10 minutes of rest after measuring more than 6 A. '
                                                     f'Wait about {int(wait // 60)} min {int(wait % 60)} s, then press Run again.')
            return
        if key != previous and not self._prompt_setup(p):
            self.busy = False
            self.status.set('Paused for wiring or setup.')
            return
        choice = self._prompt_range(p)
        if choice == 'stop':
            self.busy = False
            self.status.set('Stopped at the range selection. Progress is saved.')
            self.save()
            return
        if choice == 'skip':
            self.root.after(30, lambda: self._next(points, i + 1, key))
            return
        if self._high_voltage(p):
            if not messagebox.askyesno('HIGH VOLTAGE', f'This point outputs {abs(p["applied"]["value"]):g} V'
                                       + (' (the voltage is ramped up in 50 V steps, 5 s apart)' if not self.manual_cal else '') +
                                       '. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?'):
                self.busy = False
                self.status.set('Stopped before a high-voltage point.')
                return
        if p.get('applied') and not self.manual_cal:
            self.status.set(f'Point {p["n"]}/{len(self.points)}: setting the calibrator to {output_text(p)} ...')

            state = {'done': False, 'exc': None}

            def work():
                try:
                    self.io.apply(p, cancel=lambda: self.stop)
                except BaseException as exc:          # reported on the main thread by _poll
                    state['exc'] = exc
                    try:
                        self.io.standby()
                    except Exception:
                        pass
                state['done'] = True
            threading.Thread(target=work, daemon=True).start()
            self._poll(points, i, p, key, state)
        else:
            self._ask(points, i, p, key)

    def _poll(self, points, i, p, key, state):
        """The worker thread only sets flags; every Tk call happens here on the main thread."""
        if not state['done']:
            self.root.after(40, lambda: self._poll(points, i, p, key, state))
        elif isinstance(state['exc'], Cancelled):
            self._ask_abort()
        elif state['exc'] is not None:
            self._error(state['exc'])
        else:
            self._ask(points, i, p, key)

    def _ask_abort(self):
        self.busy = False
        self.status.set('Stopped. The calibrator is in STANDBY.')

    def _error(self, exc):
        self.busy = False
        self.status.set('Error - run stopped: ' + str(exc))
        messagebox.showerror('Calibrator stopped', str(exc))

    def _out_note(self, p, on):
        if not p.get('applied'):
            return ''
        if self.manual_cal:
            return 'Set this on the calibrator and press OPERATE, then read the meter.'
        return 'Output is ON - allow the reading to settle, then read the meter.' if on else 'Output is in STANDBY.'

    def _ask(self, points, i, p, key):
        total = len(self.points)
        self.status.set(f'Point {p["n"]}/{total}: waiting for the meter reading.')
        if p['test'] == 'numeric':
            def validate(text):
                judge_numeric(p, text)
            limit = {}
            if p.get('max_on_s'):
                on_at = getattr(self.io, 'on_at', None) if self.io and not self.manual_cal else None
                used = (time.monotonic() - on_at) if on_at else 0.0
                limit = dict(limit_s=max(1.0, p['max_on_s'] - used), on_expire=self._safe_standby if self.io and not self.manual_cal else None)
            r = ask_reading(self.root, p, total, output_text(p), self._out_note(p, True), self.accept_text(p), 'numeric',
                            unit=p['display_unit'], annunciator=bool(p.get('annunciator')), validate=validate, **limit)
            if p.get('recovery_s'):
                self.last_high_current = time.monotonic()
            if r['action'] == 'record':
                result, base = judge_numeric(p, r['text'], r['ann'])
                self._store(p, entered=r['text'].strip(), reading=base, result=result, annunciator=r['ann'] if p.get('annunciator') else None)
        elif p.get('checks'):
            answers = []
            r = dict(action='record')
            for n, chk in enumerate(p['checks'], 1):
                if not chk['output'] and self.io and not self.manual_cal:
                    self.io.standby()
                note = self._out_note(p, chk['output']) if not self.manual_cal else ('Output ON.' if chk['output'] else 'Put the calibrator in STANDBY.')
                r = ask_reading(self.root, p, total, output_text(p), note, chk['question'], 'yesno', question=chk['question'], phase=f'check {n} of {len(p["checks"])}')
                if r['action'] != 'record':
                    break
                answers.append(r['yes'])
            if r['action'] == 'record':
                self._store(p, entered='Pass' if all(answers) else 'Fail', reading=None, result='PASS' if all(answers) else 'FAIL', answers=answers)
        else:
            r = ask_reading(self.root, p, total, output_text(p), self._out_note(p, True), p['question'], 'yesno', question=p['question'])
            if r['action'] == 'record':
                ok = r['yes'] if p['test'] == 'visual' else (r['yes'])
                self._store(p, entered=('Pass' if ok else 'Fail') if p['test'] == 'visual' else
                            (f'Beeper {p["expect"]}' if ok else f'Beeper not {p["expect"]}'), reading=None, result='PASS' if ok else 'FAIL')
        if self.io and not self.manual_cal:
            self.io.standby()
        if r['action'] == 'stop':
            self.stop = True
        self.root.after(30, lambda: self._next(points, i + 1, key))

    def _safe_standby(self):
        try:
            self.io.standby()
        except Exception:
            pass

    def _store(self, p, **fields):
        fields.setdefault('synthetic', False)
        fields['timestamp'] = datetime.now().isoformat(timespec='seconds')
        self.results[p['id']] = fields
        self._update_row(p)
        self.save(silent=True)

    def _record_demo(self, p):
        """Deterministic, labelled synthetic reading inside the limits."""
        if p['test'] == 'numeric':
            lo, hi = Decimal(p['low']), Decimal(p['high'])
            places = max(-lo.as_tuple().exponent, -hi.as_tuple().exponent, 0)
            mid, half = (lo + hi) / 2, (hi - lo) / 2
            value = mid + half * Decimal(str(round(math.sin(p['n'] * 1.71) * 0.38, 4)))
            text = f'{value:.{places}f}'
            result, base = judge_numeric(p, text)
            self._store(p, entered=text, reading=base, result=result, synthetic=True, annunciator=True if p.get('annunciator') else None)
        else:
            entered = {'beeper': f'Beeper {p.get("expect", "")}'}.get(p['test'], 'Pass')
            self._store(p, entered=entered, reading=None, result='PASS', synthetic=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return HERE / 'Procedures' / f'{self.brand}{self.model}_{name}_checkpoint.json'

    def save(self, silent=False):
        path = self._checkpoint_path()
        try:
            path.write_text(json.dumps(dict(model=self.model, asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, results=self.results), indent=2))
        except OSError as exc:
            if not silent:
                self.status.set(f'Could not save progress: {exc}')
            return
        if not silent:
            self.status.set(f'Saved {path.name}')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Checkpoint', '*.json')])
        if not path:
            return
        data = json.loads(Path(path).read_text())
        if data.get('model') != self.model:
            messagebox.showerror('Wrong model', f'This checkpoint is for the Fluke {data.get("model")}.')
            return
        if any(v.get('synthetic') for v in data.get('results', {}).values()) and not self.demo:
            if not messagebox.askyesno('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'):
                return
        self.asset.set(data.get('asset', ''))
        self.serial.set(data.get('serial', ''))
        self.results = data.get('results', {})
        self.refresh()
        self.status.set(f'Loaded progress: {len(self.results)} point(s) restored.')

    # ------------------------------------------------------------------ report
    def certificate_rows(self):
        import report_pdf
        rows = []
        for p in self.points:
            r = self.results.get(p['id'])
            if not r:
                continue
            failed = r['result'] == 'FAIL'
            if p['test'] == 'numeric':
                factor = Decimal(str(p['factor']))
                clean = lambda d: float(f'{float(d * factor):.9g}')
                unit = SYMBOL[p['base_unit']]
                unc = ''
                if p['kind'] in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP') and p.get('applied') and not p.get('no_uncertainty'):
                    unc = report_pdf.point_uncertainty(dict(kind='OHM2' if p['kind'] == 'OHM' else p['kind'], nominal=p['applied']['value'],
                                                            frequency=p['applied'].get('frequency'), unit=p['base_unit'], range=None))
                a = p.get('applied') or {}
                freq = a.get('frequency') if p['kind'] in ('ACV', 'ACI') and p['display_unit'] != 'kHz' else None
                row = report_pdf.cert_row(f'{p["range"]} range' if p['range'] else describe(p), p['nominal'], clean(Decimal(p['low'])), clean(Decimal(p['high'])),
                                          unit, reading=r['reading'] if r['reading'] is not None else None, failed=failed, section=p['section'],
                                          frequency=freq, uncertainty=unc)
                if r['reading'] is None:           # overload
                    row['As Found'] = r.get('entered', '')
                if p.get('annunciator') and r.get('annunciator') is not None:
                    row['As Found'] += '  (AC annunciator ' + ('on' if r['annunciator'] else 'OFF') + ')'
                if p['kind'] == 'ACV' and p['display_unit'] == 'kHz':
                    row['Description'] = f'{p["range"]} range (2 V applied)'
            else:
                unc = ''
                if p['test'] == 'beeper':
                    unc = report_pdf.point_uncertainty(dict(kind='OHM2', nominal=p['applied']['value'], frequency=None, unit='ohm', range=None))
                row = {'Section': p['section'], 'Description': report_pdf.ascii_unit(describe(p)),
                       'Nominal': report_pdf.ascii_unit(output_text(p)) if p.get('applied') else '', 'Tolerance -': '', 'Tolerance +': '', 'UOM': '',
                       'As Found': r.get('entered', ''), 'OOT': 'OOT' if failed else '', 'As Left': 'Same', 'Uncertainty': unc}
            rows.append(row)
        return rows

    def export_pdf(self):
        rows = self.certificate_rows()
        if not rows:
            messagebox.showinfo('No results', 'No recorded results to export yet.')
            return
        try:
            import report_pdf
            import report_dialog
        except ImportError as exc:
            messagebox.showerror('Report export', str(exc))
            return
        details = report_dialog.ask_details(self.root, f'{self.info["name"]} performance verification')
        if details is None:
            return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path:
            return
        demo = self.demo or any(v.get('synthetic') for v in self.results.values())
        src = self.spec['source']
        try:
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', self.info['name']), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Limits applied', src.get('limits', 'Manufacturer display-reading limits (12 month)')),
                                                                 ('Source', src.get('cite') or f'{src["document"]}, pp. {src["pages"].split(" ")[0]}')],
                                             title=f'{self.info["name"]} Performance Verification', demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows))
        except ImportError:
            messagebox.showerror('PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab')
            return
        except Exception as exc:
            messagebox.showerror('PDF export error', str(exc))
            return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'):
            return
        self.stop = True
        self._save_settings()
        self.disconnect()
        self.root.destroy()


def main(model, argv=None, spec=None):
    """spec: a spec file name inside specs/ (or a path); the Fluke 110-series spec when omitted."""
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    App(root, model, demo='--demo' in argv, spec=load_spec(spec) if spec else None)
    root.mainloop()
