"""WaveSurfer 4104HD verification GUI — RMS noise, DC voltage, input impedance, offset, bandwidth, time base and trigger level.

Requires: pip install pyvisa; a working VISA backend (e.g. NI-VISA). Instrument commands live in ../drivers.
The 2.75-division normalization is user-reported as verified with Teledyne.
Confirm applicability and test setup before issuing formal calibration results.
"""
import sys
import json
import math
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))  # shared ui_theme.py sits next to the Manager
import ui_port
import ui_theme_core as ui
import appdata
import datamode
import drivers
import procmods
import procmods_engine
import reset_startup
from ui_port import ui as port          # every dialog, scheduler call and window operation goes through the UI port (ui_port.py)

DEFAULT_ADDRESS = 'USB0::0x05FF::0x1023::LCRY4903C19426::0::INSTR'
SCALES = [0.002, 0.005, 0.010, 0.020, 0.050, 0.100, 0.200, 0.500, 1.000]
LIMITS = [30, 38, 44, 48, 51, 52, 48, 51, 52]
# Time base and trigger level limits: HAZ-OSC-02 data sheet pages 10-11, read from the rendered page images.
TIMEBASE_LIMIT_HZ = 0.350        # error 0.00 Hz, -0.350 to +0.350 Hz
TB_SCALE = 0.200                 # V/div for the time-marker input (DC 50 Ohm)
TB_TRIGGER_V = 0.100             # trigger level on the marker
TB_READ_GAP_S = 0.5
TRIG_LEVELS = (0.0, 0.300, -0.300)
TRIG_LIMIT_V = 0.020             # +/-20 mV
TRIG_SCALE = 0.100               # 100 mV/div, DC 1 MOhm
TRIG_START_V = 0.100             # the Fluke starts 100 mV before the level
TRIG_HSCALE = 1e-3



CAL_CHOICES = ['Fluke 5560A', 'Fluke 5522A', 'Fluke 5520A']      # calibrators the connections table offers (the 5522A / 5520A through their scope option, drivers.Fluke5522AScope)

class OperatorCancelled(Exception):
    """The technician chose Cancel at a prompt inside a measurement."""


FIELDS=('Description','Nominal','Tolerance -','Tolerance +','UOM','As Found','OOT','As Left','Uncertainty')
SECTIONS=[('RMS NOISE','noise'),('DC VOLTAGE / GAIN','dcv'),('INPUT IMPEDANCE','impedance'),('VERTICAL OFFSET / P1 MEAN','offset'),('ANALOG BANDWIDTH / LEVSINE','bandwidth'),
          ('TIME BASE ACCURACY','timebase'),('TRIGGER LEVEL ACCURACY','trigger')]

# Procedure modifications (procmods_engine): which tolerance fields of each section's points can be overridden.
# section -> (nominal field or None, low field, high field, fields that identify the point besides the section)
PM_SECTIONS = {
    'dcv': ('nominal_v', 'lower_v', 'upper_v', ('channel', 'scale_v_div')),
    'impedance': ('nominal_ohm', 'lower_ohm', 'upper_ohm', ('channel', 'coupling', 'scale_v_div', 'description')),
    'offset': ('nominal_v', 'lower_v', 'upper_v', ('channel', 'scale_v_div', 'scope_offset_v')),
    'bandwidth': (None, 'lower_db', 'upper_db', ('channel', 'scale_v_div')),
    'timebase': (None, 'lower_hz', 'upper_hz', ('channel',)),                      # the limit is an error band around 0 Hz
    'trigger': ('level_v', 'lower_v', 'upper_v', ('channel', 'slope')),
}
# entry-box variable -> (tunable, factory default, factory text).  The text is exactly what the box always started with.
PM_VARS = (('delay', 'ws.rms_delay', 3, '3'), ('samples', 'ws.rms_samples', 5, '5'), ('dc_settle', 'ws.dcv_settle', 3.0, '3.0'),
           ('imp_settle', 'ws.imp_settle', 2.0, '2.0'), ('imp_samples', 'ws.imp_samples', 3, '3'),
           ('offset_settle', 'ws.offset_settle', 3.0, '3.0'), ('bw_settle', 'ws.bw_settle', 3.0, '3.0'),
           ('tb_settle', 'ws.tb_settle', 3.0, '3.0'), ('tb_samples', 'ws.tb_samples', 5, '5'), ('trig_settle', 'ws.trig_settle', 1.0, '1.0'))


class RMSNoiseApp(datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    _cal_choice = CAL_CHOICES[0]                          # the selected calibrator (instances override it from the connections table)
    CAL_CHOICES = CAL_CHOICES                            # the views read the calibrator list from the app
    VIEW = 'wavesurfer_view'                             # the toolkit's window code: wavesurfer_view_tk (Tk), later _qt

    @property
    def ui_view(self): return port.view(self.VIEW)

    def __init__(self, root):
        self.root = root
        self.pm_init('ws', 'WS4104HD', demo='--demo' in sys.argv)      # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.running = False
        self.connected = False
        self.rows = []
        self.run_config = None
        self.checkpoint_path = appdata.progress_path('rms_noise_checkpoint_v5.json')
        self.instrument_id = port.var('')
        self.serial = port.var('')
        self.visa_address = port.var(DEFAULT_ADDRESS)
        self.channel = port.var('1')
        self.all_channels = port.var(True, 'bool')
        self.awaiting_channel = False
        self.ref_factor = port.var('2.75')
        self.delay = port.var(self.pm_text('ws.rms_delay', 3, '3'))
        self.samples = port.var(self.pm_text('ws.rms_samples', 5, '5'))
        self.status = port.var('Disconnected')
        self.reading = port.var('—')
        self.db_reading = port.var('—')
        self.limit_text = port.var(','.join(map(str, LIMITS)))
        self.dc_rows = []
        self.dc_retest_index = None
        self.dc_config = None
        self.noise_retest_index = None
        self.noise_retest_result = None
        self.dc_checkpoint = appdata.progress_path('dcv_checkpoint_v6.json')
        self.fluke_address = port.var('ASRL9::INSTR')
        self.fluke_model = port.var(CAL_CHOICES[0])        # the calibrator: Fluke 5560A, 5522A or 5520A (scope option), chosen in the connections table
        self._cal_choice = CAL_CHOICES[0]                  # plain copy read by the worker threads (never a UI variable)
        self.fluke_baud = port.var('9600')
        self.dc_status = port.var('DC voltage verification ready')
        self.dc_reading = port.var('—')
        self.dc_running = False
        self.dc_pending = None
        self.dc_batch = False
        self.dc_batch_channel = None
        self.dc_batch_point_ok = False
        self.dc_p1_mode = port.var(True, 'bool')
        self.dc_auto_fluke = port.var(True, 'bool')
        self.dc_settle = port.var(self.pm_text('ws.dcv_settle', 3.0, '3.0'))
        self.offset_rows = []
        self.offset_running = False
        self.offset_batch = False
        self.offset_ok = False
        self.offset_connected_channel = None
        self.offset_checkpoint = appdata.progress_path('offset_mean_checkpoint_v28.json')
        self.offset_status = port.var('Ready — 0 of 16 offset points')
        self.offset_settle = port.var(self.pm_text('ws.offset_settle', 3.0, '3.0'))
        self.bw_rows = []
        self.bw_running = False
        self.bw_batch = False
        self.bw_ok = False
        self.bw_connected_channel = None
        self.bw_checkpoint = appdata.progress_path('bandwidth_checkpoint_v29.json')
        self.bw_status = port.var('Ready — 0 of 24 bandwidth points')
        self.bw_settle = port.var(self.pm_text('ws.bw_settle', 3.0, '3.0'))
        self.tb_rows = []
        self.tb_running = False
        self.tb_retest_index = None
        self.tb_status = port.var('Ready \u2014 0 of 1 time base point')
        self.tb_settle = port.var(self.pm_text('ws.tb_settle', 3.0, '3.0'))
        self.tb_samples = port.var(self.pm_text('ws.tb_samples', 5, '5'))
        self.tb_period_us = port.var('10')
        self.trig_rows = []
        self.trig_running = False
        self.trig_batch = False
        self.trig_ok = False
        self.trig_retest_index = None
        self.trig_connected_channel = None
        self.trig_status = port.var('Ready \u2014 0 of 24 trigger level points')
        self.trig_settle = port.var(self.pm_text('ws.trig_settle', 1.0, '1.0'))
        self.imp_rows = []
        self.imp_running = False
        self.imp_batch = False
        self.imp_batch_success = False
        self.imp_connection_confirmed = False
        self.imp_connected_input = None
        self.imp_checkpoint = appdata.progress_path('impedance_checkpoint_v11.json')
        self.imp_status = port.var('Ready — 0 of 28 impedance points')
        self.imp_settle = port.var(self.pm_text('ws.imp_settle', 2.0, '2.0'))
        self.imp_samples = port.var(self.pm_text('ws.imp_samples', 3, '3'))
        self._ckpt_key = None
        self._ckpt_id = ''
        self._pm_ws_last = {v: getattr(self, v).get() for v, _n, _d, _t in PM_VARS}   # what each box held when the modifications were applied
        self._set_ckpt_paths('UNASSIGNED')
        # All test views live in one root window. Test dialogs for cable changes
        # and safety confirmations remain modal by design.
        # The shell (title bar, strip, drawer, action bar), the scope chip and the notebook of the sections: ws4104hd_view_tk.create_shell.
        self.ui_view.create_shell(self)
        self.make_ui()
        self.make_dcv_ui()
        self.make_impedance_button()
        self.show_dcv()
        self.show_impedance()
        self.show_offset()
        self.load_offset_checkpoint()
        self.show_bandwidth()
        self.load_bandwidth_checkpoint()
        self.show_timebase()
        self.load_timebase_checkpoint()
        self.show_trigger()
        self.load_trigger_checkpoint()
        port.after(self.root, 100, self.process_events)
        self.load_checkpoint()
        self.load_dc_checkpoint()
        self.load_impedance_checkpoint()
        for var in (self.channel, self.all_channels, self.limit_text):
            var.trace_add('write', lambda *_: self._noise_settings_changed())
        self.refresh_noise_grid()
        self.refresh_dcv_table()
        self.refresh_impedance_table()
        self.refresh_offset()
        self.refresh_bandwidth()
        self.refresh_timebase()
        self.refresh_trigger()
        self.dc_status.set(f'{len(self.dc_rows)} of 80 DCV points recorded. Automatic Fluke control is OFF until enabled.')
        self.imp_status.set(f'{len(self.imp_rows)} of 28 impedance points recorded.')
        port.on_close(self.root, self.on_close)
        self.build_unified()
        self.ui_view.polish(self)
        port.after(self.root, 500, self.update_tab_titles)
        if '--demo' in sys.argv:
            self.load_demo_data()

    def make_ui(self): self.ui_view.make_ui(self)


    # ======================================================================== one results table, filterable by function
    FUNCS = (('noise', 'RMS noise'), ('dcv', 'DC voltage'), ('impedance', 'Input impedance'),
             ('offset', 'Offset (P1 mean)'), ('bandwidth', 'Bandwidth (LEVSINE)'), ('timebase', 'Time base'), ('trigger', 'Trigger level'))
    FUNC_NAME = dict(FUNCS)
    FUNC_NOTE = {
        'noise': 'RMS noise: external 50 \u03a9 termination on the channel under test; all channels ON, DC 1 M\u03a9, full bandwidth, 1 ms/div. The program sets P1 to StdDev of that channel and compares the noise level (dB) with the minimum limit.',
        'dcv': 'DC voltage: Fluke SCOPE output cable to the channel, DC 1 M\u03a9, 20 MHz BW. The program runs STBY, SCOPE DCV, OUT, OPER, reads scope P1 MEAN and returns the Fluke to STBY after every point.',
        'impedance': 'Input impedance: Fluke SCOPE measurement output (MEASR) to the channel input. The Fluke output is confirmed OFF before cables are moved.',
        'offset': 'Offset: P1 MEAN at the specified vertical offsets with the Fluke SCOPE DC output. This checks the sourced voltage at that offset, not waveform centring accuracy.',
        'bandwidth': 'Bandwidth: Fluke LEVSINE into the scope 50 \u03a9 input (no extra termination). 50 kHz reference against 1 GHz, scope P1 PkPk. The first point is a hardware pilot, then run again to continue.',
        'timebase': 'Time base: Fluke SCOPE time marker (period in Test settings, default 10 \u00b5s) into CH1 with a 50 \u03a9 cable; the program sets DC 50 \u03a9, full bandwidth and P1 Freq, averages the readings and compares the frequency error with \u00b10.350 Hz. The Fluke returns to STBY after the point.',
        'trigger': 'Trigger level: Fluke SCOPE output to the channel, 100 mV/div, DC 1 M\u03a9, 20 MHz BW. The scope is armed in Single at the level; the Fluke steps to 20 mV short of the level (must not trigger) and 20 mV past it (must trigger). You confirm both on screen; STBY after every point.',
    }

    def _rows_of(self, kind):
        return {'noise': self.rows, 'dcv': self.dc_rows, 'impedance': self.imp_rows, 'offset': self.offset_rows, 'bandwidth': self.bw_rows,
                'timebase': self.tb_rows, 'trigger': self.trig_rows}[kind]

    def _planned(self, kind):
        return len(self.noise_plan()) if kind == 'noise' else len(self._plan_points(kind))

    def _plan_points(self, kind):
        return {'dcv': self.dcv_points, 'impedance': self.impedance_points, 'offset': self.offset_points, 'bandwidth': self.bandwidth_points,
                'timebase': self.timebase_points, 'trigger': self.trigger_points}[kind]()

    def _pending(self, kind):
        return len(self._rows_of(kind)) < self._planned(kind)

    def entries(self):
        """Every planned point in every function, with its result when recorded. Display only: stored rows are unchanged."""
        out = []

        def add(kind, i, row, **kw):
            out.append(dict(kind=kind, idx=i, result=row['result'] if row else '', done=row is not None, **kw))
        for i, (ch, scale, limit) in enumerate(self.noise_plan()):
            r = self.rows[i] if i < len(self.rows) else None
            add('noise', i, r, channel=f'CH{ch}', range=self.range_text(scale), test='Noise level (minimum dB)', nominal='',
                low='' if limit is None else f'{limit:.2f}', high='', found=f"{r['db']:.2f}" if r else '', unit='dB')
        for i, p in enumerate(self.dcv_points()):
            r = self.dc_rows[i] if i < len(self.dc_rows) else None
            src = r or p
            (nom, lo, hi), reads, unit = ui.si_row([src['nominal_v'], src['lower_v'], src['upper_v']], 'V', [r['measured_v']] if r else [])
            add('dcv', i, r, channel=f"CH{src['channel']}", range=self.range_text(src['scale_v_div']), test='DC gain, 1 M\u03a9',
                nominal=self._signed(nom), low=self._signed(lo), high=self._signed(hi), found=self._signed(reads[0]) if reads else '', unit=unit)
        for i, p in enumerate(self.impedance_points()):
            r = self.imp_rows[i] if i < len(self.imp_rows) else None
            src = r or p
            (nom, lo, hi), reads, unit = ui.si_row([src['nominal_ohm'], src['lower_ohm'], src['upper_ohm']], 'ohm', [r['measured_ohm']] if r else [])
            add('impedance', i, r, channel=str(src['channel']), range=self.range_text(src['scale_v_div']), test=f"{src['description']} ({src['coupling']})",
                nominal=nom, low=lo, high=hi, found=reads[0] if reads else '', unit=unit)
        for i, p in enumerate(self.offset_points()):
            r = self.offset_rows[i] if i < len(self.offset_rows) else None
            src = r or p
            (off, nom, lo, hi), reads, unit = ui.si_row([src['scope_offset_v'], src['nominal_v'], src['lower_v'], src['upper_v']], 'V',
                                                        [r['measured_v']] if r else [], extra=3)
            add('offset', i, r, channel=f"CH{src['channel']}", range=self.range_text(src['scale_v_div']), test=f'Offset {self._signed(off)} {unit}',
                nominal=self._signed(nom), low=self._signed(lo), high=self._signed(hi), found=self._signed(reads[0]) if reads else '', unit=unit)
        for i, p in enumerate(self.bandwidth_points()):
            r = self.bw_rows[i] if i < len(self.bw_rows) else None
            src = r or p
            (amp,), _r, vunit = ui.si_row([src['amplitude_vpp']], 'Vpp')
            add('bandwidth', i, r, channel=f"CH{src['channel']}", range=self.range_text(src['scale_v_div']),
                test=f'Full BW, {amp} {vunit} 50 kHz vs 1 GHz', nominal='0', low='-3.000', high='+3.000',
                found=f"{r['response_db']:+.3f}" if r else '', unit='dB')
        for i, p in enumerate(self.timebase_points()):
            r = self.tb_rows[i] if i < len(self.tb_rows) else None
            src = r or p
            add('timebase', i, r, channel='CH1', range=f"{src['marker_period_s']*1e6:g} \u00b5s marker",
                test=f"Frequency error at {src['nominal_hz']/1e3:g} kHz", nominal='0.000', low=f"{src['lower_hz']:+.3f}",
                high=f"{src['upper_hz']:+.3f}", found=f"{r['error_hz']:+.4f}" if r else '', unit='Hz')
        for i, p in enumerate(self.trigger_points()):
            r = self.trig_rows[i] if i < len(self.trig_rows) else None
            add('trigger', i, r, channel=f"CH{p['channel']}", range=self.range_text(p['scale_v_div']),
                test=f"Trigger level, {p['slope'].lower()} slope", nominal=f"{p['level_v']*1000:+.2f}", low=f"{p['lower_v']*1000:+.2f}",
                high=f"{p['upper_v']*1000:+.2f}", found=r['outcome'] if r else '', unit='mV')
        return out

    def _pick_function(self, name):
        self.show_function.set('All functions' if name == 'All sections' else name)
        self.refresh_unified(force=True)

    def build_unified(self): self.ui_view.build_unified(self)

    # ======================================================================== As Found / As Left
    _KIND_ATTR = {'noise': 'rows', 'dcv': 'dc_rows', 'impedance': 'imp_rows', 'offset': 'offset_rows', 'bandwidth': 'bw_rows',
                  'timebase': 'tb_rows', 'trigger': 'trig_rows'}
    _SET_ATTRS = ('rows', 'run_config', 'dc_rows', 'imp_rows', 'offset_rows', 'bw_rows', 'tb_rows', 'trig_rows')
    _LEFT_TAG = '_AsLeft'

    @property
    def busy(self):
        return self._batch_busy()

    @property
    def _sets(self):
        if '_mode_sets' not in self.__dict__:
            self._mode_sets = {}
        return self._mode_sets

    def _stored_rows(self, mode, kind):
        """The result rows of one function for As Found or As Left (the other mode's rows are kept in memory while one mode is on screen)."""
        attr = self._KIND_ATTR[kind]
        if mode == self._mode:
            return getattr(self, attr)
        snap = self._sets.get(mode)
        return snap[attr] if snap else []

    def any_synthetic(self):
        return bool(getattr(self, 'demo_mode', False)) or '--demo' in sys.argv

    def _use_checkpoint_paths(self):
        """As Left results are saved in their own files beside the As Found ones (same name + _AsLeft)."""
        if '_found_paths' not in self.__dict__:
            self._found_paths = {a: getattr(self, a) for a in self.CKPT_BASE}
        for attr, p in self._found_paths.items():
            setattr(self, attr, p.with_name(p.stem + self._LEFT_TAG + p.suffix) if self._mode == datamode.LEFT else p)

    def _load_all_checkpoints(self):
        self.load_offset_checkpoint()
        self.load_bandwidth_checkpoint()
        self.load_timebase_checkpoint()
        self.load_trigger_checkpoint()
        self.load_checkpoint()
        self.load_dc_checkpoint()
        self.load_impedance_checkpoint()

    def _refresh_all_results(self):
        if self.run_config is None:
            self.ui_view.set_state(self.resume_button, 'disabled')
            self.ui_view.set_value(self.progress, 0)
            self.ui_view.set_maximum(self.progress, 36)
            self.progress_text.set('Ready \u2014 0 of 36 ranges')
        else:
            self.ui_view.set_maximum(self.progress, self.total_ranges())
            self.ui_view.set_value(self.progress, len(self.rows))
            self.progress_text.set(f'Completed {len(self.rows)} of {self.total_ranges()} ranges')
        self.refresh_noise_grid()
        self.refresh_dcv_table()
        self.refresh_impedance_table()
        self.refresh_offset()
        self.refresh_bandwidth()
        self.refresh_timebase()
        self.refresh_trigger()
        self.refresh_unified(force=True)

    def set_data_mode(self, mode, from_ui=False):
        if mode not in datamode.LABEL:
            return
        if self._batch_busy():                           # never switch in the middle of a measurement
            if from_ui:
                self.mode_var.set(self._mode)
            return
        if mode == self._mode:
            self._apply_mode_ui()
            return
        if not self.sync_asset():
            if from_ui:
                self.mode_var.set(self._mode)
            return
        self._sets[self._mode] = {a: getattr(self, a) for a in self._SET_ATTRS}
        config = self.run_config
        self._mode = mode
        self._use_checkpoint_paths()
        snap = self._sets.get(mode)
        self.tb_retest_index = self.trig_retest_index = self.dc_retest_index = self.noise_retest_index = self.noise_retest_result = None
        if snap is not None:
            for a, v in snap.items():
                setattr(self, a, v)
        else:
            for a in self._SET_ATTRS:
                setattr(self, a, [])
            self.run_config = json.loads(json.dumps(config)) if config else None     # same channels / limits / settings in both modes
            self._load_all_checkpoints()                                               # earlier session's results for this mode, if any
        self._apply_mode_ui()
        self._refresh_all_results()
        self.msg.set(f'Collecting {self.mode_label} data.' + (' Run the points again after the adjustment.' if mode == datamode.LEFT else ''))

    def run_section(self):
        if self.show_function.get() == 'All functions':
            port.message('info', 'Section', 'Choose a function in the Show box first.', parent=self.root)
            return
        self.run_pending()

    def _confirm_found_overwrite(self, kind, what):
        if self._mode != datamode.FOUND or not self._stored_rows(datamode.LEFT, kind):
            return True
        if self._from_step_active and getattr(self, '_chain_found_ok', None) == kind:
            return True                                    # answered Yes for this function at the start of the 'Rerun From Selected' chain
        ok = self._ask_found_overwrite(what)
        if ok:
            self._chain_found_ok = kind
        return ok

    def _ask_found_overwrite(self, what):
        return port.ask_yes_no(
            'Replace the As Found reading?',
            f'{what} already has As Left readings, so the instrument has been adjusted since the As Found run.\n\n'
            'Measuring As Found again now replaces the original As Found reading with a reading from the adjusted instrument.\n\n'
            'To measure after an adjustment, switch to As Left instead.\n\nReplace the As Found reading anyway?', default='no', parent=self.root)

    def _visible_entry(self, e):
        fn, st = self.show_function.get(), self.show_status.get()
        if fn != 'All functions' and self.FUNC_NAME[e['kind']] != fn:
            return False
        if st == 'Not tested' and e['done']:
            return False
        if st == 'Passed' and e['result'] != 'PASS':
            return False
        if st == 'Failed (OOT)' and e['result'] != 'FAIL':
            return False
        if st == 'As Found failed':
            fr = self._stored_rows(datamode.FOUND, e['kind'])
            if not (e['idx'] < len(fr) and fr[e['idx']].get('result') == 'FAIL'):
                return False
        return True

    def _entries_for(self, mode):
        """entries() for As Found or As Left, whichever mode is on screen (the other mode's rows are swapped in for a moment)."""
        if mode == self._mode:
            return self.entries()
        snap = self._sets.get(mode)
        if not snap:
            return []
        saved = {a: getattr(self, a) for a in self._SET_ATTRS}
        try:
            for a, v in snap.items():
                setattr(self, a, v)
            return self.entries()
        finally:
            for a, v in saved.items():
                setattr(self, a, v)

    def refresh_unified(self, force=False):
        allp = self.entries()
        other = self._entries_for(datamode.FOUND if self.is_left else datamode.LEFT)
        found_e, left_e = (other, allp) if self.is_left else (allp, other)
        numbering = {(e['kind'], e['idx']): n for n, e in enumerate(allp, 1)}
        lookup = lambda lst: {(e['kind'], e['idx']): e for e in lst}
        fmap, lmap = lookup(found_e), lookup(left_e)
        with_unit = lambda v, u: f'{v} {u}'.strip() if v not in ('', None) else ''
        shown = [e for e in allp if self._visible_entry(e)]
        all_funcs = self.show_function.get() == 'All functions'
        items = []
        for e in shown:
            key = (e['kind'], e['idx'])
            tag = 'pass' if e['result'] == 'PASS' else 'fail' if e['result'] == 'FAIL' else 'pending'
            mark = {'PASS': '\u2714 PASS', 'FAIL': '\u2716 FAIL'}.get(e['result'], '\u2014')
            u = e['unit']
            low, high = with_unit(e['low'], u), with_unit(e['high'], u)
            limits = f'{low} \u2026 {high}' if e['high'] else (f'\u2265 {low}' if e['low'] else '')
            fe, le = fmap.get(key), lmap.get(key)
            found = with_unit(fe['found'], u) if fe and fe['done'] else ''
            left = with_unit(le['found'], u) if le and le['done'] else ('Same' if (self.is_left and fe and fe['done']) else '')
            name = f"{e['channel']}   {e['range']}   {e['test']}"
            if all_funcs:
                name = f"{self.FUNC_NAME[e['kind']]}  \u00b7  {name}"
            items.append((f"{e['kind']}:{e['idx']}", (numbering[key], name, with_unit(e['nominal'], u), low, high, limits, found, '', left, mark), (tag,)))
        total = len(allp)
        passed = sum(1 for e in allp if e['result'] == 'PASS')
        failed = sum(1 for e in allp if e['result'] == 'FAIL')
        sig = (tuple(items), total, tuple((e['kind'], e['done'], e['result']) for e in other))
        if force or sig != self._shown:
            self._shown = sig
            self.ui_view.show_unified(self, items, allp, fmap, lmap, total, passed, failed)
        self._entries_cache = {f"{e['kind']}:{e['idx']}": e for e in allp}

    def on_unified_select(self, _event=None):
        sel = self.ui_view.selection(self.utree)
        if not sel:
            return
        e = self._entries_cache.get(sel[0])
        if not e:
            return
        limits = f"{e['low']} to {e['high']} {e['unit']}" if e['high'] else f"minimum {e['low']} {e['unit']}"
        found = f"  |  {self.mode_label}: {e['found']} {e['unit']}  ({e['result']})" if e['done'] else '  |  Not tested yet'
        self.detail.set(f"{self.FUNC_NAME[e['kind']]}  -  {e['channel']}  {e['range']}  -  {e['test']}\nAccept: {limits}{found}\nSetup: {self.FUNC_NOTE[e['kind']]}")

    # ---- which function is busy
    def _batch_busy(self):
        return any((self.running, self.dc_running, getattr(self, 'dc_batch', False), self.imp_running, getattr(self, 'imp_batch', False),
                    self.offset_running, getattr(self, 'offset_batch', False), self.bw_running, getattr(self, 'bw_batch', False),
                    getattr(self, 'tb_running', False), getattr(self, 'trig_running', False), getattr(self, 'trig_batch', False)))

    def _dialog_open(self): return self.ui_view.dialog_open(self)

    def _selected_kind(self):
        name = self.show_function.get()
        return next((k for k, n in self.FUNCS if n == name), None)

    def _start_function(self, kind):
        if kind == 'noise':
            (self.resume_test if (self.rows or self.run_config) else self.start_test)()
        else:
            {'dcv': self.start_dcv_batch, 'impedance': self.start_impedance_batch, 'offset': self.start_offset, 'bandwidth': self.start_bandwidth,
             'timebase': self.start_timebase, 'trigger': self.start_trigger}[kind]()

    def run_pending(self):
        if self._batch_busy():
            port.message('warning', 'Busy', 'Wait for the current measurement to finish.', parent=self.root)
            return
        if '--demo' not in sys.argv and not self.instrument_id.get().strip():
            port.message('info', 'Instrument ID needed', 'Enter the Instrument ID first. Results are saved separately for each instrument.', parent=self.root)
            return
        if not self.sync_asset():
            return
        only = self._selected_kind()
        kinds = [k for k, _n in self.FUNCS if (only is None or k == only) and self._pending(k)]
        if not kinds:
            port.message('info', 'Nothing pending', 'Every point in the selected function is already recorded.', parent=self.root)
            return
        self.chain, self._idle = kinds, 0
        self.msg.set('Running: ' + ', '.join(self.FUNC_NAME[k] for k in kinds))
        self._start_function(kinds[0])

    def stop_all(self):
        self.chain = []
        self._from_queue = ()
        if self.running:
            self.stop_test()
        if self.dc_running or getattr(self, 'dc_batch', False):
            self.stop_dcv_batch()
        if self.imp_running or getattr(self, 'imp_batch', False):
            self.stop_impedance_batch()
        if self.offset_running or getattr(self, 'offset_batch', False):
            self.stop_offset()
        if self.bw_running or getattr(self, 'bw_batch', False):
            self.stop_bandwidth()
        if self.trig_running or self.trig_batch:
            self.stop_trigger()
        self.msg.set('Stopping after the current point. Completed points are saved.')

    def rerun_selected(self):
        if not self.sync_asset():
            return
        sel = self.ui_view.selection(self.utree)
        if len(sel) != 1:
            port.message('info', 'Select a result', 'Select one completed test point in the table.', parent=self.root)
            return
        e = self._entries_cache[sel[0]]
        tree = {'noise': self.tree, 'dcv': self.dc_tree, 'impedance': self.imp_tree, 'offset': self.offset_tree, 'bandwidth': self.bw_tree,
                'timebase': self.tb_tree, 'trigger': self.trig_tree}[e['kind']]
        kids = self.ui_view.children(tree)
        if not e['done'] or e['idx'] >= len(kids):
            port.message('info', 'Not tested yet', 'That point has not been measured yet. Use Run Pending, or pick a recorded point to rerun.', parent=self.root)
            return
        if not self._confirm_found_overwrite(e['kind'], 'This function'):
            return
        self.ui_view.select(tree, kids[e['idx']])
        {'noise': self.retest_noise, 'dcv': self.retest_selected_dcv, 'impedance': self.retest_impedance,
         'offset': self.retest_offset, 'bandwidth': self.retest_bandwidth, 'timebase': self.retest_timebase, 'trigger': self.retest_trigger}[e['kind']]()

    _from_step_active = False              # True only while _from_step starts the 2nd, 3rd... point of a 'Rerun From Selected' chain
    _chain_last = None                     # (function, channel) the operator already confirmed in this chain

    def _retest_prompt(self, kind, channel, *args, **kw):
        """operator_prompt for a retest connection.  In a 'Rerun From Selected' chain the prompt is asked for the FIRST point and again only when the function or the channel
        changes (the cable really has to move); the following points on the same channel go straight on (owner, 2026-10-26: a prompt on every point).  A single Rerun
        Selected always asks."""
        if self._from_step_active and self._chain_last == (kind, channel):
            return True
        ok = port.operator_prompt(*args, **kw)
        if ok:
            self._chain_last = (kind, channel)
        return ok

    _from_queue = ()                       # 'Rerun From Selected': the table keys still to be re-measured, one at a time, by rerun_selected

    def rerun_from_selected(self):
        """The selected measured point and every measured point after it in the table as shown (section / status filters applied):
        each is re-measured exactly as Rerun Selected does it (its own prompts, overwrite question and worker), one after the other.
        A point that does not start (cancelled at its prompt, busy, refused) ends the chain; Stop ends it too."""
        if not self.sync_asset():
            return
        sel = self.ui_view.selection(self.utree)
        if len(sel) != 1:
            port.message('info', 'Select a result', 'Select one completed test point in the table.', parent=self.root)
            return
        keys = [f"{e['kind']}:{e['idx']}" for e in self.entries() if self._visible_entry(e)]
        if sel[0] not in keys:
            return
        done = {f"{e['kind']}:{e['idx']}" for e in self.entries() if e['done']}
        self._from_queue = [k for k in keys[keys.index(sel[0]) + 1:] if k in done]
        self._chain_last = None                                               # the first point of the chain always asks
        self._chain_found_ok = None
        self.rerun_selected()                                                 # the selected point, through the existing path
        if not self._batch_busy():
            self._from_queue = ()

    def _from_step(self):
        key, self._from_queue = self._from_queue[0], list(self._from_queue[1:])
        if key not in self._entries_cache:
            self._from_queue = ()
            return
        self.ui_view.select(self.utree, key)
        self._from_step_active = True
        try:
            self.rerun_selected()
        finally:
            self._from_step_active = False
        if not self._batch_busy():
            self._from_queue = ()

    def clear_function(self):
        kind = self._selected_kind()
        if kind is None:
            port.message('info', 'Choose a function', 'Choose one function in the Show list first. Results are cleared one function at a time.', parent=self.root)
            return
        if self._batch_busy() or not self.sync_asset():
            return
        extra = '\n\nAs Left readings for this function are kept.' if self._mode == datamode.FOUND and self._stored_rows(datamode.LEFT, kind) else ''
        if not port.ask_yes_no('Clear results', f'Clear all saved {self.mode_label} {self.FUNC_NAME[kind]} results? This cannot be undone.' + extra, parent=self.root):
            return
        if kind == 'noise':
            self.clear_results()
        elif kind == 'dcv':
            self.clear_dcv()
        elif kind == 'impedance':
            self.clear_impedance()
        elif kind == 'offset':
            self.offset_rows.clear()
            self.offset_checkpoint.unlink(missing_ok=True)
            self.refresh_offset()
        elif kind == 'bandwidth':
            self.bw_rows.clear()
            self.bw_checkpoint.unlink(missing_ok=True)
            self.refresh_bandwidth()
        elif kind == 'timebase':
            self.tb_rows.clear()
            self.tb_checkpoint.unlink(missing_ok=True)
            self.refresh_timebase()
        else:
            self.trig_rows.clear()
            self.trig_checkpoint.unlink(missing_ok=True)
            self.refresh_trigger()
        self.refresh_unified(force=True)

    def _unified_tick(self):
        try:
            busy = self._batch_busy()
            self.refresh_unified()
            self.ui_view.set_state(self.btn_run, 'disabled' if busy else 'normal')
            self.ui_view.set_state(self.btn_rerun, 'disabled' if busy else 'normal')
            if getattr(self, 'btn_rerun_from', None) is not None:          # the Qt build's 'Rerun From Selected'
                self.ui_view.set_state(self.btn_rerun_from, 'disabled' if busy else 'normal')
            self.ui_view.set_state(self.btn_section, 'disabled' if busy else 'normal')
            for b in self.mode_buttons:
                self.ui_view.set_state(b, 'disabled' if busy else 'normal')
            self.ui_view.set_state(self.btn_stop, 'normal' if busy else 'disabled')
            self.ui_view.set_state(self.btn_clear, 'disabled' if busy else 'normal')
            for name in ('status', 'dc_status', 'imp_status', 'offset_status', 'bw_status', 'tb_status', 'trig_status', 'progress_text'):
                var = getattr(self, name, None)
                if var is not None and var.get() != self._last_status.get(name):
                    if name in self._last_status and var.get():
                        self.msg.set(var.get())
                    self._last_status[name] = var.get()
            if self._from_queue and not busy and not self._dialog_open():
                self._from_step()
            if self.chain:
                if busy or self._dialog_open():
                    self._idle = 0
                else:
                    self._idle += 1
                    if self._idle >= 2:
                        self._idle = 0
                        if not self._pending(self.chain[0]):
                            self.chain.pop(0)
                            if self.chain:
                                self._start_function(self.chain[0])
                            else:
                                self.msg.set('Run complete. Export the report (PDF) when you are ready.')
                        else:
                            self.chain = []          # stopped, cancelled at a prompt, or an error: leave the rest to the technician
        except self.ui_view.window_gone():
            return
        port.after(self.root, 500, self._unified_tick)

    def show_settings_dialog(self): self.ui_view.show_settings_dialog(self)


    # ======================================================================== per-asset checkpoints
    CKPT_BASE = {'checkpoint_path': 'rms_noise_checkpoint_v5', 'dc_checkpoint': 'dcv_checkpoint_v6', 'offset_checkpoint': 'offset_mean_checkpoint_v28',
                 'bw_checkpoint': 'bandwidth_checkpoint_v29', 'imp_checkpoint': 'impedance_checkpoint_v11',
                 'tb_checkpoint': 'timebase_checkpoint_v1', 'trig_checkpoint': 'trigger_level_checkpoint_v1'}

    def _asset_key(self):
        return ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.instrument_id.get().strip()) or 'UNASSIGNED'

    def _set_ckpt_paths(self, key):
        """Results are saved per Instrument ID, e.g. dcv_checkpoint_v6_WS-77_A.json, like the other procedures."""
        self._ckpt_key = key
        for attr, base in self.CKPT_BASE.items():
            setattr(self, attr, appdata.progress_path(f'{base}_{key}.json'))
        self.__dict__.pop('_found_paths', None)

    def sync_asset(self):
        """Switch to the saved results of the Instrument ID now in the entry (called when the entry is left, and before every run, rerun,
        clear and export, so a report can never carry another instrument's results). Returns False if it cannot switch right now."""
        self._pm_begin()
        if '--demo' in sys.argv:
            return True
        key = self._asset_key()
        if key == self._ckpt_key:
            return True
        if self._batch_busy():
            self.instrument_id.set(self._ckpt_id)
            port.message('warning', 'Busy', 'The Instrument ID cannot change while a measurement is running.', parent=self.root)
            return False
        self._mode_sets = {}
        self._mode = datamode.FOUND                 # another instrument starts on As Found
        self._set_ckpt_paths(key)
        self._ckpt_id = self.instrument_id.get().strip()
        self._apply_mode_ui()
        self.rows, self.run_config = [], None
        self.dc_rows, self.imp_rows, self.offset_rows, self.bw_rows = [], [], [], []
        self.tb_rows, self.trig_rows = [], []
        self.tb_retest_index = self.trig_retest_index = None
        self.dc_retest_index = self.noise_retest_index = self.noise_retest_result = None
        if key != 'UNASSIGNED':
            self._adopt_legacy_results(key)
        self._load_all_checkpoints()
        self._refresh_all_results()
        have = sum(len(r) for r in (self.rows, self.dc_rows, self.imp_rows, self.offset_rows, self.bw_rows, self.tb_rows, self.trig_rows))
        self._pm_restore_sidecar(have)
        self.msg.set(f'Instrument {self._ckpt_id or key}: restored {have} saved result(s).' if have else f'Instrument {self._ckpt_id or key}: no saved results yet.')
        return True

    # ======================================================================== procedure modifications (procmods_engine)
    # What can be modified on this procedure: the settle times and sample counts of every section (they are the entry-box defaults, so a
    # technician can still change them for a run), the time base read gap, the command templates of the drivers, and the TOLERANCE of the
    # DCV / impedance / offset / bandwidth / time base / trigger points (developer mode).  Not modifiable here: skipping a point (the
    # sections save their results by position), the RMS-noise minimum limits (already a box on the screen) and every safety prompt.
    def _pm_begin(self):
        """Load the saved modifications for the Instrument ID now in the entry.  Called from sync_asset (before every run); never while a
        measurement is running; never raises."""
        try:
            if self._batch_busy():
                return
            self.pm_begin_run(None, self.instrument_id.get().strip())
            self._pm_defaults()
            self._pm_write_sidecar()
        except Exception as exc:
            if self.pm_state is not None:
                self.pm_state.warnings.append(f'procedure modifications could not be loaded ({type(exc).__name__})')

    # ---- live editing (procmods_live).  The WaveSurfer has no point list: every section computes its points on demand, so the edits are
    # applied between two points of a section (the head of next_dcv / next_impedance / next_offset / next_bandwidth / next_trigger) by
    # swapping the resolved override set; the point in progress keeps what it started with.  A section's settle / sample boxes follow the
    # modified default unless the technician typed something else.  RMS noise and the single time-base point run as one batch: an edit
    # reaches them at their next start.  Not offered: skipping a point and 'redo' from the editor (use Rerun Selected).
    def _pm_boundary(self, what):
        """True = go on.  False = saved edits could not be applied safely (outputs not confirmed): the section stops."""
        try:
            self.pm_live_boundary({'id': what, 'desc': f'next {what} point'})
            self._pm_defaults()
            self._pm_write_sidecar()
            return True
        except procmods_engine.LiveApplyError as exc:
            port.message('error', 'Edits not applied', str(exc), parent=self.root)
            return False

    def pm_driver_classes(self):
        return (drivers.WaveSurfer4104HD, drivers.Fluke5560A, drivers.Fluke5522AScope)

    def pm_supports_skip(self):
        return False

    def pm_supports_redo(self):
        return False

    def pm_title(self):
        return 'WaveSurfer 4104HD'

    def pm_context_points(self):
        views = self.pm_limit_views()
        return [v for sec in PM_SECTIONS for v in views[sec]]

    def pm_texts(self, points):
        return {}

    def pm_refresh_view(self):
        self._pm_defaults()
        self._refresh_all_results()

    def pm_live_locked_keys(self):
        """Points of a section are recorded by position: the first len(rows) have a reading, the next one is in flight while it runs."""
        import procmods
        views = self.pm_limit_views()
        pts = [v for sec in PM_SECTIONS for v in views[sec]]
        keys = procmods.point_keys(pts)
        have = {'dcv': (len(self.dc_rows), self.dc_running), 'impedance': (len(self.imp_rows), self.imp_running),
                'offset': (len(self.offset_rows), self.offset_running), 'bandwidth': (len(self.bw_rows), self.bw_running),
                'timebase': (len(self.tb_rows), self.tb_running), 'trigger': (len(self.trig_rows), self.trig_running)}
        out, at = set(), 0
        for sec in PM_SECTIONS:
            n = len(views[sec])
            done, flying = have[sec]
            out.update(keys[at:at + min(n, done + (1 if flying else 0))])
            at += n
        return out

    def _pm_defaults(self):
        """Move each entry box to its (modified) default, but only if the technician has not typed something else there."""
        for var, name, default, text in PM_VARS:
            box = getattr(self, var)
            want = self.pm_text(name, default, text)
            if box.get() == self._pm_ws_last.get(var, text) and want != box.get():
                box.set(want)
            if box.get() == want:
                self._pm_ws_last[var] = want

    def _pm_sidecar(self):
        return appdata.progress_path(f'ws4104hd_overrides_{self._asset_key()}.json')

    def _pm_write_sidecar(self):
        """The five-plus checkpoint files have no room for the modification snapshot, so it is kept next to them (only for modified runs)."""
        st = self.pm_state
        if st is None or not st.oset or not st.snapshot:
            return
        path = self._pm_sidecar()
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'asset': self.instrument_id.get().strip(), 'overrides': st.snapshot}, indent=2), encoding='utf-8')
        tmp.replace(path)

    def _pm_restore_sidecar(self, have):
        """Results exist for this instrument: continue under the modifications they were taken with (the saved snapshot), unless the
        store has changed and pm_choose(diff) says 'current'."""
        try:
            path = self._pm_sidecar()
            if have and path.exists():
                self.pm_on_checkpoint(json.loads(path.read_text(encoding='utf-8')), choose=getattr(self, 'pm_choose', None))
                self._pm_defaults()
        except Exception as exc:
            if self.pm_state is not None:
                self.pm_state.warnings.append(f'the saved modification record could not be read ({type(exc).__name__})')

    @staticmethod
    def _pm_view(section, p):
        """The point as procmods sees it (the field names it keys and limits on)."""
        nom, lo, hi, idf = PM_SECTIONS[section]
        unit = {'dcv': 'V', 'impedance': 'ohm', 'offset': 'V', 'bandwidth': 'dB', 'timebase': 'Hz', 'trigger': 'V'}[section]
        rest = [f for f in idf if f not in ('channel', 'scale_v_div', 'description')]
        return dict(section=section, kind=section.upper(), nominal=(p.get(nom) if nom else None), low=p[lo], high=p[hi], unit=unit,
                    ch=p.get('channel'), range=p.get('scale_v_div'), stim='|'.join(str(p[f]) for f in rest) or None,
                    desc=p.get('description'))

    # ---- the point editor (procmods_point_model).  The WaveSurfer has no point list with ids: a point is 'section:index' (the row's position
    # in its table), the section computes its steps itself, so the window shows no command list and edits the TOLERANCE only.
    PM_SECTION_TITLES = {'dcv': 'DC voltage', 'impedance': 'Input impedance', 'offset': 'DC offset', 'bandwidth': 'Bandwidth',
                         'timebase': 'Time base', 'trigger': 'Trigger'}

    def _pm_split(self, pid):
        sec, _, i = str(pid).partition(':')
        if sec not in PM_SECTIONS or not i.isdigit():
            return None, -1
        return sec, int(i)

    def pm_point_title(self, p):
        if not isinstance(p, dict) or 'section' not in p:
            return super().pm_point_title(p)
        bits = [self.PM_SECTION_TITLES.get(p['section'], p['section'])]
        if p.get('ch') is not None:
            bits.append(f'CH{p["ch"]}')
        if p.get('desc'):
            bits.append(str(p['desc']))
        if p.get('range') is not None:
            bits.append(f'{p["range"]:g} V/div')
        if p.get('nominal') is not None:
            bits.append(f'nominal {p["nominal"]:g} {p.get("unit", "")}'.rstrip())
        return ', '.join(bits)

    def pm_find_point(self, pid):
        """The point as it is now (with any tolerance override applied), as a procmods view dict carrying its id."""
        sec, i = self._pm_split(pid)
        if sec is None:
            return None
        pts = getattr(self, PM_POINT_METHODS[sec])()
        if not 0 <= i < len(pts):
            return None
        return dict(self._pm_view(sec, pts[i]), id=str(pid))

    def pm_factory_point(self, pid):
        sec, i = self._pm_split(pid)
        if sec is None:
            return None, None
        views = self.pm_limit_views()
        flat = [v for name in PM_SECTIONS for v in views[name]]
        keys = procmods.point_keys(flat)
        at = sum(len(views[name]) for name in PM_SECTIONS if list(PM_SECTIONS).index(name) < list(PM_SECTIONS).index(sec))
        if not 0 <= i < len(views[sec]):
            return None, None
        return dict(views[sec][i], id=str(pid)), keys[at + i]

    def pm_point_fields(self, view):
        why = 'The WaveSurfer procedure applies a change of tolerance only (its points are computed by each section).'
        return {n: {'paths': [], 'reason': why, 'note': ''} for n in ('nominal', 'unit', 'description')}

    def pm_plan_point(self, p):
        import procmods_plan
        return procmods_plan.Plan(error='The WaveSurfer sections send their commands from the section routine, not point by point, so the '
                                        'commands of a single point cannot be shown before the section is run.')

    def pm_point_busy(self, pid):
        sec, i = self._pm_split(pid)
        if sec is None:
            return ''
        have = {'dcv': (len(self.dc_rows), self.dc_running), 'impedance': (len(self.imp_rows), self.imp_running),
                'offset': (len(self.offset_rows), self.offset_running), 'bandwidth': (len(self.bw_rows), self.bw_running),
                'timebase': (len(self.tb_rows), self.tb_running), 'trigger': (len(self.trig_rows), self.trig_running)}
        done, flying = have[sec]
        if flying and i == done:
            return f'This point is being measured now ({self.PM_SECTION_TITLES[sec]} point {i + 1}); its limit cannot change until the run moves on.'
        return ''

    def pm_point_has_reading(self, pid):
        sec, i = self._pm_split(pid)
        if sec is None:
            return False
        rows = {'dcv': self.dc_rows, 'impedance': self.imp_rows, 'offset': self.offset_rows, 'bandwidth': self.bw_rows,
                'timebase': self.tb_rows, 'trigger': self.trig_rows}[sec]
        return i < len(rows)

    def pm_limit_views(self):
        """{section: [views of the FACTORY points]} - what the tolerance editor must key and check its overrides against."""
        return {sec: [self._pm_view(sec, p) for p in self._pm_factory(sec)] for sec in PM_SECTIONS}

    def _pm_factory(self, section):
        fn = getattr(type(self), PM_POINT_METHODS[section])
        return fn.pm_orig() if fn.pm_static else fn.pm_orig(self)

    def pm_section_points(self, section, pts):
        """`pts` unchanged (the same list) unless a valid, enabled, HMAC-verified limit override is in effect; then copies of the points
        concerned with the new low / high.  Nothing but the low / high of those points can change (procmods' guard is re-run)."""
        st = self.pm_state
        if st is None or not st.oset or not st.oset.has_limits:
            return pts
        try:
            nom, lo, hi, idf = PM_SECTIONS[section]
            views = [self._pm_view(section, p) for p in pts]
            patched, lim = st.patch(views)
            out = []
            for i, (p, q) in enumerate(zip(pts, patched)):
                if i in lim:
                    r = dict(p)
                    r[lo], r[hi] = q['low'], q['high']
                    r['limit_modified'], r['limit_factory'] = True, q['limit_factory']
                    out.append(r)
                else:
                    out.append(p)
            return out
        except Exception as exc:                       # anything wrong: the manufacturer's tolerances, and say so
            st.warnings.append(f'tolerance changes for {section} could not be applied ({type(exc).__name__}); factory tolerances are used')
            return pts

    def _pm_limits_ok(self, row, section, factory):
        """A saved row's tolerance is acceptable when it is the factory one, the current one, or the row says it was a modified one."""
        _n, lo, hi, _i = PM_SECTIONS[section]
        got = (row.get(lo), row.get(hi))
        cur = tuple(factory)
        pts = getattr(self, PM_POINT_METHODS[section])()
        return got == cur or bool(row.get('limit_modified')) or any((p[lo], p[hi]) == got for p in pts)

    def _pm_ckpt_points(self, section, rows):
        """The points a saved result file is compared with.  Identical to the plain points unless a tolerance modification exists or the
        saved rows carry one; then a row's own tolerance is accepted (results taken under a modification stay loadable)."""
        cur = getattr(self, PM_POINT_METHODS[section])()
        _n, lo, hi, _i = PM_SECTIONS[section]
        modified = isinstance(rows, list) and any(isinstance(r, dict) and r.get('limit_modified') for r in rows)
        if not isinstance(rows, list) or not (modified or (self.pm_state is not None and self.pm_state.oset and self.pm_state.oset.has_limits)):
            return cur
        fac = self._pm_factory(section)
        out = []
        for i, c in enumerate(cur):
            r = rows[i] if i < len(rows) and isinstance(rows[i], dict) else None
            if r is not None and r.get(lo) is not None and r.get(hi) is not None \
                    and (bool(r.get('limit_modified')) or (r[lo], r[hi]) in ((fac[i][lo], fac[i][hi]), (c[lo], c[hi]))):
                c = dict(c)
                c[lo], c[hi] = r[lo], r[hi]
            out.append(c)
        return out

    def _adopt_legacy_results(self, key):
        """Older versions saved one set of results for every instrument. Offer to assign that set to this Instrument ID, once."""
        old = {attr: Path(__file__).with_name(f'{base}.json') for attr, base in self.CKPT_BASE.items()}
        legacy = [(a, p) for a, p in old.items() if p.exists() and not getattr(self, a).exists()]
        if not legacy:
            return
        if not port.ask_yes_no('Earlier results found',
                                   f'Results saved by an earlier version (not tied to an instrument) were found.\n\nAssign them to {self._ckpt_id or key}?\n\n'
                                   'Choose No to leave them untouched (they are not deleted).', parent=self.root):
            return
        for attr, path in legacy:
            try:
                path.replace(getattr(self, attr))
            except OSError:
                pass

    def update_tab_titles(self):
        """Show progress on each tab, e.g. 'DC Voltage  12/80', with a tick when complete."""
        try:
            items = ((self.rms_tab, 'RMS Noise', len(self.rows), self.total_ranges()),
                     (self.dc_window, 'DC Voltage', len(self.dc_rows), 80),
                     (self.imp_window, 'Input Impedance', len(self.imp_rows), 28),
                     (self.offset_tab, 'Offset / P1 Mean', len(self.offset_rows), 16),
                     (self.bw_tab, 'Bandwidth / LEVSINE', len(self.bw_rows), 24),
                     (self.tb_tab, 'Time Base', len(self.tb_rows), 1),
                     (self.trig_tab, 'Trigger Level', len(self.trig_rows), 24))
            for tab, name, done, total in items:
                text = f'  {name}  \u2714  ' if done and done >= total else f'  {name}  {done}/{total}  ' if done else f'  {name}  '
                self.ui_view.set_tab_text(self, tab, text)
            if self.connected:
                self.ui_view.set_chip(self, 'Scope: connected', 'good')
            elif 'fail' in self.status.get().lower():
                self.ui_view.set_chip(self, 'Scope: connection failed', 'bad')
        except self.ui_view.window_gone():
            return
        port.after(self.root, 1000, self.update_tab_titles)

    def make_dcv_ui(self):
        # DC Voltage has its own tab; no duplicate toolbar buttons needed.
        pass

    def toggle_settings(self): self.ui_view.toggle_settings(self)

    def set_running(self, value):
        self.running = value
        self.ui_view.set_state(self.start_button, 'disabled' if value else 'normal')
        self.ui_view.set_state(self.stop_button, 'normal' if value else 'disabled')
        self.ui_view.set_state(self.connect_button, 'disabled' if value else 'normal')
        self.ui_view.set_state(self.channel_select, 'disabled' if value else 'readonly')
        self.ui_view.set_state(self.resume_button, 'disabled' if value or self.run_config is None or len(self.rows) >= self.total_ranges() else 'normal')
        if hasattr(self, 'retest_button'):
            self.ui_view.set_state(self.retest_button, 'disabled' if value else 'normal')

    def test_connection(self):
        if self.running:
            return
        self.status.set('Connecting...')
        address = self.visa_address.get().strip()
        def work():
            scope = None
            try:
                _f, scope = self.open_bench(None, 0, address, drivers.CommandLog())
                scope.open(verify_model=False)
                self.events.put(('connection', True, scope.identify()))
            except Exception as exc:
                self.events.put(('connection', False, str(exc)))
            finally:
                if scope is not None:
                    scope.close()
        threading.Thread(target=work, daemon=True).start()

    def get_config(self):
        delay = float(self.delay.get())
        samples = int(self.samples.get())
        factor = float(self.ref_factor.get())
        limits = [float(x.strip()) for x in self.limit_text.get().split(',')]
        if not math.isfinite(delay) or not 0.2 <= delay <= 120:
            raise ValueError('Settle time must be 0.2 to 120 seconds.')
        if not 1 <= samples <= 100:
            raise ValueError('Samples must be 1 to 100.')
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError('dB reference factor must be positive.')
        if len(limits) != 9 or not all(math.isfinite(x) for x in limits):
            raise ValueError('Enter exactly nine finite minimum dB limits.')
        return dict(address=self.visa_address.get().strip(), channel=int(self.channel.get()),
                    channels=[1, 2, 3, 4] if self.all_channels.get() else [int(self.channel.get())],
                    delay=delay, samples=samples, factor=factor, limits=limits)

    def save_checkpoint(self):
        if self.run_config is None:
            return
        data = {'configuration': self.run_config, 'rows': self.rows}
        temp = self.checkpoint_path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temp.replace(self.checkpoint_path)

    def total_ranges(self):
        return len(self.run_config['channels']) * len(SCALES) if self.run_config else 36

    def load_checkpoint(self):
        if not self.checkpoint_path.exists():
            return
        try:
            data = json.loads(self.checkpoint_path.read_text(encoding='utf-8'))
            config, rows = data['configuration'], data['rows']
            channels = config['channels']
            if not isinstance(rows, list) or len(rows) > 9 * len(channels):
                raise ValueError('Invalid checkpoint length')
            for i, row in enumerate(rows):
                ch, scale = channels[i // 9], SCALES[i % 9]
                if row['channel'] != ch or not math.isclose(row['scale_v_div'], scale, rel_tol=1e-8):
                    raise ValueError('Saved results do not match channel/scale order')
            self.run_config = config
            self.visa_address.set(config['address'])
            self.channel.set(str(config['channel']))
            self.all_channels.set(len(channels) == 4)
            self.delay.set(str(config['delay']))
            self.samples.set(str(config['samples']))
            self.ref_factor.set(str(config['factor']))
            self.limit_text.set(','.join(map(str, config['limits'])))
            for row in rows:
                self.add_result(row)
            self.progress_text.set(f'Restored {len(rows)} of {self.total_ranges()} ranges')
            self.set_running(False)
        except Exception as exc:
            self.status.set(f'Checkpoint could not be loaded: {exc}')

    # ---- grids list every planned test point up front; as-found values fill in as the run goes
    # grid attribute -> (running flag, retest-index attribute): while that section runs its points in turn (not a retest), the highlighted row
    # follows the point being tested
    FOLLOW_GRIDS = {'tree': ('running', 'noise_retest_index'), 'dc_tree': ('dc_running', 'dc_retest_index'), 'imp_tree': ('imp_running', 'imp_retest_index'),
                    'offset_tree': ('offset_running', 'offset_retest_index'), 'bw_tree': ('bw_running', 'bw_retest_index'),
                    'tb_tree': ('tb_running', 'tb_retest_index'), 'trig_tree': ('trig_running', 'trig_retest_index')}

    def _set_grid(self, tree, items, active=None):
        """items = [(values, tags), ...]. Updates rows in place, keeps selection, scrolls to `active`.
        While the section is running its points in turn, `active` (the point being tested) is also the highlighted row."""
        ids = port.view(RMSNoiseApp.VIEW).set_grid(tree, items, active)
        try:
            for attr, (running, retest) in self.FOLLOW_GRIDS.items():
                if getattr(self, attr, None) is tree:
                    if (getattr(self, running, False) and getattr(self, retest, None) is None and active is not None and 0 <= active < len(ids)):
                        self.ui_view.select_and_show(tree, ids[active])
                    break
        except Exception:
            pass                                                  # the highlight never breaks a measurement
        return ids

    @staticmethod
    def range_text(scale):
        """Vertical scale as a scaled value with its unit, e.g. 0.01 -> '10 mV/div'."""
        if scale is None:
            return 'EXT'
        text, unit = ui.si_one(scale, 'V', sig=3)
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return f'{text} {unit}/div'

    @staticmethod
    def _signed(text):
        return text if not text or text.startswith('-') or text.strip('0.') == '' else '+' + text

    @staticmethod
    def _tag(done, i, result=None):
        if i < done:
            return ('pass' if str(result).upper() == 'PASS' else 'fail',)
        return ('next',) if i == done else ('pending',)

    def noise_plan(self):
        """(channel, V/div, minimum dB) for every range: the saved run if there is one, else the current settings."""
        if self.run_config:
            channels, limits = self.run_config['channels'], self.run_config['limits']
        else:
            try:
                channels = [1, 2, 3, 4] if self.all_channels.get() else [int(self.channel.get())]
            except ValueError:
                channels = [1]
            try:
                limits = [float(x) for x in self.limit_text.get().split(',')]
            except ValueError:
                limits = []
            if len(limits) != 9:
                limits = [None] * 9
        return [(ch, SCALES[i], limits[i]) for ch in channels for i in range(9)]

    def refresh_noise_grid(self):
        plan = self.noise_plan()
        items = []
        for i, (ch, scale, limit) in enumerate(plan):
            if i < len(self.rows):
                row = self.rows[i]
                rms_text, rms_unit = ui.si_one(row['rms_volts'], 'V')
                values = (f"CH{row['channel']}", self.range_text(row['scale_v_div']), rms_text, rms_unit, f"{row['db']:.2f}",
                          f"{row['minimum_db']:.2f}", f"{row['margin_db']:+.2f}", 'dB', row['result'], row['samples'])
                items.append((values, self._tag(len(self.rows), i, row['result'])))
            else:
                values = (f'CH{ch}', self.range_text(scale), '', 'V', '', '' if limit is None else f'{limit:.2f}', '', 'dB', '\u2014', '')
                items.append((values, self._tag(len(self.rows), i)))
        self._set_grid(self.tree, items, active=len(self.rows))
        if not self.run_config and not self.rows:
            self.ui_view.set_maximum(self.progress, max(len(plan), 1))
            self.ui_view.set_value(self.progress, 0)
            self.progress_text.set(f'Ready — 0 of {len(plan)} ranges')

    def _noise_settings_changed(self):
        if not self.running and not self.rows and hasattr(self, 'tree'):
            self.refresh_noise_grid()

    def add_result(self, row):
        self.rows.append(row)
        self.refresh_noise_grid()
        self.ui_view.set_maximum(self.progress, self.total_ranges())
        self.ui_view.set_value(self.progress, len(self.rows))
        self.progress_text.set(f'Completed {len(self.rows)} of {self.total_ranges()} ranges')

    def confirm_channel(self, channel, scale):
        return port.operator_prompt('Prepare channel', f'Prepare CH{channel} for the next measurement',
            [('Move the 50 \u03a9 termination', f'Put the external 50 \u03a9 BNC termination on CH{channel}.'),
             ('Check the scope', 'All four channels ON, DC 1 M\u03a9, full bandwidth, 1 ms/div, averaging / ERES off.'),
             ('Automatic', f'The program sets P1 to StdDev of CH{channel} for you.')],
            facts=[('Channel', f'CH{channel}'), ('Range', self.range_text(scale))],
            caution='Cancel keeps all completed results saved so you can Resume.',
            ok='Ready \u2014 start measuring', parent=self.root)

    def launch_remaining(self, resume=False):
        if self.running or self.run_config is None or len(self.rows) >= self.total_ranges():
            return
        config = self.run_config
        index = len(self.rows)
        channel = config['channels'][index // 9]
        scale = SCALES[index % 9]
        # Resume without a redundant prompt only when the next point uses
        # the same physical channel as the last completed measurement.
        # A channel transition still requires moving the BNC termination.
        same_channel_resume = (
            resume and bool(self.rows) and self.rows[-1]['channel'] == channel
        )
        if not same_channel_resume and not self.confirm_channel(channel, scale):
            self.progress_text.set(f'Paused — {index} of {self.total_ranges()} ranges saved')
            self.set_running(False)
            return
        self.stop_event.clear()
        self.set_running(True)
        threading.Thread(target=self.worker,
            args=(config['address'], channel, config['delay'], config['samples'],
                  config['factor'], config['limits'], index % 9), daemon=True).start()

    def retest_noise(self):
        idx = self._retest_index(self.tree, self.rows, 'RMS noise', self.rms_tab)
        if idx is None:
            return
        if self.run_config is None:
            port.message('info', 'No saved run', 'Start a test first.')
            return
        config = self.run_config
        row = self.rows[idx]
        channel, scale_index = row['channel'], idx % len(SCALES)
        if not (self._from_step_active and self._chain_last == ('noise', channel)) and not self.confirm_channel(channel, SCALES[scale_index]):
            return
        self._chain_last = ('noise', channel)
        self.noise_retest_index = idx
        self.noise_retest_result = None
        self.stop_event.clear()
        self.set_running(True)
        self.progress_text.set(f'Retesting point {idx+1} of {self.total_ranges()} (CH{channel}, {self.range_text(SCALES[scale_index])})')
        threading.Thread(target=self.worker,
            args=(config['address'], channel, config['delay'], config['samples'],
                  config['factor'], config['limits'], scale_index, scale_index + 1), daemon=True).start()

    def resume_test(self):
        if self.running or self.run_config is None or len(self.rows) >= self.total_ranges():
            return
        try:
            if self.get_config() != self.run_config:
                port.message('error', 'Settings changed',
                    'Settings differ from the saved run. Restore the original settings before resuming.')
                return
        except (ValueError, TypeError) as exc:
            port.message('error', 'Invalid configuration', str(exc))
            return
        self.launch_remaining(resume=True)

    def start_test(self):
        if self.running:
            return
        try:
            config = self.get_config()
        except (ValueError, TypeError) as exc:
            port.message('error', 'Invalid configuration', str(exc))
            return
        chans = ', '.join(f'CH{c}' for c in config['channels'])
        if not port.operator_prompt('New test', 'Start a new RMS noise test',
            [('Saved results', 'Existing saved noise results will be cleared.'),
             ('Method', 'Confirm the 2.75-division method and the limits are applicable.')],
            facts=[('Channels', chans), ('Ranges', f'{self.total_ranges()} measurements')],
            ok='Clear and start', parent=self.root):
            return
        self.clear_results()
        self.run_config = config
        self.ui_view.set_maximum(self.progress, self.total_ranges())
        self.refresh_noise_grid()
        self.save_checkpoint()
        self.launch_remaining()

    def worker(self, address, channel, delay, samples, factor, limits, start_index=0, stop_index=None):
        log = drivers.CommandLog()
        scope = None
        try:
            _f, scope = self.open_bench(None, 0, address, log)
            scope.open()
            self.reset_bench(None, scope, log, key='noise')       # reset to default settings before the first point
            ident = scope.idn
            self.events.put(('status', f'Connected: {ident}'))
            self.events.put(('status', 'Turning all four channels ON, DC 1 MΩ, full bandwidth, 1 ms/div'))
            for ch in (1, 2, 3, 4):                       # the noise test's stated setup: all channels ON, DC 1 MOhm, full bandwidth (each readback verified)
                scope.enable_channel(ch)
                scope.set_coupling(ch, 'DC1M')
                scope.set_bandwidth_limit(ch, 'Full')
            scope.set_timebase(1e-3)
            scope.configure_p1(channel, 'StandardDeviation')
            self.events.put(('status', f'P1 configured: waveform StdDev of CH{channel} (readback verified)'))
            scope.set_trigger_mode('Auto')      # a stopped acquisition leaves P1 frozen: Auto keeps the StdDev updating (readback verified)
            self.events.put(('status', f'Trigger mode Auto (readback verified); P1 follows CH{channel}'))
            for idx in range(start_index, len(SCALES) if stop_index is None else stop_index):
                scale, limit = SCALES[idx], limits[idx]
                if self.stop_event.is_set():
                    break
                # Set the range and confirm the instrument actually accepted it.
                scope.set_vertical_scale(channel, scale, settle=0.0)
                if self.stop_event.wait(delay):
                    break
                scope.configure_p1(channel, 'StandardDeviation')    # re-assert (readback verified) that P1 is the StdDev of THIS channel before every point
                scope.set_trigger_mode('Auto')                       # and that the acquisition is running, so P1 is updated
                scope.read_p1_when_ready()                           # wait until the scope has a P1 value (it says 'No Data Available' right after a change), discard it
                if self.stop_event.wait(0.5):
                    break
                readings = []
                for _ in range(samples):
                    if self.stop_event.is_set():
                        break
                    volts = scope.read_p1_when_ready()
                    if volts <= 0:
                        raise ValueError(f'Invalid P1 value at {scale} V/div: {volts!r}')
                    readings.append(volts)
                    if self.stop_event.wait(0.3):
                        break
                if len(readings) != samples:
                    break
                avg_rms = sum(readings) / len(readings)
                db = 20 * math.log10(factor * scale / avg_rms)
                row = dict(timestamp=datetime.now().isoformat(timespec='seconds'),
                           instrument=ident, channel=channel, scale_v_div=scale,
                           rms_volts=avg_rms, db=db,
                           minimum_db=limit, margin_db=db-limit,
                           result='PASS' if db >= limit else 'FAIL',
                           samples=samples, reference_factor_div=factor,
                           note='2.75-division method reported verified with Teledyne by user; no guard band')
                self.events.put(('row', row))
            self.events.put(('done', self.stop_event.is_set()))
        except Exception as exc:
            self.events.put(('error', str(exc)))
        finally:
            if scope is not None:
                try:
                    scope.close()
                except Exception:
                    pass
            self.save_command_log(log, f'RMS noise CH{channel}')

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == 'ask':
                    _k, title, question, reply = event
                    reply.put(port.ask_yes_no_cancel(title, question, parent=self.root))
                elif kind == 'tb_result':
                    self.record_timebase(event[1], event[2], event[3] if len(event) > 3 else ())
                elif kind in ('tb_error', 'tb_safety'):
                    self.tb_retest_index = None
                    if kind == 'tb_error':
                        self.tb_status.set('ERROR: ' + event[1])
                    port.message('error', 'Time base error' if kind == 'tb_error' else 'Fluke output safety', event[1], parent=self.root)
                elif kind == 'tb_idle':
                    self.tb_running = False
                elif kind == 'trig_result':
                    self.record_trigger(event[1], event[2])
                    self.trig_ok = True
                elif kind in ('trig_error', 'trig_safety', 'trig_cancel'):
                    self.trig_retest_index = None
                    self.trig_batch = False
                    self.trig_ok = False
                    if kind == 'trig_cancel':
                        self.trig_status.set(event[1])
                    else:
                        if kind == 'trig_error':
                            self.trig_status.set('ERROR: ' + event[1])
                        port.message('error', 'Trigger level error' if kind == 'trig_error' else 'Fluke output safety', event[1], parent=self.root)
                elif kind == 'trig_idle':
                    self.trig_running = False
                    if self.trig_batch and self.trig_ok:
                        self.trig_ok = False
                        port.after(self.root, 250, self.next_trigger)
                if kind == 'bw_result':
                    self.record_bandwidth(event[1],event[2],event[3])
                    self.bw_ok = True
                elif kind == 'bw_error':
                    self.bw_retest_index = None
                    self.bw_batch = False
                    self.bw_ok = False
                    self.bw_status.set('ERROR: '+event[1])
                    port.message('error', 'Bandwidth error',event[1],parent=self.root)
                elif kind == 'bw_safety':
                    self.bw_retest_index = None
                    self.bw_batch = False
                    self.bw_ok = False
                    port.message('error', 'Fluke output safety',event[1],parent=self.root)
                elif kind == 'bw_idle':
                    self.bw_running = False
                    if self.bw_batch and self.bw_ok:
                        self.bw_ok = False
                        port.after(self.root, 250,self.next_bandwidth)
                if kind == 'offset_result':
                    self.record_offset(event[1], event[2], event[3])
                    self.offset_ok = True
                elif kind == 'offset_error':
                    self.offset_retest_index = None
                    self.offset_batch = False
                    self.offset_ok = False
                    self.offset_status.set('ERROR: ' + event[1])
                    port.message('error', 'Offset measurement error', event[1], parent=self.root)
                elif kind == 'offset_safety':
                    self.offset_retest_index = None
                    self.offset_batch = False
                    self.offset_ok = False
                    port.message('error', 'Fluke safety', event[1], parent=self.root)
                elif kind == 'offset_idle':
                    self.offset_running = False
                    if self.offset_batch and self.offset_ok:
                        self.offset_ok = False
                        port.after(self.root, 250, self.next_offset)
                if kind == 'connection':
                    self.connected = event[1]
                    self.status.set(('Connected: ' if event[1] else 'Connection failed: ') + event[2])
                elif kind == 'dc_value':
                    if self.ui_view.tab_open(self, 'dc_window'):
                        self.ui_view.set_state(self.dc_next_button, 'normal')
                        if port.ask_yes_no('Confirm P1 reading', f'Scope P1 returned {event[2]:+.6f} V.\n\nIs P1 set to MEAN of CH{event[1]["channel"]} and is this reading valid?', parent=self.root):
                            self.record_dcv(event[1],event[2],'scope P1 MEAN (operator confirmed)')
                elif kind == 'dc_auto_value':
                    if self.ui_view.tab_open(self, 'dc_window'):
                        if self.dc_retest_index is not None:
                            idx = self.dc_retest_index
                            self.dc_retest_index = None
                            self.record_dcv(event[1], event[2],
                                'automatic Fluke SCOPE DCV / selected-point retest')
                        elif self.dc_batch:
                            self.record_dcv(event[1], event[2], 'automatic Fluke SCOPE DCV / single P1 MEAN reading')
                            self.dc_batch_point_ok = True
                        elif port.ask_yes_no('Confirm automatic DCV reading',
                            f'Fluke returned to STBY. Scope P1 returned {event[2]:+.6f} V.\n\n'
                            f'Was P1 configured to MEAN of CH{event[1]["channel"]}, and is this result valid?',
                            parent=self.root):
                            self.record_dcv(event[1], event[2], 'automatic Fluke SCOPE DCV / single P1 MEAN reading')
                elif kind == 'dc_idle':
                    self.dc_running = False
                    if self.ui_view.tab_open(self, 'dc_window'):
                        self.ui_view.set_state(self.dc_next_button, 'normal')
                        if self.dc_batch and self.dc_batch_point_ok:
                            self.dc_batch_point_ok = False
                            port.after(self.root, 200, self.next_dcv)
                elif kind == 'dc_safety':
                    self.dc_retest_index = None
                    self.dc_batch = False
                    port.message('error', 'OUTPUT SAFETY WARNING', event[1])
                elif kind == 'dc_error':
                    self.dc_retest_index = None
                    self.dc_batch = False
                    if self.ui_view.tab_open(self, 'dc_window'):
                        self.ui_view.set_state(self.dc_next_button, 'normal')
                    port.message('error', 'DCV read error', event[1])
                elif kind == 'imp_result':
                    self.record_impedance(event[1], event[2], event[3])
                    self.imp_batch_success = True
                elif kind == 'imp_error':
                    self.imp_retest_index = None
                    self.imp_batch = False
                    self.imp_batch_success = False
                    self.imp_status.set('Impedance measurement error — point not recorded')
                    port.message('error', 'Impedance measurement error', event[1], parent=getattr(self,'imp_window',self.root))
                elif kind == 'imp_safety':
                    self.imp_retest_index = None
                    self.imp_batch = False
                    self.imp_batch_success = False
                    port.message('error', 'FLUKE SCOPE MODE', event[1], parent=getattr(self,'imp_window',self.root))
                elif kind == 'imp_idle':
                    self.imp_running = False
                    if self.ui_view.tab_open(self, 'imp_window'):
                        self.ui_view.set_state(self.imp_next_button, 'normal')
                        if self.imp_batch and self.imp_batch_success:
                            self.imp_batch_success = False
                            port.after(self.root, 300, self.next_impedance)
                elif kind == 'fluke':
                    self.status.set(('Fluke connected: ' if event[1] else 'Fluke error: ') + event[2])
                    port.message('info', 'Fluke connection', event[2]) if event[1] else port.message('error', 'Fluke connection', event[2])
                elif kind == 'status':
                    self.status.set(event[1])
                elif kind == 'row' and self.noise_retest_index is not None:
                    idx = self.noise_retest_index
                    self.rows[idx] = event[1]
                    self.refresh_noise_grid()
                    self.save_checkpoint()
                    self.noise_retest_result = f'Point {idx+1} retested — {event[1]["result"]}'
                elif kind == 'row':
                    self.add_result(event[1])
                    self.save_checkpoint()
                elif kind == 'done' and self.noise_retest_index is not None:
                    self.noise_retest_index = None
                    self.set_running(False)
                    self.progress_text.set(self.noise_retest_result or 'Retest stopped — previous result kept')
                elif kind == 'done':
                    self.set_running(False)
                    if event[1]:
                        self.progress_text.set(f'Stopped — {len(self.rows)} of {self.total_ranges()} ranges saved')
                    elif len(self.rows) == self.total_ranges():
                        self.progress_text.set(f'Completed — {len(self.rows)} of {self.total_ranges()} ranges')
                        port.message('info', 'Test complete', 'All selected channels are complete. Export the report (PDF) to save it.')
                    else:
                        # Schedule on the Tk event loop so the next channel is
                        # prepared only after the previous VISA session closes.
                        port.after(self.root, 300, self.launch_remaining)
                elif kind == 'error' and self.noise_retest_index is not None:
                    self.noise_retest_index = None
                    self.set_running(False)
                    self.progress_text.set('Retest failed — previous result kept')
                    port.message('error', 'Measurement error', event[1])
                elif kind == 'error':
                    self.set_running(False)
                    self.status.set('Test error — completed ranges preserved; use Resume Test')
                    self.progress_text.set(f'Interrupted — {len(self.rows)} of {self.total_ranges()} ranges saved')
                    port.message('error', 'Measurement error', event[1])
        except queue.Empty:
            pass
        port.after(self.root, 100, self.process_events)

    def stop_test(self):
        self.stop_event.set()
        self.progress_text.set('Stopping after current VISA operation... completed ranges will be saved')

    def clear_results(self):
        if self.running:
            return
        self.rows.clear()
        self.run_config = None
        try:
            self.checkpoint_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.ui_view.set_state(self.resume_button, 'disabled')
        self.ui_view.set_value(self.progress, 0)
        self.ui_view.set_maximum(self.progress, 36)
        self.progress_text.set('Ready — 0 of 36 ranges')
        self.refresh_noise_grid()

    def on_close(self):
        if self.tb_running or self.trig_running:
            port.message('warning', 'Measurement running', 'Finish the current point (answer any trigger question) and wait for Fluke STBY confirmation before closing.')
            return
        if self.bw_running:
            port.message('warning', 'Bandwidth running',
                'Wait for Fluke STBY confirmation before closing.')
            return
        if self.offset_running:
            port.message('warning', 'Offset running', 'Wait for Fluke STBY confirmation before closing.')
            return
        if self.imp_running:
            port.message('warning', 'Impedance in progress', 'Wait for the Fluke SCOPE OFF confirmation before closing.')
            return
        if self.dc_running:
            port.message('warning', 'DCV in progress', 'Wait until the automatic DCV point completes and Fluke STBY is confirmed before closing.')
            return
        if self.running:
            if not port.ask_yes_no('Test running', 'Stop the test and close the window?'):
                return
            self.stop_event.set()
        port.close(self.root)


    def test_fluke(self):
        """Read-only identity check; never enables output."""
        def work():
            fluke = None
            try:
                fluke, _s = self.open_bench(self.fluke_address.get().strip(), int(self.fluke_baud.get()), None, drivers.CommandLog())
                fluke.DEFAULT_TIMEOUT = 5.0
                fluke.open(verify_model=False)
                self.events.put(('fluke', True, fluke.identify()))
            except Exception as exc:
                self.events.put(('fluke', False, str(exc)))
            finally:
                if fluke is not None:
                    try: fluke.close()
                    except Exception: pass
        threading.Thread(target=work, daemon=True).start()

    def dcv_points(self):
        # Limits transcribed from HAZ-OSC-02 report, pages 4–6.
        # Positive/negative tolerances are symmetrical for each nominal voltage.
        data = [
            (0.002, 0.006, 0.001160), (0.005, 0.015, 0.001400),
            (0.010, 0.030, 0.001800), (0.020, 0.060, 0.002600),
            (0.050, 0.150, 0.005000), (0.100, 0.300, 0.009000),
            (0.200, 0.600, 0.017000), (0.500, 1.500, 0.041000),
            (1.000, 3.000, 0.081000), (2.000, 6.000, 0.161000),
        ]
        return [dict(channel=ch, scale_v_div=s, nominal_v=sign*v,
                     lower_v=sign*v-tol, upper_v=sign*v+tol)
                for ch in range(1,5) for s,v,tol in data for sign in (1,-1)]

    def show_dcv(self): self.ui_view.show_dcv(self)

    def retest_selected_dcv(self):
        """Retest an existing result without changing sequential checkpoint progress."""
        if self.running or self.dc_running or self.imp_running or self.dc_retest_index is not None:
            port.message('warning', 'Busy', 'Finish the current measurement first.', parent=self.root)
            return
        selected = self.ui_view.selection(self.dc_tree)
        if len(selected) != 1:
            port.message('info', 'Select a row', 'Select exactly one completed DCV result in the table.', parent=self.root)
            return
        idx = self.ui_view.row_index(self.dc_tree, selected[0])
        if idx >= len(self.dc_rows):
            port.message('info', 'Not tested yet', 'That point has not been measured yet. Use Run DCV Automatically / Resume DCV, or pick a recorded row to retest.', parent=self.root)
            return
        if not (self.dc_auto_fluke.get() and self.dc_p1_mode.get()):
            port.message('warning', 'Automatic retest',
                'Enable automatic Fluke SCOPE DCV and scope P1 MEAN to retest.', parent=self.root)
            return
        try:
            settle = float(self.dc_settle.get())
            baud = int(self.fluke_baud.get())
            if not math.isfinite(settle) or not 0.5 <= settle <= 30:
                raise ValueError('Settling time must be 0.5–30 seconds')
        except ValueError as exc:
            port.message('error', 'Settings', str(exc), parent=self.root)
            return
        point = self.dcv_points()[idx]
        ch = point['channel']
        if not self._retest_prompt('dcv', ch, 'Confirm DCV retest connection', f'Retest DCV point {idx+1} of 80',
            [('Connect the cable', f'Fluke SCOPE output cable to CH{ch}.'),
             ('Remove other sources', 'No external terminators, probes or other sources on the input.'),
             ('Automatic', 'The scope is set to DC 1 M\u03a9 and 20 MHz BW for you.')],
            facts=[('Channel', f'CH{ch}'), ('Test voltage', f'{point["nominal_v"]:+g} V'),
                   ('Range', self.range_text(point["scale_v_div"]))],
            caution='The previous reading is kept in the retest history. A good new reading replaces the displayed result; an error leaves it unchanged.',
            ok='Connected \u2014 retest', parent=self.root):
            return
        self.dc_batch = False
        self.dc_batch_point_ok = False
        self.dc_retest_index = idx
        self.dc_running = True
        self.ui_view.set_state(self.dc_next_button, 'disabled')
        self.dc_status.set(f'Retesting DCV point {idx+1} — CH{ch} {point["nominal_v"]:+.6f} V')
        threading.Thread(target=self.automatic_dcv_point,
            args=(point, settle, self.fluke_address.get().strip(), baud,
                  self.visa_address.get().strip()), daemon=True).start()

    def resume_dcv(self):
        """Resume at the first unrecorded DCV point using the saved checkpoint."""
        if self.dc_running or self.running or self.imp_running:
            port.message('warning', 'Busy', 'Wait for the current measurement to finish.', parent=self.root)
            return
        if len(self.dc_rows) >= len(self.dcv_points()):
            port.message('info', 'DCV complete', 'All 80 DCV points are recorded.', parent=self.root)
            return
        self.dc_status.set(f'Resuming DCV at point {len(self.dc_rows)+1} of 80.')
        if self.dc_auto_fluke.get() and self.dc_p1_mode.get():
            self.start_dcv_batch()
        else:
            self.next_dcv()

    def start_dcv_batch(self):
        if self.dc_running or self.running or self.imp_running:
            port.message('warning', 'Busy', 'Wait for the current test point to finish.', parent=self.root)
            return
        if len(self.dc_rows) >= len(self.dcv_points()):
            port.message('info', 'Complete', 'All DCV points are complete.', parent=self.root)
            return
        if not (self.dc_auto_fluke.get() and self.dc_p1_mode.get()):
            port.message('warning', 'Automatic DCV', 'Enable both automatic Fluke output and scope P1 acquisition.', parent=self.root)
            return
        self.dc_batch = True
        self.dc_batch_channel = None
        self.dc_batch_point_ok = False
        self.next_dcv()

    def stop_dcv_batch(self):
        self.dc_batch = False
        self.dc_status.set('Automatic DCV stopped; current point will finish and Fluke will return to STBY.')

    def next_dcv(self):
        if self.running or self.dc_running or self.imp_running:
            port.message('warning', 'Busy', 'Another measurement is in progress.')
            return
        if not self._pm_boundary('DC voltage'):
            self.dc_batch = False
            return
        points = self.dcv_points()
        i = len(self.dc_rows)
        if i >= len(points):
            self.dc_batch = False
            port.message('info', 'DCV complete', 'All 80 DCV points completed. Export the report (PDF).')
            return
        point = points[i]
        ch, scale, nominal = point['channel'], point['scale_v_div'], point['nominal_v']
        automatic = self.dc_auto_fluke.get()
        if automatic and not self.dc_p1_mode.get():
            port.message('warning', 'Automatic mode', 'Enable automatic scope P1 MEAN acquisition to use automatic Fluke output control.')
            return
        if automatic:
            try:
                settle = float(self.dc_settle.get())
                if not math.isfinite(settle) or not 0.5 <= settle <= 30:
                    raise ValueError()
            except ValueError:
                port.message('error', 'Settle time', 'Settle time must be 0.5 to 30 seconds.')
                return
            msg = dict(heading=f'DCV point {i+1} of 80',
                steps=[('Connect the cable', f'Fluke SCOPE output cable to CH{ch}. Remove any external 50 \u03a9 terminator.'),
                       ('Scope input', 'DC 1 M\u03a9, bandwidth 20 MHz.'),
                       ('Automatic', f'The program sets {scale*1000:g} mV/div, configures and verifies P1 MEAN, then runs STBY \u2192 SCOPE DCV \u2192 OUT \u2192 OPER, reads the scope and returns to STBY.')],
                facts=[('Channel', f'CH{ch}'), ('Output', f'{nominal:+g} V DC'), ('Range', self.range_text(scale))],
                caution='Confirm the physical connection and that the output is safe before continuing.',
                ok='Connected and safe \u2014 continue')
        else:
            msg = dict(heading=f'DCV point {i+1} of 80 (manual output)',
                steps=[('Connect the cable', f'Fluke SCOPE output cable to CH{ch}.'),
                       ('Set the Fluke', f'Manually set the DC output to {nominal:+g} V and enable it.'),
                       ('Scope', 'DC 1 M\u03a9, 20 MHz BW. If scope acquisition is selected, scale and P1 MEAN are set automatically.')],
                facts=[('Channel', f'CH{ch}'), ('Output', f'{nominal:+g} V DC'), ('Range', self.range_text(scale))],
                caution='Manual mode does not control or disable the Fluke output. Click OK only when the output is stable.',
                ok='Output stable \u2014 continue')
        if self.dc_batch:
            if not automatic:
                self.dc_batch = False
                port.message('error', 'Automatic DCV', 'Fluke automatic output control is required.', parent=self.root)
                return
            if self.dc_batch_channel != ch:
                # A physical cable change is mandatory at every new channel.
                if not port.operator_prompt(f'Connect DCV cable \u2014 CH{ch}',
                    f'Connect the Fluke SCOPE output to CH{ch}',
                    [('Connect', f'Fluke SCOPE output cable to CH{ch}.'),
                     ('Remove', 'External terminators, probes and any other sources.'),
                     ('Verify', 'Scope input is DC coupling, 1 M\u03a9, 20 MHz BW.')],
                    facts=[('Channel', f'CH{ch}'), ('Test', 'Every positive and negative DCV voltage for this channel')],
                    caution='The program applies each voltage automatically and verifies Fluke STBY after every point. Press OK only after the cable is connected and safe.',
                    ok='Connected and safe \u2014 start', parent=self.root):
                    self.dc_batch = False
                    self.dc_status.set('Automatic DCV paused at channel connection.')
                    return
                self.dc_batch_channel = ch
        elif not port.operator_prompt('Confirm DCV test setup', **msg, parent=self.root):
            return
        if automatic:
            self.dc_running = True
            self.ui_view.set_state(self.dc_next_button, 'disabled')
            threading.Thread(target=self.automatic_dcv_point,
                             args=(point, settle, self.fluke_address.get().strip(),
                                   int(self.fluke_baud.get()), self.visa_address.get().strip(),
                                   ),
                             daemon=True).start()
        elif self.dc_p1_mode.get():
            self.ui_view.set_state(self.dc_next_button, 'disabled')
            threading.Thread(target=self.read_dcv_scope, args=(point,), daemon=True).start()
        else:
            self.enter_dcv_manual(point)

    def on_cal_model(self):
        """The calibrator box changed: remember the choice for the worker threads."""
        v = self.fluke_model.get()
        self._cal_choice = v if v in CAL_CHOICES else CAL_CHOICES[0]

    def cal_name(self):
        """'5560A', '5522A' or '5520A' (the selected calibrator)."""
        return self._cal_choice.split()[-1]

    def cal_std(self):
        """The specmanager standard name the uncertainty / TAR of the selected calibrator come from (its own sheet: 5560A, 5522A or 5520A)."""
        return self.cal_name()

    def open_bench(self, fluke_addr, baud, scope_addr, log, scope_timeout=10):
        """Create the calibrator and scope drivers. (Tests replace this with simulated transports.)
        Either address may be None when that instrument is not needed."""
        if not fluke_addr:
            fluke = None
        elif self.cal_name() == '5560A':
            fluke = drivers.Fluke5560A(drivers.open_visa(fluke_addr, baud=baud), log)
        else:                                  # 5522A / 5520A with the scope option: the same procedure steps through drivers.Fluke5522AScope
            fluke = drivers.Fluke5522AScope(drivers.open_visa(fluke_addr, baud=baud), log, label=f'{self.cal_name()}')
        scope = (drivers.WaveSurfer4104HD(drivers.open_visa(scope_addr, timeout=scope_timeout), log)
                 if scope_addr else None)
        self._pm_bench(log, fluke, scope)
        return fluke, scope

    @staticmethod
    def show_channels_and_polarity(scope, ch, log):
        """DC voltage / offset points: all four channels are displayed during the readings (nothing is hidden from the technician, and the other channels are not left
        off by the reset), and the channel under test must not be inverted (an inverted channel reads the opposite sign).  Each step is read back."""
        for c in (1, 2, 3, 4):
            scope.enable_channel(c)
        if scope.ensure_not_inverted(ch):
            log.add('--', f'CH{ch} Invert was ON: turned OFF (read back)', 'WS4104HD')

    RESET_REUSE_S = 600.0              # a reset is not repeated for the next point of the same test run (same section, within this many seconds)

    def reset_bench(self, fluke, scope, log, key=None):
        """Reset the calibrator and the scope (the unit under test) to their default settings before the first point of a test; the
        unit-under-test notice is asked once per session of tests (reset_startup.SessionNotice). Raises ResetDeclined / ResetFailed."""
        notice = getattr(self, '_reset_notice', None)
        if notice is None:
            notice = self._reset_notice = reset_startup.SessionNotice(
                self.root, lambda text: port.ask_ok_cancel('Reset instruments', text, icon='warning', parent=self.root))
        now = time.monotonic()
        last = getattr(self, '_reset_last', None)
        if key is not None and last is not None and last[0] == key and now - last[1] < self.RESET_REUSE_S:
            self._reset_last = (key, now)                       # same test run: the instruments were reset at its first point, not again between points
            log.add('--', f'Instruments already reset at the start of this {key} run: not repeated between points', 'RESET')
            return
        reset_startup.reset_all([fluke] if fluke is not None else [], [scope] if scope is not None else [], confirm=notice, log=log)
        if key is not None:
            self._reset_last = (key, time.monotonic())

    def _pm_bench(self, log, *insts):
        """Procedure modifications: the command overrides are bound to each driver as it is opened, and a banner line goes at the top of
        the command log.  Nothing at all happens (no log line, no change) when no modification is stored."""
        st = self.pm_state
        if st is not None and st.oset:
            self.pm_bind_after_open(*insts)
            st.banner(log)

    def finish_bench(self, fluke, scope, log, name):
        """Common cleanup. Returns True when the Fluke is confirmed in standby (or was never opened)."""
        safe = True
        if fluke is not None and fluke._open:
            fluke.cleanup()          # STBY and confirm, never raises
            safe = fluke.standby_confirmed
        for inst in (scope, fluke):
            if inst is not None:
                try: inst.close()
                except Exception: pass
        self.save_command_log(log, name)
        return safe

    def save_command_log(self, log, name):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt (evidence for the run)."""
        try:
            folder = Path.home() / '.calibration_suite'
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {name}\n')
                f.write('\n'.join(log.lines()) + '\n')
        except OSError:
            pass

    def automatic_dcv_point(self, point, settle, fluke_addr, baud, scope_addr):
        """One DCV point through the instrument drivers: scope set up first, then calibrator output."""
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log)
            stage = 'Fluke serial open / identity'
            fluke.open()
            stage = 'scope USB open and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log, key='dcv')       # before the first point
            ch, scale, nominal = point['channel'], point['scale_v_div'], point['nominal_v']
            # Configure the scope before energizing the calibrator output.
            stage = 'scope vertical scale write / readback'
            scope.set_vertical_scale(ch, scale)
            stage = 'scope coupling and bandwidth configuration'
            scope.configure_dc_input(ch)
            stage = 'scope channels displayed, polarity'
            self.show_channels_and_polarity(scope, ch, log)
            stage = 'scope trigger Auto'
            scope.set_trigger_mode('Auto')            # the reset leaves the acquisition stopped: Auto keeps P1 updating
            stage = 'scope P1 MEAN configuration'
            scope.configure_p1(ch, 'Mean')
            stage = 'Fluke standby, SCOPE DCV, output level and OPER'
            fluke.apply_scope_dc(nominal)
            # The first P1 query is deliberately discarded to avoid a cached reading after the transition.
            stage = 'scope P1 reads'
            value = scope.read_p1_settled(settle)
            stage = 'Fluke standby after measurement'
            fluke.standby()
            self.events.put(('dc_auto_value', point, value))
        except Exception as exc:
            self.events.put(('dc_error', f'DCV communication failed at: {stage}\n{type(exc).__name__}: {exc}\nCheck Fluke STBY on the front panel before touching connections.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'DCV CH{point["channel"]} {point["nominal_v"]:+g} V'):
                self.events.put(('dc_safety', 'Fluke standby was NOT confirmed. Check the front panel and place it in STBY before disconnecting anything.'))
            self.events.put(('dc_idle',))

    def enter_dcv_manual(self, point):
        value=port.ask_number('Measured DC voltage',
            f'CH{point["channel"]} | {point["nominal_v"]:+.6f} V applied\n'
            'Enter measured oscilloscope MEAN in VOLTS:', parent=self.root)
        if value is None: return
        self.record_dcv(point,value,'manual')

    def read_dcv_scope(self, point):
        """Scope-only read: the operator has set the Fluke output by hand."""
        log=drivers.CommandLog()
        scope=None
        try:
            _f,scope=self.open_bench(None,0,self.visa_address.get().strip(),log)
            scope.open()
            scope.handshake()
            self.reset_bench(None, scope, log, key='dcv')       # reset to default settings before the first point
            ch=point['channel']
            scope.set_vertical_scale(ch,point['scale_v_div'],settle=0.0)
            scope.configure_dc_input(ch)
            self.show_channels_and_polarity(scope, ch, log)
            scope.set_trigger_mode('Auto')            # the reset leaves the acquisition stopped: Auto keeps P1 updating
            scope.configure_p1(ch,'Mean')
            time.sleep(1.5)
            self.events.put(('dc_value',point,scope.read_p1_when_ready()))
        except Exception as exc:
            self.events.put(('dc_error',str(exc)))
        finally:
            if scope:
                try:scope.close()
                except Exception:pass
            self.save_command_log(log,f'DCV scope read CH{point["channel"]}')

    def record_dcv(self,point,value,method,stats=None):
        if not math.isfinite(value):
            port.message('error', 'Invalid value','Measurement must be finite.')
            return
        row=dict(point, measured_v=value, error_v=value-point['nominal_v'],
                 result='PASS' if point['lower_v'] <= value <= point['upper_v'] else 'FAIL',
                 measurement_method=method,timestamp=datetime.now().isoformat(timespec='seconds'),
                 stimulus=(f'Fluke {self.cal_name()} SCOPE DCV / OUT / OPER / STBY' if method.startswith('automatic') else f'Fluke {self.cal_name()} guided/manual output'),
                 note='Limits from uploaded report; no guard band; scope P1 MEAN and source verified for automatic reads')
        if stats: row.update(stats)
        if method.endswith('selected-point retest'):
            # Match by point identity so sequential progress is never advanced.
            keys = ('channel', 'scale_v_div', 'nominal_v')
            matches = [i for i, old in enumerate(self.dc_rows)
                       if all(old[k] == point[k] for k in keys)]
            if len(matches) != 1:
                raise RuntimeError('Could not uniquely match retest to an existing result')
            idx = matches[0]
            previous = self.dc_rows[idx]
            history = list(previous.get('retest_history', []))
            history.append({k: v for k, v in previous.items() if k != 'retest_history'})
            row['retest_history'] = history
            row['retest_count'] = len(history)
            self.dc_rows[idx] = row
            self.save_dc_checkpoint()
            if self.ui_view.tab_open(self, 'dc_window'):
                self.refresh_dcv_table(selected_index=idx)
            self.dc_status.set(f'Retest saved for DCV point {idx+1}: {row["result"]}; '
                               f'{len(history)} previous result(s) retained.')
            return
        self.dc_rows.append(row)
        self.save_dc_checkpoint()
        if self.ui_view.tab_open(self, 'dc_window'): self.render_dcv(row)
        self.dc_status.set(f'Completed {len(self.dc_rows)} of 80 DCV points; last result {row["result"]}' +
                           (' — running channel automatically' if self.dc_batch else ''))

    def refresh_dcv_table(self, selected_index=None):
        done = len(self.dc_rows)
        items = []
        for i, p in enumerate(self.dcv_points()):
            if i < done:
                row = self.dc_rows[i]
                (nom, lo, hi), (meas, err), unit = ui.si_row([row["nominal_v"], row["lower_v"], row["upper_v"]], 'V',
                                                            [row["measured_v"], row["error_v"]])
                values = (f'CH{row["channel"]}', self.range_text(row["scale_v_div"]), nom, meas, lo, hi,
                          self._signed(err), unit, row['result'])
                items.append((values, self._tag(done, i, row['result'])))
            else:
                (nom, lo, hi), _r, unit = ui.si_row([p["nominal_v"], p["lower_v"], p["upper_v"]], 'V')
                values = (f'CH{p["channel"]}', self.range_text(p["scale_v_div"]), nom, '', lo, hi, '', unit, '\u2014')
                items.append((values, self._tag(done, i)))
        ids = self._set_grid(self.dc_tree, items, active=done)
        if selected_index is not None and selected_index < len(ids):
            self.ui_view.select_and_show(self.dc_tree, ids[selected_index])
        self.ui_view.set_value(self.dc_progress, done)

    def render_dcv(self, row):
        # Called after a result is appended: fill in that point's row and move the highlight on.
        self.refresh_dcv_table()

    def save_dc_checkpoint(self):
        tmp=self.dc_checkpoint.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version':6,'rows':self.dc_rows},indent=2),encoding='utf-8')
        tmp.replace(self.dc_checkpoint)

    def load_dc_checkpoint(self):
        if not self.dc_checkpoint.exists():return
        try:
            data=json.loads(self.dc_checkpoint.read_text(encoding='utf-8'))
            rows=data['rows']; points=self._pm_ckpt_points('dcv',rows)
            if not isinstance(rows,list) or len(rows)>len(points): raise ValueError('Invalid DCV checkpoint length')
            for idx,row in enumerate(rows):
                for key in ('channel','scale_v_div','nominal_v','lower_v','upper_v'):
                    if row[key]!=points[idx][key]:raise ValueError(f'Checkpoint mismatch at point {idx+1}: {key}')
            self.dc_rows=rows
        except Exception as exc:
            self.dc_status.set(f'Could not load DCV checkpoint: {exc}')

    def clear_dcv(self):
        if not port.ask_yes_no('Clear DCV results','Delete all DCV results and checkpoint?',parent=self.root):return
        self.dc_rows=[]
        self.dc_retest_index = None
        self.dc_checkpoint.unlink(missing_ok=True)
        self.refresh_dcv_table()
        self.ui_view.set_value(self.dc_progress, 0)
        self.dc_status.set('DCV results cleared')

    def export_dcv(self):
        self.export_calibration_section('dcv')

    # HAZ-OSC-02 input impedance verification: 6 points per channel, plus 4 EXT points.
    @staticmethod
    def impedance_points():
        points = []
        for ch in range(1, 5):
            for coupling, scale, nominal, low, high, label in (
                ('D50', .020, 50., 49., 51., '50 Ohm @ 20 mV/Div'),
                ('D50', .200, 50., 49., 51., '50 Ohm @ 200 mV/Div'),
                ('D1M', .020, 1e6, 980000., 1020000., '1 MOhm @ 20 mV/Div'),
                ('D1M', .200, 1e6, 980000., 1020000., '1 MOhm @ 200 mV/Div'),
                ('D1M', 2.000, 1e6, 980000., 1020000., '1 MOhm @ 2 V/Div'),
                ('A1M', .020, 1.2e6, 1176000., 1224000., '1.2 MOhm @ 20 mV/AC'),
            ):
                points.append(dict(channel=f'C{ch}', coupling=coupling, scale_v_div=scale,
                                   nominal_ohm=nominal, lower_ohm=low, upper_ohm=high, description=label))
        for name, coupling, nominal, low, high in (
            ('EXT', 'D1M', 1e6, 980000., 1020000.),
            ('EXT5', 'D1M', 1e6, 980000., 1020000.),
            ('EXT', 'D50', 50., 49., 51.),
            ('EXT5', 'D50', 50., 49., 51.),
        ):
            points.append(dict(channel=name, coupling=coupling, scale_v_div=None,
                               nominal_ohm=nominal, lower_ohm=low, upper_ohm=high,
                               description=f'{nominal:g} Ohm @ {name}'))
        return points

    def make_impedance_button(self):
        # Input Impedance has its own tab; no duplicate toolbar button needed.
        pass

    def show_impedance(self): self.ui_view.show_impedance(self)

    @staticmethod
    def parse_fluke_ohms(reply):
        parts = [part.strip().upper() for part in reply.split(',')]
        if len(parts) < 2 or parts[1] != 'OHM':
            raise ValueError(f'Fluke resistance reading not valid (expected OHM): {reply!r}')
        value = float(parts[0])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f'Invalid Fluke resistance value: {reply!r}')
        return value

    def resume_impedance(self):
        """Resume at the first unrecorded impedance point."""
        if self.running or self.dc_running or self.imp_running:
            port.message('warning', 'Busy', 'Wait for the current measurement to finish.', parent=self.root)
            return
        if len(self.imp_rows) >= len(self.impedance_points()):
            port.message('info', 'Complete', 'All 28 impedance points are recorded.', parent=self.root)
            return
        self.imp_status.set(f'Resuming impedance at point {len(self.imp_rows)+1} of 28.')
        self.start_impedance_batch()

    def start_impedance_batch(self):
        if self.running or self.dc_running or self.imp_running:
            port.message('warning', 'Busy', 'Wait for the current test to finish.', parent=self.root)
            return
        if len(self.imp_rows) >= len(self.impedance_points()):
            port.message('info', 'Complete', 'All 28 impedance measurements are recorded.', parent=self.root)
            return
        self.imp_batch = True
        self.imp_batch_success = False
        # A new run/resume requires confirmation of the actual cable connection.
        self.imp_connected_input = None
        self.next_impedance()

    def stop_impedance_batch(self):
        self.imp_batch = False
        self.imp_batch_success = False
        self.imp_status.set('Automatic impedance stopped. Current measurement will finish.')

    def next_impedance(self):
        if self.running or self.dc_running or self.imp_running:
            port.message('warning', 'Busy', 'Wait for the current test to finish.', parent=self.root)
            return
        if not self._pm_boundary('input impedance'):
            self.imp_batch = False
            return
        points = self.impedance_points()
        index = len(self.imp_rows)
        if index >= len(points):
            self.imp_batch = False
            self.imp_batch_success = False
            port.message('info', 'Complete', 'All 28 impedance measurements are complete.', parent=self.root)
            return
        point = points[index]
        try:
            settle = float(self.imp_settle.get())
            samples = int(self.imp_samples.get())
            baud = int(self.fluke_baud.get())
            if not math.isfinite(settle) or not .5 <= settle <= 30 or not 1 <= samples <= 20:
                raise ValueError()
        except ValueError:
            port.message('error', 'Settings', 'Settle: 0.5–30 seconds; readings: 1–20; baud: integer.', parent=self.root)
            return
        # Coupling and vertical scale are configured and verified automatically
        # on channels C1-C4. Only actual cable/input changes need confirmation.
        target = point['channel']
        ext = target.startswith('EXT')
        must_confirm = (self.imp_connected_input != target) if self.imp_batch else (
            not self.imp_connection_confirmed or
            not self.imp_rows or self.imp_rows[-1]['channel'] != target or
            self.imp_rows[-1]['coupling'] != point['coupling'])
        if must_confirm:
            mode = {'D50':'DC 50 Ω', 'D1M':'DC 1 MΩ', 'A1M':'AC 1 MΩ'}[point['coupling']]
            detail = (
                'EXT/EXT5 input selection and impedance are not remotely configured. '
                'Manually select the correct trigger mode and impedance for this point.'
                if ext else
                'The application will set and verify coupling and vertical scale automatically.'
            )
            prompt = dict(heading=f'Impedance point {index+1} of 28',
                steps=[('Output off', 'Verify the Fluke SCOPE MEASR output is OFF before moving the cable.'),
                       ('Connect', f'Fluke {self.cal_name()} SCOPE measurement cable directly to {target}. Remove other signal sources and external terminators.'),
                       ('Input mode', detail)],
                facts=[('Input', target), ('Test', point['description']), ('Input setting', mode)],
                caution='Click OK only after the cable and input mode are safe.',
                ok='Connected and safe \u2014 continue')
            if not port.operator_prompt('Confirm impedance connection', **prompt, parent=self.root):
                self.imp_batch = False
                self.imp_status.set('Automatic impedance paused for connection.')
                return
            self.imp_connection_confirmed = True
            self.imp_connected_input = target
        elif ext:
            # EXT/EXT5 modes require a manual change even without moving the BNC.
            previous = self.imp_rows[-1] if self.imp_rows else None
            if previous is None or previous['coupling'] != point['coupling']:
                mode = {'D50':'50 Ω', 'D1M':'1 MΩ'}[point['coupling']]
                if not port.operator_prompt('Confirm external trigger impedance',
                    f'Set {target} trigger input impedance',
                    [('Set the input', f'Trigger input impedance to {mode}.'),
                     ('Confirm', 'Check the setting before the resistance measurement.')],
                    facts=[('Input', target), ('Impedance', mode)], ok='Set \u2014 continue', parent=self.root):
                    self.imp_batch = False
                    return
        self.imp_running = True
        self.ui_view.set_state(self.imp_next_button, 'disabled')
        self.imp_status.set(f'Measuring {index+1}/28: {point["channel"]} — {point["description"]}')
        threading.Thread(target=self.impedance_worker,
                         args=(point, settle, samples, self.visa_address.get().strip(),
                               self.fluke_address.get().strip(), baud), daemon=True).start()

    def impedance_worker(self, point, settle, samples, scope_address, fluke_address, baud):
        log = drivers.CommandLog()
        fluke = scope = None
        scope_off_confirmed = False
        try:
            fluke, scope = self.open_bench(fluke_address, baud, scope_address, log)
            fluke.open()
            scope.open()
            self.reset_bench(fluke, scope, log, key='imp')       # reset to default settings before the first point
            scope.set_trigger_mode('Auto')            # the reset leaves the acquisition stopped
            # Disable previous scope function before any DUT reconfiguration.
            fluke.scope_off()
            ch = point['channel']
            if ch.startswith('C'):
                scope.set_coupling_legacy(ch, point['coupling'])
                # The point names the channel 'C1'..'C4' (classic command form); the VBS setter takes the number.
                scope.set_vertical_scale(int(ch[1:]), point['scale_v_div'], settle=0.0)
            # For EXT/EXT5, manual setup is required; do not silently treat EXT5 as a separate port.
            fluke.select_scope_measure_resistance()
            time.sleep(settle)
            values = []
            for _ in range(samples):
                values.append(fluke.measure_scope_resistance())
                time.sleep(.2)
            fluke.scope_off()
            scope_off_confirmed = True
            self.events.put(('imp_result', point, sum(values)/len(values), values))
        except Exception as exc:
            self.events.put(('imp_error', str(exc)))
        finally:
            if fluke is not None and fluke._open:
                try:
                    fluke.scope_off()
                    scope_off_confirmed = True
                except Exception:
                    scope_off_confirmed = False
            if not scope_off_confirmed:
                self.events.put(('imp_safety', 'Fluke SCOPE OFF was NOT confirmed. Check the Fluke front panel before changing connections.'))
            for inst in (scope, fluke):
                if inst is not None:
                    try: inst.close()
                    except Exception: pass
            self.save_command_log(log, f'Impedance {point["channel"]} {point["coupling"]}')
            self.events.put(('imp_idle',))

    def _retest_index(self, tree, rows, label, parent):
        if any((self.running, self.dc_running, self.imp_running, self.offset_running, self.bw_running, self.tb_running, self.trig_running)):
            port.message('warning', 'Busy', 'Finish the current measurement first.', parent=parent)
            return None
        selected = self.ui_view.selection(tree)
        if len(selected) != 1:
            port.message('info', 'Select a result', f'Select one completed {label} result.', parent=parent)
            return None
        idx = self.ui_view.row_index(tree, selected[0])
        if idx >= len(rows):
            port.message('info', 'Not tested yet', 'That point has not been measured yet. Pick a recorded row to retest, or use Run / Resume.', parent=parent)
            return None
        return idx

    def retest_impedance(self):
        idx = self._retest_index(self.imp_tree, self.imp_rows, 'impedance', self.imp_window)
        if idx is None: return
        point = self.impedance_points()[idx]
        if not self._retest_prompt('impedance', point['channel'], 'Confirm impedance retest', f'Retest impedance point {idx+1} of 28',
            [('Output off', 'Confirm the Fluke SCOPE measurement output is OFF before moving cables.'),
             ('Connection', 'Verify the correct connection and, for EXT inputs, the input impedance.')],
            facts=[('Input', point['channel']), ('Test', point['description'])],
            caution='The prior reading is replaced only after a successful retest.', ok='Ready \u2014 retest', parent=self.root): return
        try:
            settle=float(self.imp_settle.get()); samples=int(self.imp_samples.get()); baud=int(self.fluke_baud.get())
            if not (.5<=settle<=30 and 1<=samples<=20 and baud>0): raise ValueError()
        except ValueError:
            port.message('error', 'Settings', 'Check settle time, samples, and baud.', parent=self.root); return
        self.imp_batch=False
        self.imp_retest_index=idx
        self.imp_running=True
        self.ui_view.set_state(self.imp_next_button, 'disabled')
        self.imp_status.set(f'Retesting impedance point {idx+1}/28')
        threading.Thread(target=self.impedance_worker,
            args=(point,settle,samples,self.visa_address.get().strip(),
                  self.fluke_address.get().strip(),baud),daemon=True).start()

    def retest_offset(self):
        idx=self._retest_index(self.offset_tree,self.offset_rows,'offset',self.offset_tab)
        if idx is None:return
        point=self.offset_points()[idx]
        if not self._retest_prompt('offset', point['channel'], 'Confirm offset retest', f'Retest offset point {idx+1} of 16',
            [('Connection', 'Confirm the Fluke SCOPE cable is connected to the correct channel.')],
            facts=[('Channel', f'CH{point["channel"]}'), ('Scope offset', f'{point["scope_offset_v"]:+g} V')],
            caution='The prior reading is replaced only on success.', ok='Ready \u2014 retest', parent=self.root):return
        try:
            settle=float(self.offset_settle.get());baud=int(self.fluke_baud.get())
            if not (.5<=settle<=60 and baud>0):raise ValueError()
        except ValueError:
            port.message('error', 'Settings','Check settle time and baud.',parent=self.root);return
        self.offset_batch=False
        self.offset_retest_index=idx
        self.offset_running=True
        self.offset_status.set(f'Retesting offset point {idx+1}/16')
        threading.Thread(target=self.offset_worker,args=(point,settle,
            self.fluke_address.get().strip(),baud,self.visa_address.get().strip()),daemon=True).start()

    def retest_bandwidth(self):
        idx=self._retest_index(self.bw_tree,self.bw_rows,'bandwidth',self.bw_tab)
        if idx is None:return
        point=self.bandwidth_points()[idx]
        if not self._retest_prompt('bandwidth', point['channel'], 'Confirm bandwidth retest', f'Retest bandwidth point {idx+1} of 24',
            [('Signal path', 'Verify a rated 50 \u03a9 signal path and the scope DC50 input.'),
             ('Signal', 'The Fluke will generate a 1 GHz sine wave.')],
            facts=[('Channel', f'CH{point["channel"]}'), ('Range', self.range_text(point["scale_v_div"]))],
            caution='The prior result is replaced only on success.', ok='Ready \u2014 retest', parent=self.root):return
        try:
            settle=float(self.bw_settle.get());baud=int(self.fluke_baud.get())
            if not (.5<=settle<=60 and baud>0):raise ValueError()
        except ValueError:
            port.message('error', 'Settings','Check settle time and baud.',parent=self.root);return
        self.bw_batch=False
        self.bw_retest_index=idx
        self.bw_running=True
        self.bw_status.set(f'Retesting bandwidth point {idx+1}/24')
        threading.Thread(target=self.bandwidth_worker,args=(point,settle,
            self.fluke_address.get().strip(),baud,self.visa_address.get().strip()),daemon=True).start()

    def record_impedance(self, point, value, values):
        row = dict(point, measured_ohm=value, error_ohm=value-point['nominal_ohm'],
                   result='PASS' if point['lower_ohm'] <= value <= point['upper_ohm'] else 'FAIL',
                   individual_readings_ohm=';'.join(f'{x:.9g}' for x in values),
                   measurement_method=f'Fluke {self.cal_name()} SCOPE MEASR / *TRG',
                   timestamp=datetime.now().isoformat(timespec='seconds'),
                   note='HAZ-OSC-02 acceptance limits; no uncertainty guard band')
        retest_idx=getattr(self,'imp_retest_index',None)
        if retest_idx is not None:
            previous=self.imp_rows[retest_idx]
            row['retest_history']=previous.get('retest_history',[])+[{
                'timestamp':previous.get('timestamp'), 'result':previous.get('result'),
                'previous_row':{k:v for k,v in previous.items() if k!='retest_history'}}]
            self.imp_rows[retest_idx]=row
            self.imp_retest_index=None
        else:
            self.imp_rows.append(row)
        self.save_impedance_checkpoint()
        if self.ui_view.tab_open(self, 'imp_window'):
            self.refresh_impedance_table()
        self.imp_status.set(f'{len(self.imp_rows)}/28 complete — last: {value:.8g} Ω ({row["result"]})')

    def refresh_impedance_table(self):
        done = len(self.imp_rows)
        items = []
        for i, p in enumerate(self.impedance_points()):
            row = self.imp_rows[i] if i < done else None
            src = row or p
            scale = src['scale_v_div']
            (nom, lo, hi), reads, unit = ui.si_row([src["nominal_ohm"], src["lower_ohm"], src["upper_ohm"]], 'ohm',
                                                  [row["measured_ohm"]] if row else [])
            values = (i + 1, src['channel'], src['coupling'], self.range_text(scale),
                      nom, reads[0] if reads else '', lo, hi, unit, row['result'] if row else '\u2014')
            items.append((values, self._tag(done, i, row['result'] if row else None)))
        self._set_grid(self.imp_tree, items, active=done)
        self.ui_view.set_value(self.imp_progress, done)

    def render_impedance(self, index, row):
        self.refresh_impedance_table()

    def save_impedance_checkpoint(self):
        tmp = self.imp_checkpoint.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version':11, 'rows':self.imp_rows}, indent=2), encoding='utf-8')
        tmp.replace(self.imp_checkpoint)

    def load_impedance_checkpoint(self):
        if not self.imp_checkpoint.exists():
            return
        try:
            rows = json.loads(self.imp_checkpoint.read_text(encoding='utf-8'))['rows']
            points = self._pm_ckpt_points('impedance', rows)
            if not isinstance(rows, list) or len(rows) > len(points):
                raise ValueError('Invalid impedance checkpoint length')
            for idx, row in enumerate(rows):
                for field in ('channel','coupling','scale_v_div','nominal_ohm','lower_ohm','upper_ohm'):
                    if row[field] != points[idx][field]:
                        raise ValueError(f'Impedance checkpoint mismatch at point {idx+1}: {field}')
            self.imp_rows = rows
        except Exception as exc:
            self.imp_status.set(f'Could not restore impedance checkpoint: {exc}')

    def clear_impedance(self):
        if self.imp_running:
            return
        if not port.ask_yes_no('Clear impedance', 'Delete all impedance results and checkpoint?', parent=self.root):
            return
        self.imp_rows = []
        self.imp_connection_confirmed = False
        self.imp_connected_input = None
        self.imp_batch = False
        self.imp_checkpoint.unlink(missing_ok=True)
        self.refresh_impedance_table()
        self.ui_view.set_value(self.imp_progress, 0)
        self.imp_status.set('Impedance results cleared')

    def export_impedance(self):
        self.export_calibration_section('impedance')

    # Offset-position DC voltage verification. MEAN measures the sourced voltage,
    # not an independent center-position/offset accuracy measurement.
    @staticmethod
    def offset_points():
        pts = []
        for ch in range(1, 5):
            for scale, offset, tolerance in (
                (.020, -4.5, .050), (.020, 4.5, .050),
                (2.0, -10.0, .261), (2.0, 10.0, .261),
            ):
                stimulus = -offset
                pts.append(dict(channel=ch, scale_v_div=scale, scope_offset_v=offset,
                                nominal_v=stimulus, lower_v=stimulus-tolerance,
                                upper_v=stimulus+tolerance))
        return pts

    def show_offset(self): self.ui_view.show_offset(self)

    def start_offset(self):
        if self.offset_running or self.dc_running or self.imp_running or self.running:
            port.message('warning', 'Busy', 'Another instrument operation is running.',
                                   parent=self.root)
            return
        if len(self.offset_rows) >= 16:
            port.message('info', 'Complete', 'All 16 offset points are complete.',
                                parent=self.root)
            return
        try:
            settle = float(self.offset_settle.get())
            if not 0.5 <= settle <= 60:
                raise ValueError()
            int(self.fluke_baud.get())
        except ValueError:
            port.message('error', 'Invalid setup', 'Settle must be 0.5–60 seconds and baud numeric.',
                                 parent=self.root)
            return
        if not port.operator_prompt('Confirm offset test method', 'Offset-position DCV test',
            [('What this tests', 'P1 MEAN at specified scope vertical offsets. It does not independently verify waveform centering accuracy.'),
             ('Confirm', 'The intended test method, the limits, and the correct Fluke SCOPE BNC connection.')],
            caution='The program will enable and disable the DC voltage output.', ok='Confirmed \u2014 start', parent=self.root):
            return
        self.offset_batch = True
        self.offset_ok = False
        self.offset_connected_channel = None
        self.next_offset()

    def stop_offset(self):
        self.offset_batch = False
        self.offset_ok = False
        self.offset_status.set('Stopped after current point; saved results retained.')

    def next_offset(self):
        if not self.offset_batch or self.offset_running:
            return
        if not self._pm_boundary('offset'):
            self.offset_batch = False
            return
        points = self.offset_points()
        idx = len(self.offset_rows)
        if idx >= len(points):
            self.offset_batch = False
            self.offset_status.set('Complete — 16 of 16 offset points')
            port.message('info', 'Complete','All 16 offset points recorded.',parent=self.root)
            return
        point = points[idx]
        ch = point['channel']
        if self.offset_connected_channel != ch:
            if not port.operator_prompt('Offset cable connection',
                f'Connect the Fluke SCOPE output to CH{ch}',
                [('Standby', 'Confirm the Fluke is in STBY.'),
                 ('Connect', f'Fluke SCOPE output to CH{ch}. Disconnect other sources and terminators.')],
                facts=[('Point', f'{idx+1} of 16'), ('Channel', f'CH{ch}')],
                caution='Press OK only after the connection is safe.', ok='Connected and safe \u2014 continue', parent=self.root):
                self.offset_batch = False
                self.offset_status.set('Paused — awaiting safe cable connection')
                return
            self.offset_connected_channel = ch
        self.offset_running = True
        self.offset_status.set(
            f'Running {idx+1}/16: CH{ch} | offset {point["scope_offset_v"]:+.3f} V | '
            f'Fluke {point["nominal_v"]:+.3f} V')
        args=(point, float(self.offset_settle.get()),self.fluke_address.get().strip(),
              int(self.fluke_baud.get()),self.visa_address.get().strip())
        threading.Thread(target=self.offset_worker,args=args,daemon=True).start()

    def offset_worker(self, point, settle, fluke_addr, baud, scope_addr):
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=15)
            stage = 'Fluke serial connection / identity'
            fluke.open()
            stage = 'Fluke standby'
            fluke.standby()
            stage = 'Scope USB connection and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log, key='offset')       # before the first point
            ch = point['channel']
            stage = 'Scope scale'
            scope.set_vertical_scale(ch, point['scale_v_div'])
            stage = 'Scope DC1M and 20 MHz'
            scope.configure_dc_input(ch)
            stage = 'Scope channels displayed, polarity'
            self.show_channels_and_polarity(scope, ch, log)
            stage = 'Scope vertical offset'
            scope.set_vertical_offset(ch, point['scope_offset_v'])
            stage = 'Scope trigger Auto'
            scope.set_trigger_mode('Auto')            # the reset leaves the acquisition stopped: Auto keeps P1 updating
            stage = 'P1 MEAN setup'
            scope.configure_p1(ch, 'Mean')
            stage = 'Fluke SCOPE DCV mode'
            fluke.select_scope_dcv('1M')
            stage = 'Fluke output setting'
            programmed = fluke.set_dc_volts(point['nominal_v'])
            stage = 'Fluke OPER'
            fluke.operate()
            stage = 'Settling, discarding first P1 read, final P1 MEAN'
            value = scope.read_p1_settled(settle)
            stage = 'Fluke standby after point'
            fluke.standby()
            self.events.put(('offset_result', point, value, programmed))
        except Exception as exc:
            self.events.put(('offset_error', f'Failure at {stage}: {type(exc).__name__}: {exc}\n'
                             'Verify Fluke STBY on the front panel before touching cables.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'Offset CH{point["channel"]} {point["scope_offset_v"]:+g} V'):
                self.events.put(('offset_safety',
                    'Fluke standby NOT confirmed. Inspect Fluke front panel; do not disconnect until STBY.'))
            self.events.put(('offset_idle',))

    def record_offset(self,point,measured,programmed):
        row=dict(point,fluke_programmed_v=programmed,measured_v=measured,
                 error_v=measured-point['nominal_v'],
                 result='PASS' if point['lower_v']<=measured<=point['upper_v'] else 'FAIL',
                 method=f'Fluke {self.cal_name()} SCOPE DCV / scope P1 MEAN at programmed offset',
                 timestamp=datetime.now().isoformat(timespec='seconds'))
        retest_idx=getattr(self,'offset_retest_index',None)
        if retest_idx is not None:
            previous=self.offset_rows[retest_idx]
            row['retest_history']=previous.get('retest_history',[])+[{
                'timestamp':previous.get('timestamp'), 'result':previous.get('result'),
                'previous_row':{k:v for k,v in previous.items() if k!='retest_history'}}]
            self.offset_rows[retest_idx]=row
            self.offset_retest_index=None
        else:
            self.offset_rows.append(row)
        self.save_offset_checkpoint()
        self.refresh_offset()

    def refresh_offset(self):
        done = len(self.offset_rows)
        items = []
        for i, p in enumerate(self.offset_points()):
            if i < done:
                row = self.offset_rows[i]
                (off, src, lo, hi), (mean, err), unit = ui.si_row(
                    [row["scope_offset_v"], row["fluke_programmed_v"], row["lower_v"], row["upper_v"]], 'V',
                    [row["measured_v"], row["error_v"]], extra=3)
                values = (f'CH{row["channel"]}', self.range_text(row["scale_v_div"]), self._signed(off), self._signed(src),
                          self._signed(mean), self._signed(err), self._signed(lo), self._signed(hi), unit, row['result'])
                items.append((values, self._tag(done, i, row['result'])))
            else:
                (off, src, lo, hi), _r, unit = ui.si_row(
                    [p["scope_offset_v"], p["nominal_v"], p["lower_v"], p["upper_v"]], 'V')
                values = (f'CH{p["channel"]}', self.range_text(p["scale_v_div"]), self._signed(off), self._signed(src),
                          '', '', self._signed(lo), self._signed(hi), unit, '\u2014')
                items.append((values, self._tag(done, i)))
        self._set_grid(self.offset_tree, items, active=done)
        self.ui_view.set_value(self.offset_progress, done)
        self.offset_status.set(f'{done} of 16 offset-position DCV points recorded')

    def save_offset_checkpoint(self):
        self.offset_checkpoint.write_text(json.dumps(self.offset_rows,indent=2),
                                          encoding='utf-8')

    def load_offset_checkpoint(self):
        if not self.offset_checkpoint.exists():
            return
        try:
            rows=json.loads(self.offset_checkpoint.read_text(encoding='utf-8'))
            points=self._pm_ckpt_points('offset',rows)
            if not isinstance(rows,list) or len(rows)>16:
                raise ValueError('Invalid checkpoint length')
            for i,row in enumerate(rows):
                if not isinstance(row,dict) or any(
                    row.get(k)!=points[i][k] for k in ('channel','scale_v_div',
                                                         'scope_offset_v','nominal_v')):
                    raise ValueError(f'Checkpoint point {i+1} mismatch')
            self.offset_rows=rows
            self.refresh_offset()
        except Exception as exc:
            port.message('warning', 'Offset checkpoint',f'Could not load offset results: {exc}',
                                   parent=self.root)

    def export_offset(self):
        self.export_calibration_section('offset')

    @staticmethod
    def bandwidth_points():
        return [
            dict(channel=ch,scale_v_div=scale,amplitude_vpp=6*scale,
                 reference_hz=50000,high_hz=1000000000,lower_db=-3.0,upper_db=3.0)
            for ch in range(1,5)
            for scale in (.010,.020,.050,.100,.200,.500)
        ]

    def show_bandwidth(self): self.ui_view.show_bandwidth(self)

    def start_bandwidth(self):
        if any((self.bw_running,self.dc_running,self.imp_running,self.offset_running,self.running)):
            port.message('warning', 'Busy','An instrument operation is running.',parent=self.root)
            return
        if len(self.bw_rows)==24:
            port.message('info', 'Complete','All 24 bandwidth points are complete.',parent=self.root)
            return
        try:
            settle=float(self.bw_settle.get())
            baud=int(self.fluke_baud.get())
            if not math.isfinite(settle) or not .5<=settle<=60 or baud<=0:
                raise ValueError()
        except ValueError:
            port.message('error', 'Invalid settings','Settle must be 0.5–60 s; baud must be positive.',
                                 parent=self.root)
            return
        if not port.operator_prompt('Confirm high-frequency test', 'Bandwidth test \u2014 1 GHz sine',
            [('Signal path', 'Use a rated 50 \u03a9 signal path, the correct Fluke SCOPE output and the scope 50 \u03a9 input.'),
             ('No extra termination', 'Do not use a 1 M\u03a9 input, or a 50 \u03a9 feedthrough in addition to the scope internal termination.'),
             ('Confirm method', 'The Fluke LEVSINE command and the scope P1 PkPk measurement are suitable.')],
            caution='The Fluke will generate a 1 GHz sine signal into the oscilloscope. The first point is a hardware pilot.',
            ok='Confirmed \u2014 start', parent=self.root):
            return
        self.bw_batch=True
        self.bw_ok=False
        self.bw_connected_channel=None
        self.next_bandwidth()

    def stop_bandwidth(self):
        self.bw_batch=False
        self.bw_ok=False
        self.bw_status.set('Paused; completed points retained.')

    def next_bandwidth(self):
        if not self.bw_batch or self.bw_running:
            return
        if not self._pm_boundary('bandwidth'):
            self.bw_batch = False
            return
        idx=len(self.bw_rows)
        if idx>=24:
            self.bw_batch=False
            self.bw_status.set('Complete — 24/24 bandwidth points')
            port.message('info', 'Bandwidth complete','All 24 points recorded.',parent=self.root)
            return
        point=self.bandwidth_points()[idx]
        ch=point['channel']
        if self.bw_connected_channel!=ch:
            if not port.operator_prompt('Move 50 \u03a9 signal cable', f'Connect the Fluke SCOPE output to CH{ch}',
                [('Standby', 'Verify the Fluke output is STBY.'),
                 ('Connect', f'A rated 50 \u03a9 cable from the Fluke SCOPE output to CH{ch}.'),
                 ('Automatic', 'The scope input is set to DC50 for you.')],
                facts=[('Point', f'{idx+1} of 24'), ('Channel', f'CH{ch}')],
                caution='Confirm the connection before the output is enabled.', ok='Connected \u2014 continue', parent=self.root):
                self.bw_batch=False
                self.bw_status.set('Paused — waiting for safe cable connection')
                return
            self.bw_connected_channel=ch
        self.bw_running=True
        self.bw_status.set(f'Running {idx+1}/24: CH{ch} '
                           f'{point["scale_v_div"]*1000:g} mV/div '
                           f'{point["amplitude_vpp"]:g} Vpp')
        args=(point,float(self.bw_settle.get()),self.fluke_address.get().strip(),
              int(self.fluke_baud.get()),self.visa_address.get().strip())
        threading.Thread(target=self.bandwidth_worker,args=args,daemon=True).start()

    @staticmethod
    def read_bandwidth_vpp(scope):
        val=scope.read_p1_when_ready()
        if val<=0:
            raise RuntimeError(f'Invalid P1 PkPk amplitude {val}')
        return val

    def bandwidth_worker(self,point,settle,fluke_addr,baud,scope_addr):
        log=drivers.CommandLog()
        fluke=scope=None
        stage='opening instruments'
        try:
            fluke,scope=self.open_bench(fluke_addr,baud,scope_addr,log)
            stage='Fluke connection / identity'
            fluke.open()
            stage='Fluke standby'
            fluke.standby()
            stage='Scope connection'
            scope.open()
            stage='reset to default settings'
            self.reset_bench(fluke,scope,log, key='bw')       # before the first point
            ch=point['channel']
            amplitude=point['amplitude_vpp']
            stage='Scope scale'
            scope.set_vertical_scale(ch,point['scale_v_div'])
            stage='Scope vertical offset'
            scope.ensure_zero_offset(ch)
            stage='Scope 50 Ω coupling'
            scope.set_coupling(ch,'DC50')
            stage='Scope Full bandwidth'
            scope.set_bandwidth_limit(ch,'Full')
            stage='Scope trigger source'
            # Source verification is mandatory: never silently measure the wrong channel.
            scope.set_edge_trigger_source(ch)
            stage='Scope trigger Auto'
            scope.set_trigger_mode('Auto')            # the reset leaves the acquisition stopped: Auto keeps P1 updating
            stage='Scope P1 PkPk'
            scope.configure_p1(ch,'PkPk')
            stage='Scope 50 kHz horizontal timebase (10 us/div)'
            scope.set_timebase(10e-6)
            stage='Fluke LEVSINE 50 kHz'
            fluke.select_scope_levsine()
            fluke.set_levsine(amplitude,50e3)
            stage='Fluke output 50 kHz'
            fluke.operate()
            time.sleep(settle)
            self.read_bandwidth_vpp(scope)  # discard settling reading
            time.sleep(.35)
            reference=self.read_bandwidth_vpp(scope)
            # Detect severe clipping or missing signal before moving to 1 GHz.
            if not .4*amplitude<=reference<=1.6*amplitude:
                raise RuntimeError(
                    f'50 kHz measured {reference:.6g} Vpp vs {amplitude:.6g} Vpp '
                    '(possible clipping, wrong signal units, cable or P1 configuration).')
            stage='Fluke standby before frequency change'
            fluke.standby()
            stage='Scope 1 GHz horizontal timebase (1 ns/div)'
            scope.set_timebase(1e-9)
            stage='Fluke LEVSINE 1 GHz'
            fluke.set_levsine(amplitude,1e9)
            stage='Fluke output 1 GHz'
            fluke.operate()
            time.sleep(settle)
            self.read_bandwidth_vpp(scope)
            time.sleep(.35)
            high=self.read_bandwidth_vpp(scope)
            stage='Fluke standby after point'
            fluke.standby()
            self.events.put(('bw_result',point,reference,high))
        except Exception as exc:
            self.events.put(('bw_error',
                f'{stage}: {type(exc).__name__}: {exc}\n'
                'Check Fluke STBY on front panel before handling cables. '
                'For VI_ERROR_IO, close other VISA applications, reconnect scope USB, '
                'and retry after the scope is responsive.'))
        finally:
            if not self.finish_bench(fluke,scope,log,f'Bandwidth CH{point["channel"]} {point["amplitude_vpp"]:g} Vpp'):
                self.events.put(('bw_safety',
                    'Fluke STBY NOT confirmed. Inspect front panel; do not disconnect.'))
            self.events.put(('bw_idle',))

    def record_bandwidth(self,point,reference,high):
        response=20*math.log10(high/reference)
        row=dict(point,reference_measured_vpp=reference,high_measured_vpp=high,
                 response_db=response,
                 result='PASS' if point['lower_db']<=response<=point['upper_db'] else 'FAIL',
                 method='SCOPE LEVSINE; P1 PkPk; DC50; Full BW',
                 timestamp=datetime.now().isoformat(timespec='seconds'))
        retest_idx=getattr(self,'bw_retest_index',None)
        if retest_idx is not None:
            previous=self.bw_rows[retest_idx]
            row['retest_history']=previous.get('retest_history',[])+[{
                'timestamp':previous.get('timestamp'), 'result':previous.get('result'),
                'previous_row':{k:v for k,v in previous.items() if k!='retest_history'}}]
            self.bw_rows[retest_idx]=row
            self.bw_retest_index=None
        else:
            self.bw_rows.append(row)
        self.save_bandwidth_checkpoint()
        self.refresh_bandwidth()
        if len(self.bw_rows)==1 and self.bw_batch:
            self.bw_batch=False
            self.bw_status.set('Pilot point complete — review measured amplitudes and response; click Run / Resume to continue.')
            port.message('info', 'First-point validation',
                f'CH1 at 10 mV/div:\n50 kHz: {reference:.6g} Vpp\n'
                f'1 GHz: {high:.6g} Vpp\nResponse: {response:+.3f} dB\n\n'
                'Review the Fluke and scope setup before continuing the remaining 23 points.',
                parent=self.root)

    def refresh_bandwidth(self):
        done = len(self.bw_rows)
        items = []
        for i, p in enumerate(self.bandwidth_points()):
            if i < done:
                r = self.bw_rows[i]
                (amp,), (ref, hi), vunit = ui.si_row([r["amplitude_vpp"]], 'Vpp',
                                                    [r["reference_measured_vpp"], r["high_measured_vpp"]], extra=2)
                values = (f'CH{r["channel"]}', self.range_text(r["scale_v_div"]), amp, ref, hi, vunit,
                          f'{r["response_db"]:+.3f}', 'dB', r['result'])
                items.append((values, self._tag(done, i, r['result'])))
            else:
                (amp,), _r, vunit = ui.si_row([p["amplitude_vpp"]], 'Vpp')
                values = (f'CH{p["channel"]}', self.range_text(p["scale_v_div"]), amp, '', '', vunit, '', 'dB', '\u2014')
                items.append((values, self._tag(done, i)))
        self._set_grid(self.bw_tree, items, active=done)
        self.ui_view.set_value(self.bw_progress, done)
        self.bw_status.set(f'{done} of 24 bandwidth points recorded')

    def save_bandwidth_checkpoint(self):
        temp=self.bw_checkpoint.with_suffix('.tmp')
        temp.write_text(json.dumps(self.bw_rows,indent=2),encoding='utf-8')
        temp.replace(self.bw_checkpoint)

    def load_bandwidth_checkpoint(self):
        if not self.bw_checkpoint.exists():
            return
        try:
            rows=json.loads(self.bw_checkpoint.read_text(encoding='utf-8'))
            points=self.bandwidth_points()
            if not isinstance(rows,list) or len(rows)>24:
                raise ValueError('Invalid checkpoint length')
            for i,row in enumerate(rows):
                if not isinstance(row,dict) or any(
                    row.get(k)!=points[i][k] for k in
                    ('channel','scale_v_div','amplitude_vpp','reference_hz','high_hz')):
                    raise ValueError(f'Checkpoint point {i+1} mismatch')
            self.bw_rows=rows
            self.refresh_bandwidth()
        except Exception as exc:
            port.message('warning', 'Bandwidth checkpoint',
                f'Could not load saved bandwidth points: {exc}',parent=self.root)

    def export_bandwidth(self):
        self.export_calibration_section('bandwidth')



    # ======================================================================== time base accuracy (one point)
    # Limit from the HAZ-OSC-02 data sheet, page 10 (read from the rendered page image): error 0.00 Hz, -0.350 to +0.350 Hz.
    # The sheet does not state the stimulus. The technician recalled a time marker; the marker period is a Test setting
    # (default 10 us = 100 kHz, where +/-0.35 Hz is +/-3.5 ppm) and is saved with the result and printed on the report.
    def _tb_period(self):
        try:
            us = float(self.tb_period_us.get())
        except ValueError:
            return None
        return us * 1e-6 if math.isfinite(us) and 0.001 <= us <= 1e6 else None

    def timebase_points(self):
        period = self._tb_period() or 10e-6
        return [dict(channel=1, marker_period_s=period, nominal_hz=1.0 / period, scale_v_div=TB_SCALE,
                     lower_hz=-TIMEBASE_LIMIT_HZ, upper_hz=TIMEBASE_LIMIT_HZ)]

    def show_timebase(self): self.ui_view.show_timebase(self)

    def _tb_settings(self):
        try:
            settle, samples, baud = float(self.tb_settle.get()), int(self.tb_samples.get()), int(self.fluke_baud.get())
            if not (.5 <= settle <= 60 and 1 <= samples <= 50 and baud > 0) or self._tb_period() is None:
                raise ValueError()
        except ValueError:
            port.message('error', 'Time base settings', 'Settle must be 0.5-60 s, samples 1-50, the marker period a positive number of '
                                 'microseconds and the baud numeric (Test settings).', parent=self.root)
            return None
        return settle, samples, baud

    def _tb_confirm(self, title, heading, point):
        period, nominal = point['marker_period_s'], point['nominal_hz']
        return port.operator_prompt(title, heading,
            [('Standby', 'Confirm the Fluke is in STBY.'),
             ('Connect', 'Fluke SCOPE output to CH1 with a 50 Ω cable. Remove other cables and any feedthrough terminator.'),
             ('Automatic', 'The program sets CH1 to DC 50 Ω, full bandwidth and P1 Freq, then outputs the time marker.')],
            facts=[('Marker period', f'{period*1e6:g} µs'), ('Frequency', f'{nominal/1e3:g} kHz'),
                   ('Limit', f'±{TIMEBASE_LIMIT_HZ:.3f} Hz')],
            caution=f'First hardware run: the {self.cal_name()} SCOPE MARKER commands are not yet verified. The test stops without enabling the '
                    'output if the calibrator rejects them. Check the marker period against your procedure (Test settings).',
            ok='Connected and safe — run', parent=self.root)

    def start_timebase(self):
        if self._batch_busy():
            port.message('warning', 'Busy', 'Another instrument operation is running.', parent=self.root)
            return
        if self.tb_rows:
            port.message('info', 'Complete', 'The time base point is recorded. Use Rerun Selected to measure it again.', parent=self.root)
            return
        cfg = self._tb_settings()
        if cfg is None:
            return
        point = self.timebase_points()[0]
        if not self._tb_confirm('Time base accuracy', 'Connect the Fluke SCOPE output to CH1', point):
            self.tb_status.set('Time base not run - connection not confirmed')
            return
        self._run_timebase(point, cfg)

    def retest_timebase(self):
        idx = self._retest_index(self.tb_tree, self.tb_rows, 'time base', self.tb_tab)
        if idx is None:
            return
        cfg = self._tb_settings()
        if cfg is None:
            return
        point = self.timebase_points()[0]
        if not self._tb_confirm('Confirm time base retest', 'Retest the time base point', point):
            return
        self.tb_retest_index = idx
        self._run_timebase(point, cfg)

    def _run_timebase(self, point, cfg):
        settle, samples, baud = cfg
        self.tb_running = True
        self.tb_status.set(f'Running time base: {point["marker_period_s"]*1e6:g} µs marker on CH1')
        threading.Thread(target=self.timebase_worker, args=(point, settle, samples, self.fluke_address.get().strip(), baud,
                                                            self.visa_address.get().strip()), daemon=True).start()

    def timebase_worker(self, point, settle, samples, fluke_addr, baud, scope_addr):
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=15)
            stage = 'Fluke serial connection / identity'
            fluke.open()
            stage = 'Fluke standby'
            fluke.standby()
            stage = 'Scope USB connection and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log, key='tb')       # before the first point
            ch, period = point['channel'], point['marker_period_s']
            stage = 'Scope scale and zero offset'
            scope.set_vertical_scale(ch, point['scale_v_div'])
            scope.ensure_zero_offset(ch)
            stage = 'Scope DC 50 Ω and full bandwidth'
            scope.set_coupling(ch, 'DC50')
            scope.set_bandwidth_limit(ch, 'Full')
            stage = 'Scope edge trigger (CH1, positive, Auto)'
            scope.set_edge_trigger_source(ch)
            scope.set_trigger_slope('Positive')
            scope.set_trigger_level(TB_TRIGGER_V)
            scope.set_trigger_mode('Auto')
            stage = 'Scope horizontal scale (about 100 marker periods on screen)'
            scope.set_timebase(10 * period)
            stage = 'Scope P1 Freq'
            scope.configure_p1(ch, 'Freq')
            stage = 'Fluke SCOPE MARKER'
            fluke.select_scope_marker()
            stage = 'Fluke marker period'
            fluke.set_marker_period(period)
            stage = 'Fluke OPER'
            fluke.operate()
            stage = 'Settling, discarding first P1 read'
            time.sleep(settle)
            scope.read_p1_when_ready()
            stage = 'P1 Freq readings'
            readings = []
            for _ in range(samples):
                time.sleep(self.pm_param('ws.tb_read_gap', TB_READ_GAP_S))
                readings.append(scope.read_p1_when_ready())
            stage = 'Fluke standby after point'
            fluke.standby()
            mean = sum(readings) / len(readings)
            if not 0.99 * point['nominal_hz'] <= mean <= 1.01 * point['nominal_hz']:
                raise RuntimeError(f'P1 Freq averaged {mean:.9g} Hz, more than 1 % away from {point["nominal_hz"]:.9g} Hz '
                                   '(wrong marker period, no signal, cable or P1 setup). No result recorded.')
            self.events.put(('tb_result', point, readings, list(fluke.stale_errors)))
        except Exception as exc:
            self.events.put(('tb_error', f'Failure at {stage}: {type(exc).__name__}: {exc}\n'
                             'Verify Fluke STBY on the front panel before touching cables.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'Time base {point["marker_period_s"]*1e6:g} us marker'):
                self.events.put(('tb_safety', 'Fluke standby NOT confirmed. Inspect the Fluke front panel; do not disconnect until STBY.'))
            self.events.put(('tb_idle',))

    def record_timebase(self, point, readings, stale_errors=()):
        mean = sum(readings) / len(readings)
        error = mean - point['nominal_hz']
        spread = (sum((x - mean) ** 2 for x in readings) / (len(readings) - 1)) ** .5 if len(readings) > 1 else 0.0
        row = dict(point, readings_hz=readings, mean_hz=mean, error_hz=error, stdev_hz=spread,
                   result='PASS' if point['lower_hz'] <= error <= point['upper_hz'] else 'FAIL',
                   method=f'Fluke {self.cal_name()} SCOPE MARKER {point["marker_period_s"]*1e6:g} us into DC 50 Ohm; scope P1 Freq, mean of {len(readings)}',
                   timestamp=datetime.now().isoformat(timespec='seconds'),
                   note='Limits from HAZ-OSC-02 data sheet; no guard band')
        if stale_errors:
            row['fluke_errors_cleared_before_marker'] = list(stale_errors)   # from earlier sessions, read out before SCOPE MARKER
        idx = self.tb_retest_index
        if idx is not None:
            previous = self.tb_rows[idx]
            row['retest_history'] = previous.get('retest_history', []) + [{
                'timestamp': previous.get('timestamp'), 'result': previous.get('result'),
                'previous_row': {k: v for k, v in previous.items() if k != 'retest_history'}}]
            self.tb_rows[idx] = row
            self.tb_retest_index = None
        else:
            self.tb_rows.append(row)
        self.save_timebase_checkpoint()
        self.refresh_timebase()

    def refresh_timebase(self):
        items = []
        for i, p in enumerate(self.timebase_points()):
            r = self.tb_rows[i] if i < len(self.tb_rows) else None
            src = r or p
            values = (f'{src["marker_period_s"]*1e6:g} µs', f'{src["nominal_hz"]:.9g}',
                      f'{r["mean_hz"]:.9g}' if r else '', f'{r["error_hz"]:+.4f}' if r else '',
                      f'{src["lower_hz"]:+.3f}', f'{src["upper_hz"]:+.3f}', 'Hz', r['result'] if r else '—')
            items.append((values, self._tag(len(self.tb_rows), i, r['result'] if r else None)))
        self._set_grid(self.tb_tree, items, active=len(self.tb_rows))
        self.tb_status.set(f'{len(self.tb_rows)} of 1 time base point recorded')

    def save_timebase_checkpoint(self):
        temp = self.tb_checkpoint.with_suffix('.tmp')
        temp.write_text(json.dumps(self.tb_rows, indent=2), encoding='utf-8')
        temp.replace(self.tb_checkpoint)

    def load_timebase_checkpoint(self):
        if not self.tb_checkpoint.exists():
            return
        try:
            rows = json.loads(self.tb_checkpoint.read_text(encoding='utf-8'))
            if not isinstance(rows, list) or len(rows) > 1:
                raise ValueError('Invalid checkpoint length')
            for row in rows:
                if not isinstance(row, dict) or row.get('channel') != 1 or not row.get('marker_period_s') \
                        or not self._pm_limits_ok(row, 'timebase', (-TIMEBASE_LIMIT_HZ, TIMEBASE_LIMIT_HZ)):
                    raise ValueError('Checkpoint point mismatch')
            self.tb_rows = rows
            self.refresh_timebase()
        except Exception as exc:
            port.message('warning', 'Time base checkpoint', f'Could not load the saved time base result: {exc}', parent=self.root)

    # ======================================================================== trigger level accuracy (24 points, bracket test)
    # Limits from the HAZ-OSC-02 data sheet, pages 10-11 (rendered page images): CH1-CH4 x 0 / +300 / -300 mV x positive and
    # negative slope, level +/-20 mV. Method agreed with the technician: scope armed in Single at the level, the Fluke steps
    # SCOPE DCV from 100 mV before the level to 20 mV short of it (must NOT trigger), then to 20 mV past it (must trigger).
    # The operator answers both questions. A pass shows the trigger fired within +/-20 mV; no voltage is measured.
    @staticmethod
    def trigger_points():
        return [dict(channel=ch, scale_v_div=TRIG_SCALE, level_v=level, slope=slope,
                     lower_v=round(level - TRIG_LIMIT_V, 6), upper_v=round(level + TRIG_LIMIT_V, 6))
                for ch in range(1, 5) for level in TRIG_LEVELS for slope in ('Positive', 'Negative')]

    @staticmethod
    def trigger_outcome(row):
        if row.get('triggered_short'):
            return 'Triggered 20 mV early'
        if row.get('triggered_past') is False:
            return 'No trigger 20 mV past'
        return 'Within ±20 mV'

    def show_trigger(self): self.ui_view.show_trigger(self)

    def _trig_settings(self):
        try:
            settle, baud = float(self.trig_settle.get()), int(self.fluke_baud.get())
            if not (.2 <= settle <= 30 and baud > 0):
                raise ValueError()
        except ValueError:
            port.message('error', 'Trigger level settings', 'Settle must be 0.2-30 s and the baud numeric (Test settings).', parent=self.root)
            return None
        return settle, baud

    def start_trigger(self):
        if self._batch_busy():
            port.message('warning', 'Busy', 'Another instrument operation is running.', parent=self.root)
            return
        if len(self.trig_rows) >= len(self.trigger_points()):
            port.message('info', 'Complete', 'All 24 trigger level points are recorded.', parent=self.root)
            return
        if self._trig_settings() is None:
            return
        if not port.operator_prompt('Trigger level test method', 'Trigger level accuracy — you confirm each trigger',
            [('Setup', 'The program sets the channel to 100 mV/div, DC 1 MΩ, 20 MHz BW, edge trigger on that channel at the test level, '
                       'and arms a Single acquisition.'),
             ('Step 1', 'The Fluke steps to 20 mV SHORT of the level. You answer whether the scope triggered (it should not).'),
             ('Step 2', 'The Fluke steps to 20 mV PAST the level. You answer whether the scope triggered (it should).'),
             ('Triggered means', 'the trigger status changes from armed/Single to Stopped and a trace is captured.')],
            caution='The Fluke SCOPE DC output is enabled (at most 0.4 V) while you answer, and returns to STBY after every point. '
                    'The scope trigger commands are not yet verified on a 4104HD: check the first point on screen.',
            ok='Understood — start', parent=self.root):
            return
        self.trig_batch = True
        self.trig_ok = False
        self.trig_connected_channel = None
        self.next_trigger()

    def stop_trigger(self):
        self.trig_batch = False
        self.trig_ok = False
        self.trig_status.set('Stopped after the current point; saved results retained.')

    def next_trigger(self):
        if not self.trig_batch or self.trig_running:
            return
        if not self._pm_boundary('trigger level'):
            self.trig_batch = False
            return
        points = self.trigger_points()
        idx = len(self.trig_rows)
        if idx >= len(points):
            self.trig_batch = False
            self.trig_status.set('Complete — 24 of 24 trigger level points')
            port.message('info', 'Complete', 'All 24 trigger level points recorded.', parent=self.root)
            return
        point = points[idx]
        ch = point['channel']
        if self.trig_connected_channel != ch:
            if not port.operator_prompt('Trigger level cable connection', f'Connect the Fluke SCOPE output to CH{ch}',
                [('Standby', 'Confirm the Fluke is in STBY.'),
                 ('Connect', f'Fluke SCOPE output to CH{ch} (1 MΩ input, no terminator). Disconnect other sources.')],
                facts=[('Point', f'{idx+1} of 24'), ('Channel', f'CH{ch}')],
                caution='Press OK only after the connection is safe.', ok='Connected and safe — continue', parent=self.root):
                self.trig_batch = False
                self.trig_status.set('Paused — awaiting safe cable connection')
                return
            self.trig_connected_channel = ch
        self._run_trigger(idx, point)

    def retest_trigger(self):
        idx = self._retest_index(self.trig_tree, self.trig_rows, 'trigger level', self.trig_tab)
        if idx is None:
            return
        if self._trig_settings() is None:
            return
        point = self.trigger_points()[idx]
        if not self._retest_prompt('trigger', point['channel'], 'Confirm trigger level retest', f'Retest trigger level point {idx+1} of 24',
            [('Connection', f'Confirm the Fluke SCOPE output is connected to CH{point["channel"]}.'),
             ('You confirm', 'You will be asked twice whether the scope triggered.')],
            facts=[('Channel', f'CH{point["channel"]}'), ('Level', f'{point["level_v"]*1000:+.0f} mV'), ('Slope', point['slope'])],
            caution='The prior result is replaced only when the retest completes.', ok='Ready — retest', parent=self.root):
            return
        self.trig_batch = False
        self.trig_retest_index = idx
        self._run_trigger(idx, point)

    def _run_trigger(self, idx, point):
        settle, baud = self._trig_settings()
        self.trig_running = True
        self.trig_status.set(f'Running {idx+1}/24: CH{point["channel"]} | {point["level_v"]*1000:+.0f} mV | {point["slope"]} slope')
        threading.Thread(target=self.trigger_worker, args=(point, settle, self.fluke_address.get().strip(), baud,
                                                           self.visa_address.get().strip()), daemon=True).start()

    def ask_operator(self, title, question):
        """From a worker thread: show a Yes / No / Cancel question on the Tk thread and wait for the answer."""
        reply = queue.Queue()
        self.events.put(('ask', title, question, reply))
        return reply.get()

    def trigger_worker(self, point, settle, fluke_addr, baud, scope_addr):
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        ch, level, slope = point['channel'], point['level_v'], point['slope']
        sign = 1 if slope == 'Positive' else -1
        start, short, past = (round(level - sign * TRIG_START_V, 6), round(level - sign * TRIG_LIMIT_V, 6),
                              round(level + sign * TRIG_LIMIT_V, 6))
        title = f'Trigger level CH{ch} {level*1000:+.0f} mV {slope.lower()} slope'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=15)
            stage = 'Fluke serial connection / identity'
            fluke.open()
            stage = 'Fluke standby'
            fluke.standby()
            stage = 'Scope USB connection and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log, key='trig')       # before the first point
            stage = 'Scope scale, DC 1 MΩ / 20 MHz and zero offset'
            scope.set_vertical_scale(ch, point['scale_v_div'])
            scope.configure_dc_input(ch)
            scope.ensure_zero_offset(ch)
            scope.set_timebase(TRIG_HSCALE)
            stage = 'Scope edge trigger source, slope and level'
            scope.set_edge_trigger_source(ch)
            scope.set_trigger_slope(slope)
            level_readback = scope.set_trigger_level(level)
            stage = f'Fluke SCOPE DCV {start*1000:+.0f} mV (100 mV before the level) and OPER'
            fluke.apply_scope_dc(start)
            time.sleep(settle)
            stage = 'Scope arm Single'
            armed = scope.set_trigger_mode('Single', accept=('Stopped',))
            if armed.casefold() == 'stopped':
                raise RuntimeError('The scope triggered as soon as it was armed, before the Fluke stepped. No result recorded.')
            time.sleep(0.5)
            stage = f'Fluke step to {short*1000:+.0f} mV (20 mV short of the level)'
            fluke.set_dc_volts(short)
            if not fluke.is_operating():
                raise RuntimeError('The Fluke left OPERATE when the level changed.')
            time.sleep(settle)
            stage = 'Operator: trigger before the level?'
            triggered_short = self.ask_operator(title,
                f'The Fluke now outputs {short*1000:+.0f} mV, 20 mV short of the {level*1000:+.0f} mV trigger level '
                f'({slope.lower()} slope).\n\nDid the scope TRIGGER (status changed to Stopped, trace captured)?\n\n'
                'Yes = it triggered   No = still armed   Cancel = abandon this point')
            triggered_past = None
            if triggered_short is None:
                raise OperatorCancelled()
            if not triggered_short:
                stage = f'Fluke step to {past*1000:+.0f} mV (20 mV past the level)'
                fluke.set_dc_volts(past)
                if not fluke.is_operating():
                    raise RuntimeError('The Fluke left OPERATE when the level changed.')
                time.sleep(settle)
                stage = 'Operator: trigger past the level?'
                triggered_past = self.ask_operator(title,
                    f'The Fluke now outputs {past*1000:+.0f} mV, 20 mV past the {level*1000:+.0f} mV trigger level '
                    f'({slope.lower()} slope).\n\nDid the scope TRIGGER now?\n\n'
                    'Yes = it triggered   No = still armed   Cancel = abandon this point')
                if triggered_past is None:
                    raise OperatorCancelled()
            stage = 'Fluke standby after point'
            fluke.standby()
            self.events.put(('trig_result', point, dict(start_v=start, short_v=short, past_v=past, level_readback_v=level_readback,
                                                        triggered_short=bool(triggered_short), triggered_past=triggered_past)))
        except OperatorCancelled:
            self.events.put(('trig_cancel', 'Point abandoned at the operator prompt. Nothing was recorded.'))
        except Exception as exc:
            self.events.put(('trig_error', f'Failure at {stage}: {type(exc).__name__}: {exc}\n'
                             'Verify Fluke STBY on the front panel before touching cables.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'Trigger CH{ch} {level*1000:+.0f} mV {slope}'):
                self.events.put(('trig_safety', 'Fluke standby NOT confirmed. Inspect the Fluke front panel; do not disconnect until STBY.'))
            self.events.put(('trig_idle',))

    def record_trigger(self, point, info):
        passed = not info['triggered_short'] and info['triggered_past'] is True
        row = dict(point, **info, result='PASS' if passed else 'FAIL',
                   method=f'Bracket: Fluke {self.cal_name()} SCOPE DCV stepped to 20 mV short of and 20 mV past the level; scope Single edge trigger; operator confirmed',
                   timestamp=datetime.now().isoformat(timespec='seconds'),
                   note='Limits from HAZ-OSC-02 data sheet; pass/fail by bracket, no trigger voltage measured')
        row['outcome'] = self.trigger_outcome(row)
        idx = self.trig_retest_index
        if idx is not None:
            previous = self.trig_rows[idx]
            row['retest_history'] = previous.get('retest_history', []) + [{
                'timestamp': previous.get('timestamp'), 'result': previous.get('result'),
                'previous_row': {k: v for k, v in previous.items() if k != 'retest_history'}}]
            self.trig_rows[idx] = row
            self.trig_retest_index = None
        else:
            self.trig_rows.append(row)
        self.save_trigger_checkpoint()
        self.refresh_trigger()

    def refresh_trigger(self):
        done = len(self.trig_rows)
        items = []
        for i, p in enumerate(self.trigger_points()):
            r = self.trig_rows[i] if i < done else None
            values = (f'CH{p["channel"]}', f'{p["level_v"]*1000:+.2f}', p['slope'], f'{p["lower_v"]*1000:+.2f}', f'{p["upper_v"]*1000:+.2f}',
                      r['outcome'] if r else '', r['result'] if r else '—')
            items.append((values, self._tag(done, i, r['result'] if r else None)))
        self._set_grid(self.trig_tree, items, active=done)
        self.trig_status.set(f'{done} of 24 trigger level points recorded')

    def save_trigger_checkpoint(self):
        temp = self.trig_checkpoint.with_suffix('.tmp')
        temp.write_text(json.dumps(self.trig_rows, indent=2), encoding='utf-8')
        temp.replace(self.trig_checkpoint)

    def load_trigger_checkpoint(self):
        if not self.trig_checkpoint.exists():
            return
        try:
            rows = json.loads(self.trig_checkpoint.read_text(encoding='utf-8'))
            points = self._pm_ckpt_points('trigger', rows)
            if not isinstance(rows, list) or len(rows) > len(points):
                raise ValueError('Invalid checkpoint length')
            for i, row in enumerate(rows):
                if not isinstance(row, dict) or any(row.get(k) != points[i][k] for k in ('channel', 'level_v', 'slope', 'lower_v', 'upper_v')):
                    raise ValueError(f'Checkpoint point {i+1} mismatch')
            self.trig_rows = rows
            self.refresh_trigger()
        except Exception as exc:
            port.message('warning', 'Trigger level checkpoint', f'Could not load saved trigger level results: {exc}', parent=self.root)


    def load_demo_data(self):
        """Synthetic, memory-only export test data; no VISA, no checkpoint writes."""
        if any((self.rows,self.dc_rows,self.imp_rows,self.offset_rows,self.bw_rows,self.tb_rows,self.trig_rows)):
            port.message('warning', 'Demo data',
                'Existing calibration results are loaded. Demo data will not be mixed with them. '
                'Use a separate empty folder to launch --demo.')
            return
        self.demo_mode=True
        port.set_title(self.root, 'DEMO DATA ONLY — WaveSurfer Calibration Export Tester')
        stamp=datetime.now().isoformat(timespec='seconds')
        channels=list(range(1,5))
        scales=SCALES
        self.run_config=dict(channels=channels,channel=1,address='DEMO — NO INSTRUMENT',
            delay=3,samples=5,factor=2.75,limits=LIMITS)
        for ch in channels:
            for j,scale in enumerate(scales):
                minimum=LIMITS[j]
                db=minimum+2.5+(ch+j)%4*.7
                if ch==2 and j==3: db=minimum-1.1
                rms=(2.75*scale)/(10**(db/20))
                self.add_result(dict(channel=ch,scale_v_div=scale,rms_volts=rms,
                    db=db,minimum_db=minimum,margin_db=db-minimum,
                    result='PASS' if db>=minimum else 'FAIL',samples=5,
                    timestamp=stamp,synthetic=True))
        for i,point in enumerate(self.dcv_points()):
            p=dict(point)
            tolerance=(p['upper_v']-p['lower_v'])/2
            measured=p['nominal_v']+tolerance*(1.12 if i==8 else .14*((i%5)-2))
            p.update(measured_v=measured,error_v=measured-p['nominal_v'],
                result='PASS' if p['lower_v']<=measured<=p['upper_v'] else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.dc_rows.append(p)
        self.refresh_dcv_table()
        for i,point in enumerate(self.impedance_points()):
            p=dict(point)
            nominal=p['nominal_ohm']
            measured=nominal*(1.025 if i==2 else 1+.001*((i%7)-3))
            p.update(measured_ohm=measured,error_ohm=measured-nominal,
                result='PASS' if p['lower_ohm']<=measured<=p['upper_ohm'] else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.imp_rows.append(p)
            self.render_impedance(i+1,p)
        self.ui_view.set_value(self.imp_progress, len(self.imp_rows))
        for i,point in enumerate(self.offset_points()):
            p=dict(point)
            tolerance=(p['upper_v']-p['lower_v'])/2
            measured=p['nominal_v']+tolerance*(1.2 if i==4 else .16*((i%5)-2))
            p.update(fluke_programmed_v=p['nominal_v'],measured_v=measured,
                error_v=measured-p['nominal_v'],
                result='PASS' if p['lower_v']<=measured<=p['upper_v'] else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.offset_rows.append(p)
        self.refresh_offset()
        for i,point in enumerate(self.bandwidth_points()):
            p=dict(point)
            reference=p['amplitude_vpp']*(.995+.001*(i%5))
            response=-1.2-.14*(i%6)
            if i==12: response=-3.4
            high=reference*10**(response/20)
            p.update(reference_measured_vpp=reference,high_measured_vpp=high,
                response_db=response,
                result='PASS' if -3<=response<=3 else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.bw_rows.append(p)
        self.refresh_bandwidth()
        for point in self.timebase_points():
            p=dict(point)
            readings=[p['nominal_hz']*(1+1.1e-7)+.004*((k%3)-1) for k in range(5)]
            mean=sum(readings)/len(readings)
            p.update(readings_hz=readings,mean_hz=mean,error_hz=mean-p['nominal_hz'],stdev_hz=.004,
                result='PASS' if p['lower_hz']<=mean-p['nominal_hz']<=p['upper_hz'] else 'FAIL',synthetic=True,timestamp=stamp)
            self.tb_rows.append(p)
        self.refresh_timebase()
        for i,point in enumerate(self.trigger_points()):
            p=dict(point,triggered_short=(i==9),triggered_past=None if i==9 else True,synthetic=True,timestamp=stamp)
            p['result']='FAIL' if i==9 else 'PASS'
            p['outcome']=self.trigger_outcome(p)
            self.trig_rows.append(p)
        self.refresh_trigger()
        self.status.set('DEMO MODE — Synthetic data only; no instrument measurements')
        self.dc_status.set('DEMO DATA — 80 synthetic DCV points')
        self.imp_status.set('DEMO DATA — 28 synthetic impedance points')
        self.offset_status.set('DEMO DATA — 16 synthetic offset points')
        self.bw_status.set('DEMO DATA — 24 synthetic bandwidth points')
        self.tb_status.set('DEMO DATA — 1 synthetic time base point')
        self.trig_status.set('DEMO DATA — 24 synthetic trigger level points')
        port.message('info', 'Demo export ready',
            f'Loaded {sum(len(r) for r in (self.rows,self.dc_rows,self.imp_rows,self.offset_rows,self.bw_rows,self.tb_rows,self.trig_rows))} '
            'SYNTHETIC results in memory across seven functions. '
            'Use Export Report (PDF). '
            'No checkpoint files were written. Do not use as calibration evidence.')


    @staticmethod
    def cert_number(value, decimals=5):
        if value is None:
            return ''
        return f'{float(value):.{decimals}f}'.rstrip('0').rstrip('.') if decimals else str(value)

    @staticmethod
    def cert_scale(scale):
        if scale is None:
            return ''
        if scale < .001:
            return f'{scale*1e6:g}uV/Div'
        if scale < 1:
            return f'{scale*1000:g}mV/Div'
        return f'{scale:g}V/Div'

    @staticmethod
    def _dc_budget_value(volts, sc, standard='5560A'):
        """(value, 'V') for a DC level the Fluke 5560A applies to a 1 MOhm input: the larger of the 5560A budget (its published DC voltage specification /
        coverage divisor, k = 2) and the scope's oscilloscope DC CMC, unrounded; None when the scope has no entry for the level.  The CMC dominates
        at every WS4104HD level today (the budget is below 3 % of it); the budget only matters if the sheet or the divisor is edited."""
        import uncertainty_budget
        b=uncertainty_budget.osc_dc(volts,'1M',standard,sc)
        return (b.value,'V') if b is not None else None

    def scope_uncertainty_value(self, kind, r):
        """(value, unit) of the uncertainty for one result - the number behind scope_uncertainty - or None when the scope has no entry.
        DC gain, offset and trigger level: larger of the 5560A budget and the scope CMC; impedance and bandwidth: the scope CMC alone."""
        sc=__import__('report_pdf').scope()
        if sc is None:
            return None
        try:
            if kind=='dcv':
                return self._dc_budget_value(r['nominal_v'],sc,self.cal_std())   # absolute volts, as the row is in volts
            elif kind=='impedance':
                value,unit,_=sc.oscilloscope('impedance',ohms=r['nominal_ohm'])
            elif kind=='offset':
                return self._dc_budget_value(r['nominal_v'],sc,self.cal_std())
            elif kind=='timebase':
                # the 5560A scope marker is locked to the GPS-referenced lab standard: the lab's Frequency - Measure CMC at the marker frequency, on its own
                value,unit=sc.dmm('FREQ',r['nominal_hz'],None,None,basis='measure'),'Hz'
            elif kind=='bandwidth':
                value,unit,_=sc.oscilloscope('bandwidth',volts_pp=r['amplitude_vpp'],frequency=r['high_hz'])
            elif kind=='trigger':
                # Based on the DC voltage the Fluke sources for the point: the two bracket steps (20 mV short of and 20 mV past the
                # level) decide pass/fail, so the larger of the two is used (the CMC grows with the level). Absolute volts, 1 MOhm.
                if 'short_v' in r and 'past_v' in r:
                    sourced=max(abs(r['short_v']),abs(r['past_v']))
                else:
                    sourced=abs(r['level_v'])+TRIG_LIMIT_V          # results saved before the sourced steps were recorded
                return self._dc_budget_value(sourced,sc,self.cal_std())
            else:
                return None
        except (KeyError,TypeError,ZeroDivisionError):
            return None
        return (value,unit) if value is not None else None

    def scope_uncertainty(self, kind, r):
        """CMC from the laboratory's A2LA scope for one result ('' when the scope has no entry, e.g. RMS noise)."""
        import uncertainty
        parts=self.scope_uncertainty_value(kind,r)
        return uncertainty.format_value(parts[0],parts[1]) if parts is not None else ''

    # Tolerance (half the width of the limits, in the unit of the row's base values) per kind: (low key, high key, unit)
    _TOL_KEYS={'dcv':('lower_v','upper_v','V'),'impedance':('lower_ohm','upper_ohm','ohm'),'offset':('lower_v','upper_v','V'),
               'bandwidth':('lower_db','upper_db','dB'),'trigger':('lower_v','upper_v','V'),'timebase':('lower_hz','upper_hz','Hz')}

    def tar_tur_fields(self, kind, r):
        """dict(TAR, TUR) strings for one result record, used only when the report asks for them.
        TUR = tolerance / the scope CMC printed in the Uncertainty column (same value, rounded up), only when both are in the same unit
        (volts, ohm, dB): DC gain, impedance, offset, bandwidth and trigger level.  RMS noise and time base have no printed uncertainty: blank.
        TAR only where the Fluke 5560A sources plain DC volts (DC gain, offset, trigger level): its specmanager DCV row at that voltage,
        in volts.  Impedance (a measurement) and bandwidth (leveled sine, tolerance in dB) have no matching specification row: TAR blank."""
        import tartur, uncertainty
        try:
            keys=self._TOL_KEYS.get(kind)
            if keys is None:
                return dict(TAR='',TUR='')
            parts=self.scope_uncertainty_value(kind,r)
            u=uu=None
            if parts is not None:
                u,uu=uncertainty.round_up(parts[0]),parts[1]
            acc=au=None
            if kind in ('dcv','offset'):
                acc,au=tartur.standard_accuracy(self.cal_std(),'DCV',abs(r['nominal_v']))
            elif kind=='trigger':
                if 'short_v' in r and 'past_v' in r:
                    sourced=max(abs(r['short_v']),abs(r['past_v']))
                else:
                    sourced=abs(r['level_v'])+TRIG_LIMIT_V
                acc,au=tartur.standard_accuracy(self.cal_std(),'DCV',sourced)
            tol=tartur.half_width(r[keys[0]],r[keys[1]])
            return tartur.ratio_fields(tartur.from_values(tol,keys[2],acc,au,u,uu))
        except Exception:
            return dict(TAR='',TUR='')

    def certificate_rows(self, kind, with_uncertainty=False):
        """Report rows: the As Found readings, with the As Left reading beside any point that was measured again after an adjustment
        ('Same' is printed by the PDF for the others)."""
        frows = self._cert_records(kind, self._stored_rows(datamode.FOUND, kind), with_uncertainty)
        lrows = self._cert_records(kind, self._stored_rows(datamode.LEFT, kind), with_uncertainty)
        out = []
        for i in range(max(len(frows), len(lrows))):
            f = frows[i] if i < len(frows) else None
            l = lrows[i] if i < len(lrows) else None
            if f is None:                                   # measured only after the adjustment
                row = dict(l, **{'As Found': '', 'OOT': '', 'As Left': l['As Found'], 'As Left OOT': bool(l['OOT'])})
            else:
                row = dict(f)
                if l is not None:
                    row['As Left'] = l['As Found']
                    row['As Left OOT'] = bool(l['OOT'])
            row['Seq.'] = len(out) + 1
            out.append(row)
        return out

    def certificate_source_records(self, kind):
        """The stored result record behind each row of certificate_rows(kind), in the same order (As Found, else the As Left one)."""
        found=self._stored_rows(datamode.FOUND,kind)
        left=self._stored_rows(datamode.LEFT,kind)
        return [found[i] if i < len(found) else left[i] for i in range(max(len(found),len(left)))]

    def _cert_records(self, kind, data, with_uncertainty=False):
        result=[]
        for r in data:
            ch=r.get('channel','')
            channel = str(ch) if str(ch).upper().startswith(('C','EXT')) else f'Ch. {ch}'
            scale=self.cert_scale(r.get('scale_v_div'))
            if kind=='noise':
                desc=f'{channel} RMS Noise {scale}'
                nominal=self.cert_number(r.get('minimum_db'),3)
                lower=self.cert_number(r.get('minimum_db'),3)
                upper=''
                uom='dB'
                measured=self.cert_number(r.get('db'),4)
            elif kind=='dcv':
                desc=f'{channel} 1MOhm DC Gain {scale}'
                factor=1000 if abs(r['nominal_v']) < 1 else 1
                uom='mV' if factor==1000 else 'V'
                nominal=self.cert_number(r['nominal_v']*factor,6)
                lower=self.cert_number(r['lower_v']*factor,6)
                upper=self.cert_number(r['upper_v']*factor,6)
                measured=self.cert_number(r['measured_v']*factor,6)
            elif kind=='impedance':
                desc=f'{channel} Impedance {scale} {r.get("coupling", "")}'.strip()
                # Display the MOhm values in MOhm, the 50-Ohm values in Ohm.
                factor=1e6 if r['nominal_ohm']>=1e5 else 1
                uom='MOhm' if factor>1 else 'Ohm'
                nominal=self.cert_number(r['nominal_ohm']/factor,6)
                lower=self.cert_number(r['lower_ohm']/factor,6)
                upper=self.cert_number(r['upper_ohm']/factor,6)
                measured=self.cert_number(r['measured_ohm']/factor,6)
            elif kind=='offset':
                desc=f'{channel} Offset {r["scope_offset_v"]:+g}V {scale} (P1 Mean)'
                nominal=self.cert_number(r['nominal_v'],6)
                lower=self.cert_number(r['lower_v'],6)
                upper=self.cert_number(r['upper_v'],6)
                uom='V'
                measured=self.cert_number(r['measured_v'],6)
            elif kind=='timebase':
                desc=(f'Time Base Accuracy, {r["marker_period_s"]*1e6:g} us marker '
                      f'({self.cert_number(r["nominal_hz"]/1e3,6)} kHz)')
                nominal='0'
                lower=self.cert_number(r['lower_hz'],3)
                upper=self.cert_number(r['upper_hz'],3)
                uom='Hz'
                measured=self.cert_number(r['error_hz'],4)
            elif kind=='trigger':
                level_mv='0' if r['level_v']==0 else f'{r["level_v"]*1000:+.0f}'
                desc=f'{channel} Trigger Level {level_mv} mV @ {"Pos" if r["slope"]=="Positive" else "Neg"} slope'
                nominal=self.cert_number(r['level_v']*1000,3)
                lower=self.cert_number(r['lower_v']*1000,3)
                upper=self.cert_number(r['upper_v']*1000,3)
                uom='mV'
                measured=r.get('outcome') or self.trigger_outcome(r)
            else:
                desc=f'{channel} FULL BW {scale}'
                amp=r['amplitude_vpp']
                amp_label=(f'{self.cert_number(amp*1000,5)} mVpp' if amp<1
                           else f'{self.cert_number(amp,5)} Vpp')
                nominal=f'0 dB @ {amp_label} @ {r["high_hz"]/1e9:g} GHz' 
                lower=self.cert_number(r['lower_db'],3)
                upper=self.cert_number(r['upper_db'],3)
                uom='dB'
                measured=self.cert_number(r['response_db'],4)
            uncertainty_text=self.scope_uncertainty(kind,r) if with_uncertainty else ''
            result.append({
                'Seq.': len(result)+1,
                'Description': desc,
                'Nominal': nominal,
                'Tolerance -': lower,
                'Tolerance +': upper,
                'UOM': uom,
                'As Found': measured,
                'OOT': 'OOT' if r.get('result')=='FAIL' else '',
                'As Left': '',
                'Uncertainty': uncertainty_text,
            })
        return result

    def export_calibration_section(self,kind):
        if not self.sync_asset():
            return
        rows=self.certificate_rows(kind)
        if not rows:
            port.message('info', 'No results',f'No {kind} measurements to export.')
            return
        details=port.report_details('WaveSurfer 4104HD verification', parent=self.root)
        if details is None:
            return
        filename=port.save_file(
            defaultextension='.pdf',
            initialfile=ui.report_filename(self.instrument_id.get(),'.pdf',kind),
            filetypes=[('PDF report','*.pdf')])
        if not filename:
            return
        self.write_certificate_pdf(filename,[kind],details)

    def write_certificate_pdf(self, filename, sections, details=None):
        """'Calibration Data' PDF: laid out as a printable report."""
        titles={'noise':'RMS Noise','dcv':'DC Gain (1 MOhm)','impedance':'Input Impedance','offset':'DC Offset','bandwidth':'Bandwidth',
                'timebase':'Time Base Accuracy','trigger':'Trigger Level Accuracy'}
        rows=[]
        sources=[]
        for kind in sections:
            for row in self.certificate_rows(kind,with_uncertainty=True):
                row=dict(row)
                if not row.get('As Left'):
                    row['As Left']='Same'
                row['Section']=titles[kind]
                rows.append(row)
            sources.extend((kind,r) for r in self.certificate_source_records(kind))
        if not rows:
            port.message('info', 'No results','No recorded calibration data to export.')
            return 0
        try:
            import report_pdf
            if details is None:
                details=port.report_details('WaveSurfer 4104HD verification', parent=self.root)
                if details is None:
                    return 0
            if report_pdf.details_tar_tur(details):
                rows=report_pdf.apply_tar_tur(rows,report_pdf.details_tar_tur(details),[self.tar_tur_fields(k,r) for k,r in sources])
            count=report_pdf.write_calibration_pdf(
                filename,rows,header=[('Instrument','Teledyne LeCroy WaveSurfer 4104HD'),
                                      ('Instrument ID',self.instrument_id.get().strip() or 'NOT ENTERED'),
                                      ('Serial',self.serial.get().strip())],
                demo=self.any_synthetic(),details=details,
                footer_note=report_pdf.uncertainty_note(rows,self.cal_std()),title='Calibration Data',
                snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency','Install the PDF package with:  py -m pip install reportlab')
            return 0
        except Exception as exc:
            port.message('error', 'PDF export error',str(exc))
            return 0
        port.message('info', 'Report exported',f'Created calibration data report with {count} rows:\n{filename}')
        return count

    def export_pdf_report(self):
        if not self.sync_asset():
            return
        sections=[k for k in ('noise','dcv','impedance','offset','bandwidth','timebase','trigger') if self.certificate_rows(k)]
        if not sections:
            port.message('info', 'No results','No recorded calibration data to export.')
            return
        try:
            import report_pdf
        except ImportError as exc:
            port.message('error', 'Report export',str(exc))
            return
        details=port.report_details('WaveSurfer 4104HD verification', parent=self.root)
        if details is None:
            return
        filename=port.save_file(
            defaultextension='.pdf',
            initialfile=ui.report_filename(self.instrument_id.get()),
            filetypes=[('PDF report','*.pdf')])
        if filename:
            self.write_certificate_pdf(filename,sections,details)


# Procedure modifications: every section's point list goes through pm_section_points().  The original functions are left exactly as
# they were; these wrappers return THEIR list unchanged (the same object contents) unless a tolerance modification is in effect.
PM_POINT_METHODS = {'dcv': 'dcv_points', 'impedance': 'impedance_points', 'offset': 'offset_points', 'bandwidth': 'bandwidth_points',
                    'timebase': 'timebase_points', 'trigger': 'trigger_points'}


def _pm_wrap_points(section, name):
    raw = RMSNoiseApp.__dict__[name]
    static = isinstance(raw, staticmethod)
    orig = raw.__func__ if static else raw

    def points(self):
        pts = orig() if static else orig(self)
        return self.pm_section_points(section, pts)
    points.__name__, points.__doc__ = name, orig.__doc__
    points.pm_orig, points.pm_static = orig, static
    setattr(RMSNoiseApp, name, points)


for _section, _name in PM_POINT_METHODS.items():
    _pm_wrap_points(_section, _name)


if __name__ == '__main__':
    port.view(RMSNoiseApp.VIEW).enable_hidpi()
    port.run_app(RMSNoiseApp)
