"""Keysight 34970A / 34972A internal-DMM performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_<model>_pv.json (built by
specs/build_dacq_spec.py from the 34970A/34972A Service Guide, Chapter 4, pp. 80-87). Default limits: 1 year.

Bench: the 34970A (RS-232, selectable COM port) or the 34972A (USB), a 34901A multiplexer (or 34902A, no current tests),
and a Fluke 5560A or 5522A calibrator (or a 5520A, when its published specification covers every point) as the source. The program configures the DMM for every point (function, range,
10 PLC / 3 Hz AC filter / frequency gate), selects the channel, drives the calibrator and reads the result. It pauses
for a hook-up diagram whenever the wiring changes and never runs unattended. Hardware I/O is OFF in demo mode.

    import dacq_verification
    dacq_verification.main('34970A')       # what Procedures/Keysight_34970A_Verification.py does
"""
import json, math, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, report_filename, Settings); the window code is in dacq_view_qt.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import appdata
import datamode
import calibrator_fit
import procmods_engine
import reset_startup
import surprise
import virtualbench
import procspec
import drivers
from drivers.keysight_dacq import channel_for, pair_channel

MODEL = SPEC_PATH = SPEC = POINTS = None
PERIODS = {'24 hours': '24h', '90 days': '90d', '1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
CALIBRATORS = {'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5522A': ('5522A', drivers.Fluke5522A), 'Fluke 5520A': ('5520A', drivers.Fluke5520A)}
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
    cal = '5522A' if cal == '5520A' else cal           # the 5520A uses the 5522A picture (same NORMAL / AUX terminals; UNVERIFIED)
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


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the 34970A / 34972A and the calibrator, both through the instrument drivers."""
    SETTLE_AC = {10: 6.0, 20: 5.0}

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5560A', cal_baud=9600, module='34901A', slot=2,
                 serial=None, transports=None, mods=None, virtual=False, surprise_handler=None):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
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
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.dmm.idn
        self.guards = []
        if surprise_handler is not None:
            self.enable_surprise(surprise_handler)

    def enable_surprise(self, handler, force=False):
        """Stop on surprise (surprise.py, opt-in; wired here at the engine level, no driver edited).  handler(Surprise) -> True = Continue; it must have
        been made on the Tk thread (surprise.tk_handler).  A reply that is empty / a prompt character / not a number for READ?, or a query that times
        out twice, is a Stop-only surprise; the 34970A / 34972A error queue after CONF / NPLC / BAND / the channel scan, and after the reading, is a
        Stop / Continue surprise; the calibrator's error queue after an output is a Stop-only surprise (the output is never operated after a refusal).
        No write is ever repeated.  A virtual (demo) command log is left alone unless force=True (tests), so the simulated bench never prompts."""
        self.guards = [g for g in (surprise.attach_guard(self.dmm, handler, force, expect={'read': 'float'}, stop_only=True),
                                   surprise.attach_guard(self.cal, handler, force, stop_only=True)) if g]
        return self.guards

    def reset_roles(self):
        return [self.cal], [self.dmm]

    def pm_drivers(self):
        return (self.dmm, self.cal)

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
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt (a virtual demo session writes nothing)."""
        if virtualbench.log_is_virtual(self.log): return
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def channel(self, p):
        return channel_for(self.module, self.slot, p['role'])

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        if p['kind'] == 'FREQ': return self.pm_param('dacq.settle.freq', 3.0)
        if p['kind'] == 'ACV':
            f = p.get('frequency')
            return self.pm_param(f'dacq.settle.ac_{int(f)}hz', self.SETTLE_AC[f]) if f in self.SETTLE_AC else self.pm_param('dacq.settle.ac_other', 4.0)
        if p['kind'] == 'ACI': return self.pm_param('dacq.settle.aci', 4.0)
        if p['kind'] in ('OHM2', 'OHM4') and p['range'] >= 1e7: return self.pm_param('dacq.settle.ohm_high', 4.0)
        if p['kind'] in ('DCI', 'OHM2'): return self.pm_param('dacq.settle.dci_ohm2', 3.0)
        return self.pm_param('dacq.settle.default', 2.0)

    @procmods_engine.point_commands()
    def measure(self, p):
        self.standby()
        ch = self.channel(p)
        self.dmm.configure_point(p, ch)
        surprise.checked(self.dmm, self.dmm.check_errors, 'configuring ' + p['description'])       # no guard: exactly dmm.check_errors(...)
        if p['source'] == 'none':          # copper short / open input: the calibrator stays in STANDBY
            time.sleep(virtualbench.scaled(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('dacq.settle.zero', 1.5), self.virtual))
            reading = self.dmm.read()
            surprise.checked(self.dmm, self.dmm.check_errors, 'reading ' + p['description'])
            return reading
        k, v, f = p['kind'], p['nominal'], p.get('frequency')
        if k in ('DCV', 'ACV'): self.cal.set_output_volts(v, f, dc=k == 'DCV')
        elif k in ('DCI', 'ACI'): self.cal.set_output_amps(v, f, dc=k == 'DCI')
        elif k in ('OHM2', 'OHM4'): self.cal.set_output_ohms(v)
        elif k == 'FREQ': self.cal.set_output_volts(p['amplitude'], v)
        surprise.checked(self.cal, self.cal.check_error, p['description'], stop_only=True)   # the calibrator refuses outputs it cannot make; never operate then (so no Continue)
        self.cal.operate_unverified()
        time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
        reading = self.dmm.read()
        self.standby()
        surprise.checked(self.dmm, self.dmm.check_errors, 'reading ' + p['description'])
        return reading


class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root, model, demo=False, fast_demo=False):
        configure(model)
        self.init_virtual(demo, fast_demo)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('dacq', MODEL, demo=demo, lists=[POINTS])         # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(MODEL)
        s = self.settings
        self.asset = port.var(); self.serial = port.var()
        self.rs232 = SPEC.get('interface') == 'rs232'
        ports = list_com_ports() if self.rs232 else []
        self.dmm_addr = port.var(s.get('dmm_addr', (ports[0] if ports else 'COM1') if self.rs232 else 'USB0::0x0957::0x2007::MY00000000::INSTR'))
        self.dmm_baud = port.var(s.get('dmm_baud', '57600'))
        self.dmm_format = port.var(s.get('dmm_format', '8 data bits, no parity'))
        self.dmm_flow = port.var(s.get('dmm_flow', 'XON/XOFF (instrument default)'))
        self.cal_offer = calibrator_fit.make_offer('5520A', calibrator_fit.dmm_requests(POINTS), unverified=drivers.Fluke5520A.unverified_summary())
        self.cal_model = port.var(s.get('cal_model', 'Fluke 5560A') if s.get('cal_model', 'Fluke 5560A') in self.cal_choices() else 'Fluke 5560A')
        self.cal_addr = port.var(s.get('cal_addr', 'COM9'))
        self.cal_baud = port.var(s.get('cal_baud', '9600'))
        self.module = port.var(s.get('module', '34901A'))
        self.slot = port.var(s.get('slot', '2'))
        self.period = port.var(s.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.include_ohm2 = port.var(False, 'bool')
        self.include_ac = port.var(False, 'bool')
        self.status = port.var()
        self.detail = port.var('Select a test point to see its limits, channel and setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set(virtualbench.status_text(self) if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose the connections and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    @property
    def cal_key(self): return CALIBRATORS[self.cal_model.get()][0]

    def cal_choices(self):
        """The calibrator picker's values: the 5520A only when its published specification covers every point of the procedure (calibrator_fit)."""
        return calibrator_fit.picker_values(list(CALIBRATORS), {'Fluke 5520A': self.cal_offer})

    def active(self, p):
        if p.get('skip'): return False                               # a point skipped by a procedure modification
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

    VIEW = 'dacq_view'                               # window code: dacq_view_qt.py
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    # ------------------------------------------------------------------ layout
    def _build_ui(self): self.ui_view.build_ui(self)

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

    def pm_driver_classes(self): return (getattr(drivers, f'Keysight{MODEL}'), *[cls for _n, cls in CALIBRATORS.values()])

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated import make_dacq_bench
        cal_model = self.cal_model.get() if self.cal_model.get() in CALIBRATORS else 'Fluke 5560A'
        module, slot = self.module.get(), int(self.slot.get())

        def build(mods):
            _bench, ft, dt = make_dacq_bench(MODEL, CALIBRATORS[cal_model][0], {slot: module})
            return IO('sim', 'sim', cal_model, 9600, module, slot, transports=(dt, ft), mods=mods)
        return procmods_plan.run_plan(self.pm_state, build, lambda io: io.measure(p))

    def refresh(self):
        keep = self.ui_view.table_selection(self)
        self.ui_view.table_set_rows(self, ((str(p['id']), *self._row(p)) for p in POINTS if self._visible(p)), keep)
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.ui_view.table_has(self, iid):
            values, tags = self._row(p); self.ui_view.table_update_row(self, iid, values, tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.active_points())
        self.update_shell_sections([p for p in POINTS if self.active(p)], lambda p: p['section_title'])

    def on_period(self, save=True):
        self.pm_revert(POINTS)                                       # limits come from the period table: take the modifications off,
        procspec.apply_period(POINTS, PERIODS[self.period.get()])
        self.pm_apply(POINTS)                                        # then put them back (they only apply if they fit this period)
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
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        self.detail.set(f'{p["description"]}\nManual page {p["page"]}  |  {self.channel_text(p)}{extra}\n'
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
            self.ui_view.set_choices(self, 'dmm', ports); self.ui_view.set_choices(self, 'cal', ports)
            self.status.set(f'{len(ports)} serial port(s) found: ' + (', '.join(ports) if ports else 'none') + '. Pick the 34970A port.' if ports
                            else 'No serial ports found (pip install pyserial, or enter the port name by hand).')
            return
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type the USB address.'); return
        usb = [r for r in found if r.upper().startswith('USB')]
        self.ui_view.set_choices(self, 'dmm', usb or found); self.ui_view.set_choices(self, 'cal', found)
        guess = next((r for r in usb if '0x2007' in r.lower() or '34972' in r), usb[0] if len(usb) == 1 else None)
        if guess: self.dmm_addr.set(guess)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '.')

    def _make_io(self):
        if self.virtual:          # demo: the real IO / driver code over a simulated 34970A / 34972A and calibrator
            module, slot = self.module.get(), int(self.slot.get())
            self._vb = virtualbench.dacq_pair(MODEL, CALIBRATORS[self.cal_model.get()][0], {slot: module})
            return IO('virtual', 'virtual', self.cal_model.get(), 9600, module, slot, transports=(self._vb[2], self._vb[1]), mods=self.pm_state, virtual=True)
        return IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()),
                  self.module.get(), int(self.slot.get()), serial=self._serial_kwargs() if self.rs232 else None, mods=self.pm_state,
                  surprise_handler=self._surprise_handler())

    def _surprise_handler(self):
        """The Stop / Continue dialog for stop-on-surprise, made ON the Tk thread (here: the Test connections / Run handler), once per window.
        None in demo (virtual or fast): the simulated bench never prompts."""
        if self.demo or self.fast_demo: return None
        if getattr(self, '_sp_handler', None) is None: self._sp_handler = port.surprise_handler(self.root)
        return self._sp_handler

    def test_connections(self):
        if self.fast_demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect(); self.io = self._make_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_settings()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator output is NOT enabled.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'{MODEL}: {self.io.ident}\nModule in slot {self.slot.get()}: {self.module.get()}\n'
                            f'{self.cal_model.get()}: {self.io.cal.idn}{tag}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
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
        selected = self.ui_view.table_selection(self)
        if selected: self.execute([POINTS[int(selected[0]) - 1]])
        else: port.message('info', 'Selection', 'Select a test point first.')

    def rerun_from(self):
        selected = self.ui_view.table_selection(self)
        if selected: self.execute(self.points_from(POINTS, selected[0]))
        else: port.message('info', 'Selection', 'Select a test point first.')

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.fast_demo and self.io is None: self.test_connections()
        if not self.fast_demo and self.io is None: return
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

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
            return port.operator_prompt('Zero offset: physical setup required', f'Setup: {GROUP_TITLE[group]}',
                [('Set up the input', self.setup_text(p))], facts=facts,
                caution='Never use the calibrator as a zero source (manual p. 81).', ok='Set up - measure', image=image, parent=self.root)
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p))]
        if p['kind'] in ('ACV', 'ACI', 'FREQ'):
            steps.append(('Filter', 'The program selects the 3 Hz AC filter; each AC reading takes about 7 s.'))
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image, parent=self.root)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root, 30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        key = p['group']
        if not self.fast_demo and key != previous and not self._prompt_setup(p):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        if not self.fast_demo and p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= 100:
            if not port.ask_yes_no('HIGH VOLTAGE', f'This point outputs {p["nominal"]:g} V. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?'):
                self.busy = False; return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.fast_demo:
            reading = p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38   # deterministic, labelled synthetic
            self._record(p, reading, True); port.after(self.root, 30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    port.post(self.root, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, key):
        self._record(p, reading, bool(self.demo)); port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic):
        result = 'PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()],
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields())
        self._update_row(p); self.save(silent=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, period=self.period.get(),
                                        module=self.module.get(), slot=self.slot.get(), **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.module.set(data.get('module', self.module.get())); self.slot.set(data.get('slot', self.slot.get()))
        self.period.set(data.get('period', self.period.get())); self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
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
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details(f'Keysight {MODEL} performance verification', parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'), [tartur_wiring.point_fields(p, self.cal_key) for p in pts])
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'Keysight {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Limits applied', self.period.get()),
                                                                 ('Source', f'Keysight 34970A/34972A Service Guide, pp. 80-87 (Internal DMM Verification)')],
                                             demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, self.cal_key),
                                             snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); port.close(self.root)


def main(model, argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, model, demo=demo, fast_demo=fast)
    port.run_app(build)
