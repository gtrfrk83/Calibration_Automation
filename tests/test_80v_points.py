"""Fluke 80 Series V (83V / 87V / 88V) procedures, built from the 80 Series V Calibration Manual Table 3: per-model points and limits, temperature in degC end to end, the duty-cycle point sourced as a square wave (compound WAVE / OUT / DC_OFFSET line,
DUTY, read-backs, WAVE SINE restored after the point and after a cancel), peak Min/Max prompts, spec validation.
(Headless: the simulated 5522A bench and the dialog recorders of tests.test_handheld_options; tkinter is stubbed.)"""
import json
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
COMPOUND_DUTY = 'WAVE SQUARE; OUT 5V,1kHz; DC_OFFSET 2.5V'
COMPOUND_PEAK = 'WAVE SQUARE; OUT 6V,2kHz; DC_OFFSET 1V'
h = cmdreg = procspec = tartur = Fluke5522A = Fluke5560A = Flow = SPECS = make_io = SPEC = PTS = None


def setUpModule():
    """tkinter is stubbed here, not at import time: importing this module must not change how tests.test_beta (which needs a real tkinter and
    errors without one) is loaded."""
    global h, cmdreg, procspec, tartur, Fluke5522A, Fluke5560A, Flow, SPECS, make_io, SPEC, PTS
    import _tk_stub
    _tk_stub.install()
    import cmdreg as _cmdreg
    import handheld_dmm as _h
    import procspec as _procspec
    import tartur as _tartur
    from drivers import Fluke5522A as _a, Fluke5560A as _b
    from tests.test_handheld_options import Flow as _Flow, SPECS as _SPECS, make_io as _make_io
    h, cmdreg, procspec, tartur, Fluke5522A, Fluke5560A, Flow, SPECS, make_io = _h, _cmdreg, _procspec, _tartur, _a, _b, _Flow, _SPECS, _make_io
    SPEC = h.load_spec('fluke_80_series_v_pv.json')
    PTS = {p['id']: p for p in h.points_for(SPEC, '87V')}


def spec_io():
    io, t = make_io(SPEC)
    return io, t, t.bench


class Temperature(unittest.TestCase):
    def test_points_exact(self):
        for pid, nominal, low, high in (('3-49', 0.0, '-1.0', '1.0'), ('3-50', 100.0, '98.0', '102.0')):          # limits as printed in the manual (Table 3 steps 49 / 50)
            p = PTS[pid]
            self.assertEqual((p['display_unit'], p['base_unit'], p['factor'], p['nominal'], p['low'], p['high']), ('°C', 'degC', 1.0, nominal, low, high))
            self.assertEqual(p['applied'], dict(value=nominal, frequency=None))          # sourced in degC, read in degC
            self.assertTrue(p['note'].endswith('The calibrator sources degrees C: set the meter to °C.'))
            self.assertEqual(p['group'], 'TEMP')

    def test_engine_text_is_degc(self):
        for pid, out in (('3-49', '0 °C'), ('3-50', '100 °C')):
            p = PTS[pid]
            self.assertEqual(h.output_text(p), out)
            self.assertIn('°C', h.App.accept_text(None, p))
            self.assertNotIn('°F', h.App.accept_text(None, p) + h.output_text(p) + p['note'])

    def test_no_degf_left_in_the_80v_spec(self):
        for s in SPEC['steps']:
            self.assertNotIn(s.get('base_unit'), ('degF',), s['id'])
            self.assertNotEqual(s.get('display_unit'), '°F', s['id'])

    def test_calibrator_command_unchanged(self):
        io, t, _b = spec_io()
        io.apply(PTS['3-50'])
        self.assertIn('TC_TYPE K', t.sent)
        self.assertIn('OUT 100CEL', t.sent)

    def test_report_row_in_degc(self):
        app = object.__new__(h.App)
        app.cal_mode = type('V', (), {'get': staticmethod(lambda: 'Fluke 5522A')})()
        row = app.certificate_row(PTS['3-50'], dict(result='PASS', reading=100.1, entered='100.1'))
        self.assertEqual((row['UOM'], row['Nominal'], row['Tolerance -'], row['Tolerance +']), ('°C', '100.0 °C', '98.0', '102.0'))

    def test_tartur_guard(self):
        base = dict(kind='TEMP', nominal=100.0, frequency=None, range=None)
        for unit in ('degF', '°F', 'F'):
            r = tartur.compute(dict(base, unit=unit), 210.2, 213.8)
            self.assertEqual((r['tar'], r['tur']), (None, None), unit)
            self.assertIn('not', r['reason'])
        r = tartur.compute(dict(base, unit='degC'), 99.0, 101.0)            # genuinely matching units pass the guard (and then follow the scope lookup)
        self.assertNotIn('is not: not converted', r['reason'])
        for kind in ('DUTY', 'SQUARE'):
            r = tartur.compute(dict(kind=kind, nominal=50.0, frequency=1000.0, range=None, unit='V'), 49.7, 50.3)
            self.assertEqual((r['tar'], r['tur']), (None, None), kind)

    def test_other_handheld_specs_still_degc(self):
        for name in ('fluke_287_289_pv.json', 'klein_mm325_pv.json', 'fluke_110_series_pv.json'):
            for s in json.loads((Path(h.__file__).parent / 'specs' / name).read_text(encoding='utf-8'))['steps']:
                if s['kind'] == 'TEMP':
                    self.assertIn(s['display_unit'], ('°C',), (name, s['id']))


class DutyCycle(unittest.TestCase):
    def test_point(self):
        p = PTS['3-16']
        self.assertEqual(p['kind'], 'DUTY')
        self.assertEqual(p['applied'], dict(value=5.0, frequency=1000.0, duty=50.0, offset=2.5))
        self.assertEqual((p['low'], p['high'], p['display_unit'], p['range'], p['group']), ('49.7', '50.3', '%', '6 V', 'VOHM'))
        self.assertEqual(h.output_text(p), '5 V p-p square wave, 1 kHz, 50 % duty, 2.5 V DC offset')

    def test_wire_commands_and_readbacks(self):
        io, t, bench = spec_io()
        io.apply(PTS['3-16'])
        s = t.sent
        i = s.index(COMPOUND_DUTY)
        self.assertEqual(s[i + 1], 'DUTY 50')
        tail = s[i + 2:]
        self.assertEqual(tail[:6], ['ERR?', 'WAVE?', 'DUTY?', 'DC_OFFSET?', 'OUT?', 'ERR?'])
        self.assertEqual(tail[6], 'OPER')                                          # the output is enabled only after every read-back agreed
        self.assertEqual(sum(1 for c in s if c == COMPOUND_DUTY), 1)                # a write is sent once
        self.assertEqual(bench.fluke['wave'], 'SQUARE')

    def test_restored_to_sine_on_standby(self):
        io, t, bench = spec_io()
        io.apply(PTS['3-16'])
        n = len(t.sent)
        io.standby()
        self.assertEqual(t.sent[n:], ['STBY', 'OPER?', 'WAVE SINE; DC_OFFSET 0V', 'ERR?', 'WAVE?', 'DC_OFFSET?'])
        self.assertEqual((bench.fluke['wave'], bench.fluke['offset'], bench.fluke['operate']), ('SINE', 0.0, False))
        n = len(t.sent)
        io.standby()
        self.assertEqual(t.sent[n:], ['STBY'])                                    # nothing more once restored
        io.apply(PTS['3-17.87'])                                                     # the next DC point is not a square wave
        self.assertEqual(bench.fluke['wave'], 'SINE')
        self.assertIn('OUT 3.3V,0Hz', t.sent)

    def test_restored_after_cancel(self):
        io, t, bench = spec_io()

        def cancel(*a, **k):
            raise h.Cancelled()
        io._wait = cancel
        with self.assertRaises(h.Cancelled):
            io.apply(PTS['3-16'])
        self.assertEqual(bench.fluke['wave'], 'SQUARE')
        io.standby()                                                              # what the engine's worker does on any exception, and close() on stop / abort
        self.assertEqual((bench.fluke['wave'], bench.fluke['offset']), ('SINE', 0.0))

    def test_restored_on_close(self):
        io, t, bench = spec_io()
        io.apply(PTS['3-16'])
        io.close()
        self.assertEqual(bench.fluke['wave'], 'SINE')

    def test_failed_setup_still_restores(self):
        io, t, bench = spec_io()
        t.reject = ('DUTY 50',)
        with self.assertRaises(Exception):
            io.apply(PTS['3-16'])
        self.assertNotIn('OPER', t.sent)                                          # never operated after a rejection
        io.standby()
        self.assertEqual(bench.fluke['wave'], 'SINE')

    def test_unconfirmed_restore_blocks_the_next_point(self):
        io, t, bench = spec_io()
        io.apply(PTS['3-16'])
        t.reject = ('WAVE SINE; DC_OFFSET 0V',)
        io.standby()
        self.assertTrue(io.cal.wave_nonsine)
        n = len(t.sent)
        with self.assertRaises(Exception) as cm:
            io.apply(PTS['3-17.87'])
        self.assertIn('square wave', str(cm.exception))
        self.assertNotIn('OPER', t.sent[n:])

    def test_reset_clears_the_flag(self):
        io, t, bench = spec_io()
        io.apply(PTS['3-16'])
        rep = io.cal.reset_to_defaults()
        self.assertTrue(rep.ok)
        self.assertFalse(io.cal.wave_nonsine)

    def test_registry(self):
        r60, r22 = cmdreg.merge_commands(Fluke5560A), cmdreg.merge_commands(Fluke5522A)
        for key, tmpl in (('wave.square.out', 'WAVE SQUARE; OUT {vpp:.9g}V,{freq}; DC_OFFSET {offset:.9g}V'), ('duty.set', 'DUTY {duty:.9g}'),
                          ('duty.query', 'DUTY?'), ('wave.query', 'WAVE?'), ('dcoffset.query', 'DC_OFFSET?'), ('wave.sine.offset0', 'WAVE SINE; DC_OFFSET 0V')):
            self.assertEqual((r60[key].template, r60[key].risk, r60[key].verified), (tmpl, 'normal', False), key)
            self.assertTrue(r22[key].verified and 'Operators Manual' in r22[key].ref and 'p' in r22[key].ref, key)
        self.assertEqual((r22['wave.square.out'].readback, r22['duty.set'].readback), ('wave.query', 'duty.query'))
        self.assertEqual(cmdreg.lint_registry(r22), [])

    def test_validation_of_driver_arguments(self):
        io, t, bench = spec_io()
        bench.fluke['wave']                                                       # simulator state exists
        t.reject = ()
        io.cal.set_output_square(5.0, 1000.0, 50.0, 2.5)
        self.assertEqual(io.cal.ask('duty.query').strip(), '5.000E+01')


class PeakMinMax(unittest.TestCase):
    def test_points(self):
        a, b = PTS['3-47MAX.87'], PTS['3-47MIN.87']
        sq = dict(value=6.0, frequency=2000.0, duty=50.0, offset=1.0)
        self.assertEqual((a['applied'], b['applied']), (sq, sq))
        self.assertEqual((a['kind'], b['kind'], a['section'], b['section']), ('SQUARE', 'SQUARE', 'Peak Min / Max', 'Peak Min / Max'))
        self.assertEqual((a['low'], a['high'], a['nominal']), ('3.897', '4.103', 4.0))
        self.assertEqual((b['low'], b['high'], b['nominal']), ('-2.102', '-1.898', -2.0))
        self.assertEqual((a['display_unit'], b['display_unit'], a['range'], b['range']), ('V', 'V', '6 V dc', '6 V dc'))
        self.assertEqual(h.output_text(a), '6 V p-p square wave, 2 kHz, 50 % duty, 1 V DC offset')
        self.assertEqual(h.App.accept_text(None, a), '3.897 to 4.103 V')
        self.assertLess(a['n'], b['n'])
        self.assertEqual(b['n'], a['n'] + 1)

    def test_wire_commands(self):
        io, t, bench = spec_io()
        io.apply(PTS['3-47MAX.87'])
        self.assertIn(COMPOUND_PEAK, t.sent)
        self.assertEqual(t.sent[t.sent.index(COMPOUND_PEAK) + 1], 'DUTY 50')
        io.standby()
        io.apply(PTS['3-47MIN.87'])
        self.assertEqual(sum(1 for c in t.sent if c == COMPOUND_PEAK), 2)
        io.standby()
        self.assertEqual(bench.fluke['wave'], 'SINE')

    def test_prompt_order_and_no_dial_prompt_for_min(self):
        f = Flow('87V')
        ev = f.events
        n48, n49 = PTS['3-47MAX.87']['n'], PTS['3-47MIN.87']['n']
        real_confirm, real_ask = __import__('ui_theme').confirm_steps, sys.modules['tkinter.messagebox'].askyesno

        def confirm(root, title, sub, steps, **k):
            first = k['facts'][0][1].split()[0] if k.get('facts') else ''
            if title == 'Change the function':
                ev.append(('function', first, steps[0][1].replace('Turn the meter to: ', '')))
            elif title == 'Meter setup':
                ev.append(('meter', first, steps[0][1]))
            else:
                ev.append(('other', title))
            return True
        __import__('ui_theme').confirm_steps, sys.modules['tkinter.messagebox'].askyesno = confirm, lambda *a, **k: True
        try:
            f.app._last_switch = None
            f.app._next(f.app.points, 0, None)
        finally:
            __import__('ui_theme').confirm_steps, sys.modules['tkinter.messagebox'].askyesno = real_confirm, real_ask
        functions = [e[1] for e in ev if e[0] == 'function']
        self.assertIn(str(n48), functions)
        self.assertNotIn(str(n49), functions)                                      # same function as 1-48: the dial is not asked again
        order = [(e[0], int(e[1])) for e in ev if (e[0] == 'meter' and int(e[1]) in (n48, n49)) or (e[0] == 'function' and e[1] == str(n48)) or (e[0] == 'point' and e[1] in (n48, n49))]
        self.assertEqual(order, [('function', n48), ('meter', n48), ('point', n48), ('meter', n49), ('point', n49)])
        texts = {int(e[1]): e[2] for e in ev if e[0] == 'meter' and int(e[1]) in (n48, n49)}
        self.assertEqual(texts, {n48: PTS['3-47MAX.87']['prompt'], n49: PTS['3-47MIN.87']['prompt']})
        self.assertIn('Peak Min Max', texts[n48])
        self.assertIn('read MAX', texts[n48])
        self.assertIn('step the meter to MIN', texts[n49])
        self.assertIn('pressing and holding the MIN MAX button', PTS['3-47MIN.87']['note'])    # the exit instruction is shown with the 1-49 reading


class SpecValidation(unittest.TestCase):
    def test_shipped_specs_pass(self):
        for name in set(SPECS.values()):
            self.assertEqual(procspec.validate_manual_reading(h.load_spec(name)), [], name)

    def mutate(self, pid, **changes):
        spec = json.loads(json.dumps(SPEC))
        for s in spec['steps']:
            if s['id'] == pid:
                for k, v in changes.items():
                    if k == 'applied':
                        s['applied'].update(v)
                    else:
                        s[k] = v
        return [p.code for p in procspec.validate_manual_reading(spec)]

    def test_bad_square_wave_specs(self):
        self.assertIn('square_applied', self.mutate('3-16', applied=dict(frequency=0)))
        self.assertIn('square_applied', self.mutate('3-16', applied=dict(value=-5)))
        self.assertIn('square_duty', self.mutate('3-16', applied=dict(duty=0.5, offset=0.0)))
        self.assertIn('square_offset', self.mutate('3-16', applied=dict(duty=30)))
        spec = json.loads(json.dumps(SPEC))
        for s in spec['steps']:
            if s['id'] == '3-16':
                s['applied'] = None
        self.assertIn('square_applied', [p.code for p in procspec.validate_manual_reading(spec)])

    def test_degf_temperature_rejected(self):
        self.assertIn('temp_unit', self.mutate('3-49', base_unit='degF', display_unit='°F'))
        self.assertNotIn('temp_unit', self.mutate('3-49'))


def pts(model):
    return {p['id']: p for p in h.points_for(SPEC, model)}


class Models(unittest.TestCase):
    """Table 3 columns: '87' for the 87V, '83 and 88' for the 83V and 88V; N/A rows, footnote 7 (no Peak Min/Max on the 83V) and '87 and 88 only'."""

    def test_point_counts(self):
        self.assertEqual({m: len(h.points_for(SPEC, m)) for m in ('83V', '87V', '88V')}, {'83V': 46, '87V': 56, '88V': 50})

    def test_rebuild_is_identical(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('build_80v_spec', Path(h.__file__).parent / 'specs' / 'build_80v_spec.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(json.loads(json.dumps(mod.build_spec(), ensure_ascii=False)), SPEC)

    def test_na_rows_are_87v_only(self):
        p83, p87, p88 = pts('83V'), pts('87V'), pts('88V')
        for m in ('2', '4', '6', '8', '45', '46'):
            self.assertIn(f'3-{m}', p87)
            self.assertNotIn(f'3-{m}', p83)
            self.assertNotIn(f'3-{m}', p88)

    def test_peak_and_temperature_not_on_the_83v(self):
        p83, p88 = pts('83V'), pts('88V')
        self.assertFalse([i for i in p83 if i.startswith(('3-47', '3-49', '3-50'))])
        self.assertEqual((p88['3-47MAX.83']['low'], p88['3-47MAX.83']['high']), ('3.895', '4.105'))
        self.assertEqual((p88['3-47MIN.83']['low'], p88['3-47MIN.83']['high']), ('-2.103', '-1.897'))
        self.assertEqual((p88['3-49']['low'], p88['3-50']['high']), ('-1.0', '102.0'))

    def test_column_limits(self):
        # every value as printed in Table 3 (rendered pages 9-11)
        for pid83, pid87, l83, l87 in (('3-1.83', '3-1.87', ('327.9', '332.1'), ('327.3', '332.7')),
                                       ('3-17.83', '3-17.87', ('3.296', '3.304'), ('3.297', '3.303')),
                                       ('3-23.83', '3-23.87', ('328.5', '331.5'), ('329.1', '330.9')),
                                       ('3-33B.83', '3-33B.87', ('9.94', '10.06'), ('9.96', '10.04')),
                                       ('3-41.83', '3-41.87', ('3285', '3315'), ('3291', '3309'))):
            for model in ('83V', '88V'):
                p = pts(model)[pid83]
                self.assertEqual((p['low'], p['high']), l83, (model, pid83))
            p = pts('87V')[pid87]
            self.assertEqual((p['low'], p['high']), l87, pid87)

    def test_shared_rows(self):
        for model in ('83V', '87V', '88V'):
            p = pts(model)
            self.assertEqual((p['3-11']['low'], p['3-11']['high'], p['3-11']['display_unit']), ('99.93', '99.97', 'kHz'))
            self.assertEqual((p['3-15']['low'], p['3-15']['high'], p['3-15']['display_unit']), ('999.8', '1000.2', 'Hz'))
            self.assertEqual((p['3-43']['low'], p['3-43']['high'], p['3-43']['applied']['value']), ('4.7', '5.3', 5e-09))
            self.assertEqual((p['3-44']['low'], p['3-44']['high'], p['3-44']['applied']['value']), ('9.2', '9.8', 9.5e-06))
            self.assertEqual((p['3-29']['kind'], p['3-42']['kind']), ('NONE', 'NONE'))
            self.assertEqual(p['F-1']['test'], 'visual')
            self.assertEqual([p[f'3-{n}']['test'] for n in (51, 52, 53)], ['visual'] * 3)

    def test_trigger_level_square_wave(self):
        p = PTS['3-15']
        self.assertEqual(p['applied'], dict(value=3.4, frequency=1000.0, waveform='square', duty=50.0, offset=0.0))
        io, t, bench = spec_io()
        io.apply(p)
        self.assertIn('WAVE SQUARE; OUT 3.4V,1kHz; DC_OFFSET 0V', t.sent)
        io.standby()
        self.assertEqual(bench.fluke['wave'], 'SINE')

    def test_capacitance_rel(self):
        self.assertIn('rel_zero', PTS['3-43'])
        self.assertNotIn('rel_zero', PTS['3-44'])

    def test_launchers(self):
        root = Path(h.__file__).parent / 'Procedures'
        for m in ('83V', '87V', '88V'):
            text = (root / f'Fluke_{m}_Verification.py').read_text(encoding='utf-8')
            self.assertIn(f"MODEL = '{m}'", text)
            self.assertIn("SPEC = 'fluke_80_series_v_pv.json'", text)
        self.assertFalse((root / 'Fluke_87V.py').exists())


if __name__ == '__main__':
    unittest.main()
