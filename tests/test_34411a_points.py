"""Keysight / Agilent 34411A verification: the 34411A is a MODEL of the 34410A family (one spec with per-model flags, one engine, one driver module).

Part 1: the family spec: the models{} block, every point applies to both models (the Service Guide tables are headed "34410A/11A"), a second typing of
limits read again from the rendered pages (printed pp. 69-85), the builder reproducing the stored file, the 34410A default untouched.
Part 2: the Keysight34411A driver: its own *IDN? match (a 34410A is refused and the reverse), the same registry, the messages name the 34411A, no
digitizing / pre-trigger / reading-memory command, set / read back / compare, no retried write, GPIB and USB.
Part 3: the engine configured for the 34411A on the simulated bench: titles and settings name, checkpoint name, a full virtual run with every
calibrator x interface, the wire transcript equal to the 34410A's, the hook-up picture lookup, the launcher, the sidecar and the registration.
Each test that selects the 34411A puts the engine back on the 34410A (the engine module is shared by every test in the process).
tkinter is stubbed in setUpModule (not at import time), like tests/test_34410a_points.py.
Run:  python -m unittest tests.test_34411a_points"""
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
# limits read AGAIN from the rendered page images of this task (printed pp. 69, 71, 73, 75, 77, 79, 81, 83, 85, 87): (section, kind, range, nominal, frequency) -> 1 year text
SECOND_READ = {
    ('zero_front', 'DCI', '0.001', '0', None): '0.060 uA', ('zero_front', 'DCV', '1000', '0', None): '6 mV', ('zero_rear', 'OHM4', '10000', '0', None): '100 mohm',
    ('dcv', 'DCV', '10', '-10', None): '350 uV', ('dcv', 'DCV', '100', '100', None): '4.6 mV', ('dci', 'DCI', '0.1', '0.1', None): '55 uA',
    ('ohm', 'OHM4', '10000000', '10000000', None): '4.1 kohm', ('freq', 'FREQ', '0.1', '40', None): '28 mHz',
    ('acv', 'ACV', '10', '10', 10): '9.03 mV', ('acv', 'ACV', '100', '100', 50000): '150 mV', ('acv', 'ACV', '750', '70', 300000): '4.59 V',
    ('aci', 'ACI', '3', '2', 1000): '4.8 mA', ('acv_opt', 'ACV', '10', '0.1', 1000): '3.06 mV', ('aci_opt', 'ACI', '0.1', '0.001', 1000): '41 uA',
    ('cap', 'CAP', '0.00001', '0.000001', None): '0.014 uF',
}


def setUpModule():
    global A, VH, SPEC, PTS
    import _tk_stub
    _tk_stub.install()
    sys.path.insert(0, str(ROOT / 'Procedures'))
    import virtual_harness as _vh
    import agilent34410a_verification as _a
    A, VH = _a, _vh
    SPEC, PTS = A.SPEC, A.POINTS


def norm(x):
    return format(D(str(x)), 'f').rstrip('0').rstrip('.') or '0'


def printed_to_base(text):
    value, unit = text.split()
    return D(value) * SCALE[unit]


def bench(cal='5522A', bus='GPIB', model='34411A'):
    from drivers.simulated_34410a import make_34410a_bench
    return make_34410a_bench(cal, bus, model)


class ModelSelected(unittest.TestCase):
    """Base: selects the 34411A for the test and puts the 34410A back afterwards."""

    def setUp(self):
        A.configure('34411A')
        self.addCleanup(A.configure, '34410A')


class FamilySpec(unittest.TestCase):
    def test_the_spec_names_both_models_and_the_default_is_unchanged(self):
        self.assertEqual(SPEC['family'], ['34410A', '34411A'])
        self.assertEqual(list(SPEC['models']), ['34410A', '34411A'])
        self.assertEqual(SPEC['model'], '34410A')                              # the file's primary model stays: nothing the 34410A reads has moved
        self.assertEqual(A.MODELS, ('34410A', '34411A'))
        self.assertEqual(A.MODEL, '34410A')
        self.assertEqual(A.configure('34410A'), '34410A')

    def test_per_model_flags_as_read_from_the_service_guide_pages(self):
        m10, m11 = SPEC['models']['34410A'], SPEC['models']['34411A']
        self.assertEqual((m10['max_readings_per_s'], m10['reading_memory'], m10['min_nplc']), (10000, 50000, 0.006))            # printed pp. 7, 20
        self.assertEqual((m11['max_readings_per_s'], m11['reading_memory'], m11['min_nplc']), (50000, 1000000, 0.001))
        self.assertEqual((m10['digitizer'], m10['pretrigger'], m10['level_trigger']), (False, False, False))
        self.assertEqual((m11['digitizer'], m11['pretrigger'], m11['level_trigger']), (True, True, True))
        self.assertTrue(m10['front_rear_switch'] and m11['front_rear_switch'])                                                  # the 34411A has the switch (only the L4411A has not)
        self.assertEqual(m11['idn_match'], ['34411A'])
        self.assertEqual(SPEC['idn_match'], ['34410A'])

    def test_every_point_applies_to_both_models(self):
        for s in SPEC['sections']:
            self.assertNotIn('models', s)
            for p in s['points']:
                self.assertNotIn('models', p)
        self.assertEqual(len(PTS), 103)
        self.assertEqual(len([p for p in PTS if not p['optional']]), 86)

    def test_the_digitizer_is_not_part_of_the_verification(self):
        text = json.dumps(SPEC['sections'])
        for word in ('digitiz', 'pretrig', 'SAMP', 'level'):
            self.assertNotIn(word, text)
        self.assertIn('information only', SPEC['models_note'])

    def test_limits_read_a_second_time_from_the_page_images(self):
        seen = set()
        for s in SPEC['sections']:
            for p in s['points']:
                key = (s['id'], p['kind'], norm(p['range']), norm(p['nominal']), p.get('frequency'))
                if key in SECOND_READ and key not in seen:
                    seen.add(key)
                    self.assertEqual(D(str(p['limits']['1y'])), printed_to_base(SECOND_READ[key]), key)
        self.assertEqual(set(SECOND_READ) - seen, set())

    def test_the_24_hour_and_90_day_columns_were_read_again_for_a_few_points(self):
        pts = {(p['section'], p['kind'], norm(p['range']), norm(p['nominal']), p.get('frequency')): p for p in PTS}
        self.assertEqual((D(str(pts[('dcv', 'DCV', '100', '100', None)]['limits']['24h'])), D(str(pts[('dcv', 'DCV', '100', '100', None)]['limits']['90d']))),
                         (D('0.0026'), D('0.0041')))
        self.assertEqual(D(str(pts[('acv', 'ACV', '100', '100', 50000)]['limits']['90d'])), D('0.14'))
        self.assertEqual(D(str(pts[('ohm', 'OHM4', '1000', '1000', None)]['limits']['24h'])), D('0.025'))

    def test_the_flagged_1000_volt_discrepancy_is_carried_unchanged(self):
        p = next(q for q in PTS if q['kind'] == 'DCV' and q['nominal'] == 1000.0)
        self.assertEqual((p['limits']['24h'], p['limits']['90d'], p['limits']['1y']), (0.026, 0.041, 0.056))
        self.assertTrue(any('footnote 5' in f for f in p['flags']))

    def test_builder_reproduces_the_stored_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('build_34410a_spec', ROOT / 'specs' / 'build_34410a_spec.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(json.loads(json.dumps(mod.build())), json.loads((ROOT / 'specs' / 'keysight_34410a_pv.json').read_text(encoding='utf-8')))

    def test_the_family_block_is_the_only_change_to_the_34410a_limits(self):
        """The limits of the stored spec equal the limits in git's copy before the 34411A work (a stored digest of the 103 points x 3 periods)."""
        import hashlib
        text = json.dumps([[p['kind'], p['range'], p['nominal'], p.get('frequency'), p['limits']] for s in SPEC['sections'] for p in s['points']], sort_keys=True)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), PRE_34411A_LIMITS_SHA256)

    def test_configure_rejects_an_unknown_model(self):
        with self.assertRaises(ValueError):
            A.configure('34401A')
        with self.assertRaises(ValueError):
            A.configure('L4411A')                                               # the L4411A (no Front/Rear switch) is not built
        self.assertEqual(A.MODEL, '34410A')


class DriverTests(ModelSelected):
    def make(self, cal='5522A', bus='GPIB'):
        import drivers
        _b, ft, dt = bench(cal, bus)
        d = drivers.Keysight34411A(dt, drivers.CommandLog(), label='34411A')
        d.connect()
        ft.open()
        return d, ft, dt

    def test_same_registry_as_the_34410a_and_no_model_specific_command(self):
        import cmdreg
        import drivers
        from drivers import keysight_34410a as mod
        a, b = cmdreg.merge_commands(drivers.Keysight34410A), cmdreg.merge_commands(drivers.Keysight34411A)
        self.assertEqual({k: (c.template, c.verified, c.ref) for k, c in a.items()}, {k: (c.template, c.verified, c.ref) for k, c in b.items()})
        self.assertEqual(cmdreg.lint_registry(b), [])
        self.assertEqual((b['reset'].template, b['reset'].risk, b['reset'].verified), ('*RST', 'locked', True))
        for key, cmd in mod.COMMANDS.items():
            for word in ('SAMP', 'TRIG', 'DIG', 'PRET', 'MEM', 'DATA'):
                self.assertNotIn(word, cmd.template.upper(), key)                # nothing of the 34411A-only features is sent
            self.assertFalse(cmd.template.upper().startswith(('CAL', 'SYST:PRES')), key)

    def test_idn_accepts_the_34411a_and_refuses_a_34410a_and_the_reverse(self):
        import drivers
        from golden_capture import Scripted
        d = drivers.Keysight34411A(Scripted([(r'\*IDN\?', 'Agilent Technologies,34411A,MY1,2.35-2.35-0.09-46-09')]), drivers.CommandLog(), label='34411A')
        d.connect()
        self.assertEqual(d.MODEL, 'Keysight 34411A')
        d = drivers.Keysight34411A(Scripted([(r'\*IDN\?', 'Agilent Technologies,34410A,MY1,2.35-2.35-0.09-46-09')]), drivers.CommandLog(), label='34411A')
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.connect()
        self.assertIn('Expected a 34411A', str(cm.exception))
        d = drivers.Keysight34410A(Scripted([(r'\*IDN\?', 'Agilent Technologies,34411A,MY1,2.35-2.35-0.09-46-09')]), drivers.CommandLog(), label='34410A')
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.connect()
        self.assertIn('Expected a 34410A', str(cm.exception))                    # the 34410A messages are unchanged

    def test_the_spec_idn_match_is_what_the_drivers_accept(self):
        import drivers
        self.assertEqual(list(drivers.Keysight34410A.IDN_MATCH), SPEC['models']['34410A']['idn_match'])
        self.assertEqual(list(drivers.Keysight34411A.IDN_MATCH), SPEC['models']['34411A']['idn_match'])
        self.assertIs(A.dmm_class('34411A'), drivers.Keysight34411A)
        self.assertIs(A.dmm_class('34410A'), drivers.Keysight34410A)
        self.assertIs(A.dmm_class(), drivers.Keysight34411A)                      # the model selected now

    def test_connect_on_both_interfaces_and_local(self):
        for bus in ('GPIB', 'USB'):
            d, _ft, dt = self.make(bus=bus)
            self.assertEqual(d.bus, bus)
            self.assertIn('34411A', d.idn)
            calls = []
            dt.go_local = lambda: calls.append('GTL')
            d.local()
            self.assertEqual(calls, ['GTL'] if bus == 'GPIB' else [])

    def test_configure_sets_reads_back_and_never_repeats_a_write(self):
        d, _ft, dt = self.make()
        mark = len(dt.sent)
        d.configure_point(dict(kind='DCV', range=10.0, plc=100))
        d.configure_point(dict(kind='ACV', range=1.0, ac_bandwidth=3))
        sent = dt.sent[mark:]
        writes = [c for c in sent if not c.endswith('?')]
        self.assertEqual(len(writes), len(set(writes)))
        self.assertEqual(dt.cfg['VOLT:DC']['nplc'], 100.0)                       # 100 NPLC, never the 34411A's 0.001
        self.assertEqual(dt.cfg['VOLT:AC']['band'], 3.0)
        self.assertFalse([c for c in sent if 'NPLC 0.0' in c])

    def test_every_function_configures_and_reads_on_both_interfaces(self):
        for bus in ('GPIB', 'USB'):
            d, _ft, dt = self.make(bus=bus)
            for p in PTS:
                d.configure_point(dict(p, plc=p.get('plc') or 100, ac_bandwidth=3, aperture_s=1))
            d.check_errors('all points')

    def test_a_failed_write_is_not_retried(self):
        import drivers
        b, ft, dt = bench()
        d = drivers.Keysight34411A(dt, drivers.CommandLog(), label='34411A')
        d.connect()
        b.fail_next = 'VOLT:DC:RANG'
        with self.assertRaises(Exception):
            d.configure_point(dict(kind='DCV', range=10.0))
        self.assertEqual(len([x for x in d.log.lines() if 'VOLT:DC:RANG 10' in x or 'CONF:VOLT:DC' in x]), 1)

    def test_range_not_accepted_message_names_the_34411a(self):
        import drivers
        d, _ft, dt = self.make()
        dt.range_reply = lambda r: 10 * r
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.configure_point(dict(kind='DCV', range=1.0))
        self.assertIn('the 34411A answered', str(cm.exception))

    def test_overflow_message_names_the_34411a(self):
        import drivers
        d, ft, _dt = self.make()
        d.configure_point(dict(kind='DCV', range=10.0))
        ft.write('OUT 50V,0Hz'); ft.write('OPER')
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.read()
        self.assertIn('The 34411A reported an overload', str(cm.exception))

    def test_firmware_warning_and_front_rear(self):
        d, _ft, dt = self.make()
        self.assertEqual(d.firmware_warning(), '')
        d.idn = 'Agilent Technologies,34411A,MY1,1.07-1.07-0.01-1-1'
        self.assertIn('2.05', d.firmware_warning())
        self.assertEqual(d.front_rear(), 'FRONT')
        dt.terminals = 'REAR'
        self.assertEqual(d.front_rear(), 'REAR')

    def test_the_34410a_class_is_unchanged(self):
        import drivers
        self.assertEqual((drivers.Keysight34410A.MODEL, drivers.Keysight34410A.SHORT, drivers.Keysight34410A.IDN_MATCH), ('Keysight 34410A', '34410A', ('34410A',)))
        self.assertEqual(drivers.Keysight34411A.COMMANDS, drivers.Keysight34410A.COMMANDS)


class Flow(ModelSelected):
    """The engine configured for the 34411A on the simulated bench (virtual demo = the real IO / driver code over the simulated 34411A and calibrator)."""

    def setUp(self):
        super().setUp()
        self.hn = VH.VHarness().start()
        A.messagebox = VH.hh.messagebox

    def tearDown(self):
        self.hn.stop()              # the CURRENT harness (a test may have replaced it)

    def app(self, fast=False, cal='Fluke 5560A', **settings):
        a = A.App(self.hn.root, demo=True, fast_demo=fast)
        a.asset.set('A-11'); a.serial.set('S-11')
        a.cal_model.set(cal)
        for k, v in settings.items():
            getattr(a, k).set(v)
        self.hn.app = a
        return a

    def io(self, cal='Fluke 5522A', bus='GPIB'):
        _b, ft, dt = bench({'Fluke 5522A': '5522A', 'Fluke 5560A': '5560A', 'Fluke 5520A': '5520A'}[cal], bus)
        io = A.IO('sim', 'sim', cal, 9600, bus, transports=(dt, ft))
        io.reset_at_start()
        return io, ft, dt

    def test_engine_is_configured_for_the_34411a(self):
        self.assertEqual(A.MODEL, '34411A')
        titles = []
        self.hn.root.title = lambda t=None: titles.append(t)
        a = self.app()
        self.assertEqual(titles, ['Keysight 34411A | Performance Verification [DEMO]'])
        self.assertEqual(A.dmm_class().SHORT, '34411A')
        self.assertEqual(a._checkpoint_path().name, 'A34411A_A-11_checkpoint.json')

    def test_virtual_run_passes_every_point_and_is_marked_demo(self):
        a = self.app()
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(a.results), 86)
        self.assertTrue(all(r['result'] == 'PASS' and r['synthetic'] for r in a.results.values()))
        self.assertTrue(a.io.log.virtual)
        self.assertTrue(a.any_synthetic())
        self.assertFalse(self.hn.boxes('showerror'))
        self.assertIn('34411A', a.io.ident)
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

    def test_prompts_name_the_34411a_not_the_34410a(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        text = json.dumps([b for b in self.hn.boxes('askyesno')] + [self.hn.titles()], default=str)
        self.assertNotIn('34410A', json.dumps([a.setup_text(p) for p in PTS if p['source'] != 'none'][:60]))
        self.assertIn('34411A', json.dumps([a.setup_text(p) for p in PTS if p['source'] != 'none'][:60]))
        self.assertTrue(text)

    def test_high_voltage_and_standby_rules_hold(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        asked = [b for b in self.hn.boxes('askyesno') if b[2] == 'HIGH VOLTAGE']
        self.assertTrue(any('1000 V' in b[3] for b in asked))
        cal = [t for d, t in VH.wire(a.io) if d == '5522A']
        for t in cal:
            if t.startswith('OUT') and t.endswith(('V', 'A')) and ',' not in t:
                self.fail(f'a DC output without an explicit 0 Hz: {t}')
        for i, t in enumerate(cal):
            if t == 'OPER':
                nxt = next(x for x in cal[i + 1:] if x != 'OPER?')
                self.assertEqual(nxt, 'STBY')
        self.assertEqual(cal[-1], 'STBY')

    def test_rear_inputs_stop_before_anything_is_sourced(self):
        import drivers
        io, _ft, dt = self.io()
        dt.terminals = 'REAR'
        p = next(q for q in PTS if q['source'] == 'calibrator')
        mark = len(VH.wire(io))
        with self.assertRaises(drivers.InstrumentError) as cm:
            io.measure(p)
        self.assertIn('REAR', str(cm.exception))
        cal = [t for d, t in VH.wire(io)[mark:] if d == '5522A']
        self.assertNotIn('OPER', cal)
        self.assertEqual(cal[-1], 'STBY')

    def test_a_34410a_on_the_bus_is_refused_by_the_34411a_procedure(self):
        import drivers
        _b, ft, dt = bench(model='34410A')
        with self.assertRaises(drivers.InstrumentError):
            A.IO('sim', 'sim', 'Fluke 5522A', 9600, 'GPIB', transports=(dt, ft))

    def test_resistance_compensation_only_on_the_5522a(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        self.assertIn('ZCOMP WIRE4', [t for d, t in VH.wire(a.io) if d == '5522A'])
        self.hn.stop(); self.hn = VH.VHarness().start(); A.messagebox = VH.hh.messagebox
        b = self.app(cal='Fluke 5520A')
        self.assertTrue(self.hn.run_all())
        self.assertFalse([t for d, t in VH.wire(b.io) if 'ZCOMP' in t])

    def test_interface_selector_remembers_one_address_per_interface(self):
        a = self.app()
        a.dmm_addr.set('GPIB0::9::INSTR')
        a.interface.set('USB'); a.on_interface()
        self.assertEqual(a.dmm_addr.get(), A.DEFAULT_ADDR['USB'])
        a.dmm_addr.set('USB0::0x2A8D::0x0101::MY12345678::INSTR')
        a.interface.set('GPIB'); a.on_interface()
        self.assertEqual(a.dmm_addr.get(), 'GPIB0::9::INSTR')

    def test_report_rows_and_tar_tur(self):
        import tartur_wiring
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        rows, pts = a.certificate_rows_and_points()
        self.assertEqual(len(rows), 86)
        self.assertFalse([r for r in rows if r['OOT']])
        for p in pts:
            if p['source'] == 'calibrator':
                self.assertEqual(set(tartur_wiring.point_fields(p, '5522A')), {'TAR', 'TUR'})

    def test_pdf_of_a_demo_run_says_demo_and_is_named_asset_date(self):
        try:
            import report_pdf
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest('reportlab is not installed')
        from datetime import datetime
        import ui_theme as ui
        a = self.app()
        self.assertTrue(self.hn.run_all())
        self.assertEqual(ui.report_filename('A-11', when=datetime(2026, 10, 23)), 'A-11-10-23-2026.pdf')
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'A-11-10-23-2026.pdf'
            report_pdf.write_calibration_pdf(str(path), a.certificate_rows(), header=[('Instrument', 'Keysight 34411A')], demo=a.any_synthetic(), details={})
            self.assertTrue(path.stat().st_size > 1000)

    def test_per_point_plan_is_the_measure_routine(self):
        a = self.app()
        p = next(q for q in PTS if q['kind'] == 'DCV' and q['nominal'] == 0.1)
        text = json.dumps(a.pm_plan_point(p), default=str)
        self.assertIn('READ?', text)
        self.assertIn('OUT 0.1V,0Hz', text)


class WireEqualsTheOther(unittest.TestCase):
    """The same points on a simulated 34410A and a simulated 34411A send the same wire strings (every command is shared)."""

    def wire(self, model):
        from unittest import mock
        A.configure(model)
        try:
            self.enterContext(mock.patch.object(A.time, 'sleep', lambda *_a: None))         # the settle waits are not the subject
            _b, ft, dt = bench('5522A', 'GPIB', model)
            io = A.IO('sim', 'sim', 'Fluke 5522A', 9600, 'GPIB', transports=(dt, ft))
            io.reset_at_start()
            for p in [q for q in PTS if q['terminal'] == 'FRONT' and not q['optional']][::6]:
                io.measure(p)
            io.close()
            return [(d.replace(model, '<DMM>'), t) for d, t in VH.wire(io)]
        finally:
            A.configure('34410A')

    def test_same_commands_in_the_same_order(self):
        w10, w11 = self.wire('34410A'), self.wire('34411A')
        self.assertEqual(w10, w11)
        self.assertGreater(len(w10), 100)


class HookupAndLaunch(unittest.TestCase):
    def test_diagram_lookup_prefers_the_34411a_names_then_the_34410a_ones(self):
        old = A.HERE
        try:
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / 'diagrams').mkdir()
                A.HERE = Path(td)
                (Path(td) / 'diagrams' / 'hook_34410a_DCV.png').write_bytes(b'x')
                A.configure('34411A')
                self.assertEqual(A.find_diagram('5560A', 'DCV').name, 'hook_34410a_DCV.png')           # the same panel: the 34410A picture serves
                (Path(td) / 'diagrams' / 'hook_34411a_DCV.png').write_bytes(b'x')
                self.assertEqual(A.find_diagram('5560A', 'DCV').name, 'hook_34411a_DCV.png')
                (Path(td) / 'diagrams' / 'hook_34411a_5560A_DCV.png').write_bytes(b'x')
                self.assertEqual(A.find_diagram('5560A', 'DCV').name, 'hook_34411a_5560A_DCV.png')
                self.assertEqual(A.find_diagram('5520A', 'ACV'), None)
                A.configure('34410A')
                self.assertEqual(A.find_diagram('5560A', 'DCV').name, 'hook_34410a_DCV.png')           # the 34410A never looks for a 34411A picture
        finally:
            A.HERE = old
            A.configure('34410A')

    def test_launcher_calls_main_with_the_model(self):
        src = (ROOT / 'Procedures' / 'Agilent_34411A_Verification.py').read_text(encoding='utf-8')
        self.assertIn("MODEL = '34411A'", src)
        self.assertIn('agilent34410a_verification.main(model=MODEL)', src)
        self.assertIn('agilent34410a_verification.main()', (ROOT / 'Procedures' / 'Agilent_34410A_Verification.py').read_text(encoding='utf-8'))

    def test_main_selects_the_model_before_the_window_is_built(self):
        seen = []
        real_app, real_tk, real_flags = A.App, A.tk.Tk, A.virtualbench.flags

        class Root:
            def mainloop(self): pass

        A.App = lambda root, demo=False, fast_demo=False: seen.append((A.MODEL, demo))
        A.tk.Tk = Root
        A.virtualbench.flags = lambda argv: (True, False)
        try:
            A.main(['x', '--demo'], model='34411A')
            self.assertEqual(seen, [('34411A', True)])
            A.configure('34410A')
            A.main(['x', '--demo'])
            self.assertEqual(seen[-1], ('34410A', True))
        finally:
            A.App, A.tk.Tk, A.virtualbench.flags = real_app, real_tk, real_flags
            A.configure('34410A')

    def test_sidecar_and_registration(self):
        side = json.loads((ROOT / 'Procedures' / 'Agilent_34411A_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((side['id'], side['model'], side['category'], side['seed_verified'], side['name']),
                         ('Agilent_34411A_Verification', '34411A', 'Digital Multimeter', False, 'Agilent 34411A Performance Verification'))
        self.assertEqual(side['launcher'], 'Procedures/Agilent_34411A_Verification.py')
        self.assertEqual(side['engine'], ['agilent34410a_verification.py'])
        self.assertEqual(side['specs'], ['specs/keysight_34410a_pv.json'])
        self.assertEqual(side['hookup']['diagram_prefixes'], ['hook_34411a', 'hook_34410a'])
        for rel in side['fingerprint']['code'] + side['fingerprint']['spec'] + side['own_files'] + side['tests']:
            self.assertTrue((ROOT / rel).exists(), rel)
        import procscan
        ids = [q.id for q in procscan.procs(ROOT)]
        self.assertIn('Agilent_34411A_Verification', ids)
        self.assertEqual(ids.index('Agilent_34411A_Verification'), ids.index('Agilent_34410A_Verification') + 1)
        import verified
        self.assertIn('Agilent_34411A_Verification.py', verified.FILES)
        self.assertEqual(verified.FILES['Agilent_34411A_Verification.py']['spec'], verified.FILES['Agilent_34410A_Verification.py']['spec'])

    def test_both_models_share_the_procmods_tunables(self):
        import procmods_engine as pe
        self.assertTrue(pe.tunables_for('a34410a'))
        self.assertEqual(pe.MODEL_IDS['a34410a'], 'the model, 34410A or 34411A')


PRE_34411A_LIMITS_SHA256 = '335fa28cb96969cc751004282a6f64e9daafd743a0b4179b6b67490eb652beaf'

if __name__ == '__main__':
    unittest.main()
