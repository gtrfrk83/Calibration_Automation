"""The virtual bench on the other engines: Truevolt, DACQ, 34401A, 8846A verification, function generators, TDS2000C, MDO4000C.
Each demo run is a real run against simulated instruments: dialogs appear, commands go through the real driver, records are synthetic,
the command log is virtual (never the shared evidence file).  tkinter is stubbed in setUpModule."""
import faulthandler
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

VH = h = None


def setUpModule():
    global VH, h
    import _tk_stub
    _tk_stub.install()
    import virtual_harness as _vh
    import handheld_dmm as _h
    VH, h = _vh, _vh.hh


class Base(unittest.TestCase):
    def setUp(self):
        faulthandler.dump_traceback_later(240, exit=True)
        self.hn = VH.VHarness().start()

    def tearDown(self):
        faulthandler.cancel_dump_traceback_later()
        self.hn.stop()

    def common(self, app, expect_commands=True):
        self.assertTrue(app.virtual and not app.fast_demo)
        self.assertFalse(self.hn.boxes('showerror'), self.hn.boxes('showerror'))
        self.assertTrue(app.results)
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()), 'a demo record is not marked synthetic')
        self.assertTrue(app.any_synthetic())
        self.assertTrue([d for d in self.hn.dialogs if d[0] == 'confirm'], 'no windows of a real run were shown')
        if expect_commands:
            self.assertIsNotNone(app.io)
            self.assertTrue(app.io.log.virtual)
            self.assertTrue(VH.wire(app.io), 'no commands went through the driver')
        self.assertFalse(list(Path(self.hn.home).rglob('command_log.txt')))

    def fast_is_old(self, app):
        self.assertTrue(app.fast_demo and not app.virtual)
        self.assertIsNone(app.io)
        self.assertFalse([d for d in self.hn.dialogs if d[0] == 'confirm'])
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))


class Truevolt(Base):
    def make(self, fast=False):
        import truevolt_verification as T
        T.messagebox = h.messagebox
        app = T.App(self.hn.root, '34470A', demo=True, fast_demo=fast)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        return app

    def test_virtual(self):
        app = self.make()
        self.assertTrue(self.hn.run_all())
        self.common(app)
        self.assertTrue(any('RST' in t for _i, t in VH.wire(app.io)))

    def test_fast(self):
        app = self.make(True)
        self.assertTrue(self.hn.run_all())
        self.fast_is_old(app)


class Dacq(Base):
    def make(self, fast=False):
        import dacq_verification as D
        D.configure('34970A')
        D.messagebox = h.messagebox
        app = D.App(self.hn.root, '34970A', demo=True, fast_demo=fast)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        return app

    def test_virtual(self):
        app = self.make()
        self.assertTrue(self.hn.run_all())
        self.common(app)

    def test_fast(self):
        app = self.make(True)
        self.assertTrue(self.hn.run_all())
        self.fast_is_old(app)

    def test_high_voltage_question_is_asked_once_per_run(self):
        # owner 2026-11-02: only the first high-voltage point asks; the rest of the run is covered by that answer
        app = self.make()
        self.assertTrue(self.hn.run_all())
        import dacq_verification as D
        hv_points = [p for p in D.POINTS if p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= 100]
        self.assertGreater(len(hv_points), 1)
        asks = [d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'askyesno' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(asks), 1, asks)

    def test_every_zero_short_point_is_on_channel_3_with_partner_13(self):
        # owner 2026-11-02: the resistance shorted points use channel 3 (4-wire partner 13); the DC volts zero points followed the same day
        import dacq_verification as D
        for model in ('34970A', '34972A'):
            D.configure(model)
            app = self.make()
            ohm = [p for p in D.POINTS if p['kind'] in ('OHM4', 'OHM2') and p['source'] == 'none']
            volt = [p for p in D.POINTS if p['kind'] == 'DCV' and p['source'] == 'none']
            self.assertEqual((len(ohm), len(volt)), (14, 5))
            self.assertEqual({p['group'] for p in ohm}, {'ZERO_SHORT_OHM'})
            self.assertEqual({p['group'] for p in volt}, {'ZERO_SHORT_OHM'})
            self.assertEqual({app.io.channel(p) if app.io else D.channel_for('34901A', 2, p['role']) for p in ohm}, {203})
            self.assertEqual({D.channel_for('34901A', 2, p['role']) for p in volt}, {203})
            self.assertIn('channel 203', app.setup_text(ohm[0]))
            self.assertIn('213', app.setup_text(ohm[0]))

    def test_type_j_thermocouple_point_is_last_on_channel_2_zero_c_plus_minus_1(self):
        # owner 2026-11-02: a type J thermocouple point on channel 2 at the end, 0 degC +/- 1 degC, sourced by the calibrator's thermocouple simulation
        import dacq_verification as D
        for model in ('34970A', '34972A'):
            D.configure(model)
            p = D.POINTS[-1]
            self.assertEqual((p['kind'], p['tc_type'], p['nominal'], p['error'], p['group'], p['role']), ('TEMP', 'J', 0.0, 1.0, 'TEMP', 'tc'))
            self.assertEqual(D.channel_for('34901A', 2, p['role']), 202)
        app = self.make()
        self.assertTrue(self.hn.run_all())
        wire = [t for _i, t in VH.wire(app.io)]
        self.assertTrue(any('CONF:TEMP TC,J,(@202)' in t for t in wire), wire[-12:])
        self.assertTrue(any('OUT 0CEL' in t for t in wire))
        last = D.POINTS[-1]['id']
        self.assertIn(last, [int(k) for k in app.found])           # the optional sections are skipped; the thermocouple point is not optional


class Agilent34401A(Base):
    def make(self):
        import Agilent_34401A as A
        with mock.patch.object(A.App, 'refresh_ports', lambda s: None):
            app = A.App(self.hn.root, demo=True)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        return app

    def test_virtual(self):
        app = self.make()
        self.assertTrue(self.hn.run_all())
        self.common(app)


class Fluke8846A(Base):
    def test_virtual_stops_at_the_engines_own_lab_verified_point(self):
        import Fluke_8846A_Verification as V
        with mock.patch.object(V.App, 'refresh_ports', lambda s: None):
            app = V.App(self.hn.root, demo=True)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        self.hn.run_all()
        self.assertTrue(app.virtual)
        self.assertTrue(app.io.log.virtual)
        self.assertTrue(VH.wire(app.io))
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))


class Tds(Base):
    def test_virtual(self):
        import tds2000c_verification as T
        app = T.App(self.hn.root, demo=True)
        app.asset.set('A1')
        app.v_model.set('2024C')
        self.hn.app = app
        app.run_all()
        self.assertTrue(self.hn.pump_poll(120))
        self.common(app)

    def test_fast(self):
        import tds2000c_verification as T
        app = T.App(self.hn.root, demo=True, fast_demo=True)
        app.asset.set('A1')
        app.v_model.set('2024C')
        self.hn.app = app
        app.run_all()
        self.assertTrue(self.hn.pump_poll(120))
        self.fast_is_old(app)


class Mdo(Base):
    def test_virtual(self):
        import mdo4000c_verification as M
        from tkinter import simpledialog
        app = M.App(self.hn.root, demo=True)
        app.asset.set('A1')
        self.hn.app = app
        with mock.patch.object(simpledialog, 'askstring', lambda *a, **k: k.get('initialvalue'), create=True):
            app.run_all()
            self.assertTrue(self.hn.pump_poll(200))
        self.common(app)
        self.assertFalse([k for k, r in app.results.items() if r.get('result') == 'FAIL'])


class FunctionGenerator(Base):
    def test_virtual(self):
        import fgen_verification as F
        from tkinter import simpledialog
        F.configure('33220A')
        F.messagebox = h.messagebox
        app = F.App(self.hn.root, '33220A', demo=True)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        with mock.patch.object(simpledialog, 'askfloat', lambda *a, **k: k.get('initialvalue'), create=True):
            self.assertTrue(self.hn.run_all())
        self.common(app)


if __name__ == '__main__':
    unittest.main()
