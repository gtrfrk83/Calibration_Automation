"""Fluke 6060A / 6060A-AF synthesized signal generator: performance verification (Instruction Manual, Section 4A), two-way automated.

Test points and limits are NOT written in this file: they are loaded from specs/fluke_6060a_pv.json (built by specs/build_fluke_6060a_spec.py from the RENDERED pages 4A-3 to 4A-17 of the
manual, PDF pages 117 to 133). A point is good when LOW <= reading <= HIGH (HIGH exclusive for the manual's strict "<" limits), judged in Decimal. Output leakage (4A-9, 4A-10) is not built.

Bench (GPIB): the 6060A (unit under test), the HP 8902A measuring receiver (frequency, tuned RF level, RF power with the 11722A sensor module, AM / FM / distortion / rate), the Fluke 96270A
in power-meter mode with a Rohde & Schwarz NRP40T sensor (4A-5, 4A-6; the sensor is UNVERIFIED), the HP 8563E spectrum analyzer (4A-11) and, for the external-modulation tests, a Keysight
33210A / 33220A / 33250A function generator (or a generator you set by hand). Every address is an editable box saved with the settings. The program resets every instrument to its defaults
before the first point, pauses for the hook-up whenever the wiring changes, switches the 6060A RF output off (read back) after every point and at the end or abort, and never runs unattended.
There is no adjustment here: this is verification only. Hardware I/O is OFF in demo mode, and a demo run records only marked synthetic data.

Typed readings ('Enter reading manually') are judged by the same limit logic as automatic ones. The three 8902A calibrations (RF power sensor, AM, FM) are prompted when first needed.

    import fluke6060a_verification
    fluke6060a_verification.main()      # what Procedures/Fluke_6060A_Verification.py does
"""
import json, math, sys, threading, time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, report_filename, Settings); the window code is in fluke6060a_view_qt.py
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

MODEL = '6060A'
SPEC_PATH = HERE / 'specs' / 'fluke_6060a_pv.json'
SPEC = POINTS = None
UUT_ADDRESS = drivers.Fluke6060A.DEFAULT_ADDRESS          # the owner's lab addresses; each is an editable box and none is fixed in code
RX_ADDRESS = drivers.HP8902A.DEFAULT_ADDRESS
SA_ADDRESS = drivers.HP8563E.DEFAULT_ADDRESS
DEFAULT_RF_ADDR = 'GPIB0::4::INSTR'                        # the 96270A: the same default as the 53220A / MDO engines (UNVERIFIED example; File > Settings > Instrument addresses overrides it)
NO_LF = 'None (I set the generator by hand)'
LF_CHOICES = {NO_LF: None, 'Keysight 33210A': drivers.Keysight33210A, 'Keysight 33220A': drivers.Keysight33220A, 'Keysight 33250A': drivers.Keysight33250A}
LF_VRMS = 0.7071                                          # test 3 and 6: "0.7071 V rms as read by the DVM" (UNVERIFIED: the generator is set to this into High Z; check the DVM)
MEAS = ('selftest', 'freq_count', 'level_pm', 'level_rx', 'harmonic', 'spur', 'mod_rate', 'am_depth', 'fm_dev', 'thd', 'thd_typed', 'derived')
GROUP_TITLE = {'POWERON': 'Power-on self test', 'RX': '6060A RF OUTPUT to the 8902A RF INPUT', 'RXPWR': '6060A RF OUTPUT to the 11722A sensor module (8902A RF power)',
               'PM': '6060A RF OUTPUT to the NRP40T sensor on the 96270A', 'SA': '6060A RF OUTPUT to the 8563E', 'EXT1K': '8902A and LF generator at 1 kHz (external modulation)',
               'EXT10K': '8902A and LF generator at 10 kHz (external modulation)', 'EXT400': '8902A and LF generator at 400 Hz (external modulation)'}
WARM_UP = ('The 8902A needs 30 minutes of warm-up before its power, AM and FM calibrations (8902A manual), and the 8563E and the 6060A should be on long enough to be stable. '
           'The program does not wait for it.')
TYPED_THD_TEXT = ('Test 6: THD at 10 kHz is typed from your own distortion analyzer (the 8902A measures distortion only at 1 kHz and 400 Hz). Untick to leave those 17 points out.')


class SpecError(procspec.SpecError):
    pass


def load_spec(path=SPEC_PATH):
    """Read and check the spec (kind 'rf-generator-pv'): every point has a measurement kind, a group, limits that contain the nominal, and (for a derived point) inputs that exist."""
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('kind') != 'rf-generator-pv' or spec.get('model') != MODEL:
        raise SpecError("not a 'rf-generator-pv' spec for the 6060A")
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
            if p['meas'] not in ('selftest', 'derived') and 'gen' not in p:
                raise SpecError(f'{where}: a measured point needs a generator setting')
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
            p['_base'] = dict(nominal=p['nominal'], low=p['low'], high=p['high'], description=p['description'], khz=((p.get('gen') or {}).get('fm') or {}).get('khz'))
            points.append(p)
    return points


def configure(model=MODEL):
    """Load the spec and number the points (the one model of this engine)."""
    global SPEC, POINTS
    SPEC = load_spec()
    POINTS = flatten(SPEC)
    apply_options(POINTS, True)


def apply_options(points, typed_thd):
    """What depends on the ticked box: the typed THD points are left out when their box is unticked. Sets p['unavailable'] (a reason) or ''."""
    for p in points:
        base = p['_base']
        p['nominal'], p['low'], p['high'], p['description'] = base['nominal'], base['low'], base['high'], base['description']
        if base['khz'] is not None:
            p['gen']['fm']['khz'] = base['khz']
        p['unavailable'] = ''
        if p.get('typed_only') and not typed_thd:
            p['unavailable'] = 'THD at 10 kHz typed from your analyzer is switched off (tick the box in the settings)'
        p['error'] = float(f"{max(p['nominal'] - p['low'], p['high'] - p['nominal']):.9g}")


def prompt_key(p):
    """What decides whether the hook-up prompt is shown again: the wiring group."""
    return p['group']


class ReadingUnavailable(InstrumentError):
    """The automatic reading of a point failed (timeout, unreadable, no instrument connected). Same message as the error it wraps; the App offers a typed reading (manual_override)."""


class TypedPoint:
    """IO.measure's answer for a point that has no automatic reading (THD at 10 kHz): the RF output is still ON so the technician can read the analyzer; the App asks for the number
    and then calls IO.standby()."""

    def __init__(self, reason):
        self.reason = reason


def judge(p, reading):
    """True when LOW <= reading <= HIGH, in Decimal (a reading exactly on a limit passes; a point with strict_high needs reading < HIGH, the manual's "<" limits)."""
    value = Decimal(repr(float(reading)))
    low, high = Decimal(repr(float(p['low']))), Decimal(repr(float(p['high'])))
    if value < low:
        return False
    return value < high if p.get('strict_high') else value <= high


def derived_value(p, readings):
    """The value of a derived point from the readings (ref -> dBm) of its inputs, all in Decimal (Section 4A-5, the manual's formulas; NOT Figure 4A-3, whose section 1 example is mis-added):
    section n error = M(n) - M(0) + nominal attenuation(n);  sum = (M(0) - 12) + the errors of sections 1 to 7. None when an input has no reading yet."""
    d = p['derive']
    if any(r not in readings for r in d['inputs']):
        return None
    m = [Decimal(repr(float(readings[r]))) for r in d['inputs']]
    if d['kind'] == 'section':
        return float(f"{float(m[1] - m[0] + Decimal(str(d['constant']))):.9g}")
    total = m[0] - Decimal(str(d['level0']))
    for n in range(1, len(m)):
        total += m[n] - m[0] + Decimal(str(d['attenuation'][n]))
    return float(f'{float(total):.9g}')


def find_diagram(group):
    """Hook-up picture for a wiring group: diagrams/hook_6060A_<GROUP>.png (supplied by the owner; none is drawn here)."""
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
    """The GPIB primary address (0..30) in an address box; raises InstrumentError for anything else (these three instruments are GPIB only)."""
    n = address_of(to_visa(text))
    if n is None:
        raise InstrumentError(f'The {what} address must be a GPIB address (0 to 30 or GPIB0::n::INSTR), not {str(text).strip()!r}')
    return check_address(n)


# Settle times after RF ON, before the first reading: ENGINEERING ESTIMATES, NOT from a manual (the 6060A itself waits for a valid output, VM1). Tune them on the bench
# (procedure modifications 'f6060a.settle.*').
DEFAULT_SETTLE_S = 0.5
PM_SETTLE_S = 1.0
MOD_SETTLE_S = 2.0
SA_SETTLE_S = 1.0
SPUR_WINDOW_SPAN_HZ = 1e6


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the 6060A, the 8902A, the 8563E, the 96270A power meter and the LF generator, all through the instrument drivers. An instrument whose address box is empty is not connected:
    a point that needs it offers a typed reading."""

    def __init__(self, addrs, lf_model=NO_LF, transports=None, mods=None):
        self.log = drivers.CommandLog()
        self.gen = self.rx = self.sa = self.pm = self.lf = None
        self.lf_model = lf_model
        self._reset_state()
        tr = dict(transports or {})
        try:
            if 'gen' not in tr:
                n = gpib_number(addrs['uut'], '6060A')
                tr['gen'] = drivers.open_visa(to_visa(addrs['uut']), timeout=20)   # the box keeps its GPIB board: 'GPIB1::2::INSTR' is not turned into GPIB0
            self.gen = drivers.Fluke6060A(tr['gen'], self.log, label='6060A', address=gpib_number(addrs['uut'], '6060A') if not transports else None)
            self.gen.connect()
            for key, cls, label, what in (('rx', drivers.HP8902A, '8902A', '8902A'), ('sa', drivers.HP8563E, '8563E', '8563E')):
                text = str(addrs.get(key, '')).strip()
                if key not in tr and not text:
                    continue
                if key not in tr:
                    n = gpib_number(text, what)
                    tr[key] = drivers.open_visa(to_visa(text), timeout=40)
                inst = cls(tr[key], self.log, label=label, address=gpib_number(text, what) if (text and not transports) else None)
                inst.connect()
                setattr(self, key, inst)
            text = str(addrs.get('pm', '')).strip()
            if 'pm' in tr or text:
                if 'pm' not in tr:
                    tr['pm'] = drivers.open_visa(to_visa(text), timeout=20)
                self.pm = drivers.Fluke96270A(tr['pm'], self.log, label='96270A')
                self.pm.connect()
            text = str(addrs.get('lf', '')).strip()
            cls = LF_CHOICES.get(lf_model)
            if cls is not None and ('lf' in tr or text):
                if 'lf' not in tr:
                    tr['lf'] = drivers.open_visa(to_visa(text), timeout=20)
                self.lf = cls(tr['lf'], self.log, label=lf_model.replace('Keysight ', ''))
                self.lf.connect()
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.gen.idn

    def _reset_state(self):
        """What the program remembers about the instruments; forgotten at every reset (the reset puts them back to defaults)."""
        self._mod_on = False
        self._pm_key = None
        self._lf_set = None
        self._lf_on = False
        self._tb_checked = False

    def reset_roles(self):
        return [x for x in (self.rx, self.sa, self.pm, self.lf) if x is not None], [self.gen]

    def reset_at_start(self, confirm=None):
        report = super().reset_at_start(confirm)
        self._reset_state()
        return report

    def pm_drivers(self):
        return tuple(x for x in (self.gen, self.rx, self.sa, self.pm, self.lf) if x is not None)

    def standby(self):
        """The end of every point (and of an abort): the 6060A RF OFF, read back (SafetyError when it is not off), and the LF generator output off."""
        try:
            self.gen.end_point()
        finally:
            self.lf_off()

    def lf_off(self):
        if self.lf is not None and self._lf_on:
            try:
                self.lf.output(False)
                self._lf_on = False
            except SafetyError:
                raise
            except Exception as exc:
                self.log.add('!!', f'LF generator output off failed: {exc}', self.lf.label)
                try: self.lf.cleanup()
                except Exception: pass

    def close(self):
        try: self.standby()
        except Exception: pass
        for obj in (self.lf, self.pm, self.sa, self.rx, self.gen):
            if obj is None:
                continue
            try: obj.cleanup()
            except Exception: pass
        for obj in (self.lf, self.pm, self.sa, self.rx, self.gen):
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
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  Fluke {MODEL} session\n' + '\n'.join(new) + '\n')
            self._logged = len(lines)
        except OSError:
            pass

    def after_power_cycle(self):
        """4A-3: the technician switched the 6060A off and on. Its GPIB state is the power-on one (RF ON, interface modes lost): device clear, RF OFF confirmed at once, then the full
        reset to defaults (RC98, status clear, interface modes read back with II, options with IO). Every write once."""
        self.gen.t.clear()
        self.log.add('--', 'device clear after the power cycle; RF output is switched off at once', self.gen.label)
        self.gen.rf(False)
        report = self.gen.reset_to_defaults()
        if not report.ok:
            raise InstrumentError(f'The 6060A did not reset after the power cycle: {report.failed_step.name if report.failed_step else "?"}')
        self._mod_on = False

    # ---- calibrations of the 8902A (prompted by the App when first needed) -----------------------------------------------------------------------------
    def prep_rx_power(self):
        """Sensor module on the 8902A calibration output: zero (no RF), then the 1 mW 50 MHz power calibration."""
        rx = self._need('rx', '8902A')
        rx.zero_power_sensor()
        rx.calibrate_power_sensor()

    def prep_rx_mod(self, kind):
        self._need('rx', '8902A').calibrate_modulation(kind)

    # ---- one point ---------------------------------------------------------------------------------------------------------------------------------
    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        if p['meas'] == 'level_pm': return self.pm_param('f6060a.settle.pm', PM_SETTLE_S)
        if p['meas'] in ('harmonic', 'spur'): return self.pm_param('f6060a.settle.sa', SA_SETTLE_S)
        if p['meas'] in ('level_rx', 'mod_rate', 'am_depth', 'fm_dev', 'thd', 'freq_count'): return self.pm_param('f6060a.settle.mod', MOD_SETTLE_S)
        return self.pm_param('f6060a.settle.default', DEFAULT_SETTLE_S)

    def _need(self, name, what):
        inst = getattr(self, name)
        if inst is None:
            raise ReadingUnavailable(f'No {what} is connected (its address box is empty): type the reading from your own instrument.')
        return inst

    def after_read_failure(self, p, exc):
        """After a failed automatic reading: the RF output off (already done by measure), the failure logged; the run can go on with a typed reading."""
        self.log.add('!!', f'reading failed ({exc}); a manually entered reading may replace it', MODEL)

    @procmods_engine.point_commands()
    def measure(self, p):
        """Set the 6060A (every write read back), RF ON, settle, read; RF OFF (confirmed) afterwards, also when anything fails. A THD point typed from the analyzer returns a TypedPoint
        with the RF still ON (the App asks for the number, then calls standby())."""
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
        if kind in ('derived', 'selftest'):
            raise InstrumentError(f'{p["ref"]} is not measured by the instruments')
        needs = {'freq_count': ('rx', '8902A'), 'level_pm': ('pm', '96270A'), 'level_rx': ('rx', '8902A'), 'harmonic': ('sa', '8563E'), 'spur': ('sa', '8563E'),
                 'mod_rate': ('rx', '8902A'), 'am_depth': ('rx', '8902A'), 'fm_dev': ('rx', '8902A'), 'thd': ('rx', '8902A')}
        if kind in needs:
            self._need(*needs[kind])
        self._configure(p)
        self.gen.rf(True)
        time.sleep(self.settle(p))
        if kind == 'thd_typed':
            return TypedPoint('THD at 10 kHz cannot be measured by the 8902A (distortion at 1 kHz and 400 Hz only): read your distortion analyzer and type the value.')
        try:
            return self._read_value(p)
        except (SafetyError, ReadingUnavailable):
            raise
        except Exception as exc:                                   # a timeout, an error word, a calibration the 8902A asks for: a typed reading may replace it
            raise ReadingUnavailable(str(exc)) from exc

    def _configure(self, p):
        """Everything before RF ON: the LF generator, the generator frequency, level / section and modulation, each read back. The output is OFF here."""
        g, gen = p['gen'], self.gen
        lf = p.get('lf')
        if lf and self.lf is not None:
            if self._lf_set != (lf['freq_hz'], lf['vrms']):
                self.lf.setup('SIN', lf['freq_hz'], lf['vrms'], 'VRMS', 'INF')
                self._lf_set = (lf['freq_hz'], lf['vrms'])
            self.lf.output(True)
            self._lf_on = True
        am, fm = g.get('am'), g.get('fm')
        if self._mod_on:                                   # whatever the previous point left on is switched off first (read back), then this point's modulation is set
            gen.mod_off()
            self._mod_on = False
        if p['meas'] == 'level_pm':
            self._pm_ready(p)
        gen.set_frequency(g['freq_mhz'])
        if 'section_no' in p:
            gen.select_section(p['section_no'], rf_on=True)
        elif g.get('level_dbm') is not None:
            gen.set_level(g['level_dbm'])
        if am:
            gen.am(am['pct'], source=am['src'], rate_hz=am.get('rate_hz', 1000), input_applied=am.get('input_applied', True))
            self._mod_on = True
        if fm:
            gen.fm(fm['khz'], source=fm['src'], rate_hz=fm.get('rate_hz', 1000))
            self._mod_on = True

    def _pm_ready(self, p):
        """The power meter at this frequency, zeroed with the 6060A RF OFF (the sensor sees no signal); once per zero_key (4A-5 and 4A-6 each zero at every frequency)."""
        if self._pm_key == p['zero_key']:
            return
        self.pm.select_power_meter(frequency_hz=p['pm']['freq_mhz'] * 1e6)
        self.pm.zero()
        self._pm_key = p['zero_key']

    def _read_value(self, p):
        kind, rx = p['meas'], self.rx
        f = p['gen']['freq_mhz']
        r = p.get('rx') or {}
        if kind == 'freq_count':
            # No automatic 15.1SP time-base check: owner bench 2026-10-28, sending 15.1SP left the 8902A showing '1' (the special-function display) and locked until a preset.
            # The reference connection is the operator's hook-up step (see the group notice); the 8902A switches to the external 10 MHz by itself.
            return rx.measure_frequency_hz(f, resolution_hz=r['resolution_hz'])
        if kind == 'level_pm':
            return self.pm.read_dbm()
        if kind == 'level_rx':
            if r['mode'] == 'power':
                return rx.rf_power_dbm(f)
            try:
                return rx.tuned_rf_level_dbm(f)
            except drivers.RecalRequired:
                rx.calibrate_tuned_level(f)                 # the level is held constant: this very point's signal is still on
                return rx.tuned_rf_level_dbm(f)
        if kind == 'harmonic':
            return self._harmonic(p)
        if kind == 'spur':
            return self._spur(p)
        if kind == 'mod_rate':
            return rx.measure_modulation_rate_hz(f, source=r['source'])
        if kind == 'am_depth':
            return rx.measure_am_percent(f, detector=r['detector'], hp=r['hp'], lp=r['lp'])
        if kind == 'fm_dev':
            return rx.measure_fm_deviation_hz(f, detector=r['detector'], hp=r['hp'], lp=r['lp'])
        if kind == 'thd':
            return rx.measure_distortion(f, tone_hz=r['tone_hz'], source=r['source'])
        raise InstrumentError(f'unknown measurement {kind!r}')

    # ---- the 8563E (4A-11): the analyzer settings are this procedure's choice (UNVERIFIED) -------------------------------------------------------
    @staticmethod
    def _sa_range(level_dbm):
        return (20.0, 30) if level_dbm > 7 else (10.0, 20)

    def _harmonic(self, p):
        """The worst harmonic (2 .. n_max) in dBc from the driver's software harmonic helper (CF = n x the measured fundamental, TS, MKPK HI)."""
        f_hz = p['gen']['freq_mhz'] * 1e6
        span = min(1e6, f_hz / 4.0)
        rbw = 30e3 if span >= 1e6 else 3e3
        ref, att = self._sa_range(p['gen']['level_dbm'])
        out = self.sa.measure_harmonics(f_hz, n_max=p['sa']['n_max'], span_hz=span, rbw_hz=rbw, vbw_hz=rbw, ref_level_dbm=ref, atten_db=att)
        vals = [d for d in out['dbc'] if d is not None]
        if not vals:
            raise InstrumentError('No harmonic could be measured (none within half a span of its frequency).')
        return max(vals)

    def _spur(self, p):
        """The worst spur in dBc at the point's target: the carrier level (driver helper measure_fundamental), then a window at each target frequency (centre = the target, MKPK HI) and the
        spur level minus the carrier level. 'off' targets are OFFSETS from the carrier (both sides, the worse is taken); 'abs' targets are absolute frequencies."""
        g, s = p['gen'], p['sa']
        carrier = g['freq_mhz'] * 1e6
        ref, att = self._sa_range(g['level_dbm'])
        fund = self.sa.measure_fundamental(carrier, span_hz=1e6 if carrier >= 4e6 else carrier / 4.0, rbw_hz=30e3 if carrier >= 4e6 else 3e3, vbw_hz=30e3 if carrier >= 4e6 else 3e3,
                                           ref_level_dbm=ref, atten_db=att)
        carrier_dbm = fund['level_dbm']
        carrier = fund['freq_hz']
        target = s['target_hz']
        centres = [carrier - target, carrier + target] if s['kind'] == 'off' else [target]
        span = min(max(target / 2.0, 10e3), 2e6) if s['kind'] == 'off' else SPUR_WINDOW_SPAN_HZ
        rbw = 1e3 if span <= 20e3 else 3e3 if span <= 300e3 else 30e3
        worst = None
        for c in centres:
            if c <= 0:
                continue
            self.sa.configure(c, span, rbw, rbw, ref, att)
            self.sa.single_sweep()
            self.sa.take_sweep()
            _hz, dbm = self.sa.marker_to_peak()
            dbc = dbm - carrier_dbm
            worst = dbc if worst is None else max(worst, dbc)
        if worst is None:
            raise InstrumentError('The spur window is below 0 Hz.')
        return worst


class App(reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin, manual_override.ManualOverrideMixin):
    MANUAL_OVERRIDE = True            # the owner requires typed readings on every procedure (manual_override.py); they are judged by judge() below

    def __init__(self, root, model=MODEL, demo=False):
        configure(model)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('f6060a', MODEL, demo=demo, lists=[POINTS], shape='band')         # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(MODEL)
        s = self.settings
        self.asset = port.var(); self.serial = port.var()
        self.uut_addr = port.var(s.get('uut_addr', str(UUT_ADDRESS)))                  # 6060A (unit under test)
        self.rx_addr = port.var(s.get('addr_8902A', str(RX_ADDRESS)))                  # 8902A (File > Settings > Instrument addresses can pre-fill it)
        self.sa_addr = port.var(s.get('addr_8563E', str(SA_ADDRESS)))                  # 8563E
        self.rf_addr = port.var(s.get('rf_addr', DEFAULT_RF_ADDR))                     # 96270A
        self.lf_model = port.var(s.get('lf_model', NO_LF) if s.get('lf_model', NO_LF) in LF_CHOICES else NO_LF)
        self.lf_addr = port.var(s.get('lf_addr', ''))                                  # 33210A / 33220A / 33250A as the LF source (empty: set by hand)
        self.thd_typed = port.var(bool(s.get('thd_typed', True)), 'bool')
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self.warm_confirmed = False
        self._prep_done = set()
        for var in (self.uut_addr, self.rx_addr, self.sa_addr, self.rf_addr, self.lf_model, self.lf_addr):
            var.trace_add('write', self.reset_forget)       # an address changed in the settings: the next Run resets again
        self._build_ui()
        self.on_options(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo
                        else 'Step 1: enter the Instrument ID. Step 2: check the five addresses and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    def active(self, p):
        return not p.get('skip') and not p.get('unavailable')           # skipped by a procedure modification / not applicable to this generator or setting

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    VIEW = 'fluke6060a_view'                              # window code: fluke6060a_view_qt.py
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    def is_manual(self, p):
        return p['meas'] == 'thd_typed'               # the reading is typed from the technician's own analyzer

    def manual_reason(self, p):
        return 'The 8902A measures audio distortion only at 1 kHz and 400 Hz: read your own distortion analyzer.'

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

    def pm_driver_classes(self): return (drivers.Fluke6060A, drivers.HP8902A, drivers.HP8563E, drivers.Fluke96270A, drivers.Keysight33220A)

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_6060a import make_rf_bench
        from drivers.simulated_96270a import make_pm_transport

        def build(mods):
            bench, t6, t8902, t8563 = make_rf_bench()
            t8902.external_ref = True
            return IO(dict(uut='2'), transports=dict(gen=t6, rx=t8902, sa=t8563, pm=make_pm_transport(bench)), mods=mods)
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
        """The typed-THD box: the point list follows. Stored readings are judged again against the limits that now apply."""
        self.pm_revert(POINTS)
        apply_options(POINTS, bool(self.thd_typed.get()))
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
        self.detail.set(f'{p["description"]}\nManual page {p["page"]}  ({p["ref"]})\nSetup: {self.setup_text(p)}{extra}'
                        + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    def setup_text(self, p):
        """Hook-up instruction for a point's wiring group."""
        g = p['group']
        rx_in = ('6060A RF OUTPUT to the 8902A RF INPUT (50 ohm cable; the 8902A input is limited to +27 dBm). 6060A rear panel 10 MHz IN/OUT to the 8902A rear 10 MHz reference input, '
                 'REF INT/EXT switch as 4A-4 says. The 8902A takes the external reference by itself; check on the 8902A that it shows the external reference (the program does not send special function 15.1: it locked the receiver on the bench).')
        if g == 'POWERON':
            return 'No connections. Switch the 6060A POWER off and on and watch the self test (every indicator on for about 5 seconds; the failure codes show in the four display fields if it fails).'
        if g == 'RX':
            return rx_in
        if g == 'RXPWR':
            return ('6060A RF OUTPUT to the 11722A power sensor module connected to the 8902A SENSOR input (RF power, M4). The sensor module\'s calibration-factor table must already be loaded '
                    'in the 8902A (UNVERIFIED: this program does not enter it).')
        if g == 'PM':
            return ('6060A RF OUTPUT to the Rohde & Schwarz NRP40T sensor connected to the 96270A (power-meter mode). The sensor is zeroed with the 6060A RF off at each frequency; '
                    'the NRP40T on the 96270A is UNVERIFIED (the 96270A manual never mentions NRP sensors).')
        if g == 'SA':
            return '6060A RF OUTPUT to the 8563E RF INPUT through a cable. Do not overload the analyzer (+13 dBm needs 30 dB of input attenuation, which the program sets).'
        lf = {'EXT1K': ('1 kHz', 'sine'), 'EXT10K': ('10 kHz', 'sine'), 'EXT400': ('0.4 kHz', 'sine')}[g]
        auto = ('The program sets the selected generator to a ' + lf[1] + ' ' + lf[0] + ' at 0.7071 V rms into High Z and switches its output on only for the point.'
                if self.lf_model.get() != NO_LF and self.lf_addr.get().strip() else f'Set your function generator to a {lf[1]} at {lf[0]}, 0.7071 V rms, output on.')
        return (rx_in + f'\nLF generator output through a BNC T to the 6060A MOD INPUT and a DVM. {auto} Check that the DVM reads 0.7071 V rms (adjust the generator amplitude if not).')

    # ------------------------------------------------------------------ connection
    def _addrs(self):
        return dict(uut=self.uut_addr.get(), rx=self.rx_addr.get(), sa=self.sa_addr.get(), pm=self.rf_addr.get(), lf=self.lf_addr.get())

    def find_instruments(self):
        found = []
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception:
            pass
        gpib = [r for r in found if r.upper().startswith('GPIB')]
        for which in ('uut', 'rx', 'sa', 'rf', 'lf'):
            self.ui_view.set_choices(self, which, gpib)
        self.status.set(f'{len(gpib)} GPIB instrument(s) found: ' + (', '.join(gpib) if gpib else 'none') + '. Pick the address of each instrument.' if gpib
                        else 'No GPIB instruments found (install pyvisa and a VISA library, or enter the addresses by hand).')

    def _make_io(self):
        return IO(self._addrs(), self.lf_model.get(), mods=self.pm_state)

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
        parts = [f'{MODEL}: {self.io.ident}'] + [f'{x.label}: {x.idn}' for x in (self.io.rx, self.io.sa, self.io.pm, self.io.lf) if x is not None]
        missing = [name for name, x in (('8902A', self.io.rx), ('8563E', self.io.sa), ('96270A', self.io.pm)) if x is None]
        self.status.set('Connected: ' + self.io.ident + '.' + ' RF output is OFF.')
        port.message('info', 'Connected', '\n'.join(parts) + '\nRF output is off.' + (f'\nNot connected (empty address): {", ".join(missing)}; their points offer a typed reading.' if missing else ''))

    def _reset_failed(self, msg, skipped=False):
        if self.io is not None:
            try: self.io.save_log()          # the command log of the failed reset is on disk before the dialog
            except Exception: pass
        super()._reset_failed(msg, skipped)

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._prep_done = set()
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('uut_addr', self.uut_addr), ('addr_8902A', self.rx_addr), ('addr_8563E', self.sa_addr), ('rf_addr', self.rf_addr), ('lf_model', self.lf_model),
                         ('lf_addr', self.lf_addr)):
            self.settings.set(key, var.get())
        self.settings.set('thd_typed', bool(self.thd_typed.get()))
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
        self._prep_done = set()                         # the 8902A is reset at the start of every Run: its calibrations are asked for again
        self.reset_then(lambda: self._next(points, 0, None))     # the Run resets to defaults first (every instrument; the unit under test notice comes first)

    def reset_run(self):
        report = super().reset_run()
        if self.io is not None:
            self.io._reset_state()                           # the reset put every instrument back to its defaults: what the program remembers about them is forgotten
        return report

    # ---- hook-up and calibration prompts
    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Specification', p['page'])]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_{MODEL}_{group}.png)'))
        self.io.standby()
        steps = [('RF off', 'The 6060A RF output is switched OFF (read back) before you rewire.'), ('Wiring', self.setup_text(p))]
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image, parent=self.root)

    PREP = {   # key -> (title, heading, steps, caution)
        'rx_power': ('Calibrate the 8902A RF power', 'Sensor module on the 8902A calibration output',
                     [('Connect', 'Connect the 11722A sensor module to the 8902A RF POWER CALIBRATION OUTPUT (50 MHz, 1 mW). The 6060A RF output stays off.'),
                      ('Zero and calibrate', 'The program zeroes the sensor (no RF at it, CALIBRATE light off) and runs the 1 mW calibration; the result must be 0.999 to 1.000 mW.')],
                     'The 8902A should have been on for 30 minutes.'),
        'rx_am': ('Calibrate the 8902A AM', 'Calibrator signal to the 8902A RF INPUT',
                  [('Connect', 'Connect the 8902A AM / FM calibration source to its RF INPUT as the 8902A manual shows (UNVERIFIED connector). The 6060A RF output stays off.'),
                   ('Calibrate', 'The program runs the AM calibration (about 20 s) and requires a factor of 99 to 101 %.')],
                  'Do not change the signal while the calibration runs.'),
        'rx_fm': ('Calibrate the 8902A FM', 'Calibrator signal to the 8902A RF INPUT',
                  [('Connect', 'Connect the 8902A AM / FM calibration source to its RF INPUT as the 8902A manual shows (UNVERIFIED connector). The 6060A RF output stays off.'),
                   ('Calibrate', 'The program runs the FM calibration (about 20 s); the factor must be 99 to 101 % (that FM band is UNVERIFIED).')],
                  'Do not change the signal while the calibration runs.'),
    }

    @staticmethod
    def preps_for(p):
        if p['meas'] == 'level_rx' and p['rx']['mode'] == 'power': return ['rx_power']
        if p['meas'] == 'am_depth': return ['rx_am']
        if p['meas'] == 'fm_dev': return ['rx_fm']
        return []

    def _run_preps(self, points, i, p, key, preps):
        """One calibration of the 8902A: the prompt (UI thread), the calibration (worker thread), the next one or the hook-up prompt."""
        name = preps[0]
        title, heading, steps, caution = self.PREP[name]
        self.io.standby()
        if not port.operator_prompt(title, heading, steps, facts=[('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description'])], caution=caution,
                                    ok='Connected - calibrate', parent=self.root):
            self.busy = False; self.status.set('Paused for calibration'); return
        self.status.set(title + ' ...')

        def work():
            try:
                if name == 'rx_power': self.io.prep_rx_power()
                else: self.io.prep_rx_mod('am' if name == 'rx_am' else 'fm')
                port.post(self.root, lambda: self._preps_done(points, i, p, key, name, preps[1:]))
            except Exception as exc:
                try: self.io.standby()
                except Exception: pass
                err = exc
                port.post(self.root, lambda err=err: self._error(err))
        threading.Thread(target=work, daemon=True).start()

    def _preps_done(self, points, i, p, key, name, rest):
        self._prep_done.add(name)
        if rest: self._run_preps(points, i, p, key, rest); return
        self._next(points, i, None, after_prep=True)          # the wiring was changed for the calibration: the hook-up prompt is shown again

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
            if p['meas'] == 'selftest':
                if not self._power_on_test(p): self.busy = False; self.status.set('Paused for the power-on test'); return
                return self._selftest_done(points, i, p, key)
            if not self._prompt_setup(p):
                self.busy = False; self.status.set('Paused for wiring or setup'); return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        self._mo_current = p                           # the point being measured: 'Enter reading manually' applies to it
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.demo:
            mid, half = (p['low'] + p['high']) / 2, (p['high'] - p['low']) / 2
            reading = mid + half * math.sin(p['id'] * 1.71) * 0.38        # deterministic, labelled synthetic
            if p['meas'] == 'selftest': reading = 1.0
            self._finish_point(p, reading, True); port.after(self.root,30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    if isinstance(reading, TypedPoint):
                        port.post(self.root, lambda: self._typed_point(points, i, p, key, reading))
                    else:
                        port.post(self.root, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    if isinstance(exc, ReadingUnavailable):
                        try: self.io.after_read_failure(p, exc)
                        except Exception: pass
                        err = exc
                        port.post(self.root, lambda err=err: self._reading_failed(points, i, p, key, err))
                        return
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _finish_standby(self):
        """The end of a run or a stop: RF output off (read back) and the LF generator off."""
        if self.io is not None and not self.demo:
            try: self.io.standby()
            except Exception as exc: port.message('error', 'RF output', f'The 6060A RF output could not be confirmed OFF: {exc}\nCheck the front panel.')

    # ---- 4A-3: the power-on self test (prompt based)
    def _power_on_test(self, p):
        self.io.standby()
        return port.operator_prompt('Power-on self test', GROUP_TITLE['POWERON'],
            [('Power off and on', 'Switch the 6060A POWER switch off, then on.'), ('Watch', 'The self test runs: every indicator and display segment is on for about 5 seconds. If it passes, the generator goes to the '
                                                                                         'Instrument Preset state; if it fails the failure codes show in the four display fields.')],
            facts=[('Test', p['description']), ('Specification', p['page'])], caution='RF can be on at power-up: keep the output unconnected until the self test is over.',
            ok='Self test finished - continue', parent=self.root)

    def _selftest_done(self, points, i, p, key):
        passed = port.ask_yes_no('Power-on self test', 'Did the self test pass (Instrument Preset state, no failure code in the display)?\n\nYes = passed, No = failed.')
        reading = 1.0 if passed else 0.0

        def work():
            try:
                self.io.after_power_cycle()
                port.post(self.root, lambda: self._after_selftest(points, i, p, key, reading))
            except Exception as exc:
                err = exc
                port.post(self.root, lambda err=err: self._error(err))
        self.status.set('Restoring the remote state of the 6060A ...')
        threading.Thread(target=work, daemon=True).start()

    def _after_selftest(self, points, i, p, key, reading):
        self._finish_point(p, reading, False); port.after(self.root,30, lambda: self._next(points, i + 1, key))

    # ---- THD at 10 kHz typed from the technician's analyzer (the RF output is ON while the number is asked for)
    def _typed_point(self, points, i, p, key, typed):
        self.status.set(f'Point {p["id"]}: read your distortion analyzer and type the value (RF output is ON).')
        entered = self.mo_ask(p, reason=typed.reason, cancel_text='Stop run')
        try: self.io.standby()
        except Exception as exc: self._error(exc); return
        self._mo_current = None
        if entered is None:
            self.busy = False; self.status.set('Run stopped: no reading was typed. The RF output is OFF.'); return
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
        """The reading failed (timeout, unreadable, no instrument connected). The RF output is already off: ask for the reading and carry on, or stop as before."""
        typed = self.mo_failed(p, exc)
        self._mo_current = None
        if typed is None: self._error(exc); return
        self.mo_commit(p, typed, auto=None, why=str(exc))
        port.after(self.root,30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self._mo_current = None; self._mo_pending = None
        if self.io is not None and not self.demo:
            try: self.io.standby()                          # a stopped run leaves the RF output (and the LF generator) off
            except Exception: pass
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, manual=False, extra=None):
        result = 'PASS' if judge(p, reading) else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, manual=bool(manual) or self.is_manual(p),
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields(), **(extra or {}))
        self._update_row(p); self.save(silent=True)
        self._derive_after(p)

    # ---- derived points (4A-5 section errors and their sum)
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
        """A section reading was recorded or replaced (also a typed one): every derived point that uses it and has all its inputs is computed again."""
        if p['meas'] == 'derived':
            return
        for q in POINTS:
            if q['meas'] == 'derived' and p['ref'] in q['derive']['inputs']:
                self._derive_point(q)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, thd_typed=bool(self.thd_typed.get()),
                                        lf_model=self.lf_model.get(), **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.thd_typed.set(bool(data.get('thd_typed', self.thd_typed.get())))
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
            if not self.active(p): continue
            row = self.found_left_row(p, lambda r, p=p: self.point_row(p, r))
            if row: rows.append(row); pts.append(p)
        return rows, pts

    def point_row(self, p, r):
        """One report row. No uncertainty is printed (the suite has no uncertainty for these RF measurements; the cover sheet from the other software carries the standards)."""
        import report_pdf
        note = '' if p['unit'] != '' else ' (1 = passed)'
        return report_pdf.cert_row(p['description'] + note, p['nominal'], p['low'], p['high'], p['unit'], r['reading'], r['result'] == 'FAIL', section=self.report_section(p))

    def export_pdf(self):
        rows, pts = self.certificate_rows_and_points()
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details(f'Fluke {MODEL} performance verification', parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        try:
            header = [('Instrument', f'Fluke {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                      ('Limits applied', 'Fluke 6060A Instruction Manual, Section 4A'), ('Source', SPEC['source']['cite'])]
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


def main(argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        App(root, MODEL, demo='--demo' in argv)
    port.run_app(build)
