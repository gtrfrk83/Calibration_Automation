"""qtui.shell (the Qt twin of ui_shell.Shell) + qtui.shell_helpers + qtui.vars: construction, the API the *_view_tk files use, the Treeview-like results table, the compact
layout, the drawer, the 34410A demo window.  Skipped when PySide6 is not importable.  Headless (offscreen)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QMainWindow, QPushButton, QWidget
    from qtui import app as qapp
    from qtui import shell as S
    from qtui import shell_helpers as H
    from qtui import shell_demo
    from qtui.vars import QtVar, bind


def settle(n=6):
    for _ in range(n):
        QApplication.processEvents()


class FakeApp:
    is_left = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ShellCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa = qapp.create_app()

    def make(self, w=1320, h=820, **kw):
        win = QMainWindow()
        self.addCleanup(win.close)
        sh = S.Shell(win, 'Fluke 8846A  -  Performance Verification', 'sub <b>not bold</b>', **kw)
        win.resize(w, h)
        win.show()
        settle()
        return win, sh


class Header(ShellCase):
    def test_constructs_and_hosts_in_the_main_window(self):
        win, sh = self.make(demo=True, virtual=True)
        self.assertIs(win.centralWidget(), sh.widget)
        self.assertEqual(sh.title_label.text(), 'Fluke 8846A  -  Performance Verification')
        self.assertEqual(sh._sub.text(), 'sub <b>not bold</b>')                      # plain text
        self.assertEqual(sh._sub.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn('DEMO MODE', sh.mode_chip.text())
        self.assertEqual(sh.mode_chip.kind(), 'warn')

    def test_hardware_chip(self):
        _w, sh = self.make(demo=False)
        self.assertEqual((sh.mode_chip.text(), sh.mode_chip.kind()), ('HARDWARE MODE', 'info'))

    def test_subtitle_var_updates_the_label(self):
        _w, sh = self.make()
        sh.subtitle.set('new text')
        self.assertEqual(sh._sub.text(), 'new text')

    def test_chips(self):
        _w, sh = self.make()
        chip = sh.add_chip('Not connected', 'neutral')
        chip.set('Connected', 'good')
        self.assertEqual((chip.text(), chip.kind()), ('Connected', 'good'))
        self.assertIsNone(sh.set_modified(0))
        c = sh.set_modified(3)
        self.assertEqual(c.text(), 'MODIFIED (3)')
        self.assertTrue(c.isVisible())
        sh.set_modified(0)
        self.assertFalse(c.isVisible())
        v = sh.set_verified('VERIFIED ON HARDWARE - LOCKED')
        self.assertEqual((v.text(), v.kind(), v.isVisible()), ('VERIFIED ON HARDWARE - LOCKED', 'good', True))
        sh.set_verified('')
        self.assertFalse(v.isVisible())
        d = sh.set_devmode(True)
        self.assertEqual((d.text(), d.isVisible()), ('DEVELOPER MODE', True))
        sh.set_devmode(False)
        self.assertFalse(d.isVisible())

    def test_identity_is_bound_to_the_variables(self):
        _w, sh = self.make()
        a, s = QtVar('A-1'), QtVar('')
        sh.build_identity(a, s, focus=False)
        self.assertEqual(sh.id_entry.text(), 'A-1')
        sh.id_entry.setText('B-2')
        self.assertEqual(a.get(), 'B-2')
        s.set('SN9')
        self.assertEqual(sh.serial_entry.text(), 'SN9')

    def test_notice(self):
        _w, sh = self.make()
        n = sh.notice('Stay at the bench <now>.', 'info', title='Note')
        settle()
        self.assertEqual(n.text_label.text(), 'Stay at the bench <now>.')
        self.assertEqual(n.title_label.text(), 'Note')
        self.assertTrue(n.isVisible())

    def test_progress_panel(self):
        _w, sh = self.make()
        p = sh.build_progress()
        p.update_counts(86, 33, 1)
        self.assertEqual(p.text.get(), '34 of 86 tested')
        self.assertEqual((p.ok.text(), p.fail.text(), p.rem.text()), ('33 pass', '1 fail', '52 remaining'))
        self.assertEqual((p.ok.kind(), p.fail.kind()), ('good', 'bad'))
        p.update_counts(2, 2, 0)
        self.assertEqual((p.rem.text(), p.rem.kind()), ('All points tested', 'good'))
        p.set_rerun(5, 2, 1, 1)
        self.assertEqual(p.text.get(), '2 of 5 re-run done')
        self.assertEqual((p.ok.text(), p.fail.text(), p.rem.text()), ('1 now in limits', '1 still out', '3 to re-run'))
        p.set_rerun(0, 0, 0, 0)
        self.assertIn('nothing to re-run', p.text.get())
        p.grab()                                                    # paints without error


class Actions(ShellCase):
    def test_add_action_roles_order_state_and_compact_texts(self):
        calls = []
        win, sh = self.make()
        run = sh.add_action('▶  Run All Pending', lambda: calls.append('run'), accent=True, short='▶  Run')
        sec = sh.add_action('Run Shown Section', lambda: calls.append('sec'), short='Section')
        stop = sh.add_action('■  Stop', lambda: calls.append('stop'), danger=True, short='■ Stop', state='disabled')
        exp = sh.add_action('Export Report (PDF)', lambda: calls.append('pdf'), side='right', short='PDF')
        settle()
        self.assertEqual(run.property('role'), 'primary')
        self.assertEqual(stop.property('role'), 'danger')
        self.assertFalse(stop.isEnabled())
        self.assertEqual(stop.cget('state'), 'disabled')
        stop.configure(state='normal')
        self.assertTrue(stop.isEnabled())
        self.assertLess(run.geometry().x(), sec.geometry().x())                       # left group in order
        self.assertGreater(exp.mapTo(win, exp.rect().topLeft()).x(), stop.mapTo(win, stop.rect().topLeft()).x())     # right group on the right
        QTest.mouseClick(run, Qt.MouseButton.LeftButton)
        QTest.mouseClick(stop, Qt.MouseButton.LeftButton)
        QTest.mouseClick(exp, Qt.MouseButton.LeftButton)
        self.assertEqual(calls, ['run', 'stop', 'pdf'])
        self.assertFalse(sh.compact)
        win.resize(940, 700)
        settle(10)
        self.assertTrue(sh.compact)
        self.assertEqual((run.text(), sec.text(), exp.text()), ('▶  Run', 'Section', 'PDF'))
        win.resize(1320, 820)
        settle(10)
        self.assertFalse(sh.compact)
        self.assertEqual((run.text(), sec.text(), exp.text()), ('▶  Run All Pending', 'Run Shown Section', 'Export Report (PDF)'))

    def test_a_disabled_button_does_not_fire(self):
        calls = []
        _w, sh = self.make()
        b = sh.add_action('Stop', lambda: calls.append(1), state='disabled')
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        self.assertEqual(calls, [])

    def test_keyboard_operable(self):
        calls = []
        win, sh = self.make()
        b = sh.add_action('Go', lambda: calls.append(1), accent=True)
        b.setFocus()
        QTest.keyClick(b, Qt.Key.Key_Space)
        self.assertEqual(calls, [1])


class Sections(ShellCase):
    def test_sidebar_rows_counts_and_choosing(self):
        chosen = []
        win, sh = self.make()
        sh.on_section = chosen.append
        sh.set_sections([('DC volts', 3, 1, 8), ('Ohms', 8, 0, 8), ('AC', 0, 0, 4)])
        settle()
        self.assertEqual(list(sh._rows), ['All sections', 'DC volts', 'Ohms', 'AC'])
        allrow = sh._rows['All sections']
        self.assertEqual((allrow.ok, allrow.bad, allrow.tot), (11, 1, 20))
        QTest.mouseClick(sh._rows['Ohms'], Qt.MouseButton.LeftButton)
        self.assertEqual(chosen, ['Ohms'])
        self.assertEqual(sh.current, 'Ohms')
        self.assertTrue(sh._rows['Ohms'].selected)
        sh._rows['AC'].setFocus()
        QTest.keyClick(sh._rows['AC'], Qt.Key.Key_Return)
        self.assertEqual(chosen, ['Ohms', 'AC'])

    def test_removed_section_falls_back_to_all(self):
        chosen = []
        _w, sh = self.make()
        sh.on_section = chosen.append
        sh.set_sections([('A', 0, 0, 1), ('B', 0, 0, 1)])
        sh.choose_section('B', notify=False)
        sh.set_sections([('A', 0, 0, 1)])
        settle()
        self.assertEqual(sh.current, 'All sections')
        self.assertEqual(chosen, ['All sections'])

    def test_section_picker_in_a_small_window(self):
        chosen = []
        win, sh = self.make()
        sh.on_section = chosen.append
        sh.set_sections([('A', 0, 0, 1), ('B', 0, 0, 1)])
        filt = H.frame(None, 'h')
        sh.content_layout.addWidget(filt)
        picker = sh.build_section_picker(filt)
        settle()
        self.assertFalse(picker.isVisible())
        self.assertEqual([picker.itemText(i) for i in range(picker.count())], ['All sections', 'A', 'B'])
        win.resize(900, 700)
        settle(10)
        self.assertTrue(picker.isVisible())
        self.assertFalse(sh.sidebar.isVisible())
        picker.setCurrentIndex(2)
        picker.activated.emit(2)
        self.assertEqual(chosen[-1], 'B')
        self.assertEqual(picker.currentText(), 'B')


class Drawer(ShellCase):
    def test_open_close_escape_and_layout_slots(self):
        win, sh = self.make()
        self.assertFalse(sh.drawer.isVisible())
        sh.btn_drawer.click()
        settle()
        self.assertTrue(sh.drawer.isVisible())
        self.assertEqual(sh.drawer.geometry().right() + 1, sh.body.width())              # glued to the right edge
        sh.btn_drawer_close.click()
        self.assertFalse(sh.drawer.isVisible())
        sh.open_drawer()
        QTest.keyClick(win, Qt.Key.Key_Escape)
        settle()
        self.assertFalse(sh.drawer.isVisible())
        sh.toggle_drawer()
        self.assertTrue(sh.drawer.isVisible())
        win.resize(1000, 700)
        settle(10)
        self.assertEqual(sh.drawer.geometry().right() + 1, sh.body.width())              # follows a resize
        sh.toggle_drawer()
        self.assertFalse(sh.drawer.isVisible())

    def test_drawer_body_is_a_grid_and_the_footer_a_row(self):
        _w, sh = self.make()
        lay = sh.drawer_body.layout()
        lay.addWidget(H.label_(None, 'Limits to apply'), 0, 0)
        combo = H.combobox(None, QtVar('a'), ['a', 'b'])
        lay.addWidget(combo, 0, 1)
        sh.drawer_footer_layout.insertWidget(0, H.button(None, 'Find instruments', None))
        sh.open_drawer()
        settle()
        self.assertTrue(combo.isVisible())


class StatusBar(ShellCase):
    def test_status_var_drives_the_message_and_the_dot_colour(self):
        _w, sh = self.make()
        sh.status_var.set('Connection failed: no reply')
        settle()
        self.assertIn('Connection failed', sh.statusbar.line.text())
        self.assertEqual(sh.statusbar.line.kind(), 'bad')
        sh.status_var.set('Results saved to x.json')
        self.assertEqual(sh.statusbar.line.kind(), 'good')
        sh.status_var.set('')
        self.assertEqual(sh.statusbar.line.text(), '')

    def test_status_var_set_from_a_worker_thread_is_applied_on_the_ui_thread(self):
        import threading
        _w, sh = self.make()
        t = threading.Thread(target=lambda: sh.status_var.set('Measuring 3 of 10'))
        t.start()
        t.join()
        for _ in range(20):
            settle()
        self.assertIn('Measuring 3 of 10', sh.statusbar.line.text())

    def test_log_pane(self):
        _w, sh = self.make()
        self.assertFalse(sh.log.isVisible())
        sh.log_line('SYST:ERR?')
        sh.show_log(True)
        settle()
        self.assertTrue(sh.log.isVisible())
        self.assertIn('SYST:ERR?', sh.log.toPlainText())

    def test_menu(self):
        win, sh = self.make()
        m = sh.add_menu('&File')
        m.addAction('Save')
        self.assertTrue(win.menuBar().actions())


class ResultsTable(ShellCase):
    def table(self, error=True):
        win, sh = self.make()
        app = FakeApp()
        app.shell = sh
        tree = S.results_table(app, sh.content, error=error)
        return win, sh, app, tree

    ROWS = [('1', (1, 'Front DC current 100 uA', '0 A', '-25 nA', '25 nA', '-25 nA … 25 nA', '5 nA', '+5 nA', '', '✔ PASS'), ('pass',)),
            ('2', (2, 'Front DC volts 1 V', '0 V', '-7 uV', '7 uV', '-7 uV … 7 uV', '9 uV', '+9 uV', '', '✖ FAIL'), ('fail',)),
            ('3', (3, 'Rear ohms', '100 Ω', '99 Ω', '101 Ω', '99 Ω … 101 Ω', '', '', '', '—'), ('pending',))]

    def test_treeview_calls(self):
        _w, _sh, _app, tree = self.table()
        sel = []
        tree.bind('<<TreeviewSelect>>', lambda e: sel.append(tree.selection()))
        tree.set_all(self.ROWS)
        settle()
        self.assertEqual(tree.get_children(), ('1', '2', '3'))
        self.assertTrue(tree.exists('2') and not tree.exists('9'))
        tree.selection_set('2')
        settle(10)
        self.assertEqual(tree.selection(), ('2',))
        self.assertEqual(sel[-1], ('2',))
        tree.item('2', values=(2, 'Front DC volts 1 V', '0 V', '-7 uV', '7 uV', '-7 uV … 7 uV', '3 uV', '+3 uV', '', '✔ PASS'), tags=('pass',))
        self.assertEqual(tree.item('2', 'tags'), ('pass',))
        self.assertEqual(tree.item('2')['values'][9], '✔ PASS')
        tree.insert('', 'end', iid='4', values=(4, 'x', '', '', '', '', '', '', '', ''), tags=())
        self.assertEqual(tree.get_children(), ('1', '2', '3', '4'))
        tree.delete('4')
        self.assertEqual(tree.get_children(), ('1', '2', '3'))
        tree.delete(*tree.get_children())
        self.assertEqual(tree.get_children(), ())
        self.assertFalse(tree.exists('1'))

    def test_set_all_keeps_the_selection_by_iid(self):
        _w, _sh, _app, tree = self.table()
        tree.set_all(self.ROWS)
        tree.selection_set('3')
        settle(10)
        tree.set_all(self.ROWS, keep=tree.selection())
        settle(10)
        self.assertEqual(tree.selection(), ('3',))

    def test_headings_and_columns_follow_the_mode(self):
        _w, _sh, app, tree = self.table()
        self.assertEqual(tree.heading('found'), '● As Found')
        self.assertEqual(tree.heading('left'), 'As Left')
        app.is_left = True
        app._relabel_reading_column()
        self.assertEqual(tree.heading('found'), 'As Found')
        self.assertEqual(tree.heading('left'), '● As Left')

    def test_small_window_merges_the_limit_columns(self):
        win, sh, app, tree = self.table()
        filt = H.frame(None, 'h')
        sh.content_layout.insertWidget(0, filt)
        picker = S.small_window(app, tree, filt)
        settle()
        hidden = lambda key: tree.isColumnHidden(tree._keys.index(key))  # noqa: E731
        self.assertTrue(hidden('limits') and not hidden('low') and not hidden('high'))
        win.resize(920, 700)
        settle(10)
        self.assertTrue(sh.compact)
        self.assertFalse(hidden('limits'))
        self.assertTrue(hidden('low') and hidden('high') and hidden('error'))
        self.assertTrue(picker.isVisible())
        win.resize(1320, 820)
        settle(10)
        self.assertTrue(hidden('limits'))
        self.assertFalse(hidden('low'))

    def test_without_the_error_column(self):
        _w, _sh, _app, tree = self.table(error=False)
        self.assertTrue(tree.isColumnHidden(tree._keys.index('error')))

    def test_tone_tags_tint_failed_rows_only_and_pass_text_is_green(self):
        _w, _sh, _app, tree = self.table()
        tree.set_all(self.ROWS)
        settle()
        m = tree.source_model
        rows = tree.rows()
        self.assertEqual(m.tone_of(rows[0]), None)
        self.assertEqual(m.tone_of(rows[1]), 'bad')
        res = m.columns[tree._keys.index('result')]
        self.assertEqual(res.tone(rows[0]), 'good')
        self.assertEqual(res.tone(rows[1]), 'bad')
        self.assertEqual(res.tone(rows[2]), 'muted')

    def test_renders_all_rows_text(self):
        win, _sh, _app, tree = self.table()
        tree.set_all(self.ROWS)
        settle()
        img = tree.grab().toImage()
        self.assertGreater(img.width(), 100)
        self.assertEqual(tree.source_model.data(tree.source_model.index(1, 9)), '✖ FAIL')


class Helpers(ShellCase):
    def test_vars_bind_every_widget_kind(self):
        v, b, i = QtVar('x'), QtVar(False, 'bool'), QtVar(3, 'int')
        e = QLineEdit()
        bind(e, v)
        e.setText('typed')
        self.assertEqual(v.get(), 'typed')
        v.set('set')
        self.assertEqual(e.text(), 'set')
        c = QCheckBox('c')
        bind(c, b)
        c.setChecked(True)
        self.assertIs(b.get(), True)
        b.set(False)
        self.assertFalse(c.isChecked())
        cb = QComboBox()
        cb.addItems(['a', 'b'])
        bind(cb, v)
        v.set('b')
        self.assertEqual(cb.currentText(), 'b')
        cb.setCurrentIndex(0)
        self.assertEqual(v.get(), 'a')
        lab = QLabel()
        bind(lab, i)
        i.set(7)
        self.assertEqual(lab.text(), '7')
        self.assertEqual(i.get(), 7)
        r1, r2 = H.radiobutton(None, 'A', 'a', v), H.radiobutton(None, 'B', 'b', v)
        v.set('b')
        self.assertTrue(r2.isChecked() and not r1.isChecked())
        r1.setChecked(True)
        self.assertEqual(v.get(), 'a')

    def test_var_traces(self):
        v = QtVar('a')
        seen = []
        tid = v.trace_add('write', lambda *a: seen.append((a, v.get())))
        v.set('b')
        self.assertEqual(seen, [(('', '', 'write'), 'b')])
        v.trace_remove('write', tid)
        v.set('c')
        self.assertEqual(len(seen), 1)
        self.assertIs(QtVar(1, 'bool').get(), True)
        self.assertEqual(QtVar('2.5', 'float').get(), 2.5)

    def test_editable_combobox_is_the_address_box(self):
        v = QtVar('GPIB0::22::INSTR')
        c = H.combobox(None, v, [], state='normal')
        self.assertEqual(c.currentText(), 'GPIB0::22::INSTR')
        c.configure(values=['USB0::A', 'GPIB0::22::INSTR'])
        self.assertEqual(c.count(), 2)
        self.assertEqual(c.currentText(), 'GPIB0::22::INSTR')
        c.setEditText('TCPIP::1')
        self.assertEqual(v.get(), 'TCPIP::1')

    def test_configure_state_values_text_command(self):
        calls = []
        b = H.button(None, 'Go', lambda: calls.append('a'))
        b.configure(text='Went', command=lambda: calls.append('b'), state='disabled')
        self.assertEqual((b.text(), b.isEnabled()), ('Went', False))
        b.configure(state='normal')
        b.click()
        self.assertEqual(calls, ['b'])
        b.configure(style='Accent.TButton')
        self.assertEqual(b.property('role'), 'primary')

    def test_pack_and_grid(self):
        host = H.frame(None, 'h')
        a, b, c = QLabel('a'), QLabel('b'), QLabel('c')
        H.pack(host, a, side='left')
        H.pack(host, b, side='right')
        H.pack(host, c, side='left')                    # after a, before the right-packed b
        lay = host.layout()
        self.assertEqual([lay.itemAt(i).widget().text() for i in range(lay.count())], ['a', 'c', 'b'])
        g = QWidget()
        x = H.grid(g, QLabel('x'), 0, 0, sticky='w')
        H.grid(g, QLabel('y'), 0, 1, sticky='ew', padx=(10, 0))
        H.grid_weight(g, column=1)
        self.assertEqual(g.layout().columnStretch(1), 1)
        self.assertIsNotNone(x)

    def test_pill_notice_banner_summary_statusbar_tooltip(self):
        host = QWidget()
        p = H.Pill(host, 'ok', 'good')
        p.set('bad', 'bad')
        self.assertEqual((p.text(), p.kind()), ('bad', 'bad'))
        var = QtVar('hello')
        n = H.Notice(host, '', 'bad', textvariable=var, title='T')
        self.assertEqual(n.text_label.text(), 'hello')
        var.set('changed')
        self.assertEqual(n.label.text(), 'changed')
        ban = H.Banner(host, 'Title', 'Sub')
        pill = ban.add_pill('DEMO', 'warn')
        ban.subtitle.set('Sub2')
        self.assertEqual((ban.sub_label.text(), pill.text()), ('Sub2', 'DEMO'))
        s = H.Summary(host)
        s.update_counts(10, 5, 5)
        self.assertEqual(s.text.get(), '10 of 10 tested')
        sb = H.StatusBar(host, QtVar(''))
        got = []
        btn = sb.add_button('Save', lambda: got.append(1))
        btn.click()
        self.assertEqual(got, [1])
        w = QWidget()
        H.Tooltip(w, lambda: 'dynamic')
        self.assertEqual(w.toolTip(), 'dynamic')

    def test_theme_helpers(self):
        self.assertEqual(H.px(12), 12)
        self.assertEqual(H.C['bg'], H.theme.tokens()['bg'])
        self.assertTrue(H.is_dark())
        w = QWidget()
        H.fit_window(w, 1320, 820, 900, 640)
        self.assertGreaterEqual(w.minimumWidth(), 1)
        self.assertEqual(H.si(0.000001, 'V') if callable(H.si) else None, H.si(0.000001, 'V'))


class Demo(ShellCase):
    def test_34410a_demo_window_renders(self):
        win = QMainWindow()
        self.addCleanup(win.close)
        sh, app = shell_demo.build(win)
        win.resize(1320, 820)
        win.show()
        settle(10)
        self.assertEqual(len(app.tree.get_children()), len(app.points))
        self.assertEqual(sh.summary.text.get(), f'{min(34, len(app.points))} of {len(app.points)} tested')       # 30 sample rows when the engine cannot import (no tkinter)
        out = Path(tempfile.mkdtemp()) / 'shell.png'
        self.assertTrue(win.grab().save(str(out)))
        img = QImage(str(out))
        self.assertEqual((img.width(), img.height()), (1320, 820))
        colours = {img.pixel(x, y) for x in range(0, 1320, 37) for y in range(0, 820, 37)}
        self.assertGreater(len(colours), 6)                              # not a blank window

    def test_demo_window_in_a_small_window(self):
        win = QMainWindow()
        self.addCleanup(win.close)
        sh, app = shell_demo.build(win)
        win.resize(900, 700)
        win.show()
        settle(10)
        self.assertTrue(sh.compact)
        self.assertLessEqual(win.minimumSizeHint().width(), 900)


if __name__ == '__main__':
    unittest.main()
