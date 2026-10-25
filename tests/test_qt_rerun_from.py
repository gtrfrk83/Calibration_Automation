"""'Rerun From Selected' (action bar button next to 'Rerun Selected'): re-measures the selected test point AND every point after it, in table order, as one run through the
engine's own execute() (handheld 117 and 376, the bench DMMs, the generator / scope engines) or, for WaveSurfer (no multi-point run path: every point is a retest), one
Rerun Selected after the other.

  * the list handed to execute() is exactly [selected .. last shown], in order; the section filter narrows it to the points shown; points before it are never passed;
  * the single 'Rerun Selected' still hands over one point;
  * with nothing selected the same 'Select a test point first.' message appears and nothing runs;
  * the button is disabled while busy like 'Rerun Selected';
  * a real run on the simulated bench (fast demo) records exactly the points [i..end], in order, and leaves the earlier results untouched;
  * WaveSurfer: Rerun Selected is called once per measured point from the selection on, one at a time (each waits for the one before to finish), the chain ends when a
    point does not start or Stop is pressed.

Headless (QT_QPA_PLATFORM=offscreen), skipped when PySide6 is not importable.   Run (separate process):  <venv python> -m unittest tests.test_qt_rerun_from
"""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

try:
    import tkinter  # noqa: F401
    for _sub in ('messagebox', 'filedialog', 'simpledialog'):          # tests/dsb_run_harness.py expects them in sys.modules
        try:
            __import__('tkinter.' + _sub)
        except ImportError:
            pass
except ImportError:                                  # the CI sandbox has none
    import _tk_stub
    _tk_stub.install()

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMainWindow
    import qt_bench_harness as QB
    import qt_genscope_harness as QG
    import qt_handheld_harness as QHH
    import qt_ws_harness as HN
    import genscope_rows as G
    import handheld_dmm as hh
    import iflex_option
    import ui_port


def ids(points):
    return [str(p['id']) for p in points]


class Mixin:
    """The checks every point-list engine shares.  Subclasses give `points(app)` (the engine's whole list)."""

    def select(self, app, iid):
        app.tree.selection_set(str(iid))
        QApplication.processEvents()

    def click(self, app, button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QApplication.processEvents()

    def shown(self, app):
        return [p for p in self.points(app) if app._visible(p)]

    def sections(self, app):
        """(section_of(p), [section names]) as the engine's own filter reads them: the first accessor whose value narrows the shown list."""
        cands = [lambda p: p.get('section_title'), lambda p: p.get('section')]
        if hasattr(app, '_section'):
            cands.insert(0, app._section)
        mod = sys.modules[type(app).__module__]
        if hasattr(mod, 'SECTION_TITLE'):                                                   # MDO / TDS: the shown name is looked up from the section id
            cands.insert(0, lambda p: mod.SECTION_TITLE[p['section']])
        shown = self.shown(app)
        for of in cands:
            names = list(dict.fromkeys(of(p) for p in shown))
            if len(names) < 2 or None in names:
                continue
            app.show_section.set(names[1])
            narrowed = self.shown(app)
            app.show_section.set('All sections')
            if narrowed and len(narrowed) < len(shown) and all(of(p) == names[1] for p in narrowed):
                return of, names
        raise AssertionError('no section accessor matches the engine filter')

    def check_engine(self, app):
        with mock.patch.object(app, 'execute') as ex:
            shown = self.shown(app)
            self.assertGreater(len(shown), 6)
            i = len(shown) // 3
            self.select(app, shown[i]['id'])
            self.click(app, app.btn_rerun_from)
            self.assertEqual(ex.call_count, 1)
            self.assertEqual(ids(ex.call_args[0][0]), ids(shown[i:]))                         # exactly [i..end], in order
            self.assertTrue(set(ids(shown[:i])).isdisjoint(ids(ex.call_args[0][0])))        # the earlier points are never passed
            ex.reset_mock()
            self.click(app, app.btn_rerun)                                                    # the single rerun is unchanged: one point
            self.assertEqual([ids(c[0][0]) for c in ex.call_args_list], [[str(shown[i]['id'])]])
            ex.reset_mock()
            self.select(app, shown[-1]['id'])                                                 # the last point: just itself
            self.click(app, app.btn_rerun_from)
            self.assertEqual(ids(ex.call_args[0][0]), [str(shown[-1]['id'])])
            ex.reset_mock()
            of, secs = self.sections(app)                                                     # the section filter: the points shown, from the selection on
            app.show_section.set(secs[1])
            app.refresh()
            shown = self.shown(app)
            self.assertTrue(shown and all(of(p) == secs[1] for p in shown))
            j = len(shown) // 2
            self.select(app, shown[j]['id'])
            self.click(app, app.btn_rerun_from)
            self.assertEqual(ids(ex.call_args[0][0]), ids(shown[j:]))
            self.assertTrue(all(of(p) == secs[1] for p in ex.call_args[0][0]))
            ex.reset_mock()
            app.tree.selection_set(())                                                        # nothing selected: Rerun Selected's message, nothing runs
            QApplication.processEvents()
            with mock.patch.object(ui_port.ui, 'message') as msg:
                self.click(app, app.btn_rerun_from)
                self.click(app, app.btn_rerun)
            self.assertEqual(msg.call_args_list, [mock.call('info', 'Selection', 'Select a test point first.')] * 2)
            ex.assert_not_called()

    def check_state(self, app):
        self.assertIn(app.btn_rerun_from.text(), ('Rerun From Selected', 'From here'))     # the compact bar shows the short label
        for busy in (True, False, True):
            app.busy = busy
            QApplication.processEvents()
            self.assertEqual(app.btn_rerun_from.isEnabled(), app.btn_rerun.isEnabled(), busy)
            self.assertEqual(app.btn_rerun_from.isEnabled(), not busy)
        app.busy = False
        QApplication.processEvents()


# ====================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Handheld(Mixin, unittest.TestCase):
    def setUp(self):
        self.hn = QHH.QtHarness(None).start()

    def tearDown(self):
        self.hn.stop()

    def points(self, app):
        return app.points

    def app(self, model, spec, engine):
        a = engine.App(self.hn.root, model, demo=True, spec=hh.load_spec(spec), fast_demo=False)
        self.hn.app = a
        return a

    def test_117(self):
        a = self.app('117', 'fluke_110_series_pv.json', hh)
        self.check_engine(a)
        self.check_state(a)

    def test_376(self):
        a = self.app('376', 'fluke_376_pv.json', iflex_option)
        self.check_engine(a)
        self.check_state(a)

    def test_the_run_queue_is_forced_like_rerun_selected(self):
        a = self.app('117', 'fluke_110_series_pv.json', hh)
        seen = []
        with mock.patch.object(a, 'execute', side_effect=lambda pts: seen.append(a.__dict__.get('_queue_force'))):
            self.select(a, a.points[2]['id'])
            self.click(a, a.btn_rerun_from)
            self.click(a, a.btn_rerun)
        self.assertEqual(seen, [True, True])

    def test_nothing_before_the_selection_is_passed_on(self):
        a = self.app('117', 'fluke_110_series_pv.json', hh)
        seen = []
        with mock.patch.object(a, 'execute', side_effect=lambda pts: seen.append(ids(pts))):
            self.select(a, a.points[4]['id'])
            self.click(a, a.btn_rerun_from)
        self.assertEqual(seen, [ids(a.points[4:])])
        self.assertEqual(a.results, {})


# ====================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class BenchDmm(Mixin, unittest.TestCase):
    def setUp(self):
        self.hn = QB.QtHarness().start()

    def tearDown(self):
        self.hn.stop()

    def points(self, app):
        return sys.modules[type(app).__module__].POINTS

    def make(self, key='truevolt_34461A'):
        import qt_bench_dump as D
        app = dict(D.engines())[key](self.hn.root, True)
        app.asset.set('A-1'); app.serial.set('S-1')
        self.hn.app = app
        QB.show(self.hn.root)
        return app

    def test_truevolt_and_the_buttons(self):
        a = self.make()
        self.check_engine(a)
        self.check_state(a)

    def test_the_other_bench_engines(self):
        for key in ('dacq_34972A', 'k2000', 'f8808a', 'a34410a_34410A', 'a34401a', 'f8846a'):
            with self.subTest(key):
                self.hn.root.close()
                self.hn.root = QMainWindow()
                a = self.make(key)
                self.check_engine(a)
                self.check_state(a)

    def test_a_real_run_records_exactly_the_points_from_the_selection(self):
        a = self.make()
        a._fast_demo = True                                                                 # the engine's own demo run (_record per point, no instrument)
        shown = self.shown(a)
        self.assertGreater(len(shown), 10)
        i = len(shown) - 6
        with mock.patch.object(a, '_record', wraps=a._record) as rec:
            self.select(a, shown[i]['id'])
            self.click(a, a.btn_rerun_from)
            self.hn.pump(60)
        self.assertEqual([str(c[0][0]['id']) for c in rec.call_args_list], ids(shown[i:]))
        self.assertEqual(sorted(a.results, key=int), sorted(ids(shown[i:]), key=int))      # nothing before the selection was measured
        before = copy.deepcopy({k: v for k, v in a.results.items() if k in ids(shown[i:i + 3])})
        with mock.patch.object(a, '_record', wraps=a._record) as rec:
            self.select(a, shown[i + 3]['id'])
            self.click(a, a.btn_rerun_from)
            self.hn.pump(60)
        self.assertEqual([str(c[0][0]['id']) for c in rec.call_args_list], ids(shown[i + 3:]))
        self.assertEqual({k: a.results[k] for k in before}, before)                        # the points before the new selection are as they were


# ====================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Genscope(Mixin, unittest.TestCase):
    def setUp(self):
        self.hn = QG.QtHarness().start()

    def tearDown(self):
        self.hn.stop()

    def points(self, app):
        return sys.modules[type(app).__module__].POINTS

    def test_fgen_mdo_tds(self):
        for key in ('fgen_33220A', 'mdo4000c', 'tds2000c_2024C'):
            with self.subTest(key):
                self.hn.root.close()
                self.hn.root = QMainWindow()
                a = G.build(key, self.hn.root)
                self.hn.app = a
                self.check_engine(a)
                self.check_state(a)


# ====================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class WaveSurfer(unittest.TestCase):
    def setUp(self):
        self.h = HN.Harness()
        self.a = a = self.h.app
        a.load_demo_data()
        a.refresh_unified(force=True)
        self.busy = False
        self.calls = []

        def fake_rerun():
            self.calls.append(a.utree.selection()[0])
            self.busy = True                                                                # the retest started: it runs until the test says it is over
        self.p = [mock.patch.object(a, 'rerun_selected', fake_rerun), mock.patch.object(a, '_batch_busy', lambda: self.busy),
                  mock.patch.object(a, '_dialog_open', lambda: False)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.h.stop()

    def finish(self):
        """The running retest ends; the next periodic tick starts the next one."""
        self.busy = False
        self.a._unified_tick()

    def keys(self):
        return list(self.a.utree.get_children())

    def test_button_text_and_state(self):
        a = self.a
        self.assertIn(a.btn_rerun_from.text(), ('Rerun From Selected', 'From here'))
        self.busy = True
        a._unified_tick()
        self.assertFalse(a.btn_rerun_from.isEnabled() or a.btn_rerun.isEnabled())
        self.busy = False
        a._unified_tick()
        self.assertTrue(a.btn_rerun_from.isEnabled() and a.btn_rerun.isEnabled())

    def test_every_point_from_the_selection_one_after_the_other(self):
        a = self.a
        a.show_function.set('DC voltage')
        a.refresh_unified(force=True)
        keys = self.keys()
        self.assertEqual(len(keys), 80)
        a.utree.selection_set(keys[75])
        a.rerun_from_selected()
        self.assertEqual(self.calls, [keys[75]])                                            # the selected one first, through Rerun Selected
        a._unified_tick()
        self.assertEqual(self.calls, [keys[75]])                                            # still busy: the next one waits
        for k in keys[76:]:
            self.finish()
            self.assertEqual(self.calls[-1], k)
        self.finish()
        self.assertEqual(self.calls, keys[75:])                                             # exactly [i..end], earlier points never touched
        self.assertEqual(list(a._from_queue), [])

    def test_the_section_filter_limits_the_points(self):
        a = self.a
        a.show_function.set('Input impedance')
        a.refresh_unified(force=True)
        keys = self.keys()
        self.assertEqual(len(keys), 28)
        a.utree.selection_set(keys[25])
        a.rerun_from_selected()
        for _ in range(5):
            self.finish()
        self.assertEqual(self.calls, keys[25:])
        self.assertTrue(all(k.startswith('impedance:') for k in self.calls))

    def test_all_functions_run_in_the_order_of_the_table(self):
        a = self.a
        keys = self.keys()
        i = len(keys) - 4
        a.utree.selection_set(keys[i])
        a.rerun_from_selected()
        for _ in range(6):
            self.finish()
        self.assertEqual(self.calls, keys[i:])

    def test_unmeasured_points_are_left_alone(self):
        a = self.a
        a.dc_rows = a.dc_rows[:78]                                                          # two DCV points not measured
        a.show_function.set('DC voltage')
        a.refresh_unified(force=True)
        keys = self.keys()
        a.utree.selection_set(keys[76])
        a.rerun_from_selected()
        for _ in range(4):
            self.finish()
        self.assertEqual(self.calls, keys[76:78])                                           # the measured ones from the selection only

    def test_the_chain_ends_when_a_point_does_not_start_or_stop_is_pressed(self):
        a = self.a
        a.show_function.set('DC voltage')
        a.refresh_unified(force=True)
        keys = self.keys()
        a.utree.selection_set(keys[70])
        a.rerun_from_selected()
        self.finish()
        self.assertEqual(self.calls, keys[70:72])
        a.stop_all()                                                                        # Stop
        self.finish()
        self.finish()
        self.assertEqual(self.calls, keys[70:72])
        self.calls.clear()                                                                  # a point that does not start (cancelled at its prompt): the rest is dropped
        self.busy = False
        a.utree.selection_set(keys[60])
        with mock.patch.object(a, 'rerun_selected', lambda: self.calls.append(a.utree.selection()[0])):
            a.rerun_from_selected()
        self.assertEqual(self.calls, [keys[60]])
        self.assertEqual(list(a._from_queue), [])

    def test_no_selection(self):
        a = self.a
        a.utree.selection_set(())
        with mock.patch.object(ui_port.ui, 'message') as msg:
            a.rerun_from_selected()
        self.assertEqual(self.calls, [])
        self.assertEqual(msg.call_args[0][:2], ('info', 'Select a result'))


if __name__ == '__main__':
    unittest.main()
