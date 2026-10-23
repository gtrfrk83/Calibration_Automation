"""Keysight 34410A verification (agilent34410a_verification.py, drivers/keysight_34410a.py, specs/keysight_34410a_pv.json).

Part 1: the spec: counts per section, the printed limit text against the numeric limit (Decimal), the builder reproducing the stored file, spot values typed a second time.
Part 2: the driver on the simulated 34410A over GPIB and USB: the command registry (page references, verified flags, the unverified list), set / read back / compare,
a write is never retried, overflow, the error queue, the Front/Rear switch read, remote / local for both interfaces, the firmware warning.
Part 3: the engine on the simulated bench with each calibrator (5560A, 5522A, 5520A) and each interface: command order, explicit 0 Hz, standby after each point,
the interface selector with one remembered address per interface, the resource strings, hook-up prompts, refusal paths, Decimal judging, report rows, TAR / TUR, demo, registration.
tkinter is stubbed in setUpModule (not at import time), like tests/test_k2000_points.py.
Run:  python -m unittest tests.test_34410a_points"""
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

A = VH = SPEC = PTS = None
SCALE = {'nA': D('0.000000001'), 'uA': D('0.000001'), 'mA': D('0.001'), 'A': D(1), 'uV': D('0.000001'), 'mV': D('0.001'), 'V': D(1), 'mohm': D('0.001'),
         'ohm': D(1), 'kohm': D(1000), 'Mohm': D(1000000), 'mHz': D('0.001'), 'Hz': D(1), 'kHz': D(1000), 'uF': D('0.000001'), 'nF': D('0.000000001')}
SECTION_SIZES = {'zero_front': 18, 'zero_rear': 18, 'dcv': 7, 'dci': 6, 'ohm': 7, 'freq': 2, 'acv': 16, 'aci': 12, 'acv_opt': 9, 'aci_opt': 6, 'cap': 2}
# a second typing of some printed 1-year limits (kind, range, nominal, frequency) -> printed text, read again from the page images
SPOT = {
    ('DCV', '0.1', '0.1', None): '8.5 uV', ('DCV', '1000', '1000', None): '56 mV', ('DCI', '0.0001', '0.0001', None): '0.075 uA',
    ('DCI', '3', '2', None): '3.6 mA', ('OHM4', '100', '100', None): '14 mohm', ('OHM4', '1000', '1000', None): '110 mohm', ('OHM2', '100000000', '100000000', None): '801 kohm',
    ('ACV', '0.1', '0.1', 1000): '90 uV', ('ACV', '0.1', '0.1', 50000): '150 uV', ('ACI', '3', '2', 5000): '4.8 mA', ('FREQ', '10', '10000', None): '0.7 Hz',
}
CAL_KEY = {'Fluke 5522A': '5522A', 'Fluke 5560A': '5560A', 'Fluke 5520A': '5520A'}


def setUpModule():
    global A, VH, SPEC, PTS
    import _tk_stub
    _tk_stub.install()
    sys.path.insert(0, str(ROOT / 'Procedures'))
    import virtual_harness as _vh
    import agilent34410a_verification as _a
    A, VH = _a, _vh
    SPEC, PTS = A.SPEC, A.POINTS


def printed_to_base(text):
    value, unit = text.split()
    return D(value) * SCALE[unit]


def bench(cal='5522A', bus='GPIB'):
    from drivers.simulated_34410a import make_34410a_bench
    return make_34410a_bench(cal, bus)


class SpecTests(unittest.TestCase):
    def test_counts(self):
        self.assertEqual({s['id']: len(s['points']) for s in SPEC['sections']}, SECTION_SIZES)
        self.assertEqual(len(PTS), 103)
        self.assertEqual(len([p for p in PTS if not p['optional']]), 86)
        self.assertEqual(SPEC['periods'], ['24h', '90d', '1y'])
        self.assertEqual(SPEC['default_period'], '1y')

    def test_every_printed_limit_matches_its_number_in_every_period(self):
        for p in PTS:
            for per, text in p['printed_limits'].items():
                self.assertEqual(D(str(p['limits'][per])), printed_to_base(text), f"point {p['id']} {per}")

    def test_spot_values_typed_a_second_time(self):
        seen = set()
        for p in PTS:
            key = (p['kind'], format(D(str(p['range'])), 'f').rstrip('0').rstrip('.') or '0', format(D(str(p['nominal'])), 'f').rstrip('0').rstrip('.') or '0', p.get('frequency'))
            if key in SPOT and p['source'] != 'none' and key not in seen and not p['optional']:
                seen.add(key)
                self.assertEqual(p['limits']['1y'], float(printed_to_base(SPOT[key])), key)
        self.assertEqual(len(seen), len(SPOT), set(SPOT) - seen)

    def test_zero_sections_have_no_source_and_both_terminal_sets(self):
        for s in SPEC['sections']:
            if s['id'].startswith('zero'):
                for p in s['points']:
                    self.assertEqual(p['source'], 'none')
                    self.assertEqual(p['terminal'], 'FRONT' if s['id'] == 'zero_front' else 'REAR')
                    self.assertEqual(p['nominal'], 0.0)
        self.assertEqual({p['input'] for s in SPEC['sections'] if s['id'] == 'zero_front' for p in s['points']}, {'short', 'open'})

    def test_dc_points_come_in_plus_minus_pairs_where_the_manual_has_them(self):
        pts = [p for p in PTS if p['kind'] == 'DCV' and p['source'] == 'calibrator']
        self.assertEqual(sorted(p['nominal'] for p in pts if p['nominal'] < 0), sorted(-p['nominal'] for p in pts if p['nominal'] > 0 and -p['nominal'] in [q['nominal'] for q in pts]))
        for p in PTS:
            if p['source'] == 'calibrator':
                self.assertGreaterEqual(p['range'], abs(p['nominal']) if p['kind'] != 'FREQ' else p['amplitude'] * 0 + 0, p['id'])

    def test_the_1000_volt_dc_discrepancy_is_flagged_not_changed(self):
        p = next(q for q in PTS if q['kind'] == 'DCV' and q['nominal'] == 1000.0)
        self.assertEqual(p['limits']['1y'], 0.056)
        self.assertEqual(p['limits']['90d'], 0.041)
        self.assertTrue(any('footnote 5' in f for f in p['flags']))

    def test_optional_sections(self):
        opt = {s['id'] for s in SPEC['sections'] if s.get('optional')}
        self.assertEqual(opt, {'acv_opt', 'aci_opt', 'cap'})
        self.assertTrue(all(p['source'] == 'manual' for p in PTS if p['kind'] == 'CAP'))

    def test_builder_reproduces_the_stored_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('build_34410a_spec', ROOT / 'specs' / 'build_34410a_spec.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(json.loads(json.dumps(mod.build())), json.loads((ROOT / 'specs' / 'keysight_34410a_pv.json').read_text(encoding='utf-8')))

    def test_measurement_conditions(self):
        m = SPEC['measure']
        self.assertEqual((m['nplc'], m['ac_bandwidth'], m['freq_aperture_s']), (100, 3, 1))
        self.assertTrue(SPEC['front_rear_switch'])


class DriverTests(unittest.TestCase):
    def make(self, cal='5522A', bus='GPIB'):
        import drivers
        _b, ft, dt = bench(cal, bus)
        d = drivers.Keysight34410A(dt, drivers.CommandLog(), label='34410A')
        d.connect()
        ft.open()
        return d, ft, dt

    def test_registry_lint_pages_and_verified_flags(self):
        import cmdreg
        import drivers
        from drivers import keysight_34410a as mod
        self.assertEqual(cmdreg.lint_registry(cmdreg.merge_commands(drivers.Keysight34410A)), [])
        for key, cmd in mod.COMMANDS.items():
            self.assertTrue(cmd.ref, f'{key} has no page reference')
            self.assertIsInstance(cmd.verified, bool)
        merged = cmdreg.merge_commands(drivers.Keysight34410A)
        self.assertEqual((merged['reset'].template, merged['reset'].risk, merged['reset'].verified), ('*RST', 'locked', True))
        unverified = sorted(k for k, c in mod.COMMANDS.items() if not c.verified)
        self.assertTrue(unverified)                                         # reply formats and a few node names are not in the manuals on file
        self.assertIn('freq.volt.rang', unverified)

    def test_gpib_connect_sends_no_remote_command_and_goes_local_with_gtl(self):
        d, _ft, dt = self.make(bus='GPIB')
        self.assertEqual(d.bus, 'GPIB')
        self.assertFalse([c for c in dt.sent if 'SYST:REM' in c or 'SYST:LOC' in c])
        calls = []
        dt.go_local = lambda: calls.append('GTL')
        d.local()
        self.assertEqual(calls, ['GTL'])

    def test_usb_has_no_local_command_the_operator_presses_shift_local(self):
        d, _ft, dt = self.make(bus='USB')
        self.assertEqual(d.bus, 'USB')
        calls = []
        dt.go_local = lambda: calls.append('GTL')
        mark = len(dt.sent)
        d.local()
        d.cleanup()
        self.assertEqual(calls, [])
        self.assertEqual(dt.sent[mark:], [])

    def test_wrong_instrument_is_refused(self):
        import drivers
        from golden_capture import Scripted
        d = drivers.Keysight34410A(Scripted([(r'\*IDN\?', 'KEYSIGHT,34401A,1,1')]), drivers.CommandLog(), label='34410A')
        with self.assertRaises(drivers.InstrumentError):
            d.connect()

    def test_firmware_warning(self):
        d, _ft, dt = self.make()
        self.assertEqual(d.firmware_warning(), '')
        d.idn = 'Agilent Technologies,34410A,MY1,1.07-1.07-0.01-1-1'
        self.assertIn('2.05', d.firmware_warning())

    def test_configure_sets_reads_back_and_never_repeats_a_write(self):
        d, _ft, dt = self.make()
        mark = len(dt.sent)
        d.configure_point(dict(kind='ACV', range=10.0, ac_bandwidth=3))
        sent = dt.sent[mark:]
        writes = [c for c in sent if not c.endswith('?')]
        self.assertEqual(len(writes), len(set(writes)), 'a setting was written twice')
        self.assertNotIn('AUTO ON', ' '.join(sent))
        self.assertTrue(any(c.endswith('RANG:AUTO?') for c in sent))
        self.assertEqual(dt.cfg['VOLT:AC']['range'], 10.0)
        self.assertEqual(dt.cfg['VOLT:AC']['band'], 3.0)

    def test_dc_functions_use_100_nplc(self):
        d, _ft, dt = self.make()
        d.configure_point(dict(kind='DCV', range=10.0))
        self.assertEqual(dt.cfg['VOLT:DC']['nplc'], 100.0)

    def test_a_failed_write_is_not_retried(self):
        import drivers
        b, ft, dt = bench()
        d = drivers.Keysight34410A(dt, drivers.CommandLog(), label='34410A')
        d.connect()
        b.fail_next = 'VOLT:DC:RANG'
        with self.assertRaises(Exception):
            d.configure_point(dict(kind='DCV', range=10.0))
        self.assertEqual(len([x for x in d.log.lines() if 'VOLT:DC:RANG 10' in x or 'CONF:VOLT:DC' in x]), 1, 'the failed write was sent again')

    def test_range_not_accepted_stops_the_point(self):
        import drivers
        d, _ft, dt = self.make()
        dt.range_reply = lambda r: 10 * r
        with self.assertRaises(drivers.InstrumentError):
            d.configure_point(dict(kind='DCV', range=1.0))

    def test_range_ok_window(self):
        from drivers import Keysight34410A
        self.assertTrue(Keysight34410A.range_ok('+1.000000E-01', 0.1))
        self.assertFalse(Keysight34410A.range_ok('+1.000000E+00', 0.1))
        with self.assertRaises(Exception):
            Keysight34410A.range_ok('abc', 0.1)

    def test_overflow_is_an_error_not_a_reading(self):
        import drivers
        d, ft, dt = self.make()
        d.configure_point(dict(kind='DCV', range=10.0))
        ft.write('OUT 50V,0Hz'); ft.write('OPER')
        with self.assertRaises(drivers.InstrumentError):
            d.read()

    def test_error_queue_is_read_to_empty_and_reported(self):
        import drivers
        d, _ft, dt = self.make()
        d.check_errors('ok')
        dt.errors = ['-221,"Settings conflict"', '-113,"Undefined header"']
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.check_errors('configuring')
        self.assertIn('-221', str(cm.exception)); self.assertIn('-113', str(cm.exception))
        d.check_errors('now empty')

    def test_front_rear_switch_is_read(self):
        d, _ft, dt = self.make()
        self.assertEqual(d.front_rear(), 'FRONT')
        dt.terminals = 'REAR'
        self.assertEqual(d.front_rear(), 'REAR')

    def test_every_function_configures_on_both_interfaces(self):
        for bus in ('GPIB', 'USB'):
            d, _ft, dt = self.make(bus=bus)
            for p in PTS:
                if p['kind'] in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'FREQ', 'CAP'):
                    d.configure_point(dict(p, plc=p.get('plc') or 100, ac_bandwidth=3, aperture_s=1))
            d.check_errors('all points')


class Flow(unittest.TestCase):
    """The engine on the simulated bench (virtual demo = the real IO / driver code over the simulated 34410A and calibrator)."""

    def setUp(self):
        self.hn = VH.VHarness().start()
        A.messagebox = VH.hh.messagebox

    def tearDown(self):
        self.hn.stop()

    def app(self, fast=False, cal='Fluke 5560A', **settings):
        a = A.App(self.hn.root, demo=True, fast_demo=fast)
        a.asset.set('A-1'); a.serial.set('S-1')
        a.cal_model.set(cal)
        for k, v in settings.items():
            getattr(a, k).set(v)
        self.hn.app = a
        return a

    def wire(self, a, who=None):
        return [t for d, t in VH.wire(a.io) if who is None or d == who]

    def io(self, cal='Fluke 5522A', bus='GPIB'):
        b, ft, dt = bench(CAL_KEY[cal], bus)
        io = A.IO('sim', 'sim', cal, 9600, bus, transports=(dt, ft))
        io.reset_at_start()
        return io, b, ft, dt

    # ---- a whole run, every calibrator and interface
    def test_virtual_run_passes_every_point_and_is_marked_demo(self):
        a = self.app()
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(a.results), 86)                                  # the optional tests are not run
        self.assertTrue(all(r['result'] == 'PASS' and r['synthetic'] for r in a.results.values()))
        self.assertTrue(a.io.log.virtual)
        self.assertTrue(a.any_synthetic())
        self.assertFalse(self.hn.boxes('showerror'))
        self.assertEqual(self.hn.titles()[0], 'Before the verification')

    def test_every_calibrator_and_interface_completes_the_run(self):
        for cal in ('Fluke 5560A', 'Fluke 5522A', 'Fluke 5520A'):
            for bus in ('GPIB', 'USB'):
                a = self.app(cal=cal, interface=bus)
                self.assertTrue(self.hn.run_all(), (cal, bus))
                self.assertEqual(len(a.results), 86, (cal, bus))
                self.assertTrue(all(r['result'] == 'PASS' for r in a.results.values()), (cal, bus))
                self.hn.stop(); self.hn = VH.VHarness().start(); A.messagebox = VH.hh.messagebox

    def test_optional_tests_run_when_asked(self):
        a = self.app(include_optional=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(a.results), 103)
        self.assertIn('Connect the standard', self.hn.titles())
        self.assertFalse([t for t in self.wire(a, '5560A') if t.startswith('OUT') and t.endswith('F')])      # no calibrator command for the capacitance standard

    def test_quick_set_is_a_subset(self):
        a = self.app()
        a.test_set.set('Quick check (Q points only)')
        q = a.active_points()
        self.assertTrue(0 < len(q) < 86)
        self.assertTrue(all(p['quick'] for p in q))

    def test_command_order_dc_zero_hz_standby_and_reset_first(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        w = VH.wire(a.io)
        first_point = next(i for i, (d, t) in enumerate(w) if t.startswith('OUT'))
        self.assertTrue(any(t == '*RST' and d == '34410A' for d, t in w[:first_point]))
        cal = [t for d, t in w if d == '5522A']
        for t in cal:
            if t.startswith('OUT') and t.endswith(('V', 'A')) and ',' not in t:
                self.fail(f'a DC output without an explicit 0 Hz: {t}')
        self.assertIn('OUT 1000V,0Hz', cal)
        for i, t in enumerate(cal):
            if t == 'OPER':
                nxt = next(x for x in cal[i + 1:] if x != 'OPER?')
                self.assertEqual(nxt, 'STBY', f'no standby after the output at index {i}')
        self.assertEqual(cal[-1], 'STBY')

    def test_zero_points_never_operate_the_calibrator(self):
        io, _b, _ft, _dt = self.io()
        mark = len(VH.wire(io))
        for p in PTS[:18]:
            io.measure(p)
        cal = [t for d, t in VH.wire(io)[mark:] if d == '5522A']
        self.assertNotIn('OPER', cal)
        self.assertFalse([t for t in cal if t.startswith('OUT')])

    def test_resistance_compensation_only_on_the_5522a(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        cal = self.wire(a, '5522A')
        self.assertIn('ZCOMP WIRE4', cal)
        self.assertIn('ZCOMP NONE', cal)
        for cal_name in ('Fluke 5560A', 'Fluke 5520A'):
            self.hn.stop(); self.hn = VH.VHarness().start(); A.messagebox = VH.hh.messagebox
            b = self.app(cal=cal_name)
            self.assertTrue(self.hn.run_all())
            self.assertFalse([t for t in self.wire(b) if 'ZCOMP' in t], cal_name)

    def test_high_voltage_confirmation(self):
        self.app()
        self.assertTrue(self.hn.run_all())
        asked = [b for b in self.hn.boxes('askyesno') if b[2] == 'HIGH VOLTAGE']
        self.assertTrue(asked)
        self.assertTrue(any('1000 V' in b[3] for b in asked))

    def test_fast_demo_connects_nothing(self):
        a = self.app(fast=True)
        self.assertTrue(self.hn.run_all())
        self.assertIsNone(a.io)
        self.assertEqual(len(a.results), 86)
        self.assertTrue(all(r['synthetic'] for r in a.results.values()))
        self.assertFalse(self.hn.titles())

    # ---- the interface selector
    def test_interface_selector_remembers_one_address_per_interface(self):
        a = self.app()
        self.assertEqual(a.interface.get(), 'GPIB')
        self.assertEqual(a.dmm_addr.get(), A.DEFAULT_ADDR['GPIB'])
        a.dmm_addr.set('GPIB0::9::INSTR')
        a.interface.set('USB'); a.on_interface()
        self.assertEqual(a.dmm_addr.get(), A.DEFAULT_ADDR['USB'])
        a.dmm_addr.set('USB0::0x2A8D::0x0101::MY12345678::INSTR')
        a.interface.set('GPIB'); a.on_interface()
        self.assertEqual(a.dmm_addr.get(), 'GPIB0::9::INSTR')
        a.interface.set('USB'); a.on_interface()
        self.assertEqual(a.dmm_addr.get(), 'USB0::0x2A8D::0x0101::MY12345678::INSTR')
        self.assertEqual(A.INTERFACES, ('GPIB', 'USB'))

    def test_resource_strings(self):
        self.assertEqual(A.to_visa('22', 'GPIB'), 'GPIB0::22::INSTR')
        self.assertEqual(A.to_visa('GPIB0::9::INSTR', 'GPIB'), 'GPIB0::9::INSTR')
        self.assertEqual(A.to_visa('USB0::0x2A8D::0x0101::MY1::INSTR', 'USB'), 'USB0::0x2A8D::0x0101::MY1::INSTR')
        self.assertEqual(A.to_visa('TCPIP0::10.0.0.5::inst0::INSTR', 'USB'), 'TCPIP0::10.0.0.5::inst0::INSTR')       # a full resource passes through for either choice
        self.assertTrue(A.to_cal_visa('COM9').upper().startswith('ASRL'))

    def test_the_5520a_has_its_own_driver_and_is_not_offered_where_it_cannot_source_the_points(self):
        """CHANGED (picker-5520a): the 5520A used the 5522A driver and was always offered.  It now has Fluke5520A (command status restated for the 5520A), and the picker
        offers it only when its published specification covers every calibrator point: it does not cover the three 300 kHz AC volts points (10 V, 50 V, 70 V), so the
        34410A picker no longer lists it.  The engine still runs with it (CALIBRATORS), and the report uses its own specification sheet now that one exists."""
        import drivers
        self.assertEqual(list(A.CALIBRATORS), ['Fluke 5560A', 'Fluke 5522A', 'Fluke 5520A'])
        self.assertIs(A.CALIBRATORS['Fluke 5520A'][1], drivers.Fluke5520A)
        self.assertEqual(drivers.Fluke5520A.IDN_MATCH, ('5520',))
        a = self.app(cal='Fluke 5520A')
        self.assertFalse(a.cal_offer.offered)
        self.assertEqual(sorted(r.label for r, _v in a.cal_offer.fit.excluded),
                         ['AC volts 10.00 V @ 300.0 kHz, 10.00 V range, 3 Hz filter', 'AC volts 50.00 V @ 300.0 kHz, 100.0 V range, 3 Hz filter',
                          'AC volts 70.00 V @ 300.0 kHz, 750.0 V range, 3 Hz filter'])      # 100 mV and 1 V at 300 kHz are inside its 500 kHz range
        self.assertEqual(a.cal_choices(), ['Fluke 5560A', 'Fluke 5522A'])
        self.assertEqual(a.standard_for(PTS[40]), '5520A' if PTS[40]['source'] == 'calibrator' else None)      # its own sheet (specs/standards/fluke_5520a_standard.json)
        self.assertIn('sends no compensation command', a.setup_text(next(p for p in PTS if p['group'] == 'OHM4')))

    def test_usb_run_ends_with_a_local_reminder(self):
        a = self.app(interface='USB')
        self.assertTrue(self.hn.run_all())
        self.assertIn('Shift / Local', str(a.status.set.call_args_list[-1]))

    # ---- refusals
    def test_rear_inputs_stop_before_anything_is_sourced(self):
        import drivers
        io, _b, _ft, dt = self.io()
        dt.terminals = 'REAR'
        p = next(q for q in PTS if q['source'] == 'calibrator')
        mark = len(VH.wire(io))
        with self.assertRaises(drivers.InstrumentError) as cm:
            io.measure(p)
        self.assertIn('REAR', str(cm.exception))
        cal = [t for d, t in VH.wire(io)[mark:] if d == '5522A']
        self.assertNotIn('OPER', cal)
        self.assertEqual(cal[-1], 'STBY')

    def test_rear_zero_points_need_the_rear_switch(self):
        import drivers
        io, _b, _ft, dt = self.io()
        rear = next(p for p in PTS if p['terminal'] == 'REAR')
        with self.assertRaises(drivers.InstrumentError):
            io.measure(rear)
        dt.terminals = 'REAR'
        self.assertTrue(isinstance(io.measure(rear), float))

    def test_a_calibrator_error_stops_before_operate_and_leaves_standby(self):
        import drivers
        io, b, ft, _dt = self.io()
        p = next(q for q in PTS if q['source'] == 'calibrator')
        ft.errors = ['-222,"Data out of range"']
        mark = len(VH.wire(io))
        with self.assertRaises(drivers.InstrumentError):
            io.measure(p)
        cal = [t for d, t in VH.wire(io)[mark:] if d == '5522A']
        self.assertNotIn('OPER', cal)
        self.assertEqual(cal[-1], 'STBY')
        self.assertEqual(len([t for t in cal if t.startswith('OUT')]), 1, 'an output was resent')

    def test_a_meter_configuration_error_is_reported(self):
        import drivers
        io, _b, _ft, dt = self.io()
        dt.errors = ['-221,"Settings conflict"']
        with self.assertRaises(drivers.InstrumentError):
            io.measure(next(q for q in PTS if q['source'] == 'calibrator'))

    def test_wrong_range_on_the_meter_makes_the_reading_stop_not_pass(self):
        import drivers
        io, _b, _ft, dt = self.io()
        dt.range_reply = lambda r: 100 * r
        with self.assertRaises(drivers.InstrumentError):
            io.measure(next(q for q in PTS if q['source'] == 'calibrator'))

    # ---- judging, reports, TAR / TUR
    def test_judge_is_decimal_exact_at_the_limit(self):
        p = dict(next(q for q in PTS if q['kind'] == 'DCV' and q['nominal'] == 0.1))
        p['error'] = 8.5e-06
        self.assertTrue(A.judge(p, 0.1000085))
        self.assertTrue(A.judge(p, 0.0999915))
        self.assertFalse(A.judge(p, 0.10000851))

    def test_a_reading_outside_the_limit_is_recorded_as_a_failure(self):
        a = self.app()
        p = PTS[36]
        a._record(p, p['nominal'] + 10 * p['error'], False)
        self.assertEqual(a.results[str(p['id'])]['result'], 'FAIL')

    def test_report_rows_and_standards(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        rows, pts = a.certificate_rows_and_points()
        self.assertEqual(len(rows), 86)
        self.assertTrue(all(r['Section'] for r in rows))
        self.assertFalse([r for r in rows if r['OOT']])
        self.assertEqual(a.standard_for(next(p for p in PTS if p['source'] == 'calibrator')), '5522A')
        self.assertIsNone(a.standard_for(PTS[0]))                             # a zero-offset point has no source

    def test_tar_tur_fields_exist_for_every_point(self):
        import tartur_wiring
        for std in ('5522A', '5560A'):
            for p in PTS:
                if p['source'] == 'calibrator':
                    self.assertEqual(set(tartur_wiring.point_fields(p, std)), {'TAR', 'TUR'}, (std, p['id']))

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
        a = self.app()
        self.assertTrue(self.hn.run_all())
        rows = a.certificate_rows()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'A-1-10-22-2026.pdf'
            report_pdf.write_calibration_pdf(str(path), rows, header=[('Instrument', 'Keysight 34410A')], demo=a.any_synthetic(), details={})
            self.assertTrue(path.stat().st_size > 1000)

    def test_per_point_plan_is_the_measure_routine(self):
        a = self.app()
        p = next(q for q in PTS if q['kind'] == 'DCV' and q['nominal'] == 0.1)
        text = json.dumps(a.pm_plan_point(p), default=str)
        self.assertIn('READ?', text)
        self.assertIn('OUT 0.1V,0Hz', text)

    def test_setup_text_names_the_calibrator_terminals(self):
        a = self.app()
        dcv = next(p for p in PTS if p['group'] == 'DCV'); dci = next(p for p in PTS if p['group'] == 'DCI'); ohm = next(p for p in PTS if p['group'] == 'OHM4')
        self.assertIn('OUTPUT V/ohm HI / LO', a.setup_text(dcv))
        self.assertIn('VI AUX', a.setup_text(dci))
        a.cal_model.set('Fluke 5522A')
        self.assertIn('NORMAL HI / LO', a.setup_text(dcv))
        self.assertIn('AUX HI and AUX LO', a.setup_text(dci))
        self.assertIn('ZCOMP', a.setup_text(ohm))


class Registration(unittest.TestCase):
    def test_launcher_manager_verified_and_tunables(self):
        src = (ROOT / 'Procedures' / 'Agilent_34410A_Verification.py').read_text(encoding='utf-8')
        self.assertIn('agilent34410a_verification.main()', src)
        side = json.loads((ROOT / 'Procedures' / 'Agilent_34410A_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((side['id'], side['model'], side['category'], side['seed_verified']), ('Agilent_34410A_Verification', '34410A', 'Digital Multimeter', False))
        self.assertEqual(side['launcher'], 'Procedures/Agilent_34410A_Verification.py')
        for rel in side['fingerprint']['code'] + side['fingerprint']['spec'] + side['own_files']:
            self.assertTrue((ROOT / rel).exists(), rel)
        import procscan
        self.assertIn('Agilent_34410A_Verification', [q.id for q in procscan.procs(ROOT)])
        import procmods_engine as pe
        self.assertEqual(pe.MODEL_IDS['a34410a'], 'the model, 34410A or 34411A')
        self.assertTrue(pe.tunables_for('a34410a'))

    def test_diagram_readme_exists_and_names_the_groups(self):
        text = (ROOT / 'diagrams' / 'README_34410a.txt').read_text(encoding='utf-8')
        for g in ('ZERO_SHORT', 'ZERO_OPEN', 'DCV', 'ACV', 'DCI', 'ACI', 'OHM4', 'OHM2', 'FREQ', 'CAP'):
            self.assertIn(g, text)


if __name__ == '__main__':
    unittest.main()
