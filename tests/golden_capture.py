"""Golden command transcripts for the instrument drivers and the engines' bench I/O.

Purpose: prove that refactoring the drivers (command registry, overrides) does not change a single byte on the wire.
Every public driver method that sends a command is run with fixed arguments through a simulated transport (drivers/simulated*.py)
or, where a simulator cannot answer, a small scripted fake that returns plausible fixed replies. What is recorded is the exact sequence of
strings written and queried (write vs query marked), the CommandLog text (the log_as form, so a password is masked), the sleeps, the
transport control calls (open / close / clear / set_timeout) and the return value or exception of the call. It is NOT a test of
instrument behaviour: the scripted replies exist only to drive the code down each branch.

    capture_driver_transcripts()  -> {driver_name: [entry, ...]}        in-process, needs no tkinter
    capture_engine_transcripts()  -> {engine_name: [entry, ...]}        in a subprocess (tkinter is stubbed there)
    python -m tests.golden_capture --update     rewrite tests/golden/*.json (the flag is mandatory; with no flag it only prints a summary)

Determinism: time.sleep / time.time / time.monotonic are replaced by a fake clock that records sleeps, HOME is a temporary directory,
random is seeded, and CommandLog timestamps are dropped. No password is ever written: the 8846A calibration-security commands are
masked on the wire record too, and a sentinel password is used that the tests assert is absent from every fixture.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import random
import re
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / 'golden'
sys.path.insert(0, str(ROOT))

import drivers  # noqa: E402
from drivers import (Agilent34401A, AgilentAFG, Fluke28x, Fluke5520A, Fluke5522A, Fluke5560A, Fluke5790B, Fluke8846A, Fluke96270A,  # noqa: E402
                     Instrument, InstrumentError, Keysight33210A, Keysight33220A, Keysight33250A, Keysight34460A, Keysight34461A,
                     Keysight34465A, Keysight34470A, Keysight34970A, Keysight34972A, Keysight53131A, Keysight53132A, ReferenceMeter,
                     TektronixMDO4000C, TektronixTDS2000C, Transport, TransportError, WaveSurfer4104HD)
from drivers import Fluke5522AScope  # noqa: E402
from drivers import Fluke5522AComp, Keithley2000, Keithley2000Cal, Keysight34410A, Keysight34411A  # noqa: E402
from drivers import Agilent3458A  # noqa: E402
from drivers import fluke_28x  # noqa: E402
from drivers.keysight_332xx import Keysight332xx  # noqa: E402
from drivers.keysight_5313x import Keysight5313x  # noqa: E402
from drivers.keysight_dacq import KeysightDacq  # noqa: E402
from drivers.keysight_truevolt import KeysightTruevolt  # noqa: E402
from drivers.scpi_dmm import ScpiDmm  # noqa: E402
from drivers.fluke_8808a import Fluke8808A  # noqa: E402
from drivers.fluke_8808a_cal import Fluke8808ACal  # noqa: E402
from drivers.simulated_8808a_cal import make_8808a_cal_bench  # noqa: E402
from drivers.simulated_8808a import make_8808a_bench  # noqa: E402
from drivers.simulated import make_bench, make_dacq_bench, make_dmm_bench  # noqa: E402
from drivers.simulated_28x import SimFluke28x  # noqa: E402
from drivers.simulated import SimBench  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402
from drivers.simulated_k2000 import make_k2000_bench  # noqa: E402
from drivers.simulated_k2000_cal import SIM_CODE, make_k2000_cal_bench  # noqa: E402
from drivers.simulated_k2000_cal import _steps as k2000_cal_steps  # noqa: E402
from drivers.simulated_34410a import make_34410a_bench  # noqa: E402
from drivers.simulated_3458a import make_3458a_bench  # noqa: E402
from drivers.simulated_mdo import make_mdo_bench  # noqa: E402
from drivers.simulated_tds import make_tds_bench  # noqa: E402
from drivers.simulated_tbs import make_tbs1000_bench, make_tbs1000c_bench  # noqa: E402
from drivers.tektronix_tbs1000 import TektronixTBS1000  # noqa: E402
from drivers.tektronix_tbs1000c import TektronixTBS1000C  # noqa: E402

SCHEMA = 1
SENTINEL_PASSWORD = 'GOLDEN_SENTINEL_PW'       # not a real password; asserted absent from every fixture

# =====================================================================================================================================
# What counts as covered: every public method defined on a driver class is listed here, either as `covered` (a golden case exists whose
# name starts with "Class.method") or as `no_command` (it sends nothing). tests/test_golden_commands.py introspects drivers/ and fails when
# a class gains a public method that is in neither list. Properties are listed too (they are public attributes of the class).
# =====================================================================================================================================
COVERAGE = {
    # driver fixture name -> {class name -> {'covered': [...], 'no_command': [...]}}
    'base': {
        'Instrument': dict(
            covered=['open', 'close', 'identify', 'write', 'query', 'query_retry', 'cleanup', 'reset_to_defaults'],
            no_command=['close_to',                                         # pure arithmetic helper
                        'send', 'ask',                                      # generic registry front ends: every driver case goes through them
                        'use_commands', 'rejected_commands', 'command_overrides_active', 'describe_commands',   # no wire traffic
                        'set_point', 'point_overrides_active',              # point selection (no wire traffic)
                        'run_extras']),                                     # sends ONLY operator-typed extra lines: none exist in a factory run (tests/test_point_editor_*.py)
    },
    'fluke_5560a': {
        'Fluke5560A': dict(
            covered=['standby', 'operate', 'is_operating', 'cleanup', 'scope_off', 'select_scope_dcv', 'set_dc_volts', 'select_scope_levsine',
                     'set_levsine', 'select_scope_square', 'set_square', 'drain_errors', 'select_scope_marker', 'set_marker_period',
                     'select_scope_measure_resistance', 'measure_scope_resistance', 'set_output_volts', 'set_output_amps', 'set_output_ohms',
                     'set_output_capacitance', 'set_output_temperature', 'set_output_square', 'restore_sine', 'read_error', 'check_error', 'clear_status', 'operate_unverified',
                     'standby_quiet', 'apply_scope_dc'],
            no_command=[]),
        'Fluke5520A': dict(covered=['open'], no_command=['unverified_summary']),   # reuses the 5522A command set; own registry flags
        'Fluke5522A': dict(covered=['open', 'set_lcomp'], no_command=['lcomp_allowed']),    # inherits the rest; LCOMP ON/OFF with read-back (owner request 2026-10-26)
    },
    'scpi_dmm': {
        'ScpiDmm': dict(covered=['connect', 'remote', 'local', 'cleanup', 'configure', 'configure_frequency', 'read'], no_command=[]),
        'Fluke8846A': dict(covered=['connect_for_adjustment', 'unlock_calibration', 'lock_calibration', 'adjust_step', 'record_calibration'],
                           no_command=[]),
        'Agilent34401A': dict(covered=['set_ac_filter_slow'], no_command=[]),
    },
    'fluke_8808a': {
        'Fluke8808A': dict(covered=['write', 'query', 'send', 'identify', 'connect', 'remote', 'local', 'cleanup', 'configure_point', 'read',
                                    'check_errors', 'ensure_run_state', 'session_check'], no_command=[]),
    },
    'fluke_8808a_cal': {
        'Fluke8808ACal': dict(covered=['write', 'enter_cal_mode', 'adopt_manual_entry', 'select_function', 'set_reference', 'confirm_value', 'start_point', 'read_late', 'exit_cal', 'cleanup'], no_command=[]),
    },
    'keysight_truevolt': {
        'KeysightTruevolt': dict(covered=['connect', 'cleanup', 'set_nplc', 'set_ac_filter', 'configure_point', 'configure_frequency_point',
                                          'front_rear', 'check_errors'], no_command=[]),
        'Keysight34460A': dict(covered=['connect'], no_command=[]),
        'Keysight34461A': dict(covered=['connect'], no_command=[]),
        'Keysight34465A': dict(covered=['connect'], no_command=[]),
        'Keysight34470A': dict(covered=['connect'], no_command=[]),
    },
    'keysight_dacq': {
        'KeysightDacq': dict(covered=['connect', 'cleanup', 'module_type', 'require_module', 'configure_point', 'read', 'check_errors'],
                             no_command=[]),
        'Keysight34970A': dict(covered=['connect', 'cleanup'], no_command=[]),
        'Keysight34972A': dict(covered=['connect', 'cleanup'], no_command=[]),
    },
    'keysight_332xx': {
        'Keysight332xx': dict(covered=['connect', 'check_errors', 'self_test', 'set_load', 'setup', 'output', 'cleanup'], no_command=[]),
        'Keysight33210A': dict(covered=['connect'], no_command=[]),
        'Keysight33220A': dict(covered=['connect'], no_command=[]),
        'Keysight33250A': dict(covered=['connect'], no_command=[]),
    },
    'keysight_5313x': {
        'Keysight5313x': dict(covered=['connect', 'check_errors', 'self_test', 'configure_frequency', 'reference', 'set_reference',
                                       'read_frequency', 'frequency', 'cleanup'], no_command=[]),
        'Keysight53131A': dict(covered=['connect'], no_command=[]),
        'Keysight53132A': dict(covered=['connect'], no_command=[]),
    },
    'fluke_5790b': {
        'Fluke5790B': dict(covered=['connect', 'check_error', 'select_input', 'set_external_trigger', 'range_info', 'set_range_for',
                                    'set_autorange', 'wideband_option', 'require_wideband', 'measure', 'cleanup'], no_command=[]),
    },
    'fluke_28x': {
        'Fluke28x': dict(covered=['connect', 'identify', 'display', 'primary', 'stable_reading', 'cleanup'],
                         no_command=['model']),                             # property: derives from the *IDN text already read
    },
    'lecroy_ws4104hd': {
        'WaveSurfer4104HD': dict(
            covered=['query_retry', 'vbs_get', 'vbs_get_float', 'vbs_set_number', 'vbs_set_text', 'handshake', 'set_vertical_scale',
                     'set_vertical_offset', 'ensure_zero_offset', 'set_coupling', 'set_bandwidth_limit', 'set_coupling_legacy',
                     'configure_dc_input', 'set_timebase', 'set_edge_trigger_source', 'set_trigger_slope', 'set_trigger_level',
                     'set_trigger_mode', 'trigger_mode', 'configure_p1', 'read_p1', 'read_p1_settled', 'enable_channel', 'read_p1_when_ready', 'ensure_not_inverted'],
            no_command=[]),
    },
    'tektronix_mdo4000c': {
        'TektronixMDO4000C': dict(
            covered=['connect', 'installed_options', 'opc', 'check_errors', 'cleanup', 'set_verified', 'set_enum_verified', 'default_setup',
                     'select_only', 'channel', 'acquire_mode', 'timebase', 'delay', 'trigger_line', 'trigger_edge', 'measure_setup',
                     'stats_reset', 'stat_mean', 'stat_stddev', 'meas_value', 'mean_of', 'delay_stddev', 'fetch', 'edge_time',
                     'rf_cmd', 'rf_setup', 'rf_rbw', 'rf_trace', 'afg_set', 'afg_off', 'dvm',
                     'dvm_value', 'dvm_frequency', 'run_diagnostics', 'run_spc'],
            no_command=['rf_settle']),                                      # time.sleep only; the sleep is recorded by the engines' runs
    },
    'tektronix_tds2000c': {
        'TektronixTDS2000C': dict(
            covered=['connect', 'opc', 'check_errors', 'cleanup', 'set_verified', 'set_enum_verified', 'default_setup', 'run_self_test', 'self_cal',
                     'select_only', 'channel', 'position', 'acquire_mode', 'run', 'num_acq', 'wait_acquisitions', 'timebase',
                     'horizontal_position', 'trigger_edge', 'trigger_mode', 'set_level_50', 'trigger_state', 'measure_setup', 'meas_value',
                     'measure', 'waveform', 'waveform_burst'],
            no_command=['model_from_idn']),                                 # static: parses the *IDN? text already read
    },
    'tektronix_tbs1000': {
        'TektronixTBS1000': dict(covered=['connect'], no_command=['model_from_idn']),   # the TDS2000C driver; only the identification differs
    },
    'tektronix_tbs1000c': {
        'TektronixTBS1000C': dict(
            covered=['connect', 'opc', 'check_errors', 'cleanup', 'set_num', 'set_word', 'default_setup', 'run_self_test', 'self_cal',
                     'select_only', 'channel', 'position', 'acquire_mode', 'run', 'num_acq', 'wait_acquisitions', 'timebase',
                     'horizontal_position', 'trigger_edge', 'trigger_mode', 'set_level_50', 'trigger_state', 'measure_setup', 'meas_value',
                     'measure', 'waveform', 'waveform_burst'],
            no_command=['model_from_idn']),                                 # static: parses the *IDN? text already read
    },
    'fluke_5522a_scope': {
        'Fluke5522AScope': dict(covered=['select_scope_dcv', 'set_dc_volts'], no_command=[]),
    },
    'keithley_2000': {
        'Keithley2000': dict(covered=['connect', 'remote', 'local', 'cleanup', 'range_ok', 'configure_point', 'rel_is_on', 'acquire_reference', 'read', 'fetch',
                                      'front_rear', 'check_errors'],
                             no_command=['bus']),                              # property: derives from the transport
        'Fluke5522AComp': dict(covered=['set_compensation'], no_command=[]),
    },
    'keithley_2000_cal': {
        'Keithley2000Cal': dict(covered=['connect', 'set_firmware_class', 'lock_state', 'unlock', 'initiate', 'drain_errors', 'require_no_errors', 'wait_complete',
                                         'calibrate_step', 'set_dates', 'count', 'save', 'lock', 'cleanup'],
                                no_command=[]),
    },
    'keysight_34410a': {
        'Keysight34410A': dict(covered=['connect', 'local', 'cleanup', 'range_ok', 'configure_point', 'read', 'front_rear', 'check_errors', 'firmware_warning'],
                               no_command=['bus', 'firmware']),               # properties: derived from the transport / the *IDN? text already read
    },
    'keysight_34411a': {                                              # the family subclass of the 34410A driver (same module; its own fixture so the 34410A transcripts stay as recorded)
        'Keysight34411A': dict(covered=['connect', 'configure_point', 'read', 'firmware_warning'], no_command=[]),     # inherited methods, exercised on the subclass
    },
    'agilent_3458a': {
        'Agilent3458A': dict(covered=['identify', 'connect', 'local', 'cleanup', 'reset_to_defaults', 'set_confirmed', 'configure', 'set_trigger', 'set_output_format', 'read',
                                      'read_n', 'null', 'null_off', 'offset', 'temperature', 'revision', 'terminals', 'check_errors', 'state_summary', 'acal'],
                             no_command=['reading_timeout', 'acal_timeout', 'acal_info']),      # pure arithmetic / tables
    },
    'reference_instruments': {
        'Fluke96270A': dict(covered=['connect', 'check_error', 'set_rf', 'output', 'cleanup'], no_command=[]),
        'AgilentAFG': dict(covered=['connect', 'sine', 'square', 'output', 'cleanup'], no_command=['max_hz']),   # property
        'ReferenceMeter': dict(covered=['connect', 'frequency', 'ac_rms', 'power', 'dc'], no_command=[]),
    },
}

# Stage 7: reset_to_defaults is defined once, on Instrument, and exercised on each of these concrete drivers (golden cases "Class.reset_to_defaults").
for _cls in ('Fluke5560A', 'Fluke5520A', 'Fluke5522A', 'Fluke8846A', 'Fluke8808A', 'Agilent34401A', 'Keysight34470A', 'Keysight34970A', 'Keysight34972A', 'Keysight33220A',
             'Fluke8808ACal', 'Keysight53132A', 'Fluke5790B', 'Fluke28x', 'WaveSurfer4104HD', 'TektronixMDO4000C', 'Fluke96270A', 'AgilentAFG', 'ReferenceMeter',
             'TektronixTDS2000C', 'TektronixTBS1000', 'TektronixTBS1000C', 'Fluke5522AScope', 'Keithley2000', 'Keithley2000Cal', 'Keysight34410A', 'Keysight34411A'):
    for _fixture in COVERAGE.values():
        if _cls in _fixture:
            _fixture[_cls]['covered'].append('reset_to_defaults')

from tests import golden_tbs2000b as _tbs2000b  # noqa: E402  (TBS2000B driver / engine cases; reset_to_defaults is in its own covered list)
COVERAGE['tektronix_tbs2000b'] = _tbs2000b.COVERAGE

# Driver source files scanned by the f-string lint (everything that sends commands)
LINT_FILES = ['base', 'fluke_5560a', 'scpi_dmm', 'fluke_8808a', 'keysight_truevolt', 'keysight_dacq', 'keysight_332xx', 'keysight_5313x', 'fluke_5790b',
              'fluke_28x', 'lecroy_ws4104hd', 'tektronix_mdo4000c', 'tektronix_tds2000c', 'fluke_5522a_scope', 'reference_instruments', 'keithley_2000', 'keithley_2000_cal', 'fluke_8808a_cal', 'keysight_34410a', 'agilent_3458a']
LINT_FILES.append('tektronix_tbs2000b')
LINT_FILES += ['tektronix_tbs1000', 'tektronix_tbs1000c']

# Engines whose bench I/O is exercised by a short simulated run (name -> description). Others are listed in the report as not coverable.
ENGINES = ('truevolt_34470A', 'dacq_34970A', 'dacq_34972A', 'fgen_33220A', 'mdo4000c', 'tds2000c', 'agilent_34401a', 'fluke_8846a', 'handheld_5522a',
           'wavesurfer_dcv', 'keithley_2000', 'keysight_34410a', 'keysight_34411a')
ENGINES += ('tbs2000b', 'tbs1000c', 'tbs1000')


# =====================================================================================================================================
# deterministic environment
# =====================================================================================================================================
class Recorder:
    """The list of events of the case being run; None while nothing is being recorded (setup is silent)."""
    current = None


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def sleep(self, seconds):
        if Recorder.current is not None:
            Recorder.current.append(['sleep', float(seconds)])
        self.now += max(0.0, float(seconds))

    def monotonic(self):
        return self.now

    def time(self):
        return 1.7e9 + self.now


@contextlib.contextmanager
def pinned():
    """Fake clock, seeded random, throw-away HOME (nothing is appended to the real ~/.calibration_suite)."""
    clock = FakeClock()
    saved = (time.sleep, time.time, time.monotonic, time.perf_counter)
    time.sleep, time.time, time.monotonic, time.perf_counter = clock.sleep, clock.time, clock.monotonic, clock.monotonic
    random.seed(20261022)
    old_env = {k: os.environ.get(k) for k in ('HOME', 'CALSUITE_DATA', 'USERPROFILE')}
    tmp = tempfile.mkdtemp(prefix='golden_home_')
    os.environ['HOME'] = os.environ['USERPROFILE'] = os.environ['CALSUITE_DATA'] = tmp
    try:
        yield clock
    finally:
        time.sleep, time.time, time.monotonic, time.perf_counter = saved
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


_SECRET_WIRE = re.compile(r'^(CAL:SEC:STAT\s+(?:ON|OFF),)(.*)$', re.I)
_SECRET_CODE = re.compile(r"^(:?CAL:PROT:CODE\s+)'(.*)'$", re.I)        # Keithley 2000: :CAL:PROT:CODE '<code>'
_SECRET_ACAL = re.compile(r'^(ACAL\s+\w+,)(.*)$', re.I)                    # 3458A: ACAL <type>,<security code>


def mask_wire(text):
    """Calibration-security commands carry the password: the record keeps the prefix and the length only."""
    m = _SECRET_WIRE.match(text)
    if m:
        return f'{m.group(1)}<password masked, {len(m.group(2))} chars>'
    m = _SECRET_CODE.match(text) or _SECRET_ACAL.match(text)
    return f'{m.group(1)}<code masked, {len(m.group(2))} chars>' if m else text


# =====================================================================================================================================
# transports: scripted fake + recorder
# =====================================================================================================================================
class Scripted(Transport):
    """Fake transport. rules: list of (regex, reply). reply: str | callable(cmd) | exception | list (consumed in order, last one repeats;
    items may be exceptions). A write with no matching rule is accepted silently; a query or read with nothing pending raises TransportError."""
    name = 'SCRIPTED'

    def __init__(self, rules=(), default=None):
        self.rules = [(re.compile(r, re.I), rep) for r, rep in rules]
        self.default = default
        self._pending = None
        self._lines = []
        self.opened = False

    def open(self): self.opened = True
    def close(self): self.opened = False

    def _lookup(self, cmd):
        for rx, rep in self.rules:
            if rx.search(cmd):
                if isinstance(rep, list):
                    item = rep[0] if len(rep) == 1 else rep.pop(0)
                    return item
                return rep
        return self.default

    def write(self, text):
        rep = self._lookup(text.strip())
        if callable(rep) and not isinstance(rep, BaseException):
            rep = rep(text.strip())
        if isinstance(rep, BaseException):
            raise rep
        if isinstance(rep, tuple):                       # several reply lines for one command (Fluke 28x: ack, then data)
            self._lines, rep = list(rep[1:]), rep[0]
        else:
            self._lines = []
        self._pending = rep

    def read(self):
        if self._pending is None and self._lines:
            return self._lines.pop(0)
        if self._pending is None:
            raise TransportError('scripted transport: nothing to read')
        rep, self._pending = self._pending, None
        return rep

    def query(self, text):
        self.write(text)
        return self.read()


class RecordingTransport(Transport):
    """Wraps a simulator (or a Scripted fake). `fallback` answers commands the simulator rejects as unknown. Records only while a case runs."""

    def __init__(self, inner, fallback=None):
        self.inner, self.fallback = inner, fallback
        self.name = getattr(inner, 'name', 'REC')
        if getattr(inner, 'bus', None):
            self.bus = inner.bus                         # the Keithley 2000 driver chooses :SYST:LOC (RS-232) or GTL (GPIB) from it
        self._use_fallback_for_read = False

    @staticmethod
    def _rec(*event):
        if Recorder.current is not None:
            Recorder.current.append(list(event))

    def open(self): self._rec('ctl', 'open'); self.inner.open()
    def close(self): self._rec('ctl', 'close'); self.inner.close()
    def clear(self): self._rec('ctl', 'clear'); self.inner.clear()
    def set_timeout(self, seconds): self._rec('ctl', 'set_timeout', float(seconds)); return self.inner.set_timeout(seconds)
    def go_local(self): self._rec('ctl', 'go_local'); return self.inner.go_local()
    def set_read_termination(self, term):
        self._rec('ctl', 'set_read_termination', term)
        method = getattr(self.inner, 'set_read_termination', None)
        return method(term) if callable(method) else None

    def read_raw(self, count):
        try:
            method = getattr(self.inner, 'read_raw', None)
            if not callable(method):
                raise TransportError('this transport cannot read binary data')
            data = method(count)
        except TransportError as exc:
            self._rec('RB!', int(count), str(exc))
            raise
        self._rec('RB', int(count), bytes(data).hex())
        return data

    def _unknown(self, exc):
        return self.fallback is not None and 'unknown command' in str(exc)

    def write(self, text):
        try:
            self.inner.write(text)
            self._use_fallback_for_read = False
        except TransportError as exc:
            if self._unknown(exc):
                self.fallback.write(text)
                self._use_fallback_for_read = True
            else:
                self._rec('W!', mask_wire(text), str(exc))
                raise
        self._rec('W', mask_wire(text))

    def read(self):
        try:
            reply = (self.fallback if self._use_fallback_for_read else self.inner).read()
        except TransportError as exc:
            self._rec('R!', str(exc))
            raise
        self._rec('R', reply)
        return reply

    def query(self, text):
        try:
            reply = self.inner.query(text)
        except TransportError as exc:
            if self._unknown(exc):
                reply = self.fallback.query(text)
            else:
                self._rec('Q!', mask_wire(text), str(exc))
                raise
        self._rec('Q', mask_wire(text), reply)
        return reply


# =====================================================================================================================================
# case runner
# =====================================================================================================================================
def fmt_result(value):
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, fluke_28x.Reading):
        return f'Reading({value.id},{value.value!r},{value.unit},mult={value.mult},dec={value.decimals},{value.state})'
    if isinstance(value, fluke_28x.Display):
        return f'Display({value.summary()}; readings={[fmt_result(r) for r in value.readings]})'
    if isinstance(value, (set, frozenset)):
        return '{' + ', '.join(sorted(fmt_result(v) for v in value)) + '}'          # set order depends on the hash seed
    if isinstance(value, dict):
        return '{' + ', '.join(f'{fmt_result(k)}: {fmt_result(v)}' for k, v in sorted(value.items(), key=lambda kv: repr(kv[0]))) + '}'
    if isinstance(value, Instrument):
        return f'<{type(value).__name__}>'
    if isinstance(value, tuple):
        return '(' + ', '.join(fmt_result(v) for v in value) + ')'
    if isinstance(value, list):
        return '[' + ', '.join(fmt_result(v) for v in value) + ']'
    return re.sub(r' at 0x[0-9a-fA-F]+', '', repr(value))         # never an object address in a fixture


class Case:
    """Collects the entries for one driver fixture."""

    def __init__(self, driver):
        self.driver = driver
        self.entries = []
        self.names = set()

    def inst(self, cls, transport, label=None, opened=True, fallback=None, **kw):
        """Instrument on a recording transport. opened=True opens the transport silently (like a connect() already done)."""
        rec = RecordingTransport(transport, fallback)
        inst = cls(rec, drivers.CommandLog(), label=label, **kw)
        if opened:
            transport.open()
            inst._open = True
        return inst

    def quiet(self, fn, *a, **k):
        """Setup that must not be recorded (state of the simulator / instrument object is still changed)."""
        return fn(*a, **k)

    def run(self, name, fn, *args, _log=None, **kwargs):
        """Run one call and record its wire strings, log lines and result. `name` is 'Class.method' or 'Class.method[variant]'."""
        inst = getattr(fn, '__self__', None)
        log = _log if _log is not None else getattr(inst, 'log', None)
        if log is not None:
            log.entries.clear()
        events = []
        Recorder.current = events
        try:
            value = None
            try:
                value = fn(*args, **kwargs)
                result = 'returned ' + fmt_result(value)
            except Exception as exc:                      # noqa: BLE001 - the exception type and text are part of the record
                result = f'raised {type(exc).__name__}: {exc}'
        finally:
            Recorder.current = None
        if log is None:                                   # a constructor: the new object owns the log
            log = getattr(value, 'log', None)
        assert name not in self.names, f'duplicate golden case name {name}'
        self.names.add(name)
        call = ', '.join([fmt_result(a) for a in args] + [f'{k}={fmt_result(v)}' for k, v in kwargs.items()])
        call = call.replace(SENTINEL_PASSWORD, '<secret>').replace(SIM_CODE, '<secret>')            # never write a password into a fixture
        self.entries.append(dict(
            case=name, method=name.split('[')[0], call=call, wire=events, result=result,
            log=[f'{inst_}|{d}|{txt}' for _t, inst_, d, txt in (log.entries if log is not None else [])]))


def _scripted_state_ok(*_a):
    return None


# =====================================================================================================================================
# driver cases
# =====================================================================================================================================
def cases_base(c):
    t = Scripted([(r'\*IDN\?', 'GOLDEN,BASE,1,1'), (r'^FOO\?', ['1', '2', '3']), (r'^FLAKY\?', [TransportError('timeout'), TransportError('timeout'), '7']),
                  (r'^DEAD\?', TransportError('timeout'))])
    i = c.inst(Instrument, t, opened=False, label='Base')
    c.run('Instrument.open[verify]', i.open)
    c.run('Instrument.identify', i.identify)
    c.run('Instrument.write', i.write, 'FOO 1')
    c.run('Instrument.write[log_as]', i.write, 'SECRET 12345', log_as='SECRET ********')
    c.run('Instrument.query', i.query, 'FOO?')
    c.run('Instrument.query[log_as]', i.query, 'FOO?', log_as='FOO? (masked)')
    c.run('Instrument.query_retry[first try]', i.query_retry, 'FOO?')
    c.run('Instrument.query_retry[third try]', i.query_retry, 'FLAKY?', attempts=3, delay=0.5)
    c.run('Instrument.query_retry[gives up]', i.query_retry, 'DEAD?', attempts=2, delay=0.25)
    c.run('Instrument.cleanup', i.cleanup)
    c.run('Instrument.close', i.close)
    j = c.inst(Instrument, Scripted([(r'\*IDN\?', 'SOMEONE,ELSE,1,1')]), opened=False, label='Base2')
    j.IDN_MATCH, j.MODEL = ('EXPECTED',), 'Expected Model'
    c.run('Instrument.open[wrong model]', j.open)
    k = c.inst(Instrument, Scripted([]), opened=False, label='Base3')
    c.run('Instrument.open[no verify]', k.open, verify_model=False)


def cases_fluke_5560a(c):
    bench, ft, _s = make_bench()
    cal = c.inst(Fluke5560A, ft, label='5560A')
    c.run('Fluke5560A.standby', cal.standby)
    c.run('Fluke5560A.operate', cal.operate)
    c.run('Fluke5560A.is_operating', cal.is_operating)
    c.run('Fluke5560A.cleanup', cal.cleanup)
    c.run('Fluke5560A.scope_off', cal.scope_off)
    c.run('Fluke5560A.select_scope_dcv[1M]', cal.select_scope_dcv)
    c.run('Fluke5560A.select_scope_dcv[50]', cal.select_scope_dcv, '50')
    c.run('Fluke5560A.set_dc_volts', cal.set_dc_volts, 1.0)
    c.run('Fluke5560A.set_dc_volts[negative small]', cal.set_dc_volts, -0.0123456789)
    c.run('Fluke5560A.select_scope_levsine', cal.select_scope_levsine)
    for hz, tag in ((50.0, 'Hz'), (50e3, 'kHz'), (1.5e6, 'MHz'), (1.1e9, 'GHz')):
        c.run(f'Fluke5560A.set_levsine[{tag}]', cal.set_levsine, 2.5, hz)
    c.run('Fluke5560A.select_scope_square', cal.select_scope_square)
    c.run('Fluke5560A.set_square', cal.set_square, 1.0, 1000.0)
    ft.errors = ['-113,"Undefined header"', '-221,"Settings conflict"']
    c.run('Fluke5560A.drain_errors[stale]', cal.drain_errors)
    c.run('Fluke5560A.drain_errors[empty]', cal.drain_errors)
    c.run('Fluke5560A.select_scope_marker', cal.select_scope_marker)
    c.run('Fluke5560A.set_marker_period', cal.set_marker_period, 0.001)
    c.run('Fluke5560A.select_scope_measure_resistance', cal.select_scope_measure_resistance)
    c.run('Fluke5560A.measure_scope_resistance', cal.measure_scope_resistance)
    c.run('Fluke5560A.set_output_volts[no freq]', cal.set_output_volts, 1.0)
    c.run('Fluke5560A.set_output_volts[freq]', cal.set_output_volts, 1.0, 1000.0)
    c.run('Fluke5560A.set_output_amps[no freq]', cal.set_output_amps, 0.001)
    c.run('Fluke5560A.set_output_amps[freq]', cal.set_output_amps, 0.001, 1000.0)
    c.run('Fluke5560A.set_output_ohms', cal.set_output_ohms, 1000.0)
    c.run('Fluke5560A.set_output_capacitance[nF]', cal.set_output_capacitance, 4.7e-9)
    c.run('Fluke5560A.set_output_capacitance[uF]', cal.set_output_capacitance, 4.7e-6)
    c.run('Fluke5560A.set_output_capacitance[F]', cal.set_output_capacitance, 0.01)
    c.run('Fluke5560A.set_output_temperature', cal.set_output_temperature, 100.0)
    c.run('Fluke5560A.set_output_temperature[type J]', cal.set_output_temperature, 25.5, 'J')
    c.run('Fluke5560A.set_output_square', cal.set_output_square, 5.0, 1000.0, 50.0, 2.5)
    c.run('Fluke5560A.standby[after square wave]', cal.standby)
    c.run('Fluke5560A.restore_sine', cal.restore_sine)
    c.run('Fluke5560A.read_error', cal.read_error)
    c.run('Fluke5560A.check_error[ok]', cal.check_error, 'ctx')
    ft.errors = ['-222,"Data out of range"']
    c.run('Fluke5560A.check_error[rejected]', cal.check_error, 'out of range')
    c.run('Fluke5560A.clear_status', cal.clear_status)
    c.run('Fluke5560A.operate_unverified', cal.operate_unverified)
    c.run('Fluke5560A.standby_quiet', cal.standby_quiet)
    c.run('Fluke5560A.apply_scope_dc', cal.apply_scope_dc, 1.0)
    # failure branches of the confirmed state changes
    bad = c.inst(Fluke5560A, Scripted([(r'^OPER\?', '1')]), label='5560A')
    c.run('Fluke5560A.standby[not confirmed]', bad.standby)
    bad2 = c.inst(Fluke5560A, Scripted([(r'^OPER\?', '0')]), label='5560A')
    c.run('Fluke5560A.operate[not confirmed]', bad2.operate)
    c.run('Fluke5560A.cleanup[standby not confirmed]', bad.cleanup)
    # Fluke5522A: same command set, different identity
    ft2 = make_dacq_bench(cal='5522A')[1]
    cal2 = c.inst(Fluke5522A, ft2, opened=False, label='5522A')
    c.run('Fluke5522A.open', cal2.open)
    c.run('Fluke5522A.set_lcomp[ON]', cal2.set_lcomp, True)
    c.run('Fluke5522A.set_lcomp[OFF]', cal2.set_lcomp, False)
    ft3 = make_dacq_bench(cal='5520A')[1]
    cal3 = c.inst(Fluke5520A, ft3, opened=False, label='5520A')
    c.run('Fluke5520A.open', cal3.open)


def cases_scpi_dmm(c):
    bench, ft, dt = make_dmm_bench('8846A')
    d = c.inst(Fluke8846A, dt, opened=False, label='8846A')
    c.run('ScpiDmm.connect[8846A]', d.connect)
    c.run('ScpiDmm.remote', d.remote)
    c.run('ScpiDmm.local', d.local)
    c.run('ScpiDmm.cleanup', d.cleanup)
    for kind, rng in (('DCV', 10), ('ACV', 1), ('DCI', 0.01), ('ACI', 1), ('OHM2', 1000), ('OHM4', 100000), ('CAP', 1e-7)):
        c.run(f'ScpiDmm.configure[{kind}@8846A]', d.configure, kind, rng)
    c.run('ScpiDmm.configure_frequency', d.configure_frequency)
    bench.fluke.update(operate=True, volts=1.0)
    c.run('ScpiDmm.read', d.read)
    bench.fluke.update(operate=False)
    # 34401A (no CAP support, 7E2 serial) and a failing read
    _b, _f, dt2 = make_dmm_bench('34401A')
    a = c.inst(Agilent34401A, dt2, opened=False, label='34401A')
    c.run('ScpiDmm.connect[34401A]', a.connect)
    c.run('ScpiDmm.configure[CAP unsupported@34401A]', a.configure, 'CAP', 1e-7)
    c.run('Agilent34401A.set_ac_filter_slow', a.set_ac_filter_slow)
    over = c.inst(ScpiDmm, Scripted([(r'^READ\?', '+9.90000000E+37')]), label='DMM')
    c.run('ScpiDmm.read[overload]', over.read)
    wrong = c.inst(Fluke8846A, Scripted([(r'\*IDN\?', 'OTHER,1234,1,1')]), opened=False, label='8846A')
    c.run('ScpiDmm.connect[wrong model]', wrong.connect)
    # 8846A calibration interface: password is masked on the wire record and in the log
    pw = SENTINEL_PASSWORD
    adj = c.inst(Fluke8846A, make_dmm_bench('8846A')[2], opened=False, label='8846A')
    c.run('Fluke8846A.connect_for_adjustment', adj.connect_for_adjustment)
    c.run('Fluke8846A.unlock_calibration', adj.unlock_calibration, pw)
    c.run('Fluke8846A.adjust_step', adj.adjust_step, 'DCV', 10)
    c.run('Fluke8846A.record_calibration', adj.record_calibration)
    c.run('Fluke8846A.lock_calibration', adj.lock_calibration, pw)
    refuse = c.inst(Fluke8846A, Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), opened=False, label='8846A')
    c.run('Fluke8846A.connect_for_adjustment[refused]', refuse.connect_for_adjustment)
    notok = c.inst(Fluke8846A, Scripted([(r'^CAL\? ON', '+1'), (r'^CAL:SEC:STAT\?', '+1')]), label='8846A')
    c.run('Fluke8846A.adjust_step[failure]', notok.adjust_step, 'ACV', 1)
    c.run('Fluke8846A.unlock_calibration[still locked]', notok.unlock_calibration, pw)


def cases_8808a(c):
    bench, ft, dt = make_8808a_bench('5522A', enforce_cal_limits=False)
    d = c.inst(Fluke8808A, dt, opened=False, label='8808A')
    c.run('Fluke8808A.connect', d.connect)
    c.run('Fluke8808A.identify', d.identify)
    c.run('Fluke8808A.remote', d.remote)
    c.run('Fluke8808A.local', d.local)
    c.run('Fluke8808A.cleanup', d.cleanup)
    c.run('Fluke8808A.write', d.write, 'FORMAT 1')
    c.run('Fluke8808A.query', d.query, 'FORMAT?')
    c.run('Fluke8808A.send[set]', d.send, 'rate.set', rate='S')
    c.run('Fluke8808A.send[reset settles]', d.send, 'reset')
    c.quiet(lambda: (d.send('format.set', fmt=1), d.send('status.clear')))
    pts = [('DCV', dict(kind='DCV', range=0.2)), ('DCV 1000 V', dict(kind='DCV', range=1000.0)), ('ACV 750 V', dict(kind='ACV', range=750.0)),
           ('DCI 10 A', dict(kind='DCI', range=10.0)), ('ACI 20 mA', dict(kind='ACI', range=0.02)), ('OHM2', dict(kind='OHM2', range=2e3)),
           ('OHM4', dict(kind='OHM4', range=2e3)), ('FREQ no rate', dict(kind='FREQ', range=20000.0)),
           ('bad range', dict(kind='DCV', range=100.0)), ('CAP unsupported', dict(kind='CAP', range=1e-7))]
    for tag, p in pts:
        c.run(f'Fluke8808A.configure_point[{tag}]', d.configure_point, p)
    bench.fluke.update(operate=True, volts=0.19, unit='V', freq=0.0)
    c.quiet(d.configure_point, dict(kind='DCV', range=0.2))
    c.run('Fluke8808A.read', d.read)
    bench.fluke.update(volts=1.0)
    c.run('Fluke8808A.read[overload]', d.read)
    c.run('Fluke8808A.check_errors[ok]', d.check_errors, 'ctx')
    c.quiet(d.write, 'NOTACOMMAND')
    c.run('Fluke8808A.check_errors[command error]', d.check_errors, 'configuring')
    c.quiet(dt.handle, '*CLS')
    wrong = c.inst(Fluke8808A, Scripted([(r'\*IDN\?', 'FLUKE, 8846A, 1, 1.0'), (r'^REMS', None)]), opened=False, label='8808A')
    c.run('Fluke8808A.connect[wrong model]', wrong.connect)
    echo = c.inst(Fluke8808A, Scripted([(r'\*IDN\?', '=> FLUKE, 8808A, 1, 1.0')]), opened=False, label='8808A')
    c.run('Fluke8808A.connect[echo on]', echo.connect)
    # prompt-tolerant replies (real-bench failure: '=>' prompts after *RST with Echo set off); simulator modes in drivers/simulated_8808a.py
    pt = make_8808a_bench('5522A', enforce_cal_limits=False)[2]
    pt.prompts = True
    pd = c.inst(Fluke8808A, pt, opened=False, label='8808A')
    c.run('Fluke8808A.connect[prompts tolerated]', pd.connect)
    c.run('Fluke8808A.query[prompt skipped]', pd.query, 'FORMAT?')
    c.quiet(pd.write, 'NOTACOMMAND')
    c.run('Fluke8808A.query[command-error prompt raised]', pd.query, 'FORMAT?')
    pt.prompts = False
    rt = make_8808a_bench('5522A', enforce_cal_limits=False)[2]
    rt.prompts_after_reset, rt.banner = True, 'FLUKE 8808A'
    rd = c.inst(Fluke8808A, rt, opened=False, label='8808A')
    c.quiet(rd.connect)
    c.run('Fluke8808A.reset_to_defaults[prompts after reset]', rd.reset_to_defaults)
    et = make_8808a_bench('5522A', enforce_cal_limits=False)[2]
    et.echo = True
    ed = c.inst(Fluke8808A, et, opened=False, label='8808A')
    c.run('Fluke8808A.connect[echo of *IDN?]', ed.connect)
    # a Run that skips the once-per-session reset (owner request): REMS + read-first FORMAT / TRIGGER / RATE, and *IDN? + one *ESR?
    sb, sft, st = make_8808a_bench('5522A', enforce_cal_limits=False)
    sd = c.inst(Fluke8808A, st, opened=False, label='8808A')
    c.quiet(sd.connect)
    c.run('Fluke8808A.ensure_run_state[format 2 set once]', sd.ensure_run_state)
    c.run('Fluke8808A.ensure_run_state[nothing to set]', sd.ensure_run_state)
    c.run('Fluke8808A.session_check[ok]', sd.session_check)
    st.esr |= 0x10
    c.run('Fluke8808A.session_check[execution error logged]', sd.session_check)


def cases_truevolt(c):
    bench, ft, dt = make_dmm_bench('34470A')
    d = c.inst(Keysight34470A, dt, opened=False, label='34470A')
    c.run('KeysightTruevolt.connect', d.connect)
    c.run('KeysightTruevolt.cleanup', d.cleanup)
    for kind in ('DCV', 'DCI', 'OHM2', 'OHM4'):
        c.run(f'KeysightTruevolt.set_nplc[{kind}]', d.set_nplc, kind)
    c.run('KeysightTruevolt.set_nplc[DCV 100]', d.set_nplc, 'DCV', 100)
    c.run('KeysightTruevolt.set_nplc[DCV 0.2]', d.set_nplc, 'DCV', 0.2)
    for hz in (3, 20, 200):
        c.run(f'KeysightTruevolt.set_ac_filter[ACV {hz}]', d.set_ac_filter, 'ACV', hz)
    c.run('KeysightTruevolt.set_ac_filter[ACI 20]', d.set_ac_filter, 'ACI', 20)
    c.run('KeysightTruevolt.set_ac_filter[invalid]', d.set_ac_filter, 'ACV', 50)
    pts = [('DCV plc', dict(kind='DCV', range=10, plc=10)), ('DCV no plc', dict(kind='DCV', range=10)),
           ('DCI plc', dict(kind='DCI', range=0.01, plc=10)), ('OHM2', dict(kind='OHM2', range=1000, plc=10)),
           ('OHM4', dict(kind='OHM4', range=100000, plc=10)), ('ACV filter', dict(kind='ACV', range=1, filter_hz=20)),
           ('ACV no filter', dict(kind='ACV', range=1)), ('ACI filter', dict(kind='ACI', range=0.1, filter_hz=200)),
           ('CAP', dict(kind='CAP', range=1e-7)), ('FREQ', dict(kind='FREQ', range=1))]
    for tag, p in pts:
        c.run(f'KeysightTruevolt.configure_point[{tag}]', d.configure_point, p)
    c.run('KeysightTruevolt.configure_frequency_point', d.configure_frequency_point, 10)
    c.run('KeysightTruevolt.front_rear[FRONT]', d.front_rear)
    d.t.inner.terminals = 'REAR'
    c.run('KeysightTruevolt.front_rear[REAR]', d.front_rear)
    c.run('KeysightTruevolt.check_errors[ok]', d.check_errors, 'ctx')
    err = c.inst(Keysight34470A, Scripted([(r'^SYST:ERR\?', '-113,"Undefined header"')]), label='34470A')
    c.run('KeysightTruevolt.check_errors[error]', err.check_errors, 'configuring')
    for cls in (Keysight34460A, Keysight34461A, Keysight34465A, Keysight34470A):
        model = cls.__name__[-6:]
        x = c.inst(cls, make_dmm_bench(model)[2], opened=False, label=model)
        c.run(f'{cls.__name__}.connect', x.connect)
    wrong = c.inst(Keysight34470A, make_dmm_bench('34461A')[2], opened=False, label='34470A')
    c.run('KeysightTruevolt.connect[wrong model]', wrong.connect)


def cases_34410a(c):
    for bus in ('GPIB', 'USB'):
        bench, ft, dt = make_34410a_bench('5522A', bus)
        d = c.inst(Keysight34410A, dt, opened=False, label='34410A')
        c.run(f'Keysight34410A.connect[{bus}]', d.connect)
        c.run(f'Keysight34410A.local[{bus}]', d.local)
        c.run(f'Keysight34410A.cleanup[{bus}]', d.cleanup)
    bench, ft, dt = make_34410a_bench('5522A', 'GPIB')
    d = c.inst(Keysight34410A, dt, opened=False, label='34410A')
    c.quiet(d.connect)
    c.quiet(ft.open)
    pts = [('DCV', dict(kind='DCV', range=0.1, plc=100)), ('DCV 1000', dict(kind='DCV', range=1000.0)), ('ACV', dict(kind='ACV', range=10.0, ac_bandwidth=3)),
           ('DCI', dict(kind='DCI', range=0.001)), ('DCI 3 A', dict(kind='DCI', range=3.0)), ('ACI', dict(kind='ACI', range=1.0, ac_bandwidth=3)),
           ('OHM4', dict(kind='OHM4', range=100000.0)), ('OHM2 100M', dict(kind='OHM2', range=1e8)), ('FREQ', dict(kind='FREQ', range=1.0, aperture_s=1)),
           ('CAP', dict(kind='CAP', range=1e-6))]
    for tag, p in pts:
        c.run(f'Keysight34410A.configure_point[{tag}]', d.configure_point, p)
    c.run('Keysight34410A.configure_point[unknown kind]', d.configure_point, dict(kind='TEMP', range=1.0))
    c.quiet(d.configure_point, dict(kind='DCV', range=10.0))
    c.quiet(ft.write, 'OUT 5V,0Hz'); c.quiet(ft.write, 'OPER')
    c.run('Keysight34410A.read[5 V on 10 V]', d.read)
    c.quiet(ft.write, 'OUT 50V,0Hz')
    c.run('Keysight34410A.read[overflow]', d.read)
    c.run('Keysight34410A.check_errors[ok]', d.check_errors, 'ctx')
    dt.errors = ['-221,"Settings conflict"', '-113,"Undefined header"']
    c.run('Keysight34410A.check_errors[two errors]', d.check_errors, 'configuring')
    dt.terminals = 'REAR'
    c.run('Keysight34410A.front_rear[REAR]', d.front_rear)
    dt.terminals = 'FRON'
    c.run('Keysight34410A.front_rear[FRONT]', d.front_rear)
    for tag, reply in (('exact', '+1.000000E-01'), ('upper window', '+1.200000E-01'), ('neighbour', '+1.000000E+00'), ('text', 'abc')):
        c.run(f'Keysight34410A.range_ok[{tag}]', Keysight34410A.range_ok, reply, 0.1)
    dt.range_reply = lambda r: 10 * r                          # the meter answers another range than asked: not accepted, nothing is resent
    c.run('Keysight34410A.configure_point[range not accepted]', d.configure_point, dict(kind='DCV', range=1.0))
    dt.range_reply = lambda r: r
    wrong = c.inst(Keysight34410A, Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), opened=False, label='34410A')
    c.run('Keysight34410A.connect[wrong model]', wrong.connect)
    old = c.inst(Keysight34410A, Scripted([(r'\*IDN\?', 'Agilent Technologies,34410A,MY1,1.07-1.07-0.01-1-1')]), opened=False, label='34410A')
    c.quiet(old.connect)
    c.run('Keysight34410A.firmware_warning[old]', old.firmware_warning)
    c.run('Keysight34410A.firmware_warning[current]', d.firmware_warning)


def cases_3458a(c):
    """The 3458A on its simulator (an applied 1 mA DC current), plus scripted fakes for the branches a simulator cannot reach."""
    bench, ft, dt = make_3458a_bench('5522A')
    d = c.inst(Agilent3458A, dt, opened=False, label='3458A')
    c.run('Agilent3458A.connect', d.connect)
    c.run('Agilent3458A.identify', d.identify)
    c.run('Agilent3458A.local', d.local)
    c.run('Agilent3458A.cleanup', d.cleanup)
    old = c.inst(Agilent3458A, Scripted([(r'^ID\?', 'HP3458A'), (r'^OFORMAT\?', '1'), (r'^TRIG\?', '1')]), opened=False, label='3458A')
    c.run('Agilent3458A.connect[HP3458A firmware text]', old.connect)
    wrong = c.inst(Agilent3458A, Scripted([(r'^ID\?', 'Keysight 34410A')]), opened=False, label='3458A')
    c.run('Agilent3458A.connect[wrong model]', wrong.connect)
    dead = c.inst(Agilent3458A, Scripted([(r'^ID\?', TransportError('timeout'))]), opened=False, label='3458A')
    c.run('Agilent3458A.connect[no answer]', dead.connect)
    c.quiet(d.reset_to_defaults)
    dt.apply('DCI', 1e-3)
    points = [('DCI 1 mA', ('DCI', 1e-3), dict(nplc=10)), ('DCI 100 uA aperture', ('DCI', 1e-4), dict(aperture=1e-3, ndig=8)), ('DCI 1 A', ('DCI', 1.0), dict(nplc=100)),
              ('DCV 10 V autozero off', ('DCV', 10.0), dict(nplc=1, autozero=False)), ('ACV 1 V single trigger', ('ACV', 1.0), dict(nplc=10, trigger='SGL')),
              ('OHM 1 kohm', ('OHM', 1000.0), dict(nplc=10, trigger='SYN'))]
    for tag, args, kw in points:
        c.run(f'Agilent3458A.configure[{tag}]', d.configure, *args, **kw)
    c.run('Agilent3458A.configure[bad function]', d.configure, 'FREQ', 1.0)
    c.run('Agilent3458A.configure[range zero]', d.configure, 'DCV', 0.0)
    c.run('Agilent3458A.configure[range too high]', d.configure, 'DCI', 2.0)
    c.run('Agilent3458A.configure[nplc off grid]', d.configure, 'DCV', 10.0, nplc=2.5)
    c.run('Agilent3458A.configure[bad trigger]', d.configure, 'DCV', 10.0, trigger='LEVEL')
    c.run('Agilent3458A.configure[ndig out of range]', d.configure, 'DCV', 10.0, ndig=9)
    refused = c.inst(Agilent3458A, Scripted([(r'^FUNC\?', '6,+1.00000000E+00'), (r'^ARANGE\?', '0')]), label='3458A')
    c.run('Agilent3458A.configure[range not accepted]', refused.configure, 'DCI', 1e-3)
    auto = c.inst(Agilent3458A, Scripted([(r'^FUNC\?', '6,+1.00000000E-03'), (r'^ARANGE\?', '1')]), label='3458A')
    c.run('Agilent3458A.configure[autorange still on]', auto.configure, 'DCI', 1e-3)
    c.quiet(d.configure, 'DCI', 1e-3, nplc=10)
    c.run('Agilent3458A.read[ASCII 1 mA]', d.read)
    c.run('Agilent3458A.read_n[3]', d.read_n, 3)
    c.run('Agilent3458A.read_n[0]', d.read_n, 0)
    for fmt in ('DREAL', 'SREAL'):
        c.run(f'Agilent3458A.set_output_format[{fmt}]', d.set_output_format, fmt)
        c.run(f'Agilent3458A.read[{fmt} 1 mA]', d.read)
    c.run('Agilent3458A.set_output_format[SINT]', d.set_output_format, 'SINT')
    c.run('Agilent3458A.set_output_format[ASCII]', d.set_output_format, 'ASCII')
    dt.apply('DCI', 0.5)
    c.run('Agilent3458A.read[overload]', d.read)
    dt.apply('DCI', 1e-3)
    c.run('Agilent3458A.set_trigger[SGL]', d.set_trigger, 'SGL')
    c.run('Agilent3458A.read[single trigger]', d.read)
    c.run('Agilent3458A.set_trigger[HOLD]', d.set_trigger, 'HOLD')
    c.run('Agilent3458A.read[trigger HOLD refused]', d.read)
    c.run('Agilent3458A.set_trigger[bad]', d.set_trigger, 'BOGUS')
    c.quiet(d.set_trigger, 'SYN')
    dt.drop_readings = True
    c.run('Agilent3458A.read[no reading arrives]', d.read)
    dt.drop_readings = False
    c.run('Agilent3458A.null', d.null)
    c.run('Agilent3458A.offset', d.offset)
    c.run('Agilent3458A.null_off', d.null_off)
    c.run('Agilent3458A.null[explicit offset]', d.null, 2e-6)
    c.quiet(d.null_off)
    c.run('Agilent3458A.temperature', d.temperature)
    c.run('Agilent3458A.revision', d.revision)
    c.run('Agilent3458A.terminals[FRONT]', d.terminals)
    dt.terminals = 'REAR'
    c.run('Agilent3458A.terminals[REAR]', d.terminals)
    dt.terminals = 'FRONT'
    c.run('Agilent3458A.check_errors[ok]', d.check_errors, 'ctx')
    dt.errors = [(103, 'SYNTAX ERROR'), (106, 'PARAMETER OUT OF RANGE')]
    c.run('Agilent3458A.check_errors[two errors]', d.check_errors, 'configuring')
    c.run('Agilent3458A.state_summary', d.state_summary)
    c.run('Agilent3458A.set_confirmed[AZERO ONCE]', d.set_confirmed, 'azero.set', mode='ONCE')
    c.run('Agilent3458A.set_confirmed[unknown key]', d.set_confirmed, 'nope.set')
    c.run('Agilent3458A.set_confirmed[not accepted]', c.inst(Agilent3458A, Scripted([(r'^END\?', '0')]), label='3458A').set_confirmed, 'end.set', mode='ALWAYS')
    c.run('Agilent3458A.acal[DCV]', d.acal, 'DCV', inputs_disconnected=True)
    c.run('Agilent3458A.acal[not confirmed]', d.acal, 'ALL')
    c.run('Agilent3458A.acal[bad type]', d.acal, 'AC2', inputs_disconnected=True)
    dt.security_code = SENTINEL_PASSWORD
    c.run('Agilent3458A.acal[secured, correct code]', d.acal, 'OHMS', code=SENTINEL_PASSWORD, inputs_disconnected=True)
    c.run('Agilent3458A.acal[secured, wrong code]', d.acal, 'ALL', code='WRONG_CODE_1', inputs_disconnected=True)
    dt.security_code = None
    bench.fail_next = 'ACAL'
    c.run('Agilent3458A.acal[write times out: not repeated]', d.acal, 'ALL', inputs_disconnected=True)
    buffered = c.inst(Agilent3458A, Scripted([(r'^INBUF\?', '1')]), label='3458A')
    c.run('Agilent3458A.acal[INBUF ON]', buffered.acal, 'DCV', inputs_disconnected=True)


def cases_34411a(c):
    """The 34411A is the 34410A driver with its own *IDN? text: the same wire strings, so only the model-specific paths are recorded here."""
    for bus in ('GPIB', 'USB'):
        bench, ft, dt = make_34410a_bench('5522A', bus, '34411A')
        d = c.inst(Keysight34411A, dt, opened=False, label='34411A')
        c.run(f'Keysight34411A.connect[{bus}]', d.connect)
    bench, ft, dt = make_34410a_bench('5522A', 'GPIB', '34411A')
    d = c.inst(Keysight34411A, dt, opened=False, label='34411A')
    c.quiet(d.connect)
    c.quiet(ft.open)
    for tag, p in (('DCV', dict(kind='DCV', range=10.0, plc=100)), ('ACV', dict(kind='ACV', range=1.0, ac_bandwidth=3)), ('OHM4', dict(kind='OHM4', range=1000.0)),
                   ('FREQ', dict(kind='FREQ', range=10.0, aperture_s=1))):
        c.run(f'Keysight34411A.configure_point[{tag}]', d.configure_point, p)
    c.quiet(d.configure_point, dict(kind='DCV', range=10.0))
    c.quiet(ft.write, 'OUT 5V,0Hz'); c.quiet(ft.write, 'OPER')
    c.run('Keysight34411A.read[5 V on 10 V]', d.read)
    other = c.inst(Keysight34411A, Scripted([(r'\*IDN\?', 'Agilent Technologies,34410A,MY1,2.35-2.35-0.09-46-09')]), opened=False, label='34411A')
    c.run('Keysight34411A.connect[a 34410A answers]', other.connect)
    old = c.inst(Keysight34411A, Scripted([(r'\*IDN\?', 'Agilent Technologies,34411A,MY1,1.07-1.07-0.01-1-1')]), opened=False, label='34411A')
    c.quiet(old.connect)
    c.run('Keysight34411A.firmware_warning[old]', old.firmware_warning)
    c.run('Keysight34411A.firmware_warning[current]', d.firmware_warning)


def resets_3458a(c):
    bench, ft, dt = make_3458a_bench('5522A')
    d = c.inst(Agilent3458A, dt, label='3458A')
    dt.errors = [(103, 'SYNTAX ERROR')]
    c.run('Agilent3458A.reset_to_defaults', d.reset_to_defaults)
    bad = c.inst(Agilent3458A, Scripted([(r'^STB\?', '0'), (r'^ERRSTR\?', '0,"NO ERROR"'), (r'^END\?', '2'), (r'^OFORMAT\?', '5'), (r'^QFORMAT\?', '1'),
                                         (r'^INBUF\?', '1'), (r'^AZERO\?', '1')]), label='3458A')
    c.run('Agilent3458A.reset_to_defaults[known state not reached]', bad.reset_to_defaults)


def resets_34411a(c):
    for bus in ('GPIB', 'USB'):
        bench, ft, dt = make_34410a_bench('5522A', bus, '34411A')
        d = c.inst(Keysight34411A, dt, label='34411A')
        c.run(f'Keysight34411A.reset_to_defaults[{bus}]', d.reset_to_defaults)


def cases_k2000(c):
    for bus in ('GPIB', 'RS232'):
        bench, ft, dt = make_k2000_bench('5522A', bus)
        d = c.inst(Keithley2000, dt, opened=False, label='2000')
        c.run(f'Keithley2000.connect[{bus}]', d.connect)
        c.run(f'Keithley2000.local[{bus}]', d.local)
        c.run(f'Keithley2000.remote[{bus}]', d.remote)
        c.run(f'Keithley2000.cleanup[{bus}]', d.cleanup)
    bench, ft, dt = make_k2000_bench('5522A', 'GPIB')
    d = c.inst(Keithley2000, dt, opened=False, label='2000')
    c.quiet(d.connect)
    c.quiet(ft.open)
    pts = [('DCV', dict(kind='DCV', range=0.1, plc=1)), ('DCV 1000', dict(kind='DCV', range=1000.0, plc=1)), ('ACV', dict(kind='ACV', range=10.0, ac_bandwidth=3)),
           ('ACV 750', dict(kind='ACV', range=750.0, ac_bandwidth=3)), ('DCI', dict(kind='DCI', range=0.01, plc=1)), ('DCI 3 A', dict(kind='DCI', range=3.0, plc=1)),
           ('ACI', dict(kind='ACI', range=1.0, ac_bandwidth=3)), ('OHM4', dict(kind='OHM4', range=100000.0, plc=1)),
           ('OHM2 100M', dict(kind='OHM2', range=1e8, plc=1)), ('OHM2', dict(kind='OHM2', range=1000.0, plc=1)),
           ('DCV filter count 5', dict(kind='DCV', range=1.0, plc=1, filter_count=5)),
           ('ACV filter on override', dict(kind='ACV', range=1.0, ac_bandwidth=3, filter_on=True, filter_count=5))]
    for tag, p in pts:
        c.run(f'Keithley2000.configure_point[{tag}]', d.configure_point, p)
    c.run('Keithley2000.configure_point[unknown kind]', d.configure_point, dict(kind='FREQ', range=1.0))
    c.run('Keithley2000.rel_is_on[DCV]', d.rel_is_on, 'DCV')
    c.run('Keithley2000.rel_is_on[ACV]', d.rel_is_on, 'ACV')
    c.quiet(d.configure_point, dict(kind='DCV', range=0.1, plc=1))
    c.quiet(ft.write, 'OUT 0V,0Hz'); c.quiet(ft.write, 'OPER')
    c.run('Keithley2000.acquire_reference', d.acquire_reference)
    c.run('Keithley2000.rel_is_on[after REL]', d.rel_is_on)
    c.run('Keithley2000.read[0 V with REL]', d.read)
    c.quiet(d.configure_point, dict(kind='DCV', range=10.0, plc=1))
    c.quiet(ft.write, 'OUT 5V,0Hz')
    c.run('Keithley2000.read[5 V on 10 V]', d.read)
    c.run('Keithley2000.fetch', d.fetch)
    c.quiet(ft.write, 'OUT 50V,0Hz')
    c.run('Keithley2000.read[overflow]', d.read)
    c.run('Keithley2000.check_errors[ok]', d.check_errors, 'ctx')
    dt.errors = ['-221,"Settings conflict"', '-113,"Undefined header"']
    c.run('Keithley2000.check_errors[two errors]', d.check_errors, 'configuring')
    dt.front = False
    c.run('Keithley2000.front_rear[REAR]', d.front_rear)
    dt.front = True
    c.run('Keithley2000.front_rear[FRONT]', d.front_rear)
    for tag, reply in (('exact', '+1.000000E-01'), ('upper window', '+1.200000E-01'), ('neighbour', '+1.000000E+00'), ('text', 'abc')):
        c.run(f'Keithley2000.range_ok[{tag}]', Keithley2000.range_ok, reply, 0.1)
    dt.range_reply = lambda r: 10 * r                          # the meter answers another range than asked: not accepted, nothing is resent
    c.run('Keithley2000.configure_point[range not accepted]', d.configure_point, dict(kind='DCV', range=1.0, plc=1))
    dt.range_reply = lambda r: r
    wrong = c.inst(Keithley2000, Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), opened=False, label='2000')
    c.run('Keithley2000.connect[wrong model]', wrong.connect)
    bench, ft, dt = make_k2000_bench('5522A', 'GPIB')
    cal = c.inst(Fluke5522AComp, ft, label='5522A')
    c.quiet(ft.write, 'OUT 100OHM')
    for mode in ('WIRE4', 'NONE'):
        c.run(f'Fluke5522AComp.set_compensation[{mode}]', cal.set_compensation, mode)
    c.quiet(ft.write, 'OUT 1000000OHM')
    c.run('Fluke5522AComp.set_compensation[WIRE4 refused above 110 kohm]', cal.set_compensation, 'WIRE4')


def cases_dacq(c):
    bench, ft, dt = make_dacq_bench('34970A')
    d = c.inst(Keysight34970A, dt, opened=False, label='34970A')
    c.run('Keysight34970A.connect', d.connect)
    c.run('Keysight34970A.cleanup', d.cleanup)
    c.run('KeysightDacq.module_type', d.module_type, 2)
    c.run('KeysightDacq.require_module', d.require_module, '34901A', 2)
    c.run('KeysightDacq.require_module[wrong module]', d.require_module, '34902A', 2)
    c.run('KeysightDacq.require_module[empty slot]', d.require_module, '34901A', 3)
    pts = [('FREQ', dict(kind='FREQ', range=1, nominal=1000.0), 210), ('DCV plc', dict(kind='DCV', range=10, plc=1), 210),
           ('DCV no plc', dict(kind='DCV', range=10), 210), ('ACV default filter', dict(kind='ACV', range=1), 210),
           ('ACV 20 Hz', dict(kind='ACV', range=1, filter_hz=20), 210), ('DCI', dict(kind='DCI', range=0.01), 221),
           ('ACI', dict(kind='ACI', range=0.1, filter_hz=200), 221), ('OHM2', dict(kind='OHM2', range=1000), 210),
           ('OHM4', dict(kind='OHM4', range=1000), 210), ('ACV bad filter', dict(kind='ACV', range=1, filter_hz=50), 210),
           ('CAP unsupported', dict(kind='CAP', range=1e-7), 210)]
    for tag, p, ch in pts:
        c.run(f'KeysightDacq.configure_point[{tag}]', d.configure_point, p, ch)
    bench.fluke.update(operate=True, volts=1.0)
    c.quiet(lambda: (d.t.inner.handle('CONF:VOLT:DC 10,(@210)'), d.t.inner.handle('ROUT:SCAN (@210)')))
    c.run('KeysightDacq.read', d.read)
    c.run('KeysightDacq.check_errors[ok]', d.check_errors, 'ctx')
    bad = c.inst(Keysight34970A, Scripted([(r'^SYST:ERR\?', ['-113,"Undefined header"', '-221,"Settings conflict"', '+0,"No error"'])]), label='34970A')
    c.run('KeysightDacq.check_errors[errors]', bad.check_errors, 'configuring')
    over = c.inst(Keysight34970A, Scripted([(r'^READ\?', '+9.90000000E+37')]), label='34970A')
    c.run('KeysightDacq.read[overload]', over.read)
    _b, _f, dt2 = make_dacq_bench('34972A')
    e = c.inst(Keysight34972A, dt2, opened=False, label='34972A')
    c.run('Keysight34972A.connect', e.connect)
    c.run('Keysight34972A.cleanup', e.cleanup)
    wrong = c.inst(Keysight34972A, make_dacq_bench('34970A')[2], opened=False, label='34972A')
    c.run('KeysightDacq.connect[wrong model]', wrong.connect)


def cases_332xx(c):
    for cls, model in ((Keysight33210A, '33210A'), (Keysight33220A, '33220A'), (Keysight33250A, '33250A')):
        bench, t = make_fgen_bench(model)
        g = c.inst(cls, t['uut'], opened=False, label=model)
        c.run(f'{cls.__name__}.connect', g.connect)
        if model != '33220A':
            continue
        c.run('Keysight332xx.check_errors[ok]', g.check_errors, 'ctx')
        c.run('Keysight332xx.output[on]', g.output, True)
        c.run('Keysight332xx.output[off]', g.output, False)
        c.run('Keysight332xx.set_load[INF]', g.set_load, 'INF')
        c.run('Keysight332xx.set_load[50]', g.set_load, 50)
        c.run('Keysight332xx.setup[SIN VRMS 50]', g.setup, 'SIN', 1000.0, 1.0, 'VRMS', 50)
        c.run('Keysight332xx.setup[SQU VPP INF]', g.setup, 'SQU', 100000.0, 2.0, 'VPP', 'INF')
        c.run('Keysight332xx.setup[SIN DBM 50]', g.setup, 'SIN', 10e6, 0.0, 'DBM', 50)
        c.run('Keysight332xx.setup[bad unit]', g.setup, 'SIN', 1000.0, 1.0, 'MV', 50)
        c.run('Keysight332xx.setup[above sine range]', g.setup, 'SIN', 30e6, 1.0, 'VRMS', 50)
        c.run('Keysight332xx.self_test[pass]', g.self_test)
        bench.gen['selftest_fail'] = True
        c.run('Keysight332xx.self_test[fail]', g.self_test)
        bench.gen['selftest_fail'] = False
        c.run('Keysight332xx.cleanup', g.cleanup)
        stuck = c.inst(Keysight33220A, Scripted([(r'^OUTP\?', '1')]), label='33220A')
        c.run('Keysight332xx.output[off not confirmed]', stuck.output, False)
        c.run('Keysight332xx.cleanup[off not confirmed]', stuck.cleanup)
        off = c.inst(Keysight33220A, Scripted([(r'^OUTP\?', '0')]), label='33220A')
        c.run('Keysight332xx.output[on not confirmed]', off.output, True)
        err = c.inst(Keysight33220A, Scripted([(r'^SYST:ERR\?', '-221,"Settings conflict"')]), label='33220A')
        c.run('Keysight332xx.check_errors[error]', err.check_errors, 'setup')
        slow = c.inst(Keysight33220A, Scripted([(r'^\*TST\?', '1'), (r'^OUTP\?', '0'), (r'^SYST:ERR\?', '+625,"Self-test failed"')]), label='33220A')
        c.run('Keysight332xx.self_test[fail reply]', slow.self_test)


def cases_5313x(c):
    for cls, model in ((Keysight53131A, '53131A'), (Keysight53132A, '53132A')):
        bench, t = make_fgen_bench('33220A')
        bench.counter_model = model
        k = c.inst(cls, t['counter'], opened=False, label='Counter')
        c.run(f'{cls.__name__}.connect', k.connect)
        if model != '53132A':
            c.run('Keysight5313x.set_reference[EXT 53131A]', k.set_reference, 'EXT')
            continue
        c.run('Keysight5313x.check_errors[ok]', k.check_errors, 'ctx')
        c.run('Keysight5313x.self_test[pass]', k.self_test)
        c.run('Keysight5313x.configure_frequency[ch1 defaults]', k.configure_frequency)
        c.run('Keysight5313x.configure_frequency[ch1 expected 1 MHz DC 1M]', k.configure_frequency, 1, 0.5, 1e6, 'DC', 1e6)
        c.run('Keysight5313x.reference', k.reference)
        c.run('Keysight5313x.set_reference[INT]', k.set_reference, 'INT')
        c.run('Keysight5313x.set_reference[EXT 53132A]', k.set_reference, 'EXT')
        c.run('Keysight5313x.set_reference[bad]', k.set_reference, 'XTAL')
        c.run('Keysight5313x.read_frequency[no signal]', k.read_frequency)
        bench.gen.update(on=True, freq=1e6)
        bench.connected = 'counter'
        c.run('Keysight5313x.read_frequency', k.read_frequency)
        c.run('Keysight5313x.frequency', k.frequency)
        c.run('Keysight5313x.cleanup', k.cleanup)
        c.run('Keysight5313x.configure_frequency[bad channel]', k.configure_frequency, 3)
        c.run('Keysight5313x.configure_frequency[bad gate]', k.configure_frequency, 1, 5000)
        c.run('Keysight5313x.configure_frequency[bad impedance]', k.configure_frequency, 1, 1.0, 75)
        c.run('Keysight5313x.configure_frequency[expected out of range]', k.configure_frequency, 1, 1.0, 50, 'AC', 500e6)
    # channel 2 and the error branches need replies the simulator does not give
    rules = [(r'^:FUNC\?', '"FREQ 2"'), (r'^:INP2:IMP\?', '+5.00000E+01'), (r'^:INP2:COUP\?', 'AC'), (r'^:FREQ:ARM:STAR:SOUR\?', 'IMM'),
             (r'^:FREQ:ARM:STOP:SOUR\?', 'TIM'), (r'^:FREQ:ARM:STOP:TIM\?', '+1.00000E+00'), (r'^:FREQ:EXP2\?', '+1.00000000000E+06'),
             (r'^:SYST:ERR\?', '+0,"No error"')]
    ch2 = c.inst(Keysight53132A, Scripted(rules), label='Counter')
    c.run('Keysight5313x.configure_frequency[ch2 expected]', ch2.configure_frequency, 2, 1.0, 50, 'ac', 1e6)
    noext = c.inst(Keysight53132A, Scripted([(r'^:ROSC:SOUR\?', 'EXT'), (r'^:SYST:ERR\?', '+2009,"No valid external timebase"')]), label='Counter')
    c.run('Keysight5313x.set_reference[EXT no timebase]', noext.set_reference, 'EXT')
    other = c.inst(Keysight53132A, Scripted([(r'^:ROSC:SOUR\?', 'EXT'), (r'^:SYST:ERR\?', '-221,"Settings conflict"')]), label='Counter')
    c.run('Keysight5313x.set_reference[EXT error]', other.set_reference, 'EXT')
    lost = c.inst(Keysight53132A, Scripted([(r'^READ\?', '+1.00000000000000E+06'), (r'^:SYST:ERR\?', '+2010,"External timebase failed"')]), label='Counter')
    c.run('Keysight5313x.read_frequency[timebase lost]', lost.read_frequency)
    nan = c.inst(Keysight53132A, Scripted([(r'^READ\?', '+9.91000000000E+37'), (r'^:SYST:ERR\?', '-230,"Data corrupt or stale"')]), label='Counter')
    c.run('Keysight5313x.read_frequency[NaN]', nan.read_frequency)
    st = c.inst(Keysight53132A, Scripted([(r'^\*TST\?', '+1'), (r'^:SYST:ERR\?', '+301,"Self test failed"')]), label='Counter')
    c.run('Keysight5313x.self_test[fail]', st.self_test)
    bad = c.inst(Keysight53132A, Scripted([(r'^:SYST:ERR\?', '-113,"Undefined header"')]), label='Counter')
    c.run('Keysight5313x.check_errors[error]', bad.check_errors, 'ctx')


def cases_5790b(c):
    bench, t = make_fgen_bench('33220A')
    s = c.inst(Fluke5790B, t['std'], opened=False, label='5790B')
    c.run('Fluke5790B.connect', s.connect)
    c.run('Fluke5790B.check_error[ok]', s.check_error, 'ctx')
    for name in ('INPUT1', 'input2', 'AUX', 'WBND'):
        c.run(f'Fluke5790B.select_input[{name.upper()}]', s.select_input, name)
    c.run('Fluke5790B.select_input[bad]', s.select_input, 'FRONT')
    c.run('Fluke5790B.set_external_trigger[on]', s.set_external_trigger, True)
    c.run('Fluke5790B.set_external_trigger[off]', s.set_external_trigger, False)
    c.run('Fluke5790B.range_info', s.range_info)
    c.run('Fluke5790B.set_range_for', s.set_range_for, 0.5)
    c.run('Fluke5790B.set_range_for[negative]', s.set_range_for, -2.0)
    c.run('Fluke5790B.set_autorange', s.set_autorange)
    c.run('Fluke5790B.wideband_option[WBND]', s.wideband_option)
    c.run('Fluke5790B.require_wideband[WBND ok]', s.require_wideband, 20e6)
    c.run('Fluke5790B.require_wideband[WBND too slow]', s.require_wideband, 40e6)
    bench.std_option = 'WBAF'
    c.run('Fluke5790B.require_wideband[WBAF correction off]', s.require_wideband, 40e6)
    bench.wbaf_on = True
    c.run('Fluke5790B.require_wideband[WBAF correction on]', s.require_wideband, 40e6)
    bench.std_option = '0'
    c.run('Fluke5790B.wideband_option[none]', s.wideband_option)
    c.run('Fluke5790B.require_wideband[none]', s.require_wideband, 10e6)
    bench.std_option = 'WBND'
    c.quiet(s.select_input, 'INPUT1')
    c.quiet(s.set_range_for, 2.0)
    bench.gen.update(on=True, freq=1000.0, amp=1.0, unit='VRMS')
    bench.std['unsettled_left'] = 2
    c.run('Fluke5790B.measure[settles]', s.measure)
    bench.gen['on'] = False
    c.run('Fluke5790B.measure[value invalid]', s.measure)
    stuck = c.inst(Fluke5790B, Scripted([(r'^MEAS\?', '0.0E+00,1.0E+03,4')]), label='5790B')
    c.run('Fluke5790B.measure[never settles]', stuck.measure, 3.0, 1.0)
    short = c.inst(Fluke5790B, Scripted([(r'^MEAS\?', '1.0')]), label='5790B')
    c.run('Fluke5790B.measure[short reply]', short.measure)
    c.run('Fluke5790B.cleanup', s.cleanup)
    err = c.inst(Fluke5790B, Scripted([(r'^ERR\?', '303,"Option not installed"')]), label='5790B')
    c.run('Fluke5790B.check_error[error]', err.check_error, 'input WBND')
    for tag, ident in (('5790A emulation', 'FLUKE,5790A,1,1'), ('other model', 'KEYSIGHT,34401A,1,1')):
        w = c.inst(Fluke5790B, Scripted([(r'\*IDN\?', ident)]), opened=False, label='5790B')
        c.run(f'Fluke5790B.connect[{tag}]', w.connect)
    c.run('Fluke5790B.range_info[short reply]', c.inst(Fluke5790B, Scripted([(r'^RANGE\?', '7,1')]), label='5790B').range_info)
    auto = c.inst(Fluke5790B, Scripted([(r'^RANGE\?', '7.0E+00,6.6E+00,7E-06,1')]), label='5790B')
    c.run('Fluke5790B.set_range_for[autorange still on]', auto.set_range_for, 5.0)


def cases_28x(c):
    bench = SimBench()
    sim = SimFluke28x(bench, '289')
    m = c.inst(Fluke28x, sim, opened=False, label='289')
    c.run('Fluke28x.connect', m.connect)
    c.run('Fluke28x.identify', m.identify)
    bench.meter['value'] = lambda: 1.0
    c.run('Fluke28x.primary', m.primary)
    c.run('Fluke28x.display', m.display)
    c.run('Fluke28x.stable_reading', m.stable_reading, 'VDC')
    c.run('Fluke28x.stable_reading[no such unit]', m.stable_reading, 'OHM')
    bench.meter['value'] = lambda: 50.0
    c.run('Fluke28x.stable_reading[overload]', m.stable_reading, 'VDC')
    c.run('Fluke28x.cleanup', m.cleanup)
    other = c.inst(Fluke28x, Scripted([(r'^ID$', ('0', 'FLUKE 87,V1,1'))]), opened=False, label='87')
    c.run('Fluke28x.connect[wrong model]', other.connect)
    silent = c.inst(Fluke28x, Scripted([(r'^QM$', '0')]), label='289')
    c.run('Fluke28x.primary[no data line]', silent.primary)
    nack = c.inst(Fluke28x, Scripted([(r'^QDDA$', '1')]), label='289')
    c.run('Fluke28x.display[syntax error ack]', nack.display)


def cases_lecroy(c):
    bench, _ft, st = make_bench()
    w = c.inst(WaveSurfer4104HD, st, label='WS4104HD')
    c.run('WaveSurfer4104HD.vbs_set_number', w.vbs_set_number, 'app.Acquisition.C1.VerScale', 0.5)
    c.run('WaveSurfer4104HD.vbs_set_text', w.vbs_set_text, 'app.Acquisition.C1.Coupling', 'DC1M')
    c.run('WaveSurfer4104HD.vbs_get', w.vbs_get, 'app.Acquisition.C1.Coupling')
    c.run('WaveSurfer4104HD.vbs_get_float', w.vbs_get_float, 'app.Acquisition.C1.VerScale')
    c.run('WaveSurfer4104HD.vbs_get_float[not a number]', w.vbs_get_float, 'app.Acquisition.C1.Coupling')
    c.run('WaveSurfer4104HD.handshake', w.handshake)
    c.run('WaveSurfer4104HD.set_vertical_scale', w.set_vertical_scale, 1, 0.01)
    c.run('WaveSurfer4104HD.set_vertical_scale[channel text]', w.set_vertical_scale, '3', 0.05, settle=0.1)
    c.run('WaveSurfer4104HD.set_vertical_scale[bad channel]', w.set_vertical_scale, 'C1', 0.01)
    c.run('WaveSurfer4104HD.set_vertical_offset', w.set_vertical_offset, 1, 0.25)
    c.run('WaveSurfer4104HD.ensure_zero_offset[needs write]', w.ensure_zero_offset, 1)
    c.run('WaveSurfer4104HD.ensure_zero_offset[already zero]', w.ensure_zero_offset, 1)
    c.run('WaveSurfer4104HD.set_coupling', w.set_coupling, 1, 'DC50')
    c.run('WaveSurfer4104HD.set_bandwidth_limit', w.set_bandwidth_limit, 1, '20MHz')
    c.run('WaveSurfer4104HD.set_coupling_legacy', w.set_coupling_legacy, 'C1', 'D50')
    c.run('WaveSurfer4104HD.configure_dc_input', w.configure_dc_input, 2)
    c.run('WaveSurfer4104HD.set_timebase', w.set_timebase, 1e-3)
    c.run('WaveSurfer4104HD.set_edge_trigger_source', w.set_edge_trigger_source, 2)
    c.run('WaveSurfer4104HD.set_trigger_slope', w.set_trigger_slope, 'Negative')
    c.run('WaveSurfer4104HD.set_trigger_level', w.set_trigger_level, 0.5)
    c.run('WaveSurfer4104HD.set_trigger_mode', w.set_trigger_mode, 'Normal')
    c.run('WaveSurfer4104HD.set_trigger_mode[accept]', w.set_trigger_mode, 'Single', accept=('Stopped', 'Single'))
    c.run('WaveSurfer4104HD.trigger_mode', w.trigger_mode)
    for engine in ('Mean', 'StandardDeviation', 'PkPk', 'Freq'):
        c.run(f'WaveSurfer4104HD.configure_p1[{engine}]', w.configure_p1, 1, engine)
    c.run('WaveSurfer4104HD.configure_p1[show False]', w.configure_p1, 2, 'Mean', show=False)
    bench.fluke.update(operate=True, volts=1.0, scope='VOLT')
    c.run('WaveSurfer4104HD.read_p1', w.read_p1)
    c.run('WaveSurfer4104HD.read_p1_settled', w.read_p1_settled, 2.0)
    c.run('WaveSurfer4104HD.read_p1_when_ready', w.read_p1_when_ready, 2.0, 0.0)
    c.run('WaveSurfer4104HD.enable_channel', w.enable_channel, 2)
    c.run('WaveSurfer4104HD.ensure_not_inverted', w.ensure_not_inverted, 2)
    c.run('WaveSurfer4104HD.query_retry[first try]', w.query_retry, 'VBS? "return=app.Acquisition.C1.VerScale"')
    # read recovery (device clear, then close and reopen), needs a transport that fails
    flaky = c.inst(WaveSurfer4104HD, Scripted([(r'^VBS\?', [TransportError('timeout'), 'VBS 0.01'])]), label='WS4104HD')
    c.run('WaveSurfer4104HD.query_retry[device clear]', flaky.query_retry, 'VBS? "return=app.Acquisition.C1.VerScale"')
    flaky2 = c.inst(WaveSurfer4104HD, Scripted([(r'^VBS\?', [TransportError('timeout'), TransportError('timeout'), 'VBS 0.01'])]), label='WS4104HD')
    c.run('WaveSurfer4104HD.query_retry[reopen]', flaky2.query_retry, 'VBS? "return=app.Acquisition.C1.VerScale"')
    dead = c.inst(WaveSurfer4104HD, Scripted([(r'^VBS\?', TransportError('timeout'))]), label='WS4104HD')
    c.run('WaveSurfer4104HD.query_retry[gives up]', dead.query_retry, 'VBS? "return=app.Acquisition.C1.VerScale"')
    stale = c.inst(WaveSurfer4104HD, Scripted([(r'^VBS\?', [TransportError('t'), TransportError('t'), TransportError('t'), 'VBS 0.01'])]), label='WS4104HD')
    c.run('WaveSurfer4104HD.handshake[stale session reopened]', stale.handshake, attempts=2)
    mism = c.inst(WaveSurfer4104HD, Scripted([(r'^C1:CPL\?', 'C1:CPL A1M')]), label='WS4104HD')
    c.run('WaveSurfer4104HD.set_coupling_legacy[mismatch]', mism.set_coupling_legacy, 'C1', 'D50')
    z = c.inst(WaveSurfer4104HD, Scripted([(r'^VBS\?', 'VBS 0.5')]), label='WS4104HD')
    c.run('WaveSurfer4104HD.ensure_zero_offset[stays non-zero]', z.ensure_zero_offset, 4)
    bm = c.inst(WaveSurfer4104HD, Scripted([(r'^VBS\?.*Coupling', 'VBS DC50'), (r'^VBS\?.*BandwidthLimit', 'VBS Full')]), label='WS4104HD')
    c.run('WaveSurfer4104HD.configure_dc_input[mismatch]', bm.configure_dc_input, 1)


def cases_mdo(c):
    bench, t = make_mdo_bench()
    m = c.inst(TektronixMDO4000C, t['scope'], opened=False, label='MDO4000C')
    c.run('TektronixMDO4000C.connect', m.connect)
    c.run('TektronixMDO4000C.installed_options', m.installed_options)
    c.run('TektronixMDO4000C.opc[no timeout]', m.opc)
    c.run('TektronixMDO4000C.opc[timeout]', m.opc, 60)
    c.run('TektronixMDO4000C.check_errors[ok]', m.check_errors, 'ctx')
    c.run('TektronixMDO4000C.default_setup', m.default_setup)
    c.run('TektronixMDO4000C.select_only', m.select_only, 2)
    c.run('TektronixMDO4000C.channel[all]', m.channel, 1, term='1M', bw='TWEnty', vscale=0.5, offset=0.1, position=0.0)
    c.run('TektronixMDO4000C.channel[50 ohm minimal]', m.channel, 2, term='50', position=None)
    c.run('TektronixMDO4000C.channel[defaults]', m.channel, 3)
    c.run('TektronixMDO4000C.set_verified', m.set_verified, 'CH1:SCAle', 'CH1:SCAle?', 0.2)
    c.run('TektronixMDO4000C.set_enum_verified', m.set_enum_verified, 'CH1:BANdwidth', 'CH1:BANdwidth?', 'FULl')
    c.run('TektronixMDO4000C.acquire_mode[average]', m.acquire_mode, 'AVErage', 32)
    c.run('TektronixMDO4000C.acquire_mode[sample]', m.acquire_mode, 'SAMple')
    c.run('TektronixMDO4000C.timebase', m.timebase, 1e-3)
    c.run('TektronixMDO4000C.delay', m.delay, 0.00025)
    c.run('TektronixMDO4000C.trigger_line', m.trigger_line)
    c.run('TektronixMDO4000C.trigger_edge[level]', m.trigger_edge, 'CH1', level=0.5, slope='FALL', mode='NORMal')
    c.run('TektronixMDO4000C.trigger_edge[defaults]', m.trigger_edge, 'CH2')
    c.run('TektronixMDO4000C.measure_setup[source2]', m.measure_setup, 'DELay', 'CH1', slot=2, source2='CH2')
    c.run('TektronixMDO4000C.measure_setup[single]', m.measure_setup, 'MEAN', 'CH1')
    c.run('TektronixMDO4000C.stats_reset[weighting]', m.stats_reset, 16)
    c.run('TektronixMDO4000C.stats_reset[none]', m.stats_reset)
    c.run('TektronixMDO4000C.stat_mean', m.stat_mean)
    c.run('TektronixMDO4000C.stat_stddev', m.stat_stddev, 2)
    c.run('TektronixMDO4000C.meas_value', m.meas_value)
    c.run('TektronixMDO4000C.mean_of', m.mean_of, 1, 8, 1.0)
    c.run('TektronixMDO4000C.delay_stddev', m.delay_stddev, 1, 50, 2.0)
    c.run('TektronixMDO4000C.fetch', m.fetch, 'CH1')
    c.run('TektronixMDO4000C.edge_time', m.edge_time, 1)
    c.run('TektronixMDO4000C.rf_cmd[on]', m.rf_cmd, 'on')
    c.run('TektronixMDO4000C.rf_cmd[center]', m.rf_cmd, 'center', v=1e9)
    c.run('TektronixMDO4000C.rf_cmd[avg_count]', m.rf_cmd, 'avg_count', n=8)
    c.run('TektronixMDO4000C.rf_setup[full]', m.rf_setup, center=1e9, span=1e6, start=0.9e9, stop=1.1e9, rbw=1e3, ref_level=-10, averages=4)
    c.run('TektronixMDO4000C.rf_setup[minimal]', m.rf_setup, center=2e9, span=1e6, average_trace=False)
    c.run('TektronixMDO4000C.rf_rbw', m.rf_rbw)
    c.run('TektronixMDO4000C.rf_trace[average]', m.rf_trace)
    c.run('TektronixMDO4000C.rf_trace[normal]', m.rf_trace, average=False)
    c.run('TektronixMDO4000C.afg_set[all]', m.afg_set, 'SINusoid', 1000.0, 1.0, 0.0)
    c.run('TektronixMDO4000C.afg_set[function only]', m.afg_set, 'SQUare')
    c.run('TektronixMDO4000C.afg_off', m.afg_off)
    c.run('TektronixMDO4000C.dvm', m.dvm, 'DC', 1)
    c.run('TektronixMDO4000C.dvm_value', m.dvm_value, 1.0)
    c.run('TektronixMDO4000C.dvm_frequency', m.dvm_frequency, 1.0)
    c.run('TektronixMDO4000C.run_diagnostics', m.run_diagnostics)
    c.run('TektronixMDO4000C.run_spc', m.run_spc)
    c.run('TektronixMDO4000C.cleanup', m.cleanup)
    # branches the simulator cannot reach
    err = c.inst(TektronixMDO4000C, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='MDO4000C')
    c.run('TektronixMDO4000C.check_errors[command error]', err.check_errors, 'setup')
    err2 = c.inst(TektronixMDO4000C, Scripted([(r'^\*ESR\?', '4')]), label='MDO4000C')
    c.run('TektronixMDO4000C.check_errors[no event text]', err2.check_errors)
    noopt = c.inst(TektronixMDO4000C, Scripted([(r'^\*OPT\?', TransportError('timeout'))]), label='MDO4000C')
    c.run('TektronixMDO4000C.installed_options[query fails]', noopt.installed_options)
    flat = c.inst(TektronixMDO4000C, Scripted([(r'^CH1:SCAle\?', '0.9')]), label='MDO4000C')
    c.run('TektronixMDO4000C.set_verified[mismatch]', flat.set_verified, 'CH1:SCAle', 'CH1:SCAle?', 0.2)
    flat2 = c.inst(TektronixMDO4000C, Scripted([(r'^CH1:BANdwidth\?', 'TWO')]), label='MDO4000C')
    c.run('TektronixMDO4000C.set_enum_verified[mismatch]', flat2.set_enum_verified, 'CH1:BANdwidth', 'CH1:BANdwidth?', 'FULl')
    noedge = c.inst(TektronixMDO4000C, Scripted([(r'^WFMOutpre:NR_Pt\?', '3'), (r'^WFMOutpre', '0.0'), (r'^CURVe\?', '1,1,1')]), label='MDO4000C')
    c.run('TektronixMDO4000C.edge_time[no edge]', noedge.edge_time, 1)
    bad = c.inst(TektronixMDO4000C, Scripted([(r'^MEASUrement:MEAS1:MEAN\?', '9.91E+37')]), label='MDO4000C')
    c.run('TektronixMDO4000C.stat_mean[invalid]', bad.stat_mean)
    slow = c.inst(TektronixMDO4000C, Scripted([(r'^DIAg:STATE\?', ['EXECUTING', 'EXECUTING', 'DONE']), (r'^DIAg:RESUlt:FLAg\?', 'FAIL'),
                                               (r'^DIAg:RESUlt:LOG\?', '"1 failed"')]), label='MDO4000C')
    c.run('TektronixMDO4000C.run_diagnostics[polls and fails]', slow.run_diagnostics, 900)
    spc = c.inst(TektronixMDO4000C, Scripted([(r'^CALibrate:INTERNal:STATus\?', ['RUNNING', 'DONE']), (r'^CALibrate:RESults:SPC\?', 'FAIL')]),
                 label='MDO4000C')
    c.run('TektronixMDO4000C.run_spc[polls and fails]', spc.run_spc, 1200)
    wrong = c.inst(TektronixMDO4000C, Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), opened=False, label='MDO4000C')
    c.run('TektronixMDO4000C.connect[wrong model]', wrong.connect)


def cases_reference(c):
    bench, t = make_mdo_bench()
    rf = c.inst(Fluke96270A, t['rf1'], opened=False, label='96270A')
    c.run('Fluke96270A.connect', rf.connect)
    c.run('Fluke96270A.check_error[ok]', rf.check_error, 'ctx')
    c.run('Fluke96270A.set_rf', rf.set_rf, 1e9, -10.0)
    c.run('Fluke96270A.set_rf[above range]', rf.set_rf, 7e9, -10.0)
    c.run('Fluke96270A.set_rf[level out of range]', rf.set_rf, 1e9, 40.0)
    rf.t.inner.st['errors'].clear()
    c.run('Fluke96270A.output[on]', rf.output, True)
    c.run('Fluke96270A.output[off]', rf.output, False)
    c.run('Fluke96270A.cleanup', rf.cleanup)
    stuck = c.inst(Fluke96270A, Scripted([(r'^OUTP\?', '1')]), label='96270A')
    c.run('Fluke96270A.output[off not confirmed]', stuck.output, False)
    c.run('Fluke96270A.cleanup[off not confirmed]', stuck.cleanup)
    off = c.inst(Fluke96270A, Scripted([(r'^OUTP\?', 'OFF')]), label='96270A')
    c.run('Fluke96270A.output[on not confirmed]', off.output, True)
    bad = c.inst(Fluke96270A, Scripted([(r'^SYST:ERR\?', '-222,"Data out of range"')]), label='96270A')
    c.run('Fluke96270A.check_error[error]', bad.check_error, 'level')
    cn = c.inst(Fluke96270A, Scripted([(r'\*IDN\?', 'Fluke,96270A,1,1'), (r'^INST\?', '"PULSE"')]), opened=False, label='96270A')
    c.run('Fluke96270A.connect[instrument not confirmed]', cn.connect)

    afg = c.inst(AgilentAFG, t['gen'], opened=False, label='FuncGen')
    c.run('AgilentAFG.connect', afg.connect)
    c.run('AgilentAFG.sine[50]', afg.sine, 1e6, 1.0)
    c.run('AgilentAFG.sine[INF]', afg.sine, 1e6, 2.0, load='INF')
    c.run('AgilentAFG.square', afg.square, 1000.0, 1.0)
    c.run('AgilentAFG.sine[above range]', afg.sine, 90e6, 1.0)
    c.run('AgilentAFG.output[on]', afg.output, True)
    c.run('AgilentAFG.output[off]', afg.output, False)
    c.run('AgilentAFG.cleanup', afg.cleanup)
    wrong = c.inst(AgilentAFG, Scripted([(r'^FREQuency\?', '5000'), (r'^VOLTage\?', '1')]), label='FuncGen')
    wrong.kind = '33220'
    c.run('AgilentAFG.sine[readback mismatch]', wrong.sine, 1e6, 1.0)

    dmm = c.inst(ReferenceMeter, t['dmm'], opened=False, label='RefDMM')
    c.run('ReferenceMeter.connect', dmm.connect)
    c.run('ReferenceMeter.frequency', dmm.frequency)
    c.run('ReferenceMeter.ac_rms', dmm.ac_rms)
    c.run('ReferenceMeter.power', dmm.power)
    c.run('ReferenceMeter.dc', dmm.dc)
    over = c.inst(ReferenceMeter, Scripted([(r'^MEASure:FREQuency\?', '9.91E+37')]), label='RefDMM')
    c.run('ReferenceMeter.frequency[overload]', over.frequency)


def cases_tds(c):
    bench, t = make_tds_bench('2024C')
    m = c.inst(TektronixTDS2000C, t['scope'], opened=False, label='TDS2000C')
    c.run('TektronixTDS2000C.connect', m.connect)
    c.run('TektronixTDS2000C.opc[no timeout]', m.opc)
    c.run('TektronixTDS2000C.opc[timeout]', m.opc, 60)
    c.run('TektronixTDS2000C.check_errors[ok]', m.check_errors, 'ctx')
    c.run('TektronixTDS2000C.default_setup', m.default_setup)
    c.run('TektronixTDS2000C.select_only', m.select_only, 2)
    c.run('TektronixTDS2000C.channel[all]', m.channel, 1, vscale=0.5, position=0.0, probe=1, coupling='DC', bw_limit=True)
    c.run('TektronixTDS2000C.channel[defaults]', m.channel, 3)
    c.run('TektronixTDS2000C.position', m.position, 1, 0.0)
    c.run('TektronixTDS2000C.set_verified', m.set_verified, 'CH1:SCAle', 'CH1:SCAle?', 0.2)
    c.run('TektronixTDS2000C.set_enum_verified', m.set_enum_verified, 'CH1:BANdwidth', 'CH1:BANdwidth?', 'OFF')
    c.run('TektronixTDS2000C.acquire_mode[average]', m.acquire_mode, 'AVErage', 64)
    c.run('TektronixTDS2000C.acquire_mode[sample]', m.acquire_mode, 'SAMple')
    c.run('TektronixTDS2000C.run', m.run)
    c.run('TektronixTDS2000C.num_acq', m.num_acq)
    c.run('TektronixTDS2000C.wait_acquisitions', m.wait_acquisitions, 1, timeout=5.0, poll=0.0)
    c.run('TektronixTDS2000C.timebase', m.timebase, 1e-3)
    c.run('TektronixTDS2000C.horizontal_position', m.horizontal_position, 0.0)
    c.run('TektronixTDS2000C.trigger_edge[level]', m.trigger_edge, 'CH1', slope='FALL', mode='NORMal', coupling='DC')
    c.run('TektronixTDS2000C.trigger_edge[defaults]', m.trigger_edge, 'CH2')
    c.run('TektronixTDS2000C.trigger_mode', m.trigger_mode, 'AUTO')
    c.run('TektronixTDS2000C.set_level_50', m.set_level_50)
    c.run('TektronixTDS2000C.trigger_state', m.trigger_state)
    c.run('TektronixTDS2000C.measure_setup', m.measure_setup, 'PK2pk', 1)
    c.run('TektronixTDS2000C.meas_value', m.meas_value)
    c.run('TektronixTDS2000C.measure', m.measure, 'MEAN', 1, count=2, timeout=5.0)
    c.run('TektronixTDS2000C.waveform', m.waveform, 1)
    c.run('TektronixTDS2000C.waveform_burst', m.waveform_burst, 1, 2, 500)
    c.run('TektronixTDS2000C.run_self_test', m.run_self_test)
    c.run('TektronixTDS2000C.self_cal', m.self_cal)
    c.run('TektronixTDS2000C.cleanup', m.cleanup)
    # branches the simulator cannot reach
    err = c.inst(TektronixTDS2000C, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='TDS2000C')
    c.run('TektronixTDS2000C.check_errors[command error]', err.check_errors, 'setup')
    err2 = c.inst(TektronixTDS2000C, Scripted([(r'^\*ESR\?', '4')]), label='TDS2000C')
    c.run('TektronixTDS2000C.check_errors[no event text]', err2.check_errors)
    flat = c.inst(TektronixTDS2000C, Scripted([(r'^CH1:SCAle\?', '0.9')]), label='TDS2000C')
    c.run('TektronixTDS2000C.set_verified[mismatch]', flat.set_verified, 'CH1:SCAle', 'CH1:SCAle?', 0.2)
    flat2 = c.inst(TektronixTDS2000C, Scripted([(r'^CH1:BANdwidth\?', 'ON')]), label='TDS2000C')
    c.run('TektronixTDS2000C.set_enum_verified[mismatch]', flat2.set_enum_verified, 'CH1:BANdwidth', 'CH1:BANdwidth?', 'OFF')
    bad = c.inst(TektronixTDS2000C, Scripted([(r'^MEASUrement:IMMed:VALue\?', '9.9E+37')]), label='TDS2000C')
    c.run('TektronixTDS2000C.meas_value[invalid]', bad.meas_value)
    few = c.inst(TektronixTDS2000C, Scripted([(r'^ACQuire:NUMACq\?', '0')]), label='TDS2000C')
    c.run('TektronixTDS2000C.wait_acquisitions[too few]', few.wait_acquisitions, 5, timeout=0.0, poll=0.0)
    short = c.inst(TektronixTDS2000C, Scripted([(r'^WFMPre:XINcr\?', '1E-9'), (r'^WFMPre:XZEro\?', '0'), (r'^WFMPre:YMUlt\?', '0.1'),
                                                (r'^WFMPre:YOFf\?', '0'), (r'^WFMPre:YZEro\?', '0'), (r'^CURVe\?', 'CURVE 1,2,3')]), label='TDS2000C')
    c.run('TektronixTDS2000C.waveform[record too short]', short.waveform, 1)
    badscale = c.inst(TektronixTDS2000C, Scripted([(r'^WFMPre:XINcr\?', '0'), (r'^WFMPre:YMUlt\?', '0.1'), (r'^WFMPre:YOFf\?', '0'), (r'^WFMPre:YZEro\?', '0')]),
                      label='TDS2000C')
    c.run('TektronixTDS2000C.waveform_burst[scale not usable]', badscale.waveform_burst, 1, 2)
    failing = c.inst(TektronixTDS2000C, Scripted([(r'^DIAg:RESUlt:FLAg\?', 'FAIL'), (r'^DIAg:RESUlt:LOG\?', '"1 failed"')]), label='TDS2000C')
    c.run('TektronixTDS2000C.run_self_test[fails]', failing.run_self_test)
    nolog = c.inst(TektronixTDS2000C, Scripted([(r'^DIAg:RESUlt:FLAg\?', 'PASS'), (r'^DIAg:RESUlt:LOG\?', TransportError('timeout'))]), label='TDS2000C')
    c.run('TektronixTDS2000C.run_self_test[log query fails]', nolog.run_self_test)
    badcal = c.inst(TektronixTDS2000C, Scripted([(r'^\*CAL\?', '1'), (r'^CALibrate:STATUS\?', 'FAIL')]), label='TDS2000C')
    c.run('TektronixTDS2000C.self_cal[fails]', badcal.self_cal)
    wrong = c.inst(TektronixTDS2000C, Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), opened=False, label='TDS2000C')
    c.run('TektronixTDS2000C.connect[wrong model]', wrong.connect)


def cases_5522a_scope(c):
    bench, t = make_tds_bench('2024C', '5522A')
    cal = c.inst(Fluke5522AScope, t['cal'], label='5522A')
    c.run('Fluke5522AScope.select_scope_dcv[1M]', cal.select_scope_dcv, '1M')
    c.run('Fluke5522AScope.select_scope_dcv[50]', cal.select_scope_dcv, '50')
    noscope = c.inst(Fluke5522AScope, Scripted([(r'^ERR\?', '0,"No error"'), (r'^SCOPE\?', 'OFF')]), label='5522A')
    c.run('Fluke5522AScope.select_scope_dcv[mode not confirmed]', noscope.select_scope_dcv, '1M')
    badimp = c.inst(Fluke5522AScope, Scripted([(r'^ERR\?', '0,"No error"'), (r'^SCOPE\?', 'VOLT'), (r'^OUT_IMP\?', '50,OHM')]), label='5522A')
    c.run('Fluke5522AScope.select_scope_dcv[impedance not confirmed]', badimp.select_scope_dcv, '1M')
    junk = c.inst(Fluke5522AScope, Scripted([(r'^ERR\?', '0,"No error"'), (r'^SCOPE\?', 'VOLT'), (r'^OUT_IMP\?', 'Z1M')]), label='5522A')
    c.run('Fluke5522AScope.select_scope_dcv[unreadable impedance]', junk.select_scope_dcv, '1M')
    dc = c.inst(Fluke5522AScope, Scripted([(r'^OUT\?', '5.0E-02,V,0E+00,0,0E+00'), (r'^FUNC\?', 'SDCV')]), label='5522A')
    c.run('Fluke5522AScope.set_dc_volts[dc, 0 Hz sent]', dc.set_dc_volts, 0.05)
    ac = c.inst(Fluke5522AScope, Scripted([(r'^OUT\?', '5.0E-02,V,0E+00,0,1.0E+03'), (r'^FUNC\?', 'SACV')]), label='5522A')
    c.run('Fluke5522AScope.set_dc_volts[still AC]', ac.set_dc_volts, 0.05)


# ---- Stage 7: reset to default settings (Instrument.reset_to_defaults), one block per driver fixture, run after that fixture's other cases
def resets_base(c):
    i = c.inst(Instrument, Scripted([]), label='Base')
    c.run('Instrument.reset_to_defaults[no reset declared]', i.reset_to_defaults)


def resets_fluke_5560a(c):
    bench, ft, _s = make_bench()
    ft.opened = True
    cal = c.inst(Fluke5560A, ft, label='5560A')
    bench.fluke.update(operate=True, volts=1.0)
    c.run('Fluke5560A.reset_to_defaults', cal.reset_to_defaults)
    bench.fail_next = '*RST'
    c.run('Fluke5560A.reset_to_defaults[reset write fails: not retried]', cal.reset_to_defaults)
    ft2 = make_dacq_bench(cal='5522A')[1]
    cal2 = c.inst(Fluke5522A, ft2, label='5522A')
    c.run('Fluke5522A.reset_to_defaults', cal2.reset_to_defaults)
    ft3 = make_dacq_bench(cal='5520A')[1]
    cal3 = c.inst(Fluke5520A, ft3, label='5520A')
    c.run('Fluke5520A.reset_to_defaults', cal3.reset_to_defaults)
    stuck = c.inst(Fluke5560A, Scripted([(r'^OPER\?', '1')]), label='5560A')
    c.run('Fluke5560A.reset_to_defaults[standby not confirmed]', stuck.reset_to_defaults)


def resets_scpi_dmm(c):
    for cls, model in ((Fluke8846A, '8846A'), (Agilent34401A, '34401A')):
        bench, ft, dt = make_dmm_bench(model)
        d = c.inst(cls, dt, label=model)
        c.run(f'{cls.__name__}.reset_to_defaults', d.reset_to_defaults)


def resets_truevolt(c):
    bench, ft, dt = make_dmm_bench('34470A')
    d = c.inst(Keysight34470A, dt, label='34470A')
    c.run('Keysight34470A.reset_to_defaults', d.reset_to_defaults)


def cases_k2000_cal(c):
    """The Model 2000 calibration interface (:CAL:PROT). The code on the wire is masked in the record; the code never appears in a log line, a result or an error text."""
    steps = {x['id']: x for x in k2000_cal_steps()}
    for fw in ('A20', 'A19'):
        bench, ft, dt = make_k2000_cal_bench('5522A', 'GPIB', fw)
        d = c.inst(Keithley2000Cal, dt, opened=False, label='2000')
        c.run(f'Keithley2000Cal.connect[{fw}]', d.connect)
    bench, ft, dt = make_k2000_cal_bench('5522A', 'GPIB', 'A20')
    d = c.inst(Keithley2000Cal, dt, opened=False, label='2000')
    c.quiet(d.connect)
    c.quiet(ft.open)
    c.run('Keithley2000Cal.set_firmware_class[A19-]', d.set_firmware_class, 'A19-')
    c.run('Keithley2000Cal.set_firmware_class[bad]', d.set_firmware_class, 'A5')
    c.quiet(d.set_firmware_class, 'A20+')
    c.run('Keithley2000Cal.lock_state[locked]', d.lock_state)
    c.run('Keithley2000Cal.initiate[before unlock]', d.initiate)
    c.run('Keithley2000Cal.calibrate_step[before unlock]', d.calibrate_step, steps['D01'])
    c.run('Keithley2000Cal.unlock[bad shape]', d.unlock, 'NOT A CODE!')
    c.run('Keithley2000Cal.unlock', d.unlock, SIM_CODE)
    c.run('Keithley2000Cal.unlock[second code refused]', d.unlock, SIM_CODE)
    c.run('Keithley2000Cal.lock_state[unlocked]', d.lock_state)
    c.run('Keithley2000Cal.initiate', d.initiate)
    c.run('Keithley2000Cal.initiate[twice]', d.initiate)
    c.run('Keithley2000Cal.calibrate_step[D01 short]', d.calibrate_step, steps['D01'])
    c.quiet(ft.write, 'OUT 10V,0Hz'); c.quiet(ft.write, 'OPER')
    c.run('Keithley2000Cal.calibrate_step[D03 +10 V]', d.calibrate_step, steps['D03'], 10.0)
    c.run('Keithley2000Cal.calibrate_step[D03 parameter missing]', d.calibrate_step, steps['D03'])
    c.run('Keithley2000Cal.calibrate_step[D03 parameter out of range]', d.calibrate_step, steps['D03'], 12.0)
    c.quiet(ft.write, 'OUT 0.01V,1000Hz')
    c.run('Keithley2000Cal.calibrate_step[A01 10 mV ac]', d.calibrate_step, steps['A01'])
    c.run('Keithley2000Cal.calibrate_step[A01 parameter refused]', d.calibrate_step, steps['A01'], 1.0)
    dt.fail_steps['D04'] = 403
    c.quiet(ft.write, 'OUT -10V,0Hz')
    c.run('Keithley2000Cal.calibrate_step[D04 error +403]', d.calibrate_step, steps['D04'], -10.0)
    c.run('Keithley2000Cal.drain_errors[clean]', d.drain_errors)
    dt.errors = ['+402,"10 vdc full scale error"', '+411,"Ohms 1k error"']
    c.run('Keithley2000Cal.drain_errors[two errors]', d.drain_errors)
    dt.errors = ['+402,"10 vdc full scale error"']
    c.run('Keithley2000Cal.require_no_errors[error]', d.require_no_errors, 'ctx')
    c.run('Keithley2000Cal.require_no_errors[ok]', d.require_no_errors, 'ctx')
    c.run('Keithley2000Cal.wait_complete', d.wait_complete)
    dt.hang_opc = True
    c.run('Keithley2000Cal.wait_complete[no answer]', d.wait_complete)
    c.quiet(d.set_firmware_class, 'A19-')
    c.run('Keithley2000Cal.calibrate_step[D10 absent on A19]', d.calibrate_step, steps['D10'], 1e7)
    c.quiet(d.set_firmware_class, 'A20+')
    c.run('Keithley2000Cal.count', d.count)
    c.run('Keithley2000Cal.save[dates missing]', d.save)
    c.run('Keithley2000Cal.set_dates[due before calibration]', d.set_dates, date(2026, 10, 23), date(2026, 10, 1))
    c.run('Keithley2000Cal.set_dates[year out of range]', d.set_dates, date(1990, 1, 1), date(1991, 1, 1))
    c.run('Keithley2000Cal.set_dates', d.set_dates, date(2026, 10, 23), date(2027, 10, 23))
    c.run('Keithley2000Cal.save', d.save)
    c.run('Keithley2000Cal.lock', d.lock)
    c.run('Keithley2000Cal.cleanup', d.cleanup)
    bench, ft, dt = make_k2000_cal_bench('5522A', 'GPIB', 'A20')
    still = c.inst(Keithley2000Cal, dt, opened=False, label='2000')
    c.quiet(still.connect)
    c.run('Keithley2000Cal.unlock[wrong code, stays locked]', still.unlock, 'WRONG123')


def cases_8808a_cal(c):
    """The 8808A RS-232 calibration dialog (*TER, function name, CALREF, the Enter key, EXIT). Simulated meter: reply formats are NOT facts about the real meter."""
    bench, ft, dt = make_8808a_cal_bench('5522A', enforce_cal_limits=False)
    d = c.inst(Fluke8808ACal, dt, opened=False, label='8808A')
    c.quiet(d.connect)
    c.quiet(lambda: (d.t.set_timeout(0.01), setattr(d, 'QUIET_S', 0.01), setattr(d, 'COMMAND_GAP_S', 0.0)))
    c.run('Fluke8808ACal.select_function[before *TER]', d.select_function, 'VDC')
    c.run('Fluke8808ACal.enter_cal_mode', d.enter_cal_mode)
    c.run('Fluke8808ACal.enter_cal_mode[twice]', d.enter_cal_mode)
    c.run('Fluke8808ACal.select_function[bad name]', d.select_function, 'XYZ')
    c.run('Fluke8808ACal.confirm_value[no value yet]', d.confirm_value)
    c.run('Fluke8808ACal.select_function[VDC]', d.select_function, 'VDC')
    c.run('Fluke8808ACal.set_reference[bad text]', d.set_reference, '1e3')
    c.run('Fluke8808ACal.confirm_value', d.confirm_value)
    c.run('Fluke8808ACal.start_point[zero point]', d.start_point)
    c.run('Fluke8808ACal.set_reference', d.set_reference, '-0.1999')
    dt.cal_prompts = False
    c.run('Fluke8808ACal.set_reference[no prompt]', d.set_reference, '-0.1999')
    dt.cal_prompts = True
    c.run('Fluke8808ACal.confirm_value[second]', d.confirm_value)
    c.run('Fluke8808ACal.start_point[nothing applied: refused]', d.start_point)
    c.run('Fluke8808ACal.read_late', d.read_late)
    c.run('Fluke8808ACal.exit_cal', d.exit_cal)
    c.run('Fluke8808ACal.cleanup[not in calibration]', d.cleanup)
    bench, ft, dt = make_8808a_cal_bench('5522A', enforce_cal_limits=False)
    d = c.inst(Fluke8808ACal, dt, opened=False, label='8808A')
    c.quiet(d.connect)
    c.quiet(lambda: (setattr(d, 'QUIET_S', 0.01), setattr(d, 'COMMAND_GAP_S', 0.0), setattr(d, 'POINT_TIMEOUT_S', 0.05)))
    dt.refuse_ter = 'silent'
    c.run('Fluke8808ACal.enter_cal_mode[no banner]', d.enter_cal_mode)
    dt.refuse_ter = 'error'
    c.run('Fluke8808ACal.enter_cal_mode[error prompt]', d.enter_cal_mode)
    dt.refuse_ter = None
    bench, ft, dt = make_8808a_cal_bench('5522A', enforce_cal_limits=False)
    d = c.inst(Fluke8808ACal, dt, opened=False, label='8808A')
    c.quiet(d.connect)
    c.quiet(lambda: (setattr(d, 'QUIET_S', 0.01), setattr(d, 'COMMAND_GAP_S', 0.0), setattr(d, 'POINT_TIMEOUT_S', 0.05)))
    c.run('Fluke8808ACal.select_function[front-panel entry missing]', d.select_function, 'VDC')
    dt.enter_panel(banner=True)
    c.run('Fluke8808ACal.adopt_manual_entry[banner]', d.adopt_manual_entry)
    c.run('Fluke8808ACal.adopt_manual_entry[twice]', d.adopt_manual_entry)
    c.quiet(d.select_function, 'VDC')
    c.quiet(d.confirm_value)
    dt.hang_points.add('S001')
    c.run('Fluke8808ACal.start_point[no completion]', d.start_point)
    c.run('Fluke8808ACal.cleanup[in calibration]', d.cleanup)
    c.run('Fluke8808ACal.write[Enter key]', d.write, '')


def resets_8808a_cal(c):
    bench, ft, dt = make_8808a_cal_bench('5522A', enforce_cal_limits=False)
    d = c.inst(Fluke8808ACal, dt, label='8808A')
    c.run('Fluke8808ACal.reset_to_defaults', d.reset_to_defaults)


def resets_k2000_cal(c):
    for fw in ('A20', 'A19'):
        bench, ft, dt = make_k2000_cal_bench('5522A', 'GPIB', fw)
        d = c.inst(Keithley2000Cal, dt, label='2000')
        c.run(f'Keithley2000Cal.reset_to_defaults[{fw}]', d.reset_to_defaults)


def resets_k2000(c):
    for bus in ('GPIB', 'RS232'):
        bench, ft, dt = make_k2000_bench('5522A', bus)
        d = c.inst(Keithley2000, dt, label='2000')
        c.run(f'Keithley2000.reset_to_defaults[{bus}]', d.reset_to_defaults)


def resets_34410a(c):
    for bus in ('GPIB', 'USB'):
        bench, ft, dt = make_34410a_bench('5522A', bus)
        d = c.inst(Keysight34410A, dt, label='34410A')
        c.run(f'Keysight34410A.reset_to_defaults[{bus}]', d.reset_to_defaults)


def resets_dacq(c):
    for cls, model in ((Keysight34970A, '34970A'), (Keysight34972A, '34972A')):
        bench, ft, dt = make_dacq_bench(model)
        d = c.inst(cls, dt, label=model)
        c.run(f'{cls.__name__}.reset_to_defaults', d.reset_to_defaults)


def resets_332xx(c):
    bench, t = make_fgen_bench('33220A')
    g = c.inst(Keysight33220A, t['uut'], label='33220A')
    bench.gen.update(on=True, freq=5e6)
    c.run('Keysight33220A.reset_to_defaults', g.reset_to_defaults)
    stuck = c.inst(Keysight33220A, Scripted([(r'^OUTP\?', '1')]), label='33220A')
    c.run('Keysight33220A.reset_to_defaults[output stays on]', stuck.reset_to_defaults)


def resets_5313x(c):
    bench, t = make_fgen_bench('33220A')
    bench.counter_model = '53132A'
    k = c.inst(Keysight53132A, t['counter'], label='Counter')
    c.run('Keysight53132A.reset_to_defaults', k.reset_to_defaults)


def resets_5790b(c):
    bench, t = make_fgen_bench('33220A')
    s = c.inst(Fluke5790B, t['std'], label='5790B')
    c.run('Fluke5790B.reset_to_defaults', s.reset_to_defaults)
    q = c.inst(Fluke5790B, Scripted([(r'^ERR\?', ['101,"Command error"', '0,"No Error"'])]), label='5790B')
    c.run('Fluke5790B.reset_to_defaults[error queue not empty: warning]', q.reset_to_defaults)


def resets_28x(c):
    m = c.inst(Fluke28x, SimFluke28x(SimBench(), '289'), label='289')
    c.run('Fluke28x.reset_to_defaults[exempt]', m.reset_to_defaults)


def resets_lecroy(c):
    bench, _ft, st = make_bench()
    w = c.inst(WaveSurfer4104HD, st, label='WS4104HD')
    c.run('WaveSurfer4104HD.reset_to_defaults', w.reset_to_defaults)


def resets_mdo(c):
    bench, t = make_mdo_bench()
    m = c.inst(TektronixMDO4000C, t['scope'], label='MDO4000C')
    c.run('TektronixMDO4000C.reset_to_defaults', m.reset_to_defaults)


def resets_reference(c):
    bench, t = make_mdo_bench()
    rf = c.inst(Fluke96270A, t['rf1'], label='96270A')
    c.run('Fluke96270A.reset_to_defaults', rf.reset_to_defaults)
    g = c.inst(AgilentAFG, t['gen'], label='FuncGen')
    c.run('AgilentAFG.reset_to_defaults', g.reset_to_defaults)
    mtr = c.inst(ReferenceMeter, t['dmm'], label='RefDMM')
    c.run('ReferenceMeter.reset_to_defaults', mtr.reset_to_defaults)


def resets_tds(c):
    bench, t = make_tds_bench('2024C')
    m = c.inst(TektronixTDS2000C, t['scope'], opened=False, label='TDS2000C')
    c.run('TektronixTDS2000C.connect[reset]', m.connect)
    c.run('TektronixTDS2000C.reset_to_defaults', m.reset_to_defaults)
    bad = c.inst(TektronixTDS2000C, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='TDS2000C')
    c.run('TektronixTDS2000C.reset_to_defaults[event status not clean]', bad.reset_to_defaults)


def resets_5522a_scope(c):
    bench, t = make_tds_bench('2024C', '5522A')
    cal = c.inst(Fluke5522AScope, t['cal'], label='5522A')
    bench.fluke.update(operate=True, scope='VOLT', volts=1.0)
    c.run('Fluke5522AScope.reset_to_defaults', cal.reset_to_defaults)
    stuck = c.inst(Fluke5522AScope, Scripted([(r'^OPER\?', '0'), (r'^SCOPE\?', 'VOLT'), (r'^FUNC\?', 'SDCV')]), label='5522A')
    c.run('Fluke5522AScope.reset_to_defaults[SCOPE mode not OFF]', stuck.reset_to_defaults)


def resets_8808a(c):
    bench, ft, dt = make_8808a_bench('5522A', enforce_cal_limits=False)
    d = c.inst(Fluke8808A, dt, label='8808A')
    c.run('Fluke8808A.reset_to_defaults', d.reset_to_defaults)
    bad = c.inst(Fluke8808A, Scripted([(r'^\*ESR\?', ['32', '0']), (r'^\*OPC\?', '1'), (r'^FORMAT\?', '1'), (r'^TRIGGER\?', '1'), (r'^RATE\?', 'S')]), label='8808A')
    c.run('Fluke8808A.reset_to_defaults[error bit set: warning]', bad.reset_to_defaults)



def cases_tbs1000(c):
    """The TBS1000 is the TDS2000C driver (same programmer manual 077-0444-03): only connect / identification is its own."""
    bench, t = make_tbs1000_bench('1154')
    m = c.inst(TektronixTBS1000, t['scope'], opened=False, label='TBS1000')
    c.run('TektronixTBS1000.connect', m.connect)
    two = c.inst(TektronixTBS1000, make_tbs1000_bench('1102')[1]['scope'], opened=False, label='TBS1000')
    c.run('TektronixTBS1000.connect[two channels]', two.connect)
    wrong = c.inst(TektronixTBS1000, Scripted([(r'\*IDN\?', 'TEKTRONIX,TDS 2024C,C0,CF:91.1CT FV:v24')]), opened=False, label='TBS1000')
    c.run('TektronixTBS1000.connect[wrong model]', wrong.connect)


def resets_tbs1000(c):
    bench, t = make_tbs1000_bench('1104')
    m = c.inst(TektronixTBS1000, t['scope'], opened=False, label='TBS1000')
    c.run('TektronixTBS1000.connect[reset]', m.connect)
    c.run('TektronixTBS1000.reset_to_defaults', m.reset_to_defaults)


def cases_tbs1000c(c):
    bench, t = make_tbs1000c_bench('1202C')
    m = c.inst(TektronixTBS1000C, t['scope'], opened=False, label='TBS1000C')
    bench.fluke.update(operate=True, scope='LEVSINE', volts=0.5, freq=10e6)
    c.run('TektronixTBS1000C.connect', m.connect)
    c.run('TektronixTBS1000C.opc[no timeout]', m.opc)
    c.run('TektronixTBS1000C.opc[timeout]', m.opc, 60)
    c.run('TektronixTBS1000C.check_errors[ok]', m.check_errors, 'ctx')
    c.run('TektronixTBS1000C.default_setup', m.default_setup)
    c.run('TektronixTBS1000C.select_only', m.select_only, 2)
    c.run('TektronixTBS1000C.channel[all]', m.channel, 1, vscale=0.5, position=0.0, probe=1, coupling='DC', bw_limit=True)
    c.run('TektronixTBS1000C.channel[defaults]', m.channel, 2)
    c.run('TektronixTBS1000C.position', m.position, 1, 0.0)
    c.run('TektronixTBS1000C.set_num', m.set_num, 'ch.scale.set', 0.2, ch=1)
    c.run('TektronixTBS1000C.set_word', m.set_word, 'ch.bw.set', 'FULl', ch=1)
    c.run('TektronixTBS1000C.acquire_mode[average]', m.acquire_mode, 'AVErage', 64)
    c.run('TektronixTBS1000C.acquire_mode[sample]', m.acquire_mode, 'SAMple')
    c.run('TektronixTBS1000C.run', m.run)
    c.run('TektronixTBS1000C.num_acq', m.num_acq)
    c.run('TektronixTBS1000C.wait_acquisitions', m.wait_acquisitions, 1, timeout=5.0, poll=0.0)
    c.run('TektronixTBS1000C.timebase', m.timebase, 1e-3)
    c.run('TektronixTBS1000C.horizontal_position', m.horizontal_position, 1e-3)
    c.run('TektronixTBS1000C.trigger_edge[aux]', m.trigger_edge, 'EXT', slope='FALL', mode='NORMal', coupling='DC')
    c.run('TektronixTBS1000C.trigger_edge[defaults]', m.trigger_edge, 'CH2')
    c.run('TektronixTBS1000C.trigger_mode', m.trigger_mode, 'AUTO')
    c.run('TektronixTBS1000C.set_level_50', m.set_level_50)
    c.run('TektronixTBS1000C.trigger_state', m.trigger_state)
    c.run('TektronixTBS1000C.measure_setup', m.measure_setup, 'PK2Pk', 1)
    c.run('TektronixTBS1000C.meas_value', m.meas_value)
    c.run('TektronixTBS1000C.measure', m.measure, 'MEAN', 1, count=2, timeout=5.0)
    c.run('TektronixTBS1000C.default_setup[again]', m.default_setup)
    c.run('TektronixTBS1000C.waveform', m.waveform, 1)
    c.run('TektronixTBS1000C.waveform_burst', m.waveform_burst, 1, 2, 300)
    c.run('TektronixTBS1000C.run_self_test', m.run_self_test)
    c.run('TektronixTBS1000C.self_cal', m.self_cal)
    c.run('TektronixTBS1000C.cleanup', m.cleanup)
    # branches the simulator cannot reach
    err = c.inst(TektronixTBS1000C, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='TBS1000C')
    c.run('TektronixTBS1000C.check_errors[command error]', err.check_errors, 'setup')
    flat = c.inst(TektronixTBS1000C, Scripted([(r'^CH1:SCAle\?', '0.9')]), label='TBS1000C')
    c.run('TektronixTBS1000C.set_num[mismatch]', flat.set_num, 'ch.scale.set', 0.2, ch=1)
    flat2 = c.inst(TektronixTBS1000C, Scripted([(r'^CH1:BANdwidth\?', 'TWENTY')]), label='TBS1000C')
    c.run('TektronixTBS1000C.set_word[mismatch]', flat2.set_word, 'ch.bw.set', 'FULl', ch=1)
    src = c.inst(TektronixTBS1000C, Scripted([(r'^MEASUrement:IMMed:SOUrce1\?', 'CH2')]), label='TBS1000C')
    c.run('TektronixTBS1000C.measure_setup[source mismatch]', src.measure_setup, 'MEAN', 1)
    bad = c.inst(TektronixTBS1000C, Scripted([(r'^MEASUrement:IMMed:VALue\?', '9.9E+37')]), label='TBS1000C')
    c.run('TektronixTBS1000C.meas_value[invalid]', bad.meas_value)
    few = c.inst(TektronixTBS1000C, Scripted([(r'^ACQuire:NUMACq\?', '350')]), label='TBS1000C')
    c.run('TektronixTBS1000C.wait_acquisitions[count does not move]', few.wait_acquisitions, 5, timeout=0.0, poll=0.0)
    short = c.inst(TektronixTBS1000C, Scripted([(r'^WFMOutpre:XINcr\?', '1E-9'), (r'^WFMOutpre:XZEro\?', '0'), (r'^WFMOutpre:YMUlt\?', '0.1'),
                                                (r'^WFMOutpre:YOFf\?', '0'), (r'^WFMOutpre:YZEro\?', '0'), (r'^CURVe\?', ':CURVE 1,2,3')]), label='TBS1000C')
    c.run('TektronixTBS1000C.waveform[record too short]', short.waveform, 1)
    junk = c.inst(TektronixTBS1000C, Scripted([(r'^WFMOutpre:XINcr\?', '1E-9'), (r'^WFMOutpre:XZEro\?', '0'), (r'^WFMOutpre:YMUlt\?', '0.1'),
                                               (r'^WFMOutpre:YOFf\?', '0'), (r'^WFMOutpre:YZEro\?', '0'), (r'^CURVe\?', '#41000xyz')]), label='TBS1000C')
    c.run('TektronixTBS1000C.waveform[binary reply]', junk.waveform, 1)
    badscale = c.inst(TektronixTBS1000C, Scripted([(r'^WFMOutpre:XINcr\?', '0'), (r'^WFMOutpre:YMUlt\?', '0.1'), (r'^WFMOutpre:YOFf\?', '0'),
                                                   (r'^WFMOutpre:YZEro\?', '0')]), label='TBS1000C')
    c.run('TektronixTBS1000C.waveform_burst[scale not usable]', badscale.waveform_burst, 1, 2)
    narrow = c.inst(TektronixTBS1000C, Scripted([(r'^WFMOutpre:XINcr\?', '1E-9'), (r'^WFMOutpre:YMUlt\?', '0.1'), (r'^WFMOutpre:YOFf\?', '0'),
                                                 (r'^WFMOutpre:YZEro\?', '0'), (r'^CURVe\?', 'CURVE 1,2,3')]), label='TBS1000C')
    c.run('TektronixTBS1000C.waveform_burst[window too short]', narrow.waveform_burst, 1, 1)
    failing = c.inst(TektronixTBS1000C, Scripted([(r'^DIAg:RESUlt:FLAg\?', 'FAIL'), (r'^DIAg:RESUlt:LOG\?', '"FAIL--ACQ"')]), label='TBS1000C')
    c.run('TektronixTBS1000C.run_self_test[fails]', failing.run_self_test)
    nolog = c.inst(TektronixTBS1000C, Scripted([(r'^DIAg:RESUlt:FLAg\?', 'PASS'), (r'^DIAg:RESUlt:LOG\?', TransportError('timeout'))]), label='TBS1000C')
    c.run('TektronixTBS1000C.run_self_test[log query fails]', nolog.run_self_test)
    badcal = c.inst(TektronixTBS1000C, Scripted([(r'^\*CAL\?', '1'), (r'^CALibrate:INTERNal:STATus\?', 'FAIL')]), label='TBS1000C')
    c.run('TektronixTBS1000C.self_cal[fails]', badcal.self_cal)
    wrong = c.inst(TektronixTBS1000C, Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), opened=False, label='TBS1000C')
    c.run('TektronixTBS1000C.connect[wrong model]', wrong.connect)


def resets_tbs1000c(c):
    bench, t = make_tbs1000c_bench('1202C')
    m = c.inst(TektronixTBS1000C, t['scope'], opened=False, label='TBS1000C')
    c.run('TektronixTBS1000C.connect[reset]', m.connect)
    c.run('TektronixTBS1000C.reset_to_defaults', m.reset_to_defaults)
    bad = c.inst(TektronixTBS1000C, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"'), (r'^HORizontal:RECOrdlength\?', '2000'),
                                              (r'^HORizontal:MAIn:DELay:MODe\?', 'OFF'), (r'^HORizontal:MAIn:POSition\?', '50')]), label='TBS1000C')
    c.run('TektronixTBS1000C.reset_to_defaults[event status not clean]', bad.reset_to_defaults)


def _with_resets(cases, resets):
    def both(c):
        cases(c)
        resets(c)
    return both


def cases_3458a_all(c):
    cases_3458a(c)
    resets_3458a(c)


DRIVER_CASES = {
    'base': _with_resets(cases_base, resets_base), 'fluke_5560a': _with_resets(cases_fluke_5560a, resets_fluke_5560a),
    'scpi_dmm': _with_resets(cases_scpi_dmm, resets_scpi_dmm), 'fluke_8808a': _with_resets(cases_8808a, resets_8808a), 'keysight_truevolt': _with_resets(cases_truevolt, resets_truevolt),
    'keysight_dacq': _with_resets(cases_dacq, resets_dacq), 'keysight_332xx': _with_resets(cases_332xx, resets_332xx),
    'keysight_5313x': _with_resets(cases_5313x, resets_5313x), 'fluke_5790b': _with_resets(cases_5790b, resets_5790b),
    'fluke_28x': _with_resets(cases_28x, resets_28x), 'lecroy_ws4104hd': _with_resets(cases_lecroy, resets_lecroy),
    'tektronix_mdo4000c': _with_resets(cases_mdo, resets_mdo), 'tektronix_tds2000c': _with_resets(cases_tds, resets_tds),
    'fluke_5522a_scope': _with_resets(cases_5522a_scope, resets_5522a_scope), 'reference_instruments': _with_resets(cases_reference, resets_reference),
    'keithley_2000': _with_resets(cases_k2000, resets_k2000),
    'keithley_2000_cal': _with_resets(cases_k2000_cal, resets_k2000_cal),
    'fluke_8808a_cal': _with_resets(cases_8808a_cal, resets_8808a_cal),
    'keysight_34410a': _with_resets(cases_34410a, resets_34410a),
    'keysight_34411a': _with_resets(cases_34411a, resets_34411a),
    'agilent_3458a': cases_3458a_all,
    'tektronix_tbs1000': _with_resets(cases_tbs1000, resets_tbs1000),
    'tektronix_tbs1000c': _with_resets(cases_tbs1000c, resets_tbs1000c),
}
DRIVER_CASES['tektronix_tbs2000b'] = _tbs2000b.driver_cases


# ==== APPEND-ONLY BLOCK, 3 Series MDO (drivers/tektronix_mdo3.py; branch tektronix-mdo3): its own fixtures tektronix_mdo3.json / engine_mdo3.json ======
from drivers import TektronixMDO3  # noqa: E402
from drivers.simulated_mdo3 import make_mdo3_bench  # noqa: E402

COVERAGE['tektronix_mdo3'] = {
    'TektronixMDO3': dict(
        covered=['connect', 'installed_options', 'opc', 'check_errors', 'cleanup', 'set_verified', 'default_setup', 'select_only', 'bandwidth', 'channel',
                 'acquire_mode', 'timebase', 'delay', 'trigger_line', 'trigger_edge', 'trigger_counter_on', 'trigger_frequency', 'measure_setup',
                 'gating_off', 'stats_reset', 'stat_mean', 'stat_stddev', 'meas_value', 'mean_of', 'delay_stddev', 'fetch', 'edge_time', 'rf_cmd',
                 'rf_setup', 'rf_rbw', 'rf_trace', 'afg_set', 'afg_off', 'dvm', 'dvm_value', 'run_diagnostics', 'run_spc', 'reset_to_defaults'],
        no_command=[]),
}
LINT_FILES.append('tektronix_mdo3')
ENGINES += ('mdo3',)


def cases_mdo3(c):
    bench, t = make_mdo3_bench('34-1000')
    m = c.inst(TektronixMDO3, t['scope'], opened=False, label='MDO3')
    c.run('TektronixMDO3.connect', m.connect)
    c.run('TektronixMDO3.installed_options', m.installed_options)
    c.run('TektronixMDO3.opc[no timeout]', m.opc)
    c.run('TektronixMDO3.opc[timeout]', m.opc, 60)
    c.run('TektronixMDO3.check_errors[ok]', m.check_errors, 'ctx')
    c.run('TektronixMDO3.default_setup', m.default_setup)
    c.run('TektronixMDO3.select_only', m.select_only, 2)
    c.run('TektronixMDO3.channel[all]', m.channel, 1, term='1M', bw='TWEnty', vscale=0.5, offset=0.1, position=0.0)
    c.run('TektronixMDO3.channel[50 ohm minimal]', m.channel, 2, term='50', position=None)
    c.run('TektronixMDO3.channel[defaults]', m.channel, 3)
    c.run('TektronixMDO3.bandwidth[250 MHz]', m.bandwidth, 1, 'TWOFifty')
    c.run('TektronixMDO3.bandwidth[full, model bandwidth unknown]', m.bandwidth, 1, 'FULl')
    m.full_bw_hz = 1e9
    c.run('TektronixMDO3.bandwidth[full, 1 GHz model]', m.bandwidth, 1, 'FULl')
    c.run('TektronixMDO3.set_verified', m.set_verified, 'ch.scale.set', 'ch.scale.get', 0.2, ch='1')
    c.run('TektronixMDO3.acquire_mode[average]', m.acquire_mode, 'AVErage', 32)
    c.run('TektronixMDO3.acquire_mode[sample]', m.acquire_mode, 'SAMple')
    c.run('TektronixMDO3.timebase', m.timebase, 1e-3)
    c.run('TektronixMDO3.delay', m.delay, 0.08)
    c.run('TektronixMDO3.trigger_line', m.trigger_line)
    c.run('TektronixMDO3.trigger_edge[level]', m.trigger_edge, 'CH1', level=0.0, slope='RISe', mode='NORMal')
    c.run('TektronixMDO3.trigger_edge[defaults]', m.trigger_edge, 'CH2')
    c.run('TektronixMDO3.trigger_edge[level on LINE]', m.trigger_edge, 'LINE', level=0.5)
    c.run('TektronixMDO3.trigger_counter_on', m.trigger_counter_on)
    c.run('TektronixMDO3.trigger_frequency[not available]', m.trigger_frequency, 1.0)
    bench.gen.update(on=True, f=1e3)
    c.run('TektronixMDO3.trigger_frequency', m.trigger_frequency, 1.0)
    bench.gen.update(on=False)
    c.run('TektronixMDO3.measure_setup[single]', m.measure_setup, 'MEAN', 'CH1')
    c.run('TektronixMDO3.measure_setup[slot 2]', m.measure_setup, 'RMS', 'CH1', slot=2)
    c.run('TektronixMDO3.measure_setup[source2 refused]', m.measure_setup, 'DELay', 'CH1', source2='CH2')
    c.run('TektronixMDO3.gating_off', m.gating_off)
    c.run('TektronixMDO3.stats_reset[weighting]', m.stats_reset, 16)
    c.run('TektronixMDO3.stats_reset[none]', m.stats_reset)
    c.run('TektronixMDO3.stat_mean', m.stat_mean)
    c.run('TektronixMDO3.stat_stddev', m.stat_stddev, 2)
    c.run('TektronixMDO3.meas_value', m.meas_value)
    c.run('TektronixMDO3.mean_of', m.mean_of, 1, 8, 1.0)
    c.run('TektronixMDO3.delay_stddev', m.delay_stddev, 1, 50, 2.0)
    c.run('TektronixMDO3.fetch', m.fetch, 'CH1')
    c.run('TektronixMDO3.edge_time', m.edge_time, 1)
    c.run('TektronixMDO3.rf_cmd[on]', m.rf_cmd, 'on')
    c.run('TektronixMDO3.rf_cmd[center]', m.rf_cmd, 'center', v=1e9)
    c.run('TektronixMDO3.rf_setup[full]', m.rf_setup, center=1e9, span=1e6, start=0.9e9, stop=1.1e9, rbw=1e3, ref_level=-15, averages=4, detection='AVErage')
    c.run('TektronixMDO3.rf_setup[minimal]', m.rf_setup, center=2e9, span=1e6, average_trace=False)
    c.run('TektronixMDO3.rf_rbw', m.rf_rbw)
    c.run('TektronixMDO3.rf_trace[average]', m.rf_trace)
    c.run('TektronixMDO3.rf_trace[normal]', m.rf_trace, average=False)
    c.run('TektronixMDO3.afg_set[all]', m.afg_set, 'SINE', 1000.0, 1.0, 0.0)
    c.run('TektronixMDO3.afg_set[dc]', m.afg_set, 'DC', offset=1.0)
    c.run('TektronixMDO3.afg_off', m.afg_off)
    c.run('TektronixMDO3.dvm[dc]', m.dvm, 'DC', 1)
    c.run('TektronixMDO3.dvm[acrms ch2]', m.dvm, 'ACRMS', 2)
    c.run('TektronixMDO3.dvm_value', m.dvm_value, 1.0)
    c.run('TektronixMDO3.run_diagnostics', m.run_diagnostics)
    c.run('TektronixMDO3.run_spc', m.run_spc)
    c.run('TektronixMDO3.cleanup', m.cleanup)
    # a 2-channel MDO32: CH3 / CH4 are never addressed
    b2, t2 = make_mdo3_bench('32-200')
    m2 = c.inst(TektronixMDO3, t2['scope'], opened=False, label='MDO3')
    c.run('TektronixMDO3.connect[MDO32]', m2.connect)
    c.run('TektronixMDO3.select_only[MDO32]', m2.select_only, 1)
    # branches the simulator cannot reach
    err = c.inst(TektronixMDO3, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='MDO3')
    c.run('TektronixMDO3.check_errors[command error]', err.check_errors, 'setup')
    noopt = c.inst(TektronixMDO3, Scripted([(r'^\*OPT\?', TransportError('timeout'))]), label='MDO3')
    c.run('TektronixMDO3.installed_options[query fails]', noopt.installed_options)
    bare = c.inst(TektronixMDO3, Scripted([(r'^\*OPT\?', 'SA:Spectrum analyzer maximum input frequency,AFG:Arbitrary Function Generator,3-DVM:Digital Voltmeter')]), label='MDO3')
    c.run('TektronixMDO3.installed_options[bare SA code]', bare.installed_options)
    flat = c.inst(TektronixMDO3, Scripted([(r'^CH1:SCAle\?', '0.9')]), label='MDO3')
    c.run('TektronixMDO3.set_verified[mismatch]', flat.set_verified, 'ch.scale.set', 'ch.scale.get', 0.2, ch='1')
    bw = c.inst(TektronixMDO3, Scripted([(r'^CH1:BANdwidth\?', '2.5000E+08')]), label='MDO3')
    bw.full_bw_hz = 1e9
    c.run('TektronixMDO3.bandwidth[full reads back 250 MHz]', bw.bandwidth, 1, 'FULl')
    bw20 = c.inst(TektronixMDO3, Scripted([(r'^CH1:BANdwidth\?', '2.5000E+08')]), label='MDO3')
    c.run('TektronixMDO3.bandwidth[20 MHz mismatch]', bw20.bandwidth, 1, 'TWEnty')
    noedge = c.inst(TektronixMDO3, Scripted([(r'^WFMOutpre:NR_Pt\?', '3'), (r'^WFMOutpre', '0.0'), (r'^CURVe\?', '1,1,1')]), label='MDO3')
    c.run('TektronixMDO3.edge_time[no edge]', noedge.edge_time, 1)
    bad = c.inst(TektronixMDO3, Scripted([(r'^MEASUrement:MEAS1:MEAN\?', '9.91E+37')]), label='MDO3')
    c.run('TektronixMDO3.stat_mean[invalid]', bad.stat_mean)
    off = c.inst(TektronixMDO3, Scripted([(r'^DISplay:TRIGFrequency\?', '0')]), label='MDO3')
    c.run('TektronixMDO3.trigger_counter_on[stays off]', off.trigger_counter_on)
    slow = c.inst(TektronixMDO3, Scripted([(r'^DIAg:RESUlt:FLAg\?', ['IN PROGRESS', 'IN PROGRESS', 'FAIL']), (r'^DIAg:RESUlt:LOG\?', '"FAIL--ACQ"')]), label='MDO3')
    c.run('TektronixMDO3.run_diagnostics[polls and fails]', slow.run_diagnostics, 900)
    spc = c.inst(TektronixMDO3, Scripted([(r'^CALibrate:INTERNal:STATus\?', ['RUNNING', 'FAIL']), (r'^CALibrate:RESults:SPC\?', 'FAIL')]), label='MDO3')
    c.run('TektronixMDO3.run_spc[polls and fails]', spc.run_spc, 1200)
    afg = c.inst(TektronixMDO3, Scripted([(r'^AFG:OUTPut:LOAd:IMPEDance\?', 'HIGHZ')]), label='MDO3')
    c.run('TektronixMDO3.afg_set[load not 50 ohm]', afg.afg_set, 'SINE', 1000.0, 1.0, 0.0)
    noafg = c.inst(TektronixMDO3, Scripted([(r'^\*OPT\?', 'DVM:Digital Voltmeter')]), label='MDO3')
    c.run('TektronixMDO3.afg_off[no AFG option: nothing sent]', noafg.afg_off)
    wrong = c.inst(TektronixMDO3, Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), opened=False, label='MDO3')
    c.run('TektronixMDO3.connect[wrong model]', wrong.connect)
    old = c.inst(TektronixMDO3, Scripted([(r'\*IDN\?', 'TEKTRONIX,MDO3104,C012345,CF:91.1CT FV:v1.30')]), opened=False, label='MDO3')
    c.run('TektronixMDO3.connect[MDO3000 series refused]', old.connect)


def resets_mdo3(c):
    bench, t = make_mdo3_bench('34-1000')
    m = c.inst(TektronixMDO3, t['scope'], opened=False, label='MDO3')
    c.quiet(m.connect)
    c.run('TektronixMDO3.reset_to_defaults', m.reset_to_defaults)
    bad = c.inst(TektronixMDO3, Scripted([(r'^\*OPC\?', '1'), (r'^\*OPT\?', 'NONE'), (r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='MDO3')
    c.run('TektronixMDO3.reset_to_defaults[event status not clean]', bad.reset_to_defaults)


DRIVER_CASES['tektronix_mdo3'] = _with_resets(cases_mdo3, resets_mdo3)
# ==== end of the 3 Series MDO block ===========================================================================================================


def capture_driver_transcripts():
    """{driver fixture name: [entry, ...]} - entries are JSON-serialisable and identical on every run."""
    out = {}
    with pinned():
        for name, fn in DRIVER_CASES.items():
            case = Case(name)
            fn(case)
            out[name] = case.entries
    return out


# =====================================================================================================================================
# engines (one short simulated run each), executed in a subprocess because tkinter is stubbed there
# =====================================================================================================================================
def _engine_main(names):
    """Runs inside the subprocess: returns {engine: [entry]}."""
    sys.path.insert(0, str(ROOT / 'tests'))
    import importlib.util
    spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
    stub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stub)
    stub.install()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'Procedures'))
    from tests import golden_engines          # noqa: E402  (imports engine modules, which need the stub)
    out = {}
    with pinned():
        for name in names:
            out[name] = golden_engines.RUNS[name]()
    return out


def capture_engine_transcripts(names=ENGINES):
    import subprocess
    code = ('import json,sys; sys.path.insert(0, %r); from tests import golden_capture as g; '
            'sys.stdout.write("\\n@@GOLDEN@@" + json.dumps(g._engine_main(%r)))' % (str(ROOT), list(names)))
    proc = subprocess.run([sys.executable, '-c', code], cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or '@@GOLDEN@@' not in proc.stdout:
        raise RuntimeError(f'engine capture failed (exit {proc.returncode}):\n{proc.stderr[-3000:]}\n{proc.stdout[-1000:]}')
    return json.loads(proc.stdout.split('@@GOLDEN@@', 1)[1])


# =====================================================================================================================================
# f-string lint baseline
# =====================================================================================================================================
_LINT = {
    'write_f': re.compile(r'self\.write\(\s*f[\'"]'),
    'query_f': re.compile(r'self\.query\(\s*f[\'"]'),
    'query_retry_f': re.compile(r'self\.query_retry\(\s*f[\'"]'),
    # commands that reach the wire through a private helper (the f-string is the command text) ...
    'helper_f': re.compile(r'self\.(?:_set_text|_set_number|_text|_number|_num|_set_text_verified|_set_and_check|vbs_set_number|vbs_set_text|'
                           r'set_verified|set_enum_verified)\(\s*f[\'"]'),
    # ... through str.format / concatenation at the call
    'format_f': re.compile(r'self\.(?:write|query)\([^()\n]*(?:\[[^\]\n]*\])?\.format\('),
    'concat_f': re.compile(r'self\.(?:write|query)\([^\n]*[\'"]\s*\+\s*\w'),
}


def count_fstring_commands():
    """{driver file: {pattern: count}} - occurrences of a command built at the call site: an f-string literal passed straight to
    write / query / query_retry (write_f, query_f, query_retry_f), to a helper that sends it (helper_f), or built with .format / + (format_f,
    concat_f). The first two are the specified ratchet; the others keep a conversion from moving commands into helpers unnoticed."""
    out = {}
    for stem in LINT_FILES:
        text = (ROOT / 'drivers' / f'{stem}.py').read_text(encoding='utf-8')
        out[stem] = {k: len(rx.findall(text)) for k, rx in _LINT.items()}
    return out


# =====================================================================================================================================
# fixtures
# =====================================================================================================================================
def dumps(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def fixture_text(name, entries):
    return dumps(dict(schema=SCHEMA, name=name, entries=entries))


def capture_all():
    """Every fixture as {file name: text}."""
    files = {}
    for name, entries in capture_driver_transcripts().items():
        files[f'{name}.json'] = fixture_text(name, entries)
    for name, entries in capture_engine_transcripts().items():
        files[f'engine_{name}.json'] = fixture_text('engine_' + name, entries)
    files['fstring_lint_baseline.json'] = dumps(dict(schema=SCHEMA, counts=count_fstring_commands()))
    return files


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--update' not in argv:
        print(__doc__)
        print('Nothing written. Re-run with --update to rewrite tests/golden/*.json (review the git diff before committing).')
        return 0
    files = capture_all()
    GOLDEN.mkdir(exist_ok=True)
    for stale in GOLDEN.glob('*.json'):
        if stale.name not in files:
            stale.unlink()
    for fname, text in files.items():
        (GOLDEN / fname).write_text(text, encoding='utf-8')
    print(f'wrote {len(files)} fixtures to {GOLDEN}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
