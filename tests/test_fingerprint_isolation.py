"""Per-procedure verified fingerprints: editing procedure A no longer unlocks procedure B (verified.py, procscan.py `fingerprint`).
Throw-away trees copied from the real suite; the real registry is never used.   Run:  python -m unittest tests.test_fingerprint_isolation"""
import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import procscan  # noqa: E402
import verified as V  # noqa: E402
from tests._pkg_helpers import make_tree  # noqa: E402

IDS = ['Fluke_117_Verification', 'Fluke_113_Verification', 'Fluke_87V', 'Keithley_2000_Verification', 'Fluke_287_Verification', 'Fluke_289_Verification']


class Isolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.tree = make_tree(self.t / 'suite', IDS)
        self.reg = V.Registry(self.t / 'r.sqlite3', base=self.tree, now=lambda: datetime(2026, 10, 22, 9, 0))
        self.entries = {}
        for pid in IDS:
            p = procscan.find(pid, self.tree)
            self.entries[pid] = V.make_entry(p.name, p.model, self.tree / p.launcher, self.tree)
            self.reg.verify(self.entries[pid], 'Mike', '2026-10-20', '', '', today=date(2026, 10, 22))

    def kinds(self):
        return {pid: self.reg.status(e).kind for pid, e in self.entries.items()}

    def assert_only(self, changed, msg=''):
        got = self.kinds()
        self.assertEqual({k for k, v in got.items() if v == 'changed'}, set(changed), msg + str(got))
        self.assertEqual({k for k, v in got.items() if v == 'verified'}, set(IDS) - set(changed), msg + str(got))

    def edit(self, rel, fn):
        p = self.tree / rel
        p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')

    def test_starting_point_all_verified(self):
        self.assert_only([])

    def test_a_model_specific_step_of_a_shared_spec_unlocks_only_that_model(self):
        def add_step(text):
            d = json.loads(text)
            d['steps'].append({**d['steps'][0], 'models': ['113'], 'id': 'only-113-extra'})
            return json.dumps(d)
        self.edit('specs/fluke_110_series_pv.json', add_step)
        self.assert_only(['Fluke_113_Verification'])

    def test_a_model_entry_of_a_shared_spec_unlocks_only_that_model(self):
        def tweak(text):
            d = json.loads(text)
            d['models']['113']['_probe'] = 1
            return json.dumps(d)
        self.edit('specs/fluke_110_series_pv.json', tweak)
        self.assert_only(['Fluke_113_Verification'])

    def test_a_step_shared_by_both_models_unlocks_both(self):
        def tweak(text):
            d = json.loads(text)
            step = next(s for s in d['steps'] if '113' in s['models'] and '117' in s['models'])
            step['_probe'] = 1
            return json.dumps(d)
        self.edit('specs/fluke_110_series_pv.json', tweak)
        self.assert_only(['Fluke_113_Verification', 'Fluke_117_Verification'])

    def test_a_common_part_of_a_shared_spec_unlocks_every_model_using_it(self):
        def tweak(text):
            d = json.loads(text)
            d['options']['function_prompt'] = not d['options']['function_prompt']
            return json.dumps(d)
        self.edit('specs/fluke_110_series_pv.json', tweak)
        self.assert_only(['Fluke_113_Verification', 'Fluke_117_Verification'])

    def test_another_meters_hookup_data_does_not_unlock(self):
        self.edit('hookups.py', lambda t: t.replace("name='Fluke 87V'", "name='Fluke 87V (renamed)'", 1))
        self.assert_only(['Fluke_87V'])
        self.reg.sync(self.entries['Fluke_87V'])

    def test_another_meters_hookup_caution_does_not_unlock(self):
        self.edit('hookups.py', lambda t: t.replace('The mA µA input is fused', 'The mA µA input is fused (edited)', 1))
        self.assert_only(['Fluke_87V'])

    def test_hookup_code_unlocks_every_meter_that_uses_it_but_not_the_meterless_ones(self):
        self.edit('hookups.py', lambda t: t.replace("return '5522A' if ('5522' in t", "return '5522A' if ('5522' in t or 'x' in t", 1))
        self.assert_only(['Fluke_117_Verification', 'Fluke_113_Verification', 'Fluke_87V'])

    def test_another_procedures_launcher_driver_and_spec_do_not_unlock(self):
        self.edit('Procedures/Fluke_87V.py', lambda t: t + '\n# edit\n')
        self.assert_only(['Fluke_87V'])
        self.edit('drivers/keithley_2000.py', lambda t: t + '\n# edit\n')
        self.assert_only(['Fluke_87V', 'Keithley_2000_Verification'])
        self.edit('specs/fluke_87v_pv.json', lambda t: t.replace('{', '{"_probe": 1,', 1))
        self.assert_only(['Fluke_87V', 'Keithley_2000_Verification'])

    def test_a_shared_engine_still_unlocks_everything_that_runs_on_it(self):
        self.edit('handheld_dmm.py', lambda t: t + '\n# edit\n')
        self.assert_only(['Fluke_117_Verification', 'Fluke_113_Verification', 'Fluke_87V', 'Fluke_287_Verification', 'Fluke_289_Verification'])

    def test_a_shared_driver_still_unlocks_every_user_of_it(self):
        self.edit('drivers/fluke_5560a.py', lambda t: t + '\n# edit\n')
        self.assert_only(IDS)

    def test_auto_unlock_event_is_written_once_and_names_the_file(self):
        self.edit('Procedures/Fluke_87V.py', lambda t: t + '\n# edit\n')
        for _ in range(3):
            self.reg.statuses(list(self.entries.values()))
        hist = self.reg.history('Fluke_87V.py')
        self.assertEqual([h['action'] for h in hist], ['verify', 'unlock'])
        self.assertEqual(hist[-1]['who'], 'system')
        self.assertIn('Procedures/Fluke_87V.py', hist[-1]['reason'])
        self.assertEqual(len(self.reg.history('Fluke_117_Verification.py')), 1)

    def test_locked_procedures_still_cannot_be_unlocked_without_a_reason_and_unlock_needs_no_passphrase(self):
        with self.assertRaises(V.VerifyError):
            self.reg.unlock('Fluke_87V.py', 'Sam', '')
        self.reg.unlock('Fluke_87V.py', 'Sam', 'checking the jack names')
        self.assertEqual(self.reg.lock_reason(proc_key='Fluke_87V.py'), '')
        self.assertTrue(self.reg.lock_reason(proc_key='Fluke_117_Verification.py'))


class RecordsFromBeforeSlices(unittest.TestCase):
    """A verified record taken by the old code stored whole files (the whole shared spec, hookups.py, drivers/base.py ...)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.tree = make_tree(self.t / 'suite', ['Fluke_117_Verification', 'Fluke_113_Verification'])
        self.reg = V.Registry(self.t / 'r.sqlite3', base=self.tree, now=lambda: datetime(2026, 10, 22, 9, 0))
        legacy = json.loads((ROOT / 'tests' / 'fixtures' / 'legacy_registry.json').read_text(encoding='utf-8'))['FILES']['Fluke_117_Verification.py']
        legacy['code'] = list(legacy['code']) + [f for f in ('handheld_dmm_view_tk.py', 'ui_port.py', 'ui_port_tk.py') if f not in legacy['code']]    # the UiPort port added these to the sidecar: a record taken before it is meant to say 'Changed' (NOTES 'UiPort, WP-H')
        comps = {'code': {r: V._file_digest(self.tree / r) for r in legacy['code']}, 'spec': {r: V._file_digest(self.tree / r) for r in legacy['spec']},
                 'overrides': {}}
        p = procscan.find('Fluke_117_Verification', self.tree)
        self.entry = V.make_entry(p.name, p.model, self.tree / p.launcher, self.tree)
        with self.reg._db() as con:
            self.reg._insert(con, 'Fluke_117_Verification.py', 'verify', 'Mike', on_date='2026-10-20', name=p.name, model='117',
                             hash=self.reg.definition_hash(comps), components=comps)

    def test_an_old_record_is_unchanged_when_nothing_changed(self):
        self.assertEqual(self.reg.status(self.entry).kind, 'verified')

    def test_an_old_record_ignores_files_the_procedure_no_longer_lists(self):
        self.assertEqual(self.reg.status(self.entry).kind, 'verified')
        p = self.tree / 'Procedures/Fluke_113_Verification.py'                     # another procedure: never part of it
        p.write_text(p.read_text() + '\n# edit\n')
        self.assertEqual(self.reg.status(self.entry).kind, 'verified')

    def test_an_old_record_compares_the_whole_shared_spec(self):
        spec = self.tree / 'specs/fluke_110_series_pv.json'
        d = json.loads(spec.read_text())
        d['models']['113']['_probe'] = 1                                             # only model 113's part: a NEW record would not care
        spec.write_text(json.dumps(d))
        st = self.reg.status(self.entry)
        self.assertEqual(st.kind, 'changed')
        self.assertTrue(any('fluke_110_series_pv.json' in c for c in st.changes), st.changes)

    def test_an_old_record_notices_a_declared_file_that_was_not_in_it(self):
        side = self.tree / 'Procedures/Fluke_117_Verification.procedure.json'
        d = json.loads(side.read_text())
        d['fingerprint']['code'].append('drivers/transport.py')
        d['fingerprint']['code'].append('procspec.py')                               # not in the old record
        side.write_text(json.dumps(d))
        (self.tree / 'procspec.py').write_text('# x\n')
        st = self.reg.status(self.entry)
        self.assertEqual(st.kind, 'changed')
        self.assertTrue(any('procspec.py (new)' in c for c in st.changes), st.changes)


if __name__ == '__main__':
    unittest.main()
