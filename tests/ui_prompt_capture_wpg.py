"""Prompt scenarios of work package WP-G (function generators and scopes): fgen_verification (33220A / 33250A / 33210A), mdo4000c_verification, tds2000c_verification.

Registered into tests/ui_prompt_capture.SCENARIOS (keys 'fgen', 'mdo4000c', 'tds2000c'); fixtures tests/golden_ui/ui_prompts_<key>.json were recorded on the UNPORTED
engines.  Not a test module.  The typed readings (fgen askfloat, MDO4000C askstring) are answered with the box's pre-filled simulated value, like the beta tests do.
"""
from __future__ import annotations

from unittest import mock

from ui_port import Answers


def _accept_initial(rec):
    """The scripted operator presses OK on a reading box that holds a simulated value (virtual bench): answer = its `initial`."""
    if rec['kind'] in ('ask_number', 'ask_text'):
        return rec.get('initial')
    return None


def _prompts(hn):
    return hn.port.prompts if hasattr(hn, 'port') else hn.prompts


def _finish(out, name, hn):
    out[name] = _prompts(hn)
    bypassed = hn.prompts if hasattr(hn, 'port') else []
    hn.stop()
    assert not bypassed, f'{name}: prompts bypassed the port: {bypassed[:2]}'


def _answers(*rules):
    return Answers([_accept_initial, *rules])


def _misc(hn, a, out, name, fail=None):
    """The small dialogs, one by one (shared by the three engines)."""
    a.asset.set('')
    a.execute(a.active_points()[:1])                       # no instrument ID -> warning
    a.asset.set('A-1')
    a.tree.selection.return_value = ()                     # Rerun Selected with nothing selected -> info
    a.rerun()
    a.export_pdf()                                         # nothing recorded yet -> info
    a.test_connections()                                   # virtual: connects the simulated bench -> info 'Connected (DEMO)'
    (fail or a._error)(RuntimeError('boom'))               # a measurement failure -> error (the scopes report it from _finished)
    a.busy = True
    hn.answers.rules.append(lambda r: False if r.get('title') == 'Active run' else None)
    a.on_close()                                           # busy: 'Stop and close?' -> No (stays open)
    hn.answers.rules.clear()
    a.busy = False
    _finish(out, name, hn)


def _export_load(hn, a, out, name, pump):
    assert pump(hn, a)
    (hn.port.prompts if hasattr(hn, 'port') else hn.prompts).clear()
    a.export_pdf()                                         # report details -> None (cancelled)
    hn.answers.rules.append(lambda r: {} if r['kind'] == 'report_details' else None)
    a.export_pdf()                                         # report details given, save-as cancelled ('')
    a.load()                                               # open-file cancelled ('')
    _finish(out, name, hn)


def _run_fgen(make_harness):
    import fgen_verification as F
    out = {}

    def new(model='33220A', answers=None):
        hn = make_harness(answers or _answers())
        hn.start()
        F.configure(model)
        a = F.App(hn.root, model, demo=True)
        a.asset.set('A-1'); a.serial.set('S-1')
        hn.app = a
        return hn, a

    def run(hn, a):
        a.run_all()
        return hn.pump(120)

    for model in ('33220A', '33250A', '33210A'):          # the generator pops up the typed counter / power-meter readings through call_from_worker
        hn, a = new(model)
        assert run(hn, a), model
        _finish(out, f'virtual_run_{model}', hn)

    hn, a = new(answers=_answers(lambda r: False if r.get('title') == 'Test conditions' else None))
    run(hn, a)
    _finish(out, 'conditions_cancelled', hn)

    hn, a = new(answers=_answers(lambda r: False if r.get('title') == 'Rewire / verify - generator output is OFF' else None))
    run(hn, a)
    _finish(out, 'wiring_cancelled', hn)

    hn, a = new(answers=Answers())                         # every typed reading box cancelled (askfloat -> None)
    run(hn, a)
    _finish(out, 'typed_reading_cancelled', hn)

    hn, a = new()
    _misc(hn, a, out, 'dialogs_misc')

    hn, a = new()
    _export_load(hn, a, out, 'export_and_load_cancelled', run)
    return out


def _run_mdo(make_harness):
    import mdo4000c_verification as M
    out = {}

    def new(answers=None, fast=False):
        hn = make_harness(answers or _answers())
        hn.start()
        a = M.App(hn.root, demo=True, fast_demo=fast)
        a.asset.set('A-1'); a.serial.set('S-1')
        hn.app = a
        return hn, a

    def run(hn, a):
        a.run_all()
        return hn.pump_poll(300)

    hn, a = new()
    assert run(hn, a)
    _finish(out, 'virtual_run', hn)

    def afg(answers):                                      # the AFG option with no reference DMM / counter: its readings are typed (the manual dialog)
        hn, a = new(answers)
        a.v_afg.set(True); a.on_config(save=False)
        a.test_connections()
        a.io.dmm = a.io.counter = None                     # no reference DMM / counter attached
        return hn, a

    hn, a = afg(None)
    assert run(hn, a)
    _finish(out, 'afg_typed_readings', hn)

    first = {'n': 0}

    def bad_number_once(rec):                              # the first reading box gets text that is not a number -> warning, then the box again
        if rec['kind'] == 'ask_text' and first['n'] == 0:
            first['n'] = 1
            return 'abc'
        return None
    hn, a = afg(Answers([bad_number_once, _accept_initial]))
    assert run(hn, a)
    _finish(out, 'afg_reading_not_a_number', hn)

    hn, a = afg(Answers([]))                               # every reading box cancelled (askstring -> None)
    run(hn, a)
    _finish(out, 'afg_reading_cancelled', hn)

    hn, a = new(Answers([_accept_initial, lambda r: False if r['kind'] == 'operator_prompt' else None]))
    run(hn, a)
    _finish(out, 'first_prompt_cancelled', hn)

    hn, a = new()
    _misc(hn, a, out, 'dialogs_misc', a._finished)
    hn, a = new()
    _export_load(hn, a, out, 'export_and_load_cancelled', run)
    return out


def _run_tds(make_harness):
    import tds2000c_verification as T
    out = {}

    def new(answers=None, fast=False):
        hn = make_harness(answers)
        hn.start()
        a = T.App(hn.root, demo=True, fast_demo=fast)
        a.asset.set('A-1'); a.serial.set('S-1')
        a.v_model.set('2024C')
        hn.app = a
        return hn, a

    def run(hn, a):
        a.run_all()
        return hn.pump_poll(300)

    hn, a = new()
    assert run(hn, a)
    _finish(out, 'virtual_run_2024C', hn)

    hn, a = new()
    a.v_model.set('2012C')
    a.on_config()
    assert run(hn, a)
    _finish(out, 'virtual_run_2012C', hn)

    hn, a = new(Answers([lambda r: False if r['kind'] == 'operator_prompt' else None]))
    run(hn, a)
    _finish(out, 'first_prompt_cancelled', hn)

    hn, a = new()
    a.read_model()                                         # virtual: connects and reads the simulated scope -> info
    _finish(out, 'read_model', hn)

    hn, a = new(fast=True)
    a.test_connections()                                   # fast demo -> 'Demo mode' info
    a.read_model()
    _finish(out, 'fast_demo_dialogs', hn)

    hn, a = new()
    _misc(hn, a, out, 'dialogs_misc', a._finished)
    hn, a = new()
    _export_load(hn, a, out, 'export_and_load_cancelled', run)
    return out


SCENARIOS = {'fgen': _run_fgen, 'mdo4000c': _run_mdo, 'tds2000c': _run_tds}
