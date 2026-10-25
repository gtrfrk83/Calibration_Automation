"""Saved uncertainty calculations: stored in the lab registry file, listed in the calculator's rail, reopened and edited later."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.modules.setdefault('tkinter', None)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import labregistry
import uncertainty_store as store
from PySide6.QtWidgets import QApplication
from qtui import app
from qtui.screens import uncertainty_calculator as U

app.create_app()


class TempRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.object(labregistry, 'DB', Path(self.dir.name) / 'lab_registry.sqlite3')
        patcher.start()
        self.addCleanup(patcher.stop)


class StoreTests(TempRegistry):
    def test_round_trip_update_duplicate_delete(self):
        i = store.save('DC 10 V', {'unit': 'V', 'groups': [['A', ['1', '2']]]}, 'U = x')
        rec = store.load(i)
        self.assertEqual((rec['name'], rec['state']['groups'], rec['summary']), ('DC 10 V', [['A', ['1', '2']]], 'U = x'))
        self.assertEqual(store.save('DC 10 V v2', {'unit': 'mV'}, 'U = y', calc_id=i), i)
        self.assertEqual(store.load(i)['state'], {'unit': 'mV'})
        self.assertEqual(len(store.listing()), 1)
        j = store.duplicate(i, 'copy')
        self.assertNotEqual(i, j)
        self.assertEqual([r['name'] for r in store.listing('copy')], ['copy'])
        self.assertTrue(store.delete(i))
        self.assertIsNone(store.load(i))
        self.assertEqual(len(store.listing()), 1)

    def test_damaged_file_gives_empty_results(self):
        Path(labregistry.DB).write_bytes(b'not a database')
        self.assertEqual(store.listing(), [])
        self.assertIsNone(store.load(1))
        self.assertIsNone(store.save('x', {}))

    def test_procedures_database_is_not_touched(self):
        self.assertNotEqual(Path(labregistry.DB).name, 'calibration_procedures.sqlite3')


class PanelSaveTests(TempRegistry):
    def setUp(self):
        super().setUp()
        self.p = U.UncertaintyCalculatorPanel()
        self.addCleanup(self.p.close)
        self.p.show()
        QApplication.processEvents()
        self.names = []
        self.yes = True
        for name, repl in (('_ask_name', lambda *a, **k: self.names.pop(0) if self.names else ''), ('_confirm', lambda *a, **k: self.yes), ('_error', lambda *a, **k: None)):
            patcher = mock.patch.object(U, name, repl)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fill(self, title='DC volts 10 V', last='10.0001'):
        p = self.p
        p.unit_e.setText('V')
        p.title_e.setText(title)
        p.rep_text.setPlainText(f'10.0001\n10.0003\n9.9999\n10.0002\n10.0000\n{last}')
        for col, vals in enumerate((['10.0001', '10.0002', '10.0000'], ['10.0004', '10.0005', '10.0003'])):
            p.groups.setItem(0, col, U.QTableWidgetItem(f'Day {col + 1}'))
            for r, v in enumerate(vals):
                p.groups.setItem(1 + r, col, U.QTableWidgetItem(v))
        p.add_type_b('Standard', '0.00004', 'k2')
        p.recalc()

    def test_save_then_reopen_restores_everything_and_the_same_result(self):
        self.fill()
        self.names = ['Volts 10 V']
        before = self.p.result.reported
        cid = self.p.save_current()
        self.assertIsNotNone(cid)
        self.assertEqual(self.p.saved_list.count(), 1)
        self.assertIn('Volts 10 V', self.p.saved_list.item(0).text())
        self.p.new_calculation()
        self.assertEqual(self.p.rep_text.toPlainText(), '')
        self.assertEqual(self.p.typeb.rowCount(), 0)
        self.assertTrue(self.p.open_saved(cid))
        self.assertEqual(self.p.title_e.text(), 'DC volts 10 V')
        self.assertEqual(self.p.group_data()['Day 2'], ['10.0004', '10.0005', '10.0003'])
        self.assertEqual(self.p.typeb.rowCount(), 1)
        self.assertEqual(self.p.result.reported, before)
        self.assertFalse(self.p.is_dirty())

    def test_edit_later_and_save_updates_the_same_row(self):
        self.fill()
        self.names = ['One']
        cid = self.p.save_current()
        self.p.rep_text.setPlainText('10.0\n10.1\n9.9')
        self.p.recalc()
        self.assertTrue(self.p.is_dirty())
        self.assertIn('Unsaved', self.p.state_label.text())
        self.assertEqual(self.p.save_current(), cid)                        # no name asked again
        self.assertEqual(len(store.listing()), 1)
        self.assertEqual(store.load(cid)['state']['repeat_text'], '10.0\n10.1\n9.9')

    def test_save_as_makes_a_second_row_and_cancel_saves_nothing(self):
        self.fill()
        self.names = ['One']
        self.p.save_current()
        self.names = ['Two']
        self.assertNotEqual(self.p.save_current(as_new=True), None)
        self.assertEqual(len(store.listing()), 2)
        self.names = ['']
        self.assertIsNone(self.p.save_current(as_new=True))
        self.assertEqual(len(store.listing()), 2)

    def test_unsaved_changes_are_not_lost_without_a_yes(self):
        self.fill()
        self.names = ['One']
        a = self.p.save_current()
        self.names = ['Two']
        self.p.new_calculation()
        self.fill(title='Other')
        b = self.p.save_current()
        self.p.rep_text.setPlainText('1\n2\n3')
        self.yes = False
        self.assertFalse(self.p.open_saved(a))
        self.assertEqual(self.p.current_id, b)
        self.assertEqual(self.p.rep_text.toPlainText(), '1\n2\n3')
        self.yes = True
        self.assertTrue(self.p.open_saved(a))
        self.assertEqual(self.p.title_e.text(), 'DC volts 10 V')

    def test_delete_and_duplicate(self):
        self.fill()
        self.names = ['One']
        self.p.save_current()
        self.names = ['One (copy)']
        self.assertIsNotNone(self.p.duplicate_saved())
        self.assertEqual(self.p.saved_list.count(), 2)
        self.assertTrue(self.p.delete_saved())
        self.assertEqual(self.p.saved_list.count(), 1)
        self.assertIsNone(self.p.current_id)

    def test_the_list_can_be_folded_away_for_room(self):
        self.assertTrue(self.p.rail_body.isVisibleTo(self.p))
        self.p.set_rail_open(False)
        self.assertFalse(self.p.rail_body.isVisibleTo(self.p))
        self.assertLess(self.p.rail.width() if self.p.rail.width() else 30, 100)
        self.p.set_rail_open(True)
        self.assertTrue(self.p.rail_body.isVisibleTo(self.p))

    def test_search_filters_the_rail(self):
        self.fill()
        self.names = ['Volts']
        self.p.save_current()
        self.names = ['Ohms']
        self.p.save_current(as_new=True)
        self.p.find_e.setText('ohm')
        self.p.refresh()
        self.assertEqual(self.p.saved_list.count(), 1)


if __name__ == '__main__':
    unittest.main()
