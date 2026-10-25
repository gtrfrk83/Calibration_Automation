"""Qt twin of the window of 'Readiness check (no hardware)...' (Calibration_Procedure_Manager.readiness_check on Tk): runs tools/readiness_check.py on the
simulated bench in a subprocess (no instrument I/O) and shows what it printed.  The headless logic (tools/readiness_check.py, tools/readiness_run.py) is
unchanged; this module only holds the window and the runner that feeds it.

    from qtui.screens import readiness
    h = readiness.start_readiness(parent, proc_id, proc_name, base_dir, status=status_line)     # status: anything with .set(text), optional
    win = readiness.ReadinessWindow(parent, proc_name, report_text)

The window shows the READINESS report two ways: a findings list (level, check, finding; select one for its detail lines) and the report text exactly as the tool
printed it (the Tk window showed only that text; 'Report text' is the same text, with a Copy button).  When the text is not a report (the tool could not run,
a traceback) there are no findings and the text tab is the one shown.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

from qtui import theme
from qtui.screens import common
from qtui.table import Column, DataTable
from qtui.widgets import Badge, SegmentedFilter, label

TIMEOUT_S = 300
LEVELS = ('FAIL', 'WARN', 'PASS', 'info')                       # worst first (readiness_check.MARK)
BADGE = {'FAIL': 'bad', 'WARN': 'warn', 'PASS': 'good', 'info': 'info'}
DEFAULT_SIZE = (1000, 680)
_FINDING = re.compile(r'^  (PASS|WARN|FAIL|info)\s+(\S+)\s+(.*)$')
_DETAIL = re.compile(r'^ {9}- (.*)$')
_running = set()                                                   # checks in flight: the handle (and its timer) must outlive the caller's reference
_MORE = re.compile(r'^ {9}(\.\.\. .*)$')
_HEAD = re.compile(r'^READINESS\s+(.*?)\s+\[(.*)\]\s*$')
_RESULT = re.compile(r'result:\s*(\S+)\s+\((\d+) FAIL, (\d+) WARN\)\s+([\d.]+) s')


class Report:
    """The parsed text of readiness_check.render(): header facts and the findings (dicts: level, check, text, details, more)."""

    def __init__(self, text: str):
        self.text = text
        self.name = self.id = self.engine = self.worst = ''
        self.fails = self.warns = 0
        self.seconds = ''
        self.findings: list[dict] = []
        cur = None
        for line in text.splitlines():
            m = _HEAD.match(line)
            if m and not self.id:
                self.name, self.id = m.group(1), m.group(2)
                continue
            if line.startswith('engine:') and not self.worst:
                self.engine = line.split('result:')[0].replace('engine:', '').strip()
                r = _RESULT.search(line)
                if r:
                    self.worst, self.fails, self.warns, self.seconds = r.group(1), int(r.group(2)), int(r.group(3)), r.group(4)
                continue
            m = _FINDING.match(line)
            if m:
                cur = dict(level=m.group(1), check=m.group(2), text=m.group(3), details=[], more='')
                self.findings.append(cur)
                continue
            m = _DETAIL.match(line)
            if m and cur is not None:
                cur['details'].append(m.group(1))
                continue
            m = _MORE.match(line)
            if m and cur is not None:
                cur['more'] = m.group(1)

    @property
    def is_report(self) -> bool:
        return bool(self.id and self.findings)

    def counts(self) -> dict:
        out = {lv: 0 for lv in LEVELS}
        for f in self.findings:
            out[f['level']] += 1
        return out


def parse_report(text: str) -> Report:
    return Report(text)


def run_check(proc_id, tool: Path, base: Path, runner=None, timeout: int = TIMEOUT_S) -> str:
    """What the Tk Manager did in its worker thread: run the tool in a subprocess and return its stdout + stderr (or the reason it could not run)."""
    run = runner or subprocess.run
    try:
        r = run([sys.executable, str(tool), str(proc_id)], capture_output=True, text=True, timeout=timeout, cwd=str(base))
        return (r.stdout or '') + (r.stderr or '')
    except (OSError, subprocess.SubprocessError) as exc:
        return f'The readiness check could not run: {exc}'


# ------------------------------------------------------------------------------------------------------------ the window
class ReadinessWindow(QWidget):
    def __init__(self, parent, name, text):
        super().__init__(common.qparent(parent), Qt.WindowType.Window)
        self.setObjectName('root')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.name, self.text = name, text
        self.report = parse_report(text)
        self.setWindowTitle(f'Readiness check - {name}')
        common.clamp_size(self, *DEFAULT_SIZE, 640, 400)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = label(name, 'h2', wrap=True)
        self.subtitle = label('', 'sub', wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        head.addLayout(col, 1)
        self.result_badge = Badge('', 'neutral')
        head.addWidget(self.result_badge)
        root.addLayout(head)
        self.note = common.hint('')
        root.addWidget(self.note)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 10, 0, 0)
        pl.setSpacing(8)
        self.filter = SegmentedFilter([('all', 'All', None)] + [(lv, lv, None) for lv in LEVELS])
        self.filter.currentChanged.connect(lambda _k: self._apply_filter())
        fr = QHBoxLayout()
        fr.addWidget(self.filter)
        fr.addStretch(1)
        pl.addLayout(fr)
        cols = [Column('level', 'Level', width=80, kind='badge', badge_map=BADGE, getter=lambda r: r['level']),
                Column('check', 'Check', width=130, getter=lambda r: r['check']),
                Column('text', 'Finding', width=640, stretch=True, getter=lambda r: r['text'])]
        self.table = DataTable(cols, self.report.findings, multi=False, row_key=lambda r: id(r), empty_text='No findings')
        self.table.selectionChangedRows.connect(lambda rows: self.show_detail(rows[0] if rows else None))
        pl.addWidget(self.table, 3)
        self.detail_title = label('', 'section', wrap=True)
        pl.addWidget(self.detail_title)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setProperty('mono', True)
        self.detail.setFont(theme.ui_font(mono=True))
        self.detail.setAccessibleName('Detail lines of the selected finding')
        pl.addWidget(self.detail, 2)
        self.tabs.addTab(page, 'Findings')

        self.box = QPlainTextEdit()                                 # exactly what the tool printed
        self.box.setReadOnly(True)
        self.box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.box.setFont(theme.ui_font(mono=True))
        self.box.setAccessibleName('Readiness report text')
        self.box.setPlainText(text)
        self.tabs.addTab(self.box, 'Report text')

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_copy = QPushButton('Copy report')
        self.btn_copy.clicked.connect(self.copy)
        self.btn_close = QPushButton('Close')
        self.btn_close.setProperty('role', 'primary')
        self.btn_close.clicked.connect(self.close)
        foot.addWidget(self.btn_copy)
        foot.addWidget(self.btn_close)
        root.addLayout(foot)
        self._fill()

    def _fill(self):
        rep = self.report
        if rep.is_report:
            c = rep.counts()
            self.subtitle.setText(f'{rep.name}  [{rep.id}]   engine: {rep.engine}   {rep.seconds} s')
            kind = {'FAIL': 'bad', 'WARN': 'warn', 'PASS': 'good'}.get(rep.worst, 'neutral')
            self.result_badge.set(f'{rep.worst}   {rep.fails} FAIL  {rep.warns} WARN', kind)
            for lv in LEVELS:
                self.filter.set_count(lv, c[lv])
            self.filter.set_count('all', len(rep.findings))
            self.note.setText('Select a finding to see its detail lines. The Report text tab has the report exactly as the tool printed it.')
            self.tabs.setCurrentIndex(0)
        else:
            self.subtitle.setText('No readiness report: the tool printed something else (shown under Report text).')
            self.result_badge.set('NO REPORT', 'warn')
            self.filter.setVisible(False)
            self.table.setVisible(False)
            self.detail.setVisible(False)
            self.detail_title.setVisible(False)
            self.tabs.setCurrentIndex(1)
        self.show_detail(None)

    def _apply_filter(self):
        k = self.filter.current()
        self.table.set_predicate(None if k == 'all' else (lambda r, k=k: r['level'] == k))

    def show_detail(self, f):
        if f is None:
            self.detail_title.setText('')
            self.detail.setPlainText('')
            return
        self.detail_title.setText(f'{f["check"]}: {f["text"]}')
        lines = [f'- {d}' for d in f['details']] + ([f['more']] if f['more'] else [])
        self.detail.setPlainText('\n'.join(lines) if lines else '(no detail lines for this finding)')

    def select_check(self, check):
        """Select the first finding of `check` (what a click does)."""
        f = next((f for f in self.report.findings if f['check'] == check), None)
        self.table.select_rows([f] if f is not None else [])
        self.show_detail(f)
        return f

    def copy(self):
        QGuiApplication.clipboard().setText(self.text)


# ------------------------------------------------------------------------------------------------------------ the runner
class Readiness:
    """One readiness check in flight: the worker thread runs the tool, a timer on the UI thread shows the window when it is done (the Tk Manager polled every
    200 ms the same way).  `window` is the ReadinessWindow once shown, `output` the tool's text."""

    def __init__(self, parent, proc_id, proc_name, base, status=None, runner=None, on_done=None):
        self.parent, self.proc_id, self.proc_name, self.status, self.on_done = parent, proc_id, proc_name, status, on_done
        self.base = Path(base)
        self.tool = self.base / 'tools' / 'readiness_check.py'
        self.runner = runner
        self.window = None
        self.output = None
        self.thread = None
        self.started = False

    def start(self) -> bool:
        if not self.tool.is_file():
            common.show_info(self.parent, 'Readiness check', 'tools/readiness_check.py was not found next to the Manager.')
            return False
        self._say(f'Readiness check of {self.proc_name} ...')
        out = []

        def work():
            out.append(run_check(self.proc_id, self.tool, self.base, self.runner))
        self._out = out
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self.started = True
        _running.add(self)
        self._timer = QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        return True

    def _say(self, text):
        if self.status is not None:
            self.status.set(text)

    def _poll(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self._timer.stop()
        _running.discard(self)
        self.show()

    def show(self):
        self.output = self._out[0] if self._out else ''
        self.window = ReadinessWindow(self.parent, self.proc_name, self.output)
        self.window.show()
        self._say('Readiness check finished.')
        if self.on_done:
            self.on_done(self)

    def wait(self, timeout: float = 60.0) -> bool:
        """Block (tests) until the tool finished and the window is up, pumping events."""
        import time
        from PySide6.QtWidgets import QApplication
        end = time.monotonic() + timeout
        while self.window is None and time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.02)
        return self.window is not None


def start_readiness(parent, proc_id, proc_name, base, status=None, runner=None, on_done=None) -> Readiness | None:
    """Readiness check of the selected procedure on the simulated bench (tools/readiness_check.py in a subprocess; no instrument I/O).  Returns the running
    Readiness (None when the tool is missing: the same message as the Tk Manager is shown)."""
    h = Readiness(parent, proc_id, proc_name, base, status, runner, on_done)
    return h if h.start() else None
