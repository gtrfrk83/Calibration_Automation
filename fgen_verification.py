"""Keysight / Agilent 33210A, 33220A and 33250A function generator performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_<model>_pv.json, written by
specs/build_fgen_spec.py from Chapter 4 (Calibration Procedures) of each model's Service Guide. Default limits: 1 year.

Instruments
  Generator under test     USB / GPIB / LAN (RS-232 on the 33250A)            drivers/keysight_332xx.py
  Fluke 5790B              AC amplitude and low-frequency flatness (the manual uses a 3458A DMM here)   drivers/fluke_5790b.py
  Frequency counter        internal timebase (53131A Opt 010 in the manual)   drivers.ReferenceMeter; leave blank to type readings
  Power meter + sensor     0 / +10 / +20 dB range flatness (E4418B + 8482A, -20 dB attenuator for +20 dB)   drivers.ReferenceMeter;
                           leave blank to type readings
Flatness follows the manual's worksheet: offset_N = 10 log(5 V100k^2) - 10 log(5 V1k^2) from the 5790B readings, and each
point is (P(f) - P(100 kHz)) + offset_N, which is what the power meter shows in Relative Power mode with that offset entered.
The generator output is switched OFF after every point and before every wiring change; each switch is confirmed with OUTP?.
Hardware I/O is off in demo mode, and demo results are labelled as demo data everywhere.

    import fgen_verification
    fgen_verification.main('33220A')       # what Procedures/Keysight_33220A_Verification.py does
"""
import csv, json, math, sys, threading, time, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, simpledialog

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, report and drivers sit next to the Manager
import ui_theme as ui
import drivers

MODEL = SPEC_PATH = SPEC = POINTS = None
PERIODS = {'90 days': '90d', '1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
KINDS = ('SELFTEST', 'TIMEBASE', 'ACAMP', 'LFFLAT', 'FLAT')
REF_CMC_PATH = HERE / 'specs' / 'fgen_332xx_reference_cmc.json'
STD_INPUTS = {'INPUT 1 (type N)': 'INPUT1', 'INPUT 2 (binding posts)': 'INPUT2'}
FLAT_REF_HZ = 100e3
SETTLE = {'TIMEBASE': 2.0, 'ACAMP': 1.0, 'LFFLAT': 1.0, 'FLAT': 1.5}


class SpecError(ValueError):
    pass


class NeedReference(RuntimeError):
    """A flatness point was asked for before the AC amplitude / low-frequency references it needs were recorded."""


# ================================================================================================================
# spec
# ================================================================================================================
def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('schema') != 4:
        raise SpecError(f'{Path(path).name}: expected a schema 4 (function generator) spec')
    periods = spec['periods']
    if spec['default_period'] not in periods:
        raise SpecError('default_period is not one of periods')
    for s in spec['sections']:
        for i, p in enumerate(s['points'], 1):
            where = f"{s['id']} point {i}"
            if p['kind'] not in KINDS:
                raise SpecError(f'{where}: unknown kind {p["kind"]!r}')
            if set(p['limits']) != set(periods) or any(not v > 0 for v in p['limits'].values()):
                raise SpecError(f'{where}: limits must be positive for every period {periods}')
            if p['kind'] != 'SELFTEST' and not (p.get('frequency') and p.get('amp_unit') and p.get('load')):
                raise SpecError(f'{where}: needs frequency, amp_unit and load')
    return spec


def flatten(spec):
    points = []
    for s in spec['sections']:
        for raw in s['points']:
            p = dict(raw)
            p['id'] = len(points) + 1
            p['section'] = s['id']; p['section_title'] = s['title']; p['page'] = s['page']
            p['group'] = s['group']; p['setup'] = s['setup']
            p.setdefault('quick', False)
            p['desc'] = describe(p)
            points.append(p)
    return points


def _si(value, unit):
    n, sym = ui.si_one(value, unit)
    return f'{n} {sym}'


def describe(p):
    """Display text only; the point keeps base units."""
    k = p['kind']
    if k == 'SELFTEST':
        return 'Complete self-test (*TST?)'
    func = 'Sine' if p['function'] == 'SIN' else 'Square'
    load = 'High Z' if p['load'] == 'INF' else '50 ohm'
    if p['amp_unit'] == 'DBM':
        amp = f"{p['amplitude']:+.2f} dBm"
    elif p['amp_unit'] == 'VPP':
        amp = f"{p['amplitude']:.2f} Vpp"
    else:
        amp = _si(p['amplitude'], 'V') + 'rms'
    text = f"{func} {amp} @ {_si(p['frequency'], 'Hz')}, {load}"
    if k == 'FLAT':
        text += f", {p['range_db']:+d} dB range".replace('+0 dB', '0 dB')
    return text


def configure(model):
    global MODEL, SPEC_PATH, SPEC, POINTS
    MODEL = model
    SPEC_PATH = HERE / 'specs' / f'keysight_{model.lower()}_pv.json'
    SPEC = load_spec(SPEC_PATH)
    POINTS = flatten(SPEC)
    apply_period(POINTS, SPEC['default_period'])


def apply_period(points, period):
    for p in points:
        p['error'] = float(f"{p['limits'][period]:.9g}")


def judge(p, reading):
    if p['kind'] == 'SELFTEST':
        return 'PASS' if reading == 0 else 'FAIL'
    return 'PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL'


def flat_offset(results, range_db):
    """Worksheet step 5 (100kHz_NdB_offset) in dB from the recorded 5790B readings, or raise NeedReference."""
    hi, lo = f'100k_{range_db}dB', f'1k_{range_db}dB'
    found = {}
    for p in POINTS:
        if p.get('ref') in (hi, lo):
            rec = results.get(str(p['id']))
            if rec is not None and rec.get('reading') is not None:
                found[p['ref']] = rec['reading']
    if hi not in found or lo not in found:
        names = [f'{q["section_title"]} {q["desc"]}' for q in POINTS if q.get('ref') in (hi, lo)]
        raise NeedReference(f'The {range_db} dB range offset needs these points first: ' + '; '.join(names))
    v100, v1 = found[hi], found[lo]
    return 10 * math.log10(5.0 * v100 ** 2) - 10 * math.log10(5.0 * v1 ** 2)


def to_visa(text):
    """'COM9' / '9' -> 'ASRL9::INSTR'; anything that already looks like a VISA resource passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port (COM9) or a full VISA address (USB0::...::INSTR, GPIB0::10::INSTR).')
    return f'ASRL{int(t)}::INSTR'


# ================================================================================================================
# bench I/O (no tkinter: the simulated-bench tests drive this class directly)
# ================================================================================================================
class IO:
    """The generator under test, the 5790B, and (optionally) a counter and a power meter. A reference left without an
    address is read by the technician: ask_number(prompt, unit) is called and must return a float (or None to stop)."""

    def __init__(self, addrs, transports=None, ask_number=None, std_input='INPUT1'):
        self.log = drivers.CommandLog()
        self.ask_number = ask_number
        self.std_input = std_input
        self.uut = self.std = self.counter = self.power = None
        t = transports or {}

        def tr(key, **kw):
            return t[key] if key in t else drivers.open_visa(to_visa(addrs[key]), timeout=30, **kw)

        try:
            self.uut = getattr(drivers, f'Keysight{MODEL}')(tr('uut', **self._serial(addrs, 'uut')), self.log, label=MODEL)
            self.uut.connect()
            self.std = drivers.Fluke5790B(tr('std', **self._serial(addrs, 'std')), self.log, label='5790B')
            self.std.connect()
            for key, label in (('counter', 'Counter'), ('power', 'PowerMeter')):
                if key in t or (addrs.get(key) or '').strip():
                    inst = drivers.ReferenceMeter(tr(key), self.log, label=label); inst.connect(); setattr(self, key, inst)
        except Exception:
            self.close(); raise
        self.ident = self.uut.idn

    @staticmethod
    def _serial(addrs, key):
        """Serial settings only for ASRL (RS-232) addresses; the 5790B needs XON/XOFF and CR LF."""
        a = (addrs.get(key) or '').strip().upper()
        if not (a.startswith(('ASRL', 'COM')) or a.isdigit()):
            return {}
        if key == 'std':
            s = drivers.FLUKE_5790B_SERIAL
            return dict(baud=int(addrs.get('std_baud') or s.baud), data_bits=s.data_bits, parity=s.parity, stop_bits=s.stop_bits,
                        write_termination=s.write_termination, read_termination=s.read_termination, flow_control=s.flow_control)
        # 33250A RS-232 (User's Guide ch. 2): factory 57600 baud, 8 data bits, no parity; set its handshake to None (the factory DTR/DSR
        # is not offered by the transport). Line endings are not verified on hardware - prefer GPIB.
        return dict(baud=int(addrs.get('uut_baud') or 57600), write_termination='\n', read_termination='\n')

    # ---- safety ----------------------------------------------------------------------------------------------
    def all_off(self):
        """Generator output OFF (confirmed). Called after every point and before every wiring prompt."""
        if self.uut:
            self.uut.output(False)

    def close(self):
        for obj in (self.uut, self.std, self.counter, self.power):
            if obj is None:
                continue
            try: obj.cleanup()
            except Exception: pass
            try: obj.close()
            except Exception: pass
        self.save_log()

    def save_log(self):
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    # ---- readings --------------------------------------------------------------------------------------------
    def _manual(self, prompt, unit):
        if self.ask_number is None:
            raise drivers.InstrumentError(f'No address for this reference and no way to type a reading: {prompt}')
        v = self.ask_number(prompt, unit)
        if v is None:
            raise drivers.InstrumentError('Reading not entered; run stopped.')
        return float(v)

    def _frequency(self):
        if self.counter:
            f = self.counter.frequency()
            if not 1e6 < f < 1e8:
                raise drivers.InstrumentError(f'Counter reads {f:g} Hz: check the cable and the counter input (50 ohm, channel 1).')
            return f
        return self._manual('Read the frequency counter (generator: 10 MHz sine, 1 Vpp).', 'Hz')

    def _power(self, what):
        if self.power:
            try:
                return self.power.power()
            except drivers.InstrumentError as exc:
                raise drivers.InstrumentError(f'{exc} - check the sensor, attenuator and cable, and that the power meter is zeroed.') from exc
        return self._manual(f'Read the power meter in dBm ({what}). Relative mode and offset OFF: type the absolute reading.', 'dBm')

    def _out(self, p, frequency=None):
        self.uut.setup(p['function'], frequency or p['frequency'], p['amplitude'], p['amp_unit'], p['load'])
        self.uut.output(True)
        time.sleep(SETTLE.get(p['kind'], 1.0))

    # ---- one point -----------------------------------------------------------------------------------------
    def measure(self, p, results, pref_cache):
        """Returns (reading, raw dict). The generator output is OFF when this returns or raises."""
        try:
            return self._measure(p, results, pref_cache)
        finally:
            self.all_off()

    def _measure(self, p, results, pref_cache):
        k = p['kind']
        if k == 'SELFTEST':
            passed, detail = self.uut.self_test()
            return (0 if passed else 1), dict(detail=detail)
        if k == 'TIMEBASE':
            self._out(p)
            return self._frequency(), {}
        if k in ('ACAMP', 'LFFLAT'):
            self.std.select_input(self.std_input)
            self.std.set_external_trigger(True)
            self.std.set_range_for(p['nominal'])
            self._out(p)
            volts, freq = self.std.measure()
            if not math.isclose(freq, p['frequency'], rel_tol=0.01):
                raise drivers.InstrumentError(f'5790B measured {freq:g} Hz, expected {p["frequency"]:g} Hz: check the cable to the 5790B.')
            return volts, dict(freq_hz=freq)
        if k == 'FLAT':
            offset = flat_offset(results, p['range_db'])
            key = p['section']
            if key not in pref_cache:
                self._out(p, FLAT_REF_HZ)
                pref = self._power(f'{p["section_title"]} reference, 100 kHz')
                self.uut.output(False)
                expected = p['amplitude'] - (20.0 if p['range_db'] == 20 else 0.0)
                if p['range_db'] == 20 and pref > 10.0:
                    raise drivers.SafetyError(f'The power meter reads {pref:+.2f} dBm at +23.9 dBm output: the -20 dB attenuator is '
                                              'not fitted. Output switched OFF. Fit the attenuator before continuing.')
                if abs(pref - expected) > 3.0:
                    raise drivers.InstrumentError(f'Power meter reads {pref:+.2f} dBm, expected about {expected:+.1f} dBm: check the sensor, '
                                                  'attenuator and cable, and that the power meter is zeroed.')
                pref_cache[key] = pref
            pref = pref_cache[key]
            self._out(p)
            pf = self._power(f'{p["desc"]}')
            return (pf - pref) + offset, dict(p_ref_dbm=pref, p_dbm=pf, offset_db=offset)
        raise drivers.InstrumentError(f'No executor for {k}')


def demo_reading(p):
    """Deterministic synthetic reading, labelled as demo data everywhere it appears."""
    if p['kind'] == 'SELFTEST':
        return 0, {}
    return p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38, {}


# ================================================================================================================
# uncertainty and report rows
# ================================================================================================================
def _ref_cmc():
    try:
        return json.loads(REF_CMC_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def point_uncertainty(p):
    """(text, source) - the editable reference file first, then the laboratory scope (Measure entries), else ''."""
    import uncertainty
    entry = _ref_cmc().get(p['kind']) or {}
    if entry.get('rel') is not None or entry.get('abs') is not None:
        value = (entry.get('rel') or 0) * abs(p['nominal'] if p['kind'] != 'FLAT' else 1.0) + (entry.get('abs') or 0)
        return uncertainty.format_value(value, entry.get('unit', p['unit'])), 'reference file'
    if p['kind'] in ('ACAMP', 'LFFLAT', 'TIMEBASE'):
        import report_pdf
        sc = report_pdf.scope()
        if sc is not None:
            kind = 'FREQ' if p['kind'] == 'TIMEBASE' else 'ACV'
            value = sc.dmm(kind, p['nominal'], None, None if kind == 'FREQ' else p['frequency'], basis='measure')
            if value is not None:
                return uncertainty.format_value(value, 'Hz' if kind == 'FREQ' else 'V'), 'scope'
    return '', ''


def display_ref(p):
    """SI-prefix reference for display: dB is never prefixed (no 'mdB'); volts and hertz scale with the nominal."""
    return 1.0 if p['unit'] == 'dB' else (p['nominal'] or p['error'])


def _db_row(p, r, failed, sec, unc):
    lo, hi = p['nominal'] - p['error'], p['nominal'] + p['error']
    dp = max(len(f'{p["error"]:g}'.split('.')[1]) if '.' in f'{p["error"]:g}' else 0, 2)
    return {'Section': sec, 'Description': p['desc'], 'Nominal': f'{p["nominal"]:.{dp}f} dB', 'Tolerance -': f'{lo:.{dp}f}',
            'Tolerance +': f'{hi:.{dp}f}', 'UOM': 'dB', 'As Found': f'{r["reading"]:.{dp + 2}f}', 'OOT': 'OOT' if failed else '',
            'As Left': 'Same', 'Uncertainty': unc}


def certificate_rows(results):
    import report_pdf
    rows = []
    for p in POINTS:
        r = results.get(str(p['id']))
        if not r:
            continue
        failed = r['result'] == 'FAIL'
        sec = p['section_title']
        if p['kind'] == 'SELFTEST':
            rows.append({'Section': sec, 'Description': p['desc'], 'Nominal': 'Pass', 'Tolerance -': 'N/A', 'Tolerance +': 'N/A', 'UOM': '',
                         'As Found': 'Pass' if r['reading'] == 0 else 'Fail', 'OOT': 'OOT' if failed else '', 'As Left': 'Same', 'Uncertainty': ''})
            continue
        unc, _src = point_uncertainty(p)
        if p['unit'] == 'dB':
            rows.append(_db_row(p, r, failed, sec, unc))
            continue
        desc = p['desc'] + (' (typical)' if p.get('typical') else '')
        rows.append(report_pdf.cert_row(desc, p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error'], p['unit'],
                                        r['reading'], failed, section=sec, uncertainty=unc))
    return rows


# ================================================================================================================
# application
# ================================================================================================================
class App:
    WIRING = {
        'NONE': ('Self-test', [('Disconnect', 'Remove any cable from the generator OUTPUT. No connections are needed for the self-test.')]),
        'COUNTER': ('Connect the frequency counter', [('Connect', 'Generator OUTPUT to the frequency counter input with a 50 ohm BNC cable.'),
                                                      ('Counter', 'Counter input terminated at 50 ohm (manual step 1). Use an external reference '
                                                                  'on the counter if it has one.')]),
        'STD': ('Connect the Fluke 5790B', [('Connect', 'Generator OUTPUT to the 5790B {input} with a short RG-58 BNC cable '
                                                        '(type N input: N(m) to BNC(f) adapter; binding posts: BNC to dual banana).'),
                                            ('5790B', 'No other cables on the 5790B inputs. Guard and ground as your lab practice.')]),
        'POWER': ('Connect the power sensor', [('Power meter', 'Zero and calibrate the power meter with the sensor, then connect the sensor.'),
                                               ('Connect', 'Generator OUTPUT to the power sensor (N(m) to BNC(f) adapter), no attenuator.')]),
        'POWER_ATT': ('Fit the -20 dB attenuator', [('Attenuator', 'Fit the -20 dB attenuator (8491A Opt 020 or equivalent) between the generator '
                                                                   'OUTPUT and the power sensor.'),
                                                    ('Why', 'The +20 dB range points output +23.9 dBm (about 245 mW), above the 8482A sensor maximum.')]),
    }

    def __init__(self, root, model, demo=False):
        configure(model)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}; self.pref_cache = {}; self.conditions_ok = False
        ui.apply_theme(root)
        root.title(f'{SPEC["manufacturer"]} {MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1320, 840, min_w=1080, min_h=640)
        self.settings = ui.Settings(f'fgen_{MODEL}')
        g = self.settings.get
        self.asset = tk.StringVar(); self.serial = tk.StringVar()
        self.addr = {k: tk.StringVar(value=g(k, d)) for k, d in (('uut', 'USB0::0x0957::0x0407::MY00000000::INSTR'), ('std', 'GPIB0::8::INSTR'),
                                                                   ('counter', ''), ('power', ''), ('std_baud', '9600'), ('uut_baud', '57600'))}
        self.std_input = tk.StringVar(value=g('std_input', 'INPUT 1 (type N)'))
        self.period = tk.StringVar(value=g('period', PERIOD_LABEL[SPEC['default_period']]))
        self.test_set = tk.StringVar(value='Full verification')
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        self.show_section = tk.StringVar(value='All sections')
        self.show_status = tk.StringVar(value='All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo else
                        'Step 1: enter the Instrument ID. Step 2: enter the addresses and press Test Connections. Step 3: Run All.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)

    # ------------------------------------------------------------------ selection
    def active(self, p):
        return not (self.test_set.get().startswith('Quick') and not p['quick'])

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy

    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'):
            idle = 'disabled' if value else 'normal'
            for b in (self.btn_run, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find):
                b.configure(state=idle)
            self.btn_stop.configure(state='normal' if value else 'disabled')
            for c in (self.period_combo, self.set_combo):
                c.configure(state='disabled' if value else 'readonly')

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        src = SPEC['source']
        banner = ui.Banner(root, f'{SPEC["manufacturer"]} {MODEL}  -  Performance Verification',
                           f'Test points from the {MODEL} Service Guide, {src["chapter"]}, pp. {src["pages"]}  |  {len(POINTS)} points in the spec')
        banner.pack(fill='x')
        banner.add_pill('DEMO MODE  -  simulated readings' if self.demo else 'HARDWARE MODE', 'warn' if self.demo else 'info')
        self.conn_pill = banner.add_pill('Not connected', 'neutral')
        ui.StatusBar(root, self.status, right='spec v4').pack(side='bottom', fill='x')
        body = ttk.Frame(root, padding=(18, 14, 18, 10)); body.pack(fill='both', expand=True)

        top = ttk.Frame(body); top.pack(fill='x'); top.columnconfigure(1, weight=1)
        dut = ttk.LabelFrame(top, text='Instrument under test', padding=12)
        dut.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        ttk.Label(dut, text='Instrument ID *').grid(row=0, column=0, sticky='w', pady=3)
        e = ttk.Entry(dut, textvariable=self.asset, width=22); e.grid(row=0, column=1, padx=(10, 0), pady=3); e.focus_set()
        ttk.Label(dut, text='Serial number').grid(row=1, column=0, sticky='w', pady=3)
        ttk.Entry(dut, textvariable=self.serial, width=22).grid(row=1, column=1, padx=(10, 0), pady=3)
        ttk.Label(dut, text='Limits to apply').grid(row=2, column=0, sticky='w', pady=3)
        self.period_combo = ttk.Combobox(dut, textvariable=self.period, values=list(PERIODS), width=19, state='readonly')
        self.period_combo.grid(row=2, column=1, padx=(10, 0), pady=3)
        self.period_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_period())

        conn = ttk.LabelFrame(top, text='Instrument connections  (USB, GPIB, LAN or RS-232)', padding=12)
        conn.grid(row=0, column=1, sticky='nsew'); conn.columnconfigure(1, weight=1)
        self.entries = {}
        rows = (('uut', f'{MODEL} (under test)'), ('std', 'Fluke 5790B'), ('counter', 'Frequency counter'), ('power', 'Power meter'))
        for r, (key, label) in enumerate(rows):
            ttk.Label(conn, text=label).grid(row=r, column=0, sticky='w', pady=3)
            cb = ttk.Combobox(conn, textvariable=self.addr[key], state='normal'); cb.grid(row=r, column=1, sticky='ew', padx=(8, 12), pady=3)
            self.entries[key] = cb
        self.btn_find = ttk.Button(conn, text='Find instruments', command=self.find_instruments); self.btn_find.grid(row=0, column=2, padx=(0, 8))
        self.btn_test = ttk.Button(conn, text='Test connections', command=self.test_connections); self.btn_test.grid(row=0, column=3)
        row = ttk.Frame(conn); row.grid(row=1, column=2, columnspan=2, sticky='w')
        ttk.Label(row, text='Input', style='Muted.TLabel').pack(side='left')
        ttk.Combobox(row, textvariable=self.std_input, values=list(STD_INPUTS), width=20, state='readonly').pack(side='left', padx=(5, 8))
        ttk.Label(row, text='Baud', style='Muted.TLabel').pack(side='left')
        ttk.Combobox(row, textvariable=self.addr['std_baud'], values=['9600', '19200', '38400', '57600', '115200'], width=7, state='readonly').pack(side='left', padx=(5, 0))
        ttk.Label(conn, text='Leave the counter or power meter blank to type its readings. Examples: USB0::0x0957::0x0407::<serial>::INSTR   '
                             'GPIB0::10::INSTR   TCPIP0::192.168.1.20::INSTR   COM9', style='Muted.TLabel').grid(row=4, column=1, columnspan=3, sticky='w')

        if self.demo:
            ui.Notice(body, 'Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode').pack(fill='x', pady=(12, 0))
        else:
            ui.Notice(body, 'The program switches the generator output OFF after every point and asks you to confirm the wiring before every new setup. '
                            'The +20 dB range needs the -20 dB attenuator in front of the power sensor.', 'info', title='Hardware mode').pack(fill='x', pady=(12, 0))
        ttk.Label(body, text=src['note'], style='Small.TLabel', wraplength=1180, justify='left').pack(anchor='w', pady=(6, 0))

        tools = ttk.Frame(body); tools.pack(fill='x', pady=(8, 6))
        self.btn_run = ttk.Button(tools, text='▶  Run All Pending', style='Accent.TButton', command=self.run_all); self.btn_run.pack(side='left')
        self.btn_rerun = ttk.Button(tools, text='Rerun Selected', command=self.rerun); self.btn_rerun.pack(side='left', padx=8)
        self.btn_stop = ttk.Button(tools, text='■  Stop After This Point', style='Danger.TButton', command=self.request_stop, state='disabled'); self.btn_stop.pack(side='left')
        self.set_combo = ttk.Combobox(tools, textvariable=self.test_set, values=['Full verification', 'Quick check (Q points only)'], width=26, state='readonly')
        self.set_combo.pack(side='left', padx=(18, 6)); self.set_combo.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        ttk.Button(tools, text='Export Report (PDF)', command=self.export_pdf).pack(side='right', padx=(8, 0))
        ttk.Button(tools, text='Export CSV', command=self.export_csv).pack(side='right', padx=(8, 0))
        self.btn_load = ttk.Button(tools, text='Load progress', command=self.load); self.btn_load.pack(side='right', padx=(8, 0))
        ttk.Button(tools, text='Save progress', command=self.save).pack(side='right', padx=(8, 0))

        sumrow = ttk.Frame(body); sumrow.pack(fill='x', pady=(2, 8))
        self.summary = ui.Summary(sumrow); self.summary.pack(side='left', fill='x', expand=True)
        filt = ttk.Frame(sumrow); filt.pack(side='right', padx=(24, 0))
        ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='left')
        c1 = ttk.Combobox(filt, textvariable=self.show_section, values=['All sections'] + [s['title'] for s in SPEC['sections']], width=24, state='readonly')
        c1.pack(side='left', padx=6)
        c2 = ttk.Combobox(filt, textvariable=self.show_status, values=['All points', 'Not tested', 'Passed', 'Failed (OOT)'], width=13, state='readonly'); c2.pack(side='left')
        for c in (c1, c2): c.bind('<<ComboboxSelected>>', lambda _e: self.refresh())

        info = ttk.LabelFrame(body, text='Selected test point', padding=(12, 8)); info.pack(side='bottom', fill='x', pady=(10, 0))
        ttk.Label(info, textvariable=self.detail, wraplength=1100, justify='left').pack(anchor='w', fill='x')
        cols = ('n', 'section', 'description', 'nominal', 'low', 'high', 'reading', 'units', 'result')
        self.tree = ui.make_table(body, cols, ('#', 'Section', 'Description', 'Nominal', 'Low limit', 'High limit', 'Reading', 'Units', 'Result'),
                                  (44, 170, 380, 100, 100, 100, 110, 64, 90), height=12,
                                  anchors={'description': 'w', 'section': 'w', 'nominal': 'e', 'low': 'e', 'high': 'e', 'reading': 'e', 'units': 'w'},
                                  stretch={'n': False, 'section': False, 'nominal': False, 'low': False, 'high': False, 'reading': False, 'units': False, 'result': False})
        self.tree.tag_configure('pending', foreground=ui.C['muted'])
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
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
        return True

    def _row(self, p):
        rec = self.results.get(str(p['id']), {}); res = rec.get('result', ''); reading = rec.get('reading', '')
        shown = {'PASS': '✔ PASS', 'FAIL': '✖ FAIL'}.get(res, '—')
        name = p['section_title'] + (' ★' if p['quick'] else '')
        if p['kind'] == 'SELFTEST':
            rd = '' if reading == '' else ('Pass' if reading == 0 else 'Fail')
            return (p['id'], name, p['desc'], 'Pass', '', '', rd, '', shown), (res.lower() or 'pending',)
        vals, reads, unit_text = ui.si_row([p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'],
                                           [reading] if reading != '' else [], ref=display_ref(p))
        return (p['id'], name, p['desc'], vals[0], vals[1], vals[2], reads[0] if reads else '', unit_text, shown), (res.lower() or 'pending',)

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
        vals = [self.results.get(str(p['id']), {}).get('result', '') for p in self.active_points()]
        self.summary.update_counts(len(vals), vals.count('PASS'), vals.count('FAIL'))

    def on_period(self, save=True):
        apply_period(POINTS, PERIODS[self.period.get()])
        for key, rec in self.results.items():
            rec['result'] = judge(POINTS[int(key) - 1], rec['reading'])
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        lines = [p['desc']]
        if p['kind'] != 'SELFTEST':
            v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'], ref=display_ref(p))
            lines.append(f'Acceptable reading: {v[0]} to {v[1]} {u}  ({self.period.get()} limit)  |  Manual page {p["page"]}'
                         + ('  |  Quick check (Q)' if p['quick'] else ''))
        if p.get('typical'): lines.append('Guideline only: ' + p.get('note', ''))
        if p['kind'] in ('ACAMP', 'LFFLAT') and p['nominal'] >= 2.5:
            lines.append('5790B note: the 7 V range input is 50 kOhm (Table 4-4). With the generator\'s 50 ohm source this reads about 0.1 % '
                         'lower than a 1 MOhm DMM such as the 3458A the manual lists.')
        if p.get('ref'): lines.append(f'Worksheet reference: {p["ref"].replace("k_", "kHz_")}_reference (used for the flatness offsets).')
        lines.append('Setup: ' + p['setup'])
        rec = self.results.get(str(p['id']), {})
        if rec.get('raw'):
            lines.append('Recorded: ' + ', '.join(f'{k} = {v:.6g}' if isinstance(v, float) else f'{k} = {v}' for k, v in rec['raw'].items()))
        self.detail.set('\n'.join(lines))

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        for cb in self.entries.values(): cb['values'] = found
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def _addrs(self):
        return {k: v.get() for k, v in self.addr.items()}

    def test_connections(self):
        if self.demo: messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); self.root.update_idletasks()
        try:
            self.disconnect()
            self.io = IO(self._addrs(), ask_number=self.ask_number_threadsafe, std_input=STD_INPUTS[self.std_input.get()])
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); messagebox.showerror('Connection error', str(exc)); return
        self._set_conn(True); self._save_settings()
        extra = '\n'.join(f'{n}: {o.idn}' for n, o in (('Counter', self.io.counter), ('Power meter', self.io.power)) if o)
        manual = [n for n, o in (('frequency counter', self.io.counter), ('power meter', self.io.power)) if not o]
        self.status.set('Connected: ' + self.io.ident + '. Generator output is OFF.')
        messagebox.showinfo('Connected', f'{MODEL}: {self.io.ident}\nFluke 5790B: {self.io.std.idn}\n{extra}\n'
                            + (f'You will type the readings for: {", ".join(manual)}.\n' if manual else '') + 'Generator output is OFF.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else ('Demo - no hardware' if self.demo else 'Not connected'),
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for k, v in self.addr.items(): self.settings.set(k, v.get())
        self.settings.set('std_input', self.std_input.get()); self.settings.set('period', self.period.get())
        self.settings.save()

    def ask_number_threadsafe(self, prompt, unit):
        """Called from the worker thread; asks on the main thread and waits."""
        box, done = {}, threading.Event()
        def ask():
            try: box['v'] = simpledialog.askfloat('Type the reading', f'{prompt}\n\nReading in {unit}:', parent=self.root)
            finally: done.set()
        self.root.after(0, ask); done.wait()
        return box.get('v')

    # ------------------------------------------------------------------ running
    def request_stop(self): self.stop = True; self.status.set('Stopping after current test point.')
    def run_all(self): self.execute([p for p in self.active_points() if str(p['id']) not in self.results])

    def rerun(self):
        sel = self.tree.selection()
        if sel: self.execute([POINTS[int(sel[0]) - 1]])
        else: messagebox.showinfo('Selection', 'Select a test point first.')

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): messagebox.showwarning('Instrument ID', 'Enter an instrument ID.'); return
        if not self.demo and self.io is None: self.test_connections()
        if not self.demo and self.io is None: return
        if not self.demo and not self.conditions_ok and not ui.confirm_steps(self.root, 'Test conditions', 'Before you start',
                [('Warm-up', 'The generator has been powered on for at least 1 hour (manual, Test Considerations).'),
                 ('Environment', SPEC['source']['conditions'] + '.'),
                 ('Cables', 'Short RG-58 or equivalent 50 ohm cables only.')],
                facts=[('Points to run', len(points)), ('Limits', self.period.get())], ok='Conditions met - start'):
            return
        self.conditions_ok = True
        self.stop = False; self.busy = True; self.pref_cache = {}
        self._next(points, 0, None)

    def _prompt_setup(self, p):
        title, steps = self.WIRING[p['group']]
        steps = [(a, b.format(input=self.std_input.get())) for a, b in steps]
        image = HERE / 'diagrams' / f'hook_332xx_{p["group"]}.png'
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['section_title']), ('Manual page', p['page'])]
        return ui.confirm_steps(self.root, 'Rewire / verify - generator output is OFF', title,
                                [('Output OFF', f'The {MODEL} output has been switched OFF (confirmed).')] + steps,
                                facts=facts, caution='Continue only after physically checking the connections.',
                                ok='Connections verified - continue', image=str(image) if image.is_file() else None)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        key = p['group']
        if not self.demo and key != previous:
            try: self.io.all_off()
            except Exception as exc: self._error(exc); return
            if not self._prompt_setup(p):
                self.busy = False; self.status.set('Paused for wiring'); return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["section_title"]} - {p["desc"]}')
        if self.tree.exists(str(p['id'])): self.tree.selection_set(str(p['id'])); self.tree.see(str(p['id']))
        if self.demo:
            reading, raw = demo_reading(p)
            self._record(p, reading, raw, True); self.root.after(30, lambda: self._next(points, i + 1, key))
            return

        def work():
            try:
                reading, raw = self.io.measure(p, self.results, self.pref_cache)
                self.root.after(0, lambda: self._done(points, i, p, reading, raw, key))
            except Exception as exc:
                self.root.after(0, lambda: self._error(exc))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, raw, key):
        self._record(p, reading, raw, False); self.root.after(30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False
        title = 'SAFETY - check the front panel' if isinstance(exc, drivers.SafetyError) else 'Measurement stopped'
        self.status.set('Error - run stopped: ' + str(exc)); messagebox.showerror(title, str(exc))

    def _record(self, p, reading, raw, synthetic):
        stale = []
        if p.get('ref'):
            rng = int(p['ref'].split('_')[1].rstrip('dB'))
            stale = [q for q in POINTS if q['kind'] == 'FLAT' and q['range_db'] == rng and str(q['id']) in self.results]
        self.results[str(p['id'])] = dict(reading=reading, result=judge(p, reading), raw=raw, synthetic=synthetic,
                                          period=PERIODS[self.period.get()], timestamp=datetime.now().isoformat(timespec='seconds'))
        self._update_row(p); self.save(silent=True)
        if stale:
            messagebox.showwarning('Flatness reference changed',
                                   f'This reading is a flatness reference. {len(stale)} {p["ref"].split("_")[1]} range flatness result(s) were '
                                   'recorded with the earlier reference: rerun them.')

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return HERE / 'Procedures' / f'{MODEL}_{name}_checkpoint.json'

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(model=MODEL, asset=self.asset.get(), serial=self.serial.get(), demo=self.demo,
                                        period=self.period.get(), results=self.results), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if data.get('model') not in (None, MODEL):
            messagebox.showerror('Checkpoint', f'This checkpoint is for a {data.get("model")}, not a {MODEL}.'); return
        if any(v.get('synthetic') for v in data.get('results', {}).values()) and not self.demo:
            if not messagebox.askyesno('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.period.set(data.get('period', self.period.get())); self.results = data.get('results', {})
        self.on_period(save=False); self.status.set(f'Loaded progress: {len(self.results)} point(s) restored.')

    def export_pdf(self):
        rows = certificate_rows(self.results)
        if not rows: messagebox.showinfo('No results', 'No recorded results to export yet.'); return
        try: import report_pdf, report_dialog
        except ImportError as exc: messagebox.showerror('Report export', str(exc)); return
        details = report_dialog.ask_details(self.root, f'{MODEL} performance verification')
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.demo or any(v.get('synthetic') for v in self.results.values())
        note = ('Uncertainty: AC amplitude and low-frequency flatness use the laboratory A2LA scope, AC Voltage - Measure; the timebase uses '
                'Frequency - Measure; RF flatness uses specs/fgen_332xx_reference_cmc.json and is blank where no value is set. '
                'AC amplitude reference standard: Fluke 5790B (the manual lists a 3458A DMM).')
        try:
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'{SPEC["manufacturer"]} {MODEL}'), ('Instrument ID', self.asset.get()),
                                                                 ('Serial', self.serial.get()), ('Limits applied', self.period.get()),
                                                                 ('Source', f'{SPEC["source"]["document"]}, {SPEC["source"]["chapter"]}, pp. {SPEC["source"]["pages"]}')],
                                             demo=demo, details=details, footer_note=note, title='Calibration Data')
        except ImportError:
            messagebox.showerror('PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            messagebox.showerror('PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')], initialfile=f'{MODEL}_verification.csv')
        if not path: return
        demo = 'YES' if self.demo or any(v.get('synthetic') for v in self.results.values()) else 'NO'
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['Instrument ID', self.asset.get(), 'Serial Number', self.serial.get()])
            w.writerow(['SOURCE', f'{SPEC["source"]["document"]}, pp. {SPEC["source"]["pages"]}'])
            w.writerow(['LIMITS APPLIED', self.period.get()]); w.writerow(['DEMO DATA', demo]); w.writerow([])
            w.writerow(['#', 'Section', 'Description', 'Nominal', 'Low', 'High', 'Unit', 'Reading', 'Status', 'Quick check', 'Manual page',
                        'Worksheet values', 'Timestamp', 'Synthetic'])
            for p in POINTS:
                r = self.results.get(str(p['id']), {}); n = p['nominal']; e = p['error']
                lo, hi = ('', '') if p['kind'] == 'SELFTEST' else (n - e, n + e)
                w.writerow([p['id'], p['section_title'], p['desc'], 'Pass' if p['kind'] == 'SELFTEST' else n, lo, hi, p['unit'], r.get('reading', ''),
                            r.get('result', ''), 'Q' if p['quick'] else '', p['page'], json.dumps(r.get('raw', {})), r.get('timestamp', ''), r.get('synthetic', '')])
        self.status.set(f'Exported {path}')

    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); self.root.destroy()


def main(model, argv=None):
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    App(root, model, demo='--demo' in argv)
    root.mainloop()
