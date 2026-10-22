"""Tk wiring of the per-point editor (procmods_point_ui, LiveHook.open) under tests/_tk_stub.py.

Proves only that the wiring runs and calls the model.  It does NOT show what the windows look like: the Tk windows have never been viewed."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
tk_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk_stub)
STUBBED = tk_stub.install()

from tests import point_editor_harness as PH  # noqa: E402


class FakeEvent:
    x, y, x_root, y_root = 5, 7, 100, 200


class FakeTree:
    def __init__(self, rows=('68', '69')):
        self.rows, self.sel, self.bound = list(rows), (), {}

    def bind(self, seq, fn, add=None):
        self.bound[seq] = fn

    def identify_row(self, y):
        return self.rows[0] if y < 100 else ''

    def selection_set(self, iid):
        self.sel = (iid,)

    def selection(self):
        return self.sel


class FakeMenu:
    last = None

    def __init__(self, *a, **k):
        self.items, self.popped = [], None
        FakeMenu.last = self

    def delete(self, *a):
        self.items = []

    def add_command(self, **kw):
        self.items.append(kw)

    def tk_popup(self, x, y):
        self.popped = (x, y)

    def grab_release(self):
        pass


class FakeTreeview:
    """Just enough of ttk.Treeview for the window's command list."""

    def __init__(self, *a, **k):
        self.items, self.sel = {}, ()

    def heading(self, *a, **k): pass
    def column(self, *a, **k): pass
    def tag_configure(self, *a, **k): pass
    def pack(self, *a, **k): pass
    def configure(self, *a, **k): pass
    def bind(self, *a, **k): pass
    def yview(self, *a): pass

    def delete(self, *iids):
        for i in iids:
            self.items.pop(i, None)
        self.sel = tuple(i for i in self.sel if i in self.items)

    def get_children(self, *a):
        return tuple(self.items)

    def insert(self, parent, where, iid=None, values=(), tags=()):
        self.items[iid] = (values, tags)

    def exists(self, iid):
        return iid in self.items

    def selection_set(self, iid):
        self.sel = (iid,)

    def selection(self):
        return self.sel


@unittest.skipUnless(STUBBED, 'real tkinter present: the stub test would need a display')
class Wiring(unittest.TestCase):
    def setUp(self):
        import procmods_point_ui as UIP
        self.UIP = UIP
        UIP._open.clear()
        self.b = PH.truevolt()
        self.addCleanup(self.b.stop)
        self.app, self.lock = self.b.app, self.b.env.lock
        self.app.asset.set('A-100')
        p = mock.patch.object(UIP.tk, 'Menu', FakeMenu, create=True)
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(UIP.ttk, 'Treeview', FakeTreeview, create=True)
        q.start()
        self.addCleanup(q.stop)
        self.info = mock.patch.object(UIP.messagebox, 'showinfo')
        self.shown = self.info.start()
        self.addCleanup(self.info.stop)

    def test_right_click_offers_edit_for_the_row_under_the_pointer(self):
        tree = FakeTree()
        self.UIP.attach_tree_menu(self.app, tree, lock=self.lock)
        for seq in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):
            self.assertIn(seq, tree.bound)
        self.assertEqual(tree.bound['<Button-3>'](FakeEvent), 'break')
        menu = FakeMenu.last
        self.assertEqual(tree.sel, ('68',), 'the row is selected')
        self.assertEqual([(i['label'], i['state']) for i in menu.items], [('Edit', 'normal')])
        self.assertEqual(menu.popped, (100, 200))

    def test_a_click_off_the_rows_does_nothing(self):
        tree = FakeTree()
        self.UIP.attach_tree_menu(self.app, tree, lock=self.lock)
        ev = FakeEvent()
        ev.y = 500
        self.assertIsNone(tree.bound['<Button-3>'](ev))
        self.assertIsNone(FakeMenu.last.popped if FakeMenu.last else None)

    def test_edit_is_disabled_with_the_reason_on_a_verified_locked_procedure(self):
        self.app.pm_state._store().lock_reason = lambda model, key='': 'This procedure is verified on hardware and locked.'
        tree = FakeTree()
        self.UIP.attach_tree_menu(self.app, tree, lock=self.lock)
        tree.bound['<Button-3>'](FakeEvent)
        items = FakeMenu.last.items
        self.assertEqual(items[0]['state'], 'disabled')
        self.assertIn('verified', items[1]['label'])

    def test_edit_is_disabled_while_that_point_is_being_measured(self):
        self.app.pm_point_busy = lambda pid: 'This point is being measured now.' if str(pid) == '68' else ''
        tree = FakeTree()
        self.UIP.attach_tree_menu(self.app, tree, lock=self.lock)
        tree.bound['<Button-3>'](FakeEvent)
        self.assertEqual(FakeMenu.last.items[0]['state'], 'disabled')

    def test_a_resolver_maps_rows_to_point_ids(self):
        tree = FakeTree(rows=('section:0',))
        self.UIP.attach_tree_menu(self.app, tree, resolver=lambda iid: 68, lock=self.lock)
        tree.selection_set('section:0')
        self.assertEqual(self.UIP.selected_point(self.app), 68)
        self.assertIsNone(self.UIP.selected_point(type('A', (), {})()))

    def test_no_selection_means_no_point(self):
        self.UIP.attach_tree_menu(self.app, FakeTree(), lock=self.lock)
        self.assertIsNone(self.UIP.selected_point(self.app))

    def test_open_point_window_builds_the_model_and_a_second_open_raises_the_first(self):
        made = []

        class W:
            def __init__(self, parent, app, model):
                made.append(model)

            def winfo_exists(self):
                return True

            def lift(self):
                made.append('lift')
        with mock.patch.object(self.UIP, 'PointWindow', W):
            w1 = self.UIP.open_point_window(self.app, 68, lock=self.lock)
            w2 = self.UIP.open_point_window(self.app, 68, lock=self.lock)
        self.assertIs(w1, w2)
        self.assertEqual(made[0].pid, 68)
        self.assertEqual(made.count('lift'), 1)

    def test_open_point_window_says_why_instead_of_opening_a_locked_point(self):
        self.app.pm_state._store().lock_reason = lambda model, key='': 'verified and locked'
        with mock.patch.object(self.UIP, 'PointWindow') as W:
            self.assertIsNone(self.UIP.open_point_window(self.app, 68, lock=self.lock))
        W.assert_not_called()
        self.assertIn('verified and locked', self.shown.call_args[0][1])

    def test_the_window_builds_refreshes_and_applies_under_the_stub(self):
        model = self.UIP.PM.PointEditModel(self.app, 68, self.lock, store=self.b.env.store)
        win = self.UIP.PointWindow(None, self.app, model)
        win.refresh()
        win.update_header()
        win.update_buttons()
        row = next(r for r in model.rows if r.key == 'conf.acv')
        model.stage_command(row.seq, 'CONF:VOLT:AC {range:.9g},DEF')
        win.reason.set('a reason')
        model.set_reason('a reason')
        win.apply()
        self.assertEqual(win.message.get(), '')
        win.cancel()
        with mock.patch.object(self.UIP.messagebox, 'askyesno', return_value=True):
            win.close()
        self.assertNotIn((id(self.app), '68'), self.UIP._open)

    def test_an_error_while_saving_is_shown_not_raised(self):
        model = self.UIP.PM.PointEditModel(self.app, 68, self.lock, store=self.b.env.store)
        win = self.UIP.PointWindow(None, self.app, model)
        row = next(r for r in model.rows if r.key == 'conf.acv')
        model.stage_command(row.seq, 'CONF:VOLT:AC {range:.9g}')
        model.set_reason('x')
        with mock.patch.object(model, 'apply', side_effect=self.UIP.pm.OverrideError(['no good'])):
            win.apply()
        self.assertTrue(win.message.get())


@unittest.skipUnless(STUBBED, 'real tkinter present: the stub test would need a display')
class LiveHookOpen(unittest.TestCase):
    def setUp(self):
        import procmods_point_ui as UIP
        import procmods_ui as UI
        self.UIP, self.UI = UIP, UI
        UIP._open.clear()
        self.b = PH.truevolt()
        self.addCleanup(self.b.stop)
        self.app = self.b.app
        self.calls = []
        calls = self.calls

        class Shell:
            root = None

            def add_action(self, text, cmd, **kw):
                calls.append(text)
                return mock.MagicMock()

            def set_modified(self, n): pass
            def set_devmode(self, on): pass
        self.hook = UI.attach_live(self.app, Shell(), self.b.env.lock)
        p = mock.patch.object(UI.messagebox, 'showinfo')
        self.shown = p.start()
        self.addCleanup(p.stop)

    def test_the_button_is_called_edit_point(self):
        self.assertEqual(self.calls, ['Edit point'])

    def test_with_nothing_selected_it_says_to_select_a_point(self):
        self.assertIsNone(self.hook.open())
        self.assertIn('Select a test point', self.shown.call_args[0][1])

    def test_with_a_selected_point_it_opens_that_points_window(self):
        tree = FakeTree()
        self.UIP.attach_tree_menu(self.app, tree, lock=self.b.env.lock)
        tree.selection_set('68')
        with mock.patch.object(self.UIP, 'open_point_window', return_value='WIN') as op:
            self.assertEqual(self.hook.open(), 'WIN')
        self.assertEqual(op.call_args[0][1], 68 if not isinstance(op.call_args[0][1], str) else '68')

    def test_a_verified_locked_procedure_refuses_with_the_reason(self):
        self.app.pm_state._store().lock_reason = lambda model, key='': 'verified and locked'
        self.assertIsNone(self.hook.open())
        self.assertIn('verified and locked', self.shown.call_args[0][1])


@unittest.skipUnless(STUBBED, 'real tkinter present: the stub test would need a display')
class WaveSurferBinding(unittest.TestCase):
    def test_every_section_list_is_bound_and_its_rows_resolve_to_section_points(self):
        import re
        import Procedures.WaveSurfer_WS4104HD as W
        src = Path(W.__file__).read_text(encoding='utf-8')
        binds = re.findall(r"self\.pm_bind_tree\(self\.(\w+_tree), lambda iid, t=self\.\w+_tree: '(\w+):%d' % t\.index\(iid\)\)", src)
        self.assertEqual(sorted(k for _t, k in binds), ['bandwidth', 'dcv', 'impedance', 'offset', 'timebase', 'trigger'])
        b = PH.wavesurfer()
        self.addCleanup(b.stop)
        app = b.app
        for kind in ('dcv', 'impedance', 'offset', 'bandwidth', 'timebase', 'trigger'):
            self.assertIsNotNone(app.pm_find_point('%s:0' % kind), kind)
        import procmods_point_ui as UIP

        class Tree(FakeTree):
            def index(self, iid):
                return int(iid)
        tree = Tree(rows=('0',))
        with mock.patch.object(UIP.tk, 'Menu', FakeMenu, create=True):
            UIP.attach_tree_menu(app, tree, resolver=lambda iid, t=tree: 'dcv:%d' % t.index(iid), lock=b.env.lock)
            tree.bound['<Button-3>'](FakeEvent)
        self.assertEqual(UIP.selected_point(app), 'dcv:0')
        self.assertEqual(FakeMenu.last.items[0]['state'], 'normal')


if __name__ == '__main__':
    unittest.main()
