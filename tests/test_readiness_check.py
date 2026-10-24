"""tools/readiness_check.py: every check on synthetic transcripts (fast, no simulated run), then a quick real run through the simulated bench.

    python -m unittest tests.test_readiness_check
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]

import readiness_check as RC  # noqa: E402
from cmdreg import Cmd, Placeholder  # noqa: E402

def setUpModule():
    RC._load_modules()


F = Placeholder('float', '.9g', 1.0)
REG = {
    'out.set': Cmd('OUT {v:.9g} V', 'set', placeholders={'v': F}, kind='set', readback='out.get', verified=True, ref='manual p.1'),
    'out.get': Cmd('OUT?', 'get', kind='query', verified=True, ref='manual p.1'),
    'oper': Cmd('OPER', 'operate', kind='set', risk='output', readback='oper.q', verified=True, ref='p.2'),
    'stby': Cmd('STBY', 'standby', kind='action', risk='output', verified=True, ref='p.2'),
    'oper.q': Cmd('OPER?', 'operate?', kind='query', verified=True, ref='p.2'),
    'unk': Cmd('UNK {v:.9g}', 'unknown', placeholders={'v': F}, kind='set', verified=False, ref='guess'),
    'noref': Cmd('NOREF', 'noref', kind='action', verified=True, ref=''),
    'err.query': Cmd('FOO:ERRQ?', 'errors', kind='query', risk='locked', verified=False),
}
REGS = {'CAL': (object, REG)}


def tl(*cmds):
    """timeline of ('cmd', label, '>>', text) entries; the string 'PT' is a recorded-point marker."""
    return [('pt',) if c == 'PT' else ('cmd', 'CAL', '>>', c) for c in cmds]


def analyse(check, *cmds, **kw):
    timeline = tl(*cmds)
    tr = RC.transcript(timeline, REGS)
    rep = RC.Report(proc=type('P', (), dict(id='X', name='X', engine=[]))())
    if check is RC.check_outputs:
        RC.check_outputs(rep, tr, timeline)
    elif check is RC.check_commands:
        RC.check_commands(rep, tr, REGS, {})
    else:
        check(rep, tr)
    return rep


def levels(rep, name):
    return [f.level for f in rep.findings if f.check == name]


class Commands(unittest.TestCase):
    def test_unverified_and_unregistered_are_listed(self):
        rep = analyse(RC.check_commands, 'OUT 1 V', 'OUT?', 'UNK 3', 'WHATEVER 1', '*IDN?')
        f = [x for x in rep.findings if x.check == 'commands']
        self.assertEqual(f[0].level, RC.INFO, 'unverified commands in use are a note, not a warning')
        self.assertIn('1 unverified command(s) in use', f[0].text)
        self.assertTrue(f[0].show)
        self.assertTrue(any('UNK 3' in d for d in f[0].details))
        self.assertTrue(any(x.level == RC.WARN and 'NOT in any COMMANDS registry' in x.text for x in f))
        self.assertFalse(any('IDN' in d for x in f for d in x.details), '*IDN? is exempt')

    def test_all_verified_passes_and_missing_page_is_reported(self):
        rep = analyse(RC.check_commands, 'OUT 1 V', 'OUT?')
        self.assertEqual(levels(rep, 'commands')[0], RC.PASS)
        rep = analyse(RC.check_commands, 'NOREF')
        self.assertIn(RC.WARN, levels(rep, 'commands'))


    def test_unverified_alone_does_not_warn_and_the_list_is_still_printed(self):
        rep = analyse(RC.check_commands, 'OUT 1 V', 'OUT?', 'UNK 3')
        self.assertNotIn(RC.WARN, [f.level for f in rep.findings if f.check == 'commands'])
        self.assertEqual(rep.worst, RC.INFO)
        rep.proc.engine = ['e.py']
        text = RC.render(rep)
        self.assertIn('unverified command(s) in use', text)
        self.assertIn('UNK 3', text, 'the list stays visible without --verbose (it goes into the final summary)')

    def test_exit_code_ignores_the_note_but_a_real_warn_still_counts(self):
        # the exit rule in main(): FAIL, or WARN with --strict.  A report with only the unverified note is clean even under --strict.
        note = analyse(RC.check_commands, 'UNK 3')
        self.assertNotIn(RC.WARN, note.counts)
        self.assertNotIn(RC.FAIL, note.counts)
        warn = analyse(RC.check_commands, 'OUT 1 V', 'OUT?', 'WHATEVER 1')
        self.assertIn(RC.WARN, warn.counts, 'wire text with no registry entry is still a WARN')


class Readback(unittest.TestCase):
    def test_write_followed_by_readback_passes(self):
        rep = analyse(RC.check_readback, 'OUT 1 V', 'OUT?', 'OUT 2 V', 'OUT?')
        self.assertIn(RC.PASS, levels(rep, 'readback'))
        self.assertNotIn(RC.WARN, levels(rep, 'readback'))

    def test_write_without_readback_warns(self):
        rep = analyse(RC.check_readback, 'OUT 1 V', 'OUT 2 V', 'OUT?')
        warn = [f for f in rep.findings if f.level == RC.WARN]
        self.assertEqual(len(warn), 1)
        self.assertIn('1 of 2', warn[0].text)

    def test_output_enable_without_state_query_is_only_info(self):
        rep = analyse(RC.check_readback, 'OPER', 'STBY')
        self.assertNotIn(RC.WARN, levels(rep, 'readback'))
        self.assertIn(RC.INFO, levels(rep, 'readback'))


class Outputs(unittest.TestCase):
    def test_left_on_at_the_end_fails(self):
        self.assertIn(RC.FAIL, levels(analyse(RC.check_outputs, 'OPER', 'PT'), 'outputs'))

    def test_standby_after_each_point_passes(self):
        self.assertEqual(levels(analyse(RC.check_outputs, 'OPER', 'PT', 'STBY', 'OPER', 'PT', 'STBY'), 'outputs'), [RC.PASS])

    def test_on_again_after_a_point_without_standby_warns(self):
        self.assertIn(RC.WARN, levels(analyse(RC.check_outputs, 'OPER', 'PT', 'OPER', 'PT', 'STBY'), 'outputs'))

    def test_sweep_within_a_point_is_not_flagged(self):
        self.assertEqual(levels(analyse(RC.check_outputs, 'OPER', 'OPER', 'OPER', 'PT', 'STBY'), 'outputs'), [RC.PASS])

    def test_no_output_command_is_info(self):
        self.assertEqual(levels(analyse(RC.check_outputs, 'OUT? '), 'outputs'), [RC.INFO])


def dlg(n, kind='confirm', title='Set the knob', head='Step'):
    return [('dlg', kind, title, head)] * n


class Prompts(unittest.TestCase):
    def run_check(self, timeline, points):
        rep = RC.Report(proc=None)
        RC.check_prompts(rep, timeline, dict(results=points))
        return rep.findings[0]

    def test_many_prompts_for_an_automated_procedure_warn(self):
        distinct = [('dlg', 'confirm', f'Do thing {i}', 'Ready') for i in range(30)]
        f = self.run_check(distinct, 20)
        self.assertEqual(f.level, RC.WARN)
        self.assertIn('many for a fully automated', f.text)

    def test_same_prompt_repeated_warns(self):
        self.assertEqual(self.run_check(dlg(4, title='Press the button'), 40).level, RC.WARN)

    def test_hookup_prompts_and_typed_readings_are_the_procedure(self):
        t = [('dlg', 'reading', 'x', 'y')] * 30 + [('dlg', 'confirm', f'Connect the cable {i}', 'Hook-up') for i in range(20)]
        self.assertNotEqual(self.run_check(t, 30).level, RC.WARN)

    def test_few_prompts_pass(self):
        t = [('dlg', 'confirm', 'Warm up for 30 minutes', 'Before you start'), ('dlg', 'confirm', 'Connect the cable', 'Hook-up')]
        self.assertEqual(self.run_check(t, 50).level, RC.PASS)


class Uncertainty(unittest.TestCase):
    def rows(self, *rows):
        rep = RC.Report(proc=None)
        RC.check_uncertainty(rep, dict(report=dict(rows=list(rows))))
        return rep

    def row(self, **kw):
        base = dict(should=True, uncertainty='0.01', covered=True, kind='dcv', section='DC', description='1 V', tur='4', tar='4')
        base.update(kw)
        return base

    def test_all_printed_passes(self):
        self.assertIn(RC.PASS, levels(self.rows(self.row(), self.row(should=False, uncertainty='')), 'uncertainty'))

    def test_missing_inside_the_scope_fails(self):
        self.assertIn(RC.FAIL, levels(self.rows(self.row(uncertainty='', covered=True)), 'uncertainty'))

    def test_missing_outside_the_scope_is_info_for_a_few(self):
        rep = self.rows(*[self.row() for _ in range(20)], self.row(uncertainty='', covered=False))
        self.assertIn(RC.INFO, levels(rep, 'uncertainty'))
        self.assertNotIn(RC.FAIL, levels(rep, 'uncertainty'))

    def test_missing_with_unknown_coverage_warns(self):
        self.assertIn(RC.WARN, levels(self.rows(self.row(uncertainty='', covered=None)), 'uncertainty'))

    def test_no_rows(self):
        rep = RC.Report(proc=None)
        RC.check_uncertainty(rep, dict(report=dict(rows=[], note='no report')))
        self.assertEqual(levels(rep, 'uncertainty'), [RC.INFO])


class Tunables(unittest.TestCase):
    def test_unregistered_name_at_run_time_fails(self):
        rep = RC.Report(proc=None)
        RC.check_tunables(rep, None, dict(pm_params=[('nosuchengine.settle_s', 1.0)]), [])
        self.assertEqual(rep.findings[0].level, RC.FAIL)

    def test_registered_name_with_its_default_passes(self):
        name, t = next(iter(RC.procmods_engine.TUNABLES.items()))
        rep = RC.Report(proc=None)
        RC.check_tunables(rep, None, dict(pm_params=[(name, t['default'])]), [])
        self.assertEqual(rep.findings[0].level, RC.PASS, rep.findings[0].details)

    def test_wrong_default_fails(self):
        name, t = next(iter(RC.procmods_engine.TUNABLES.items()))
        rep = RC.Report(proc=None)
        RC.check_tunables(rep, None, dict(pm_params=[(name, float(t['default']) + 7.0)]), [])
        self.assertEqual(rep.findings[0].level, RC.FAIL)


class Housekeeping(unittest.TestCase):
    def test_unverified_error_query_off_the_list_warns(self):
        rep = RC.Report(proc=None)
        RC.check_housekeeping(rep, REGS, {('CAL', 'err.query')})
        self.assertEqual(rep.findings[0].level, RC.WARN)
        self.assertIn('would prompt', rep.findings[0].details[0])

    def test_standard_error_query_is_housekeeping(self):
        reg = {'err.query': Cmd('SYST:ERR?', 'errors', kind='query', risk='locked', verified=False)}
        rep = RC.Report(proc=None)
        RC.check_housekeeping(rep, {'X': (object, reg)}, {('X', 'err.query')})
        self.assertEqual(rep.findings[0].level, RC.PASS)

    def test_a_query_not_used_in_the_run_is_not_asked(self):
        rep = RC.Report(proc=None)
        RC.check_housekeeping(rep, REGS, set())
        self.assertEqual(rep.findings[0].level, RC.PASS)


class Shared(unittest.TestCase):
    def proc(self, pid):
        return type('P', (), dict(id=pid))()

    def info(self, changed, flipped, **kw):
        return dict(base='origin/main', changed=changed, flipped=flipped, new=[], note='', seeded=['Fluke_117_Verification'], **kw)

    def test_nothing_changed_passes(self):
        rep = RC.Report(proc=None)
        RC.check_shared(rep, self.info({}, []))
        self.assertEqual(rep.findings[0].level, RC.PASS)

    def test_flipping_a_verified_procedure_fails(self):
        rep = RC.Report(proc=None)
        RC.check_shared(rep, self.info({'drivers/transport.py': 'M'}, [(self.proc('Fluke_117_Verification'), ['drivers/transport.py'])]))
        self.assertEqual(rep.findings[0].level, RC.FAIL)
        self.assertIn('Fluke_117_Verification', rep.findings[0].text)
        self.assertTrue(any('drivers/transport.py' in d for d in rep.findings[0].details))

    def test_flipping_an_unverified_procedure_warns(self):
        rep = RC.Report(proc=None)
        RC.check_shared(rep, self.info({'handheld_dmm.py': 'M'}, [(self.proc('Fluke_87V'), ['handheld_dmm.py'])]))
        self.assertEqual(rep.findings[0].level, RC.WARN)

    def test_registry_list_replaces_the_seed(self):
        rep = RC.Report(proc=None)
        RC.check_shared(rep, self.info({'handheld_dmm.py': 'M'}, [(self.proc('Fluke_87V'), ['handheld_dmm.py'])], registry_verified=['Fluke_87V']))
        self.assertEqual(rep.findings[0].level, RC.FAIL)

    def test_a_new_file_only_changes_nothing(self):
        rep = RC.Report(proc=None)
        RC.check_shared(rep, self.info({'tools/readiness_check.py': 'A'}, []))
        self.assertEqual(rep.findings[0].level, RC.PASS)

    def test_real_comparison_against_main_runs(self):
        info = RC.shared_touch()
        if info['base'] is None:
            self.skipTest('no git base')
        self.assertIn('changed', info)
        self.assertIsInstance(info['flipped'], list)


class Surprise(unittest.TestCase):
    def test_new_procedure_without_the_mixin_warns(self):
        import surprise

        class Plain:
            pass

        class Wired(surprise.SurpriseMixin):
            pass
        proc = type('P', (), dict(id='New_One'))()
        rep = RC.Report(proc=proc)
        RC.check_surprise(rep, proc, {'A': (Plain, {})}, dict(new=['New_One']))
        self.assertEqual(rep.findings[0].level, RC.WARN)
        rep = RC.Report(proc=proc)
        RC.check_surprise(rep, proc, {'A': (Wired, {})}, dict(new=['New_One']))
        self.assertEqual(rep.findings[0].level, RC.PASS)

    def test_existing_procedure_is_not_reported(self):
        proc = type('P', (), dict(id='Old_One'))()
        rep = RC.Report(proc=proc)
        RC.check_surprise(rep, proc, {'A': (object, {})}, dict(new=['New_One']))
        self.assertEqual(rep.findings, [])


class ReportAndExit(unittest.TestCase):
    def test_worst_level_and_render(self):
        rep = RC.Report(proc=type('P', (), dict(id='X', name='X', engine=['e.py']))())
        rep.add(RC.PASS, 'a', 'fine')
        rep.add(RC.WARN, 'b', 'hmm', ['detail one'])
        self.assertEqual(rep.worst, RC.WARN)
        text = RC.render(rep)
        self.assertIn('WARN', text)
        self.assertIn('detail one', text)
        rep.add(RC.FAIL, 'c', 'bad')
        self.assertEqual(rep.worst, RC.FAIL)
        self.assertEqual(json.loads(json.dumps(rep.as_dict(), default=str))['worst'], RC.FAIL)

    def test_unknown_procedure_exits_with_a_message(self):
        r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'readiness_check.py'), 'No_Such_Procedure'], capture_output=True, text=True, cwd=str(ROOT))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('No procedure', r.stdout + r.stderr)


class SurpriseInFingerprint(unittest.TestCase):
    """A wired engine depends on surprise.py: the sidecar file list must name it (static, no run)."""

    def _exp(self, pid):
        proc = RC.procscan.find(pid + '.py', ROOT) or next(p for p in RC.procscan.procs(ROOT) if p.id == pid)
        return proc, RC.expected_fingerprint(proc, {})

    def test_wired_engines_expect_and_list_surprise(self):
        for pid in ('Keysight_34460A_Verification', 'Keysight_34970A_Verification', 'Agilent_34410A_Verification'):
            proc, exp = self._exp(pid)
            self.assertIn('surprise.py', exp, pid)
            self.assertIn('surprise.py', proc.fingerprint_code, pid)

    def test_an_unwired_engine_does_not_expect_it(self):
        _proc, exp = self._exp('Fluke_117_Verification')
        self.assertNotIn('surprise.py', exp)

    def test_listed_surprise_is_reported_as_listed(self):
        proc, _exp = self._exp('Keysight_34460A_Verification')
        rep = RC.Report(proc=proc)
        RC.check_fingerprint(rep, proc, {})
        self.assertFalse([f for f in rep.findings if f.level == RC.WARN], [f.text for f in rep.findings])   # no 'incomplete' warning
        self.assertFalse([d for f in rep.findings for d in f.details if 'missing from the fingerprint list' in d and 'surprise.py' in d])
        # and the same file without it in the list is reported as missing
        import dataclasses
        bare = dataclasses.replace(proc, fingerprint_code=tuple(c for c in proc.fingerprint_code if c != 'surprise.py'))
        rep2 = RC.Report(proc=bare)
        RC.check_fingerprint(rep2, bare, {})
        self.assertTrue([d for f in rep2.findings for d in f.details if 'missing from the fingerprint list' in d and 'surprise.py' in d])


class SimulatedRun(unittest.TestCase):
    """One procedure through the simulated bench, end to end (about 2 s)."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp()) / 'r.json'
        cls.r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'readiness_check.py'), 'Fluke_117_Verification', '--base', 'HEAD', '--json', str(cls.out)],
                               capture_output=True, text=True, cwd=str(ROOT), timeout=300)      # --base HEAD: the 'shared' check compares with this very commit, so the result does not depend on which procedures the branch flips relative to main

    def test_exit_code_and_report(self):
        # Every check except 'shared' must not FAIL. 'shared' is measured against HEAD here (setUpClass), so it only reports uncommitted edits to
        # fingerprinted files; a developer's dirty tree may legitimately make it FAIL, which must not fail this test.
        data = json.loads(self.out.read_text(encoding='utf-8'))
        bad = [f for f in data['reports'][0]['findings'] if f['level'] == RC.FAIL and f['check'] != 'shared']
        self.assertEqual(bad, [], self.r.stdout)
        shared_failed = any(f['level'] == RC.FAIL and f['check'] == 'shared' for f in data['reports'][0]['findings'])
        if not shared_failed:
            self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)
        self.assertIn('READINESS', self.r.stdout)
        self.assertIn('40 of 40 points run', self.r.stdout)

    def test_json_has_every_check(self):
        data = json.loads(self.out.read_text(encoding='utf-8'))
        rep = data['reports'][0]
        names = {f['check'] for f in rep['findings']}
        for need in ('sidecar', 'run', 'commands', 'readback', 'outputs', 'prompts', 'uncertainty', 'tunables', 'housekeeping', 'diagrams', 'fingerprint', 'shared'):
            self.assertIn(need, names)
        self.assertEqual(rep['procedure'], 'Fluke_117_Verification')

    def test_static_only_run(self):
        r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'readiness_check.py'), 'Fluke_8808A_Adjustment', '--no-run'], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertIn(r.returncode, (0, 1))
        self.assertIn('not run', r.stdout)

    def test_a_clean_run_has_no_hardware_io(self):
        """The check imports no pyvisa / serial: it must work with them blocked."""
        code = 'import sys; sys.modules["pyvisa"]=None; sys.modules["serial"]=None; sys.argv=["x","Fluke_117_Verification","--no-run"]; import runpy; runpy.run_path("tools/readiness_check.py", run_name="__main__")'
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertIn('READINESS', r.stdout, r.stderr[-500:])


if __name__ == '__main__':
    unittest.main()
