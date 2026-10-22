"""Controller for the 'Modify procedure' window (Tk-free, unit-tested).  procmods_ui.py builds thin widgets on top of this.

    lock  = DevLock(devmode)                       # passphrase unlock / first-use / 15-minute idle auto-lock / lock-out delay
    model = ProcModsModel(Context(...), lock)      # rows for every tab, drafts, validation, test, apply, import / export

Everything is READ-ONLY until `lock` is unlocked (and no run is in progress): the model refuses to stage or apply otherwise, and the
store (procmods.Store) refuses again without a devmode session, so a UI bug cannot bypass the gate.

Edits are staged as drafts (nothing is written until `apply()`): Undo drops a draft, Reset stages "back to factory" (the stored row
stays for the audit trail, it is only disabled).  Writes are made exactly once; a failed write is reported and never retried.

Passphrases are handled only inside DevLock.unlock / first_use and handed straight to devmode; they are never stored on the object,
logged, put in a message, or returned.
"""
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from datetime import datetime

import cmdreg
import devmode as dev
import procmods as pm

TABS = ('Commands', 'Settings', 'Points', 'Text', 'Tolerances', 'Changes')
SCOPE_LABELS = {'run': 'This run only', 'asset': 'This asset', 'model': 'All of this model'}
TEST_NOTE = ('A query is sent once and the reply and the error queue are shown. Nothing is retried. The simulator only confirms that the '
             'command has the right shape for the simulator; whether the real instrument accepts it is UNVERIFIED until tested on hardware.')


def chip_text(count) -> str:
    """Header chip: 'MODIFIED (3)', or '' when nothing is modified."""
    return f'MODIFIED ({int(count)})' if count else ''


def devmode_chip_text(unlocked) -> str:
    return 'DEVELOPER MODE' if unlocked else ''


def row_badges(row) -> list:
    """Badge codes for a list row: 'M' modified (amber), '!' unverified, 'S' stale, 'lock' locked."""
    out = []
    if row.get('modified') or row.get('state') == 'modified':
        out.append('M')
    if row.get('state') == 'stale':
        out.append('S')
    if row.get('unverified'):
        out.append('!')
    if row.get('locked'):
        out.append('lock')
    return out


def count_for_model(store, model, asset_id='') -> int:
    """Enabled overrides that would apply to this model (and asset, if given): the Manager's badge.  Never raises."""
    try:
        n = 0
        for e in store.candidates(model, asset_id):
            n += 1
        return n
    except Exception:
        return 0


def model_counts(store) -> dict:
    """{lower-case model: number of enabled model-wide overrides}: one query for the Manager's list badges.  Never raises."""
    out = {}
    try:
        for e in store.entries(heads_only=True, enabled=True):
            if e['scope'] == 'model' and e['model']:
                out[e['model'].casefold()] = out.get(e['model'].casefold(), 0) + 1
    except Exception:
        pass
    return out


# ------------------------------------------------------------------------------------------------------------ developer lock
@dataclass
class LockResult:
    ok: bool
    message: str = ''
    wait_s: float = 0.0
    state: str = ''


class DevLock:
    """UI-free wrapper around devmode: remembers the session, detects idle auto-lock, reports the lock-out delay."""

    def __init__(self, devmode=None, clock=time.monotonic):
        self.devmode = devmode or dev.DevMode()
        self._clock = clock
        self.session = None
        self._listeners = []
        self._last_state = None

    def on_change(self, fn):
        self._listeners.append(fn)

    def _notify(self):
        st = self.state
        if st != self._last_state:
            self._last_state = st
            for fn in list(self._listeners):
                try:
                    fn(st)
                except Exception:
                    pass

    @property
    def state(self) -> str:
        """'unset' (no passphrase yet) | 'locked' | 'lockout' (waiting after wrong passphrases) | 'unlocked'."""
        if self.session is not None and self.session.valid():
            return 'unlocked'
        if not self.devmode.is_set():
            return 'unset'
        return 'lockout' if self.devmode.lockout_remaining() > 0 else 'locked'

    @property
    def unlocked(self) -> bool:
        return self.state == 'unlocked'

    @property
    def remaining_s(self) -> float:
        return self.session.remaining_s if self.session is not None else 0.0

    def lockout_text(self) -> str:
        w = self.devmode.lockout_remaining()
        return f'Too many wrong passphrases. Try again in {int(w) + 1} s.' if w > 0 else ''

    def poll(self) -> str:
        """Call on a timer: notices the idle auto-lock and a finished lock-out; returns the state."""
        st = self.state
        if st != 'unlocked' and self.session is not None:
            self.session = None
        self._notify()
        return st

    def touch(self):
        if self.session is not None:
            self.session.touch()

    def lock(self):
        if self.session is not None:
            self.session.lock()
            self.session = None
        self._notify()

    def first_use(self, passphrase, confirm) -> LockResult:
        if self.devmode.is_set():
            return LockResult(False, 'A passphrase is already set.', state=self.state)
        if passphrase != confirm:
            return LockResult(False, 'The two entries do not match.', state=self.state)
        try:
            self.session = self.devmode.set_passphrase(passphrase)
        except dev.DevModeError as ex:
            return LockResult(False, str(ex), state=self.state)
        self._notify()
        return LockResult(True, 'Passphrase set. Developer mode is unlocked.', state='unlocked')

    def unlock(self, passphrase) -> LockResult:
        try:
            self.session = self.devmode.unlock(passphrase)
        except dev.LockedOut as ex:
            return LockResult(False, str(ex), wait_s=ex.wait_s, state='lockout')
        except dev.BadPassphrase:
            wait = self.devmode.lockout_remaining()
            msg = 'Wrong passphrase.' + (f' Locked out for {int(wait) + 1} s.' if wait > 0 else '')
            self._notify()
            return LockResult(False, msg, wait_s=wait, state=self.state)
        except dev.DevModeError as ex:
            return LockResult(False, str(ex), state=self.state)
        self._notify()
        return LockResult(True, 'Developer mode unlocked.', state='unlocked')


# ------------------------------------------------------------------------------------------------------------ context / drafts
@dataclass
class Context:
    title: str = 'Procedure'
    model: str = ''
    asset_id: str = ''
    demo: bool = False
    registries: dict = field(default_factory=dict)      # {driver class name: {key: cmdreg.Cmd}}
    points: list = field(default_factory=list)          # the factory point list of the running spec
    defaults: dict = field(default_factory=dict)        # {tunable name: factory default}
    texts: dict = field(default_factory=dict)           # {'setup:<point>' / 'prompt:<name>' ...: factory text}
    store: object = None                                # procmods.Store
    idn: object = None                                  # str or callable -> *IDN? of the connected instrument (None: not connected)
    test_command: object = None                         # callable(driver, key, text) -> {'ok','reply','errors','idn'}; supplied by the engine
    is_running: object = None                           # callable -> bool
    author: str = ''
    run_entries: list = field(default_factory=list)     # in-memory 'run' scope entries (the engine passes them to resolve())


@dataclass
class Draft:
    kind: str
    target: str
    action: str = 'set'                                 # 'set' | 'reset'
    value: dict = field(default_factory=dict)
    label: str = ''
    factory: object = None
    cmd: object = None
    driver: str = ''
    point: dict | None = None
    tested: dict | None = None
    uid: str | None = None                              # for 'reset': the stored override (or run entry) uid


@dataclass
class Check:
    problems: list
    changed: bool

    @property
    def valid(self) -> bool:
        return not self.problems


@dataclass
class ApplyResult:
    done: list = field(default_factory=list)
    errors: list = field(default_factory=list)          # [(draft key, message)]

    @property
    def ok(self) -> bool:
        return not self.errors


class NeedsConfirmation(Exception):
    """Asset / model scope edits need an explicit confirmation (UI asks, then calls apply(confirmed=True))."""

    def __init__(self, items):
        super().__init__('asset-wide or model-wide changes need confirmation')
        self.items = items


class ProcModsModel:
    def __init__(self, ctx: Context, lock: DevLock, now=datetime.now):
        self.ctx = ctx
        self.lock = lock
        self.store = ctx.store or pm.Store(devmode=lock.devmode)
        self._now = now
        self.scope = 'run'
        self.drafts: dict = {}
        self.reasons: dict = {}
        self.test_results: dict = {}
        self._testing = False
        self.oset = None
        self.refresh()

    # ------------------------------------------------------------------ state
    def idn(self):
        i = self.ctx.idn
        return i() if callable(i) else i

    def running(self) -> bool:
        try:
            return bool(self.ctx.is_running and self.ctx.is_running())
        except Exception:
            return True                                  # cannot tell: treat as running (read-only)

    @property
    def read_only_reason(self) -> str:
        if self.running():
            return 'A run is in progress. Stop the run to edit.'
        if not self.lock.unlocked:
            return 'Read-only. Unlock developer mode to make changes.'
        return ''

    @property
    def editable(self) -> bool:
        return not self.read_only_reason

    def refresh(self):
        self.oset = pm.resolve(self.ctx.model, self.ctx.asset_id, run_overrides=self.ctx.run_entries, idn=self.idn(), store=self.store)
        return self.oset

    def modified_count(self) -> int:
        return len(self.oset.active()) if self.oset else 0

    def chip(self) -> str:
        return chip_text(self.modified_count())

    @property
    def dirty(self) -> bool:
        return bool(self.drafts)

    def set_scope(self, scope):
        if scope not in pm.SCOPES:
            raise ValueError('unknown scope')
        if scope == 'asset' and not self.ctx.asset_id:
            raise ValueError('enter an instrument ID first')
        if scope == 'model' and not self.ctx.model:
            raise ValueError('no model is known')
        self.scope = scope

    def _need_edit(self):
        if not self.editable:
            raise pm.OverrideError(self.read_only_reason)
        self.lock.touch()

    # ------------------------------------------------------------------ rows
    def _decorate(self, rows, kind):
        for r in rows:
            d = self.drafts.get((kind, r.get('target') or r['key']))
            r['draft'] = d is not None
            if d is not None:
                r['staged'] = 'reset' if d.action == 'reset' else 'edit'
            r['badges'] = row_badges(r)
        return rows

    def commands(self, filter='all', search=''):
        return self._decorate(pm.rows(self.ctx.registries, self.oset, filter, search), 'command')

    def settings(self, filter='all', search=''):
        return self._decorate(pm.setting_rows(self.oset, self.ctx.defaults, filter, search), 'param')

    def points(self, filter='all', search=''):
        return self._decorate(pm.point_rows(self.ctx.points, self.oset, filter, search), 'point')

    def texts(self, filter='all', search=''):
        out = []
        needle = (search or '').casefold()
        for key, factory in sorted(self.ctx.texts.items()):
            locked = bool(pm.LOCKED_TEXT.match(key.partition(':')[2]))
            e = next((x for x in self.oset.active('text') if x['target'] == key), None)
            cur = self.oset.text(key, factory)
            state = 'locked' if locked else 'modified' if e and cur != factory else 'factory'
            row = {'key': key, 'name': key, 'factory': factory, 'current': cur, 'state': state, 'modified': state == 'modified',
                   'locked': locked, 'lock_reason': 'Safety prompt: locked' if locked else '', 'unverified': False,
                   'uid': e['uid'] if e else None}
            if needle and needle not in f'{key} {factory} {cur}'.casefold():
                continue
            if filter == 'modified' and state != 'modified':
                continue
            if filter in ('unverified',) or (filter == 'locked' and not locked):
                continue
            out.append(row)
        return self._decorate(out, 'text')

    def tolerances(self, filter='all', search=''):
        out = []
        needle = (search or '').casefold()
        for p, k in zip(self.ctx.points, pm.point_keys(self.ctx.points)):
            fac = pm.limit_factory(p)
            if fac['mode'] == 'band' and fac['low'] is None and fac['high'] is None:
                continue
            e = self.oset.limit_override(k)
            unit = p.get('unit', '')
            man = pm._tolerance_text(fac, fac, unit)[0]
            used = pm._tolerance_text(fac, e['value'], unit)[1] if e else man
            name = p.get('description') or p.get('desc') or k
            row = {'key': k, 'target': k, 'name': name, 'factory': man, 'current': used, 'state': 'modified' if e else 'factory',
                   'modified': bool(e), 'mode': fac['mode'], 'unit': unit, 'locked': False, 'lock_reason': '', 'unverified': False,
                   'uid': e['uid'] if e else None,
                   'note': 'Pass/fail logic and the manufacturer limits are not changed; the report states the tolerance used.'}
            if needle and needle not in f'{k} {name}'.casefold():
                continue
            if filter == 'modified' and not e:
                continue
            if filter in ('unverified', 'locked'):
                continue
            out.append(row)
        tampered = {t['target'] for t in self.oset.tampered()}
        for r in out:
            r['tampered'] = r['key'] in tampered
        return self._decorate(out, 'limit')

    def changes(self):
        rows = pm.changes(self.oset, self.ctx.points, self.ctx.registries, self.ctx.defaults)
        for r in rows:
            r['badges'] = (['M'] if r['status'] == 'active' else []) + (['!'] if r['unverified'] else []) + (['S'] if r['status'] == 'stale' else [])
            r['tampered'] = r['status'] == 'tampered'
        return rows

    def tab_counts(self) -> dict:
        """Numbers for the tab headings, e.g. 'Changes (3)'."""
        n = {t: 0 for t in TABS}
        for e in self.oset.active():
            n[{'command': 'Commands', 'param': 'Settings', 'point': 'Points', 'text': 'Text', 'limit': 'Tolerances'}[e['kind']]] += 1
        n['Changes'] = len(self.oset.entries())
        return n

    def visible_tabs(self) -> list:
        have = {'Commands': bool(self.ctx.registries), 'Settings': bool(self.ctx.defaults), 'Points': bool(self.ctx.points),
                'Text': bool(self.ctx.texts), 'Tolerances': bool(self.ctx.points), 'Changes': True}
        return [t for t in TABS if have[t]]

    # ------------------------------------------------------------------ command detail (the editor pane)
    def _cmd(self, target):
        name, _, key = target.partition(':')
        return name, key, (self.ctx.registries.get(name) or {}).get(key)

    def command_detail(self, target) -> dict:
        name, key, cmd = self._cmd(target)
        if cmd is None:
            return {'found': False}
        ok, why = cmdreg.is_overridable(cmd)
        row = next((r for r in pm.rows({name: self.ctx.registries[name]}, self.oset) if r['key'] == key), None) or {}
        d = self.drafts.get(('command', target))
        text = d.value.get('template') if d is not None and d.action == 'set' else row.get('current', cmd.template)
        ph = {n: {'type': p.type, 'fmt': p.fmt, 'required': p.required, 'sample': p.sample} for n, p in cmd.placeholders.items()}
        can, why_test = self.can_test(target)
        res = self.test_results.get(target)
        badges = row_badges(row) if row else []
        if d is not None:
            badges = sorted(set(badges + ['M']), key=['M', 'S', '!', 'lock'].index)
        return {'found': True, 'target': target, 'driver': name, 'key': key, 'name': cmd.name or key, 'description': cmd.description,
                'factory': cmd.template, 'current': text, 'applied': row.get('current', cmd.template),
                'kind': cmd.kind, 'risk': cmd.risk, 'verified': cmd.verified, 'ref': cmd.ref,
                'editable': ok and self.editable, 'lock_reason': why if not ok else self.read_only_reason,
                'locked': not ok, 'placeholders': ph, 'readback': cmd.readback,
                'paired': (self.ctx.registries[name].get(cmd.readback).template if cmd.readback and cmd.readback in self.ctx.registries[name] else None),
                'badges': badges, 'state': row.get('state', 'factory'), 'uid': row.get('uid'), 'stored_reason': row.get('reason', ''),
                'draft': d is not None, 'reason': self.reasons.get(('command', target), ''),
                'can_test': can, 'test_reason': why_test, 'test_result': res,
                'tested': bool(res and res.get('ok') and res.get('text') == text),
                'status': self.command_status(target, text)}

    def command_status(self, target, text) -> str:
        """The line under the editor: 'Valid.  Not yet tested' / problems."""
        chk = self.check_command(target, text)
        if chk.problems:
            return chk.problems[0]
        res = self.test_results.get(target)
        tested = bool(res and res.get('ok') and res.get('text') == text)
        return ('Valid.' if chk.changed else 'Same as factory.') + ('  Tested OK.' if tested else '  Not yet tested.')

    def check_command(self, target, text) -> Check:
        name, key, cmd = self._cmd(target)
        if cmd is None:
            return Check(['unknown command'], False)
        ok, why = cmdreg.is_overridable(cmd)
        if not ok:
            return Check([why], False)
        if text == cmd.template:
            return Check([], False)
        probs = [str(p) for p in cmdreg.validate(text, cmd, name)]
        return Check(probs, True)

    # ------------------------------------------------------------------ staging
    def _key(self, kind, target):
        return (kind, target)

    def set_reason(self, kind, target, reason):
        self.reasons[(kind, target)] = reason or ''

    def stage_command(self, target, text) -> Check:
        self._need_edit()
        chk = self.check_command(target, text)
        k = ('command', target)
        if chk.problems or not chk.changed:
            self.drafts.pop(k, None)                     # invalid, or the factory text typed back: nothing is staged
            return chk
        name, key, cmd = self._cmd(target)
        res = self.test_results.get(target)
        tested = None
        if res and res.get('ok') and res.get('text') == text:
            tested = {'at': res['at'], 'idn': res.get('idn'), 'result': res.get('reply')}
        self.drafts[k] = Draft('command', pm.command_target(name, key), value={'template': text}, label=cmd.name or key, cmd=cmd,
                               driver=name, factory=cmd.template, tested=tested)
        return chk

    def stage_param(self, name, value, point_key=None) -> list:
        self._need_edit()
        target = f'{name}@{point_key}' if point_key else name
        probs = pm._check_param_value(name, value)
        spec = pm.PARAMS.get(name)
        if spec is None:
            return [f'unknown setting {name!r}']
        if point_key and not spec['per_point']:
            probs.append(f'{name} cannot be set for a single point')
        factory = self.ctx.defaults.get(name)
        if probs:
            return probs
        same = pm._same_num(value, factory) if isinstance(factory, (int, float)) and not isinstance(factory, bool) else value == factory
        if same:
            self.drafts.pop(('param', target), None)
            return []
        self.drafts[('param', target)] = Draft('param', target, value={'value': value}, label=spec['label'], factory=factory)
        return []

    def stage_skip(self, point_key, skip=True) -> list:
        self._need_edit()
        p = self._point(point_key)
        if p is None:
            return ['unknown point']
        k = ('point', point_key)
        if not skip:
            if self.oset.point_override(point_key):
                return self.stage_reset('point', point_key)
            self.drafts.pop(k, None)
            return []
        self.drafts[k] = Draft('point', point_key, value={'skip': True}, point=p, label=p.get('description') or p.get('desc') or point_key)
        return []

    def stage_text(self, key, text) -> list:
        self._need_edit()
        factory = self.ctx.texts.get(key)
        probs = pm._check_text(key, text)
        if factory is None:
            probs.append('unknown text item')
        if probs:
            return probs
        if text == factory:
            self.drafts.pop(('text', key), None)
            return []
        self.drafts[('text', key)] = Draft('text', key, value={'text': text}, label=key, factory=factory)
        return []

    def _point(self, key):
        for p, k in zip(self.ctx.points, pm.point_keys(self.ctx.points)):
            if k == key:
                return p
        return None

    def stage_limit(self, point_key, **vals) -> list:
        """vals: error=... (a +/- point) or low=..., high=... (a band point).  Developer mode only (as everything here)."""
        self._need_edit()
        p = self._point(point_key)
        if p is None:
            return ['unknown point']
        fac = pm.limit_factory(p)
        value = {'mode': fac['mode']}
        value.update({k: v for k, v in vals.items() if k in ('error', 'low', 'high')})
        probs = pm.check_limit_value(p, value)
        if probs:
            return probs
        if all(pm._same_num(value.get(k), fac.get(k)) for k in ('error', 'low', 'high')):
            self.drafts.pop(('limit', point_key), None)
            return []
        self.drafts[('limit', point_key)] = Draft('limit', point_key, value=value, point=p,
                                                  label=p.get('description') or p.get('desc') or point_key)
        return []

    def undo(self, kind, target):
        """Drop a staged edit (and its reason)."""
        self.drafts.pop((kind, target), None)
        self.reasons.pop((kind, target), None)

    def _existing(self, kind, target):
        """The override currently in effect for an item (run entry first, then stored heads), as an entry dict."""
        for e in self.oset.active(kind):
            if e['target'] == target:
                return e
        return None

    def stage_reset(self, kind, target) -> list:
        """Back to factory for one item: drops a staged edit; when an override is in effect, stages its removal."""
        self._need_edit()
        self.drafts.pop((kind, target), None)
        e = self._existing(kind, target)
        if e is not None:
            self.drafts[(kind, target)] = Draft(kind, target, action='reset', uid=e['uid'], label=e['value'].get('label') or target)
        return []

    def stage_reset_all(self) -> int:
        self._need_edit()
        self.drafts.clear()
        n = 0
        for e in self.oset.active():
            self.drafts[(e['kind'], e['target'])] = Draft(e['kind'], e['target'], action='reset', uid=e['uid'],
                                                          label=e['value'].get('label') or e['target'])
            n += 1
        return n

    def cancel(self):
        self.drafts.clear()
        self.reasons.clear()

    # ------------------------------------------------------------------ test command
    def can_test(self, target):
        name, key, cmd = self._cmd(target)
        if cmd is None:
            return False, 'unknown command'
        if self.ctx.demo:
            return False, 'Not available in demo mode.'
        if self.ctx.test_command is None or self.idn() in (None, ''):
            return False, 'No instrument is connected.'
        if cmd.risk != 'normal' or cmd.kind != 'query':
            return False, 'Only read-only queries can be tested here.'
        if not self.editable:
            return False, self.read_only_reason
        if self._testing:
            return False, 'A test is already running.'
        return True, ''

    def test_command(self, target, text=None) -> dict:
        """Send the (edited) query ONCE through the engine's callable.  Never retried; press again to repeat."""
        ok, why = self.can_test(target)
        if not ok:
            return {'ok': False, 'message': why}
        name, key, cmd = self._cmd(target)
        text = text if text is not None else self.command_detail(target)['current']
        probs = self.check_command(target, text).problems
        if probs:
            return {'ok': False, 'message': probs[0]}
        samples = {n: cmdreg._default_sample(p) for n, p in cmd.placeholders.items()}
        try:
            rendered = cmdreg.render(dataclasses.replace(cmd, template=text), samples)
        except cmdreg.CmdError as ex:
            return {'ok': False, 'message': str(ex)}
        self._testing = True
        self.lock.touch()
        try:
            raw = self.ctx.test_command(name, key, rendered) or {}
            res = {'ok': bool(raw.get('ok')), 'reply': str(raw.get('reply', '')), 'errors': raw.get('errors', ''), 'idn': raw.get('idn') or self.idn(),
                   'sent': rendered}
            if res['ok'] and res['errors'] not in ('', None, [], '0,"No error"', '+0,"No error"'):
                res['ok'] = False
                res['message'] = f'The instrument reported an error: {res["errors"]}'
        except Exception as ex:                          # the callable's failure is shown, not retried
            res = {'ok': False, 'reply': '', 'errors': '', 'idn': self.idn(), 'sent': rendered, 'message': f'Test failed: {type(ex).__name__}: {ex}'}
        finally:
            self._testing = False
        res['text'] = text
        res['at'] = self._now().isoformat(timespec='seconds')
        self.test_results[target] = res
        d = self.drafts.get(('command', target))
        if d is not None and d.value.get('template') == text:
            d.tested = {'at': res['at'], 'idn': res['idn'], 'result': res['reply']} if res['ok'] else None
        return res

    # ------------------------------------------------------------------ apply
    def pending(self) -> list:
        """Staged items for the confirmation / review list."""
        out = []
        for (kind, target), d in self.drafts.items():
            out.append({'kind': kind, 'target': target, 'action': d.action, 'label': d.label or target, 'factory': d.factory,
                        'value': d.value, 'reason': self.reasons.get((kind, target), ''), 'scope': self.scope if d.action == 'set' else '',
                        'unverified': d.kind == 'command' and not d.tested})
        return out

    def missing_reasons(self) -> list:
        return [f'{kind}:{t}' for (kind, t), _ in self.drafts.items() if not self.reasons.get((kind, t), '').strip()]

    def scope_confirmation_needed(self) -> list:
        if self.scope == 'run':
            return []
        return [p for p in self.pending() if p['action'] == 'set']

    def apply(self, confirmed=False) -> ApplyResult:
        """Write every staged item once.  Raises OverrideError when read-only or a reason is missing, NeedsConfirmation for asset /
        model scope until confirmed=True.  A failed item is reported and left staged; nothing is retried."""
        self._need_edit()
        miss = self.missing_reasons()
        if miss:
            raise pm.OverrideError('a reason is required for: ' + ', '.join(miss))
        need = self.scope_confirmation_needed()
        if need and not confirmed:
            raise NeedsConfirmation(need)
        result = ApplyResult()
        session = self.lock.session
        author = self.ctx.author or None
        for (kind, target), d in list(self.drafts.items()):
            reason = self.reasons[(kind, target)].strip()
            try:
                if d.action == 'reset':
                    self._write_reset(d, session, author)
                else:
                    self._write_set(d, reason, session, author)
                result.done.append(f'{kind}:{target}')
                del self.drafts[(kind, target)]
                self.reasons.pop((kind, target), None)
            except pm.OverrideError as ex:
                result.errors.append((f'{kind}:{target}', '; '.join(ex.problems)))
        self.refresh()
        return result

    def _write_reset(self, d, session, author):
        run = next((e for e in self.ctx.run_entries if e['uid'] == d.uid), None)
        if run is not None:
            self.ctx.run_entries.remove(run)
            return
        self.store.reset(d.uid, author, session)

    def _opts(self, d):
        o = {}
        if d.cmd is not None:
            o.update(cmd=d.cmd, driver_name=d.driver)
        if d.point is not None:
            o['point'] = d.point
        if d.factory is not None and d.kind in ('param', 'text'):
            o['factory'] = d.factory
        if d.label:
            o['label'] = d.label
        if d.tested:
            o['tested'] = d.tested
        return o

    def _write_set(self, d, reason, session, author):
        opts = self._opts(d)
        if self.scope == 'run':
            old = next((e for e in self.ctx.run_entries if e['kind'] == d.kind and e['target'] == d.target), None)
            entry = pm.make_run_entry(d.kind, d.target, d.value, reason, author=author, session=session, devmode=self.lock.devmode, **opts)
            if old is not None:
                self.ctx.run_entries.remove(old)
            self.ctx.run_entries.append(entry)
            return
        scope_kw = dict(model=self.ctx.model, asset_id=self.ctx.asset_id if self.scope == 'asset' else '')
        head = next((e for e in self.store.entries(heads_only=True, kind=d.kind)
                     if e['target'] == d.target and e['scope'] == self.scope and e['model'].casefold() == scope_kw['model'].casefold()
                     and e['asset_id'].casefold() == scope_kw['asset_id'].casefold()), None)
        if head is None:
            self.store.add(d.kind, d.target, d.value, self.scope, reason, author=author, session=session, **scope_kw, **opts)
            return
        new = self.store.edit(head['uid'], value=d.value, reason=reason, author=author, session=session, **opts)
        if not new['enabled']:
            self.store.set_enabled(new['uid'], True, author, session)

    # ------------------------------------------------------------------ import / export
    def export(self, path):
        """Write the enabled override sets for this model / asset to a *.calov.json.  Returns the notes."""
        self._need_edit()
        _, notes = pm.export_entries(self.store, path, model=self.ctx.model, asset_id=None,
                                     session=self.lock.session, who=self.ctx.author or None)
        return notes

    def import_preview(self, path) -> dict:
        """Parse a file and show what it would do; applies nothing."""
        return pm.import_preview(self.store, path, registries=self.ctx.registries, session=self.lock.session)

    def import_apply(self, preview, accept=None) -> list:
        self._need_edit()
        created = pm.apply_import(self.store, preview, who=self.ctx.author or None, session=self.lock.session, accept=accept)
        self.refresh()
        return created

    @staticmethod
    def preview_lines(preview) -> list:
        out = []
        for it in preview.get('items', []):
            e = it['entry'] if isinstance(it['entry'], dict) else {}
            state = 'problem' if it['problems'] else it['conflict'] or 'new'
            out.append({'index': it['index'], 'accept': it['accept'], 'state': state, 'kind': e.get('kind'), 'target': e.get('target'),
                        'scope': e.get('scope'), 'reason': e.get('reason'), 'problems': it['problems'],
                        'needs_devmode': it['needs_devmode']})
        return out

    def history(self, uid) -> list:
        return self.store.history(uid)
