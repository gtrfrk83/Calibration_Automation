"""Demo mode = the virtual bench (virtualbench.py).  A demo run walks the prompts of a real run, every command goes through the real driver on the
simulated instruments, and nothing it produces can pass for evidence.  Fast demo (--fast-demo) keeps the old quick behaviour.  Real runs are unchanged.

tkinter is stubbed in setUpModule (not at import time) so test_beta.py still loads normally."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

V = h = VH = None


def setUpModule():
    global V, h, VH
    import _tk_stub
    _tk_stub.install()
    import virtualbench as _v
    import handheld_dmm as _h
    import virtual_harness as _vh
    V, h, VH = _v, _h, _vh


def pdf_text(path):
    try:
        out = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True, timeout=60).stdout
    except FileNotFoundError:
        raise unittest.SkipTest('pdftotext not available')
    return out


def export(app, harness, name='A-1'):
    out = tempfile.mkdtemp() + '/x.pdf'
    d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}],
         'procedure': '', 'show_tar_tur': True}
    import report_dialog
    with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), \
            mock.patch.object(h.filedialog, 'asksaveasfilename', lambda **k: out):
        app.export_pdf()
    return out


class Pure(unittest.TestCase):
    def test_flags(self):
        self.assertEqual(V.flags(['x']), (False, False))
        self.assertEqual(V.flags(['x', '--demo']), (True, False))
        self.assertEqual(V.flags(['x', '--fast-demo']), (True, True))

    def test_waits_are_shortened_only_when_virtual(self):
        self.assertEqual(V.scaled(30, False), 30)
        self.assertLess(V.scaled(30, True), 1.0)
        self.assertEqual(V.scaled(0, True), 0)

    def test_plausible_text_in_tolerance_and_deterministic(self):
        for n in range(1, 60):
            t = V.plausible_text('9.95', '10.05', n)
            self.assertTrue(9.95 <= float(t) <= 10.05, t)
            self.assertEqual(t, V.plausible_text('9.95', '10.05', n))

    def test_failure_toggle_is_seeded_and_goes_outside_limits(self):
        bad = [n for n in range(1, 61) if V.failing_point(n, True)]
        self.assertTrue(5 <= len(bad) <= 15)
        self.assertEqual(bad, [n for n in range(1, 61) if V.failing_point(n, True)])
        self.assertFalse(any(V.failing_point(n, False) for n in range(1, 61)))
        for n in bad:
            t = float(V.plausible_text('9.95', '10.05', n, True))
            self.assertFalse(9.95 <= t <= 10.05, (n, t))

    def test_old_object_with_only_demo_is_fast_demo(self):
        class Old(V.VirtualMixin):
            demo = True
        self.assertTrue(Old().fast_demo)
        self.assertFalse(Old().virtual)

    def test_virtual_command_log_never_reaches_the_shared_file(self):
        from drivers.transport import CommandLog
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}):
            log = V.mark_log(CommandLog())
            log.add('>>', '*RST', 'X')
            log.append_default('virtual run')
            self.assertFalse(list(Path(home).rglob('command_log.txt')))


class HandheldVirtual(unittest.TestCase):
    MODEL = '77'
    SPEC = 'fluke_77_series_iv'

    def setUp(self):
        self.hn = VH.VHarness().start()
        self.home = self.hn.home

    def tearDown(self):
        self.hn.stop()

    def make(self, model='77IV', fast=False, failures=False):
        app = h.App(self.hn.root, model, demo=True, spec=h.load_spec('fluke_77iv_pv.json'), fast_demo=fast)
        app.asset.set('A-1')
        app.serial.set('S-1')
        app.demo_failures = None                    # no tk variable under the stub: the plain flag is read
        app.demo_failures_on = failures
        self.hn.app = app
        return app

    def test_virtual_run_walks_real_prompts_and_offers_fill(self):
        app = self.make()
        self.assertTrue(app.virtual and not app.fast_demo)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), len(app.points))
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertTrue(self.hn.fills, 'the Fill button was never offered')
        self.assertTrue([d for d in self.hn.dialogs if d[0] == 'confirm'], 'no hook-up / function prompts were shown')
        self.assertFalse(self.hn.boxes('showerror'))

    def test_commands_go_through_the_driver_on_the_simulator(self):
        app = self.make()
        self.hn.run_all()
        self.assertIsNotNone(app.io)
        wire = [t for _i, t in VH.wire(app.io)]
        self.assertTrue(wire, 'no commands were sent')
        self.assertLess(next(i for i, t in enumerate(wire) if '*RST' in t), next(i for i, t in enumerate(wire) if t.startswith('OUT ')))   # reset first
        self.assertEqual(wire[-1], 'STBY')                         # the output ends in standby
        self.assertTrue(any(t.startswith('OUT ') for t in wire))
        self.assertTrue(app.io.log.virtual)

    def test_nothing_is_written_to_the_shared_command_log_or_registry(self):
        app = self.make()
        self.hn.run_all()
        self.assertFalse(list(Path(self.home).rglob('command_log.txt')))

    def test_pdf_is_demo_marked_on_every_page(self):
        app = self.make()
        self.hn.run_all()
        out = export(app, self.hn)
        text = pdf_text(out)
        pages = [p for p in text.split('\f') if p.strip()]
        self.assertTrue(pages)
        for i, pg in enumerate(pages, 1):
            self.assertIn('DEMO DATA - NOT CALIBRATION EVIDENCE', ' '.join(pg.split()), f'page {i} not marked DEMO')

    def test_history_is_untouched_by_a_demo_report(self):
        app = self.make()
        self.hn.run_all()
        export(app, self.hn)
        dbs = [p for p in Path(self.home).rglob('*.sqlite3')]
        import sqlite3
        for p in dbs:
            con = sqlite3.connect(str(p))
            for (name,) in con.execute("select name from sqlite_master where type='table'").fetchall():
                if re.search(r'history|event|usage|report', name, re.I):
                    self.assertEqual(con.execute(f'select count(*) from "{name}"').fetchone()[0], 0, f'{p.name}.{name}')
            con.close()

    def test_failures_toggle_makes_some_points_fail(self):
        app = self.make(failures=True)
        self.hn.run_all()
        fails = [k for k, r in app.found.items() if r['result'] == 'FAIL']
        self.assertTrue(fails)
        self.assertLess(len(fails), len(app.found))

    def test_operator_may_type_anything(self):
        app = self.make()
        first = next(p['id'] for p in app.points if p['test'] == 'numeric')
        self.hn.readings[first] = '123456'
        self.hn.run_all()
        self.assertEqual(app.found[first]['result'], 'FAIL')
        self.assertNotIn(first, self.hn.fills[:0])

    def test_fast_demo_is_the_old_quick_demo(self):
        app = self.make(fast=True)
        self.assertTrue(app.fast_demo and not app.virtual)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), len(app.points))
        self.assertIsNone(app.io)                                   # no instrument touched
        self.assertFalse(self.hn.fills)
        self.assertFalse([d for d in self.hn.dialogs if d[0] == 'confirm'])
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))


class RealRunUnchanged(unittest.TestCase):
    def setUp(self):
        self.hn = VH.VHarness().start()

    def tearDown(self):
        self.hn.stop()

    def test_real_run_has_no_demo_marks_and_no_fill_button(self):
        from drivers.simulated import make_bench
        from test_handheld_options import Spy
        bench, _a, _b = make_bench()
        io = h.IO('Fluke 5522A', 'sim', transport=Spy(bench, '5522A'))
        io.auto_ramp = False
        app = h.App(self.hn.root, '77IV', demo=False, spec=h.load_spec('fluke_77iv_pv.json'), io_factory=lambda: io)
        app.cal_mode.set(h.CAL_CHOICES[1])
        app.asset.set('A-1')
        app.serial.set('S-1')
        app.io = io
        self.hn.app = app
        self.hn.default_reading = VH.DH.typed_nominal
        self.hn.run_all()
        self.assertFalse(self.hn.fills)
        self.assertFalse(app.virtual)
        self.assertFalse(getattr(io.log, 'virtual', False))
        self.assertFalse(any(r.get('synthetic') for r in app.found.values()))
        self.assertFalse(app.any_synthetic())


if __name__ == '__main__':
    unittest.main()
