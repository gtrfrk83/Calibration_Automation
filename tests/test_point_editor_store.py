"""The storage layer of the per-point editor: commands and extra lines typed for ONE point, and the developer-mode point definition
(nominal, unit, description) beside the tolerance.  procmods + procmods_pointdef; no tkinter, no instrument."""
import copy
import json
import sqlite3
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import procmods as pm  # noqa: E402
import procmods_pointdef as pdef  # noqa: E402
import procmods_live as live  # noqa: E402
from tests import test_procmods as TP  # noqa: E402


class Decimals(unittest.TestCase):
    def test_parse_is_strict_and_decimal(self):
        self.assertEqual(pdef.parse_decimal('0.1'), Decimal('0.1'))
        self.assertEqual(pdef.parse_decimal(' 1e-3 '), Decimal('0.001'))
        for bad in ('', 'abc', 'nan', 'inf', '-inf', '1,5', '5 V', '1.2.3', None, True, float('nan'), float('inf')):
            self.assertIsNone(pdef.parse_decimal(bad), repr(bad))

    def test_decimal_equality_has_no_binary_float_surprises(self):
        self.assertFalse(0.1 + 0.2 == 0.3)
        self.assertTrue(pdef.same_decimal('0.30', '0.3'))
        self.assertTrue(pdef.same_decimal(Decimal('0.1') + Decimal('0.2'), '0.3'))
        self.assertEqual(pdef.dec_text('5.000'), '5')
        self.assertEqual(pdef.dec_text('1E+3'), '1000')
        self.assertEqual(pdef.dec_text('-0.0'), '0')

    def test_units_are_base_units_of_the_same_kind(self):
        self.assertEqual(pdef.check_unit('V', 'VDC'), [])
        self.assertEqual(pdef.check_unit('ohm', 'OHM'), [])
        self.assertIn('base unit', ' '.join(pdef.check_unit('V', 'mV')))                 # display scaling is display only
        self.assertTrue(pdef.check_unit('V', 'Hz'))                                      # another dimension
        self.assertTrue(pdef.check_unit('V', 'furlong'))
        self.assertTrue(pdef.check_unit('V', 5))

    def test_command_targets_round_trip(self):
        t = pdef.point_command_target('Drv', 'conf', 'k|1')
        self.assertEqual(pdef.parse_command_target(t), {'driver': 'Drv', 'key': 'conf', 'point': 'k|1', 'extra': None})
        t = pdef.extra_command_target('Drv', 'after', 2, 'k|1')
        self.assertEqual(pdef.parse_command_target(t)['extra'], ('after', 2))
        self.assertIsNone(pdef.parse_command_target('Drv:conf')['point'])


class PerPointCommands(TP.Base):
    def key(self, i=3):
        return pm.point_key(self.points[i])

    def test_a_command_for_one_point_is_validated_like_a_driver_wide_one(self):
        tgt = pdef.point_command_target('ScpiDmm', 'nplc', self.key())
        e = self.store.add('command', tgt, {'template': 'VOLT:DC:NPLC {nplc:g}2'}, 'model', 'slow', model='M', cmd=TP.NPLC, driver_name='ScpiDmm',
                           session=self.session)
        self.assertEqual(e['target'], tgt)
        for bad in ('VOLT:DC:NPLC 2', 'VOLT:DC:NPLC {nplc:g};*RST', 'VOLT:DC:NPLC {nplc:g}', 'VOLT:DC:NPLC {zz}'):
            with self.assertRaises(pm.OverrideError, msg=bad):
                self.store.add('command', pdef.point_command_target('ScpiDmm', 'nplc', self.key(4)), {'template': bad}, 'model', 'r', model='M',
                               cmd=TP.NPLC, driver_name='ScpiDmm', session=self.session)

    def test_output_and_locked_commands_cannot_be_overridden_for_a_point(self):
        with self.assertRaises(pm.OverrideError):
            self.store.add('command', pdef.point_command_target('ScpiDmm', 'oper', self.key()), {'template': 'OPER ON'}, 'model', 'r', model='M',
                           cmd=TP.OPER, driver_name='ScpiDmm', session=self.session)

    def test_it_needs_an_unlocked_developer_session(self):
        with self.assertRaises(pm.OverrideError):
            self.store.add('command', pdef.point_command_target('ScpiDmm', 'nplc', self.key()), {'template': 'VOLT:DC:NPLC {nplc:g}2'}, 'model', 'r',
                           model='M', cmd=TP.NPLC, driver_name='ScpiDmm', session=None)

    def test_resolution_keeps_point_commands_apart_from_driver_wide_ones(self):
        k = self.key()
        self.store.add('command', pdef.point_command_target('ScpiDmm', 'nplc', k), {'template': 'VOLT:DC:NPLC {nplc:g}2'}, 'model', 'r', model='M',
                       cmd=TP.NPLC, driver_name='ScpiDmm', session=self.session)
        o = pm.resolve('M', None, store=self.store)
        self.assertEqual(o.commands_for('ScpiDmm', TP.REG), {}, 'the driver-wide table is untouched')
        tpls, uids, rejected = o.point_commands_for('ScpiDmm', TP.REG)
        self.assertEqual(tpls, {k: {'nplc': 'VOLT:DC:NPLC {nplc:g}2'}})
        self.assertEqual(list(uids[k]), ['nplc'])
        self.assertEqual(rejected, [])

    def test_a_factory_change_makes_it_stale_and_it_is_not_applied(self):
        k = self.key()
        self.store.add('command', pdef.point_command_target('ScpiDmm', 'nplc', k), {'template': 'VOLT:DC:NPLC {nplc:g}2'}, 'model', 'r', model='M',
                       cmd=TP.NPLC, driver_name='ScpiDmm', session=self.session)
        changed = dict(TP.REG, nplc=TP.Cmd('VOLT:DC:NPLC {nplc:g} 1', 'Set NPLC', placeholders=TP.NPLC.placeholders, kind='set', readback='nplc?'))
        tpls, _u, rejected = pm.resolve('M', None, store=self.store).point_commands_for('ScpiDmm', changed)
        self.assertEqual(tpls, {})
        self.assertTrue(rejected and 'stale' in rejected[0][1][0])

    def test_import_refuses_commands_typed_for_one_point(self):
        k = self.key()
        self.store.add('command', pdef.point_command_target('ScpiDmm', 'nplc', k), {'template': 'VOLT:DC:NPLC {nplc:g}2'}, 'model', 'r', model='M',
                       cmd=TP.NPLC, driver_name='ScpiDmm', session=self.session)
        payload, _ = pm.export_entries(self.store, session=self.session)
        prev = pm.import_preview(self.store, payload, registries={'ScpiDmm': TP.REG})
        self.assertTrue(any('one point' in p for it in prev['items'] for p in it['problems']))


class ExtraLines(TP.Base):
    def tgt(self, phase='before', n=1, i=3):
        return pdef.extra_command_target('ScpiDmm', phase, n, pm.point_key(self.points[i]))

    def add(self, value, **kw):
        kw.setdefault('session', self.session)
        return self.store.add('command', kw.pop('target', None) or self.tgt(), value, 'model', 'trial', model='M', driver_name='ScpiDmm', **kw)

    def test_a_write_needs_its_read_back_and_expected_reply(self):
        e = self.add({'template': 'SENS:VOLT:DC:NPLC 2', 'readback': 'SENS:VOLT:DC:NPLC?', 'expect': '2'})
        self.assertTrue(e['value']['extra'])
        self.assertEqual(e['value']['phase'], 'before')
        for bad in ({'template': 'SENS:VOLT:DC:NPLC 2'},
                    {'template': 'SENS:VOLT:DC:NPLC 2', 'readback': 'SENS:VOLT:DC:NPLC?'},
                    {'template': 'SENS:VOLT:DC:NPLC 2', 'readback': 'SENS:VOLT:DC:NPLC', 'expect': '2'},
                    {'template': '', 'readback': 'X?', 'expect': '1'}):
            with self.assertRaises(pm.OverrideError, msg=str(bad)):
                self.add(bad, target=self.tgt(n=2))

    def test_a_query_takes_neither(self):
        self.add({'template': 'SENS:VOLT:DC:NPLC?'}, target=self.tgt('after'))
        with self.assertRaises(pm.OverrideError):
            self.add({'template': 'SENS:VOLT:DC:NPLC?', 'readback': 'X?', 'expect': '1'}, target=self.tgt('after', 2))

    def test_dangerous_and_plumbing_commands_are_refused(self):
        for bad in ('*RST', '*CLS', 'SYST:ERR?', 'ERR?', 'CAL:STOR', 'OUTP ON', 'VOLT 1;VOLT 2', 'VOLT {x}', 'CAL:SEC:STAT OFF', 'SYST:SEC:IMM'):
            with self.assertRaises(pm.OverrideError, msg=bad):
                self.add({'template': bad, 'readback': 'VOLT?', 'expect': '1'}, target=self.tgt(n=3))
        with self.assertRaises(pm.OverrideError):
            self.add({'template': 'VOLT 1', 'readback': 'SYST:ERR?', 'expect': '1'}, target=self.tgt(n=3))

    def test_at_most_three_lines_per_point_driver_and_phase(self):
        with self.assertRaises(pm.OverrideError):
            self.add({'template': 'A?'}, target=self.tgt(n=4))

    def test_extras_for_orders_before_then_after_and_belongs_to_its_point(self):
        self.add({'template': 'B1?'}, target=self.tgt('before', 1))
        self.add({'template': 'A1?'}, target=self.tgt('after', 1))
        self.add({'template': 'B2?'}, target=self.tgt('before', 2))
        self.add({'template': 'OTHER?'}, target=self.tgt('before', 1, i=4))
        out = pm.resolve('M', None, store=self.store).extras_for('ScpiDmm')
        k = pm.point_key(self.points[3])
        self.assertEqual([(x['phase'], x['n'], x['template']) for x in out[k]], [('before', 1, 'B1?'), ('before', 2, 'B2?'), ('after', 1, 'A1?')])
        self.assertEqual(len(out), 2)

    def test_extras_are_recorded_unverified_and_summarised_for_the_report(self):
        self.add({'template': 'SENS:X 1', 'readback': 'SENS:X?', 'expect': '1'})
        o = pm.resolve('M', None, store=self.store)
        s = pm.modifications_summary(o)
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]['unverified'])
        self.assertIn('SENS:X 1', s[0]['text'])
        self.assertFalse(s[0]['tolerances_modified'])


class PointDefinition(TP.Base):
    def point(self):
        return self.points[3]

    def add(self, value, p=None, **kw):
        p = p or self.point()
        return self.store.add('limit', pm.point_key(p), value, kw.pop('scope', 'model'), 'customer spec', model='M', point=p,
                              session=kw.pop('session', self.session), **kw)

    def value(self, **extra):
        p = self.point()
        v = {'mode': 'error', 'error': p['error'], 'fields': {}}
        v.update(extra)
        return v

    def test_description_unit_and_nominal_are_patched_and_the_limit_guard_still_holds(self):
        p = self.point()
        v = self.value(nominal='0.0005', new_unit='ADC', description='DC current, 1 mA range (customer point)',
                       fields={'nominal': ['nominal'], 'unit': ['unit'], 'description': ['description']})
        self.add(v)
        o = pm.resolve('M', None, store=self.store)
        out = pm.apply_points(self.points, o)
        self.assertEqual(out[3]['nominal'], 0.0005)
        self.assertEqual(out[3]['unit'], 'ADC')
        self.assertEqual(out[3]['description'], 'DC current, 1 mA range (customer point)')
        self.assertEqual(out[3]['limit_fields'], ['description', 'nominal', 'unit'])
        self.assertEqual(out[3]['error'], p['error'], 'the tolerance was not touched')
        self.assertEqual(self.points[3]['nominal'], p['nominal'], 'the factory list is not modified in place')
        self.assertEqual([q['nominal'] for i, q in enumerate(out) if i != 3], [q['nominal'] for i, q in enumerate(self.points) if i != 3])

    def test_a_definition_change_alone_is_not_a_tolerance_change(self):
        self.add(self.value(description='Renamed', fields={'description': ['description']}))
        o = pm.resolve('M', None, store=self.store)
        self.assertFalse(pm.tolerances_modified(o))
        s = pm.modifications_summary(o)[0]
        self.assertIn('Renamed', s['text'])
        self.assertFalse(s.get('tolerances_modified'))

    def test_a_nominal_change_is_judging(self):
        self.add(self.value(nominal='0.0007', fields={'nominal': ['nominal']}))
        self.assertTrue(pm.tolerances_modified(pm.resolve('M', None, store=self.store)))

    def test_bad_values_are_refused_with_a_reason(self):
        f = {'nominal': ['nominal'], 'unit': ['unit'], 'description': ['description']}
        cases = [self.value(nominal='abc', fields=f), self.value(nominal='nan', fields=f), self.value(new_unit='mV', fields=f),
                 self.value(new_unit='Hz', fields=f), self.value(new_unit='ohm', fields=f), self.value(description='   ', fields=f),
                 self.value(description='x' * 500, fields=f), self.value(description='a\nb', fields=f),
                 self.value(nominal='1', fields={'nominal': ['limits']}), self.value(nominal='1', fields={}), self.value(nominal='1')]
        for v in cases:
            with self.assertRaises(pm.OverrideError, msg=str(v)):
                self.add(v)
        self.assertEqual(self.store.entries(), [])

    def test_nothing_to_override_is_refused(self):
        with self.assertRaises(pm.OverrideError):
            self.add(self.value())

    def test_band_points_keep_low_le_nominal_le_high_decimal_safe(self):
        steps = json.loads((ROOT / 'specs' / 'fluke_80_series_v_pv.json').read_text(encoding='utf-8'))['steps']
        p = next(s for s in steps if s.get('low') is not None and s.get('nominal') is not None and s['nominal'] != 0)
        self.assertEqual(pm.check_limit_value(p, {'mode': 'band', 'low': p['low'], 'high': p['high']}), [])
        nom_disp = Decimal(str(p['nominal'])) / Decimal(str(p['factor']))
        hi = Decimal(str(p['high']))
        too_far = pdef.dec_text(hi + abs(nom_disp) + 1)
        probs = pm.check_limit_value(p, {'mode': 'band', 'low': p['low'], 'high': p['high'], 'nominal': str(float(too_far) * float(p['factor']))})
        self.assertTrue(any('nominal' in x for x in probs), probs)
        self.assertTrue(pm.check_limit_value(p, {'mode': 'band', 'low': p['high'], 'high': p['low']}))
        self.assertTrue(pm.check_limit_value(p, {'mode': 'band', 'low': 'x', 'high': p['high']}))

    def test_decimal_text_is_what_is_stored(self):
        e = self.add(self.value(nominal='0.30', fields={'nominal': ['nominal']}))
        self.assertEqual(e['value']['nominal'], '0.30')
        out = pm.apply_points(self.points, pm.resolve('M', None, store=self.store))
        self.assertEqual(out[3]['nominal'], 0.3)

    def test_tampering_with_a_definition_makes_it_not_apply(self):
        e = self.add(self.value(description='Renamed', fields={'description': ['description']}))
        con = sqlite3.connect(self.db)
        con.execute('DROP TRIGGER override_append_only')
        con.execute('UPDATE override SET value_json=? WHERE uid=?', (json.dumps({**e['value'], 'description': 'Something else'}), e['uid']))
        con.commit()
        con.close()
        o = pm.resolve('M', None, store=self.store)
        self.assertEqual([x['status'] for x in o.entries()], ['tampered'])
        self.assertNotEqual(pm.apply_points(self.points, o)[3].get('description'), 'Something else')
        self.assertEqual(pm.apply_points(self.points, o)[3]['description'], self.points[3]['description'])

    def test_a_changed_spec_makes_the_definition_stale(self):
        self.add(self.value(nominal='0.0005', fields={'nominal': ['nominal']}))
        o = pm.resolve('M', None, store=self.store)
        other = copy.deepcopy(self.points)
        other[3]['error'] = other[3]['error'] * 3
        self.assertEqual(pm.apply_points(other, o)[3]['nominal'], other[3]['nominal'])

    def test_run_scope_is_in_memory_only_and_verified(self):
        v = self.value(description='Renamed', fields={'description': ['description']})
        run = pm.make_run_entry('limit', pm.point_key(self.point()), v, 'try', point=self.point(), session=self.session)
        o = pm.resolve('M', None, run_overrides=[run], store=self.store)
        self.assertEqual(pm.apply_points(self.points, o)[3]['description'], 'Renamed')
        self.assertEqual(self.store.entries(), [])
        bad = copy.deepcopy(run)
        bad['value']['description'] = 'forged'
        self.assertEqual(pm.apply_points(self.points, pm.resolve('M', None, run_overrides=[bad], store=self.store))[3]['description'],
                         self.points[3]['description'])

    def test_definition_cannot_be_imported(self):
        self.add(self.value(description='Renamed', fields={'description': ['description']}))
        payload, _ = pm.export_entries(self.store, session=self.session)
        prev = pm.import_preview(self.store, payload)
        self.assertTrue(any('not imported' in p for it in prev['items'] for p in it['problems']))


class AuditTrail(TP.Base):
    def test_a_live_event_names_who_when_old_new_reason_and_the_point(self):
        p = self.points[3]
        k = pm.point_key(p)
        old = pm.resolve('M', None, store=self.store)
        self.store.add('limit', k, {'mode': 'error', 'error': p['error'] * 2, 'description': 'Renamed', 'fields': {'description': ['description']}},
                       'model', 'customer spec', model='M', point=p, session=self.session, author='mike')
        new = pm.resolve('M', None, store=self.store)
        ev = live.make_event(old, new, rev=2, before={'id': 7, 'desc': 'next'}, point_id=lambda key: 4 if key == k else None, redo=[4])
        c = ev['changes'][0]
        self.assertEqual((c['author'], c['reason'], c['point_key'], c['point_id']), ('mike', 'customer spec', k, 4))
        self.assertIn('description=Renamed', c['new'])
        self.assertTrue(c['at'])
        self.assertEqual(ev['before_point'], 7)
        self.assertEqual(ev['redo'], [4])
        line = live.event_line(ev)
        self.assertIn('[point 4]', line)
        self.assertIn('redo of point(s) 4', line)

    def test_extra_lines_show_their_read_back_in_the_audit_text(self):
        k = pm.point_key(self.points[3])
        old = pm.resolve('M', None, store=self.store)
        self.store.add('command', pdef.extra_command_target('ScpiDmm', 'before', 1, k), {'template': 'SENS:X 1', 'readback': 'SENS:X?', 'expect': '1'},
                       'model', 'trial', model='M', driver_name='ScpiDmm', session=self.session)
        ev = live.make_event(old, pm.resolve('M', None, store=self.store), point_id=lambda key: 4)
        self.assertIn('read back with SENS:X?', ev['changes'][0]['new'])
        self.assertEqual(ev['changes'][0]['point_id'], 4)


if __name__ == '__main__':
    unittest.main()
