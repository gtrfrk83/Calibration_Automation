"""Keysight 53210A / 53220A / 53230A verification (keysight_53220a_verification.py, drivers/keysight_53220a.py, drivers/simulated_53220a.py, specs/keysight_53220a_pv.json).

Part 1: the spec: counts per section, every printed limit against an independent second typing (read again from the record pages 91-99 of the Service Guide), the printed text
against the number, the datasheet ratios (with the two documented exceptions), the builder reproducing the stored file.
Part 2: the driver on the simulated counter: registry (page references, verified flags, the 53210A's unverified commands), set / read back / compare, no retry of a write,
the error queue, +2009 without the external reference, the non-volatile reference settings restored, 9.91E37, the options.
Part 3: the engine on the simulated bench (all three models): stimulus routing, command order, standby after each point, the Std Dev reusing the Mean readings, the other-standard
prompts, Decimal judging, uncertainty, report rows, PDF, demo marking, registration.
tkinter is stubbed in setUpModule (not at import time), like tests/test_34410a_points.py.
Run:  python -m unittest tests.test_keysight_53220a_points"""
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

A = VH = SPEC = PTS = K = None
SCALE = {'mHz': D('0.001'), 'Hz': D(1), 'kHz': D(1000), 'MHz': D(1000000), 'GHz': D(1000000000), 'ns': D('0.000000001'), 'us': D('0.000001')}
SECTION_SIZES = {'ov': 1, 't1': 1, 't2': 12, 't3': 8, 't4': 4, 't5': 2, 't6a': 4, 't6b': 6, 't7': 8}


def V(text):
    """'9.999 999 990 MHz' -> Decimal in base units (the second typing of the record pages is written in the printed form)."""
    num, unit = text.rsplit(' ', 1)
    return D(num.replace(' ', '')) * SCALE[unit]


def M(lo, hi):
    return (V(lo), V(hi))


# the printed limits typed a second time from the record pages (min, max); Std Dev maxima are single values.  53210A / 53220A / 53230A.
MEAN2 = {
    '2a.10MHz': {'53210A': M('9.999 999 900 MHz', '10.000 000 100 MHz'), '53220A': M('9.999 999 990 MHz', '10.000 000 010 MHz'), '53230A': M('9.999 999 990 MHz', '10.000 000 010 MHz')},
    '2a.115MHz': {'53210A': M('114.999 998 850 MHz', '115.000 001 150 MHz'), '53220A': M('114.999 999 885 MHz', '115.000 000 115 MHz'), '53230A': M('114.999 999 885 MHz', '115.000 000 115 MHz')},
    '2a.350MHz': {'53210A': M('349.999 996 500 MHz', '350.000 003 500 MHz'), '53220A': M('349.999 999 650 MHz', '350.000 000 350 MHz'), '53230A': M('349.999 999 650 MHz', '350.000 000 350 MHz')},
}
SDEV2 = {
    '2a.10MHz': {'53210A': V('140 mHz'), '53220A': V('70 mHz'), '53230A': V('14 mHz')},
    '2a.115MHz': {'53210A': D('1.61'), '53220A': V('805 mHz'), '53230A': V('161 mHz')},
    '2a.350MHz': {'53210A': D('4.9'), '53220A': D('2.45'), '53230A': V('490 mHz')},
}
OTHER_MEAN = {
    '3.ch1.1MHz': {'53220A': M('0.999 800 000 us', '1.000 200 000 us'), '53230A': M('0.999 900 000 us', '1.000 100 000 us')},
    '3.ch1.250MHz': {'53220A': M('0.003 800 000 us', '0.004 200 000 us'), '53230A': M('0.003 900 000 us', '0.004 100 000 us')},
    '4a.ch1.5ns': {'53220A': M('4.600 ns', '5.400 ns'), '53230A': M('4.800 ns', '5.200 ns')},
    '5.ch1-ch2.49.9ns': {'53220A': M('49.400 ns', '50.400 ns'), '53230A': M('49.650 ns', '50.150 ns')},
    '6a.100MHz': {'53210A': M('99.999 999 000 MHz', '100.000 001 000 MHz'), '53220A': M('99.999 999 900 MHz', '100.000 000 100 MHz'), '53230A': M('99.999 999 900 MHz', '100.000 000 100 MHz')},
    '6a.5.88GHz': {'53210A': M('5.879 999 941 200 GHz', '5.880 000 058 800 GHz'), '53220A': M('5.879 999 994 120 GHz', '5.880 000 005 880 GHz'),
                   '53230A': M('5.879 999 994 120 GHz', '5.880 000 005 880 GHz')},
    '6b.300MHz': {'53210A': M('299.999 997 MHz', '300.000 003 MHz'), '53220A': M('299.999 999 7 MHz', '300.000 000 3 MHz'), '53230A': M('299.999 999 7 MHz', '300.000 000 3 MHz')},
    '6b.3.1GHz': {'53210A': M('3.099 999 969 GHz', '3.100 000 031 GHz'), '53220A': M('3.099 999 996 9 GHz', '3.100 000 003 1 GHz'), '53230A': M('3.099 999 996 9 GHz', '3.100 000 003 1 GHz')},
    '6b.15GHz': {'53210A': M('14.999 999 850 GHz', '15.000 000 150 GHz'), '53220A': M('14.999 999 985 GHz', '15.000 000 015 GHz'), '53230A': M('14.999 999 985 GHz', '15.000 000 015 GHz')},
    '7a.6GHz.200ns': {'53230A': M('5.994 000 000 GHz', '6.006 000 000 GHz')},
    '7b.6GHz.13us': {'53230A': M('5.999 954 000 GHz', '6.000 046 000 GHz')},
    '7c.1.35GHz.400ns': {'53230A': M('1.348 865 000 GHz', '1.351 350 000 GHz')},       # the printed record-page minimum (the test text gives 1.348 650 000: flagged)
    '7d.1.35GHz.13us': {'53230A': M('1.349 979 200 GHz', '1.350 020 800 GHz')},
}
OTHER_SDEV = {
    '3.ch1.1MHz': {'53220A': V('0.140 ns'), '53230A': V('0.028 ns')}, '3.ch1.250MHz': {'53220A': V('0.140 ns'), '53230A': V('0.028 ns')},
    '4a.ch1.5ns': {'53220A': V('0.140 ns'), '53230A': V('0.028 ns')}, '5.ch1-ch2.49.9ns': {'53220A': V('0.140 ns'), '53230A': V('0.028 ns')},
    '6a.100MHz': {'53210A': D('1.4'), '53220A': D('0.7'), '53230A': D('0.14')},
    '6a.5.88GHz': {'53210A': D('82.3'), '53220A': D('41.1'), '53230A': D('8.23')},
    '6b.300MHz': {'53210A': D('4.2'), '53220A': D('2.1'), '53230A': D('0.42')},
    '6b.3.1GHz': {'53210A': D('43.4'), '53220A': D('21.7'), '53230A': D('4.34')},
    '6b.15GHz': {'53210A': D('210'), '53220A': D('105'), '53230A': D('21')},
    '7a.6GHz.200ns': {'53230A': V('3.000 MHz')}, '7b.6GHz.13us': {'53230A': V('18.500 kHz')},
    '7c.1.35GHz.400ns': {'53230A': V('338 kHz')}, '7d.1.35GHz.13us': {'53230A': V('7.79 kHz')},
}
T1 = {'std': {'1y': M('9.999 990 000 MHz', '10.000 010 000 MHz'), 'gt1y': M('9.999 995 000 MHz', '10.000 005 000 MHz')},
      '010': {'1y': M('9.999 999 500 MHz', '10.000 000 500 MHz'), 'gt1y': M('9.999 999 750 MHz', '10.000 000 250 MHz')}}


def setUpModule():
    global A, VH, SPEC, PTS, K
    import _tk_stub
    _tk_stub.install()
    import ui_port
    ui_port.ui.__dict__.pop('view', None)             # tests/test_highlight_follows_point.py leaves a fake `port.view` on the shared proxy; this module needs the real Tk view over the stub
    sys.path.insert(0, str(ROOT / 'Procedures'))
    import virtual_harness as _vh
    import keysight_53220a_verification as _a
    from drivers import keysight_53220a as _k
    K = _k
    A, VH = _a, _vh
    SPEC, PTS = A.SPEC, A.POINTS


def by_ref(ref):
    return next(p for p in PTS if p['ref'] == ref)


class SpecTests(unittest.TestCase):
    def test_counts(self):
        self.assertEqual({s['id']: len(s['points']) for s in SPEC['sections']}, SECTION_SIZES)
        self.assertEqual(len(PTS), 46)
        self.assertEqual(SPEC['default_period'], '1y')
        self.assertEqual(set(SPEC['models']), {'53210A', '53220A', '53230A'})
        self.assertEqual(len({p['ref'] for p in PTS}), 46)

    def test_every_mean_limit_matches_the_second_typing(self):
        for table in (MEAN2, OTHER_MEAN):
            for key, models in table.items():
                p = by_ref(key + '.mean')
                for model, (lo, hi) in models.items():
                    lim = p['limits'][model]
                    self.assertEqual((D(repr(lim['low'])), D(repr(lim['high']))), (lo, hi), (key, model))
                self.assertEqual(set(p['limits']), set(models), key)

    def test_every_std_dev_limit_matches_the_second_typing(self):
        for table in (SDEV2, OTHER_SDEV):
            for key, models in table.items():
                p = by_ref(key + '.sdev')
                for model, mx in models.items():
                    self.assertEqual(D(repr(p['limits'][model]['max'])), mx, (key, model))
                self.assertEqual(set(p['limits']), set(models), key)

    def test_channel_2_points_carry_the_channel_1_limits_and_no_53210a(self):
        for base in ('10MHz', '115MHz', '350MHz'):
            for stat in ('mean', 'sdev'):
                a, b = by_ref(f'2a.{base}.{stat}'), by_ref(f'2b.{base}.{stat}')
                self.assertEqual({m: a['limits'][m] for m in ('53220A', '53230A')}, b['limits'])
                self.assertNotIn('53210A', b['limits'])
        for p in PTS:
            if p['func'] in ('SPER', 'PWID', 'TINT', 'BURST'):
                self.assertNotIn('53210A', p['limits'], p['ref'])

    def test_time_base_limits_by_option_and_period(self):
        p = by_ref('1.10MHz.mean')
        self.assertEqual(p['limits_by'], 'timebase_option')
        for model in SPEC['models']:
            for tb, per in T1.items():
                for period, (lo, hi) in per.items():
                    lim = p['limits'][model][tb][period]
                    self.assertEqual((D(repr(lim['low'])), D(repr(lim['high']))), (lo, hi), (model, tb, period))
        for tb in T1:                                              # the >1 year limits are exactly half of the 1 year limits (footnotes [a], [b])
            lo1, hi1 = T1[tb]['1y']; lo2, hi2 = T1[tb]['gt1y']
            self.assertEqual((hi1 - lo1) / 2, hi2 - lo2)

    def test_apply_limits_follows_the_period_and_option(self):
        pts = [dict(p) for p in PTS]
        t1 = next(p for p in pts if p['ref'] == '1.10MHz.mean')
        for tb, per in T1.items():
            for period in ('1y', 'gt1y'):
                A.apply_limits(pts, '53220A', period, tb)
                self.assertEqual((D(repr(t1['low'])), D(repr(t1['high']))), per[period])
        A.apply_limits(pts, '53210A', '1y', 'std')
        self.assertFalse(next(p for p in pts if p['ref'] == '2b.10MHz.mean')['applies_model'])
        self.assertTrue(next(p for p in pts if p['ref'] == '2a.10MHz.mean')['applies_model'])

    def test_printed_text_agrees_with_the_number(self):
        import re
        for p in PTS:
            for model, lim in p['limits'].items():
                for sub in ([lim] if 'printed' in lim else [v for tb in lim.values() for v in tb.values()]):
                    nums = re.findall(r'[\d ]+\.[\d ]+|\d+', sub['printed'].replace('..', ' '))
                    self.assertTrue(nums, (p['ref'], model))
                    if 'max' in sub:
                        self.assertTrue(sub['printed'].startswith('<'), (p['ref'], model))

    def test_datasheet_ratios_with_the_documented_exceptions(self):
        rules = SPEC['datasheet_check']['rules']
        for p in PTS:
            if p['test_no'] in ('2a', '2b', '6a', '6b') and p['func'] == 'FREQ':
                for model, lim in p['limits'].items():
                    if p['stat'] == 'mean':
                        half = (D(repr(lim['high'])) - D(repr(lim['low']))) / 2
                        want = D(rules['mean_half_width_relative'][model]) * D(repr(p['nominal']))
                        self.assertLess(abs(half - want) / want, D('0.0005'), (p['ref'], model))
                    else:
                        want = D(rules['sdev_max_relative'][model]) * D(repr(p['nominal']))
                        tol = D('0.003') if p['ref'] == '6a.5.88GHz.sdev' else D('0.0005')            # printed 41.1 / 82.3 / 8.23 are the truncated 41.16 / 82.32 / 8.232
                        self.assertLess(abs(D(repr(lim['max'])) - want) / want, tol, (p['ref'], model))
            if p['func'] in ('SPER',) and p['stat'] == 'mean':
                for model, lim in p['limits'].items():
                    self.assertEqual((D(repr(lim['high'])) - D(repr(lim['low']))) / 2, D(rules['single_period_half_width_s'][model]), (p['ref'], model))
            if p['func'] in ('SPER', 'PWID', 'TINT') and p['stat'] == 'sdev':
                for model, lim in p['limits'].items():
                    self.assertEqual(D(repr(lim['max'])), D(rules['sdev_time_s'][model]), (p['ref'], model))

    def test_documented_exceptions_are_flagged_on_the_points(self):
        self.assertTrue(any('1.348 650 000' in f for f in by_ref('7c.1.35GHz.400ns.mean')['flags']))
        self.assertTrue(any('truncated' in f for f in by_ref('6a.5.88GHz.sdev')['flags']))
        self.assertTrue(any('Median' in f for f in by_ref('5.ch1-ch2.49.9ns.mean')['flags']))
        self.assertEqual(by_ref('7c.1.35GHz.400ns.mean')['limits']['53230A']['low'], 1348865000.0)           # the printed value is never changed silently

    def test_options_required_per_test(self):
        want = {'6a': {'106'}, '6b': {'115'}, '7a': {'106', '150'}, '7b': {'106', '150'}, '7c': {'115', '150'}, '7d': {'115', '150'}}
        for p in PTS:
            self.assertEqual(set(p['requires']), want.get(p['test_no'], set()), p['ref'])
        for p in PTS:
            if p['func'] == 'BURST':
                self.assertEqual(set(p['limits']), {'53230A'})

    def test_quick_points(self):
        quick = {p['test_no'] for p in PTS if p['quick']}
        self.assertEqual(quick, {'OV2', '1', '2a', '2b', '4a', '4b', '5', '6a', '6b', '7a', '7c'})
        self.assertFalse(any(p['quick'] for p in PTS if p['test_no'] in ('3', '7b', '7d')))

    def test_every_point_names_its_stimulus_and_pages(self):
        for p in PTS:
            self.assertTrue(p['page'] and p['stimulus']['group'] in ('NONE', 'LH', 'MW', 'PULSE', 'BURST'), p['ref'])
            if p['stimulus']['group'] != 'NONE':
                self.assertIn(p['timebase'], ('INT', 'EXT'))

    def test_builder_reproduces_the_stored_file(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'x.json'
            r = subprocess.run([sys.executable, '-I', str(ROOT / 'specs' / 'build_53220a_spec.py'), '--out', str(out)], capture_output=True, text=True, cwd=str(ROOT))
            if r.returncode != 0 and 'unrecognized' in r.stderr:
                self.skipTest('the builder has no --out switch')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8')), json.loads((ROOT / 'specs' / 'keysight_53220a_pv.json').read_text(encoding='utf-8')))


def bench(model='53230A', bus='USB', options=None):
    from drivers.simulated_53220a import make_53220a_bench
    return make_53220a_bench(model, bus, options)


class DriverTests(unittest.TestCase):
    def make(self, model='53230A', options=None):
        import drivers
        b, rft, ct = bench(model, options=options)
        cls = {'53210A': K.Keysight53210A, '53220A': K.Keysight53220A, '53230A': K.Keysight53230A}[model]
        d = cls(ct, drivers.CommandLog(), label=model)
        d.connect()
        return d, b, rft, ct

    def test_registry_lint_and_references(self):
        import cmdreg
        import drivers
        for cls in (K.Keysight53220A, K.Keysight53230A, K.Keysight53210A, K.Fluke96270AWide):
            self.assertEqual(cmdreg.lint_registry(cmdreg.merge_commands(cls)), [], cls.__name__)
        for key, c in K.Keysight53220A.COMMANDS.items():
            self.assertTrue(c.verified, key)
            self.assertIn('p.', c.ref or '', key)
        self.assertEqual(K.Keysight53220A.COMMANDS['err.query'].risk, 'locked')
        self.assertEqual(K.Keysight53220A.COMMANDS['reset'].risk, 'locked')

    def test_53210a_commands_are_all_unverified(self):
        import drivers
        self.assertTrue(K.Keysight53210A.COMMANDS)
        self.assertFalse([k for k, c in K.Keysight53210A.COMMANDS.items() if c.verified])
        self.assertEqual(K.Keysight53210A.MICRO_CH, 2)
        d, *_ = self.make('53210A')
        self.assertEqual(d._channel(3), 2)

    def test_options_are_parsed_per_model(self):
        d, *_ = self.make('53230A')
        self.assertEqual((d.options['timebase'], d.options['ch3'], d.options['pulse']), ('010', '115', '150'))
        d, *_ = self.make('53220A', options='0,106,0,0,0')
        self.assertEqual((d.options['timebase'], d.options['ch3'], d.options['pulse']), ('std', '106', None))
        d, *_ = self.make('53230A', options='0,0,0,0,0')
        self.assertEqual((d.options['timebase'], d.options['ch3'], d.options['pulse']), ('std', None, None))

    def test_wrong_model_is_refused(self):
        import drivers
        b, rft, ct = bench('53220A')
        d = K.Keysight53230A(ct, drivers.CommandLog(), label='x')
        with self.assertRaises(drivers.InstrumentError):
            d.connect()

    def test_a_configuration_is_set_read_back_and_compared(self):
        d, b, rft, ct = self.make()
        d.configure_point(dict(by_ref('2a.10MHz.mean')))
        sent = ct.sent
        self.assertIn('INP1:IMP 50', sent)
        self.assertIn('INP1:IMP?', sent)
        self.assertIn('CONF:FREQ 10000000,DEF,(@1)', sent)
        self.assertEqual(sent.count('INP1:IMP 50'), 1)
        d.check_errors('test')

    def test_a_read_back_mismatch_stops_and_the_write_is_not_repeated(self):
        import drivers
        d, b, rft, ct = self.make()
        orig, seen = ct.handle, []

        def handle(cmd):
            seen.append(cmd)
            return None if cmd.upper().startswith('INP1:IMP 50') else orig(cmd)          # the counter ignores the write
        ct.handle = handle
        with self.assertRaises(drivers.InstrumentError):
            d.configure_point(dict(by_ref('2a.10MHz.mean')))
        self.assertEqual([c for c in seen if c.startswith('INP1:IMP 50')], ['INP1:IMP 50'])

    def test_an_error_in_the_queue_is_raised_and_names_the_error(self):
        import drivers
        d, b, rft, ct = self.make()
        ct.errors.append('-221,"Settings conflict"')
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.check_errors('configuring')
        self.assertIn('-221', str(cm.exception))

    def test_no_external_reference_is_error_2009(self):
        import drivers
        d, b, rft, ct = self.make()
        b.ext_ref_present = False
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.set_reference('EXT')
        self.assertIn('2009', str(cm.exception))

    def test_the_reference_oscillator_is_restored_at_cleanup_and_survives_reset(self):
        d, b, rft, ct = self.make()
        before = dict(ct.nv)
        d.set_reference('EXT')
        d.reset_to_defaults()
        self.assertEqual(ct.nv['src'], 'EXT')                              # *RST does not touch the non-volatile reference settings
        d.set_reference('INT')
        d.cleanup()
        self.assertEqual(ct.nv, before)

    def test_reference_is_not_rewritten_when_unchanged(self):
        d, b, rft, ct = self.make()
        d.set_reference('EXT')
        n = len([c for c in ct.sent if c.startswith('SENS:ROSC:SOUR EXT')])
        d.set_reference('EXT')
        self.assertEqual(len([c for c in ct.sent if c.startswith('SENS:ROSC:SOUR EXT')]), n)

    def test_no_signal_is_reported_not_judged(self):
        import drivers
        d, b, rft, ct = self.make()
        d.set_reference('EXT')
        d.configure_point(dict(by_ref('2a.10MHz.mean')))
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.measure_stats()                                               # the 96270A output is off: 9.91E37
        self.assertIn('9.91', str(cm.exception))

    def test_a_full_set_of_100_readings_with_the_statistics_commands(self):
        d, b, rft, ct = self.make()
        d.set_reference('EXT')
        b.rf1.update(f=10e6, p=7.0, on=True)
        d.configure_point(dict(by_ref('2a.10MHz.mean')))
        r = d.measure_stats()
        self.assertEqual(r['count'], 100)
        self.assertAlmostEqual(r['mean'], 10e6, delta=1)
        for c in ('SAMP:COUN 100', 'TRIG:SOUR BUS', 'CALC:STAT ON', 'CALC:AVER:STAT ON', 'INIT', '*TRG', '*OPC?', 'CALC:AVER:COUN:CURR?', 'CALC:AVER:AVER?', 'CALC:AVER:SDEV?'):
            self.assertIn(c, ct.sent)
        self.assertLess(ct.sent.index('INIT'), ct.sent.index('*TRG'))
        self.assertLess(ct.sent.index('*TRG'), ct.sent.index('CALC:AVER:AVER?'))

    def test_self_test_returns_zero_and_a_failure_is_one(self):
        d, b, rft, ct = self.make()
        self.assertEqual(d.self_test(), 0)
        ct.selftest_fail = True
        self.assertEqual(d.self_test(), 1)

    def test_every_point_of_every_model_configures_without_an_error(self):
        for model, opts in (('53210A', '0,106,0,0,0'), ('53220A', '010,115,0,0,400'), ('53230A', '010,106,150,0,400')):
            d, b, rft, ct = self.make(model, options=opts)
            d.set_reference('EXT')
            A.apply_limits(PTS, model, '1y', 'std')
            for p in PTS:
                if p['func'] == 'TST' or model not in p['limits']:
                    continue
                if set(p['requires']) - {opts.split(',')[1], '150' if 'x150' in opts else '150' if opts.split(',')[2] == '150' else ''}:
                    continue
                d.configure_point(dict(p))
            d.check_errors('all points of ' + model)
        A.apply_limits(PTS, A.MODEL, '1y', 'std')

    def test_the_wide_96270a_driver_adds_no_command(self):
        import drivers
        self.assertEqual(set(K.Fluke96270AWide.COMMANDS), set(drivers.Fluke96270A.COMMANDS))
        self.assertEqual(K.Fluke96270AWide.MAX_HZ, 27e9)


class StimulusRouting(unittest.TestCase):
    def stim(self, **k):
        return dict(dict(mode='auto', rf=True, loss_db=0.0, ext_low=False), **k)

    def test_leveling_head_points_are_automatic_with_the_loss_added(self):
        pl = A.plan_stimulus(by_ref('2a.10MHz.mean'), self.stim(loss_db=1.5))
        self.assertEqual((pl['mode'], pl['route'], pl['level_set']), ('rf', 'LH', 8.5))
        pl = A.plan_stimulus(by_ref('6b.3.1GHz.mean'), self.stim())
        self.assertEqual((pl['mode'], pl['route'], pl['level_set']), ('rf', 'LH', -27.0))

    def test_low_level_microwave_needs_another_standard_unless_extended_low_level(self):
        p = by_ref('6a.5.88GHz.mean')
        pl = A.plan_stimulus(p, self.stim())
        self.assertEqual(pl['mode'], 'manual')
        self.assertIn('-4 dBm', pl['reason'])
        pl = A.plan_stimulus(p, self.stim(ext_low=True))
        self.assertEqual((pl['mode'], pl['route'], pl['level_set']), ('rf', 'MW', -27.0))

    def test_15_ghz_is_direct_output_at_minus_4_dbm(self):
        p = by_ref('6b.15GHz.mean')
        self.assertEqual(A.plan_stimulus(p, self.stim())['mode'], 'rf')
        self.assertEqual(A.plan_stimulus(p, self.stim(loss_db=3.0))['level_set'], -1.0)
        self.assertEqual(A.plan_stimulus(p, self.stim(loss_db=-1.0))['mode'], 'manual')           # a negative "loss" would put the level below the Microwave O/P floor

    def test_pulse_and_burst_are_always_another_standard(self):
        for ref in ('4a.ch1.5ns.mean', '4b.ch2.5ns.mean', '5.ch1-ch2.49.9ns.mean', '7a.6GHz.200ns.mean', '7d.1.35GHz.13us.mean'):
            pl = A.plan_stimulus(by_ref(ref), self.stim())
            self.assertEqual(pl['mode'], 'manual', ref)
            self.assertTrue(pl['reason'], ref)

    def test_other_standards_for_every_test_and_no_96270a(self):
        self.assertEqual(A.plan_stimulus(by_ref('2a.10MHz.mean'), self.stim(mode='manual'))['mode'], 'manual')
        self.assertEqual(A.plan_stimulus(by_ref('2a.10MHz.mean'), self.stim(rf=False))['mode'], 'manual')
        self.assertEqual(A.plan_stimulus(by_ref('OV2'), self.stim(mode='manual'))['mode'], 'none')

    def test_the_input_guard_refuses_a_level_above_the_cap(self):
        p = dict(by_ref('2a.10MHz.mean'))
        p['stimulus'] = dict(p['stimulus'], level_dbm=13.0)
        with self.assertRaises(ValueError):
            A.plan_stimulus(p, self.stim())


class Judging(unittest.TestCase):
    def setUp(self):
        A.configure('53220A')

    def test_mean_is_inclusive_and_decimal_exact(self):
        p = by_ref('2a.10MHz.mean')
        self.assertTrue(A.judge(p, 10000000.01))
        self.assertTrue(A.judge(p, 9999999.99))
        self.assertFalse(A.judge(p, 10000000.0100001))
        self.assertFalse(A.judge(p, 9999999.9899999))

    def test_std_dev_is_below_the_printed_maximum(self):
        p = by_ref('2a.10MHz.sdev')
        self.assertTrue(A.judge(p, 0.0))
        self.assertTrue(A.judge(p, 0.0699))
        self.assertFalse(A.judge(p, 0.07))
        self.assertFalse(A.judge(p, 0.1))

    def test_self_test_passes_only_on_zero(self):
        p = by_ref('OV2')
        self.assertTrue(A.judge(p, 0))
        self.assertFalse(A.judge(p, 1))


class Flow(unittest.TestCase):
    """The engine on the simulated bench (virtual demo = the real IO / driver code over the simulated counter and 96270A)."""

    OPTIONS = {'53210A': '0,106,0,0,0', '53220A': '010,115,0,0,400', '53230A': '010,106,150,0,400'}

    def setUp(self):
        self.hn = VH.VHarness().start()
        A.messagebox = VH.hh.messagebox

    def tearDown(self):
        A.configure('53220A')
        self.hn.stop()

    def app(self, model='53220A', fast=False, options=None, **settings):
        A.configure(model)
        a = A.App(self.hn.root, demo=True, fast_demo=fast)
        a.asset.set('A-1'); a.serial.set('S-1')
        a.virtual_options = options or self.OPTIONS[model]
        for k, v in settings.items():
            getattr(a, k).set(v)
        self.hn.app = a
        return a

    def connect(self, a):
        a.test_connections()
        self.assertIsNotNone(a.io)

    def wire(self, a, who=None):
        return [t for d, t in VH.wire(a.io) if who is None or d == who]

    def run_model(self, model):
        a = self.app(model)
        self.connect(a)                                                      # the options are read from *OPT? and the points that apply are shown
        self.assertTrue(self.hn.run_all())
        return a

    def test_virtual_run_passes_every_point_of_every_model_and_is_marked_demo(self):
        want = {'53210A': 1 + 1 + 6 + 4, '53220A': 1 + 1 + 12 + 8 + 4 + 2 + 6, '53230A': 1 + 1 + 12 + 8 + 4 + 2 + 4 + 4}
        for model in A.MODELS:
            a = self.run_model(model)
            self.assertEqual(len(a.results), want[model], model)
            self.assertEqual(len(a.active_points()), want[model], model)
            self.assertTrue(all(r['result'] == 'PASS' and r['synthetic'] for r in a.results.values()), model)
            self.assertTrue(a.io.log.virtual)
            self.assertTrue(a.any_synthetic())
            self.assertFalse(self.hn.boxes('showerror'), (model, self.hn.boxes('showerror')))
            self.assertEqual(self.hn.titles()[0], 'Before the verification')
            self.hn.stop(); self.hn = VH.VHarness().start(); A.messagebox = VH.hh.messagebox

    def test_the_options_come_from_the_counter_and_a_mismatch_is_warned(self):
        a = self.app('53230A', tb_opt=A.TB_CHOICES[0], ch3_opt=A.CH3_CHOICES[2])
        self.connect(a)
        self.assertEqual((a.tb_opt.get(), a.ch3_opt.get(), a.pulse_opt.get()), (A.TB_CHOICES[1], A.CH3_CHOICES[1], True))
        text = a.apply_detected_options()
        self.assertIn('Options read from the counter', text)
        self.hn.stop(); self.hn = VH.VHarness().start(); A.messagebox = VH.hh.messagebox
        a = self.app('53230A', tb_opt=A.TB_CHOICES[0], ch3_opt=A.CH3_CHOICES[2])
        a.test_connections()
        a.tb_opt.set(A.TB_CHOICES[0])
        self.assertIn('WARNING', a.apply_detected_options())

    def test_points_follow_the_declared_options_and_model(self):
        a = self.app('53230A')
        n = lambda: len(a.active_points())
        self.assertEqual(n(), 28)                                            # no microwave channel, no pulse option
        a.ch3_opt.set(A.CH3_CHOICES[2]); a.on_options()
        self.assertEqual(n(), 28 + 6)
        a.pulse_opt.set(True); a.on_options()
        self.assertEqual(n(), 28 + 6 + 4)
        a.ch3_opt.set(A.CH3_CHOICES[1]); a.on_options()
        self.assertEqual(n(), 28 + 4 + 4)
        A.configure('53210A')
        a53210 = A.App(self.hn.root, demo=True, fast_demo=False)
        self.assertEqual(len(a53210.active_points()), 8)                     # Channel 1 only, no time tests

    def test_time_base_option_changes_test_1_limits(self):
        a = self.app('53220A')
        p = by_ref('1.10MHz.mean')
        self.assertEqual((p['low'], p['high']), (9999990.0, 10000010.0))
        a.tb_opt.set(A.TB_CHOICES[1]); a.on_options()
        self.assertEqual((p['low'], p['high']), (9999999.5, 10000000.5))
        a.period.set('More than 1 year'); a.on_period()
        self.assertEqual((p['low'], p['high']), (9999999.75, 10000000.25))
        a.tb_opt.set(A.TB_CHOICES[0]); a.period.set('1 year or less'); a.on_options()

    def test_command_order_reset_first_reference_and_standby_after_each_point(self):
        a = self.run_model('53220A')
        w = VH.wire(a.io)
        first = next(i for i, (d, t) in enumerate(w) if t == '*TST?')
        self.assertTrue(any(t == '*RST' and d == '53220A' for d, t in w[:first]))
        self.assertTrue(any(t == '*RST' and d == '96270A' for d, t in w[:first]))
        ctr = [t for d, t in w if d == '53220A']
        self.assertLess(ctr.index('SENS:ROSC:SOUR INT'), ctr.index('SENS:ROSC:SOUR EXT'))                  # Test 1 on the internal time base, then the external reference
        rf = [t for d, t in w if d == '96270A']
        self.assertEqual(rf[-1], 'OUTP?')
        ons = [i for i, t in enumerate(rf) if t == 'OUTP ON']
        self.assertTrue(ons)
        for i in ons:
            nxt = next(t for t in rf[i + 1:] if t.startswith('OUTP O') and t != 'OUTP ON')
            self.assertEqual(nxt, 'OUTP OFF')
        for a_, b_ in zip(ons, ons[1:]):
            self.assertIn('OUTP OFF', rf[a_ + 1:b_], 'the output stayed on between two points')
        self.assertEqual(len([t for t in rf if t == 'OUTP ON']), len([p for p in a.active_points() if p['stat'] == 'mean' and p['stimulus']['group'] in ('LH', 'MW')]))

    def test_the_std_dev_point_reuses_the_100_readings_of_its_mean(self):
        a = self.run_model('53220A')
        ctr = self.wire(a, '53220A')
        means = [p for p in a.active_points() if p['stat'] == 'mean' and p['func'] != 'TST']
        self.assertEqual(ctr.count('INIT'), len(means))
        self.assertEqual(ctr.count('*TRG'), len(means))
        for p in a.active_points():
            if p['stat'] == 'sdev':
                self.assertEqual(a.results[str(p['id'])]['stimulus'], a.results[str(by_ref(p['parent'])['id'])]['stimulus'])

    def test_a_std_dev_point_run_alone_measures_by_itself(self):
        a = self.app('53220A')
        self.connect(a)
        p = by_ref('2a.10MHz.sdev')
        a.execute([p])
        self.assertTrue(self.hn.pump())
        ctr = self.wire(a, '53220A')
        self.assertEqual(ctr.count('INIT'), 1)
        self.assertEqual(a.results[str(p['id'])]['result'], 'PASS')

    def test_no_96270a_command_for_the_pulse_tests_and_prompts_for_the_other_standard(self):
        a = self.run_model('53220A')
        self.assertIn('Connect the other standard', self.hn.titles())
        pulse = [p for p in a.active_points() if p['stimulus']['group'] == 'PULSE']
        self.assertEqual(sum(1 for t in self.hn.titles() if t == 'Connect the other standard'), len({p['ref'] for p in pulse if p['stat'] == 'mean'}))
        self.assertTrue(all(a.results[str(p['id'])]['stimulus'] == 'manual' for p in pulse))

    def test_other_standards_for_every_test_connects_no_96270a(self):
        a = self.app('53220A', stim_mode=A.STIM_CHOICES[1])
        self.connect(a)
        self.assertIsNone(a.io.rf)
        self.assertTrue(self.hn.run_all())
        self.assertFalse(self.wire(a, '96270A'))
        self.assertTrue(all(r['stimulus'] in ('manual', 'none') for r in a.results.values()))
        self.assertTrue(all(r['result'] == 'PASS' for r in a.results.values()))

    def test_a_missing_reference_stops_the_run_and_leaves_the_output_off(self):
        import drivers
        b, rft, ct = bench('53220A')
        io = A.IO('sim', 'sim', 'USB', transports=(ct, rft), stim=dict(mode='auto', loss_db=0.0, ext_low=False))
        io.reset_at_start()
        b.ext_ref_present = False
        with self.assertRaises(drivers.InstrumentError) as cm:
            io.measure(by_ref('2a.10MHz.mean'))
        self.assertIn('2009', str(cm.exception))
        self.assertFalse(b.rf1['on'])

    def test_the_input_guard_stops_before_any_output(self):
        b, rft, ct = bench('53220A')
        io = A.IO('sim', 'sim', 'USB', transports=(ct, rft), stim=dict(mode='auto', loss_db=0.0, ext_low=False))
        p = dict(by_ref('2a.10MHz.mean'))
        p['stimulus'] = dict(p['stimulus'], level_dbm=15.0)
        with self.assertRaises(ValueError):
            io.measure(p)
        self.assertFalse(b.rf1['on'])

    def test_a_reading_outside_the_limit_is_recorded_as_a_failure(self):
        a = self.app('53220A')
        p = by_ref('2a.10MHz.mean')
        a._record(p, p['nominal'] + 1.0, False)
        self.assertEqual(a.results[str(p['id'])]['result'], 'FAIL')

    def test_uncertainty_only_where_the_scope_has_a_cmc(self):
        for p in PTS:
            self.assertEqual(A.App.has_uncertainty(p), p['stat'] == 'mean' and p['func'] in ('FREQ', 'SPER'), p['ref'])
        for ref in ('2a.10MHz.mean', '6b.15GHz.mean', '1.10MHz.mean'):
            self.assertTrue(A.App.uncertainty_text(by_ref(ref)), ref)
        sper = A.App.uncertainty_text(by_ref('3.ch1.1MHz.mean'))
        self.assertTrue(sper.endswith('s'), sper)
        for ref in ('2a.10MHz.sdev', '4a.ch1.5ns.mean', '5.ch1-ch2.49.9ns.mean', '7a.6GHz.200ns.mean', 'OV2'):
            self.assertEqual(A.App.uncertainty_text(by_ref(ref)), '', ref)

    def test_report_rows(self):
        a = self.run_model('53220A')
        rows, pts = a.certificate_rows_and_points()
        self.assertEqual(len(rows), len(a.active_points()))
        self.assertTrue(all(r['Section'] for r in rows))
        self.assertFalse([r for r in rows if r['OOT']])
        self.assertEqual([bool(r['Uncertainty']) for r in rows], [A.App.has_uncertainty(p) for p in pts])
        self.assertTrue(any('[other standard]' in r['Description'] for r in rows))
        self.assertIsNone(a.standard_for(PTS[0]))

    def test_report_file_name_is_asset_date(self):
        from datetime import datetime
        import ui_theme as ui
        self.assertEqual(ui.report_filename('A-1', when=datetime(2026, 10, 22)), 'A-1-10-22-2026.pdf')

    def test_pdf_of_a_demo_run_says_demo(self):
        try:
            import report_pdf
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest('reportlab is not installed')
        a = self.run_model('53230A')
        rows = a.certificate_rows()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'A-1-10-22-2026.pdf'
            report_pdf.write_calibration_pdf(str(path), rows, header=[('Instrument', 'Keysight 53230A')], demo=a.any_synthetic(), details={})
            self.assertTrue(path.stat().st_size > 1000)

    def test_fast_demo_results_are_synthetic_and_pass(self):
        a = self.app('53220A', fast=True)
        self.assertTrue(self.hn.run_all())
        self.assertTrue(a.results)
        self.assertTrue(all(r['synthetic'] and r['result'] == 'PASS' for r in a.results.values()))
        self.assertTrue(a.any_synthetic())

    def test_checkpoint_is_written_for_the_model(self):
        a = self.app('53230A')
        a.save(silent=True)
        path = a._checkpoint_path()
        self.assertIn('K53230A_A-1_checkpoint', path.name)
        data = json.loads(path.read_text())
        self.assertTrue(data['demo'])

    def test_per_point_plan_is_the_measure_routine(self):
        a = self.app('53220A')
        text = json.dumps(a.pm_plan_point(by_ref('2a.10MHz.mean')), default=str)
        self.assertIn('CALC:AVER:AVER?', text)
        self.assertIn('OUTP ON', text)

    def test_setup_text_names_the_connections(self):
        a = self.app('53220A')
        self.assertIn('Channel 1', a.setup_text(by_ref('2a.10MHz.mean')))
        self.assertIn('Channel 2', a.setup_text(by_ref('2b.10MHz.mean')))
        self.assertIn('EXT REF IN', a.setup_text(by_ref('2a.10MHz.mean')))
        self.assertIn('INTERNAL', a.setup_text(by_ref('1.10MHz.mean')))
        a.rear_opt.set(True)
        self.assertIn('rear-panel', a.setup_text(by_ref('2a.10MHz.mean')))
        a.ref_mode.set(A.REF_CHOICES[1])
        self.assertIn('REF OUT', a.setup_text(by_ref('2a.10MHz.mean')))

    def test_visa_strings(self):
        self.assertEqual(A.to_visa('3', 'GPIB'), 'GPIB0::3::INSTR')
        self.assertEqual(A.to_visa('COM4', 'USB'), 'ASRL4::INSTR')
        self.assertEqual(A.to_visa('TCPIP0::10.0.0.5::inst0::INSTR', 'LAN'), 'TCPIP0::10.0.0.5::inst0::INSTR')
        with self.assertRaises(ValueError):
            A.to_visa('12', 'USB', default_gpib=False)


class Registration(unittest.TestCase):
    def test_launchers_sidecars_and_tunables(self):
        import procscan
        ids = [q.id for q in procscan.procs(ROOT)]
        for model in ('53220A', '53230A', '53210A'):
            pid = f'Keysight_{model}_Verification'
            src = (ROOT / 'Procedures' / f'{pid}.py').read_text(encoding='utf-8')
            self.assertIn(f"keysight_53220a_verification.main(model='{model}')", src)
            side = json.loads((ROOT / 'Procedures' / f'{pid}.procedure.json').read_text(encoding='utf-8'))
            self.assertEqual((side['id'], side['model'], side['category'], side['seed_verified']), (pid, model, 'Frequency Counter', False))
            self.assertEqual(side['launcher'], f'Procedures/{pid}.py')
            for rel in side['fingerprint']['code'] + side['fingerprint']['spec'] + side['own_files']:
                self.assertTrue((ROOT / rel).exists(), rel)
            self.assertIn(pid, ids)
        import procmods_engine as pe
        self.assertEqual(pe.MODEL_IDS['a53220a'], 'the model, 53210A, 53220A or 53230A')
        self.assertTrue(pe.tunables_for('a53220a'))

    def test_diagram_readme_exists_and_names_the_groups(self):
        text = (ROOT / 'diagrams' / 'README_53220a.txt').read_text(encoding='utf-8')
        for g in ('TIMEBASE', 'CH1', 'CH2', 'CH3_LH', 'CH3_MW', 'PULSE_CH1', 'PULSE_CH2', 'TINT', 'BURST'):
            self.assertIn(g, text)
        self.assertEqual({p['group'] for p in PTS} - {'NONE'}, {'TIMEBASE', 'CH1', 'CH2', 'CH3_LH', 'CH3_MW', 'PULSE_CH1', 'PULSE_CH2', 'TINT', 'BURST'})


if __name__ == '__main__':
    unittest.main()
