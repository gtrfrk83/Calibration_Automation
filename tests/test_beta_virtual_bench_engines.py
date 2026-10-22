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
