"""Datasheet Builder build-time rules 1-5 (datasheet_builder_rules.py, NOTES.md 'Two-way datasheet rules'): pass and fail cases for each rule on the shipped
fixtures (multimeter, scope and generator sheets), the handheld template, the Mudcats import, a sheet with an out-of-range point, a sheet with unverified
commands and a unit mismatch; the dry run on the simulated bench; the pre-run list a real run asks the operator to accept; the Manager list's Automation
column; the Sheet check window under the Tk stub.
No tkinter is installed here, so tests/_tk_stub.py (via the run harness) stands in for it.
Run:  python -m unittest tests.test_datasheet_builder_rules"""
import json
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import dsb_run_harness as H  # noqa: E402,F401   (installs the tkinter stub; dsb_runtime needs it)
import dsb_fixtures as fx  # noqa: E402
import mdd_synth  # noqa: E402
import mdd_importer_v49 as imp  # noqa: E402
import mdd_convert as mc  # noqa: E402
import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_rules as rules  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402
import datasheet_builder_ui_model as M  # noqa: E402
import dsb_manager  # noqa: E402
import dsb_prerun  # noqa: E402
import dsb_runtime as rt  # noqa: E402
from drivers.simulated import SimFlukeTransport  # noqa: E402
from drivers.transport import TransportError  # noqa: E402
from tests.test_dsb_ui_model import REG  # noqa: E402


def dcv_sheet(points=((5, 'r10'),), ranges=((10, 'r10'),), spec='0.05 % of reading + 0.01 % of range', title='Rules DCV'):
    ds = db.Datasheet('Acme', 'RM-1', title)
    fn = ds.add_function('DCV', id='dcv')
    for fs, rid in ranges:
        fn.add_range(fs, id=rid)
    ds.set_spec(fn, spec)
    for v, rid in points:
        db.add_point(fn, v, range_id=rid)
    return ds


def pid_of(ds, nominal):
    """The id of the point whose nominal is `nominal` (the ids carry a sign: 'dcv.r1500.+1500')."""
    return next(p.id for _f, p in ds.all_points() if p.nominal == D(str(nominal)))


def far_sheet():
    """A DC volts sheet with a point (1500 V) that no calibrator reaches."""
    return dcv_sheet(points=((5, 'r10'), (1500, 'r1500')), ranges=((10, 'r10'), (1500, 'r1500')))


def codes(chk, rule=None, level=None):
    return [f.code for f in chk.findings if (rule is None or f.rule == rule) and (level is None or f.level == level)]


class Base(unittest.TestCase):
    matcher = None

    @classmethod
    def setUpClass(cls):
        cls.matcher = dm.Matcher(REG)

    def check(self, ds, **kw):
        return rules.check(ds, matcher=self.matcher, **kw)


# ================================================================================================================================ rule 1
class Rule1Coverage(Base):
    def test_in_range_sheet_has_no_coverage_finding(self):
        chk = self.check(dcv_sheet())
        self.assertEqual(codes(chk, 1), [])

    def test_a_point_outside_every_calibrator_is_a_warning_that_offers_manual_entry(self):
        ds = far_sheet()
        chk = self.check(ds)
        f = [f for f in chk.findings if f.rule == 1]
        self.assertEqual([(x.level, x.code, x.action) for x in f], [('warn', 'not_covered', 'manual_entry')])
        self.assertIn('1.5 kV', f[0].text)
        self.assertIn('Apply the fix', f[0].fix)
        self.assertEqual(f[0].point_ids, (pid_of(ds, 1500),))
        self.assertEqual([f.code for f in chk.errors()], ['no_uncertainty'])   # rule 1 itself is a warning; the missing uncertainty (rule 5) is what blocks

    def test_manual_entry_fix_removes_the_finding_and_is_one_assignment(self):
        ds = far_sheet()
        f = [f for f in self.check(ds).findings if f.rule == 1][0]
        self.assertEqual(rules.manual_entry_for(ds, f), 1)
        self.assertEqual(ds.assignments, {pid_of(ds, 1500): 'MANUAL'})
        self.assertEqual(rules.manual_entry_for(ds, f), 0)
        self.assertEqual(codes(self.check(ds), 1), [])

    def test_a_calibrator_the_author_chose_that_cannot_make_the_point_is_an_error(self):
        ds = far_sheet()
        ds.assignments[pid_of(ds, 1500)] = '5560A'
        chk = self.check(ds)
        self.assertEqual([(f.level, f.code) for f in chk.findings if f.rule == 1], [('error', 'chosen_cannot')])
        self.assertFalse(chk.ok)

    def test_the_multimeter_fixture_flags_its_uncovered_ac_point(self):
        chk = self.check(fx.dmm_34461a_like())
        f = [f for f in chk.findings if f.rule == 1]
        self.assertEqual(len(f), 1)
        self.assertIn('750', f[0].text)
        self.assertEqual(f[0].level, 'warn')

    def test_a_manual_calibration_is_not_checked_for_coverage(self):
        ds = dcv_sheet(points=((1500, 'r1500'),), ranges=((1500, 'r1500'),))
        ds.options['manual_entry'] = True
        self.assertEqual(codes(self.check(ds), 1), [])

    def test_a_point_that_will_not_run_on_its_assigned_standard_is_a_warning(self):
        chk = self.check(fx.generator_33220a_like())
        self.assertIn('not_on_assigned', codes(chk, 1))                        # GEN_OFFSET: the 5790B driver has no DC mode


# ================================================================================================================================ rule 2
class Rule2Unverified(Base):
    def capacitance_sheet(self):
        ds = db.Datasheet('Acme', 'RM-2', 'Rules CAP')
        fn = ds.add_function('CAP', id='cap')
        fn.add_range('0.00000001', resolution='0.000000000001', id='r10n')
        ds.set_spec(fn, '1 % of reading + 2 counts')
        db.add_point(fn, '0.000000001', range_id='r10n')
        return ds

    def test_a_capacitance_point_lists_the_calibrator_commands_that_are_not_verified(self):
        chk = self.check(self.capacitance_sheet())
        self.assertTrue(chk.dry.available, chk.dry.reason)
        names = [u.line() for u in chk.unverified]
        self.assertTrue(any('capacitance' in n.lower() and 'not verified on hardware' in n for n in names), names)
        self.assertTrue(all(u.point_ids for u in chk.unverified))
        f = [f for f in chk.findings if f.rule == 2]
        self.assertTrue(f and all(x.level == 'warn' for x in f))               # build time: warnings; the block is at run time
        self.assertTrue(chk.ok)

    def test_the_list_follows_the_registry_flags_not_the_driver_tables(self):
        chk = self.check(dcv_sheet())
        for u in chk.unverified:
            reg = chk.dry.registries[u.driver]
            cmd = reg.get(u.key) if u.key else None
            self.assertTrue(cmd is None or not cmd.verified or not cmd.ref, u.line())
        # a command with a verified flag AND a manual page reference is sent but not listed
        sent = {(e.driver, e.key) for pr in chk.dry.points.values() for e in pr.commands if e.key}
        ok = {(d, k) for d, k in sent if chk.dry.registries[d][k].verified and chk.dry.registries[d][k].ref}
        self.assertTrue(ok)
        self.assertFalse(ok & {(u.driver, u.key) for u in chk.unverified})

    def test_fingerprint_changes_with_the_list_and_not_with_the_values(self):
        a = self.check(dcv_sheet(points=((5, 'r10'),))).fingerprint()
        b = self.check(dcv_sheet(points=((5, 'r10'), (7, 'r10')))).fingerprint()
        c = self.check(self.capacitance_sheet()).fingerprint()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a and c)

    def test_without_the_dry_run_the_driver_table_still_names_the_unverified_standards(self):
        with mock.patch.object(rules, '_runner_modules', side_effect=ImportError('no tkinter')):
            chk = self.check(self.capacitance_sheet())
        self.assertFalse(chk.dry.available)
        self.assertTrue(chk.unverified)
        self.assertIn('no tkinter', chk.dry.reason)
        self.assertIn('not_run', codes(chk, 4))                                # said, as a note

    def test_the_manual_calibration_sends_nothing_so_nothing_is_listed(self):
        ds = dcv_sheet()
        ds.options['manual_entry'] = True
        chk = self.check(ds)
        self.assertEqual(chk.unverified, [])
        self.assertEqual(chk.fingerprint(), '')


class PreRunAcceptance(Base):
    def spec_of(self, ds):
        return dsp.export_spec(ds, plan=dm.match_datasheet(ds, matcher=None) if False else self.matcher.match(ds)).spec

    def test_a_list_is_asked_once_and_declining_stops_the_run(self):
        spec = self.spec_of(dcv_sheet())
        with mock.patch.object(rules.dm if hasattr(rules, 'dm') else dm, 'Matcher', lambda *a, **k: self.matcher):
            asked = []
            self.assertFalse(dsb_prerun.accepted(None, spec, '', ask=lambda info: asked.append(info) or False))
            self.assertEqual(len(asked), 1)
            self.assertTrue(asked[0]['count'] >= 1)
            self.assertTrue(asked[0]['lines'])
            self.assertTrue(dsb_prerun.accepted(None, spec, '', ask=lambda info: True))

    def test_the_fingerprint_the_builder_passed_skips_the_second_question(self):
        ds = dcv_sheet()
        spec = self.spec_of(ds)
        with mock.patch.object(dm, 'Matcher', lambda *a, **k: self.matcher):
            fp = dsb_prerun.pre_run(spec)['fingerprint']
            self.assertTrue(fp)
            self.assertTrue(dsb_prerun.accepted(None, spec, fp, ask=lambda info: self.fail('asked twice')))
            self.assertFalse(dsb_prerun.accepted(None, spec, 'not-the-list', ask=lambda info: False))

    def test_a_manual_calibration_is_never_asked(self):
        ds = dcv_sheet()
        ds.options['manual_entry'] = True
        spec = dsp.export_spec(ds).spec
        self.assertTrue(dsb_prerun.accepted(None, spec, '', ask=lambda info: self.fail('asked')))

    def test_when_the_list_cannot_be_worked_out_the_operator_is_asked_that(self):
        spec = self.spec_of(dcv_sheet())
        with mock.patch.object(rules, 'check', side_effect=RuntimeError('boom')):
            asked = []
            self.assertFalse(dsb_prerun.accepted(None, spec, '', ask=lambda info: asked.append(info) or False))
        self.assertIn('could not be worked out', asked[0]['intro'])

    def test_launch_args_carry_the_accepted_list_only_for_a_real_run(self):
        row = dict(spec_path='/x/y.json', accepted_unverified='abc123')
        self.assertIn('--accept-unverified', dsb_manager.launch_args(row))
        self.assertEqual(dsb_manager.launch_args(row)[-1], 'abc123')
        self.assertNotIn('--accept-unverified', dsb_manager.launch_args(row, demo=True))
        self.assertNotIn('--accept-unverified', dsb_manager.launch_args(dict(spec_path='/x/y.json')))


# ================================================================================================================================ rule 3
class Rule3Units(Base):
    def with_label(self, label, kind_label_on='point'):
        ds = dcv_sheet()
        fn = ds.functions[0]
        if kind_label_on == 'point':
            fn.points[0].label = label
        else:
            fn.ranges[0].label = label
        return ds

    def test_matching_labels_pass(self):
        for label in ('5 V', '5.000 V', '5000 mV', '1 to 10 V', '5 Vrms'):
            self.assertEqual(codes(self.check(self.with_label(label), dry_run_on=False), 3), [], label)

    def test_a_label_in_another_unit_is_an_error_and_never_converted(self):
        chk = self.check(self.with_label('5 mA'), dry_run_on=False)
        f = [f for f in chk.findings if f.rule == 3]
        self.assertEqual([(x.level, x.code, x.action) for x in f], [('error', 'unit_mismatch', 'make_check')])
        self.assertIn('mA', f[0].text)
        self.assertIn('not converted', f[0].text)
        self.assertFalse(chk.ok)

    def test_an_unknown_unit_is_an_error(self):
        chk = self.check(self.with_label('5 furlongs'), dry_run_on=False)
        self.assertEqual([(f.level, f.code) for f in chk.findings if f.rule == 3], [('error', 'unit_unknown')])

    def test_range_labels_are_checked_too(self):
        chk = self.check(self.with_label('20 kHz', 'range'), dry_run_on=False)
        self.assertEqual([f.code for f in chk.findings if f.rule == 3], ['unit_mismatch'])
        self.assertEqual(codes(self.check(self.with_label('10 V', 'range'), dry_run_on=False), 3), [])

    def test_the_generator_amplitude_unit_is_checked(self):
        ds = fx.generator_33220a_like()
        self.assertEqual(codes(self.check(ds, dry_run_on=False), 3, 'error'), [])
        fn = next(f for f in ds.functions if f.kind == 'GEN_AMPL')
        fn.settings['amp_unit'] = 'dBm'
        self.assertEqual(codes(self.check(ds, dry_run_on=False), 3, 'error'), ['unit_unknown'])
        fn.settings['amp_unit'], fn.settings['waveform'] = 'Vpp', 'TRI'
        self.assertEqual(codes(self.check(ds, dry_run_on=False), 3, 'error'), ['unit_mismatch'])

    def test_make_check_row_moves_the_point_to_a_flagged_pass_fail_section(self):
        ds = self.with_label('5 mA')
        q = rules.make_check_row(ds, 'dcv', ds.functions[0].points[0].id)
        self.assertEqual([f.kind for f in ds.functions], ['DCV', 'CHECK'])
        self.assertEqual(ds.functions[0].points, [])
        self.assertEqual(ds.assignments[q.id], 'MANUAL')
        self.assertIn('Unit not accepted', q.note)
        self.assertEqual(q.label, '5 mA')                                           # the original text stays on the row
        self.assertEqual(db.errors(db.validate(ds)), [])
        self.assertEqual(codes(self.check(ds, dry_run_on=False), 3), [])

    def test_a_sheet_with_a_unit_error_is_saved_as_a_draft_not_ready(self):
        ds = self.with_label('5 mA')
        with tempfile.TemporaryDirectory() as t:
            res = db.save(ds, root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3')
            self.assertTrue(res.ok)
            self.assertEqual(res.status, 'draft')
            self.assertTrue(any(str(p.code) == 'rule3_unit_mismatch' for p in res.problems), res.problems)
            fixed = self.with_label('5 V')
            self.assertEqual(db.save(fixed, root=Path(t) / 'us2', db=Path(t) / 'reg2.sqlite3').status, 'ready')

    def test_the_mudcats_import_is_clean(self):
        d = Path(tempfile.mkdtemp())
        conv = mc.convert(imp.parse_mdd(mdd_synth.write_mdd(d / 'Synth 87V.MDD')))
        rules.set_waiver(conv.sheet, [rules.WHOLE_SHEET], 'manual_calibration', '', who='import')       # what mdd_convert.register records
        chk = rules.check(conv.sheet, matcher=self.matcher)
        self.assertEqual(chk.errors(), [], [f.text for f in chk.errors()])
        self.assertFalse(chk.dry.available)                                         # a manual calibration drives nothing
        self.assertEqual(codes(chk, 1), [])
        self.assertEqual(chk.unverified, [])
        self.assertEqual(set(codes(chk, 5)), {'waived'})                            # the whole-sheet waiver is listed, one line per section


# ================================================================================================================================ rule 4
class Rule4DryRun(Base):
    def test_every_point_of_the_fixtures_is_run_on_the_simulated_bench(self):
        for name in ('dmm_34461a_like', 'scope_tds2000c_like', 'generator_33220a_like', 'acv_bands_sheet'):
            ds = getattr(fx, name)()
            chk = self.check(ds)
            n = sum(1 for _f, p in ds.all_points() if p.enabled)
            self.assertTrue(chk.dry.available, (name, chk.dry.reason))
            self.assertEqual(len(chk.dry.points), n, name)
            self.assertEqual([k for k, pr in chk.dry.points.items() if pr.status == 'unsupported'], [], name)
            self.assertEqual(codes(chk, 4, 'error'), [], name)
            self.assertEqual({f.rule for f in chk.errors()} - {5}, set(), name)           # (the 34461A fixture has a 750 V @ 50 kHz point no calibrator covers: rule 5)
            self.assertTrue(chk.dry.ran >= 1, name)

    def test_commands_are_recorded_per_point_with_the_registry_flags(self):
        chk = self.check(dcv_sheet())
        pr = next(iter(chk.dry.points.values()))
        self.assertEqual(pr.status, 'ok')
        self.assertTrue(any(e.wire.startswith('OUT ') for e in pr.commands))
        self.assertTrue(any(e.wire == 'STBY' for e in pr.commands))               # standby after the point is part of the dry run

    def test_a_command_the_simulated_driver_does_not_know_is_an_error_and_blocks_ready(self):
        orig = SimFlukeTransport._handle

        def handle(self, cmd):
            if cmd.upper().startswith('OUT') and 'NF' in cmd.upper():
                raise TransportError(f'simulated 5560A: unknown command {cmd!r}')
            return orig(self, cmd)
        ds = Rule2Unverified.capacitance_sheet(self)
        with mock.patch.object(SimFlukeTransport, '_handle', handle):
            chk = self.check(ds)
            f = [f for f in chk.findings if f.rule == 4]
            self.assertEqual([(x.level, x.code) for x in f], [('error', 'unsupported_command')])
            self.assertIn('cannot be marked ready', f[0].fix)
            self.assertFalse(chk.ok)
            with tempfile.TemporaryDirectory() as t:
                with mock.patch.object(dm, 'Matcher', lambda *a, **k: self.matcher):
                    res = db.save(ds, root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3')
                self.assertEqual(res.status, 'draft')
                self.assertTrue(any(str(p.code) == 'rule4_unsupported_command' for p in res.problems), res.problems)
        self.assertTrue(self.check(ds).ok)                                           # the same sheet without the missing command is fine

    def test_a_command_error_in_the_error_queue_counts_as_unsupported(self):
        orig = SimFlukeTransport._handle

        def handle(self, cmd):
            if cmd.upper().startswith('OUT') and 'NF' in cmd.upper():
                self.errors = getattr(self, 'errors', []) + ['-113,"Undefined header"']
                return None
            return orig(self, cmd)
        with mock.patch.object(SimFlukeTransport, '_handle', handle):
            chk = self.check(Rule2Unverified.capacitance_sheet(self))
        self.assertEqual(codes(chk, 4, 'error'), ['unsupported_command'])

    def test_a_limit_of_the_simulation_is_only_a_warning(self):
        orig = SimFlukeTransport._handle

        def handle(self, cmd):
            if cmd.upper().startswith('OUT') and 'NF' in cmd.upper():
                raise ValueError('the simulation cannot do this')
            return orig(self, cmd)
        with mock.patch.object(SimFlukeTransport, '_handle', handle):
            chk = self.check(Rule2Unverified.capacitance_sheet(self))
        self.assertEqual([(f.level, f.code) for f in chk.findings if f.rule == 4], [('warn', 'dry_run_stopped')])
        self.assertTrue(chk.ok)

    def test_the_dry_run_needs_a_sheet_without_problems(self):
        ds = dcv_sheet()
        ds.functions[0].spec = []                                                    # no limits: validate() has errors
        chk = self.check(ds)
        self.assertFalse(chk.dry.available)
        self.assertIn('problems', chk.dry.reason)

    def test_the_handheld_template_checks_without_errors(self):
        g = M.GridModel(M.Storage(Path(tempfile.mkdtemp()) / 'us', Path(tempfile.mkdtemp()) / 'r.sqlite3'), matcher_factory=lambda: self.matcher)
        g.add_handheld_functions()
        chk = g.sheet_check()
        self.assertEqual(chk.errors(), [])
        self.assertEqual(chk.sources, {})


# ================================================================================================================================ rule 5
class Rule5Sources(Base):
    def test_a_covered_point_names_its_standards_sheet(self):
        self_ds = dcv_sheet()
        chk = self.check(self_ds, dry_run_on=False)
        s = chk.sources[pid_of(self_ds, 5)]
        self.assertTrue(s.has_source)
        self.assertEqual(s.level, 'ok')
        self.assertIn('standards sheet', s.text)
        self.assertTrue(s.text.startswith(s.standard))
        self.assertEqual(codes(chk, 5), [])

    def test_a_point_nothing_covers_is_called_out_and_never_zero(self):
        ds = far_sheet()
        chk = self.check(ds, dry_run_on=False)
        s = chk.sources[pid_of(ds, 1500)]
        self.assertFalse(s.has_source)
        self.assertTrue(s.text.startswith('none: blank'), s.text)
        self.assertEqual(s.level, 'error')
        f = [f for f in chk.findings if f.rule == 5]
        self.assertEqual([(x.level, x.code) for x in f], [('error', 'no_uncertainty')])
        self.assertIn('never shows zero', f[0].text)
        self.assertNotIn(' 0 ', s.text)

    def test_a_hand_set_point_has_no_source(self):
        ds = dcv_sheet()
        pid = pid_of(ds, 5)
        ds.assignments[pid] = 'MANUAL'
        s = self.check(ds, dry_run_on=False).sources[pid]
        self.assertFalse(s.has_source)
        self.assertIn('set by hand', s.text)

    def test_kinds_the_report_leaves_blank_say_so_without_a_warning(self):
        chk = self.check(fx.generator_33220a_like(), dry_run_on=False)
        self.assertTrue(all(not s.has_source and s.level == 'info' for s in chk.sources.values()))
        self.assertEqual(codes(chk, 5), [])

    def test_many_uncovered_points_in_one_section_are_one_finding(self):
        pts = tuple((1100 + 50 * i, 'r2000') for i in range(6))
        ds = dcv_sheet(points=pts, ranges=((2000, 'r2000'),))
        f = [f for f in self.check(ds, dry_run_on=False).findings if f.rule == 5]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].count, 6)

    def test_the_one_point_lookup_used_by_the_inspector_agrees_with_the_full_check(self):
        ds = fx.dmm_34461a_like()
        chk = self.check(ds, dry_run_on=False)
        for fn, p in list(ds.all_points())[:25]:
            one = rules.point_source(ds, fn.id, p.id, matcher=self.matcher)
            self.assertEqual((one.text, one.has_source), (chk.sources[p.id].text, chk.sources[p.id].has_source), p.id)

    def test_the_report_row_of_an_uncovered_point_has_a_blank_uncertainty(self):
        ds = far_sheet()
        spec = dsp.export_spec(ds, plan=self.matcher.match(ds)).spec
        h = H.Harness().start()
        try:
            app = h.make_app(spec, demo=False)
            p = next(p for p in app.points if p['id'].endswith('1500'))
            row = app.certificate_row(p, {'reading': 1500.0, 'entered': '1500', 'result': 'PASS', 'standard': 'manual'})
            self.assertEqual(row.get('Uncertainty', ''), '')
        finally:
            h.stop()


# ================================================================================================================================ the grid model and the list
class ModelTests(Base):
    def grid(self, ds):
        g = M.GridModel(M.Storage(Path(tempfile.mkdtemp()) / 'us', Path(tempfile.mkdtemp()) / 'r.sqlite3'), matcher_factory=lambda: self.matcher)
        g.ds = ds
        g._bump()
        return g

    def test_check_is_cached_until_the_next_edit(self):
        g = self.grid(dcv_sheet())
        self.assertIsNone(g.sheet_check(compute=False))
        self.assertEqual(g.check_pill(), ('', 'good'))
        a = g.sheet_check()
        self.assertIs(g.sheet_check(), a)
        self.assertEqual(g.check_pill()[1], 'warn')                                  # the unverified command is a warning
        g._bump()
        self.assertIsNone(g.sheet_check(compute=False))

    def test_rows_name_the_section_the_row_the_rule_and_a_plain_fix(self):
        ds = far_sheet()
        g = self.grid(ds)
        rows = g.check_rows()
        r1 = next(r for r in rows if r['rule'] == 1)
        self.assertEqual((r1['level'], r1['where'], r1['action']), ('warn', 'DC volts', 'manual_entry'))
        self.assertTrue(r1['row'] and r1['key'].startswith('p:dcv:'))
        self.assertTrue(r1['fix'])
        self.assertTrue(r1['title'].startswith('Rule 1'))
        self.assertTrue(any(r['rule'] == 5 for r in rows))

    def test_apply_fix_is_one_undo_step(self):
        ds = far_sheet()
        g = self.grid(ds)
        g.sheet_check()
        i = next(r['idx'] for r in g.check_rows(compute=False) if r['rule'] == 1)
        res = g.apply_check_fix(i)
        self.assertTrue(res.ok, res.message)
        self.assertIn('by hand', res.message)
        self.assertEqual(g.ds.assignments, {pid_of(g.ds, 1500): 'MANUAL'})
        self.assertEqual(codes(g.sheet_check(), 1), [])
        g.undo()
        self.assertEqual(g.ds.assignments, {})
        self.assertFalse(g.apply_check_fix(99).ok)

    def test_make_check_fix_through_the_model(self):
        ds = dcv_sheet()
        ds.functions[0].points[0].label = '5 mA'
        g = self.grid(ds)
        g.sheet_check()
        i = next(r['idx'] for r in g.check_rows(compute=False) if r['rule'] == 3)
        res = g.apply_check_fix(i)
        self.assertTrue(res.ok, res.message)
        self.assertEqual([f.kind for f in g.ds.functions], ['DCV', 'CHECK'])
        self.assertEqual(g.sheet_check().errors(), [])

    def test_a_finding_with_no_automatic_fix_says_so(self):
        g = self.grid(dcv_sheet())
        g.sheet_check()
        i = next(r['idx'] for r in g.check_rows(compute=False) if r['rule'] == 2)
        self.assertFalse(g.apply_check_fix(i).ok)

    def test_uncertainty_line_of_the_selected_row(self):
        g = self.grid(dcv_sheet(points=((5, 'r10'), (1500, 'r1500')), ranges=((10, 'r10'), (1500, 'r1500'))))
        keys = [r['key'] for r in g.rows() if r['kind'] == 'point']
        text, level = g.uncertainty_line(keys[0])
        self.assertIn('standards sheet', text)
        self.assertEqual(level, 'ok')
        text, level = g.uncertainty_line(keys[1])
        self.assertTrue(text.startswith('none: blank'))
        self.assertEqual(level, 'error')
        self.assertEqual(g.uncertainty_line(next(r['key'] for r in g.rows() if r['kind'] == 'header')), ('', 'ok'))

    def test_pre_run_list_is_the_checks_unverified_commands(self):
        g = self.grid(dcv_sheet())
        info = g.pre_run_list()
        self.assertTrue(info['count'] and info['lines'] and info['fingerprint'])
        self.assertEqual(info['fingerprint'], g.sheet_check().fingerprint())

    def test_the_drafts_message_says_what_the_sheet_check_found(self):
        ds = dcv_sheet()
        ds.functions[0].points[0].label = '5 mA'
        g = self.grid(ds)
        g.ds.make, g.ds.model, g.ds.title = 'Acme', 'RM-1', 'Draft by rule'
        res = g.save_sheet()
        self.assertTrue(res.ok, res.message)
        self.assertIn('DRAFT', res.message)
        self.assertIn('sheet check found', res.message)
        self.assertEqual(res.detail.status, 'draft')


class ListColumn(Base):
    row = dict(deleted=False, runnable_version=1, spec_file='')

    def text(self, eng, check=None):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / 's.json'
            f.write_text(json.dumps({'dsb': {'engine': eng}}))
            return M.DatasheetList.automation_text(dict(self.row, spec_file=str(f)), check)

    def test_unchanged_text_when_nothing_is_unverified(self):
        self.assertEqual(self.text(dict(points=18, runnable=18, hand_set=0)), 'Ready: all 18 points run by the suite')
        self.assertEqual(self.text(dict(points=18, runnable=10, hand_set=8)), 'Ready: 10 of 18 points run by the suite, 8 set by hand')

    def test_it_no_longer_says_all_points_run_when_commands_are_unverified(self):
        t = self.text(dict(points=18, runnable=18, hand_set=0, check=dict(unverified_points=3, unverified_commands=2)))
        self.assertNotIn('all 18', t)
        self.assertIn('3 use commands not yet verified on hardware', t)
        self.assertIn('accept', t)
        t = self.text(dict(points=18, runnable=10, hand_set=8), dict(unverified_points=4))
        self.assertIn('8 set by hand', t)
        self.assertIn('4 use commands', t)

    def test_a_saved_sheet_carries_the_check_summary_in_its_spec(self):
        with tempfile.TemporaryDirectory() as t:
            ds = fx.dmm_34461a_like()
            rules.set_waiver(ds, ['acv.r750.+750@50000'], 'no_source', '', who='t')            # the one point no calibrator covers (rule 5 would block the save)
            with mock.patch.object(dm, 'Matcher', lambda *a, **k: self.matcher):
                res = db.save(ds, root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3')
            self.assertEqual(res.status, 'ready')
            spec = json.loads(Path(res.spec_path).read_text())
            chk = spec['dsb']['engine']['check']
            self.assertEqual((chk['errors'], chk['dry_run']), (0, True))
            self.assertTrue(chk['unverified_points'] >= 1 and chk['fingerprint'])

    def test_a_sheet_saved_before_the_check_existed_is_counted_from_the_matcher(self):
        with tempfile.TemporaryDirectory() as t:
            store = M.Storage(Path(t) / 'us', Path(t) / 'reg.sqlite3')
            ds = fx.dmm_34461a_like()
            rules.set_waiver(ds, ['acv.r750.+750@50000'], 'no_source', '', who='t')            # the one point no calibrator covers (rule 5 would block the save)
            with mock.patch.object(dm, 'Matcher', lambda *a, **k: self.matcher):
                res = db.save(ds, root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3')
            self.assertEqual(res.status, 'ready')
            spec = json.loads(Path(res.spec_path).read_text())
            del spec['dsb']['engine']['check']
            Path(res.spec_path).write_text(json.dumps(spec))
            lst = M.DatasheetList(store, matcher_factory=lambda: self.matcher)
            row = lst.refresh()[0]
            self.assertIn('use commands not yet verified', row['automation'])


# ================================================================================================================================ the window (Tk stub)
class WindowTests(Base):
    def setUp(self):
        import datasheet_builder_ui as ui_mod
        self.ui = ui_mod
        p = mock.patch.object(ui_mod.ui, 'fit_window')
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.store = M.Storage(t / 'user_specs', t / 'lab_registry.sqlite3', who='tester')
        self.panel = ui_mod.DatasheetBuilderPanel(ui_mod.tk.Frame(), self.store, on_saved=lambda: None, status=ui_mod.tk.StringVar(), matcher_factory=lambda: self.matcher)

    def window(self, ds):
        win = self.panel.new()
        win.model.ds = ds
        win.model._bump()
        win.refresh()
        return win

    def test_sheet_check_button_pill_and_window(self):
        win = self.window(dcv_sheet(points=((5, 'r10'), (1500, 'r1500')), ranges=((10, 'r10'), (1500, 'r1500'))))
        self.assertTrue(hasattr(win, 'check_b'))
        self.assertEqual(win.model.check_pill()[0], '')
        w = win.show_check()
        self.assertIsInstance(w, self.ui.CK.SheetCheckWindow)
        self.assertTrue(win.model.check_pill()[0].startswith('check:'))
        self.assertTrue(w._rows)
        self.assertIs(win.show_check(compute=False), w)                              # the open window is reused

    def test_check_window_actions(self):
        win = self.window(dcv_sheet(points=((5, 'r10'), (1500, 'r1500')), ranges=((10, 'r10'), (1500, 'r1500'))))
        w = win.show_check()
        i = next(i for i, r in enumerate(w._rows) if r['rule'] == 1)
        with mock.patch.object(w, '_selected', return_value=w._rows[i]):
            self.assertEqual(w.go()['rule'], 1)
            res = w.fix()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(win.model.ds.assignments, {pid_of(win.model.ds, 1500): 'MANUAL'})
        self.assertFalse([r for r in w._rows if r['rule'] == 1])
        self.assertIsNotNone(w.commands())                                           # the commands to accept list

    def test_an_error_in_the_check_stops_run_and_demo(self):
        ds = dcv_sheet()
        ds.functions[0].points[0].label = '5 mA'
        win = self.window(ds)
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(demo)
        for demo in (True, False):
            with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=True) as ask:
                res = win.run_sheet(demo)
            self.assertFalse(res.ok)
            self.assertIn('sheet check found', res.message)
            self.assertFalse(ask.called)
        self.assertEqual(calls, [])

    def test_real_run_question_lists_the_unverified_commands_and_passes_the_fingerprint(self):
        win = self.window(dcv_sheet())
        win.model.ds.make, win.model.ds.model, win.model.ds.title = 'Acme', 'RM-1', 'Rules DCV'
        seen, entries = [], []
        win.launcher = lambda entry, demo=False: entries.append((dict(entry), demo))
        with mock.patch.object(self.ui.messagebox, 'askyesno', lambda title, message, **kw: seen.append((title, message, kw)) or True):
            res = win.run_sheet(False)
        self.assertTrue(res.ok, res.message)
        title, message, kw = seen[0]
        self.assertEqual((title, kw.get('default')), ('Run on real instruments', 'no'))
        self.assertIn('Yes means you accept them', message)
        self.assertIn('not verified on hardware', message)
        fp = win.model.sheet_check().fingerprint()
        self.assertEqual(entries[0][0]['accepted_unverified'], fp)
        # demo: no question about real instruments, no acceptance passed
        entries.clear()
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=True):
            self.assertTrue(win.run_sheet(True).ok)
        self.assertNotIn('accepted_unverified', entries[0][0])

    def test_declining_the_list_launches_nothing(self):
        win = self.window(dcv_sheet())
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(demo)
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=False):
            res = win.run_sheet(False)
        self.assertFalse(res.ok)
        self.assertEqual(calls, [])

    def test_inspector_shows_the_uncertainty_source_of_the_selected_row(self):
        win = self.window(far_sheet())
        keys = [r['key'] for r in win.model.rows() if r['kind'] == 'point']
        shown = []
        with mock.patch.object(win.panel_box, 'set_uncertainty', lambda text, level='ok': shown.append((text, level))):
            win.model.select(keys[0], 'nominal')
            win.sync()
            win.model.select(keys[1], 'nominal')
            win.sync()
        self.assertIn('standards sheet', shown[0][0])
        self.assertEqual(shown[0][1], 'ok')
        self.assertTrue(shown[1][0].startswith('none: blank'))
        self.assertEqual(shown[1][1], 'error')
        self.assertIn('uncert', win.panel_box.sections)


# ================================================================================================================================ rule 5, owner rule: no publish without an uncertainty or a waiver
class Rule5Blocking(Base):
    def save(self, ds, t, name='a'):
        with mock.patch.object(dm, 'Matcher', lambda *a, **k: self.matcher):
            return db.save(ds, who='tester', root=Path(t) / ('us' + name), db=Path(t) / f'reg{name}.sqlite3')

    def test_a_reading_with_no_uncertainty_blocks_publishing(self):
        with tempfile.TemporaryDirectory() as t:
            res = self.save(far_sheet(), t)
            self.assertEqual(res.status, 'draft')
            codes_ = [str(p.code) for p in res.problems]
            self.assertIn('rule5_no_uncertainty', codes_)
            self.assertIn('never shows zero', ' '.join(str(p) for p in res.problems))

    def test_the_finding_names_the_row_the_reason_and_the_fix(self):
        ds = far_sheet()
        f = [f for f in rules.check(ds, matcher=self.matcher, dry_run_on=False).findings if f.code == 'no_uncertainty'][0]
        self.assertEqual((f.rule, f.level, f.action), (5, 'error', 'waive'))
        self.assertIn('1.5 kV', f.text)
        self.assertIn('no standards sheet covers this point', f.text)
        self.assertIn('Waive', f.fix)
        self.assertEqual(f.point_ids, (pid_of(ds, 1500),))

    def test_reasons_are_specific(self):
        ds = dcv_sheet()
        pid = pid_of(ds, 5)
        ds.assignments[pid] = 'MANUAL'
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertIn('no standard selected', chk.sources[pid].text)
        self.assertEqual(chk.sources[pid].level, 'error')

    def test_a_waiver_lets_the_sheet_publish_and_is_recorded_everywhere(self):
        ds = far_sheet()
        pid = pid_of(ds, 1500)
        rules.set_waiver(ds, [pid], 'scope', '', who='mike')
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual([f.code for f in chk.errors()], [])
        w = [f for f in chk.findings if f.code == 'waived']
        self.assertEqual(len(w), 1)                                                   # shown in the check, never silent
        self.assertIn('scope of accreditation', w[0].text)
        self.assertIn('mike', w[0].text)
        self.assertIn('waived', chk.sources[pid].text)
        self.assertFalse(chk.sources[pid].has_source)                                 # still blank on the report, never zero
        with tempfile.TemporaryDirectory() as t:
            res = self.save(ds, t)
            self.assertEqual(res.status, 'ready')
            saved = json.loads(Path(res.version_file).read_text())
            self.assertEqual(saved['options']['uncertainty_waivers'][pid]['code'], 'scope')   # stored in the sheet
            self.assertEqual(saved['options']['uncertainty_waivers'][pid]['by'], 'mike')
            hist = db.versions(res.uid, root=Path(t) / 'usa', db=Path(t) / 'rega.sqlite3')
            self.assertIn('uncertainty waivers: 1 point', hist[0]['note'])             # and in the sheet's history
            spec = json.loads(Path(res.spec_path).read_text())
            self.assertEqual((spec['dsb']['engine']['check']['missing_uncertainties'], spec['dsb']['engine']['check']['waived_uncertainties']), (0, 1))

    def test_a_typed_reason_is_required_for_other_and_kept(self):
        ds = far_sheet()
        pid = pid_of(ds, 1500)
        with self.assertRaises(db.DsError):
            rules.set_waiver(ds, [pid], 'other', '  ', who='m')
        with self.assertRaises(db.DsError):
            rules.set_waiver(ds, [pid], 'nonsense', 'x', who='m')
        rules.set_waiver(ds, [pid], 'other', 'customer supplies the standard', who='m')
        self.assertEqual(rules.waiver_for(ds, pid)['reason'], 'customer supplies the standard')

    def test_removing_the_waiver_puts_the_error_back(self):
        ds = far_sheet()
        pid = pid_of(ds, 1500)
        rules.set_waiver(ds, [pid], 'no_source', '', who='m')
        self.assertEqual(rules.clear_waiver(ds, [pid]), 1)
        self.assertNotIn('uncertainty_waivers', ds.options)
        self.assertEqual([f.code for f in rules.check(ds, matcher=self.matcher, dry_run_on=False).errors()], ['no_uncertainty'])

    def test_fixing_the_point_publishes_without_a_waiver(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self.save(dcv_sheet(), t).status, 'ready')

    def test_kinds_that_carry_no_uncertainty_need_no_waiver(self):
        for name in ('generator_33220a_like', 'scope_tds2000c_like'):
            chk = rules.check(getattr(fx, name)(), matcher=self.matcher, dry_run_on=False)
            self.assertEqual([f.code for f in chk.findings if f.rule == 5], [], name)
        self.assertFalse(rules.should_have(*next(iter(fx.generator_33220a_like().all_points()))))

    def test_a_disabled_point_is_not_checked(self):
        ds = far_sheet()
        next(p for _f, p in ds.all_points() if p.nominal == D('1500')).enabled = False
        self.assertEqual([f.code for f in rules.check(ds, matcher=self.matcher, dry_run_on=False).errors()], [])

    def test_the_mudcats_import_is_recorded_as_waived_for_the_whole_sheet(self):
        d = Path(tempfile.mkdtemp())
        parsed = imp.parse_mdd(mdd_synth.write_mdd(d / 'Synth 87V.MDD'))
        conv = mc.convert(parsed)
        self.assertTrue([f for f in rules.check(conv.sheet, matcher=self.matcher).errors() if f.rule == 5])   # a converted sheet alone is not waived
        res = mc.register(conv, parsed, 'tester', registry=d / 'reg.sqlite3', root=d / 'us', archive_to=d / 'arch')
        self.assertTrue(res.ok, res.message)
        ds = db.load(res.uid, root=d / 'us', db=d / 'reg.sqlite3') if hasattr(db, 'load') else None
        if ds is not None:
            w = rules.waivers(ds)[rules.WHOLE_SHEET]
            self.assertEqual((w['code'], w['by']), ('manual_calibration', 'import (tester)'))

    def test_the_handheld_template_is_not_blocked(self):
        g = M.GridModel(M.Storage(Path(tempfile.mkdtemp()) / 'us', Path(tempfile.mkdtemp()) / 'r.sqlite3'), matcher_factory=lambda: self.matcher)
        g.set_header(make='Acme', model='DM-1', title='DM-1 handheld')
        g.add_handheld_functions()
        chk = rules.check(g.ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual([f.code for f in chk.errors()], [])                          # sections without points: nothing should have an uncertainty yet
        dcv = next(f for f in g.ds.functions if f.kind == 'DCV')
        g.select(f'e:{dcv.id}', 'nominal')
        g.set_target_function('DC volts')
        g.commit_cell('5 V')
        chk = rules.check(g.ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual([f.code for f in chk.errors() if f.rule == 5], [])           # a covered 5 V point

    def test_model_waive_is_one_undo_step_and_unblocks(self):
        g = Rule5Blocking.grid(self, far_sheet())
        g.sheet_check()
        idx = next(r['idx'] for r in g.check_rows(compute=False) if r['code'] == 'no_uncertainty')
        self.assertFalse(g.apply_check_fix(idx).ok)                                   # waiving needs a reason: the plain fix only says so
        res = g.waive_finding(idx, 'zero_offset')
        self.assertTrue(res.ok, res.message)
        self.assertEqual([f.code for f in g.sheet_check().errors()], [])
        g.undo()
        self.assertEqual([f.code for f in g.sheet_check().errors()], ['no_uncertainty'])

    def grid(self, ds):
        g = M.GridModel(M.Storage(Path(tempfile.mkdtemp()) / 'us', Path(tempfile.mkdtemp()) / 'r.sqlite3'), matcher_factory=lambda: self.matcher)
        g.ds = ds
        g._bump()
        return g

    def test_the_manager_list_says_how_many_are_missing(self):
        text = M.DatasheetList.automation_text(dict(runnable_version=1, spec_file='x'), dict(missing_uncertainties=3)) if False else None
        import tempfile as _t
        d = Path(_t.mkdtemp())
        spec = d / 's.json'
        spec.write_text(json.dumps({'dsb': {'engine': {'points': 4, 'runnable': 4, 'hand_set': 0}}}))
        row = dict(runnable_version=1, spec_file=str(spec))
        self.assertEqual(M.DatasheetList.automation_text(row, dict(missing_uncertainties=0)), 'Ready: all 4 points run by the suite')
        self.assertIn('missing uncertainties: 3', M.DatasheetList.automation_text(row, dict(missing_uncertainties=3)))


if __name__ == '__main__':
    unittest.main()
