"""Command registries of the generator, counter, 5790B and reference-instrument drivers (no tkinter, no hardware):
an override changes the wire text and marks only the log; locked / output keys refuse overrides; describe_commands() lists the registry."""
import re
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
from drivers.fluke_5790b import Fluke5790B  # noqa: E402
from drivers.keysight_332xx import Keysight33220A, Keysight332xx  # noqa: E402
from drivers.keysight_5313x import Keysight53131A, Keysight5313x  # noqa: E402
from drivers.reference_instruments import AgilentAFG, Fluke96270A, ReferenceMeter  # noqa: E402
from drivers.transport import CommandLog, Transport  # noqa: E402

DRIVERS = [Keysight332xx, Keysight5313x, Fluke5790B, Fluke96270A, AgilentAFG, ReferenceMeter]

# (risk -> verified -> count) per driver. Nothing in these drivers has been run on hardware (NOTES.md), so nothing is verified=True.
EXPECTED = {
    # Stage 7 added the locked reset + opc.query to each (verified=True where a manual page backs it)
    'Keysight332xx': {('normal', False): 16, ('output', False): 3, ('locked', False): 5},
    'Keysight5313x': {('normal', False): 22, ('locked', False): 3, ('locked', True): 2},
    'Fluke5790B': {('normal', False): 11, ('locked', False): 2, ('locked', True): 2},
    'Fluke96270A': {('normal', False): 11, ('output', False): 3, ('locked', False): 3, ('locked', True): 1},
    'AgilentAFG': {('normal', False): 4, ('output', False): 5, ('locked', False): 4},
    'ReferenceMeter': {('normal', False): 6, ('locked', False): 3},
}


class Scripted(Transport):
    """Answers a query with the first matching rule's reply (default '0'); records every write and query."""
    name = 'scripted'

    def __init__(self, rules=()):
        self.rules = [(re.compile(p), list(r) if isinstance(r, list) else r) for p, r in rules]
        self.writes, self.queries = [], []

    def open(self): pass
    def close(self): pass
    def set_timeout(self, s): pass

    def write(self, text):
        self.writes.append(text)

    def query(self, text):
        self.queries.append(text)
        for rx, reply in self.rules:
            if rx.search(text):
                if isinstance(reply, list):                       # successive replies; the last one repeats
                    return reply.pop(0) if len(reply) > 1 else reply[0]
                return reply
        return '0'


def make(cls, rules=()):
    t = Scripted(rules)
    inst = cls(t, CommandLog(), label=cls.__name__)
    return inst, t


def logged(inst, d='>>'):
    return [t for _ts, _i, direction, t in inst.log.entries if direction == d]


class Registry(unittest.TestCase):
    def test_registries_are_sane(self):
        for cls in DRIVERS:
            reg = cmdreg.merge_commands(cls)
            self.assertTrue(reg, cls.__name__)
            self.assertEqual(cmdreg.lint_registry(reg), [], cls.__name__)

    def test_counts_per_risk_and_verified(self):
        for cls in DRIVERS:
            inst, _t = make(cls)
            got = Counter((d['risk'], d['verified']) for d in inst.describe_commands())
            self.assertEqual(dict(got), EXPECTED[cls.__name__], cls.__name__)

    def test_describe_commands_lists_the_registry(self):
        for cls in DRIVERS:
            inst, _t = make(cls)
            rows = inst.describe_commands()
            reg = cmdreg.merge_commands(cls)
            self.assertEqual([r['key'] for r in rows], list(reg))
            for r in rows:
                self.assertEqual(r['factory'], reg[r['key']].template)
                self.assertEqual(r['overridable'], r['risk'] == 'normal')
                self.assertFalse(r['overridden'])

    def test_output_state_and_plumbing_keys_are_not_normal(self):
        for cls in DRIVERS:
            for key, cmd in cmdreg.merge_commands(cls).items():
                if re.search(r'^(OUTP(UT)?\b(?!:LOAD)|APPLy)', cmd.template, re.I):
                    self.assertEqual(cmd.risk, 'output', f'{cls.__name__}.{key}')
                if cmd.template in ('*CLS', '*TST?', 'ERR?', 'SYST:ERR?', ':SYST:ERR?', 'SYSTem:ERRor?'):
                    self.assertEqual(cmd.risk, 'locked', f'{cls.__name__}.{key}')

    def test_locked_and_output_keys_refuse_overrides(self):
        for cls in DRIVERS:
            inst, t = make(cls)
            reg = cmdreg.merge_commands(cls)
            fixed = {k: c.template for k, c in reg.items() if c.risk != 'normal'}
            self.assertTrue(fixed, cls.__name__)
            rejected = inst.use_commands(fixed)                       # even the unchanged factory text is refused
            self.assertEqual({k for k, _u, _p in rejected}, set(fixed), cls.__name__)
            self.assertEqual(inst.command_overrides_active(), [])
            self.assertTrue(all('not editable' in p for _k, _u, probs in rejected for p in probs))

    def test_output_enable_cannot_be_smuggled_into_a_normal_key(self):
        inst, _t = make(Keysight33220A)
        rej = inst.use_commands({'unit.vrms': 'OUTP ON', 'freq.set': 'FREQ {frequency:.3f};OUTP ON'})
        self.assertEqual({k for k, _u, _p in rej}, {'unit.vrms', 'freq.set'})
        self.assertEqual(inst.command_overrides_active(), [])
        inst, _t = make(Fluke96270A)
        rej = inst.use_commands({'freq.level': 'FREQ {f:.3f};:POW {p:.2f};OUTP ON'})
        self.assertEqual([k for k, _u, _p in rej], ['freq.level'])

    def test_afg_apply_is_not_overridable(self):
        inst, _t = make(AgilentAFG)
        self.assertEqual(cmdreg.merge_commands(AgilentAFG)['apply.sin'].risk, 'output')
        rej = inst.use_commands({'apply.sin': 'APPLy:SINusoid {frequency_hz:.3f},{vpp:.3f},0'})
        self.assertEqual([k for k, _u, _p in rej], ['apply.sin'])


class Generator332xx(unittest.TestCase):
    RULES = [(r'^FREQ\?', '1000'), (r'^OUTP\?', '0'), (r'^SYST:ERR\?', '+0,"No error"'), (r'^VOLT\?', '1'),
             (r'^VOLT:OFFS\?', '0'), (r'^FUNC\?', 'SIN'), (r'^VOLT:UNIT\?', ['VRMS', 'VPP']), (r'^VOLT:RANG:AUTO\?', '1'), (r'^OUTP:LOAD\?', '50')]

    def test_no_override_wire_and_log_are_the_old_text(self):
        g, t = make(Keysight33220A, self.RULES)
        g.setup('SIN', 1000.0, 1.0, 'VPP', '50')
        self.assertEqual(t.writes, ['OUTP OFF', 'VOLT:UNIT VRMS', 'OUTP:LOAD 50', 'FUNC SIN', 'VOLT:OFFS 0', 'VOLT:RANG:AUTO ON',
                                    'VOLT:UNIT VPP', 'FREQ 1000', 'VOLT 1'])
        self.assertFalse(any('OVERRIDE' in x for x in logged(g)))
        self.assertEqual(g.command_overrides_active(), [])

    def test_override_changes_wire_and_marks_only_the_log(self):
        g, t = make(Keysight33220A, self.RULES)
        self.assertEqual(g.use_commands({'freq.set': 'FREQ {frequency:.3f}'}, uids={'freq.set': 'f1'}), [])
        g.setup('SIN', 1000.0, 1.0, 'VPP', '50')
        self.assertIn('FREQ 1000.000', t.writes)
        self.assertFalse(any('OVERRIDE' in w for w in t.writes))              # the wire never carries the marker
        self.assertIn('FREQ 1000.000  [OVERRIDE ov-f1]', logged(g))
        self.assertEqual(len([x for x in logged(g) if 'OVERRIDE' in x]), 1)   # only that command is marked
        self.assertEqual(g.command_overrides_active(), ['ov-f1'])

    def test_output_goes_through_locked_keys(self):
        g, t = make(Keysight33220A, [(r'^OUTP\?', '1')])
        g.output(True)
        self.assertEqual(t.writes, ['OUTP ON'])
        g.cleanup()
        self.assertEqual(t.writes, ['OUTP ON', 'OUTP OFF'])
        self.assertEqual(t.queries, ['OUTP?', 'OUTP?'])


class Counter5313x(unittest.TestCase):
    def test_override_on_the_gate_time(self):
        c, t = make(Keysight53131A, [(r'^:FUNC\?', 'FREQ'), (r'^:INP1:IMP\?', '50'), (r'^:INP1:COUP\?', 'AC'),
                                      (r'ARM:STAR:SOUR\?', 'IMM'), (r'ARM:STOP:SOUR\?', 'TIM'), (r'STOP:TIM\?', '0.5')])
        c.use_commands({'gate.set': ':FREQ:ARM:STOP:TIM {gate_s:.3f}'}, uids={'gate.set': 'g7'})
        c.configure_frequency(1, 0.5)
        self.assertIn(':FREQ:ARM:STOP:TIM 0.500', t.writes)
        self.assertIn(':FREQ:ARM:STOP:TIM 0.500  [OVERRIDE ov-g7]', logged(c))
        self.assertIn(':FUNC "FREQ 1"', t.writes)
        self.assertIn(':INP1:IMP 50', t.writes)


class Standard5790B(unittest.TestCase):
    RULES = [(r'^INPUT\?', 'INPUT2'), (r'^ERR\?', '0,"No Error"')]

    def test_override_input_select(self):
        s, t = make(Fluke5790B, self.RULES)
        s.use_commands({'input.set': 'INPUT {name}'}, uids={'input.set': 'a'})          # unchanged text: not an override
        s.select_input('input2')
        self.assertEqual(t.writes, ['INPUT INPUT2'])
        self.assertEqual(s.command_overrides_active(), [])
        s.use_commands({'input.set': 'INP {name}'}, uids={'input.set': 'b'})
        s.select_input('INPUT2')
        self.assertEqual(t.writes[-1], 'INP INPUT2')
        self.assertEqual(logged(s)[-3], 'INP INPUT2  [OVERRIDE ov-b]')

    def test_split_conditional_keys(self):
        s, t = make(Fluke5790B, [(r'^EXTRIG\?', '1'), (r'^ERR\?', '0,"No Error"')])
        s.set_external_trigger(True)
        self.assertEqual(t.writes, ['EXTRIG ON'])
        s2, t2 = make(Fluke5790B, [(r'^EXTRIG\?', '0'), (r'^ERR\?', '0,"No Error"')])
        s2.set_external_trigger(False)
        s2.cleanup()
        self.assertEqual(t2.writes, ['EXTRIG OFF', 'EXTRIG OFF'])

    def test_range_uses_absolute_value(self):
        s, t = make(Fluke5790B, [(r'^RANGE\?', '2.2,0.22,1e-6,0'), (r'^ERR\?', '0,"No Error"')])
        s.set_range_for(-1.0)
        self.assertEqual(t.writes, ['RANGE 1'])


class Reference(unittest.TestCase):
    def test_rf_override_and_output_keys(self):
        r, t = make(Fluke96270A, [(r'^FREQ\?', '1000000000'), (r'^POW\?', '-10'), (r'^SYST:ERR\?', '0')])
        r.use_commands({'freq.level': 'FREQ {f:.6f};:POW {p:.2f}'}, uids={'freq.level': 'r9'})
        r.set_rf(1e9, -10.0)
        self.assertEqual(t.writes, ['FREQ 1000000000.000000;:POW -10.00'])
        self.assertEqual(logged(r)[0], 'FREQ 1000000000.000000;:POW -10.00  [OVERRIDE ov-r9]')
        r2, t2 = make(Fluke96270A, [(r'^OUTP\?', 'ON')])
        r2.output(True)
        self.assertEqual(t2.writes, ['OUTP ON'])
        self.assertEqual(r2.set_rf.__func__, Fluke96270A.set_rf)

    def test_afg_conditional_load_keys(self):
        a, t = make(AgilentAFG, [(r'^FREQuency\?', '1000000'), (r'^VOLTage\?', '1'), (r'^SYSTem:ERRor\?', '+0,"No error"')])
        a.kind = '33220'
        a.sine(1e6, 1.0)
        a.sine(1e6, 1.0, load='INF')
        self.assertEqual(t.writes, ['OUTPut OFF', 'OUTPut:LOAD 50', 'APPLy:SINusoid 1000000,1,0',
                                    'OUTPut OFF', 'OUTPut:LOAD INF', 'APPLy:SINusoid 1000000,1,0'])

    def test_meter_override(self):
        m, t = make(ReferenceMeter, [(r'^READ\?', '1.5')])
        m.use_commands({'vac.band': 'VOLTage:AC:BANDwidth 20'}, uids={'vac.band': 'm1'})
        with mock.patch('drivers.reference_instruments.time.sleep'):
            self.assertEqual(m.ac_rms(), 1.5)
        self.assertEqual(t.writes, ['CONFigure:VOLTage:AC', 'VOLTage:AC:BANDwidth 20'])
        self.assertIn('VOLTage:AC:BANDwidth 20  [OVERRIDE ov-m1]', logged(m))


if __name__ == '__main__':
    unittest.main()
