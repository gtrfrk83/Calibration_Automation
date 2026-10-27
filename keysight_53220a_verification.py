"""Keysight 53210A / 53220A / 53230A universal frequency counter / timer performance verification, driven from the manufacturer's Performance Tests chapter.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_53220a_pv.json, built by specs/build_53220a_spec.py from the Keysight
53210A/53220A/53230A Assembly Level Service Guide, chapter 1 Performance Tests (the record pages 90-99 carry the limits).  Two-way: the program configures the
counter over USB, LAN or GPIB (set, read back, compare; the error queue is checked; nothing is written twice), makes 100 readings on one software trigger and judges the counter's
own Mean or Std Dev.  Stimulus: the Fluke 96270A RF reference source where it can make the signal, otherwise the standard the operator connects (the prompt names it).
Hardware I/O is OFF in demo mode.  Never run unattended: wiring confirmations are required.

    import keysight_53220a_verification
    keysight_53220a_verification.main()                      # what Procedures/Keysight_53220A_Verification.py does
    keysight_53220a_verification.main(model='53230A')        # what Procedures/Keysight_53230A_Verification.py does

Model family: ONE spec and ONE engine for the 53210A, 53220A and 53230A.  The spec's models{} block carries the per-model flags and each point carries a limit per model
(a point without a limit for the model does not apply to it: Channel 2 and the time tests on the 53210A, the burst tests on the 53220A / 53210A).  Options are declared by
the operator (and filled in from *OPT? at connect): 010 time base, 106 / 115 microwave channel, 150 pulse microwave (53230A), 201 rear inputs (operator only).
"""
import json, math, sys, threading, time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, report_filename, Settings); the window code is in keysight_53220a_view_qt.py
import drivers
from drivers import keysight_53220a as k53        # not exported by drivers/__init__ (it inherits surprise.SurpriseMixin, which imports the drivers package)
import appdata
import datamode
import procmods_engine
import reset_startup
import surprise
import virtualbench
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)

MODEL = '53220A'
SPEC_PATH = HERE / 'specs' / 'keysight_53220a_pv.json'
PERIODS = {'1 year or less': '1y', 'More than 1 year': 'gt1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
INTERFACES = ('USB', 'LAN', 'GPIB')
DEFAULT_ADDR = {'USB': 'USB0::0x0957::0x0000::MY00000000::INSTR', 'LAN': 'TCPIP0::192.168.0.10::inst0::INSTR', 'GPIB': 'GPIB0::3::INSTR'}      # UNVERIFIED examples: press Find instruments
DEFAULT_RF_ADDR = 'GPIB0::4::INSTR'                                                                                                          # UNVERIFIED example
TB_CHOICES = ('Standard time base', 'Option 010 (OCXO)')
CH3_CHOICES = ('No microwave channel', 'Option 106 (6 GHz)', 'Option 115 (15 GHz)')
STIM_CHOICES = ('Fluke 96270A where it can', 'Other standards for every test')
PULSE_GEN_CHOICES = ('Pulse generator: Keysight 81134A or equivalent', 'Pulse generator: Agilent 33250A')
# The Agilent 33250A as the pulse generator for Tests 4a, 4b and 5 (owner decision 2026-10-27).  From the Agilent 33250A User's Guide, read as page images (printed pages): pulse width
# 8 ns minimum (p. 167, p. 320), edge time 5 ns minimum (p. 168), width at least 1.6 x edge time (p. 167), period 20 ns minimum (p. 166), 10 Vpp into 50 ohm (p. 320), ONE Output
# connector plus a Sync output that is a 50 % duty square wave for pulses (p. 62).  Single source: drivers/keysight_53220a.PULSE_LIMITS.  The pulse automation (AgilentAFGPulse.pulse) exists, but
# no pulse point of the chapter is within these limits, so no point is routed to it; tests/test_keysight_53220a_points.py fails if a point becomes feasible (it must then be routed).
GEN_33250A = dict(name='Agilent 33250A', min_width_s=max(k53.PULSE_LIMITS['min_width_s'], 1.6 * k53.PULSE_LIMITS['min_edge_s']), min_edge_s=k53.PULSE_LIMITS['min_edge_s'],
                  min_period_s=k53.PULSE_LIMITS['min_period_s'], max_vpp=k53.PULSE_LIMITS['max_vpp'], outputs=1)
REF_CHOICES = ('House 10 MHz standard', '96270A 10 MHz Ref Out')
# 96270A output routes: Leveling Head 1 mHz to 4.024 GHz, -130 to +24 dBm; Microwave O/P direct to 27 GHz, -4 to +24 dBm (-100 dBm with the Extended Low Level option).  The route is a
# front-panel choice (no remote command is documented: UNVERIFIED), so the hook-up prompt names it.
LH_MAX_HZ, MW_MAX_HZ = 4.024e9, 27e9
LH_MIN_DBM, RF_MAX_DBM = -130.0, 24.0
MW_MIN_DBM, MW_MIN_DBM_EXT = -4.0, -100.0     # the owner's 96270A has NO Extended Low Level (2026-10-27): above 4 GHz the Microwave O/P is used and its floor is -4 dBm
INPUT_CAP_DBM = 10.0           # the level at the counter input is never planned above this (a conservative guard, UNVERIFIED against the input damage level)
GROUP_TITLE = {'TIMEBASE': 'absolute time base', 'CH1': 'Channel 1', 'CH2': 'Channel 2', 'CH3_LH': 'microwave channel (from the Leveling Head)', 'CH3_MW': 'microwave channel (from the Microwave O/P)',
               'PULSE_CH1': 'pulse width, Channel 1', 'PULSE_CH2': 'pulse width, Channel 2', 'TINT': 'time interval, Channel 1 to Channel 2', 'BURST': 'pulse burst frequency',
               'NONE': 'self-test'}
STIM_NEEDS = {'PULSE': 'Pulse generator: 5 ns pulse width +/- 40 ps, 1 Vpp, period 66.6 ns, two outputs 49.9 ns apart for the time interval test (Keysight 81134A in the manual)',
              'BURST': 'Pulse-modulated microwave signal generator: 100 MHz to 15 GHz, pulse width accuracy +/- 10 %, PRI 1 ms (Keysight E8257D-520-UNW in the manual); the 96270A has no pulse modulation',
              'MW': 'External attenuator after the 96270A Microwave O/P (the Microwave O/P gives -4 dBm at best) and a power meter to verify the level at the counter input, as the manual asks',
              'LH': 'Signal generator (the manual names an SRS CG635)'}


def load_spec(path=None):
    spec = json.loads(Path(path or SPEC_PATH).read_text(encoding='utf-8'))
    if spec.get('kind') != 'counter-pv':
        raise ValueError(f'{path or SPEC_PATH}: not a counter-pv spec')
    return spec


def flatten(spec):
    """The points of every section, in order, with a running id and the section title."""
    points = []
    for sec in spec['sections']:
        for p in sec['points']:
            q = dict(p)
            q['section_id'], q['section_title'] = sec['id'], sec['title']
            q['test_no'], q['test'] = q['test'], 'numeric'            # 'test' is the engines' check type (uncertainty_expect reads it); the manual's test number is test_no
            q['id'] = len(points) + 1
            points.append(q)
    return points


def _hz(v):
    return ui.si_row([v], 'Hz')[0][0] + ' ' + ui.si_row([v], 'Hz')[2]


def _tm(v):
    return ui.si_row([v], 's')[0][0] + ' ' + ui.si_row([v], 's')[2]


def micro_channel(model):
    return SPEC['models'][model]['micro_channel']


def chan_name(p, model=None):
    ch = p.get('channel')
    if ch == 12:
        return 'Ch 1 to Ch 2'
    if ch == 3:
        return f'Ch {micro_channel(model or MODEL)} (microwave)' if (model or MODEL) == '53210A' else 'Ch 3 (microwave)'
    return f'Ch {ch}' if ch else ''


def describe(p, model=None):
    """The test point's name in the table and the report."""
    if p['func'] == 'TST':
        return 'Operational verification: self-test (*TST?)'
    st = p['stimulus']
    body = {'FREQ': lambda: _hz(p['nominal']), 'SPER': lambda: f'Single period {_tm(p["nominal"])} ({_hz(st["frequency"])})',
            'PWID': lambda: f'Pulse width {_tm(p["nominal"])}', 'TINT': lambda: f'Time interval {_tm(p["nominal"])}',
            'BURST': lambda: f'{_hz(p["nominal"])} burst, {_tm(st["burst_width_s"])} wide'}[p['func']]()
    if p['ref'].startswith('1.'):
        body = 'Absolute time base ' + body
    return f'Test {p["test_no"]}: {body}, {chan_name(p, model)}, ' + ('Mean' if p['stat'] == 'mean' else 'Std Dev')


def hook_group(p):
    """The hook-up group (prompt and diagram key) of a point."""
    f, ch, g = p['func'], p.get('channel'), p['stimulus']['group']
    if f == 'TST':
        return 'NONE'
    if p['ref'].startswith('1.'):
        return 'TIMEBASE'
    if f == 'TINT':
        return 'TINT'
    if f == 'PWID':
        return 'PULSE_CH1' if ch == 1 else 'PULSE_CH2'
    if f == 'BURST':
        return 'BURST'
    if ch == 3:
        return 'CH3_MW' if g == 'MW' else 'CH3_LH'
    return 'CH1' if ch == 1 else 'CH2'


def apply_limits(points, model, period, timebase_opt):
    """Set low / high (and max for a Std Dev point) from the printed limits of the model, the period and the time-base option.  A point with no limit for the model does not apply."""
    for p in points:
        lim = p['limits'].get(model)
        p['applies_model'] = lim is not None
        if lim is None:
            p['low'] = p['high'] = None
            p['printed_limit'] = ''
            continue
        if p.get('limits_by') == 'timebase_option':
            lim = lim['010' if timebase_opt == '010' else 'std'][period]
        if p['stat'] == 'sdev':
            p['low'], p['high'] = 0.0, float(lim['max'])
        else:
            p['low'], p['high'] = float(lim['low']), float(lim['high'])
        p['printed_limit'] = lim['printed']


SPEC = load_spec()
POINTS = flatten(SPEC)
for _p in POINTS:
    _p['group'] = hook_group(_p)
    _p['description'] = describe(_p)
apply_limits(POINTS, MODEL, SPEC['default_period'], 'std')
MODELS = tuple(SPEC['models'])


def model_info(model=None):
    return SPEC['models'][model or MODEL]


def configure(model=MODEL):
    """Select the model of the family.  Descriptions, the counter driver, the settings / checkpoint names and the wording of the prompts follow."""
    global MODEL
    if model not in SPEC['models']:
        raise ValueError(f'unknown model {model!r}: expected one of {", ".join(SPEC["models"])}')
    MODEL = model
    for p in POINTS:
        p['description'] = describe(p, model)
    apply_limits(POINTS, model, SPEC['default_period'], 'std')
    return MODEL


def counter_class(model=None):
    return {'53210A': k53.Keysight53210A, '53230A': k53.Keysight53230A}.get(model or MODEL, k53.Keysight53220A)


def find_diagram(src, group):
    """Hook-up picture: diagrams/hook_53220a_<src>_<GROUP>.png, then diagrams/hook_53220a_<GROUP>.png (diagrams/README_53220a.txt).  src is '96270A' or 'manual'.
    A 53230A / 53210A looks for its own hook_53230a_ / hook_53210a_ names first."""
    names = [f'hook_53220a_{src}_{group}', f'hook_53220a_{group}']
    if MODEL != '53220A':
        names = [f'hook_{MODEL.lower()}_{src}_{group}', f'hook_{MODEL.lower()}_{group}'] + names
    for name in names:
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def to_visa(text, interface='USB', default_gpib=True):
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    if t.upper().startswith('COM') and t[3:].isdigit():
        return f'ASRL{int(t[3:])}::INSTR'
    if interface == 'GPIB' or default_gpib:
        if t.isdigit() and 0 <= int(t) <= 30:
            return f'GPIB0::{int(t)}::INSTR'
    raise ValueError('Enter a GPIB address (0 to 30) or a full VISA resource (USB0::..., TCPIP0::...::inst0::INSTR, GPIB0::n::INSTR, COM port).')


def judge(p, reading) -> bool:
    """PASS when the reading is inside the printed limits, in Decimal (the float reading is taken at its shortest exact text).  Mean: low <= x <= high.
    Std Dev: 0 <= x < the printed maximum (the tables print '<').  Self-test: 0."""
    x = Decimal(repr(float(reading)))
    if p['stat'] == 'sdev':
        return Decimal(0) <= x < Decimal(repr(p['high']))
    if p['stat'] == 'pass':
        return x == 0
    return Decimal(repr(p['low'])) <= x <= Decimal(repr(p['high']))


def pulse_shortfalls(st, gen=GEN_33250A):
    """What the pulse generator cannot do of the settings a pulse point asks for (empty = it can).  st: the point's stimulus dict."""
    out = []
    w = st.get('width_s')
    if w is not None and w < gen['min_width_s']:
        out.append(f'pulse width {_tm(w)} is below its minimum pulse width ({_tm(gen["min_width_s"])})')
    if w is not None and w < 1.6 * gen['min_edge_s'] * (1 - 1e-12):
        out.append(f'the pulse width must be at least 1.6 x the edge time and the edge time is {_tm(gen["min_edge_s"])} at best, so {_tm(1.6 * gen["min_edge_s"])} at least')
    if st.get('period_s') is not None and st['period_s'] < gen['min_period_s']:
        out.append(f'period {_tm(st["period_s"])} is below its minimum ({_tm(gen["min_period_s"])})')
    if st.get('vpp') is not None and st['vpp'] > gen['max_vpp']:
        out.append(f'{st["vpp"]:g} Vpp is above its maximum ({gen["max_vpp"]:g} Vpp into 50 ohm)')
    if st.get('delay_s') and gen['outputs'] < 2:
        out.append(f'the time interval test needs two outputs {_tm(st["delay_s"])} apart and it has one output (plus a Sync output)')
    return out


def plan_stimulus(p, stim):
    """How a point is stimulated.  stim: dict(mode 'auto' | 'manual', rf True/False (a 96270A is connected), loss_db, ext_low, pulse_gen '81134A' | '33250A').
    Returns dict(mode 'rf' | 'manual' | 'none', route 'LH' | 'MW' | None, level_set, atten_db, reason).  atten_db: the external attenuation the technician must fit after the 96270A
    Microwave O/P when the level at the counter is below what that output can make (the level is kept as printed).  Raises ValueError when the level would exceed the input guard."""
    st = p['stimulus']
    g = st['group']
    if g == 'NONE':
        return dict(mode='none', route=None, level_set=None, atten_db=0.0, reason='')
    target = st.get('level_dbm')
    if target is not None and target > INPUT_CAP_DBM:
        raise ValueError(f'{p["description"]}: {target:g} dBm at the counter is above the {INPUT_CAP_DBM:g} dBm guard')
    if g == 'PULSE':
        if stim.get('pulse_gen') == '33250A':
            short = pulse_shortfalls(st)
            if st.get('delay_s'):
                short.append('it has ONE output and this test needs two outputs ' + _tm(st['delay_s']) + ' apart')
            if short:
                return dict(mode='manual', route=None, level_set=None, atten_db=0.0, reason='The Agilent 33250A cannot make this signal: ' + '; '.join(short) + '. Use ' + STIM_NEEDS['PULSE'])
            if stim.get('mode') == 'auto' and stim.get('gen'):
                return dict(mode='pulse', route=None, level_set=None, atten_db=0.0, reason='')
            return dict(mode='manual', route=None, level_set=None, atten_db=0.0,
                        reason='No Agilent 33250A is connected (enter its address and press Test connections), or the stimulus is another standard')
        return dict(mode='manual', route=None, level_set=None, atten_db=0.0, reason=STIM_NEEDS[g])
    if g == 'BURST':
        return dict(mode='manual', route=None, level_set=None, atten_db=0.0, reason=STIM_NEEDS[g])
    if stim.get('mode') != 'auto' or not stim.get('rf'):
        return dict(mode='manual', route=None, level_set=None, atten_db=0.0, reason='The selected stimulus is another standard' if stim.get('mode') != 'auto' else 'No 96270A is connected')
    f, loss = st['frequency'], float(stim.get('loss_db') or 0.0)
    level = target + loss
    if g == 'LH' and f <= LH_MAX_HZ:
        if LH_MIN_DBM <= level <= RF_MAX_DBM:
            return dict(mode='rf', route='LH', level_set=level, atten_db=0.0, reason='')
        return dict(mode='manual', route=None, level_set=None, atten_db=0.0, reason=f'{level:g} dBm is outside the Leveling Head range ({LH_MIN_DBM:g} to {RF_MAX_DBM:g} dBm)')
    floor = MW_MIN_DBM_EXT if stim.get('ext_low') else MW_MIN_DBM
    if f > MW_MAX_HZ or level > RF_MAX_DBM:
        return dict(mode='manual', route=None, level_set=None, atten_db=0.0, reason=f'{f / 1e9:g} GHz at {level:g} dBm is outside the 96270A Microwave O/P range')
    if level >= floor:
        return dict(mode='rf', route='MW', level_set=level, atten_db=0.0, reason='')
    atten = floor - level        # the Microwave O/P is set to its floor; the difference is the attenuation needed between it and the cable to the counter (arithmetic only, not a manual value)
    return dict(mode='rf', route='MW', level_set=floor, atten_db=atten,
                reason=f'The 96270A Microwave O/P cannot make {level:g} dBm (its floor is {floor:g} dBm): it is set to {floor:g} dBm and {atten:g} dB of external attenuation is needed before the counter input')


def gen_ok(p, pulse_gen):
    """A point made for one pulse generator exists only with that generator (the 5 ns pulse points: the 81134A or equivalent; the 8 ns ones: the Agilent 33250A, which cannot make 5 ns)."""
    return not p.get('gen') or p['gen'] == pulse_gen


def points_for(model, options, quick=False, pulse_gen='81134A'):
    """The test points that exist for a model with the declared options (the manual's option columns): a point needs a printed limit for the model and every option it lists
    (201 only changes the hook-up text).  Independent of the window: the window uses the same rule."""
    have = set(options)
    return [p for p in POINTS if p['limits'].get(model) is not None and set(p.get('requires', [])) - {'201'} <= have and (p['quick'] or not quick) and gen_ok(p, pulse_gen)]


def counts_text(model, options, pulse_gen='81134A'):
    full, quick = points_for(model, options, pulse_gen=pulse_gen), points_for(model, options, True, pulse_gen)
    tests = {}
    for p in full:
        tests[p['test_no']] = tests.get(p['test_no'], 0) + 1
    return f'{len(full)} test points ({len(quick)} in the quick check): ' + ', '.join(f'{k} x{v}' for k, v in tests.items())


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the counter under test and the Fluke 96270A (when used), both through the instrument drivers."""

    def __init__(self, ctr_address, rf_address, interface='USB', transports=None, mods=None, virtual=False, surprise_handler=None, stim=None, gen_address='', gen_transport=None):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        self.stim = dict(stim or {}, rf=False, gen=False)
        self.cache = None                  # (ref, stats) of the last Mean point: the Std Dev point of the same measurement reuses the same 100 readings
        self.rf = None
        self.gen = None                    # the Agilent 33250A as the pulse generator (Tests 4a / 4b at 8 ns), when its address was given
        if transports:
            ctr_t, rf_t = transports[0], transports[1]
            gen_transport = gen_transport or (transports[2] if len(transports) > 2 else None)
        else:
            ctr_t = drivers.open_visa(to_visa(ctr_address, interface, default_gpib=False), timeout=20)
            rf_t = drivers.open_visa(to_visa(rf_address), timeout=20) if rf_address.strip() else None
            if gen_transport is None and str(gen_address).strip():
                gen_transport = drivers.open_visa(to_visa(gen_address), timeout=20)
        self.ctr = counter_class()(ctr_t, self.log, label=MODEL)
        try:
            self.ctr.connect()
            self.ctr.check_errors('connecting')
            if rf_t is not None:
                self.rf = k53.Fluke96270AWide(rf_t, self.log, label='96270A')
                self.rf.connect()
                self.stim['rf'] = True
            if gen_transport is not None:
                self.gen = k53.AgilentAFGPulse(gen_transport, self.log, label='33250A')
                self.gen.connect()
                self.gen.check_errors('connecting')
                self.stim['gen'] = True
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.ctr.idn
        self.guards = []
        if surprise_handler is not None:
            self.enable_surprise(surprise_handler)

    def enable_surprise(self, handler, force=False):
        """Stop on surprise (surprise.py, opt-in).  The counter's set-and-read-back mismatch and statistics replies, and the 96270A's error queue, are Stop-only surprises.  A virtual (demo)
        command log is left alone unless force=True (tests)."""
        self.guards = [g for g in (surprise.attach_guard(self.ctr, handler, force, expect={'calc.mean': 'float', 'calc.sdev': 'float', 'calc.count': 'float'}, stop_only=True),
                                   surprise.attach_guard(self.rf, handler, force, stop_only=True) if self.rf else None,
                                   surprise.attach_guard(self.gen, handler, force, stop_only=True) if self.gen else None) if g]
        return self.guards

    def reset_roles(self):
        return ([d for d in (self.rf, self.gen) if d]), [self.ctr]

    def pm_drivers(self):
        return tuple(d for d in (self.ctr, self.rf, self.gen) if d is not None)

    def standby(self):
        if self.rf is not None:
            self.rf.output(False)
        if self.gen is not None:
            self.gen.output(False)

    def close(self):
        try: self.standby()
        except Exception: pass
        try:
            if self.rf is not None: self.rf.cleanup()
        except Exception: pass
        try:
            if self.gen is not None: self.gen.cleanup()
        except Exception: pass
        try: self.ctr.cleanup()                       # the reference oscillator settings as found, then local (GTL on GPIB)
        except Exception: pass
        for obj in (self.ctr, self.rf, self.gen):
            try:
                if obj is not None: obj.close()
            except Exception: pass
        self.save_log()

    def save_log(self):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt (a virtual demo session writes nothing)."""
        if virtualbench.log_is_virtual(self.log): return
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  Keysight {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def settle(self, p, route):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        if route == 'MW': return self.pm_param('a53220a.settle.mw', 3.0)
        if route == 'LH': return self.pm_param('a53220a.settle.lh', 2.0)
        if route == 'PULSE': return self.pm_param('a53220a.settle.pulse', 1.0)
        return self.pm_param('a53220a.settle.manual', 2.0)

    def meter_point(self, p):
        return dict(p, gate_s=p.get('gate_s'))

    def stats(self, p, plan):
        """Mean and Std Dev of 100 readings for the point; the Std Dev point reuses the readings of the Mean point just measured."""
        parent = p.get('parent')
        if parent and self.cache and self.cache[0] == parent:
            return self.cache[1]
        if p['timebase']:
            self.ctr.set_reference(p['timebase'])
        surprise.checked(self.ctr, self.ctr.configure_point, self.meter_point(p), kind='readback', expected='the value that was set', stop_only=True)
        if plan['mode'] == 'rf':
            st = p['stimulus']
            self.rf.set_rf(st['frequency'], plan['level_set'])
            surprise.checked(self.rf, self.rf.check_error, p['description'], stop_only=True)       # the source refuses what it cannot make; never operate then
            self.rf.output(True)
            time.sleep(virtualbench.scaled(self.settle(p, plan['route']), self.virtual))
        elif plan['mode'] == 'pulse':
            st = p['stimulus']
            self.gen.pulse(st['period_s'], st['width_s'], vpp=st['vpp'])                       # set, read back, compared, error queue read (the driver); the output is still OFF
            self.gen.output(True)
            time.sleep(virtualbench.scaled(self.settle(p, 'PULSE'), self.virtual))
        elif plan['mode'] == 'manual':
            time.sleep(virtualbench.scaled(self.settle(p, None), self.virtual))
        res = self.ctr.measure_stats()
        self.ctr.check_errors('reading ' + p['description'])
        self.cache = (p['ref'], res)
        return res

    @procmods_engine.point_commands()
    def measure(self, p):
        """One test point: returns the reading (the Mean, the Std Dev, or the *TST? result)."""
        self.standby()
        try:
            if p['func'] == 'TST':
                self.cache = None
                value = self.ctr.self_test()
                self.ctr.check_errors('self-test')
                return float(value)
            plan = plan_stimulus(p, self.stim)
            res = self.stats(p, plan)
            return float(res['sdev'] if p['stat'] == 'sdev' else res['mean'])
        finally:
            self.standby()


class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root, demo=False, fast_demo=False):
        self.init_virtual(demo, fast_demo)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('a53220a', MODEL, demo=demo, lists=[POINTS], shape='band')     # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(f'Keysight{MODEL}')
        s = self.settings

        def pick(key, choices, default):
            v = s.get(key, default)
            return v if v in choices else default
        self.asset = port.var(); self.serial = port.var()
        self.interface = port.var(pick('interface', INTERFACES, 'USB'))
        self.addrs = {i: s.get(f'ctr_addr_{i}', DEFAULT_ADDR[i]) for i in INTERFACES}
        self._iface_shown = self.interface.get()
        self.ctr_addr = port.var(self.addrs[self._iface_shown])
        self.rf_addr = port.var(s.get('rf_addr', DEFAULT_RF_ADDR))
        self.gen_addr = port.var(s.get('gen_addr', ''))                # the Agilent 33250A (pulse generator); empty = another pulse generator, set by hand
        self.period = port.var(pick('period', PERIODS, PERIOD_LABEL[SPEC['default_period']]))
        self.tb_opt = port.var(pick('tb_opt', TB_CHOICES, TB_CHOICES[0]))
        self.ch3_opt = port.var(pick('ch3_opt', CH3_CHOICES, CH3_CHOICES[0]))
        self.pulse_opt = port.var(s.get('pulse_opt', 'no') == 'yes', 'bool')
        self.rear_opt = port.var(s.get('rear_opt', 'no') == 'yes', 'bool')
        self.stim_mode = port.var(pick('stim_mode', STIM_CHOICES, STIM_CHOICES[0]))
        self.pulse_gen = port.var(pick('pulse_gen', PULSE_GEN_CHOICES, PULSE_GEN_CHOICES[0]))
        self.opts_declared = False         # True once the technician touched an option selector (or loaded a checkpoint): *OPT? then only warns, the technician's selection decides
        self.atten = {}
        self.ref_mode = port.var(pick('ref_mode', REF_CHOICES, REF_CHOICES[0]))
        self.loss = port.var(s.get('loss_db', '0'))
        self.ext_low = port.var(s.get('ext_low', 'no') == 'yes', 'bool')
        self.test_set = port.var('Full verification')
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set(virtualbench.status_text(self) if demo
                        else 'Step 1: enter the Instrument ID. Step 2: declare the options, choose the interface and addresses and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    VIEW = 'keysight_53220a_view'                          # window code: keysight_53220a_view_qt.py

    @property
    def ui_view(self): return port.view(self.VIEW)

    # the options the operator declared (or the counter reported at connect)
    def option_codes(self):
        codes = set()
        if self.tb_opt.get() == TB_CHOICES[1]: codes.add('010')
        if self.ch3_opt.get() == CH3_CHOICES[1]: codes.add('106')
        if self.ch3_opt.get() == CH3_CHOICES[2]: codes.add('115')
        if self.pulse_opt.get(): codes.add('150')
        if self.rear_opt.get(): codes.add('201')
        return codes

    def timebase_opt(self):
        return '010' if '010' in self.option_codes() else 'std'

    def stim_state(self):
        try: loss = float(str(self.loss.get()).replace(',', '.') or 0)
        except ValueError: loss = 0.0
        rf = (self.io.rf is not None) if self.io is not None else (bool(self.rf_addr.get().strip()) or self.virtual)         # once connected, what is really connected
        gen = (self.io.gen is not None) if self.io is not None else (bool(self.gen_addr.get().strip()) or self.virtual)
        return dict(mode='auto' if self.stim_mode.get() == STIM_CHOICES[0] else 'manual', rf=rf, gen=gen, loss_db=loss, ext_low=bool(self.ext_low.get()),
                    pulse_gen='33250A' if self.pulse_gen.get() == PULSE_GEN_CHOICES[1] else '81134A')

    def plan(self, p):
        try: return plan_stimulus(p, self.stim_state())
        except ValueError as exc: return dict(mode='manual', route=None, level_set=None, reason=str(exc), blocked=True)

    def is_manual(self, p): return self.plan(p)['mode'] == 'manual'

    def manual_reason(self, p): return self.plan(p)['reason'] if self.is_manual(p) else ''

    def applicable(self, p):
        """Does the point exist for this model and these options?"""
        if not p.get('applies_model'): return False
        if not gen_ok(p, self.stim_state()['pulse_gen']): return False          # the 5 ns points belong to the 81134A, the 8 ns ones to the 33250A
        need = {c for c in p.get('requires', []) if c != '201'}
        return need <= self.option_codes()

    def active(self, p):
        if not self.applicable(p): return False
        if p.get('skip'): return False                               # a point skipped by a procedure modification
        if self.test_set.get().startswith('Quick') and not p['quick']: return False
        return True

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    # ------------------------------------------------------------------ layout
    def _build_ui(self): self.ui_view.build_ui(self)

    def on_interface(self):
        old, new = self._iface_shown, self.interface.get()
        if new == old: return
        self.addrs[old] = self.ctr_addr.get()
        self.ctr_addr.set(self.addrs[new]); self._iface_shown = new
        self.ui_view.set_choices(self, 'ctr', ())
        if not self.demo: self._save_settings()

    def pm_driver_classes(self): return (counter_class(), k53.Fluke96270AWide)

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_53220a import make_53220a_bench

        def build(mods):
            bench, rft, ct = make_53220a_bench(MODEL, 'USB')
            self._prepare_bench(bench, p)
            return IO('sim', 'sim', 'USB', transports=(ct, rft), mods=mods, stim=self.stim_state())
        return procmods_plan.run_plan(self.pm_state, build, lambda io: io.measure(p))

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
        cells, tags = self.shell_cells(p['id'], p['nominal'] if p['stat'] == 'mean' else 0.0, p['low'], p['high'], p['unit'])
        mark = (' ★' if p['quick'] else '') + (' [other standard]' if p['stimulus']['group'] != 'NONE' and self.is_manual(p) else '') + (' [+attenuator]' if self.plan(p).get('atten_db') else '')
        return (p['id'], p['description'] + mark, *cells), tags

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
        """The period or the time-base option changed: the limits come from the tables, so take the modifications off, apply, put them back, and re-judge stored readings."""
        self.pm_revert(POINTS)
        apply_limits(POINTS, MODEL, PERIODS[self.period.get()], self.timebase_opt())
        self.pm_apply(POINTS)
        for records in (self.found, self.left):
            for key, rec in records.items():
                p = POINTS[int(key) - 1]
                if p.get('low') is not None: rec['result'] = 'PASS' if judge(p, rec['reading']) else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_options(self):
        """The technician declared an option: the points that need it appear or go; Test 1 changes limits with the time-base option.  From now on *OPT? only warns."""
        self.opts_declared = True
        self._options_changed()

    def _options_changed(self):
        self.reset_forget()
        self.on_period()
        if hasattr(self, 'status'): self.status.set(f'{MODEL} with {", ".join(sorted(self.option_codes())) or "no options"}: ' + counts_text(MODEL, self.option_codes(), self.stim_state()['pulse_gen']))

    def on_pulse_gen(self):
        """The pulse generator choice changed: the pulse points that belong to the other generator go and the ones for this one appear (the 33250A runs Tests 4a / 4b at 8 ns)."""
        self._options_changed()
        self._save_settings()

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['low'], p['high']], p['unit'])
        flags = ('  |  ' + '; '.join(p['flags'])) if p.get('flags') else ''
        why = self.manual_reason(p)
        att = self.plan(p).get('atten_db')
        stim = f'Other standard: {why}' if why else ('Agilent 33250A (set and switched on by the program)' if self.plan(p)['mode'] == 'pulse' else '96270A' + (f' with {att:g} dB external attenuation: {self.plan(p)["reason"]}' if att else '') if p['stimulus']['group'] != 'NONE' else 'none')
        self.detail.set(f'{p["description"]}\nManual page {p["page"]}{flags}\n'
                        f'Setup: {self.setup_text(p)}\nStimulus: {stim}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    # ------------------------------------------------------------------ wiring text
    def stim_text(self, p):
        st = p['stimulus']
        g = st['group']
        if g == 'NONE': return ''
        if g == 'PULSE':
            t = f'pulse width {_tm(st["width_s"])}, period {_tm(st["period_s"])}, {st["vpp"]:g} Vpp'
            return t + (f', second output delayed {_tm(st["delay_s"])} from the first' if st.get('delay_s') else '')
        if g == 'BURST':
            return f'{_hz(st["frequency"])} at {st["level_dbm"]:g} dBm, pulse modulated: width {_tm(st["burst_width_s"])}, PRI {_tm(st["pri_s"])}'
        return f'{_hz(st["frequency"])} sine at {st["level_dbm"]:g} dBm'

    def setup_text(self, p):
        g = p['group']
        base = '50 ohm cables (RG-58 in the manual). '
        rear = ' Use the rear-panel input (Option 201).' if '201' in self.option_codes() else ''
        ref = ('the 10 MHz reference from the 96270A REF OUT to the counter EXT REF IN (and the house standard to the 96270A reference input)' if self.ref_mode.get() == REF_CHOICES[1]
               else 'the house 10 MHz standard to the counter EXT REF IN')
        if g == 'NONE': return 'Nothing is connected for the self-test; the counter performs a Factory Reset afterwards.'
        if g == 'TIMEBASE':
            return base + f'Test 1 uses the INTERNAL time base. Signal to Channel 1 (50 ohm); the stimulus and the house standard must share the primary frequency standard (better than 1e-10). {self.stim_text(p)}.' + rear
        if g in ('CH1', 'CH2'):
            return base + f'{self.stim_text(p)} to Channel {1 if g == "CH1" else 2} (50 ohm, DC); {ref}.' + rear
        if g in ('CH3_LH', 'CH3_MW'):
            mw = 'the 96270A Microwave O/P' if g == 'CH3_MW' else 'the 96270A Leveling Head output'
            return base + f'{self.stim_text(p)} from {mw} to the microwave input ({chan_name(p)}); {ref}.' + rear
        if g in ('PULSE_CH1', 'PULSE_CH2'):
            return base + f'{"Agilent 33250A" if p.get("gen") == "33250A" else "Pulse generator"} output to Channel {1 if g == "PULSE_CH1" else 2}: {self.stim_text(p)}; {ref}.' + rear
        if g == 'TINT':
            return base + f'Pulse generator: both outputs to Channel 1 and Channel 2 with equal cable lengths: {self.stim_text(p)}; {ref}.' + rear
        return base + f'Pulse-modulated microwave generator to the microwave input: {self.stim_text(p)}; {ref}.' + rear

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        found = []
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        want = {'USB': 'USB', 'LAN': 'TCPIP', 'GPIB': 'GPIB'}[self.interface.get()]
        mine = [r for r in found if r.upper().startswith(want)]
        self.ui_view.set_choices(self, 'ctr', mine or found); self.ui_view.set_choices(self, 'rf', found); self.ui_view.set_choices(self, 'gen', found)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def _prepare_bench(self, bench, p):
        """The things the operator does that no command can: connect the standard a manual point needs, set the cable loss, connect the 10 MHz reference."""
        st = p['stimulus']
        bench.cable_loss_db = self.stim_state()['loss_db']
        bench.ext_ref_present = True
        bench.atten_db = self.plan(p).get('atten_db', 0.0)           # the external attenuator the technician fits after the Microwave O/P
        if st['group'] == 'NONE' or self.plan(p)['mode'] != 'manual':
            bench.external_signal = None
        elif st['group'] == 'PULSE':
            bench.external_signal = dict(kind='PULSE', f=0.0, width_s=st['width_s'], delay_s=st.get('delay_s', 0.0))
        elif st['group'] == 'BURST':
            bench.external_signal = dict(kind='BURST', f=st['frequency'], level_dbm=st['level_dbm'], burst_width_s=st['burst_width_s'])
        else:
            bench.external_signal = dict(kind='CW', f=st['frequency'], level_dbm=st['level_dbm'])

    def _new_io(self):
        stim = self.stim_state()
        if self.virtual:          # demo: the real IO / driver code over a simulated counter and 96270A
            from drivers.simulated_53220a import make_53220a_bench, DEFAULT_OPTIONS
            self._vb = make_53220a_bench(MODEL, self.interface.get(), getattr(self, 'virtual_options', None) or DEFAULT_OPTIONS[MODEL])
            use_rf = stim['mode'] == 'auto'
            use_gen = use_rf and stim['pulse_gen'] == '33250A'
            return IO('virtual', 'virtual', self.interface.get(), transports=(self._vb[2], self._vb[1] if use_rf else None, self._vb[0].gen_transport if use_gen else None), mods=self.pm_state, virtual=True, stim=stim)
        use_gen = stim['mode'] == 'auto' and stim['pulse_gen'] == '33250A'
        return IO(self.ctr_addr.get(), self.rf_addr.get() if stim['mode'] == 'auto' else '', self.interface.get(), mods=self.pm_state, surprise_handler=self._surprise_handler(), stim=stim,
                  gen_address=self.gen_addr.get() if use_gen else '')

    def _surprise_handler(self):
        if self.demo or self.fast_demo: return None
        if getattr(self, '_sp_handler', None) is None: self._sp_handler = port.surprise_handler(self.root)
        return self._sp_handler

    def apply_detected_options(self):
        """*OPT? pre-fills the option selectors, unless the technician already declared them: then a difference is only WARNED and the technician's selection decides.
        Returns the text for the connect message."""
        o = self.io.ctr.options or {}
        want = (TB_CHOICES[1] if o.get('timebase') == '010' else TB_CHOICES[0],
                {None: CH3_CHOICES[0], '106': CH3_CHOICES[1], '115': CH3_CHOICES[2]}.get(o.get('ch3'), CH3_CHOICES[0]), bool(o.get('pulse')))
        had = (self.tb_opt.get(), self.ch3_opt.get(), bool(self.pulse_opt.get()))
        text = f'Options read from the counter (*OPT? {o.get("raw", "")}): {want[0]}; {want[1]}; ' + ('Option 150 pulse' if want[2] else 'no Option 150')
        if o.get('unknown'): text += f'. Unrecognised option fields: {o["unknown"]}'
        names = lambda t: f'{t[0]}; {t[1]}; ' + ('Option 150' if t[2] else 'no Option 150')
        if self.opts_declared:
            if had != want: text += f'. WARNING: this differs from what you declared ({names(had)}). YOUR SELECTION IS USED; change the option selectors if the counter is right.'
            return text
        self.tb_opt.set(want[0]); self.ch3_opt.set(want[1]); self.pulse_opt.set(want[2])
        text += '. The option selectors were filled in from this; check them before the run.'
        self._options_changed()
        return text

    def test_connections(self):
        if self.fast_demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect(); self.io = self._new_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_settings()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        opt = self.apply_detected_options()
        rf = f'\n96270A: {self.io.rf.idn}' if self.io.rf is not None else '\nNo 96270A: every stimulus is another standard.'
        self.status.set('Connected: ' + self.io.ident + tag + '. Stimulus output is NOT enabled.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'Keysight {MODEL}: {self.io.ident}{rf}{tag}\n{opt}\nStimulus output is not enabled.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        self.addrs[self.interface.get()] = self.ctr_addr.get()
        for i in INTERFACES:
            self.settings.set(f'ctr_addr_{i}', self.addrs[i])
        for key, var in (('interface', self.interface), ('rf_addr', self.rf_addr), ('gen_addr', self.gen_addr), ('period', self.period), ('tb_opt', self.tb_opt), ('ch3_opt', self.ch3_opt), ('stim_mode', self.stim_mode),
                         ('ref_mode', self.ref_mode), ('loss_db', self.loss), ('pulse_gen', self.pulse_gen)):
            self.settings.set(key, var.get())
        for key, var in (('pulse_opt', self.pulse_opt), ('rear_opt', self.rear_opt), ('ext_low', self.ext_low)):
            self.settings.set(key, 'yes' if var.get() else 'no')
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

    def time_base_text(self): return 'Option 010 time base' if '010' in self.option_codes() else 'standard time base'

    def attenuation_needs(self, points):
        """[(name, need)] for the points that need external attenuation after the 96270A Microwave O/P."""
        need = sorted({self.plan(p)['atten_db'] for p in points if self.plan(p).get('atten_db')})
        return [('External attenuator', STIM_NEEDS['MW'] + ' (' + ' / '.join(f'{a:g} dB' for a in need) + ' for the cable loss set)')] if need else []

    def other_standards(self, points):
        """The standards the selected run needs besides the 96270A: [(name, need)] for the manual points."""
        out = {}
        for p in points:
            if p['stimulus']['group'] != 'NONE' and self.is_manual(p):
                out[p['stimulus']['group']] = STIM_NEEDS[p['stimulus']['group']]
        return list(out.items())

    def _prompt_start(self, points):
        """Warm-up, environment and the reference oscillator, asked once at the start of a run.  Returns False if the technician cancels."""
        steps = [('Warm-up', f'The {MODEL} must have warmed up for 45 minutes (2.5 hours after delivery, 72 hours if stored for months) (Service Guide p. 28). Allow the 96270A and the other standards their own warm-up.'),
                 ('Environment', 'Ambient 18 to 28 C (ideally 23 C +/- 1 C) and relative humidity below 80 % (p. 28).'),
                 ('Cables', '50 ohm cables (RG-58 in the manual); the counter inputs are set to 50 ohm, DC coupled.'),
                 ('10 MHz reference', 'Tests 2 to 7 use the EXTERNAL reference: ' + ('the house 10 MHz standard (better than 1e-10) to EXT REF IN.' if self.ref_mode.get() == REF_CHOICES[0] else
                  'the 96270A 10 MHz REF OUT to EXT REF IN, with the 96270A itself locked to the house standard. Test 1 uses the internal time base.') +
                  ' The program changes the reference setting (stored in non-volatile memory) and puts it back as found when the session ends.')]
        steps.insert(0, ('Installed options', f'Declared: {", ".join(sorted(self.option_codes())) or "none"} ({self.time_base_text()}). This run: ' + counts_text(MODEL, self.option_codes())
                         + '. Cancel and change the option selectors if this is not what the counter has (the counter reports its own options with *OPT? at connect; your selection decides).'))
        std = self.other_standards(points) + self.attenuation_needs(points)
        if std:
            steps.append(('Other standards needed', '; '.join(f'{k}: {v}' for k, v in std)))
        return port.operator_prompt('Before the verification', 'Warm-up and conditions', steps,
            facts=[('Limits', f'{self.period.get()}, {self.timebase_opt() == "010" and "Option 010" or "standard time base"}'), ('Options', ', '.join(sorted(self.option_codes())) or 'none'),
                   ('Stimulus', self.stim_mode.get()), ('Pulse generator', self.pulse_gen.get()), ('Interface', self.interface.get())],
            caution=f'The program restores the {MODEL} factory defaults (*RST) before the first point, then sets inputs, function, gate and trigger for every point.',
            ok='Conditions met - start', parent=self.root)

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.fast_demo and self.io is None: self.test_connections()
        if not self.fast_demo and self.io is None: return
        points = [q for q in points if self.active(q)]                     # the options read from the counter at connect may remove points
        if not points: self.status.set('None of the selected points applies to this counter and its options.'); return
        if not self.fast_demo and not self._prompt_start(points): self.status.set('Run not started: warm-up and conditions were not confirmed.'); return
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    def _prompt_setup(self, p, plan):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed), or the standard to set for a point on another standard."""
        group, manual = p['group'], plan['mode'] == 'manual'
        src = 'manual' if manual else ('33250A' if plan['mode'] == 'pulse' else '96270A')
        image = None if group == 'NONE' else (find_diagram(src, group) or (find_diagram('manual', group) if src == '33250A' else None))                 # the self-test connects nothing: no picture is expected
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Manual page', p['page'])]
        if image is None and group != 'NONE':
            facts.append(('Diagram', f'not installed (expected diagrams/hook_53220a_{src}_{group}.png)'))
        self.io.standby()
        if group == 'NONE':
            return port.operator_prompt('Self-test', 'Operational verification', [('Self-test', 'Disconnect all signals from the inputs. The self-test takes more than 5 seconds; the counter then resets to factory settings.')],
                                        facts=facts, caution='Nothing is connected.', ok='Start the self-test', image=image, parent=self.root)
        if manual:
            return port.operator_prompt('Connect the other standard', f'Set up for {GROUP_TITLE[group]}',
                [('Why', plan['reason']), ('Standard', STIM_NEEDS.get(p['stimulus']['group'], STIM_NEEDS['LH'])), ('Set the standard', self.stim_text(p) + f' (cable loss to allow for: {self.stim_state()["loss_db"]:g} dB)'),
                 ('Wiring', self.setup_text(p))],
                facts=facts, caution='Check the signal level against the counter input rating before connecting. The program reads the counter itself.', ok='Standard connected - measure', image=image, parent=self.root)
        if plan['mode'] == 'pulse':
            return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
                [('Output off', 'The Agilent 33250A output is switched off before you rewire.'), ('Wiring', self.setup_text(p)),
                 ('33250A', 'Its Output connector goes to the counter input (50 ohm). The program sets the pulse (' + self.stim_text(p) + ', edge time 5 ns), reads every setting back and switches the output on for the measurement only.')],
                facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image, parent=self.root)
        steps = [('Output off', 'The 96270A output is put in standby before you rewire.'), ('Wiring', self.setup_text(p))]
        if plan.get('atten_db'):
            steps.append(('External attenuation', f'{plan["reason"]}. Fit it between the Microwave O/P (or its cable) and the counter input. The level required at the counter input is '
                          f'{p["stimulus"]["level_dbm"]:g} dBm +/- 0.5 dBm (Service Guide p. 66): verify it with a power meter or use cables / an attenuator of certified loss. The attenuator value is the '
                          f'difference only; the manual lists no attenuator.'))
        if plan['route'] == 'MW':
            steps.append(('96270A output', 'Select the Microwave O/P (direct output) on the 96270A front panel; the program cannot select the route (no remote command is documented).'))
        elif plan['route'] == 'LH':
            steps.append(('96270A output', 'Select the Leveling Head output on the 96270A front panel and connect the head; the program cannot select the route (no remote command is documented).'))
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}', steps, facts=facts,
                                    caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image, parent=self.root)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            end = f' The counter is still under remote control: press Local on the {MODEL}.' if (self.interface.get() != 'GPIB' and not self.fast_demo) else ''
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.' + end); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root, 30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        plan = self.plan(p)
        self.atten[p['id']] = plan.get('atten_db', 0.0)
        if plan.get('blocked'):
            self._error(plan['reason']); return
        key = (p['group'], plan['mode']) if plan['mode'] != 'manual' else (p['group'], p.get('parent') or p['ref'])       # an other-standard point is set up for every measurement (its Std Dev shares it)
        if not self.fast_demo and key != previous and not self._prompt_setup(p, plan):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.virtual: self._virtual_operator(p)                       # the virtual operator does what the prompt asked
        if self.fast_demo:
            span = p['high'] - p['low']
            reading = (p['low'] + span * (0.5 + 0.38 * math.sin(p['id'] * 1.71))) if p['stat'] == 'mean' else (p['high'] * 0.3 if p['stat'] == 'sdev' else 0.0)   # deterministic, labelled synthetic
            self._record(p, reading, True, plan['mode']); port.after(self.root, 30, lambda: self._next(points, i + 1, key))
        else:
            stim = {k: v for k, v in self.stim_state().items() if k != 'rf'}        # read on the UI thread (Tk variables); a cable loss or stimulus change made after connecting applies to this point

            def work():
                try:
                    self.io.stim.update(stim)
                    reading = self.io.measure(p)
                    port.post(self.root, lambda: self._done(points, i, p, reading, key, plan['mode']))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _virtual_operator(self, p):
        """The hook-up actions no command can do, done on the simulated bench after the prompt: connect the other standard, the cable loss and the 10 MHz reference."""
        if self._vb: self._prepare_bench(self._vb[0], p)

    def _done(self, points, i, p, reading, key, mode):
        self._record(p, reading, bool(self.demo), mode); port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, mode='rf'):
        result = 'PASS' if judge(p, reading) else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()], stimulus=mode, atten_db=self.atten.get(p['id'], 0.0),
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields())
        self._update_row(p); self.save(silent=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'K{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, period=self.period.get(), tb_opt=self.tb_opt.get(), ch3_opt=self.ch3_opt.get(),
                                        pulse_opt=bool(self.pulse_opt.get()), rear_opt=bool(self.rear_opt.get()), **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.period.set(data.get('period', self.period.get()))
        if data.get('tb_opt') in TB_CHOICES: self.tb_opt.set(data['tb_opt'])
        if data.get('ch3_opt') in CH3_CHOICES: self.ch3_opt.set(data['ch3_opt'])
        self.pulse_opt.set(bool(data.get('pulse_opt', self.pulse_opt.get()))); self.rear_opt.set(bool(data.get('rear_opt', self.rear_opt.get())))
        self.opts_declared = True                                    # the results in the file were taken with these options
        self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
        self.on_period(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    @staticmethod
    def report_section(p):
        return p['section_title']

    @staticmethod
    def has_uncertainty(p):
        """True for the points that carry an Uncertainty: Mean frequency points (the 'Frequency - Measure' CMC alone, owner rule 2026-10-26) and Mean single-period points (that
        relative CMC times the period: derived, flagged).  Std Dev, pulse width, time interval, pulse burst and self-test points carry none: the scope has no CMC for them."""
        return p.get('stat') == 'mean' and p.get('func') in ('FREQ', 'SPER')

    @staticmethod
    def uncertainty_text(p):
        import report_pdf
        if not App.has_uncertainty(p): return ''
        if p['func'] == 'FREQ':
            return report_pdf.point_uncertainty(dict(kind='FREQ', nominal=p['nominal'], unit='Hz'))
        sc = report_pdf.scope()
        if sc is None: return ''
        import uncertainty
        f = p['stimulus']['frequency']
        value = sc.dmm('FREQ', f, None, None)
        return uncertainty.format_value(value / f * p['nominal'], 's') if value is not None else ''

    def standard_for(self, p):
        return None                  # the uncertainty of a frequency point is the CMC alone, never combined with the stimulus (owner rule)

    def certificate_rows(self):
        return self.certificate_rows_and_points()[0]

    def _cert_row(self, p, r):
        import report_pdf
        low, high = p['low'], p['high']
        text = {'mean': None, 'sdev': 'Std Dev (limit is a maximum)', 'pass': 'Self-test result (0 = pass)'}[p['stat']]
        suffix = ' [other standard]' if r.get('stimulus') == 'manual' else (f' [{r["atten_db"]:g} dB external attenuator]' if r.get('atten_db') else '')
        return report_pdf.cert_row(p['description'] + suffix, p['nominal'] if p['stat'] == 'mean' else 0.0, low, high, p['unit'], r['reading'], r['result'] == 'FAIL',
                                   section=self.report_section(p), nominal_text=text, uncertainty=self.uncertainty_text(p))

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from."""
        rows, pts = [], []
        for p in POINTS:
            if not self.applicable(p): continue
            row = self.found_left_row(p, lambda r, p=p: self._cert_row(p, r))
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
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'Keysight {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Limits applied', f'{self.period.get()}; {"Option 010" if self.timebase_opt() == "010" else "standard"} time base'),
                                                                 ('Source', 'Keysight 53210A/53220A/53230A Assembly Level Service Guide, chapter 1 (Performance Tests)')],
                                             demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, None), snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True
        if not self.demo: self._save_settings()
        self.disconnect(); port.close(self.root)


def main(argv=None, model=None):
    """model: '53220A' (default), '53230A' or '53210A'; the launcher of each model passes its own."""
    argv = sys.argv if argv is None else argv
    if model:
        configure(model)
    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, demo=demo, fast_demo=fast)
    port.run_app(build)
