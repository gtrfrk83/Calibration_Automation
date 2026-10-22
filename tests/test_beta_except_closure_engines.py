"""A failed measurement reaches App._error with its message and clears the busy flag (regression for the `except ... as exc` closure bug).

The worker thread's `except` block used to schedule `lambda: self._error(exc)`; `exc` is deleted when the block ends, so the lambda raised
NameError on the main thread and the run was left busy with no message.  Each engine's real App runs on its simulated bench with
io.measure replaced by a function that raises; the main-thread callbacks are pumped by the live-editor harness.
Named to sort after test_beta (it installs tests/_tk_stub.py through the harness).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402

import drivers  # noqa: E402
import dacq_verification as D  # noqa: E402
import fgen_verification as F  # noqa: E402
import truevolt_verification as T  # noqa: E402
import Agilent_34401A as A  # noqa: E402
import Fluke_8846A_Verification as V  # noqa: E402
from drivers.simulated import make_dacq_bench, make_dmm_bench  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402

BOOM = 'simulated read-back mismatch 42'


class FailedMeasure:
    def setUp(self):
        self.h = H.EngineHarness().start(*self.MODULES)
        self.addCleanup(self.h.stop)
        p = mock.patch('time.sleep', side_effect=lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.build()
        st = self.app.pm_state
        st.store, st.devmode = self.h.env.store, self.h.env.dm
        self.standby_calls = []
        real_standby = getattr(self.app.io, 'standby', None)
        if real_standby is not None:
            def standby(*a, **k):
                self.standby_calls.append(1)
                return real_standby(*a, **k)
            self.app.io.standby = standby

        def measure(*a, **k):
            raise RuntimeError(BOOM)
        self.app.io.measure = measure

    def test_failed_measure_reaches_error(self):
        app = self.app
        app.execute(self.points)
        self.assertTrue(self.h.pump(30), 'the run must not be left busy')
        errors = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'showerror']
        self.assertEqual(len(errors), 1, self.h.dialogs)
        self.assertIn(BOOM, errors[0][3])
        self.assertFalse(app.busy)
        self.assertEqual(app.results if hasattr(app, 'results') else {}, {}, 'a failed point records nothing')


class TruevoltFail(FailedMeasure, unittest.TestCase):
    MODULES = (T,)

    def build(self):
        T.configure('34470A')
        app = self.app = T.App(self.h.root, '34470A', demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        _b, ft, dt = make_dmm_bench('34470A')
        app.io = T.IO('sim', 'sim', transports=(dt, ft), mods=app.pm_state)
        self.points = [p for p in T.POINTS if p['kind'] == 'DCV' and p['source'] == 'calibrator'][:2]

    def test_standby_attempted_after_failure(self):
        self.app.execute(self.points)
        self.h.pump(30)
        self.assertTrue(self.standby_calls, 'outputs go to standby after a failed point')


class DacqFail(FailedMeasure, unittest.TestCase):
    MODULES = (D,)

    def build(self):
        D.configure('34970A')
        app = self.app = D.App(self.h.root, '34970A', demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        _b, ft, dt = make_dacq_bench('34970A')
        app.io = D.IO('sim', 'sim', cal_model='Fluke 5560A', module='34901A', slot=2, transports=(dt, ft), mods=app.pm_state)
        self.points = [p for p in D.POINTS if p['kind'] == 'DCV' and p['source'] == 'calibrator'][:2]


class FgenFail(FailedMeasure, unittest.TestCase):
    MODULES = (F,)

    def build(self):
        F.configure('33220A')
        app = self.app = F.App(self.h.root, '33220A', demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        bench, t = make_fgen_bench('33220A')
        bench.connected = 'std'
        app.io = F.IO({}, transports=t, ask_number=lambda prompt, unit: 0.0, mods=app.pm_state)
        self.points = [p for p in F.POINTS if p['kind'] == 'ACAMP'][:2]


class A34401Fail(FailedMeasure, unittest.TestCase):
    MODULES = (A,)
    MOD = A
    MODEL = '34401A'

    def build(self):
        mod = self.MOD
        rp = mock.patch.object(mod.App, 'refresh_ports', lambda self_: None)
        rp.start()
        self.addCleanup(rp.stop)
        app = self.app = mod.App(self.h.root, demo=False)
        self.h.app = app
        app.asset.set('A-100')
        app.serial.set('S')
        _b, ft, dt = make_dmm_bench(self.MODEL)
        queue_ = [dt, ft]
        with mock.patch.object(drivers, 'open_visa', lambda *a, **k: queue_.pop(0)):
            app.io = mod.IO('1', '2', 9600, 'None', 8, mods=app.pm_state)
        self.points = [p for p in mod.POINTS if p['kind'] == 'DCV' and not p.get('zero_offset')][:2]


class F8846Fail(A34401Fail):
    MODULES = (V,)
    MOD = V
    MODEL = '8846A'


if __name__ == '__main__':
    unittest.main()
