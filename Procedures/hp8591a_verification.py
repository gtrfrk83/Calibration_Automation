"""HP 8591A spectrum analyzer performance verification (USAF T.O. 33K3-4-2864-1, 30 May 2012), two-way automated.

Test points and limits are NOT written in this file: they are loaded from specs/hp_8591a_pv.json (built by specs/build_hp_8591a_spec.py from the RENDERED pages of the T.O.). A point is good when
LOW <= reading <= HIGH (HIGH exclusive for the document's "<" limits), judged in Decimal. The document names a sweeper, power meter, counter, synthesizer, step attenuators and signal / function
generators; this bench replaces all of them with the Fluke 96270A (leveled sine, internal AM, power-meter mode with an R&S NRP40T), each replacement flagged UNVERIFIED on the point.

Bench (GPIB): the 8591A (unit under test) and the 96270A. Both addresses are editable boxes saved with the settings. The program resets both instruments to their defaults before the first
point, pauses for the hook-up whenever the wiring changes, switches the 96270A output off (read back) after every point and at the end or abort, and never runs unattended. There is no
adjustment here and no calibration command is ever sent to the analyzer: the self-calibration of 3.3 is a prompt you carry out from the front panel. The CAL OUT frequency count and the displayed
average noise level are typed readings. Hardware I/O is OFF in demo mode, and a demo run records only marked synthetic data.

Typed readings ('Enter reading manually') are judged by the same limit logic as automatic ones.

    import hp8591a_verification
    hp8591a_verification.main()      # what Procedures/HP_8591A_Verification.py does
"""
import json, math, sys, threading, time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

OWN_DIR = Path(__file__).resolve().parent         # Procedures/ (this engine and its window code travel with the procedure, so a package can update them)
HERE = OWN_DIR.parent                              # the suite folder: ui_theme, procspec, drivers, specs and diagrams sit there
for _d in (str(HERE), str(OWN_DIR)):
    if _d not in sys.path:
        sys.path.append(_d)
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (report_filename, Settings); the window code is in hp8591a_view_qt.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import appdata
import datamode
import procmods_engine
import reset_startup
import procspec
import drivers
import manual_override
from drivers.base import InstrumentError, SafetyError
from drivers.gpib_address import address_of, check_address

MODEL = '8591A'
SPEC_PATH = HERE / 'specs' / 'hp_8591a_pv.json'
STATE_KEY = MODEL
VARIANT_LABEL = ''
SPEC: dict[str, Any] = {}           # set by configure()
POINTS: list[dict[str, Any]] = []
UUT_ADDRESS = drivers.HP8591A.DEFAULT_ADDRESS            # UNVERIFIED example; the box is editable and saved with the settings
DEFAULT_RF_ADDR = 'GPIB0::4::INSTR'                      # the 96270A: the same default as the other engines (UNVERIFIED example)
MEAS = ('selfcal', 'calout_pm', 'calout_ctr', 'manual', 'freq_marker', 'noise_sb', 'span_cal', 'sweep_time', 'scale_log', 'scale_lin', 'atten', 'reflevel', 'rbw_switch', 'rbw_bw', 'freq_resp', 'derived')
SRC_KINDS = ('freq_marker', 'noise_sb', 'span_cal', 'sweep_time', 'scale_log', 'scale_lin', 'atten', 'reflevel', 'rbw_bw', 'freq_resp')       # the points that need the 96270A as the signal source
GROUP_TITLE = {'SELFCAL': 'Self-calibration of the 8591A (front panel)', 'CALPM': '8591A CAL OUT to the NRP40T sensor on the 96270A', 'CALCTR': '8591A CAL OUT to a frequency counter (typed)',
               'SRC': '96270A RF OUTPUT to the 8591A INPUT', 'CALIN': '8591A CAL OUT to the 8591A INPUT', 'DANL': '50 ohm termination on the 8591A INPUT (typed)'}
WARM_UP = ('The 8591A needs 30 minutes of warm-up before its self-calibration routines (3.3), and the 96270A should be on long enough to be stable. The program does not wait for it.')
RB_LIST = (1e3, 3e3, 10e3, 30e3, 100e3, 300e3, 1e6, 3e6)
MEAS_TIMEOUT_S = 60.0


class SpecError(procspec.SpecError):
    pass


def load_spec(path=None):
    """Read and check the spec (kind 'spectrum-analyzer-pv'): every point has a measurement kind, a group, limits that contain the nominal and the settings its kind needs."""
    spec = json.loads(Path(path or SPEC_PATH).read_text(encoding='utf-8'))
    if spec.get('kind') != 'spectrum-analyzer-pv' or spec.get('model') != MODEL:
        raise SpecError("not a 'spectrum-analyzer-pv' spec for the 8591A")
    refs = set()
    for s in spec['sections']:
        for p in s['points']:
            where = f"{s['id']} point {p.get('ref', '?')}"
            if p['ref'] in refs:
                raise SpecError(f'{where}: duplicate ref')
            refs.add(p['ref'])
            if p['meas'] not in MEAS:
                raise SpecError(f'{where}: unknown measurement {p["meas"]!r}')
            if p['group'] not in GROUP_TITLE:
                raise SpecError(f'{where}: unknown group {p["group"]!r}')
            if not isinstance(p['low'], (int, float)) or not isinstance(p['high'], (int, float)) or p['low'] > p['high']:
                raise SpecError(f'{where}: low must not be above high')
            if not p['low'] <= p['nominal'] <= p['high']:
                raise SpecError(f'{where}: limits do not contain the nominal')
            if p['meas'] in SRC_KINDS and 'src' not in p:
                raise SpecError(f'{where}: a measured point needs a source (96270A) setting')
            if p['meas'] == 'sweep_time' and 'am' not in p:
                raise SpecError(f'{where}: a sweep-time point needs an AM setting')
            if p['meas'] == 'calout_ctr' and p.get('opt') not in ('std', '004'):
                raise SpecError(f'{where}: a counter point needs opt std or 004')
    for s in spec['sections']:
        for p in s['points']:
            if p['meas'] == 'derived' and not all(r in refs for r in p['derive']['inputs']):
                raise SpecError(f'{s["id"]} point {p["ref"]}: derived from a point that does not exist')
    return spec


def flatten(spec):
    """One flat, numbered list of points (ids start at 1) in the spec's run order."""
    points = []
    for s in spec['sections']:
        for raw in s['points']:
            p = json.loads(json.dumps(raw))                       # a private copy: option handling and modifications patch it
            p.update(id=len(points) + 1, section=s['id'], section_title=s['title'], section_page=s['page'], setup=s['setup'], optional=False)
            p['error'] = float(f"{max(p['nominal'] - p['low'], p['high'] - p['nominal']):.9g}")
            p['unavailable'] = ''
            p['not_tested'] = False
            p['_base'] = dict(nominal=p['nominal'], low=p['low'], high=p['high'], description=p['description'])
            points.append(p)
    return points


def configure(model=MODEL):
    """Load the spec and number the points (the one model of this engine)."""
    global SPEC, POINTS
    SPEC = load_spec()
    POINTS = flatten(SPEC)
    apply_options(POINTS, False)


def apply_options(points, opt004):
    """What depends on the settings: the CAL OUT frequency point of the other reference option is left out, and a sweep-time row whose modulation rate the 96270A internal AM cannot make
    (below its minimum) is NOT run and is listed on the report as not tested (p['not_tested'] True). Sets p['unavailable'] (a reason) or ''."""
    for p in points:
        base = p['_base']
        p['nominal'], p['low'], p['high'], p['description'] = base['nominal'], base['low'], base['high'], base['description']
        p['unavailable'] = ''
        p['not_tested'] = False
        if p['meas'] == 'calout_ctr' and p['opt'] != ('004' if opt004 else 'std'):
            p['unavailable'] = 'the other frequency-reference option (see the settings)'
        if p['meas'] == 'sweep_time' and p['am']['rate_hz'] < drivers.reference_instruments.AM_RATE_MIN_HZ - 1e-12:
            p['not_tested'] = True
            p['unavailable'] = (f'not tested: the {p["am"]["rate_hz"]:g} Hz modulation is below the {drivers.reference_instruments.AM_RATE_MIN_HZ:g} Hz minimum of the 96270A internal AM (Operator Manual)')
        p['error'] = float(f"{max(p['nominal'] - p['low'], p['high'] - p['nominal']):.9g}")


def prompt_key(p):
    """What decides whether the hook-up prompt is shown again: the wiring group."""
    return p['group']


class ReadingUnavailable(InstrumentError):
    """The automatic reading of a point failed (timeout, unreadable, no instrument connected). Same message as the error it wraps; the App offers a typed reading (manual_override)."""


class TypedPoint:
    """IO.measure's answer for a point that has no automatic reading (CAL OUT counter, displayed average noise level): the App asks for the number and then calls IO.standby()."""

    def __init__(self, reason):
        self.reason = reason


def judge(p, reading):
    """True when LOW <= reading <= HIGH, in Decimal (a reading exactly on a limit passes; a point with strict_high needs reading < HIGH, the document's "<" limits)."""
    value = Decimal(repr(float(reading)))
    low, high = Decimal(repr(float(p['low']))), Decimal(repr(float(p['high'])))
    if value < low:
        return False
    return value < high if p.get('strict_high') else value <= high


def derived_value(p, readings):
    """The value of a derived point (4.11.31: the most positive, the most negative and the range of the frequency-response readings), in Decimal. None when an input has no reading yet."""
    d = p['derive']
    if any(r not in readings for r in d['inputs']):
        return None
    m = [Decimal(repr(float(readings[r]))) for r in d['inputs']]
    if d['op'] == 'max':
        out = max(m)
    elif d['op'] == 'min':
        out = min(m)
    else:
        out = max(m) - min(m)
    return float(f'{float(out):.9g}')


def find_diagram(group):
    """Hook-up picture for a wiring group: diagrams/hook_8591A_<GROUP>.png (supplied by the owner; none is drawn here)."""
    path = HERE / 'diagrams' / f'hook_{MODEL}_{group}.png'
    return path if path.exists() else None


def to_visa(text):
    """'2' -> 'GPIB0::2::INSTR'; a full VISA resource passes through."""
    t = str(text).strip()
    if '::' in t or t.upper().startswith(('GPIB', 'USB', 'TCPIP', 'ASRL')):
        return t
    if t.isdigit() and 0 <= int(t) <= 30:
        return f'GPIB0::{int(t)}::INSTR'
    raise ValueError('Enter a GPIB address (0 to 30) or a full VISA resource such as GPIB0::14::INSTR.')


def gpib_number(text, what):
    """The GPIB primary address (0..30) in an address box; raises InstrumentError for anything else (the 8591A is GPIB only)."""
    n = address_of(to_visa(text))
    if n is None:
        raise InstrumentError(f'The {what} address must be a GPIB address (0 to 30 or GPIB0::n::INSTR), not {str(text).strip()!r}')
    return check_address(n)


# ---- reading the 401-point trace (pure functions; the measurement methods use them) --------------------------------------------------------------------------
def auto_rb(span_hz):
    """The widest resolution bandwidth of the 8591A that is at most span / 50 (at least 1 kHz): a peak then covers several of the 401 trace points."""
    want = max(float(span_hz) / 50.0, RB_LIST[0])
    return max(r for r in RB_LIST if r <= want + 1e-9)


def peak_position(trace):
    """The trace position (0 .. 400, fractional) of the highest point, refined by a parabola through it and its neighbours (exact for a Gaussian response in dB)."""
    i = max(range(len(trace)), key=trace.__getitem__)
    if 0 < i < len(trace) - 1:
        a, b, c = trace[i - 1], trace[i], trace[i + 1]
        den = a - 2.0 * b + c
        if den != 0:
            return i + 0.5 * (a - c) / den
    return float(i)


def width_at(trace, drop_db=3.0):
    """The width (trace points) of the response where it is `drop_db` below its peak: linear interpolation of the two crossings. InstrumentError when a crossing is off the trace."""
    i = max(range(len(trace)), key=trace.__getitem__)
    thr = trace[i] - drop_db
    j = i
    while j > 0 and trace[j] >= thr:
        j -= 1
    if trace[j] >= thr:
        raise InstrumentError('the response does not fall by 3 dB on the left side of the trace')
    left = j + (thr - trace[j]) / (trace[j + 1] - trace[j])
    k = i
    while k < len(trace) - 1 and trace[k] >= thr:
        k += 1
    if trace[k] >= thr:
        raise InstrumentError('the response does not fall by 3 dB on the right side of the trace')
    right = k - 1 + (trace[k - 1] - thr) / (trace[k - 1] - trace[k])
    return right - left


def eight_period_time_s(trace, sweep_s, periods=8):
    """The time of `periods` modulation periods in a zero-span sweep: the rising crossings of the mid level (halfway between the lowest and the highest trace value) give the mean period in
    trace points; one point is sweep_s / 400. InstrumentError when there is no modulation to see or fewer than three crossings."""
    lo, hi = min(trace), max(trace)
    if hi - lo < 6.0:
        raise InstrumentError(f'no modulation seen in the zero-span trace (swing {hi - lo:.1f} dB)')
    thr = (lo + hi) / 2.0
    cross = []
    for i in range(len(trace) - 1):
        a, b = trace[i], trace[i + 1]
        if a < thr <= b:
            cross.append(i + (thr - a) / (b - a))
    if len(cross) < 3:
        raise InstrumentError(f'only {len(cross)} rising crossing(s) in the zero-span trace; at least 3 are needed')
    period_pts = (cross[-1] - cross[0]) / (len(cross) - 1)
    return periods * period_pts * float(sweep_s) / (len(trace) - 1)


# Settle times after the source output is switched ON, before the first reading: ENGINEERING ESTIMATES, NOT from a manual. Tune them on the bench (procedure modifications 'hp8591a.settle.*').
DEFAULT_SETTLE_S = 0.5
PM_SETTLE_S = 1.0
AM_SETTLE_S = 1.0


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the 8591A and the 96270A, both through the instrument drivers. An empty 96270A address box means no source is connected: a point that needs it offers a typed reading."""

    def __init__(self, addrs, transports=None, mods=None):
        self.log = drivers.CommandLog()
        self.uut: drivers.HP8591A = cast(Any, None)
        self.src: Any = None
        self._reset_state()
        tr = dict(transports or {})
        try:
            if 'uut' not in tr:
                gpib_number(addrs['uut'], '8591A')
                tr['uut'] = drivers.open_visa(to_visa(addrs['uut']), timeout=20)
            self.uut = drivers.HP8591A(tr['uut'], self.log, label='8591A', address=gpib_number(addrs['uut'], '8591A') if not transports else None)
            self.uut.connect()
            text = str(addrs.get('src', '')).strip()
            if 'src' in tr or text:
                if 'src' not in tr:
                    tr['src'] = drivers.open_visa(to_visa(text), timeout=20)
                self.src = drivers.Fluke96270A(tr['src'], self.log, label='96270A')
                self.src.connect()
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.uut.idn

    def _reset_state(self):
        """What the program remembers about the instruments; forgotten at every reset (the reset puts them back to defaults)."""
        self._src_mode = 'SINE'          # SINE, AM or PM (power meter): what the 96270A is selected as
        self._src_on = False
        self._pm_sel = False

    def reset_roles(self):
        return [x for x in (self.src,) if x is not None], [self.uut]

    def reset_at_start(self, confirm=None):
        report = super().reset_at_start(confirm)
        self._reset_state()
        return report

    def pm_drivers(self):
        return tuple(x for x in (self.uut, self.src) if x is not None)

    def standby(self):
        """The end of every point (and of an abort): the 96270A output OFF, read back (SafetyError when it is not off), and the source back to the leveled sine after AM. The analyzer has no output."""
        if self.src is None or not self._src_on:
            return
        self._src_on = False
        self.src.output(False)
        if self._src_mode == 'AM':
            self.src.select_sine()
            self._src_mode = 'SINE'

    def close(self):
        try: self.standby()
        except Exception: pass
        for obj in (self.src, self.uut):
            if obj is None:
                continue
            try: obj.cleanup()
            except Exception: pass
        for obj in (self.src, self.uut):
            if obj is None:
                continue
            try: obj.close()
            except Exception: pass
        self.save_log()

    _logged = 0          # log lines already appended to the shared log

    def save_log(self):
        """Append the exact commands sent (not yet saved) to ~/.calibration_suite/command_log.txt."""
        lines = self.log.lines()
        new = lines[self._logged:]
        if not new:
            return
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  HP {MODEL} session\n' + '\n'.join(new) + '\n')
            self._logged = len(lines)
        except OSError:
            pass

    # ---- the power-meter zero (prompted by the App before the sensor is connected to CAL OUT) -----------------------------------------------------
    def prep_pm_zero(self):
        """The NRP40T on the 96270A in power-meter mode, zeroed with nothing connected to the sensor (UNVERIFIED sensor). The zero is asked once and never retried."""
        src = self._need('src', '96270A')
        src.select_power_meter(frequency_hz=300e6)
        self._src_mode, self._pm_sel = 'PM', True
        src.zero()

    # ---- one point ---------------------------------------------------------------------------------------------------------------------------------
    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        if p['meas'] == 'calout_pm': return self.pm_param('hp8591a.settle.pm', PM_SETTLE_S)
        if p['meas'] == 'sweep_time': return self.pm_param('hp8591a.settle.am', AM_SETTLE_S)
        return self.pm_param('hp8591a.settle.default', DEFAULT_SETTLE_S)

    def _need(self, name, what):
        inst = getattr(self, name)
        if inst is None:
            raise ReadingUnavailable(f'No {what} is connected (its address box is empty): type the reading from your own instrument.')
        return inst

    def after_read_failure(self, p, exc):
        """After a failed automatic reading: the output off (already done by measure), the failure logged; the run can go on with a typed reading."""
        self.log.add('!!', f'reading failed ({exc}); a manually entered reading may replace it', MODEL)

    @procmods_engine.point_commands()
    def measure(self, p):
        """Set the analyzer and the source (every write read back), output ON, settle, read; output OFF (confirmed) afterwards, also when anything fails. A typed point returns a TypedPoint."""
        try:
            value = self._measure(p)
        except BaseException:
            try:
                self.standby()
            except SafetyError:
                raise
            except Exception as exc:
                self.log.add('!!', f'could not confirm standby after a failed point: {exc}', MODEL)
            raise
        if not isinstance(value, TypedPoint):
            self.standby()
        return value

    def _measure(self, p):
        kind = p['meas']
        if kind in ('derived', 'selfcal'):
            raise InstrumentError(f'{p["ref"]} is not measured by the instruments')
        if kind in ('manual', 'calout_ctr'):                       # the reading comes from the technician's own instrument (nothing is programmed)
            return TypedPoint(p.get('manual_prompt') or 'Read your instrument and type the value.')
        if kind in SRC_KINDS:
            self._need('src', '96270A')
        try:
            value = getattr(self, '_m_' + kind)(p)
            self.uut.check_errors(p['ref'])
            return value
        except (SafetyError, ReadingUnavailable):
            raise
        except Exception as exc:                                   # a timeout, a setting the analyzer did not accept, an unreadable trace: a typed reading may replace it
            raise ReadingUnavailable(str(exc)) from exc

    # ---- building blocks -----------------------------------------------------------------------------------------------------------------------------
    def _tune(self, cf=None, span=None, rb=None, vb=None, rl=None, at=None, log_db='keep'):
        """Analyzer settings, each read back. rb / vb default to the widest bandwidth that fits the span; log_db None is linear."""
        u = self.uut
        if cf is not None: u.set_center_hz(cf)
        if span is not None: u.set_span_hz(span)
        if rb is None and span is not None: rb = auto_rb(span)
        if rb is not None: u.set_rbw_hz(rb)
        if vb is None and rb is not None: vb = rb
        if vb is not None: u.set_vbw_hz(vb)
        if rl is not None: u.set_reference_level_dbm(rl)
        if at is not None: u.set_attenuation_db(at)
        if log_db != 'keep': u.set_scale(log_db)

    def _sweep(self):
        self.uut.single_sweep()
        self.uut.take_sweep()

    def _amp(self):
        """One sweep, then the amplitude of the highest peak (AUNITS units)."""
        self._sweep()
        return self.uut.marker_to_peak()[1]

    def _src_set(self, freq_hz, level_dbm):
        """The 96270A as the leveled sine at this frequency and level, read back. The output is not touched."""
        if self._src_mode != 'SINE':
            self.src.select_sine()
            self._src_mode, self._pm_sel = 'SINE', False
        self.src.set_rf(freq_hz, level_dbm)

    def _src_out(self, p):
        self.src.output(True)
        self._src_on = True
        time.sleep(self.settle(p))

    # ---- the measurements ----------------------------------------------------------------------------------------------------------------------------
    def _m_calout_pm(self, p):
        """4.1: the CAL OUT level with the NRP40T on the 96270A (zeroed before it was connected)."""
        src = self._need('src', '96270A')
        if not self._pm_sel:
            src.select_power_meter(frequency_hz=p['pm']['freq_hz'])
            self._src_mode, self._pm_sel = 'PM', True
        time.sleep(self.settle(p))
        return src.read_dbm()

    def _m_freq_marker(self, p):
        """4.2: the marker frequency of a 1.5 GHz signal at the span of the row."""
        s, t = p['src'], p['ti']
        self.uut.preset()
        self._src_set(s['freq_hz'], s['level_dbm'])
        self._tune(cf=t['cf_hz'], span=t['span_hz'], rl=0.0)
        self._src_out(p)
        self._sweep()
        return self.uut.marker_to_peak()[0]

    def _m_noise_sb(self, p):
        """4.3: the carrier peak is found at 10 MHz span, then 200 kHz span / 1 kHz RBW / 30 Hz VBW; the delta marker at the offset gives dBc."""
        s, t = p['src'], p['ti']
        self.uut.preset()
        self._src_set(s['freq_hz'], s['level_dbm'])
        self._tune(cf=s['freq_hz'], span=10e6, rl=0.0)
        self._src_out(p)
        self._sweep()
        hz = self.uut.marker_to_peak()[0]
        self._tune(cf=hz, span=200e3, rb=1e3, vb=30.0)
        self._sweep()
        hz = self.uut.marker_to_peak()[0]
        return self.uut.delta_at(hz + t['offset_hz'])

    def _m_span_cal(self, p):
        """Table 2: the signal is put at the frequency of graticule position 40 and 360 (cf -/+ 0.4 span); the peak positions on the trace give the source difference that would be 320 points apart."""
        s, t = p['src'], p['ti']
        span = t['span_hz']
        f1, f2 = t['cf_hz'] - 0.4 * span, t['cf_hz'] + 0.4 * span
        self.uut.preset()
        self._src_set(f1, s['level_dbm'])
        self._tune(cf=t['cf_hz'], span=span, rl=0.0)
        self._src_out(p)
        self._sweep()
        i1 = peak_position(self.uut.read_trace())
        self.src.set_rf(f2, s['level_dbm'])
        time.sleep(self.settle(p))
        self._sweep()
        i2 = peak_position(self.uut.read_trace())
        if i2 - i1 < 100:
            raise InstrumentError(f'the two peak positions ({i1:.1f} and {i2:.1f}) are too close for a span measurement')
        return (f2 - f1) * 320.0 / (i2 - i1)

    def _m_sweep_time(self, p):
        """Table 3: zero span at 500 MHz with the 96270A internal AM; the time of 8 modulation periods from the 401-point trace."""
        a, t = p['am'], p['ti']
        self.uut.preset()
        self.src.setup_am(p['src']['freq_hz'], p['src']['level_dbm'], a['depth_pct'], a['rate_hz'], a['shape'])
        self._src_mode, self._pm_sel = 'AM', False
        self._tune(cf=p['src']['freq_hz'], span=0.0, rb=3e6, vb=3e6, rl=0.0)
        self.uut.set_sweep_time_s(t['st_s'])
        self._src_out(p)
        self._sweep()
        return eight_period_time_s(self.uut.read_trace(), self.uut.sweep_time_s())

    def _m_scale_log(self, p):
        """Tables 4 and 5: the marker amplitude change when the source is lowered from the reference level (0 dBm at the analyzer input) by the step."""
        s, sc, t = p['src'], p['scale'], p['ti']
        self.uut.preset()
        self._src_set(s['freq_hz'], sc['ref_dbm'])
        self._tune(cf=t['cf_hz'], span=50e3, rb=3e3, vb=30.0, rl=0.0)
        self._src_out(p)
        a0 = self._amp()
        self.src.set_rf(s['freq_hz'], sc['ref_dbm'] + sc['step_db'])
        time.sleep(self.settle(p))
        a1 = self._amp()
        return a1 - a0

    def _m_scale_lin(self, p):
        """Table 6: linear scale in volts. The reference is trimmed to 223.6 mV +/-0.4 mV (the source level is read back each time), then lowered by the step; the marker voltage is the reading."""
        s, sc, t = p['src'], p['scale'], p['ti']
        target, tol = sc['ref_v'], 0.0004
        self.uut.preset()
        self._tune(cf=t['cf_hz'], span=50e3, rb=3e3, vb=30.0, rl=0.0, log_db=None)      # the reference level is set in dBm, before the units change (RL? then answers in volts)
        self.uut.set_units('V')
        level = sc['ref_dbm']
        self._src_set(s['freq_hz'], level)
        self._src_out(p)
        trimmed = False
        for _ in range(5):
            v = self._amp()
            if abs(v - target) <= tol:
                trimmed = True
                break
            if v <= 0:
                raise InstrumentError('no signal at the linear-scale reference')
            level += 20.0 * math.log10(target / v)
            self.src.set_rf(s['freq_hz'], level)
            time.sleep(self.settle(p))
        if not trimmed:
            raise InstrumentError(f'the reference could not be set to {target * 1e3:.1f} mV +/-0.4 mV (last reading {v * 1e3:.2f} mV)')
        self.src.set_rf(s['freq_hz'], level + sc['step_db'])
        time.sleep(self.settle(p))
        return self._amp()

    def _step_pair(self, p, cf, tune_ref, tune_row):
        """Reference sweep and row sweep of a level / attenuation / reference-level point: the marker change minus the source change (0 for a perfect analyzer)."""
        s = p['src']
        self.uut.preset()
        self._src_set(cf, s['ref_level_dbm'])
        self._tune(cf=cf, **tune_ref)
        self._src_out(p)
        a0 = self._amp()
        tune_row()
        self.src.set_rf(cf, s['level_dbm'])
        time.sleep(self.settle(p))
        a1 = self._amp()
        return (a1 - a0) - (s['level_dbm'] - s['ref_level_dbm'])

    def _m_atten(self, p):
        """Table 7: reference level and input attenuation change together with the source level; the displayed level should not change."""
        t = p['ti']
        return self._step_pair(p, t['cf_hz'], dict(span=100e3, rb=10e3, vb=100.0, rl=t['ref_rl_dbm'], at=t['ref_at_db'], log_db=1),
                               lambda: self._tune(rl=t['rl_dbm'], at=t['at_db']))

    def _m_reflevel(self, p):
        """Table 8: the reference level changes together with the source level; the displayed level should not change."""
        t = p['ti']
        return self._step_pair(p, t['cf_hz'], dict(span=50e3, rb=3e3, vb=30.0, rl=t['ref_rl_dbm'], log_db=1), lambda: self._tune(rl=t['rl_dbm']))

    def _m_rbw_switch(self, p):
        """Table 9: CAL OUT (300 MHz, -20 dBm) on the INPUT; the peak amplitude at the row's bandwidth minus that at 3 kHz / 50 kHz span."""
        t = p['ti']
        self.uut.preset()
        self._tune(cf=t['cf_hz'], span=t['ref_span_hz'], rb=t['ref_rb_hz'], vb=1e3, rl=-20.0, log_db=1)
        a0 = self._amp()
        self._tune(span=t['span_hz'], rb=t['rb_hz'])
        return self._amp() - a0

    def _m_rbw_bw(self, p):
        """Table 10: the -3 dB width of the resolution filter from the 401-point trace (span 6 x RBW, VBW = RBW / 10, at least 30 Hz). Shown at 2 dB/division and +5 dBm so both -3 dB points are on screen."""
        s, t = p['src'], p['ti']
        rb = t['rb_hz']
        vb = max(30.0, rb / 10.0)
        self.uut.preset()
        self._src_set(s['freq_hz'], s['level_dbm'])
        self._tune(cf=t['cf_hz'], span=20.0 * rb, rb=rb, vb=vb, rl=5.0, log_db=2)
        self._src_out(p)
        self._sweep()
        hz = self.uut.marker_to_peak()[0]
        span = 6.0 * rb
        self._tune(cf=hz, span=span, rb=rb, vb=vb)
        self._sweep()
        trace = self.uut.read_trace()
        return width_at(trace, 3.0) * span / (len(trace) - 1)

    def _m_freq_resp(self, p):
        """4.11: the peak amplitude at the frequency minus that at 300 MHz, both at the same source level and analyzer settings."""
        s, t = p['src'], p['ti']
        self.uut.preset()
        self._src_set(s['freq_hz'], s['level_dbm'])
        self._tune(cf=t['cf_hz'], span=t['span_hz'], rb=t['rb_hz'], vb=t['rb_hz'], rl=t['rl_dbm'], log_db=1)
        self._src_out(p)
        a_f = self._amp()
        self._tune(cf=s['ref_freq_hz'])
        self.src.set_rf(s['ref_freq_hz'], s['level_dbm'])
        time.sleep(self.settle(p))
        return a_f - self._amp()


class App(reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin, manual_override.ManualOverrideMixin):
    MANUAL_OVERRIDE = True            # the owner requires typed readings on every procedure (manual_override.py); they are judged by judge() below

    def __init__(self, root, model=MODEL, demo=False):
        configure(model)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('hp8591a', STATE_KEY, demo=demo, lists=[POINTS], shape='band')         # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(STATE_KEY)
        s = self.settings
        self.asset = port.var(); self.serial = port.var()
        self.uut_addr = port.var(s.get('uut_addr', str(UUT_ADDRESS)))                  # 8591A (unit under test)
        self.rf_addr = port.var(s.get('rf_addr', DEFAULT_RF_ADDR))                     # 96270A
        self.opt004 = port.var(bool(s.get('opt004', False)), 'bool')                   # the unit has the Option 004 frequency reference (4.1.13 limits)
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self.warm_confirmed = False
        self._prep_done = set()
        for var in (self.uut_addr, self.rf_addr):
            var.trace_add('write', self.reset_forget)       # an address changed in the settings: the next Run resets again
        self._build_ui()
        self.on_options(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo
                        else 'Step 1: enter the Instrument ID. Step 2: check the two addresses and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    def active(self, p):
        return not p.get('skip') and not p.get('unavailable')           # skipped by a procedure modification / not applicable to this unit or setting

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    VIEW = 'hp8591a_view'                              # window code: hp8591a_view_qt.py
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    def is_manual(self, p):
        return p['meas'] in ('selfcal', 'calout_ctr', 'manual')   # the reading is typed / answered from the technician's own look at the analyzer or counter

    def manual_reason(self, p):
        if p['meas'] == 'selfcal':
            return 'The self-calibration is run from the front panel: answer 1 for done, 0 for not done.'
        return p.get('manual_prompt') or 'Read your instrument and type the value.'

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
        cells, tags = self.shell_cells(p['id'], p['nominal'], p['low'], p['high'], p['unit'])
        return (p['id'], p['description'] + ('  [typed]' if self.is_manual(p) else ''), *cells), tags

    def mo_point(self, iid): return POINTS[int(iid) - 1]
    def mo_total(self): return len(POINTS)

    def pm_driver_classes(self): return (drivers.HP8591A, drivers.Fluke96270A)

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_8591a import make_8591a_bench

        def build(mods):
            bench, t_uut, t_src = make_8591a_bench()
            return IO(dict(uut='18'), transports=dict(uut=t_uut, src=t_src), mods=mods)
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

    def on_options(self, save=True):
        """The Option 004 box: the point list follows. Stored readings are judged again against the limits that now apply."""
        self.pm_revert(POINTS)
        apply_options(POINTS, bool(self.opt004.get()))
        self.pm_apply(POINTS)
        for records in (self.found, self.left):
            for key, rec in records.items():
                rec['result'] = 'PASS' if judge(POINTS[int(key) - 1], rec['reading']) else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        extra = ('\nUNVERIFIED / printed discrepancies:\n- ' + '\n- '.join(p['flags'])) if p.get('flags') else ''
        self.detail.set(f'{p["description"]}\nDocument {p["page"]}  ({p["ref"]})\nSetup: {self.setup_text(p)}{extra}'
                        + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    def setup_text(self, p):
        """Hook-up instruction for a point's wiring group."""
        g = p['group']
        if g == 'SELFCAL':
            return ('No connections. After the 30 minute warm-up run the analyzer\'s own self-calibration routines from the front panel (User\'s Guide, "Improving Accuracy With Self-Calibration Routines"). '
                    'The program sends no calibration command.')
        if g == 'CALPM':
            return ('8591A front-panel CAL OUT to the Rohde & Schwarz NRP40T sensor connected to the 96270A (power-meter mode). The sensor is zeroed with nothing connected to it (the program asks first), '
                    'then connected to CAL OUT (300 MHz, -20 dBm). The NRP40T on the 96270A is UNVERIFIED (the 96270A manual never mentions NRP sensors).')
        if g == 'CALCTR':
            return ('Frequency counter input (50 ohm) to the 8591A CAL OUT; the 10 MHz frequency standard to the counter EXT FREQ STD input. Read the counter and type the frequency in Hz. '
                    'The reference option of the unit under test is chosen in the settings.')
        if g == 'SRC':
            return ('96270A RF OUTPUT to the 8591A INPUT 50 ohm (cable). The program sets the 96270A frequency and level (each read back) and switches its output ON only for the point. '
                    'The document\'s Figure 1 also ties the instrument 10 MHz references together; the 96270A is not locked to the analyzer here (UNVERIFIED).')
        if g == 'CALIN':
            return '8591A CAL OUT to the 8591A INPUT (50 ohm cable). The 96270A is not used.'
        return ('4.12: first CAL OUT to the INPUT for the reference-level offset (4.12.2 to 4.12.6), then a 50 ohm termination on the INPUT. Follow the document\'s steps on the analyzer and type the '
                'display-line amplitude in dBm. Set the reference-level offset back to 0 dB afterwards.')

    # ------------------------------------------------------------------ connection
    def _addrs(self):
        return dict(uut=self.uut_addr.get(), src=self.rf_addr.get())

    def find_instruments(self):
        found = []
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception:
            pass
        gpib = [r for r in found if r.upper().startswith('GPIB')]
        for which in ('uut', 'rf'):
            self.ui_view.set_choices(self, which, gpib)
        self.status.set(f'{len(gpib)} GPIB instrument(s) found: ' + (', '.join(gpib) if gpib else 'none') + '. Pick the address of each instrument.' if gpib
                        else 'No GPIB instruments found (install pyvisa and a VISA library, or enter the addresses by hand).')

    def _make_io(self):
        return IO(self._addrs(), mods=self.pm_state)

    def test_connections(self):
        if self.demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect(); self.io = self._make_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True); self._save_settings()
        self.on_options(save=False)
        parts = [f'{MODEL}: {self.io.ident}'] + [f'{x.label}: {x.idn}' for x in (self.io.src,) if x is not None]
        missing = [name for name, x in (('96270A', self.io.src),) if x is None]
        self.status.set('Connected: ' + self.io.ident + '.')
        port.message('info', 'Connected', '\n'.join(parts) + (f'\nNot connected (empty address): {", ".join(missing)}; the points that need it offer a typed reading.' if missing else ''))

    def _reset_failed(self, msg, skipped=False):
        if self.io is not None:
            try: self.io.save_log()          # the command log of the failed reset is on disk before the dialog
            except Exception: pass
        super()._reset_failed(msg, skipped)

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._prep_done = set()
        self._set_conn(None)

    def connected_io(self) -> IO:
        """The connected instruments (hardware mode); a clear error instead of a crash when they are not connected."""
        if self.io is None:
            raise InstrumentError('The instruments are not connected. Press Test connections first.')
        return self.io

    def _set_conn(self, ok):
        pill = getattr(self, 'conn_pill', None)
        if pill is not None:
            pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('uut_addr', self.uut_addr), ('rf_addr', self.rf_addr)):
            self.settings.set(key, var.get())
        self.settings.set('opt004', bool(self.opt004.get()))
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
        if not self.demo and not self.warm_confirmed:
            if not port.ask_yes_no('Warm-up', WARM_UP + '\n\nHave the instruments been on long enough?'): return
            self.warm_confirmed = True
        if not self.demo and self.io is None: self.test_connections()
        if not self.demo and self.io is None: return
        self._mo_pending = None; self._mo_current = None
        self.stop = False; self.busy = True
        self._prep_done = set()                         # the sensor zero is asked for again at every Run
        self.reset_then(lambda: self._upfront_preps(points))     # the Run resets to defaults first (every instrument; the unit under test notice comes first)

    def reset_run(self):
        report = super().reset_run()
        if self.io is not None:
            self.io._reset_state()                           # the reset put every instrument back to its defaults: what the program remembers about them is forgotten
        return report

    # ---- hook-up and zero prompts
    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Specification', p['page'])]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_{MODEL}_{group}.png)'))
        self.connected_io().standby()
        steps = [('Output off', 'The 96270A output is switched OFF (read back) before you rewire.'), ('Wiring', self.setup_text(p))]
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image, parent=self.root)

    PREP = {   # key -> (title, heading, steps, caution)
        'pm_zero': ('Zero the NRP40T power sensor', 'Sensor not connected to any signal',
                    [('Disconnect', 'Disconnect the NRP40T sensor from every signal (it is connected to CAL OUT afterwards).'),
                     ('Zero', 'The program selects the 96270A power meter (300 MHz) and zeroes the sensor; the zero is asked once and not repeated.')],
                    'Nothing may be connected to the sensor while it is zeroed.'),
    }

    @staticmethod
    def preps_for(p):
        return ['pm_zero'] if p['meas'] == 'calout_pm' else []

    def _run_preps(self, points, i, p, key, preps):
        """One preparation: the prompt (UI thread), the work (worker thread), the next one or the hook-up prompt."""
        name = preps[0]
        title, heading, steps, caution = self.PREP[name]
        self.connected_io().standby()
        if not port.operator_prompt(title, heading, steps, facts=[('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description'])], caution=caution,
                                    ok='Ready - zero', parent=self.root):
            self.busy = False; self.status.set('Paused for the sensor zero'); return
        self.status.set(title + ' ...')

        def work():
            try:
                self.connected_io().prep_pm_zero()
                port.post(self.root, lambda: self._preps_done(points, i, p, key, name, preps[1:]))
            except Exception as exc:
                try: self.connected_io().standby()
                except Exception: pass
                err = exc
                port.post(self.root, lambda err=err: self._error(err))
        threading.Thread(target=work, daemon=True).start()

    def _upfront_preps(self, points):
        """The sensor zero the points of this run need is done once, here, before the first point."""
        need, first = [], None
        if not self.demo:
            for p in points:
                if p['meas'] == 'derived' or p.get('skip') or p.get('unavailable'): continue
                for k in self.preps_for(p):
                    if k not in need and k not in self._prep_done: need.append(k); first = first or p
        if not need: self._next(points, 0, None); return
        self._upfront = True
        self._run_preps(points, 0, first, prompt_key(first), need)

    def _preps_done(self, points, i, p, key, name, rest):
        self._prep_done.add(name)
        if rest: self._run_preps(points, i, p, key, rest); return
        upfront, self._upfront = getattr(self, '_upfront', False), False
        self._next(points, i, None, after_prep=not upfront)          # the wiring was changed for the zero: the hook-up prompt is shown again

    def _next(self, points, i, previous, after_prep=False):
        if i >= len(points) or self.stop:
            self._finish_standby()
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        if not after_prep:
            try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
            except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root,30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        key = prompt_key(p)
        self._mo_current = p
        if p['meas'] == 'derived':
            self._derive_point(p); port.after(self.root,30, lambda: self._next(points, i + 1, previous)); return
        need = [] if self.demo else [k for k in self.preps_for(p) if k not in self._prep_done]
        if need:
            self._run_preps(points, i, p, key, need); return
        if not self.demo and key != previous:
            if p['meas'] == 'selfcal':
                if not self._selfcal_prompt(p): self.busy = False; self.status.set('Paused for the self-calibration'); return
                return self._selfcal_done(points, i, p, key)
            if not self._prompt_setup(p):
                self.busy = False; self.status.set('Paused for wiring or setup'); return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        self._mo_current = p                           # the point being measured: 'Enter reading manually' applies to it
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.demo:
            mid, half = (p['low'] + p['high']) / 2, (p['high'] - p['low']) / 2
            reading = mid + half * math.sin(p['id'] * 1.71) * 0.38        # deterministic, labelled synthetic
            if p['meas'] == 'selfcal': reading = 1.0
            self._finish_point(p, reading, True); port.after(self.root,30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.connected_io().measure(p)
                    if isinstance(reading, TypedPoint):
                        port.post(self.root, lambda: self._typed_point(points, i, p, key, reading))
                    else:
                        port.post(self.root, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.connected_io().standby()
                    except Exception: pass
                    if isinstance(exc, ReadingUnavailable):
                        try: self.connected_io().after_read_failure(p, exc)
                        except Exception: pass
                        err = exc
                        port.post(self.root, lambda err=err: self._reading_failed(points, i, p, key, err))
                        return
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _finish_standby(self):
        """The end of a run or a stop: the 96270A output off (read back)."""
        if self.io is not None and not self.demo:
            try: self.io.standby()
            except Exception as exc: port.message('error', 'RF output', f'The 96270A output could not be confirmed OFF: {exc}\nCheck the front panel.')

    # ---- 3.3: the self-calibration (prompt based; the program sends no calibration command)
    def _selfcal_prompt(self, p):
        self.connected_io().standby()
        return port.operator_prompt('Self-calibration', GROUP_TITLE['SELFCAL'],
            [('Warm up', 'The analyzer has been on for 30 minutes.'), ('Calibrate', 'Run the self-calibration routines from the front panel (User\'s Guide, "Improving Accuracy With Self-Calibration Routines"). '
                                                                                  'The program sends no calibration command to the analyzer.')],
            facts=[('Test', p['description']), ('Specification', p['page'])], caution='The performance of the analyzer is specified only after the self-calibration routines have been run.',
            ok='Self-calibration finished - continue', parent=self.root)

    def _selfcal_done(self, points, i, p, key):
        passed = port.ask_yes_no('Self-calibration', 'Did the self-calibration routines complete without an error?\n\nYes = done, No = not done.')
        self._finish_point(p, 1.0 if passed else 0.0, False)
        port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    # ---- typed readings (CAL OUT counter, displayed average noise level)
    def _typed_point(self, points, i, p, key, typed):
        self.status.set(f'Point {p["id"]}: read your instrument and type the value.')
        entered = self.mo_ask(p, reason=typed.reason, cancel_text='Stop run')
        try: self.connected_io().standby()
        except Exception as exc: self._error(exc); return
        self._mo_current = None
        if entered is None:
            self.busy = False; self.status.set('Run stopped: no reading was typed. The 96270A output is OFF.'); return
        self.mo_commit(p, entered, auto=None, why=typed.reason)
        port.after(self.root,30, lambda: self._next(points, i + 1, key))

    def _done(self, points, i, p, reading, key):
        self._finish_point(p, reading, False); port.after(self.root,30, lambda: self._next(points, i + 1, key))

    def _finish_point(self, p, reading, synthetic):
        """The automatic reading of point p arrived: record it, or the reading typed for this point while it was measured (manual_override; logged as the auto reading)."""
        typed = self.mo_take_pending(p)
        self._mo_current = None
        if typed is not None: self.mo_commit(p, typed, auto=reading)
        else: self._record(p, reading, synthetic)

    def _reading_failed(self, points, i, p, key, exc):
        """The reading failed (timeout, unreadable, no instrument connected). The output is already off: ask for the reading and carry on, or stop as before."""
        typed = self.mo_failed(p, exc)
        self._mo_current = None
        if typed is None: self._error(exc); return
        self.mo_commit(p, typed, auto=None, why=str(exc))
        port.after(self.root,30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self._mo_current = None; self._mo_pending = None
        if self.io is not None and not self.demo:
            try: self.io.standby()                          # a stopped run leaves the 96270A output off
            except Exception: pass
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, manual=False, extra=None):
        result = 'PASS' if judge(p, reading) else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, manual=bool(manual) or self.is_manual(p),
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields(), **(extra or {}))
        self._update_row(p); self.save(silent=True)
        self._derive_after(p)

    # ---- derived points (4.11.31: most positive, most negative, range)
    def _readings(self):
        return {q['ref']: self.results[str(q['id'])]['reading'] for q in POINTS if q['meas'] != 'derived' and str(q['id']) in self.results}

    def _derive_point(self, p):
        value = derived_value(p, self._readings())
        if value is None:
            return False
        synthetic = self.demo or any(self.results[str(q['id'])].get('synthetic') for q in POINTS if q['ref'] in p['derive']['inputs'])
        result = 'PASS' if judge(p, value) else 'FAIL'
        self.results[str(p['id'])] = dict(reading=value, result=result, synthetic=synthetic, manual=False, derived=True, timestamp=datetime.now().isoformat(timespec='seconds'),
                                          data=self.mode_label, **self.pm_result_fields())
        self._update_row(p); self.save(silent=True)
        return True

    def _derive_after(self, p):
        """A frequency-response reading was recorded or replaced (also a typed one): every derived point that uses it and has all its inputs is computed again."""
        if p['meas'] == 'derived':
            return
        for q in POINTS:
            if q['meas'] == 'derived' and p['ref'] in q['derive']['inputs']:
                self._derive_point(q)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'{STATE_KEY}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, opt004=bool(self.opt004.get()),
                                        **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.opt004.set(bool(data.get('opt004', self.opt004.get())))
        self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
        self.on_options(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    @staticmethod
    def report_section(p):
        return p['section_title']

    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        return self.certificate_rows_and_points()[0]

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from."""
        rows, pts = [], []
        for p in POINTS:
            if p.get('not_tested') and not p.get('skip'):
                rows.append(self.not_tested_row(p)); pts.append(p)        # kept on the report, no result
                continue
            if not self.active(p): continue
            row = self.found_left_row(p, lambda r, p=p: self.point_row(p, r))
            if row: rows.append(row); pts.append(p)
        return rows, pts

    def not_tested_row(self, p):
        """A point this bench cannot make: on the report with its limits, no reading, marked NOT TESTED."""
        import report_pdf
        reason = p['unavailable'].replace('not tested: ', '', 1)
        return report_pdf.cert_row(f"{p['description']} - NOT TESTED: {reason}", p['nominal'], p['low'], p['high'], p['unit'], None, False, section=self.report_section(p))

    def point_row(self, p, r):
        """One report row. No uncertainty is printed (the suite has no uncertainty for these RF measurements; the cover sheet from the other software carries the standards)."""
        import report_pdf
        note = '' if p['unit'] != '' else ' (1 = done)'
        return report_pdf.cert_row(p['description'] + note, p['nominal'], p['low'], p['high'], p['unit'], r['reading'], r['result'] == 'FAIL', section=self.report_section(p))

    def export_pdf(self):
        rows, pts = self.certificate_rows_and_points()
        if not any(not p.get('not_tested') for p in pts): port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details(f'HP {MODEL} performance verification' + (f' ({VARIANT_LABEL})' if VARIANT_LABEL else ''), parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        try:
            header = [('Instrument', f'HP {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                      ('Limits applied', SPEC['source'].get('limits_text') or 'T.O. 33K3-4-2864-1'), ('Source', SPEC['source']['cite']),
                      ('Frequency reference', 'Option 004' if self.opt004.get() else 'Standard')]
            report_pdf.write_calibration_pdf(path, rows, header=header, demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, None),
                                             snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); port.close(self.root)


def main(argv=None, spec_path=None, state_key=None, variant_label=None):
    """spec_path / state_key / variant_label: a second procedure on this engine (a different spec, its own saved state and its own title); None keeps the document's procedure."""
    global SPEC_PATH, STATE_KEY, VARIANT_LABEL
    if spec_path is not None: SPEC_PATH = Path(spec_path)
    if state_key is not None: STATE_KEY = state_key
    if variant_label is not None: VARIANT_LABEL = variant_label
    argv = sys.argv if argv is None else argv
    def build(root):
        App(root, MODEL, demo='--demo' in argv)
    port.run_app(build)
