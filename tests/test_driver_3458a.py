"""Keysight / Agilent 3458A driver (drivers/agilent_3458a.py) and its simulator (drivers/simulated_3458a.py).

Part 1: the command registry (page references, verified flags, locked commands, nothing that calibrates), the command strings exactly as the User's Guide prints them.
Part 2: reading parsing: ASCII, SREAL and DREAL (hand-built binary samples), the overload value, the range tables.
Part 3: set / read back / compare, a write is never retried, only read-only queries are, the error queue, timeouts that scale with NPLC and ACAL, secrets stay out of the log.
Part 4: the reset (device clear, RESET, CSB, barrier, drain, END ALWAYS, known state), identity, remote / local, the read-only state summary.
Part 5: a run on the simulated bench: an applied source and the calibrator measured over the DCI ranges 100 uA to 1 A, null, binary formats, autocal.
Run:  python -m unittest tests.test_driver_3458a"""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
import drivers  # noqa: E402
from drivers import Agilent3458A, CommandLog, InstrumentError, SafetyError, Transport, TransportError  # noqa: E402
from drivers import agilent_3458a as M  # noqa: E402
from drivers.simulated_3458a import make_3458a_bench  # noqa: E402

PASSWORD = 'SECRET_CODE_XYZ'


class Wire(Transport):
    """Scripted fake: `answers` maps an upper-case command to a reply (str, list consumed in order, or an exception); records every call."""
    name = 'WIRE'

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls = []                     # ('W' | 'Q' | 'R' | 'RB' | ..., text)
        self._reply = None
        self.raw = b''

    def open(self): pass
    def close(self): pass

    def _answer(self, cmd):
        rep = self.answers.get(cmd.strip().upper())
        if isinstance(rep, list):
            rep = rep.pop(0) if len(rep) > 1 else rep[0]
        if isinstance(rep, BaseException):
            raise rep
        return rep

    def write(self, text):
        self.calls.append(('W', text))
        self._reply = self._answer(text)

    def read(self):
        self.calls.append(('R', ''))
        if self._reply is None:
            raise TransportError('nothing to read')
        reply, self._reply = self._reply, None
        return reply

    def query(self, text):
        self.calls.append(('Q', text))
        rep = self._answer(text)
        if rep is None:
            raise TransportError('nothing to read')
        return rep

    def read_raw(self, count):
        self.calls.append(('RB', count))
        return self.raw

    def set_timeout(self, seconds):
        self.calls.append(('T', seconds))

    def writes(self):
        return [t for k, t in self.calls if k == 'W']

    def queries(self):
        return [t for k, t in self.calls if k == 'Q']


def make(answers=None, opened=True):
    wire = Wire(answers)
    d = Agilent3458A(wire, CommandLog(), label='3458A')
    d._open = opened
    return d, wire


def sim():
    bench, ft, dt = make_3458a_bench('5522A')
    d = Agilent3458A(dt, CommandLog(), label='3458A')
    d.connect()
    d.reset_to_defaults()
    return d, dt, ft, bench


class TestRegistry(unittest.TestCase):
    REG = cmdreg.merge_commands(Agilent3458A)

    def test_lint_clean(self):
        self.assertEqual(cmdreg.lint_registry(self.REG), [])

    def test_every_command_has_a_page_and_a_verified_flag(self):
        for key, cmd in self.REG.items():
            self.assertIsInstance(cmd.verified, bool, key)
            self.assertIn(' p. ', cmd.ref, key)
            self.assertIn("3458A User's Guide", cmd.ref, key)

    def test_locked_plumbing(self):
        for key in ('reset', 'status.clear', 'opc.query', 'err.query', 'id.query', 'acal', 'acal.secured'):
            self.assertEqual(self.REG[key].risk, 'locked', key)
        self.assertEqual((self.REG['reset'].template, self.REG['reset'].verified, self.REG['reset'].kind), ('RESET', True, 'set'))
        self.assertIn('332', self.REG['reset'].ref)

    def test_command_strings_as_printed(self):
        want = {'reset': 'RESET', 'status.clear': 'CSB', 'opc.query': 'STB?', 'err.query': 'ERRSTR?', 'id.query': 'ID?', 'temp.query': 'TEMP?', 'rev.query': 'REV?',
                'err.register': 'ERR?', 'err.aux': 'AUXERR?', 'func.query': 'FUNC?', 'func.set': 'FUNC {function},{max_input:.9G}', 'nplc.set': 'NPLC {nplc:.9G}',
                'aper.set': 'APER {seconds:.9G}', 'ndig.set': 'NDIG {digits:d}', 'trig.set': 'TRIG {event}', 'trig.sgl': 'TRIG SGL', 'end.set': 'END {mode}',
                'oformat.set': 'OFORMAT {fmt}', 'qformat.set': 'QFORMAT {type}', 'math.set': 'MATH {operation}', 'smath.offset': 'SMATH OFFSET,{value:.9G}',
                'rmath.offset': 'RMATH OFFSET', 'acal': 'ACAL {type}', 'acal.secured': 'ACAL {type},{code}', 'acband.set': 'ACBAND {low:.9G},{high:.9G}',
                'level.set': 'LEVEL {percent:.9G},{coupling}', 'nrdgs.set': 'NRDGS {count:d},{event}', 'lfreq.line': 'LFREQ LINE', 'azero.set': 'AZERO {mode}'}
        for key, template in want.items():
            self.assertEqual(self.REG[key].template, template, key)

    def test_nothing_that_calibrates_or_changes_security(self):
        for key, cmd in self.REG.items():
            head = cmd.template.split()[0].rstrip('?').upper()
            self.assertNotIn(head, {'CAL', 'SCAL', 'SECURE', 'CALSTR', 'PRESET', 'TEST', 'LOCK', 'ADDRESS', 'DISP', 'SCRATCH'}, key)
        self.assertEqual([k for k, c in self.REG.items() if c.template.startswith('ACAL')], ['acal', 'acal.secured'])

    def test_secret_code_is_a_secret_placeholder(self):
        self.assertTrue(self.REG['acal.secured'].secret)
        self.assertFalse(self.REG['acal'].secret)

    def test_sgl_is_an_action_not_a_settable_event(self):
        self.assertNotIn('SGL', self.REG['trig.set'].placeholders['event'].enum)
        self.assertEqual(self.REG['trig.sgl'].kind, 'action')

    def test_every_set_with_a_readback_has_a_confirmation_rule(self):
        for key, cmd in self.REG.items():
            if cmd.kind == 'set' and cmd.readback:
                self.assertIn(key, M.CONFIRM, key)
                self.assertEqual(M.CONFIRM[key][0], cmd.readback, key)


class TestParsing(unittest.TestCase):
    def test_ascii_readings(self):
        self.assertEqual(M.decode_reading('+1.00000000E-03\r\n'), 1e-3)
        self.assertEqual(M.decode_reading(b'-4.50000000E+00'), -4.5)
        self.assertEqual(len('+1.00000000E-03'), 15)                        # the 15 bytes per ASCII reading of the guide (p. 308)
        for bad in ('', 'abc', '1.0,2.0'):
            with self.assertRaises(InstrumentError):
                M.decode_reading(bad)

    def test_binary_samples(self):
        self.assertEqual(M.decode_reading(bytes.fromhex('3F800000'), 'SREAL'), 1.0)
        self.assertEqual(M.decode_reading(bytes.fromhex('C0200000'), 'SREAL'), -2.5)
        self.assertEqual(M.decode_reading(bytes.fromhex('3FF0000000000000'), 'DREAL'), 1.0)
        self.assertEqual(M.decode_reading(bytes.fromhex('C004000000000000'), 'DREAL'), -2.5)
        self.assertAlmostEqual(M.decode_reading(bytes.fromhex('3A83126F'), 'SREAL'), 1e-3, places=9)
        self.assertEqual(M.decode_reading(M.encode_reading(1.2345678901234, 'DREAL'), 'DREAL'), 1.2345678901234)
        self.assertEqual(M.decode_reading(M.encode_reading(0.25, 'SREAL'), 'SREAL'), 0.25)

    def test_binary_wrong_length_or_format(self):
        with self.assertRaises(InstrumentError):
            M.decode_reading(b'\x00\x00\x00', 'SREAL')
        with self.assertRaises(InstrumentError):
            M.decode_reading(b'\x00' * 8, 'SINT')
        with self.assertRaises(InstrumentError):
            M.encode_reading(1.0, 'DINT')

    def test_the_guides_sreal_conversion_program_agrees(self):
        """UG p. 153 converts four bytes A,B,C,D by hand; the struct decoding must give the same number for the same bytes."""
        def guide(a, b, c, d):
            s = 1
            if a > 127:
                s, a = -1, a - 128
            a = a * 2 - 127
            if b > 127:
                a += 1
            else:
                b += 128
            return s * (b * 65536.0 + c * 256.0 + d) * 2.0 ** (a - 23)
        for raw in (bytes.fromhex('3F800000'), bytes.fromhex('C0200000'), bytes.fromhex('3A83126F'), bytes.fromhex('42F6E979')):
            self.assertAlmostEqual(guide(*raw), M.decode_reading(raw, 'SREAL'), places=6)

    def test_overload(self):
        for text in ('+1.00000000E+38', '-1.00000000E+38'):
            with self.assertRaises(M.OverloadError):
                M.check_overload(M.decode_reading(text))
        sreal_overload = M.encode_reading(1e38, 'SREAL')                    # slightly below 1E+38 after the 32 bit rounding (UG p. 153)
        self.assertLess(M.decode_reading(sreal_overload, 'SREAL'), 1e38)
        with self.assertRaises(M.OverloadError):
            M.check_overload(M.decode_reading(sreal_overload, 'SREAL'))
        with self.assertRaises(M.OverloadError):
            M.check_overload(float('nan'))
        self.assertEqual(M.check_overload(1.5), 1.5)

    def test_range_tables(self):
        self.assertEqual(M.select_range('DCI', 1e-3), (1e-3, 1.2e-3))
        self.assertEqual(M.select_range('DCI', 1.2e-3), (1e-3, 1.2e-3))
        self.assertEqual(M.select_range('DCI', 1.3e-3)[0], 1e-2)
        self.assertEqual(M.select_range('DCI', 0.12e-6)[0], 1e-7)
        self.assertEqual(M.select_range('DCI', 1.0), (1.0, 1.05))
        self.assertEqual(M.select_range('DCI', 1.2), (1.0, 1.05))
        self.assertEqual(M.select_range('DCV', 1000.0), (1000.0, 1050.0))
        self.assertEqual(M.select_range('DCV', 0.1), (0.1, 0.12))
        self.assertEqual(M.select_range('ACV', 0.01), (0.01, 0.012))
        self.assertEqual(M.select_range('OHM', 12.0), (10.0, 12.0))
        self.assertEqual(M.select_range('OHMF', 1.2e9), (1e9, 1.2e9))
        self.assertEqual(M.select_range('ACI', 120e-6)[0], 1e-4)
        for bad in (('DCI', 1.21), ('DCV', 1001.0), ('DCV', 0.0), ('DCV', -1.0), ('FREQ', 1.0), ('DCV', float('nan'))):
            with self.assertRaises(InstrumentError, msg=bad):
                M.select_range(*bad)
        self.assertEqual([r for r, _f in M.RANGES['DCI']], [1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0])

    def test_nplc_grid(self):
        for ok in (0, 0.0001, 0.5, 1, 2, 10, 20, 100, 1000):
            self.assertTrue(M.nplc_ok(ok), ok)
        for bad in (-1, 1.5, 15, 1001, float('nan')):
            self.assertFalse(M.nplc_ok(bad), bad)


class TestWrites(unittest.TestCase):
    def test_configure_sends_exactly_the_printed_commands_in_order(self):
        d, dt, ft, bench = sim()
        dt.sent.clear()
        d.configure('DCI', 1e-3, nplc=100, ndig=8, trigger='SYN')
        self.assertEqual(dt.sent, ['FUNC DCI,0.001', 'FUNC?', 'ARANGE?', 'NPLC 100', 'NPLC?', 'NDIG 8', 'NDIG?', 'TRIG SYN', 'TRIG?', 'ERRSTR?'])

    def test_aperture_replaces_nplc(self):
        d, dt, ft, bench = sim()
        dt.sent.clear()
        d.configure('DCV', 10.0, aperture=1e-3)
        self.assertIn('APER 0.001', dt.sent)
        self.assertNotIn('NPLC', ' '.join(x.split()[0] for x in dt.sent))

    def test_exponent_forms_on_the_wire(self):
        d, dt, ft, bench = sim()
        dt.sent.clear()
        d.configure('DCI', 1e-6, nplc=10)
        self.assertEqual(dt.sent[0], 'FUNC DCI,1E-06')
        d.set_confirmed('smath.offset', value=2.5e-9)
        self.assertIn('SMATH OFFSET,2.5E-09', dt.sent)

    def test_validation_happens_before_anything_is_sent(self):
        d, dt, ft, bench = sim()
        dt.sent.clear()
        for args, kw in ((('FREQ', 1.0), {}), (('DCV', 0.0), {}), (('DCI', 5.0), {}), (('DCV', 10.0), dict(nplc=2.5)), (('DCV', 10.0), dict(trigger='LEVEL')),
                         (('DCV', 10.0), dict(aperture=2.0))):
            with self.assertRaises(InstrumentError, msg=(args, kw)):
                d.configure(*args, **kw)
        self.assertEqual(dt.sent, [])

    def test_readback_mismatch_raises_and_the_write_is_not_repeated(self):
        d, wire = make({'FUNC?': '6,+1.00000000E+00', 'ARANGE?': '0'})
        with self.assertRaises(InstrumentError) as cm:
            d.configure('DCI', 1e-3)
        self.assertIn('not accepted', str(cm.exception))
        self.assertEqual(wire.writes(), ['FUNC DCI,0.001'])
        self.assertEqual(wire.queries(), ['FUNC?'])

    def test_autorange_left_on_is_refused(self):
        d, wire = make({'FUNC?': '6,+1.00000000E-03', 'ARANGE?': '1'})
        with self.assertRaises(InstrumentError) as cm:
            d.configure('DCI', 1e-3)
        self.assertIn('autorange', str(cm.exception))
        self.assertEqual(wire.writes(), ['FUNC DCI,0.001'])

    def test_range_reply_may_be_the_nominal_range_or_the_full_scale(self):
        for reply in ('6,+1.00000000E-03', '6,+1.20000000E-03', '6,1E-3'):
            d, wire = make({'FUNC?': reply, 'ARANGE?': '0', 'NPLC?': '10', 'TRIG?': '5', 'ERRSTR?': '0,"NO ERROR"'})
            d.configure('DCI', 1e-3)
        d, wire = make({'FUNC?': '6,+1.00000000E-02', 'ARANGE?': '0'})
        with self.assertRaises(InstrumentError):
            d.configure('DCI', 1e-3)

    def test_wrong_function_in_the_readback_is_refused(self):
        d, wire = make({'FUNC?': '1,+1.00000000E-03', 'ARANGE?': '0'})
        with self.assertRaises(InstrumentError):
            d.configure('DCI', 1e-3)

    def test_a_failed_write_is_never_retried(self):
        d, wire = make({'FUNC DCI,0.001': TransportError('write failed')})
        with self.assertRaises(TransportError):
            d.configure('DCI', 1e-3)
        self.assertEqual(wire.writes(), ['FUNC DCI,0.001'])
        d, wire = make({'RESET': TransportError('write failed')})
        rep = d.reset_to_defaults()
        self.assertFalse(rep.ok)
        self.assertEqual(wire.writes().count('RESET'), 1)

    def test_only_read_only_queries_retry(self):
        d, wire = make({'ERRSTR?': [TransportError('timeout'), TransportError('timeout'), '0,"NO ERROR"']})
        d.check_errors('ctx')
        self.assertEqual(wire.queries(), ['ERRSTR?'] * 3)
        d, wire = make({'TEMP?': [TransportError('timeout'), '+38.9']})
        self.assertEqual(d.temperature(), 38.9)
        # a reading is a trigger: it is never retried
        d, wire = make()
        d.trigger = 'SYN'
        with self.assertRaises(InstrumentError):
            d.read()
        self.assertEqual([k for k, _t in wire.calls].count('R'), 1)

    def test_set_confirmed_unknown_key(self):
        d, wire = make()
        with self.assertRaises(InstrumentError):
            d.set_confirmed('nope.set')
        self.assertEqual(wire.calls, [])

    def test_set_confirmed_compares_every_field(self):
        d, wire = make({'ACBAND?': '+2.00000000E+01,+2.00000000E+06', 'LEVEL?': '+0.00000000E+00,2'})
        self.assertTrue(d.set_confirmed('acband.set', low=20.0, high=2e6))
        self.assertEqual(wire.writes(), ['ACBAND 20,2000000'])
        with self.assertRaises(InstrumentError):
            d.set_confirmed('acband.set', low=20.0, high=1e6)
        d.set_confirmed('level.set', percent=0.0, coupling='AC')
        with self.assertRaises(InstrumentError):
            d.set_confirmed('level.set', percent=0.0, coupling='DC')

    def test_readback_accepts_alpha_or_numeric_replies(self):
        d, wire = make({'END?': 'ALWAYS'})
        d.set_confirmed('end.set', mode='ALWAYS')
        d, wire = make({'END?': '2'})
        d.set_confirmed('end.set', mode='ALWAYS')
        d, wire = make({'END?': '0'})
        with self.assertRaises(InstrumentError):
            d.set_confirmed('end.set', mode='ALWAYS')


class TestErrors(unittest.TestCase):
    def test_error_queue_is_drained_and_reported(self):
        d, dt, ft, bench = sim()
        dt.errors = [(103, 'SYNTAX ERROR'), (106, 'PARAMETER OUT OF RANGE')]
        with self.assertRaises(InstrumentError) as cm:
            d.check_errors('configuring')
        self.assertIn('103,"SYNTAX ERROR"', str(cm.exception))
        self.assertIn('106,"PARAMETER OUT OF RANGE"', str(cm.exception))
        self.assertIn('configuring', str(cm.exception))
        d.check_errors()                                                    # drained

    def test_empty_queue_is_silent(self):
        d, wire = make({'ERRSTR?': '0,"NO ERROR"'})
        d.check_errors('x')
        self.assertEqual(wire.queries(), ['ERRSTR?'])

    def test_a_queue_that_never_empties_stops(self):
        d, wire = make({'ERRSTR?': '103,"SYNTAX ERROR"'})
        with self.assertRaises(InstrumentError):
            d.check_errors()
        self.assertLessEqual(len(wire.queries()), 40)

    def test_configure_ends_with_an_error_check(self):
        d, dt, ft, bench = sim()
        dt.errors = [(103, 'SYNTAX ERROR')]
        with self.assertRaises(InstrumentError):
            d.configure('DCV', 10.0)

    def test_overload_is_an_error_not_a_number(self):
        d, dt, ft, bench = sim()
        d.configure('DCI', 1e-3)
        dt.apply('DCI', 0.5)
        with self.assertRaises(M.OverloadError):
            d.read()

    def test_read_needs_syn_or_sgl(self):
        d, dt, ft, bench = sim()
        for event in ('AUTO', 'HOLD'):
            d.trigger = event
            with self.assertRaises(InstrumentError):
                d.read()

    def test_no_reading_is_reported(self):
        d, dt, ft, bench = sim()
        d.configure('DCV', 10.0)
        dt.drop_readings = True
        with self.assertRaises(InstrumentError) as cm:
            d.read()
        self.assertIn('no reading arrived', str(cm.exception))


class TestTimeouts(unittest.TestCase):
    def test_reading_timeout_scales_with_nplc(self):
        d, dt, ft, bench = sim()
        values = []
        for plc in (1, 10, 100, 1000):
            d.configure('DCV', 10.0, nplc=plc)
            values.append(d.reading_timeout())
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], d.DEFAULT_TIMEOUT)
        self.assertGreater(values[-1], 1000 * 0.02 * 2)                    # more than one 1000 PLC reading with autozero at 50 Hz
        self.assertEqual(dt.timeout, values[-1])                            # configure applies it to the transport

    def test_autozero_and_ac_lengthen_the_timeout(self):
        d, dt, ft, bench = sim()
        d.configure('DCV', 10.0, nplc=1000)
        with_az = d.reading_timeout()
        d.configure('DCV', 10.0, nplc=1000, autozero=False)
        self.assertLess(d.reading_timeout(), with_az)
        d.configure('ACV', 1.0, nplc=1)
        self.assertGreater(d.reading_timeout(), d.DEFAULT_TIMEOUT)

    def test_aperture_timeout(self):
        d, dt, ft, bench = sim()
        d.configure('DCV', 10.0, aperture=1.0)
        self.assertGreater(d.reading_timeout(), 2.0)

    def test_acal_timeouts_cover_the_guides_durations(self):
        self.assertEqual(M.ACAL_SECONDS, {'ALL': 960, 'DCV': 165, 'AC': 165, 'OHMS': 660})
        self.assertEqual(M.ACAL_SETTLE_SECONDS, {'ALL': 1800, 'DCV': 900, 'AC': 900, 'OHMS': 1800})
        for kind, seconds in M.ACAL_SECONDS.items():
            self.assertGreater(Agilent3458A.acal_timeout(kind), seconds)

    def test_acal_raises_the_transport_timeout_and_restores_it(self):
        d, dt, ft, bench = sim()
        seen = []
        real = dt.set_timeout
        dt.set_timeout = lambda s: (seen.append(s), real(s))[1]
        dt.timeout = 12.0
        info = d.acal('ALL', inputs_disconnected=True)
        self.assertEqual(seen[0], Agilent3458A.acal_timeout('ALL'))
        self.assertEqual(seen[-1], 12.0)
        self.assertEqual(info['run_seconds'], 960)
        self.assertEqual(dt.acal_runs, ['ALL'])

    def test_acal_with_too_short_a_timeout_cannot_happen_but_a_timeout_is_not_retried(self):
        d, dt, ft, bench = sim()
        bench.fail_next = 'ACAL'
        dt.sent.clear()
        with self.assertRaises(InstrumentError) as cm:
            d.acal('DCV', inputs_disconnected=True)
        self.assertIn('NOT repeated', str(cm.exception))
        self.assertEqual([c for c in dt.sent if c.startswith('ACAL')], [])      # the simulated timeout fires before the command is handled: nothing was resent
        self.assertEqual(dt.acal_runs, [])


class TestSecrets(unittest.TestCase):
    def test_security_code_goes_on_the_wire_but_not_into_the_log(self):
        d, dt, ft, bench = sim()
        dt.security_code = PASSWORD
        d.acal('DCV', code=PASSWORD, inputs_disconnected=True)
        self.assertIn(f'ACAL DCV,{PASSWORD.upper()}', [c.upper() for c in dt.sent])
        text = '\n'.join(d.log.lines())
        self.assertNotIn(PASSWORD, text)
        self.assertIn('ACAL DCV,********', text)
        self.assertEqual(dt.acal_runs, ['DCV'])

    def test_wrong_code_is_an_error_after_the_autocal(self):
        d, dt, ft, bench = sim()
        dt.security_code = PASSWORD
        with self.assertRaises(InstrumentError):
            d.acal('DCV', code='WRONG', inputs_disconnected=True)
        self.assertNotIn('WRONG', '\n'.join(d.log.lines()))

    def test_acal_refuses_without_the_operators_confirmation(self):
        d, dt, ft, bench = sim()
        dt.sent.clear()
        with self.assertRaises(SafetyError):
            d.acal('ALL')
        with self.assertRaises(InstrumentError):
            d.acal('ALL2', inputs_disconnected=True)
        self.assertEqual(dt.sent, [])

    def test_acal_needs_the_bus_held(self):
        d, wire = make({'INBUF?': '1'})
        with self.assertRaises(InstrumentError):
            d.acal('DCV', inputs_disconnected=True)
        self.assertEqual(wire.writes(), [])

    def test_acal_checks_the_error_queue_and_reports_temperature(self):
        d, dt, ft, bench = sim()
        info = d.acal('OHMS', inputs_disconnected=True)
        self.assertEqual((info['type'], info['run_seconds'], info['settle_seconds'], info['warmup_seconds']), ('OHMS', 660, 1800, 7200))
        self.assertEqual(info['temperature_c'], dt.temperature)
        self.assertEqual(Agilent3458A.acal_info('DCV')['settle_seconds'], 900)


class TestResetAndIdentity(unittest.TestCase):
    def test_reset_sequence(self):
        bench, ft, dt = make_3458a_bench('5522A')
        d = Agilent3458A(dt, CommandLog(), label='3458A')
        d.connect()
        dt.sent.clear()
        calls = []
        real_clear = dt.clear
        dt.clear = lambda: (calls.append(len(dt.sent)), real_clear())[1]
        rep = d.reset_to_defaults()
        self.assertTrue(rep.ok, rep.text())
        self.assertEqual(calls, [0])                                        # the device clear came before the RESET (UG p. 333)
        self.assertEqual(dt.sent, ['RESET', 'CSB', 'STB?', 'ERRSTR?', 'END ALWAYS', 'END?', 'OFORMAT?', 'QFORMAT?', 'INBUF?', 'AZERO?'])
        self.assertEqual((dt.oformat, dt.end, dt.trig, dt.nplc), ('ASCII', 'ALWAYS', 'AUTO', 10.0))
        self.assertEqual((d.trigger, d.out_format), ('AUTO', 'ASCII'))

    def test_reset_clears_old_settings_and_errors(self):
        d, dt, ft, bench = sim()
        d.configure('DCI', 1e-3, nplc=100, trigger='SYN')
        dt.errors = [(103, 'SYNTAX ERROR')]
        rep = d.reset_to_defaults()
        self.assertTrue(rep.ok)
        self.assertEqual((dt.func, dt.nplc, dt.trig, dt.auto, dt.errors), ('DCV', 10.0, 'AUTO', 1, []))
        self.assertEqual((d.function, d.nplc), ('DCV', 10.0))

    def test_reset_reports_a_known_state_that_is_not_reached(self):
        d, wire = make({'STB?': '0', 'ERRSTR?': '0,"NO ERROR"', 'END?': '2', 'OFORMAT?': '1', 'QFORMAT?': '1', 'INBUF?': '1', 'AZERO?': '1'})
        rep = d.reset_to_defaults()
        self.assertFalse(rep.ok)
        self.assertIn('input buffer', rep.failed_step.detail)

    def test_reset_is_the_power_on_reset_not_preset(self):
        self.assertEqual(Agilent3458A.COMMANDS['reset'].template, 'RESET')
        d, dt, ft, bench = sim()
        self.assertNotIn('PRESET NORM', dt.sent)

    def test_identity_matches_both_texts(self):
        for text in ('Keysight 3458A', 'HP3458A', 'Agilent 3458A'):
            bench, ft, dt = make_3458a_bench()
            dt.idn_text = text
            d = Agilent3458A(dt, CommandLog(), label='3458A').connect()
            self.assertEqual(d.idn, text)

    def test_wrong_model_is_refused(self):
        bench, ft, dt = make_3458a_bench()
        dt.idn_text = 'Keysight 34410A'
        with self.assertRaises(InstrumentError):
            Agilent3458A(dt, CommandLog(), label='3458A').connect()

    def test_connect_sets_the_read_termination_and_learns_the_format(self):
        bench, ft, dt = make_3458a_bench()
        dt.oformat, dt.trig = 'DREAL', 'SYN'
        d = Agilent3458A(dt, CommandLog(), label='3458A').connect()
        self.assertEqual(dt.read_termination, '\n')
        self.assertEqual((d.out_format, d.trigger), ('DREAL', 'SYN'))
        self.assertIn('ID?', dt.sent)
        self.assertNotIn('RESET', dt.sent)

    def test_unsupported_output_format_at_connect(self):
        bench, ft, dt = make_3458a_bench()
        dt.oformat = 'SINT'
        with self.assertRaises(InstrumentError):
            Agilent3458A(dt, CommandLog(), label='3458A').connect()

    def test_local_sends_gtl(self):
        bench, ft, dt = make_3458a_bench()
        d = Agilent3458A(dt, CommandLog(), label='3458A')
        calls = []
        dt.go_local = lambda: calls.append('GTL')
        d.local()
        d.cleanup()
        self.assertEqual(calls, ['GTL', 'GTL'])

    def test_state_summary_is_read_only(self):
        d, dt, ft, bench = sim()
        d.configure('DCI', 1e-3, nplc=10)
        dt.sent.clear()
        summary = d.state_summary()
        self.assertTrue(all(c.endswith('?') for c in dt.sent), dt.sent)
        for forbidden in ('ERRSTR?', 'ERR?', 'AUXERR?', 'STB?'):
            self.assertNotIn(forbidden, dt.sent)
        self.assertEqual(summary['id'], 'Keysight 3458A')
        self.assertEqual((summary['output format'], summary['end'], summary['trigger'], summary['autorange']), ('1', '2', '5', '0'))
        self.assertTrue(summary['function,range'].startswith('6,'))
        self.assertEqual(summary['input buffer'], '0')

    def test_state_summary_reports_a_failing_query_instead_of_raising(self):
        d, wire = make({'ID?': 'Keysight 3458A'})
        summary = d.state_summary()
        self.assertEqual(summary['id'], 'Keysight 3458A')
        self.assertTrue(summary['nplc'].startswith('ERROR'))


class TestTransport(unittest.TestCase):
    def test_base_transport_defaults(self):
        t = Transport()
        t.set_read_termination('\n')                                        # a no-op where there is nothing to configure
        with self.assertRaises(NotImplementedError):
            t.read_raw(4)

    def test_visa_transport_reads_binary_by_count_and_sets_the_termination(self):
        class Res:
            read_termination = None

            def read_bytes(self, count, break_on_termchar=False):
                self.args = (count, break_on_termchar)
                return b'\x0a' * count                                       # a termination character inside binary data must not stop the read

        t = drivers.VisaTransport('GPIB0::22::INSTR')
        t._res = Res()
        t.set_read_termination('\n')
        self.assertEqual(t._res.read_termination, '\n')
        self.assertEqual(t.read_raw(8), b'\x0a' * 8)
        self.assertEqual(t._res.args, (8, False))
        t._res = None
        t.set_read_termination('\n')                                        # not open: nothing happens
        with self.assertRaises(TransportError):
            t.read_raw(4)


class TestSimulatedBench(unittest.TestCase):
    def test_applied_dc_current_over_the_high_current_ranges(self):
        d, dt, ft, bench = sim()
        for rng, value in ((1e-4, 1e-4), (1e-3, 1e-3), (1e-2, 1e-2), (1e-1, 0.1), (1.0, 1.0)):
            dt.apply('DCI', value)
            d.configure('DCI', rng, nplc=10)
            reading = d.read()
            self.assertAlmostEqual((reading - 2e-9) / value, 1.000002, places=6, msg=rng)
            self.assertEqual(dt.nominal['DCI'], rng)

    def test_the_input_limit_of_the_1_a_range_is_an_overload(self):
        d, dt, ft, bench = sim()
        d.configure('DCI', 1.0)
        dt.apply('DCI', 1.04)
        self.assertAlmostEqual(d.read(), 1.04, places=4)
        dt.apply('DCI', 1.06)                                               # full scale is 1.05 A (UG p. 273)
        with self.assertRaises(M.OverloadError):
            d.read()

    def test_calibrator_output_is_measured(self):
        d, dt, ft, bench = sim()
        ft.open()
        ft.write('OUT 1E-3A,0Hz')
        ft.write('OPER')
        d.configure('DCI', 1e-3)
        self.assertAlmostEqual(d.read(), 1e-3, places=8)
        ft.write('OUT 1E-3A,60Hz')                                          # an AC output is not a DC current
        self.assertAlmostEqual(d.read(), 2e-9, places=10)
        ft.write('STBY')
        self.assertAlmostEqual(d.read(), 2e-9, places=10)                   # standby: only the offset

    def test_wrong_function_for_the_source_reads_only_the_offset(self):
        d, dt, ft, bench = sim()
        ft.open()
        ft.write('OUT 5V,0Hz')
        ft.write('OPER')
        d.configure('DCI', 1e-3)
        self.assertAlmostEqual(d.read(), 2e-9, places=10)
        d.configure('DCV', 10.0)
        self.assertAlmostEqual(d.read(), 5.0, places=4)

    def test_all_formats_agree(self):
        d, dt, ft, bench = sim()
        dt.apply('DCV', 1.234567)
        d.configure('DCV', 10.0)
        ascii_value = d.read()
        d.set_output_format('DREAL')
        self.assertAlmostEqual(d.read(), ascii_value, places=7)                  # ASCII carries 9 digits, DREAL all of them
        d.set_output_format('SREAL')
        self.assertAlmostEqual(d.read(), ascii_value, places=5)
        d.set_output_format('ASCII')
        self.assertEqual(d.read(), ascii_value)
        text = '\n'.join(d.log.lines())
        self.assertIn('<DREAL 8 bytes ', text)
        self.assertIn('<SREAL 4 bytes ', text)

    def test_binary_overload(self):
        d, dt, ft, bench = sim()
        d.configure('DCV', 1.0)
        dt.apply('DCV', 5.0)
        for fmt in ('SREAL', 'DREAL'):
            d.set_output_format(fmt)
            with self.assertRaises(M.OverloadError):
                d.read()

    def test_read_n_and_single_trigger(self):
        d, dt, ft, bench = sim()
        dt.apply('DCV', 1.0)
        d.configure('DCV', 10.0, trigger='SGL')
        dt.sent.clear()
        values = d.read_n(3)
        self.assertEqual(len(values), 3)
        self.assertEqual(dt.sent, ['TRIG SGL'] * 3)
        d.set_trigger('SYN')
        dt.sent.clear()
        self.assertEqual(len(d.read_n(2)), 2)
        self.assertEqual(dt.sent, [])                                       # TRIG SYN: the read request is the trigger, nothing is sent
        with self.assertRaises(InstrumentError):
            d.read_n(0)

    def test_null_and_offset(self):
        d, dt, ft, bench = sim()
        d.configure('DCV', 10.0)
        dt.apply('DCV', 0.001)
        register = d.null()
        self.assertAlmostEqual(register, 0.001, delta=1e-6)                 # the gain (2 ppm) and the 0.4 uV offset of the simulated meter
        self.assertAlmostEqual(d.read(), 0.0, places=10)                    # input unchanged: nulled
        dt.apply('DCV', 0.0015)
        self.assertAlmostEqual(d.read(), 0.0005, places=7)
        self.assertAlmostEqual(d.offset(), register, places=12)
        d.null_off()
        self.assertAlmostEqual(d.read(), 0.0015, delta=1e-6)
        self.assertEqual(d.null(offset=1e-6), 1e-6)
        d.null_off()

    def test_housekeeping_queries(self):
        d, dt, ft, bench = sim()
        self.assertEqual(d.temperature(), 38.9)
        self.assertEqual(d.revision(), ('9', '2'))
        self.assertEqual(d.terminals(), 'FRONT')
        dt.terminals = 'REAR'
        self.assertEqual(d.terminals(), 'REAR')

    def test_ohms_and_ac_functions_configure(self):
        d, dt, ft, bench = sim()
        dt.apply('OHM', 1000.0)
        d.configure('OHM', 1000.0, nplc=10)
        self.assertAlmostEqual(d.read(), 1000.0, delta=0.01)
        dt.apply('ACV', 1.0)
        d.configure('ACV', 1.0, nplc=1)
        self.assertAlmostEqual(d.read(), 1.0, places=4)

    def test_everything_sent_in_a_run_is_in_the_registry(self):
        """Every line the driver put on the simulated wire is the rendering of a registered command (the simulator raises on anything it does not know)."""
        d, dt, ft, bench = sim()
        dt.apply('DCI', 1e-3)
        d.configure('DCI', 1e-3, nplc=100, ndig=8, trigger='SYN')
        d.read_n(2)
        d.set_output_format('DREAL')
        d.read()
        d.set_output_format('ASCII')
        d.null()
        d.null_off()
        d.state_summary()
        d.check_errors()
        d.acal('DCV', inputs_disconnected=True)
        heads = {c.split()[0].split(',')[0].rstrip('?') for c in dt.sent}
        registered = {cmd.template.split()[0].rstrip('?') for cmd in cmdreg.merge_commands(Agilent3458A).values()}
        self.assertTrue(heads <= registered, heads - registered)


if __name__ == '__main__':
    unittest.main()
