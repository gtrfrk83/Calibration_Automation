"""'Find instruments' window on a REAL Tk (run by tests/test_instrument_scan_real_tk.py in a subprocess; not a test module).

    python tests/real_tk_find_instruments.py <light|dark>

Drives the window with real events against a FAKE ResourceManager (tests/test_instrument_scan.py): a scan with a 3458A on GPIB1::22, two 34410A that need a
serial, a 34972A on USB, a silent resource, an unknown instrument and a serial port that is listed but not asked; Cancel on a hanging resource; the no-VISA
message; Remember / Forget; the explicit RS-232 check with the simulated 8808A.  Set FIND_SHOTS=<folder> to also save PNG screenshots there.
Everything is written to a throw-away registry."""
import faulthandler
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures')]
THEME = sys.argv[1] if len(sys.argv) > 1 else 'light'
os.environ['CALSUITE_THEME'] = THEME

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

import instrument_scan as S  # noqa: E402
import instrument_scan_ui as U  # noqa: E402
import ui_theme as ui  # noqa: E402
from tests.test_instrument_scan import FakeRM, IDN_3458, IDN_34410, SAMPLES  # noqa: E402

SHOTS = os.environ.get('FIND_SHOTS', '')
faulthandler.dump_traceback_later(int(os.environ.get('FIND_WATCHDOG', '120')), exit=True)      # a hang shows where, instead of blocking the test run


def check(name, cond, detail=''):
    if not cond:
        raise AssertionError(f'{name}: {detail}')
    print(f'CHECK {name} ok')


def pump(root, n=10):
    for _ in range(n):
        root.update()


def pump_until(root, cond, seconds=8):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


def inside(win, widget):
    win.update_idletasks()
    if not widget.winfo_ismapped():
        return False
    x, y, w, h = widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()
    return (win.winfo_rootx() <= x and x + w <= win.winfo_rootx() + win.winfo_width() + 1 and
            win.winfo_rooty() <= y and y + h <= win.winfo_rooty() + win.winfo_height() + 1)


def shot(win, name):
    if not SHOTS:
        return
    from PIL import ImageGrab
    win.update_idletasks()
    win.update()
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ['DISPLAY']).save(Path(SHOTS) / f'find_instruments_{name}_{THEME}.png')


def bench():
    return FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458),
                   'GPIB1::4::INSTR': dict(replies={'*IDN?': SAMPLES['5522A']}),
                   'GPIB1::23::INSTR': dict(replies=IDN_34410('MY54321001')),
                   'USB0::0x2A8D::0x0101::MY54321002::INSTR': dict(replies=IDN_34410('MY54321002')),
                   'USB0::0x0957::0x2007::MY49001234::INSTR': dict(replies={'*IDN?': SAMPLES['34972A'].replace('MY00000008', 'MY49001234')}),
                   'GPIB1::9::INSTR': dict(replies={}),
                   'USB0::0x1AB1::0x04CE::DS1ZA1::INSTR': dict(replies={'*IDN?': 'RIGOL TECHNOLOGIES,DS1054Z,DS1ZA1,00.04.04'})},
                  listed=['GPIB1::INTFC', 'GPIB1::22::INSTR', 'GPIB1::4::INSTR', 'GPIB1::23::INSTR', 'GPIB1::9::INSTR',
                          'USB0::0x2A8D::0x0101::MY54321002::INSTR', 'USB0::0x0957::0x2007::MY49001234::INSTR', 'USB0::0x1AB1::0x04CE::DS1ZA1::INSTR',
                          'ASRL9::INSTR', 'ASRL3::INSTR'])


def make_window(root, rm, mem, **kw):
    sc = lambda probe_all, go_local: S.Scanner(rm_factory=lambda: rm, timeout_ms=40, probe_all_gpib=probe_all, go_local=go_local)  # noqa: E731
    return U.open_find_instruments(root, memory=mem, scanner_factory=sc, serial_ports=lambda: ['ASRL9::INSTR', 'ASRL3::INSTR'], **kw)


def checks_find_instruments():
    tmp = Path(tempfile.mkdtemp())
    mem = S.ResourceMemory(tmp / 'lab_registry.sqlite3', workstation='tech@bench')
    root = tk.Tk()
    ui.apply_theme(root)
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    root.geometry('300x200+0+0')
    rm = bench()
    w = make_window(root, rm, mem)
    win = w.win
    pump(root, 20)
    shot(win, '1_before')
    check('window opens, Scan enabled, Cancel disabled', str(w.btn_scan.cget('state')) == 'normal' and str(w.btn_cancel.cget('state')) == 'disabled')
    check('empty hint is shown before a scan', w.empty.winfo_ismapped())

    w.btn_scan.invoke()
    check('the scan is running in a thread (window answers)', w.job is not None and w.job.thread is not None)
    check('scan finishes', pump_until(root, lambda: w.report is not None))
    pump(root, 10)
    rows = [w.table.item(k, 'values') for k in w.table.get_children()]
    by = {r[0]: r for r in rows}
    check('the 3458A on GPIB1::22 is listed with the model key', by['GPIB1::22::INSTR'][1:3] == ('Keysight 3458A', '3458A'), by.get('GPIB1::22::INSTR'))
    check('the two 34410A show their serials and ask to choose', by['GPIB1::23::INSTR'][3] == 'MY54321001' and 'choose by serial' in by['GPIB1::23::INSTR'][4]
          and by['USB0::0x2A8D::0x0101::MY54321002::INSTR'][3] == 'MY54321002')
    check('an unknown instrument has no model key', by['USB0::0x1AB1::0x04CE::DS1ZA1::INSTR'][2] == '-')
    check('the silent resource says so', by['GPIB1::9::INSTR'][4].startswith('No answer'), by['GPIB1::9::INSTR'])
    check('identified rows come first', rows[0][0] in ('GPIB1::22::INSTR', 'GPIB1::23::INSTR', 'GPIB1::4::INSTR', 'USB0::0x0957::0x2007::MY49001234::INSTR', 'USB0::0x2A8D::0x0101::MY54321002::INSTR'))
    check('serial ports are listed, not asked', 'ASRL9::INSTR' in w.backend.get() and not any(n.startswith('ASRL') for n in rm.opened), (w.backend.get(), rm.opened))
    check('only queries went to the instruments', rm.only_queries())
    check('buttons are inside the window', all(inside(win, b) for b in (w.btn_scan, w.btn_cancel, w.btn_copy, w.btn_remember, w.btn_forget, w.btn_serial)))
    check('table fits the window', inside(win, w.table.master))
    shot(win, '2_results')

    first = next(k for k in w.table.get_children() if w.table.item(k, 'values')[0] == 'GPIB1::22::INSTR')
    w.table.selection_set(first)
    pump(root, 10)
    check('selecting a row enables Copy and Accept', str(w.btn_copy.cget('state')) == 'normal' and str(w.btn_remember.cget('state')) == 'normal')
    w.btn_copy.invoke()
    check('Copy resource puts the resource string on the clipboard', win.clipboard_get() == 'GPIB1::22::INSTR', win.clipboard_get())
    w.btn_remember.invoke()
    pump(root, 5)
    recs = mem.remembered()
    check('Accept and remember saves one row', [(r.model, r.resource) for r in recs] == [('3458A', 'GPIB1::22::INSTR')], recs)
    first = next(k for k in w.table.get_children() if w.table.item(k, 'values')[0] == 'GPIB1::22::INSTR')
    check('the row now says remembered', 'remembered' in w.table.item(first, 'values')[4])
    check('the selection stayed on the row', first in w.table.selection())
    check('Forget is enabled for it', str(w.btn_forget.cget('state')) == 'normal')
    shot(win, '3_remembered')

    # an unknown / silent row cannot be accepted
    unk = next(k for k in w.table.get_children() if w.table.item(k, 'values')[0] == 'GPIB1::9::INSTR')
    w.table.selection_set(unk)
    pump(root, 5)
    check('a row that did not identify cannot be remembered', str(w.btn_remember.cget('state')) == 'disabled')
    w.table.selection_set(first)
    pump(root, 5)
    w.btn_forget.invoke()
    pump(root, 5)
    check('Forget removes it', mem.remembered() == [])

    # the wire log
    w.btn_log.invoke()
    pump(root, 5)
    text = w.log_text.get('1.0', 'end')
    check('what was sent is shown, queries only', '*IDN?' in text and 'ID?' in text and '*RST' not in text)
    shot(win, '4_log')
    w.btn_log.invoke()

    # RS-232: only on request, with the driver's own code
    from drivers.simulated_8808a import make_8808a_bench
    _b, _c, dt = make_8808a_bench()
    w.serial_checker = lambda port, key: S.serial_hit(port, key, transport_factory=lambda p, s: dt)
    w.port.set('ASRL9::INSTR')
    w.family.set(next(lab for lab in w.family_labels if lab.startswith('8808A')))
    w.btn_serial.invoke()
    check('the serial check returns a row', pump_until(root, lambda: any('ASRL9' in w.table.item(k, 'values')[0] for k in w.table.get_children())))
    row = next(w.table.item(k, 'values') for k in w.table.get_children() if 'ASRL9' in w.table.item(k, 'values')[0])
    check('the 8808A on the port is identified with its serial', row[2] == '8808A' and row[3] == 'SIM0001', row)
    check('the 8808A sim saw only *IDN?', [c for c in dt.sent if c != '*IDN?'] == [], dt.sent)
    shot(win, '5_serial')

    check('no Tk callback errors', not errs, errs)
    win.destroy()

    # Cancel while a resource hangs: the window stays alive and returns at once
    gate = threading.Event()
    rm2 = FakeRM({'GPIB0::1::INSTR': dict(replies={}, block=gate), 'GPIB0::2::INSTR': dict(replies=IDN_3458)})
    w2 = make_window(root, rm2, mem)
    pump(root, 10)
    w2.btn_scan.invoke()
    pump(root, 10)
    check('while scanning Cancel is enabled and Scan is not', str(w2.btn_cancel.cget('state')) == 'normal' and str(w2.btn_scan.cget('state')) == 'disabled')
    shot(w2.win, '6_scanning')
    t0 = time.time()
    w2.btn_cancel.invoke()
    pump(root, 5)
    check('Cancel returns at once and the window is usable again', time.time() - t0 < 1.0 and str(w2.btn_scan.cget('state')) == 'normal', time.time() - t0)
    gate.set()
    pump(root, 10)
    check('the abandoned scan adds no rows', not w2.table.get_children())
    w2.win.destroy()

    # no VISA installed: a plain message, no traceback
    def no_visa():
        raise S.ScanError('No VISA library was found, so instruments cannot be listed. Install NI-VISA or the Keysight IO Libraries Suite (or pip install pyvisa-py).')
    w3 = U.open_find_instruments(root, memory=mem, scanner_factory=lambda a, g: S.Scanner(rm_factory=no_visa), serial_ports=lambda: [])
    pump(root, 10)
    w3.btn_scan.invoke()
    check('no VISA: the message is shown', pump_until(root, lambda: 'No VISA library' in w3.problem_var.get()) and w3.problem.winfo_ismapped(), w3.problem_var.get())
    check('no VISA: Scan is usable again', str(w3.btn_scan.cget('state')) == 'normal')
    shot(w3.win, '7_no_visa')
    w3.win.destroy()

    # chooser mode: returns the accepted resource
    rm4 = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458)})
    w4 = make_window(root, rm4, mem, choose=True)
    pump(root, 10)
    w4.btn_scan.invoke()
    pump_until(root, lambda: w4.report is not None)
    w4.table.selection_set(w4.table.get_children()[0])
    pump(root, 5)
    check('chooser: Use this resource is enabled for an identified row', str(w4.btn_use.cget('state')) == 'normal')
    w4.btn_use.invoke()
    pump(root, 5)
    check('chooser: the accepted resource is the result and is remembered', w4.result == 'GPIB1::22::INSTR' and mem.remembered('3458A'))
    check('no Tk callback errors (later windows)', not errs, errs)
    root.destroy()


def checks_manager_button():
    """The Manager shows the 'Find instruments...' button in its bottom bar and the button opens the window."""
    import Calibration_Procedure_Manager as CPM
    CPM.init_db()
    root = tk.Tk()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    m = CPM.Manager(root)
    pump(root, 20)
    bar = root._cal_statusbar
    btn = next((b for b in bar._buttons if str(b.cget('text')).startswith('Find instruments')), None)
    check('Manager: Find instruments button in the bottom bar', btn is not None)
    check('Manager: button is on screen', inside(root, btn), (btn.winfo_rootx(), btn.winfo_width(), root.winfo_width()))
    opened = []
    import instrument_scan_ui
    orig = instrument_scan_ui.FindInstrumentsWindow
    instrument_scan_ui.FindInstrumentsWindow = lambda parent, **kw: opened.append(parent) or orig(parent, memory=S.ResourceMemory(Path(tempfile.mkdtemp()) / 'r.sqlite3'),
                                                                                                scanner_factory=lambda a, g: S.Scanner(rm_factory=bench), serial_ports=lambda: [])
    try:
        btn.invoke()
        pump(root, 20)
    finally:
        instrument_scan_ui.FindInstrumentsWindow = orig
    check('Manager: the button opens the window', len(opened) == 1)
    tops = [x for x in root.winfo_children() if isinstance(x, tk.Toplevel)]
    check('Manager: a Find instruments window exists', any(t.title().startswith('Find instruments') for t in tops), [t.title() for t in tops])
    shot(root, '8_manager')
    check('Manager: no Tk callback errors', not errs, errs)
    root.destroy()


if __name__ == '__main__':
    try:
        checks_find_instruments()
        checks_manager_button()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print('ALL OK')
