"""Tk wiring of 'Import procedure package...' under the tkinter stub: the Manager button's flow (pick, preview, confirm, install, refresh) and the library
folder setting. It proves the wiring calls the model in the right order; how the windows LOOK is checked on a real Tk (tests/real_tk_checks.py).
Run:  python -m unittest tests.test_packages_ui"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
tk_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk_stub)
tk_stub.install()

import packages as P  # noqa: E402
import procscan  # noqa: E402
import verified as V  # noqa: E402
from tests._pkg_helpers import make_tree  # noqa: E402

K2 = 'Keithley_2000_Verification'


class Var:
    def __init__(self, v=''):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class ImportFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        old = os.environ.get('CALSUITE_DATA')
        os.environ['CALSUITE_DATA'] = str(self.t / 'data')
        self.addCleanup(lambda: os.environ.__setitem__('CALSUITE_DATA', old) if old is not None else os.environ.pop('CALSUITE_DATA', None))
        for name in ('appdata', 'Calibration_Procedure_Manager'):
            sys.modules.pop(name, None)
        import Calibration_Procedure_Manager as CPM
        self.CPM = CPM
        self.addCleanup(sys.modules.pop, 'Calibration_Procedure_Manager', None)
        src = make_tree(self.t / 'src', [K2])
        self.zip = P.build_package(K2, src, self.t / 'lib', registry=V.Registry(self.t / 'sr.sqlite3', base=src))
        self.tree = make_tree(self.t / 'target', [], [K2])
        mgr = self.mgr = object.__new__(CPM.Manager)
        mgr.root, mgr.status = object(), Var()
        mgr.verified = V.Registry(self.t / 'reg.sqlite3', base=self.tree)
        mgr.refresh = mock.Mock()
        patches = [mock.patch.object(CPM, 'BASE', self.tree), mock.patch.object(CPM, 'messagebox'), mock.patch.object(CPM.packages_ui, 'choose_package'),
                   mock.patch.object(CPM.packages_ui, 'ask_install'), mock.patch.object(CPM.packages_ui, 'show_result'),
                   mock.patch.object(CPM.packages, 'get_library_dir', return_value=str(self.t / 'lib'))]
        self.box, self.choose, self.ask, self.show = [p.start() for p in patches][1:5]
        self.addCleanup(lambda: [p.stop() for p in patches])

    def test_confirmed_import_installs_refreshes_and_reports(self):
        self.choose.return_value = str(self.zip)
        self.ask.return_value = True
        self.mgr.import_package()
        self.assertTrue((self.tree / 'Procedures' / f'{K2}.py').is_file())
        self.assertEqual(procscan.find(K2, self.tree).id, K2)
        self.mgr.refresh.assert_called_once()
        self.assertIn('Imported', self.mgr.status.get())
        self.show.assert_called_once()
        pv = self.ask.call_args[0][1]
        self.assertTrue(pv.ok and pv.in_library)                       # the preview saw the library folder setting
        self.assertEqual(len(P.imports(self.mgr.verified.path)), 1)

    def test_declined_import_writes_nothing(self):
        self.choose.return_value = str(self.zip)
        self.ask.return_value = False
        self.mgr.import_package()
        self.assertFalse((self.tree / 'Procedures' / f'{K2}.py').exists())
        self.mgr.refresh.assert_not_called()
        self.assertEqual(P.imports(self.mgr.verified.path), [])

    def test_no_file_chosen_does_nothing(self):
        self.choose.return_value = ''
        self.mgr.import_package()
        self.ask.assert_not_called()

    def test_a_refused_package_is_shown_and_nothing_is_installed(self):
        bad = self.t / 'junk.zip'
        bad.write_bytes(b'nope')
        self.choose.return_value = str(bad)
        self.ask.return_value = False                                   # the dialog has no Install button for a refused package
        self.mgr.import_package()
        pv = self.ask.call_args[0][1]
        self.assertFalse(pv.ok)
        self.assertFalse((self.tree / 'Procedures' / f'{K2}.py').exists())

    def test_a_failure_during_install_is_reported(self):
        self.choose.return_value = str(self.zip)
        self.ask.return_value = True
        with mock.patch.object(self.CPM.packages, 'install', side_effect=P.PackageError('boom')):
            self.mgr.import_package()
        self.box.showerror.assert_called_once()
        self.mgr.refresh.assert_not_called()

    def test_the_manager_has_the_button_and_the_folder_setting(self):
        src = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        self.assertIn("label='Import procedure package...'", src)          # now an item of the Library menu (was a button on the Procedures tab)
        self.assertIn("label='Library folder...'", src)
        self.assertNotIn('Procedure Development', src)

    def test_library_folder_buttons_use_the_setting(self):
        self.mgr.lib_folder = Var()
        with mock.patch.object(self.CPM.packages, 'set_library_dir') as setter, mock.patch.object(self.CPM.packages, 'get_library_dir', return_value=''):
            self.mgr.set_library_folder('')
        setter.assert_called_once_with('')
        self.assertIn('not set', self.mgr.lib_folder.get())


if __name__ == '__main__':
    unittest.main()
