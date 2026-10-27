"""Qt twin of report_review.py: the 'Review uncertainties before generating the PDF' window.

Every test point with its assigned uncertainty, the standard that applied it (a drop-down per row, or for the selected rows), budget, scope minimum,
reported value, TUR and a status badge; filters All / Needs attention / Changed by me; 'Set standard for selected rows' + Apply; a typed uncertainty for
a point the lab scope does not cover; 'Reset changes'; Cancel; Generate PDF.  The model is the toolkit-free report_review_model.py (the same one the Tk
window uses); the engine is found and the models are built by report_review_flow.py (moved out of the Tk module unchanged).  The overrides are stored
exactly as before in details['uncertainty_review'] and report_pdf / report_snapshot apply and keep them; nothing here changes a limit, a pass / fail
result, an instrument command or the PDF layout.

    from qtui.screens import report_review
    details = report_review.ask(parent, procedure)         # details dict | None (cancelled) | report_review.UNAVAILABLE (use the plain popup)

`ask(parent, procedure, app=None)` has the contract of the Tk report_review.ask; ReviewWindow(parent, model, procedure, demo, details, position) mirrors the
Tk constructor, `.run()` returns the details dict or None.  Public methods and attributes keep the Tk names: refresh, choose, apply_bulk, on_default,
reset, edit_standards, details, generate, cancel, btn_ok, btn_reset, bulk_box, default_box, pills, hint, default_hint, filter (the current filter name).

Look: review_proto.py (approved).  The first column holds a check box that mirrors the row selection (Ctrl / Shift-click selects as before; the box is the
visible way to pick rows for 'Set standard for selected rows').
"""
from __future__ import annotations

import time

import report_pdf
import report_review_model as M
import ui_theme_core as core
from PySide6.QtCore import QEvent, QItemSelectionModel, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget)
from report_review_flow import COVERED, SHORT, UNAVAILABLE, asset_of, build_models, find_app, finish, hint_kinds, is_demo   # noqa: F401  (re-exported like the Tk module)

from ..table import CellDelegate, Column, DataTable
from ..theme import M as SP
from ..widgets import Badge, Banner, ModalDialog, PrimaryButton, SecondaryButton, SegmentedFilter, SectionHeader, label, rule
from .report_details import StandardsGrid, demo_title

BADGE = {M.AS_BUDGETED: 'good', M.RAISED: 'warn', M.NOT_IN_SCOPE: 'bad', M.CHANGED: 'info', M.MANUAL: 'warn', M.NO_UNC: 'neutral', M.ASSIGNED: 'warn'}
PILLS = (('As budgeted', 'good'), ('Raised to scope', 'warn'), ('Not in scope', 'bad'), ('Standard changed', 'info'), (M.MANUAL, 'warn'), (M.ASSIGNED, 'warn'))
NOTE = ('Reported = larger of Budget and Scope minimum, rounded up to 2 significant figures (k = 2), never below the lab’s A2LA scope minimum. '
        'Limits and pass / fail are never touched.')
DEMO_TEXT = 'DEMO DATA - NOT CALIBRATION EVIDENCE. This is a demo run: the PDF is stamped DEMO and nothing is recorded in Asset History.'
MAX_W, MAX_H, MIN_W, MIN_H = 1560, 860, 860, 520


def _qparent(parent):
    return parent if isinstance(parent, QWidget) else None


def ask(parent, procedure='', app=None):
    """The review window for the engine behind `parent`.  Returns the details dict, None when cancelled, or UNAVAILABLE (use the plain popup)."""
    built = build_models(parent, procedure, app)
    if built is UNAVAILABLE:
        return UNAVAILABLE
    models, demo = built
    details = None
    for n, model in enumerate(models, 1):
        win = ReviewWindow(parent, model, procedure, demo=demo, details=details, position=(n, len(models)))
        details = win.run()
        if details is None:
            return None
    return finish(models, details)


class _TypedEdit(QLineEdit):
    """The editor of a Reported cell the lab scope does not cover: only Enter keeps the text (a focus change or Esc leaves the cell as it was)."""
    entered = False


class _ReviewDelegate(CellDelegate):
    """The table's delegate plus the Reported-cell editor: one click opens it (as the Tk window), Enter commits, Esc cancels."""

    def __init__(self, table, owner: 'ReviewWindow'):
        super().__init__(table)
        self.owner = owner

    def _kind(self, index) -> str:
        col = self.table.source_model.columns[index.column()]
        if col.key == 'std' and not col.is_editable(self.table.row_of(index)):
            return 'text'                                           # a row with no drop-down (locked): plain text, not an empty box
        return col.kind

    def _is_typed(self, index) -> bool:
        return self.table.source_model.columns[index.column()].key == 'reported'

    def createEditor(self, parent, opt, index):
        if self._is_typed(index):
            ed = _TypedEdit(parent)
            ed.setText((self.table.row_of(index).typed or {}).get('text', ''))
            ed.setAccessibleName('Typed uncertainty')
            self.owner.typing_started(self.table.row_of(index))
            QTimer.singleShot(0, ed.selectAll)
            return ed
        return super().createEditor(parent, opt, index)

    def setEditorData(self, editor, index):
        if not isinstance(editor, _TypedEdit):
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, _TypedEdit):
            if editor.entered:
                self.owner.commit_typed(self.table.row_of(index), editor.text())
            return
        super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, opt, index):
        if isinstance(editor, _TypedEdit):
            r = opt.rect.adjusted(-40, 1, 0, -1)
            editor.setGeometry(r)
            return
        super().updateEditorGeometry(editor, opt, index)

    def eventFilter(self, obj, ev):
        if isinstance(obj, _TypedEdit) and ev.type() == QEvent.Type.KeyPress and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            obj.entered = True
        return super().eventFilter(obj, ev)

    def editorEvent(self, event, model, opt, index):
        if self._is_typed(index) and index.flags() & Qt.ItemFlag.ItemIsEditable:
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton and opt.rect.contains(event.position().toPoint()):
                self.table.edit(index)
                return True
        return super().editorEvent(event, model, opt, index)


class ReviewWindow(QDialog):
    last = None                      # the most recent window (the checks drive it)
    HEADS = ('Step', 'Test point', 'Tolerance', 'Standard used', 'Budget', 'Scope minimum', 'Reported (k=2)', 'TUR', 'Status')

    def __init__(self, parent, model, procedure='', demo=False, details=None, position=(1, 1)):
        super().__init__(_qparent(parent))
        self.parent_obj, self.model, self.procedure, self.demo = parent, model, procedure, demo
        ReviewWindow.last = self
        self.store = core.Settings('report_details')
        self.result = None
        self._reedit = None
        self._sel = set()
        self._closing = False
        self.setWindowTitle(demo_title('Review uncertainties before generating the PDF'))
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowCloseButtonHint
                            | Qt.WindowType.WindowMaximizeButtonHint)
        self._build(details or {}, position)
        self._fit()
        try:                                                        # 'use it for all points like this' rules saved in earlier runs
            import uncertainty_fixes
            import uncertainty_why
            self.rules_applied = uncertainty_why.apply_saved_rules(model, uncertainty_fixes.who_am_i())
        except Exception:
            self.rules_applied = 0
        self.refresh()
        if self.rules_applied:
            self._show_hint(f'{self.rules_applied} point(s) the lab scope does not cover use a saved rule (Status: {M.MANUAL}); '
                            'select one and press Why? / Fix to change it.', 'info')

    # ------------------------------------------------------------------------------------------------------------------ layout
    def _build(self, prior, position):
        m = self.model
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- header bar: title + subtitle, status pills
        bar = QFrame()
        bar.setProperty('surface', 'bar')
        self.head_grid = QGridLayout(bar)
        self.head_grid.setContentsMargins(SP.page_margin, SP.lg, SP.page_margin, SP.lg)
        self.head_grid.setHorizontalSpacing(SP.lg)
        self.head_grid.setVerticalSpacing(SP.sm)
        self.header = SectionHeader('Review uncertainties before generating the PDF', '', level='h2')
        self.head_grid.addWidget(self.header, 0, 0)
        self.pill_box = QWidget()
        pb = QHBoxLayout(self.pill_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(SP.sm)
        self.pills = {}
        for key, kind in PILLS:
            self.pills[key] = Badge('', kind)
            pb.addWidget(self.pills[key], 0, Qt.AlignmentFlag.AlignVCenter)
        self.head_grid.addWidget(self.pill_box, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.head_grid.setColumnStretch(0, 1)
        self._pills_below = False
        root.addWidget(bar)
        asset = m.asset or 'not entered'
        self.subtitle_base = f'{self.procedure or "Calibration"} · Asset {asset}' + (f' · meter {position[0]} of {position[1]}' if position[1] > 1 else '')
        if self.demo:
            wrap = QHBoxLayout()
            wrap.setContentsMargins(SP.page_margin, SP.sm, SP.page_margin, 0)
            self.demo_banner = Banner(DEMO_TEXT, 'warn')
            wrap.addWidget(self.demo_banner)
            root.addLayout(wrap)

        # ---- compact details strip
        strip = QFrame()
        strip.setProperty('surface', 'strip')
        g = QGridLayout(strip)
        g.setContentsMargins(SP.page_margin, SP.sm, SP.page_margin, SP.sm)
        g.setHorizontalSpacing(SP.sm)
        g.setVerticalSpacing(SP.sm)
        self.fields = {}
        for key in ('technician', 'temperature', 'humidity'):         # no longer asked here (the cover certificate carries them): the keys stay in the details, empty, so the report code is unchanged
            self.fields[key] = QLineEdit('')
        g.addWidget(label('Default standard', 'kvkey'), 0, 0)
        self.default_box = QComboBox()
        self.default_box.setFixedWidth(170)
        self.default_box.setAccessibleName('Default standard')
        self.default_box.activated.connect(lambda _i: self.on_default())
        g.addWidget(self.default_box, 0, 1)
        remembered = report_pdf.remembered_show_tar_tur()
        self.tar = QCheckBox('TAR on the PDF')
        self.tar.setChecked(bool(prior.get('show_tar', remembered.tar)))
        self.tur = QCheckBox('TUR on the PDF')
        self.tur.setChecked(bool(prior.get('show_tur', remembered.tur)))
        self.left_numeric = QCheckBox('As left data as numerical')
        self.left_numeric.setToolTip('Copy every As Found reading to As Left, so the As Left column is numerical instead of Same')
        self.left_numeric.setChecked(bool(prior.get('left_numeric', report_pdf.remembered_left_numeric())))
        g.addWidget(self.tar, 0, 2, 1, 2)
        g.addWidget(self.tur, 0, 4, 1, 2)
        g.addWidget(self.left_numeric, 0, 6, 1, 2)
        self.btn_standards = SecondaryButton('Standards used…')
        self.btn_standards.clicked.connect(self.edit_standards)
        g.addWidget(self.btn_standards, 0, 7, 1, 1, Qt.AlignmentFlag.AlignRight)
        g.setColumnStretch(6, 1)
        self.standards = prior.get('standards') or self.store.get('standards', []) or []
        root.addWidget(strip)

        # ---- filter / bulk bar
        tools = QHBoxLayout()
        tools.setContentsMargins(SP.page_margin, SP.md, SP.page_margin, SP.sm)
        tools.setSpacing(SP.sm)
        tools.addWidget(label('Show'))
        self.filter_bar = SegmentedFilter([(name, name, None) for name in M.FILTERS])
        self.filter_bar.currentChanged.connect(lambda _k: self.refresh())
        tools.addWidget(self.filter_bar)
        tools.addStretch(1)
        tools.addWidget(label('Set standard for selected rows'))
        self.bulk_box = QComboBox()
        self.bulk_box.setFixedWidth(170)
        self.bulk_box.setAccessibleName('Standard for the selected rows')
        tools.addWidget(self.bulk_box)
        self.btn_apply = SecondaryButton('Apply')
        self.btn_apply.clicked.connect(self.apply_bulk)
        tools.addWidget(self.btn_apply)
        self.btn_why = SecondaryButton('Why? / Fix\u2026')
        self.btn_why.setToolTip('For a point with no uncertainty: what is missing, and one-click ways to fix it')
        self.btn_why.setEnabled(False)
        self.btn_why.clicked.connect(lambda: self.why())
        tools.addWidget(self.btn_why)
        self.btn_assign = SecondaryButton('Assign uncertainty\u2026')
        self.btn_assign.setToolTip('For a point with no uncertainty: accept a suggested value with one tap, or enter your own (field_uncertainty.py)')
        self.btn_assign.setEnabled(False)
        self.btn_assign.clicked.connect(lambda: self.assign())
        tools.addWidget(self.btn_assign)
        root.addLayout(tools)
        cta = QHBoxLayout()                                         # 'No uncertainty for this point: Assign' (only while a point should carry one and has none)
        cta.setContentsMargins(SP.page_margin, 0, SP.page_margin, SP.sm)
        cta.setSpacing(SP.sm)
        self.cta = Banner('', 'warn')
        self.cta_btn = PrimaryButton('Assign')
        self.cta_btn.clicked.connect(lambda: self.assign(first=True))
        cta.addWidget(self.cta, 1)
        cta.addWidget(self.cta_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cta_row = QWidget()
        self.cta_row.setLayout(cta)
        self.cta_row.hide()
        root.addWidget(self.cta_row)

        # ---- the grid
        cols = [
            Column('pick', '', width=44, kind='checkbox', editable=True, getter=lambda r: r.spec.idx in self._sel, setter=self._set_picked),
            Column('step', self.HEADS[0], width=64, getter=lambda r: r.spec.step, natural=True, mono=True),
            Column('point', self.HEADS[1], width=240, stretch=True, getter=lambda r: f'{r.spec.nominal_text}  ·  {r.spec.description}'),
            Column('tol', self.HEADS[2], width=160, getter=lambda r: M.tolerance_text(r.spec) or '—', mono=True),
            Column('std', self.HEADS[3], width=186, kind='combo', getter=self._std_text, setter=self._set_std, editable=lambda r: not r.spec.locked,
                   choices=lambda r: [M.label(k) for k in self.model.options(r.spec.idx)], tone=lambda r: 'muted' if r.spec.locked else None),
            Column('budget', self.HEADS[4], width=128, align='right', mono=True, getter=lambda r: M.fmt(r.cur.budget, r.cur.unit) or '—'),
            Column('scope', self.HEADS[5], width=148, align='right', mono=True,
                   getter=lambda r: M.fmt(r.cur.cmc, r.cur.unit) or ('not in scope' if r.cur.status != M.NO_UNC else '—')),
            Column('scope_raw', 'Scope CMC (as published)', width=190, mono=True, getter=lambda r: r.scope_text or '—'),
            Column('reported', self.HEADS[6], width=160, align='right', mono=True, bold=True, getter=self._reported_text, editable=lambda r: r.can_type()),
            Column('tur', self.HEADS[7], width=110, align='right', mono=True, getter=lambda r: r.tur_text or '—'),
            Column('status', self.HEADS[8], width=186, kind='badge', getter=self._status_text, badge=lambda v, r: BADGE.get(self._status_text(r), 'neutral')),
        ]
        blue = lambda r: 'info' if r.status == M.CHANGED else None            # a changed standard turns the row's text blue (the status badge still says what the uncertainty did)
        for col in cols:
            if col.key in ('step', 'point', 'tol', 'budget', 'scope', 'scope_raw', 'reported', 'tur'):
                col.tone = blue
            elif col.key == 'std':
                _locked = col.tone
                col.tone = lambda r, _l=_locked: _l(r) or blue(r)
        self.table = DataTable(cols, m.rows, row_tone=self._tone, row_key=lambda r: r.spec.idx, multi=True, empty_text='No points to review')
        self.table.setItemDelegate(_ReviewDelegate(self.table, self))
        self.table.setAccessibleName('Test points and their uncertainties')
        self.table.selectionChangedRows.connect(self._on_selection)
        self.table.cellEdited.connect(self._cell_edited)
        self.table.rowActivated.connect(self._activate)
        self.table.itemDelegate().closeEditor.connect(self._editor_closed)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(SP.page_margin, 0, SP.page_margin, 0)
        wrap.addWidget(self.table)
        root.addLayout(wrap, 1)

        # ---- the hint line (what is not in scope / what to type / what is wrong with an entry) and the notes
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(SP.page_margin, SP.sm, SP.page_margin, 0)
        self.hint = Banner('', 'error')
        self.hint.hide()
        hint_row.addWidget(self.hint)
        root.addLayout(hint_row)
        foot = QHBoxLayout()
        foot.setContentsMargins(SP.page_margin, SP.md, SP.page_margin, SP.md)
        self.note = label(NOTE, 'hint', wrap=True)
        foot.addWidget(self.note, 1)
        root.addLayout(foot)

        # ---- buttons
        root.addWidget(rule())
        bottom = QFrame()
        bottom.setProperty('surface', 'barbottom')
        bb = QHBoxLayout(bottom)
        bb.setContentsMargins(SP.page_margin, SP.md, SP.page_margin, SP.md)
        bb.setSpacing(SP.sm)
        bb.addStretch(1)
        self.btn_cancel = SecondaryButton('Cancel')
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_reset = SecondaryButton('Reset changes')
        self.btn_reset.clicked.connect(self.reset)
        self.btn_ok = PrimaryButton('Generate PDF' if position[0] == position[1] else f'Next meter ({position[0]}/{position[1]})')
        self.btn_ok.setMinimumWidth(130)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.generate)
        for b in (self.btn_cancel, self.btn_reset, self.btn_ok):
            bb.addWidget(b)
        root.addWidget(bottom)
        self.setTabOrder(self.btn_cancel, self.btn_reset)
        self.setTabOrder(self.btn_reset, self.btn_ok)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        below = self.width() < 1120                                 # the pills never squeeze the title: they drop under it in a narrow window
        if below != self._pills_below:
            self._pills_below = below
            if below:
                self.head_grid.addWidget(self.pill_box, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            else:
                self.head_grid.addWidget(self.pill_box, 0, 1, 1, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _fit(self):
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        w, h = min(MAX_W, scr.width() - 60), min(MAX_H, scr.height() - 110)
        self.setMinimumSize(min(MIN_W, w), min(MIN_H, h))
        self.resize(w, h)
        par = self.parentWidget().window() if self.parentWidget() is not None else None
        geo = par.frameGeometry() if par is not None and par.isVisible() else scr
        r = self.frameGeometry()
        r.moveCenter(geo.center())
        self.move(max(scr.left(), min(r.left(), scr.right() - r.width())), max(scr.top(), min(r.top(), scr.bottom() - r.height())))

    # ------------------------------------------------------------------------------------------------------------------ cell content
    def _std_text(self, r) -> str:
        s = r.spec
        if s.locked and s.q.get('kind') == 'FREQ':
            return M.LOCKED_FREQUENCY
        if s.locked:
            return s.std_label or '—'
        return M.label(r.standard)

    def field_gap(self, r) -> bool:
        """The point should carry an uncertainty, prints none and has no assignment yet."""
        return r.spec.idx in (getattr(self.model, 'field_missing', None) or {}) and r.assigned is None and r.typed is None

    def _reported_text(self, r) -> str:
        rep = r.reported_text or '—'
        if r.can_type() and r.typed is None:
            rep += '  [type]'                                            # a point the scope does not cover: click to type an uncertainty
        elif self.field_gap(r):
            rep += '  [assign]'                                          # no uncertainty for this point: Assign (field_uncertainty)
        return rep

    def _status_text(self, r):
        """A row whose standard the person changed keeps showing what the uncertainty did (As budgeted / Raised to scope); the row text turns blue instead."""
        return r.cur.status if r.status == M.CHANGED else r.status

    def _tone(self, r):
        if r.spec.locked and r.cur.status in (M.NO_UNC, M.AS_BUDGETED):
            return None
        return {M.MANUAL: 'warn', M.NOT_IN_SCOPE: 'fail'}.get(r.status)

    def row_values(self, r) -> tuple:
        """The text of every cell of row `r` (the Tk row_values, without the drop-down arrow)."""
        s, e = r.spec, r.cur
        return (s.step, f'{s.nominal_text}  ·  {s.description}', M.tolerance_text(s) or '—', self._std_text(r), M.fmt(e.budget, e.unit) or '—',
                M.fmt(e.cmc, e.unit) or ('not in scope' if e.status != M.NO_UNC else '—'), self._reported_text(r), r.tur_text or '—', r.status)

    # ------------------------------------------------------------------------------------------------------------------ content
    @property
    def filter(self) -> str:
        return self.filter_bar.current()

    def set_filter(self, name: str) -> None:
        self.filter_bar.set_current(name)
        self.refresh()

    def refresh(self):
        m = self.model
        name = self.filter
        if name == 'All':
            self.table.set_predicate(None)
        else:
            vis = {id(r) for r in m.visible(name)}
            self.table.set_predicate(lambda r: id(r) in vis)
        self.table.refresh()
        c = m.counts()
        with_unc = c['all'] - c.get(M.NO_UNC, 0)
        self.header.set_subtitle(f'{self.subtitle_base} · {with_unc} of {c["all"]} points carry an uncertainty')
        for key, pill in self.pills.items():
            pill.setText(f'{c.get(key, 0)} {SHORT.get(key, key.lower())}')
            if key == M.ASSIGNED:
                pill.setVisible(bool(c.get(key, 0)))                  # only while something is assigned in the field
        gaps = [r for r in m.rows if self.field_gap(r)]
        self.cta_row.setVisible(bool(gaps))
        if gaps:
            self.cta.set_text(('No uncertainty for this point: ' if len(gaps) == 1 else f'No uncertainty for {len(gaps)} points: ') +
                              ('assign a suggested value or enter your own. ' if not getattr(self.model, 'field_demo', self.demo) else 'assign one (demo: kept for this session only). ') +
                              'Pass / fail, limits and the run are not affected.')
            self.cta_btn.setText('Assign' if len(gaps) == 1 else f'Assign ({len(gaps)})')
        for key, text in (('All', f'All {c["all"]}'), ('Needs attention', f'Needs attention {c["attention"]}'), ('Changed by me', f'Changed by me {c["changed"]}')):
            self.filter_bar.set_count(key, {'All': c['all'], 'Needs attention': c['attention'], 'Changed by me': c['changed']}[key])
        n_bad = c.get(M.NOT_IN_SCOPE, 0)
        self.default_hint = (f'{n_bad} point(s) not in the lab scope (red): printed as before. Click the Reported cell [type] to enter an uncertainty.' if n_bad else '')
        if self._reedit is None and not self._typing():
            self._show_hint(self.default_hint)
        opts = sorted({k for r in m.rows if not r.spec.locked for k in m.options(r.spec.idx)}, key=lambda k: M.SOURCE_STANDARDS.index(k) if k in M.SOURCE_STANDARDS else 9)
        self.default_box.clear()
        self.default_box.addItems([M.label(k) for k in opts])
        self.default_box.setCurrentText(M.label(m.default_std))
        self.default_box.setEnabled(bool(opts))
        self.btn_reset.setEnabled(bool(c['changed'] or m.default_std != m.engine_default))
        self.on_select()

    def _show_hint(self, text, kind='error'):
        self.hint.set_kind(kind)
        self.hint.set_text(text)
        self.hint.setVisible(bool(text))

    def _typing(self) -> bool:
        return self.table.state() == QAbstractItemView.State.EditingState

    def hint_text(self) -> str:
        return self.hint.text_label.text() if self.hint.isVisible() else ''

    def _on_selection(self, rows):
        self._sel = {r.spec.idx for r in rows}
        self.table.refresh()
        self.on_select()

    def selected_indexes(self) -> list:
        return [r.spec.idx for r in self.table.selected_rows()]

    def on_select(self, _e=None):
        idx = self.selected_indexes()
        common = self.model.common_options(idx) if idx else []
        keep = self.bulk_box.currentText()
        self.bulk_box.clear()
        self.bulk_box.addItems([M.label(k) for k in common])
        self.bulk_box.setEnabled(bool(common))
        if keep and M.key_of(keep) in common:
            self.bulk_box.setCurrentText(keep)
        else:
            self.bulk_box.setCurrentIndex(-1)                  # nothing chosen yet (the Tk box is empty until a standard is picked)
        self.btn_apply.setEnabled(bool(common))
        one = self.model.rows[idx[0]] if len(idx) == 1 else None
        self.btn_why.setEnabled(bool(one is not None and (one.cur.status == M.NOT_IN_SCOPE or one.typed is not None)))
        self.btn_assign.setEnabled(bool(one is not None and one.typed is None and (self.field_gap(one) or one.assigned is not None or one.spec.printed.get('Uncertainty'))))

    def why(self, idx=None):
        """The 'Why is there no uncertainty?' panel for the selected row (or `idx`).  Returns its outcome ('applied' | 'flagged' | None)."""
        from .uncertainty_why_dialog import WhyDialog
        if idx is None:
            sel = self.selected_indexes()
            if len(sel) != 1:
                return None
            idx = sel[0]
        out = WhyDialog(self, self.model, idx, asset=self.model.asset).run()
        if out == 'applied':
            self.refresh()
            self._show_hint('')
        elif out == 'flagged':
            self._show_hint('Flagged for quality: it is on the uncertainty issues list.', 'info')
        return out

    def assign(self, idx=None, first=False):
        """The 'Assign uncertainty' panel (field_uncertainty) for the selected row, `idx`, or (first=True) the first point that has none.  Returns its outcome."""
        from .field_uncertainty_panel import AssignDialog
        if idx is None:
            if first:
                gaps = [r.spec.idx for r in self.model.rows if self.field_gap(r)]
                if not gaps:
                    return None
                idx = gaps[0]
            else:
                sel = self.selected_indexes()
                if len(sel) != 1:
                    return None
                idx = sel[0]
        out = AssignDialog(self, self.model, idx, asset=self.model.asset, demo=bool(getattr(self.model, 'field_demo', self.demo))).run()
        if out in ('assigned', 'withdrawn'):
            self.refresh()
            self._show_hint('')
        return out

    # ------------------------------------------------------------------------------------------------------------------ editing
    def _set_picked(self, row, on):
        """The check box of a row: select / deselect that row (additive)."""
        t = self.table
        for i in range(t.proxy.rowCount()):
            ix = t.proxy.index(i, 0)
            if t.row_of(ix) is row:
                last = t.proxy.columnCount() - 1
                from PySide6.QtCore import QItemSelection
                sel = QItemSelection(ix, t.proxy.index(i, last))
                t.selectionModel().select(sel, (QItemSelectionModel.SelectionFlag.Select if on else QItemSelectionModel.SelectionFlag.Deselect))
                break
        (self._sel.add if on else self._sel.discard)(row.spec.idx)

    def _set_std(self, row, text):
        self._changed_std = self.model.set_standard(row.spec.idx, text)

    def _cell_edited(self, row, key, _old, _new):
        if key == 'std':
            QTimer.singleShot(0, self.refresh)                      # after the editor has closed

    def choose(self, idx, text):
        """Set the standard of one row from the drop-down text (synchronous: what the cell editor does after it closes)."""
        self.model.set_standard(idx, text)
        self.refresh()

    def typing_started(self, row):
        unit = row.entry_hint()
        self._show_hint(f'Type the uncertainty (k = 2) for step {row.spec.step}, for example 3.5 {unit}; a bare number is in {unit}. '
                        'Enter keeps it, empty clears it, Esc cancels.', 'info')

    def commit_typed(self, row, text):
        """Enter in the typed editor: keep it (ok), or say what is wrong and keep the editor open with the text."""
        ok, msg = self.model.set_typed(row.spec.idx, text)
        if ok:
            self._show_hint('')
            QTimer.singleShot(0, self.refresh)
        else:
            self._reedit = (row, text, msg)
            self._show_hint(msg)

    def _editor_closed(self, editor, _hint):
        self._closed_at = time.monotonic()
        if self._reedit is not None:
            row, text, msg = self._reedit
            QTimer.singleShot(0, lambda: self._reopen(row, text, msg))
        elif isinstance(editor, _TypedEdit):
            self._show_hint(self.default_hint)                      # Esc / focus change: the cell stays as it was

    def _reopen(self, row, text, msg):
        self._reedit = None
        t = self.table
        col = t.column_index('reported')
        for i in range(t.proxy.rowCount()):
            ix = t.proxy.index(i, col)
            if t.row_of(ix) is row:
                t.edit(ix)
                ed = t.indexWidget(ix)
                if isinstance(ed, QLineEdit):
                    ed.setText(text)
                    ed.selectAll()
                self._show_hint(msg)                                # what is wrong stays on screen (the editor opening wrote the prompt)
                break

    def _activate(self, row):
        """Enter on a row: open its drop-down, or the typed entry of a point the scope does not cover."""
        if time.monotonic() - getattr(self, '_closed_at', 0.0) < 0.35:
            return                                                  # the Enter that committed a cell editor must not open the next one
        t = self.table
        key = 'std' if not row.spec.locked else ('reported' if row.can_type() else None)
        if key is None:
            if self.field_gap(row):
                QTimer.singleShot(0, lambda: self.assign(row.spec.idx))        # no uncertainty for this point: Assign
            return
        col = t.column_index(key)
        for i in range(t.proxy.rowCount()):
            ix = t.proxy.index(i, col)
            if t.row_of(ix) is row:
                t.edit(ix)
                return

    def apply_bulk(self):
        idx = self.selected_indexes()
        text = self.bulk_box.currentText()
        if idx and text:
            self.model.set_standard_many(idx, text)
            self.refresh()

    def on_default(self, _e=None):
        self.model.set_default(self.default_box.currentText())
        self.refresh()

    def reset(self):
        self.model.reset()
        self.refresh()

    def edit_standards(self):
        dlg = ModalDialog(self, 'Standards used', width=620)
        dlg.setWindowTitle(demo_title('Standards used'))
        dlg.title_label.setText('Standards used (kept with the report record; optional)')
        grid = StandardsGrid(self.standards)
        dlg.body.addLayout(grid.layout)

        def ok():
            self.standards = grid.values()
        dlg.add_button('Cancel', cancel=True)
        dlg.add_button('OK', role='primary', default=True, callback=ok)
        dlg.run()

    # ------------------------------------------------------------------------------------------------------------------ finish
    def details(self) -> dict:
        d = {k: e.text().strip() for k, e in self.fields.items()}
        d['standards'] = [dict(s) for s in self.standards]
        d['procedure'] = self.procedure
        d['show_tar'], d['show_tur'] = bool(self.tar.isChecked()), bool(self.tur.isChecked())
        d['show_tar_tur'] = report_pdf.TarTur(d['show_tar'], d['show_tur'])
        d['left_numeric'] = bool(self.left_numeric.isChecked())
        return d

    def generate(self):
        d = self.details()
        report_pdf.remember_show_tar_tur(d['show_tar_tur'])
        report_pdf.remember_left_numeric(d['left_numeric'])
        self.store.set('standards', d['standards'])
        self.store.save()
        self.result = d
        self.accept()

    def cancel(self):
        self.result = None
        self.reject()

    def run(self):
        self.exec()
        return self.result
