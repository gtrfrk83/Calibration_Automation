"""Tektronix TBS2000B performance verification (TBS2072B / 2074B / 2102B / 2104B / 2202B / 2204B), driven from the TBS2000B Series Oscilloscope Specification and
Performance Verification manual (077-1538-03 Rev D), pp. 19-26.

Test points and limits come from specs/tektronix_tbs2000b_pv.json (built by specs/build_tbs2000b_spec.py from the page images).  The sections run in the order
of the procedures in the manual: self test and signal path compensation (p. 22), bandwidth (p. 23), vertical offset accuracy (p. 24), sample rate and delay
time accuracy (p. 25), DC balance (p. 26).

Built on the TDS2000C procedure (tds2000c_verification.py): the same window, the same stimulus (the scope option of a Fluke 5560A, 5522A or 5520A: SCOPE DC volts,
leveled sine, time marker), the same calibrator code (its Runner's set / read back / standby helpers are inherited, not copied), the same prompts where the
hook-up is the same, the same uncertainty source (the lab's A2LA oscilloscope CMC) and TAR / TUR wiring.  The TDS2000C procedure itself is not changed.
The oscilloscope driver is drivers/tektronix_tbs2000b.py (the TBS2000B command set differs from the TDS2000C's).

Never run unattended: the program stops and asks for every cable and terminator change.  Writes are never retried; settings are read back; the calibrator is put
in STANDBY (and that is confirmed) after every point.
Demo (no hardware):  python Procedures/Tektronix_TBS2000B_Verification.py --demo
"""
from __future__ import annotations

import json, math, queue, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import ui_port  # noqa: F401
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, si, report_filename, Settings); the window code is in tbs2000b_view_qt.py / _qt.py
from ui_port import ui as port
import appdata
import datamode
import manual_override
import reset_startup
import virtualbench
import drivers
from drivers.tektronix_tbs2000b import TektronixTBS2000B
import tds2000c_verification as tds
from tds2000c_verification import Skip, Stopped, display_row, edge_times, fmt_plain, judge, to_visa  # noqa: F401  (shared pure helpers)

SPEC_PATH = HERE / 'specs' / 'tektronix_tbs2000b_pv.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
POINTS = SPEC['points']
MODELS = SPEC['models']
MODEL_INFO = SPEC['models_info']
SECTION_TITLE = {s['id']: s['title'] for s in SPEC['sections']}
SECTION_PAGE = {s['id']: s['page'] for s in SPEC['sections']}
PLAIN_UNITS = tds.PLAIN_UNITS
SLEEP_SCALE = 1.0            # tests set this (and tds2000c_verification.SLEEP_SCALE, whose helpers are inherited) to 0
VIRTUAL_PACE = 1.0
CAL_CHOICES = list(tds.CAL_CHOICES)          # Fluke 5560A, 5522A, 5520A: the TDS2000C procedure's calibrators
DEFAULT_MODEL = '2204B'
EDGE_CAPTURES = 5


def pause(seconds):
    if seconds > 0 and SLEEP_SCALE > 0:
        time.sleep(seconds * SLEEP_SCALE * VIRTUAL_PACE)


def set_virtual_pace(on):
    global VIRTUAL_PACE
    VIRTUAL_PACE = virtualbench.WAIT_SCALE if on else 1.0
    tds.set_virtual_pace(on)                 # the inherited calibrator helpers wait through tds2000c_verification.pause


class Config:
    def __init__(self, model=DEFAULT_MODEL):
        self.model = model

    def as_dict(self):
        return dict(model=self.model)

    @property
    def info(self):
        return MODEL_INFO[self.model]

    def applies(self, p):
        return not p.get('models') or self.model in p['models']


def demo_reading(p):
    """Deterministic synthetic reading. Everything made from it is labelled demo data (never evidence)."""
    return tds.demo_reading(p)


# ======================================================================================================================
# uncertainty (the lab's A2LA oscilloscope CMC, as the TDS2000C procedure)
# ======================================================================================================================
def uncertainty_parts(p, raw):
    """(value, unit, style) or None ('N/A').  Offset points: the scope's oscilloscope DC CMC (1 MOhm) at the applied level, in volts.  Bandwidth: the level-sine
    flatness CMC in dB turned into volts at the reading, as the TDS2000C procedure.  Time marker, DC balance (no stimulus) and pass/fail points: none."""
    if p['stim'] == 'none' or p.get('passfail'):
        return None
    import report_pdf
    sc = report_pdf.scope()
    if sc is None:
        return None
    try:
        if p['kind'] == 'OFFSET':
            v, _u, _n = sc.oscilloscope('offset', volts=abs(p['vsrc']), impedance='1M')
            if v:
                return v, 'V', 'si'
        if p['kind'] == 'BW':
            v, _u, _n = sc.oscilloscope('bandwidth', volts_pp=raw.get('src_vpp', 3.0), frequency=raw.get('freq', 50e6))
            if v is not None:
                return (10 ** (v / 20) - 1) * raw.get('reading', 2.12), 'V', 'bwv'
        if p['kind'] == 'TIMEBASE':
            m = tds.marker_parts(p)          # the calibrator's Scope Out time-mark specification, in divisions (shared with the TDS2000C engine)
            if m is not None:
                return m
    except Exception:
        return None
    return None


format_uncertainty = tds.format_uncertainty


def uncertainty_text(p, raw):
    parts = uncertainty_parts(p, raw)
    if parts is None:
        return 'N/A'
    try:
        return format_uncertainty(parts)
    except Exception:
        return 'N/A'


def tar_tur_fields(p, r):
    """dict(TAR, TUR): TUR = half the tolerance / the printed uncertainty when both are volts (offset and bandwidth points); TAR is always blank (no
    specification row of the calibrator matches a scope-option output here), as in the TDS2000C procedure."""
    import tartur
    try:
        if p.get('passfail') or p.get('stim') == 'none':
            return dict(TAR='', TUR='')
        raw = r.get('raw', {})
        text = r.get('uncertainty') or uncertainty_text(p, raw)
        parts = uncertainty_parts(p, raw)
        u = uu = None
        if parts is not None and text != 'N/A' and format_uncertainty(parts) == text:
            import uncertainty
            u, uu = uncertainty.round_up(parts[0]), parts[1]
        acc = tds.marker_accuracy(p) if (p['kind'] == 'TIMEBASE' and u is not None) else None
        return tartur.ratio_fields(tartur.from_values(tartur.half_width(p['low'], p['high']), p['unit'], acc, 'div' if acc else None, u, uu))
    except Exception:
        return dict(TAR='', TUR='')


# ======================================================================================================================
# bench I/O
# ======================================================================================================================
class IO(reset_startup.IOResetMixin):
    """The oscilloscope (USB) and the calibrator."""

    def __init__(self, addrs, transports=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        self.addrs = addrs
        self.scope = self.cal = None
        t = transports or {}

        def tr(name, **kw):
            return t[name] if name in t else drivers.open_visa(to_visa(addrs[name]), timeout=30, **kw)
        text = addrs.get('cal_model', CAL_CHOICES[0])
        try:
            self.scope = TektronixTBS2000B(tr('scope'), self.log, label='TBS2000B'); self.scope.connect()
            if '5560' in text:
                self.cal = drivers.Fluke5560A(tr('cal', baud=int(addrs.get('cal_baud', 9600))), self.log, label='5560A')
            else:
                self.cal = drivers.Fluke5522AScope(tr('cal', baud=int(addrs.get('cal_baud', 9600))), self.log, label='5520A/5522A')
            self.cal.open(verify_model=True); self.cal.clear_status()
        except Exception:
            self.close(); raise
        self.cal.RESET_SCOPE_OFF = True               # the reset leaves the calibrator in standby with its SCOPE function OFF (the procedure selects its mode per test)
        self.ident = self.scope.idn
        self.is_5560 = '5560' in text

    def reset_roles(self):
        """(standards, units under test): the calibrator is reset first, then the oscilloscope."""
        return [self.cal], [self.scope]

    def all_outputs_off(self):
        try:
            self.cal.standby_quiet()
        except Exception:
            pass

    def close(self):
        self.all_outputs_off()
        for inst in (self.scope, self.cal):
            if inst:
                try: inst.close()
                except Exception: pass
        self.save_log()

    def save_log(self):
        if virtualbench.log_is_virtual(self.log): return          # a virtual (demo) session is never evidence
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            lines = self.log.lines()
            new, self._saved = lines[getattr(self, '_saved', 0):], len(lines)
            if not new:
                return
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  TBS2000B session\n' + '\n'.join(new) + '\n')
        except OSError:
            pass


# ======================================================================================================================
# the runner: the TDS2000C Runner's calibrator helpers (dc_source, apply_dc, select_levsine, set_sine, tune_sine, ask, wire, run_point) with the TBS2000B tests
# ======================================================================================================================
class Runner(tds.Runner):

    # ---- self test / signal path compensation (p. 22) -------------------------------------------------------------------------------------
    def do_selftest(self, p):
        self.wire(('SELF',), 'Self test', [
            ('Warm up', 'The oscilloscope must have been operating continuously for twenty minutes within its operating temperature range (p. 22).'),
            ('Disconnect', 'Disconnect all probes and cables from the instrument inputs.'),
            ('Do not touch', 'The self test is started by the program (one loop) and runs for a few minutes. Do not touch the oscilloscope until the program continues.')])
        self.io.scope.default_setup()                                                       # step 2: Default Setup
        self.status('Self test running - do not touch the oscilloscope ...')
        sc, pace = self.io.scope, (SLEEP_SCALE * VIRTUAL_PACE)
        ok, log = sc.run_self_test(settle=sc.SELF_TEST_SETTLE * pace, poll=sc.SELF_TEST_POLL * pace)     # steps 3-8, started remotely
        return (1.0 if ok else 0.0), dict(log=log[:300])

    def do_spc(self, p):
        self.wire(('SPC',), 'Signal path compensation', [
            ('Disconnect', 'Remove all input signals (probes and cables) from the channel inputs (p. 22). Input signals with AC components adversely affect SPC.'),
            ('Wait', 'The compensation takes several minutes; the oscilloscope does not answer commands meanwhile.')])
        self.status('Signal path compensation running (several minutes) ...')
        ok, text = self.io.scope.self_cal()
        return (1.0 if ok else 0.0), dict(result=text)

    # ---- bandwidth (p. 23) -------------------------------------------------------------------------------------------------------------------
    def do_bw(self, p):
        ch = p['ch']
        freq = self.cfg.info['bw_test_hz']
        self.wire(('LEV', ch), f'Bandwidth - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Calibrator SCOPE output (leveled sine, 50 Ohm) to CH{ch} through the 50 Ohm BNC cable and the 50 Ohm feedthrough terminator at the scope input.')])
        s = self.io.scope
        s.default_setup(); self._scope_ctx = ('BW', ch)
        s.select_only(ch)
        s.channel(ch, vscale=p['vscale'], position=0.0, probe=1)
        s.acquire_mode('AVErage', 16)
        s.trigger_edge(f'CH{ch}', 'RISe', 'AUTO', coupling='NOISErej')
        s.timebase(p['hscale_ref'])
        s.check_errors('bandwidth setup')
        self.select_levsine()
        src, vin = self.tune_sine(ch, p['ref_hz'], p['ref_target'], p['ref_target'], low=p['ref_low'], high=p['ref_high'])
        s.timebase(p['hscale'])
        self.set_sine(src, freq)
        vbw = s.measure('PK2Pk', ch)
        self.io.cal.standby_quiet()
        return vbw, dict(src_vpp=src, vin_pp=vin, vbw_pp=vbw, freq=freq, ref_hz=p['ref_hz'])

    # ---- vertical offset accuracy (p. 24) -------------------------------------------------------------------------------------------------------
    def do_offset(self, p):
        ch = p['ch']
        self.wire(('DCV', ch), f'Vertical offset accuracy - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Calibrator SCOPE output to CH{ch} with the BNC cable (SCOPE volts, 1 MOhm output impedance). No terminator.')])
        s = self.io.scope
        if self._scope_ctx != ('OFFSET', ch):
            s.default_setup(); self._scope_ctx = ('OFFSET', ch)
            s.select_only(ch)
            s.acquire_mode('AVErage', 16)
            s.measure_setup('MEAN', ch)
        s.channel(ch, vscale=p['vscale'], position=p['position'], probe=1, offset=p['offset'])
        s.check_errors('offset setup')
        self.dc_source()
        self.apply_dc(p['vsrc'])
        mean = s.measure('MEAN', ch)
        self.io.cal.standby_quiet()
        return mean, dict(applied=p['vsrc'], offset=p['offset'], position=p['position'], vscale=p['vscale'],
                          trace_div=p['position'] + (mean - p['offset']) / p['vscale'])

    # ---- sample rate and delay time accuracy (p. 25) ---------------------------------------------------------------------------------------------
    def do_timebase(self, p):
        self.wire(('MARK',), 'Sample rate and delay time accuracy', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', 'Calibrator SCOPE output (time marker) to CH1 through the BNC cable and the 50 Ohm feedthrough terminator at the scope input.')])
        s, cal = self.io.scope, self.io.cal
        s.default_setup(); self._scope_ctx = ('TB',)
        s.select_only(1)
        s.channel(1, vscale=p['vscale'], position=0.0, probe=1)                       # steps 4-6
        s.acquire_mode('SAMple')
        s.trigger_edge('CH1', 'RISe', 'AUTO', coupling='DC')
        s.record_length()
        s.timebase(p['hscale_set'])                                                    # step 7
        cal.standby_quiet(); cal.select_scope_marker(); cal.set_marker_period(p['period']); cal.operate()      # step 2
        pause(2.0)
        s.set_level_50()                                                               # step 9
        s.trigger_mode('NORMal')
        s.wait_acquisitions(2)
        _times, volts = s.waveform(1)                                                  # step 10: centre the marker vertically
        mid = (max(volts) + min(volts)) / 2
        s.position(1, max(-5.0, min(5.0, -mid / p['vscale'])))
        s.delay(p['delay'])                                                            # steps 11, 12, 14: delay exactly 1 ms
        s.timebase(p['hscale_meas'])                                                   # step 13
        pause(1.0)
        s.wait_acquisitions(2)
        edges = []
        for _ in range(EDGE_CAPTURES):                                                 # step 15, measured instead of read by eye
            times, volts = s.waveform(1)
            if not (times[0] <= p['delay'] <= times[-1]):
                raise drivers.InstrumentError(f'The waveform record ({times[0]:.9g} s to {times[-1]:.9g} s after the trigger) does not contain the '
                                              f'{p["delay"]:g} s delay: check HORizontal:DELay:TIMe and WFMOutpre:XZEro on this firmware')
            found = edge_times(times, volts, 'RISe')
            if not found:                   # no edge in the record around the delay: far outside +/-2.5 div, a FAIL, not a program error
                cal.standby_quiet()
                return 99.0, dict(edge_missing=True, delay_s=p['delay'], note='no marker edge in the record around the delay')
            edges.append(min(found, key=lambda t: abs(t - p['delay'])))
            pause(0.2)
            s.wait_acquisitions(1)
        mean_edge = sum(edges) / len(edges)
        err_div = (mean_edge - p['delay']) / p['hscale_meas']
        cal.standby_quiet()
        return err_div, dict(edge_s=mean_edge, spread_s=max(edges) - min(edges), delay_s=p['delay'], ppm=(mean_edge - p['delay']) / p['delay'] * 1e6)

    # ---- DC balance (p. 26) -------------------------------------------------------------------------------------------------------------------------
    def do_dcbal(self, p):
        ch = p['ch']
        self.wire(('TERM', ch), f'DC balance - CH{ch}', [('Disconnect', 'Remove all cables from the oscilloscope inputs.'),
                  ('Connect', f'Fit a 50 Ohm terminator on the CH{ch} input; nothing else is connected (p. 26).')])
        s = self.io.scope
        s.default_setup(); self._scope_ctx = ('DCBAL', ch)
        s.timebase(p['hscale'])                                                        # step 2
        s.trigger_edge('LINE', 'RISe', 'AUTO', coupling=None)                         # steps 3-5: AC Line trigger
        s.acquire_mode('AVErage', p['averages'])                                       # steps 6-9
        s.select_only(ch)
        s.channel(ch, vscale=p['vscale'], position=0.0, probe=1, coupling='DC', offset=0.0)     # steps 10-13
        s.check_errors('DC balance setup')
        mean = s.measure('MEAN', ch, count=p['averages'])                              # steps 14-18
        return mean, dict(averages=p['averages'], vscale=p['vscale'])


# ======================================================================================================================
# the application window (the TDS2000C App's behaviour; its window code is tbs2000b_view_tk.py / tbs2000b_view_qt.py)
# ======================================================================================================================
class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, manual_override.ManualOverrideMixin):
    MANUAL_OVERRIDE = True            # owner request: type a reading instead of the automatic one (manual_override.py)
    PREFIX = 'TBS'

    def __init__(self, root, demo=False, fast_demo=False):
        self.root, self.demo = root, demo
        self.init_virtual(demo, fast_demo)
        self.io = None
        self._busy = False
        self.stop = False
        self.results = {}
        self.q = queue.Queue()
        self.cfg = Config()
        self.ui_view.setup_window(self)
        self.settings = ui.Settings('TBS2000B')
        g = self.settings.get
        self.asset, self.serial = port.var(), port.var()
        self.v_model = port.var(g('model', DEFAULT_MODEL))
        self.addr = {k: port.var(g(k, d)) for k, d in (('scope', ''), ('cal', 'COM9'), ('cal_baud', '9600'), ('cal_model', CAL_CHOICES[0]))}
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_config(save=False)
        self.status.set(virtualbench.status_text(self) if demo else
                        'Step 1: instrument ID and model. Step 2: addresses, then Test Connections. Step 3: Run All Pending.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)
        port.after(self.root, 50, self._pump)

    def cal_text(self):
        return self.addr['cal_model'].get()

    def _model_text(self):
        m = self.v_model.get().replace(self.PREFIX, '')
        return m if m in MODELS else DEFAULT_MODEL

    def read_cfg(self):
        self.cfg = Config(self._model_text())
        return self.cfg

    def active_points(self):
        return [p for p in POINTS if self.cfg.applies(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, v):
        self._busy = v
        if hasattr(self, 'btn_run'): self._sync_buttons()

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    VIEW = 'tbs2000b_view'

    @property
    def ui_view(self): return port.view(self.VIEW)

    def _build_ui(self): self.ui_view.build_ui(self)

    def on_config(self, save=True):
        self.v_model.set(self._model_text())
        self.read_cfg()
        if save:
            self.settings.set('model', self.v_model.get()); self.settings.save()
        self.refresh()

    def read_model(self):
        if self.fast_demo:
            port.message('info', 'Demo mode', 'Demo mode uses no hardware.'); return
        if self.io is None: self.test_connections()
        if self.io is None: return
        model = self.io.scope.model
        if model in MODELS:
            self.v_model.set(model); self.on_config()
            port.message('info', 'Model read', f'The oscilloscope reports TBS{model} ({self.io.scope.channels} channels).')
        else:
            port.message('warning', 'Model', f'Could not recognise a model in: {self.io.scope.idn}\nChoose it in the Model box.')

    # ---- table ---------------------------------------------------------------------------------------------------------------------------
    def _visible(self, p):
        if not self.cfg.applies(p): return False
        rec = self.results.get(str(p['id']), {}); res = rec.get('result', '')
        if self.show_section.get() not in ('All sections', SECTION_TITLE[p['section']]): return False
        st = self.show_status.get()
        if st == 'Not tested' and res: return False
        if st == 'Passed' and res != 'PASS': return False
        if st == 'Failed (OOT)' and res != 'FAIL': return False
        if not self.status_visible(str(p['id']), st): return False
        if st == 'Skipped' and res != 'SKIP': return False
        return True

    def _row(self, p):
        key = str(p['id']); rec = self.results.get(key, {}); res = rec.get('result', '')
        shown = {'PASS': '✔ PASS', 'FAIL': '✖ FAIL', 'SKIP': '⊘ skipped'}.get(res, '—')
        if p.get('passfail'):
            word = lambda r: '' if not r or r.get('reading') is None else ('Pass' if r['reading'] >= 0.5 else 'Fail')
            f, l = self.found.get(key), self.left.get(key)
            return (p['id'], p['desc'], 'Pass', '', '', 'Pass', word(f), '', word(l) or ('Same' if (self.is_left and f) else ''), shown), (res.lower() or 'pending',)
        unit = p['unit']
        fmt = (lambda v: fmt_plain(v, 5) + (' ' + unit if unit else '')) if unit in PLAIN_UNITS else (lambda v: ui.si(v, unit))
        cells, tags = self.shell_cells(key, p['nominal'], p['low'], p['high'], unit, fmt=fmt)
        cells = list(cells)
        if res == 'SKIP': cells[4:7] = ['', '', '']
        return (p['id'], p['desc'], *cells), tags

    def refresh(self):
        keep = self.ui_view.table_selection(self)
        self.ui_view.table_set_rows(self, ((str(p['id']), *self._row(p)) for p in POINTS if self._visible(p)), keep)
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.ui_view.table_has(self, iid):
            v, tags = self._row(p); self.ui_view.table_update_row(self, iid, v, tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.active_points())
        self.update_shell_sections(self.active_points(), lambda p: SECTION_TITLE[p['section']])

    def on_select(self, _e=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        nom, lo, hi, _r, unit = display_row(p)
        raw = self.results.get(str(p['id']), {}).get('raw')
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        work = ''
        if raw:
            work = '\nWorksheet: ' + ', '.join(f'{k} = {v:.6g}' if isinstance(v, float) else f'{k} = {v}' for k, v in raw.items() if not isinstance(v, (list, dict)))
        both = ('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''
        self.detail.set(f'{p["desc"]}\nStimulus: {"calibrator scope option" if p["stim"] == "cal" else "none"}  |  Manual page {SECTION_PAGE[p["section"]]}{extra}{work}{both}')

    # ---- connections ---------------------------------------------------------------------------------------------------------------------------
    def find_instruments(self):
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        for cb in self.addr_boxes.values(): cb['values'] = found
        self.status.set(f'{len(found)} VISA resource(s): ' + (', '.join(found) if found else 'none'))

    def addrs(self):
        return {k: v.get() for k, v in self.addr.items()}

    def test_connections(self):
        if self.fast_demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect()
            if self.virtual:          # demo: the real IO / driver code over a simulated scope and calibrator
                from drivers.simulated_tbs2000b import make_tbs_bench
                cal = '5560A' if '5560' in self.cal_text() else '5522A'
                self._vb, t = make_tbs_bench(self._model_text(), cal)
                set_virtual_pace(True)
                self.io = IO(self.addrs(), transports=t, virtual=True)
            else: self.io = IO(self.addrs())
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_addrs()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator in standby.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'Oscilloscope: {self.io.ident}\nCalibrator: {self.io.cal.idn}{tag}')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        set_virtual_pace(False)
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else ('Demo - no hardware' if self.demo else 'Not connected'),
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_addrs(self):
        for k, v in self.addr.items(): self.settings.set(k, v.get())
        self.settings.save()

    # ---- thread <-> UI ------------------------------------------------------------------------------------------------------------------------------
    def post(self, kind, payload=None):
        self.q.put((kind, payload, None))

    def request(self, kind, payload):
        """Called on the worker thread: ask the main thread something and wait for the answer."""
        box = dict(ev=threading.Event(), value=None)
        self.q.put((kind, payload, box))
        while not box['ev'].wait(0.1):
            if self.stop:
                raise Stopped()
        return box['value']

    def mo_point(self, iid): return POINTS[int(iid) - 1]
    def mo_total(self): return len(POINTS)

    def mo_applicable(self, p):
        if p.get('passfail'):                 # a pass / fail check (self-test, signal path compensation): the instrument's own verdict, there is no reading to type
            return False, 'This check is a pass / fail result of the instrument itself: there is no reading to type.'
        return True, ''

    def mo_standby(self): self.io.all_outputs_off()

    def mo_record(self, p, value, synthetic, extra):
        """The typed value is judged by judge() like every reading; no raw measurements are kept (the demo reading is recorded the same way)."""
        if threading.current_thread() is threading.main_thread(): self._record(p, value, {}, synthetic, extra=extra)
        else: self._record_threadsafe(p, value, {}, synthetic, extra=extra)

    def _pump(self):
        try:
            while True:
                kind, payload, box = self.q.get_nowait()
                if kind == 'status': self.status.set(payload)
                elif kind == 'select':
                    if self.ui_view.table_has(self, payload): self.ui_view.table_select(self, payload, see=True)
                elif kind == 'row': self._update_row(POINTS[payload - 1])
                elif kind == 'done': self._finished(payload)
                elif kind == 'mo_ask':                          # a typed reading (manual_override) asked for by the worker thread
                    box['value'] = self.mo_ask(payload['p'], reason=payload['reason'], cancel_text=payload['cancel']); box['ev'].set()
                elif kind == 'ask':
                    box['value'] = port.operator_prompt(payload['title'], payload['heading'], payload['steps'], facts=payload['facts'],
                                                         caution=payload['caution'], ok=payload['ok'], image=payload.get('image'), parent=self.root)
                    box['ev'].set()
        except queue.Empty:
            pass
        port.after(self.root, 50, self._pump)

    # ---- running ------------------------------------------------------------------------------------------------------------------------------------------
    def request_stop(self): self.stop = True; self.status.set('Stopping after the current step.')
    def run_all(self): self.execute([p for p in self.active_points() if str(p['id']) not in self.results])

    def run_section(self): self.run_shown_section()

    def rerun(self):
        sel = self.ui_view.table_selection(self)
        if sel: self.execute([POINTS[int(sel[0]) - 1]])
        else: port.message('info', 'Selection', 'Select a test point first.')

    def rerun_from(self):
        sel = self.ui_view.table_selection(self)
        if sel: self.execute(self.points_from(POINTS, sel[0]))
        else: port.message('info', 'Selection', 'Select a test point first.')

    def execute(self, points):
        if not self.confirm_found_overwrite(points): return
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        self.read_cfg()
        if self.fast_demo:
            for p in points:
                self._record(p, demo_reading(p), {}, True)
            self.status.set('Demo run complete.'); self.save(silent=True); return
        if self.io is None: self.test_connections()
        if self.io is None: return
        self.mo_reset_run()
        self.stop = False; self.busy = True
        if not self.reset_notice_ok(): return                  # unit-under-test notice, before any instrument is touched
        threading.Thread(target=self._worker, args=(points,), daemon=True).start()

    def _worker(self, points):
        runner = Runner(self)
        error = None
        try:
            self.post('status', 'Resetting instruments to default settings ...')
            self.reset_run()                               # every run (first, re-run, resume): before the first point and before any other calibrator / scope command
            for i, p in enumerate(points, 1):
                if self.stop: raise Stopped()
                self.post('status', f'Running {i}/{len(points)}: {p["desc"]}')
                self.post('select', str(p['id']))                       # the highlighted row follows the point being tested
                try:
                    got = self.mo_worker_point(p, lambda: runner.run_point(p))       # None: a typed reading (manual_override) was recorded in its place
                    if got is not None:
                        reading, raw = got
                        self._record_threadsafe(p, reading, raw, bool(self.demo))
                except Skip as s:
                    self.results[str(p['id'])] = dict(result='SKIP', reason=str(s), synthetic=bool(self.demo), timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label)
                    self.post('row', p['id'])
        except Stopped:
            error = 'stopped'
        except BaseException as exc:
            error = exc
        finally:
            try: self.io.all_outputs_off()
            except Exception: pass
            try: self.io.save_log()
            except Exception: pass
        self.post('done', error)

    def _finished(self, error):
        self.mo_reset_run()
        self.busy = False; self.save(silent=True)
        if error == 'stopped': self.status.set('Run stopped. Progress is saved.')
        elif error is not None:
            self.status.set('Error - run stopped: ' + str(error)); port.message('error', 'Measurement stopped', str(error))
        else: self.status.set('Run complete. Save progress or export a report.')

    def _record_threadsafe(self, p, reading, raw, synthetic, extra=None):
        raw = dict(raw, reading=reading)
        self.results[str(p['id'])] = dict(reading=reading, raw=raw, result=judge(p, reading), synthetic=synthetic,
                                          uncertainty=uncertainty_text(p, raw), timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **(extra or {}))
        self.post('row', p['id'])
        self.save(silent=True)

    def _record(self, p, reading, raw, synthetic, extra=None):
        self._record_threadsafe(p, reading, raw, synthetic, extra=extra)
        self._update_row(p)

    # ---- files ----------------------------------------------------------------------------------------------------------------------------------------------
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'TBS{self.cfg.model}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, config=self.cfg.as_dict(), **self.save_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'The checkpoint contains DEMO results. Load for review only?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.v_model.set(data.get('config', {}).get('model', self.v_model.get()))
        self.load_results(data)
        self.on_config(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s).')

    def certificate_row(self, p, r):
        """The report row of one recorded point (r = its record); None for a skipped point."""
        import report_pdf
        if not r or r['result'] not in ('PASS', 'FAIL'): return None
        failed = r['result'] == 'FAIL'
        unc = r.get('uncertainty') or uncertainty_text(p, r.get('raw', {}))
        sec = SECTION_TITLE[p['section']]
        if p.get('passfail'):
            return dict(Section=sec, Description=p['desc'], Nominal='Pass', **{'Tolerance -': 'N/A', 'Tolerance +': 'N/A'}, UOM='',
                        **{'As Found': 'Pass' if not failed else 'Fail'}, OOT='OOT' if failed else '', **{'As Left': 'Same'}, Uncertainty='N/A')
        if p['unit'] in PLAIN_UNITS:
            nom, lo, hi, rd, unit = display_row(p, r['reading'])
            return {'Section': sec, 'Description': p['desc'], 'Nominal': nom, 'Tolerance -': lo, 'Tolerance +': hi, 'UOM': unit, 'As Found': rd,
                    'OOT': 'OOT' if failed else '', 'As Left': 'Same', 'Uncertainty': unc}
        row = report_pdf.cert_row(p['desc'], p['nominal'], p['low'] if p['low'] is not None else float('nan'), p['high'] if p['high'] is not None else float('nan'),
                                  p['unit'], r['reading'], failed, section=sec, uncertainty=unc)
        if p['low'] is None: row['Tolerance -'] = 'N/A'
        if p['high'] is None: row['Tolerance +'] = 'N/A'
        if p['low'] is None or p['high'] is None:
            row['Nominal'] = ('<= ' if p['high'] is not None else '>= ') + row['Tolerance +' if p['high'] is not None else 'Tolerance -'] + ' ' + row['UOM']
        return row

    def certificate_pairs(self):
        """(point, report row): As Found for every recorded point; As Left where it was measured again after an adjustment, else 'Same'."""
        pairs = []
        for p in POINTS:
            if not self.cfg.applies(p): continue
            row = self.found_left_row(p, lambda r: self.certificate_row(p, r))
            if row: pairs.append((p, row))
        return pairs

    def certificate_rows(self):
        return [row for _p, row in self.certificate_pairs()]

    def tar_tur_for(self, p):
        key = str(p['id'])
        r = self.found.get(key)
        if not r or r.get('result') not in ('PASS', 'FAIL'):
            r = self.left.get(key) or {}
        if r.get('result') not in ('PASS', 'FAIL'):
            return dict(TAR='', TUR='')
        return tar_tur_fields(p, r)

    def export_pdf(self):
        pairs = self.certificate_pairs()
        rows = [row for _p, row in pairs]
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details('Tektronix TBS2000B performance verification', parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        skipped = sum(1 for v in self.found.values() if v.get('result') == 'SKIP')
        note = ('Uncertainty: offset and bandwidth points use the laboratory A2LA scope (calibrator CMC); points the scope does not cover show N/A.'
                + (f' {skipped} point(s) were skipped.' if skipped else ''))
        try:
            if report_pdf.details_tar_tur(details):
                rows = report_pdf.apply_tar_tur(rows, report_pdf.details_tar_tur(details), [self.tar_tur_for(p) for p, _row in pairs])
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'Tektronix TBS{self.cfg.model}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Source', 'TBS2000B Series Specification and Performance Verification 077-1538-03 Rev D, pp. 19-26')],
                                             demo=demo, details=details, footer_note=note, title='Calibration Data',
                                             snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_addrs(); self.disconnect(); port.close(self.root)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, demo=demo, fast_demo=fast)
    port.run_app(build)
