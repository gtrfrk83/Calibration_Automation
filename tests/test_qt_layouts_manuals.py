"""Remembered window layouts and the manual finder / viewer hand-off."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.modules.setdefault('tkinter', None)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import manuals
from PySide6.QtWidgets import QApplication, QSplitter, QWidget
from qtui import layouts, manual_viewer

app = QApplication.instance() or QApplication([])


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.t), 'CALSUITE_LAYOUTS': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_window_size_splitter_and_extra_come_back(self):
        w, sp = QWidget(), QSplitter()
        sp.addWidget(QWidget())
        sp.addWidget(QWidget())
        w.resize(701, 533)
        sp.resize(600, 100)
        sp.setSizes([100, 500])
        self.assertTrue(layouts.save('t', w, {'s': sp}, extra={'open': True}))
        w2, sp2 = QWidget(), QSplitter()
        sp2.addWidget(QWidget())
        sp2.addWidget(QWidget())
        sp2.resize(600, 100)
        extra = layouts.restore('t', w2, {'s': sp2})
        self.assertEqual(extra, {'open': True})
        self.assertEqual((w2.width(), w2.height()), (701, 533))
        self.assertLess(sp2.sizes()[0], sp2.sizes()[1])

    def test_nothing_saved_or_damaged_file_means_defaults(self):
        w = QWidget()
        self.assertEqual(layouts.restore('none', w), {})
        layouts.path().write_text('{ not json', encoding='utf-8')
        self.assertEqual(layouts.restore('t', w), {})
        layouts.path().write_text(__import__('json').dumps({'t': {'geometry': '!!!'}}), encoding='utf-8')
        self.assertEqual(layouts.restore('t', w), {})

    def test_reset_forgets_one_window(self):
        w = QWidget()
        layouts.save('a', w)
        layouts.save('b', w)
        layouts.reset('a')
        self.assertEqual((layouts.saved('a'), bool(layouts.saved('b'))), ({}, True))

    def test_switched_off_does_not_write(self):
        with mock.patch.dict(os.environ, {'CALSUITE_LAYOUTS': '0'}):
            self.assertFalse(layouts.save('a', QWidget()))
        self.assertFalse(layouts.path().exists())


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        for n in ('5522 manual.pdf', '33220 Calibration Manual.pdf', '5790B Manual.pdf', 'notes.txt'):
            (self.t / n).write_bytes(b'%PDF-1.4\n')
        self.env = mock.patch.dict(os.environ, {'CALSUITE_MANUALS': str(self.t)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_find_by_model(self):
        self.assertEqual([p.name for p in manuals.find('Fluke 5522A')], ['5522 manual.pdf'])
        self.assertEqual([p.name for p in manuals.find('33220A')], ['33220 Calibration Manual.pdf'])
        self.assertEqual(manuals.find('99999'), [])
        self.assertEqual(manuals.find(''), [])

    def test_page_from_reference(self):
        self.assertEqual([manuals.page_from_ref(x) for x in ('Manual page 14', 'p. 8', 'pp. 15-16', '7', 'none')], [14, 8, 15, 7, None])

    def test_missing_manual_tells_where_to_put_it(self):
        with mock.patch.object(manual_viewer.QMessageBox, 'information') as info:
            self.assertIsNone(manual_viewer.open_for_model(None, 'Nonexistent 12345'))
        self.assertIn(str(self.t), info.call_args[0][2])

    @unittest.skipIf(manual_viewer.HAVE_PDF, 'this PySide6 has QtPdf: the viewer window is used instead')
    def test_without_qtpdf_the_system_viewer_gets_the_file_and_page(self):
        with mock.patch.object(manual_viewer.QDesktopServices, 'openUrl') as op:
            self.assertIsNone(manual_viewer.open_for_model(None, '5522A', page=14))
        url = op.call_args[0][0]
        self.assertTrue(url.toLocalFile().endswith('5522 manual.pdf'))
        self.assertEqual(url.fragment(), 'page=14')


if __name__ == '__main__':
    unittest.main()
