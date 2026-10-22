"""Golden command transcripts: the drivers must keep sending exactly the same strings, in the same order.

Re-captures every transcript (tests/golden_capture.py) and compares it with the recorded fixtures in tests/golden/*.json. A mismatch prints
the first differing cases as a unified diff. If a change of wire behaviour is intended, review it and rewrite the fixtures explicitly:

    python -m tests.golden_capture --update

Also here: the coverage test (a driver class that gains a public method must be added to golden_capture.COVERAGE together with a golden
case, or to its no_command list) and the f-string lint baseline (self.write(f'...') / self.query(f'...') per driver; the registry refactor
ratchets it down to zero except for locked commands).
"""
import difflib
import importlib
import inspect
import json
import pkgutil
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import drivers  # noqa: E402
from tests import golden_capture as gc  # noqa: E402

HOW_TO_UPDATE = '\nIf this change is intended, review it, then run:  python -m tests.golden_capture --update'

# Locked commands may keep an f-string after the registry refactor (outputs, calibration): {driver file stem: {pattern key: allowed count}}.
# Today everything is baseline; the refactor lowers tests/golden/fstring_lint_baseline.json and fills this in only for locked commands.
LOCKED_FSTRING_ALLOWED = {}

_cache = {}


def captured():
    if 'files' not in _cache:
        _cache['files'] = gc.capture_all()
    return _cache['files']


def entry_diff(name, want_text, got_text, limit=70):
    want, got = json.loads(want_text), json.loads(got_text)
    w = {e['case']: e for e in want['entries']} if 'entries' in want else {}
    g = {e['case']: e for e in got['entries']} if 'entries' in got else {}
    lines = []
    for case in list(w) + [c for c in g if c not in w]:
        if w.get(case) == g.get(case):
            continue
        if case not in g:
            lines.append(f'--- case removed: {case}')
            continue
        if case not in w:
            lines.append(f'+++ case added:   {case}')
            continue
        a = gc.dumps(w[case]).splitlines()
        b = gc.dumps(g[case]).splitlines()
        lines.append(f'@@ {case}')
        lines.extend(difflib.unified_diff(a, b, 'recorded', 'now', lineterm='', n=2))
        if len(lines) > limit:
            break
    if not lines:
        lines = list(difflib.unified_diff(want_text.splitlines(), got_text.splitlines(), 'recorded', 'now', lineterm='', n=2))
    shown = lines[:limit]
    more = f'\n... {len(lines) - limit} more diff lines' if len(lines) > limit else ''
    return f'{name}: transcript differs from the golden fixture\n' + '\n'.join(shown) + more + HOW_TO_UPDATE


class GoldenFixtures(unittest.TestCase):
    def test_fixture_files_match_the_captured_set(self):
        have = {p.name for p in gc.GOLDEN.glob('*.json')}
        want = set(captured())
        self.assertEqual(sorted(have - want), [], 'fixture files that no longer correspond to a capture (remove them)' + HOW_TO_UPDATE)
        self.assertEqual(sorted(want - have), [], 'captures without a recorded fixture' + HOW_TO_UPDATE)

    def test_every_transcript_matches_its_fixture(self):
        bad = []
        for fname, text in sorted(captured().items()):
            path = gc.GOLDEN / fname
            if not path.exists():
                bad.append(f'{fname}: no fixture recorded')
                continue
            recorded = path.read_text(encoding='utf-8')
            if recorded != text:
                bad.append(entry_diff(fname, recorded, text))
        if bad:
            self.fail('\n\n'.join(bad))

    def test_capture_is_deterministic(self):
        again = gc.capture_all()
        first = captured()
        self.assertEqual(sorted(first), sorted(again))
        for fname in first:
            self.assertEqual(first[fname], again[fname], f'{fname} changed between two captures in one process: the capture is not deterministic')

    def test_fixtures_are_human_diffable(self):
        for path in gc.GOLDEN.glob('*.json'):
            text = path.read_text(encoding='utf-8')
            data = json.loads(text)
            self.assertEqual(text, gc.dumps(data), f'{path.name} is not sorted-keys / indent 1 JSON')

    def test_no_secret_or_address_in_any_fixture(self):
        for path in gc.GOLDEN.glob('*.json'):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn(gc.SENTINEL_PASSWORD, text, path.name)
            self.assertIsNone(re.search(r'CAL:SEC:STAT\s+(?:ON|OFF),(?!\*{8}|<password masked)', text), f'{path.name}: unmasked calibration password')
            self.assertIsNone(re.search(r' at 0x[0-9a-fA-F]+', text), f'{path.name}: object address in a fixture (not deterministic)')
            self.assertNotRegex(text, r'20[0-9]{2}-[0-9]{2}-[0-9]{2}T', f'{path.name}: timestamp in a fixture')

    def test_password_commands_are_masked_in_wire_and_log(self):
        text = (gc.GOLDEN / 'scpi_dmm.json').read_text(encoding='utf-8')
        self.assertIn('CAL:SEC:STAT OFF,********', text)           # CommandLog form (log_as)
        self.assertIn('CAL:SEC:STAT ON,********', text)
        self.assertIn('<password masked, ', text)                  # wire record keeps only the length


# ---------------------------------------------------------------------------------------------------------------------------------------
def driver_classes():
    """{class name: class} for every Instrument subclass defined in a public module of drivers/ (including Instrument itself)."""
    found = {}
    for info in pkgutil.iter_modules(drivers.__path__):
        if info.name.startswith('_'):                      # _template.py is documentation, not a driver
            continue
        mod = importlib.import_module('drivers.' + info.name)
        for name, cls in vars(mod).items():
            if inspect.isclass(cls) and issubclass(cls, drivers.Instrument) and cls.__module__ == mod.__name__:
                found[name] = cls
    return found


def public_names(cls):
    return {n for n, v in vars(cls).items()
            if not n.startswith('_') and (inspect.isfunction(v) or isinstance(v, (staticmethod, classmethod, property)))}


class GoldenCoverage(unittest.TestCase):
    table = {cname: spec for classes in gc.COVERAGE.values() for cname, spec in classes.items()}

    def test_every_driver_class_is_in_the_table(self):
        missing = sorted(set(driver_classes()) - set(self.table))
        self.assertEqual(missing, [], 'driver classes without a golden coverage entry (add them to golden_capture.COVERAGE and write cases)')

    def test_no_new_public_method_without_a_golden_entry(self):
        problems = []
        for name, cls in sorted(driver_classes().items()):
            spec = self.table.get(name)
            if spec is None:
                continue
            listed = set(spec['covered']) | set(spec['no_command'])
            new = sorted(public_names(cls) - listed)
            if new:
                problems.append(f'{name} has public method(s) {new} with no golden case: add a case to tests/golden_capture.py and list them '
                                f'in COVERAGE[...]["covered"] (or in "no_command" if they send nothing)')
            stale = sorted(n for n in listed if not hasattr(cls, n))
            if stale:
                problems.append(f'{name}: COVERAGE lists {stale} which the class no longer has')
            both = sorted(set(spec['covered']) & set(spec['no_command']))
            if both:
                problems.append(f'{name}: {both} listed as both covered and no_command')
        self.assertEqual(problems, [])

    def test_every_covered_method_has_a_recorded_case(self):
        classes = driver_classes()
        recorded = set()
        for fname, text in captured().items():
            if fname.startswith('engine_') or not fname.endswith('.json') or fname.startswith('fstring'):
                continue
            for e in json.loads(text)['entries']:
                cname, _, mname = e['method'].partition('.')
                cls = classes.get(cname)
                chain = [k.__name__ for k in cls.__mro__] if cls else [cname]
                recorded.update((k, mname) for k in chain)            # a case on a subclass exercises the inherited method
        missing = [f'{c}.{m}' for c, spec in sorted(self.table.items()) for m in spec['covered'] if (c, m) not in recorded]
        self.assertEqual(missing, [], 'covered methods with no golden case (a case name must start with "Class.method")')

    def test_every_case_belongs_to_a_covered_method(self):
        orphans = []
        for fname, text in captured().items():
            if fname.startswith('engine_') or fname.startswith('fstring'):
                continue
            for e in json.loads(text)['entries']:
                cname, _, mname = e['method'].partition('.')
                if mname not in self.table.get(cname, {'covered': []})['covered']:
                    orphans.append(e['case'])
        self.assertEqual(orphans, [], 'cases whose Class.method is not listed under COVERAGE[...]["covered"]')

    def test_each_driver_file_is_linted(self):
        mods = {i.name for i in pkgutil.iter_modules(drivers.__path__) if not i.name.startswith('_')}
        no_wire = {'__init__', 'transport', 'selftest'} | {m for m in mods if m.startswith('simulated')}
        self.assertEqual(sorted(mods - no_wire - set(gc.LINT_FILES)), [], 'driver module not in golden_capture.LINT_FILES')


class FStringLintBaseline(unittest.TestCase):
    """EXPECTED to report the existing f-string commands: the registry refactor moves every command into a Cmd template, so these counts
    ratchet down to zero (except commands registered as locked, listed in LOCKED_FSTRING_ALLOWED). Rewrite the baseline with --update only
    when the count went DOWN."""

    def test_counts_match_baseline(self):
        recorded = json.loads((gc.GOLDEN / 'fstring_lint_baseline.json').read_text(encoding='utf-8'))['counts']
        now = gc.count_fstring_commands()
        problems = []
        for stem in sorted(set(recorded) | set(now)):
            for key in sorted(set(recorded.get(stem, {})) | set(now.get(stem, {}))):
                a, b = recorded.get(stem, {}).get(key, 0), now.get(stem, {}).get(key, 0)
                allowed = LOCKED_FSTRING_ALLOWED.get(stem, {}).get(key, 0)
                if b > a:
                    problems.append(f'drivers/{stem}.py {key}: {b} f-string command(s), baseline {a}. New commands must be registered in the '
                                    'command registry (a Cmd template), not written as f-strings.')
                elif b < a:
                    problems.append(f'drivers/{stem}.py {key}: down from {a} to {b} (good). Ratchet the baseline: python -m tests.golden_capture --update')
                if b < allowed:
                    problems.append(f'drivers/{stem}.py {key}: below the locked allowance {allowed}')
        self.assertEqual(problems, [])

    def test_lint_pattern_matches_what_it_should(self):
        """A pattern that matches nothing proves nothing: check it against sample source text."""
        rx = gc._LINT
        self.assertTrue(rx['write_f'].search("        self.write(f'OUT {volts:.9g}V')"))
        self.assertTrue(rx['write_f'].search('        self.write(f"VBS \'{path}={value}\'")'))
        self.assertTrue(rx['query_f'].search("        reply = self.query(f'SYST:CTYP? {slot * 100}')"))
        self.assertTrue(rx['query_retry_f'].search("self._parse(self.query_retry(f'VBS? \"return={path}\"'))"))
        self.assertFalse(rx['write_f'].search("        self.write('STBY')"))
        self.assertFalse(rx['write_f'].search("        self.write(RF[key].format(**fmt))"))


if __name__ == '__main__':
    unittest.main()
