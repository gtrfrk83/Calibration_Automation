"""Qt twin of labregistry_ui.HistoryPanel: the Asset History tab (instruments with reports on this computer, the reports of the selected instrument, the
points of the selected report), 'Regenerate PDF...' (report_snapshot.regenerate: ask where to save, never overwrite without asking), 'Open report PDF',
the drift chart of a point, and the small 'what would you like to do' question.

    AssetHistoryPanel(parent)            a QWidget the Manager puts in its History tab (Tk: HistoryPanel(parent), a ttk.Frame)

Same constructor signature, same public methods (refresh, show_runs, show_points, regenerate_pdf, open_report, show_drift, _selected_run_id,
_show_regen_hint, _runs_double, _runs_menu), the same texts, questions and order of questions, the same data (labregistry / report_snapshot, read only
here).  Look changes only: DataTable (sortable, resizable, badges), a splitter between the three tables, a themed drift chart.
Dialogs go through the module functions `_info`, `_ask_yes_no`, `_ask_ok_cancel`, `_error`, `_save_file`, `_open_file` (a test replaces them).
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date

import demo_history
import labregistry as reg
import report_snapshot as snap
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMenu, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from .. import theme
from ..table import Column, DataTable
from ..theme import M
from ..widgets import Banner, MessageDialog, ModalDialog, PrimaryButton, SearchField, SecondaryButton, label
from ._share import ShareWidth
from .report_details import demo_title

RESULT_BADGE = {'PASS': 'good', 'OUT OF TOLERANCE': 'bad'}


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# dialogs (module level so a test can answer them; every one is parented to the panel's window like the Tk `parent=`)
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def _info(parent, title, text):
    MessageDialog(parent, 'info', demo_title(title), text).run()


def _error(parent, title, text):
    MessageDialog(parent, 'error', demo_title(title), text).run()


def _ask_yes_no(parent, title, text, *, default_no=True):
    """Yes / No with the warning icon; the preselected button is 'No' (Tk: default='no') unless default_no is False."""
    buttons = (('Yes', 'yes', None), ('No', 'no', 'primary')) if default_no else (('Yes', 'yes', 'primary'), ('No', 'no', None))
    return MessageDialog(parent, 'warning', demo_title(title), text, buttons=buttons, cancel_key='no').run() == 'yes'


def _ask_ok_cancel(parent, title, text):
    return MessageDialog(parent, 'question', demo_title(title), text, buttons=(('OK', 'ok', 'primary'), ('Cancel', 'cancel', None)), cancel_key='cancel').run() == 'ok'


def _save_file(parent, title, initial_dir, initial_file, filter_text, default_ext='.pdf'):
    """The save-as dialog; the overwrite question is asked by the caller, so Qt's own is switched off.  '' = cancelled."""
    start = os.path.join(initial_dir, initial_file) if initial_dir else initial_file
    path, _flt = QFileDialog.getSaveFileName(parent, title, start, filter_text, options=QFileDialog.Option.DontConfirmOverwrite)
    if path and default_ext and not os.path.splitext(path)[1]:
        path += default_ext
    return path


def _open_file(path):
    """The system viewer for `path` (Windows: os.startfile; macOS: open; elsewhere xdg-open).  OSError is the caller's to report."""
    try:
        os.startfile(path)                                    # Windows
    except AttributeError:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])


# ================================================================================================ asset history
class AssetHistoryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = []
        self.demo = False                                        # True = showing the fictional demonstration history (Help > Show demonstration asset history)
        self.db = None                                           # the demo registry file while demo is on (read only); None = the real registry
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(M.sm)
        self.banner = Banner(f'<b>{demo_history.BANNER}</b>', 'warn')
        self.banner.setAccessibleName('Demonstration data notice')
        self.banner.hide()
        root.addWidget(self.banner)

        bar = QHBoxLayout()
        bar.setSpacing(M.sm)
        bar.addWidget(label('Find'))
        self.term = SearchField('Instrument ID, model or serial number', delay_ms=120)
        self.term.setMinimumWidth(300)
        self.term.queryChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.term)
        bar.addWidget(label('Instrument ID, model or serial number', 'hint'))
        self.btn_refresh = SecondaryButton('Refresh')
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        self.note = label('', 'sub')
        bar.addWidget(self.note)
        root.addLayout(bar)

        tone = lambda r: 'fail' if (r['overdue'] or r['failed']) else None             # noqa: E731
        self.assets = DataTable([
            Column('asset', 'Instrument ID', width=150, getter=lambda r: r['asset_id']),
            Column('model', 'Instrument', width=250, stretch=True),
            Column('serial', 'Serial number', width=140),
            Column('runs', 'Reports', width=80, align='right'),
            Column('last', 'Last report', width=120, mono=True),
            Column('result', 'Last result', width=170, kind='badge', badge_map=RESULT_BADGE),
            Column('due', 'Next due', width=170, mono=True),
        ], row_key=lambda r: r['asset_id'], multi=False, row_tone=tone, empty_text='No instruments')
        self._share_assets = ShareWidth(self.assets, (150, 250, 140, 80, 120, 170, 170), (0.8, 1.6, 1.0, 0.4, 0.7, 1.0, 0.8))
        self.assets.setAccessibleName('Instruments with reports')
        self.assets.selectionChangedRows.connect(lambda _rows: self.show_runs())

        self.runs = DataTable([
            Column('date', 'Report date', width=150, mono=True),
            Column('procedure', 'Procedure', width=330, stretch=True),
            Column('tech', 'Technician', width=150),
            Column('points', 'Points', width=80, align='right'),
            Column('failed', 'Out of tol.', width=100, align='right'),
            Column('file', 'Report file', width=330),
        ], row_key=lambda r: r['id'], multi=False, row_tone=lambda r: 'fail' if r['fail'] else None, empty_text='No reports')
        self._share_runs = ShareWidth(self.runs, (150, 330, 150, 80, 100, 330), (0.9, 1.6, 0.9, 0.4, 0.5, 1.4))
        self.runs.setAccessibleName('Reports of the selected instrument')
        self.runs.selectionChangedRows.connect(lambda _rows: self.show_points())
        self.runs.rowActivated.connect(self._runs_double)                                      # double-click (or Enter): regenerate the PDF
        self.runs.customContextMenuRequested.disconnect()                                      # the DataTable's copy menu is replaced by the report menu
        self.runs.customContextMenuRequested.connect(self._runs_menu)

        self.points = DataTable([
            Column('section', 'Section', width=130),
            Column('desc', 'Test point', width=300, stretch=True, getter=lambda r: r['description']),
            Column('nominal', 'Nominal', width=120, align='right', mono=True),
            Column('low', 'Low limit', width=100, align='right', mono=True),
            Column('high', 'High limit', width=100, align='right', mono=True),
            Column('found', 'As found', width=110, align='right', mono=True),
            Column('unit', 'Units', width=70),
            Column('result', 'Result', width=80),
            Column('pct', '% of tol.', width=90, align='right', mono=True),
        ], row_key=lambda r: r['n'], multi=False, row_tone=lambda r: 'fail' if r['result'] == 'FAIL' else None, empty_text='No points')
        self._share_points = ShareWidth(self.points, (130, 300, 120, 100, 100, 110, 70, 80, 90), (0.8, 1.6, 0.9, 0.8, 0.8, 0.8, 0.4, 0.5, 0.6))
        self.points.setAccessibleName('Points in the selected report')
        self.points.rowActivated.connect(lambda _r: self.show_drift())

        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(M.sm)
        split.addWidget(self._pane(None, self.assets))
        split.addWidget(self._pane(label('Reports for the selected instrument (newest first)', 'section'), self.runs))
        legend = label('% of tolerance = how much of the allowed error the as-found reading used (0 on nominal, 100 at a limit)', 'hint')
        split.addWidget(self._pane(label('Points in the selected report', 'section'), self.points, legend))
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 5)
        split.setSizes([200, 170, 320])
        self.splitter = split
        root.addWidget(split, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(M.sm)
        self.btn_drift = PrimaryButton('Drift of selected point...')
        self.btn_drift.clicked.connect(self.show_drift)
        self.btn_open = SecondaryButton('Open report PDF')
        self.btn_open.clicked.connect(self.open_report)
        self.btn_regen = SecondaryButton('Regenerate PDF...')
        self.btn_regen.clicked.connect(self.regenerate_pdf)
        self.regen_note = label('', 'sub')
        for w in (self.btn_drift, self.btn_open, self.btn_regen):
            buttons.addWidget(w)
        buttons.addSpacing(M.sm)
        buttons.addWidget(self.regen_note, 1)
        root.addLayout(buttons)

        self.menu = QMenu(self)
        self.act_regen = self.menu.addAction('Regenerate PDF...')
        self.act_regen.triggered.connect(self.regenerate_pdf)
        self.act_open = self.menu.addAction('Open report PDF')
        self.act_open.triggered.connect(self.open_report)
        self.refresh()

    @staticmethod
    def _pane(heading, table, trailing=None):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(M.xs)
        if heading is not None or trailing is not None:
            row = QHBoxLayout()
            row.setSpacing(M.md)
            if heading is not None:
                row.addWidget(heading)
            if trailing is not None:
                row.addWidget(trailing, 1)
            else:
                row.addStretch(1)
            v.addLayout(row)
        v.addWidget(table, 1)
        return w

    # ------------------------------------------------------------------------------------------------------------------ demonstration history
    def set_demo(self, on: bool):
        """Show the fictional demonstration history (True) or the real one (False).  Returns the state afterwards (a demo file that can not be made or
        fails its checks leaves the real history showing and says why).  The real registry is not opened or changed by this; the demo file is only read."""
        if on:
            path = demo_history.ensure()
            ok, why = demo_history.verify(path) if path else (False, 'The demonstration history could not be created in your data folder.')
            if not ok:
                _error(self._toplevel(), 'Demonstration asset history', why)
                on = False
            else:
                self.db = path
        if not on:
            self.db = None
        self.demo = bool(on)
        self.banner.setVisible(self.demo)
        for w in (self.btn_regen, self.btn_open):
            w.setEnabled(not self.demo)
        self.act_regen.setEnabled(not self.demo)
        self.act_open.setEnabled(not self.demo)
        self.term.setText('')                                    # a search typed for the other history would only hide rows
        self.refresh()
        return self.demo

    # ------------------------------------------------------------------------------------------------------------------ data
    def _toplevel(self):
        return self.window()

    def refresh(self):
        rows = []
        for r in reg.assets_overview(self.term.text().strip(), db=self.db):
            if self.demo and not str(r['asset_id']).upper().startswith(demo_history.PREFIX):
                continue                                         # belt and braces: demonstration mode never shows a non-DEMO asset
            due, _ = reg.next_due(r['asset_id'], db=self.db)
            overdue = bool(due and due < date.today())
            rows.append(dict(r, overdue=overdue, result='OUT OF TOLERANCE' if r['failed'] else 'PASS', last=r['last'][:10],
                             due=(due.isoformat() + ('  OVERDUE' if overdue else '')) if due else ''))
        self.assets.set_rows(rows)
        if self.demo:
            self.note.setText(f'{len(rows)} fictional instrument(s). Nothing here is a real calibration record.')
        else:
            self.note.setText(f'{len(rows)} instrument(s) with reports on this computer.' if rows else 'No reports recorded yet: history is added each time a PDF report is exported.')
        self.show_runs()

    def _asset(self):
        sel = self.assets.selected_rows()
        return sel[0]['asset_id'] if sel else None

    def show_runs(self):
        keep = [r['id'] for r in self.runs.selected_rows()]
        asset = self._asset()
        rows = []
        for r in (reg.runs_for(asset, db=self.db) if asset else []):
            rows.append(dict(r, date=r['run_at'].replace('T', ' ')[:16], tech=r['technician'], points=r['total'], failed=r['failed'] or '',
                             file=os.path.basename(r['report_file']), fail=bool(r['failed']), failed_n=r['failed'], procedure=r['procedure']))
        self.runs.set_rows(rows, keep_selection=False)
        pick = next((r for r in rows if r['id'] in keep), rows[0] if rows else None)
        if pick is not None:
            self.runs.select_rows([pick])
        self.show_points()

    def show_points(self):
        sel = self.runs.selected_rows()
        run_id = int(sel[0]['id']) if sel else None
        self._points = reg.points_for(run_id, db=self.db) if run_id is not None else []
        rows = []
        for n, p in enumerate(self._points):
            pct = '' if p['dev_pct'] is None else f"{p['dev_pct']:+.0f}%"
            rows.append(dict(p, n=n, pct=pct))
        self.points.set_rows(rows, keep_selection=False)
        self._show_regen_hint(run_id)

    # ------------------------------------------------------------------------------------------------------------------ regenerate the PDF of an event
    def _show_regen_hint(self, run_id):
        """One line saying whether the selected event can be printed again (report_snapshot.availability); never raises."""
        if self.demo:
            self.regen_note.setText(demo_history.PDF_HINT if run_id is not None else '')
            return
        try:
            self.regen_note.setText(snap.availability(run_id)[1] if run_id is not None else '')
        except Exception:
            self.regen_note.setText('')

    def _selected_run_id(self):
        sel = self.runs.selected_rows()
        return int(sel[0]['id']) if sel else None

    def regenerate_pdf(self):
        """Print the selected event's report again (report_snapshot.regenerate): ask where to save, never overwrite without asking."""
        parent = self._toplevel()
        if self.demo:                                            # demonstration events are never printed: no dialog, no file, nothing written
            _info(parent, 'Regenerate PDF', demo_history.PDF_REFUSAL)
            return
        run_id = self._selected_run_id()
        if run_id is None:
            _info(parent, 'Regenerate PDF', 'Select a report in the middle table first.')
            return

        def choose(default_name, original):
            initial_dir = os.path.dirname(original) if original and os.path.isdir(os.path.dirname(original)) else ''
            return _save_file(parent, 'Save regenerated report', initial_dir, default_name, 'PDF report (*.pdf)')

        def overwrite(path, is_original):
            what = 'This is the file the original report was saved to.\n\n' if is_original else ''
            return _ask_yes_no(parent, 'Replace file?', f'{what}{os.path.basename(path)} already exists. Replace it?', default_no=True)

        result = snap.regenerate(run_id, choose_path=choose, confirm_overwrite=overwrite,
                                 confirm_rebuilt=lambda text: _ask_ok_cancel(parent, 'Rebuild from history rows', text + '\n\nContinue?'))
        if result.message:                                  # a cancel has no message
            _info(parent, 'Regenerate PDF', result.message)

    def _runs_double(self, row=None):
        """Double-click on a report: regenerate the PDF (a click on empty space gives no row and does nothing)."""
        if row is None:
            return
        self.regenerate_pdf()                                 # double-click goes straight to regenerate (Open stays on the button / menu)

    def _runs_menu(self, pos):
        """Right click on a report: select it and offer Regenerate PDF... / Open report PDF."""
        ix = self.runs.indexAt(pos)
        row = self.runs.row_of(ix) if ix.isValid() else None
        if row is not None:
            self.runs.select_rows([row])
            self.menu.popup(self.runs.viewport().mapToGlobal(pos))

    def open_report(self):
        if self.demo:
            _info(self._toplevel(), 'Report', 'Demonstration events have no PDF.')
            return
        sel = self.runs.selected_rows()
        run = next((r for r in reg.runs_for(self._asset() or '') if sel and r['id'] == sel[0]['id']), None)
        if not run or not run['report_file'] or not os.path.exists(run['report_file']):
            _info(self._toplevel(), 'Report', 'The PDF is not at the place it was saved (it may have been moved or deleted).')
            return
        try:
            _open_file(run['report_file'])
        except OSError as exc:
            _error(self._toplevel(), 'Report', str(exc))

    def show_drift(self):
        asset, sel = self._asset(), self.points.selected_rows()
        if not asset or not sel:
            _info(self._toplevel(), 'Drift', 'Select a test point in the lower table first.')
            return
        p = self._points[sel[0]['n']]
        open_drift_chart(self._toplevel(), asset, p['section'], p['description'], p['unit'], db=self.db)


# ================================================================================================ small windows
def choose_action(parent):
    """Small three-button question: 'regenerate' / 'open' / None."""
    dlg = ModalDialog(parent, 'Report', width=520)
    dlg.setWindowTitle(demo_title('Report'))
    dlg.title_label.setText('What would you like to do with this report?')
    dlg.sub_label.setText('Regenerate prints it again from the record saved when it was issued (it asks where to save).')
    dlg.sub_label.show()
    dlg.add_button('Regenerate PDF...', role='primary', result='regenerate', default=True)
    dlg.add_button('Open saved PDF', result='open')
    dlg.add_button('Cancel', result='cancel', cancel=True)
    out = dlg.run()
    return out if out in ('regenerate', 'open') else None


class DriftChart(QWidget):
    """As-found error as a % of the tolerance, one point per report: 0 = on nominal, +100 / -100 = at a limit (the Tk canvas, painted from the theme)."""
    L, R, T, B = 56, 70, 22, 44

    def __init__(self, data, unit='', parent=None):
        super().__init__(parent)
        self.points = [(d, f, v) for d, f, v in data if v is not None]
        self.unit = unit
        self.setMinimumSize(560, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName('Drift chart')

    def sizeHint(self):
        return QSize(760, 300)

    def paintEvent(self, _ev):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.setPen(QPen(QColor(t['border']), 1))
        p.setBrush(QColor(t['card']))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), M.radius_md, M.radius_md)
        f = QFont(self.font())
        f.setPixelSize(M.font_small)
        p.setFont(f)
        L, R, T, B = self.L, self.R, self.T, self.B
        pts = self.points
        if len(pts) < 1:
            p.setPen(QColor(t['muted']))
            p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, 'No numeric history for this point yet.')
            return
        top = max(120.0, max(abs(v) for _, _, v in pts) * 1.15)
        y = lambda v: T + (top - v) / (2 * top) * (H - T - B)                    # noqa: E731
        n = len(pts)
        x = lambda i: L + (W - L - R) * (0.5 if n == 1 else i / (n - 1))          # noqa: E731
        p.fillRect(QRectF(L, y(100), W - R - L, y(-100) - y(100)), QColor(t['good_bg']))
        for v in (-100, -50, 0, 50, 100):
            pen = QPen(QColor(t['bad'] if abs(v) == 100 else t['border']), 1)
            if v:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(L, y(v)), QPointF(W - R, y(v)))
            p.setPen(QColor(t['muted']))
            p.drawText(QRectF(0, y(v) - 10, L - 6, 20), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f'{v:+d}%' if v else '0')
        if n > 1:
            p.setPen(QPen(QColor(t['primary']), 2))
            p.drawPolyline(QPolygonF([QPointF(x(i), y(v)) for i, (_d, _f, v) in enumerate(pts)]))
        for i, (d, fnd, v) in enumerate(pts):
            bad = abs(v) > 100
            p.setPen(QPen(QColor(t['card']), 1.5))
            p.setBrush(QColor(t['bad'] if bad else t['primary']))
            p.drawEllipse(QPointF(x(i), y(v)), 4.5, 4.5)
            p.setPen(QColor(t['muted']))
            p.drawText(QRectF(x(i) - 50, H - B + 6, 100, 18), Qt.AlignmentFlag.AlignCenter, str(d)[:10])
            p.setPen(QColor(t['text']))
            p.drawText(QRectF(x(i) - 60, y(v) - 26, 120, 18), Qt.AlignmentFlag.AlignCenter, f'{fnd} {self.unit}'.strip())


def open_drift_chart(parent, asset, section, description, unit='', db=None):
    data = reg.drift(asset, section, description, db=db)
    dlg = ModalDialog(parent, 'Drift', width=820)
    dlg.setWindowTitle(demo_title('Drift') + (' [DEMONSTRATION DATA]' if db is not None else ''))
    dlg.title_label.setText(f'{asset}  -  {description}')
    dlg.sub_label.setText(('DEMONSTRATION DATA (fictional)   |   ' if db is not None else '') +
                          f'{section}   |   as-found error as a % of the tolerance, one point per report.  0 = on nominal; +100 / -100 = at a limit.')
    dlg.sub_label.show()
    dlg.chart = DriftChart(data, unit)
    dlg.body.addWidget(dlg.chart)
    dlg.add_button('Close', role='primary', cancel=True, default=True)
    dlg.run()
