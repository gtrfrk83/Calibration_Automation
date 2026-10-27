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


def cap_sheet():
    """A capacitance sheet: the 5560A's capacitance commands are not verified on hardware, so a real run lists them (a DC volts sheet lists nothing: only routine ERR? is unverified)."""
    ds = db.Datasheet('Acme', 'RM-2', 'Rules CAP')
    fn = ds.add_function('CAP', id='cap')
    fn.add_range('0.00000001', resolution='0.000000000001', id='r10n')
    ds.set_spec(fn, '1 % of reading + 2 counts')
    db.add_point(fn, '0.000000001', range_id='r10n')
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
        a = self.check(cap_sheet()).fingerprint()
        ds = cap_sheet()
        db.add_point(ds.functions[0], '0.000000002', range_id='r10n')
        b = self.check(ds).fingerprint()
        c = self.check(dcv_sheet()).fingerprint()
        self.assertEqual(a, b)                                                  # more points, same commands: same list
        self.assertNotEqual(a, c)
        self.assertTrue(a)
        self.assertEqual(c, '')                                                 # a DC volts sheet has only exempt unverified commands

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
        spec = self.spec_of(cap_sheet())
        with mock.patch.object(rules.dm if hasattr(rules, 'dm') else dm, 'Matcher', lambda *a, **k: self.matcher):
            asked = []
            self.assertFalse(dsb_prerun.accepted(None, spec, '', ask=lambda info: asked.append(info) or False))
            self.assertEqual(len(asked), 1)
            self.assertTrue(asked[0]['count'] >= 1)
            self.assertTrue(asked[0]['lines'])
            self.assertTrue(dsb_prerun.accepted(None, spec, '', ask=lambda info: True))

    def test_the_fingerprint_the_builder_passed_skips_the_second_question(self):
        ds = cap_sheet()
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
            self.assertEqual([c for c in codes(self.check(self.with_label(label), dry_run_on=False), 3) if c != 'unit_variants'], [], label)

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
        rules.apply_manual_standard(conv.sheet, '', who='import', matcher=self.matcher)       # what mdd_convert.register records for 'None: waive' (per point, never the whole sheet)
        chk = rules.check(conv.sheet, matcher=self.matcher)
        self.assertEqual(chk.errors(), [], [f.text for f in chk.errors()])
        self.assertFalse(chk.dry.available)                                         # a manual calibration drives nothing
        self.assertEqual(codes(chk, 1), [])
        self.assertEqual(chk.unverified, [])
        self.assertEqual(set(codes(chk, 5)), {'waived'})                            # the per-point waivers are listed, one line per section


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

    def test_kinds_the_suite_cannot_resolve_are_blank_and_waived_in_the_fixture(self):
        chk = self.check(fx.generator_33220a_like(), dry_run_on=False)
        self.assertTrue(all(not s.has_source and s.level == 'info' and s.waived for s in chk.sources.values()))
        self.assertEqual(set(codes(chk, 5)), {'waived'})

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
        g = self.grid(cap_sheet())
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
        g = self.grid(cap_sheet())
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
        g = self.grid(cap_sheet())
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

    def test_kinds_outside_the_cmc_table_need_no_waiver(self):
        ds = db.Datasheet('Acme', 'RM-3', 'Rules DIODE')
        fn = ds.add_function('DIODE', id='dio')
        fn.add_range('3', resolution='0.0001', id='r3')
        ds.set_spec(fn, '0.1 % of reading + 2 counts')
        db.add_point(fn, '0.5', range_id='r3')
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual([f.code for f in chk.findings if f.rule == 5], [])
        self.assertFalse(rules.should_have(fn, fn.points[0]))

    def test_a_disabled_point_is_not_checked(self):
        ds = far_sheet()
        next(p for _f, p in ds.all_points() if p.nominal == D('1500')).enabled = False
        self.assertEqual([f.code for f in rules.check(ds, matcher=self.matcher, dry_run_on=False).errors()], [])

    def test_the_mudcats_import_without_a_standard_is_waived_per_point_not_for_the_whole_sheet(self):
        d = Path(tempfile.mkdtemp())
        parsed = imp.parse_mdd(mdd_synth.write_mdd(d / 'Synth 87V.MDD'))
        conv = mc.convert(parsed)
        self.assertTrue([f for f in rules.check(conv.sheet, matcher=self.matcher).errors() if f.rule == 5])   # a converted sheet alone is not waived
        res = mc.register(conv, parsed, 'tester', registry=d / 'reg.sqlite3', root=d / 'us', archive_to=d / 'arch')          # standard='' = None: waive
        self.assertTrue(res.ok, res.message)
        ds = db.load(res.uid, root=d / 'us', db=d / 'reg.sqlite3')
        w = rules.waivers(ds)
        self.assertNotIn(rules.WHOLE_SHEET, w)                                       # the old blanket waiver is gone
        should = [p.id for fn, p in ds.all_points() if p.enabled and rules.should_have(fn, p)]
        self.assertTrue(should)
        self.assertEqual(sorted(k for k in w), sorted(should))                       # one recorded waiver per point that should carry an uncertainty, none for the others
        self.assertTrue(all((v['code'], v['by']) == ('manual_calibration', 'import (tester)') for v in w.values()))
        self.assertTrue(all(v == 'MANUAL' for v in ds.assignments.values()))

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


# ================================================================================================================================ rule 2 exemptions, fail closed, notes
class HousekeepingExempt(Base):
    def test_only_read_only_status_queries_and_cls_are_exempt(self):
        for wire in ('*CLS', '*IDN?', '*ESR?', '*STB?', '*OPC?', 'ID?', 'ERR?', 'SYST:ERR?', ':SYST:ERR?', 'syst:err?', 'SYSTEM:ERROR? ', ':SYSTem:ERRor?'.upper()):
            self.assertTrue(rules.is_housekeeping(wire), wire)
        for wire in ('*RST', '*OPC', 'OUT 1V', 'OUT 0.0001A,0Hz', 'OUT?', 'STBY', 'OPER', ':ROSC:EXT:CHEC ON', 'SCOPE?', '*SRE 32', '*ESE 1', ':CONF:VOLT', ''):
            self.assertFalse(rules.is_housekeeping(wire), wire)

    def test_a_sheet_whose_only_unverified_commands_are_housekeeping_asks_nothing(self):
        chk = self.check(dcv_sheet())
        self.assertTrue(chk.dry.available, chk.dry.reason)
        self.assertEqual(chk.unverified, [])
        self.assertEqual(chk.fingerprint(), '')
        self.assertEqual([f.code for f in chk.findings if f.rule == 2], [])
        spec = dsp.export_spec(dcv_sheet(), plan=self.matcher.match(dcv_sheet())).spec
        with mock.patch.object(dm, 'Matcher', lambda *a, **k: self.matcher):
            self.assertTrue(dsb_prerun.accepted(None, spec, '', ask=lambda info: self.fail('the operator was asked')))

    def test_the_real_run_question_does_not_mention_acceptance_then(self):
        g = M.GridModel(M.Storage(Path(tempfile.mkdtemp()) / 'us', Path(tempfile.mkdtemp()) / 'r.sqlite3'), matcher_factory=lambda: self.matcher)
        g.ds = dcv_sheet()
        g._bump()
        info = g.pre_run_list()
        self.assertEqual((info['count'], info['lines'], info['fingerprint']), (0, [], ''))

    def test_commands_that_configure_source_or_measure_are_still_listed_and_the_exempt_ones_are_not(self):
        chk = self.check(cap_sheet())
        lines = ' '.join(chk.pre_run_lines())
        self.assertIn('OUT 1NF', lines)
        self.assertNotIn('ERR?', lines)
        self.assertTrue(all(not rules.is_housekeeping(u.wire) for u in chk.unverified))
        sent = {e.wire for pr in chk.dry.points.values() for e in pr.commands}
        self.assertTrue(any(rules.is_housekeeping(w) for w in sent))             # they ARE sent; they are only left off the list


class FailClosed(Base):
    def test_a_crash_in_the_check_is_one_error_with_the_reason(self):
        with mock.patch.object(rules, 'check', side_effect=RuntimeError('boom')), self.assertLogs('datasheet_builder_rules', 'ERROR') as log:
            problems, chk = rules.blocking_problems(dcv_sheet())
        self.assertIsNone(chk)
        self.assertEqual([(p.code, p.level) for p in problems], [('rule_check_failed', 'error')])
        self.assertIn('The sheet check could not run: RuntimeError: boom', str(problems[0]))
        self.assertIn('Traceback', log.output[0])                                   # the traceback is in the log

    def test_save_makes_a_draft_and_never_publishes_unchecked(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(rules, 'check', side_effect=RuntimeError('boom')), self.assertLogs('datasheet_builder_rules', 'ERROR'):
            res = db.save(dcv_sheet(), root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3')
            self.assertEqual(res.status, 'draft')
            self.assertIsNone(res.spec_path or None)
            self.assertIn('rule_check_failed', [str(p.code) for p in res.problems])
            self.assertIn('could not run', ' '.join(str(p) for p in res.problems))

    def test_when_the_rules_module_cannot_even_be_loaded_it_is_a_draft_too(self):
        import builtins
        real = builtins.__import__

        def no_rules(name, *a, **k):
            if name == 'datasheet_builder_rules':
                raise ImportError('gone')
            return real(name, *a, **k)
        with tempfile.TemporaryDirectory() as t, mock.patch.object(builtins, '__import__', no_rules), self.assertLogs('datasheet_builder', 'ERROR'):
            res = db.save(dcv_sheet(), root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3')
        self.assertEqual(res.status, 'draft')
        self.assertIn('rule_check_failed', [str(p.code) for p in res.problems])

    def test_a_working_check_still_publishes(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(dm, 'Matcher', lambda *a, **k: self.matcher):
            self.assertEqual(db.save(dcv_sheet(), root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3').status, 'ready')


class Attribution(Base):
    def test_the_mdd_import_waiver_is_attributed(self):
        d = Path(tempfile.mkdtemp())
        parsed = imp.parse_mdd(mdd_synth.write_mdd(d / 'Synth 87V.MDD'))
        conv = mc.convert(parsed)
        res = mc.register(conv, parsed, 'tester', registry=d / 'reg.sqlite3', root=d / 'us', archive_to=d / 'arch')
        self.assertTrue(res.ok, res.message)
        ds = db.load(res.uid, root=d / 'us', db=d / 'reg.sqlite3')
        w = rules.waivers(ds)
        self.assertTrue(w and rules.WHOLE_SHEET not in w)
        self.assertTrue(all(v['reason'].startswith('manual calibration: ') and v['by'] == 'import (tester)' for v in w.values()))
        chk = rules.check(ds, matcher=self.matcher)
        note = [f for f in chk.findings if f.code == 'waived']
        self.assertTrue(note and all('manual calibration: no standard was chosen' in f.text and 'import (tester)' in f.text for f in note))
        self.assertIn('uncertainty waivers', db.versions(res.uid, root=d / 'us', db=d / 'reg.sqlite3')[0]['note'])

    def test_accepted_unit_spellings_are_listed_in_a_note(self):
        ds = dcv_sheet()
        p = ds.functions[0].points[0]
        p.label = '5 Vrms'
        ds.functions[0].ranges[0].label = '10 VDC'
        chk = self.check(ds, dry_run_on=False)
        f = [f for f in chk.findings if f.code == 'unit_variants']
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].level, 'info')
        self.assertIn('"Vrms"', f[0].text)
        self.assertIn('"VDC"', f[0].text)
        self.assertEqual(rules.text_unit_ex('1 kOhm')[2], '"Ohm" read as \u03a9')
        self.assertEqual(rules.text_unit_ex('5 V')[2], '')                          # the program's own spelling: no note


# ================================================================================================================================ rule 5: the set comes from the CMC table
def strip_waivers(ds):
    ds.options.pop(rules.WAIVER_KEY, None)
    return ds


def one_point_sheet(kind, nominal, fs, spec='0.01 % of reading + 2 counts', **settings):
    ds = db.Datasheet('Acme', 'RM-9', f'Rules {kind}')
    fn = ds.add_function(kind, id='f', **({'settings': settings} if settings else {}))
    fn.add_range(fs, resolution='1e-9', id='r1')
    ds.set_spec(fn, spec)
    db.add_point(fn, nominal, range_id='r1')
    return ds


class Rule5CmcSet(Base):
    def test_every_kind_and_section_of_the_cmc_table_is_mapped_and_in_the_set(self):
        keys = rules.cmc_table_keys()
        self.assertTrue({'DCV', 'DCI', 'OHM', 'CAP', 'ACI', 'ACV', 'FREQ', 'oscilloscope.dc', 'oscilloscope.flatness', 'oscilloscope.amplitude'} <= keys)
        missing = sorted(k for k in keys if k not in rules.CMC_KIND_MAP)
        self.assertEqual(missing, [], 'a kind in specs/a2la_1888_03_cmc.json that the Sheet check does not know: add it to CMC_KIND_MAP')
        for k in keys:
            for kind in rules.CMC_KIND_MAP[k]:
                self.assertIn(kind, db.KINDS, k)
                self.assertIn(kind, rules.SHOULD_HAVE_KINDS, (k, kind))

    def test_a_new_kind_in_the_table_is_picked_up_from_the_file(self):
        d = Path(tempfile.mkdtemp())
        data = json.loads((ROOT / 'specs' / 'a2la_1888_03_cmc.json').read_text(encoding='utf-8'))
        data['entries'].append(dict(data['entries'][0], kind='NEWKIND'))
        (d / 'cmc.json').write_text(json.dumps(data), encoding='utf-8')
        self.assertIn('NEWKIND', rules.cmc_table_keys(d / 'cmc.json'))
        self.assertNotIn('NEWKIND', rules.CMC_KIND_MAP)                                  # the test above would fail on it

    def test_a_kind_removed_from_the_table_leaves_the_set(self):
        d = Path(tempfile.mkdtemp())
        data = json.loads((ROOT / 'specs' / 'a2la_1888_03_cmc.json').read_text(encoding='utf-8'))
        data['entries'] = [e for e in data['entries'] if e['kind'] != 'FREQ']
        (d / 'cmc.json').write_text(json.dumps(data), encoding='utf-8')
        self.assertNotIn('FREQ', rules.should_have_kinds(d / 'cmc.json'))
        self.assertIn('FREQ', rules.SHOULD_HAVE_KINDS)

    def test_what_can_be_resolved_today_and_what_only_by_waiver(self):
        self.assertEqual(set(rules.RESOLVABLE_KINDS), {'DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP', 'TEMP'})
        only_by_waiver = rules.SHOULD_HAVE_KINDS - set(rules.RESOLVABLE_KINDS)
        self.assertEqual(only_by_waiver, {'FREQ', 'PERIOD', 'GEN_FREQ', 'SCOPE_TIMEBASE', 'SCOPE_GAIN', 'SCOPE_OFFSET', 'SCOPE_BW', 'GEN_AMPL', 'GEN_FLAT', 'GEN_OFFSET'})

    def test_a_frequency_point_blocks_publishing_until_it_is_waived(self):
        ds = one_point_sheet('FREQ', '1000', '300000')
        ds.functions[0].points[0].amplitude = D('1')
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        f = [f for f in chk.errors() if f.code == 'no_uncertainty']
        self.assertEqual(len(f), 1, [x.text for x in chk.findings])
        self.assertIn('no uncertainty calculation for this kind yet', f[0].text)
        self.assertIn('not implemented', f[0].fix)
        with tempfile.TemporaryDirectory() as t:
            res = db.save(ds, root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3')
            self.assertEqual(res.status, 'draft')
            pid = ds.functions[0].points[0].id
            rules.set_waiver(ds, [pid], 'not_implemented', '', who='mike')
            self.assertEqual([x.code for x in rules.check(ds, matcher=self.matcher, dry_run_on=False).errors()], [])
            ok = db.save(ds, root=Path(t) / 'us2', db=Path(t) / 'reg2.sqlite3')
            self.assertEqual(ok.status, 'ready')
            self.assertIn('not implemented in the suite yet', json.dumps(json.loads(Path(ok.version_file).read_text())['options']))

    def test_a_scope_amplitude_point_blocks_publishing_until_it_is_waived(self):
        for name in ('generator_33220a_like', 'scope_tds2000c_like'):
            ds = strip_waivers(getattr(fx, name)())
            chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
            self.assertTrue([f for f in chk.errors() if f.code == 'no_uncertainty'], name)
            with tempfile.TemporaryDirectory() as t:
                self.assertEqual(db.save(ds, root=Path(t) / 'us', db=Path(t) / 'reg.sqlite3').status, 'draft', name)
            self.assertEqual(rules.check(getattr(fx, name)(), matcher=self.matcher, dry_run_on=False).errors(), [], name)       # the fixture carries its waivers

    def test_the_waiver_list_offers_the_not_implemented_reason(self):
        self.assertIn(('not_implemented', 'Uncertainty calculation for this kind is not implemented in the suite yet'), rules.WAIVER_REASONS)

    def test_the_dmm_kinds_still_resolve_without_a_waiver(self):
        self.assertEqual([f.code for f in rules.check(dcv_sheet(), matcher=self.matcher, dry_run_on=False).errors()], [])

    def test_the_mudcats_import_is_covered_by_its_waivers_even_with_frequency_rows(self):
        d = Path(tempfile.mkdtemp())
        conv = mc.convert(imp.parse_mdd(mdd_synth.write_mdd(d / 'Synth 87V.MDD')))
        self.assertTrue([f for f in rules.check(conv.sheet, matcher=self.matcher, dry_run_on=False).errors() if f.rule == 5])
        rules.apply_manual_standard(conv.sheet, '', who='import (t)', matcher=self.matcher)
        self.assertEqual(rules.check(conv.sheet, matcher=self.matcher, dry_run_on=False).errors(), [])

    def test_a_whole_sheet_waiver_of_an_older_import_still_works_unchanged(self):
        """Existing imported manual procedures are not changed: they keep their whole-sheet waiver and are evaluated when next saved."""
        d = Path(tempfile.mkdtemp())
        conv = mc.convert(imp.parse_mdd(mdd_synth.write_mdd(d / 'Synth 87V.MDD')))
        rules.set_waiver(conv.sheet, [rules.WHOLE_SHEET], 'manual_calibration', 'manual calibration: imported from .MDD, no automation', who='import (t)')
        chk = rules.check(conv.sheet, matcher=self.matcher, dry_run_on=False)
        self.assertEqual(chk.errors(), [])
        self.assertEqual(set(codes(chk, 5)), {'waived'})
        self.assertTrue(all('imported from .MDD, no automation' in f.text for f in chk.findings if f.code == 'waived'))
        self.assertTrue(any('waived (manual calibration: imported from .MDD, no automation' in s.text for s in chk.sources.values()))


# ================================================================================================================================ manual calibrations: the standard of the uncertainty
class ManualStandard(Base):
    """A manual calibration carries the uncertainty of the STANDARD the author chose (owner decision) instead of a whole-sheet waiver."""

    def sheet(self):
        d = Path(tempfile.mkdtemp())
        return mc.convert(imp.parse_mdd(mdd_synth.write_mdd(d / 'Synth 87V.MDD'))).sheet

    def pts(self, ds):
        return {int(p.id.rsplit('.p', 1)[1]): (fn, p) for fn, p in ds.all_points()}

    def test_the_chosen_standard_gives_the_uncertainty_on_resolvable_points(self):
        import report_pdf
        import uncertainty
        ds = self.sheet()
        plan = rules.apply_manual_standard(ds, '5522A', who='import (t)', matcher=self.matcher)
        pts = self.pts(ds)
        dcv = pts[2][1]                                                          # 1.000 V DC
        self.assertEqual(ds.assignments[dcv.id], '5522A')                       # the person's override, instead of the 'MANUAL' marker
        self.assertEqual(ds.options['manual_standard'], '5522A')
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual(chk.errors(), [], [f.text for f in chk.errors()])
        src = chk.sources[dcv.id]
        self.assertTrue(src.has_source and src.standard == '5522A' and '5522A standards sheet' in src.text, src.text)
        # the same figure as an AUTOMATED sheet gets for that standard, and as the report code works it out (k = 2, rounded up, never below the lab CMC)
        auto = ds.copy()
        auto.options['manual_entry'] = False
        a = self.matcher.match(auto, overrides={dcv.id: '5522A'}).assignments[dcv.id]
        self.assertEqual(a.status, 'assigned')
        self.assertEqual(plan.sourced[dcv.id].uncertainty, a.uncertainty)
        self.assertTrue(a.uncertainty > 0)
        text = uncertainty.format_value(a.uncertainty, 'V')
        self.assertEqual(text, report_pdf.point_uncertainty(dict(kind='DCV', nominal=1.0, frequency=None, unit='V', range=None), '5522A'))
        # every DCV / ACV / ohm point the 5522A covers carries one
        for n in (1, 2, 3, 4, 5, 7, 8):
            self.assertEqual(ds.assignments[pts[n][1].id], '5522A', n)
            self.assertTrue(chk.sources[pts[n][1].id].has_source, n)

    def test_a_point_the_standard_does_not_cover_gets_a_per_point_waiver(self):
        ds = self.sheet()
        plan = rules.apply_manual_standard(ds, '5522A', who='import (t)', matcher=self.matcher)
        pts = self.pts(ds)
        nocov = pts[6][1]                                                        # an AC point with no frequency in the MDD: no row can cover it
        self.assertIn(nocov.id, plan.waived)
        self.assertEqual(ds.assignments[nocov.id], 'MANUAL')
        w = rules.waivers(ds)
        self.assertNotIn(rules.WHOLE_SHEET, w)
        self.assertEqual((w[nocov.id]['code'], w[nocov.id]['by']), ('manual_calibration', 'import (t)'))
        self.assertIn('5522A does not cover this point', w[nocov.id]['reason'])
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual(chk.errors(), [])
        src = chk.sources[nocov.id]
        self.assertFalse(src.has_source)
        self.assertTrue(src.waived and 'waived' in src.text, src.text)
        listed = [f for f in chk.findings if f.code == 'waived' and nocov.id in f.point_ids]
        self.assertEqual(len(listed), 1)                                         # never silent: listed in the Sheet check
        self.assertIn('5522A does not cover this point', listed[0].text)

    def test_frequency_takes_the_lab_frequency_cmc_alone_when_the_standard_covers_it(self):
        import report_pdf
        import uncertainty
        ds = self.sheet()
        plan = rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        fn, fq = self.pts(ds)[11]                                                # Frequency
        self.assertEqual(fn.kind, 'FREQ')
        self.assertEqual(ds.assignments[fq.id], '5522A')
        self.assertNotIn(fq.id, plan.waived)
        cand = plan.sourced[fq.id]
        self.assertEqual(cand.uncertainty, cand.cmc)                              # the scope CMC alone: not the standard's own frequency row (that is far larger)
        self.assertEqual(cand.uncertainty, report_pdf.scope().dmm('FREQ', float(fq.nominal), None, None, basis='measure'))
        q = dict(kind='FREQ', nominal=float(fq.nominal), frequency=None, unit='Hz', range=1.0, source='x')
        self.assertEqual(uncertainty.format_value(cand.uncertainty, 'Hz'), report_pdf.point_uncertainty(q, '5522A'))        # the engines' own report text
        self.assertGreater(cand.uncertainty, 0)
        self.assertEqual(rules.check(ds, matcher=self.matcher, dry_run_on=False).errors(), [])

    def _freq_sheet(self, kind, nominal, fs):
        ds = db.Datasheet('Acme', 'RM-9', f'Manual {kind}')
        ds.options['manual_entry'] = True
        fn = ds.add_function(kind, id='f')
        fn.add_range(fs, resolution='1e-9', id='r1')
        ds.set_spec(fn, '0.01 % of reading')
        db.add_point(fn, nominal, range_id='r1')
        return ds, fn

    def test_period_is_the_same_relative_uncertainty_of_one_over_f_in_seconds(self):
        ds, fn = self._freq_sheet('PERIOD', '1 ms', '1')
        plan = rules.apply_manual_standard(ds, '5560A', matcher=self.matcher)
        p = fn.points[0]
        cand = plan.sourced[p.id]
        rel = self.matcher.scope.dmm('FREQ', 1000.0, None, None, basis='measure') / 1000.0                  # the CMC relative to the frequency
        self.assertAlmostEqual(cand.uncertainty / 1e-3, rel, delta=rel * 1e-9)
        self.assertTrue(0 < cand.uncertainty < 1e-9)                                                            # seconds, not hertz
        self.assertIsNone(cand.tur)                                                                             # no ratio claimed across units
        self.assertEqual(ds.assignments[p.id], '5560A')

    def test_a_frequency_the_standard_does_not_cover_is_waived_per_point(self):
        ds, fn = self._freq_sheet('FREQ', '50 MHz', '1e9')
        plan = rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        pid = fn.points[0].id
        self.assertIn(pid, plan.waived)
        self.assertIn('5522A does not cover this point', plan.waived[pid])
        self.assertEqual(ds.assignments[pid], 'MANUAL')
        self.assertIn(pid, rules.waivers(ds))

    def test_what_a_manual_sheet_resolves_that_an_automated_one_does_not(self):
        self.assertEqual(rules.MANUAL_RESOLVABLE_KINDS, rules.RESOLVABLE_KINDS + ('FREQ', 'PERIOD'))
        self.assertNotIn('FREQ', rules.RESOLVABLE_KINDS)                                       # an automated sheet's FREQ / PERIOD stay waived (the matcher's figure there is another method)
        ds, fn = self._freq_sheet('GEN_FREQ', '1 kHz', '1e6')
        plan = rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        self.assertIn('no uncertainty calculation', plan.waived[fn.points[0].id])              # still waived: no calculation for it yet

    def test_the_figures_of_an_automated_sheet_are_not_touched(self):
        ds = self.sheet()
        auto = ds.copy()
        auto.options['manual_entry'] = False
        fq = self.pts(auto)[11][1]
        a = self.matcher.match(auto, overrides={fq.id: '5522A'}).assignments[fq.id]
        self.assertGreater(a.uncertainty, 1e-3)                                                # the standard's own frequency row, as before (not the 7e-12 relative CMC)

    def test_none_waive_is_the_old_result_but_per_point(self):
        ds = self.sheet()
        self.assertTrue([f for f in rules.check(ds, matcher=self.matcher, dry_run_on=False).errors() if f.rule == 5])      # nothing chosen, nothing waived: blocked
        plan = rules.apply_manual_standard(ds, '', who='import (t)', matcher=self.matcher)
        self.assertEqual(plan.sourced, {})
        self.assertTrue(all(v == 'MANUAL' for v in ds.assignments.values()))
        should = {p.id for fn, p in ds.all_points() if rules.should_have(fn, p)}
        self.assertEqual(set(rules.waivers(ds)), should)
        self.assertNotIn(rules.WHOLE_SHEET, rules.waivers(ds))
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual(chk.errors(), [])
        self.assertTrue(all(not chk.sources[pid].has_source and chk.sources[pid].waived for pid in should))
        self.assertTrue(all('no standard was chosen' in rules.waivers(ds)[pid]['reason'] for pid in should))

    def test_kinds_that_carry_no_uncertainty_by_design_need_no_waiver(self):
        ds = self.sheet()
        rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        by_design = [p.id for fn, p in ds.all_points() if fn.kind in ('TEMPF', 'COND', 'PCT', 'CHECK', 'DIODE', 'CONT')]
        self.assertTrue(by_design)
        w = rules.waivers(ds)
        self.assertFalse([pid for pid in by_design if pid in w])
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertTrue(all(chk.sources[pid].level == 'info' and not chk.sources[pid].waived for pid in by_design))

    def test_an_uncertainty_is_never_zero_or_invented(self):
        ds = self.sheet()
        plan = rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        self.assertTrue(plan.sourced and all(c.uncertainty and c.uncertainty > 0 for c in plan.sourced.values()))
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        for pid, src in chk.sources.items():
            self.assertTrue(src.has_source or src.text.startswith('none: blank'), (pid, src.text))
        # a standard that cannot source anything on the sheet puts a waiver on every point, never a made-up figure
        ds2 = self.sheet()
        plan2 = rules.apply_manual_standard(ds2, '5790B', matcher=self.matcher)
        self.assertEqual(plan2.sourced, {})
        self.assertTrue(all('5790B does not cover this point' in r or 'no uncertainty calculation' in r for r in plan2.waived.values()))
        self.assertEqual(rules.check(ds2, matcher=self.matcher, dry_run_on=False).errors(), [])

    def test_the_author_can_choose_a_different_standard_for_one_point(self):
        ds = self.sheet()
        rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        dcv = self.pts(ds)[2][1]
        ds.assignments[dcv.id] = '5560A'                                          # the existing override (ds.assignments, the Builder's per-point picker)
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual(chk.sources[dcv.id].standard, '5560A')
        self.assertIn('5560A standards sheet', chk.sources[dcv.id].text)
        self.assertEqual(chk.sources[self.pts(ds)[3][1].id].standard, '5522A')       # the others keep the sheet's standard
        self.assertEqual(rules.point_source(ds, self.pts(ds)[2][0].id, dcv.id, matcher=self.matcher).standard, '5560A')
        self.assertEqual(chk.errors(), [])

    def test_the_builders_picker_works_on_a_manual_sheet_and_says_nothing_is_automated(self):
        ds = self.sheet()
        rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        ed = M.GridModel(M.Storage(root=Path(tempfile.mkdtemp()) / "us", db_path=Path(tempfile.mkdtemp()) / "r.sqlite3"), ds, matcher_factory=lambda: self.matcher)
        dcv = self.pts(ds)[2][1]
        ed.run_match()
        self.assertIn('Manual calibration', ed.match_summary_text())
        self.assertNotIn('can be run automatically', ed.match_summary_text())
        row = next(r for r in ed.match_rows() if r['point_id'] == dcv.id)
        self.assertEqual((row['standard'], row['can_automate']), ('5522A', False))
        self.assertIn('set by hand', row['automation'])
        self.assertTrue(all(not c['can_automate'] for c in ed.candidate_rows(dcv.id)))
        self.assertTrue(ed.set_assignment(dcv.id, '5560A').ok)
        self.assertEqual(ed.ds.assignments[dcv.id], '5560A')
        self.assertEqual(ed.sheet_check(compute=True).sources[dcv.id].standard, '5560A')

    def test_removing_a_waiver_puts_the_error_back(self):
        ds = self.sheet()
        rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        pid = self.pts(ds)[6][1].id
        rules.clear_waiver(ds, [pid])
        chk = rules.check(ds, matcher=self.matcher, dry_run_on=False)
        self.assertEqual([f.code for f in chk.errors()], ['no_uncertainty'])
        self.assertIn(pid, chk.errors()[0].point_ids)

    def test_a_second_apply_replaces_the_first(self):
        ds = self.sheet()
        rules.apply_manual_standard(ds, '', matcher=self.matcher)
        rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        rules.apply_manual_standard(ds, '5560A', matcher=self.matcher)
        self.assertEqual({v for v in ds.assignments.values()} - {'MANUAL'}, {'5560A'})
        self.assertEqual(ds.options['manual_standard'], '5560A')
        self.assertTrue(all('5522A' not in w['reason'] for w in rules.waivers(ds).values()))

    def test_the_manager_list_counts_missing_uncertainties_for_a_manual_sheet(self):
        ds = self.sheet()
        self.assertTrue(rules.list_summary(ds, matcher=self.matcher)['missing'] > 0)
        rules.apply_manual_standard(ds, '5522A', matcher=self.matcher)
        s = rules.list_summary(ds, matcher=self.matcher)
        self.assertEqual((s['missing'], s['runnable'], s['unverified']), (0, 0, 0))
        self.assertEqual(s['points'], sum(1 for _f, p in ds.all_points() if p.enabled))

    def test_best_fit_standard_is_preselected_from_the_sheets_kinds(self):
        ds = self.sheet()
        fits = mc.standard_fits(ds, matcher=self.matcher)
        self.assertEqual(mc.best_standard(fits), '5522A')                         # handheld DMM functions: 5522A (then 5520A, 5560A) when the coverage ties
        top = [f for f in fits if f.covered == fits[0].covered]
        self.assertEqual([f.model for f in top][:3], ['5522A', '5520A', '5560A'])
        self.assertTrue(all(f.covered == 0 for f in fits if f.model in ('5790B', '8563E', '3458A')))
        # a sheet none of the standards can cover: nothing is pre-selected (None: waive)
        diode = db.Datasheet('A', 'B', 'only diode')
        fn = diode.add_function('DIODE', id='d')
        fn.add_range('3', id='r')
        db.add_point(fn, '0.5', range_id='r')
        self.assertEqual(mc.best_standard(mc.standard_fits(diode, matcher=self.matcher)), '')

    def test_non_manual_sheets_resolve_exactly_as_before(self):
        ds = dcv_sheet()
        chk = self.check(ds, dry_run_on=False)
        pid = ds.functions[0].points[0].id
        self.assertTrue(chk.sources[pid].has_source)
        self.assertEqual(rules.list_summary(ds, matcher=self.matcher)['runnable'], 1)
        src = rules.uncertainty_source(ds, ds.functions[0], ds.functions[0].points[0], None, manual_sheet=False)
        self.assertIn('no standard selected', src.text)


class SensorRule(Base):
    """Rule 5, temperature: the sensor a temperature point is sourced as must be chosen (an ERROR that blocks publishing); old tc_type sheets keep working."""

    def temp_sheet(self, **settings):
        ds = db.Datasheet('A', 'T1', 'T')
        ds.set_periods([('1y', 'y')], '1y')
        t = ds.add_function('TEMP', settings=dict(settings))
        t.add_range('2000', '0.1')
        ds.set_spec(t, '1 °C')
        db.add_point(t, 100)
        db.add_point(t, 150)
        return ds, t

    def sensor_findings(self, ds):
        return [f for f in self.check(ds).findings if f.code == 'sensor_not_chosen']

    def test_no_choice_is_an_error_naming_the_rows_and_pointing_at_the_first(self):
        ds, t = self.temp_sheet()
        f = self.sensor_findings(ds)
        self.assertEqual([(x.level, x.rule, x.count) for x in f], [('error', 5, 2)])
        self.assertEqual(f[0].point_ids, tuple(p.id for p in t.points))
        self.assertIn('no sensor chosen', f[0].text)
        self.assertEqual([x.code for x in self.check(ds).findings if x.code == 'not_covered'], [])      # not also reported as 'no standard covers it'

    def test_a_point_sensor_or_an_old_tc_type_satisfies_it(self):
        ds, t = self.temp_sheet()
        t.points[0].settings['sensor'] = 'Pt385-100'
        self.assertEqual(len(self.sensor_findings(ds)[0].point_ids), 1)             # only the other one is missing
        t.points[1].settings['sensor'] = 'J'
        self.assertEqual(self.sensor_findings(ds), [])
        old, _t = self.temp_sheet(tc_type='K')
        self.assertEqual(self.sensor_findings(old), [])

    def test_a_disabled_point_and_a_manual_entry_sheet_are_not_reported(self):
        ds, t = self.temp_sheet()
        for p in t.points:
            p.enabled = False
        self.assertEqual(self.sensor_findings(ds), [])
        ds2, _t2 = self.temp_sheet()
        ds2.options['manual_entry'] = True
        self.assertEqual(self.sensor_findings(ds2), [])

    def test_nothing_is_reported_at_load(self):
        ds, _t = self.temp_sheet()
        back = db.Datasheet.from_dict(ds.to_dict())
        self.assertEqual(db.errors(db.validate(back)), [])                       # loading and validating say nothing; only the sheet check does


if __name__ == '__main__':
    unittest.main()
