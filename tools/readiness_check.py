"""Readiness check: is a calibration procedure ready for its FIRST run on real hardware?  No instruments, no windows.

    python tools/readiness_check.py <procedure id | launcher file | sidecar file>  [--json out.json] [--verbose] [--no-run] [--strict]
    python tools/readiness_check.py --all [--json out.json]            every procedure registered in Procedures/ (one summary table)

Why: every new automated procedure has needed several revisions before it ran correctly on real hardware (prompt characters where a
value was expected, tunables that were referenced but never registered, an unverified housekeeping query that made every run prompt, a driver
edit of a shared file that flipped verified procedures, too many operator prompts, points that print no uncertainty).  Each of those can
be seen on the simulated bench, so this tool looks for them before the owner does.

What it does
  1. Runs the procedure's WHOLE flow once on the simulated bench (the virtual bench of --demo, tools/readiness_run.py, a fresh interpreter,
     a throw-away HOME, tkinter replaced by the test stub) and reads the result from the EXISTING command log (drivers/transport.CommandLog)
     plus the dialogs the operator would have seen.  Nothing is added to the logging; nothing is sent to hardware.
  2. Checks that run and the procedure's files, and prints a PASS / WARN / FAIL checklist (INFO = for your information):

       run        the virtual run finished; no error dialog; demo records synthetic; the command log stayed virtual
       commands   every command sent, with its COMMANDS-registry verified flag and manual page; unverified ones listed as an INFO note (not a
                  WARN); raw (unregistered) wire text
       readback   a registered write whose declared read-back query was never sent
       outputs    calibrator / generator output left ON between points or at the end of the run
       prompts    operator prompts per point (flag many in a procedure that reads its own meter)
       tunables   pm_param names that are not registered in procmods_engine (the 8808A DCI settle case), wrong defaults, unknown engine prefix
       uncertainty  points that should print an uncertainty (Datasheet Builder rule 5, NATURAL_UNITS, no_uncertainty respected) and print none
       housekeeping unverified ERR? / *ESR? style queries that the Datasheet Builder would still prompt for
       diagrams   hook-up picture names that are missing from diagrams/
       fingerprint  the sidecar file list against the files the procedure really depends on (incomplete list, shared files)
       shared     the branch against its base: which shared files changed and which procedures' fingerprints (= verified procedures) flip
       sidecar    the sidecar and the files it names
       surprise   a NEW procedure (not on the base branch) whose drivers do not inherit surprise.SurpriseMixin

Levels: FAIL = something is wrong and will stop or mislead a real run; WARN = look at it before the first run; INFO = for the record.
Exit code 0 = no FAIL (with --strict: no WARN either), 1 = at least one FAIL.  The checks are calibrated on the procedures already in the
repo (see NOTES.md, 'Readiness check and stop-on-surprise'): a finding that is true for most existing procedures is INFO, not WARN.

Not covered (by design): whether a reply FORMAT is what the real instrument sends (only the instrument can tell), whether a write is compared
with its read-back in the engine's own code (the stop-on-surprise guard, surprise.py, covers that at run time), WaveSurfer WS4104HD
(its demo mode loads canned data) and the guided adjustment procedures (their demo issues no CAL commands on purpose): those get the static
checks only.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import string
import subprocess
import sys
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]

PASS, WARN, FAIL, INFO = 'PASS', 'WARN', 'FAIL', 'INFO'
ORDER = {FAIL: 0, WARN: 1, INFO: 2, PASS: 3}

# ----- calibration of the checks (measured on the 41 procedures in the repo; see NOTES.md) --------------------------------------------------
PROMPT_RATIO_WARN = 0.8         # operator prompts (not reading entries) per measured point, for a procedure that reads its own meter (TDS2000C, verified: 0.71)
PROMPT_MIN_COUNT = 12           # ... and only above this many prompts in total
PROMPT_REPEAT = 3               # the same prompt (title and heading) shown this many times or more is listed (high-voltage questions differ by voltage)
READBACK_LOOKAHEAD = 120        # a write's read-back query must come within this many later commands of the same instrument
DETAIL_LINES = 5                # lines of detail per check in the one-screen report (--verbose: all)
RUN_TIMEOUT_S = 600

SAMPLE = 3


@dataclass
class Finding:
    level: str
    check: str
    text: str
    details: list = field(default_factory=list)
    show: bool = False              # an INFO whose detail lines are still printed in the one-screen report (the unverified-commands note)

    def as_dict(self):
        return dict(level=self.level, check=self.check, text=self.text, details=list(self.details))


@dataclass
class Report:
    proc: object
    findings: list = field(default_factory=list)
    run: dict = field(default_factory=dict)
    seconds: float = 0.0

    def add(self, level, check, text, details=(), show=False):
        self.findings.append(Finding(level, check, text, list(details), show))

    @property
    def counts(self):
        return Counter(f.level for f in self.findings)

    @property
    def worst(self):
        return min((f.level for f in self.findings), key=lambda l: ORDER[l], default=PASS)

    def as_dict(self):
        p = self.proc
        return dict(procedure=p.id, name=p.name, engine=list(p.engine), worst=self.worst, counts=dict(self.counts),
                    findings=[f.as_dict() for f in self.findings], run={k: v for k, v in self.run.items() if k != 'timeline'}, seconds=self.seconds)


# ================================================================================================================ loading
def _load_modules():
    """The suite modules the checks use.  Everything here is Tk-free; the stub is only a safety net for a module that imports tkinter."""
    global procscan, cmdreg, verified, procmods_engine, hookups, dbr
    try:
        import tkinter  # noqa: F401
    except Exception:
        import readiness_run
        readiness_run._stub_tkinter()
    sys.path[:0] = [str(ROOT / 'Procedures')]
    import procscan as _ps
    import cmdreg as _cr
    import verified as _vf
    import procmods_engine as _pe
    import hookups as _hk
    import datasheet_builder_rules as _db
    import drivers  # noqa: F401
    procscan, cmdreg, verified, procmods_engine, hookups, dbr = _ps, _cr, _vf, _pe, _hk, _db


procscan = cmdreg = verified = procmods_engine = hookups = dbr = None


def resolve(arg):
    """The registered procedure for an id, a launcher file name, or a path to the launcher / sidecar."""
    name = Path(arg).name
    for suffix in ('.procedure.json', '.py'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    proc = procscan.find(name, ROOT)
    if proc is not None:
        return proc
    launcher = ROOT / 'Procedures' / f'{name}.py'
    if launcher.is_file():                                         # a launcher with no (or a broken) sidecar: checked, and the sidecar check fails
        return procscan.Proc(id=name, name=name, launcher=f'Procedures/{name}.py', sidecar=f'Procedures/{name}.procedure.json')
    raise SystemExit(f'No procedure "{arg}" (looked for Procedures/{name}.py and its sidecar).')


STATIC_ONLY = {'WaveSurfer_WS4104HD': 'its demo mode loads canned data (no virtual instruments) and the engine has no headless entry point'}


def static_only_reason(proc):
    if proc.id in STATIC_ONLY:
        return STATIC_ONLY[proc.id]
    if proc.effective_kind == 'adjustment':
        return 'a guided adjustment: its demo issues no calibration commands on purpose (safety) and every step is behind a dialog'
    return ''


def file_of(rel):
    return ROOT / procscan.split_label(rel)[0]


# ================================================================================================================ the run
def run_dynamic(proc, timeout=RUN_TIMEOUT_S):
    """The worker's record (dict).  A crash or a timeout of the worker is a record with 'error' set, not an exception."""
    spec = dict(id=proc.id, launcher=proc.launcher, engine=list(proc.engine))
    try:
        r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'readiness_run.py'), json.dumps(spec)], capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return dict(ok=False, error=f'the run did not finish in {timeout} s (worker killed)', timeline=[], classes={})
    parts = r.stdout.split('@@READINESS@@')
    if len(parts) < 2:
        return dict(ok=False, error='the worker produced no result: ' + (r.stderr.strip().splitlines() or ['(no output)'])[-1][:300], timeline=[], classes={})
    try:
        return json.loads(parts[-1])
    except ValueError as exc:
        return dict(ok=False, error=f'the worker result could not be read: {exc}', timeline=[], classes={})


# ================================================================================================================ registry helpers
def _resolve_class(path):
    mod, _, name = path.partition(':')
    try:
        module = __import__(mod, fromlist=['_'])
        return getattr(module, name)
    except Exception:
        return None


def registries(run, proc):
    """{instrument label: (class, {key: Cmd})} from the run's classes; for a static-only procedure the classes of the sidecar's driver modules."""
    out = OrderedDict()
    for label, path in (run.get('classes') or {}).items():
        cls = _resolve_class(path)
        if cls is not None:
            out[label] = (cls, cmdreg.merge_commands(cls))
    if not out:
        from drivers.base import Instrument
        import inspect
        for name in proc.drivers:
            try:
                module = __import__(f'drivers.{name}', fromlist=['_'])
            except Exception:
                continue
            for cname, cls in vars(module).items():
                if inspect.isclass(cls) and issubclass(cls, Instrument) and cls.__module__ == module.__name__ and cls.COMMANDS is not None:
                    reg = cmdreg.merge_commands(cls)
                    if reg:
                        out[f'{cname} (static)'] = (cls, reg)
    return out


_TAG = re.compile(r'\s+\[(?:OVERRIDE|EXTRA)[^\]]*\]\s*$')


def template_regex(template):
    parts = []
    try:
        for lit, name, _spec, _conv in string.Formatter().parse(template):
            parts.append(re.escape(lit))
            if name is not None:
                parts.append('.+?')
    except ValueError:
        parts = [re.escape(template)]
    return re.compile('^' + ''.join(parts) + '$', re.I | re.S)


def literal_len(template):
    try:
        return sum(len(lit) for lit, _n, _s, _c in string.Formatter().parse(template))
    except ValueError:
        return len(template)


class Matcher:
    """Wire text -> registry key for one instrument (the most specific template that fits)."""

    def __init__(self, registry):
        self.items = sorted(((literal_len(c.template), k, template_regex(c.template), c) for k, c in registry.items()), key=lambda t: (-t[0], t[1]))
        self.reg = registry

    def key_of(self, wire):
        text = _TAG.sub('', wire.strip())
        for _n, key, rx, _c in self.items:
            if rx.match(text):
                return key
        return None


def is_query_text(text):
    head = text.strip().split(None, 1)[0] if text.strip() else ''
    return '?' in head


# ================================================================================================================ transcript analysis (pure: used by the tests with synthetic input)
def transcript(timeline, regs):
    """[(index, label, key, wire, cmd)] for every written command (direction '>>') of an instrument with a registry; key None = not in the registry."""
    matchers = {lab: Matcher(reg) for lab, (_c, reg) in regs.items()}
    out = []
    for i, e in enumerate(timeline):
        if e[0] != 'cmd' or e[2] != '>>':
            continue
        label, text = e[1], e[3]
        m = matchers.get(label)
        key = m.key_of(text) if m else None
        out.append((i, label, key, text, m.reg.get(key) if (m and key) else None))
    return out


def check_commands(rep, tr, regs, run):
    """Every command the run sent: registry key, verified flag, manual page."""
    used = OrderedDict()                               # (label, key) -> [count, example wire]
    raw = OrderedDict()
    for _i, label, key, wire, cmd in tr:
        if key is None and wire.strip().upper() == '*IDN?':        # Instrument.identify() in drivers/base.py: every driver, every connection
            continue
        if key is None:
            r = raw.setdefault((label, _TAG.sub('', wire).split(None, 1)[0] if wire.strip() else ''), [0, wire])
            r[0] += 1
        else:
            u = used.setdefault((label, key), [0, wire])
            u[0] += 1
    unverified, noref = [], []
    for (label, key), (n, wire) in used.items():
        cmd = regs[label][1][key]
        if not cmd.verified:
            unverified.append(f'{label}: {key}  "{wire}"  x{n}  ({cmd.ref or "no manual page recorded"})')
        elif not (cmd.ref or '').strip():
            noref.append(f'{label}: {key}  "{wire}"')
    n_cmds = sum(v[0] for v in used.values()) + sum(v[0] for v in raw.values())
    head = f'{len(used)} registered commands used ({n_cmds} sent), {len(used) - len(unverified)} verified'
    if unverified:
        # a note, not a warning (owner decision): the lab's procedures are built from the manuals that exist and the list goes into the final summary
        rep.add(INFO, 'commands', head + f'; note: {len(unverified)} unverified command(s) in use (list them in the final summary)', unverified, show=True)
    else:
        rep.add(PASS, 'commands', head)
    if noref:
        rep.add(WARN, 'commands', f'{len(noref)} verified command(s) with no manual page recorded', noref)
    if raw:
        # raw wire text: sent without a registry entry, so it cannot carry a verified flag or be overridden / listed by the Datasheet Builder
        rows = [f'{label}: "{wire}" x{n}' for (label, _h), (n, wire) in raw.items()]
        rep.add(WARN, 'commands', f'{len(raw)} kind(s) of wire text sent that are NOT in any COMMANDS registry (no verified flag possible)', rows)
    # the commands the drivers declare but this run did not use (what else the procedure could send)
    unused = []
    for label, (_c, reg) in regs.items():
        if label.endswith('(static)'):
            continue
        for key, cmd in reg.items():
            if (label, key) not in used and not cmd.verified and cmd.risk != 'locked':
                unused.append(f'{label}: {key} "{cmd.template}"')
    if unused:
        rep.add(INFO, 'commands', f'{len(unused)} more UNVERIFIED registered command(s) were not used in this run (the procedure or an operator choice could send them)', unused)


def raw_sends(rel):
    """[(line, regex or None, text)] for every .write / .query / .query_retry call in the file whose first argument is a string or f-string literal:
    wire text written in code instead of through the COMMANDS registry (send / ask)."""
    tree = _parse(rel)
    out = []
    if tree is None:
        return out
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Attribute) and node.func.attr in ('write', 'query', 'query_retry')):
            continue
        a0 = node.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            out.append((node.lineno, re.compile('^' + re.escape(a0.value) + '$', re.I | re.S), a0.value))
        elif isinstance(a0, ast.JoinedStr):
            text = ''.join(str(v.value) if isinstance(v, ast.Constant) else '{}' for v in a0.values)
            out.append((node.lineno, _fstring_regex(a0), text))
    return out


def check_raw_sends(rep, proc, run, regs, files):
    """Wire text written in the driver / engine code that no COMMANDS template covers: the Command table cannot show a verified flag or a manual page
    for it, an override cannot replace it, and the Datasheet Builder lists it as 'not in the command registry'.  *IDN? (Instrument.identify) is exempt."""
    templates = [template_regex(c.template) for _l, (_c, reg) in regs.items() for c in reg.values()]
    rows = []
    for rel in files:
        if not file_of(rel).is_file():
            continue
        for line, rx, text in raw_sends(rel):
            if text.strip().upper() == '*IDN?':
                continue
            probe = re.sub(r'\{\}', 'X', text)
            if any(t.match(probe) for t in templates):
                continue
            rows.append(f'{Path(rel).name}:{line}  "{text}"')
    if rows:
        rep.add(INFO, 'commands', f'{len(rows)} wire-text literal(s) written in the code that no COMMANDS template covers (cannot carry a verified flag or manual page)', rows)


def check_static_commands(rep, proc, regs):
    """Registry of a procedure that cannot be run headless: what its drivers can send."""
    rows, n = [], 0
    for label, (_c, reg) in regs.items():
        for key, cmd in reg.items():
            n += 1
            if not cmd.verified:
                rows.append(f'{label.replace(" (static)", "")}: {key} "{cmd.template}" ({cmd.ref or "no manual page recorded"})')
    if not regs:
        rep.add(INFO, 'commands', 'no driver registry found for the sidecar\'s drivers')
        return
    rep.add(INFO if rows else PASS, 'commands', f'static: {n} registered commands in the sidecar\'s drivers; note: {len(rows)} unverified (not run: see "run")', rows, show=bool(rows))


_ON = re.compile(r'^(?:OPER|OUTP\w*(?::STAT\w*)?\s+(?:ON|1)|AFG:OUTP\w*:STAT\w*\s+ON|APPL\w*[ :].*)$', re.I)
_OFF = re.compile(r'^(?:STBY|OUTP\w*(?::STAT\w*)?\s+(?:OFF|0)|AFG:OUTP\w*:STAT\w*\s+OFF|\*RST)$', re.I)


def check_outputs(rep, tr, timeline):
    """Standing rule: outputs go to standby / off after each point.  On the command stream: an output still ON at the end of the run, and an
    output switched ON again while still ON after a point was recorded in between (that point left it on).  Switching an output on again WITHIN
    a point (a sweep through amplitudes or frequencies) is normal and not reported."""
    mark_at = [i for i, e in enumerate(timeline) if e[0] == 'pt']
    state, across, within, last_on = {}, [], 0, {}
    for i, label, key, wire, cmd in tr:
        text = _TAG.sub('', wire).strip()
        if _ON.match(text):
            if state.get(label):
                if any(last_on[label][0] < m < i for m in mark_at):
                    across.append((label, last_on[label][1], text))
                else:
                    within += 1
            state[label] = True
            last_on[label] = (i, text)
        elif _OFF.match(text):
            state[label] = False
    on_end = [lab for lab, on in state.items() if on]
    seen = any(_ON.match(_TAG.sub('', w).strip()) for _i, _l, _k, w, _c in tr)
    if not seen:
        rep.add(INFO, 'outputs', 'no output-enable command was sent in this run (nothing to switch off)')
        return
    if on_end:
        rep.add(FAIL, 'outputs', 'an output is still ON at the end of the run: ' + ', '.join(on_end))
    if across:
        c = Counter((l, a, b) for l, a, b in across)
        rep.add(WARN, 'outputs', f'an output was left ON after a point was recorded and switched on again without standby / off: {len(across)} time(s)',
                [f'{l}: "{a}" then "{b}" x{n}' for (l, a, b), n in c.most_common()])
    if not mark_at and within:
        rep.add(INFO, 'outputs', f'{within} output-on while on (no recorded-point marks in this engine, so within-point and between-point cannot be told apart)')
    if not on_end and not across:
        rep.add(PASS, 'outputs', 'standby / off before every output-on that follows a recorded point, and at the end'
                + (f' ({within} repeat output-on within a point: a sweep)' if within else ''))


def check_readback(rep, tr):
    """A registered write that declares a read-back query must be followed by that query (same instrument) before the same write is repeated / within
    the look-ahead.  The comparison itself is in the engine's code and is not visible here (surprise.py covers it at run time)."""
    by_label = defaultdict(list)
    for i, label, key, wire, cmd in tr:
        by_label[label].append((key, cmd))
    missing = Counter()
    missing_out = Counter()
    checked = Counter()
    undeclared = Counter()
    for label, items in by_label.items():
        for n, (key, cmd) in enumerate(items):
            if key is None or cmd is None or cmd.kind != 'set':
                continue
            if not cmd.readback:
                undeclared[(label, key, cmd.template)] += 1
                continue
            checked[(label, key)] += 1
            found = False
            for k2, _c2 in items[n + 1:n + 1 + READBACK_LOOKAHEAD]:
                if k2 == cmd.readback or (k2 and k2.startswith(cmd.readback.rsplit('.', 1)[0] + '.') and cmd.readback.count('.') > 1 and k2.split('.')[0] == cmd.readback.split('.')[0] and k2.endswith(cmd.readback.rsplit('.', 1)[-1])):
                    found = True
                    break
                if k2 == key:                      # written again first
                    break
            if not found:
                (missing_out if cmd.risk == 'output' else missing)[(label, key, cmd.readback)] += 1
    total = sum(checked.values())
    if missing_out:
        rep.add(INFO, 'readback', f'{sum(missing_out.values())} output-enable write(s) were not followed by their state query (OPER? / OUTP?): the output state is not confirmed',
                [f'{l}: {k} (read-back {rb}) x{n}' for (l, k, rb), n in missing_out.most_common()])
    if missing:
        rep.add(WARN, 'readback', f'{sum(missing.values())} of {total} writes with a declared read-back were not followed by it',
                [f'{l}: {k} (read-back {rb}) x{n}' for (l, k, rb), n in missing.most_common()])
    elif total:
        rep.add(PASS, 'readback', f'{total} writes with a declared read-back were each followed by it')
    if undeclared:
        rep.add(INFO, 'readback', f'{len(undeclared)} registered write(s) declare no read-back query in COMMANDS (the manual may have none; confirm)',
                [f'{l}: {k} "{t}" x{n}' for (l, k, t), n in undeclared.most_common()])


ESSENTIAL = re.compile(r'reset|warm|before|high voltage|rewire|connect|zero offset|set ?up|own standard|cycle power|terminat|self[ -]|calibration|conditions|hook|cable|function|temperature', re.I)


def classify_dialogs(timeline):
    out = Counter()
    seen = Counter()
    for e in timeline:
        if e[0] != 'dlg':
            continue
        kind = e[1]
        if kind == 'reading':
            out['reading'] += 1
        elif kind == 'confirm' or (kind.startswith('box:') and kind != 'box:showerror'):
            out['prompt'] += 1
            seen[(kind.replace('confirm', '').replace('box:', '') or 'dialog', e[2], e[3])] += 1
        elif kind == 'thread-error':
            out['thread-error'] += 1
    return out, seen


def check_prompts(rep, timeline, run):
    """Prompts the operator answers (hook-up, safety, setup) against the points measured.  Hook-up / safety / warm-up prompts are the procedure;
    what is flagged is the same prompt shown again and again, and a prompt for nearly every point in a procedure that reads its own meter."""
    c, seen = classify_dialogs(timeline)
    readings = c['reading']
    prompts = c['prompt']
    measured = run.get('results') or run.get('points') or 0
    typed = readings >= max(3, 0.5 * measured)             # the operator reads the meter and types the value: a prompt per point is the procedure
    nm = max(1, measured)
    per = prompts / nm
    essential = sum(n for (_k, t, h), n in seen.items() if ESSENTIAL.search(t) or ESSENTIAL.search(h))
    other = [(k, t, h, n) for (k, t, h), n in seen.items() if not (ESSENTIAL.search(t) or ESSENTIAL.search(h))]
    repeats = [(t, h, n) for (_k, t, h), n in seen.items() if n >= PROMPT_REPEAT and not re.search(r'high voltage', t, re.I)]
    mode = 'the operator types the readings' if typed else 'readings are taken from the instrument'
    head = f'{prompts} prompts for {measured} points ({per:.2f} per point; {essential} hook-up / safety / setup); {mode}'
    details = [f'shown {n}x: {t} / {h}' for t, h, n in sorted(repeats, key=lambda r: -r[2])]
    if other:
        details += [f'not a hook-up / safety / setup prompt: {t} / {h} x{n}' for _k, t, h, n in other[:SAMPLE]]
    if not typed and prompts >= PROMPT_MIN_COUNT and per > PROMPT_RATIO_WARN:
        rep.add(WARN, 'prompts', head + ' - many for a fully automated procedure', details)
    elif repeats and not typed:
        rep.add(WARN, 'prompts', head + ' - the same prompt more than once', details)
    else:
        rep.add(PASS if not details else INFO, 'prompts', head, details)


def check_run(rep, run, proc, reason):
    if reason:
        rep.add(INFO, 'run', f'not run (static checks only): {reason}')
        return
    if run.get('error'):
        rep.add(FAIL, 'run', f'the virtual run failed: {run["error"]}', ([run['trace']] if run.get('trace') else []))
        return
    probs = []
    c, _t = classify_dialogs(run.get('timeline', []))
    errs = [e for e in run.get('timeline', []) if e[0] == 'dlg' and e[1] == 'box:showerror']
    thr = [e for e in run.get('timeline', []) if e[0] == 'dlg' and e[1] == 'thread-error']
    for e in errs:
        probs.append(f'error dialog: {e[2]}: {e[3]}')
    for e in thr:
        probs.append(f'worker thread error: {e[2]} {e[3]}')
    if run.get('note'):
        probs.append(run['note'])
    if probs:
        rep.add(FAIL, 'run', 'the virtual run did not complete cleanly', probs)
    pts, res = run.get('points'), run.get('results')
    summary = f'{res} of {pts} points run' if pts else f'{res} results'
    wire = sum(1 for e in run.get('timeline', []) if e[0] == 'cmd' and e[2] == '>>')
    virt = 'virtual instruments' if run.get('virtual') else 'simulated bench (engine without a virtual-demo mode)'
    if not probs:
        rep.add(PASS, 'run', f'{summary}; {wire} commands sent to {virt}; {run.get("seconds")} s')
    if pts and res is not None and res < pts:
        rep.add(INFO, 'run', f'{pts - res} point(s) were not run in the virtual run (the window\'s default options skip some: Rear panel, optional 2-wire / AC choices ...)',
                [f'{k} / {sec}: {n}' for k, sec, n in run.get('skipped') or []])
    if run.get('virtual'):
        if run.get('synthetic_ok') is False:
            rep.add(FAIL, 'run', 'a virtual (demo) record is NOT marked synthetic: demo data could look like real evidence')
        bad = [l for l, v in (run.get('log_virtual') or {}).items() if v is False and l not in ('RESET',)]
        if bad:
            rep.add(FAIL, 'run', 'a command log was not marked virtual in demo mode (it would be appended to the shared evidence log): ' + ', '.join(bad))


# ================================================================================================================ source scans
def _parse(rel):
    path = file_of(rel)
    try:
        return ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    except (OSError, SyntaxError):
        return None


def _fstring_regex(node):
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(re.escape(str(v.value)))
        else:
            parts.append('.+?')
    return re.compile('^' + ''.join(parts) + '$', re.I | re.S)


def tunable_calls(rel):
    """[(line, pattern or name, default node value or None, is_literal)] for every pm_param(...) call in the file."""
    tree = _parse(rel)
    out = []
    if tree is None:
        return out
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ''
        if name != 'pm_param':
            continue
        a0 = node.args[0]
        default = None
        if len(node.args) > 1:
            try:
                default = ast.literal_eval(node.args[1])
            except Exception:
                default = None
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            out.append((node.lineno, a0.value, default, True))
        elif isinstance(a0, ast.JoinedStr):
            out.append((node.lineno, _fstring_regex(a0), default, False))
        else:
            out.append((node.lineno, None, default, False))
    return out


def check_tunables(rep, proc, run, files):
    T = procmods_engine.TUNABLES
    bad, unresolved, wrongdef, n = [], [], [], 0
    for rel in files:
        for line, pat, default, literal in tunable_calls(rel):
            n += 1
            where = f'{Path(rel).name}:{line}'
            if pat is None:
                unresolved.append(where)
            elif literal:
                t = T.get(pat)
                if t is None:
                    bad.append(f'{where}: pm_param("{pat}") is not registered in procmods_engine (add _t(...); until then the editor cannot change it)')
                else:
                    if default is not None and isinstance(default, (int, float)) and abs(float(default) - float(t['default'])) > 1e-12:
                        wrongdef.append(f'{where}: "{pat}" default {default} in the engine, {t["default"]} registered')
            else:
                if not any(pat.match(k) for k in T):
                    bad.append(f'{where}: no registered tunable matches the computed name {pat.pattern}')
    dyn = []
    for name, default in run.get('pm_params') or []:
        t = T.get(name)
        if t is None:
            if not any(name == b.split('"')[1] for b in bad if '"' in b):
                dyn.append(f'asked for at run time but not registered: "{name}"')
        else:
            try:
                if abs(float(default) - float(t['default'])) > 1e-12:
                    wrongdef.append(f'run time: "{name}" asked with default {default}, registered {t["default"]}')
            except (TypeError, ValueError):
                pass
    eng = {nm.split('.')[0] for nm in T}
    foreign = sorted({name.split('.')[0] for name, _d in (run.get('pm_params') or []) if name.split('.')[0] not in procmods_engine.MODEL_IDS})
    problems = bad + dyn + wrongdef + [f'engine prefix "{f}" is not in procmods_engine.MODEL_IDS' for f in foreign]
    if problems:
        rep.add(FAIL, 'tunables', f'{len(problems)} tunable problem(s) ({n} pm_param calls read)', problems)
    else:
        rep.add(PASS, 'tunables', f'{n} pm_param calls: every name is registered with the same default' + (f'; {len(unresolved)} computed name(s) not checked' if unresolved else ''))
    del eng


def check_uncertainty(rep, run):
    """Points that should carry an uncertainty (the engine's own rule, else Datasheet Builder rule 5: a kind in the CMC table, sourced by a calibrator,
    not a zero-offset / no-source / own-standard / no_uncertainty point; NATURAL_UNITS and no_uncertainty respected by the same functions the
    report uses) and print none.  Blank where the scope of accreditation does not cover the point is stated in the report footer: INFO for a few,
    WARN for many; blank where the scope DOES cover it is a bug: FAIL."""
    rows = (run.get('report') or {}).get('rows') or []
    note = (run.get('report') or {}).get('note') or ''
    if not rows:
        rep.add(INFO, 'uncertainty', note or 'no report rows to check')
        return
    if note:
        rep.add(INFO, 'uncertainty', note)
    should = [r for r in rows if r.get('should')]
    miss = [r for r in should if not r.get('uncertainty')]
    bug = [r for r in miss if r.get('covered') is True]
    unknown = [r for r in miss if r.get('covered') is None]
    uncovered = [r for r in miss if r.get('covered') is False]

    def group(rs):
        by = defaultdict(list)
        for r in rs:
            by[(r.get('kind'), r.get('section'))].append(r)
        return [f'{k[0]} / {k[1]}: {len(v)}, e.g. "{v[0]["description"]}"' for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    if bug:
        rep.add(FAIL, 'uncertainty', f'{len(bug)} point(s) are inside the scope of accreditation but print no uncertainty (of {len(should)} that should)', group(bug))
    if unknown:
        rep.add(WARN, 'uncertainty', f'{len(unknown)} point(s) that should carry an uncertainty print none (coverage by the scope could not be worked out)', group(unknown))
    if uncovered:
        level = WARN if len(uncovered) >= max(5, 0.1 * len(should)) else INFO
        rep.add(level, 'uncertainty', f'{len(uncovered)} of {len(should)} points print no uncertainty because the scope of accreditation does not cover them (the report footer says so)', group(uncovered))
    if not miss:
        rep.add(PASS, 'uncertainty', f'all {len(should)} points that should carry an uncertainty print one ({len(rows) - len(should)} rows carry none by design)')
    ratio_bad = [r for r in should if r.get('uncertainty') and r.get('tur') == '' and r.get('tar') == '']
    rb = [r for r in rows if r.get('ratio_error')]
    if ratio_bad:
        rep.add(INFO, 'uncertainty', f'{len(ratio_bad)} point(s) with an uncertainty have no TAR / TUR (percent or one-sided tolerance, no specification row: expected for some)',
                [f'{r["description"]} ({r.get("kind")})' for r in ratio_bad[:SAMPLE]])
    if rb:
        rep.add(WARN, 'uncertainty', f'TAR / TUR could not be computed for {len(rb)} row(s): {rb[0]["ratio_error"]}')


def check_housekeeping(rep, regs, used=None):
    """The Datasheet Builder asks about every unverified command except its HOUSEKEEPING list (rule 2).  An unverified error / status query whose
    header is not on that list would make every run prompt."""
    would, covered = [], []
    seen = set()
    for label, (_c, reg) in regs.items():
        for key, cmd in reg.items():
            if cmd.kind != 'query' or cmd.verified:
                continue
            if not re.match(r'(err|esr|stb|opc|status|idn|ese|sre|event)', key, re.I):          # error / status plumbing by name: a calibration or self-test query is not housekeeping
                continue
            if used is not None and (label, key) not in used:                                      # the Builder only asks about commands the dry run sent
                continue
            wire = cmd.template.split('{')[0]
            tag = (label, key)
            if tag in seen:
                continue
            seen.add(tag)
            if dbr.is_housekeeping(wire):
                covered.append(f'{key} "{wire}"')
            else:
                would.append(f'{label.replace(" (static)", "")}: {key} "{wire}" is UNVERIFIED and not on the HOUSEKEEPING list: it would prompt')
    if would:
        rep.add(WARN, 'housekeeping', f'{len(would)} unverified status / error query(ies) would make the Datasheet Builder prompt', would)
    else:
        rep.add(PASS, 'housekeeping', f'no unverified status / error query outside the HOUSEKEEPING list ({len(covered)} on the list, not asked)')


def check_surprise(rep, proc, regs, shared):
    """Stop-on-surprise (surprise.py) is on by default for NEW procedures: their driver classes inherit SurpriseMixin.  Existing procedures are opt-in
    (turning it on edits shared files and flips verified procedures: NOTES.md), so for them nothing is reported."""
    if shared is None or proc.id not in (shared.get('new') or []):
        return
    import surprise
    classes = [c for _l, (c, _r) in regs.items() if isinstance(c, type)]
    plain = [c.__name__ for c in classes if not issubclass(c, surprise.SurpriseMixin)]
    if not classes:
        rep.add(INFO, 'surprise', 'new procedure: no driver class resolved, stop-on-surprise not checked')
    elif plain:
        rep.add(WARN, 'surprise', 'new procedure whose driver(s) do not inherit surprise.SurpriseMixin (stop-on-surprise is default for new procedures): ' + ', '.join(plain))
    else:
        rep.add(PASS, 'surprise', 'every driver of this new procedure inherits SurpriseMixin (stop-on-surprise available)')


def check_diagrams(rep, proc, run):
    misses = list(run.get('diagram_misses') or [])
    prefixes = list(proc.diagram_prefixes)
    d = ROOT / 'diagrams'
    notes = []
    for pre in prefixes:
        if not any(d.glob(pre + '*.png')):
            notes.append(f'no picture at all with the prefix "{pre}" in diagrams/')
    if misses or notes:
        rep.add(WARN, 'diagrams', f'{len(misses) + len(notes)} hook-up picture problem(s): picture(s) not installed (the dialog shows the text instead and names the file)',
                [f'diagrams/{m}' if not m.startswith('diagrams') else m for m in misses] + notes)
    else:
        rep.add(PASS, 'diagrams', 'every hook-up picture the run looked for is installed' if prefixes or run.get('timeline') else 'no hook-up pictures used')


def _driver_files(run, proc):
    """drivers/*.py files the procedure's instruments come from: the MRO of every driver class used in the run (else the sidecar's driver modules)."""
    files = set()
    for path in (run.get('classes') or {}).values():
        cls = _resolve_class(path)
        if cls is None:
            continue
        for k in cls.__mro__:
            if k.__module__.startswith('drivers.') and not k.__module__.split('.')[-1].startswith('simulated'):
                files.add('drivers/' + k.__module__.split('.', 1)[1].replace('.', '/') + '.py')
    return files


ENGINE_LIKE = re.compile(r'(_verification|_adjustment|_option|handheld_dmm)$')


def expected_fingerprint(proc, run):
    """(expected files, why) - what a change to should flip the procedure."""
    exp = OrderedDict()
    exp[proc.launcher] = 'launcher'
    for e in proc.engine:
        exp[e] = 'engine named in the sidecar'
    tree = _parse(proc.launcher)
    if tree is not None:
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            for nm in names:
                top = nm.split('.')[0]
                if (ROOT / f'{top}.py').is_file() and ENGINE_LIKE.search(top):
                    exp.setdefault(f'{top}.py', 'engine imported by the launcher')
    for e in list(exp):
        if e.endswith('.py') and e != proc.launcher:
            t = _parse(e)
            if t is not None:
                for node in ast.walk(t):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
                    if 'procspec' in names:
                        exp.setdefault('procspec.py', 'spec loader imported by the engine')
    exp.setdefault('drivers/base.py', 'driver base class')
    exp.setdefault('drivers/transport.py', 'transports')
    for f in sorted(_driver_files(run, proc)):
        exp.setdefault(f, 'driver class used in the run')
    if not run.get('classes'):
        for d in proc.drivers:
            exp.setdefault(f'drivers/{d}.py', 'driver module named in the sidecar')
    for f in list(exp):                  # stop-on-surprise: an engine / driver that imports surprise.py depends on it
        if f.endswith('.py') and f != 'surprise.py':
            t = _parse(f)
            if t is not None:
                for node in ast.walk(t):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
                    if 'surprise' in names:
                        exp.setdefault('surprise.py', f'stop-on-surprise module imported by {f}')
                        break
    return exp


def shared_count():
    cnt = Counter()
    for p in procscan.procs(ROOT):
        for lab in p.fingerprint_code:
            cnt[procscan.split_label(lab)[0]] += 1
    return cnt


def check_fingerprint(rep, proc, run):
    listed = {procscan.split_label(l)[0]: l for l in proc.fingerprint_code}
    exp = expected_fingerprint(proc, run)
    missing = [f'{f}  ({why})' for f, why in exp.items() if f not in listed]
    extra = [f for f in listed if f not in exp and not f.startswith('hookups.py') and not (ROOT / f).suffix == '.json']
    notes = []
    if proc.hookup_meter and not any(l.startswith('hookups.py') for l in proc.fingerprint_code):
        missing.append(f'hookups.py#{proc.hookup_meter}  (the sidecar names the hook-up meter {proc.hookup_meter})')
    # spec files read by the run
    own_text = ''
    for rel in {proc.launcher, *proc.engine, 'procspec.py'}:
        try:
            own_text += file_of(rel).read_text(encoding='utf-8-sig', errors='replace')
        except OSError:
            pass
    # a spec file counts when the run read it AND the procedure's own sources name it (importing another engine for the harness reads that engine's spec)
    others = set()                       # specs that are the test-point file of ANOTHER procedure: read by a shared engine's queue / listing code, not a dependency of this one
    for q in procscan.procs(ROOT):
        if q.id != proc.id:
            others.update(procscan.split_label(l)[0] for l in (*q.fingerprint_spec, *q.specs))
    others -= {procscan.split_label(l)[0] for l in (*proc.fingerprint_spec, *proc.specs)}

    def spec_like(names):
        return [o for o in (names or []) if o.startswith('specs/') and not o.startswith('specs/standards/') and Path(o).name != 'a2la_1888_03_cmc.json'
                and Path(o).name in own_text and o not in others]
    opened = spec_like(run.get('opened'))
    import_only = [o for o in spec_like(run.get('opened_import')) if o not in opened]
    spec_listed = {procscan.split_label(l)[0] for l in proc.fingerprint_spec}
    spec_missing = [o for o in opened if o not in spec_listed]
    seen_any = set(run.get('opened') or []) | set(run.get('opened_import') or [])
    spec_unused = [s for s in sorted(spec_listed) if seen_any and s not in seen_any]
    import_only = [o for o in import_only if o not in spec_listed]
    for f in missing:
        notes.append('missing from the fingerprint list: ' + f)
    for f in spec_missing:
        notes.append('read by the run but not in the spec fingerprint: ' + f)
    cnt = shared_count()
    shared = sorted(((f, cnt[f]) for f in listed if cnt[f] >= 5 and f not in ('drivers/base.py', 'drivers/transport.py')), key=lambda t: -t[1])
    if missing or spec_missing:
        rep.add(WARN, 'fingerprint', 'the sidecar file list is incomplete: a change to these files would NOT flip "verified on hardware"', notes)
    else:
        rep.add(PASS, 'fingerprint', f'{len(listed)} code files + {len(spec_listed)} spec file(s) listed; every file the run depends on is in the list')
    if extra and run.get('classes'):
        rep.add(INFO, 'fingerprint', 'the sidecar lists driver / engine files this run did not use (other options or models may)', extra)
    sh = [f'{f} is in {n} procedures\' fingerprints (an edit flips all of them)' for f, n in shared]
    sh += [f'drivers/base.py and drivers/transport.py are in {cnt["drivers/base.py"]} / {cnt["drivers/transport.py"]} fingerprints (every driver procedure)']
    rep.add(INFO, 'fingerprint', 'shared files in the list (editing one flips every procedure that lists it)', sh)
    if import_only:
        rep.add(INFO, 'fingerprint', 'spec file(s) read only while importing (module-level defaults of a shared engine), not in the spec fingerprint', import_only)
    if spec_unused:
        rep.add(INFO, 'fingerprint', f'{len(spec_unused)} spec file(s) listed but not read in this run (other models / options?)', spec_unused[:SAMPLE])


def check_sidecar(rep, proc):
    sidecar = ROOT / proc.sidecar
    if not sidecar.is_file():
        rep.add(FAIL, 'sidecar', f'{proc.sidecar} does not exist: the Manager will not list the procedure and "verified on hardware" cannot track it')
        return
    probs = []
    for label in (*proc.engine, *proc.fingerprint_code, *proc.fingerprint_spec, *proc.specs, *proc.own_files):
        if not file_of(label).is_file():
            probs.append(f'file named in the sidecar does not exist: {label}')
    for d in proc.drivers:
        if not (ROOT / 'drivers' / f'{d}.py').is_file():
            probs.append(f'driver module named in the sidecar does not exist: drivers/{d}.py')
    if proc.hookup_meter and proc.hookup_meter not in getattr(hookups, 'METERS', {}):
        probs.append(f'hookup meter "{proc.hookup_meter}" is not in hookups.METERS')
    for t in proc.tests:
        if not (ROOT / t).is_file():
            probs.append(f'test file named in the sidecar does not exist: {t}')
    result = procscan.scan_folder(ROOT / 'Procedures')
    for name, reason in result.problems:
        if name.startswith(proc.id):
            probs.append(f'the Manager skips this sidecar: {reason}')
    if probs:
        rep.add(FAIL, 'sidecar', f'{len(probs)} problem(s) in the sidecar', probs)
    else:
        rep.add(PASS, 'sidecar', f'{proc.sidecar}: valid, every named file exists')


# ================================================================================================================ the branch against its base (shared-file touch)
def git(*args):
    r = subprocess.run(['git', *args], capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode, r.stdout


def default_base():
    for ref in ('origin/main', 'main'):
        if git('rev-parse', '--verify', '--quiet', ref)[0] == 0:
            return ref
    return None


def changed_files(base):
    """Files changed on this branch since it left `base`, plus uncommitted changes: {path: status}."""
    out = {}
    rc, text = git('diff', '--name-status', f'{base}...HEAD')
    if rc == 0:
        for line in text.splitlines():
            st, _, path = line.partition('\t')
            out[path.split('\t')[-1]] = st[0]
    rc, text = git('diff', '--name-status', 'HEAD')
    if rc == 0:
        for line in text.splitlines():
            st, _, path = line.partition('\t')
            out[path.split('\t')[-1]] = st[0]
    return out


def base_reader(base):
    def read(rel):
        r = subprocess.run(['git', 'show', f'{base}:{rel}'], capture_output=True, cwd=str(ROOT))
        return r.stdout if r.returncode == 0 else None
    return read


def work_reader():
    def read(rel):
        try:
            return (ROOT / rel).read_bytes()
        except OSError:
            return None
    return read


def base_procs(base):
    """The sidecars as they are on `base`: {id: Proc}."""
    rc, text = git('ls-tree', '--name-only', f'{base}', 'Procedures/')
    out = {}
    if rc != 0:
        return out
    for rel in text.splitlines():
        if not rel.endswith('.procedure.json'):
            continue
        raw = base_reader(base)(rel)
        try:
            doc = json.loads(raw.decode('utf-8-sig'))
            stem = Path(rel).name[:-len('.procedure.json')]
            out[stem] = procscan.parse_sidecar(doc, stem)
        except Exception:
            continue
    return out


def shared_touch(base=None, registry=None):
    """dict(base, changed, flipped: [(proc, why [files])], seeded: [ids], new: [ids])."""
    base = base or default_base()
    info = dict(base=base, changed={}, flipped=[], new=[], note='')
    if base is None:
        info['note'] = 'no git base (origin/main / main) found: not compared'
        return info
    ch = changed_files(base)
    info['changed'] = ch
    old = base_procs(base)
    cur = {p.id: p for p in procscan.procs(ROOT)}
    comp = verified.Registry.file_components
    seed = {p['proc_key'][:-3] for p in verified.SEED}
    rb, rw = base_reader(base), work_reader()
    for pid, proc in cur.items():
        if pid not in old:
            info['new'].append(pid)
            continue
        c0 = comp(None, old[pid], rb)
        c1 = comp(None, proc, rw)
        diffs = []
        for part in (0, 1):
            for lab in sorted(set(c0[part]) | set(c1[part])):
                if c0[part].get(lab) != c1[part].get(lab):
                    diffs.append(procscan.split_label(lab)[0] + (' (listed now)' if lab not in c0[part] else ' (no longer listed)' if lab not in c1[part] else ''))
        if diffs:
            info['flipped'].append((proc, diffs))
    info['seeded'] = sorted(seed)
    if registry:
        try:
            reg = verified.Registry(registry)
            info['registry_verified'] = sorted(k[:-3] for k, r in reg.records().items() if getattr(r, 'verified', False))
        except Exception as exc:
            info['note'] = f'registry {registry} not read: {exc}'
    return info


def check_shared(rep, info, proc=None):
    if info['note']:
        rep.add(INFO, 'shared', info['note'])
        return
    ch = info['changed']
    if not ch:
        rep.add(PASS, 'shared', f'no file changed against {info["base"]}: no procedure fingerprint flips')
        return
    flipped = info['flipped']
    verified_ids = set(info.get('registry_verified') or info.get('seeded') or [])
    hit_verified = [p for p, _d in flipped if p.id in verified_ids]
    cnt = shared_count()
    shared_files = sorted((f for f in ch if cnt.get(f)), key=lambda f: -cnt[f])
    details = [f'{f} ({ch[f]}) is in {cnt[f]} procedure fingerprint(s)' for f in shared_files]
    details += [f'{p.id}: {", ".join(d)}' for p, d in flipped[:12]]
    if len(flipped) > 12:
        details.append(f'... and {len(flipped) - 12} more')
    src = 'recorded as verified in the registry given' if info.get('registry_verified') is not None else 'seeded verified list (TDS2000C, WaveSurfer, Fluke 117); the real list is in the lab registry on the owner\'s machine'
    if hit_verified:
        rep.add(FAIL, 'shared', f'{len(flipped)} existing procedure(s) flip to "Changed since verification" against {info["base"]}, including VERIFIED: '
                + ', '.join(p.id for p in hit_verified) + f'  [{src}]', details)
    elif flipped:
        rep.add(WARN, 'shared', f'{len(flipped)} existing procedure(s) flip to "Changed since verification" against {info["base"]} (none of the seeded verified ones; {src})', details)
    else:
        rep.add(PASS, 'shared', f'{len(ch)} file(s) changed against {info["base"]}; no existing procedure fingerprint flips'
                + (f'; new procedure(s): {", ".join(info["new"])}' if info['new'] else ''))
    if info['new']:
        rep.add(INFO, 'shared', 'procedures new on this branch: ' + ', '.join(info['new']))


# ================================================================================================================ one procedure
def check_procedure(proc, run_it=True, shared=None, timeout=RUN_TIMEOUT_S, base=None):
    rep = Report(proc)
    import time
    t0 = time.time()
    reason = static_only_reason(proc)
    run = {}
    if run_it and not reason:
        run = run_dynamic(proc, timeout)
    rep.run = run
    timeline = run.get('timeline', [])
    check_sidecar(rep, proc)
    if run_it:
        check_run(rep, run, proc, reason)
    regs = registries(run, proc)
    if timeline and not run.get('error') or timeline:
        tr = transcript(timeline, regs)
        check_commands(rep, tr, regs, run)
        check_readback(rep, tr)
        check_outputs(rep, tr, timeline)
        check_prompts(rep, timeline, run)
        check_uncertainty(rep, run)
    else:
        check_static_commands(rep, proc, regs)
    files = [proc.launcher, *proc.engine]
    check_raw_sends(rep, proc, run, regs, sorted({*files, *_driver_files(run, proc), *(f'drivers/{d}.py' for d in proc.drivers if not run.get('classes'))} - {'drivers/base.py', 'drivers/transport.py'}))
    check_tunables(rep, proc, run, files)
    check_housekeeping(rep, regs, {(l, k) for _i, l, k, _w, _c in tr} if timeline else None)
    check_diagrams(rep, proc, run)
    check_fingerprint(rep, proc, run)
    if shared is not None:
        check_shared(rep, shared, proc)
    check_surprise(rep, proc, regs, shared)
    rep.findings.sort(key=lambda f: 0)                       # keep insertion order (stable)
    rep.seconds = round(time.time() - t0, 1)
    return rep


# ================================================================================================================ output
MARK = {PASS: 'PASS', WARN: 'WARN', FAIL: 'FAIL', INFO: 'info'}


def render(rep, verbose=False):
    p = rep.proc
    run = rep.run
    lines = [f'READINESS  {p.name}  [{p.id}]', f'engine: {", ".join(p.engine) or p.launcher}   '
             f'result: {rep.worst}   ({rep.counts.get(FAIL, 0)} FAIL, {rep.counts.get(WARN, 0)} WARN)   {rep.seconds} s']
    for f in rep.findings:
        lines.append(f'  {MARK[f.level]:<4} {f.check:<12} {f.text}')
        shown = f.details if verbose else (f.details[:DETAIL_LINES] if (f.level != INFO or f.show) else [])
        for d in shown:
            lines.append(f'         - {d}')
        if len(f.details) > len(shown):
            lines.append(f'         ... {len(f.details) - len(shown)} {"more" if shown else "detail line(s)"} (--verbose)')
    return '\n'.join(lines)


def render_table(reports):
    lines = [f'{"procedure":<38} {"engine":<28} {"FAIL":>4} {"WARN":>4}  result']
    for r in reports:
        eng = (r.proc.engine[0] if r.proc.engine else 'launcher')[:28]
        lines.append(f'{r.proc.id:<38} {eng:<28} {r.counts.get(FAIL, 0):>4} {r.counts.get(WARN, 0):>4}  {r.worst}')
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Readiness check of a calibration procedure (simulated bench; no hardware).')
    ap.add_argument('procedure', nargs='?', help='procedure id, launcher file or sidecar file')
    ap.add_argument('--all', action='store_true', help='every registered procedure')
    ap.add_argument('--json', metavar='FILE', help='write the full result as JSON')
    ap.add_argument('--verbose', action='store_true', help='all detail lines')
    ap.add_argument('--no-run', action='store_true', help='static checks only (no simulated run)')
    ap.add_argument('--strict', action='store_true', help='exit 1 on WARN as well')
    ap.add_argument('--base', help='git ref the branch is compared with (default origin/main, else main)')
    ap.add_argument('--registry', help='lab_registry.sqlite3 to read the real "verified on hardware" list from')
    ap.add_argument('--timeout', type=int, default=RUN_TIMEOUT_S)
    args = ap.parse_args(argv)
    _load_modules()
    if not args.procedure and not args.all:
        ap.error('give a procedure or --all')
    procs = procscan.procs(ROOT) if args.all else [resolve(args.procedure)]
    shared = shared_touch(args.base, args.registry)
    reports = []
    for proc in procs:
        reports.append(check_procedure(proc, run_it=not args.no_run, shared=shared, timeout=args.timeout))
        if args.all:
            print(f'{reports[-1].worst:<5} {proc.id}', file=sys.stderr, flush=True)
    if args.all:
        print(render_table(reports))
        print()
        branch = Report(procs[0])
        check_shared(branch, shared)
        for f in branch.findings:
            print(f'  {MARK[f.level]:<4} shared       {f.text}')
            for d in (f.details if args.verbose else f.details[:DETAIL_LINES]):
                print(f'         - {d}')
    else:
        print(render(reports[0], args.verbose))
    if args.json:
        data = [r.as_dict() for r in reports]
        Path(args.json).write_text(json.dumps(dict(base=shared.get('base'), reports=data, shared=dict(changed=shared['changed'], flipped=[(p.id, d) for p, d in shared['flipped']],
                                                                                                    new=shared['new'])), indent=1, default=str), encoding='utf-8')
    worst = [r.worst for r in reports]
    bad = FAIL in worst or (args.strict and WARN in worst)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
