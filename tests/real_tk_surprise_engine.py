"""Real-Tk check of an engine wired for stop-on-surprise (run by tests/test_surprise_wiring.py in a subprocess; not a test module).

    python tests/real_tk_surprise_engine.py <engine> <scenario>        engine: truevolt | dacq | a34410 | fgen      scenario: clean | stop | continue

The real engine window (real Tk, a worker thread, mainloop) is connected to simulated instruments with a fault injected (tests/surprise_faults.py).
The Stop / Continue dialog must appear ON the Tk thread, with the right buttons, and the answer must do what the engine promises:
  clean     no dialog at all, every point recorded
  stop      a stop-only surprise (no Continue button): Stop -> the engine's own error dialog, outputs to standby, the points before it recorded
  continue  a Continue-able surprise: Continue -> every point recorded as usual, the surprise in the command log
Prints 'CHECK <name> ok' lines and 'ALL OK'."""
import sys
import threading
import time
import traceback
from pathlib import Path

import os  # noqa: E402
import tempfile  # noqa: E402

_HOME = tempfile.mkdtemp()                                         # settings, checkpoints and the command log of this check never touch the real home
os.environ.update(HOME=_HOME, USERPROFILE=_HOME, CALSUITE_DATA=str(Path(_HOME) / 'data'))

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'Procedures')]

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

import surprise  # noqa: E402
from surprise_faults import FaultTransport, Rule  # noqa: E402


def check(name, cond, detail=''):
    if not cond:
        raise AssertionError(f'{name}: {detail}')
    print(f'CHECK {name} ok')


def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


def toplevels(root):
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and hasattr(w, '_surprise')]


class Setup:
    """Per-engine: the module, the simulated bench with faults, the points to run and the fault for each scenario."""

    def __init__(self, engine, scenario):
        self.engine, self.scenario = engine, scenario
        getattr(self, engine)()

    def truevolt(self):
        import truevolt_verification as T
        from drivers.simulated import make_dmm_bench
        self.mod = T
        T.configure('34470A')
        _b, ft, dt = make_dmm_bench('34470A')
        d_rules, c_rules = [], []
        if self.scenario == 'stop':
            d_rules = [Rule('READ?', '=>', nth=2)]                                       # a prompt character where a reading was expected
        elif self.scenario == 'continue':
            d_rules = [Rule('SYST:ERR?', '-113,"Undefined header"', after='VOLT:DC:NPLC', nth=2)]
        self.dmm, self.cal = FaultTransport(dt, *d_rules), FaultTransport(ft, *c_rules)
        self.points = [p for p in T.POINTS if p['source'] == 'calibrator' and p['terminal'] != 'REAR'][:3]
        self.app_args = ('34470A',)
        self.open_visa = lambda addr, **k: self.dmm if addr.upper().startswith('USB') else self.cal
        self.expect_stop = dict(recorded=1, text='READ?')
        self.expect_continue = dict(recorded=3, text='-113')
        self.prepare = lambda app: None
        self.n_guards = 2
        self.standby_tail = ['STBY']

    def a34410(self):
        import agilent34410a_verification as A
        from drivers.simulated_34410a import make_34410a_bench
        self.mod = A
        A.configure('34410A')
        _b, ft, dt = make_34410a_bench('5560A', 'GPIB', '34410A')
        d_rules = []
        if self.scenario == 'stop':
            d_rules = [Rule('READ?', '=>', nth=2)]
        elif self.scenario == 'continue':
            d_rules = [Rule('SYST:ERR?', '-113,"Undefined header"', nth=3)]              # connect (1), after the configuration of point 1 (2), after its reading (3)
        self.dmm, self.cal = FaultTransport(dt, *d_rules), FaultTransport(ft)
        self.points = [p for p in A.POINTS if p['source'] == 'calibrator' and p['terminal'] != 'REAR' and p['kind'] in ('DCV', 'DCI')][:3]
        self.app_args = ()
        self.open_visa = lambda addr, **k: self.cal if addr.upper().startswith('ASRL') else self.dmm
        self.expect_stop = dict(recorded=1, text='READ?')
        self.expect_continue = dict(recorded=3, text='-113')
        self.prepare = lambda app: None
        self.n_guards = 2
        self.standby_tail = ['STBY']

    def dacq(self):
        import dacq_verification as D
        from drivers.simulated import make_dacq_bench
        self.mod = D
        D.configure('34970A')
        _b, ft, dt = make_dacq_bench('34970A', '5560A', {2: '34901A'})
        d_rules = []
        if self.scenario == 'stop':
            d_rules = [Rule('READ?', '=>', nth=2)]
        elif self.scenario == 'continue':
            d_rules = [Rule('SYST:ERR?', '-113,"Undefined header"', nth=3)]              # connect (1), after CONF of point 1 (2), after its reading (3)
        self.dmm, self.cal = FaultTransport(dt, *d_rules), FaultTransport(ft)
        self.points = [p for p in D.POINTS if p['source'] == 'calibrator'][:3]
        self.app_args = ('34970A',)
        self.open_visa = lambda addr, **k: self.cal if '9' in addr else self.dmm            # COM9 = the calibrator, COM1 = the 34970A
        self.expect_stop = dict(recorded=1, text='READ?')
        self.expect_continue = dict(recorded=3, text='-113')
        self.prepare = lambda app: (app.dmm_addr.set('COM1'), app.cal_addr.set('COM9'))
        self.n_guards = 2
        self.standby_tail = ['STBY']

    def fgen(self):
        import fgen_verification as F
        from drivers.simulated_fgen import make_fgen_bench
        self.mod = F
        F.configure('33220A')
        bench, t = make_fgen_bench('33220A')
        bench.connected = 'std'                                                       # the generator output is cabled to the 5790B (the ACAMP points)
        s_rules = []
        if self.scenario == 'stop':
            s_rules = [Rule('MEAS?', '=>', nth=4)]                                    # a prompt character where a reading was expected (the first MEAS? of point 2: point 1 took three, two unsettled)
        elif self.scenario == 'continue':
            s_rules = [Rule('ERR?', '-113,"Undefined header"', after='EXTRIG', nth=2)]      # the 5790B's queue after EXTRIG: connect (no EXTRIG), point 1 (1), point 2 (2)
        self.dmm, self.cal = FaultTransport(t['uut']), FaultTransport(t['std'], *s_rules)         # (named dmm / cal only for the shared code: generator, 5790B)
        self.points = [p for p in F.POINTS if p['kind'] == 'ACAMP'][:3]
        self.app_args = ('33220A',)
        self.open_visa = lambda addr, **k: self.dmm if addr.upper().startswith('USB') else self.cal
        self.expect_stop = dict(recorded=1, text='MEAS?')
        self.expect_continue = dict(recorded=3, text='-113')
        self.prepare = lambda app: None
        self.n_guards = 2
        self.standby_tail = ['OUTP OFF', 'OUTP?']                                     # the engine's own all_off


def main(engine, scenario):
    S = Setup(engine, scenario)
    mod = S.mod
    log = {'boxes': []}
    for name in ('showinfo', 'showwarning', 'showerror'):
        setattr(messagebox, name, lambda *a, _n=name, **k: log['boxes'].append((_n, a[:2])))
    for name in ('askyesno', 'askokcancel', 'askyesnocancel'):
        setattr(messagebox, name, lambda *a, **k: True)
    __import__('ui_theme').confirm_steps = lambda *a, **k: True                    # the hook-up / safety prompts are not what is tested here
    time.sleep = lambda s: None                                    # settle waits
    mod.drivers.open_visa = S.open_visa

    root = tk.Tk()
    root.geometry('1200x800+0+0')
    app = mod.App(root, *S.app_args, demo=False, fast_demo=False)
    app.asset.set('A1')
    app.serial.set('S1')
    S.prepare(app)
    app.test_connections()                                       # on the Tk thread: the handler is made here, as in the real window
    check('real connection: every connected instrument guarded', len(app.io.guards) == S.n_guards, app.io.guards)
    state = {'dialog': None, 'started': False, 'pressed': False, 'texts': ''}
    answer = 'stop' if scenario == 'stop' else 'continue'

    def poll():
        tops = toplevels(root)
        if tops and not state['pressed']:
            w = tops[0]
            state['dialog'] = w
            state['texts'] = '\n'.join(str(c.cget('text')) if not isinstance(c, tk.Text) else c.get('1.0', 'end') for c in walk(w) if 'text' in c.keys() or isinstance(c, tk.Text))
            state['has_cont'] = w._surprise['cont'] is not None
            state['pressed'] = True
            w._surprise['stop' if answer == 'stop' else 'cont'].invoke()
        if state['started'] and not app.busy and not toplevels(root):
            root.quit()
        elif time.monotonic() > end:
            root.quit()
        else:
            root.after(20, poll)

    end = time.monotonic() + 60
    app.execute(S.points)
    state['started'] = True
    root.after(20, poll)
    root.mainloop()
    check('the run ended (not hung)', not app.busy)
    recorded = len(app.results)
    wire = [t for _i, d, t in ((e[1], e[2], e[3]) for e in app.io.log.entries) if d == '>>']
    if scenario == 'clean':
        check('clean: no dialog', state['dialog'] is None)
        check('clean: every point recorded', recorded == len(S.points), recorded)
        check('clean: no error dialog', not [b for b in log['boxes'] if b[0] == 'showerror'], log['boxes'])
    elif scenario == 'stop':
        exp = S.expect_stop
        check('stop: one dialog on the Tk thread', state['dialog'] is not None)
        check('stop: no Continue button (Continue is not safe here)', state['has_cont'] is False)
        check('stop: dialog names the command and says why', exp['text'] in state['texts'] and 'Continue is not offered' in state['texts'], state['texts'][:600])
        check('stop: the points before it are recorded', recorded == exp['recorded'], recorded)
        check('stop: the engine shows its own error dialog', [b for b in log['boxes'] if b[0] == 'showerror'], log['boxes'])
        check('stop: outputs end in standby / off', wire[-len(S.standby_tail):] == S.standby_tail, wire[-5:])
        check('stop: the surprise is in the command log', any(e[2] == '!!' and 'SURPRISE reply' in e[3] for e in app.io.log.entries))
    else:
        exp = S.expect_continue
        check('continue: one dialog with Stop and Continue', state['dialog'] is not None and state['has_cont'] is True)
        check('continue: dialog shows the entry', exp['text'] in state['texts'], state['texts'][:600])
        check('continue: every point recorded', recorded == exp['recorded'], recorded)
        check('continue: no error dialog', not [b for b in log['boxes'] if b[0] == 'showerror'], log['boxes'])
        check('continue: noted in the command log', any(e[2] == '!!' and 'operator chose Continue' in e[3] for e in app.io.log.entries))
    app.stop = True
    root.destroy()


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2])
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    print('ALL OK')
