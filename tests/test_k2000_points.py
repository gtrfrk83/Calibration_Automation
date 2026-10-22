"""Keithley Model 2000 verification (keithley2000_verification.py, drivers/keithley_2000.py, specs/keithley_2000_pv.json).

Part 1: the spec: counts per section, a SECOND typing of every limit (independent of specs/build_k2000_spec.py, which recomputes each half-width from the one-year
accuracy specification and aborts on a disagreement), the printed limit text against the numeric limit (Decimal), the builder reproducing the stored file.
Part 2: the driver on the simulated 2000 (GPIB and RS-232): the command registry (page references, verified flags, the unverified list), set / read back /
compare, a write is never retried, REL, overflow, the error queue, the INPUTS switch, remote / local, the 5522A ZCOMP command.
Part 3: the engine (keithley2000_verification.IO and App) on the simulated bench: command order, explicit 0 Hz, standby after each point, REL once, the resistance
compensation, high-voltage and hook-up prompts, the 700 V option, set-up refusal paths, Decimal judging, report rows (negative nominals), TAR / TUR, demo, registration.
tkinter is stubbed in setUpModule (not at import time), like tests/test_170_points.py.
Run:  python -m unittest tests.test_k2000_points"""
import json
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

K = VH = SPEC = PTS = None
SCALE = {'mV': D('0.001'), 'V': D(1), 'mA': D('0.001'), 'A': D(1), 'ohm': D(1), 'kohm': D(1000), 'Mohm': D(1000000)}

# --- every limit (half-width, 1 year) read a second time from the printed tables: id -> (kind, nominal, range, frequency, half-width, group)
LIMITS = {
    1: ('DCV', '0.1', '0.1', None, '0.0000085', 'DCV'), 2: ('DCV', '-0.1', '0.1', None, '0.0000085', 'DCV'),
    3: ('DCV', '1', '1', None, '0.000037', 'DCV'), 4: ('DCV', '-1', '1', None, '0.000037', 'DCV'),
    5: ('DCV', '10', '10', None, '0.00035', 'DCV'), 6: ('DCV', '-10', '10', None, '0.00035', 'DCV'),
    7: ('DCV', '100', '100', None, '0.0051', 'DCV'), 8: ('DCV', '-100', '100', None, '0.0051', 'DCV'),
    9: ('DCV', '1000', '1000', None, '0.061', 'DCV'), 10: ('DCV', '-1000', '1000', None, '0.061', 'DCV'),
    11: ('ACV', '0.1', '0.1', 1000, '0.00009', 'ACV'), 12: ('ACV', '0.1', '0.1', 50000, '0.00017', 'ACV'),
    13: ('ACV', '1', '1', 1000, '0.0009', 'ACV'), 14: ('ACV', '1', '1', 50000, '0.0017', 'ACV'),
    15: ('ACV', '10', '10', 1000, '0.009', 'ACV'), 16: ('ACV', '10', '10', 50000, '0.017', 'ACV'),
    17: ('ACV', '100', '100', 1000, '0.09', 'ACV'), 18: ('ACV', '100', '100', 50000, '0.17', 'ACV'),
    19: ('ACV', '700', '750', 1000, '0.645', 'ACV'), 20: ('ACV', '219', '750', 50000, '0.638', 'ACV'),
    21: ('ACV', '700', '750', 50000, '1.215', 'ACV700'),
    22: ('DCI', '0.01', '0.01', None, '0.0000058', 'DCI'), 23: ('DCI', '-0.01', '0.01', None, '0.0000058', 'DCI'),
    24: ('DCI', '0.1', '0.1', None, '0.00013', 'DCI'), 25: ('DCI', '-0.1', '0.1', None, '0.00013', 'DCI'),
    26: ('DCI', '1', '1', None, '0.00088', 'DCI'), 27: ('DCI', '-1', '1', None, '0.00088', 'DCI'),
    28: ('DCI', '2.2', '3', None, '0.00276', 'DCI'), 29: ('DCI', '-2.2', '3', None, '0.00276', 'DCI'),
    30: ('ACI', '1', '1', 1000, '0.0014', 'ACI'), 31: ('ACI', '2.2', '3', 1000, '0.0051', 'ACI'),
    32: ('OHM4', '100', '100', None, '0.014', 'OHM4'), 33: ('OHM4', '1000', '1000', None, '0.11', 'OHM4'),
    34: ('OHM4', '10000', '10000', None, '1.1', 'OHM4'), 35: ('OHM4', '100000', '100000', None, '11', 'OHM4'),
    36: ('OHM4', '1000000', '1000000', None, '110', 'OHM4'), 37: ('OHM4', '10000000', '10000000', None, '4100', 'OHM4'),
    38: ('OHM4', '100000000', '100000000', None, '153000', 'OHM100M'),
}
SECTION_SIZES = {'dcv': 10, 'acv': 10, 'acv700': 1, 'dci': 8, 'aci': 2, 'ohm4': 6, 'ohm100m': 1}


def setUpModule():
    global K, VH, SPEC, PTS
    import _tk_stub
    _tk_stub.install()
    sys.path.insert(0, str(ROOT / 'Procedures'))
    import virtual_harness as _vh
    import keithley2000_verification as _k
    K, VH = _k, _vh
    SPEC, PTS = K.SPEC, K.POINTS


def printed_to_base(text):
    """'99.9915 to 100.0085 mV' -> (Decimal low, Decimal high) in base units."""
    low, _to, high, unit = text.split()
    return D(low) * SCALE[unit], D(high) * SCALE[unit]


class SpecTests(unittest.TestCase):
    def test_counts(self):
        self.assertEqual({s['id']: len(s['points']) for s in SPEC['sections']}, SECTION_SIZES)
        self.assertEqual(len(PTS), 38)
        self.assertEqual(SPEC['periods'], ['1y'])
        self.assertEqual(SPEC['default_period'], '1y')

    def test_every_limit_is_typed_twice(self):
        self.assertEqual(set(LIMITS), {p['id'] for p in PTS})
        for p in PTS:
            kind, nominal, rng, freq, half, group = LIMITS[p['id']]
            self.assertEqual((p['kind'], D(str(p['nominal'])), D(str(p['range'])), p.get('frequency'), p['group']), (kind, D(nominal), D(rng), freq, group), p['id'])
            self.assertEqual(D(str(p['limits']['1y'])), D(half), f"point {p['id']}")

    def test_printed_text_matches_the_numbers(self):
        for p in PTS:
            low, high = printed_to_base(p['printed_limits'])
            nominal, half = D(str(p['nominal'])), D(str(p['limits']['1y']))
            tol = D(0)
            if p.get('computed_limit') is not None:          # 219 V @ 50 kHz: the printed text is the rounded value
                tol = D('0.0005')
            self.assertLessEqual(abs(low - (nominal - half)), tol, p['id'])
            self.assertLessEqual(abs(high - (nominal + half)), tol, p['id'])
            self.assertLess(low, high)

    def test_the_one_rounded_printed_value(self):
        rounded = [p for p in PTS if p.get('computed_limit') is not None]
        self.assertEqual([p['id'] for p in rounded], [20])
        self.assertEqual(D(str(rounded[0]['computed_limit'])), D('0.6378'))
        self.assertEqual(rounded[0]['variant'], 'alt219')

    def test_dc_points_come_in_plus_minus_pairs(self):
        for kind in ('DCV', 'DCI'):
            pts = [p for p in PTS if p['kind'] == kind]
            self.assertEqual(sorted(p['nominal'] for p in pts), sorted([-p['nominal'] for p in pts]))
            for p in pts:
                self.assertIsNone(p.get('frequency'))
                self.assertGreaterEqual(p['range'], abs(p['nominal']))

    def test_ranges_hold_the_signal_and_are_real_2000_ranges(self):
        real = {'DCV': (0.1, 1, 10, 100, 1000), 'ACV': (0.1, 1, 10, 100, 750), 'DCI': (0.01, 0.1, 1, 3), 'ACI': (1, 3),
                'OHM4': (1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8)}
        for p in PTS:
            self.assertIn(p['range'], real[p['kind']], p['id'])
            self.assertGreaterEqual(p['range'], abs(p['nominal']))
            if p['kind'] in ('ACV', 'ACI'):
                self.assertIn(p['frequency'], (1000.0, 50000.0))

    def test_the_700_volt_point_is_optional_and_by_hand(self):
        sec = next(s for s in SPEC['sections'] if s['id'] == 'acv700')
        self.assertTrue(sec['optional'])
        self.assertEqual(sec['source'], 'manual')
        p = next(q for q in PTS if q['id'] == 21)
        self.assertTrue(p['optional'] and p['source'] == 'manual')
        self.assertEqual(p['frequency'], 50000.0)

    def test_ohm_hundred_megohm_is_its_own_hookup_group(self):
        self.assertEqual({p['id'] for p in PTS if p['group'] == 'OHM100M'}, {38})

    def test_builder_reproduces_the_stored_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('build_k2000_spec', ROOT / 'specs' / 'build_k2000_spec.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(json.loads(json.dumps(mod.build())), json.loads((ROOT / 'specs' / 'keithley_2000_pv.json').read_text(encoding='utf-8')))

    def test_measurement_conditions_and_prep(self):
        m = SPEC['measure']
        self.assertEqual((m['nplc'], m['filter_state'], m['filter_count'], m['filter_type'], m['ac_bandwidth']), (1, 'ON', 10, 'REPeat', 30))
        z = SPEC['prep']['dcv_rel_zero']
        self.assertEqual((z['kind'], z['range'], z['nominal']), ('DCV', 0.1, 0.0))
        self.assertTrue(SPEC['general'])


def bench(cal='5522A', bus='GPIB'):
    from drivers.simulated_k2000 import make_k2000_bench
    return make_k2000_bench(cal, bus)


class DriverTests(unittest.TestCase):
    def make(self, cal='5522A', bus='GPIB'):
        import drivers
        _b, ft, dt = bench(cal, bus)
        d = drivers.Keithley2000(dt, drivers.CommandLog(), label='2000')
        d.connect()
        ft.open()
        return d, ft, dt

    def test_registry_lint_pages_and_verified_flags(self):
        import cmdreg
        import drivers
        from drivers import keithley_2000 as mod
        self.assertEqual(cmdreg.lint_registry(cmdreg.merge_commands(drivers.Keithley2000)), [])
        reg = mod.COMMANDS
        self.assertGreater(len(reg), 90)
        for key, cmd in reg.items():
            self.assertTrue(cmd.ref, f'{key} has no page reference')
            self.assertIsInstance(cmd.verified, bool)
        merged = cmdreg.merge_commands(drivers.Keithley2000)
        self.assertEqual((merged['reset'].template, merged['reset'].risk, merged['reset'].verified), ('*RST', 'locked', True))
        self.assertTrue(all(cmd.verified for k, cmd in reg.items() if k.startswith(('func.', 'range.', 'nplc.', 'band.', 'tcon.', 'count.', 'filter.', 'rel.')) and 'query' not in k))
        unverified = sorted(k for k, c in reg.items() if not c.verified)
        self.assertTrue(unverified)                                           # the read-back reply formats are not stated in the manual
        self.assertTrue(all(reg[k].kind == 'query' for k in unverified), 'only queries (reply formats) may be unverified')

    def test_connect_gpib_sends_no_remote_command_and_goes_local_with_gtl(self):
        d, _ft, dt = self.make(bus='GPIB')
        self.assertNotIn(':SYST:REM', dt.sent)
        d.local()
        self.assertNotIn(':SYST:LOC', dt.sent)

    def test_rs232_enters_remote_and_leaves_with_local(self):
        d, _ft, dt = self.make(bus='RS232')
        self.assertIn(':SYST:REM', dt.sent)
        d.cleanup()
        self.assertEqual(dt.sent[-1], ':SYST:LOC')

    def test_wrong_instrument_is_refused(self):
        import drivers
        from tests import golden_capture as gc
        t = gc.Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')])
        with self.assertRaises(drivers.InstrumentError):
            drivers.Keithley2000(t, drivers.CommandLog(), label='2000').connect()

    def test_configure_sets_reads_back_and_never_repeats_a_write(self):
        d, _ft, dt = self.make()
        mark = len(dt.sent)
        d.configure_point(dict(kind='ACV', range=10.0, ac_bandwidth=30))
        sent = dt.sent[mark:]
        writes = [c for c in sent if not c.endswith('?')]
        self.assertEqual(len(writes), len(set(writes)), 'a setting was written twice')
        self.assertEqual(writes[0], ":SENS:FUNC 'VOLT:AC'")
        self.assertIn(':SENS:VOLT:AC:DET:BAND 30', writes)
        self.assertNotIn('AUTO ON', ' '.join(sent))
        for w in writes:                                                      # every write is followed (not necessarily at once) by its query
            self.assertIn(w.split(' ')[0] + '?', ' '.join(sent).replace(w, w), w)
        # autorange is only ever asked about, never switched on; the range is a manual one
        self.assertIn(':SENS:VOLT:AC:RANG:AUTO?', sent)
        self.assertEqual(dt.cfg['VOLT:AC']['range'], 10.0)

    def test_a_failed_write_is_not_retried(self):
        import drivers
        b, ft, dt = bench()
        d = drivers.Keithley2000(dt, drivers.CommandLog(), label='2000')
        d.connect()
        b.fail_next = ':SENS:VOLT:DC:RANG'
        with self.assertRaises(Exception):
            d.configure_point(dict(kind='DCV', range=10.0, plc=1))
        attempts = [line for line in d.log.lines() if ':SENS:VOLT:DC:RANG 9' in line]
        self.assertEqual(len(attempts), 1, 'the failed write was sent again')
        self.assertNotIn(':SENS:VOLT:DC:NPLC 1', ' '.join(d.log.lines()))             # and the point stopped there

    def test_range_not_accepted_stops_the_point(self):
        import drivers
        d, _ft, dt = self.make()
        dt.range_reply = lambda r: 10 * r
        with self.assertRaises(drivers.InstrumentError):
            d.configure_point(dict(kind='DCV', range=1.0, plc=1))
        self.assertEqual(len([c for c in dt.sent if c.startswith(':SENS:VOLT:DC:RANG ')]), 1)

    def test_range_ok_window(self):
        from drivers import Keithley2000
        for reply, rng, want in (('+1.000000E-01', 0.1, True), ('+1.200000E-01', 0.1, True), ('+1.000000E+00', 0.1, False), ('+7.575E+02', 750.0, True),
                                 ('+1.01E+03', 1000.0, True), ('+1.2E+08', 1e8, True), ('+1.0E+07', 1e8, False)):
            self.assertIs(Keithley2000.range_ok(reply, rng), want, (reply, rng))

    def test_rel_zero_reference_and_state(self):
        d, ft, dt = self.make()
        d.configure_point(dict(kind='DCV', range=0.1, plc=1))
        self.assertFalse(d.rel_is_on('DCV'))
        ft.write('OUT 0V,0Hz')
        ft.write('OPER')
        ref = d.acquire_reference()
        self.assertAlmostEqual(ref, 2.5e-6, places=12)
        self.assertTrue(d.rel_is_on('DCV'))
        self.assertAlmostEqual(d.read(), 0.0, places=9)                         # the offset is removed
        i = dt.sent.index(':SENS:VOLT:DC:REF:ACQ')
        self.assertEqual(dt.sent[i - 1], ':READ?')                              # a reading exists before the reference is taken (p. 5-44)
        self.assertEqual(dt.sent[i + 1], ':SENS:VOLT:DC:REF?')
        self.assertEqual(dt.sent[i + 2], ':SENS:VOLT:DC:REF:STAT ON')
        self.assertEqual(dt.sent[i + 3], ':SENS:VOLT:DC:REF:STAT?')

    def test_rel_is_forced_off_for_the_other_functions(self):
        d, _ft, dt = self.make()
        for kind, rng in (('ACV', 1.0), ('DCI', 0.1), ('ACI', 1.0), ('OHM4', 1000.0)):
            mark = len(dt.sent)
            d.configure_point(dict(kind=kind, range=rng, plc=1, ac_bandwidth=30))
            self.assertTrue(any('REF:STAT OFF' in c for c in dt.sent[mark:]), kind)

    def test_overflow_is_an_error_not_a_reading(self):
        import drivers
        d, ft, dt = self.make()
        d.configure_point(dict(kind='DCV', range=1.0, plc=1))
        ft.write('OUT 50V,0Hz'); ft.write('OPER')
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.read()
        self.assertIn('overflow', str(cm.exception))

    def test_error_queue_is_read_to_empty_and_reported(self):
        import drivers
        d, _ft, dt = self.make()
        d.check_errors('quiet')
        dt.errors = ['-221,"Settings conflict"', '-113,"Undefined header"']
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.check_errors('configuring')
        self.assertIn('-221', str(cm.exception))
        self.assertIn('-113', str(cm.exception))
        d.check_errors('now empty')

    def test_inputs_switch_is_read(self):
        d, _ft, dt = self.make()
        self.assertEqual(d.front_rear(), 'FRONT')
        dt.front = False
        self.assertEqual(d.front_rear(), 'REAR')

    def test_read_and_fetch_agree(self):
        d, ft, dt = self.make()
        d.configure_point(dict(kind='DCV', range=1.0, plc=1))
        ft.write('OUT 1V,0Hz'); ft.write('OPER')
        self.assertAlmostEqual(d.read(), 1.0000045, places=5)                 # +2 ppm gain and the 2.5 uV offset of the simulated meter (no REL here)
        self.assertAlmostEqual(d.fetch(), 1.0000045, places=5)

    def test_zcomp_only_below_110_kohm_on_the_5522a(self):
        import drivers
        _d, ft, _dt = self.make('5522A')
        cal = drivers.Fluke5522AComp(ft, drivers.CommandLog(), label='5522A')
        cal.open(verify_model=False)
        ft.write('OUT 1000OHM')
        cal.set_compensation('WIRE4')
        ft.write('OUT 1000000OHM')
        with self.assertRaises(drivers.InstrumentError):
            cal.set_compensation('WIRE4')
        cal.set_compensation('NONE')
        self.assertFalse(hasattr(drivers.Fluke5560A, 'set_compensation'))


class Flow(unittest.TestCase):
    """The engine on the simulated bench (virtual demo = the real IO / driver code over the simulated 2000 and calibrator)."""

    def setUp(self):
        self.hn = VH.VHarness().start()
        K.messagebox = VH.hh.messagebox

    def tearDown(self):
        self.hn.stop()

    def app(self, fast=False, cal='Fluke 5560A', **settings):
        a = K.App(self.hn.root, demo=True, fast_demo=fast)
        a.asset.set('K-1'); a.serial.set('S-1')
        a.cal_model.set(cal)
        for k, v in settings.items():
            getattr(a, k).set(v)
        self.hn.app = a
        return a

    def wire(self, a, who=None):
        return [t for d, t in VH.wire(a.io) if who is None or d == who]

    # ---- a whole run
    def test_virtual_run_passes_every_point_and_is_marked_demo(self):
        a = self.app()
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(a.results), 37)                                    # the optional 700 V point is not run
        self.assertNotIn('21', a.results)
        self.assertTrue(all(r['result'] == 'PASS' and r['synthetic'] for r in a.results.values()))
        self.assertTrue(a.io.log.virtual)
        self.assertTrue(a.any_synthetic())
        self.assertFalse(self.hn.boxes('showerror'))
        titles = self.hn.titles()
        self.assertEqual(titles[0], 'Before the verification')
        self.assertEqual(titles[1:].count('Rewire / verify before enabling output'), 6)       # DCV, ACV, DCI, ACI, 4-wire ohms, 100 Mohm

    def test_command_order_dc_zero_hz_standby_and_reset_first(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        w = VH.wire(a.io)
        first_point = next(i for i, (d, t) in enumerate(w) if t.startswith('OUT'))
        self.assertTrue(any(t == '*RST' and d == '2000' for d, t in w[:first_point]))
        cal = [t for d, t in w if d == '5522A']
        for t in cal:
            if t.startswith('OUT') and t.endswith(('V', 'A')) and ',' not in t:
                self.fail(f'a DC output without an explicit 0 Hz: {t}')
        self.assertIn('OUT -1000V,0Hz', cal)
        self.assertIn('OUT 0V,0Hz', cal)
        # standby after every point: after each OPER the next calibrator command that is not a query is STBY
        for i, t in enumerate(cal):
            if t == 'OPER':
                nxt = next(x for x in cal[i + 1:] if x != 'OPER?')
                self.assertEqual(nxt, 'STBY', f'no standby after the output at index {i}')
        self.assertEqual(cal[-1], 'STBY')

    def test_rel_zero_is_done_once_before_the_first_dc_volts_point(self):
        a = self.app()
        self.assertTrue(self.hn.run_all())
        acq = [i for i, t in enumerate(self.wire(a, '2000')) if t == ':SENS:VOLT:DC:REF:ACQ']
        self.assertEqual(len(acq), 1)
        w = self.wire(a, '2000')
        self.assertLess(acq[0], next(i for i, t in enumerate(w) if t == ':SENS:VOLT:AC:RANG 0.09'))
        cal = self.wire(a, '5560A')
        self.assertEqual(cal.index('OUT 0V,0Hz'), min(i for i, t in enumerate(cal) if t.startswith('OUT')))      # the zero is the first output

    def test_resistance_compensation_on_the_5522a_and_none_on_the_5560a(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        cal = self.wire(a, '5522A')
        modes = [(cal[i - 1], cal[i]) for i, t in enumerate(cal) if t.startswith('ZCOMP ') and not t.endswith('?')]
        self.assertEqual([m[1] for m in modes], ['ZCOMP WIRE4'] * 4 + ['ZCOMP NONE'] * 3)
        for out, _z in modes:
            self.assertTrue(out.endswith('OHM'))
        for i, t in enumerate(cal):
            if t.startswith('ZCOMP ') and not t.endswith('?'):
                self.assertEqual(next(x for x in cal[i + 1:] if x not in ('ZCOMP?',)), 'ERR?')      # error queue read before OPER
        self.assertNotIn('OPER', cal[cal.index('ZCOMP WIRE4'):cal.index('ZCOMP WIRE4') + 3])
        self.hn.stop(); self.setUp()
        b = self.app(cal='Fluke 5560A')
        self.assertTrue(self.hn.run_all())
        self.assertFalse([t for t in self.wire(b, '5560A') if t.startswith('ZCOMP')])

    def test_high_voltage_confirmation_at_100_volts_and_up(self):
        self.app()
        self.assertTrue(self.hn.run_all())
        asked = [b for b in self.hn.boxes('askyesno') if b[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(asked), 8)                    # +/-100 V and +/-1000 V DC; 100 V AC at 1 kHz and 50 kHz; 700 V 1 kHz; 219 V 50 kHz
        self.assertTrue(any('-1000 V' in b[3] for b in asked))

    def test_700_volt_option_swaps_the_219_volt_point(self):
        a = self.app(cal='Fluke 5522A')
        a.include_700.set(True)
        self.assertTrue(a.active(PTS[20]) and not a.active(PTS[19]))
        self.assertTrue(self.hn.run_all())
        self.assertIn('21', a.results)
        self.assertNotIn('20', a.results)
        self.assertEqual(len(a.results), 37)
        self.assertIn('Connect the standard', self.hn.titles())
        self.assertFalse([t for t in self.wire(a, '5522A') if t.startswith('OUT 700V,50000Hz')])         # no calibrator command for the by-hand point
        self.assertTrue(a.results['21']['synthetic'])

    def test_fast_demo_connects_nothing(self):
        a = self.app(fast=True)
        self.assertTrue(self.hn.run_all())
        self.assertIsNone(a.io)
        self.assertEqual(len(a.results), 37)
        self.assertTrue(all(r['synthetic'] for r in a.results.values()))
        self.assertFalse(self.hn.titles())

    # ---- refusals
    def io(self, cal='Fluke 5522A'):
        b, ft, dt = bench(CAL_KEY[cal], 'GPIB')
        io = K.IO('sim', 'sim', cal, 9600, 'GPIB', transports=(dt, ft))
        io.reset_at_start()
        return io, b, ft, dt

    def test_rear_inputs_stop_before_anything_is_sourced(self):
        import drivers
        io, _b, _ft, dt = self.io()
        dt.front = False
        mark = len(VH.wire(io))
        with self.assertRaises(drivers.InstrumentError) as cm:
            io.measure(PTS[2])
        self.assertIn('REAR', str(cm.exception))
        cal = [t for d, t in VH.wire(io)[mark:] if d == '5522A']
        self.assertNotIn('OPER', cal)
        self.assertEqual(cal[-1], 'STBY')

    def test_a_calibrator_error_stops_before_operate_and_leaves_standby(self):
        import drivers
        io, b, ft, _dt = self.io()
        io.measure(PTS[0])                                   # the REL zero and the first point
        mark = len(VH.wire(io))
        ft.errors = ['-222,"Data out of range"']
        with self.assertRaises(drivers.InstrumentError):
            io.measure(PTS[2])
        cal = [t for d, t in VH.wire(io)[mark:] if d == '5522A']
        self.assertNotIn('OPER', cal)
        self.assertEqual(cal[-1], 'STBY')
        self.assertEqual(len([t for t in cal if t.startswith('OUT')]), 1, 'an output was resent')

    def test_a_meter_configuration_error_is_reported(self):
        import drivers
        io, _b, _ft, dt = self.io()
        io.measure(PTS[0])
        dt.errors = ['-221,"Settings conflict"']
        with self.assertRaises(drivers.InstrumentError):
            io.measure(PTS[2])

    def test_wrong_range_on_the_meter_makes_the_reading_stop_not_pass(self):
        import drivers
        io, _b, _ft, dt = self.io()
        dt.range_reply = lambda r: 100 * r
        with self.assertRaises(drivers.InstrumentError):
            io.measure(PTS[0])

    # ---- judging
    def test_judge_is_decimal_exact_at_the_limit(self):
        p = dict(PTS[0])
        p['error'] = 8.5e-06
        self.assertTrue(K.judge(p, 0.1000085))
        self.assertTrue(K.judge(p, 0.0999915))
        self.assertFalse(K.judge(p, 0.10000851))
        n = dict(PTS[1]); n['error'] = 8.5e-06
        self.assertTrue(K.judge(n, -0.1000085))
        self.assertFalse(K.judge(n, -0.0999914))
        big = dict(PTS[37]); big['error'] = 153000.0
        self.assertTrue(K.judge(big, 100153000.0))
        self.assertFalse(K.judge(big, 100153000.1))

    def test_a_reading_outside_the_limit_is_recorded_as_a_failure(self):
        a = self.app()
        self.assertTrue(self.hn.run_all())
        p = PTS[2]
        a._record(p, p['nominal'] + 2 * p['error'], True)
        self.assertEqual(a.results[str(p['id'])]['result'], 'FAIL')
        a._record(p, p['nominal'] + 0.5 * p['error'], True)
        self.assertEqual(a.results[str(p['id'])]['result'], 'PASS')

    # ---- reports
    def test_report_rows_negative_nominals_and_standards(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        rows, pts = a.certificate_rows_and_points()
        self.assertEqual(len(rows), 37)
        neg = rows[1]                                          # -100 mV
        self.assertTrue(neg['Nominal'].startswith('-100'), neg)
        self.assertLess(float(neg['Tolerance -']), float(neg['Tolerance +']))
        self.assertEqual(neg['Uncertainty'], rows[0]['Uncertainty'])
        self.assertTrue(all(r['Section'] for r in rows))
        self.assertFalse([r for r in rows if r['OOT']])

    def test_700_volt_row_claims_no_calibrator_uncertainty(self):
        a = self.app()
        a.include_700.set(True)
        self.assertTrue(self.hn.run_all())
        rows, pts = a.certificate_rows_and_points()
        row = next(r for p, r in zip(pts, rows) if p['id'] == 21)
        self.assertEqual(a.standard_for(PTS[19]), '5560A')
        self.assertIsNone(a.standard_for(next(p for p in PTS if p['id'] == 21)))
        import report_pdf
        self.assertEqual(row['Uncertainty'], report_pdf.point_uncertainty(next(p for p in PTS if p['id'] == 21), None))      # the scope CMC, not a calibrator budget

    def test_tar_tur_fields_exist_for_every_point(self):
        import tartur_wiring
        for std in ('5522A', '5560A'):
            for p in PTS:
                f = tartur_wiring.point_fields(p, std)
                self.assertEqual(set(f), {'TAR', 'TUR'})
            self.assertTrue(tartur_wiring.point_fields(PTS[2], std)['TUR'])

    def test_report_file_name_is_asset_date(self):
        from datetime import datetime
        import ui_theme as ui
        self.assertEqual(ui.report_filename('K-1', when=datetime(2026, 10, 22)), 'K-1-10-22-2026.pdf')

    def test_pdf_of_a_demo_run_says_demo(self):
        try:
            import report_pdf
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest('reportlab is not installed')
        a = self.app()
        self.assertTrue(self.hn.run_all())
        rows = a.certificate_rows()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'K-1-10-22-2026.pdf'
            report_pdf.write_calibration_pdf(str(path), rows, header=[('Instrument', 'Keithley Model 2000')], demo=a.any_synthetic(), details={})
            self.assertTrue(path.stat().st_size > 1000)

    # ---- editor / modifications
    def test_per_point_plan_is_the_measure_routine(self):
        a = self.app()
        plan = a.pm_plan_point(PTS[0])
        text = json.dumps(plan, default=str)
        self.assertIn(':READ?', text)
        self.assertIn('OUT 0.1V,0Hz', text)

    def test_setup_text_names_the_calibrator_terminals(self):
        a = self.app()
        self.assertIn('OUTPUT V/ohm HI / LO', a.setup_text(PTS[0]))
        self.assertIn('VI AUX', a.setup_text(PTS[21]))
        a.cal_model.set('Fluke 5522A')
        self.assertIn('NORMAL HI / LO', a.setup_text(PTS[0]))
        self.assertIn('AUX HI and AUX LO', a.setup_text(PTS[21]))
        self.assertIn('ZCOMP', a.setup_text(PTS[31]))
        a.cal_model.set('Fluke 5560A')
        self.assertIn('sends no compensation command', a.setup_text(PTS[31]))


CAL_KEY = {'Fluke 5522A': '5522A', 'Fluke 5560A': '5560A'}


class Registration(unittest.TestCase):
    def test_launcher_manager_verified_and_tunables(self):
        src = (ROOT / 'Procedures' / 'Keithley_2000_Verification.py').read_text(encoding='utf-8')
        self.assertIn('keithley2000_verification.main()', src)
        from tests._registry_text import manager_text            # the Manager finds procedures by scanning Procedures/*.procedure.json
        mgr = manager_text()
        self.assertIn("'Keithley 2000 Performance Verification': 'Keithley_2000_Verification.py'", mgr)
        self.assertIn("('Keithley 2000 Performance Verification','Keithley','2000','Digital Multimeter','Keithley_2000_Verification.py')", mgr)
        self.assertIn("'Keithley_2000_Verification.py': '1'", mgr)
        import verified
        self.assertIn('Keithley_2000_Verification.py', verified.FILES)
        for rel in verified.FILES['Keithley_2000_Verification.py']['code'] + verified.FILES['Keithley_2000_Verification.py']['spec']:
            self.assertTrue((ROOT / rel).exists(), rel)
        import procmods_engine as pe
        self.assertEqual(pe.MODEL_IDS['k2000'], '2000')
        self.assertTrue(pe.tunables_for('k2000'))

    def test_diagram_readme_exists_and_names_the_groups(self):
        text = (ROOT / 'diagrams' / 'README_k2000.txt').read_text(encoding='utf-8')
        for g in ('DCV', 'ACV', 'ACV700', 'DCI', 'ACI', 'OHM4', 'OHM100M'):
            self.assertIn(g, text)


if __name__ == '__main__':
    unittest.main()
