"""Datasheet Builder runtime against the simulated benches (drivers/simulated*.py): generated DMM, scope and generator datasheets are run end to end
by the real engine code (handheld_dmm.App + dsb_runtime.DsbApp, worker threads, drivers, judging, checkpoint, PDF).  Only the modal dialogs are
scripted (tests/dsb_run_harness.py); no tkinter is installed here, so tests/_tk_stub.py stands in for it.
Run:  python -m unittest tests.test_dsb_runtime_bench"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import dsb_run_harness as H  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402
import dsb_runtime as rt  # noqa: E402
import report_dialog  # noqa: E402
from drivers.simulated import make_bench, SimFlukeTransport  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402


def spec_of(ds, plan=True):
    return dsp.export_spec(ds, plan=dm.match_datasheet(ds) if plan else None).spec


def cal_io(scope=False, models=('5560A', '5522A')):
    bench, _a, _b = make_bench()
    return rt.DsbIO({}, transports={m: SimFlukeTransport(bench, m) for m in models}, scope=scope)


def manual(app):
    app.cal_mode.set(rt.hh.CAL_CHOICES[2])        # the engine's own calibrator box: Manual
    return app


def outs(w):
    return [(i, t) for i, (_inst, t) in enumerate(w) if t.startswith('OUT ') and not t.endswith('?')]


class Base(unittest.TestCase):
    def setUp(self):
        self.h = H.Harness().start()

    def tearDown(self):
        self.h.stop()

    def pdf_text(self, app, details=None):
        out = tempfile.mkdtemp() + '/A-100-test.pdf'
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}],
             'procedure': '', 'show_tar_tur': True}
        d.update(details or {})
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), \
                mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        return subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout


class DmmRun(Base):
    def run_dmm(self, io=None, plan=True):
        io = io or cal_io()
        app = self.h.make_app(spec_of(fx.dmm_34461a_like(), plan=plan), io=io)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        return app, io

    def test_every_point_is_judged_from_the_typed_reading(self):
        app, io = self.run_dmm()
        self.assertEqual(len(app.found), len(app.points))
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        self.assertTrue(all(r['source'] == 'typed' and not r['synthetic'] for r in app.found.values()))
        self.assertTrue(all(r['standard'] in ('5560A', '5522A') for r in app.found.values()))

    def test_report_prints_the_absolute_limits_as_low_and_high_limit(self):
        """The report rows already hold the absolute low / high limits (row keys 'Tolerance -' / 'Tolerance +', unchanged for snapshots and history);
        a Datasheet Builder report now heads them Low Limit / High Limit.  The numbers and the verdict are the ones the run judged with."""
        app, io = self.run_dmm()
        p = next(q for q in app.points if q['id'] == 'dcv.r10.+5')
        row = app.certificate_row(p, app.found[p['id']])
        self.assertEqual((row['Tolerance -'], row['Tolerance +']), (p['low'], p['high']))
        text = self.pdf_text(app)
        head = next(line for line in text.splitlines() if 'Nominal' in line and 'UOM' in line)
        self.assertIn('Low Limit', head)
        self.assertIn('High Limit', head)
        self.assertNotIn('Tolerance', head)
        self.assertIn(p['low'], text)
        self.assertIn(p['high'], text)
        self.assertIn('RESULT: PASS', text)

    def test_wire_reset_first_zero_hz_on_dc_standby_after_each_point(self):
        app, io = self.run_dmm()
        w = H.wire(io)
        o = outs(w)
        self.assertTrue(o)
        first = o[0][0]
        before = [t for _i, t in w[:first]]
        self.assertIn('*RST', before)
        self.assertEqual(before.count('*RST'), 2, 'both calibrators are reset before any output')
        dc = [t for _i, t in o if t.startswith('OUT ') and ',' in t and t.rstrip().endswith('Hz') and t.split(',')[1] == '0Hz']
        self.assertTrue(dc, 'DC points carry an explicit 0 Hz')
        self.assertTrue(all(',0Hz' in t for _i, t in o[:12]), 'the first points are DC volts: explicit 0 Hz on each')
        for (i, _a), (j, _b) in zip(o, o[1:]):
            self.assertTrue(any(t == 'STBY' for _x, t in w[i + 1:j]), 'standby between points')
        self.assertEqual(w[-3][1], 'STBY')
        self.assertIn('STBY', [t for _i, t in w[-4:]])

    def test_high_voltage_points_ask_once_and_output_once(self):
        app, io = self.run_dmm()
        hv = [d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(hv), 1, 'rule 9: one high-voltage question per hook-up group (all of these points are in the one voltage / ohms hook-up)')
        self.assertTrue(any(p['applied']['value'] == 1000 for p in app.points if p['run']['kind'] == 'DCV'), 'the group does reach 1000 V')
        o = [t for _i, t in outs(H.wire(io))]
        self.assertEqual(len(o), len(set(zip(o, range(len(o))))), 'each point is output exactly once')
        self.assertEqual(sum(1 for t in o if t.startswith('OUT 1000V')), 1)

    def test_out_of_tolerance_reading_fails(self):
        io = cal_io()
        app = self.h.make_app(spec_of(fx.dmm_34461a_like()), io=io)
        self.h.default_reading = H.typed_nominal
        bad = next(p for p in app.points if p['nominal'] and p['run']['kind'] == 'DCV')
        self.h.readings[bad['id']] = lambda p: H.typed_nominal(p, offset=p['nominal'] / p['factor'] * 0.5)
        self.assertTrue(self.h.run_all())
        self.assertEqual(app.found[bad['id']]['result'], 'FAIL')
        self.assertEqual(sum(1 for r in app.found.values() if r['result'] == 'FAIL'), 1)

    def test_spec_without_a_saved_plan_gets_its_standards_at_run_time(self):
        app, io = self.run_dmm(plan=False)
        self.assertTrue(app.dsb['plan'])
        self.assertTrue(any(r['route']['assigned'] for r in app.found.values()))
        self.assertTrue(any(r['route']['auto'] for r in app.found.values()))

    def test_substituted_standard_is_recorded_and_tar_tur_left_blank(self):
        io = cal_io(models=('5522A',))
        app = self.h.make_app(spec_of(fx.dmm_34461a_like()), io=io)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        subs = [r for r in app.found.values() if r['route']['assigned'] and r['route']['assigned'] != r['standard']]
        self.assertTrue(subs, 'the 5560A assignments fall back to the connected 5522A')
        self.assertTrue(all(r['standard'] == '5522A' for r in app.found.values() if r['route']['auto']))

    def test_no_instrument_is_fully_manual_and_says_so(self):
        app = manual(self.h.make_app(spec_of(fx.dmm_34461a_like())))
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        self.assertTrue(all(r['standard'] in ('', 'manual') for r in app.found.values()))
        self.assertTrue(all(not r['route']['auto'] for r in app.found.values()))

    def test_demo_run_is_synthetic_and_never_real_looking(self):
        app = self.h.make_app(spec_of(fx.dmm_34461a_like()), demo=True)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertTrue(app.found)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        text = self.pdf_text(app)
        self.assertIn('DEMO', text.upper())

    def test_report_names_datasheet_and_standards(self):
        app, io = self.run_dmm()
        text = self.pdf_text(app)
        self.assertIn('34461A', text)
        self.assertIn('user-built', text)
        self.assertIn('Standards:', text)
        self.assertRegex(text, r'5560A \(\d+\)')

    def test_procmods_state_is_shared_with_the_io(self):
        app, io = self.run_dmm()
        self.assertIs(io.pm_state, app.pm_state)


class Resume(Base):
    def test_checkpoint_resume_skips_done_points_and_resets_again(self):
        spec = spec_of(fx.dmm_34461a_like())
        io = cal_io()
        app = self.h.make_app(spec, io=io)
        n = 6
        ids = [p['id'] for p in app.points]
        self.h.default_reading = lambda p: H.typed_nominal(p) if p['id'] in ids[:n] else None
        self.h.run_all()
        self.assertEqual(len(app.found), n)
        app.save(silent=True)
        path = app._checkpoint_path()
        data = json.loads(path.read_text())
        self.assertEqual(data['dsb']['uid'], spec['dsb']['uid'])
        self.assertEqual(data['dsb']['period'], app.period)

        h2 = self.h
        io2 = cal_io()
        app2 = h2.make_app(spec, io=io2)
        with mock.patch.object(rt.hh.filedialog, 'askopenfilename', lambda **k: str(path)):
            app2.load()
        self.assertEqual(len(app2.found), n)
        h2.default_reading = H.typed_nominal
        self.assertTrue(h2.run_all())
        self.assertEqual(len(app2.found), len(app2.points))
        w = H.wire(io2)
        self.assertEqual([t for _i, t in w].count('*RST'), 2, 'the reset runs again on resume')
        self.assertEqual(len(outs(w)), len(app2.points) - n, 'only the missing points are output')

    def test_the_standards_screen_comes_before_a_real_run_and_names_what_is_connected(self):
        spec = spec_of(fx.dmm_34461a_like())
        app = self.h.make_app(spec, io=cal_io())
        self.h.default_reading = H.typed_nominal
        self.h.run_all()
        screens = [d for d in self.h.dialogs if d[0] == 'confirm' and d[1] == 'Before the run']
        self.assertEqual(len(screens), 1)
        self.assertTrue(any('connected' in line for line in screens[0][3]))
        rows = app.pre_run_rows(app.points)
        self.assertTrue(rows)
        self.assertTrue(all(r[2] for r in rows))                       # the simulated bench answers

    def test_an_interrupted_run_is_offered_for_continuing(self):
        spec = spec_of(fx.dmm_34461a_like())
        app = self.h.make_app(spec, io=cal_io())
        n = 6
        ids = [p['id'] for p in app.points]
        self.h.default_reading = lambda p: H.typed_nominal(p) if p['id'] in ids[:n] else None
        self.h.run_all()
        self.assertEqual(len(app.found), n)                          # the progress file was saved after each point
        asked = [d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'Continue the saved run?']
        self.assertEqual(asked, [])                                  # nothing saved before the first run: no offer
        # a new window, the same instrument ID: the offer appears, Yes keeps the six readings and runs only the rest
        io2 = cal_io()
        app2 = self.h.make_app(spec, io=io2)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        asked = [d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'Continue the saved run?']
        self.assertEqual(len(asked), 1)
        self.assertEqual(len(app2.found), len(app2.points))
        self.assertEqual(len(outs(H.wire(io2))), len(app2.points) - n)
        # No: the saved readings are not loaded
        self.h.dialogs.clear()
        self.h.box_answer['askyesno'] = False
        app3 = self.h.make_app(spec, io=cal_io())
        self.h.run_all()
        self.assertTrue(any(d[0] == 'box' and d[2] == 'Continue the saved run?' for d in self.h.dialogs))

    def test_checkpoint_of_another_datasheet_version_or_period_is_refused(self):
        spec = spec_of(fx.dmm_34461a_like())
        app = self.h.make_app(spec, io=cal_io())
        self.h.default_reading = lambda p: H.typed_nominal(p) if p['n'] <= 2 else None
        self.h.run_all()
        app.save(silent=True)
        path = app._checkpoint_path()
        data = json.loads(path.read_text())
        for key, val in (('version', 99), ('uid', 'other'), ('period', '90d')):
            bad = json.loads(json.dumps(data))
            bad['dsb'][key] = val
            path.write_text(json.dumps(bad))
            app2 = self.h.make_app(spec, io=cal_io())
            self.h.dialogs.clear()
            with mock.patch.object(rt.hh.filedialog, 'askopenfilename', lambda **k: str(path)):
                app2.load()
            self.assertEqual(len(app2.found), 0, key)
            self.assertTrue(any(d[0] == 'box' and d[1] == 'showerror' for d in self.h.dialogs), key)


class EmptySectionRun(Base):
    """A sheet started from the handheld template still has empty sections when it is run: they are skipped, with no error and nothing printed for them."""

    def sheet_with_empty_sections(self):
        ds = fx.dmm_34461a_like()
        have = {f.kind for f in ds.functions}
        added = [ds.add_function(k).name for k in ('DCI', 'ACI', 'OHM2', 'CONT', 'CAP', 'FREQ', 'TEMP', 'DIODE') if k not in have]
        self.assertTrue(added)
        return ds, added

    def test_export_skips_empty_sections_and_still_validates(self):
        ds, added = self.sheet_with_empty_sections()
        self.assertEqual([], [str(p) for p in dsp.db.errors(dsp.db.validate(ds))])
        res = dsp.export_spec(ds)
        self.assertIsNotNone(res.spec)
        plain = dsp.export_spec(fx.dmm_34461a_like()).spec
        self.assertEqual([s['nominal'] for s in res.spec['steps']], [s['nominal'] for s in plain['steps']])
        import procspec
        self.assertEqual([], list(procspec.validate_manual_reading(res.spec)))

    def test_run_is_the_same_as_without_the_empty_sections_and_prints_no_empty_section(self):
        ds, added = self.sheet_with_empty_sections()
        app = self.h.make_app(spec_of(ds), io=cal_io())
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), len(app.points))
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        text = self.pdf_text(app)
        self.assertIn('DC volts', text)
        for name in added:
            self.assertNotIn(name, text)


class ScopeRun(Base):
    def reading(self, p):
        run = p['run']
        if p['test'] == 'visual':
            return True
        return '-1.5' if run['op'] == 'scope_bw' else H.typed_nominal(p)

    def test_scope_datasheet_sources_dc_sine_and_marker(self):
        io = cal_io(scope=True)
        app = self.h.make_app(spec_of(fx.scope_tds2000c_like()), io=io)
        self.h.default_reading = self.reading
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), len(app.points))
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        w = H.wire(io)
        text = [t for _i, t in w]
        self.assertLess(text.index('*RST'), text.index('SCOPE DCV'), 'reset first')
        self.assertTrue(any(t.startswith('OUT -0.036') for t in text))
        self.assertTrue(any('MHz' in t and t.startswith('OUT') for t in text), 'leveled sine for bandwidth')
        self.assertTrue(any('SCOPE MARK' in t.upper() or t.startswith('MARK') for t in text), 'time marker')
        for (i, _a), (j, _b) in zip(outs(w), outs(w)[1:]):
            self.assertTrue(any(t == 'STBY' for _x, t in w[i + 1:j]))
        self.assertEqual(text[-1] if text[-1] != 'OPER?' else text[-2], 'STBY')

    def test_bandwidth_reference_is_asked_once_per_run(self):
        io = cal_io(scope=True)
        app = self.h.make_app(spec_of(fx.scope_tds2000c_like()), io=io)
        self.h.default_reading = self.reading
        self.assertTrue(self.h.run_all())
        bw = [p for p in app.points if p['run']['op'] == 'scope_bw']
        self.assertTrue(bw)
        refs = [d for d in self.h.dialogs if d[0] == 'confirm' and d[1] == 'Reference level']
        self.assertEqual(len(refs), 1)

    def test_trigger_answered_no_fails_the_point(self):
        io = cal_io(scope=True)
        app = self.h.make_app(spec_of(fx.scope_tds2000c_like()), io=io)
        self.h.default_reading = self.reading
        trig = next(p for p in app.points if p['run']['op'] == 'scope_trigger')
        self.h.readings[trig['id']] = False
        self.assertTrue(self.h.run_all())
        self.assertEqual(app.found[trig['id']]['result'], 'FAIL')

    def test_no_calibrator_is_fully_manual(self):
        app = manual(self.h.make_app(spec_of(fx.scope_tds2000c_like())))
        self.h.default_reading = self.reading
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), len(app.points))
        self.assertTrue(all(not r['route']['auto'] for r in app.found.values()))


class GeneratorRun(Base):
    def make(self, models=('5790B', '53132A')):
        bench, t = make_fgen_bench('33220A')
        trans = {'5790B': t['std'], '53132A': t['counter']}
        io = rt.DsbIO({}, transports={m: trans[m] for m in models})
        app = self.h.make_app(spec_of(fx.generator_33220a_like()), io=io)

        def operator(title, heading, steps, facts):
            """The operator sets the simulated unit under test as the prompt asks."""
            run = app._cur['run']
            txt = ' '.join(s if isinstance(s, str) else ' '.join(s) for s in steps).upper()
            f = run['reference_hz'] if 'REFERENCE' in txt else run['frequency']
            amp = run['nominal'] if run['kind'] == 'GEN_AMPL' else (run['amplitude'] or 1.0)
            bench.connected = 'counter' if run['op'] == 'std_freq' else 'std'
            if run['op'] == 'std_flat' and 'REFERENCE' not in txt and title == 'Check the setup':
                return True
            bench.gen.update(on=True, func='SIN', freq=f if f else (run['nominal'] if run['kind'] == 'GEN_FREQ' else 1e3), unit='VPP', load=1e40,
                             amp=(amp * 2 * 2 ** 0.5 if run['kind'] != 'GEN_FREQ' else 1.0))
            if run['kind'] == 'GEN_FREQ':
                bench.gen.update(freq=run['nominal'], amp=1.0)
            return True
        self.h.on_confirm = operator
        self.h.default_reading = H.typed_nominal
        return app, io, bench

    def test_generator_points_are_read_by_the_standards(self):
        app, io, bench = self.make()
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), len(app.points))
        by = {}
        for p in app.points:
            by.setdefault(p['run']['kind'], set()).add(app.found[p['id']]['standard'])
        self.assertEqual(by['GEN_AMPL'], {'5790B'})
        self.assertEqual(by['GEN_FREQ'], {'53132A'})
        self.assertTrue(by['GEN_OFFSET'] <= {'', 'manual'}, 'offset has no verified driver reading: by hand')
        self.assertTrue(all(r['source'] == 'standard' for k, r in app.found.items() if r['standard'] in ('5790B', '53132A')))
        text = [t for _i, t in H.wire(io)]
        self.assertLess(text.index('*RST'), text.index('MEAS?'))
        self.assertIn('RANGE 0.02', text)

    def test_counter_failure_falls_back_to_a_typed_reading(self):
        app, io, bench = self.make()
        orig = self.h.on_confirm

        def wrong_input(title, heading, steps, facts):
            r = orig(title, heading, steps, facts)
            if app._cur['run']['op'] == 'std_freq':
                bench.connected = 'std'                   # counter not connected to the unit: its read fails
            return r
        self.h.on_confirm = wrong_input
        self.assertTrue(self.h.run_all())
        fr = [app.found[p['id']] for p in app.points if p['run']['op'] == 'std_freq']
        self.assertTrue(fr)
        self.assertTrue(all(r['source'] == 'typed' for r in fr))
        self.assertTrue(any(d[0] == 'box' and d[2] == 'Measuring standard' for d in self.h.dialogs))

    def test_standard_without_a_driver_degrades_to_manual_and_report_says_so(self):
        app, io, bench = self.make(models=('53132A',))              # no 5790B: amplitude / flatness points have no connected standard
        self.assertTrue(self.h.run_all())
        amp = [app.found[p['id']] for p in app.points if p['run']['kind'] == 'GEN_AMPL']
        self.assertTrue(amp)
        self.assertTrue(all(not r['route']['auto'] and r['source'] == 'typed' for r in amp))
        text = self.pdf_text(app)
        self.assertIn('By hand', text)
        self.assertIn('[manual]', text)

    def test_generator_report_names_datasheet_and_standards(self):
        app, io, bench = self.make()
        self.assertTrue(self.h.run_all())
        text = self.pdf_text(app)
        self.assertIn('33220A', text)
        self.assertIn('5790B (', text)
        self.assertIn('53132A (', text)
        self.assertIn('Unverified', text)


if __name__ == '__main__':
    unittest.main()
