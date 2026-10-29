"""Datasheet Builder: runnable spec output (existing 'manual-reading' schema + the additive 'dsb' extension), procspec validation, and the stock
handheld engine listing / judging the generated points.  No tkinter (stubbed as in test_pad_reading).
Run:  python -m unittest tests.test_datasheet_builder_specs"""
import json
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import _tk_stub  # noqa: E402
_tk_stub.install()
import datasheet_builder as db  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import handheld_dmm as hh  # noqa: E402
import procspec  # noqa: E402

SPECS = HERE.parent / 'specs'


class ProcspecHook(unittest.TestCase):
    def test_shipped_handheld_specs_are_clean(self):
        for name in ('fluke_110_series_pv', 'fluke_80_series_v_pv', 'fluke_287_289_pv', 'klein_mm325_pv'):
            spec = json.loads((SPECS / f'{name}.json').read_text(encoding='utf-8'))
            self.assertEqual(procspec.validate_manual_reading(spec), [], name)

    def test_schema1_specs_load_as_before(self):
        spec = procspec.load(SPECS / 'keysight_34461a_pv.json')
        self.assertEqual(spec['model'], '34461A')

    def test_a_handheld_spec_now_loads_through_procspec(self):
        spec = procspec.load(SPECS / 'klein_mm325_pv.json')
        self.assertEqual(len(spec['steps']), 18)

    def test_broken_manual_reading_specs_are_caught_with_codes(self):
        spec = json.loads((SPECS / 'klein_mm325_pv.json').read_text(encoding='utf-8'))
        spec['steps'][0].pop('low')
        spec['steps'][1]['models'] = ['NOPE']
        spec['steps'][2]['id'] = spec['steps'][3]['id']
        spec['steps'][4]['low'], spec['steps'][4]['high'] = '9', '1'
        codes = {p.code for p in procspec.validate_manual_reading(spec)}
        self.assertTrue({'step_key', 'model_unknown', 'dup_id', 'limit_inverted'} <= codes, codes)
        self.assertTrue(procspec.validate_manual_reading({}))                   # an empty / foreign object: problems, never an exception
        self.assertTrue(procspec.validate_manual_reading({'steps': 5, 'models': []}))


class Export(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = fx.dmm_34461a_like()
        cls.res = dsp.export_spec(cls.ds)
        cls.spec = cls.res.spec

    def test_exports_and_validates(self):
        self.assertTrue(self.res.ok, [str(p) for p in db.errors(self.res.problems)])
        self.assertEqual(procspec.validate_manual_reading(self.spec), [])
        self.assertEqual(self.spec['kind'], 'manual-reading')
        self.assertEqual(self.spec['schema'], 2)
        self.assertTrue(self.spec['user_built'])
        self.assertEqual(self.spec['options']['function_prompt'], True)
        self.assertEqual(self.spec['options']['auto_ramp'], False)

    def test_worked_limit_reaches_the_step_in_display_units(self):
        step = next(s for s in self.spec['steps'] if s['id'] == 'dcv.r10.+5')
        # 1 y: 0.0040 % of 5 V = 0.0002 V; 0.0035 % of 10 V = 0.00035 V; total 0.00055 V
        self.assertEqual((step['low'], step['high']), ('4.99945', '5.00055'))
        self.assertEqual((step['display_unit'], step['factor'], step['base_unit']), ('V', 1.0, 'V'))
        self.assertEqual(step['range'], '10.00000 V')
        self.assertEqual(step['dsb']['limit']['low'], '4.99945')
        self.assertEqual(step['dsb']['limit']['periods']['90d']['high'], '5.00045')
        small = next(s for s in self.spec['steps'] if s['id'] == 'dcv.r0.1.+0.1')
        self.assertEqual((small['display_unit'], small['factor']), ('mV', 0.001))
        self.assertEqual(small['range'], '100.0000 mV')

    def test_limits_shown_follow_the_chosen_period(self):
        spec90 = dsp.export_spec(self.ds, period='90d').spec
        step = next(s for s in spec90['steps'] if s['id'] == 'dcv.r10.+5')
        self.assertEqual((step['low'], step['high']), ('4.99955', '5.00045'))
        self.assertEqual(spec90['dsb']['period'], '90d')
        self.assertFalse(dsp.export_spec(self.ds, period='5y').ok)

    def test_engine_kinds(self):
        kinds = {s['id']: s['kind'] for s in self.spec['steps']}
        self.assertEqual(kinds['dcv.r10.+5'], 'DCV')
        self.assertEqual(next(s for s in self.spec['steps'] if s['dsb']['kind'] == 'OHM2')['kind'], 'OHM')
        f = next(s for s in self.spec['steps'] if s['dsb']['kind'] == 'FREQ' and s['nominal'] == 1000.0)
        self.assertEqual((f['kind'], f['applied'], f['base_unit']), ('ACV', {'value': 1.0, 'frequency': 1000.0}, 'Hz'))
        a = next(s for s in self.spec['steps'] if s['id'] == 'acv.r10.+10@1000')
        self.assertEqual(a['applied'], {'value': 10.0, 'frequency': 1000.0})
        i = next(s for s in self.spec['steps'] if s['dsb']['kind'] == 'DCI' and s['nominal'] == 3.0)
        self.assertEqual(i['group'], 'AMP10')

    def test_dsb_header_and_embedded_datasheet(self):
        head = self.spec['dsb']
        self.assertEqual((head['schema'], head['make'], head['model']), ('dsb-1', 'Keysight', '34461A'))
        back = dsp.datasheet_from_spec(self.spec)
        self.assertEqual(back.to_dict(), self.ds.to_dict())
        self.assertTrue(head['engine']['stock_runnable'])

    def test_json_round_trip_through_procspec_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'u.json'
            path.write_text(json.dumps(self.spec), encoding='utf-8')
            spec = procspec.load(path)
            self.assertEqual(spec['steps'][0]['id'], self.spec['steps'][0]['id'])
            self.assertEqual(dsp.datasheet_from_spec(spec).to_dict(), self.ds.to_dict())

    def test_disabled_points_are_left_out(self):
        ds = fx.dmm_34461a_like()
        ds.function('dcv').points[0].enabled = False
        spec = dsp.export_spec(ds).spec
        self.assertNotIn(ds.function('dcv').points[0].id, [s['id'] for s in spec['steps']])

    def test_errors_block_the_export_nothing_is_corrected(self):
        ds = fx.dmm_34461a_like()
        ds.function('dcv').ranges[0].resolution = D(-1)
        res = dsp.export_spec(ds)
        self.assertIsNone(res.spec)
        self.assertIn('range_resolution', [p.code for p in res.problems])

    def test_one_sided_without_bound_blocks_the_runnable_spec(self):
        ds = fx.scope_tds2000c_like()
        ds.function('scope_bw').spec[0].bound = None
        res = dsp.export_spec(ds)
        self.assertIsNone(res.spec)
        self.assertIn('one_sided_needs_bound', [p.code for p in res.problems])

    def test_assignment_recorded_from_overrides_and_plan(self):
        ds = fx.dmm_34461a_like()
        ds.assignments['dcv.r10.+5'] = '5522A'
        spec = dsp.export_spec(ds).spec
        step = next(s for s in spec['steps'] if s['id'] == 'dcv.r10.+5')
        self.assertEqual(step['dsb']['assignment'], {'standard': '5522A', 'mode': 'override'})
        self.assertNotIn('assignment', next(s for s in spec['steps'] if s['id'] == 'dcv.r10.+1')['dsb'])


class LazyAliases(unittest.TestCase):
    def test_public_names_on_the_main_module(self):
        ds = fx.dmm_34461a_like()
        self.assertTrue(db.export_spec(ds).ok)
        self.assertTrue(callable(db.driver_table) and callable(db.match_datasheet) and callable(db.automation_status))
        self.assertTrue(callable(db.datasheet_from_spec))
        with self.assertRaises(AttributeError):
            db.no_such_thing


class ScopeAndGeneratorExtension(unittest.TestCase):
    def test_generator_points_are_hand_set_with_a_stimulus_block(self):
        res = dsp.export_spec(fx.generator_33220a_like())
        self.assertTrue(res.ok)
        self.assertEqual(procspec.validate_manual_reading(res.spec), [])
        s = res.spec['steps'][0]
        self.assertEqual((s['kind'], s['group'], s['dsb']['direction'], s['dsb']['engine_ready']), ('NONE', 'NONE', 'source', False))
        self.assertEqual(s['dsb']['stimulus']['settings']['waveform'], 'SIN')
        self.assertIn('Read the measuring standard', s['setup'])
        self.assertFalse(res.spec['dsb']['engine']['stock_runnable'])

    def test_scope_gain_is_drivable_by_the_stock_engine_and_the_rest_is_hand_set(self):
        spec = dsp.export_spec(fx.scope_tds2000c_like()).spec
        by = {}
        for s in spec['steps']:
            by.setdefault(s['dsb']['kind'], []).append(s)
        self.assertEqual({s['kind'] for s in by['SCOPE_GAIN']}, {'DCV'})
        self.assertTrue(all(s['dsb']['engine_ready'] for s in by['SCOPE_GAIN']))
        self.assertEqual({s['kind'] for s in by['SCOPE_BW']}, {'NONE'})
        self.assertEqual({s['kind'] for s in by['SCOPE_TRIGGER']}, {'VISUAL'})
        bw = by['SCOPE_BW'][0]
        # 3 dB, low_only with bound 3: nominal 0 dB, accept -3 .. +3 dB
        self.assertEqual((bw['low'], bw['high'], bw['display_unit']), ('-3', '3', 'dB'))
        self.assertEqual(bw['dsb']['stimulus']['amplitude'], '3')

    def test_dsb_validator_catches_a_damaged_extension(self):
        spec = dsp.export_spec(fx.scope_tds2000c_like()).spec
        bad = json.loads(json.dumps(spec))
        bad['steps'][0]['dsb']['limit']['low'], bad['steps'][0]['dsb']['limit']['high'] = '9', '1'
        bad['steps'][1]['dsb']['kind'] = 'NOPE'
        bad['steps'][2]['dsb']['point_id'] = 'x'
        codes = {p.code for p in procspec.validate_manual_reading(bad)}
        self.assertTrue({'limit_inverted', 'bad_kind', 'dsb_point_id'} <= codes, codes)
        worse = json.loads(json.dumps(spec))
        worse['dsb']['schema'] = 'v9'
        self.assertIn('dsb_schema', {p.code for p in procspec.validate_manual_reading(worse)})
        headless = json.loads(json.dumps(spec))
        headless.pop('dsb')
        self.assertIn('dsb_header', {p.code for p in procspec.validate_manual_reading(headless)})
        with self.assertRaises(procspec.SpecError):
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / 'x.json').write_text(json.dumps(worse), encoding='utf-8')
                procspec.load(Path(d) / 'x.json')


class StockHandheldEngine(unittest.TestCase):
    """The generated DMM spec runs through handheld_dmm's own point list, descriptions and judging, unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.ds = fx.dmm_34461a_like()
        cls.spec = dsp.export_spec(cls.ds).spec
        cls.pts = hh.points_for(cls.spec, '34461A')

    def test_points_listed_in_order_and_numbered(self):
        self.assertEqual(len(self.pts), sum(len(f.points) for f in self.ds.functions))
        self.assertEqual([p['n'] for p in self.pts], list(range(1, len(self.pts) + 1)))
        self.assertEqual(self.pts[0]['id'], 'dcv.r0.1.-0.1')
        self.assertEqual({p['group'] for p in self.pts}, {'VOHM', 'UAMP', 'AMP10'})

    def test_describe_and_output_text_work_for_every_point(self):
        for p in self.pts:
            self.assertTrue(hh.describe(p))
            self.assertTrue(hh.output_text(p))
        dc = next(p for p in self.pts if p['id'] == 'dcv.r10.+5')
        self.assertEqual(hh.output_text(dc), '5 V DC')
        ac = next(p for p in self.pts if p['id'] == 'acv.r10.+10@1000')
        self.assertEqual(hh.output_text(ac), '10 V AC @ 1 kHz')

    def test_judging_uses_the_generated_limits_exactly(self):
        p = next(p for p in self.pts if p['id'] == 'dcv.r10.+5')
        self.assertEqual(hh.judge_numeric(p, '4.99945')[0], 'PASS')
        self.assertEqual(hh.judge_numeric(p, '5.00055')[0], 'PASS')
        self.assertEqual(hh.judge_numeric(p, '5.00056')[0], 'FAIL')
        self.assertEqual(hh.judge_numeric(p, '4.99944')[0], 'FAIL')
        self.assertEqual(hh.pad_reading(p, '5'), '5.00000')                       # padded to the limits' resolution (standing rule)
        mv = next(p for p in self.pts if p['id'] == 'dcv.r0.1.+0.1')
        self.assertEqual(hh.judge_numeric(mv, '100.0')[0], 'PASS')                # typed in mV (display unit)
        self.assertAlmostEqual(hh.judge_numeric(mv, '100.0')[1], 0.1)

    def test_scope_and_generator_specs_list_too(self):
        for mk, model in ((fx.scope_tds2000c_like, 'TDS2024C'), (fx.generator_33220a_like, '33220A')):
            spec = dsp.export_spec(mk()).spec
            pts = hh.points_for(spec, model)
            self.assertEqual(len(pts), len(spec['steps']))
            for p in pts:
                hh.describe(p)
                if p['group'] != 'NONE':
                    hh.output_text(p)


if __name__ == '__main__':
    unittest.main()
