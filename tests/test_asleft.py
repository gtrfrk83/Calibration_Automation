"""As Found / As Left toggle, 'Run Shown Section' and the wrapping toolbars, tested in real windows (demo mode, no instruments).

Run:  python -m unittest tests.test_asleft      (from the repository folder; needs tkinter and a display -
                                                 on a machine without a screen:  xvfb-run -a python -m unittest tests.test_asleft)
The tests are skipped when tkinter or a display is not available.  Reports and progress files are written to a temporary folder.
"""
import contextlib, importlib, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
try:
    import tkinter as tk
    from tkinter import ttk
    _probe = tk.Tk(); _probe.destroy()
    HAVE_TK = True
except Exception:                                  # no tkinter, or no display
    HAVE_TK = False

TMP = Path(tempfile.mkdtemp())


def pump(root, until, seconds=60):
    end = time.time() + seconds
    while not until() and time.time() < end:
        root.update(); time.sleep(0.003)
    root.update()


class Harness:
    """Opens one procedure window and answers its dialogs."""

    def __init__(self, module, factory):
        self.mod = importlib.import_module(module)
        self.root = tk.Tk()
        self.app = factory(self.mod, self.root)
        self.dialogs = []                                       # (kind, title) of every message box that was shown
        self.answer = True
        for name in ('showinfo', 'showwarning', 'showerror'):
            setattr(self.mod.messagebox, name, lambda title='', msg='', _n=name, **k: self.dialogs.append((_n, title, msg)))
        self.mod.messagebox.askyesno = lambda title='', msg='', **k: (self.dialogs.append(('askyesno', title, msg)), self.answer)[1]
        self.root.update()

    def close(self):
        with contextlib.suppress(Exception):
            self.root.destroy()


def load_pdf_text(path):
    return subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout


@unittest.skipUnless(HAVE_TK, 'tkinter or a display is not available')
class TruevoltAsLeft(unittest.TestCase):
    def setUp(self):
        self.h = Harness('truevolt_verification', lambda m, r: m.App(r, '34461A', demo=True))
        self.app, self.root, self.m = self.h.app, self.h.root, self.h.mod
        self.app.asset.set('T-1'); self.app.serial.set('S1')
        self.cp = TMP / (self.id().split('.')[-1] + '_checkpoint.json')          # progress files go to the temp folder
        self.app._checkpoint_path = lambda: self.cp

    def tearDown(self):
        self.h.close()

    def run_found(self):
        self.app.run_all(); pump(self.root, lambda: not self.app.busy)

    def test_found_then_left_section(self):
        app = self.app
        self.run_found()
        n = len(app.active_points())
        self.assertEqual(len(app.found), n)
        self.assertEqual(len(app.left), 0)
        # a failing As Found reading in one section
        p5 = self.m.POINTS[4]
        app.found['5'] = dict(reading=p5['nominal'] + 10 * p5['error'] + 1e-9, result='FAIL', synthetic=True)
        app.set_data_mode('left')
        self.assertTrue(app.is_left)
        self.assertEqual(app.results, {})                            # nothing collected As Left yet
        sec = p5['section_title']
        app.show_section.set(sec); app._visible  # noqa: B018
        app.run_section(); pump(self.root, lambda: not app.busy)
        in_sec = [p for p in app.active_points() if p['section_title'] == sec]
        self.assertEqual(sorted(app.left, key=int), sorted((str(p['id']) for p in in_sec), key=int))
        self.assertEqual(len(app.found), n)                          # As Found untouched
        self.assertEqual(app.found['5']['result'], 'FAIL')           # including the failing one
        self.assertEqual(app.left['5']['result'], 'PASS')
        self.assertTrue(all(r['data'] == 'As Left' for r in app.left.values()))

    def test_run_shown_section_needs_a_filter(self):
        self.app.run_section()
        self.assertEqual(self.h.dialogs[-1][0], 'showinfo')
        self.assertFalse(self.app.found)

    def test_as_found_failed_filter_runs_only_failed(self):
        app = self.app
        self.run_found()
        for k in ('3', '7'):                                          # two failures
            p = self.m.POINTS[int(k) - 1]
            app.found[k] = dict(reading=p['nominal'] + 5 * p['error'], result='FAIL', synthetic=True)
        app.set_data_mode('left')
        app.show_status.set('As Found failed'); app.refresh()
        self.assertEqual(sorted(app.tree.get_children(), key=int), ['3', '7'])
        app.run_section(); pump(self.root, lambda: not app.busy)
        self.assertEqual(sorted(app.left, key=int), ['3', '7'])

    def test_report_as_left_column(self):
        app = self.app
        self.run_found()
        p = self.m.POINTS[2]
        app.found['3'] = dict(reading=p['nominal'] + 5 * p['error'], result='FAIL', synthetic=True)
        app.set_data_mode('left')
        app._record(p, p['nominal'], True)                           # adjusted: now inside the limits
        q = self.m.POINTS[3]
        app._record(q, q['nominal'] + 9 * q['error'], True)          # still outside
        rows = app.certificate_rows()
        by = {r['Description']: r for r in rows}
        same = [r for r in rows if r['As Left'] == 'Same']
        self.assertEqual(len(same), len(rows) - 2)
        left = [r for r in rows if r['As Left'] != 'Same']
        self.assertEqual(sorted(bool(r.get('As Left OOT')) for r in left), [False, True])
        self.assertEqual(sum(1 for r in rows if r['OOT']), 1)         # the As Found OOT column is only about As Found
        path = TMP / 'tv.pdf'
        from tkinter import filedialog
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda *a, **k: {}), \
                mock.patch.object(self.m.filedialog, 'asksaveasfilename', lambda **k: str(path)):
            app.export_pdf()
        text = load_pdf_text(path)
        self.assertIn('AS LEFT: OUT OF TOLERANCE', text)
        self.assertIn('1 of 2', text)
        self.assertIn('DEMO DATA', text)

    def test_report_without_adjustment_is_unchanged(self):
        self.run_found()
        rows = self.app.certificate_rows()
        self.assertTrue(rows and all(r['As Left'] == 'Same' for r in rows))
        path = TMP / 'tv_same.pdf'
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda *a, **k: {}), \
                mock.patch.object(self.m.filedialog, 'asksaveasfilename', lambda **k: str(path)):
            self.app.export_pdf()
        self.assertNotIn('AS LEFT', load_pdf_text(path))

    def test_save_and_load_keep_both_sets(self):
        app = self.app
        self.run_found()
        app.set_data_mode('left')
        p = self.m.POINTS[0]
        app._record(p, p['nominal'], True)
        app.save()
        saved = json.loads(self.cp.read_text())
        self.assertEqual(set(saved), {'asset', 'serial', 'demo', 'period', 'results', 'left_results'})
        self.assertEqual(list(saved['left_results']), ['1'])
        app2 = self.m.App(tk.Tk(), '34461A', demo=True)
        try:
            with mock.patch.object(self.m.filedialog, 'askopenfilename', lambda **k: str(self.cp)):
                app2.load()
            self.assertEqual(len(app2.found), len(app.found)); self.assertEqual(list(app2.left), ['1'])
            self.assertFalse(app2.is_left)                            # a loaded file starts on As Found
        finally:
            app2.root.destroy()

    def test_old_progress_file_without_left_loads(self):
        data = dict(asset='X', serial='', demo=True, period='1 year', results={'1': dict(reading=0.0, result='PASS', synthetic=True)})
        path = TMP / 'old.json'; path.write_text(json.dumps(data))
        with mock.patch.object(self.m.filedialog, 'askopenfilename', lambda **k: str(path)):
            self.app.load()
        self.assertEqual(list(self.app.found), ['1']); self.assertEqual(self.app.left, {})

    def test_remeasuring_as_found_after_adjustment_asks_first(self):
        app = self.app
        self.run_found()
        app.set_data_mode('left')
        p = self.m.POINTS[0]
        app._record(p, p['nominal'], True)
        app.set_data_mode('found')
        before = dict(app.found['1'])
        self.h.answer = False                                         # the technician says no
        app.execute([p]); self.root.update()
        self.assertEqual(self.h.dialogs[-1][0], 'askyesno')
        self.assertIn('Replace the As Found', self.h.dialogs[-1][1])
        self.assertEqual(app.found['1'], before); self.assertFalse(app.busy)
        self.h.answer = True
        app.execute([p]); pump(self.root, lambda: not app.busy)
        self.assertNotEqual(app.found['1'].get('timestamp'), None)

    def test_toggle_is_locked_while_running(self):
        app = self.app
        app.busy = True
        app.set_data_mode('left')
        self.assertFalse(app.is_left)
        self.assertTrue(all(str(b['state']) == 'disabled' for b in app.mode_buttons))
        app.busy = False
        app.set_data_mode('left'); self.assertTrue(app.is_left)

    def test_table_heading_follows_mode(self):
        self.app.set_data_mode('left')
        self.assertEqual(self.app.tree.heading('left')['text'], '● As Left')          # the dot marks the column being collected
        self.assertEqual(self.app.tree.heading('found')['text'], 'As Found')
        self.app.set_data_mode('found')
        self.assertEqual(self.app.tree.heading('found')['text'], '● As Found')
        self.assertEqual(self.app.tree.heading('left')['text'], 'As Left')


def all_buttons(widget):
    for w in widget.winfo_children():
        if isinstance(w, ttk.Button):
            yield w
        yield from all_buttons(w)


@unittest.skipUnless(HAVE_TK, 'tkinter or a display is not available')
class ToolbarWrap(unittest.TestCase):
    """At every window width each button shows its full text (never squeezed), and nothing is cut off at the right edge."""

    def check(self, module, factory, widths=(900, 1000, 1400)):
        h = Harness(module, factory)
        try:
            for w in widths:
                h.root.geometry(f'{w}x760+0+0'); h.root.update(); h.root.update()
                for b in all_buttons(h.root):
                    if not b.winfo_ismapped():
                        continue
                    self.assertGreaterEqual(b.winfo_width(), b.winfo_reqwidth() - 2, f'{module} {w}px: "{b.cget("text")}" is squeezed')
                    right = b.winfo_rootx() + b.winfo_width() - h.root.winfo_rootx()
                    self.assertLessEqual(right, h.root.winfo_width() + 2, f'{module} {w}px: "{b.cget("text")}" runs past the window edge')
        finally:
            h.close()

    def test_truevolt(self):
        self.check('truevolt_verification', lambda m, r: m.App(r, '34461A', demo=True))

    def test_dacq(self):
        self.check('dacq_verification', lambda m, r: m.App(r, '34970A', demo=True))

    def test_fgen(self):
        self.check('fgen_verification', lambda m, r: m.App(r, '33220A', demo=True))

    def test_mdo(self):
        self.check('mdo4000c_verification', lambda m, r: m.App(r, demo=True))

    def test_handheld(self):
        self.check('handheld_dmm', lambda m, r: m.App(r, '117', demo=True), widths=(1000, 1100, 1400))

    def test_34401a(self):
        self.check('Procedures.Agilent_34401A', lambda m, r: m.App(r, demo=True))

    def test_8846a(self):
        self.check('Procedures.Fluke_8846A_Verification', lambda m, r: m.App(r, demo=True))


@unittest.skipUnless(HAVE_TK, 'tkinter or a display is not available')
class OlderProcedures(unittest.TestCase):
    """Fluke 8846A and Agilent 34401A: same As Found / As Left behaviour, demo mode."""
    MODULES = ['Procedures.Fluke_8846A_Verification', 'Procedures.Agilent_34401A']

    def open(self, name):
        h = Harness(name, lambda m, r: m.App(r, demo=True))
        self.addCleanup(h.close)
        h.app.asset.set('T-1')
        h.app._checkpoint_path = lambda: TMP / 'older_checkpoint.json'
        return h

    def test_found_then_left_section(self):
        for name in self.MODULES:
            with self.subTest(module=name):
                h = self.open(name); app = h.app
                app.run_all(); pump(h.root, lambda: not app.busy)
                n = len(app.found)
                self.assertGreater(n, 0)
                app.set_data_mode('left')
                self.assertEqual(app.results, {})
                sec = next(p for p in h.mod.POINTS)['kind']
                values = [w for w in app.root.winfo_children()]  # noqa: F841
                combos = [w for w in _walk(app.root) if isinstance(w, ttk.Combobox) and w.cget('textvariable') == str(app.show_section)]
                if combos:
                    app.show_section.set(combos[0]['values'][1])
                else:                                                   # redesigned window: the sidebar picks the section
                    app.shell.choose_section(app.shell.sections[0][0])
                    self.assertEqual(app.show_section.get(), app.shell.sections[0][0])
                app.run_section(); pump(h.root, lambda: not app.busy)
                self.assertTrue(app.left)
                self.assertLess(len(app.left), n)
                self.assertEqual(len(app.found), n)
                self.assertTrue(all(r['data'] == 'As Left' for r in app.left.values()))

    def test_run_section_needs_a_filter(self):
        for name in self.MODULES:
            with self.subTest(module=name):
                h = self.open(name)
                h.app.run_section()
                self.assertEqual(h.dialogs[-1][0], 'showinfo')
                self.assertFalse(h.app.found)


@unittest.skipUnless(HAVE_TK, 'tkinter or a display is not available')
class WaveSurferAsLeft(unittest.TestCase):
    """WaveSurfer keeps seven result lists; the toggle swaps them and the report merges both sets (demo data, memory only)."""

    def setUp(self):
        self._argv = list(sys.argv)
        sys.argv.append('--demo')
        self.addCleanup(lambda: sys.argv.__setitem__(slice(None), self._argv))
        self.mod = importlib.import_module('Procedures.WaveSurfer_WS4104HD')
        with mock.patch.object(self.mod.messagebox, 'showinfo', lambda *a, **k: None), \
                mock.patch.object(self.mod.messagebox, 'showwarning', lambda *a, **k: None):
            self.root = tk.Tk()
            self.app = self.mod.RMSNoiseApp(self.root)
        self.root.update()

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.root.destroy()

    def test_toggle_swaps_sets_and_keeps_found(self):
        app = self.app
        n = len(app.dc_rows)
        self.assertGreater(n, 0)
        app.set_data_mode('left')
        self.assertTrue(app.is_left)
        self.assertEqual(app.dc_rows, [])
        self.assertEqual(len(app._stored_rows('found', 'dcv')), n)
        self.assertEqual(app.utree.heading('left')['text'], '● As Left')
        import copy
        app.dc_rows.append(copy.deepcopy(app._stored_rows('found', 'dcv')[0]))
        rows = app.certificate_rows('dcv')
        self.assertEqual(len(rows), n)
        self.assertEqual(rows[0]['As Left'], rows[0]['As Found'])
        self.assertEqual(rows[1]['As Left'], '')                  # the report prints 'Same' for these
        app.set_data_mode('found')
        self.assertEqual(len(app.dc_rows), n)
        self.assertEqual(len(app._stored_rows('left', 'dcv')), 1)

    def test_checkpoint_files_are_separate(self):
        app = self.app
        found_path = app.dc_checkpoint
        app.set_data_mode('left')
        self.assertNotEqual(app.dc_checkpoint, found_path)
        self.assertIn('_AsLeft', app.dc_checkpoint.name)
        app.set_data_mode('found')
        self.assertEqual(app.dc_checkpoint, found_path)

    def test_buttons_not_squeezed(self):
        for w in (900, 1000, 1400):
            self.root.geometry(f'{w}x760+0+0'); self.root.update(); self.root.update()
            for b in all_buttons(self.root):
                if b.winfo_ismapped():
                    self.assertGreaterEqual(b.winfo_width(), b.winfo_reqwidth() - 2, f'{w}px: "{b.cget("text")}" is squeezed')
                    self.assertLessEqual(b.winfo_rootx() + b.winfo_width() - self.root.winfo_rootx(), self.root.winfo_width() + 2,
                                         f'{w}px: "{b.cget("text")}" runs past the window edge')

    def test_run_section_needs_a_function(self):
        shown = []
        with mock.patch.object(self.mod.messagebox, 'showinfo', lambda *a, **k: shown.append(a)):
            self.app.run_section()
        self.assertEqual(len(shown), 1)

    def test_as_found_failed_filter(self):
        app = self.app
        app.show_status.set('As Found failed')
        app.refresh_unified(force=True)
        failed = [e for e in app.entries() if e['result'] == 'FAIL']
        self.assertEqual(len(app.utree.get_children()), len(failed))


@unittest.skipUnless(HAVE_TK, 'tkinter or a display is not available')
class EveryEngine(unittest.TestCase):
    """Demo run end to end in the DAQ, function generator, MDO4000C and handheld engines: As Found, then an As Left section, then the PDF."""
    CASES = [('dacq_verification', lambda m, r: m.App(r, '34970A', demo=True)),
             ('fgen_verification', lambda m, r: m.App(r, '33220A', demo=True)),
             ('mdo4000c_verification', lambda m, r: m.App(r, demo=True)),
             ('handheld_dmm', lambda m, r: m.App(r, '117', demo=True))]

    def test_found_left_report(self):
        for name, factory in self.CASES:
            with self.subTest(module=name):
                h = Harness(name, factory)
                self.addCleanup(h.close)
                app = h.app
                app.asset.set('T-1')
                app._checkpoint_path = lambda n=name: TMP / (n + '_ckpt.json')
                app.run_all(); pump(h.root, lambda: not app.busy, 120)
                n = len(app.found)
                self.assertGreater(n, 0)
                app.set_data_mode('left')
                combos = [w for w in _walk(app.root) if isinstance(w, ttk.Combobox) and w.cget('textvariable') == str(app.show_section)]
                if combos:
                    app.show_section.set(combos[0]['values'][1])
                else:                                                   # redesigned window: the sidebar picks the section
                    app.shell.choose_section(app.shell.sections[0][0])
                    self.assertEqual(app.show_section.get(), app.shell.sections[0][0])
                app.run_section(); pump(h.root, lambda: not app.busy, 120)
                self.assertTrue(app.left, name)
                self.assertEqual(len(app.found), n)
                rows = app.certificate_rows()
                self.assertEqual(len(rows), n)
                self.assertTrue(any(r['As Left'] not in ('Same', '') for r in rows))
                self.assertTrue(any(r['As Left'] == 'Same' for r in rows))


def _walk(widget):
    for w in widget.winfo_children():
        yield w
        yield from _walk(w)


if __name__ == '__main__':
    unittest.main()
