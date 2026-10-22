"""Tk wiring of 'Verified on hardware' under the tkinter stub: the Procedures list column / card / buttons (Calibration_Procedure_Manager), the two dialogs
(verified_ui), the running window's disabled 'Edit procedure' control (procmods_ui.LiveHook) and the header chip (ui_shell).

Only proves that the wiring runs and calls the model: it does NOT show what the windows look like (Tk windows have never been viewed here).
Run:  python -m unittest tests.test_verified_ui"""
import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
tk_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk_stub)
STUBBED = tk_stub.install()

import devmode  # noqa: E402
import procmods  # noqa: E402
import procmods_engine as pe  # noqa: E402
import procmods_ui_model as M  # noqa: E402
import verified as V  # noqa: E402


class Widget:
    """A button / label / pill stand-in that remembers what it was told."""

    def __init__(self):
        self.opts, self.text, self.kind, self.shown = {}, '', None, True

    def configure(self, **kw):
        self.opts.update(kw)

    config = configure

    def set(self, text, kind=None):
        self.text, self.kind = text, kind

    def get(self):
        return self.text

    def pack(self, *a, **k):
        self.shown = True

    def pack_forget(self):
        self.shown = False

    def bind(self, *a, **k):
        pass

    def __getitem__(self, k):
        return self.opts[k]

    def __setitem__(self, k, v):
        self.opts[k] = v


class Var:
    def __init__(self, v=''):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


@unittest.skipUnless(STUBBED, 'real tkinter present: these stub tests would need a display')
class LiveHookTests(unittest.TestCase):
    """The running window: the 'Edit procedure' control is shown disabled with the reason while the procedure is verified and locked."""

    def setUp(self):
        import procmods_ui
        self.ui = procmods_ui
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.db = self.t / 'lab_registry.sqlite3'
        self.dm = devmode.DevMode(self.t / 'devmode.json', iterations=1000)
        self.store = procmods.Store(self.db, devmode=self.dm)
        self.reg = V.Registry(self.db)
        self.entry = V.Entry('Fluke_117_Verification.py', 'Fluke 117 Performance Verification', '117', str(ROOT / 'Procedures' / 'Fluke_117_Verification.py'))
        self.lock = M.DevLock(self.dm, clock=lambda: 1000.0)
        self.calls = []
        calls, test = self.calls, self

        class Shell:
            root = Widget()

            def add_action(self, text, cmd, **kw):
                test.button = Widget()
                calls.append(('action', text))
                return test.button

            def set_modified(self, n):
                calls.append(('mod', n))

            def set_devmode(self, on):
                calls.append(('dev', on))

            def set_verified(self, text):
                calls.append(('verified', text))
        self.shell = Shell()

        class App(pe.ProcModsMixin):
            pass
        self.app = App()
        self.app.pm_init('handheld', '117', demo=True, store=self.store, devmode=self.dm)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unlocked_procedure_keeps_an_enabled_control_and_no_chip(self):
        hook = self.ui.attach_live(self.app, self.shell, self.lock)
        self.assertEqual(self.button.opts.get('state'), 'normal')
        self.assertIn(('verified', ''), self.calls)
        self.assertEqual(hook.locked_reason, '')

    def test_locked_procedure_disables_the_control_shows_the_chip_and_explains(self):
        self.reg.verify(self.entry, 'Mike', '2026-10-20', today=date(2026, 10, 22))
        hook = self.ui.attach_live(self.app, self.shell, self.lock)
        self.assertEqual(self.button.opts.get('state'), 'disabled')
        self.assertIn(('verified', 'VERIFIED ON HARDWARE - LOCKED'), self.calls)
        self.assertIn('verified on hardware', hook.locked_reason)
        self.assertIsNotNone(hook._tip, 'the reason is the control\'s tooltip')
        with mock.patch.object(self.ui.messagebox, 'showinfo') as info, mock.patch.object(self.ui, 'open_modify_window') as opened:
            self.assertIsNone(hook.open())
        info.assert_called_once()
        self.assertIn('Unlock for editing', info.call_args[0][1])
        opened.assert_not_called()

    def test_unlocking_elsewhere_reenables_it_on_the_next_refresh(self):
        self.reg.verify(self.entry, 'Mike', '2026-10-20', today=date(2026, 10, 22))
        hook = self.ui.attach_live(self.app, self.shell, self.lock)
        self.reg.unlock(self.entry.proc_key, 'Sam', 'looking at the settle times')
        hook.refresh()
        self.assertEqual(self.button.opts.get('state'), 'normal')
        self.assertEqual(self.calls[-1][0], 'verified')
        self.assertEqual(self.calls[-1][1], '')

    def test_a_shell_without_the_chip_method_still_works(self):
        self.reg.verify(self.entry, 'Mike', '2026-10-20', today=date(2026, 10, 22))
        del type(self.shell).set_verified
        hook = self.ui.attach_live(self.app, self.shell, self.lock)
        self.assertEqual(self.button.opts.get('state'), 'disabled')
        self.assertTrue(hook.locked_reason)

    def test_an_engine_that_cannot_tell_does_not_lock(self):
        class Bare:
            pm_state = None
        hook = self.ui.LiveHook.__new__(self.ui.LiveHook)
        hook.app = Bare()
        self.assertEqual(hook.verified_reason(), '')

    def test_open_modify_window_banner_carries_the_lock_text(self):
        """The editor window of a locked procedure is read-only and its banner says why (developer mode does not help)."""
        self.reg.verify(self.entry, 'Mike', '2026-10-20', today=date(2026, 10, 22))
        model = M.ProcModsModel(M.Context(title='Fluke 117', model='117', store=self.store), self.lock)
        self.assertIn('verified on hardware', model.read_only_reason)
        win = self.ui.ModifyWindow.__new__(self.ui.ModifyWindow)
        win.model, win.lock = model, self.lock
        win.btn_lock, win.chip_dev, win.chip_mod, win.banner, win.info = Widget(), Widget(), Widget(), Var(), Var()
        win.update_info = lambda: None
        win.update_buttons = lambda: None
        win.update_header()
        self.assertIn('Unlock for editing', win.banner.get())


@unittest.skipUnless(STUBBED, 'real tkinter present: these stub tests would need a display')
class ShellChip(unittest.TestCase):
    def test_set_verified_adds_updates_and_hides_the_chip(self):
        import ui_shell
        made = []

        class Pill(Widget):
            def __init__(self, parent, text='', kind='neutral'):
                super().__init__()
                self.text, self.kind = text, kind
                made.append(self)

            def winfo_manager(self):
                return 'pack' if self.shown else ''
        shell = ui_shell.Shell.__new__(ui_shell.Shell)
        shell.chip_frame = object()
        with mock.patch.object(ui_shell.ui, 'Pill', Pill):
            self.assertIsNone(shell.set_verified(''))
            chip = shell.set_verified('VERIFIED ON HARDWARE - LOCKED')
            self.assertEqual((chip.text, chip.kind, chip.shown), ('VERIFIED ON HARDWARE - LOCKED', 'good', True))
            shell.set_verified('')
            self.assertFalse(chip.shown)
            shell.set_verified('VERIFIED ON HARDWARE - LOCKED')
            self.assertTrue(chip.shown)
            self.assertEqual(len(made), 1)


class FakeTable:
    def __init__(self):
        self.rows, self.sel, self._empty = {}, [], mock.MagicMock()

    def selection(self):
        return tuple(self.sel)

    def delete(self, *items):
        for i in items:
            self.rows.pop(i, None)

    def get_children(self):
        return tuple(self.rows)

    def insert(self, parent, index, iid=None, values=(), tags=()):
        self.rows[iid] = dict(values=tuple(values), tags=tuple(tags))

    def exists(self, iid):
        return iid in self.rows

    def selection_set(self, iid):
        self.sel = [iid]

    def tag_configure(self, *a, **k):
        pass

    def bind(self, *a, **k):
        pass


@unittest.skipUnless(STUBBED, 'real tkinter present: these stub tests would need a display')
class IndexTests(unittest.TestCase):
    """The Procedures list of the Manager: column, tags, card, buttons and the handlers, with fake widgets and a throw-away registry."""

    @classmethod
    def setUpClass(cls):
        import Calibration_Procedure_Manager as CPM
        cls.CPM = CPM

    def setUp(self):
        CPM = self.CPM
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'registry.sqlite3'
        V._SEEDED.discard(str(self.db))
        mgr = self.mgr = object.__new__(CPM.Manager)
        mgr.root = Widget()
        mgr.search, mgr.category, mgr.status = Var(''), Var(CPM.ALL_CATEGORIES), Var('')
        mgr.category_box = Widget()
        mgr.table = FakeTable()
        mgr.verified = V.Registry(self.db, seed=True)
        for name in ('d_name', 'd_sub', 'd_desc', 'd_path', 'd_ver_text'):
            setattr(mgr, name, Var())
        for name in ('d_pill', 'd_ver', 'd_mod', 'btn_run', 'btn_demo', 'btn_changes', 'btn_verify', 'btn_lock'):
            setattr(mgr, name, Widget())
        mgr._mod_counts = lambda refresh=False: {}
        self.patches = [mock.patch.object(CPM, 'messagebox'), mock.patch.object(CPM, 'simpledialog'),
                        mock.patch.object(CPM.verified_ui, 'ask_mark'), mock.patch.object(CPM.verified_ui, 'ask_unlock'),
                        mock.patch.object(CPM, 'init_db', lambda: None)]
        self.box, self.sd, self.ask_mark, self.ask_unlock, _ = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        import sqlite3
        self.libdb = Path(self.tmp.name) / 'procs.sqlite3'
        con = sqlite3.connect(self.libdb)
        con.execute('CREATE TABLE procedures (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, manufacturer TEXT, model TEXT, category TEXT, '
                    'script_path TEXT, description TEXT DEFAULT "", enabled INTEGER DEFAULT 1)')
        rows = [('Tektronix TDS2000C / TDS1000C-EDU Performance Verification', 'Tektronix', 'TDS2000C/TDS1000C-EDU', 'Oscilloscope', 'Procedures/Tektronix_TDS2000C_Verification.py'),
                ('WaveSurfer WS4104HD Verification', 'Teledyne LeCroy', 'WS4104HD', 'Oscilloscope', 'Procedures/WaveSurfer_WS4104HD.py'),
                ('Fluke 117 Performance Verification', 'Fluke', '117', 'Digital Multimeter', 'Procedures/Fluke_117_Verification.py'),
                ('Fluke 116 Performance Verification', 'Fluke', '116', 'Digital Multimeter', 'Procedures/Fluke_116_Verification.py')]
        con.executemany('INSERT INTO procedures(name,manufacturer,model,category,script_path) VALUES(?,?,?,?,?)', rows)
        con.commit()
        con.close()
        p = mock.patch.object(CPM, 'DB', self.libdb)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(CPM.dsb_manager, 'user_rows', lambda *a, **k: [])
        p.start()
        self.addCleanup(p.stop)
        mgr.refresh()
        self.iid = {r['values'][0]: i for i, r in mgr.table.rows.items()}

    def tearDown(self):
        V._SEEDED.discard(str(self.db))
        self.tmp.cleanup()

    def cell(self, name):
        return self.mgr.table.rows[self.iid[name]]['values'][5]

    def select(self, name):
        self.mgr.table.sel = [self.iid[name]]
        self.mgr.refresh_details()

    # ---- the list
    def test_column_shows_the_three_seeded_as_verified_and_the_rest_as_not(self):
        self.assertEqual(self.cell('Tektronix TDS2000C / TDS1000C-EDU Performance Verification'), 'Verified 2026-10-22  [locked]')
        self.assertEqual(self.cell('WaveSurfer WS4104HD Verification'), 'Verified 2026-10-22  [locked]')
        self.assertEqual(self.cell('Fluke 117 Performance Verification'), 'Verified 2026-10-22  [locked]')
        self.assertEqual(self.cell('Fluke 116 Performance Verification'), 'Not verified')
        self.assertIn('verified', self.mgr.table.rows[self.iid['Fluke 117 Performance Verification']]['tags'])
        self.assertNotIn('verified', self.mgr.table.rows[self.iid['Fluke 116 Performance Verification']]['tags'])
        self.assertEqual(len(self.mgr.table.rows[self.iid['Fluke 117 Performance Verification']]['values']), 6)

    def test_card_for_a_locked_procedure(self):
        self.select('Fluke 117 Performance Verification')
        self.assertEqual(self.mgr.d_ver.kind, 'good')
        self.assertIn('LOCKED', self.mgr.d_ver.text)
        self.assertEqual((self.mgr.btn_verify.opts['state'], self.mgr.btn_lock.opts['state']), ('disabled', 'normal'))
        self.assertEqual(self.mgr.btn_lock.opts['text'], 'Unlock for editing...')

    def test_card_for_an_unverified_procedure(self):
        self.select('Fluke 116 Performance Verification')
        self.assertEqual(self.mgr.d_ver.text, 'NOT VERIFIED ON HARDWARE')
        self.assertEqual((self.mgr.btn_verify.opts['state'], self.mgr.btn_lock.opts['state']), ('normal', 'disabled'))
        self.assertEqual(self.mgr.btn_verify.opts['text'], 'Mark verified on hardware...')

    def test_nothing_selected_disables_both(self):
        self.mgr.table.sel = []
        self.mgr.refresh_details()
        self.assertEqual((self.mgr.btn_verify.opts['state'], self.mgr.btn_lock.opts['state']), ('disabled', 'disabled'))

    # ---- mark
    def test_mark_verified_records_locks_and_refreshes_the_list(self):
        self.select('Fluke 116 Performance Verification')
        self.ask_mark.return_value = dict(who='Mike', on_date='2026-10-21', note='clean run', hardware='Instrument: 116 SN 9')
        rec = self.mgr.mark_verified()
        self.assertEqual((rec.verified_by, rec.verified_on, rec.locked), ('Mike', '2026-10-21', True))
        self.iid = {r['values'][0]: i for i, r in self.mgr.table.rows.items()}
        self.assertEqual(self.cell('Fluke 116 Performance Verification'), 'Verified 2026-10-21  [locked]')
        self.assertIn('locked against edits', self.mgr.status.get())
        self.assertTrue(self.mgr.verified.lock_reason(model='116'))

    def test_mark_cancelled_changes_nothing(self):
        self.select('Fluke 116 Performance Verification')
        self.ask_mark.return_value = None
        self.assertIsNone(self.mgr.mark_verified())
        self.assertEqual(self.cell('Fluke 116 Performance Verification'), 'Not verified')

    def test_mark_refusal_is_shown_in_a_message_box(self):
        self.select('Fluke 116 Performance Verification')
        self.ask_mark.return_value = dict(who='Mike', on_date='2026-10-21', note='', hardware='')
        with mock.patch.object(V.Registry, 'verify', side_effect=V.VerifyError('nope')):
            self.assertIsNone(self.mgr.mark_verified())
        self.box.showerror.assert_called_once()

    # ---- unlock / lock again
    def test_unlock_needs_the_dialog_and_records_the_reason(self):
        self.select('Fluke 117 Performance Verification')
        self.ask_unlock.return_value = dict(who='Sam', reason='new calibrator model needs another settle time')
        rec = self.mgr.toggle_lock()
        self.assertFalse(rec.locked)
        self.assertEqual(self.mgr.verified.lock_reason(model='117'), '')
        self.iid = {r['values'][0]: i for i, r in self.mgr.table.rows.items()}
        self.assertEqual(self.cell('Fluke 117 Performance Verification'), 'Verified 2026-10-22  [UNLOCKED]')
        self.select('Fluke 117 Performance Verification')
        self.assertEqual(self.mgr.btn_lock.opts['text'], 'Lock again (nothing changed)')
        self.assertEqual(self.mgr.btn_lock.opts['state'], 'normal')
        self.assertEqual(self.mgr.btn_verify.opts['text'], 'Mark verified again...')

    def test_unlock_cancelled_stays_locked(self):
        self.select('Fluke 117 Performance Verification')
        self.ask_unlock.return_value = None
        self.assertIsNone(self.mgr.toggle_lock())
        self.assertTrue(self.mgr.verified.lock_reason(model='117'))

    def test_lock_again_when_nothing_changed(self):
        self.select('Fluke 117 Performance Verification')
        self.ask_unlock.return_value = dict(who='Sam', reason='just wanted to look at the commands')
        self.mgr.toggle_lock()
        self.select('Fluke 117 Performance Verification')
        self.sd.askstring.return_value = 'Sam'
        rec = self.mgr.toggle_lock()
        self.assertTrue(rec.locked)
        self.assertTrue(self.mgr.verified.lock_reason(model='117'))
        self.assertEqual([h['action'] for h in self.mgr.verified.history('Fluke_117_Verification.py')], ['seed', 'unlock', 'relock'])

    # ---- other index actions
    def test_remove_from_library_is_refused_for_a_locked_procedure(self):
        self.select('Fluke 117 Performance Verification')
        self.mgr.remove()
        self.box.showinfo.assert_called_once()
        self.assertIn('verified on hardware', self.box.showinfo.call_args[0][1])
        self.box.askyesno.assert_not_called()

    def test_procedure_changes_passes_the_key_so_the_editor_locks_exactly(self):
        self.select('Fluke 117 Performance Verification')
        with mock.patch.object(self.CPM.procmods_ui, 'open_manager_changes') as opened, mock.patch.object(self.CPM.procmods_ui, 'shared_lock') as lock, \
                mock.patch.object(self.CPM.procmods, 'Store'):
            lock.return_value.devmode = None
            self.mgr.procedure_changes()
        self.assertEqual(opened.call_args.kwargs['proc_key'], 'Fluke_117_Verification.py')
        self.assertEqual(opened.call_args.args[1], '117')

    def test_an_update_of_a_verified_script_shows_changed_since(self):
        """Replacing a file of a verified procedure (an updated zip) flags it in the list; the suite does not block the update."""
        base = Path(self.tmp.name) / 'install'
        for rel in V.FILES['Fluke_117_Verification.py']['code'] + V.FILES['Fluke_117_Verification.py']['spec']:
            f = base / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('{}' if rel.endswith('.json') else f'# {rel}\n', encoding='utf-8')
        self.mgr.verified = V.Registry(Path(self.tmp.name) / 'fresh.sqlite3', base=base, seed=True)
        self.mgr.refresh()
        self.iid = {r['values'][0]: i for i, r in self.mgr.table.rows.items()}
        self.assertEqual(self.cell('Fluke 117 Performance Verification'), 'Verified 2026-10-22  [locked]')
        (base / 'handheld_dmm.py').write_text('# the updated engine\n', encoding='utf-8')
        self.mgr.refresh()
        self.iid = {r['values'][0]: i for i, r in self.mgr.table.rows.items()}
        self.assertEqual(self.cell('Fluke 117 Performance Verification'), 'Changed since verification - needs hardware re-verification')
        self.assertNotIn('verified', self.mgr.table.rows[self.iid['Fluke 117 Performance Verification']]['tags'])
        self.select('Fluke 117 Performance Verification')
        self.assertEqual(self.mgr.d_ver.kind, 'warn')
        self.assertIn('handheld_dmm.py', self.mgr.d_ver_text.get())
        self.assertEqual(self.mgr.btn_verify.opts['text'], 'Mark verified on hardware...')
        self.assertEqual(self.mgr.btn_verify.opts['state'], 'normal')
        self.assertEqual(self.mgr.btn_lock.opts['state'], 'disabled')
        self.assertEqual(self.mgr.verified.lock_reason(model='117'), '', 'auto-unlocked: editable until it is verified again')
        self.assertEqual(self.mgr.d_ver.text, 'CHANGED SINCE VERIFICATION - NEEDS HARDWARE RE-VERIFICATION')


@unittest.skipUnless(STUBBED, 'real tkinter present: these stub tests would need a display')
class DialogTests(unittest.TestCase):
    """verified_ui under the stub: the Return key submits; a wrong entry is explained and keeps the dialog open."""

    def setUp(self):
        import verified_ui
        self.vui = verified_ui
        self.vars = []
        test = self

        def make_var(*a, value='', **k):
            v = Var(value)
            test.vars.append(v)
            return v
        self.patches = [mock.patch.object(verified_ui.tk, 'StringVar', make_var)]
        win = self.win = Widget()
        win.destroyed = False
        win.destroy = lambda: setattr(win, 'destroyed', True)
        win.bound = {}
        win.bind = lambda seq, fn, *a: win.bound.__setitem__(seq, fn)
        win.resizable = lambda *a: None
        self.patches += [mock.patch.object(verified_ui.ui, 'dialog', lambda *a, **k: win), mock.patch.object(verified_ui.ui, 'center_on', lambda *a: None),
                         mock.patch.object(verified_ui.ui, 'Settings', lambda name: mock.MagicMock(get=lambda k, d=None: ''))]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.entry = V.Entry('Fluke_117_Verification.py', 'Fluke 117 Performance Verification', '117', '')

    def run_dialog(self, fn, edits, presses=1):
        win, vars_ = self.win, self.vars

        class Parent:
            def wait_window(self_, w):
                for edit in edits:
                    edit(vars_)
                for _ in range(presses):
                    if not win.destroyed:
                        win.bound['<Return>'](None)
        return fn(Parent(), self.entry, V.Status('none'))

    def test_mark_dialog_returns_the_cleaned_form(self):
        today = date(2026, 10, 22)
        out = self.run_dialog(lambda p, e, s: self.vui.ask_mark(p, e, s, today=today),
                              [lambda v: (v[0].set('  Mike '), v[2].set('117 SN 5'), v[3].set('5522A'), v[4].set('ran clean'))])
        self.assertEqual(out, dict(who='Mike', on_date='2026-10-22', note='ran clean', hardware='Instrument: 117 SN 5; Calibrator: 5522A'))
        self.assertTrue(self.win.destroyed)

    def test_mark_dialog_explains_a_wrong_entry_and_stays_open(self):
        out = self.run_dialog(lambda p, e, s: self.vui.ask_mark(p, e, s, today=date(2026, 10, 22)), [lambda v: (v[0].set(''), v[1].set('2027-01-01'))])
        self.assertIsNone(out)
        self.assertFalse(self.win.destroyed)
        self.assertIn('name', self.vars[5].get())
        self.assertIn('future', self.vars[5].get())

    def test_unlock_dialog_requires_a_typed_reason(self):
        out = self.run_dialog(self.vui.ask_unlock, [lambda v: (v[0].set('Sam'), v[1].set('fix'))])
        self.assertIsNone(out)
        self.assertFalse(self.win.destroyed)
        self.assertIn('reason', self.vars[2].get())
        self.vars[1].set('new calibrator firmware needs a longer settle')
        self.win.bound['<Return>'](None)
        self.assertTrue(self.win.destroyed)

    def test_unlock_dialog_returns_name_and_reason(self):
        out = self.run_dialog(self.vui.ask_unlock, [lambda v: (v[0].set('Sam'), v[1].set('new calibrator firmware needs a longer settle'))])
        self.assertEqual(out, {'who': 'Sam', 'reason': 'new calibrator firmware needs a longer settle'})


if __name__ == '__main__':
    unittest.main()
