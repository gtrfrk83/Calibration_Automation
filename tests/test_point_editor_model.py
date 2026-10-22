"""procmods_point_model: what the per-point window shows and lets a person do, with no Tk.  Real engine Apps on the simulated benches (the
engine supplies the command list, the point and the run state); a throw-away override store; developer mode through devmode.py's real gate."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import point_editor_harness as PH  # noqa: E402
import procmods as pm  # noqa: E402
import procmods_point_model as PM  # noqa: E402
import procmods_pointdef as pdef  # noqa: E402

PASSPHRASE = 'correct horse battery'


class Base(unittest.TestCase):
    build = staticmethod(PH.truevolt)

    def setUp(self):
        self.b = self.build()
        self.addCleanup(self.b.stop)
        self.app = self.b.app
        self.env = self.b.env
        self.lock = self.env.lock
        if hasattr(self.app, 'asset'):
            self.app.asset.set('A-100')

    def point(self, kind='ACV', pid=68):
        return next(q for q in self.b.points if q['kind'] == kind and q['id'] == pid)

    def model(self, pid=68, **kw):
        return PM.PointEditModel(self.app, pid, self.lock, store=self.env.store, **kw)

    def row(self, m, key, nth=0):
        return [r for r in m.rows if r.key == key][nth]

    def lock_dev(self):
        self.lock.lock()
        self.assertFalse(self.lock.unlocked)


class Rows(Base):
    def test_rows_are_in_send_order_with_this_points_values(self):
        m = self.model()
        self.assertEqual([r.wire for r in m.rows][:6], ['STBY', 'ROUT:TERM?', 'CONF:VOLT:AC 0.1', 'VOLT:AC:BAND 200', 'SYST:ERR?', 'OUT 0.1V,1000Hz'])
        self.assertEqual([r.seq for r in m.rows], list(range(1, len(m.rows) + 1)))
        self.assertIn('AC volts', m.title)

    def test_every_row_has_key_text_read_back_risk_and_verified_flag(self):
        m = self.model()
        r = self.row(m, 'conf.acv')
        self.assertEqual((r.template, r.factory_template), ('CONF:VOLT:AC {range:.9g}', 'CONF:VOLT:AC {range:.9g}'))
        self.assertEqual((r.label, r.risk, r.status_text, r.changed), ('34470A', 'normal', 'verified', False))
        self.assertEqual(r.placeholders, ['range'])
        unverified = [x for x in m.rows if x.status_text == 'UNVERIFIED']
        self.assertTrue(unverified)

    def test_normal_risk_commands_are_editable_locked_and_output_ones_say_why_not(self):
        m = self.model()
        self.assertTrue(self.row(m, 'conf.acv').editable)
        oper = self.row(m, 'oper.on')
        self.assertFalse(oper.editable)
        self.assertIn('output', oper.reason.lower())
        err = self.row(m, 'err.query')
        self.assertFalse(err.editable)
        self.assertIn('Locked', err.reason)

    def test_a_command_sent_twice_is_editable_once(self):
        m = self.model()
        a, b = [r for r in m.rows if r.key == 'oper.stby']
        self.assertIsNone(a.repeat_of)
        self.assertEqual(b.repeat_of, a.seq)
        self.assertIn(f'step {a.seq}', b.reason)

    def test_a_command_that_is_not_in_the_table_is_read_only(self):
        m = self.model()
        raw = [r for r in m.rows if r.key is None]
        for r in raw:
            self.assertFalse(r.editable)

    def test_test_command_is_not_offered_unless_the_engine_supplies_one(self):
        m = self.model()
        ok, text = m.test_info(1)
        self.assertFalse(ok)
        self.assertIn('Not tested', text)


class Gate(Base):
    def test_locked_developer_mode_shows_everything_and_edits_nothing(self):
        self.lock_dev()
        m = self.model()
        self.assertTrue(m.needs_unlock)
        self.assertFalse(m.editable)
        self.assertIn('developer mode', m.read_only_reason.lower())
        self.assertTrue(all(not r.editable for r in m.rows))
        self.assertTrue(all(not f.editable for f in m.fields.values()))
        self.assertTrue(m.stage_command(3, 'CONF:VOLT:AC {range:g}'))
        self.assertTrue(m.stage_field('error', '1'))
        self.assertTrue(m.add_extra('Keysight34470A', 'before', 'FOO?'))
        self.assertEqual(m.pm.drafts, {})

    def test_unlocking_with_the_existing_gate_makes_it_editable(self):
        self.lock_dev()
        self.assertTrue(self.lock.unlock('wrong wrong wrong').ok is False)
        self.assertTrue(self.lock.unlock(PASSPHRASE).ok)
        m = self.model()
        self.assertTrue(m.editable)
        self.assertTrue(self.row(m, 'conf.acv').editable)
        self.assertTrue(m.fields['error'].editable)

    def test_the_model_asks_the_lock_each_time_so_an_auto_lock_takes_effect(self):
        m = self.model()
        self.assertTrue(m.editable)
        self.lock.lock()
        self.assertFalse(m.editable)
        self.assertTrue(m.needs_unlock)

    def test_a_verified_locked_procedure_is_a_viewer_even_with_developer_mode_on(self):
        st = self.app.pm_state
        st._store().lock_reason = lambda model, key='': 'This procedure is verified on hardware and locked.'
        m = self.model()
        self.assertIn('verified', m.blocked_reason)
        self.assertFalse(m.editable)
        self.assertFalse(m.needs_unlock, 'unlocking developer mode would not help')
        ok, why = PM.menu_state(self.app, 68)
        self.assertFalse(ok)
        self.assertIn('verified', why)

    def test_the_point_being_measured_cannot_be_edited(self):
        st = self.app.pm_state
        self.app.busy = True
        st.live.cursor = (id([]), 0, 68)
        m = self.model()
        self.assertIn('being measured now', m.blocked_reason)
        self.assertFalse(m.editable)
        self.assertEqual(m.stage_command(3, 'CONF:VOLT:AC {range:g}')[0][:5], 'Point')
        ok, why = PM.menu_state(self.app, 68)
        self.assertFalse(ok)
        self.assertIn('being measured', why)
        other = self.model(pid=69) if self.app.pm_find_point(69) else None
        if other is not None:
            self.assertEqual(other.blocked_reason, '', 'any other point can be edited during a run')

    def test_menu_is_enabled_for_an_editable_point_and_disabled_for_a_row_that_is_not_a_point(self):
        self.assertEqual(PM.menu_state(self.app, 68), (True, ''))
        ok, why = PM.menu_state(self.app, 99999)
        self.assertFalse(ok)
        self.assertIn('not a test point', why)


class Commands(Base):
    def test_typed_command_is_checked_previewed_and_recorded_unverified(self):
        m = self.model()
        seq = self.row(m, 'conf.acv').seq
        self.assertTrue(m.stage_command(seq, 'CONF:VOLT:AC {range:g};*RST'))
        self.assertTrue(m.stage_command(seq, 'CONF:VOLT:AC 2'))
        self.assertEqual(m.pm.drafts, {})
        self.assertEqual(m.stage_command(seq, 'CONF:VOLT:AC {range:.3g}'), [])
        r = m.row(seq)
        self.assertEqual((r.staged, r.preview, r.changed), ('CONF:VOLT:AC {range:.3g}', 'CONF:VOLT:AC 0.1', True))
        self.assertTrue(any('UNVERIFIED' in w for w in m.warnings()))

    def test_locked_and_output_rows_refuse_a_typed_command(self):
        m = self.model()
        probs = m.stage_command(self.row(m, 'oper.on').seq, 'OPER')
        self.assertTrue(probs)
        self.assertEqual(m.pm.drafts, {})

    def test_restore_default_drops_a_staged_command(self):
        m = self.model()
        seq = self.row(m, 'conf.acv').seq
        m.stage_command(seq, 'CONF:VOLT:AC {range:.3g}')
        self.assertEqual(m.restore_command(seq), [])
        self.assertEqual(m.pm.drafts, {})
        self.assertFalse(m.row(seq).changed)

    def test_typing_the_factory_text_back_clears_the_staging(self):
        m = self.model()
        seq = self.row(m, 'conf.acv').seq
        m.stage_command(seq, 'CONF:VOLT:AC {range:.3g}')
        self.assertEqual(m.stage_command(seq, 'CONF:VOLT:AC {range:.9g}'), [])
        self.assertEqual(m.pm.drafts, {})

    def test_a_reason_is_required_and_the_scope_defaults_to_this_run_only(self):
        m = self.model()
        m.stage_command(self.row(m, 'conf.acv').seq, 'CONF:VOLT:AC {range:.3g}')
        self.assertEqual(m.scope, 'run')
        self.assertIn('Enter the reason for the change.', m.blockers())
        with self.assertRaises(pm.OverrideError):
            m.apply()
        m.set_reason('lab trial')
        self.assertEqual(m.blockers(), [])

    def test_apply_for_this_run_only_changes_the_plan_for_that_point_only_and_stores_nothing(self):
        m = self.model()
        seq = self.row(m, 'conf.acv').seq
        m.stage_command(seq, 'CONF:VOLT:AC {range:.3g}')
        m.set_reason('lab trial')
        res = m.apply()
        self.assertTrue(res.ok, res.errors)
        self.assertEqual(self.env.store.entries(), [], 'run scope is never written to the database')
        r = self.row(m, 'conf.acv')
        self.assertEqual((r.source, r.changed, r.template), ('this point', True, 'CONF:VOLT:AC {range:.3g}'))
        self.assertEqual(r.wire, 'CONF:VOLT:AC 0.1')
        other = self.model(pid=self.other_acv())
        self.assertFalse(any(x.changed for x in other.rows), 'a different point is unchanged')
        entry = self.app.pm_state.run_entries[0]
        self.assertEqual((entry['reason'], entry['scope']), ('lab trial', 'run'))
        self.assertTrue(entry['author'])
        self.assertIsNone(entry['tested'], 'recorded as not tested, i.e. UNVERIFIED')

    def other_acv(self):
        return next(q['id'] for q in self.b.points if q['kind'] == 'ACV' and q['id'] != 68)

    def test_saved_for_the_instrument_goes_to_the_store_with_who_and_why(self):
        m = self.model()
        m.set_scope('asset')
        m.stage_command(self.row(m, 'conf.acv').seq, 'CONF:VOLT:AC {range:.3g}')
        m.set_reason('customer request')
        with self.assertRaises(PM.M.NeedsConfirmation):
            m.apply()
        res = m.apply(confirmed=True)
        self.assertTrue(res.ok, res.errors)
        e = self.env.store.entries()[0]
        self.assertEqual((e['scope'], e['reason'], e['kind']), ('asset', 'customer request', 'command'))
        self.assertIn('@', e['target'])

    def test_restore_default_removes_a_saved_point_command_on_apply(self):
        m = self.model()
        m.set_scope('model')
        m.stage_command(self.row(m, 'conf.acv').seq, 'CONF:VOLT:AC {range:.3g}')
        m.set_reason('trial')
        m.apply(confirmed=True)
        m2 = self.model()
        m2.set_scope('model')
        r = self.row(m2, 'conf.acv')
        self.assertEqual(r.source, 'this point')
        m2.restore_command(r.seq)
        m2.set_reason('back to normal')
        self.assertTrue(m2.apply(confirmed=True).ok)
        m3 = self.model()
        self.assertEqual(self.row(m3, 'conf.acv').source, 'factory')
        self.assertFalse(self.row(m3, 'conf.acv').changed)


class ExtraLines(Base):
    def test_before_and_after_lines_are_staged_listed_where_they_will_be_sent_and_saved(self):
        m = self.model()
        self.assertEqual(m.add_extra('Keysight34470A', 'after', 'SENS:VOLT:AC:BAND 20', 'SENS:VOLT:AC:BAND?', '20'), [])
        self.assertEqual(m.add_extra('Fluke5560A', 'before', 'FOO?'), [])
        self.assertEqual((m.rows[0].wire, m.rows[0].pending), ('FOO?', True))
        self.assertEqual((m.rows[-1].wire, m.rows[-1].readback_wire), ('SENS:VOLT:AC:BAND 20', 'SENS:VOLT:AC:BAND?'))
        m.set_reason('trial')
        self.assertTrue(m.apply().ok)
        lines = [r for r in m.rows if r.extra]
        self.assertEqual([(r.extra['phase'], r.wire) for r in lines], [('before', 'FOO?'), ('after', 'SENS:VOLT:AC:BAND 20')])
        self.assertFalse(any(r.pending for r in m.rows))

    def test_a_write_without_read_back_a_forbidden_command_or_a_stranger_is_refused(self):
        m = self.model()
        self.assertTrue(m.add_extra('Keysight34470A', 'after', 'SENS:X 1'))
        self.assertTrue(m.add_extra('Keysight34470A', 'after', '*RST'))
        self.assertTrue(m.add_extra('Keysight34470A', 'sideways', 'FOO?'))
        self.assertTrue(m.add_extra('Keithley', 'after', 'FOO?'))
        self.assertEqual(m.pm.drafts, {})

    def test_at_most_three_lines_per_instrument_and_phase(self):
        m = self.model()
        for _ in range(3):
            self.assertEqual(m.add_extra('Keysight34470A', 'after', 'FOO?'), [])
        self.assertTrue(m.add_extra('Keysight34470A', 'after', 'FOO?'))

    def test_remove_a_staged_line_and_a_saved_one(self):
        m = self.model()
        m.add_extra('Keysight34470A', 'after', 'FOO?')
        self.assertEqual(m.remove_extra(m.rows[-1].seq), [])
        self.assertEqual(m.pm.drafts, {})
        m.add_extra('Keysight34470A', 'after', 'FOO?')
        m.set_reason('r')
        m.apply()
        saved = m.rows[-1]
        self.assertEqual(m.remove_extra(saved.seq), [])
        m.set_reason('remove it')
        self.assertTrue(m.apply().ok)
        self.assertFalse(any(r.extra for r in m.rows))


class DeveloperFields(Base):
    def test_fields_show_factory_and_effective_values_and_the_base_unit(self):
        m = self.model()
        self.assertEqual(set(m.fields), {'description', 'nominal', 'unit', 'error'})
        f = m.fields['nominal']
        self.assertEqual((f.factory, f.effective, f.unit, f.editable), ('0.1', '0.1', 'V', True))
        self.assertEqual(f.display, '100 mV', 'SI scaling is display only')
        self.assertEqual(f.text, '0.1')
        self.assertEqual(m.fields['error'].display, '70 µV')

    def test_parsing_is_decimal_safe_and_validated(self):
        for name, bad in (('nominal', 'abc'), ('nominal', 'nan'), ('nominal', '1,5'), ('error', '0'), ('error', '-1'), ('error', 'x'),
                          ('unit', 'mV'), ('unit', 'Hz'), ('unit', 'banana'), ('description', ''), ('description', 'x' * 300)):
            m = self.model()
            self.assertTrue(m.stage_field(name, bad), (name, bad))
            self.assertIsNone(m.limit_draft())
            self.assertTrue(m.blockers())
        m = self.model()
        self.assertEqual(m.stage_field('error', '0.1'), [])
        self.assertEqual(m.stage_field('nominal', '0.30'), [])
        self.assertEqual(m.limit_draft().value['nominal'], '0.30', 'the text typed is what is stored')

    def test_one_draft_carries_tolerance_nominal_unit_and_description_together(self):
        m = self.model()
        m.stage_field('error', '0.001')
        m.stage_field('unit', 'VAC')
        m.stage_field('description', 'AC volts, customer point')
        d = m.limit_draft()
        self.assertEqual((d.value['mode'], d.value['error'], d.value['new_unit'], d.value['description']), ('error', '0.001', 'VAC', 'AC volts, customer point'))
        self.assertEqual(sorted(d.value['fields']), ['description', 'unit'])
        self.assertTrue(m.judging_changes)
        self.assertTrue(m.needs_acknowledgement)
        self.assertIn(PM.TIP_LIMIT, m.warnings())

    def test_unit_and_description_alone_do_not_change_pass_fail(self):
        m = self.model()
        m.stage_field('unit', 'VAC')
        m.stage_field('description', 'renamed')
        self.assertFalse(m.judging_changes)
        self.assertFalse(m.needs_acknowledgement)
        self.assertNotIn(PM.TIP_LIMIT, m.warnings())

    def test_restore_default_returns_a_field_to_the_manufacturer_value(self):
        m = self.model()
        m.stage_field('error', '0.001')
        m.stage_field('description', 'renamed')
        m.restore_field('error')
        self.assertEqual(m.fields['error'].text, m.fields['error'].factory)
        self.assertEqual(list(m.limit_draft().value['fields']), ['description'])
        m.restore_field('description')
        self.assertIsNone(m.limit_draft())

    def test_saving_a_definition_patches_the_point_for_the_next_use_and_audits_it(self):
        m = self.model()
        m.set_scope('asset')
        m.stage_field('error', '0.001')
        m.stage_field('description', 'AC volts, customer point')
        m.acknowledge(True)
        m.set_reason('customer spec 7')
        self.assertEqual(m.blockers(), [])
        self.assertTrue(m.apply(confirmed=True).ok)
        e = [x for x in self.env.store.entries() if x['kind'] == 'limit'][0]
        self.assertEqual((e['reason'], e['scope']), ('customer spec 7', 'asset'))
        self.assertTrue(e['mac'], 'a limit change is HMAC-protected')
        self.assertEqual(e['value']['factory']['error'], 7e-05, 'the manufacturer value is recorded beside the new one')
        live = self.app.pm_find_point(68)
        self.assertEqual(live['error'], 0.001)
        self.assertEqual(live['description'], 'AC volts, customer point')
        self.assertTrue(live['limit_modified'])
        again = self.model()
        self.assertEqual(again.fields['error'].effective, '0.001')
        self.assertTrue(again.fields['error'].changed)
        self.assertEqual(again.fields['error'].factory, '0.00007')

    def test_acknowledgement_is_needed_before_a_limit_change_is_applied(self):
        m = self.model()
        m.stage_field('error', '0.001')
        m.set_reason('r')
        self.assertTrue(any('audit trail' in x for x in m.blockers()))
        m.acknowledge(True)
        self.assertEqual(m.blockers(), [])

    def test_a_bad_value_blocks_apply_and_names_the_field(self):
        m = self.model()
        m.stage_field('nominal', 'abc')
        m.set_reason('r')
        self.assertTrue(any('Nominal' in x for x in m.blockers()))

    def test_without_developer_mode_the_fields_are_read_only_with_a_reason(self):
        self.lock_dev()
        m = self.model()
        for f in m.fields.values():
            self.assertFalse(f.editable)
            self.assertTrue(f.reason)


class BandPoints(Base):
    build = staticmethod(PH.handheld)

    def test_handheld_limits_are_in_display_units_and_the_nominal_in_base_units(self):
        cap = next(q for q in self.b.points if q['kind'] == 'CAP' and q.get('applied'))
        m = self.model(pid=cap['id'])
        self.assertEqual(set(m.fields), {'description', 'nominal', 'unit', 'low', 'high'})
        self.assertEqual(m.fields['nominal'].effective, '0.0009')
        self.assertEqual((m.fields['low'].effective, m.fields['high'].effective), ('881', '919'))
        self.assertIn('µF', m.fields['low'].note)
        self.assertFalse(m.fields['unit'].editable)
        self.assertIn('scaling', m.fields['unit'].reason)

    def test_low_must_not_pass_nominal_or_high(self):
        cap = next(q for q in self.b.points if q['kind'] == 'CAP' and q.get('applied'))
        m = self.model(pid=cap['id'])
        m.stage_field('low', '950')
        self.assertTrue(any('low must be below high' in x or 'nominal' in x for x in m.field_problems), m.field_problems)
        m.stage_field('low', '881')
        m.stage_field('high', '880')
        self.assertTrue(m.field_problems)
        m.stage_field('high', '930')
        self.assertEqual(m.field_problems, [])
        self.assertEqual(m.limit_draft().value['high'], '930')

    def test_nominal_moves_the_calibrator_output_and_keeps_inside_the_limits(self):
        cap = next(q for q in self.b.points if q['kind'] == 'CAP' and q.get('applied'))
        m = self.model(pid=cap['id'])
        self.assertEqual(m.fields['nominal'].editable, True)
        m.stage_field('nominal', '0.0001')
        self.assertTrue(m.field_problems, 'outside the 881..919 uF limits')
        m.stage_field('nominal', '0.00091')
        self.assertEqual(m.field_problems, [])
        self.assertEqual(m.limit_draft().value['fields']['nominal'], ['nominal', 'applied.value'])

    def test_the_description_of_a_handheld_point_can_be_created(self):
        pt = next(q for q in self.b.points if q.get('applied'))
        m = self.model(pid=pt['id'])
        self.assertEqual(m.stage_field('description', 'Customer step 4'), [])
        self.assertEqual(m.limit_draft().value['fields']['description'], ['dsb_desc'])

    def test_points_with_no_output_have_no_commands_and_no_nominal(self):
        pt = next(q for q in self.b.points if not q.get('applied'))
        m = self.model(pid=pt['id'])
        self.assertEqual(m.rows, [])
        self.assertIn('no calibrator output', m.plan_note)
        self.assertFalse(m.fields['nominal'].editable)


class Redo(Base):
    def measured(self, pid=68):
        self.app.results[str(pid)] = {'result': 'PASS', 'reading': 0.1}

    def test_a_tolerance_change_on_a_point_with_a_reading_forces_a_redo(self):
        self.measured()
        m = self.model()
        m.stage_field('error', '0.001')
        m.acknowledge(True)
        m.set_reason('r')
        self.assertTrue(m.has_reading and m.redo_required and m.redo_will_happen)
        self.assertIn('measured again', m.effective_from_text())
        self.assertTrue(m.apply().ok)
        self.assertIn(68, self.app.pm_state.live.redo)

    def test_a_description_change_does_not_force_a_redo(self):
        self.measured()
        m = self.model()
        m.stage_field('description', 'renamed')
        m.set_reason('r')
        self.assertFalse(m.redo_required)
        self.assertTrue(m.apply().ok)
        self.assertNotIn(68, self.app.pm_state.live.redo)

    def test_a_command_change_on_a_measured_point_offers_a_redo_and_says_the_reading_stays(self):
        self.measured()
        m = self.model()
        m.stage_command(self.row(m, 'conf.acv').seq, 'CONF:VOLT:AC {range:.3g}')
        self.assertTrue(m.redo_optional)
        self.assertFalse(m.redo_will_happen)
        self.assertIn('only if the point is measured again', m.effective_from_text())
        m.set_redo(True)
        self.assertTrue(m.redo_will_happen)
        m.set_reason('r')
        self.assertTrue(m.apply().ok)
        self.assertIn(68, self.app.pm_state.live.redo)

    def test_a_procedure_that_cannot_redo_refuses_a_judging_change_on_a_measured_point(self):
        w = PH.wavesurfer()
        self.addCleanup(w.stop)
        w.app.dc_rows = [object()] * 3
        m = PM.PointEditModel(w.app, 'dcv:0', w.env.lock, store=w.env.store)
        self.assertTrue(m.has_reading)
        m.stage_field('low', str(float(m.fields['low'].effective) - 0.01))
        m.acknowledge(True)
        m.set_reason('r')
        self.assertTrue(m.redo_problem)
        self.assertTrue(any('cannot redo' in x for x in m.blockers()))


class Scope(Base):
    def test_demo_edits_are_this_run_only_and_marked(self):
        self.app.demo = True
        self.app.pm_state.demo = True
        m = self.model()
        self.assertTrue(m.demo)
        with self.assertRaises(ValueError):
            m.set_scope('asset')
        choices = {c[0]: c for c in m.scope_choices()}
        self.assertFalse(choices['asset'][2])
        self.assertFalse(choices['model'][2])
        m.stage_field('description', 'x')
        self.assertTrue(any('DEMO' in w for w in m.warnings()))

    def test_asset_scope_needs_the_instrument_id(self):
        self.app.asset.set('')
        self.app.pm_state.asset = ''
        m = self.model()
        self.assertFalse({c[0]: c for c in m.scope_choices()}['asset'][2])
        with self.assertRaises(ValueError):
            m.set_scope('asset')


class Audit(Base):
    def test_a_live_edit_event_names_the_point_the_reason_and_where_it_took_effect(self):
        m = self.model()
        m.stage_field('error', '0.001')
        m.acknowledge(True)
        m.set_reason('customer spec 7')
        m.set_scope('asset')
        self.app.asset.set('A-100')
        m = self.model()
        m.set_scope('asset')
        m.stage_field('error', '0.001')
        m.acknowledge(True)
        m.set_reason('customer spec 7')
        self.assertTrue(m.apply(confirmed=True).ok)
        st = self.app.pm_state
        self.assertFalse(st.live.dirty, 'not running: applied at once')
        ev = st.live.events[-1]
        c = ev['changes'][0]
        self.assertEqual((c['kind'], c['reason'], c['point_id'], c['scope']), ('limit', 'customer spec 7', 68, 'asset'))
        self.assertTrue(c['author'] and c['at'])
        self.assertIn('error=0.001', c['new'])
        self.assertIn('error=7e-05', c['old'])


if __name__ == '__main__':
    unittest.main()
