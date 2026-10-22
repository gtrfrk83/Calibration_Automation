"""drivers/base.py: commands typed for ONE test point and extra command lines (set_point / run_extras).  Simulated 5560A and a scripted device;
no tkinter, no hardware.  Unmodified behaviour is covered by test_driver_commands_base.py and the golden transcripts."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cmdreg import Cmd, Placeholder  # noqa: E402
from drivers import Fluke5560A, Instrument, InstrumentError  # noqa: E402
from drivers.simulated import make_bench  # noqa: E402
from drivers.transport import CommandLog, Transport  # noqa: E402


def cal():
    _bench, ft, _st = make_bench()
    inst = Fluke5560A(ft, CommandLog(), label='5560A')
    inst.open()
    del inst.log.entries[:]
    return inst


def texts(inst, d='>>'):
    return [t for _ts, _i, direction, t in inst.log.entries if direction == d]


class Scripted(Transport):
    """Records writes; answers each query from `replies` (text -> reply)."""
    name = 'scripted'

    def __init__(self, replies=None):
        self.sent, self.replies = [], dict(replies or {})

    def open(self): pass
    def close(self): pass
    def set_timeout(self, s): pass

    def write(self, text):
        self.sent.append(('w', text))

    def query(self, text):
        self.sent.append(('q', text))
        return self.replies.get(text, '0')


class Dev(Instrument):
    MODEL = 'Dev'
    COMMANDS = {
        'a': Cmd('A {x:g}', 'Set A', placeholders={'x': Placeholder('float', 'g', 1.0)}, kind='set', readback='a.q', verified=True),
        'a.q': Cmd('A?', 'Read A', kind='query', verified=True),
    }


def dev(replies=None):
    t = Scripted(replies)
    return Dev(t, CommandLog(), label='Dev'), t


class PointSelection(unittest.TestCase):
    def test_nothing_changes_without_overrides(self):
        d, t = dev()
        d.use_commands({}, points={}, extras={})
        d.set_point('k1')
        d.send('a', x=2)
        d.run_extras('before')
        d.run_extras('after')
        d.set_point(None)
        self.assertEqual(t.sent, [('w', 'A 2')])
        self.assertEqual(d.point_overrides_active('k1'), [])

    def test_the_point_override_applies_to_that_point_only(self):
        d, t = dev()
        d.use_commands({}, points={'k1': {'a': 'A2 {x:g}'}}, point_uids={'k1': {'a': 'u1'}})
        d.send('a', x=1)                                     # no point selected
        d.set_point('k1')
        d.send('a', x=2)
        d.set_point('k2')
        d.send('a', x=3)
        d.set_point(None)
        d.send('a', x=4)
        self.assertEqual([x for _k, x in t.sent], ['A 1', 'A2 2', 'A 3', 'A 4'])
        self.assertEqual(texts(d)[1], 'A2 2  [OVERRIDE ov-u1]')
        self.assertEqual(d.point_overrides_active('k1'), ['ov-u1'])

    def test_the_point_override_wins_over_the_driver_wide_one(self):
        d, t = dev()
        d.use_commands({'a': 'AW {x:g}'}, uids={'a': 'wide'}, points={'k1': {'a': 'AP {x:g}'}}, point_uids={'k1': {'a': 'pt'}})
        d.set_point('k1')
        d.send('a', x=1)
        d.set_point('k9')
        d.send('a', x=1)
        self.assertEqual([x for _k, x in t.sent], ['AP 1', 'AW 1'])

    def test_invalid_point_overrides_are_rejected_at_load_and_never_sent(self):
        c = cal()
        rej = c.use_commands({}, points={'k1': {'out.volts': 'OUT {volts:.3f}V;*RST', 'oper.on': 'OPER', 'err.query': 'ERR?', 'nope': 'X'}},
                             point_uids={'k1': {'out.volts': 'u1'}})
        self.assertEqual({k for k, _u, _p in rej}, {'out.volts', 'oper.on', 'err.query', 'nope'})
        c.set_point('k1')
        c.set_output_volts(1.0)
        self.assertEqual(texts(c), ['OUT 1V'])

    def test_a_point_override_failing_at_send_time_falls_back_to_factory(self):
        c = cal()
        c.use_commands({}, points={'k1': {'out.volts': 'OUT {volts:.6f}V'}}, point_uids={'k1': {'out.volts': 'u9'}})
        c._cmd_pt['k1']['out.volts'] = ('OUT {volts:.6f}V;*RST', 'u9')
        c.set_point('k1')
        c.set_output_volts(1.0)
        self.assertEqual(texts(c), ['OUT 1V'])
        self.assertIn('OVERRIDE REJECTED ov-u9', texts(c, '!!')[0])

    def test_unknown_point_override_keys_are_never_a_crash(self):
        d, _t = dev()
        for junk in (None, {}, {'k': None}, {'k': {'a': None}}, {'k': {'a': 5}}):
            d.use_commands({}, points=junk)
        d.set_point('k')
        d.send('a', x=1)


class ExtraLines(unittest.TestCase):
    X = {'phase': 'before', 'n': 1, 'template': 'B 5', 'readback': 'B?', 'expect': '5', 'uid': 'e1'}

    def test_a_write_is_sent_once_read_back_and_compared(self):
        d, t = dev({'B?': '5'})
        d.use_commands({}, extras={'k1': [self.X]})
        d.set_point('k1')
        d.run_extras('before')
        d.run_extras('after')
        self.assertEqual(t.sent, [('w', 'B 5'), ('q', 'B?')])
        self.assertEqual(texts(d), ['B 5  [EXTRA ov-e1 UNVERIFIED]', 'B?  [EXTRA ov-e1 UNVERIFIED]'])

    def test_a_mismatch_stops_the_point_and_nothing_is_retried(self):
        d, t = dev({'B?': '6'})
        d.use_commands({}, extras={'k1': [self.X]})
        d.set_point('k1')
        with self.assertRaises(InstrumentError) as cm:
            d.run_extras('before')
        self.assertIn('was not confirmed', str(cm.exception))
        self.assertEqual(t.sent, [('w', 'B 5'), ('q', 'B?')])

    def test_numeric_replies_compare_as_numbers_and_text_ignores_case_and_quotes(self):
        d, t = dev({'B?': '+5.000E+0'})
        d.use_commands({}, extras={'k1': [self.X, dict(self.X, n=2, template='M SIN', readback='M?', expect='SIN')]})
        t.replies['M?'] = '"sin"'
        d.set_point('k1')
        d.run_extras('before')
        self.assertEqual(len(t.sent), 4)

    def test_a_query_is_just_asked(self):
        d, t = dev()
        d.use_commands({}, extras={'k1': [{'phase': 'after', 'n': 1, 'template': 'STAT?', 'uid': 'q1'}]})
        d.set_point('k1')
        d.run_extras('before')
        self.assertEqual(t.sent, [])
        d.run_extras('after')
        self.assertEqual(t.sent, [('q', 'STAT?')])

    def test_order_is_the_order_given(self):
        d, t = dev({'B?': '5', 'C?': '6'})
        d.use_commands({}, extras={'k1': [self.X, dict(self.X, n=2, template='C 6', readback='C?', expect='6')]})
        d.set_point('k1')
        d.run_extras('before')
        self.assertEqual([x for _k, x in t.sent], ['B 5', 'B?', 'C 6', 'C?'])

    def test_a_forbidden_line_is_rejected_at_send_time_and_not_sent(self):
        d, t = dev()
        d.use_commands({}, extras={'k1': [dict(self.X, template='*RST')]})
        d.set_point('k1')
        d.run_extras('before')
        self.assertEqual(t.sent, [])
        self.assertTrue(texts(d, '!!'))

    def test_extras_of_another_point_are_not_sent(self):
        d, t = dev({'B?': '5'})
        d.use_commands({}, extras={'k1': [self.X]})
        d.set_point('k2')
        d.run_extras('before')
        d.set_point(None)
        d.run_extras('before')
        self.assertEqual(t.sent, [])


if __name__ == '__main__':
    unittest.main()
