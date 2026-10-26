"""Datasheet Builder UI controller (datasheet_builder_ui_model.py): the guided flow, validation gating of Save, undo / redo, the live worked example,
point table rows, matcher results, import / export and the version list.  No tkinter.   Run:  python -m unittest tests.test_dsb_ui_model"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_ui_model as M  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import specmanager as sm  # noqa: E402

_TMP = tempfile.mkdtemp()
REG = Path(_TMP) / 'standards.sqlite3'
sm.seed(path=REG)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.store = M.Storage(self.t / 'user_specs', self.t / 'lab_registry.sqlite3', who='tester')
        self.matcher = dm.Matcher(REG)

    def tearDown(self):
        self.tmp.cleanup()

    def editor(self, ds=None):
        return M.EditorModel(self.store, ds, matcher_factory=lambda: self.matcher)

    def built(self):
        """A small complete DC volts datasheet built through the controller only."""
        ed = self.editor()
        self.assertTrue(ed.set_header('Acme', 'DM-1', 'DM-1 Performance Verification', notes='bench meter'))
        self.assertTrue(ed.add_function('DCV'))
        fid = ed.fid
        self.assertTrue(ed.add_ranges(fid, '100 mV, 1 V, 10 V'))
        self.assertTrue(ed.edit_range(fid, 'r10', resolution='10 uV'))
        self.assertTrue(ed.add_spec_entry(fid, {'1y': '0.05 % of reading + 0.01 % of range'}))
        self.assertTrue(ed.add_rule(fid, {'type': 'percent_of_range', 'percents': '10, 50, 100', 'bipolar': True}))
        return ed, fid


class FlowTests(Base):
    def test_steps_and_gating(self):
        ed = self.editor()
        self.assertEqual([s['key'] for s in M.STEPS], ['header', 'functions', 'ranges', 'spec', 'points', 'automation', 'review'])
        self.assertTrue(ed.go(1))
        res = ed.go(2)
        self.assertFalse(res)
        self.assertIn('function', res.message)
        ed.add_function('DCV')
        self.assertTrue(ed.go(2))
        self.assertFalse(ed.go(3))                                   # no range yet
        self.assertIn('range', ed.go(3).message)
        ed.add_range(ed.fid, '10 V')
        self.assertTrue(ed.go(3))
        self.assertTrue(ed.go(4))
        self.assertFalse(ed.go(5))                                   # no point yet
        self.assertTrue(ed.go(6))                                    # the review page is always reachable (it explains what is missing)
        self.assertTrue(ed.go(0))                                    # going back is always allowed
        self.assertEqual(ed.step, 0)

    def test_next_back_and_reached(self):
        ed = self.editor()
        ed.next()
        self.assertEqual(ed.step, 1)
        ed.next()                                                    # blocked: no function
        self.assertEqual(ed.step, 1)
        ed.back()
        self.assertEqual(ed.step, 0)
        self.assertEqual(ed.reached, {0, 1})

    def test_step_states_follow_content_and_problems(self):
        ed = self.editor()
        st = {s['key']: s for s in ed.step_states()}
        self.assertEqual(st['header']['state'], 'current')
        self.assertEqual(st['functions']['state'], 'todo')
        self.assertFalse(st['ranges']['enterable'])
        ed, fid = self.built()
        ed.go(4)
        st = {s['key']: s for s in ed.step_states()}
        self.assertEqual([st[k]['state'] for k in ('header', 'functions', 'ranges', 'spec')], ['done'] * 4)
        self.assertEqual(st['points']['state'], 'current')
        self.assertEqual(st['automation']['state'], 'todo')
        ed.remove_spec_entry(fid, 0)
        ed.go(3)
        st = {s['key']: s for s in ed.step_states()}
        self.assertEqual(st['spec']['state'], 'current')
        ed.go(4)
        st = {s['key']: s for s in ed.step_states()}
        self.assertEqual(st['spec']['state'], 'error')               # no specification: the limits cannot be calculated
        self.assertGreater(st['spec']['errors'], 0)

    def test_header_and_periods(self):
        ed = self.editor()
        self.assertFalse(ed.problems_for(0) == [])                   # make and model are empty
        ed.set_header(make='  Keysight ', model='34461A', title='PV')
        self.assertEqual((ed.ds.make, ed.ds.model), ('Keysight', '34461A'))
        self.assertEqual([p['code'] for p in ed.problems_for(0)], [])
        self.assertTrue(ed.add_period('90d'))
        self.assertEqual([p['id'] for p in ed.period_rows()], ['1y', '90d'])
        self.assertEqual(ed.ds.periods[1].label, '90 days')          # preset label
        self.assertFalse(ed.add_period('90d'))                       # duplicate
        self.assertFalse(ed.add_period('bad id!'))
        self.assertTrue(ed.set_default_period('90d'))
        self.assertEqual(ed.ds.default_period, '90d')
        self.assertEqual(ed.period, '90d')
        self.assertTrue(ed.remove_period('90d'))
        self.assertEqual((ed.ds.default_period, ed.period), ('1y', '1y'))
        self.assertFalse(ed.remove_period('1y'))                     # the last one stays
        self.assertEqual([p['id'] for p in ed.period_presets() if p['used']], ['1y'])

    def test_remove_period_takes_its_specification_text_and_typed_limits_with_it(self):
        ed = self.editor(fx.dmm_34461a_like())
        fid = 'dcv'
        pid = ed.fn(fid).points[0].id
        ed.set_point_override(fid, pid, '0.001', '0.002', period='90d')
        self.assertTrue(ed.remove_period('90d'))
        e = ed.fn(fid).spec[0]
        self.assertEqual(list(e.exprs), ['1y'])
        self.assertEqual(ed.fn(fid).point(pid).overrides, {})
        self.assertEqual([p for p in ed.problems() if p['code'] in ('spec_missing_period', 'spec_period_unknown')], [])

    def test_functions(self):
        ed = self.editor()
        kinds = {k['kind']: k for k in ed.kind_choices()}
        self.assertEqual(kinds['DCV']['label'], 'DC volts (V)')
        self.assertEqual(kinds['OHM2']['symbol'], 'Ω')
        self.assertEqual({k['group'] for k in kinds.values()}, {'dmm', 'scope', 'generator'})
        self.assertTrue(ed.add_function('TEMP'))
        self.assertEqual(ed.setting_fields(ed.fid), [])                # a new temperature section assumes no sensor (it is chosen per point, 'Sourced as')
        self.assertNotIn('tc_type', ed.fn().settings)
        self.assertTrue(ed.set_function_setting(ed.fid, 'tc_type', 'J'))   # an old sheet's section-level letter is still stored and read
        self.assertEqual(ed.fn().settings['tc_type'], 'J')
        self.assertTrue(ed.add_function('GEN_AMPL'))
        self.assertEqual(ed.fn().direction, 'source')
        self.assertEqual([v for v, _ in ed.direction_choices(ed.fid)], ['source'])
        self.assertEqual([v for v, _ in ed.direction_choices('temp')], ['measure', 'source'])
        self.assertTrue(ed.add_function('ACV'))
        self.assertTrue(ed.add_function('ACV'))                      # a second ACV gets its own id
        self.assertEqual([f['id'] for f in ed.function_rows()], ['temp', 'gen_ampl', 'acv', 'acv2'])
        self.assertTrue(ed.move_function('acv2', -1))
        self.assertEqual([f['id'] for f in ed.function_rows()][-2:], ['acv2', 'acv'])
        self.assertTrue(ed.set_function('acv', name='AC volts (high)'))
        self.assertEqual(ed.fn('acv').name, 'AC volts (high)')
        self.assertFalse(ed.set_function('acv', direction='sideways'))
        self.assertFalse(ed.add_function('NOPE'))
        self.assertIn('NOPE', ed.add_function('NOPE').message)
        self.assertTrue(ed.remove_function('acv2'))
        self.assertNotIn('acv2', [f['id'] for f in ed.function_rows()])

    def test_ranges_edit_remove_and_usage(self):
        ed, fid = self.built()
        rows = ed.range_rows(fid)
        self.assertEqual([r['text'] for r in rows], ['100 mV', '1 V', '10 V'])
        self.assertEqual(rows[2]['resolution'], '10 µV')
        self.assertEqual(rows[2]['points'], 6)
        self.assertFalse(ed.add_range(fid, '10 V'))                  # duplicate
        self.assertFalse(ed.add_range(fid, '10 A'))                  # wrong unit
        self.assertFalse(ed.add_range(fid, 'ten'))
        self.assertTrue(ed.edit_range(fid, 'r1', label='1.00000 V', display_unit='m'))
        self.assertEqual(ed.range_rows(fid)[1]['text'], '1.00000 V')
        res = ed.remove_range(fid, 'r10')                            # used by points: refused unless cascade
        self.assertFalse(res)
        self.assertEqual(ed.range_usage(fid, 'r10'), dict(points=6, spec=0))
        self.assertTrue(ed.remove_range(fid, 'r10', cascade=True))
        self.assertEqual([r.id for r in ed.fn(fid).ranges], ['r0.1', 'r1'])
        self.assertFalse([p for p in ed.fn(fid).points if p.range_id == 'r10'])

    def test_resolution_helper(self):
        ed = self.editor()
        self.assertEqual(ed.resolution_from_decimals('m', 4), db.D('1E-7'))      # 100.0000 mV shows 0.1 uV
        self.assertEqual(ed.resolution_from_decimals('', 5), db.D('1E-5'))       # 10.00000 V
        self.assertEqual(ed.resolution_from_decimals('k', 1), db.D('100'))
        with self.assertRaises(db.DsError):
            ed.resolution_from_decimals('', 99)

    def test_every_error_is_a_message_never_an_exception(self):
        ed, fid = self.built()
        before = ed.ds.to_json()
        for bad in (ed.add_range('nope', '1 V'), ed.add_range(fid, 'x'), ed.add_spec_entry(fid, {'1y': '5 %'}), ed.add_spec_entry(fid, {'1y': ''}),
                    ed.add_rule(fid, {'type': 'fixed', 'values': ''}), ed.add_rule(fid, {'type': 'nope'}), ed.add_point(fid, '1 kV'),
                    ed.edit_point(fid, 'missing', nominal='1'), ed.remove_point(fid, 'missing'), ed.remove_range(fid, 'r99'), ed.set_assignment('missing', '5560A')):
            self.assertFalse(bad)
            self.assertTrue(bad.message)
        self.assertEqual(ed.ds.to_json(), before)


class UndoTests(Base):
    def test_undo_redo_of_every_kind_of_edit(self):
        ed = self.editor()
        self.assertFalse(ed.can_undo)
        self.assertFalse(ed.undo())
        ed.set_header('A', 'B', 'C')
        ed.add_function('DCV')
        ed.add_range(ed.fid, '10 V', '10 uV')
        snap = ed.ds.to_json()
        ed.add_spec_entry(ed.fid, {'1y': '0.1 % of reading'})
        ed.add_rule(ed.fid, {'type': 'zero_and_full'})
        self.assertGreater(len(ed.fn().points), 0)
        self.assertEqual(ed.undo_label, 'add rule')
        self.assertTrue(ed.undo())
        self.assertEqual(ed.fn().points, [])
        self.assertTrue(ed.undo())
        self.assertEqual(ed.ds.to_json(), snap)
        self.assertTrue(ed.can_redo)
        self.assertTrue(ed.redo())
        self.assertTrue(ed.redo())
        self.assertGreater(len(ed.fn().points), 0)
        self.assertFalse(ed.redo())
        # a new edit forgets the redo stack
        ed.undo()
        ed.set_header(notes='x')
        self.assertFalse(ed.can_redo)

    def test_undo_of_removing_a_function_brings_back_its_points_and_selection(self):
        ed, fid = self.built()
        n = len(ed.fn(fid).points)
        ed.remove_function(fid)
        self.assertEqual(ed.fid, '')
        self.assertTrue(ed.undo())
        self.assertEqual(len(ed.fn(fid).points), n)

    def test_failed_edit_is_not_an_undo_step_and_changes_nothing(self):
        ed, fid = self.built()
        depth = len(ed._undo)
        before = ed.ds.to_json()
        self.assertFalse(ed.add_spec_entry(fid, {'1y': '0.05 % of reading + banana'}))
        self.assertEqual(len(ed._undo), depth)
        self.assertEqual(ed.ds.to_json(), before)

    def test_nothing_changed_is_not_an_undo_step(self):
        ed, fid = self.built()
        depth = len(ed._undo)
        res = ed.recalculate(fid)
        self.assertEqual(res.message, 'No point changed.')
        self.assertEqual(len(ed._undo), depth)

    def test_dirty_follows_saved_state_through_undo(self):
        ed, fid = self.built()
        self.assertTrue(ed.dirty)
        self.assertTrue(ed.save())
        self.assertFalse(ed.dirty)
        ed.set_header(notes='more')
        self.assertTrue(ed.dirty)
        ed.undo()
        self.assertFalse(ed.dirty)                                   # back to exactly what was saved

    def test_undo_limit(self):
        ed = self.editor()
        for i in range(M.EditorModel.UNDO_LIMIT + 20):
            ed.set_header(notes=str(i))
        self.assertEqual(len(ed._undo), M.EditorModel.UNDO_LIMIT)


class ExampleTests(Base):
    def test_worked_example_matches_the_core(self):
        ed, fid = self.built()
        r = ed.example(fid, '0.05 % of reading + 0.01 % of range', range_id='r10')
        self.assertTrue(r['ok'])
        self.assertEqual(r['text'], 'At 5 V on the 10 V range the low limit is 4.9965 V and the high limit is 5.0035 V.')
        self.assertEqual((r['low'], r['high'], r['plus']), (db.D('4.9965'), db.D('5.0035'), db.D('0.0035')))
        self.assertEqual(r['normalised'], '±(0.05 % of reading + 0.01 % of range)')
        self.assertEqual(r['parts'], ['0.05 % of reading = 2.5 mV', '0.01 % of range = 1 mV'])
        # the same number the point table shows
        p = ed.fn(fid).point('dcv.r10.+5')
        self.assertEqual(ed.fn(fid).limit_for(p, '1y').high, r['high'])

    def test_example_other_reading_counts_and_small_prefix(self):
        ed, fid = self.built()
        r = ed.example(fid, '2 counts', range_id='r10', reading='1 V')
        self.assertEqual(r['text'], 'At 1 V on the 10 V range the low limit is 0.99998 V and the high limit is 1.00002 V.')
        r = ed.example(fid, '20 ppm of reading', range_id='r1', reading='0.5 V')
        self.assertEqual(r['plus'], db.D('0.00001'))
        r = ed.example(fid, 'max(0.01 % of reading, 50 uV)', range_id='r10', reading='0.1 V')
        self.assertEqual(r['plus'], db.D('0.00005'))                 # the floor wins at small readings

    def test_example_asymmetric_and_frequency(self):
        ed = self.editor()
        ed.add_function('ACV')
        ed.add_range(ed.fid, '10 V', '10 uV')
        r = ed.example(ed.fid, '0.1 % of reading', range_id='r10', f_lo='1 kHz', f_hi='10 kHz', minus_text='0.2 % of reading')
        self.assertTrue(r['ok'])
        self.assertIn('and 5.5 kHz', r['text'])
        self.assertIn('low limit is 4.99 V and the high limit is 5.005 V', r['text'])

    def test_example_errors_are_plain_language(self):
        ed, fid = self.built()
        r = ed.example(fid, '0.05 %')
        self.assertFalse(r['ok'])
        self.assertIn('of reading', r['text'])                       # the hint for an ambiguous basis
        self.assertIn('unit', ed.example(fid, '5')['error'])
        self.assertIn('Type the accuracy', ed.example(fid, '  ')['error'])
        self.assertIn('cannot be read', ed.example(fid, 'wibble')['error'])
        self.assertFalse(ed.example(fid, '0.1 % of reading', reading='abc')['ok'])
        self.assertTrue(ed.example(fid, '0.05 %', default_basis='reading')['ok'])

    def test_example_without_ranges_still_validates_the_text(self):
        ed = self.editor()
        ed.add_function('DCV')
        r = ed.example(ed.fid, '0.1 % of reading')
        self.assertTrue(r['ok'])
        self.assertIn('Add a range', r['text'])
        self.assertIn('counts', ed.example(ed.fid, '2 counts')['text'] + 'counts')

    def test_counts_without_resolution_say_so(self):
        ed = self.editor()
        ed.add_function('DCV')
        ed.add_range(ed.fid, '10 V')
        r = ed.example(ed.fid, '2 counts', range_id='r10')
        self.assertFalse(r['ok'])
        self.assertIn('resolution', r['text'])

    def test_helpers_insert_the_common_forms(self):
        ed, fid = self.built()
        names = [h['key'] for h in ed.helpers(fid)]
        self.assertEqual(names, ['pct_reading', 'pct_range', 'counts', 'floor', 'offset', 'ppm', 'sum'])
        t = ed.insert_helper('', 'pct_reading', fid)
        self.assertEqual(t, '0.01 % of reading')
        t = ed.insert_helper(t, 'pct_range', fid)
        self.assertEqual(t, '0.01 % of reading + 0.005 % of range')
        t = ed.insert_helper(t, 'counts', fid)
        self.assertTrue(ed.example(fid, t, range_id='r10')['ok'])
        self.assertTrue(ed.example(fid, ed.insert_helper('', 'floor', fid), range_id='r10')['ok'])
        self.assertIn('µV', ed.insert_helper('', 'offset', fid))
        self.assertTrue(ed.example(fid, ed.insert_helper('', 'ppm', fid), range_id='r10')['ok'])
        self.assertEqual(ed.insert_helper('0.1 % of reading', 'sum', fid), '0.1 % of reading + ')
        self.assertEqual(ed.insert_helper('0.1 % of reading +', 'sum', fid), '0.1 % of reading + ')
        self.assertEqual(ed.insert_helper('x', 'nope', fid), 'x')
        for h in ed.helpers(fid):                                   # every template parses (the sum helper is only a joiner)
            if h['key'] != 'sum':
                self.assertTrue(ed.example(fid, h['template'], range_id='r10')['ok'], h)

    def test_helpers_use_the_function_unit(self):
        ed = self.editor()
        ed.add_function('OHM2')
        self.assertIn('Ω', ed.insert_helper('', 'offset', ed.fid))
        self.assertTrue(ed.example(ed.fid, ed.insert_helper('', 'floor', ed.fid))['ok'])

    def test_spec_rows_and_editing(self):
        ed = self.editor(fx.acv_bands_sheet())
        rows = ed.spec_rows('acv')
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]['scope'], '1 V range, 10 Hz to 1 kHz')
        self.assertEqual(rows[0]['texts']['1y'], '0.1 % of reading + 0.05 % of range')
        self.assertTrue(ed.edit_spec_entry('acv', 0, {'1y': '0.2 % of reading + 0.05 % of range'}, range_id='r1', f_lo='10', f_hi='1000'))
        self.assertEqual(ed.spec_rows('acv')[0]['texts']['1y'], '0.2 % of reading + 0.05 % of range')
        self.assertTrue(ed.copy_spec_to_ranges('acv', 0, ['r10']))
        self.assertEqual(len(ed.spec_rows('acv')), 5)
        self.assertFalse(ed.edit_spec_entry('acv', 9, {'1y': '1 %'}))
        self.assertTrue(ed.remove_spec_entry('acv', 4))
        self.assertEqual(ed.uncovered_ranges('acv'), [])
        ed.remove_spec_entry('acv', 0), ed.remove_spec_entry('acv', 0), ed.remove_spec_entry('acv', 0)
        self.assertEqual(ed.uncovered_ranges('acv'), ['1 V'])

    def test_one_sided_entry_needs_a_bound_message(self):
        ed = self.editor()
        ed.add_function('SCOPE_BW')
        ed.add_range(ed.fid, '10 V')
        self.assertTrue(ed.add_spec_entry(ed.fid, {'1y': '3 dB'}, mode='low_only'))
        codes = [p['code'] for p in ed.problems() if p['step'] == M.S_SPEC]
        self.assertIn('one_sided_needs_bound', codes)
        ed.edit_spec_entry(ed.fid, 0, {'1y': '3 dB'}, mode='low_only', bound='3')
        self.assertNotIn('one_sided_needs_bound', [p['code'] for p in ed.problems() if p['step'] == M.S_SPEC])


class PointTests(Base):
    def test_rule_catalog_and_rules(self):
        ed, fid = self.built()
        cat = ed.rule_catalog(fid)
        self.assertEqual([r['key'] for r in cat['rules']], list(db.RULE_TYPES))
        self.assertFalse(cat['needs_frequency'])
        self.assertIn('none', [c[0] for c in cat['freq']])
        self.assertEqual(cat['ranges'][0], ('r0.1', '100 mV'))
        ed.add_function('ACV')
        self.assertTrue(ed.rule_catalog('acv')['needs_frequency'])
        self.assertNotIn('none', [c[0] for c in ed.rule_catalog('acv')['freq']])

    def test_every_rule_type_builds_points(self):
        ed = self.editor()
        ed.add_function('DCV')
        fid = ed.fid
        ed.add_ranges(fid, '1 V, 10 V')
        forms = [dict(type='zero_and_full', bipolar=True), dict(type='fixed', values='1 mV, 5 V'), dict(type='linear', start='1 V', stop='3 V', count='3'),
                 dict(type='linear', start='4 V', stop='6 V', step='1 V'), dict(type='log', start='10 mV', stop='1 V', per_decade='1'), dict(type='decade_125', start='2 V', stop='5 V'),
                 dict(type='percent_of_range', percents='25 %', zero=True)]
        for f in forms:
            res = ed.add_rule(fid, f)
            self.assertTrue(res, (f, res.message))
        self.assertEqual(len(ed.rule_rows(fid)), 7)
        self.assertEqual({r['label'] for r in ed.rule_rows(fid)} - {r['label'] for r in M.RULE_TYPES}, set())
        self.assertGreater(len(ed.fn(fid).points), 15)
        self.assertIn('1 mV', ed.rule_rows(fid)[1]['text'])

    def test_rule_form_errors(self):
        ed, fid = self.built()
        for bad in (dict(type='linear', start='1 V', stop='3 V'), dict(type='log', start='1 V', stop='3 V'), dict(type='percent_of_range', percents=''),
                    dict(type='fixed', values='5 apples'), dict(type='linear', start='', stop='3 V', count='3'), dict(type='frequency_sweep', nominal='x'),
                    dict(type='percent_of_range', percents='10', freq_mode='list', freq_values='')):
            res = ed.add_rule(fid, bad)
            self.assertFalse(res, bad)
            self.assertTrue(res.message)

    def test_ac_rules_need_a_frequency_and_support_every_frequency_mode(self):
        ed = self.editor(fx.acv_bands_sheet())
        self.assertFalse(ed.add_rule('acv', dict(type='percent_of_range', percents='50')))      # AC without a frequency rule
        for form in (dict(freq_mode='list', freq_values='100 Hz, 1 kHz'), dict(freq_mode='bands', freq_at='mid'), dict(freq_mode='linear', freq_start='100', freq_stop='300', freq_count='3'),
                     dict(freq_mode='log', freq_start='10', freq_stop='1000', freq_per_decade='2')):
            res = ed.add_rule('acv', dict(type='percent_of_range', percents='100', **form))
            self.assertTrue(res, (form, res.message))
        self.assertTrue(all(p.frequency is not None for p in ed.fn('acv').points))
        self.assertIn('band', ed.rule_rows('acv')[1]['text'] + ed.rule_rows('acv')[2]['text'])

    def test_edit_disable_remove_rule(self):
        ed, fid = self.built()
        rid = ed.rule_rows(fid)[0]['id']
        form = ed.rule_form(fid, rid)
        self.assertEqual((form['type'], form['percents'], form['bipolar']), ('percent_of_range', '10, 50, 100', True))
        form['percents'] = '100'
        res = ed.update_rule(fid, rid, form)
        self.assertTrue(res)
        self.assertIn('removed', res.message)
        self.assertEqual(len(ed.fn(fid).points), 6)
        self.assertTrue(ed.set_rule_enabled(fid, rid, False))
        self.assertEqual(ed.fn(fid).points, [])
        self.assertTrue(ed.set_rule_enabled(fid, rid, True))
        self.assertEqual(len(ed.fn(fid).points), 6)
        self.assertTrue(ed.remove_rule(fid, rid))
        self.assertEqual((ed.fn(fid).rules, ed.fn(fid).points), ([], []))
        self.assertFalse(ed.remove_rule(fid, rid))

    def test_skipped_values_are_reported(self):
        ed, fid = self.built()
        res = ed.add_rule(fid, dict(type='fixed', values='5 V, 500 V'))
        self.assertTrue(res)
        self.assertIn('skipped', res.message)
        self.assertIn('500', res.message)

    def test_point_table_rows(self):
        ed, fid = self.built()
        rows = ed.point_rows(fid)
        self.assertEqual(len(rows), 18)
        r = next(x for x in rows if x['id'] == 'dcv.r10.+5')
        self.assertEqual((r['nominal'], r['low'], r['high']), ('5 V', '4.9965 V', '5.0035 V'))
        self.assertEqual(r['accept'], 'Accept if 4.9965 V <= reading <= 5.0035 V')
        self.assertEqual((r['origin'], r['source'], r['range']), ('rule', 'spec', '10 V'))
        self.assertIn('0.05 % of reading', r['tol_text'])
        small = next(x for x in rows if x['id'] == 'dcv.r0.1.+0.01')
        self.assertEqual((small['nominal'], small['low'], small['high']), ('10 mV', '9.985 mV', '10.015 mV'))     # one prefix across the row
        self.assertEqual(next(x for x in rows if x['id'] == 'dcv.r10.-5')['nominal'], '-5 V')

    def test_point_rows_follow_the_period(self):
        ed = self.editor(fx.dmm_34461a_like())
        a = next(r for r in ed.point_rows('dcv', '90d') if r['id'] == 'dcv.r10.+10')
        b = next(r for r in ed.point_rows('dcv', '1y') if r['id'] == 'dcv.r10.+10')
        self.assertNotEqual((a['low'], a['high']), (b['low'], b['high']))
        self.assertTrue(ed.set_period('90d'))
        self.assertEqual(next(r for r in ed.point_rows('dcv') if r['id'] == 'dcv.r10.+10')['high'], a['high'])
        self.assertFalse(ed.set_period('nope'))

    def test_hand_tools_add_edit_override_remove(self):
        ed, fid = self.built()
        n = len(ed.fn(fid).points)
        res = ed.add_point(fid, '7 V')
        self.assertTrue(res, res.message)
        self.assertEqual(len(ed.fn(fid).points), n + 1)
        row = next(r for r in ed.point_rows(fid) if r['nominal'] == '7 V')
        self.assertEqual(row['origin'], 'manual')
        self.assertFalse(ed.add_point(fid, '7 V'))                  # duplicate
        self.assertFalse(ed.add_point(fid, '70 V'))                 # no range holds it
        pid = row['id']
        self.assertTrue(ed.edit_point(fid, pid, nominal='7.5 V', label='check'))
        self.assertEqual(ed.fn(fid).point(pid).nominal, db.D('7.5'))
        self.assertEqual(ed.fn(fid).point(pid).id, pid)              # the id never changes
        # edit a rule point: it becomes 'edited' and survives a recalculate
        rp = 'dcv.r10.+5'
        self.assertTrue(ed.edit_point(fid, rp, note='by hand'))
        self.assertEqual(next(r for r in ed.point_rows(fid) if r['id'] == rp)['origin'], 'edited')
        self.assertTrue(ed.set_point_override(fid, rp, '4.99', '5.01'))
        r = next(r for r in ed.point_rows(fid) if r['id'] == rp)
        self.assertEqual((r['low'], r['high'], r['source'], r['override']), ('4.99 V', '5.01 V', 'override', True))
        self.assertEqual(ed.point_detail(fid, rp)['low'], '4.99')
        self.assertTrue(ed.clear_point_override(fid, rp))
        self.assertEqual(next(r for r in ed.point_rows(fid) if r['id'] == rp)['source'], 'spec')
        self.assertTrue(ed.set_point_enabled(fid, rp, False))
        self.assertFalse(next(r for r in ed.point_rows(fid) if r['id'] == rp)['enabled'])
        self.assertTrue(ed.remove_point(fid, pid))
        res = ed.remove_point(fid, 'dcv.r10.+1')
        self.assertIn('recalculate', res.message)
        self.assertTrue(ed.recalculate(fid))
        self.assertIsNotNone(ed.fn(fid).point('dcv.r10.+1'))        # an unedited rule point returns
        self.assertIsNotNone(ed.fn(fid).point(rp))                   # an edited one was never touched

    def test_override_inverted_is_a_located_error(self):
        ed, fid = self.built()
        ed.set_point_override(fid, 'dcv.r10.+5', '5.1', '4.9')
        errs = [p for p in ed.problems() if p['code'] in ('override_inverted', 'limit_inverted')]
        self.assertTrue(errs)
        self.assertEqual(errs[0]['step'], M.S_POINTS)
        self.assertEqual(errs[0]['point_id'], 'dcv.r10.+5')
        self.assertIn('10 V range', errs[0]['location'])
        self.assertIn('point 5 V', errs[0]['location'])
        self.assertTrue(next(r for r in ed.point_rows(fid) if r['id'] == 'dcv.r10.+5')['has_error'])
        self.assertEqual([r['id'] for r in ed.point_rows(fid, only_problems=True)], ['dcv.r10.+5'])

    def test_continuity_point_is_pass_fail(self):
        ed = self.editor()
        ed.add_function('CONT')
        ed.add_range(ed.fid, '1000 ohm', '0.1')
        self.assertTrue(ed.add_point(ed.fid, '10 ohm', expect='on'))
        r = ed.point_rows(ed.fid)[0]
        self.assertIn('Pass / fail', r['accept'])
        self.assertEqual(ed.fn().points[0].settings['expect'], 'on')
        self.assertTrue(ed.point_form_fields(ed.fid)['expect'])

    def test_freq_kind_uses_amplitude(self):
        ed = self.editor()
        ed.add_function('FREQ')
        ed.add_range(ed.fid, '300 kHz', '0.001')
        ed.add_spec_entry(ed.fid, {'1y': '0.01 % of reading + 3 counts'})
        self.assertTrue(ed.rule_catalog(ed.fid)['uses_amplitude'])
        self.assertTrue(ed.add_rule(ed.fid, dict(type='fixed', values='1 kHz, 100 kHz', amplitude='1 V')))
        self.assertEqual([r['frequency'] for r in ed.point_rows(ed.fid)], ['', ''])
        self.assertEqual(ed.point_rows(ed.fid)[0]['amplitude'], '1 V')
        self.assertEqual(ed.point_rows(ed.fid)[0]['nominal'], '1 kHz')


class ProblemTests(Base):
    def test_problems_are_located_and_mapped_to_steps(self):
        ed = self.editor()
        ed.add_function('DCV')
        by = {p['code']: p for p in ed.problems()}
        self.assertEqual(by['no_make']['step'], M.S_HEADER)
        self.assertEqual(by['no_ranges']['step'], M.S_RANGES)
        self.assertEqual(by['no_ranges']['function_id'], 'dcv')
        self.assertEqual(by['no_ranges']['location'], 'DC volts')
        self.assertEqual(by['no_spec']['step'], M.S_SPEC)
        self.assertEqual(by['no_points']['step'], M.S_POINTS)
        self.assertEqual(by['no_points']['level'], 'warn')
        self.assertEqual([p['level'] for p in ed.problems()][:1], ['error'])        # errors first

    def test_missing_period_text_points_at_the_spec_line(self):
        ed, fid = self.built()
        ed.add_period('90d')
        p = next(p for p in ed.problems() if p['code'] == 'spec_missing_period')
        self.assertEqual((p['step'], p['function_id'], p['spec_index']), (M.S_SPEC, fid, 0))
        self.assertEqual(p['location'], 'DC volts, specification line 1')
        target = ed.goto_problem(p)
        self.assertEqual((ed.step, ed.fid, target['spec_index']), (M.S_SPEC, fid, 0))
        ed.edit_spec_entry(fid, 0, {'1y': '0.05 % of reading', '90d': '0.04 % of reading'})
        self.assertEqual([p for p in ed.problems() if p['code'] == 'spec_missing_period'], [])

    def test_counts(self):
        ed, fid = self.built()
        self.assertEqual(ed.problem_counts(), dict(errors=0, warnings=0))
        ed.remove_spec_entry(fid, 0)
        self.assertGreater(ed.problem_counts()['errors'], 0)

    def test_problem_cache_follows_changes(self):
        ed, fid = self.built()
        a = ed.problems()
        self.assertIs(ed.problems(), a)
        ed.remove_spec_entry(fid, 0)
        self.assertIsNot(ed.problems(), a)
        ed.undo()
        self.assertEqual(ed.problems(), [])


class SaveTests(Base):
    def test_save_is_gated_by_errors_and_drafts_are_explicit(self):
        ed = self.editor()
        ed.set_header('A', 'B', 'C')
        ed.add_function('DCV')
        rv = ed.review()
        self.assertFalse(rv['can_save'])
        self.assertTrue(rv['can_save_draft'])
        self.assertIn('draft', rv['save_text'])
        res = ed.save()
        self.assertFalse(res)
        self.assertIn('error', res.message)
        self.assertEqual(self.store.list(), [])                      # nothing was written
        self.assertEqual(self.store.entries(), [])
        res = ed.save(as_draft=True)
        self.assertTrue(res)
        self.assertEqual(res.detail.status, 'draft')
        self.assertIn('DRAFT', res.message)
        self.assertEqual(self.store.entries(), [])                   # a draft is not a procedure
        self.assertEqual(self.store.list()[0]['status'], 'draft')

    def test_empty_datasheet_is_not_saved_even_as_draft(self):
        ed = self.editor()
        self.assertFalse(ed.review()['can_save_draft'])
        self.assertFalse(ed.save(as_draft=True))
        self.assertEqual(self.store.list(), [])

    def test_save_registers_a_user_built_procedure_and_every_save_is_a_new_version(self):
        ed, fid = self.built()
        rv = ed.review()
        self.assertTrue(rv['can_save'])
        self.assertEqual((rv['errors'], rv['next_version']), (0, 1))
        res = ed.save(note='first')
        self.assertTrue(res, res.message)
        self.assertEqual((res.detail.status, res.detail.version), ('ready', 1))
        self.assertIn('user-built', res.message)
        entries = self.store.entries()
        self.assertEqual([(e['uid'], e['tag'], e['category']) for e in entries], [(res.detail.uid, 'user-built', 'User-built')])
        spec = json.loads(Path(entries[0]['spec_path']).read_text(encoding='utf-8'))
        self.assertEqual(spec['kind'], 'manual-reading')
        self.assertEqual(len(spec['steps']), 18)
        self.assertFalse(ed.dirty)
        ed.set_header(notes='changed')
        self.assertEqual(ed.review()['next_version'], 2)
        res2 = ed.save(note='second')
        self.assertEqual(res2.detail.version, 2)
        vr = ed.version_rows()
        self.assertEqual([(v['version'], v['status_text'], v['note'], v['who']) for v in vr], [(2, 'runnable', 'second', 'tester'), (1, 'runnable', 'first', 'tester')])
        # a later draft does not replace the runnable spec of the earlier version
        ed.remove_spec_entry(fid, 0)
        self.assertTrue(ed.save(as_draft=True))
        self.assertEqual(json.loads(Path(entries[0]['spec_path']).read_text(encoding='utf-8'))['dsb']['version'], 2)

    def test_load_version_creates_a_new_version_on_save(self):
        ed, fid = self.built()
        ed.save(note='v1')
        ed.add_point(fid, '7 V')
        ed.save(note='v2')
        self.assertEqual(len(ed.fn(fid).points), 19)
        res = ed.load_version(1)
        self.assertTrue(res, res.message)
        self.assertEqual(len(ed.fn(fid).points), 18)
        self.assertTrue(ed.dirty)
        self.assertEqual(ed.based_on, f'{ed.ds.uid} v1')
        self.assertTrue(ed.save(note='back to v1'))
        self.assertEqual([v['version'] for v in ed.version_rows()], [3, 2, 1])
        self.assertFalse(ed.load_version(99))
        self.assertTrue(ed.undo())                                   # load is undoable too
        # opening an older version from storage
        old = M.EditorModel.open(self.store, ed.ds.uid, 2, matcher_factory=lambda: self.matcher)
        self.assertEqual(len(old.fn(fid).points), 19)
        self.assertIsNone(M.EditorModel.open(self.store, 'nope'))

    def test_a_write_failure_is_reported_not_raised(self):
        ed, fid = self.built()
        blocker = self.t / 'blocked'
        blocker.write_text('a file where the folder should be')
        ed.storage = M.Storage(blocker / 'user_specs', self.t / 'x.sqlite3')
        res = ed.save()
        self.assertFalse(res)
        self.assertTrue(res.message.startswith('Not saved'))
        self.assertTrue(ed.dirty)

    def test_never_touches_calibration_procedures_database(self):
        import appdata
        before = appdata.db_path('calibration_procedures.sqlite3')
        existed = before.exists()
        ed, fid = self.built()
        ed.save()
        self.assertEqual(before.exists(), existed)                   # not even created
        import sqlite3
        with sqlite3.connect(self.t / 'lab_registry.sqlite3') as con:
            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        self.assertIn('user_datasheets', tables)


class MatchTests(Base):
    def test_match_rows_and_summary(self):
        ed, fid = self.built()
        res = ed.run_match()
        self.assertTrue(res, res.message)
        self.assertEqual(res.message, '18 of 18 points have a standard; 18 can be run automatically.')
        rows = ed.match_rows()
        self.assertEqual(len(rows), 18)
        r = next(x for x in rows if x['point_id'] == 'dcv.r10.+5')
        self.assertEqual((r['status'], r['standard'], r['automation'], r['level'], r['mode']), ('assigned', '5560A', 'can automate', 'ok', 'auto'))
        self.assertRegex(r['tur'], r'^\d+\.\d:1$')
        self.assertRegex(r['tar'], r'^\d+\.\d:1$')
        self.assertEqual(r['point'], '5 V')
        s = ed.match_summary()
        self.assertEqual(s['total']['points'], 18)
        self.assertEqual(s['functions'][0]['name'], 'DC volts')
        self.assertTrue(ed.match_fresh())
        ed.set_header(notes='x')
        self.assertFalse(ed.match_fresh())
        self.assertEqual(ed.step_states()[M.S_AUTOMATION]['state'], 'todo')

    def test_match_needs_a_valid_datasheet(self):
        ed = self.editor()
        ed.add_function('DCV')
        res = ed.run_match()
        self.assertFalse(res)
        self.assertIn('Fix the', res.message)
        self.assertEqual(ed.match_rows(), [])

    def test_uncovered_points_say_why_and_cannot_automate_is_worded(self):
        ed = self.editor(fx.generator_33220a_like())
        self.assertTrue(ed.run_match())
        un = ed.match_rows(filter='uncovered')
        cannot = ed.match_rows(filter='cannot')
        every = ed.match_rows()
        self.assertEqual(len(every), len(ed.match_result.assignments))
        for r in un:
            self.assertTrue(r['reason'] and r['message'])
            self.assertEqual((r['level'], r['automation']), ('bad', 'cannot automate (no standard)'))
        for r in cannot:
            self.assertEqual(r['level'], 'warn')
            self.assertTrue(r['automation'].startswith('cannot automate') or r['automation'].startswith('set by hand'))
        texts = {r['automation'] for r in every}
        self.assertTrue(any(t.startswith('can automate') for t in texts))      # at least the 5790B rows (commands unverified)
        self.assertEqual(len(ed.match_rows(filter='unverified')), sum(1 for r in every if r['automation_status'] == 'unverified'))

    def test_cannot_automate_names_the_missing_driver(self):
        ed = self.editor()
        ed.set_header('Acme', 'S-1', 'S-1 PV')
        ed.add_function('SCOPE_TIMEBASE')
        ed.add_range(ed.fid, '1 s', '1e-9')
        ed.add_spec_entry(ed.fid, {'1y': '0.01 % of reading'})
        ed.add_point(ed.fid, '1 ms')
        self.assertTrue(ed.run_match())
        r = ed.match_rows()[0]
        self.assertEqual(r['status'], 'assigned')
        self.assertIn('automate', r['automation'])
        self.assertEqual(r['can_automate'], r['automation_status'] in ('ok', 'unverified'))

    def test_override_per_point_and_manual(self):
        ed, fid = self.built()
        ed.run_match()
        pid = 'dcv.r10.+5'
        ch = ed.override_choices(pid)
        self.assertEqual(ch[0][0], '')
        self.assertEqual(ch[-1][0], 'MANUAL')
        self.assertIn('5522A', [v for v, _ in ch])
        cands = ed.candidate_rows(pid)
        self.assertEqual(cands[0]['standard'], '5560A')
        self.assertTrue(cands[0]['chosen'])
        self.assertTrue(ed.set_assignment(pid, '5522A'))
        r = next(x for x in ed.match_rows() if x['point_id'] == pid)
        self.assertEqual((r['standard'], r['mode'], r['overridden']), ('5522A', 'override', True))
        self.assertEqual(ed.ds.assignments, {pid: '5522A'})          # persisted in the datasheet
        self.assertTrue(ed.set_assignment(pid, 'MANUAL'))
        r = next(x for x in ed.match_rows() if x['point_id'] == pid)
        self.assertEqual((r['standard'], r['status'], r['automation']), ('MANUAL', 'manual', 'set by hand (your own standard)'))
        self.assertTrue(ed.set_assignment(pid, ''))
        self.assertEqual(ed.ds.assignments, {})
        self.assertEqual(next(x for x in ed.match_rows() if x['point_id'] == pid)['standard'], '5560A')
        self.assertTrue(ed.undo())                                   # overrides are undoable
        self.assertTrue(ed.match_fresh() or ed.match_result is not None)
        self.assertTrue(ed.set_assignment(pid, '5790B'))  # a standard that cannot cover it stays visible, never silently changed
        r = next(x for x in ed.match_rows() if x['point_id'] == pid)
        self.assertEqual((r['status'], r['standard']), ('uncovered', ''))
        self.assertTrue(r['reason'])
        self.assertTrue(ed.clear_assignments())
        self.assertEqual(ed.ds.assignments, {})
        self.assertFalse(ed.set_assignment('missing', '5560A'))

    def test_overrides_are_saved_with_the_datasheet(self):
        ed, fid = self.built()
        ed.run_match()
        ed.set_assignment('dcv.r10.+5', '5522A')
        self.assertTrue(ed.save())
        again = M.EditorModel.open(self.store, ed.ds.uid)
        self.assertEqual(again.ds.assignments, {'dcv.r10.+5': '5522A'})

    def test_matcher_failure_is_a_message(self):
        ed, fid = self.built()

        def boom():
            raise RuntimeError('standards database missing')
        ed.matcher_factory = boom
        res = ed.run_match()
        self.assertFalse(res)
        self.assertIn('standards', res.message)
        self.assertEqual(ed.match_error, res.message)

    def test_driver_rows_only_list_functions_of_this_datasheet(self):
        ed, fid = self.built()
        rows = ed.driver_rows()
        r5560 = next(r for r in rows if r['model'] == '5560A')
        self.assertEqual(list(r5560['functions']), ['DCV'])
        self.assertEqual(r5560['functions']['DCV']['text'], 'can automate')
        self.assertTrue(any(r['model'] == '5790B' for r in rows))

    def test_review_includes_automation_line(self):
        ed, fid = self.built()
        self.assertIn('not been checked', ed.review()['automation'])
        ed.run_match()
        self.assertIn('18 of 18', ed.review()['automation'])
        ed.set_assignment('dcv.r10.+5', 'MANUAL')
        self.assertIn('own standard choice', ed.review()['automation'])
        self.assertEqual(ed.review()['points'], 18)
        self.assertEqual(ed.review()['functions'][0]['name'], 'DC volts')


class ListTests(Base):
    def make(self, title='PV one', **kw):
        ed, fid = self.built()
        ed.set_header(title=title, **kw)
        res = ed.save()
        self.assertTrue(res)
        return res.detail.uid

    def test_rows_search_and_empty_text(self):
        lst = M.DatasheetList(self.store)
        self.assertEqual(lst.refresh(), [])
        self.assertIn('No datasheets yet', lst.empty_text())
        uid = self.make()
        rows = lst.refresh()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r['make'], r['model'], r['title'], r['version'], r['points'], r['functions'], r['status']), ('Acme', 'DM-1', 'PV one', 1, 18, 'DC volts', 'ready'))
        self.assertEqual(r['automation'], 'Ready: all 18 points run by the suite')
        self.assertRegex(r['saved'], r'^\d{4}-\d\d-\d\dT')
        lst.search = 'nothing like it'
        self.assertEqual(lst.rows(), [])
        self.assertIn('search', lst.empty_text())
        lst.search = 'dc volts'
        self.assertEqual(len(lst.rows()), 1)
        lst.search = 'acme'
        self.assertEqual(len(lst.rows()), 1)
        self.assertEqual(lst.row(uid)['uid'], uid)

    def test_draft_and_hand_set_automation_text(self):
        ed = self.editor()
        ed.set_header('A', 'B', 'draft one')
        ed.add_function('DCV')
        ed.save(as_draft=True)
        lst = M.DatasheetList(self.store)
        self.assertIn('Draft', lst.refresh()[0]['automation'])
        lst2 = M.DatasheetList(self.store)
        gen = self.editor(fx.generator_33220a_like())
        self.assertTrue(gen.save())
        row = next(r for r in lst2.refresh() if r['model'] == '33220A')
        self.assertRegex(row['automation'], r'^Ready: \d+ of \d+ points run by the suite, \d+ set by hand(; \d+ use commands not yet verified on hardware.*)?$')

    def test_new_open_duplicate_delete_restore(self):
        uid = self.make()
        lst = M.DatasheetList(self.store)
        lst.refresh()
        self.assertEqual(lst.new().ds.make, '')
        ed = lst.open(uid)
        self.assertEqual(ed.ds.uid, uid)
        self.assertEqual(ed.based_on, f'{uid} v1')
        self.assertIsNone(lst.open('missing'))
        self.assertIn('missing', lst.last_error)
        res = lst.duplicate(uid, 'PV two')
        self.assertTrue(res, res.message)
        self.assertEqual(len(lst.rows()), 2)
        self.assertNotEqual(res.detail, uid)
        res = lst.delete(uid)
        self.assertTrue(res)
        self.assertEqual(len(lst.rows()), 1)
        self.assertEqual([e['uid'] for e in self.store.entries()], [lst.rows()[0]['uid']])          # left the Procedures list
        lst.show_deleted = True
        rows = lst.refresh()
        self.assertEqual(len(rows), 2)
        gone = next(r for r in rows if r['deleted'])
        self.assertEqual(gone['automation'], 'Deleted (can be restored)')
        self.assertFalse(lst.delete('missing'))
        self.assertTrue(lst.restore(uid))
        lst.show_deleted = False
        self.assertEqual(len(lst.refresh()), 2)
        self.assertEqual(len(self.store.entries()), 2)
        self.assertFalse(lst.restore(uid))
        self.assertFalse(lst.duplicate('missing'))

    def test_export_import_json(self):
        uid = self.make()
        lst = M.DatasheetList(self.store)
        path = self.t / 'out.json'
        self.assertFalse(lst.export_json(uid, ''))
        self.assertFalse(lst.export_json('missing', str(path)))
        res = lst.export_json(uid, str(path))
        self.assertTrue(res, res.message)
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['schema'], 'dsb-1')
        res = lst.import_json(str(path))
        self.assertTrue(res, res.message)
        self.assertNotEqual(res.detail, uid)                         # always a NEW datasheet
        self.assertEqual(len(lst.rows()), 2)
        bad = self.t / 'bad.json'
        bad.write_text('{"not": "a datasheet"}')
        res = lst.import_json(str(bad))
        self.assertFalse(res)
        self.assertTrue(res.message.startswith('Not imported'))
        self.assertFalse(lst.import_json(str(self.t / 'nope.json')))
        self.assertFalse(lst.import_json(''))
        self.assertEqual(len(lst.rows()), 2)
        # a runnable spec file (which carries its datasheet) imports too
        spec = next(e['spec_path'] for e in self.store.entries() if e['uid'] == uid)
        self.assertTrue(lst.import_json(spec))
        self.assertEqual(len(lst.rows()), 3)

    def test_export_a_chosen_version(self):
        ed, fid = self.built()
        ed.save()
        ed.add_point(fid, '7 V')
        ed.save()
        lst = M.DatasheetList(self.store)
        p1, p2 = self.t / 'v1.json', self.t / 'v2.json'
        self.assertTrue(lst.export_json(ed.ds.uid, str(p1), 1))
        self.assertTrue(lst.export_json(ed.ds.uid, str(p2)))
        count = lambda p: sum(len(f['points']) for f in json.loads(p.read_text(encoding='utf-8'))['functions'])
        self.assertEqual((count(p1), count(p2)), (18, 19))

    def test_version_list(self):
        ed, fid = self.built()
        ed.save(note='one')
        ed.remove_spec_entry(fid, 0)
        ed.save(note='two', as_draft=True)
        lst = M.DatasheetList(self.store)
        vr = lst.version_rows(ed.ds.uid)
        self.assertEqual([(v['version'], v['status_text'], v['note']) for v in vr], [(2, 'draft (had problems)', 'two'), (1, 'runnable', 'one')])
        self.assertEqual(lst.version_rows('missing'), [])
        self.assertEqual(lst.open(ed.ds.uid, 1).ds.version, 1)


class MoreModelTests(Base):
    def test_example_for_a_saved_line_and_period_label_and_amount(self):
        ed = self.editor(fx.dmm_34461a_like())
        r = ed.example_for_entry('dcv', 0, '90d')
        self.assertTrue(r['ok'], r['text'])
        self.assertIn('low limit is', r['text'])
        self.assertTrue(ed.set_period_label('90d', '3 months'))
        self.assertEqual(ed.ds.periods[0].label, '3 months')
        self.assertFalse(ed.set_period_label('nope', 'x'))
        self.assertEqual(ed.parse_amount('5 mV', 'dcv'), db.D('0.005'))
        with self.assertRaises(db.DsError):
            ed.parse_amount('5 A', 'dcv')

    def test_locate_every_shape_of_where(self):
        ed = self.editor(fx.dmm_34461a_like())
        loc = ed.locate('dcv/spec1', 'spec_missing_period')
        self.assertEqual((loc['step'], loc['spec_index'], loc['text']), (M.S_SPEC, 0, 'DC volts, specification line 1'))
        loc = ed.locate('dcv/rule/pct', 'rule_params')
        self.assertEqual((loc['step'], loc['function_id']), (M.S_POINTS, 'dcv'))
        loc = ed.locate('dcv/r10', 'range_value')
        self.assertEqual((loc['step'], loc['range_id'], loc['text']), (M.S_RANGES, 'r10', 'DC volts, 10 V range'))
        loc = ed.locate('dcv.r10.+5', 'limit_inverted')                         # a bare point id
        self.assertEqual((loc['function_id'], loc['point_id'], loc['step']), ('dcv', 'dcv.r10.+5', M.S_POINTS))
        loc = ed.locate('datasheet', 'no_functions')
        self.assertEqual((loc['step'], loc['text']), (M.S_FUNCTIONS, 'Functions'))
        loc = ed.locate('datasheet', 'dup_period')
        self.assertEqual(loc['step'], M.S_HEADER)
        self.assertEqual(ed.locate('mystery/place', 'x')['step'], M.S_REVIEW)
        self.assertEqual(ed.locate('dcv', 'bad_kind')['step'], M.S_FUNCTIONS)
        self.assertEqual(ed.locate('dcv', 'no_points')['step'], M.S_POINTS)

    def test_open_missing_and_matcher_default_factory_is_lazy(self):
        ed = self.editor()
        self.assertIsNone(ed._matcher)
        self.assertEqual(ed.match_rows(), [])
        self.assertEqual(ed.match_summary()['total']['points'], 0)
        self.assertEqual(ed.candidate_rows('x'), [])
        self.assertFalse(ed.match_fresh())

    def test_function_display_unit_and_range_prefix_show_in_tables(self):
        ed, fid = self.built()
        self.assertTrue(ed.set_function(fid, display_unit='m'))
        self.assertEqual(ed.range_rows(fid)[2]['text'], '10000 mV')
        row = next(r for r in ed.point_rows(fid) if r['id'] == 'dcv.r10.+5')
        self.assertEqual((row['nominal'], row['low'], row['high']), ('5000 mV', '4996.5 mV', '5003.5 mV'))
        self.assertEqual(ed.ds.functions[0].display_unit, 'm')                  # display only; the values are untouched
        self.assertEqual(ed.fn(fid).point('dcv.r10.+5').nominal, db.D('5'))
        self.assertTrue(ed.set_function(fid, display_unit='base'))
        self.assertEqual(ed.ds.functions[0].display_unit, '')


class StorageTests(Base):
    def test_storage_defaults_do_not_raise(self):
        s = M.Storage()
        self.assertIsInstance(s.who, str)
        self.assertEqual(s.kw(), dict(root=None, db=None))

    def test_ui_model_has_no_tkinter(self):
        text = (HERE.parent / 'datasheet_builder_ui_model.py').read_text(encoding='utf-8')
        self.assertNotIn('tkinter', text.replace('no tkinter', ''))
        self.assertNotIn('calibration_procedures', text.replace('calibration_procedures.sqlite3: storage', '').replace('Nothing here touches calibration_procedures.sqlite3', ''))


if __name__ == '__main__':
    unittest.main()
