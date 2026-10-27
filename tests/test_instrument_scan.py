"""Find instruments (instrument_scan.py): identity matching, the read-only guarantee, timeouts, duplicates, serial ports, memory and the VISA back ends,
all against a FAKE ResourceManager (no hardware, no VISA, no display).  The fake records every call so the tests can prove that only queries were sent.
Run:  python -m unittest tests.test_instrument_scan"""
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import drivers  # noqa: E402
import instrument_scan as S  # noqa: E402


class FakeTimeout(Exception):
    error_code = -1073807339

    def __str__(self):
        return 'VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.'


class FakeNoListener(Exception):
    def __str__(self):
        return 'VI_ERROR_NLISTENERS (-1073807265): No listeners condition is detected (both NRFD and NDAC are deasserted).'


class FakeRes:
    """One instrument.  replies {query: reply}; a query it does not know times out (a real instrument that does not understand it stays silent)."""

    def __init__(self, rm, name, replies, error=None, block=None, nonlistener=False):
        self.rm, self.name, self.replies, self.error, self.block = rm, name, dict(replies), error, block
        self.queries, self.writes, self.cleared, self.control_calls, self.closed = [], [], 0, [], False
        self.timeout = None

    def query(self, text):
        self.queries.append(text)
        self.rm.wire.append((self.name, 'query', text))
        if self.block is not None:
            self.block.wait(30)
        if self.error is not None:
            raise self.error
        if text in self.replies:
            return self.replies[text] + '\n'
        raise FakeTimeout()

    def write(self, text):
        self.writes.append(text)
        self.rm.wire.append((self.name, 'write', text))

    def read(self):
        self.rm.wire.append((self.name, 'read', ''))
        return ''

    def clear(self):
        self.cleared += 1
        self.rm.wire.append((self.name, 'clear', ''))

    def control_ren(self, mode):
        self.control_calls.append(mode)

    def close(self):
        self.closed = True


class FakeRM:
    def __init__(self, instruments, listed=None, open_errors=None, visalib=None):
        """instruments {name: dict(replies=..., error=..., block=...)}; listed = names list_resources returns (default: the instruments' names plus extras)."""
        self.specs = instruments
        self.listed = list(listed if listed is not None else instruments)
        self.open_errors = open_errors or {}
        self.opened, self.wire, self.resources, self.closed = [], [], {}, False
        self.visalib = visalib

    def list_resources(self, query='?*::INSTR'):
        return tuple(self.listed)

    def open_resource(self, name, open_timeout=None, **kw):
        self.opened.append(name)
        if name in self.open_errors:
            raise self.open_errors[name]
        spec = self.specs.get(name)
        if spec is None:
            raise FakeNoListener()
        res = FakeRes(self, name, **spec)
        self.resources[name] = res
        return res

    def close(self):
        self.closed = True

    # ---- assertions
    def only_queries(self):
        return all(kind == 'query' and text.endswith('?') for _n, kind, text in self.wire)


def scanner_for(rm, **kw):
    return S.Scanner(rm_factory=lambda: rm, timeout_ms=50, **kw)


IDN_3458 = {'ID?': 'Keysight 3458A'}
IDN_34410 = lambda serial: {'*IDN?': f'Agilent Technologies,34410A,{serial},2.35-2.35-0.09-46-09'}  # noqa: E731

# a reply sample for every family (the form each driver's IDN_MATCH is built for); see Family.source for where each form was read
SAMPLES = {
    '5560A': 'FLUKE,5560A,1234567,1.0', '5522A': 'FLUKE,5522A,5248000,1.0+1.3+1.8', '5520A': 'FLUKE,5520A,1111111,1.0+1.0+1.0',
    '5502A': 'FLUKE,5502A,2222222,1.0+1.0+1.0', '5500A': 'FLUKE,5500A,3333333,1.0+1.0+1.0', '5790B': 'FLUKE,5790B,7649820, v1.08+v1.01 FPGAv4',
    '8808A': 'FLUKE, 8808A, SIM0001, 1.0 D1.0', '8846A': 'FLUKE,8846A,4444444,1.0', '34401A': 'HEWLETT-PACKARD,34401A,0,10-5-2',
    '34410A': 'Agilent Technologies,34410A,MY00000001,2.35', '34411A': 'Agilent Technologies,34411A,MY00000002,2.35',
    '34460A': 'Keysight Technologies,34460A,MY00000003,3.01', '34461A': 'Keysight Technologies,34461A,MY00000004,3.01',
    '34465A': 'Keysight Technologies,34465A,MY00000005,3.01', '34470A': 'Keysight Technologies,34470A,MY00000006,3.01',
    '34970A': 'Agilent Technologies,34970A,MY00000007,13-2', '34972A': 'Agilent Technologies,34972A,MY00000008,1.04',
    '33210A': 'Agilent Technologies,33210A,MY00000009,1.0', '33220A': 'Agilent Technologies,33220A,MY0000000A,2.02-2.02',
    '33250A': 'Agilent Technologies,33250A,MY0000000B,2.00', '53131A': 'HEWLETT-PACKARD, 53131A,0,4806', '53132A': 'HEWLETT-PACKARD, 53132A,0,4806',
    '96270A': 'Fluke,96270A,5555555,1.00', 'Keithley 2000': 'KEITHLEY INSTRUMENTS INC.,MODEL 2000,0123456,A19  /A02',
    '3458A': 'Keysight 3458A', 'MDO4000C': 'TEKTRONIX,MDO4104C,C012345,CF:91.1CT FV:v1.0', 'MDO3': 'TEKTRONIX,MDO34,C012345,CF:91.1CT FV:v1.0', 'TDS2000C': 'TEKTRONIX,TDS 2024C,C012345,CF:91.1CT FV:v24.00',
    'WS4104HD': 'LECROY,WS4104HD,LCRY1234,9.9',
}
SAMPLES['TBS2000B'] = 'TEKTRONIX,TBS2104 ,CU10100,CF:91.1CT FV:v2015-12-10_01-00-59rootfs; FPGA:v1.21;'     # TBS2000B Programmer Manual p. 121


class Identity(unittest.TestCase):
    def test_every_family_has_a_sample_and_matches(self):
        self.assertEqual(set(SAMPLES), set(S.FAMILY))
        for key, reply in SAMPLES.items():
            fam = S.match_family(S.parse_identity(reply))
            self.assertIsNotNone(fam, key)
            self.assertEqual(fam.key, key, reply)

    def test_samples_agree_with_the_drivers_own_identity_text(self):
        """The suite's drivers refuse an instrument whose reply lacks their IDN_MATCH text: a model this table accepts must pass its driver."""
        for key, reply in SAMPLES.items():
            cls = getattr(drivers, S.FAMILY[key].driver)
            match = tuple(getattr(cls, 'IDN_MATCH', ()) or ())
            if match:
                self.assertTrue(any(m.upper() in reply.upper() for m in match), (key, match, reply))

    def test_parse_forms(self):
        i = S.parse_identity('HEWLETT-PACKARD, 53132A,0,XXXX\r\n')
        self.assertEqual((i.manufacturer, i.model, i.serial, i.firmware), ('HEWLETT-PACKARD', '53132A', '', 'XXXX'))
        i = S.parse_identity('FLUKE,5522A,5248000,1.0+1.3+1.8')
        self.assertEqual((i.model, i.serial, i.firmware), ('5522A', '5248000', '1.0+1.3+1.8'))
        for text in ('Keysight 3458A', 'HP3458A', '  HP3458A\x00 '):
            i = S.parse_identity(text)
            self.assertEqual((i.model, i.serial), ('3458A', ''), text)
            self.assertEqual(S.match_family(i).key, '3458A')
        self.assertEqual(S.parse_identity('').model, '')

    def test_unknown_instrument_is_not_matched(self):
        self.assertIsNone(S.match_family(S.parse_identity('ACME,Frobnicator 9000,1,1')))
        self.assertIsNone(S.match_family(S.parse_identity('Keysight 34420A')))
        self.assertIsNone(S.match_family(S.parse_identity('Tektronix,TDS 3032B,0,CF:91.1CT')))

    def test_resource_names(self):
        self.assertEqual([S.bus_of(r) for r in ('GPIB1::22::INSTR', 'USB0::0x2A8D::0x0101::MY1::INSTR', 'TCPIP0::10.0.0.5::inst0::INSTR', 'ASRL9::INSTR', 'GPIB0::INTFC')],
                         ['GPIB', 'USB', 'TCPIP', 'ASRL', 'GPIB'])
        self.assertEqual(S.gpib_boards(['GPIB1::22::INSTR', 'GPIB0::INTFC', 'USB0::1::2::3::INSTR']), [0, 1])
        self.assertEqual(S.gpib_address('GPIB1::22::INSTR'), 22)


class ReadOnly(unittest.TestCase):
    def test_guard(self):
        for ok in ('*IDN?', 'ID?', ' *IDN? '):
            self.assertEqual(S.assert_read_only(ok), ok.strip())
        for bad in ('*RST', '*CLS', '*IDN?;*RST', 'OUTPUT ON', 'ID', '', '*RST?\n', 'VOLT 5', 'ERR? ;STBY', '*SAV 1', '*TRG'):
            with self.assertRaises(S.ReadOnlyError, msg=bad):
                S.assert_read_only(bad)

    def test_probe_lists_are_queries_only(self):
        for bus, probes in S.PROBES.items():
            for p in probes:
                S.assert_read_only(p)
        for f in S.FAMILIES:
            S.assert_read_only(f.probe)

    def test_a_scan_sends_only_queries(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies=IDN_3458), 'GPIB0::4::INSTR': dict(replies={'*IDN?': SAMPLES['5522A']}),
                     'USB0::0x0957::0x2007::MY1::INSTR': dict(replies={'*IDN?': SAMPLES['34972A']}), 'GPIB0::9::INSTR': dict(replies={})},
                    listed=['GPIB0::22::INSTR', 'GPIB0::4::INSTR', 'USB0::0x0957::0x2007::MY1::INSTR', 'GPIB0::9::INSTR', 'ASRL3::INSTR', 'GPIB0::INTFC'])
        report = scanner_for(rm).scan()
        self.assertTrue(rm.wire)
        self.assertTrue(rm.only_queries(), rm.wire)
        for res in rm.resources.values():
            self.assertEqual(res.writes, [])
            self.assertEqual(res.cleared, 0)
            self.assertEqual(res.control_calls, [])            # no GTL unless asked for
            self.assertTrue(res.closed)
        self.assertTrue(rm.closed)
        self.assertEqual({h.key for h in report.identified()}, {'3458A', '5522A', '34972A'})

    def test_a_forbidden_probe_never_reaches_the_wire(self):
        rm = FakeRM({'GPIB0::5::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']})})
        with self.assertRaises(S.ReadOnlyError):
            scanner_for(rm).probe_resource(rm, 'GPIB0::5::INSTR', probes=['*RST'], log=[])
        self.assertEqual(rm.wire, [])
        self.assertTrue(rm.resources['GPIB0::5::INSTR'].closed)


class Probing(unittest.TestCase):
    def test_3458a_is_asked_after_a_scpi_probe_and_answers_to_id(self):
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458)})
        report = scanner_for(rm).scan()
        res = rm.resources['GPIB1::22::INSTR']
        self.assertEqual(res.queries, ['*IDN?', 'ID?'])          # *IDN? once (no retry), then ID?
        (hit,) = report.hits
        self.assertEqual((hit.status, hit.key, hit.probe, hit.serial, hit.resource), ('identified', '3458A', 'ID?', '', 'GPIB1::22::INSTR'))

    def test_preferred_probe_goes_first_for_a_remembered_3458a(self):
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458)})
        scanner_for(rm, preferred={'GPIB1::22::INSTR': 'ID?'}).scan()
        self.assertEqual(rm.resources['GPIB1::22::INSTR'].queries, ['ID?'])

    def test_scpi_instrument_is_asked_once(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']})})
        scanner_for(rm).scan()
        self.assertEqual(rm.resources['GPIB0::22::INSTR'].queries, ['*IDN?'])

    def test_silent_resource_times_out_and_the_last_query_is_retried_once(self):
        rm = FakeRM({'GPIB0::7::INSTR': dict(replies={}), 'USB0::1::2::3::INSTR': dict(replies={})})
        report = scanner_for(rm).scan()
        self.assertEqual(rm.resources['GPIB0::7::INSTR'].queries, ['*IDN?', 'ID?', 'ID?'])
        self.assertEqual(rm.resources['USB0::1::2::3::INSTR'].queries, ['*IDN?', '*IDN?'])
        self.assertEqual([h.status for h in report.hits], ['no reply', 'no reply'])
        self.assertTrue(all('imeout' in h.error for h in report.hits))
        self.assertTrue(rm.only_queries())

    def test_a_non_timeout_error_is_not_retried(self):
        rm = FakeRM({'USB0::1::2::3::INSTR': dict(replies={}, error=RuntimeError('USB device went away'))})
        (hit,) = scanner_for(rm).scan().hits
        self.assertEqual(rm.resources['USB0::1::2::3::INSTR'].queries, ['*IDN?'])
        self.assertIn('went away', hit.error)

    def test_a_resource_that_errors_on_open_does_not_stop_the_scan(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']}), 'USB0::9::9::9::INSTR': dict(replies={})},
                    open_errors={'USB0::9::9::9::INSTR': RuntimeError('Insufficient location information or the device is not present')})
        report = scanner_for(rm).scan()
        by = {h.resource: h for h in report.hits}
        self.assertEqual(by['GPIB0::22::INSTR'].key, '34401A')
        self.assertEqual(by['USB0::9::9::9::INSTR'].status, 'error')
        self.assertIn('could not open', by['USB0::9::9::9::INSTR'].error)

    def test_unknown_instrument_is_reported_but_has_no_model_key(self):
        rm = FakeRM({'USB0::5::5::5::INSTR': dict(replies={'*IDN?': 'ACME,Frobnicator 9000,1,1'})})
        (hit,) = scanner_for(rm).scan().hits
        self.assertEqual((hit.status, hit.key), ('unknown', ''))
        self.assertEqual(hit.idn, 'ACME,Frobnicator 9000,1,1')

    def test_go_local_only_when_asked(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']}), 'USB0::1::2::3::INSTR': dict(replies={'*IDN?': SAMPLES['34972A']})})
        fake_const = types.SimpleNamespace(RENLineOperation=types.SimpleNamespace(address_gtl='GTL'))
        fake_pyvisa = types.SimpleNamespace(constants=fake_const)
        with mock.patch.dict(sys.modules, {'pyvisa': fake_pyvisa}):
            scanner_for(rm, go_local=True).scan()
        self.assertEqual(rm.resources['GPIB0::22::INSTR'].control_calls, ['GTL'])
        self.assertEqual(rm.resources['USB0::1::2::3::INSTR'].control_calls, [])    # GPIB only


class SerialPorts(unittest.TestCase):
    def test_asrl_is_listed_never_opened_or_queried(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']}), 'ASRL9::INSTR': dict(replies={'*IDN?': SAMPLES['8808A']}),
                     'ASRL3::INSTR': dict(replies={'*IDN?': SAMPLES['5560A']})},
                    listed=['GPIB0::22::INSTR', 'ASRL9::INSTR', 'ASRL3::INSTR', 'TCPIP0::10.0.0.1::9999::SOCKET'])
        report = scanner_for(rm).scan()
        self.assertEqual(report.serial_ports, ['ASRL9::INSTR', 'ASRL3::INSTR'])
        self.assertEqual(rm.opened, ['GPIB0::22::INSTR'])
        self.assertTrue(all(n == 'GPIB0::22::INSTR' for n, _k, _t in rm.wire))
        self.assertEqual([r for r, _why in report.skipped], ['TCPIP0::10.0.0.1::9999::SOCKET'])

    def test_remembered_serial_port_is_not_verified_blind(self):
        rm = FakeRM({'ASRL9::INSTR': dict(replies={'*IDN?': SAMPLES['8808A']})})
        chk = scanner_for(rm).verify('ASRL9::INSTR', '8808A')
        self.assertFalse(chk.ok)
        self.assertEqual(rm.opened, [])

    def test_explicit_check_uses_the_drivers_own_identify_and_sends_only_that_query(self):
        from drivers.simulated_8808a import make_8808a_bench
        bench, _ct, dt = make_8808a_bench()
        asked = []
        orig = dt.handle
        dt.handle = lambda cmd: (asked.append(cmd.strip()), orig(cmd))[1]
        hit = S.serial_hit('ASRL9::INSTR', '8808A', transport_factory=lambda port, settings: dt)
        self.assertEqual(asked, ['*IDN?'])
        self.assertEqual((hit.status, hit.key, hit.serial), ('identified', '8808A', 'SIM0001'))
        self.assertFalse(dt.opened)                                   # closed again

    def test_wrong_family_chosen_is_reported(self):
        from drivers.simulated_8808a import make_8808a_bench
        _b, _c, dt = make_8808a_bench()
        hit = S.serial_hit('ASRL9::INSTR', '5560A', transport_factory=lambda port, settings: dt)
        # the 8808A answers but the technician said 5560A: the 5560A driver's identify() is what asks, and the reply is not a 5560A
        self.assertNotEqual(hit.status, 'identified')

    def test_families_without_serial_check_are_refused(self):
        with self.assertRaises(S.ScanError):
            S.serial_identity('ASRL9::INSTR', '3458A')
        with self.assertRaises(S.ScanError):
            S.serial_identity('GPIB0::22::INSTR', '8808A')

    def test_serial_settings_come_from_the_driver(self):
        self.assertEqual(S.serial_settings_for(S.FAMILY['8808A']).baud, 9600)
        self.assertEqual(S.serial_settings_for(S.FAMILY['Keithley 2000']).baud, 4800)
        self.assertEqual(S.serial_settings_for(S.FAMILY['34970A']).baud, 57600)
        self.assertEqual(S.serial_settings_for(S.FAMILY['5560A']).baud, 9600)


class Duplicates(unittest.TestCase):
    def test_same_model_two_serials_flags_both_for_choice(self):
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_34410('MY111')), 'USB0::0x2A8D::0x0101::MY222::INSTR': dict(replies=IDN_34410('MY222')),
                     'GPIB1::4::INSTR': dict(replies={'*IDN?': SAMPLES['5522A']})})
        report = scanner_for(rm).scan()
        by = {h.resource: h for h in report.hits}
        self.assertTrue(by['GPIB1::22::INSTR'].needs_serial and by['USB0::0x2A8D::0x0101::MY222::INSTR'].needs_serial)
        self.assertEqual({by['GPIB1::22::INSTR'].serial, by['USB0::0x2A8D::0x0101::MY222::INSTR'].serial}, {'MY111', 'MY222'})
        self.assertFalse(by['GPIB1::4::INSTR'].needs_serial)

    def test_same_instrument_on_two_resources_is_one_instrument(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies=IDN_34410('MY111')), 'USB0::0x2A8D::0x0101::MY111::INSTR': dict(replies=IDN_34410('MY111'))})
        report = scanner_for(rm).scan()
        first, second = report.hits
        self.assertEqual(second.alias_of, first.resource)
        self.assertEqual(len(report.identified()), 1)
        self.assertFalse(first.needs_serial)

    def test_two_3458a_have_no_serial_to_tell_them_apart(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies=IDN_3458), 'GPIB0::23::INSTR': dict(replies=IDN_3458)})
        report = scanner_for(rm).scan()
        self.assertTrue(all(h.needs_serial for h in report.hits))
        self.assertTrue(all(not h.alias_of for h in report.hits))                # the resource is all there is to choose by


class GpibNames(unittest.TestCase):
    def test_board_without_listed_instruments_is_asked_address_by_address(self):
        """pyvisa-py (and some adapters) list GPIB1::INTFC but no instruments: addresses 0-30 are asked, an empty address costs no timeout."""
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458)}, listed=['GPIB1::INTFC', 'USB0::INTFC'])
        report = scanner_for(rm).scan()
        self.assertEqual(rm.opened, [f'GPIB1::{a}::INSTR' for a in range(31)])
        self.assertEqual([(h.resource, h.key) for h in report.hits], [('GPIB1::22::INSTR', '3458A')])
        self.assertEqual(report.empty_gpib, 30)
        self.assertTrue(any('GPIB1' in w or 'GPIB' in w for w in report.warnings))
        self.assertTrue(rm.only_queries())

    def test_listed_instruments_are_not_asked_twice_when_all_addresses_are_requested(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']})}, listed=['GPIB0::INTFC', 'GPIB0::22::INSTR'])
        scanner_for(rm, probe_all_gpib=True).scan()
        self.assertEqual(rm.opened.count('GPIB0::22::INSTR'), 1)
        self.assertEqual(len(rm.opened), 31)

    def test_listed_instruments_alone_are_not_extended_by_default(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']})}, listed=['GPIB0::INTFC', 'GPIB0::22::INSTR'])
        scanner_for(rm).scan()
        self.assertEqual(rm.opened, ['GPIB0::22::INSTR'])

    def test_the_adapter_number_is_whatever_the_backend_lists(self):
        for board in (0, 1, 3):
            name = f'GPIB{board}::22::INSTR'
            rm = FakeRM({name: dict(replies=IDN_3458)})
            (hit,) = scanner_for(rm).scan().hits
            self.assertEqual((hit.resource, hit.key), (name, '3458A'))


class Backends(unittest.TestCase):
    def test_describe_backend(self):
        py = type('PyVisaLibrary', (), {'__module__': 'pyvisa_py.highlevel', 'library_path': 'py'})()
        ni = type('IVIVisaLibrary', (), {'__module__': 'pyvisa.ctwrapper.highlevel', 'library_path': r'C:\WINDOWS\system32\visa64.dll'})()
        self.assertEqual(S.describe_backend(FakeRM({}, visalib=py))[0], 'pyvisa-py')
        self.assertEqual(S.describe_backend(FakeRM({}, visalib=ni))[0], 'VISA library (NI-VISA / Keysight)')
        self.assertIn('visa64', S.describe_backend(FakeRM({}, visalib=ni))[1])

    def test_pyvisa_py_without_gpib_says_so(self):
        py = type('PyVisaLibrary', (), {'__module__': 'pyvisa_py.highlevel', 'library_path': 'py'})()
        rm = FakeRM({'USB0::1::2::3::INSTR': dict(replies={'*IDN?': SAMPLES['34972A']})}, visalib=py)
        report = scanner_for(rm).scan()
        self.assertTrue(any('pyvisa-py lists no GPIB' in w for w in report.warnings))

    def test_pyvisa_not_installed(self):
        with mock.patch.dict(sys.modules, {'pyvisa': None}):
            with self.assertRaises(S.ScanError) as cm:
                S.default_resource_manager()
        self.assertIn('pip install pyvisa', str(cm.exception))

    def test_no_visa_library(self):
        def boom(*a):
            raise OSError('Could not locate a VISA implementation. Install either the NI binary or pyvisa-py.')
        with mock.patch.dict(sys.modules, {'pyvisa': types.SimpleNamespace(ResourceManager=boom)}):
            with self.assertRaises(S.ScanError) as cm:
                S.default_resource_manager()
        self.assertIn('No VISA library was found', str(cm.exception))
        self.assertIn('NI-VISA', str(cm.exception))

    def test_falls_back_to_pyvisa_py(self):
        calls = []

        def rm(*a):
            calls.append(a)
            if not a:
                raise OSError('no NI library')
            return 'rm-py'
        with mock.patch.dict(sys.modules, {'pyvisa': types.SimpleNamespace(ResourceManager=rm)}):
            self.assertEqual(S.default_resource_manager(), 'rm-py')
        self.assertEqual(calls, [(), ('@py',)])

    def test_list_failure_is_a_scan_error(self):
        class Bad(FakeRM):
            def list_resources(self, query='?*::INSTR'):
                raise RuntimeError('driver service not running')
        with self.assertRaises(S.ScanError) as cm:
            scanner_for(Bad({})).scan()
        self.assertIn('driver service', str(cm.exception))


class Job(unittest.TestCase):
    def wait(self, job, kinds, seconds=5):
        got, end = [], time.time() + seconds
        while time.time() < end:
            got += job.poll()
            if any(k in kinds for k, _p in got):
                return got
            time.sleep(0.01)
        return got

    def test_runs_in_a_thread_and_reports_progress(self):
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies=IDN_3458), 'USB0::1::2::3::INSTR': dict(replies={'*IDN?': SAMPLES['34972A']})})
        job = S.ScanJob(scanner_for(rm)).start()
        got = self.wait(job, ('done', 'error'))
        kinds = [k for k, _p in got]
        self.assertIn('progress', kinds)
        self.assertEqual(kinds[-1], 'done')
        self.assertEqual(len(got[-1][1].identified()), 2)
        self.assertTrue(job.thread.daemon)

    def test_cancel_returns_at_once_even_when_a_resource_hangs(self):
        gate = threading.Event()
        rm = FakeRM({'GPIB0::1::INSTR': dict(replies={}, block=gate), 'GPIB0::2::INSTR': dict(replies=IDN_3458)})
        job = S.ScanJob(scanner_for(rm)).start()
        time.sleep(0.1)
        t0 = time.time()
        job.cancel()
        self.assertEqual(job.poll(), [])
        self.assertLess(time.time() - t0, 0.5)
        gate.set()                                       # let the stuck call finish: its result is dropped
        time.sleep(0.3)
        self.assertEqual(job.poll(), [])

    def test_cancel_between_resources_stops_the_scan(self):
        rm = FakeRM({f'GPIB0::{a}::INSTR': dict(replies=IDN_3458) for a in range(1, 6)})
        cancel = threading.Event()
        seen = []

        def progress(i, n, msg):
            seen.append(msg)
            if i == 1:
                cancel.set()
        report = scanner_for(rm).scan(progress=progress, cancel=cancel)
        self.assertTrue(report.cancelled)
        self.assertLess(len(rm.opened), 5)

    def test_an_exception_becomes_an_error_event(self):
        job = S.ScanJob(None, runner=lambda progress, cancel: (_ for _ in ()).throw(RuntimeError('boom'))).start()
        got = self.wait(job, ('error',))
        self.assertEqual(got[-1][0], 'error')
        self.assertIn('boom', got[-1][1])

    def test_no_visa_is_an_error_event_with_the_message(self):
        def factory():
            raise S.ScanError('No VISA library was found')
        job = S.ScanJob(S.Scanner(rm_factory=factory)).start()
        got = self.wait(job, ('error',))
        self.assertEqual(got[-1], ('error', 'No VISA library was found'))


class Memory(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'lab_registry.sqlite3'
        self.clock = [S.datetime(2026, 10, 23, 9, 0, 0)]
        self.mem = S.ResourceMemory(self.path, workstation='tech1@benchpc', now=lambda: self.clock[0])
        S.clear_session_cache()

    def tearDown(self):
        self.dir.cleanup()

    def hit(self, resource='GPIB1::22::INSTR', key='3458A', serial='', idn='Keysight 3458A'):
        return S.Hit(resource, 'GPIB', 'identified', 'ID?', idn, S.parse_identity(idn), key, 'x')

    def test_reading_creates_nothing(self):
        self.assertEqual(self.mem.remembered(), [])
        self.assertFalse(self.path.exists())

    def test_remember_and_read_back(self):
        self.mem.remember(self.hit())
        (rec,) = self.mem.remembered()
        self.assertEqual((rec.model, rec.resource, rec.serial, rec.idn, rec.last_seen), ('3458A', 'GPIB1::22::INSTR', '', 'Keysight 3458A', '2026-10-23 09:00:00'))
        con = sqlite3.connect(self.path)
        cols = [r[1] for r in con.execute('PRAGMA table_info(instrument_resources)')]
        con.close()
        self.assertEqual(cols, ['workstation', 'model', 'serial', 'resource', 'idn', 'last_seen'])

    def test_one_row_per_model_and_serial_and_the_newest_address_wins(self):
        h = self.hit(idn='Agilent Technologies,34410A,MY111,2.35', key='34410A', resource='GPIB0::22::INSTR')
        self.mem.remember(h)
        self.clock[0] = S.datetime(2026, 10, 24, 9, 0, 0)
        self.mem.remember(self.hit(idn='Agilent Technologies,34410A,MY111,2.35', key='34410A', resource='GPIB1::22::INSTR'))
        self.mem.remember(self.hit(idn='Agilent Technologies,34410A,MY222,2.35', key='34410A', resource='USB0::1::2::MY222::INSTR'))
        recs = self.mem.remembered('34410A')
        self.assertEqual({(r.serial, r.resource) for r in recs}, {('MY111', 'GPIB1::22::INSTR'), ('MY222', 'USB0::1::2::MY222::INSTR')})

    def test_per_workstation(self):
        self.mem.remember(self.hit())
        other = S.ResourceMemory(self.path, workstation='tech2@otherpc')
        self.assertEqual(other.remembered(), [])

    def test_only_identified_results_are_remembered(self):
        with self.assertRaises(ValueError):
            self.mem.remember(S.Hit('GPIB0::1::INSTR', 'GPIB', 'no reply'))

    def test_forget(self):
        self.mem.remember(self.hit())
        self.mem.forget('3458A')
        self.assertEqual(self.mem.remembered(), [])

    def test_damaged_file_reads_as_empty(self):
        self.path.write_bytes(b'not a database at all' * 20)
        self.assertEqual(self.mem.remembered(), [])

    def test_status_column(self):
        h = self.hit()
        self.assertEqual(self.mem.status_of(h), '')
        self.mem.remember(h)
        self.assertEqual(self.mem.status_of(h), 'remembered')
        self.assertEqual(self.mem.status_of(self.hit(resource='GPIB0::22::INSTR')), 'address changed (was GPIB1::22::INSTR)')

    def test_calibration_procedures_database_is_not_touched(self):
        main = Path(self.dir.name) / 'calibration_procedures.sqlite3'
        con = sqlite3.connect(main)
        con.execute('CREATE TABLE procedures (id INTEGER)')
        con.commit()
        con.close()
        before = main.read_bytes()
        self.mem.remember(self.hit())
        self.assertEqual(main.read_bytes(), before)

    def test_remembered_resource_is_a_default_only_after_a_check_confirms_it(self):
        self.mem.remember(self.hit())
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458)})
        self.assertEqual(S.default_resource('3458A', self.mem, scanner_for(rm)), 'GPIB1::22::INSTR')
        self.assertEqual(rm.resources['GPIB1::22::INSTR'].queries, ['ID?'])          # the ONE query this family answers: no *IDN? to a 3458A
        self.assertTrue(rm.only_queries())

    def test_renumbered_adapter_is_not_offered(self):
        self.mem.remember(self.hit())
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies=IDN_3458)})                  # now on board 0; GPIB1 is gone
        self.assertEqual(S.default_resource('3458A', self.mem, scanner_for(rm)), '')
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies={'*IDN?': SAMPLES['34401A']})})   # GPIB1::22 is now something else
        self.assertEqual(S.default_resource('3458A', self.mem, scanner_for(rm)), '')

    def test_serial_mismatch_is_not_offered(self):
        self.mem.remember(self.hit(resource='GPIB0::22::INSTR', key='34410A', idn='Agilent Technologies,34410A,MY111,2.35'))
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies=IDN_34410('MY999'))})
        self.assertEqual(S.default_resource('34410A', self.mem, scanner_for(rm)), '')

    def test_confirmed_once_per_session(self):
        self.mem.remember(self.hit())
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458)})
        sc = scanner_for(rm)
        self.assertEqual(S.default_resource('3458A', self.mem, sc), 'GPIB1::22::INSTR')
        self.assertEqual(S.default_resource('3458A', self.mem, sc), 'GPIB1::22::INSTR')
        self.assertEqual(len(rm.resources['GPIB1::22::INSTR'].queries), 1)
        S.clear_session_cache()                                                     # a new session asks again
        S.default_resource('3458A', self.mem, sc)
        self.assertEqual(len(rm.opened), 2)

    def test_two_serials_need_the_serial(self):
        for serial, res in (('MY111', 'GPIB0::22::INSTR'), ('MY222', 'GPIB0::23::INSTR')):
            self.mem.remember(self.hit(resource=res, key='34410A', idn=f'Agilent Technologies,34410A,{serial},2.35'))
        rm = FakeRM({'GPIB0::22::INSTR': dict(replies=IDN_34410('MY111')), 'GPIB0::23::INSTR': dict(replies=IDN_34410('MY222'))})
        self.assertEqual(S.default_resource('34410A', self.mem, scanner_for(rm)), '')
        self.assertEqual(S.default_resource('34410A', self.mem, scanner_for(rm), serial='MY222'), 'GPIB0::23::INSTR')

    def test_remembered_serial_port_is_never_checked_blind(self):
        self.mem.remember(S.Hit('ASRL9::INSTR', 'ASRL', 'identified', 'driver identify()', 'FLUKE,8808A,SIM0001,1.0', S.parse_identity('FLUKE,8808A,SIM0001,1.0'), '8808A', 'x'))
        rm = FakeRM({'ASRL9::INSTR': dict(replies={'*IDN?': SAMPLES['8808A']})})
        self.assertEqual(S.default_resource('8808A', self.mem, scanner_for(rm)), '')
        self.assertEqual(rm.opened, [])


class WindowRows(unittest.TestCase):
    def test_serial_names(self):
        self.assertEqual(S.serial_resource_names(['COM9', 'COM10', 'COM9', '/dev/ttyUSB0', 'ASRL3::INSTR']),
                         ['ASRL9::INSTR', 'ASRL10::INSTR', 'ASRL/dev/ttyUSB0::INSTR', 'ASRL3::INSTR'])

    def test_serial_choices_are_the_checkable_families(self):
        keys = [k for k, _l in S.serial_family_choices()]
        self.assertIn('8808A', keys)
        self.assertIn('5560A', keys)
        self.assertNotIn('3458A', keys)

    def test_rows_show_resource_instrument_key_serial_and_state(self):
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458), 'USB0::1::2::MY5::INSTR': dict(replies=IDN_34410('MY5')), 'GPIB1::9::INSTR': dict(replies={}),
                     'USB0::7::7::7::INSTR': dict(replies={'*IDN?': 'ACME,Thing,1,1'})})
        rows = S.result_rows(scanner_for(rm).scan().hits)
        by = {r[0][0]: r for r in rows}
        self.assertEqual(by['GPIB1::22::INSTR'][0][:4], ('GPIB1::22::INSTR', 'Keysight 3458A', '3458A', '-'))
        self.assertEqual(by['USB0::1::2::MY5::INSTR'][0][2:4], ('34410A', 'MY5'))
        self.assertEqual(by['GPIB1::22::INSTR'][1], 'pass')
        self.assertEqual(by['GPIB1::9::INSTR'][1], 'error')
        self.assertEqual(by['USB0::7::7::7::INSTR'][1], 'pending')
        self.assertEqual([r[0][0] for r in rows][:2], sorted(['GPIB1::22::INSTR', 'USB0::1::2::MY5::INSTR']))      # identified first
        self.assertIn('Identified', by['GPIB1::22::INSTR'][0][4])

    def test_duplicate_rows_say_to_choose_by_serial(self):
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_34410('MY111')), 'GPIB1::23::INSTR': dict(replies=IDN_34410('MY222'))})
        for values, _tag, _h in S.result_rows(scanner_for(rm).scan().hits):
            self.assertIn('choose by serial', values[4])


class Wiring(unittest.TestCase):

    def test_the_new_modules_are_in_no_procedure_fingerprint(self):
        """Adding / changing them cannot flip a verified procedure to 'Changed since verification'."""
        import json
        for f in sorted((ROOT / 'Procedures').glob('*.procedure.json')):
            code = json.loads(f.read_text(encoding='utf-8'))['fingerprint']['code']
            self.assertFalse([c for c in code if 'instrument_scan' in c], f.name)
        import verified
        self.assertFalse([c for c in verified.USER_CODE if 'instrument_scan' in c])


class NoEngineEdits(unittest.TestCase):
    def test_new_modules_do_not_touch_the_fingerprinted_engines(self):
        """The new code must not import or patch the procedure engines (their files are in the verified procedures' fingerprints)."""
        text = (ROOT / 'instrument_scan.py').read_text(encoding='utf-8')
        for engine in ('handheld_dmm', 'truevolt_verification', 'dacq_verification', 'fgen_verification', 'mdo4000c_verification', 'tds2000c_verification',
                       'keithley2000_verification', 'agilent34410a_verification', 'fluke8808a_verification'):
            self.assertNotIn(engine, text)


if __name__ == '__main__':
    unittest.main()
