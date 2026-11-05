"""Bench session for the Keysight 53210A / 53220A / 53230A counter driver (NOTES.md 'Bench-first driver workflow').  Run it on the bench PC BEFORE the procedure:

    python -m drivers.k53220a_bench --address USB0::0x0957::0x1807::MY12345678::INSTR          stage 1: read-only queries; nothing is changed
    python -m drivers.k53220a_bench --address GPIB0::3::INSTR --settings                       + stage 2: every configuration the procedure uses (asks before writes)
    python -m drivers.k53220a_bench --address ... --settings --ext-ref                         + the external 10 MHz reference test (10 MHz on Ext Ref In)
    python -m drivers.k53220a_bench --address ... --settings --signal                          + stage 3: 100 readings of a 10 MHz signal on Channel 1
    python -m drivers.k53220a_bench --model 53230A ...                                         the 53230A (or 53210A) driver
    python -m drivers.k53220a_bench --sim [--settings --ext-ref --signal --yes]                the same against the simulator (no hardware)

Why: the counter driver was written from the Programmer's Reference before the bench-first rule; its reply formats are assumptions and the simulator replays
those assumptions.  The first bench run of the procedure stopped on one (2026-11-05: CONF? answers without the channel list).  This script sends every
configuration the procedure sends, one at a time, and records the counter's exact replies, so every other wrong assumption shows up here instead of in a run.

Stage 1 (always): *IDN?, *OPT?, SYST:ERR?, the reference oscillator, every input / gate / trigger / statistics query.  No write except the device clear
         and *CLS of connect (they change no setting).
Stage 2 (--settings): *RST, then configure_point for each function the procedure uses on this model and its options (frequency Ch 1 / Ch 2 / microwave, single
         period, pulse width, time interval, burst): each setting set, read back and compared by the driver; CONF? recorded after each; the error queue read.
         With nothing connected the statistics must refuse the 9.91E37 'Not a Number' reply.  The internal time base is selected; --ext-ref also selects the
         external 10 MHz and runs its check.  The reference oscillator settings (non-volatile) are put back as found at the end.
Stage 3 (--signal): 10 MHz on Channel 1 (house standard or a generator, 50 ohm, about 0 dBm): 100 readings, Mean / Std Dev / count.
--selftest: *TST? (the counter then does a Factory Reset).
A failed step is recorded with the counter's reply and the session goes on to the next step.  Each write asks first: y = send it, a = send every write of
this session without asking (the counter has no output to protect), anything else stops.  Record: k53220a_bench_<time>.txt (screen + the command log).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .base import InstrumentError
from .keysight_53220a import Keysight53210A, Keysight53220A, Keysight53230A
from .transport import CommandLog, Transport

MODELS = {'53220A': Keysight53220A, '53230A': Keysight53230A, '53210A': Keysight53210A}
# stage 1 read-only queries: (registry key, channel or None)
READ_ONLY = [('opt.query', None), ('err.query', None), ('rosc.src.query', None), ('rosc.auto.query', None), ('rosc.ext.freq.query', None),
             ('freq.mode.query', None), ('gate.src.query', None), ('gate.time.query', None), ('samp.count.query', None), ('trig.count.query', None),
             ('trig.delay.query', None), ('trig.source.query', None), ('calc.state.query', None), ('calc.aver.state.query', None)]
INPUT_QUERIES = ('inp.coup.query', 'inp.imp.query', 'inp.prob.query', 'inp.rang.query', 'inp.filt.query', 'inp.nrej.query', 'inp.lev.auto.query', 'inp.lev.query',
                 'inp.slop.query')


class Stop(BaseException):
    """The person declined a write.  A BaseException, so no driver `except Exception` (the reset steps catch those) can swallow it and carry on."""


class AskBeforeWrite(Transport):
    """Wraps a transport: queries pass, every write waits for 'y' (or 'a' = all from now on); anything else stops."""

    def __init__(self, inner, answer, auto=False):
        self.inner, self.answer, self.auto = inner, answer, auto
        self.allow_unasked = False                 # True while connect (*CLS) and cleanup (reference restore) run

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def open(self): self.inner.open()
    def close(self): self.inner.close()
    def set_timeout(self, s): self.inner.set_timeout(s)
    def clear(self): self.inner.clear()
    def go_local(self): self.inner.go_local()
    def read(self): return self.inner.read()
    def query(self, text): return self.inner.query(text)

    def write(self, text):
        if not (self.auto or self.allow_unasked):
            a = self.answer(f'   send {text!r} to the counter? [y = yes, a = yes to all, n = stop] ').strip().lower()
            if a == 'a':
                self.auto = True
            elif a != 'y':
                raise Stop(f'not sent: {text}')
        self.inner.write(text)


def points_for(ctr):
    """The configurations the procedure sends on this model with the options the counter reports (one per function / channel)."""
    o = ctr.options or {}
    pts = [('frequency Ch 1, 10 MHz, gate 10 ms (Test 1 / 2a)', dict(func='FREQ', channel=1, nominal=10e6, gate_s=0.01))]
    if ctr.TWO_CH:
        pts += [('frequency Ch 2, 115 MHz, gate 10 ms (Test 2b)', dict(func='FREQ', channel=2, nominal=115e6, gate_s=0.01)),
                ('single period Ch 1 (Test 3)', dict(func='SPER', channel=1, nominal=1e-6)),
                ('pulse width Ch 1 (Test 4a)', dict(func='PWID', channel=1, nominal=5e-9)),
                ('time interval Ch 1 to Ch 2 (Test 5)', dict(func='TINT', channel=12, nominal=49.9e-9))]
    if o.get('ch3'):
        pts.append(('frequency microwave channel, 5.88 GHz (Test 6a)', dict(func='FREQ', channel=3, nominal=5.88e9, gate_s=0.01)))
        if o.get('pulse') and ctr.SHORT == '53230A':
            pts.append(('burst frequency microwave channel, 6 GHz narrow (Test 7a)', dict(func='BURST', channel=3, nominal=6e9, narrow=True, burst_db=-12)))
    return pts


def run(ctr, args, out, connect_signal=None):
    rows = []

    def step(name, fn):
        try:
            res = fn()
            rows.append((name, 'PASS', '' if res is None else str(res)))
        except Stop:
            raise
        except Exception as exc:
            rows.append((name, 'FAIL', f'{type(exc).__name__}: {exc}'))
            try:                                              # the error queue as it stands, so the next step starts clean
                ctr.check_errors(name)
            except Stop:
                raise
            except Exception as qexc:
                rows[-1] = (name, 'FAIL', f'{rows[-1][2]} | then {qexc}')
        out(f'{rows[-1][1]}  {name}  {rows[-1][2]}')

    reg = ctr._registry()
    out('--- stage 1: read-only queries')
    out(f'options parsed from *OPT?: {ctr.options}')
    for key, ch in READ_ONLY:
        step(f'query {reg[key].template}', lambda k=key: ctr.query_retry(k, attempts=1).strip())
    for ch in ((1, 2) if ctr.TWO_CH else (1,)):
        for key in INPUT_QUERIES:
            step(f'query {reg[key].template.format(ch=ch)}', lambda k=key, c=ch: ctr.ask(k, ch=c).strip())
    step('error queue after the queries', lambda: ctr.check_errors('stage 1'))
    if args.settings:
        out('--- stage 2: the configurations the procedure sends (each write asks first)')
        step('reset_to_defaults (*RST, *CLS, *OPC?, error queue)', lambda: _reset_ok(ctr.reset_to_defaults().text()))
        step('time base INTERNAL (set, read back)', lambda: (ctr.set_reference('INT'), ctr.read_reference())[1])
        if args.ext_ref:
            step('time base EXTERNAL 10 MHz + SENS:ROSC:EXT:CHEC ONCE (10 MHz on Ext Ref In)', lambda: (ctr.set_reference('EXT'), ctr.read_reference())[1])
        for name, p in points_for(ctr):
            step(f'configure {name}', lambda q=p: ctr.configure_point(dict(q)))
            step(f'   CONF? after {name}', lambda: ctr.query_retry('conf.query', attempts=1).strip())
        step('statistics with no signal connected: 9.91E37 must be refused', lambda: _expect_refused(lambda: (ctr.configure_point(
            dict(func='FREQ', channel=1, nominal=10e6, gate_s=0.01)), ctr.measure_stats(10))))
        if args.selftest:
            step('*TST? self-test (then Factory Reset)', ctr.self_test)
    if args.signal:
        out('--- stage 3: 10 MHz on Channel 1')
        if not (args.yes or ctr.t.answer('   connect 10 MHz (about 0 dBm, 50 ohm) to Channel 1, then press Enter (n = skip): ').strip().lower() != 'n'):
            out('stage 3 skipped')
        else:
            if connect_signal:
                connect_signal()                              # the simulator: the operator connects 10 MHz now
            step('configure frequency Ch 1, 10 MHz, gate 10 ms', lambda: ctr.configure_point(dict(func='FREQ', channel=1, nominal=10e6, gate_s=0.01)))
            step('100 readings: Mean / Std Dev / count', ctr.measure_stats)
            step('error queue after the readings', lambda: ctr.check_errors('stage 3'))
    return rows


def _reset_ok(text):
    if 'FAILED' in text.upper():
        raise InstrumentError(text)
    return text


def _expect_refused(fn):
    try:
        res = fn()
    except InstrumentError as exc:
        return f'refused as expected: {exc}'
    raise InstrumentError(f'readings with nothing connected were accepted: {res}')


def main(argv=None, answer=input, transport=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--address', help='VISA resource of the counter (USB0::..., TCPIP0::..., GPIB0::n::INSTR)')
    ap.add_argument('--model', default='53220A', choices=sorted(MODELS), help='counter model (default 53220A)')
    ap.add_argument('--settings', action='store_true', help='stage 2: the configurations the procedure sends (asks before writes)')
    ap.add_argument('--ext-ref', action='store_true', help='with --settings: also select the external 10 MHz reference (connect it to Ext Ref In)')
    ap.add_argument('--signal', action='store_true', help='stage 3: 100 readings of 10 MHz on Channel 1')
    ap.add_argument('--selftest', action='store_true', help='with --settings: also run *TST? (the counter then does a Factory Reset)')
    ap.add_argument('--sim', action='store_true', help='use the simulator instead of the instrument')
    ap.add_argument('--yes', action='store_true', help='answer every prompt yes (only with --sim)')
    ap.add_argument('--out', default='.', help='folder for the record file')
    args = ap.parse_args(argv)
    if args.yes and not args.sim:
        ap.error('--yes is only allowed with --sim: on the bench the writes are confirmed by hand (a = yes to all)')
    if not args.sim and not args.address and transport is None:
        ap.error('--address is required (or --sim)')
    connect_signal = None
    if transport is not None:
        inner = transport
    elif args.sim:
        from .simulated_53220a import make_53220a_bench
        bench, _rf, inner = make_53220a_bench(args.model)
        connect_signal = lambda: setattr(bench, 'external_signal', dict(kind='CW', f=10e6, level_dbm=0.0))
    else:
        from . import open_visa
        inner = open_visa(args.address, timeout=20)
    t = AskBeforeWrite(inner, answer, auto=args.yes)
    log = CommandLog(echo=True)
    ctr = MODELS[args.model](t, log, label=args.model)
    lines = []

    def out(text):
        print(text)
        lines.append(text)

    rows = []
    try:
        t.allow_unasked = True                      # connect: device clear and *CLS only (no setting changes)
        ctr.connect()
        t.allow_unasked = False
        out(f'*IDN? {ctr.idn}  ({"simulator" if args.sim else args.address})')
        out(f'reference oscillator found: {ctr.saved_ref}')
        rows = run(ctr, args, out, connect_signal)
    except Stop as exc:
        out(f'STOPPED: {exc}')
    except Exception as exc:
        out(f'FAILED: {type(exc).__name__}: {exc}')
    finally:
        if ctr._open:
            t.allow_unasked = True                  # the reference oscillator back as found, then local
            ctr.cleanup()
            out(f'cleanup: reference oscillator now {_safe(ctr.read_reference)} (found {ctr.saved_ref})')
            ctr.close()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = Path(args.out) / f'k{args.model.lower()}_bench_{stamp}{"_SIMULATED" if args.sim else ""}.txt'
    passed = sum(1 for _n, s, _d in rows if s == 'PASS')
    summary = [f'--- summary: {passed} passed, {len(rows) - passed} failed'] + [f'FAIL  {n}  {d}' for n, s, d in rows if s != 'PASS']
    for s in summary:
        print(s)
    text = '\n'.join([f'Keysight {args.model} bench record {stamp} {"SIMULATED - not evidence" if args.sim else args.address}', ''] + lines + [''] + summary
                     + ['', '--- command log (every command and exact reply)'] + [str(e) for e in log.lines()])
    path.write_text(text + '\n', encoding='utf-8')
    print(f'\nrecord written: {path}')
    return 0 if rows and passed == len(rows) else 1


def _safe(fn):
    try:
        return fn()
    except Exception as exc:
        return f'(not read: {exc})'


if __name__ == '__main__':
    sys.exit(main())
