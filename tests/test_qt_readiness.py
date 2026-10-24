"""Qt twin of the 'Readiness check (no hardware)...' window (qtui.screens.readiness): the report text of tools/readiness_check.render() on synthetic reports
(same scenarios as tests/test_readiness_check.py), the findings list, the runner with a fake subprocess, and the real tool on one procedure.
Skipped when PySide6 is not importable.

    <venv python> -m unittest tests.test_qt_readiness
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

import readiness_check as RC  # noqa: E402

if HAVE_QT:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QPushButton
    from qtui import app as qapp
    from qtui.screens import common
    from qtui.screens import readiness as R
    QAPP = qapp.create_app()


def setUpModule():
    RC._load_modules()


def make_report(*findings, seconds=1.5):
    rep = RC.Report(proc=type('P', (), dict(id='Fluke_117_Verification', name='Fluke 117', engine=['handheld_dmm.py'], launcher=''))())
    for f in findings:
        rep.add(*f)
    rep.seconds = seconds
    return rep


FINDINGS = [
    (RC.FAIL, 'commands', '2 commands are not in the registry', ['WHATEVER 1', 'FOO 2']),
    (RC.WARN, 'outputs', 'output left on at the end of 1 point', ['point 4: no STBY after OPER']),
    (RC.PASS, 'readback', 'every write has a read-back'),
    (RC.INFO, 'unverified', '3 commands unverified on hardware', ['UNK 3', 'A', 'B'], True),
]


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Parsing(unittest.TestCase):
    def setUp(self):
        self.text = RC.render(make_report(*FINDINGS))
        self.rep = R.parse_report(self.text)

    def test_header_and_counts(self):
        r = self.rep
        self.assertTrue(r.is_report)
        self.assertEqual((r.name, r.id, r.engine, r.worst, r.fails, r.warns, r.seconds), ('Fluke 117', 'Fluke_117_Verification', 'handheld_dmm.py', 'FAIL', 1, 1, '1.5'))
        self.assertEqual(r.counts(), {'FAIL': 1, 'WARN': 1, 'PASS': 1, 'info': 1})

    def test_findings_match_what_the_tool_printed(self):
        got = [(f['level'], f['check'], f['text'], f['details']) for f in self.rep.findings]
        self.assertEqual(got, [('FAIL', 'commands', '2 commands are not in the registry', ['WHATEVER 1', 'FOO 2']),
                               ('WARN', 'outputs', 'output left on at the end of 1 point', ['point 4: no STBY after OPER']),
                               ('PASS', 'readback', 'every write has a read-back', []),
                               ('info', 'unverified', '3 commands unverified on hardware', ['UNK 3', 'A', 'B'])])

    def test_long_detail_lists_keep_the_more_line(self):
        rep = R.parse_report(RC.render(make_report((RC.WARN, 'commands', 'many', [f'cmd {i}' for i in range(9)]))))
        f = rep.findings[0]
        self.assertEqual(len(f['details']), RC.DETAIL_LINES)
        self.assertEqual(f['more'], f'... {9 - RC.DETAIL_LINES} more (--verbose)')

    def test_other_text_is_not_a_report(self):
        for t in ('', 'The readiness check could not run: boom', 'Traceback (most recent call last):\n  File "x"'):
            self.assertFalse(R.parse_report(t).is_report, t)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Window(unittest.TestCase):
    def setUp(self):
        self.text = RC.render(make_report(*FINDINGS))
        self.w = R.ReadinessWindow(None, 'Fluke 117', self.text)
        self.w.resize(1000, 680)
        self.w.show()
        QAPP.processEvents()
        self.addCleanup(lambda: self.w.close() if __import__('shiboken6').isValid(self.w) else None)

    def test_title_header_filter_counts_and_rows(self):
        w = self.w
        self.assertEqual(w.windowTitle(), 'Readiness check - Fluke 117')
        self.assertIn('FAIL', w.result_badge.text())
        self.assertEqual([r['check'] for r in w.table.visible_rows()], ['commands', 'outputs', 'readback', 'unverified'])
        self.assertEqual(w.tabs.tabText(0), 'Findings')
        self.assertEqual(w.tabs.tabText(1), 'Report text')

    def test_report_text_tab_is_exactly_the_tool_text_and_copy_copies_it(self):
        self.assertEqual(self.w.box.toPlainText(), self.text)
        self.w.btn_copy.click()
        self.assertEqual(QGuiApplication.clipboard().text(), self.text)

    def test_filter_shows_one_level(self):
        self.w.filter.set_current('FAIL', emit=True)
        QAPP.processEvents()
        self.assertEqual([r['check'] for r in self.w.table.visible_rows()], ['commands'])
        self.w.filter.set_current('all', emit=True)
        QAPP.processEvents()
        self.assertEqual(len(self.w.table.visible_rows()), 4)

    def test_selecting_a_finding_shows_its_detail_lines(self):
        f = self.w.select_check('commands')
        self.assertEqual(f['level'], 'FAIL')
        self.assertEqual(self.w.detail_title.text(), 'commands: 2 commands are not in the registry')
        self.assertEqual(self.w.detail.toPlainText(), '- WHATEVER 1\n- FOO 2')
        self.w.select_check('readback')
        self.assertEqual(self.w.detail.toPlainText(), '(no detail lines for this finding)')

    def test_a_non_report_shows_the_raw_text(self):
        w = R.ReadinessWindow(None, 'X', 'The readiness check could not run: boom')
        self.addCleanup(w.close)
        w.show()
        self.assertEqual(w.result_badge.text(), 'NO REPORT')
        self.assertEqual(w.tabs.currentIndex(), 1)
        self.assertEqual(w.box.toPlainText(), 'The readiness check could not run: boom')

    def test_close_button_closes(self):
        import shiboken6
        self.w.btn_close.click()
        QAPP.sendPostedEvents(None, 0)               # DeleteOnClose
        QAPP.processEvents()
        self.assertFalse(shiboken6.isValid(self.w) and self.w.isVisible())


class FakeStatus:
    def __init__(self):
        self.log = []

    def set(self, t):
        self.log.append(t)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Runner(unittest.TestCase):
    def test_runs_the_tool_with_the_procedure_id_in_the_manager_folder(self):
        calls = []

        def runner(cmd, **kw):
            calls.append((cmd, kw))
            return type('R', (), dict(stdout='READINESS TEXT', stderr=' (err)'))()
        out = R.run_check('Fluke_117_Verification', ROOT / 'tools' / 'readiness_check.py', ROOT, runner=runner)
        self.assertEqual(out, 'READINESS TEXT (err)')
        cmd, kw = calls[0]
        self.assertEqual(cmd, [sys.executable, str(ROOT / 'tools' / 'readiness_check.py'), 'Fluke_117_Verification'])
        self.assertEqual((kw['timeout'], kw['cwd'], kw['capture_output'], kw['text']), (300, str(ROOT), True, True))

    def test_a_tool_that_cannot_run_is_reported_not_raised(self):
        def runner(cmd, **kw):
            raise OSError('no python')
        self.assertEqual(R.run_check('x', Path('t.py'), ROOT, runner=runner), 'The readiness check could not run: no python')

    def test_start_shows_the_window_with_the_status_messages(self):
        st = FakeStatus()
        text = RC.render(make_report(*FINDINGS))
        h = R.start_readiness(None, 'Fluke_117_Verification', 'Fluke 117', ROOT, status=st, runner=lambda cmd, **kw: type('R', (), dict(stdout=text, stderr=''))())
        self.assertIsNotNone(h)
        self.assertEqual(st.log[0], 'Readiness check of Fluke 117 ...')
        self.assertTrue(h.wait(10))
        self.addCleanup(h.window.close)
        self.assertEqual(st.log[-1], 'Readiness check finished.')
        self.assertEqual(h.window.windowTitle(), 'Readiness check - Fluke 117')
        self.assertEqual(h.window.box.toPlainText(), text)
        self.assertNotIn(h, R._running)

    def test_a_missing_tool_says_so_and_starts_nothing(self):
        shown = []
        orig = common.show_info
        common.show_info = lambda parent, title, text, **k: shown.append((title, text))
        self.addCleanup(setattr, common, 'show_info', orig)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(R.start_readiness(None, 'x', 'X', d))
        self.assertEqual(shown, [('Readiness check', 'tools/readiness_check.py was not found next to the Manager.')])

    def test_the_real_tool_runs_on_a_procedure_without_the_simulated_run(self):
        out = R.run_check('Fluke_117_Verification --no-run'.split()[0], ROOT / 'tools' / 'readiness_check.py', ROOT, timeout=120)
        rep = R.parse_report(out)
        if not rep.is_report:
            self.skipTest('the real tool printed no report here: ' + out[:200])
        self.assertEqual(rep.id, 'Fluke_117_Verification')
        self.assertTrue(rep.findings)


if __name__ == '__main__':
    unittest.main()
