"""Keysight 34970A / 34972A internal-DMM performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_<model>_pv.json (built by
specs/build_dacq_spec.py from the 34970A/34972A Service Guide, Chapter 4, pp. 80-87). Default limits: 1 year.

Bench: the 34970A (RS-232, selectable COM port) or the 34972A (USB), a 34901A multiplexer (or 34902A, no current tests),
and a Fluke 5560A or 5522A calibrator as the source. The program configures the DMM for every point (function, range,
10 PLC / 3 Hz AC filter / frequency gate), selects the channel, drives the calibrator and reads the result. It pauses
for a hook-up diagram whenever the wiring changes and never runs unattended. Hardware I/O is OFF in demo mode.

    import dacq_verification
    dacq_verification.main('34970A')       # what Procedures/Keysight_34970A_Verification.py does
"""
import json, math, sys, threading, time, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_theme as ui
import ui_shell
import appdata
import datamode
import procspec
import drivers
from drivers.keysight_dacq import channel_for, pair_channel

MODEL = SPEC_PATH = SPEC = POINTS = None
PERIODS = {'24 hours': '24h', '90 days': '90d', '1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
CALIBRATORS = {'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5522A': ('5522A', drivers.Fluke5522A)}
PARITY_FORMATS = {'8 data bits, no parity': (8, 'none'), '7 data bits, even parity': (7, 'even'), '7 data bits, odd parity': (7, 'odd')}
FLOW = {'XON/XOFF (instrument default)': 'xon_xoff', 'None': 'none', 'RTS/CTS': 'rts_cts'}
BAUDS = ['57600', '115200', '38400', '19200', '9600', '4800', '2400', '1200']
GROUPS = ('ZERO_SHORT', 'ZERO_OPEN', 'DCV', 'OHM4', 'OHM2', 'DCI', 'ACV', 'ACI', 'FREQ')
GROUP_TITLE = {'ZERO_SHORT': 'Shorted input (zero offset)', 'ZERO_OPEN': 'Open current input (zero offset)', 'DCV': 'DC volts',
               'OHM4': '4-wire ohms', 'OHM2': '2-wire ohms', 'DCI': 'DC current', 'ACV': 'AC volts', 'ACI': 'AC current', 'FREQ': 'Frequency'}


def configure(model):
    """Select the model: loads its spec, numbers the points and writes plain descriptions."""
    global MODEL, SPEC_PATH, SPEC, POINTS
    MODEL = model
    SPEC_PATH = HERE / 'specs' / f'keysight_{model.lower()}_pv.json'
    SPEC = procspec.load(SPEC_PATH)
    POINTS = procspec.flatten(SPEC)
    for p in POINTS:
        if p['source'] == 'none':
            what = 'input open' if p.get('input') == 'open' else 'input shorted'
            p['description'] = f"Zero offset, {procspec.NAMES[p['kind']]}, {procspec._fmt(p['range'], p['unit'])} range ({what})"
    procspec.apply_period(POINTS, SPEC['default_period'])


def find_diagram(model, cal, group):
    """Hook-up picture for a wiring group: diagrams/hook_<model>_<cal>_<GROUP>.png, then the shared hook_dacq_ names."""
    for name in (f'hook_{model}_{cal}_{group}', f'hook_dacq_{cal}_{group}', f'hook_{model}_{group}', f'hook_dacq_{group}'):
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def to_visa(text):
    """'COM9' / '9' -> 'ASRL9::INSTR'; anything that already looks like a VISA resource passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port such as COM9.')
    return f'ASRL{int(t)}::INSTR'


def list_com_ports():
    """Names of the serial ports on this computer (pyserial, else the VISA ASRL resources). [] when neither is installed."""
    try:
        from serial.tools import list_ports
        return sorted((p.device for p in list_ports.comports()), key=lambda s: (len(s), s))
    except Exception:
        pass
    try:
        import pyvisa
        return [r for r in pyvisa.ResourceManager().list_resources() if r.upper().startswith('ASRL')]
    except Exception:
        return []


class IO:
    """Bench I/O: the 34970A / 34972A and the calibrator, both through the instrument drivers."""
    SETTLE_AC = {10: 6.0, 20: 5.0}

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5560A', cal_baud=9600, module='34901A', slot=2,
                 serial=None, transports=None):
        self.log = drivers.CommandLog()
        self.module, self.slot = module, int(slot)
        cal_name, cal_cls = CALIBRATORS[cal_model]
        if transports:
            dmm_t, cal_t = transports
        else:
            if MODEL == '34970A':
                dmm_t = drivers.open_visa(to_visa(dmm_address), timeout=30, **(serial or {}))
            else:
                dmm_t = drivers.open_visa(dmm_address.strip(), timeout=30)
            cal_t = drivers.open_visa(to_visa(cal_address), timeout=20, baud=cal_baud)
        self.dmm = getattr(drivers, f'Keysight{MODEL}')(dmm_t, self.log, label=MODEL)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            self.dmm.connect()
            self.dmm.require_module(module, self.slot)
            self.dmm.check_errors('connecting')
        except Exception:
            self.close(); raise
        self.ident = self.dmm.idn

    def standby(self):
        self.cal.standby_quiet()

    def close(self):
        try: self.standby()
        except Exception: pass
        try: self.dmm.cleanup()
        except Exception: pass
        for obj in (self.dmm, self.cal):
            try: obj.close()
            except Exception: pass
        self.save_log()

    def save_log(self):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt."""
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def channel(self, p):
        return channel_for(self.module, self.slot, p['role'])

    def settle(self, p):
        if p['kind'] == 'FREQ': return 3.0
        if p['kind'] == 'ACV': return self.SETTLE_AC.get(p.get('frequency'), 4.0)
        if p['kind'] == 'ACI': return 4.0
        if p['kind'] in ('OHM2', 'OHM4') and p['range'] >= 1e7: return 4.0
        if p['kind'] in ('DCI', 'OHM2'): return 3.0
        return 2.0

    def measure(self, p):
        self.standby()
        ch = self.channel(p)
        self.dmm.configure_point(p, ch)
        self.dmm.check_errors('configuring ' + p['description'])
        if p['source'] == 'none':          # copper short / open input: the calibrator stays in STANDBY
            time.sleep(1.5)
            reading = self.dmm.read()
            self.dmm.check_errors('reading ' + p['description'])
            return reading
        k, v, f = p['kind'], p['nominal'], p.get('frequency')
        if k in ('DCV', 'ACV'): self.cal.set_output_volts(v, f)
        elif k in ('DCI', 'ACI'): self.cal.set_output_amps(v, f)
        elif k in ('OHM2', 'OHM4'): self.cal.set_output_ohms(v)
        elif k == 'FREQ': self.cal.set_output_volts(p['amplitude'], v)
        self.cal.check_error(p['description'])   # the calibrator refuses outputs it cannot make; never operate then
        self.cal.operate_unverified()
        time.sleep(self.settle(p))
        reading = self.dmm.read()
        self.standby()
        self.dmm.check_errors('reading ' + p['description'])
        return reading


class App(datamode.DataModeMixin):
    def __init__(self, root, model, demo=False):
        configure(model)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        ui.apply_theme(root)
        root.title(f'Keysight {MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1340, 860, min_w=900, min_h=660)
        self.settings = ui.Settings(MODEL)
        s = self.settings
        self.asset = tk.StringVar(); self.serial = tk.StringVar()
        self.rs232 = SPEC.get('interface') == 'rs232'
        ports = list_com_ports() if self.rs232 else []
        self.dmm_addr = tk.StringVar(value=s.get('dmm_addr', (ports[0] if ports else 'COM1') if self.rs232 else 'USB0::0x0957::0x2007::MY00000000::INSTR'))
        self.dmm_baud = tk.StringVar(value=s.get('dmm_baud', '57600'))
        self.dmm_format = tk.StringVar(value=s.get('dmm_format', '8 data bits, no parity'))
        self.dmm_flow = tk.StringVar(value=s.get('dmm_flow', 'XON/XOFF (instrument default)'))
        self.cal_model = tk.StringVar(value=s.get('cal_model', 'Fluke 5560A'))
        self.cal_addr = tk.StringVar(value=s.get('cal_addr', 'COM9'))
        self.cal_baud = tk.StringVar(value=s.get('cal_baud', '9600'))
        self.module = tk.StringVar(value=s.get('module', '34901A'))
        self.slot = tk.StringVar(value=s.get('slot', '2'))
        self.period = tk.StringVar(value=s.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.include_ohm2 = tk.BooleanVar(value=False)
        self.include_ac = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits, channel and setup.')
        self.show_section = tk.StringVar(value='All sections')
        self.show_status = tk.StringVar(value='All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose the connections and press Test Connections. Step 3: Run All.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)

    # ------------------------------------------------------------------ selection
    @property
    def cal_key(self): return CALIBRATORS[self.cal_model.get()][0]

    def active(self, p):
        if p.get('opt') == 'ohm2' and not self.include_ohm2.get(): return False
        if p.get('opt') == 'ac' and not self.include_ac.get(): return False
        if p['role'] == 'current' and self.module.get() == '34902A': return False     # the 34902A has no current input
        return True

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    def _sync_buttons(self):
        idle = 'disabled' if self._busy else 'normal'
        for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
            b.configure(state=idle)
        self.btn_stop.configure(state='normal' if self._busy else 'disabled')
        for c in (self.period_combo, self.module_combo, self.slot_combo, self.ohm2_check, self.ac_check):
            c.configure(state='disabled' if self._busy else ('readonly' if isinstance(c, ttk.Combobox) else 'normal'))

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        sh = self.shell = ui_shell.Shell(root, f'Keysight {MODEL}  -  Performance Verification',
                                         f'Internal DMM tests from the 34970A/34972A Service Guide, pp. 80-87  |  {len(POINTS)} points in the spec  |  '
                                         + ('RS-232' if self.rs232 else 'USB'), demo=self.demo, on_section=self.pick_section, version='spec v1')
        self.status = sh.status_var
        self.conn_pill = sh.add_chip('Not connected', 'neutral')
        sh.build_identity(self.asset, self.serial)
        self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
        self.summary = sh.build_progress()
        if self.demo: sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode')
        else: sh.notice('The program pauses and shows the hook-up for every new setup and before any high-voltage point. Warm the instrument up for 2 hours with a copper short on the multiplexer first. Stay at the bench while a run is in progress.', 'info')

        d = sh.drawer_body; d.columnconfigure(1, weight=1)
        ttk.Label(d, text='Limits to apply').grid(row=0, column=0, sticky='w', pady=4)
        self.period_combo = ttk.Combobox(d, textvariable=self.period, values=list(PERIODS), width=20, state='readonly')
        self.period_combo.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=4)
        self.period_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
        ttk.Label(d, text='Multiplexer module').grid(row=1, column=0, sticky='w', pady=4)
        mod = ttk.Frame(d); mod.grid(row=1, column=1, sticky='w', padx=(10, 0), pady=4)
        self.module_combo = ttk.Combobox(mod, textvariable=self.module, values=['34901A', '34902A'], width=8, state='readonly')
        self.module_combo.pack(side='left'); self.module_combo.bind('<<ComboboxSelected>>', lambda _e: (self.refresh(), self._save_settings()))
        ttk.Label(mod, text='slot', style='Muted.TLabel').pack(side='left', padx=(8, 4))
        self.slot_combo = ttk.Combobox(mod, textvariable=self.slot, values=['1', '2', '3'], width=3, state='readonly')
        self.slot_combo.pack(side='left'); self.slot_combo.bind('<<ComboboxSelected>>', lambda _e: (self.refresh(), self._save_settings()))
        self.ohm2_check = ttk.Checkbutton(d, text='Include 2-wire ohms (optional)', variable=self.include_ohm2, command=self.refresh)
        self.ohm2_check.grid(row=2, column=0, columnspan=2, sticky='w', pady=(4, 0))
        self.ac_check = ttk.Checkbutton(d, text='Include optional AC tests', variable=self.include_ac, command=self.refresh)
        self.ac_check.grid(row=3, column=0, columnspan=2, sticky='w', pady=(2, 10))
        ttk.Separator(d).grid(row=4, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        r = 5
        wrap = ui.px(340)
        if self.rs232:
            ttk.Label(d, text='34970A COM port').grid(row=r, column=0, sticky='w', pady=4)
            self.dmm_entry = ttk.Combobox(d, textvariable=self.dmm_addr, values=list_com_ports(), state='normal', width=14)
            self.dmm_entry.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
            for text, var, values, width in (('Baud', self.dmm_baud, BAUDS, 9), ('Format', self.dmm_format, list(PARITY_FORMATS), 24), ('Flow control', self.dmm_flow, list(FLOW), 30)):
                ttk.Label(d, text=text).grid(row=r, column=0, sticky='w', pady=4)
                ttk.Combobox(d, textvariable=var, values=values, width=width, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
            ttk.Label(d, text='On the 34970A: Interface > I/O Config, choose RS-232 and set the same baud, parity and flow control. Factory default: 57600, 8 bits no parity, XON/XOFF.',
                      style='Muted.TLabel', wraplength=wrap, justify='left').grid(row=r, column=0, columnspan=2, sticky='w', pady=(2, 6)); r += 1
            find_text = 'Refresh ports'
        else:
            ttk.Label(d, text='34972A USB address').grid(row=r, column=0, sticky='w', pady=4)
            self.dmm_entry = ttk.Combobox(d, textvariable=self.dmm_addr, state='normal', width=34)
            self.dmm_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
            ttk.Label(d, text='Example: USB0::0x0957::0x2007::<serial>::INSTR  (press Find instruments with the USB cable connected)',
                      style='Muted.TLabel', wraplength=wrap, justify='left').grid(row=r, column=0, columnspan=2, sticky='w', pady=(0, 6)); r += 1
            find_text = 'Find instruments'
        ttk.Label(d, text='Calibrator').grid(row=r, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.cal_model, values=list(CALIBRATORS), width=14, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='Calibrator address').grid(row=r, column=0, sticky='w', pady=4)
        self.cal_entry = ttk.Combobox(d, textvariable=self.cal_addr, state='normal', width=34)
        self.cal_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='Calibrator baud').grid(row=r, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='COM9, GPIB0::6::INSTR ...', style='Muted.TLabel').grid(row=r, column=1, sticky='w', padx=(10, 0)); r += 1
        btns = sh.drawer_footer
        self.btn_find = ttk.Button(btns, text=find_text, command=self.find_instruments); self.btn_find.pack(side='left', padx=(0, 8))
        self.btn_test = ttk.Button(btns, text='Test connections', command=self.test_connections, style='Accent.TButton'); self.btn_test.pack(side='left')

        self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
        self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
        self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
        self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
        sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
        self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
        sh.add_action('Save progress', self.save, side='right', short='Save')

        body = sh.content
        info = ttk.Frame(body); info.pack(side='bottom', fill='x', pady=(8, 0))
        ttk.Label(info, textvariable=self.detail, wraplength=1000, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
        ttk.Label(info, text=SPEC['source']['note'], style='Small.TLabel', wraplength=1000, justify='left').pack(anchor='w', pady=(4, 0))
        filt = ttk.Frame(body); filt.pack(side='top', fill='x', pady=(0, 6))
        ttk.Label(filt, text='Test points', style='Bold.TLabel').pack(side='left')
        c2 = ttk.Combobox(filt, textvariable=self.show_status, values=datamode.STATUS_FILTERS, width=14, state='readonly'); c2.pack(side='right')
        ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='right', padx=(0, 6))
        c2.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        self.tree = ui_shell.results_table(self, body)
        ui_shell.small_window(self, self.tree, filt)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        self.update_shell_sections(POINTS, lambda p: p['section_title'])
        ui.polish(root)

    # ------------------------------------------------------------------ table
    def _visible(self, p):
        if not self.active(p): return False
        res = self.results.get(str(p['id']), {}).get('result', '')
        sec = self.show_section.get(); st = self.show_status.get()
        if sec != 'All sections' and p['section_title'] != sec: return False
        if st == 'Not tested' and res: return False
        if st == 'Passed' and res != 'PASS': return False
        if st == 'Failed (OOT)' and res != 'FAIL': return False
        if not self.status_visible(str(p['id']), st): return False
        return True

    def _row(self, p):
        cells, tags = self.shell_cells(p['id'], p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error'], p['unit'])
        return (p['id'], p['description'], *cells), tags

    def refresh(self):
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for p in POINTS:
            if self._visible(p):
                values, tags = self._row(p); self.tree.insert('', 'end', iid=str(p['id']), values=values, tags=tags)
        if keep and self.tree.exists(keep[0]): self.tree.selection_set(keep[0])
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.tree.exists(iid):
            values, tags = self._row(p); self.tree.item(iid, values=values, tags=tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.active_points())
        self.update_shell_sections([p for p in POINTS if self.active(p)], lambda p: p['section_title'])

    def on_period(self, save=True):
        procspec.apply_period(POINTS, PERIODS[self.period.get()])
        for records in (self.found, self.left):     # re-judge stored readings (As Found and As Left) against the newly selected limits
            for key, rec in records.items():
                p = POINTS[int(key) - 1]
                rec['result'] = 'PASS' if abs(rec['reading'] - p['nominal']) <= p['error'] else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def channel_text(self, p):
        """'channel 210' (and the 4-wire partner) for the module and slot chosen."""
        module, slot = self.module.get(), int(self.slot.get())
        try:
            ch = channel_for(module, slot, p['role'])
        except Exception:
            return 'not available on this module'
        if p['kind'] == 'OHM4':
            return f'channel {ch} (4-wire partner channel {pair_channel(module, ch)})'
        return f'channel {ch}'

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        self.detail.set(f'{p["description"]}\nAcceptable reading: {v[0]} to {v[1]} {u}  ({self.period.get()} limit)  |  Manual page {p["page"]}  |  {self.channel_text(p)}{extra}\n'
                        f'Setup: {self.setup_text(p)}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    def setup_text(self, p):
        """Hook-up instruction for a point's wiring group, with the channel numbers of the module in use."""
        module, slot = self.module.get(), int(self.slot.get())
        g = p['group']
        try:
            ch = channel_for(module, slot, p['role'])
        except Exception:
            return 'This module has no such channel.'
        pair = pair_channel(module, ch) if p['role'] != 'current' else None
        if g == 'ZERO_SHORT':
            return (f'Disconnect the calibrator from the module. Fit low-thermal copper shorts across HI/LO of channel {ch} and, for the 4-wire ohms points, '
                    f'of its partner channel {pair}. The calibrator stays in STANDBY.')
        if g == 'ZERO_OPEN':
            return f'Leave the current channel {ch} OPEN (nothing connected). The calibrator stays in STANDBY.'
        five60 = self.cal_key == '5560A'
        out = 'OUTPUT V/ohm HI / LO' if five60 else 'NORMAL HI / LO'
        base = 'Shielded twisted pair, shield to the calibrator LO; calibrator LO to earth ground. '
        if g in ('DCV', 'ACV', 'FREQ'):
            return base + f'Calibrator {out} to channel {ch} HI / LO.'
        if g == 'OHM4':
            return (f'4-wire: calibrator {out} (force) to channel {ch} HI / LO and calibrator SENSE HI / LO to the partner channel {pair} HI / LO. '
                    'Turn the calibrator\'s external sense (EX SNS / EXT SENSE) ON at its front panel.')
        if g == 'OHM2':
            return (f'2-wire: calibrator {out} to channel {ch} HI / LO (the median-length path). Calibrator external sense OFF; '
                    'use its 2-wire compensation if it offers it.')
        if g in ('DCI', 'ACI'):
            amps = 'VI AUX output and OUTPUT LO' if five60 else 'AUX HI and AUX LO'
            return f'Calibrator {amps} to the current channel {ch} (HI / LO). Check the calibrator range and the fuse first.'
        return p['setup']

    # ------------------------------------------------------------------ connection
    def _serial_kwargs(self):
        bits, parity = PARITY_FORMATS[self.dmm_format.get()]
        return dict(baud=int(self.dmm_baud.get()), data_bits=bits, parity=parity, stop_bits=1,
                    write_termination='\n', read_termination='\n', flow_control=FLOW[self.dmm_flow.get()])

    def find_instruments(self):
        if self.rs232:
            ports = list_com_ports()
            self.dmm_entry['values'] = ports; self.cal_entry['values'] = ports
            self.status.set(f'{len(ports)} serial port(s) found: ' + (', '.join(ports) if ports else 'none') + '. Pick the 34970A port.' if ports
                            else 'No serial ports found (pip install pyserial, or enter the port name by hand).')
            return
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type the USB address.'); return
        usb = [r for r in found if r.upper().startswith('USB')]
        self.dmm_entry['values'] = usb or found; self.cal_entry['values'] = found
        guess = next((r for r in usb if '0x2007' in r.lower() or '34972' in r), usb[0] if len(usb) == 1 else None)
        if guess: self.dmm_addr.set(guess)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '.')

    def _make_io(self):
        return IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()),
                  self.module.get(), int(self.slot.get()), serial=self._serial_kwargs() if self.rs232 else None)

    def test_connections(self):
        if self.demo: messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); self.root.update_idletasks()
        try:
            self.disconnect(); self.io = self._make_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); messagebox.showerror('Connection error', str(exc)); return
        self._set_conn(True); self._save_settings()
        self.status.set('Connected: ' + self.io.ident + '. Calibrator output is NOT enabled.')
        messagebox.showinfo('Connected', f'{MODEL}: {self.io.ident}\nModule in slot {self.slot.get()}: {self.module.get()}\n'
                            f'{self.cal_model.get()}: {self.io.cal.idn}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('dmm_addr', self.dmm_addr), ('dmm_baud', self.dmm_baud), ('dmm_format', self.dmm_format), ('dmm_flow', self.dmm_flow),
                         ('cal_model', self.cal_model), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('module', self.module),
                         ('slot', self.slot), ('period', self.period)):
            self.settings.set(key, var.get())
        self.settings.save()

    # ------------------------------------------------------------------ running
    def request_stop(self): self.stop = True; self.status.set('Stopping after current test point.')
    def run_all(self): self.execute([p for p in self.active_points() if str(p['id']) not in self.results])
    def run_section(self): self.run_shown_section()

    def rerun(self):
        selected = self.tree.selection()
        if selected: self.execute([POINTS[int(selected[0]) - 1]])
        else: messagebox.showinfo('Selection', 'Select a test point first.')

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): messagebox.showwarning('Instrument ID', 'Enter an instrument ID.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.demo and self.io is None: self.test_connections()
        if not self.demo and self.io is None: return
        self.stop = False; self.busy = True
        self._next(points, 0, None)

    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(MODEL, self.cal_key, group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Channel', self.channel_text(p)),
                 ('Manual page', p['page'])]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_{MODEL}_{self.cal_key}_{group}.png)'))
        self.io.standby()
        if p['source'] == 'none':
            return ui.confirm_steps(self.root, 'Zero offset: physical setup required', f'Setup: {GROUP_TITLE[group]}',
                [('Set up the input', self.setup_text(p))], facts=facts,
                caution='Never use the calibrator as a zero source (manual p. 81).', ok='Set up - measure', image=image)
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p))]
        if p['kind'] in ('ACV', 'ACI', 'FREQ'):
            steps.append(('Filter', 'The program selects the 3 Hz AC filter; each AC reading takes about 7 s.'))
        return ui.confirm_steps(self.root, 'Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        key = p['group']
        if not self.demo and key != previous and not self._prompt_setup(p):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        if not self.demo and p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= 100:
            if not messagebox.askyesno('HIGH VOLTAGE', f'This point outputs {p["nominal"]:g} V. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?'):
                self.busy = False; return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        if self.tree.exists(str(p['id'])): self.tree.selection_set(str(p['id'])); self.tree.see(str(p['id']))
        if self.demo:
            reading = p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38   # deterministic, labelled synthetic
            self._record(p, reading, True); self.root.after(30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    self.root.after(0, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    self.root.after(0, lambda: self._error(exc))
            threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, key):
        self._record(p, reading, False); self.root.after(30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); messagebox.showerror('Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic):
        result = 'PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()],
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label)
        self._update_row(p); self.save(silent=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, period=self.period.get(),
                                        module=self.module.get(), slot=self.slot.get(), **self.save_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not messagebox.askyesno('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.module.set(data.get('module', self.module.get())); self.slot.set(data.get('slot', self.slot.get()))
        self.period.set(data.get('period', self.period.get())); self.load_results(data)
        # optional points that were run come back visible
        ran = set(self.found) | set(self.left)
        self.include_ohm2.set(any(POINTS[int(k) - 1].get('opt') == 'ohm2' for k in ran))
        self.include_ac.set(any(POINTS[int(k) - 1].get('opt') == 'ac' for k in ran))
        self.on_period(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    @staticmethod
    def report_section(p):
        return p['section_title']

    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        return self.certificate_rows_and_points()[0]

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from (for the optional TAR / TUR fields)."""
        import report_pdf
        rows, pts = [], []
        for p in POINTS:
            row = self.found_left_row(p, lambda r: report_pdf.point_row(p, r['reading'], r['result'] == 'FAIL', section=self.report_section(p), standard=self.cal_key))
            if row: rows.append(row); pts.append(p)
        return rows, pts

    def export_pdf(self):
        rows, pts = self.certificate_rows_and_points()
        if not rows: messagebox.showinfo('No results', 'No recorded results to export yet.'); return
        try: import report_pdf, report_dialog
        except ImportError as exc: messagebox.showerror('Report export', str(exc)); return
        details = report_dialog.ask_details(self.root, f'Keysight {MODEL} performance verification')
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'), [tartur_wiring.point_fields(p, self.cal_key) for p in pts])
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'Keysight {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Limits applied', self.period.get()),
                                                                 ('Source', f'Keysight 34970A/34972A Service Guide, pp. 80-87 (Internal DMM Verification)')],
                                             demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, self.cal_key))
        except ImportError:
            messagebox.showerror('PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            messagebox.showerror('PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); self.root.destroy()


def main(model, argv=None):
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    App(root, model, demo='--demo' in argv)
    root.mainloop()
