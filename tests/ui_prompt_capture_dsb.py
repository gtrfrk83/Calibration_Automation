"""Prompt characterization of the user-built datasheet runtime (dsb_runtime.py, dsb_override.py, dsb_prerun.py; work package QT-H of the Qt migration).

Same canonical records and harness classes as tests/ui_prompt_capture.py; registered in its SCENARIOS at the bottom of that module.  Not a test module.
The scenarios run DsbApp (handheld_dmm.App + the Datasheet Builder rules) on the simulated benches of tests/test_dsb_runtime*.py with a scripted operator: a real-mode
run of the DMM sheet, a demo (virtual bench) run, the scope sheet, the generator sheet with a counter and a 5790B that the scripted operator wires up on the simulated bench
(a rule of `Answers` acts on the bench and answers True, like Harness.on_confirm), a manual (no calibrator) run, the HIGH VOLTAGE refusal, a standard that cannot give a
reading (the 'Measuring standard' question), the reset question, the small dialogs and the manual-override entry.  `main` (the launcher's open-file question and the bad
spec error) can only be recorded at the Tk level (TK_LEVEL_ONLY in ui_prompt_capture): it creates the window itself.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from ui_port import Answers, record  # noqa: E402


def _imports():
    import dsb_fixtures as fx
    import dsb_run_harness as H
    import dsb_runtime as rt
    import datasheet_builder_match as dm
    import datasheet_builder_specs as dsp
    from drivers.simulated import make_bench, SimFlukeTransport
    from drivers.simulated_fgen import make_fgen_bench
    return fx, H, rt, dm, dsp, make_bench, SimFlukeTransport, make_fgen_bench


def _run_dsb(make_harness):
    fx, H, rt, dm, dsp, make_bench, SimFlukeTransport, make_fgen_bench = _imports()
    import dsb_override
    out = {}

    def spec_of(ds):
        return dsp.export_spec(ds, plan=dm.match_datasheet(ds)).spec

    def cal_io(scope=False, models=('5560A', '5522A')):
        bench, _a, _b = make_bench()
        return rt.DsbIO({}, transports={m: SimFlukeTransport(bench, m) for m in models}, scope=scope)

    def prompts(hn):
        return hn.port.prompts if hasattr(hn, 'port') else hn.prompts

    def steady(rec):
        """Which of the two calibrators a point is assigned to follows a set order that changes with PYTHONHASHSEED (dsb planner): name it 'CAL' in the notes."""
        return dict(rec, note=re.sub(r'assigned standard: (5560A|5522A)', 'assigned standard: CAL', rec['note'])) if rec.get('note') else rec

    def done(name, hn):
        out[name] = [steady(r) for r in prompts(hn)]
        bypassed = hn.prompts if hasattr(hn, 'port') else []
        hn.stop()
        assert not bypassed, f'{name}: prompts bypassed the port: {bypassed[:2]}'

    def new(ds, answers=None, io=None, demo=False, manual=False, period=None):
        hn = make_harness(answers)
        hn.start()
        app = hn.make_app(spec_of(ds), demo=demo, io=io, period=period)
        if manual:
            app.cal_mode.set(rt.hh.CAL_CHOICES[2])
        hn.app = app
        hn.default_reading = H.typed_nominal
        hn.fill = False
        return hn, app

    # 1. the DMM sheet on the simulated 5560A / 5522A: cable prompts, the high-voltage question, the reset question, typed readings
    hn, app = new(fx.dmm_34461a_like(), io=cal_io())
    assert hn.run_all()
    done('real_run_dmm', hn)

    # 2. the same sheet on the virtual bench (demo)
    hn, app = new(fx.dmm_34461a_like(), demo=True)
    assert hn.run_all()
    done('demo_run_dmm', hn)

    # 3. nothing connected: every point by hand
    hn, app = new(fx.dmm_34461a_like(), manual=True)
    assert hn.run_all()
    done('manual_run_dmm', hn)

    # 4. the operator refuses the first high-voltage question
    hn, app = new(fx.dmm_34461a_like(), Answers([lambda r: False if r.get('title') == 'HIGH VOLTAGE' else None]), io=cal_io())
    hn.run_all()
    done('high_voltage_refused', hn)

    # 5. the scope sheet: reference level, set-up cards
    def scope_reading(p):
        if p['test'] == 'visual':
            return True
        return '-1.5' if p['run']['op'] == 'scope_bw' else H.typed_nominal(p)
    hn, app = new(fx.scope_tds2000c_like(), io=cal_io(scope=True))
    hn.default_reading = scope_reading
    assert hn.run_all()
    done('real_run_scope', hn)

    # 6. the generator sheet with a simulated 33220A, 5790B and 53132A: the operator wires the bench as each card asks
    def gen_hn(answers_extra=()):
        bench, t = make_fgen_bench('33220A')
        trans = {'5790B': t['std'], '53132A': t['counter']}
        io = rt.DsbIO({}, transports=trans)
        box = {}

        def operator(rec):
            if rec['kind'] != 'operator_prompt':
                return None
            if box['app']._cur is None:                 # the 'Before the run' standards screen comes before the first point: nothing to wire yet
                return True
            run = box['app']._cur['run']
            txt = ' '.join(s if isinstance(s, str) else ' '.join(s) for s in rec['steps']).upper()
            f = run['reference_hz'] if 'REFERENCE' in txt else run['frequency']
            amp = run['nominal'] if run['kind'] == 'GEN_AMPL' else (run['amplitude'] or 1.0)
            bench.connected = 'counter' if run['op'] == 'std_freq' else 'std'
            if run['op'] == 'std_flat' and 'REFERENCE' not in txt and rec['title'] == 'Check the setup':
                return True
            bench.gen.update(on=True, func='SIN', freq=f if f else (run['nominal'] if run['kind'] == 'GEN_FREQ' else 1e3), unit='VPP', load=1e40,
                             amp=(amp * 2 * 2 ** 0.5 if run['kind'] != 'GEN_FREQ' else 1.0))
            if run['kind'] == 'GEN_FREQ':
                bench.gen.update(freq=run['nominal'], amp=1.0)
            return True
        rules = [*answers_extra, operator]
        hn, app = new(fx.generator_33220a_like(), Answers(rules), io=io)
        box['app'] = app
        return hn, app, bench

    hn, app, bench = gen_hn()
    assert hn.run_all()
    done('real_run_generator', hn)

    # 7. the counter is wired to the wrong input: 'Measuring standard' (Yes = type the standard's reading, No = skip the point; Cancel = stop the run is not scriptable
    #    through a rule: None means 'no opinion' to Answers)
    for name, choice in (('measuring_standard_typed', True), ('measuring_standard_skip', False)):
        hn, app, bench = gen_hn([lambda r, _c=choice: _c if r['kind'] == 'ask_yes_no_cancel' and r['title'] == 'Measuring standard' else None])
        inner = hn.answers.rules[-1]

        def wrong_input(rec, _inner=inner, _app=app, _bench=bench):
            r = _inner(rec)
            if rec['kind'] == 'operator_prompt' and _app._cur is not None and _app._cur['run']['op'] == 'std_freq':
                _bench.connected = 'std'
            return r
        hn.answers.rules[-1] = wrong_input
        hn.run_all()
        done(name, hn)

    # 8. the small dialogs
    hn, app = new(fx.dmm_34461a_like(), io=cal_io())
    app.asset.set('')
    app.execute(app.points[:1])                              # no instrument ID -> warning
    app.asset.set('A-100')
    app.test_connection()                                    # not virtual, a calibrator chosen but no standard address: nothing to connect -> info
    app.cal_mode.set(rt.hh.CAL_CHOICES[2])
    app.test_connection()                                    # Manual -> info
    app.found['1'] = dict(reading=1.0, entered='1.0', result='PASS')
    app.period_var.set('90d')
    app.on_period()                                          # readings are recorded: the period cannot be changed -> info
    app.found.clear()
    app.period_var.set('90d')
    app.on_period()                                          # now it can
    app._error(RuntimeError('boom'))                         # a failure -> error
    app.busy = True
    hn.answers.rules.append(lambda r: False if r.get('title') == 'Active run' else None)
    app.on_close()                                           # busy: 'Stop and close?' -> No (stays open)
    hn.answers.rules.clear()
    app.busy = False
    done('dialogs_misc', hn)

    # 9. the virtual bench: connect; the fast demo has nothing to connect
    hn, app = new(fx.dmm_34461a_like(), demo=True)
    app.test_connection()                                    # virtual: connects the simulated calibrator -> info 'Connected (DEMO)'
    app._fast_demo = True
    app.test_connection()                                    # fast demo -> info 'Demo mode'
    app._fast_demo = False
    done('demo_connect', hn)

    # 10. manual override (right-click > Enter reading manually): no instrument ID, then a typed reading through the entry window (recorded at mo_ask)
    hn, app = new(fx.dmm_34461a_like(), io=cal_io())
    entered = []

    def mo_ask(self, p, reason='', cancel_text='Cancel', stored=''):
        rec = record('ask_typed', f'point {p["id"]}', dsb_override.hh.describe(p), None, reason=reason or None, cancel=cancel_text, stored=stored or None)
        typed = dsb_override.parse_typed(p, '1') if len(entered) == 1 else None
        entered.append(typed)
        prompts(hn).append(dict(rec, answer=None if typed is None else typed.shown))
        return typed
    patch = mock.patch.object(dsb_override.DsbOverrideMixin, 'mo_ask', mo_ask)
    patch.start()
    hn.patches.append(patch)
    p0 = next(p for p in app.points if p['test'] == 'numeric')
    app.asset.set('')
    app.mo_replace(p0)                                       # no instrument ID -> warning
    app.asset.set('A-100')
    app.mo_replace(p0)                                       # the entry window is cancelled
    app.mo_replace(p0)                                       # a value is entered
    done('manual_override', hn)

    # 11. the pre-run list of unverified commands (rule 2): the list window (recorded at show_list) accepted, then cancelled
    import dsb_prerun
    hn, app = new(fx.dmm_34461a_like())
    spec = app.spec

    def show_list(root, info):
        rec = record('prerun_list', 'Unverified commands: accept before a real run', re.sub(r'\d+', 'N', info.get('intro') or dsb_prerun.intro(info)), None,
                     listed=bool(info['lines']))                  # the commands themselves depend on which calibrator the planner assigns (hash order): not recorded
        ans = hn.answers.for_(rec, True)
        prompts(hn).append(dict(rec, answer=ans))
        return ans
    patch = mock.patch.object(dsb_prerun, 'show_list', show_list)
    patch.start()
    hn.patches.append(patch)
    prompts(hn).append(record('prerun_result', 'accepted', '', dsb_prerun.accepted(None, spec, '')))
    hn.answers.rules.append(lambda r: False if r['kind'] == 'prerun_list' else None)
    prompts(hn).append(record('prerun_result', 'refused', '', dsb_prerun.accepted(None, spec, '')))
    prompts(hn).append(record('prerun_result', 'same list already accepted', '', dsb_prerun.accepted(None, spec, dsb_prerun.pre_run(spec)['fingerprint'])))
    done('prerun_list', hn)
    return out


def _run_dsb_main(make_harness):
    """The launcher: no --spec (the open-file window: cancelled), and a spec file that cannot be loaded (error box).  Tk level only: main() creates the window."""
    fx, H, rt, dm, dsp, make_bench, SimFlukeTransport, make_fgen_bench = _imports()
    out = {}
    hn = make_harness(None)
    hn.start()
    rt.main([])
    out['main_open_file_cancelled'] = [dict(r, options={k: v for k, v in r['options'].items() if k != 'initialdir'}) if 'options' in r else r     # initialdir is a temp path
                                       for r in (hn.port.prompts if hasattr(hn, 'port') else hn.prompts)]
    hn.stop()
    hn = make_harness(None)
    hn.start()
    rt.main(['--spec', str(HERE / 'no_such_datasheet.json')])
    out['main_bad_spec'] = [dict(r, text=r['text'].replace(str(HERE), '<tests>')) for r in (hn.port.prompts if hasattr(hn, 'port') else hn.prompts)]
    hn.stop()
    return out


SCENARIOS = {'dsb': _run_dsb, 'dsb_main': _run_dsb_main}
