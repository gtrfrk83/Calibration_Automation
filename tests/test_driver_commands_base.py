"""Instrument.send / ask / use_commands / describe_commands on the simulated 5560A (no tkinter, no hardware)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
from cmdreg import Cmd, Placeholder  # noqa: E402
from drivers import Fluke5522A, Fluke5560A, Instrument, InstrumentError  # noqa: E402
from drivers.simulated import SimFlukeTransport, make_bench  # noqa: E402
from drivers.transport import CommandLog, Transport, TransportError  # noqa: E402

PASSWORD = 'S3cretPw!'


def cal():
    _bench, ft, _st = make_bench()
    inst = Fluke5560A(ft, CommandLog(), label='5560A')
    inst.open()
    del inst.log.entries[:]                    # drop the *IDN? exchange
    return inst


def texts(inst, d='>>'):
    return [t for _ts, _i, direction, t in inst.log.entries if direction == d]


class FailingTransport(Transport):
    name = 'failing'

    def __init__(self):
        self.writes, self.queries = [], []

    def open(self): pass
    def close(self): pass
    def set_timeout(self, s): pass

    def write(self, text):
        self.writes.append(text)
        raise TransportError('simulated timeout')

    def query(self, text):
        self.queries.append(text)
        raise TransportError('simulated timeout')


class Secretive(Instrument):
    MODEL = 'Secretive'
    COMMANDS = {
        'sec.off': Cmd('SEC OFF,{pw}', 'Unlock', placeholders={'pw': Placeholder('secret')}, kind='set', risk='normal'),
        'plain': Cmd('PLAIN {x:g}', 'Plain', placeholders={'x': Placeholder('float', 'g', 1.0)}, kind='set'),
    }


class Wire(Transport):
    def __init__(self): self.sent = []
    def open(self): pass
    def close(self): pass
    def set_timeout(self, s): pass
    def write(self, text): self.sent.append(text)
    def query(self, text): self.sent.append(text); return '1'


class NoOverride(unittest.TestCase):
    def test_wire_and_log_identical_to_the_old_fstrings(self):
        c = cal()
        c.set_output_volts(1.23456789012, 1000.0)
        c.set_dc_volts(-0.0123456789)
        want = [f'OUT {1.23456789012:.9g}V,{1000.0:.9g}Hz', f'OUT {-0.0123456789:.9f}V', 'OUT?']
        self.assertEqual(texts(c)[-3:], want)
        self.assertEqual(c.command_overrides_active(), [])
        self.assertFalse(any('OVERRIDE' in t for _a, _b, _c, t in c.log.entries))


class Override(unittest.TestCase):
    def test_override_changes_the_wire_and_marks_only_the_log(self):
        c = cal()
        sent = []
        orig = c.t.write
        c.t.write = lambda text: (sent.append(text), orig(text))[1]
        rej = c.use_commands({'out.volts': 'OUT {volts:.6f}V'}, uids={'out.volts': 'ab12cd34'})
        self.assertEqual(rej, [])
        c.set_output_volts(1.5)
        self.assertEqual(sent, ['OUT 1.500000V'])                          # the wire has no marker
        self.assertEqual(texts(c), ['OUT 1.500000V  [OVERRIDE ov-ab12cd34]'])
        self.assertEqual(c.command_overrides_active(), ['ov-ab12cd34'])
        c.set_output_volts(1.5, 1000.0)                                    # the hz variant is a different key: unchanged
        self.assertEqual(texts(c)[-1], 'OUT 1.5V,1000Hz')

    def test_override_forms_and_uid_prefix(self):
        c = cal()
        c.use_commands({'out.volts': ('OUT {volts:.3f}V', 'ov-x1'), 'out.ohms': {'template': 'OUT {ohms:.3f}OHM', 'uid': 'y2'}})
        c.set_output_volts(2.0)
        c.set_output_ohms(10.0)
        self.assertEqual(texts(c), ['OUT 2.000V  [OVERRIDE ov-x1]', 'OUT 10.000OHM  [OVERRIDE ov-y2]'])
        self.assertEqual(set(c.command_overrides_active()), {'ov-x1', 'ov-y2'})

    def test_invalid_override_is_dropped_at_load_and_recorded(self):
        c = cal()
        rej = c.use_commands({'out.volts': 'OUT {nope}V', 'out.ohms': '*RST'}, uids={'out.volts': 'u1', 'out.ohms': 'u2'})
        self.assertEqual({k for k, _u, _p in rej}, {'out.volts', 'out.ohms'})
        self.assertEqual(c.command_overrides_active(), [])
        self.assertTrue(any('OVERRIDE REJECTED' in t for t in texts(c, '!!')))
        c.set_output_volts(1.0)
        self.assertEqual(texts(c), ['OUT 1V'])                              # factory text, no marker

    def test_override_failing_at_send_time_falls_back_to_factory(self):
        c = cal()
        c.use_commands({'out.volts': 'OUT {volts:.6f}V'}, uids={'out.volts': 'u9'})
        c._cmd_ov['out.volts'] = ('OUT {volts:.6f}V;*RST', 'u9')           # corrupted after load
        c.set_output_volts(1.0)
        self.assertEqual(texts(c), ['OUT 1V'])
        rejected = texts(c, '!!')
        self.assertEqual(len(rejected), 1)
        self.assertIn('OVERRIDE REJECTED ov-u9 out.volts', rejected[0])
        self.assertEqual(c.command_overrides_active(), [])
        c.set_output_volts(2.0)                                            # dropped for good, not re-reported
        self.assertEqual(len(texts(c, '!!')), 1)

    def test_locked_output_and_secret_keys_cannot_be_overridden(self):
        c = cal()
        bad = {'oper.on': 'OPER', 'oper.stby': 'STBY', 'oper.query': 'OPER?', 'err.query': 'ERR?', 'status.clear': '*CLS',
               'trg.measr': '*TRG', 'nope.key': 'X'}
        rej = c.use_commands(bad)
        self.assertEqual({k for k, _u, _p in rej}, set(bad))
        self.assertEqual(c.command_overrides_active(), [])
        s = Secretive(Wire(), CommandLog())
        rej = s.use_commands({'sec.off': 'SEC ON,{pw}'}, uids={'sec.off': 's1'})
        self.assertEqual([k for k, _u, _p in rej], ['sec.off'])
        self.assertIn('secret', {p.code for p in cmdreg.validate('SEC ON,{pw}', Secretive.COMMANDS['sec.off'])})

    def test_use_commands_replaces_and_never_raises(self):
        c = cal()
        c.use_commands({'out.volts': 'OUT {volts:.3f}V'}, uids={'out.volts': 'a'})
        c.use_commands({})
        self.assertEqual(c.command_overrides_active(), [])
        for junk in (None, {'out.volts': None}, {'out.volts': 5}, {'out.volts': ('x',)}, {'out.volts': {}}):
            c.use_commands(junk)
        c.set_output_volts(1.0)
        self.assertEqual(texts(c)[-1], 'OUT 1V')

    def test_inherited_by_the_5522a(self):
        bench, _ft, _s = make_bench()
        c = Fluke5522A(SimFlukeTransport(bench, '5522A'), CommandLog())
        c.open()
        del c.log.entries[:]
        c.use_commands({'out.ohms': 'OUT {ohms:.2f}OHM'}, uids={'out.ohms': 'k'})
        c.set_output_ohms(100.0)
        self.assertEqual(texts(c)[-1], 'OUT 100.00OHM  [OVERRIDE ov-k]')


class NoRetry(unittest.TestCase):
    def test_send_and_the_converted_setters_never_retry(self):
        t = FailingTransport()
        c = Fluke5560A(t, CommandLog())
        with self.assertRaises(TransportError):
            c.send('out.volts', volts=1.0)
        self.assertEqual(t.writes, ['OUT 1V'])
        with self.assertRaises(TransportError):
            c.set_dc_volts(1.0)
        self.assertEqual(len(t.writes), 2)
        with self.assertRaises(TransportError):
            c.use_commands({'out.ohms': 'OUT {ohms:.2f}OHM'}) or c.set_output_ohms(5.0)
        self.assertEqual(len(t.writes), 3)

    def test_ask_does_not_retry_but_query_retry_does_for_queries(self):
        t = FailingTransport()
        c = Fluke5560A(t, CommandLog())
        with self.assertRaises(TransportError):
            c.ask('out.query')
        self.assertEqual(len(t.queries), 1)
        import drivers.base as base
        saved = base.time.sleep
        base.time.sleep = lambda s: None
        try:
            with self.assertRaises(InstrumentError):
                c.query_retry('out.query', attempts=3)
        finally:
            base.time.sleep = saved
        self.assertEqual(len(t.queries), 4)

    def test_query_retry_rejects_non_query_keys(self):
        t = FailingTransport()
        c = Fluke5560A(t, CommandLog())
        for key in ('out.volts', 'oper.on', 'scope.dcv', 'status.clear'):
            with self.assertRaises(InstrumentError):
                c.query_retry(key)
        self.assertEqual((t.writes, t.queries), ([], []))
        with self.assertRaises(InstrumentError):
            c.ask('out.volts', volts=1.0)
        with self.assertRaises(InstrumentError):
            c.send('out.query')
        with self.assertRaises(InstrumentError):
            c.send('no.such.key')

    def test_query_retry_with_a_key_uses_the_override(self):
        c = cal()
        c.use_commands({'out.query': 'OUT?'}, uids={})                      # identical text is accepted
        self.assertTrue(c.query_retry('out.query').startswith('0.000000000'))


class Secrets(unittest.TestCase):
    def test_secret_value_goes_on_the_wire_but_never_in_the_log(self):
        w = Wire()
        s = Secretive(w, CommandLog())
        s.send('sec.off', pw=PASSWORD)
        self.assertEqual(w.sent, ['SEC OFF,' + PASSWORD])
        self.assertEqual(texts(s), ['SEC OFF,********'])
        self.assertNotIn(PASSWORD, '\n'.join(s.log.lines()))
        self.assertNotIn(PASSWORD, repr(s.describe_commands()))

    def test_bad_secret_value_error_does_not_echo_it(self):
        s = Secretive(Wire(), CommandLog())
        with self.assertRaises(ValueError) as cm:
            s.send('sec.off', pw='café-' + PASSWORD)
        self.assertNotIn(PASSWORD, str(cm.exception))

    def test_5560a_registry_has_no_secret(self):
        self.assertFalse(any(c.secret for c in cmdreg.merge_commands(Fluke5560A).values()))


class Describe(unittest.TestCase):
    def setUp(self):
        self.rows = {r['key']: r for r in cal().describe_commands()}

    def test_registry_is_sane_and_covers_every_command(self):
        reg = cmdreg.merge_commands(Fluke5560A)
        self.assertEqual(cmdreg.lint_registry(reg), [])
        self.assertEqual(set(self.rows), set(reg))
        self.assertEqual(cmdreg.validate_bundle({}, reg), [])

    def test_fields(self):
        r = self.rows['out.volts']
        self.assertEqual((r['factory'], r['current'], r['kind'], r['risk'], r['verified'], r['overridden'], r['editable']),
                         ('OUT {volts:.9g}V', 'OUT {volts:.9g}V', 'set', 'normal', True, False, True))
        self.assertEqual(self.rows['out.dc']['readback'], 'out.query')
        self.assertEqual(self.rows['out.dc']['factory'], 'OUT {volts:.9f}V')
        self.assertIn('5560A', self.rows['out.dc']['ref'])
        for key in ('name', 'description', 'ref', 'placeholders', 'owner'):
            self.assertIn(key, r)

    def test_output_and_locked_are_not_editable(self):
        for key in ('oper.stby', 'oper.on', 'oper.query'):
            self.assertEqual((self.rows[key]['risk'], self.rows[key]['editable']), ('output', False), key)
        for key in ('err.query', 'status.clear', 'trg.measr'):
            self.assertEqual((self.rows[key]['risk'], self.rows[key]['editable']), ('locked', False), key)

    def test_unverified_commands_are_flagged(self):
        for key in ('scope.square', 'out.square', 'scope.marker', 'out.marker', 'tc.type', 'out.temp', 'out.cap.nf', 'out.cap.uf', 'out.cap.f'):
            self.assertFalse(self.rows[key]['verified'], key)
        for key in ('out.dc', 'scope.dcv', 'scope.measr', 'out.volts', 'oper.on'):
            self.assertTrue(self.rows[key]['verified'], key)

    def test_current_follows_an_override(self):
        c = cal()
        c.use_commands({'out.ohms': 'OUT {ohms:.4f}OHM'}, uids={'out.ohms': 'q'})
        row = {r['key']: r for r in c.describe_commands()}['out.ohms']
        self.assertEqual((row['factory'], row['current'], row['overridden'], row['uid']), ('OUT {ohms:.9g}OHM', 'OUT {ohms:.4f}OHM', True, 'ov-q'))

    def test_counts(self):
        reg = cmdreg.merge_commands(Fluke5560A)
        by = {}
        for c in reg.values():
            by[(c.risk, c.verified)] = by.get((c.risk, c.verified), 0) + 1
        self.assertEqual(len(reg), 35)   # main's 33 (incl. the DC out.volts.dc / out.amps.dc keys) + reset, + opc.query (Stage 7)
        self.assertEqual(sum(1 for c in reg.values() if not c.verified), 12)
        self.assertEqual(sum(1 for c in reg.values() if c.risk == 'output'), 3)
        self.assertEqual(sum(1 for c in reg.values() if c.risk == 'locked'), 5)


if __name__ == '__main__':
    unittest.main()
