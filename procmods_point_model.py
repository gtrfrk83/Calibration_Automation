"""The model behind the per-point editor window (Tk-free; the window is procmods_point_ui.py).

What the window is for (Mike's request): right-click a test point of the running procedure, choose Edit, and see in a small window
  * the instrument commands the engine will send for THAT point on the selected instruments, in send order, with this point's values
    filled in (procmods_plan: a dry run of the engine's own point routine on the simulated bench; nothing is re-derived here),
  * and type changes: a different command for this point, or extra command lines before / after the point's own commands;
  * and, with developer mode on, change the point's tolerance, nominal, unit and description.

Everything it saves goes through the existing storage layer (procmods.Store / make_run_entry via procmods_ui_model.ProcModsModel.apply):
append-only overrides with reason, author and date, the run-modification snapshot and the live_edits audit trail, the "this run only" /
"save for this instrument" / "save for all <model>" scopes, and the point-boundary rule (nothing changes a point that is in progress; a saved
edit reaches the next point, or the redo of this one).  This module adds no new way of writing anything.

Gate: the existing developer-mode gate (devmode.py, wrapped by procmods_ui_model.DevLock).  Without an unlocked session the window shows the
commands and the fields read-only; with it, commands and fields can be edited and saved.  There is no second password scheme.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import cmdreg
import procmods as pm
import procmods_pointdef as pdef
import procmods_plan
import procmods_ui_model as M

TIP_LIMIT = ('Changing a limit changes whether this point passes or fails. The change is recorded in the audit trail (who, when, the old and '
             'new values and your reason) and is printed with the results.')
TIP_UNVERIFIED = ('A command you type is recorded as UNVERIFIED: it has not been checked against the manufacturer\'s manual. A setting is '
                  'sent once, read back and compared; it is never retried. Outputs return to standby after the point.')
SAVE_NEEDS_DEV = 'Saving a change for this instrument or for all of this model needs developer mode. A change for this run only does not.'
SAVED_NEEDS_DEV = 'This command change is saved for later runs; removing it needs developer mode.'
NOT_TESTED = 'Not tested (this procedure offers no way to try a command from here)'

FIELD_LABELS = {'description': 'Description', 'nominal': 'Nominal', 'unit': 'Unit', 'error': 'Tolerance (+/-)', 'low': 'Lower limit',
                'high': 'Upper limit'}
FIELD_ORDER = ('description', 'nominal', 'unit', 'error', 'low', 'high')


# ------------------------------------------------------------------------------------------------------------ display helpers
_SI = ((1e12, 'T'), (1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1.0, ''), (1e-3, 'm'), (1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p'))


def si_text(value, unit='') -> str:
    """Display-only SI scaling (1e-3 V -> '1 mV').  The stored / sourced value is never rounded or changed by this."""
    d = pdef.parse_decimal(value)
    if d is None:
        return '' if value is None else str(value)
    if unit in ('%', 'ratio', 'dB', 'dBm', 'dBc', 'div', 'ppm', 'PCT', 'dBm/Hz', 'dBc/Hz'):         # not SI-scaled
        return f'{pdef.dec_text(d)} {unit}'
    x = float(d)
    if x == 0:
        return f'0 {unit}'.rstrip()
    for scale, prefix in _SI:
        if abs(x) >= scale * 0.9999999:
            return f'{pdef.dec_text(Decimal(repr(round(x / scale, 9))))} {prefix}{unit}'.rstrip()
    return f'{pdef.dec_text(d)} {unit}'.rstrip()


def _text(v) -> str:
    if v is None:
        return ''
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return pdef.dec_text(repr(v) if isinstance(v, float) else v) or str(v)
    return str(v)


# ------------------------------------------------------------------------------------------------------------ rows
@dataclass
class CmdRow:
    seq: int
    driver: str                      # driver class name (what an override target uses)
    label: str                       # the instrument as the operator knows it ('5560A', '34470A' ...)
    op: str                          # 'write' | 'query'
    wire: str                        # what goes on the wire for this point (after any override)
    key: str | None = None           # registry key; None = not in the command registry
    name: str = ''
    kind: str = ''
    risk: str = ''
    verified: bool | None = None
    template: str = ''               # the template now in effect (factory, or the override)
    factory_template: str = ''
    placeholders: list = field(default_factory=list)
    vals: dict = field(default_factory=dict)
    readback_key: str | None = None  # registry key of the query that reads this command back
    readback_wire: str = ''          # that query as sent for this point
    editable: bool = False
    reason: str = ''                 # why it is read-only
    changed: bool = False            # differs from the manufacturer default for this point
    source: str = 'factory'          # 'factory' | 'this point' | 'all points' | 'extra'
    target: str = ''                 # the override target an edit of this row writes ('Driver:key@<point key>')
    uid: str | None = None           # the stored override that produced `template`
    repeat_of: int | None = None     # the same registry command already appears earlier in this point's list
    extra: dict | None = None        # {'phase','n','uid','readback','expect'} for an operator-typed extra line
    pending: bool = False            # an extra line staged in this window and not saved yet
    staged: str | None = None        # template typed in this window, not saved yet
    staged_problems: list = field(default_factory=list)
    preview: str = ''                # the text that would be sent for this point with the staged template ('' = no staged change)

    @property
    def status_text(self) -> str:
        if self.extra is not None:
            return 'UNVERIFIED (typed)'
        if self.verified is None:
            return 'not in the command table'
        return 'verified' if self.verified else 'UNVERIFIED'

    @property
    def risk_text(self) -> str:
        return {'normal': 'normal', 'output': 'output (locked)', 'locked': 'locked'}.get(self.risk, self.risk or '-')

    @property
    def shown_wire(self) -> str:
        return self.preview or self.wire


@dataclass
class FieldState:
    name: str
    label: str
    factory: str = ''                # the manufacturer / spec value (text)
    effective: str = ''              # the value in effect now (text)
    staged: str | None = None        # typed in this window, not saved yet
    unit: str = ''                   # base unit, for the display-only SI text
    editable: bool = False
    reason: str = ''                 # why it is read-only (what this procedure does with the field)
    note: str = ''
    problems: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.staged if self.staged is not None else self.effective

    @property
    def changed(self) -> bool:
        """Differs from the manufacturer value (what is in effect or staged)."""
        return not _same(self.name, self.text, self.factory)

    @property
    def dirty(self) -> bool:
        return self.staged is not None and not _same(self.name, self.staged, self.effective)

    @property
    def display(self) -> str:
        """Display-only scaled text for numeric fields."""
        if self.name in ('nominal', 'error', 'low', 'high'):
            return si_text(self.text, self.unit) if self.unit else self.text
        return self.text


def _same(name, a, b) -> bool:
    if name in ('nominal', 'error', 'low', 'high'):
        return pdef.same_decimal(a, b) if (pdef.parse_decimal(a) is not None and pdef.parse_decimal(b) is not None) else (a or '') == (b or '')
    return (a or '') == (b or '')


# ------------------------------------------------------------------------------------------------------------ the menu
def run_from_entry(app):
    """The right-click 'Run from here' of every point list: (label, command, enabled, reason) or None when the procedure has no Rerun From.
    It is the same action as the 'Rerun From Selected' button (the right-click has already selected the row), so it needs no new run logic.
    Independent of the Edit lock: a verified procedure can still be run.  Never raises."""
    try:
        fn = getattr(app, 'rerun_from', None) or getattr(app, 'rerun_from_selected', None)
        if fn is None:
            return None
        busy = bool(getattr(app, 'busy', False))
        bb = getattr(app, '_batch_busy', None)
        if not busy and callable(bb):
            busy = bool(bb())
        if busy:
            return ('Run from here', fn, False, 'A test is running. Stop it first.')
        btn = getattr(app, 'btn_rerun_from', None)
        if btn is not None:
            try:
                ok = btn.isEnabled() if hasattr(btn, 'isEnabled') else str(btn['state']) != 'disabled'
            except Exception:
                ok = True
            if not ok:
                return ('Run from here', fn, False, 'Not available right now.')
        return ('Run from here', fn, True, '')
    except Exception:
        return None


def menu_state(app, pid) -> tuple:
    """(enabled, reason) for the right-click 'Edit' of point `pid`.  Disabled, with the reason, when the procedure is verified / locked or the
    point is being measured right now.  Never raises."""
    try:
        st = app.pm_state
        if st is None:
            return False, 'Procedure modifications are not available in this procedure.'
        why = ''
        store = st._store()
        fn = getattr(store, 'lock_reason', None)
        if fn is not None:
            why = fn(st.model, st.proc_key) or ''
        if why:
            return False, why
        why = app.pm_point_busy(pid)
        if why:
            return False, why
        if app.pm_find_point(pid) is None:
            return False, 'This row is not a test point.'
        return True, ''
    except Exception as exc:                                        # the menu never breaks the window
        return False, f'The point editor is not available ({type(exc).__name__}).'


# ------------------------------------------------------------------------------------------------------------ the model
class PointEditModel:
    """One open point window.  Build it, read `rows` / `fields`, stage edits, call apply()."""

    def __init__(self, app, pid, lock, *, store=None, now=datetime.now, load_plan=True):
        self.app, self.pid, self.lock, self._now = app, pid, lock, now
        self.ctx = app.pm_live_context()
        if store is not None:
            self.ctx.store = store
        self.pm = M.ProcModsModel(self.ctx, lock, now=now)
        self.pm.run_commands_ungated = True                          # Mike: a RUN-ONLY command edit needs no passphrase (nothing is stored)
        self.live_point = app.pm_find_point(pid)
        self.view, self.key = app.pm_factory_point(pid)
        self.title = self._title()
        self.reason = ''
        self.acknowledged = False
        self.redo_chosen = False
        self.plan = procmods_plan.Plan(note='')
        self.rows: list = []
        self.fields: dict = {}
        self.field_problems: list = []
        self._extra_drafts: list = []                                # targets of extra-line drafts, in the order added
        self.command_problems: dict = {}
        self.load(plan=load_plan)

    # ------------------------------------------------------------------ state
    def _title(self) -> str:
        p = self.live_point if self.live_point is not None else self.view
        try:
            return f'Point {self.pid}: {self.app.pm_point_title(p)}'
        except Exception:
            return f'Point {self.pid}'

    @property
    def demo(self) -> bool:
        return bool(self.ctx.demo)

    @property
    def scope(self) -> str:
        return self.pm.scope

    def set_scope(self, scope):
        if scope != 'run' and not self.lock.unlocked:
            raise ValueError(SAVE_NEEDS_DEV)
        self.pm.set_scope(scope)                                     # raises ValueError with the reason (demo: this run only)

    def scope_choices(self) -> list:
        """[(scope, label, available, why)] for the window's 'Applies to' choice."""
        model = self.ctx.model or 'this model'
        out = [('run', 'This run only', True, '')]
        if self.demo:
            why = 'Demo mode: an edit applies to this run only and is never saved.'
            return [('run', 'This run only (demo)', True, ''), ('asset', 'Save for this instrument', False, why),
                    ('model', f'Save for all {model}', False, why)]
        dev = self.lock.unlocked
        out.append(('asset', 'Save for this instrument', bool(self.ctx.asset_id) and dev,
                    SAVE_NEEDS_DEV if not dev else '' if self.ctx.asset_id else 'Enter the instrument ID first.'))
        out.append(('model', f'Save for all {model}', bool(self.ctx.model) and dev, '' if dev else SAVE_NEEDS_DEV))
        return out

    @property
    def blocked_reason(self) -> str:
        """Why nothing at all can be edited for this point (the window is a viewer): verified / locked procedure, point being measured, edits
        not available.  '' = editable once developer mode is on."""
        if self.live_point is None or self.view is None:
            return 'This row is not a test point of the procedure.'
        why = self.pm.verified_lock
        if why:
            return why
        try:
            why = self.ctx.live.blocked_reason() if self.ctx.live is not None else ''
        except Exception:
            why = 'live editing is not available right now'
        if why:
            return why
        return self.app.pm_point_busy(self.pid)

    @property
    def commands_editable(self) -> bool:
        """Typed / edited commands for THIS RUN need no developer mode; only a verified/locked procedure, a point in progress or a
        non-editable run stops them."""
        return not self.blocked_reason

    @property
    def needs_unlock(self) -> bool:
        return not self.blocked_reason and not self.lock.unlocked

    @property
    def editable(self) -> bool:
        return not self.blocked_reason and self.lock.unlocked

    @property
    def read_only_reason(self) -> str:
        return self.blocked_reason or ('' if self.lock.unlocked else 'Read-only. Turn on developer mode to make changes.')

    @property
    def dev_state(self) -> str:
        return self.lock.state

    @property
    def has_reading(self) -> bool:
        try:
            return bool(self.app.pm_point_has_reading(self.pid))
        except Exception:
            return False

    @property
    def supports_redo(self) -> bool:
        return bool(self.ctx.live is not None and self.ctx.live.supports_redo)

    def load(self, plan=True):
        """(Re)read the saved changes and rebuild the rows and the fields.  Staged (unsaved) edits are kept."""
        self.pm.refresh()
        self.live_point = self.app.pm_find_point(self.pid)
        self.view, self.key = self.app.pm_factory_point(self.pid)
        self.title = self._title()
        if plan and self.live_point is not None:
            self.plan = self.app.pm_plan_point(self.live_point)
        self.rebuild()

    def rebuild(self):
        if self.pm.scope != 'run' and not self.lock.unlocked:        # developer mode went off (idle auto-lock): back to this run only
            self.pm.scope = 'run'
        self.rows = self._build_rows()
        self._build_fields()
        self._rebuild_limit()

    # ------------------------------------------------------------------ commands
    def _registry(self, driver) -> dict:
        return self.ctx.registries.get(driver) or {}

    def _overrides(self):
        """({target: entry} of the active command overrides)."""
        return {e['target']: e for e in (self.pm.oset.active('command') if self.pm.oset else [])}

    def _build_rows(self) -> list:
        ov = self._overrides()
        rows, seen = [], {}
        entries = list(self.plan.entries)
        used = set()
        why_ro = self.blocked_reason
        i = 0
        while i < len(entries):
            e = entries[i]
            i += 1
            if i - 1 in used:
                continue
            row = CmdRow(e.seq, e.driver, e.label, e.op, e.wire, e.key, e.name, e.kind, e.risk, e.verified)
            if e.extra is not None:
                row.extra, row.source, row.changed, row.template = dict(e.extra), 'extra', True, e.wire
                row.editable, row.reason = False, 'An extra line you typed: remove it and add it again to change it.'
                row.uid = e.extra.get('uid')
                if e.op == 'write' and i < len(entries) and entries[i].extra is not None and entries[i].op == 'query' \
                        and entries[i].extra.get('uid') == e.extra.get('uid'):
                    row.readback_wire = entries[i].wire
                    used.add(i)
                rows.append(row)
                continue
            cmd = self._registry(e.driver).get(e.key) if e.key else None
            row.factory_template = cmd.template if cmd else ''
            row.placeholders = sorted(cmd.placeholders) if cmd else []
            row.vals = dict(e.vals)
            row.changed = e.changed
            row.template = row.factory_template
            pt = f'{e.driver}:{e.key}@{self.key}' if e.key else ''
            wide = f'{e.driver}:{e.key}' if e.key else ''
            if pt in ov:
                row.source, row.uid, row.template, row.target = 'this point', ov[pt]['uid'], ov[pt]['value'].get('template', ''), pt
            elif wide in ov and e.override_uid:
                row.source, row.uid, row.template = 'all points', ov[wide]['uid'], ov[wide]['value'].get('template', '')
            if cmd is not None:
                row.readback_key = cmd.readback
                if cmd.readback and i < len(entries) and entries[i].op == 'query' and entries[i].key == cmd.readback and entries[i].extra is None:
                    row.readback_wire = entries[i].wire
                    used.add(i)
            row.target = pt
            # may this row be edited here?
            if cmd is None:
                row.reason = 'Not in the command table: the procedure sends this itself.'
            elif (e.driver, e.key) in seen:
                row.repeat_of = seen[(e.driver, e.key)]
                row.reason = f'Same command as step {row.repeat_of}: a change there applies to this one too.'
            else:
                ok, why = cmdreg.is_overridable(cmd)
                if not ok:
                    row.reason = why[0].upper() + why[1:] + '.'
                elif self.pm.verified_lock:
                    row.reason = self.pm.verified_lock
                elif why_ro:
                    row.reason = why_ro
                else:
                    row.editable = True
                seen.setdefault((e.driver, e.key), e.seq)
            if row.source == 'all points':
                row.reason = row.reason or ''
            rows.append(row)
        # staged edits show on the rows they belong to
        for r in rows:
            d = self.pm.drafts.get(('command', r.target)) if r.target else None
            if d is not None and d.action == 'set':
                r.staged = d.value.get('template')
                r.preview = self._preview(r, r.staged)
                r.changed = True
        # extra lines staged in this window and not saved yet
        for tgt in self._extra_drafts:
            d = self.pm.drafts.get(('command', tgt))
            if d is None or d.action != 'set':
                continue
            t = pdef.parse_command_target(tgt)
            x = d.value
            head = (x.get('template') or '').split(None, 1)
            r = CmdRow(0, d.driver, d.driver, 'query' if head and '?' in head[0] else 'write',
                       x.get('template', ''), None, 'Extra command', 'set', 'normal', False, template=x.get('template', ''), changed=True,
                       source='extra', target=tgt, extra={'phase': t['extra'][0], 'n': t['extra'][1], 'uid': None,
                                                          'readback': x.get('readback', ''), 'expect': x.get('expect', '')},
                       pending=True, readback_wire=x.get('readback', ''))
            r.label = self._label_of(d.driver)
            rows.append(r)
        for n, r in enumerate(rows, 1):
            if r.seq == 0:
                r.seq = n
        # pending extras go first ('before') or last ('after')
        before = [r for r in rows if r.pending and r.extra['phase'] == 'before']
        after = [r for r in rows if r.pending and r.extra['phase'] == 'after']
        mid = [r for r in rows if not r.pending]
        out = before + mid + after
        for n, r in enumerate(out, 1):
            r.seq = n
        return out

    def _label_of(self, driver) -> str:
        for e in self.plan.entries:
            if e.driver == driver:
                return e.label
        return driver

    def _preview(self, row, text) -> str:
        cmd = self._registry(row.driver).get(row.key)
        if cmd is None or text is None:
            return ''
        try:
            return cmdreg.render(dataclasses.replace(cmd, template=text), row.vals)
        except cmdreg.CmdError as exc:
            return f'(cannot be shown: {exc})'

    def row(self, seq) -> CmdRow | None:
        return next((r for r in self.rows if r.seq == seq), None)

    def check_template(self, seq, text) -> list:
        """Problems with `text` as this row's command for this point ([] = fine)."""
        r = self.row(seq)
        if r is None or r.key is None:
            return ['unknown command']
        cmd = self._registry(r.driver).get(r.key)
        return [str(p) for p in cmdreg.validate(text, cmd, r.driver)]

    def stage_command(self, seq, text) -> list:
        """Stage `text` (a template, with the command's {placeholders}) as this point's command.  Returns the problems; [] when staged (or
        when the factory text was typed back, which clears the staging)."""
        r = self.row(seq)
        if r is None:
            return ['unknown command']
        if not r.editable:
            return [r.reason or self.blocked_reason or 'this command cannot be changed']
        text = (text or '').strip()
        k = ('command', r.target)
        if text == (r.template or '').strip() and k not in self.pm.drafts:
            return []
        if text == r.factory_template:
            self.pm.drafts.pop(k, None)
            if r.source == 'this point':                             # typing the factory text back is a restore
                return self.restore_command(seq)
            self.command_problems.pop(seq, None)
            self.rebuild()
            return []
        probs = self.check_template(seq, text)
        if probs:
            self.command_problems[seq] = probs
            return probs
        self.command_problems.pop(seq, None)
        cmd = self._registry(r.driver)[r.key]
        self.pm.drafts[k] = M.Draft('command', r.target, value={'template': text}, label=f'{cmd.name or r.key} (point {self.pid})', cmd=cmd,
                                    driver=r.driver, factory=cmd.template)
        self.rebuild()
        return []

    def _is_run_entry(self, uid) -> bool:
        return any(e.get('uid') == uid for e in self.ctx.run_entries)

    def restore_command(self, seq) -> list:
        """'Restore default' for a command changed for this point (a staged edit is dropped; a saved one is removed on Apply)."""
        r = self.row(seq)
        if r is None:
            return ['unknown command']
        if r.pending:
            return self.remove_extra(seq)
        if r.source == 'all points':
            return ['This command was changed for all points in the Procedure changes window; restore it there.']
        k = ('command', r.target)
        self.pm.drafts.pop(k, None)
        self.command_problems.pop(seq, None)
        if r.source == 'this point' and r.uid:
            if not self._is_run_entry(r.uid) and not self.lock.unlocked:
                self.rebuild()
                return [SAVED_NEEDS_DEV]
            self.pm.drafts[k] = M.Draft('command', r.target, action='reset', uid=r.uid, label=f'{r.name or r.key} (point {self.pid})')
        self.rebuild()
        return []

    # ---- extra command lines ----------------------------------------------------------------------------------------------------
    def extra_drivers(self) -> list:
        """[(driver class name, label)] a line can be added to (the instruments that take part in this point)."""
        out, seen = [], set()
        for e in self.plan.entries:
            if e.driver not in seen:
                seen.add(e.driver)
                out.append((e.driver, e.label))
        if not out:
            try:
                for d in self.app.pm_scope_drivers():
                    n = type(d).__name__
                    if n not in seen:
                        seen.add(n)
                        out.append((n, getattr(d, 'label', n)))
            except Exception:
                pass
        return out

    def _next_n(self, driver, phase) -> int:
        used = set()
        for e in self.plan.entries:
            if e.extra and e.driver == driver and e.extra.get('phase') == phase:
                used.add(e.extra.get('n'))
        for e in self._overrides().values():
            t = pdef.parse_command_target(e['target'])
            if t['extra'] and t['point'] == self.key and t['driver'] == driver and t['extra'][0] == phase:
                used.add(t['extra'][1])
        for tgt in self._extra_drafts:
            t = pdef.parse_command_target(tgt)
            if t['driver'] == driver and t['extra'][0] == phase:
                used.add(t['extra'][1])
        n = 1
        while n in used:
            n += 1
        return n

    def add_extra(self, driver, phase, text, readback='', expect='') -> list:
        """Stage an extra command line for this point and instrument: sent `phase` ('before' | 'after') the point's own commands.  A write must
        name the query that reads it back and the reply that proves it (set, read back, compare; sent once, never retried)."""
        why = self.blocked_reason
        if why:
            return [why]
        if phase not in pdef.PHASES:
            return ['phase must be before or after']
        if driver not in dict(self.extra_drivers()):
            return ['that instrument does not take part in this point']
        n = self._next_n(driver, phase)
        tgt = pdef.extra_command_target(driver, phase, n, self.key)
        value = {'template': (text or '').strip(), 'readback': (readback or '').strip(), 'expect': (expect or '').strip()}
        probs = pm._extra_problems(pdef.parse_command_target(tgt), value, driver)
        if probs:
            return probs
        self.pm.drafts[('command', tgt)] = M.Draft('command', tgt, value=value, label=f'Extra command {phase} (point {self.pid})', driver=driver)
        self._extra_drafts.append(tgt)
        self.rebuild()
        return []

    def remove_extra(self, seq) -> list:
        r = self.row(seq)
        if r is None or r.extra is None:
            return ['not an extra line']
        why = self.blocked_reason
        if why and not r.pending:
            return [why]
        if not r.pending and not self.lock.unlocked and not self._is_run_entry(r.uid):
            return [SAVED_NEEDS_DEV]
        k = ('command', r.target)
        if r.pending:
            self.pm.drafts.pop(k, None)
            if r.target in self._extra_drafts:
                self._extra_drafts.remove(r.target)
        else:
            tgt = next((t for t, e in self._overrides().items() if e['uid'] == r.uid), None)
            if tgt is None:
                return ['that extra line is no longer saved']
            self.pm.drafts[('command', tgt)] = M.Draft('command', tgt, action='reset', uid=r.uid, label=f'Extra command (point {self.pid})')
            r.target = tgt
        self.rebuild()
        return []

    # ---- testing -------------------------------------------------------------------------------------------------------------------
    def test_info(self, seq) -> tuple:
        """(available, text): 'Test command' is offered only if the engine supplies one; otherwise the row says it is not tested."""
        if self.ctx.test_command is None:
            return False, NOT_TESTED
        return False, 'Not tested (commands cannot be tried while the procedure is open)'

    # ------------------------------------------------------------------ developer-mode fields
    def _field_spec(self) -> dict:
        try:
            return self.app.pm_point_fields(self.view)
        except Exception:
            return {}

    def _build_fields(self):
        keep = {n: f.staged for n, f in self.fields.items() if f.staged is not None}
        self.fields = {}
        p, v = self.live_point, self.view
        if p is None or v is None:
            return
        spec = self._field_spec()
        unit = str(pdef.get_path(p, 'unit') or p.get('base_unit') or '')
        why = self.read_only_reason
        fac = pm.limit_factory(v)
        ov = self.pm.oset.limit_override(self.key) if self.pm.oset else None
        ovv = (ov or {}).get('value') or {}
        fdef = (ovv.get('factory') or {}).get('def') or {}
        for name in ('description', 'nominal', 'unit'):
            s = spec.get(name) or {'paths': [], 'reason': 'not available', 'note': ''}
            paths = s.get('paths') or []
            f = FieldState(name, FIELD_LABELS[name], unit=unit if name == 'nominal' else '')
            if name == 'description':
                f.effective = self.app.pm_point_title(p)
                f.factory = fdef.get('description') if 'description' in fdef and fdef['description'] else self.app.pm_point_title(v)
            else:
                cur = pdef.get_path(p, paths[0]) if paths else None
                orig = pdef.get_path(v, paths[0]) if paths else None
                f.effective = pdef.dec_text(cur) if name == 'nominal' else _text(cur)
                f.factory = pdef.dec_text(fdef.get(name, orig)) if name == 'nominal' else _text(fdef.get(name, orig))
            f.note = s.get('note') or ''
            f.reason = s.get('reason') or ''
            f.editable = not f.reason and not why
            if not f.reason and why:
                f.reason = why
            self.fields[name] = f
        lim_note = ''
        for name in ('error', 'low', 'high'):
            if (name == 'error') != (fac['mode'] == 'error'):
                continue
            f = FieldState(name, FIELD_LABELS[name], unit=unit if fac['mode'] == 'error' else '')
            if fac['mode'] == 'error':
                f.factory = _text((ovv.get('factory') or fac).get('error'))
                f.effective = _text(p.get('error'))
            else:
                f.factory = _text((ovv.get('factory') or fac).get(name))
                f.effective = _text(p.get(name))
                if p.get('display_unit'):
                    f.unit = ''
                    f.note = f'in {p["display_unit"]}'
            if (fac['mode'] == 'band' and fac.get(name) is None):
                f.reason = 'this point has no ' + name + ' limit'
            elif why:
                f.reason = why
            f.editable = not f.reason
            self.fields[name] = f
        for n, text in keep.items():
            if n in self.fields:
                self.fields[n].staged = text

    def stage_field(self, name, text) -> list:
        """Stage a developer-mode field.  Returns the problems for THIS field ([] = fine so far); cross-field problems (low <= nominal <= high)
        are in `field_problems`.  Decimal-safe: the text typed is what is checked and stored."""
        f = self.fields.get(name)
        if f is None:
            return ['unknown field']
        if not f.editable:
            return [f.reason or self.read_only_reason or 'this field cannot be changed']
        text = (text or '').strip()
        probs = []
        if name in ('nominal', 'error', 'low', 'high'):
            if pdef.parse_decimal(text) is None:
                probs.append(f'{f.label} must be a finite number')
            elif name == 'error' and pdef.parse_decimal(text) <= 0:
                probs.append('the +/- error must be a positive number')
        elif name == 'unit':
            probs += pdef.check_unit(f.factory, text)
        elif name == 'description':
            probs += pdef.check_description(text)
        f.problems = probs
        f.staged = None if (not probs and _same(name, text, f.effective)) else text
        if probs:
            f.staged = text
        self._rebuild_limit()
        return probs

    def restore_field(self, name):
        """'Restore default' for one developer field: back to the manufacturer / spec value."""
        f = self.fields.get(name)
        if f is None or not f.editable:
            return
        f.problems = []
        f.staged = None if _same(name, f.factory, f.effective) else f.factory
        self._rebuild_limit()

    def _want(self) -> dict:
        return {n: f.text for n, f in self.fields.items()}

    def _rebuild_limit(self):
        """Turn the staged fields into ONE limit draft built from the full effective state (tolerance + nominal / unit / description)."""
        k = ('limit', self.key)
        existing = self.pm.drafts.get(k)
        if existing is not None:
            self.pm.drafts.pop(k, None)
        self.field_problems = []
        if not self.fields or not any(f.staged is not None for f in self.fields.values()):
            return
        if any(f.problems for f in self.fields.values()):
            return
        v = self.view
        fac = pm.limit_factory(v)
        want = self._want()
        spec = self._field_spec()
        value = {'mode': fac['mode']}
        if fac['mode'] == 'error':
            value['error'] = want['error']
        else:
            value['low'], value['high'] = want.get('low'), want.get('high')
        fields = {}
        for name, key in (('nominal', 'nominal'), ('unit', 'new_unit'), ('description', 'description')):
            f = self.fields.get(name)
            if f is None or not f.editable:
                continue
            if f.changed or (f.staged is not None and f.dirty):
                value[key] = want[name]
                fields[name] = list((spec.get(name) or {}).get('paths') or [])
        if fields:
            value['fields'] = fields
        probs = pm.check_limit_value(v, dict(value)) + pm.check_point_definition(v, dict(value))
        if probs:
            self.field_problems = probs
            return
        same_tol = all(pm._same_num(value.get(a), fac.get(a)) for a in ('error', 'low', 'high'))
        existing_ov = self.pm.oset.limit_override(self.key) if self.pm.oset else None
        if same_tol and not fields:                                  # everything is back at the manufacturer value
            if existing_ov is not None:
                self.pm.drafts[k] = M.Draft('limit', self.key, action='reset', uid=existing_ov['uid'], label=self._plabel())
            return
        tol_or_nom = (not same_tol) or ('nominal' in value) or (existing_ov is not None and self._existing_moves_judging(existing_ov))
        self.pm.drafts[k] = M.Draft('limit', self.key, value=value, point=v, label=self._plabel(), forces_redo=bool(tol_or_nom))

    def _existing_moves_judging(self, ov) -> bool:
        return False

    def _plabel(self) -> str:
        return f'Point {self.pid}'

    # ------------------------------------------------------------------ what Apply would do
    def limit_draft(self):
        return self.pm.drafts.get(('limit', self.key))

    @property
    def judging_changes(self) -> bool:
        """True when what is staged changes how the point is judged (tolerance or nominal), including restoring them."""
        d = self.limit_draft()
        if d is None:
            return False
        if d.action == 'reset':
            ov = self.pm.oset.limit_override(self.key) if self.pm.oset else None
            val = (ov or {}).get('value') or {}
            return pm.tolerance_changed(val) or any(c[0] == 'nominal' for c in pm.definition_changes(val))
        return d.forces_redo is not False

    @property
    def redo_required(self) -> bool:
        return self.judging_changes and self.has_reading

    @property
    def redo_optional(self) -> bool:
        return bool(self.has_reading and not self.redo_required and self._command_or_extra_staged())

    def _command_or_extra_staged(self) -> bool:
        return any(k == 'command' for (k, _t) in self.pm.drafts)

    def set_redo(self, on):
        self.redo_chosen = bool(on)

    @property
    def redo_will_happen(self) -> bool:
        return self.redo_required or (self.redo_chosen and self.has_reading)

    @property
    def redo_problem(self) -> str:
        if self.redo_required and not self.supports_redo:
            return ('This point already has a reading and this procedure cannot redo a single point from here, so its tolerance / nominal cannot '
                    'be changed now. Clear the reading with Rerun Selected first.')
        return ''

    @property
    def needs_acknowledgement(self) -> bool:
        return self.judging_changes

    def acknowledge(self, on=True):
        self.acknowledged = bool(on)

    @property
    def dirty(self) -> bool:
        return bool(self.pm.drafts)

    def staged_summary(self) -> list:
        """Plain-text lines of what Apply will save: [(what, old, new)]."""
        out = []
        for (kind, target), d in self.pm.drafts.items():
            if kind == 'command':
                t = pdef.parse_command_target(target)
                if d.action == 'reset':
                    out.append((f'Restore default: {d.label}', '', ''))
                elif t['extra'] is not None:
                    line = d.value.get('template', '')
                    if d.value.get('readback'):
                        line += f'   (read back with {d.value["readback"]}, expect {d.value.get("expect", "")})'
                    out.append((f'Extra command, {t["extra"][0]} the point\'s own commands ({self._label_of(d.driver)})', '', line))
                else:
                    out.append((f'Command {d.label}', d.factory or '', d.value.get('template', '')))
            elif kind == 'limit':
                if d.action == 'reset':
                    out.append(('Restore the manufacturer tolerance and point definition', '', ''))
                    continue
                for name, f in self.fields.items():
                    if f.staged is not None and not f.problems:
                        out.append((FIELD_LABELS[name], f.effective, f.staged))
        return out

    def warnings(self) -> list:
        w = []
        if self.judging_changes:
            w.append(TIP_LIMIT)
        if any(k == 'command' and d.action == 'set' for (k, _t), d in self.pm.drafts.items()):
            w.append(TIP_UNVERIFIED)
        nominal = self.fields.get('nominal')
        if nominal is not None and nominal.staged is not None and nominal.note:
            w.append(nominal.note)
        if self.demo:
            w.append('DEMO: this edit applies to this demo run only and is never saved. Nothing from a demo run is evidence.')
        return w

    def effective_from_text(self) -> str:
        """When the staged changes reach the instruments."""
        if not self.pm.drafts:
            return ''
        if self.redo_will_happen:
            return ('The point is measured again at the next point boundary (the reading now on record is replaced when the new one is recorded). '
                    + self.pm.applies_from_text())
        if self.has_reading:
            return 'This point already has a reading; the change takes effect only if the point is measured again. ' + self.pm.applies_from_text()
        return self.pm.applies_from_text() or 'With the next Run.'

    # ------------------------------------------------------------------ apply
    def set_reason(self, text):
        self.reason = text or ''

    def blockers(self) -> list:
        """Everything that stops Apply right now ([] = ready)."""
        out = []
        bad = [f'{f.label}: {p}' for f in self.fields.values() for p in f.problems] + list(self.field_problems)
        if not self.pm.drafts and not bad:
            out.append('Nothing has been changed.')
            return out
        if self.blocked_reason:
            out.append(self.blocked_reason)
        elif not self.lock.unlocked and not self.pm.run_only_commands():
            out.append('Developer mode is needed for this change: only typed or edited commands for this run only can be made without it.')
        out += bad
        if not self.reason.strip():
            out.append('Enter the reason for the change.')
        if self.redo_problem:
            out.append(self.redo_problem)
        if self.needs_acknowledgement and not self.acknowledged:
            out.append('Confirm that you understand the change alters pass/fail and is recorded in the audit trail.')
        return out

    def apply(self, confirmed=False) -> M.ApplyResult:
        """Save every staged change once (the storage layer's apply: set, never retried).  Raises procmods.OverrideError / NeedsConfirmation
        like ProcModsModel.apply."""
        why = self.blockers()
        if why:
            raise pm.OverrideError('; '.join(why))
        for key in list(self.pm.drafts):
            self.pm.set_reason(key[0], key[1], self.reason.strip())
        redo = [self.key] if self.redo_will_happen else []
        res = self.pm.apply(confirmed=confirmed, redo=redo)
        if res.ok:
            self._extra_drafts.clear()
            for f in self.fields.values():
                f.staged = None
            self.reason, self.acknowledged, self.redo_chosen = '', False, False
        self.load(plan=True)
        return res

    def cancel(self):
        self.pm.cancel()
        self._extra_drafts.clear()
        for f in self.fields.values():
            f.staged = None
            f.problems = []
        self.command_problems.clear()
        self.reason, self.acknowledged, self.redo_chosen = '', False, False
        self.rebuild()

    # ------------------------------------------------------------------ plan status
    @property
    def plan_note(self) -> str:
        if self.plan.error:
            return ('The list may be incomplete: the dry run of this point stopped (' + self.plan.error + '). '
                    'It is what the simulated bench could show; a real instrument that answers differently takes the procedure\'s own error path.')
        return self.plan.note

    @property
    def plan_incomplete(self) -> bool:
        return bool(self.plan.error)

    @property
    def banner(self) -> str:
        parts = []
        if self.demo:
            parts.append('DEMO')
        w = self.app.pm_live_where() if hasattr(self.app, 'pm_live_where') else {}
        if w.get('running'):
            parts.append('Run in progress: saved changes reach the next point boundary; the point in progress is never changed.')
        return '  '.join(parts)

    def pending_saved(self) -> list:
        try:
            return [x['text'] for x in self.app.pm_state.live.pending]
        except Exception:
            return []
