"""Datasheet Builder editor scenarios that run unchanged against the Tk panel (under tests/_tk_stub.py) and the Qt panel (qtui.screens.datasheet_builder).
Both windows expose the same handles (`win.model`, `win.sync()`, `win.bar_v`, `win.commit_bar()`, `win.calc()`, `win.save()`, `win.panel_box.types / .v / .b`,
`win.open_ranges()` ... `.page`), so one script drives both; what each scenario saves (the files under user_specs and the registry rows) and every
message it got back are compared byte for byte by tests/test_qt_dsb.py.  Toolkit-free: no tkinter, no PySide6 import here."""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import re
import sqlite3
from pathlib import Path
from unittest import mock

NOW = '2026-01-01T00:00:00'


class _FixedDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromisoformat(NOW)


@contextlib.contextmanager
def frozen_time():
    """Every time stamp the builder writes (versions, registry rows, the runnable spec's exported_at) is the same constant, so two runs can be compared byte for byte."""
    import datasheet_builder as db
    import datasheet_builder_specs as specs
    with mock.patch.object(db, '_now', lambda: NOW), mock.patch.object(specs, 'datetime', _FixedDatetime):
        yield


class Env:
    """What a toolkit provides: `panel` (the DatasheetBuilderPanel), `new(handheld)` -> an editor window, `answer(yes)` -> context manager that answers every
    Yes / No question, `log` (list of (step, ok, message))."""

    def __init__(self, panel, new, answer):
        self.panel, self.new, self.answer = panel, new, answer
        self.log = []

    def rec(self, step, res):
        if res is None:
            self.log.append((step, None, ''))
        else:
            self.log.append((step, bool(getattr(res, 'ok', True)), getattr(res, 'message', '')))
        return res


def dcv_label(win):
    return next(c['label'] for c in win.model.function_choices() if c['kind'] == 'DCV' and not c['fid'])


def kind_label(win, kind):
    return next(c['label'] for c in win.model.function_choices() if c['kind'] == kind and not c['fid'])


def header(env, win, make, model, title):
    win.make_v.set(make), win.model_v.set(model), win.title_v.set(title)
    return env.rec('header', win.commit_header())


def type_cell(env, win, text, col='nominal', key=None):
    win.model.select(key, col=col)
    win.sync()
    win.bar_v.set(text)
    return env.rec(f'type {text!r} in {col}', win.commit_bar('down'))


def points(win):
    return [r['key'] for r in win.model.rows() if r['kind'] == 'point']


def tolerance(env, win, key, iv=None, fs=None, floor=None, calc=None, db_=None):
    win.model.select(key, 'low')
    win.sync()
    box = win.panel_box
    for k in ('iv', 'fs', 'floor', 'db', 'calc'):
        box.types[k].set(False)
    for k, v in (('iv', iv), ('fs', fs), ('floor', floor), ('db', db_), ('calc', calc)):
        if v is not None:
            box.types[k].set(True)
            box.v[k].set(v)
    return env.rec(f'calc {key}', win.calc())


# ------------------------------------------------------------------------------------------------------------------------------ scenarios
def s_basic(env):
    """Header, one function, four rows with a calculated tolerance, save, edit a cell, undo / redo, save again (version 2)."""
    win = env.new(False)
    header(env, win, 'Acme', 'DM-1', 'DM-1 Basic')
    env.rec('function', win.function_chosen(dcv_label(win)))
    for v in ('100 mV', '1 V', '5 V', '10 V'):
        type_cell(env, win, v)
    for k in points(win):
        tolerance(env, win, k, iv='0.05', fs='0.01')
    env.rec('save 1', win.save())
    k = points(win)[2]
    type_cell(env, win, '6 V', key=k)
    env.rec('undo', win.undo())
    env.rec('redo', win.redo())
    env.rec('remark', None)
    win.model.select(k, 'nominal')
    win.sync()
    win.remark_v.set('use the short leads')
    env.rec('remark set', win.remark_set())
    win.run_v.set(False)
    env.rec('run off', win.run_set())
    env.rec('recalc', win.recalc())
    env.rec('save 2', win.save())
    win.close()


def s_bare_unit(env):
    """A bare number typed in a unit-ful cell shows with its unit: 5 on a mV row is 5 mV."""
    win = env.new(False)
    header(env, win, 'Acme', 'DM-2', 'DM-2 Bare unit')
    env.rec('function', win.function_chosen(dcv_label(win)))
    type_cell(env, win, '50 mV')
    type_cell(env, win, '2 V')
    first = points(win)[0]
    res = type_cell(env, win, '5', key=first)
    env.log.append(('bare 5 shows', None, win.model.cell_text(first, 'nominal')))
    for k in points(win):
        tolerance(env, win, k, iv='0.05', fs='0.01')
    env.rec('save', win.save())
    win.close()


def s_multi_asym_calc(env):
    """Several rows at once, an asymmetrical tolerance, the accuracy statement box and a floor."""
    win = env.new(False)
    header(env, win, 'Acme', 'DM-3', 'DM-3 Multi')
    env.rec('function', win.function_chosen(dcv_label(win)))
    type_cell(env, win, '1 V')
    k = points(win)[0]
    win.model.select(k, 'low')
    win.sync()
    box = win.panel_box
    box.types['iv'].set(True), box.v['iv'].set('0.05')
    box.b['multi'].set(True), box.v['multi_mode'].set('span'), box.v['multi_high'].set('9 V'), box.v['multi_n'].set('5')
    box.multi_changed()
    env.rec('multi calc', win.calc())
    ks = points(win)
    win.model.select(ks[-1], 'low')
    win.sync()
    box = win.panel_box
    box.b['multi'].set(False), box.multi_changed()
    box.types['iv'].set(True), box.types['fs'].set(False)
    box.b['asym'].set(True)
    box.asym_changed()
    box.v['iv'].set('0.1')
    box.v['operand'].set('-')
    box.operand_changed()
    box.v['iv'].set('0.2')
    env.rec('asym calc', win.calc())
    win.model.select(ks[0], 'low')
    win.sync()
    box = win.panel_box
    box.types['iv'].set(False)
    box.types['calc'].set(True), box.v['calc'].set('0.05 % of reading + 2 counts')
    env.rec('statement calc', win.calc())
    win.model.select(ks[1], 'low')
    win.sync()
    box = win.panel_box
    box.types['iv'].set(True), box.v['iv'].set('0.05')
    box.types['floor'].set(True), box.v['floor'].set('20')
    env.rec('floor calc', win.calc())
    env.rec('copy down', win.copy_down())
    env.rec('save', win.save())
    win.close()


def s_ac_frequency(env):
    """An AC volts section: a value @ a frequency."""
    win = env.new(False)
    header(env, win, 'Acme', 'DM-4', 'DM-4 AC')
    env.rec('function', win.function_chosen(kind_label(win, 'ACV')))
    type_cell(env, win, '1 V @ 1 kHz')
    type_cell(env, win, '1 V @ 20 kHz')
    for k in points(win):
        tolerance(env, win, k, iv='0.5', fs='0.05')
    env.rec('save', win.save())
    win.close()


def s_pages(env):
    """The detail pages: ranges, details and time periods, sections, specification line; then Standards and save."""
    win = env.new(False)
    header(env, win, 'Acme', 'DM-5', 'DM-5 Pages')
    env.rec('function', win.function_chosen(dcv_label(win)))
    type_cell(env, win, '5 V')
    dlg = win.open_ranges()
    p = dlg.page
    dlg.reload()
    p.fs.set('20 V'), p.res.set('100 µV')
    env.rec('range add', p.add())
    p.bulk.set('2 V, 200 mV')
    env.rec('ranges add many', p.add_many())
    dlg.reload()
    p.decimals.set('4'), p.dec_prefix.set('m')
    p.use_decimals()
    env.log.append(('resolution from decimals', None, p.res.get()))
    dlg = win.open_details()
    p = dlg.page
    dlg.reload()
    p.custom_id.set('90d'), p.custom_label.set('90 days')
    env.rec('period add', p.add_custom())
    p.outward.set(True)
    env.rec('rounding', p.set_rounding())
    dlg = win.open_functions()
    p = dlg.page
    dlg.reload()
    p.d_switch.set('DC volts, auto range off')
    env.rec('function apply', p.apply())
    dlg = win.open_spec()
    p = dlg.page
    dlg.reload()
    for pid in p.period_vars:
        p.period_vars[pid].set('0.05 % of reading + 0.01 % of range')
    env.rec('spec add', p.add())
    env.rec('save', win.save())
    win.close()


def s_typed_limits(env):
    """An old sheet's typed Low / High pair is kept, marked and can be cleared."""
    win = env.new(False)
    header(env, win, 'Acme', 'DM-6', 'DM-6 Typed')
    env.rec('function', win.function_chosen(dcv_label(win)))
    type_cell(env, win, '5 V')
    k = points(win)[0]
    tolerance(env, win, k, iv='0.05')
    fn, pt = win.model.point_of(k)
    pt.overrides['1y'] = {'low': '4.9', 'high': '5.2'}
    win.model._bump()
    win.model.select(k, 'low')
    win.sync()
    env.log.append(('limits_from', None, win.model.row(k)['limits_from']))
    env.rec('save typed', win.save())
    env.rec('clear typed', win.clear_typed_limits())
    env.log.append(('limits_from after', None, win.model.row(k)['limits_from']))
    env.rec('save cleared', win.save())
    win.close()


def s_template_and_draft(env):
    """The handheld template (empty sections, one row filled) and a refused save that is kept as a draft."""
    win = env.new(True)
    header(env, win, 'Acme', 'DM-7', 'DM-7 Template')
    dcv = next(f for f in win.model.ds.functions if f.kind == 'DCV')
    win.model.select(f'e:{dcv.id}', 'nominal')
    env.rec('target', win.model.set_target_function('DC volts'))
    win.sync()
    type_cell(env, win, '5 V')
    tolerance(env, win, points(win)[0], iv='0.05')
    env.rec('save template', win.save())
    win.close()
    win = env.new(False)
    header(env, win, 'Acme', 'DM-8', 'DM-8 Draft')
    env.rec('function', win.function_chosen(dcv_label(win)))
    type_cell(env, win, '5 V')                          # no tolerance: one thing to fix, the save is offered as a draft
    with env.answer(True):
        env.rec('save draft', win.save())
    win.close()


def s_handheld_add(env):
    win = env.new(False)
    header(env, win, 'Acme', 'DM-9', 'DM-9 Add')
    with env.answer(True):
        env.rec('add handheld', win.add_handheld())
        env.rec('add handheld again', win.add_handheld())
    env.rec('lock', win.model.set_locked(True))
    env.rec('unlock', win.model.set_locked(False))
    env.rec('save', win.save())
    win.close()


SCENARIOS = (s_basic, s_bare_unit, s_multi_asym_calc, s_ac_frequency, s_pages, s_typed_limits, s_template_and_draft, s_handheld_add)


def run_all(env):
    for fn in SCENARIOS:
        env.log.append((f'== {fn.__name__}', None, ''))
        fn(env)
    return env.log


# ------------------------------------------------------------------------------------------------------------------------------ what was saved
def dump_storage(root: Path, db_path: Path) -> dict:
    """Every file under `root` (text, with the folder name made neutral) and every registry row, as plain data to compare."""
    root = Path(root)
    out = {'files': {}, 'db': {}}
    norm = lambda s: s.replace(str(root), '<root>').replace(root.as_posix(), '<root>').replace(str(Path(db_path).parent), '<dir>')   # noqa: E731
    for f in sorted(root.rglob('*')):
        if f.is_file():
            out['files'][f.relative_to(root).as_posix()] = norm(f.read_text(encoding='utf-8'))
    con = sqlite3.connect(str(db_path))
    try:
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            cols = [c[1] for c in con.execute(f'PRAGMA table_info({name})')]
            rows = [[norm(str(v)) if isinstance(v, str) else v for v in r] for r in con.execute(f'SELECT * FROM {name} ORDER BY 1')]
            out['db'][name] = dict(columns=cols, rows=rows)
    finally:
        con.close()
    return out
