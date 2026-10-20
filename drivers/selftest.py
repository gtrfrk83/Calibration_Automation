"""Driver self-test.  Safe checks only: identify, standby, set/read-back with the output left in STANDBY.

  python -m drivers.selftest --sim
  python -m drivers.selftest --fluke ASRL9::INSTR --baud 9600 --scope USB0::0x05FF::0x1023::SERIAL::0::INSTR
Run it from the suite folder (the one containing ui_theme.py).  Prints every command sent.
"""
import argparse
import sys

from . import CommandLog, Fluke5560A, WaveSurfer4104HD, open_visa
from .fluke_5560a import SERIAL_DEFAULT
from .simulated import make_bench


def run(fluke, scope):
    report = []

    def check(name, fn):
        try:
            result = fn()
            report.append((name, True, '' if result is None else str(result)))
        except Exception as exc:
            report.append((name, False, f'{type(exc).__name__}: {exc}'))

    if fluke is not None:
        check('5560A  identify', lambda: fluke.idn)
        check('5560A  standby confirmed', fluke.standby)
        check('5560A  SCOPE DCV + 1 MOhm', fluke.select_scope_dcv)
        check('5560A  program 0.006 V (stays in standby)', lambda: fluke.set_dc_volts(0.006))
        check('5560A  output still in standby', lambda: None if not fluke.is_operating() else 1 / 0)
        check('5560A  SCOPE OFF', fluke.scope_off)
    if scope is not None:
        check('Scope  identify', lambda: scope.idn)
        check('Scope  CH1 10 mV/div', lambda: scope.set_vertical_scale(1, 0.01))
        check('Scope  CH1 DC 1 MOhm / 20 MHz', lambda: scope.configure_dc_input(1))
        check('Scope  P1 = Mean of CH1', lambda: scope.configure_p1(1, 'Mean'))
        check('Scope  read P1', lambda: f'{scope.read_p1():.6g} V')
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sim', action='store_true', help='use the built-in simulators')
    ap.add_argument('--fluke', help='5560A VISA address, e.g. ASRL9::INSTR or GPIB0::6::INSTR')
    ap.add_argument('--baud', type=int, default=SERIAL_DEFAULT.baud)
    ap.add_argument('--scope', help='WaveSurfer VISA address (USB0::...)')
    a = ap.parse_args(argv)
    log = CommandLog(echo=True)
    if a.sim:
        _bench, ft, st = make_bench()
    else:
        if not (a.fluke or a.scope):
            ap.error('give --sim, or --fluke and/or --scope')
        ft = open_visa(a.fluke, baud=a.baud, write_termination='\r', read_termination='\r\n') if a.fluke else None
        st = open_visa(a.scope) if a.scope else None
    fluke = Fluke5560A(ft, log).open() if ft else None
    scope = WaveSurfer4104HD(st, log).open() if st else None
    try:
        report = run(fluke, scope)
    finally:
        if fluke: fluke.cleanup(); fluke.close()
        if scope: scope.close()
    print()
    for name, ok, detail in report:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    return 0 if all(ok for _n, ok, _d in report) else 1


if __name__ == '__main__':
    sys.exit(main())
