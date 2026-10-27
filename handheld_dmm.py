"""Verification engine for handheld meters: the calibrator output is set for you and the meter reading is typed in or, for meters
with an IR interface (Fluke 287 / 289, spec option "ir": "fluke28x"), read over the IR cable.

The calibrator output is set automatically (Fluke 5560A or 5522A over RS-232, or by hand if you prefer);
the technician reads the meter display and types the value in - or chooses "Read over IR", where the program reads the display,
checks the meter's function, range and REL / Low Pass state against the point, waits for a stable reading and records it. Test points and limits are NOT in this file:
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
import re
import sys
import threading
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import hookups
import ui_port
import ui_theme_core as ui                  # only its toolkit-free helpers here (Settings, report_filename); the window code is in handheld_dmm_view_tk.py
import appdata
import calibrator_fit
import datamode
import drivers
import procmods_engine
import reset_startup
import run_queue_engine
import virtualbench
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)

SPEC_PATH = HERE / 'specs' / 'fluke_110_series_pv.json'
READ_TYPED, READ_IR = 'Type the reading', 'Read over IR (Fluke IR cable)'
CAL_CHOICES = ['Fluke 5560A  (automatic output)', 'Fluke 5522A  (automatic output)', 'Manual  (5560A front panel)', 'Manual  (5522A front panel)']
OLD_CAL_CHOICES = {'Manual  (I set the calibrator)': 'Manual  (5560A front panel)'}
# The 5520A is added to the picker per procedure, and only when its published specification covers every output the procedure asks for (calibrator_fit);
# see App.cal_choices.  The 5522A / 5560A entries above are unchanged.
CAL_5520A_AUTO, CAL_5520A_MANUAL = 'Fluke 5520A  (automatic output)', 'Manual  (5520A front panel)'

WIRING = {
    'VOHM': 'Calibrator NORMAL HI / LO output to the meter VΩ and COM input terminals.',
    'AMP10': 'Calibrator in STANDBY, then reconfigure: calibrator high-current output to the meter 10 A and COM terminals. Check the meter fuse and that the leads are rated for 10 A.',
    'UAMP': 'Calibrator in STANDBY, then reconfigure: calibrator current output to the meter µA / mA input and COM terminals.',
    'TEMP': 'K-type thermocouple (mini-plug on both ends) between the calibrator thermocouple output and the meter temperature input, using the Fluke 80AK adapter. Allow the junctions to stabilise.',
    'VOLTALERT': 'Double banana plug on the calibrator voltage output; the meter is held against the plug (see the point instructions).',
    # user-built datasheets (dsb_runtime.py): the calibrator's SCOPE BNC output
    'SCOPE_DC': 'Calibrator SCOPE output (SCOPE voltage, 1 MΩ output impedance) to the oscilloscope input with the BNC cable. No terminator.',
    'SCOPE_SINE': 'Calibrator SCOPE output (leveled sine, 50 Ω) to the oscilloscope input through the 50 Ω BNC cable and a 50 Ω feedthrough terminator at the scope input.',
    'SCOPE_MARKER': 'Calibrator SCOPE output (time marker) to the oscilloscope input with the BNC cable and a 50 Ω feedthrough terminator at the scope input.',
}
SYMBOL = {'ohm': 'Ω', 'V': 'V', 'A': 'A', 'F': 'F', 'Hz': 'Hz', 'C': '°C', 'degC': '°C', 'degF': '°F', 'S': 'S', '%': '%', 's': 's', 'dB': 'dB'}
TEMP_BASE_UNITS = ('C', 'degC', 'degF')     # temperatures are never SI-prefixed (no 'k°C'); the calibrator always sources degrees C
SQUARE_KINDS = ('DUTY', 'SQUARE')          # square-wave sources: applied = value (V peak-to-peak), frequency, duty (%), offset (V DC); DUTY is read as duty cycle, SQUARE as DCV (Peak Min Max)


def load_spec(path=SPEC_PATH):
    """A spec JSON by absolute path, or by file name inside specs/ (e.g. 'klein_mm325_pv.json')."""
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = HERE / 'specs' / path
    return json.loads(path.read_text(encoding='utf-8'))


def points_for(spec, model):
    """The model's steps in manual order (functional checks first), numbered 1..n."""
    order = spec.get('options', {}).get('table_order') or {'F': 0}     # opt-in: run whole tables in this order (e.g. F, 3, 4)
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
    if p.get('dsb_out'):                       # user-built datasheets: the runtime words the output itself (scope / generator points)
        return p['dsb_out']
    a = p.get('applied')
    if not a:
        return 'No calibrator output (STANDBY)'
    kind, v, f = p['kind'], a['value'], a.get('frequency')
    unit = {'ACV': 'V', 'DCV': 'V', 'ACI': 'A', 'DCI': 'A', 'OHM': 'ohm', 'CAP': 'F', 'TEMP': 'C', 'DUTY': 'V', 'SQUARE': 'V'}[kind]
    text = _fmt(v, unit)
    if kind in SQUARE_KINDS or (kind == 'ACV' and a.get('waveform') == 'square'):
        text += f' p-p square wave, {_fmt(f, "Hz")}, {a.get("duty", 50.0):g} % duty'
        if a.get('offset'):
            text += f', {_fmt(a["offset"], "V")} DC offset'
    elif kind in ('ACV', 'ACI'):
        text += f' AC @ {_fmt(f, "Hz")}'
    elif kind in ('DCV', 'DCI'):
        text += ' DC'
    return text


def describe(p):
    if p.get('dsb_desc'):                      # user-built datasheets: a description that also carries the frequency / level
        return p['dsb_desc']
    if p['test'] == 'beeper':
        return f'Continuity, {output_text(p)}: beeper {p["expect"].upper()}'
    if p['test'] == 'visual':
        return p.get('title') or p['section'] + (' ' + p['switch'].split('(')[-1].strip(') ') if p['section'] == 'VoltAlert' else '')
    return f'{p["section"]}, {p["range"]} range' if p['range'] else p['section']


def split_switch(switch):
    """'V~  (AC volts)' -> ('V~', 'AC volts'); text without a double-space bracket (e.g. 'Temperature') -> (text, '')."""
    m = re.match(r'^(.*?)\s{2,}\((.*)\)\s*$', switch or '', re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else ((switch or '').strip(), '')


def function_change_card(p, total, standby_text, standby_known=False):
    """What the 'Change the function' window (layout C, ui_theme.confirm_steps(layout='function_change')) shows for point `p`.
    Presentation only: the same facts the list layout carried (point n of N, the test, the meter function and range, the rotary switch step,
    the standby step).  `standby_known` is True only when the program has CONFIRMED the calibrator is in standby (a read-back); the engine
    sends STBY before the dialog but does not read it back (standby_quiet swallows errors), so it passes False and step 1 is a numbered
    step, not a green tick."""
    short, detail = split_switch(p['switch'])
    meter = f'Meter: {short}' + (f'  range {p["range"]}' if p['range'] else '')
    steps = [('Calibrator output is OFF (standby)' if standby_known else 'Standby', standby_text, 'done' if standby_known else 'todo'),
             (f'Turn the rotary switch to {short}', detail, 'todo'),
             (f'Press Done when the meter shows {short}', 'The program then goes on with this point.', 'todo')]
    return dict(n=p['n'], total=total, test=describe(p), meter_line=meter, steps=steps)


# Owner decision 2026-10-26: on the handheld multimeters and clamp meters every frequency reading whose standard is a calibrator takes the uncertainty of the
# CALIBRATOR'S OWN OUTPUT FREQUENCY SPECIFICATION (uncertainty_budget, 'FREQ' with the calibrator model).  Set this ONE switch to False to get the older
# lab rule back: the 'Frequency - Measure' CMC alone, never combined with the calibrator.  Bench DMMs, scopes, generators and counters are not affected.
FREQ_UNCERTAINTY_FROM_CALIBRATOR = True


def freq_from_calibrator():
    """True while the owner rule (2026-10-26) is on: a frequency reading is judged by the calibrator's own output-frequency specification."""
    return bool(FREQ_UNCERTAINTY_FROM_CALIBRATOR)


def unc_frequency(p):
    """The frequency (Hz) a frequency-reading point (unc_kind FREQ) is judged at: the applied frequency, or `unc_frequency` for a point whose calibrator is set by hand."""
    a = p.get('applied') or {}
    f = a.get('frequency')
    return f if f is not None else p.get('unc_frequency')


def pad_reading(p, text):
    """Rule: a typed reading is filled out to the point's display resolution with zeros (5 -> 5.000 on a 5.000 V point), so the
    stored/printed reading matches the test point's resolution. The resolution is the most decimals in the point's limits.
    Text that is not a plain number (OL) and readings typed with more decimals than the resolution are left as typed."""
    t = text.strip().replace(',', '')
    try:
        Decimal(t)
    except InvalidOperation:
        return text.strip()
    if t.upper() in ('NAN', 'INF', '-INF', 'INFINITY', '-INFINITY') or 'E' in t.upper():
        return text.strip()
    want = 0
    for key in ('low', 'high'):
        try:
            want = max(want, max(0, -Decimal(p[key]).as_tuple().exponent))
        except (KeyError, InvalidOperation, TypeError):
            pass
    whole, _, frac = t.partition('.')
    if whole in ('', '+', '-'):                       # '.5' is written 0.5 (and '-.5' as -0.5), whatever the resolution
        whole += '0'
        t = whole + '.' + frac if '.' in t else whole
    if len(frac) >= want:
        return t
    return f'{whole}.{frac.ljust(want, "0")}' if want else whole


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
def pm_same(a, b):
    """Decimal-safe equality of two numbers (procmods_pointdef)."""
    import procmods_pointdef
    return procmods_pointdef.same_decimal(a, b)


class Cancelled(Exception):
    pass


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """The calibrator: set the output for a point, confirm it was accepted, and never leave it energised."""
    RAMP_ABOVE, RAMP_STEP, RAMP_DELAY = 100.0, 50.0, 5.0     # the 110-series manual's "ramp up in 50 V increments, 5 s apart"
    auto_ramp = True                                          # the spec's options.auto_ramp (false: straight to the test value)
    virtual = False                                           # demo on the virtual bench: waits are shortened, nothing is appended to the shared log

    def __init__(self, model_name, address, baud=9600, transport=None, mods=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual:
            virtualbench.mark_log(self.log)
        cls = drivers.Fluke5522A if '5522' in model_name else drivers.Fluke5520A if '5520' in model_name else drivers.Fluke5560A
        t = transport or drivers.open_visa(address, timeout=20, baud=baud)
        self.cal = cls(t, self.log, label=cls.MODEL)
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close()
            raise
        self.ident = self.cal.idn

    def reset_roles(self):
        return [self.cal], []          # the meter under test has no remote interface here (typed readings)

    def pm_drivers(self):
        return (self.cal,)

    def standby(self):
        """Output to STANDBY; a calibrator left on a square wave (duty-cycle / Peak Min Max points) is put back to WAVE SINE with no DC offset
        straight after (once, read back; a failure is logged and the next point refuses to start, see apply)."""
        self.cal.standby_quiet()
        self._lcomp_off()
        if getattr(self.cal, 'wave_nonsine', False):
            try:
                self.cal.restore_sine()
            except Exception as exc:
                self.log.add('!!', f'square wave NOT changed back to sine: {exc}', self.cal.label)

    @staticmethod
    def uses_coil(p):
        """AC current through the 50-turn coil (the coil groups, or a point carrying the coil uncertainty rule)."""
        return p.get('kind') == 'ACI' and ('COIL' in str(p.get('group') or '') or bool(p.get('unc_standard')))

    def _lcomp_off(self):
        """LCOMP OFF after a coil point (set once, read back; a failure is logged, never retried)."""
        if not getattr(self, '_lcomp_on', False):
            return
        self._lcomp_on = False
        try:
            self.cal.set_lcomp(False)
            self.cal.check_error('LCOMP OFF')
        except Exception as exc:
            self.log.add('!!', f'LCOMP was NOT confirmed OFF: {exc}', self.cal.label)
        self.cal.standby_quiet()                    # the last command is STBY again: the output is left in standby

    def _lcomp_for(self, p, amps, hz, context):
        """Inductive load compensation ON for an AC current point through the 50-turn coil (5522A / 5520A: LCOMP ON, read back).  Outside the range the calibrator
        allows (below 440 Hz under 0.33 A, below 1 kHz from 0.33 A) it is not set and the reason is logged; a calibrator without LCOMP (5560A) leaves it to the
        operator (the point's group text says so)."""
        if not self.uses_coil(p) or not hasattr(self.cal, 'set_lcomp'):
            return
        if not self.cal.lcomp_allowed(amps, hz):
            self.log.add('!!', f'LCOMP not set: {hz} Hz at {amps} A is outside what the calibrator allows for compensation', self.cal.label)
            return
        self.cal.set_lcomp(True)
        self._lcomp_on = True
        self.cal.check_error(context)

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
        if virtualbench.log_is_virtual(self.log):                  # a virtual (demo) session is never evidence
            return
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

    def _volts(self, v, f, context, cancel, ramp=None, dc=False):
        steps = [v]
        if ramp:                                   # a ramp the meter's manual prescribes (e.g. 60 V then 120 V)
            steps = [float(x) for x in ramp]
        elif self.auto_ramp and abs(v) > self.RAMP_ABOVE:
            n = int(abs(v) // self.RAMP_STEP)
            steps = [math.copysign(self.RAMP_STEP * i, v) for i in range(1, n + 1)]
            if abs(steps[-1]) < abs(v):
                steps.append(v)
        for i, level in enumerate(steps):
            self.cal.set_output_volts(level, f, dc=dc)
            self.cal.check_error(context)
            if i == 0:
                self.cal.operate_unverified()
            if len(steps) > 1 and i < len(steps) - 1:
                self._wait(virtualbench.scaled(self.pm_param('handheld.ramp_delay', self.RAMP_DELAY), self.virtual), cancel)

    @procmods_engine.point_commands()
    def apply(self, p, cancel=None):
        """Program and enable the output for point p, then wait for it to settle."""
        a = p['applied']
        kind, v, f = p['kind'], a['value'], a.get('frequency')
        context = describe(p)
        self.standby()
        if getattr(self.cal, 'wave_nonsine', False) and kind not in SQUARE_KINDS:
            raise drivers.InstrumentError('The calibrator is still on a square wave (WAVE SINE was not confirmed after the last square-wave point): '
                                          'output not enabled. Run again (the calibrator is reset to its defaults first).')
        square_level = kind == 'ACV' and a.get('waveform') == 'square'       # a datasheet level given in Vpp: a square wave, amplitude peak-to-peak
        if kind in ('DCV', 'ACV') and not square_level:
            self._volts(v, f, context, cancel, ramp=p.get('ramp'), dc=kind == 'DCV')
        else:
            if kind in ('DCI', 'ACI'):
                self.cal.set_output_amps(v, f, dc=kind == 'DCI')
                if kind == 'ACI':
                    self._lcomp_for(p, v, f, context)
            elif kind == 'OHM':
                self.cal.set_output_ohms(v)
            elif kind == 'CAP':
                self.cal.set_output_capacitance(v)
            elif kind == 'TEMP':
                self.cal.set_output_temperature(v)
            elif kind in SQUARE_KINDS or square_level:
                if not hasattr(self.cal, 'set_output_square'):
                    raise drivers.InstrumentError(f'{getattr(self.cal, "label", "The calibrator")} cannot make a square wave: this point asks for a level in Vpp '
                                                  f'({_fmt(v, "V")} p-p). Output not enabled.')
                self.cal.set_output_square(v, f, a.get('duty', 50.0), a.get('offset', 0.0))
            else:
                raise ValueError('No calibrator output for ' + kind)
            self.cal.check_error(context)      # the calibrator refuses outputs it cannot make; never operate then
            self.cal.operate_unverified()
        self.on_at = time.monotonic()
        self._wait(virtualbench.scaled(p.get('settle', self.pm_param('handheld.settle.default', 3.0)), self.virtual), cancel)


def limit_line(p):
    """The text after 'Limit:' in the reading window and the point detail.  Shipped specs print their own `tol_text`.  A step made by the Datasheet
    Builder (it has a 'dsb' block) shows its LOW and HIGH limit (absolute, in the display unit and padding of the Low limit / High limit columns)
    and the statement they came from, never a +/- error: 'Low limit 4.9965 V, High limit 5.0035 V  (from 0.05 % of reading + 2 counts)'.
    Display only: the step's tol_text, low and high are not changed."""
    text = p.get('tol_text') or ''
    if not text or not p.get('dsb') or 'low' not in p or 'high' not in p:
        return text
    unit = p.get('display_unit', '')
    typed = (p['dsb'].get('limit') or {}).get('source') == 'override'
    how = 'typed limits' if typed else (f'from {p["accuracy"]}' if p.get('accuracy') else '')
    return f'Low limit {p["low"]} {unit}, High limit {p["high"]} {unit}'.replace(' ,', ',').rstrip() + (f'  ({how})' if how else '')


# ============================================================================ the reading dialog
READING_WIDTH = 560         # content width of the reading window in 96-dpi units (layout C; text wraps inside it)
OUTPUT_ON_NOTE = 'Output is ON'     # the note _out_note gives while the program has the calibrator output on


def ask_reading(parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None):
    """One modal dialog. mode 'numeric' (type the display) or 'yesno' (answer a question).
    Returns dict(action='record'|'skip'|'stop', text=, ann=, yes=).  The window is the toolkit's (UiPort.ask_reading; Tk: handheld_dmm_view_tk.ask_reading).
    Kept as a module function: the test harnesses and run_queue_engine call it as handheld_dmm.ask_reading."""
    return ui_port.ui.ask_reading(p, total, out_text, out_note, accept, mode, question, unit, annunciator, validate, phase, limit_s, on_expire, device, source, demo_fill,
                                  parent=parent)


def ask_readings(parent, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None,
                 device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading=''):
    """The one-window reading entry for a run queue (several meters, one point): UiPort.ask_readings (Tk: run_queue_ui.ask_readings).
    Kept as a module function: run_queue_engine calls it as handheld_dmm.ask_readings."""
    return ui_port.ui.ask_readings(p, total, out_text, out_note, accept, meters, unit, judge, limit_s, on_expire, device, source, demo_fill, tol_text, phase, heading,
                                   parent=parent)


# ============================================================================ the IR set-up / reading problem dialog
def ask_ir_problem(parent, p, total, problems, shown):
    """The meter (read over IR) is not set up as the point needs, or the reading did not settle.
    Returns 'retry', 'type' (type this reading instead), 'skip' or 'stop'.  The window is the toolkit's (UiPort.ask_ir_problem)."""
    return ui_port.ui.ask_ir_problem(p, total, problems, shown, parent=parent)


def ir_text(p, r):
    """The meter reading converted to the point's display unit, at the meter's own resolution (what a technician would type)."""
    if r.overload:
        return 'OL'
    shift = round(math.log10(10 ** r.mult / p['factor']))
    return f'{r.value / p["factor"]:.{max(r.decimals - shift, 0)}f}'


def ir_read(meter, p, cancel=None, timeout=45.0):
    """(text, Reading, Display, history) for point p, or raises SetupProblem with what to fix. Pure I/O - no Tk."""
    want = p['ir']
    disp = meter.display()
    problems = drivers.fluke_28x.check_setup(disp, want)
    if problems:
        raise SetupProblem(problems, disp.summary())
    try:
        r, disp, history = meter.stable_reading(want['unit'], cancel=cancel, timeout=p.get('ir_timeout', timeout))
    except drivers.InstrumentError as exc:
        raise SetupProblem([str(exc)], '')
    problems = drivers.fluke_28x.check_setup(disp, want)       # the set-up must still be right at the moment of the reading
    if problems:
        raise SetupProblem(problems, disp.summary())
    return ir_text(p, r), r, disp, history


class SetupProblem(Exception):
    def __init__(self, problems, shown):
        super().__init__('; '.join(problems))
        self.problems, self.shown = problems, shown


# ============================================================================ the range-selection dialog
def ask_range(parent, p, total, dial, standby_text):
    """'Turn the dial to ...' with a picture of the dial and the target position marked.
    Returns 'ok' (continue), 'skip' (skip the point) or 'stop'.  The window is the toolkit's (UiPort.ask_range)."""
    return ui_port.ui.ask_range(p, total, dial, standby_text, parent=parent)


# ============================================================================ application
class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, run_queue_engine.QueueMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root, model, demo=False, spec=None, io_factory=None, meter_factory=None, fast_demo=False):
        self.root, self.model, self.demo = root, model, demo
        self.init_virtual(demo, fast_demo)
        self.meter, self.meter_factory = None, meter_factory
        self._stage = {'id': None, 'done': set()}
        self.spec = spec or load_spec()
        self.info = self.spec['models'][model]
        self.points = self.build_points()
        self.by_id = {p['id']: p for p in self.points}
        self.cal_offer = self.calibrator_offer()               # the 5520A: in the picker only when its published specification covers this procedure's points
        self.pm_init('handheld', model, demo=demo, lists=[self.points], on_change=self._pm_points_changed)   # procedure modifications
        self.io, self._busy, self.stop = None, False, False
        self.io_factory = io_factory
        self.results = {}
        self.ui_view.setup_window(self)
        self.brand = self.info.get('brand', 'Fluke')
        self.last_high_current = None
        self.settings = ui.Settings(self.settings_name())
        self.asset, self.serial = port.var(), port.var()
        _saved = self.settings.get('cal_mode', CAL_CHOICES[0])
        _saved = OLD_CAL_CHOICES.get(_saved, _saved)
        self.cal_mode = port.var(_saved if _saved in self.cal_choices() or '5520' not in _saved else CAL_CHOICES[0])   # a saved 5520A choice the picker no longer offers falls back to the default
        self.cal_addr = port.var(self.settings.get('cal_addr', 'COM9'))
        self.cal_baud = port.var(self.settings.get('cal_baud', '9600'))
        self.ir = self.spec.get('options', {}).get('ir')
        saved = self.settings.get('read_mode', READ_TYPED)
        self.read_mode = port.var(saved if saved in (READ_TYPED, READ_IR) else READ_TYPED)
        self.ir_addr = port.var(self.settings.get('ir_addr', 'COM5'))
        self.status = port.var()
        self.detail = port.var('Select a test point to see its limits and setup.')
        self.show_section, self.show_status = port.var('All sections'), port.var('All points')
        self._build_ui()
        self.status.set(('DEMO MODE (virtual instruments): the windows of a real run appear; commands go to a simulated calibrator. Enter an Instrument ID, then press Run All.' if self.virtual else
                         'FAST DEMO: no commands are sent and no readings are asked for. Enter an Instrument ID, then press Run All.') if demo else
                        'Step 1: enter the Instrument ID. Step 2: choose the calibrator and press Test connection (or choose Manual). Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    def build_points(self):
        """The point list of this run (a hook: user-built datasheets, dsb_runtime.py, add their scope / generator points)."""
        return points_for(self.spec, self.model)

    def calibrator_offer(self):
        """calibrator_fit.Offer for the Fluke 5520A: offered only when every output this procedure asks for is inside the 5520A's published specification
        (a hook: user-built datasheets route their points through the Datasheet Builder match and override it)."""
        return calibrator_fit.make_offer('5520A', calibrator_fit.handheld_requests(self.points), unverified=drivers.Fluke5520A.unverified_summary())

    def cal_choices(self):
        """The calibrator picker's values: the 5560A / 5522A entries as always, then the 5520A (automatic and front-panel) when its specification covers the procedure."""
        out = list(CAL_CHOICES)
        if self.cal_offer.offered:
            out.insert(2, CAL_5520A_AUTO)
            out.append(CAL_5520A_MANUAL)
        return out

    def settings_name(self):
        return f'{self.brand.lower()}{self.model}'

    def _pm_points_changed(self):
        """The point list was patched in place (procedure modifications): the lookup by id must follow."""
        self.by_id = {p['id']: p for p in self.points}

    @property
    def busy(self):
        return self._busy

    @busy.setter
    def busy(self, value):
        self._busy = value
        if not value and self._q is not None:
            self._queue_aborted()                  # a run queue was paused / failed: keep every meter's progress
        if hasattr(self, 'btn_run'):
            self.ui_view.sync_buttons(self, value)

    @property
    def manual_cal(self):
        return self.cal_mode.get().startswith('Manual')

    @property
    def use_ir(self):
        return bool(self.ir) and self.read_mode.get() == READ_IR

    # ------------------------------------------------------------------ layout
    VIEW = 'handheld_dmm_view'                             # the toolkit's window code: handheld_dmm_view_tk (Tk), later _qt

    @property
    def ui_view(self): return port.view(self.VIEW)

    def _build_ui(self): self.ui_view.build_ui(self)

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
        if not self.status_visible(p['id'], st):
            return False
        return True

    def _row(self, p):
        key = p['id']
        rec, f, l = self.results.get(key, {}), self.found.get(key), self.left.get(key)
        res = rec.get('result', '')
        shown = {'PASS': '✔ PASS', 'FAIL': '✖ FAIL'}.get(res, '—')
        numeric = p['test'] == 'numeric'
        unit = p['display_unit'] if numeric else ''
        with_unit = lambda v: (f'{v} {unit}'.strip() if v not in ('', None) else '')
        found = with_unit((f or {}).get('entered', '')) if f else ''
        left = with_unit(l.get('entered', '')) if l else ('Same' if (self.is_left and f) else '')
        low, high = (with_unit(p['low']), with_unit(p['high'])) if numeric else ('', '')
        step = p.get('ref') or ('p. 7' if p['table'] == 'F' else f'T{p["table"]} #{p["step"]}')
        out = output_text(p) if p.get('applied') else '—'
        return (p['n'], f'{describe(p)}   ({step})', out, low, high, (low + ' … ' + high) if numeric else '', found, '', left, shown), (res.lower() or 'pending',)

    def pm_driver_classes(self): return (drivers.Fluke5560A, drivers.Fluke5522A, drivers.Fluke5520A)

    def pm_point_fields(self, view):
        """Developer-mode fields of a handheld point.  The nominal (base units) is what the calibrator is told to output and what the reading
        is judged against; the limits are strings in the display unit (the unit shown is tied to that scaling, so it is not editable); the
        description is the line shown to the technician (a user-datasheet point already has one; a built-in one is worded from its section)."""
        out = super().pm_point_fields(view)
        a = view.get('applied')
        if not a or 'nominal' not in view:
            out['nominal'] = {'paths': [], 'reason': 'this point sources nothing, so it has no nominal', 'note': ''}
        elif view.get('ramp'):
            out['nominal'] = {'paths': [], 'reason': 'this point follows a ramp the meter\'s manual prescribes; its steps are not recomputed', 'note': ''}
        elif not pm_same(a.get('value'), view.get('nominal')):
            out['nominal'] = {'paths': [], 'reason': 'the value this point sources differs from its nominal', 'note': ''}
        else:
            out['nominal'] = {'paths': ['nominal', 'applied.value'], 'reason': '',
                              'note': 'In base units (V, A, ohm, F ...). This sets the output the calibrator is told to make and the value the reading '
                                      'is judged against; the high-voltage prompts and the ramp rules still apply to the new value.'}
        out['unit'] = {'paths': [], 'reason': 'the unit is tied to the scaling of the limits (mV, kohm ...) and is not editable', 'note': ''}
        out['description'] = {'paths': ['dsb_desc'], 'reason': '', 'note': 'The line shown to the technician for this point.'}
        return out

    def pm_plan_point(self, p):
        """The commands IO.apply sends for point p, then the STANDBY the run sends once the reading is typed: a dry run on the simulated bench
        (procmods_plan).  The meter under test has no remote interface here (the technician types the reading), so only the calibrator has commands."""
        import procmods_plan
        from drivers.simulated import make_bench, SimFlukeTransport
        if not p.get('applied'):
            return procmods_plan.Plan(note='This point has no calibrator output (nothing is sourced), so no instrument command is sent for it.')
        if self.manual_cal:
            return procmods_plan.Plan(note='The calibrator is set to Manual: the technician sets its output by hand, so no instrument command is sent.')
        model = '5522A' if '5522' in self.cal_mode.get() else '5520A' if '5520' in self.cal_mode.get() else '5560A'
        auto_ramp = self._auto_ramp()

        def build(mods):
            bench, _a, _b = make_bench()
            io = IO(self.cal_mode.get(), 'sim', transport=SimFlukeTransport(bench, model), mods=mods)
            io.auto_ramp = auto_ramp
            return io

        def run(io):
            io.apply(p)
            io.standby()                                   # what the run does once the reading has been typed
        return procmods_plan.run_plan(self.pm_state, build, run)

    def pm_point_title(self, p): return describe(p)

    def refresh(self):
        keep = self.ui_view.table_selection(self)
        self.ui_view.table_set_rows(self, ((p['id'], *self._row(p)) for p in self.points if self._visible(p)), keep)
        self.update_summary()

    def _update_row(self, p):
        if self.ui_view.table_has(self, p['id']):
            values, tags = self._row(p)
            self.ui_view.table_update_row(self, p['id'], values, tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.points)
        self.update_shell_sections(self.points, lambda p: p['section'])

    def accept_text(self, p):
        if p['test'] == 'numeric':
            extra = '  and the AC annunciator is ON' if p.get('annunciator') else ''
            return f'{p["low"]} to {p["high"]} {p["display_unit"]}{extra}'
        return p.get('question') or ' / '.join(c['question'] for c in p['checks'])

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel:
            return
        p = self.by_id[sel[0]]
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        limit = f'\nLimit: {limit_line(p)}' if p.get('tol_text') else ''
        self.detail.set(f'{describe(p)}\nAccept: {self.accept_text(p)}  |  Meter: {p["switch"]}' + (f', {p["range"]} range' if p['range'] else '') + limit +
                        f'\nSetup: {self.setup_text(p)}{extra}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

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

    def _drawn_image(self, p, image):
        """The drawn hook-up picture for the chosen calibrator (diagrams/hook_<meter>_<cal>_<group>.png) when the spec names one with the option
        'hookup_images' and it exists; otherwise the picture the group already had (the supplied panel photo). Only the picture changes, never a step."""
        meter = self.spec.get('options', {}).get('hookup_images')
        if not meter:
            return image
        drawn = hookups.image_path(meter, hookups.calibrator_key(self.cal_mode.get()), p['group'])
        return drawn or image

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
        self.ui_view.set_choices(self, 'cal', found)
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
        elif self.virtual:                                  # demo: the real IO / driver code over a simulated calibrator
            _bench, transport = virtualbench.calibrator_transport(self.cal_mode.get())
            self.io = IO(self.cal_mode.get(), 'virtual', 9600, transport=transport, mods=self.pm_state, virtual=True)
        else:
            self.io = IO(self.cal_mode.get(), self._address(), int(self.cal_baud.get()), mods=self.pm_state)
        self.io.auto_ramp = self._auto_ramp()
        self._set_conn(True)
        if not self.demo:
            self._save_settings()                           # a demo never changes the saved connection settings

    def test_connection(self):
        if self.fast_demo:
            port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.')
            return
        if self.manual_cal:
            port.message('info', 'Manual calibrator', 'Manual mode: no connection is needed. The program will tell you what to set on the calibrator.')
            return
        self.status.set('Connecting ...')
        port.flush(self.root)
        try:
            self.connect()
        except Exception as exc:
            self.disconnect()
            self._set_conn(False)
            self.status.set('Connection error: ' + str(exc))
            port.message('error', 'Connection error', str(exc))
            return
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator output is NOT enabled.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'{self.io.ident}{tag}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io:
            self.io.close()
            self.io = None
        self.disconnect_meter()
        self._set_conn(None)

    def _ir_address(self):
        t = self.ir_addr.get().strip()
        if '::' in t:
            return t
        t = t.upper().replace('COM', '')
        if not t.isdigit():
            raise ValueError('Enter the IR cable COM port (e.g. COM5).')
        return f'ASRL{int(t)}::INSTR'

    def connect_meter(self):
        self.disconnect_meter()
        if self.meter_factory:
            self.meter = self.meter_factory()
        else:
            s = drivers.fluke_28x.SERIAL_DEFAULT
            t = drivers.open_visa(self._ir_address(), timeout=3, baud=s.baud, data_bits=s.data_bits, parity=s.parity, stop_bits=s.stop_bits,
                                  write_termination=s.write_termination, read_termination=s.read_termination, flow_control=s.flow_control)
            self.meter = drivers.Fluke28x(t, drivers.CommandLog(), label=f'Fluke{self.model}').connect()
        if self.meter.model != self.model:
            got = self.meter.idn
            self.disconnect_meter()
            raise drivers.InstrumentError(f'The IR cable reaches a Fluke {got.split(",")[0].split()[-1]}, but this procedure is for the Fluke {self.model}.')
        self._save_settings()

    def disconnect_meter(self):
        if self.meter:
            self.meter.log.append_default(f'Fluke {self.model} IR session')     # the exact queries and replies, as evidence
            try:
                self.meter.close()
            except Exception:
                pass
            self.meter = None

    def test_ir(self):
        if self.demo:
            self.read_mode.set(READ_TYPED)
            port.message('info', 'Demo mode', 'The IR cable is not simulated: in demo mode the readings are typed (or filled with the simulated reading).')
            return
        try:
            self.connect_meter()
        except Exception as exc:
            self.status.set('IR connection error: ' + str(exc))
            port.message('error', 'IR connection', str(exc))
            return
        self.read_mode.set(READ_IR)
        self.status.set('Meter on the IR cable: ' + self.meter.idn)
        port.message('info', 'IR connection', f'{self.meter.idn}\nReadings will be collected over IR.')

    def _set_conn(self, ok):
        self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Demo - no hardware' if self.demo else 'Manual calibrator' if self.manual_cal else 'Not connected',
                           'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('cal_mode', self.cal_mode), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('read_mode', self.read_mode), ('ir_addr', self.ir_addr)):
            self.settings.set(key, var.get())
        self.settings.save()

    # ------------------------------------------------------------------ running
    def request_stop(self):
        self.stop = True
        self.status.set('Stopping after the current test point.')

    def run_all(self):
        self.execute(self.queue_pending(self.points) if self.queue_wants_run() else [p for p in self.points if p['id'] not in self.results])

    def run_section(self):
        self.run_shown_section(self.points)

    def rerun(self):
        sel = self.ui_view.table_selection(self)
        if sel:
            self._queue_force = True                       # a run queue measures the chosen point again on every meter
            self.execute([self.by_id[sel[0]]])
        else:
            port.message('info', 'Selection', 'Select a test point first.')

    def rerun_from(self):
        sel = self.ui_view.table_selection(self)
        if sel:
            self._queue_force = True                       # as Rerun Selected: a run queue measures these points again on every meter
            self.execute(self.points_from(self.points, sel[0]))
        else:
            port.message('info', 'Selection', 'Select a test point first.')

    def execute(self, points):
        if self.busy or not points:
            return
        if self.queue_wants_run():                         # two or more meters in the run queue (run_queue_engine.py); one meter runs below, as always
            return self.queue_execute(points)
        self.__dict__.pop('_queue_force', None)
        if not self.asset.get().strip():
            port.message('warning', 'Instrument ID', 'Enter an instrument ID.')
            return
        points = self.pm_begin_run(points, self.asset.get().strip())     # load the saved modifications for this asset (patches self.points)
        if not points:
            self.status.set('Every selected point is skipped by a procedure modification.')
            return
        if not self.confirm_found_overwrite(points):
            return
        if self.virtual and self.use_ir:
            self.read_mode.set(READ_TYPED)                  # the IR cable is not simulated
        if not self.fast_demo and not self.manual_cal and self.io is None:
            self.test_connection()
            if self.io is None:
                return
        if not self.demo and self.use_ir and self.meter is None:
            self.test_ir()
            if self.meter is None:
                return
        self.stop = False
        self.busy = True
        self._last_switch = None
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    def reset_extra_uuts(self):
        return [self.meter] if (self.use_ir and self.meter is not None) else []     # the 287 / 289 on IR: documented exemption (no reset)

    def reset_log(self):
        return self.io.log if self.io is not None else (self.meter.log if self.meter is not None else None)

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
            image = self._drawn_image(p, image)
            return port.operator_prompt('Change the cables', group['title'], steps + self._qsteps(), facts=self._qfacts(facts), caution=group.get('caution'),
                                        ok='Connections checked - continue', image=image if image and image.is_file() else None, parent=self.root)
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
        return port.operator_prompt('Check the setup', f'Set up for {p["section"]}', steps + self._qsteps(), facts=self._qfacts(facts), caution=caution, ok='Done - continue', parent=self.root)

    def _auto_ramp(self):
        return bool(self.spec.get('options', {}).get('auto_ramp', True))

    def _high_voltage(self, p):
        a = p.get('applied')
        threshold = self.spec.get('options', {}).get('hv_threshold_v', 500)
        return bool(a) and p['kind'] in ('DCV', 'ACV') and abs(a['value']) >= threshold

    def _hv_group_seen(self, key):
        """options.hv_once_per_group (opt-in, default off: other specs keep the per-point question): the high-voltage question was already
        answered Yes for this hook-up group."""
        return bool(self.spec.get('options', {}).get('hv_once_per_group')) and getattr(self, '_hv_ok_key', None) == key

    def _prompt_function(self, p):
        """options.function_prompt: each time the meter's rotary switch has to move to a new function, tell the operator (the output is
        in standby meanwhile). Points of group NONE (functional checks, hand-set points) and points that get the dial/range prompt carry their own. True = go on, False = the operator cancelled."""
        opts = self.spec.get('options', {})
        if not opts.get('function_prompt'):
            return True
        if p['group'] == 'NONE':                   # functional checks / hand-set points: no dial prompt (their own prompt already told the operator);
            self._last_switch = p['switch']        # the next point on the same function (e.g. conductance, capacitance) is not asked again
            return True
        if opts.get('range_prompt') and p.get('dial'):     # the range prompt ('Turn the dial to ...', every point) already covers the function
            self._last_switch = p['switch']
            return True
        if p['switch'] == getattr(self, '_last_switch', None):
            return True
        standby = ('Keep the calibrator in STANDBY while you turn the rotary switch.' if self.manual_cal
                   else 'The calibrator output is OFF (standby) while you turn the rotary switch.')
        facts = [('Next point', f'{p["n"]} of {len(self.points)}'), ('Test', describe(p)), ('Meter', p['switch'] + (f', range {p["range"]}' if p['range'] else ''))]
        if not port.operator_prompt('Change the function', p['section'],
                                    [('Rotary switch', f'Turn the meter to: {p["switch"]}'), ('Standby', standby)] + self._qsteps(),
                                    facts=self._qfacts(facts), ok='Done - continue', layout='function_change',
                                    card=function_change_card(p, len(self.points), standby + self._qnote()), parent=self.root):
            return False
        self._last_switch = p['switch']
        return True

    def _prompt_range(self, p):
        """'ok' / 'skip' / 'stop' - only for specs that ask for range selection (options.range_prompt)."""
        if not self.spec.get('options', {}).get('range_prompt') or not p.get('dial'):
            return 'ok'
        text = ('Put the calibrator in STANDBY while you turn the dial. The program sets the output after you continue.' if self.manual_cal
                else 'The calibrator output is OFF (standby) while you turn the dial. The program sets the output after you continue.')
        return ask_range(self.root, p, len(self.points), self.spec['dial'], text + self._qnote())

    def _rest_remaining(self, p):
        """Seconds the meter must still rest before a high-current point (0 when none is needed)."""
        rest = p.get('recovery_s')
        if not rest or self.last_high_current is None:
            return 0.0
        return max(0.0, rest - (time.monotonic() - self.last_high_current))

    def _next(self, points, i, previous):
        if (i >= len(points) or self.stop) and self._q is not None:
            self._queue_unit_done()                        # a run queue: this unit is finished, go on to the next one
            return
        if i >= len(points) or self.stop:
            self.busy = False
            self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.')
            return
        p = points[i]
        try:
            p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc:
            self._error(exc)
            return
        if p is None:                                                # skipped by an edit made during the run
            port.after(self.root, 30, lambda: self._next(points, i + 1, previous))
            return
        key = self._group_key(p)
        if self.ui_view.table_has(self, p['id']):
            self.ui_view.table_select(self, p['id'], see=True)
        if self._q is not None:
            self._queue_tick(p)
        if self.fast_demo:
            self._fast_demo_record(p)
            port.after(self.root, 20, lambda: self._next(points, i + 1, key))
            return
        if self.io:
            self.io.standby()
        wait = self._rest_remaining(p)
        if wait > 0:
            self.busy = False
            self.status.set(f'Paused: the meter must rest {wait / 60:.1f} more minutes after a high-current point.')
            port.message('info', 'Meter rest period', f'The meter manual requires 10 minutes of rest after measuring more than 6 A. '
                                                     f'Wait about {int(wait // 60)} min {int(wait % 60)} s, then press Run again.')
            return
        if key != previous:
            self._hv_ok_key = None                         # options.hv_once_per_group: a new hook-up group asks the high-voltage question again
        if key != previous and not self._prompt_setup(p):
            self.busy = False
            self.status.set('Paused for wiring or setup.')
            return
        if not self._prompt_function(p):
            self.busy = False
            self.status.set('Paused at the function change.')
            return
        choice = self._prompt_range(p)
        if choice == 'stop':
            self.busy = False
            self.status.set('Stopped at the range selection. Progress is saved.')
            self.save()
            return
        if choice == 'skip':
            port.after(self.root, 30, lambda: self._next(points, i + 1, key))
            return
        if self._stage['id'] != p['id']:
            self._stage = {'id': p['id'], 'done': set()}
        if p.get('prompt') and 'prompt' not in self._stage['done']:
            if not port.operator_prompt('Meter setup', p['section'], [('Meter', p['prompt'])] + self._qsteps(),
                                        facts=self._qfacts([('Point', f'{p["n"]} of {len(self.points)}'), ('Meter', p['switch'] + (f', range {p["range"]}' if p['range'] else ''))]),
                                        ok='Done - continue', parent=self.root):
                self.busy = False
                self.status.set('Paused at the meter setup.')
                return
            self._stage['done'].add('prompt')
        if p.get('rel_zero') and 'rel' not in self._stage['done']:
            self._rel_zero(points, i, p, key)
            return
        if self._high_voltage(p) and not self._q_hv_seen(p) and not self._hv_group_seen(key):
            if not port.ask_yes_no('HIGH VOLTAGE', self._q_hv_text(f'This point outputs {abs(p["applied"]["value"]):g} V'
                                       + (' (the voltage is ramped up in 50 V steps, 5 s apart)' if not self.manual_cal and not p.get('ramp') and self._auto_ramp() and abs(p['applied']['value']) > IO.RAMP_ABOVE else '') +
                                       '. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?')):
                self.busy = False
                self.status.set('Stopped before a high-voltage point.')
                return
            self._q_hv_note(p)
            if self.spec.get('options', {}).get('hv_once_per_group'):
                self._hv_ok_key = key
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

    def _rel_zero(self, points, i, p, key):
        """The table's REL offset: apply the zero input (or none), have the technician press REL, then continue with the point."""
        z = p['rel_zero']
        zero_point = dict(p, applied=dict(value=z['value'], frequency=None), ramp=None) if z.get('value') is not None else None

        def ask():
            if zero_point is not None and self.manual_cal:
                steps = [('Calibrator', f'Set {output_text(zero_point)} and press OPERATE.'), ('REL', z['text'])]
            else:
                steps = [('REL', z['text'])]
            ok = port.operator_prompt('Set the REL offset', f'{p["section"]}: REL offset',
                                      steps + self._qsteps(), facts=self._qfacts([('Point', f'{p["n"]} of {len(self.points)}'),
                                                    ('Calibrator output', output_text(zero_point) if zero_point else 'none (STANDBY)')]),
                                      caution='The program checks over IR that REL is on.' if self.use_ir else None, ok='REL set - continue', parent=self.root)
            if self.io and not self.manual_cal:
                self._safe_standby()
            if not ok:
                self.busy = False
                self.status.set('Paused at the REL offset.')
                return
            self._stage['done'].add('rel')
            port.after(self.root, 30, lambda: self._next(points, i, key))

        if zero_point is None or self.manual_cal or not self.io:
            ask()
            return
        self.status.set(f'Point {p["n"]}/{len(self.points)}: REL offset - setting the calibrator to {output_text(zero_point)} ...')
        state = {'done': False, 'exc': None}

        def work():
            try:
                self.io.apply(zero_point, cancel=lambda: self.stop)
            except BaseException as exc:
                state['exc'] = exc
                self._safe_standby()
            state['done'] = True

        def wait():
            if not state['done']:
                port.after(self.root, 40, wait)
            elif isinstance(state['exc'], Cancelled):
                self._ask_abort()
            elif state['exc'] is not None:
                self._error(state['exc'])
            else:
                ask()
        threading.Thread(target=work, daemon=True).start()
        wait()

    def _poll(self, points, i, p, key, state):
        """The worker thread only sets flags; every Tk call happens here on the main thread."""
        if not state['done']:
            port.after(self.root, 40, lambda: self._poll(points, i, p, key, state))
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
        port.message('error', 'Calibrator stopped', str(exc))

    def _out_note(self, p, on):
        if not p.get('applied'):
            return ''
        if self.manual_cal:
            return 'Set this on the calibrator and press OPERATE, then read the meter.'
        return OUTPUT_ON_NOTE + ' - allow the reading to settle, then read the meter.' if on else 'Output is in STANDBY.'

    def reading_labels(self, p):
        """Extra keyword arguments for ask_reading (a hook: user-built datasheets say 'oscilloscope' / 'measuring standard' instead of 'meter')."""
        return {}

    def _fill(self, p, yesno=False, sub=0):
        """Virtual bench only: {'demo_fill': callable} for the 'Fill with a simulated reading' button; {} in a real run, so its windows are unchanged."""
        if not self.virtual:
            return {}
        if yesno:
            return dict(demo_fill=lambda: virtualbench.plausible_answer(p['n'] + sub, self.virtual_failures()))
        return dict(demo_fill=lambda: virtualbench.plausible_text(p['low'], p['high'], p['n'], self.virtual_failures()))

    def _ask(self, points, i, p, key):
        if self._q_shared() and len(self._q.unit.needs.get(str(p['id']), self._q.unit.meters)) > 1:
            self._ask_shared(points, i, p, key)            # a run queue, several meters wired together: one window reads them all
            return
        total = len(self.points)
        if p['test'] == 'numeric' and self.use_ir and p.get('ir') and not self._stage.get('typed'):
            self._ask_ir(points, i, p, key)
            return
        self.status.set(f'Point {p["n"]}/{total}: waiting for the meter reading.')
        if p.get('ir_auto') == 'id' and self.use_ir and self.meter:
            try:
                idn = self.meter.identify()
            except Exception as exc:
                idn = f'no reply ({exc})'
            ok = idn.upper().startswith(f'FLUKE {self.model}')
            self._store(p, entered=f'ID: {idn}', reading=None, result='PASS' if ok else 'FAIL', source='IR')
            port.after(self.root, 30, lambda: self._next(points, i + 1, key))
            return
        if p['test'] == 'numeric':
            def validate(text):
                judge_numeric(p, text)
            limit = {}
            if p.get('max_on_s'):
                on_at = getattr(self.io, 'on_at', None) if self.io and not self.manual_cal else None
                used = (time.monotonic() - on_at) if on_at else 0.0
                limit = dict(limit_s=max(1.0, p['max_on_s'] - used), on_expire=self._safe_standby if self.io and not self.manual_cal else None)
            r = ask_reading(self.root, p, total, output_text(p), self._out_note(p, True), self.accept_text(p), 'numeric',
                            unit=p['display_unit'], annunciator=False, validate=validate, **limit, **self.reading_labels(p), **self._fill(p))     # the annunciator is a separate confirmation below
            if p.get('recovery_s'):
                self.last_high_current = time.monotonic()
            if r['action'] == 'record':
                entered = pad_reading(p, r['text'])
                ann = True
                if p.get('annunciator'):
                    ann = bool(port.ask_yes_no('AC annunciator', f'{describe(p)}\n\nIs the AC annunciator ON in the meter display?\n\n'
                                                   'Yes = it is on.  No = it is not (the point then fails).'))
                result, base = judge_numeric(p, entered, ann)
                self._store(p, entered=entered, reading=base, result=result, annunciator=ann if p.get('annunciator') else None,
                            source='typed')
        elif p.get('checks'):
            answers = []
            r = dict(action='record')
            for n, chk in enumerate(p['checks'], 1):
                if not chk['output'] and self.io and not self.manual_cal:
                    self.io.standby()
                note = self._out_note(p, chk['output']) if not self.manual_cal else ('Output ON.' if chk['output'] else 'Put the calibrator in STANDBY.')
                r = ask_reading(self.root, p, total, output_text(p), note, chk['question'], 'yesno', question=chk['question'], phase=f'check {n} of {len(p["checks"])}',
                                **self.reading_labels(p), **self._fill(p, True, n))
                if r['action'] != 'record':
                    break
                answers.append(r['yes'])
            if r['action'] == 'record':
                self._store(p, entered='Pass' if all(answers) else 'Fail', reading=None, result='PASS' if all(answers) else 'FAIL', answers=answers)
        else:
            r = ask_reading(self.root, p, total, output_text(p), self._out_note(p, True), p['question'], 'yesno', question=p['question'], **self.reading_labels(p), **self._fill(p, True))
            if r['action'] == 'record':
                ok = r['yes'] if p['test'] == 'visual' else (r['yes'])
                self._store(p, entered=('Pass' if ok else 'Fail') if p['test'] == 'visual' else
                            (f'Beeper {p["expect"]}' if ok else f'Beeper not {p["expect"]}'), reading=None, result='PASS' if ok else 'FAIL')
        if self.io and not self.manual_cal:
            self.io.standby()
        if r['action'] == 'stop':
            self.stop = True
        port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _ask_ir(self, points, i, p, key):
        """Read the point over IR on a worker thread; on a set-up problem put the calibrator in STANDBY and ask the technician."""
        total = len(self.points)
        self.status.set(f'Point {p["n"]}/{total}: reading the meter over IR (waiting for a stable reading) ...')
        state = {'done': False, 'exc': None, 'out': None}

        def work():
            try:
                state['out'] = ir_read(self.meter, p, cancel=lambda: self.stop, timeout=self.pm_param('handheld.ir_timeout', 45.0))
            except BaseException as exc:
                state['exc'] = exc
            state['done'] = True

        def wait():
            if not state['done']:
                port.after(self.root, 60, wait)
                return
            exc = state['exc']
            if exc is None:
                text, r, disp, history = state['out']
                result, base = judge_numeric(p, text)
                self._store(p, entered=text, reading=base, result=result, source='IR',
                            ir=dict(display=disp.summary(), unit=r.unit, last=[x.display_text() for x in history[-5:]]))
                if self.io and not self.manual_cal:
                    self._safe_standby()
                port.after(self.root, 30, lambda: self._next(points, i + 1, key))
                return
            if self.io and not self.manual_cal:
                self._safe_standby()
            if isinstance(exc, SetupProblem):
                problems, shown = exc.problems, exc.shown
            elif isinstance(exc, drivers.InstrumentError):
                problems, shown = [str(exc)], ''
            else:
                self._error(exc)
                return
            choice = ask_ir_problem(self.root, p, total, problems, shown)
            if choice == 'stop':
                self.busy = False
                self.status.set('Stopped. The calibrator is in STANDBY. Progress is saved.')
                self.save()
            elif choice == 'skip':
                port.after(self.root, 30, lambda: self._next(points, i + 1, key))
            elif choice == 'type':
                self._stage['typed'] = True
                self._reapply(points, i, p, key)
            else:
                self._reapply(points, i, p, key)

        threading.Thread(target=work, daemon=True).start()
        wait()

    def _reapply(self, points, i, p, key):
        """Set the output again (it was put in STANDBY while the meter was fixed) and go back to reading the point."""
        if p.get('applied') and self.io and not self.manual_cal:
            state = {'done': False, 'exc': None}

            def work():
                try:
                    self.io.apply(p, cancel=lambda: self.stop)
                except BaseException as exc:
                    state['exc'] = exc
                    self._safe_standby()
                state['done'] = True
            threading.Thread(target=work, daemon=True).start()
            self._poll(points, i, p, key, state)
        else:
            self._ask(points, i, p, key)

    def _safe_standby(self):
        try:
            self.io.standby()
        except Exception:
            pass

    def _store(self, p, **fields):
        fields.setdefault('synthetic', bool(self.demo))      # everything recorded in a demo (typed or filled) is synthetic
        fields['timestamp'] = datetime.now().isoformat(timespec='seconds')
        fields['data'] = self.mode_label
        fields.update(self.pm_result_fields())
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
    def _checkpoint_path(self, asset=None):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in (self.asset.get() if asset is None else asset)) or 'UNASSIGNED'
        return appdata.progress_path(f'{self.brand}{self.model}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        try:
            path.write_text(json.dumps(dict(model=self.model, asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        except OSError as exc:
            if not silent:
                self.status.set(f'Could not save progress: {exc}')
            return
        if not silent:
            self.status.set(f'Saved {path.name}')

    def checkpoint_problem(self, data):
        """A reason this progress file must not be loaded, or None (a hook: user-built datasheets check the datasheet and its version)."""
        return None

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path:
            return
        data = json.loads(Path(path).read_text())
        if data.get('model') != self.model:
            port.message('error', 'Wrong model', f'This checkpoint is for the Fluke {data.get("model")}.')
            return
        problem = self.checkpoint_problem(data)
        if problem:
            port.message('error', 'Wrong datasheet', problem)
            return
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'):
                return
        self.asset.set(data.get('asset', ''))
        self.serial.set(data.get('serial', ''))
        self.load_results(data)
        self.pm_on_checkpoint(data)                                     # a saved modification snapshot is used unless the store has changed
        self.queue_sync_after_load()                                    # a run queue keeps one result set per meter
        self.refresh()
        self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    # ------------------------------------------------------------------ report
    def certificate_row(self, p, r):
        """The report row of one recorded point (r = its record)."""
        import report_pdf
        failed = r['result'] == 'FAIL'
        if p['test'] == 'numeric':
            factor = Decimal(str(p['factor']))
            clean = lambda d: float(f'{float(d * factor):.9g}')
            unit = SYMBOL[p['base_unit']]
            unc = ''
            if self.has_uncertainty(p) and p.get('unc_kind') == 'FREQ':       # a frequency reading: the calibrator's own output-frequency spec (FREQ_UNCERTAINTY_FROM_CALIBRATOR); switched off, the Frequency - Measure CMC alone
                unc = report_pdf.point_uncertainty(dict(kind='FREQ', nominal=unc_frequency(p), frequency=None, unit='Hz', range=None,
                                                        use_standard=freq_from_calibrator()), standard=self.calibrator_model() if freq_from_calibrator() else None)
            elif self.has_uncertainty(p):
                unc = report_pdf.point_uncertainty(dict(kind='OHM2' if p['kind'] == 'OHM' else p['kind'], nominal=p['applied']['value'],
                                                        frequency=p['applied'].get('frequency'), unit=p.get('unc_unit') or p['base_unit'], range=None),
                                                        standard=self.calibrator_model())      # unc_unit (opt-in, Fluke 376 iFlex simulation): the source is volts, the reading is amps
            a = p.get('applied') or {}
            freq = a.get('frequency') if p['kind'] in ('ACV', 'ACI') and p['display_unit'] != 'kHz' and not p.get('no_freq_suffix') else None      # no_freq_suffix: opt-in per point (Fluke 170 series Hz-unit frequency rows)
            row = report_pdf.cert_row(f'{p["range"]} range' if p['range'] else describe(p), p['nominal'], clean(Decimal(p['low'])), clean(Decimal(p['high'])),
                                      unit, reading=r['reading'] if r['reading'] is not None else None, failed=failed, section=p['section'],
                                      frequency=freq, uncertainty=unc)
            if r['reading'] is None:           # overload
                row['As Found'] = r.get('entered', '')
            if p.get('annunciator') and r.get('annunciator') is not None:
                row['As Found'] += '  (AC annunciator ' + ('on' if r['annunciator'] else 'OFF') + ')'
            if p['kind'] == 'ACV' and p['display_unit'] == 'kHz':
                row['Description'] = f'{p["range"]} range (2 V applied)'
            if p.get('report_desc'):                   # a spec's own report wording (Fluke 77 IV: the 5 V applied at 50 kHz; the corrected step 8)
                row['Description'] = p['report_desc']
            if p['base_unit'] in TEMP_BASE_UNITS:      # temperatures are never SI-prefixed (no 'k°C')
                d = max(len(x.split('.')[1]) if '.' in x else 0 for x in (p['low'], p['high']))
                row.update({'Nominal': f'{p["nominal"]:.{d}f} {unit}', 'Tolerance -': p['low'], 'Tolerance +': p['high'], 'UOM': unit})
                if r['reading'] is not None:
                    row['As Found'] = r.get('entered', f'{r["reading"]:.{d}f}')
        else:
            unc = ''
            if p['test'] == 'beeper':
                unc = report_pdf.point_uncertainty(dict(kind='OHM2', nominal=p['applied']['value'], frequency=None, unit='ohm', range=None))
            row = {'Section': p['section'], 'Description': report_pdf.ascii_unit(describe(p)),
                   'Nominal': report_pdf.ascii_unit(output_text(p)) if p.get('applied') else '', 'Tolerance -': '', 'Tolerance +': '', 'UOM': '',
                   'As Found': r.get('entered', ''), 'OOT': 'OOT' if failed else '', 'As Left': 'Same', 'Uncertainty': unc}
        return row

    def certificate_rows(self):
        """As Found for every recorded point; As Left where it was measured again after an adjustment, else 'Same'."""
        return self.certificate_rows_and_points()[0]

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from (for the optional TAR / TUR fields)."""
        rows, pts = [], []
        for p in self.points:
            row = self.found_left_row(p, lambda r: self.certificate_row(p, r))
            if row:
                rows.append(row)
                pts.append(p)
        return rows, pts

    @staticmethod
    def has_uncertainty(p):
        """True for the points that carry an Uncertainty (and TAR / TUR): numeric DCV / ACV / DCI / ACI / OHM / CAP with a source, and the
        thermocouple-simulation TEMP points (degC only: a degF point has no degC calibrator specification, so it stays blank)."""
        if p.get('unc_kind') == 'FREQ' and unc_frequency(p) is not None and not p.get('no_uncertainty'):
            return True                   # a frequency reading carries an uncertainty (calibrator's frequency spec, or the CMC alone when the switch is off): no applied source needed (a hand-set calibrator point)
        if not p.get('applied') or p.get('no_uncertainty'):
            return False
        if p['kind'] == 'TEMP':
            return p.get('base_unit') in ('C', 'degC')
        return p['kind'] in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP')

    def certificate_fields(self, p):
        """Optional TAR / TUR fields of one point, from the same point, limits and calibrator model as its Uncertainty cell.
        Only points that carry an uncertainty today (numeric DCV / ACV / DCI / ACI / OHM / CAP with a source) get ratios; all others stay blank."""
        blank = dict(TAR='', TUR='')
        try:
            if not (p['test'] == 'numeric' and self.has_uncertainty(p)):
                return blank
            import tartur
            factor = Decimal(str(p['factor']))
            clean = lambda d: float(f'{float(d * factor):.9g}')
            if p.get('unc_kind') == 'FREQ':            # frequency reading: switch on, the calibrator's frequency spec (TAR and TUR as any point); switch off, the CMC alone (TAR blank)
                q = dict(kind='FREQ', nominal=unc_frequency(p), frequency=None, unit='Hz', range=None, use_standard=freq_from_calibrator())
            else:
                q = dict(kind='OHM2' if p['kind'] == 'OHM' else p['kind'], nominal=p['applied']['value'],
                         frequency=p['applied'].get('frequency'), unit=p['base_unit'], range=None)
            fields = tartur.row_fields(q, clean(Decimal(p['low'])), clean(Decimal(p['high'])), standard=self.calibrator_model())
            if p.get('unc_kind') == 'FREQ' and not freq_from_calibrator():
                fields = tartur.row_fields(q, clean(Decimal(p['low'])), clean(Decimal(p['high'])), standard=None)
            return fields
        except Exception:
            return blank

    def export_pdf(self):
        if self.queue_offer_all_reports():                  # a run queue: one report per meter (run_queue_engine.py)
            return
        rows, pts = self.certificate_rows_and_points()
        if not rows:
            port.message('info', 'No results', 'No recorded results to export yet.')
            return
        try:
            import report_pdf
        except ImportError as exc:
            port.message('error', 'Report export', str(exc))
            return
        details = port.report_details(f'{self.info["name"]} performance verification', parent=self.root)
        if details is None:
            return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path:
            return
        demo = self.any_synthetic()
        src = self.spec['source']
        details = self.report_details(details)
        try:
            if details.get('show_tar_tur'):
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'), [self.certificate_fields(p) for p in pts])
            report_pdf.write_calibration_pdf(path, rows, header=self.report_header(src),
                                             title=self.report_title(), demo=demo, details=details,
                                             footer_note=' '.join(x for x in (report_pdf.uncertainty_note(rows, self.calibrator_model()), self.temperature_note(), self.source_note()) if x),
                                             snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab')
            return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc))
            return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def report_title(self):
        """options.report_title (the Fluke 77 IV spec: 'Calibration Data') or, as always before, '<model> Performance Verification'."""
        return self.spec.get('options', {}).get('report_title') or f'{self.info["name"]} Performance Verification'

    def report_header(self, src):
        return [('Instrument', self.info['name']), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                ('Limits applied', src.get('limits', 'Manufacturer display-reading limits (12 month)')),
                ('Source', src.get('cite') or f'{src["document"]}, pp. {src["pages"].split(" ")[0]}')]

    def report_details(self, details):
        """The report-details dict (a hook: user-built datasheets add the standards that were actually used)."""
        return details

    def calibrator_model(self):
        """Model of the calibrator in use ('5560A' / '5522A' / '5520A'), for the uncertainty budget."""
        text = self.cal_mode.get()
        return '5522A' if '5522A' in text else '5520A' if '5520A' in text else '5560A' if '5560A' in text else None

    def temperature_note(self):
        """Footer text (kept with the issued report; the PDF itself does not print the footer) for the thermocouple-simulation points, or '' when the run
        has none.  Says where the temperature uncertainty comes from and what it leaves out."""
        cal = self.calibrator_model()
        if not cal or not any(self.has_uncertainty(p) and p['kind'] == 'TEMP' for p in self.points):
            return ''
        return (f'Temperature points: the uncertainty is the published 1-year Type K thermocouple-simulation specification of the {cal} calibrator, in degC '
                '(accuracy divided by the coverage divisor, with the calibrator resolution where known), k = 2. The scope of accreditation '
                'Type K thermocouple line (A2LA 1888.03 printed p. 13) is the CMC floor. It does not include the Fluke 80AK adapter, the thermocouple or reference-junction effects at the meter. '
                'A temperature outside the calibrator\'s specified Type K range shows no uncertainty or ratio.')

    def source_note(self):
        """How the numeric readings were collected (IR and / or typed), for the report footer; plus the spec's own source.report_note
        (the Fluke 77 IV spec states there which printed limit was corrected)."""
        note = self.spec.get('source', {}).get('report_note', '')
        if not self.ir:
            return note
        every = list(self.all_records())
        ir = sum(1 for r in every if r.get('source') == 'IR' and r.get('reading', 0) is not None)
        typed = sum(1 for r in every if r.get('source') == 'typed')
        if not (ir or typed):
            return note
        parts = ([f'{ir} reading(s) read from the meter over its IR interface, with the function, range and REL / Low Pass state checked'] if ir else []) + \
                ([f'{typed} typed in by the technician from the display'] if typed else [])
        return ' '.join(x for x in (note, 'Meter readings: ' + '; '.join(parts) + '.') if x)

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'):
            return
        self.stop = True
        self._save_settings()
        self.disconnect()
        port.close(self.root)


def main(model, argv=None, spec=None):
    """spec: a spec file name inside specs/ (or a path); the Fluke 110-series spec when omitted."""
    argv = sys.argv if argv is None else argv

    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, model, demo=demo, spec=load_spec(spec) if spec else None, fast_demo=fast)
    port.run_app(build)
