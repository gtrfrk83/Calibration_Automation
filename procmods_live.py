"""Live editing inside a RUNNING procedure: the Tk-free rules (state, audit events, point lookups, the model-side bridge).

The editor itself is the existing one (procmods_ui.ModifyWindow on procmods_ui_model.ProcModsModel); nothing here edits an override.  What this
module adds is WHEN a saved edit takes effect inside a run, and what is recorded about it.

Rules (each one is tested in tests/test_beta_live_editor*.py)
  * An edit is written to the override store (scope asset / model) or to the run's in-memory entries (scope "this run only") when the
    operator presses Apply, exactly as before the run.  It does NOT reach the running procedure at that moment: the state is only marked
    `dirty`.  The engine applies it at the next POINT BOUNDARY (ProcModsMixin.pm_step), between two points, never inside a point and never
    in the middle of an instrument write sequence.  The in-flight point keeps the settings, commands, limits and prompts it started with.
  * At that boundary, before anything is rebound, the engine puts the outputs in standby (the engine's own standby call, once, not retried);
    if that fails nothing is applied and the run stops with the engine's normal error path.  The instrument reset that precedes the first
    point of a run is NOT run again.
  * Every applied revision is appended to the run's snapshot (procmods.build_snapshot), so the checkpoint, the report snapshot and
    procmods_engine.applied_modifications() list it exactly like an edit made before the run.  In addition a `live_edits` event is kept for
    each application: when, before which point, what changed (kind, target, old, new, reason, author, scope), the revision, demo flag.
  * Redo: the operator may ask for a point to be measured again with the new settings.  The point is put back in front of the run's queue
    at the boundary (the engine's own 'previous' wiring key is cleared so the setup prompt is shown again); its old reading stays until the
    new one replaces it, and the operator confirms that replacement when asking.  Nothing is retried automatically.
  * A point that has a reading, or is in progress, cannot be skipped by a live edit, and its tolerance can only be changed together with a redo
    (otherwise the report would print a tolerance the reading was not judged against).
  * Demo runs: live edits are limited to "this run only" (never written to the real override store) and are marked demo in the event.
"""
from __future__ import annotations

from datetime import datetime

import procmods


class LiveApplyError(RuntimeError):
    """The pending edits could not be applied at a point boundary (e.g. the outputs could not be confirmed in standby).  Nothing was applied;
    the engine stops the run through its normal error path."""


def point_id(p):
    return p.get('id', p.get('n')) if isinstance(p, dict) else None


def describe_point(p) -> str:
    if not isinstance(p, dict):
        return ''
    for k in ('description', 'desc', 'test', 'section_title', 'section'):
        v = p.get(k)
        if v:
            return str(v)
    return f'point {point_id(p)}'


def _iso(now=None):
    return (now or datetime.now()).isoformat(timespec='seconds')


class LiveState:
    """Per-run live-edit bookkeeping, held on procmods_engine.ModsState as `.live`."""

    def __init__(self):
        self.dirty = False                    # edits saved since the last boundary (not yet in effect)
        self.dirty_at = None
        self.events: list = []                # applied edits, oldest first (kept in the checkpoint)
        self.run_points = None                # the list the running loop walks
        self.index = -1                       # index of the point in progress
        self.cursor = None                    # (id(list), index, point id) of the point in progress
        self.redo: list = []                  # point ids to measure again at the next boundary
        self.noted: set = set()               # point ids whose technician note was shown in this run
        self.pending: list = []               # [{'text', 'at'}] saved edits waiting for the boundary (for the editor's banner)

    def start_run(self, points=None):
        self.dirty, self.dirty_at = False, None
        self.run_points, self.index, self.cursor = points, -1, None
        self.redo = []
        self.noted = set()
        self.pending = []

    def mark_saved(self, text='', now=None):
        self.dirty = True
        self.dirty_at = self.dirty_at or _iso(now)
        if text:
            self.pending.append({'text': text, 'at': _iso(now)})

    def request_redo(self, ids):
        for i in ids:
            if i is not None and i not in self.redo:
                self.redo.append(i)


# ------------------------------------------------------------------------------------------------------------ what changed
def _by_uid(oset):
    return {e['uid']: e for e in (oset.active() if oset else [])}


def _value_text(e):
    v = e.get('value') or {}
    k = e.get('kind')
    if k == 'command':
        return v.get('template', '')
    if k == 'param':
        return str(v.get('value'))
    if k == 'point':
        return 'skipped'
    if k == 'text':
        return v.get('text', '')
    if k == 'limit':
        return ', '.join(f'{a}={v[a]}' for a in ('error', 'low', 'high') if v.get(a) is not None)
    return ''


def _factory_text(e):
    v = e.get('value') or {}
    f = v.get('factory')
    if e.get('kind') == 'limit' and isinstance(f, dict):
        return ', '.join(f'{a}={f[a]}' for a in ('error', 'low', 'high') if f.get(a) is not None)
    return '' if f is None else str(f)


def diff_sets(old, new) -> list:
    """What differs between two OverrideSets (active entries): [{'action': 'added'|'changed'|'removed', kind, target, label, scope, old, new,
    reason, author, at, uid}].  `old` / `new` may be None or empty."""
    a, b = _by_uid(old), _by_uid(new)
    out = []
    old_by_target = {(e['kind'], e['target']): e for e in a.values()}
    new_by_target = {(e['kind'], e['target']): e for e in b.values()}
    for uid, e in b.items():
        if uid in a:
            continue
        before = old_by_target.get((e['kind'], e['target']))
        out.append({'action': 'changed' if before else 'added', 'kind': e['kind'], 'target': e['target'],
                    'label': (e.get('value') or {}).get('label') or e['target'], 'scope': e.get('scope', ''),
                    'old': _value_text(before) if before else _factory_text(e), 'new': _value_text(e), 'reason': e.get('reason', ''),
                    'author': e.get('author', ''), 'at': e.get('created_at', ''), 'uid': uid})
    for uid, e in a.items():
        if uid in b or (e['kind'], e['target']) in new_by_target:
            continue
        out.append({'action': 'removed', 'kind': e['kind'], 'target': e['target'], 'label': (e.get('value') or {}).get('label') or e['target'],
                    'scope': e.get('scope', ''), 'old': _value_text(e), 'new': _factory_text(e), 'reason': e.get('reason', ''),
                    'author': e.get('author', ''), 'at': e.get('created_at', ''), 'uid': uid})
    return out


def make_event(old, new, *, rev=0, before=None, demo=False, standby=None, now=None) -> dict | None:
    """The audit record of one application at a boundary; None when the effective set did not change."""
    changes = diff_sets(old, new)
    if not changes:
        return None
    return {'at': _iso(now), 'rev': rev, 'hash': new.hash if new else '', 'before_point': (before or {}).get('id'),
            'before_desc': (before or {}).get('desc', ''), 'demo': bool(demo), 'standby_confirmed': standby, 'changes': changes}


def event_line(ev) -> str:
    """One line for the command log / status bar."""
    parts = [f'{c["action"]} {c["label"]}: {c["old"]} -> {c["new"]}' for c in ev['changes']]
    when = (f'applied before point {ev["before_point"]}' if ev.get('before_point') is not None
            else 'applied while no point was running (effective with the next point / Run)')
    return f'LIVE EDIT rev {ev["rev"]}' + (' [DEMO]' if ev.get('demo') else '') + f' {when}: ' + '; '.join(parts)


# ------------------------------------------------------------------------------------------------------------ the model's view of a run
class LiveBridge:
    """What procmods_ui_model.Context.live is: how the editor sees the running procedure.  Everything is a callable supplied by the engine
    (procmods_engine.ProcModsMixin.pm_live_context), so the model stays Tk-free and testable with a fake."""

    def __init__(self, *, where, locked_keys, blocked, saved, redo, running, supports_skip=True, supports_redo=True, pending=None):
        self._where, self._locked, self._blocked, self._saved, self._redo, self._running = where, locked_keys, blocked, saved, redo, running
        self._pending = pending
        self.supports_skip = supports_skip
        self.supports_redo = supports_redo

    def where(self) -> dict:
        return self._where()

    def locked_keys(self) -> set:
        """Point keys (procmods.point_key) that already have a reading in the data set being collected, or are in progress."""
        try:
            return set(self._locked())
        except Exception:
            return set()

    def blocked_reason(self) -> str:
        try:
            return self._blocked() or ''
        except Exception:
            return 'live editing is not available right now'

    def saved(self, texts) -> None:
        self._saved(list(texts))

    def request_redo(self, keys) -> None:
        self._redo(list(keys))

    def pending(self) -> list:
        """Texts of edits that were saved but have not reached the running procedure yet."""
        try:
            return list(self._pending()) if self._pending else []
        except Exception:
            return []

    def running(self) -> bool:
        try:
            return bool(self._running())
        except Exception:
            return True


def where_text(w) -> str:
    """The sentence the editor shows: which point a change applies from."""
    if not w or not w.get('running'):
        return 'No run is in progress: saved changes start with the next Run.'
    cur, nxt = w.get('current'), w.get('next')
    if w.get('generic'):
        return 'A measurement is in progress and is not changed. Saved changes start at the next point.'
    head = f'Point {cur["id"]} ({cur["desc"]}) is in progress and is not changed. ' if cur else ''
    if nxt:
        return head + f'Saved changes start at point {nxt["id"]} ({nxt["desc"]}).'
    return head + 'No further point is queued in this run: saved changes start with the next Run.'
