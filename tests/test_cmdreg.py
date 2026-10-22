"""cmdreg: formatter equals f-strings; validator rules.  No tkinter, no I/O."""
import itertools
import unittest

from cmdreg import Cmd, Placeholder as P, render, validate, merge_commands, command_owners, validate_bundle, lint_registry, is_overridable

VOLTS = Cmd('OUT {volts:.9g}V', 'Program a voltage', placeholders={'volts': P('float', '.9g', 1.0)}, kind='set')
NPLC = Cmd('VOLT:DC:NPLC {nplc:g}', 'Set NPLC', placeholders={'nplc': P('float', 'g', 10.0)}, kind='set', readback='nplc?')
NPLCQ = Cmd('VOLT:DC:NPLC?', 'Read NPLC', kind='query')
CONF = Cmd('CONF:{func} {range:.9g}', 'Configure', placeholders={'func': P('enum', '', 'VOLT:DC', enum=('VOLT:DC', 'CURR:DC')),
                                                                 'range': P('float', '.9g', 1.0)})
NOARG = Cmd('SENS:ZERO:AUTO ON', 'Autozero', kind='set')


def codes(text, cmd, name=None):
    return {p.code for p in validate(text, cmd, name)}


class Render(unittest.TestCase):
    def test_equals_fstrings(self):
        values = [0, 1, -1, 0.1, 1 / 3, 1e-9, 123456789.123456789, 1e21, 5, 2.5e-6, 1000, 100.0, float('1e300')]
        for spec in ('', '.9g', 'g', '.6f', '.3e', '.0f', 'd', '10.4f', '+.3g', '08.3f', ',.2f', '.12g', 'E', '.2%'):
            for v in values:
                try:
                    want = f'{{x:{spec}}}'.format(x=v)
                except ValueError:
                    continue
                tpl = 'A {x:' + spec + '} B'
                self.assertEqual(render(tpl, {'x': v}), 'A ' + want + ' B')
        self.assertEqual(render(VOLTS, {'volts': 1.23456789012}), f'OUT {1.23456789012:.9g}V')
        for v in values[:10]:
            self.assertEqual(render(VOLTS, {'volts': v}), f'OUT {v:.9g}V')

    def test_render_errors(self):
        from cmdreg import CmdError
        for bad in ({}, {'volts': None}, {'volts': 'x'}, {'volts': float('nan')}, {'volts': float('inf')}, {'volts': True}):
            with self.assertRaises(CmdError):
                render(VOLTS, bad)
        with self.assertRaises(CmdError):
            render(CONF, {'func': 'OHM', 'range': 1})
        self.assertEqual(render(CONF, {'func': 'CURR:DC', 'range': 0.1, 'extra': 1}), 'CONF:CURR:DC 0.1')


class Validate(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validate('OUT {volts:.6f}V', VOLTS), [])
        self.assertEqual(validate('OUT {volts:.9g}V', VOLTS), [])
        self.assertEqual(validate('VOLT:DC:NPLC {nplc:g}', NPLC), [])
        self.assertEqual(validate('SENS:ZERO:AUTO OFF', NOARG), [])

    def test_basics(self):
        self.assertIn('empty', codes('', VOLTS))
        self.assertIn('ascii', codes('OUT {volts}Vµ', VOLTS))
        self.assertIn('ascii', codes('OUT {volts}\nV', VOLTS))
        self.assertIn('length', codes('OUT {volts}V' + 'X' * 300, VOLTS))
        self.assertIn('syntax', codes('OUT {volts', VOLTS))
        self.assertIn('syntax', codes('OUT {}V', VOLTS))
        self.assertNotIn('length', codes('OUT {volts}V' + 'X' * 200, VOLTS))

    def test_placeholders(self):
        self.assertIn('placeholder.unknown', codes('OUT {amps}A {volts}', VOLTS))
        self.assertIn('placeholder.missing', codes('OUT 5V', VOLTS))
        self.assertIn('attr', codes('OUT {volts.real}V', VOLTS))
        self.assertIn('attr', codes('OUT {volts[0]}V', VOLTS))
        self.assertIn('conv', codes('OUT {volts!r}V', VOLTS))
        self.assertIn('format', codes('OUT {volts:{volts}}V', VOLTS))
        self.assertIn('format', codes('OUT {volts:d}V', VOLTS))          # d does not fit a float sample
        self.assertIn('format', codes('OUT {volts:zzz}V', VOLTS))
        self.assertIn('format', codes('OUT {volts:99999.9f}V', VOLTS))
        self.assertIn('format', codes('CONF:{func:d} {range}', CONF))
        self.assertEqual(validate('CONF:{func} {range:.3f}', CONF), [])

    def test_forbidden_patterns(self):
        for t in ('*RST', '*rst', '*SAV 1', '*RCL 2', 'SYST:PRES', 'SYSTem:PRESet', ':SYST:PRES', 'SYST:SEC:IMM', 'CAL:VAL 1',
                  'CALibration:STORe', 'SEC:STAT', 'PASS:X', 'DIAG:TEST', 'SERV:X', 'FACT:X', 'SENS:ZERO:AUTO ON;*RST',
                  'SENS:ZERO:AUTO ON; SYST:PRES', 'CAL_STORE', 'SYST:COMM:LAN:IP 1', 'MMEM:DEL "x"'):
            self.assertIn('forbidden', codes(t, NOARG), t)
        for t in ('CALC:AVER:STAT ON', 'CALCulate:STATe ON', 'SENS:ZERO:AUTO OFF', 'SYST:ERR?', 'DISP:TEXT "CAL"', 'SENS:FREQ:APER 0.1'):
            self.assertNotIn('forbidden', codes(t, NOARG), t)
        self.assertIn('forbidden', codes('SENS:ZERO:AUTO ON;CAL:X 1', NOARG, 'Fluke8846A'))
        self.assertIn('forbidden', codes('SENS:ZERO:AUTO ON;  CALIBRATION : X', NOARG, 'Fluke8846A'))

    def test_output_tokens(self):
        for t in ('OPER', 'oper', 'OPERATE', 'OUTP ON', 'OUTP1 ON', 'OUTPut:STATe ON', 'OUTP:STAT?', 'SENS:ZERO:AUTO ON;OUTP 1', ':OUTP ON'):
            self.assertIn('output', codes(t, NOARG), t)
        self.assertNotIn('output', codes('OUTP:LOAD 50', NOARG))
        self.assertNotIn('output', codes('OUTP OFF', NOARG))
        outcmd = Cmd('OPER', 'Operate', kind='action', risk='output')
        self.assertIn('locked', codes('OPER', Cmd('OPER2', risk='output', kind='action')))
        self.assertEqual(validate('OPER', outcmd), [])                      # identical to factory is fine; edits are locked
        self.assertIn('locked', codes('OPER ', outcmd))

    def test_locked_and_secret(self):
        self.assertFalse(is_overridable(Cmd('X', risk='locked'))[0])
        self.assertFalse(is_overridable(Cmd('X', risk='output'))[0])
        self.assertIn('locked', codes('*CLS', Cmd('*IDN?', risk='locked', kind='query')))
        sec = Cmd('CAL:SEC:STAT OFF,{pw}', 'x', placeholders={'pw': P('secret', '', 'x')})
        self.assertFalse(is_overridable(sec)[0])
        self.assertIn('secret', codes('STAT {pw}', sec))
        self.assertEqual(validate(sec.template, sec), [])

    def test_kind_rules(self):
        self.assertIn('readback', codes('VOLT:DC:NPLC', NPLCQ))
        self.assertEqual(validate('VOLT:DC:NPLC? 5', NPLCQ), [])
        self.assertIn('type', codes('VOLT:NPLC? {nplc}', NPLC))

    def test_bundle_keeps_readback(self):
        reg = {'set': Cmd('VOLT:DC:NPLC {nplc:g}', placeholders={'nplc': P('float', 'g', 1)}, kind='set', readback='get'),
               'get': Cmd('VOLT:DC:NPLC?', kind='query')}
        self.assertEqual(validate_bundle({}, reg), [])
        self.assertEqual(validate_bundle({'get': 'VOLT:DC:NPLC2?'}, reg), [])
        self.assertTrue(validate_bundle({'get': 'VOLT:DC:NPLC2'}, reg))
        self.assertTrue(validate_bundle({}, {'set': Cmd('X', kind='set', readback='gone')}))
        self.assertEqual(lint_registry(reg), [])
        self.assertTrue(lint_registry({'a': Cmd('X {y}', kind='set')}))

    def test_vbs(self):
        vbs = Cmd("VBS 'app.Acquisition.C1.VerScale = {scale:g}'", 'Scale', placeholders={'scale': P('float', 'g', 0.5)}, lang='vbs')
        self.assertEqual(validate("VBS 'app.Acquisition.C2.VerScale = {scale:g}'", vbs), [])
        self.assertEqual(validate("VBS 'app.Math.F1.Source1 = \"C2\"'", Cmd("VBS 'app.Math.F1.Source1 = \"C1\"'", lang='vbs', kind='set')), [])
        bad = ("VBS 'app.Utility.Setup = 1'", "VBS 'app.Acquisition.C1.VerScale = {scale:g}:x=1'", "VBS 'CreateObject(\"WScript.Shell\")'",
               "VBS 'app.Acquisition.C1.X = Shell({scale:g})'", "VBS 'app.Measure.P1 = Calibrate'", "VBS 'app.Acquisition.C1.X = Exec({scale})'",
               "VBS 'x = 1 : app.Acquisition.C1.VerScale = {scale:g}'", "VBS? 'app.Acquisition.C1.VerScale = {scale:g}'")
        for t in bad:
            self.assertIn('vbs', codes(t, vbs), t)
        self.assertIn('vbs', codes("VBS 'app.Acquisition.C1.VerScale = {scale:g}'x", vbs))
        # by driver name alone
        self.assertIn('vbs', codes("VBS 'app.Utility.X = 1'", None, 'LeCroyWS4104HD'))

    def test_never_raises(self):
        for t in (None, 5, b'x', object(), '{', '}', '{{}}', '{0}', '{a b}', '\x00', 'x' * 10000):
            self.assertIsInstance(validate(t, VOLTS), list)
            self.assertIsInstance(validate(t, None), list)
        self.assertIsInstance(validate('OUT', Cmd('X', placeholders={'a': object()})), list)

    def test_merge_mro(self):
        class A:
            COMMANDS = {'a': Cmd('A'), 'b': Cmd('B')}

        class B(A):
            COMMANDS = {'b': Cmd('B2'), 'c': Cmd('C')}

        class C(B):
            pass
        m = merge_commands(C)
        self.assertEqual({k: v.template for k, v in m.items()}, {'a': 'A', 'b': 'B2', 'c': 'C'})
        self.assertEqual(command_owners(C()), {'a': 'A', 'b': 'B', 'c': 'B'})


if __name__ == '__main__':
    unittest.main()
