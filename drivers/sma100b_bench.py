"""First bench session for the R&S SMA100B driver over GPIB (NOTES.md 'Bench-first driver workflow').  Run it on the bench PC:

    python -m drivers.sma100b_bench                               read-only queries at GPIB0::28::INSTR (factory address, manual p. 788); nothing is changed
    python -m drivers.sma100b_bench --address GPIB0::7::INSTR     another address
    python -m drivers.sma100b_bench --settings                    + settings with RF OFF (*CLS, *RST, CW, 1 GHz, -30 dBm ...): every write asks for a typed 'y'
    python -m drivers.sma100b_bench --settings --rf               + RF ON at -30 dBm for a moment, then RF OFF (typed 'RF ON' first)
    python -m drivers.sma100b_bench --sim [--settings --rf --yes] the same against the simulator (no hardware; --yes answers every prompt)

Stage 1 (always) sends only queries: *IDN?, *OPT?, SYST:ERR?, OUTP?, FREQ?, POW?, POW:LIM?, ROSC:SOUR?, the mode / unit / modulation / offset queries.
Stage 2 (--settings) and 3 (--rf) go through the driver; a write is sent only after the person types y for THAT command (n stops the session; RF is then
switched off). Never sent: the level limit, the GPIB address, calibration / protection / memory commands (the driver has none). RF is switched OFF and
confirmed at the end whatever happened.  Every command and exact reply goes to the screen and to sma100b_bench_<time>.txt (the record for setting
verified=True in drivers/rs_sma100b.py, together with a driver_verify pass).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .base import InstrumentError
from .rs_sma100b import RSSMA100B
from .transport import CommandLog, Transport

READ_ONLY = ('idn.query', 'opt.query', 'err.query', 'outp.query', 'freq.query', 'pow.query', 'pow.limit.query', 'rosc.query', 'freq.mode.query',
             'pow.mode.query', 'unit.query', 'mod.query', 'freq.offs.query', 'freq.mult.query', 'pow.offs.query')


class Stop(Exception):
    pass


class AskBeforeWrite(Transport):
    """Wraps a transport: queries pass, every write waits for a typed 'y' (n / anything else stops). Answers come from `answer(prompt) -> str`."""

    def __init__(self, inner, answer, auto=False):
        self.inner, self.answer, self.auto = inner, answer, auto
        self.allow_unasked = False                 # True only while cleanup switches RF off (always allowed)

    def __getattr__(self, name):                   # address, name ... of the real transport (gpib_address.retarget writes them through)
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
            if self.answer(f'   send {text!r} to the SMA100B? [y/n] ').strip().lower() != 'y':
                raise Stop(f'not sent: {text}')
        self.inner.write(text)


def run(gen, args, out):
    rows = []

    def step(name, fn):
        try:
            res = fn()
            rows.append((name, 'PASS', '' if res is None else str(res)))
        except Stop:
            raise
        except Exception as exc:
            rows.append((name, 'FAIL', f'{type(exc).__name__}: {exc}'))
        out(f'{rows[-1][1]}  {name}  {rows[-1][2]}')

    out('--- stage 1: read-only queries')
    for key in READ_ONLY:
        step(f'query {gen._registry()[key].template}', lambda k=key: gen.query_retry(k, attempts=1).strip())
    if args.settings:
        out('--- stage 2: settings with RF OFF (each write asks first)')
        step('*CLS + RF OFF confirmed', lambda: (gen.send('status.clear'), gen.output(False))[1])
        step('reset_to_defaults (*RST, *CLS, *OPC?, queue, RF OFF, CW set-up)', lambda: gen.reset_to_defaults().text())
        step('cw_setup (dBm, CW, modulation off, no offsets)', gen.cw_setup)
        step('set 1 GHz, -30 dBm (RF stays OFF)', lambda: gen.setup(1e9, -30.0))
        step('read back (Hz, dBm, RF on?)', gen.read_setting)
        step('out-of-range frequency 1 THz is refused (error queue)', lambda: _expect_refused(lambda: gen.set_frequency(1e12)))
        step('error queue empty', lambda: gen.check_errors('bench'))
        if args.selftest:
            step('*TST? self-test (RF OFF)', gen.self_test)
    if args.rf:
        if not args.settings:
            raise SystemExit('--rf needs --settings')
        out('--- stage 3: RF ON at -30 dBm, 1 GHz')
        if not (args.yes or gen.t.answer('   type RF ON to switch the RF output on at -30 dBm (load connected?): ').strip().upper() == 'RF ON'):
            raise Stop('RF ON not confirmed')
        step('RF ON confirmed (OUTP ON, OUTP?)', lambda: gen.output(True))
        time.sleep(1.0)
        step('read back with RF on', gen.read_setting)
        step('RF OFF confirmed (OUTP OFF, OUTP?)', lambda: gen.output(False))
    return rows


def _expect_refused(fn):
    try:
        fn()
    except InstrumentError as exc:
        return f'refused as expected: {exc}'
    raise InstrumentError('a 1 THz frequency was accepted')


def main(argv=None, answer=input):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--address', default='GPIB0::28::INSTR', help='VISA address (default GPIB0::28::INSTR, the factory address)')
    ap.add_argument('--settings', action='store_true', help='stage 2: settings with RF OFF (asks before every write)')
    ap.add_argument('--selftest', action='store_true', help='with --settings: also run *TST? (can take a while)')
    ap.add_argument('--rf', action='store_true', help='stage 3: RF ON at -30 dBm, then OFF (asks first)')
    ap.add_argument('--sim', action='store_true', help='use the simulator instead of the GPIB bus')
    ap.add_argument('--yes', action='store_true', help='answer every prompt yes (only with --sim)')
    ap.add_argument('--out', default='.', help='folder for the record file')
    args = ap.parse_args(argv)
    if args.yes and not args.sim:
        ap.error('--yes is only allowed with --sim: on the bench every write is confirmed by hand')
    if args.sim:
        from .simulated_sma100b import SimSMA100BTransport
        inner = SimSMA100BTransport()
    else:
        from . import open_visa
        inner = open_visa(args.address)
    t = AskBeforeWrite(inner, answer, auto=args.yes)
    log = CommandLog(echo=True)
    gen = RSSMA100B(t, log, label='SMA100B')
    lines = []

    def out(text):
        print(text)
        lines.append(text)

    rows = []
    try:
        gen.open(verify_model=True)
        out(f'*IDN? {gen.idn}  ({"simulator" if args.sim else args.address})')
        rows = run(gen, args, out)
    except Stop as exc:
        out(f'STOPPED: {exc}')
    except Exception as exc:
        out(f'FAILED: {type(exc).__name__}: {exc}')
    finally:
        if gen._open:
            if args.settings or args.rf:
                t.allow_unasked = True                 # RF OFF at the end is always sent
                gen.cleanup()
                out(f'cleanup: RF OFF {"confirmed" if gen.output_off_confirmed else "NOT CONFIRMED - check the front panel"}')
            else:
                try:
                    t.go_local()
                except Exception:
                    pass
            gen.close()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = Path(args.out) / f'sma100b_bench_{stamp}{"_SIMULATED" if args.sim else ""}.txt'
    text = '\n'.join([f'R&S SMA100B bench record {stamp} {"SIMULATED - not evidence" if args.sim else args.address}', ''] + lines
                     + ['', '--- command log (every command and exact reply)'] + [str(e) for e in log.lines()])
    path.write_text(text + '\n', encoding='utf-8')
    print(f'\nrecord written: {path}')
    return 0 if rows and all(s == 'PASS' for _n, s, _d in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
