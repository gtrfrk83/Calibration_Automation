"""Run queue for the handheld multimeter procedures (Tk-free model; the windows are in run_queue_ui.py, the run logic in run_queue_engine.py).

A queue lists several meters of the SAME model (asset number, serial, technician).  Two ways to run them:

  point by point   all meters are wired to the calibrator together; each point is set once and the operator reads meter 1, 2, 3 in one window.
  one meter at a time   the existing flow runs for meter 1 to completion, then the operator swaps in meter 2, and so on.

Nothing is merged between assets: every meter keeps its own results, As Found / As Left sets, checkpoint file, report and Asset History record.
A queue with fewer than two meters is not a queue: the procedure runs exactly as it always did.

WHICH POINTS CAN BE SHARED (point by point).  `share_reason(p, options)` returns None when the point may be shared, else one sentence saying why it
cannot; such points (and the points around them that cannot be shared either) fall back to one meter at a time, with a prompt that says why.

  shareable by default   DC / AC voltage (incl. frequency and the high-voltage points; the HV question is asked once per hook-up group), the
                         no-calibrator yes / no checks (display test ...) and points set up by hand with no calibrator output (open input ...).
  never shared           current (DCI / ACI, groups AMP10 / UAMP: the meters would have to be in series), resistance / continuity (kind OHM),
                         capacitance (CAP) and thermocouple simulation (TEMP) (Mike: these are connected to one meter at a time), 4-wire
                         resistance (group OHM4: sense leads), VoltAlert (the meter is held against the plug), scope outputs, the duty-cycle /
                         square-wave special sources (kinds DUTY / SQUARE).
  explicit flags         a point may carry `queue_share: true | false` (wins over the defaults), and a spec may carry
                         `options.queue_share: false` (the whole family is one-meter-only), `options.queue_single_kinds: [...]`,
                         `options.queue_single_groups: [...]`.  No shipped spec carries any of these today (editing a spec would change what a
                         verified procedure's fingerprint covers); the defaults above decide.
"""
from __future__ import annotations

import json
from pathlib import Path

POINT_BY_POINT, ONE_AT_A_TIME = 'point', 'meter'
MODES = (POINT_BY_POINT, ONE_AT_A_TIME)
MODE_NAMES = {POINT_BY_POINT: 'Point by point', ONE_AT_A_TIME: 'One meter at a time'}
MAX_METERS = 8                       # the reading window has one row per meter

CURRENT_REASON = 'current points: the meters would have to be wired in series, so each meter is done on its own'
OHM4_REASON = '4-wire resistance: each meter needs its own sense leads'
VOLTALERT_REASON = 'VoltAlert: the meter is held against the plug one at a time'
SCOPE_REASON = 'oscilloscope output: one instrument at a time'
SPECIAL_REASON = 'special source (duty cycle / square wave with offset): connected to one meter at a time'
SOURCE_REASON = 'resistance, capacitance and thermocouple sources: connected to one meter at a time (lab rule)'
FLAGGED_REASON = 'this point is flagged one-meter-only in the procedure'
FAMILY_REASON = 'this meter family is flagged one-meter-only in the procedure'
IR_REASON = 'readings are taken over one IR cable, so one meter at a time'


class QueueError(ValueError):
    pass


class QueueMeter:
    """One meter of the queue and ALL of its own run state."""

    def __init__(self, asset, serial='', tech=''):
        self.asset, self.serial, self.tech = str(asset).strip(), str(serial or '').strip(), str(tech or '').strip()
        self.status = 'Ready'
        self.found, self.left = {}, {}                 # the two result sets (datamode): this meter only
        self.last_high_current = None                  # monotonic time of this meter's last high-current point (rest rule)
        self.note = ''

    def results(self, left=False):
        return self.left if left else self.found

    def label(self):
        return self.asset

    def row(self):
        return dict(asset=self.asset, serial=self.serial, tech=self.tech, status=self.status)


def clean_key(asset):
    return str(asset or '').strip().casefold()


class RunQueue:
    def __init__(self):
        self.meters: list[QueueMeter] = []
        self.mode = POINT_BY_POINT

    # ---- editing -------------------------------------------------------------------------------------------------
    def __len__(self):
        return len(self.meters)

    def active(self):
        """True when this is a real queue (two or more meters); fewer = the plain single-meter run."""
        return len(self.meters) >= 2

    def find(self, asset):
        key = clean_key(asset)
        return next((m for m in self.meters if clean_key(m.asset) == key), None)

    def add(self, asset, serial='', tech=''):
        asset = str(asset or '').strip()
        if not asset:
            raise QueueError('Enter the asset number of the meter.')
        if self.find(asset) is not None:
            raise QueueError(f'Asset {asset} is already in the queue: every meter has its own results and report, so an asset can be listed once.')
        if len(self.meters) >= MAX_METERS:
            raise QueueError(f'A queue holds at most {MAX_METERS} meters.')
        m = QueueMeter(asset, serial, tech)
        self.meters.append(m)
        return m

    def remove(self, index):
        if 0 <= index < len(self.meters):
            return self.meters.pop(index)
        return None

    def move(self, index, delta):
        j = index + delta
        if 0 <= index < len(self.meters) and 0 <= j < len(self.meters):
            self.meters[index], self.meters[j] = self.meters[j], self.meters[index]
            return j
        return index

    def problems(self):
        out, seen = [], set()
        for n, m in enumerate(self.meters, 1):
            if not m.asset:
                out.append(f'Meter {n} has no asset number.')
            elif clean_key(m.asset) in seen:
                out.append(f'Asset {m.asset} is listed twice.')
            seen.add(clean_key(m.asset))
        return out

    def names(self):
        return [m.asset for m in self.meters]

    # ---- saved queue (so a resumed run finds the same list) ---------------------------------------------------------
    def to_dict(self, model='', demo=False):
        return dict(version=1, model=model, demo=bool(demo), mode=self.mode, meters=[dict(asset=m.asset, serial=m.serial, tech=m.tech) for m in self.meters])

    def load_dict(self, data, model='', demo=False):
        """Fill from a saved queue; False (nothing changed) when it belongs to another model / a demo run."""
        if not isinstance(data, dict) or data.get('model') != model or bool(data.get('demo')) != bool(demo):
            return False
        meters = []
        for row in data.get('meters') or []:
            if isinstance(row, dict) and str(row.get('asset', '')).strip():
                meters.append(QueueMeter(row['asset'], row.get('serial', ''), row.get('tech', '')))
        if len({clean_key(m.asset) for m in meters}) != len(meters):
            return False
        self.meters = meters[:MAX_METERS]
        self.mode = data.get('mode') if data.get('mode') in MODES else POINT_BY_POINT
        return True


def save_queue(path, queue, model='', demo=False):
    try:
        Path(path).write_text(json.dumps(queue.to_dict(model, demo), indent=2))
        return True
    except OSError:
        return False


def read_queue(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------------------------ sharing rules
def share_reason(p, options=None):
    """None when the point may be shared by all meters wired to the calibrator together, else a sentence saying why not."""
    options = options or {}
    if options.get('queue_share') is False:
        return FAMILY_REASON
    explicit = p.get('queue_share')
    if explicit is False:
        return FLAGGED_REASON
    if explicit is True:
        return None
    if p.get('kind') in set(options.get('queue_single_kinds') or ()) or p.get('group') in set(options.get('queue_single_groups') or ()):
        return FLAGGED_REASON
    kind, group = p.get('kind'), str(p.get('group') or '')
    if kind in ('DCI', 'ACI') or group in ('AMP10', 'UAMP'):
        return CURRENT_REASON
    if group == 'OHM4':
        return OHM4_REASON
    if group == 'VOLTALERT':
        return VOLTALERT_REASON
    if group.startswith('SCOPE'):
        return SCOPE_REASON
    if kind in ('DUTY', 'SQUARE'):
        return SPECIAL_REASON
    if kind in ('OHM', 'CAP', 'TEMP'):
        return SOURCE_REASON
    return None


class Unit:
    """One piece of the plan.  shared: all `meters` are on the calibrator at once and `points` are read for each of them (per point, the meters
    in `needs[point id]`).  single: `points` are run for the one meter in `meters`, with the existing single-meter flow."""

    def __init__(self, kind, points, meters, reason='', needs=None, prompt=False, reset=False):
        self.kind, self.points, self.meters, self.reason = kind, points, meters, reason
        self.needs = needs or {}
        self.prompt, self.reset = prompt, reset

    @property
    def shared(self):
        return self.kind == 'shared'

    def describe(self):
        return f'{self.kind}: {len(self.points)} point(s), meters {[m.asset for m in self.meters]}' + (f' ({self.reason})' if self.reason else '')


def plan(points, queue, options=None, mode=None, use_ir=False, force=False, left=False):
    """The ordered units of one queue run.

    points  the points to run, in order.  A point is run for a meter that has no reading yet in the set being collected (`left`), or for every
            meter when `force` (Rerun Selected).
    Point by point: consecutive shareable points (with two or more meters still needing them) form one shared unit; every other point runs one meter
    at a time (a prompt before each meter says why).  One meter at a time (or IR): every meter runs the whole list in turn, in queue order."""
    mode = mode or queue.mode
    meters = list(queue.meters)

    def needs(p):
        return meters if force else [m for m in meters if str(p['id']) not in m.results(left)]

    units = []
    if mode == ONE_AT_A_TIME or use_ir or len(meters) < 2:
        for m in meters:
            pts = [p for p in points if m in needs(p)]
            if pts:
                units.append(Unit('single', pts, [m], reason=IR_REASON if (use_ir and mode != ONE_AT_A_TIME) else '', prompt=bool(units), reset=bool(units)))
        return units
    cur = None
    for p in points:
        need = needs(p)
        if not need:
            continue
        reason = share_reason(p, options)
        if len(need) >= 2 and reason is None:
            if cur is None or cur.kind != 'shared':
                cur = Unit('shared', [], meters)
                units.append(cur)
            cur.points.append(p)
            cur.needs[str(p['id'])] = need
        else:
            if cur is None or cur.kind != 'single':
                cur = Unit('single', [], [], reason=reason or '')
                units.append(cur)
            cur.points.append(p)
            for m in need:
                if m not in cur.meters:
                    cur.meters.append(m)
            if reason and reason not in cur.reason:
                cur.reason = reason if not cur.reason else cur.reason + '; ' + reason
            cur.needs[str(p['id'])] = need
    out = []
    for u in units:
        if u.kind == 'shared':
            out.append(u)
            continue
        # a single unit: one run per meter (queue order) over the points that meter still needs
        order = [m for m in meters if m in u.meters]
        for m in order:
            pts = [p for p in u.points if m in u.needs[str(p['id'])]]
            if pts:
                reason = u.reason or ('only this meter still needs these points' if len(order) == 1 and len(meters) > 1 else '')
                out.append(Unit('single', pts, [m], reason=reason, prompt=True))
    return out


def summary(points, queue, options=None, mode=None, use_ir=False):
    """Plain numbers for the setup window: calibrator settings with the chosen mode and with one meter at a time, plus the reasons some points cannot be shared."""
    mode = mode or queue.mode
    n = len(queue.meters)
    pts = list(points)
    alone = len(pts) * max(n, 1)
    shared = [p for p in pts if share_reason(p, options) is None]
    single = [p for p in pts if share_reason(p, options) is not None]
    if mode == ONE_AT_A_TIME or use_ir or n < 2:
        settings, shared_n = alone, 0
    else:
        shared_n = len(shared)
        settings = shared_n + len(single) * n
    reasons = {}
    for p in single:
        reasons.setdefault(share_reason(p, options), 0)
        reasons[share_reason(p, options)] += 1
    return dict(points=len(pts), meters=n, settings=settings, alone=alone, saved=alone - settings, shared=shared_n, single=len(single) if mode == POINT_BY_POINT and not use_ir else len(pts),
                reasons=reasons)


def progress(queue, points, left=False):
    """Per meter: recorded / failed counts for the progress window.  A 'point' is one test point of the procedure."""
    total = len(points)
    order = {str(p['id']): p['n'] for p in points}
    rows = []
    for m in queue.meters:
        res = m.results(left)
        rec = [k for k in res if k in order]
        fails = sorted((order[k] for k in rec if res[k].get('result') == 'FAIL'))
        rows.append(dict(asset=m.asset, serial=m.serial, status=m.status, recorded=len(rec), failed=len(fails), first_fail=fails[0] if fails else None, total=total))
    return rows
