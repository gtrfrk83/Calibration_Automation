"""Uniformity rules (NOTES.md, 'Uniformity rules', owner 2026-11-05): one check per rule over every shipped procedure.

A check lists violations as stable text keys.  tests/fixtures/conformance_allowlist.json holds
    - 'rules' -> violations: the violations that existed when the rules were adopted (the cleanup backlog, to be fixed), and
    - 'exceptions': findings that are correct as they are, each with its reason (a meter that picks AC or DC itself needs no dial prompt).
A test fails when
    - a NEW violation appears (not in the allowlist): fix it, or, only with the owner's agreement, add it to the allowlist with the reason; or
    - an allowlisted violation is GONE (it was fixed): remove it from the allowlist, so it cannot come back unnoticed.
Regenerate the allowlist only after reviewing the change (it keeps the reasons already written):
    python tests/test_procedure_conformance.py --write-allowlist
Run:  python -m unittest tests.test_procedure_conformance
Nothing here talks to an instrument; rule 9 runs the spec builders in a temporary copy of the suite, never in the real folder.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import procscan  # noqa: E402
import uniformity  # noqa: E402

ALLOWLIST_PATH = ROOT / 'tests' / 'fixtures' / 'conformance_allowlist.json'

# handheld_dmm.py's built-in option defaults (what a spec gets when it leaves an option out), until the engine reads specs/handheld_defaults.json
# (handheld_dmm.App._high_voltage 'hv_threshold_v' 500, _hv_group_seen opt-in, _auto_ramp True, _prompt_function opt-in, report_title()).
ENGINE_DEFAULTS = {'hv_threshold_v': 500, 'hv_once_per_group': False, 'auto_ramp': True, 'function_prompt': False, 'report_title': None}
CALIBRATORS = ('5520A', '5522A', '5560A', '5700A')
HV_RE = re.compile(r'high[ -]voltage', re.I)
VOLT_RE = re.compile(r'\d\s*V\b|volt', re.I)
COUNT_RES = (re.compile(r'(\d+)\s+(?:test\s+)?points?\b'), re.compile(r'\((\d+)\s+without\b'))


# ---------------------------------------------------------------------------------------------------- helpers

@lru_cache(maxsize=None)
def procs():
    result = procscan.scan()
    assert not result.problems, result.problems
    return tuple(result.procs)


@lru_cache(maxsize=None)
def allowlist():
    return json.loads(ALLOWLIST_PATH.read_text(encoding='utf-8'))


@lru_cache(maxsize=None)
def sidecar(pid):
    return json.loads((ROOT / 'Procedures' / f'{pid}.procedure.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=None)
def text(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


@lru_cache(maxsize=None)
def load_json(rel):
    return json.loads(text(rel))


def code_files(p):
    """The procedure's own code: the launcher and the engine modules its sidecar names (that exist)."""
    return [p.launcher] + [e for e in p.engine if (ROOT / e).is_file() and e != p.launcher]


def is_handheld(p):
    return 'handheld_dmm.py' in p.engine


def handheld_spec(p):
    """(spec path, spec dict, model key) of a handheld_dmm procedure, or None."""
    for rel in p.specs:
        spec = load_json(rel)
        if isinstance(spec, dict) and 'steps' in spec and isinstance(spec.get('models'), dict):
            parts = [procscan.split_label(label)[1] for label in p.fingerprint_spec if procscan.split_label(label)[0] == rel]
            model = next((x for x in parts if x), None) or (next(iter(spec['models'])) if len(spec['models']) == 1 else None)
            if model:
                return rel, spec, model
    return None


@lru_cache(maxsize=None)
def handheld_points(pid):
    import handheld_dmm
    p = next(x for x in procs() if x.id == pid)
    rel, spec, model = handheld_spec(p)
    return handheld_dmm.points_for(spec, model)


def options(spec):
    return spec.get('options', {}) or {}


def effective(spec, key):
    return options(spec).get(key, ENGINE_DEFAULTS[key])


def group_prompts(p, spec, group):
    """[(calibrator key, title + steps + caution text, caution)] the operator sees for a cable change to `group`."""
    import hookups
    meter = options(spec).get('hookup_meter') or p.hookup_meter
    out = []
    if meter and hookups.has(meter, group):
        for cal in ('5560A', '5522A'):
            plan = hookups.plan(meter, cal, group) or {}
            body = ' '.join([plan.get('title') or ''] + [' '.join(map(str, s)) for s in plan.get('steps') or ()] + [plan.get('caution') or ''])
            out.append((cal, body, plan.get('caution')))
        return out
    g = (spec.get('groups') or {}).get(group)
    if g:
        body = ' '.join([g.get('title') or ''] + [' '.join(map(str, s)) for s in g.get('steps') or ()] + [g.get('caution') or ''])
        out.append(('spec', body, g.get('caution')))
    return out


def local_module(name, src):
    for c in (ROOT / (name.replace('.', '/') + '.py'), ROOT / name.replace('.', '/') / '__init__.py', src.parent / (name.split('.')[-1] + '.py')):
        if c.is_file():
            return c.relative_to(ROOT).as_posix()
    return None


@lru_cache(maxsize=None)
def direct_imports(rel):
    tree = ast.parse(text(rel))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            names.add(n.module)
            names.update(f'{n.module}.{a.name}' for a in n.names)
    return frozenset(m for m in (local_module(x, ROOT / rel) for x in names) if m)


def data_files(rel):
    """specs/*.json files a code file names in a string literal (by path or bare file name)."""
    out = set()
    for name in re.findall(r"""['"]((?:specs/)?[\w.\-]+\.json)['"]""", text(rel)):
        cand = ROOT / name if name.startswith('specs/') else ROOT / 'specs' / name
        if cand.is_file():
            out.add(cand.relative_to(ROOT).as_posix())
    return out


# ---------------------------------------------------------------------------------------------------- the checks (rule number -> violation keys)

def rule1_high_voltage():
    """30 V everywhere, once per hook-up group, a written caution on every hook-up group that has a point at or above it."""
    out = set()
    seen_specs = set()
    for p in procs():
        if is_handheld(p) and handheld_spec(p):
            rel, spec, model = handheld_spec(p)
            if rel not in seen_specs:
                seen_specs.add(rel)
                if effective(spec, 'hv_threshold_v') != uniformity.HV_THRESHOLD_V:
                    out.add(f'{rel}: threshold {effective(spec, "hv_threshold_v")} V')
                if not effective(spec, 'hv_once_per_group'):
                    out.add(f'{rel}: asked every point')
            hv_groups = {pt['group'] for pt in handheld_points(p.id)
                         if pt['group'] != 'NONE' and pt.get('applied') and pt['kind'] in ('DCV', 'ACV')
                         and abs(pt['applied']['value']) >= uniformity.HV_THRESHOLD_V}
            for g in sorted(hv_groups):
                prompts = group_prompts(p, spec, g)
                if not prompts or not all(c and VOLT_RE.search(c) for _, _, c in prompts):
                    out.add(f'{p.id}: group {g} has no high-voltage caution')
        else:
            for rel in code_files(p):
                if HV_RE.search(text(rel)) and 'HV_THRESHOLD_V' not in text(rel):
                    out.add(f'{rel}: own high-voltage threshold')
    return out


def rule2_function_prompts():
    """Consecutive points that differ in function (kind) must differ in switch text or carry their own prompt (handheld_dmm specs)."""
    out = set()
    for p in procs():
        if not (is_handheld(p) and handheld_spec(p)):
            continue
        _, spec, _ = handheld_spec(p)
        last = None
        for pt in handheld_points(p.id):
            if pt['group'] == 'NONE':
                last = pt
                continue
            covered = pt.get('prompt') or (options(spec).get('range_prompt') and pt.get('dial'))
            if last is not None and last['group'] != 'NONE' and pt['kind'] != last['kind'] and pt['switch'] == last['switch'] and not covered:
                out.add(f'{p.id}: {last["id"]} {last["kind"]} -> {pt["id"]} {pt["kind"]} on the same switch text')
            last = pt
    return out


def rule3_calibrator_safeguards():
    """Engines leave calibrator safeguards to the shared driver: no operate_unverified(), no OUT_IMP written by an engine."""
    out = set()
    files = {rel for p in procs() for rel in code_files(p)}
    for rel in sorted(files):
        src = text(rel)
        if re.search(r'operate_unverified\s*\(', src):
            out.add(f'{rel}: calls operate_unverified')
        if 'OUT_IMP' in src:
            out.add(f'{rel}: writes OUT_IMP itself')
    return out


def rule4_calibrators_named():
    """Cable prompts that name a calibrator name every calibrator the procedure offers, and no other (handheld_dmm procedures)."""
    import calibrator_fit
    out = set()
    for p in procs():
        if not (is_handheld(p) and handheld_spec(p)):
            continue
        _, spec, _ = handheld_spec(p)
        pts = handheld_points(p.id)
        offered = {'5560A', '5522A'}
        try:
            if calibrator_fit.make_offer('5520A', calibrator_fit.handheld_requests(pts)).offered:
                offered.add('5520A')
        except Exception as exc:                                # a broken fit is its own problem; say so instead of hiding it
            out.add(f'{p.id}: 5520A offer could not be worked out ({type(exc).__name__})')
        for g in sorted({pt['group'] for pt in pts if pt['group'] != 'NONE'}):
            body = ' '.join(b for _, b, _ in group_prompts(p, spec, g))
            if not any(cal in body for cal in CALIBRATORS):      # generic wording ('the calibrator') names none, which is fine
                continue
            for cal in sorted(offered):
                if cal not in body:
                    out.add(f'{p.id}: group {g} does not name the {cal}')
            for cal in CALIBRATORS:
                if cal not in offered and cal in body:
                    out.add(f'{p.id}: group {g} names the {cal}, which it does not offer')
    return out


def rule5_adjustments():
    """Every adjustment procedure goes through adjustment_audit; a secret never reaches a transport error message."""
    out = set()
    for p in procs():
        if p.effective_kind != procscan.KIND_ADJUSTMENT and p.family != 'adjustment':
            continue
        if 'adjustment_audit.py' not in p.engine or not any('adjustment_audit' in text(rel) for rel in code_files(p)):
            out.add(f'{p.id}: not on adjustment_audit')
    if secret_leaks_in_transport_error():
        out.add('drivers/base.py: a secret placeholder reaches the transport error text')
    return out


def secret_leaks_in_transport_error():
    import cmdreg
    from drivers.base import Instrument
    from drivers.transport import Transport, TransportError

    class Failing(Transport):
        name = 'failing'
        def open(self): pass
        def close(self): pass
        def set_timeout(self, seconds): pass
        def write(self, text): raise TransportError(f'write {text!r} failed: device gone')
        def query(self, text): raise TransportError(f'query {text!r} failed: device gone')

    class Probe(Instrument):
        MODEL = 'probe'
        COMMANDS = {'unlock': cmdreg.Cmd('CAL:SEC:STAT OFF,{password}', 'Unlock', 'test', placeholders={'password': cmdreg.Placeholder('secret')},
                                         kind='set')}

    inst = Probe(Failing())
    try:
        inst.send('unlock', password='Zx9-not-a-real-code')
    except Exception as exc:
        chain, e = [], exc
        while e is not None:
            chain.append(f'{e} {e!r}')
            e = e.__cause__ or e.__context__
        return 'Zx9-not-a-real-code' in ' '.join(chain)
    return False


def rule6_warmup():
    """Each sidecar declares the warm-up: {"minutes": n, "ref": "<manual, page>"} (0 minutes when the manuals state none); a procedure with a
    warm-up asks for it."""
    out = set()
    for p in procs():
        w = sidecar(p.id).get('warmup')
        if not (isinstance(w, dict) and isinstance(w.get('minutes'), int) and not isinstance(w.get('minutes'), bool)
                and w['minutes'] >= 0 and isinstance(w.get('ref'), str) and w['ref'].strip()):
            out.add(f'{p.id}: warm-up not declared')
        elif w['minutes'] > 0 and not any(re.search(r'warm', text(rel), re.I) for rel in code_files(p)):
            out.add(f'{p.id}: {w["minutes"]} min warm-up never asked')
    return out


def rule7_pass_fail():
    """Pass/fail goes through uniformity.within_limits (exact decimal, on-limit passes)."""
    return {f'{p.id}: own pass/fail comparison' for p in procs() if not any('within_limits' in text(rel) for rel in code_files(p))}


def rule8_fingerprints():
    """The fingerprint lists every procedure module, driver and data file the procedure's code imports or names; shared infrastructure
    (allowlist 'shared_modules') is in no fingerprint."""
    shared = set(allowlist()['shared_modules'])
    procedure_specs = {rel for p in procs() for rel in p.specs}     # a shared engine names other models' spec files (defaults): not a dependency
    out = set()
    listed_anywhere = set()
    for p in procs():
        have = {procscan.split_label(label)[0] for label in (*p.fingerprint_code, *p.fingerprint_spec)}
        listed_anywhere |= have
        need = set()
        for rel in code_files(p):
            need |= direct_imports(rel)
            need |= {d for d in data_files(rel) if d not in procedure_specs or d in p.specs}
        for rel in sorted(need - have - shared - {p.launcher}):
            out.add(f'{p.id}: fingerprint misses {rel}')
    for rel in sorted(shared & listed_anywhere):
        out.add(f'shared module {rel} is in a fingerprint')
    return out


NOT_SPEC_BUILDERS = {'build_hookups.py', 'build_hookups_753.py', 'build_hookups_ext.py', 'build_hookups_u1251b.py', 'build_standard_spec.py'}
NOT_SPECS = {'specs/handheld_defaults.json'}
VOLATILE_KEYS = ('built', 'generated', 'sheet_generated')


def _normal(obj):
    if isinstance(obj, dict):
        return {k: _normal(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_normal(x) for x in obj]
    return obj


@lru_cache(maxsize=None)
def rule9_builders():
    """Every spec JSON has a committed builder with repo-relative paths, and running it reproduces the committed file."""
    out = set()
    for p in procs():
        if not p.specs:
            out.add(f'{p.id}: limits in the code, no spec file')
    builders = sorted(b for b in (ROOT / 'specs').glob('build_*.py') if b.name not in NOT_SPEC_BUILDERS)
    jsons = sorted(j.relative_to(ROOT).as_posix() for j in [*(ROOT / 'specs').glob('*.json'), *(ROOT / 'specs' / 'standards').glob('*.json')])
    jsons = [j for j in jsons if j not in NOT_SPECS]
    for b in builders:
        if re.search(r"""['"](/home/|/mnt/|/Users/|[A-Za-z]:[\\/])""", b.read_text(encoding='utf-8')):
            out.add(f'specs/{b.name}: absolute path')
    for j in jsons:
        name = j.rsplit('/', 1)[-1]
        if not any(name in b.read_text(encoding='utf-8') for b in builders):
            out.add(f'{j}: no builder')
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / 'suite'
        shutil.copytree(ROOT, copy, ignore=lambda d, names: [n for n in names if n in ('.git', 'diagrams', '__pycache__', 'tests') or n.lower().endswith('.pdf')])
        for b in builders:
            r = subprocess.run([sys.executable, str(copy / 'specs' / b.name)], cwd=copy, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                out.add(f'specs/{b.name}: does not run')
        for j in jsons:
            new, old = (copy / j), (ROOT / j)
            if new.read_bytes() != old.read_bytes() and _normal(json.loads(new.read_text(encoding='utf-8'))) != _normal(json.loads(old.read_text(encoding='utf-8'))):
                out.add(f'{j}: differs from what its builder writes')
    return frozenset(out)


def rule10_handheld_defaults():
    """A handheld spec option that differs from specs/handheld_defaults.json gives its reason in options.option_reasons."""
    defaults = uniformity.handheld_defaults()
    out = set()
    for rel in sorted({handheld_spec(p)[0] for p in procs() if is_handheld(p) and handheld_spec(p)}):
        spec = load_json(rel)
        reasons = options(spec).get('option_reasons') or {}
        for key, want in defaults.items():
            got = effective(spec, key)
            if got != want and not str(reasons.get(key) or '').strip():
                out.add(f'{rel}: {key} is {got!r} without a reason')
    return out


def _count_candidates(p):
    if is_handheld(p) and handheld_spec(p):
        pts = handheld_points(p.id)
        n = len(pts)
        return {n, n - sum(1 for x in pts if x.get('include')), n - sum(1 for x in pts if x['group'] == 'NONE'),
                n - sum(1 for x in pts if x.get('test') == 'visual')}
    for rel in p.specs:
        spec = load_json(rel)
        if isinstance(spec, dict) and isinstance(spec.get('sections'), list):
            return {sum(len(s.get('points') or ()) for s in spec['sections'])}
    return set()


def rule11_point_counts():
    """Point counts written in the sidecar description, the launcher docstring and the handheld spec model note match the spec."""
    out = set()
    for p in procs():
        cands = _count_candidates(p)
        if not cands:
            continue
        sources = [('description', p.description), ('launcher docstring', ast.get_docstring(ast.parse(text(p.launcher))) or '')]
        if is_handheld(p) and handheld_spec(p):
            _, spec, model = handheld_spec(p)
            sources.append(('spec model note', str(spec['models'][model].get('model_note') or '')))
        for where, body in sources:
            for rx in COUNT_RES:
                for m in rx.finditer(body):
                    if int(m.group(1)) not in cands:
                        out.add(f'{p.id}: {where} says {m.group(1)} points (spec: {", ".join(map(str, sorted(cands)))})')
    return out


def rule12_family():
    """Every sidecar names its family (uniformity.FAMILIES)."""
    return {f'{p.id}: family {p.family!r}' for p in procs() if p.family not in uniformity.FAMILIES}


CHECKS = {'1': rule1_high_voltage, '2': rule2_function_prompts, '3': rule3_calibrator_safeguards, '4': rule4_calibrators_named,
          '5': rule5_adjustments, '6': rule6_warmup, '7': rule7_pass_fail, '8': rule8_fingerprints, '9': rule9_builders,
          '10': rule10_handheld_defaults, '11': rule11_point_counts, '12': rule12_family}


# ---------------------------------------------------------------------------------------------------- tests

class Conformance(unittest.TestCase):
    def check(self, rule):
        found = set(CHECKS[rule]())
        excepted = allowlist().get('exceptions', {}).get(rule, {})
        allowed = set(allowlist()['rules'].get(rule, {}).get('violations', []))
        new, fixed = sorted(found - allowed - set(excepted)), sorted(allowed - found)
        msg = []
        unused = sorted(set(excepted) - found)
        if unused:
            msg.append(f'rule {rule}: {len(unused)} exception(s) no longer match anything: remove them from {ALLOWLIST_PATH.name}:\n  ' + '\n  '.join(unused))
        blank = sorted(k for k, why in excepted.items() if not str(why).strip())
        if blank:
            msg.append(f'rule {rule}: exception(s) without a reason:\n  ' + '\n  '.join(blank))
        if new:
            msg.append(f'rule {rule}: {len(new)} new violation(s) (fix them; see NOTES.md, Uniformity rules):\n  ' + '\n  '.join(new))
        if fixed:
            msg.append(f'rule {rule}: {len(fixed)} allowlisted violation(s) no longer happen: remove them from {ALLOWLIST_PATH.name}:\n  ' + '\n  '.join(fixed))
        if msg:
            self.fail('\n'.join(msg))

    def test_rule01_high_voltage(self): self.check('1')
    def test_rule02_function_prompts(self): self.check('2')
    def test_rule03_calibrator_safeguards(self): self.check('3')
    def test_rule04_calibrators_named(self): self.check('4')
    def test_rule05_adjustments(self): self.check('5')
    def test_rule06_warmup(self): self.check('6')
    def test_rule07_pass_fail(self): self.check('7')
    def test_rule08_fingerprints(self): self.check('8')
    def test_rule09_builders(self): self.check('9')
    def test_rule10_handheld_defaults(self): self.check('10')
    def test_rule11_point_counts(self): self.check('11')
    def test_rule12_family(self): self.check('12')

    def test_allowlist_names_only_known_rules(self):
        self.assertEqual(set(allowlist()['rules']) - set(CHECKS), set())
        self.assertEqual(set(allowlist().get('exceptions', {})) - set(CHECKS), set())


class WithinLimits(unittest.TestCase):
    """uniformity.within_limits: exact decimal, limits inclusive (rule 7)."""
    def test_on_the_limit_passes(self):
        self.assertTrue(uniformity.within_limits(-100.0091, -100.0091, -99.9909))
        self.assertTrue(uniformity.within_limits('-99.9909', '-100.0091', '-99.9909'))
        self.assertFalse(abs(-100.0091 + 100) <= 0.0091)          # what a float comparison does with the same numbers

    def test_outside_fails_and_order_of_limits_does_not_matter(self):
        self.assertFalse(uniformity.within_limits('-100.0092', '-100.0091', '-99.9909'))
        self.assertTrue(uniformity.within_limits(5, 6, 4))

    def test_not_a_number_raises(self):
        with self.assertRaises(ValueError):
            uniformity.within_limits('OL', 0, 1)


def write_allowlist():
    """Rewrite the allowlist from the current violations, keeping the shared-module list and every reason already written."""
    old = json.loads(ALLOWLIST_PATH.read_text(encoding='utf-8')) if ALLOWLIST_PATH.is_file() else {}
    exceptions = old.get('exceptions', {})
    data = {'note': old.get('note', ''), 'shared_modules': old.get('shared_modules', []), 'exceptions': exceptions, 'rules': {}}
    for rule, fn in CHECKS.items():
        prev = old.get('rules', {}).get(rule, {})
        data['rules'][rule] = {'title': (fn.__doc__ or '').strip().split('\n')[0], 'reason': prev.get('reason', ''),
                               'violations': sorted(set(fn()) - set(exceptions.get(rule, {})))}
    ALLOWLIST_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    for rule, block in data['rules'].items():
        print(f'rule {rule}: {len(block["violations"])}')


if __name__ == '__main__':
    if '--write-allowlist' in sys.argv:
        write_allowlist()
    else:
        unittest.main()
