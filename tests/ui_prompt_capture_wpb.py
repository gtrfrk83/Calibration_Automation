"""Prompt characterization of the bench-DMM engines of work package WP-B (Qt migration, NOTES.md 'UiPort and the Qt migration'): Truevolt (34460A / 34461A /
34465A / 34470A), DACQ (34970A / 34972A), Keithley 2000, Agilent 34401A, Fluke 8846A.  (The Fluke 8808A has its scenario in tests/ui_prompt_capture.py.)

Same canonical records and harness classes as tests/ui_prompt_capture.py; registered in its SCENARIOS at the bottom of that module.  Not a test module.
Every scenario is a virtual-bench run on the simulated instruments with a scripted operator (the Fill / default answers of the harness), plus a few refusals and
the small dialogs: no instrument ID, nothing selected, nothing to export, connect, error, close while busy, export / load cancelled.
"""
from __future__ import annotations

from unittest import mock

from ui_port import Answers


def _bench(make_harness, new_app, points, hv_title='HIGH VOLTAGE', warm_title=None, models=(None,), excel=False):
    """new_app(hn, model) -> app (sets hn.app).  points(app) -> the app's active points.  Returns {scenario: [records]}."""
    out = {}

    def prompts(hn):
        return hn.port.prompts if hasattr(hn, 'port') else hn.prompts

    def done(name, hn):
        out[name] = prompts(hn)
        bypassed = hn.prompts if hasattr(hn, 'port') else []
        hn.stop()
        assert not bypassed, f'{name}: prompts bypassed the port: {bypassed[:2]}'

    def new(answers=None, model=None):
        hn = make_harness(answers)
        hn.start()
        app = new_app(hn, model)
        hn.app = app
        return hn, app

    # 1. a whole virtual run per model
    for model in models:
        hn, a = new(model=model)
        assert hn.run_all(), model
        done('virtual_run' + (f'_{model}' if model else ''), hn)

    # 2. the operator refuses the first high-voltage question: the run stops
    hn, a = new(Answers([lambda r: False if str(r.get('title', '')).startswith(hv_title) else None]), models[0])
    hn.run_all()
    done('high_voltage_refused', hn)

    # 3. the operator cancels the first wiring card: the run stops
    hn, a = new(Answers([lambda r: False if r['kind'] == 'operator_prompt' else None]), models[0])
    hn.run_all()
    done('first_prompt_cancelled', hn)

    # 4. the operator cancels the warm-up card (engines that have one)
    if warm_title:
        hn, a = new(Answers([lambda r: False if r.get('title') == warm_title else None]), models[0])
        hn.run_all()
        done('warmup_cancelled', hn)

    # 5. the small dialogs, one by one
    hn, a = new(model=models[0])
    a.asset.set('')
    a.execute(points(a)[:1])                               # no instrument ID -> warning
    a.asset.set('A-1')
    a.tree.selection.return_value = ()                     # Rerun Selected with nothing selected -> info
    a.rerun()
    a.export_pdf()                                         # nothing recorded yet -> info
    a.test_connections()                                   # virtual: connects the simulated bench -> info 'Connected (DEMO)'
    a._error(RuntimeError('boom'))                         # a measurement failure -> error
    a.busy = True
    hn.answers.rules.append(lambda r: False if r.get('title') == 'Active run' else None)
    a.on_close()                                           # busy: 'Stop and close?' -> No (stays open)
    hn.answers.rules.clear()
    a.busy = False
    done('dialogs_misc', hn)

    # 6. export with results: details window cancelled, then details given + save-as cancelled; load: file dialog cancelled
    hn, a = new(model=models[0])
    assert hn.run_all() is True
    (hn.port.prompts if hasattr(hn, 'port') else hn.prompts).clear()
    a.export_pdf()                                         # report details -> None (cancelled)
    hn.answers.rules.append(lambda r: {} if r['kind'] == 'report_details' else None)
    a.export_pdf()                                         # report details given, save-as cancelled ('')
    if excel:
        a.export_excel()                                   # save-as cancelled ('')
    a.load()                                               # open-file cancelled ('')
    done('export_and_load_cancelled', hn)
    return out


def _run_truevolt(make_harness):
    import truevolt_verification as T

    def new_app(hn, model):
        app = T.App(hn.root, model, demo=True, fast_demo=False)
        app.asset.set('A-1'); app.serial.set('S-1')
        return app
    return _bench(make_harness, new_app, lambda a: a.active_points(), models=('34470A', '34461A'))


def _run_dacq(make_harness):
    import dacq_verification as D

    def new_app(hn, model):
        D.configure(model)
        app = D.App(hn.root, model, demo=True, fast_demo=False)
        app.asset.set('A-1'); app.serial.set('S-1')
        return app
    return _bench(make_harness, new_app, lambda a: a.active_points(), models=('34970A', '34972A'))


def _run_k2000(make_harness):
    import keithley2000_verification as K

    def new_app(hn, model):
        app = K.App(hn.root, demo=True, fast_demo=False)
        app.asset.set('A-1'); app.serial.set('S-1')
        return app
    return _bench(make_harness, new_app, lambda a: a.active_points(), warm_title='Before the verification')


def _run_a34401a(make_harness):
    import Agilent_34401A as A

    def new_app(hn, model):
        with mock.patch.object(A.App, 'refresh_ports', lambda s: None):
            app = A.App(hn.root, demo=True)
        app.asset.set('A-1'); app.serial.set('S-1')
        return app
    return _bench(make_harness, new_app, lambda a: A.POINTS)


def _run_f8846a(make_harness):
    import Fluke_8846A_Verification as V

    def new_app(hn, model):
        with mock.patch.object(V.App, 'refresh_ports', lambda s: None):
            app = V.App(hn.root, demo=True)
        app.asset.set('A-1'); app.serial.set('S-1')
        return app
    return _bench(make_harness, new_app, lambda a: V.POINTS, excel=True)


SCENARIOS = {'truevolt': _run_truevolt, 'dacq': _run_dacq, 'k2000': _run_k2000, 'a34401a': _run_a34401a, 'f8846a': _run_f8846a}
