"""The 'Assign uncertainty' panel: what a field technician uses when a test point has no uncertainty.  The logic is field_uncertainty.py (toolkit-free); this is the window.

    AssignDialog(parent, model, idx, asset='', demo=False).run()    -> 'assigned' | None      (model: report_review_model.ReviewModel annotated by field_uncertainty.annotate)
    FieldAssignmentsDialog(parent).run()                            the lab owner's list of every assignment, with CSV export and 'Withdraw'
    open_for_app(parent, app)                                       from a running procedure window: builds the model of the points recorded so far and opens the panel

The window shows the point (function, nominal, frequency, range, calibrator / standard, tolerance), WHY it has no uncertainty (uncertainty_why.diagnose), ranked
SUGGESTIONS each with a one-tap 'Use this', and 'Enter my own value' (value + unit in the point's own unit, a required reason, the technician's name).  It can apply to this
point only (default) or to the other points of the same kind that the choice can safely cover (the count is shown and confirmed first).  A point that already prints a
computed uncertainty is only touched after 'Replace the computed value' is ticked and a reason is given.  Nothing here changes a limit, a pass / fail result, a reading, an
instrument command or a prompt.  Demo: assignments are kept in memory for the session and never saved.

Tests replace the hooks `confirm(title, text) -> bool`, `ask_save_path() -> str`, `ask_withdraw() -> (who, reason) | None`.
"""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QRadioButton, QScrollArea, QVBoxLayout, QWidget)

import field_uncertainty as F
import report_review_model as M
import ui_theme_core as core
import uncertainty_why as W

from ..table import Column, DataTable
from ..theme import M as SP
from ..widgets import Badge, Banner, ModalDialog, PrimaryButton, SecondaryButton, label, rule

SETTINGS = 'field_uncertainty'
MARK = {'missing': ('✗', 'bad'), 'ok': ('✓', 'good'), 'hint': ('!', 'warn')}


def _remembered_name() -> str:
    return str(core.Settings(SETTINGS).get('who', '') or '')


def _remember_name(name: str) -> None:
    s = core.Settings(SETTINGS)
    s.set('who', str(name).strip())
    s.save()


class AssignDialog(ModalDialog):
    def __init__(self, parent, model, idx, asset='', demo=False, procedure=None):
        super().__init__(parent, 'Assign uncertainty', width=780)
        self.model, self.demo, self.asset = model, bool(demo), asset or getattr(model, 'asset', '')
        self.procedure = procedure
        self.outcome = None
        self.assigned_ids: list = []
        self.touched = 0
        self.suggested: list = []
        self.group: dict = {}
        self._extra: list = []                                         # suggestions the technician built from another standard
        self.points = self._point_list(idx)
        self.pos = max(0, self.points.index(idx)) if idx in self.points else 0
        self.set_title('Assign uncertainty' + ((core.DEMO_SUFFIX or ' [DEMO]') if self.demo else ''))
        self.setMinimumWidth(780)

        nav = QHBoxLayout()
        self.nav_label = label('', 'sub', wrap=True)
        self.btn_prev = SecondaryButton('◀ Previous')
        self.btn_next = SecondaryButton('Next ▶')
        self.btn_prev.clicked.connect(lambda _c=False: self.step(-1))
        self.btn_next.clicked.connect(lambda _c=False: self.step(1))
        nav.addWidget(self.nav_label, 1)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        self.body.addLayout(nav)
        if self.demo:
            self.demo_banner = Banner('Demo mode: an assigned value is kept for this session only. It is never saved, and the report stays stamped DEMO DATA.', 'warn')
            self.body.addWidget(self.demo_banner)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inner = QWidget()
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(0, 0, SP.sm, 0)
        self.lay.setSpacing(SP.md)
        self.scroll.setWidget(self.inner)
        scr = (QApplication.primaryScreen()).availableGeometry()
        self.scroll.setMinimumHeight(max(300, min(620, int(scr.height() * 0.58))))
        self.body.addWidget(self.scroll, 1)

        # ---- the point
        self.point_card = QFrame()
        self.point_card.setProperty('surface', 'card')
        pc = QVBoxLayout(self.point_card)
        pc.setContentsMargins(SP.lg, SP.md, SP.lg, SP.md)
        pc.setSpacing(SP.xs)
        self.point_title = label('', 'h2', wrap=True)
        pc.addWidget(self.point_title)
        self.point_grid = QVBoxLayout()
        self.point_grid.setSpacing(2)
        pc.addLayout(self.point_grid)
        self.lay.addWidget(self.point_card)

        # ---- already assigned / computed notices
        self.notice = Banner('', 'info')
        self.notice.hide()
        self.lay.addWidget(self.notice)
        self.replace_check = QCheckBox('Replace the computed value (a reason is required)')
        self.replace_check.hide()
        self.replace_check.toggled.connect(lambda _on: self._sync_enabled())
        self.lay.addWidget(self.replace_check)

        # ---- why
        self.lay.addWidget(label('Why there is no uncertainty', 'section'))
        self.why_box = QVBoxLayout()
        self.why_box.setSpacing(SP.sm)
        self.lay.addLayout(self.why_box)

        # ---- suggestions
        self.lay.addWidget(label('Suggestions', 'section'))
        self.sug_box = QVBoxLayout()
        self.sug_box.setSpacing(SP.sm)
        self.lay.addLayout(self.sug_box)
        more = QHBoxLayout()
        more.addWidget(label('Build one from another standard', 'sub'))
        self.std_combo = QComboBox()
        self.std_combo.setAccessibleName('Standard to build a budget from')
        self.std_combo.setMinimumWidth(180)
        more.addWidget(self.std_combo)
        self.btn_build = SecondaryButton('Add suggestion')
        self.btn_build.clicked.connect(lambda _c=False: self.build_from_standard())
        more.addWidget(self.btn_build)
        more.addStretch(1)
        self.lay.addLayout(more)

        # ---- own value
        self.lay.addWidget(label('Enter my own value', 'section'))
        own = QHBoxLayout()
        own.setSpacing(SP.sm)
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText('Value, for example 12.5')
        self.value_edit.setAccessibleName('Uncertainty value')
        self.value_edit.setMinimumWidth(180)
        self._chk = None
        self.value_edit.textChanged.connect(lambda _t: self._check_manual())
        self.unit_combo = QComboBox()
        self.unit_combo.setAccessibleName('Uncertainty unit')
        self.unit_combo.currentIndexChanged.connect(lambda _i: self._check_manual())
        self.k_note = label('k = 2', 'hint')
        own.addWidget(self.value_edit, 1)
        own.addWidget(self.unit_combo)
        own.addWidget(self.k_note)
        self.lay.addLayout(own)
        self.manual_msg = label('', 'hint', wrap=True)
        self.lay.addWidget(self.manual_msg)
        self.confirm_check = QCheckBox('I know this is below the lab CMC and I confirm it')
        self.confirm_check.hide()
        self.confirm_check.toggled.connect(lambda _on: self._sync_enabled())
        self.lay.addWidget(self.confirm_check)

        # ---- the record
        self.lay.addWidget(rule())
        self.lay.addWidget(label('Recorded with the value', 'section'))
        form = QVBoxLayout()
        form.setSpacing(SP.sm)
        self.reason_edit = QLineEdit()
        self.reason_edit.setAccessibleName('Reason')
        self.reason_edit.setPlaceholderText('Reason (required for your own value or a replacement; optional for a suggestion)')
        self.who_edit = QLineEdit(_remembered_name())
        self.who_edit.setAccessibleName('Your name')
        self.who_edit.setPlaceholderText('Your name (required)')
        form.addWidget(self.reason_edit)
        form.addWidget(self.who_edit)
        self.lay.addLayout(form)
        self.scope_point = QRadioButton('Apply to this point only')
        self.scope_kind = QRadioButton('Apply to all points of this kind in this procedure')
        self.scope_point.setChecked(True)
        self.scope_point.toggled.connect(lambda _on: self._sync_scope())
        self.lay.addWidget(self.scope_point)
        self.lay.addWidget(self.scope_kind)
        self.scope_note = label('', 'hint', wrap=True)
        self.lay.addWidget(self.scope_note)
        self.lay.addStretch(1)

        self.msg = Banner('', 'error')
        self.msg.hide()
        self.body.addWidget(self.msg)
        self.btn_manual = self.add_button('Use my value', role='primary', result='manual', close=False, callback=self.use_manual)
        self.btn_withdraw = self.add_button('Withdraw assignment...', result='withdraw', close=False, callback=self.withdraw_current)
        self.add_button('Close', cancel=True)
        self.show_point(self.pos)

    # ------------------------------------------------------------------------------------------------------------------ hooks the tests replace
    def confirm(self, title, text) -> bool:
        from ..widgets import MessageDialog
        return MessageDialog(self, 'question', title, text, buttons=(('Apply', 'yes', 'primary'), ('Cancel', 'no', '')), cancel_key='no').run() == 'yes'

    def ask_withdraw(self):
        d = ModalDialog(self, 'Withdraw this assignment', subtitle='The record stays in the list, marked withdrawn. The point prints no uncertainty again.', width=520)
        who = QLineEdit(self.who_edit.text())
        why = QLineEdit()
        who.setPlaceholderText('Your name')
        why.setPlaceholderText('Reason')
        d.body.addWidget(who)
        d.body.addWidget(why)
        d.add_button('Cancel', cancel=True)
        d.add_button('Withdraw', role='danger', result='ok')
        return (who.text(), why.text()) if d.run() == 'ok' else None

    # ------------------------------------------------------------------------------------------------------------------ the points
    def _point_list(self, idx) -> list:
        miss = sorted(getattr(self.model, 'field_missing', {}) or {})
        todo = [i for i in miss if self.model.rows[i].assigned is None]
        if idx not in todo:
            todo = sorted(set(todo) | {idx})
        return todo

    @property
    def idx(self) -> int:
        return self.points[self.pos]

    @property
    def info(self) -> F.PointInfo:
        return self._info

    def step(self, d):
        n = len(self.points)
        self.show_point((self.pos + d) % n)

    def show_point(self, pos):
        self.pos = pos
        self.msg.hide()
        self._chk = None
        self.value_edit.clear()
        self.confirm_check.setChecked(False)
        self.confirm_check.hide()
        self.replace_check.setChecked(False)
        self._extra = []
        i = self.idx
        self.row = self.model.rows[i]
        self._info = F.point_info(self.model, i, self.procedure)
        info = self._info
        n = len(self.points)
        left = sum(1 for j in self.points if self.model.rows[j].assigned is None)
        self.nav_label.setText(f'Point {pos + 1} of {n}' + (f' · {left} still without an uncertainty' if left else ' · all assigned'))
        self.btn_prev.setEnabled(n > 1)
        self.btn_next.setEnabled(n > 1)
        # point card
        self.point_title.setText(f'{info.nominal_text}  ·  {info.description}')
        self._clear(self.point_grid)
        rows = [('Function', f'{info.section or "-"}  (step {info.step})'), ('Kind', info.kind or '-')]
        if info.frequency:
            rows.append(('Frequency', _hz(info.frequency)))
        if info.range:
            rows.append(('Range', F.format_decimal(F.dec(info.range), info.unit if info.unit in F.PREFIXABLE else info.tolerance_unit)))
        rows.append(('Calibrator / standard', M.label(info.standard) or info.standard or 'none applies'))
        tol = M.tolerance_text(self.row.spec)
        if tol:
            rows.append(('Tolerance of the unit under test', tol))
        if info.floor is not None:
            rows.append(('Lab CMC floor', f'{F.format_decimal(info.floor, info.unit)}  ({info.floor_text})'))
        self.facts = dict(rows)
        for k, v in rows:
            line = QHBoxLayout()
            kl = label(k, 'kvkey')
            kl.ensurePolished()
            kl.setMinimumWidth(kl.fontMetrics().horizontalAdvance('Tolerance of the unit under test') + 24)       # follows the text scale
            kl.setMaximumWidth(kl.minimumWidth())
            line.addWidget(kl)
            vl = label(v, 'kvvalue', wrap=True)
            line.addWidget(vl, 1)
            self.point_grid.addLayout(line)
        # existing assignment / computed value
        a = self.row.assigned
        self.notice.hide()
        self.replace_check.setVisible(info.has_computed)
        if info.has_computed:
            self.notice.set_kind('warn')
            self.notice.set_text(f'This point already prints a computed uncertainty ({info.computed_text}). It is only replaced if you tick "Replace the computed value" and give a reason.')
            self.notice.show()
        elif a is not None:
            self.notice.set_kind('info')
            self.notice.set_text(f'Already assigned: {a["display"]} by {a["who"]} on {a["at"][:10]} ({a["source"]}). It prints on the report, marked as assigned in the field. '
                                 'Choose another value below to change it, or withdraw it.')
            self.notice.show()
        self.btn_withdraw.setVisible(a is not None)
        # why
        self._clear(self.why_box)
        self.diag = W.diagnose(self.model, i)
        reasons = list(self.diag.reasons)
        if info.locked:
            reasons.insert(0, ('missing', 'This procedure', info.locked + '.'))
        if not reasons:
            reasons.append(('missing', 'Uncertainty', 'The engine printed no uncertainty for this point.'))
        from ..theme import tokens
        for kind, title, text in reasons:
            mark, tone = MARK.get(kind, ('•', 'muted'))
            line = QHBoxLayout()
            m = label(mark, 'h2')
            m.setStyleSheet(f'color: {tokens().get(tone, tokens().get("text"))};')
            m.setFixedWidth(22)
            line.addWidget(m, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(title, 'kvkey'))
            col.addWidget(label(text, 'sub', wrap=True))
            line.addLayout(col, 1)
            self.why_box.addLayout(line)
        # suggestions
        self.suggested = F.suggestions(self.model, i, self.procedure)
        self._fill_standards()
        self._draw_suggestions()
        # own value
        self.unit_combo.blockSignals(True)
        self.unit_combo.clear()
        for text, factor in F.prefix_choices(info.unit):
            self.unit_combo.addItem(text, factor)
        self.unit_combo.setCurrentIndex(self._default_prefix())
        self.unit_combo.blockSignals(False)
        self.value_edit.setPlaceholderText(f'Value in {self.unit_combo.currentText()}, for example 12.5')
        self.manual_msg.setText('Your own value is checked before it is kept: positive, in the unit of the point, and not below the lab CMC unless you confirm it.')
        self._sync_scope()
        self._sync_enabled()

    @staticmethod
    def _clear(layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif it.layout() is not None:
                AssignDialog._clear(it.layout())

    def _default_prefix(self) -> int:
        """The drop-down entry the typed number most likely means: the one that shows the best suggestion (else the CMC floor, else a hundredth of the tolerance)."""
        ref = self.suggested[0].value if self.suggested else self._info.floor
        if ref is None and self._info.low is not None and self._info.high is not None:
            ref = abs(F.dec((self._info.high - self._info.low) / 200.0))
        if ref is None or ref <= 0:
            return max(0, self.unit_combo.count() - 1 if self.unit_combo.count() == 1 else 0)
        best, bestd = 0, None
        for k in range(self.unit_combo.count()):
            f = self.unit_combo.itemData(k)
            mant = ref / f
            d = abs(float(mant.copy_abs().ln() / Decimal(10).ln()) - 1.0) if mant > 0 else 99
            if bestd is None or d < bestd:
                best, bestd = k, d
        return best

    def _fill_standards(self):
        self.std_combo.clear()
        have = {s.standard for s in self.suggested if s.standard}
        for key in F.standard_choices(self.model, self.idx):
            if key not in have:
                self.std_combo.addItem(M.label(key) or key, key)
        self.btn_build.setEnabled(self.std_combo.count() > 0)
        self.std_combo.setEnabled(self.std_combo.count() > 0)

    def _draw_suggestions(self):
        self._clear(self.sug_box)
        self.sug_buttons = []
        shown = self.suggested[:6]
        if not shown:
            self.sug_box.addWidget(label('Nothing in the lab scope, the standards’ specifications or the earlier fixes describes this point. Enter your own value below.', 'sub', wrap=True))
            return
        for n, s in enumerate(shown):
            box = QFrame()
            box.setProperty('surface', 'card')
            h = QHBoxLayout(box)
            h.setContentsMargins(SP.md, SP.sm, SP.md, SP.sm)
            col = QVBoxLayout()
            col.setSpacing(2)
            head = label(s.line, 'kvvalue', wrap=True)
            col.addWidget(head)
            if s.detail:
                col.addWidget(label(s.detail + f'  [{s.machinery}]', 'hint', wrap=True))
            if s.caution:
                col.addWidget(Badge(s.caution, 'warn', small=True))
            h.addLayout(col, 1)
            b = (PrimaryButton if n == 0 else SecondaryButton)('Use this')
            b.setAccessibleName(f'Use suggestion {n + 1}: {s.line}')
            b.setToolTip(f'{s.machinery}')
            b.clicked.connect(lambda _c=False, sg=s: self.use_suggestion(sg))
            h.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.sug_box.addWidget(box)
            self.sug_buttons.append(b)

    def build_from_standard(self, key=None):
        """'Build one from another standard': the budget of the chosen standard's published specification at this point (k = 2), added to the suggestions.  Returns the
        Suggestion, or None when that standard's sheet has no row for the point."""
        key = key or self.std_combo.currentData()
        if not key:
            return None
        s = F.budget_for_standard(self.model, self.idx, key, self.procedure)
        if s is None:
            self._say(f'{M.label(key) or key} has no specification row that covers this point.', 'info')
            return None
        self.suggested = [x for x in self.suggested if x.basis != s.basis] + [s]
        self.suggested.sort(key=lambda x: (x.rank, x.standard))
        self._fill_standards()
        self._draw_suggestions()
        self._sync_enabled()
        self._sync_scope()
        self._say(f'Added: {s.line}.', 'good')
        return s

    # ------------------------------------------------------------------------------------------------------------------ state
    def _say(self, text, kind='error'):
        self.msg.set_kind(kind)
        self.msg.set_text(text)
        self.msg.setVisible(bool(text))

    def _factor(self) -> Decimal:
        f = self.unit_combo.currentData()
        return f if isinstance(f, Decimal) else Decimal(1)

    def _check_manual(self):
        text = self.value_edit.text().strip()
        self.confirm_check.setVisible(False)
        if not text:
            self.manual_msg.setText('Your own value is checked before it is kept: positive, in the unit of the point, and not below the lab CMC unless you confirm it.')
            self._sync_enabled()
            self._sync_scope()
            return None
        best = self.suggested[0].value if self.suggested else None
        chk = F.check_manual(self._info, text, self._factor(), best)
        lines = list(chk.errors) + list(chk.warnings)
        if chk.ok:
            lines.insert(0, f'Will be kept as {chk.display}.')
        self.manual_msg.setText(' '.join(lines))
        self.confirm_check.setVisible(chk.below_cmc)
        if not chk.below_cmc:
            self.confirm_check.setChecked(False)
        self._chk = chk
        self._sync_enabled()
        self._sync_scope()
        return chk

    def _sync_enabled(self):
        locked = self._info.has_computed and not self.replace_check.isChecked()
        for b in self.sug_buttons:
            b.setEnabled(not locked)
        txt = self.value_edit.text().strip()
        ok = False
        if txt and not locked:
            chk = getattr(self, '_chk', None)
            ok = bool(chk is not None and chk.ok and (not chk.below_cmc or self.confirm_check.isChecked()))
        self.btn_manual.setEnabled(ok)

    def _group_for_manual(self) -> dict:
        v = F.parse_value(self.value_edit.text(), self._info.unit, self._factor())[0] or Decimal(1)
        return F.kind_group(self.model, self.idx, 'manual', v)

    def _sync_scope(self):
        i = self.idx
        sug = self.suggested[0] if self.suggested else None
        gs = F.kind_group(self.model, i, 'suggested', suggestion=sug) if sug else {'items': [], 'skipped': 0}
        gm = self._group_for_manual()
        others = len([j for j in (getattr(self.model, 'field_missing', {}) or {}) if j != i and self.model.rows[j].assigned is None])
        if not others:
            self.scope_note.setText('This is the only point of this run without an uncertainty.')
        else:
            parts = [f'{others} other point(s) in this run print no uncertainty.']
            if sug and gs['items']:
                parts.append(f'"Use this" would give {len(gs["items"])} of them their own value from the same standard' + (f' ({gs["skipped"]} cannot be described and are left alone)' if gs['skipped'] else '') + '.')
            elif sug:
                parts.append('A suggestion describes this point only.')
            parts.append(f'A value you type is spread only over the {len(gm["items"])} point(s) with the same kind, level, frequency and range' +
                         (f' ({gm["skipped"]} with other conditions are left alone)' if gm['skipped'] else '') + ': one number is not the uncertainty of a different level.')
            self.scope_note.setText(' '.join(parts))
        self.scope_kind.setEnabled(bool(gs['items'] or gm['items']))
        if not self.scope_kind.isEnabled():
            self.scope_point.setChecked(True)

    # ------------------------------------------------------------------------------------------------------------------ actions
    def _record_people(self, manual: bool):
        who, reason = self.who_edit.text().strip(), self.reason_edit.text().strip()
        msgs = F.check_people(reason, who, need_reason=(manual or self.replace_check.isChecked()))
        return who, reason, msgs

    def use_suggestion(self, s):
        """One tap on a suggestion."""
        who, reason, msgs = self._record_people(False)
        if msgs:
            self._say(' '.join(msgs))
            return False
        reason = reason or f'Accepted the suggestion: {s.line}.'
        return self._apply(s.value, s.source, who, reason, suggestion=s)

    def use_manual(self):
        who, reason, msgs = self._record_people(True)
        chk = self._check_manual()
        if chk is None:
            self._say('Enter a value.')
            return False
        if not chk.ok:
            self._say(' '.join(chk.errors))
            return False
        if msgs:
            self._say(' '.join(msgs))
            return False
        if chk.below_cmc and not self.confirm_check.isChecked():
            self._say('The value is below the lab CMC. Tick the confirmation to keep it.')
            return False
        return self._apply(chk.value, 'manual', who, reason, manual=True)

    def _apply(self, value, source, who, reason, suggestion=None, manual=False):
        info = self._info
        replace = bool(info.has_computed)
        if replace and not self.replace_check.isChecked():
            self._say('Tick "Replace the computed value" first.')
            return False
        items = [(info, value, source)]
        scope = 'point'
        if self.scope_kind.isChecked():
            g = F.kind_group(self.model, self.idx, 'manual' if manual else 'suggested', value=value if manual else None, suggestion=suggestion)
            if g['items']:
                lines = '\n'.join(f'  {x.nominal_text} · {x.description}: {F.format_decimal(v, x.unit)}' for x, v, _s in g['items'][:12])
                more = f'\n  ... and {len(g["items"]) - 12} more' if len(g['items']) > 12 else ''
                if not self.confirm('Apply to all points of this kind?', f'This point and {len(g["items"])} other point(s) will be assigned:\n{lines}{more}'
                                    + (f'\n\n{g["skipped"]} other point(s) cannot be covered safely and are left alone.' if g['skipped'] else '')):
                    return False
                items += g['items']
                scope = 'kind'
        try:
            ids = F.add_many(items, reason=reason, who=who, demo=self.demo, replace=replace, confirm_below_cmc=bool(self.confirm_check.isChecked()), scope=scope,
                             asset=self.asset)
        except F.Refused as e:
            self._say(str(e))
            return False
        except F.StorageError as e:
            self._say(str(e))
            return False
        self.assigned_ids += ids
        self.touched += len(ids)
        if not self.demo:
            _remember_name(who)
        self.outcome = 'assigned'
        self._refresh_rows()
        left = [j for j in self.points if self.model.rows[j].assigned is None]
        if left:
            self.points = self._point_list(left[0])
            self.show_point(self.points.index(left[0]))
            self._say(f'Assigned {F.format_decimal(value, info.unit)}' + (f' to {len(ids)} points' if len(ids) > 1 else '') + '. The next point is shown.', 'good')
        else:
            self.result_key = 'assigned'
            self.accept()
        return True

    def _refresh_rows(self):
        """Attach what is stored now to every row of the model (the review window then shows what will print)."""
        stored = F.lookup_all(self._info.procedure, self.demo)
        for row in self.model.rows:
            a = stored.get(F.point_id(row.spec.section, row.spec.description, row.spec.nominal_text))
            printed = str(row.spec.printed.get('Uncertainty') or '').strip()
            row.assigned = a if (a is not None and (printed in ('', 'N/A') or a['replaces'])) else None

    def withdraw_current(self):
        a = self.row.assigned
        if a is None:
            return False
        got = self.ask_withdraw()
        if not got:
            return False
        try:
            F.withdraw(a['id'], got[0], got[1], demo=self.demo)
        except (F.Refused, F.StorageError) as e:
            self._say(str(e))
            return False
        self.outcome = self.outcome or 'withdrawn'
        self._refresh_rows()
        self.show_point(self.pos)
        self._say('The assignment was withdrawn. The point prints no uncertainty again.', 'info')
        return False

    def run(self):
        super().run()
        return self.outcome


def _hz(f) -> str:
    return F.format_decimal(F.dec(f), 'Hz')


# ======================================================================================================================================== the owner's list
class FieldAssignmentsDialog(ModalDialog):
    """Every uncertainty assigned in the field: procedure, point, value, basis, reason, who, when; CSV export; 'Withdraw'.  Later the lab owner can promote the good ones to
    permanent rules (not built here)."""
    HEADS = ('Status', 'Procedure', 'Point', 'Value', 'Basis', 'Reason', 'Who', 'When', 'First used on')

    def __init__(self, parent=None, demo=False):
        super().__init__(parent, 'Field assignments', subtitle='Uncertainties technicians assigned at the point of use. Each is marked on the report it was printed on.', width=1100)
        self.demo = demo
        self.rows = []
        cols = [Column('status', self.HEADS[0], width=96, kind='badge', getter=lambda r: F.status_of(r), badge_map={'active': 'warn', 'withdrawn': 'neutral'}),
                Column('proc', self.HEADS[1], width=210, getter=lambda r: r['procedure_id']),
                Column('point', self.HEADS[2], width=300, stretch=True, getter=lambda r: f'{r["nominal_text"]}  ·  {r["description"]}  ({r["section"]})'),
                Column('value', self.HEADS[3], width=110, align='right', mono=True, bold=True, getter=lambda r: r['display'] + (' (replaces)' if r['replaces'] else '')),
                Column('basis', self.HEADS[4], width=260, getter=lambda r: 'entered by hand' if r['source'] == 'manual' else r['source'].replace(F.SESSION_PREFIX, 'suggestion: ', 1)),
                Column('reason', self.HEADS[5], width=260, getter=lambda r: r['reason']),
                Column('who', self.HEADS[6], width=110, getter=lambda r: r['who']),
                Column('when', self.HEADS[7], width=150, mono=True, getter=lambda r: r['at'].replace('T', ' ')),
                Column('used', self.HEADS[8], width=170, getter=lambda r: (r['first_asset'] or '-') + (f' (run {r["first_run"]})' if r['first_run'] else ''))]
        self.table = DataTable(cols, [], row_key=lambda r: r['id'], multi=False, empty_text='No uncertainty has been assigned in the field yet')
        self.table.setAccessibleName('Field assignments')
        self.table.setMinimumHeight(320)
        self.body.addWidget(self.table, 1)
        self.count_label = label('', 'sub')
        self.body.addWidget(self.count_label)
        self.status_line = label('', 'hint', wrap=True)
        self.body.addWidget(self.status_line)
        self.btn_export = self.add_button('Export CSV...', result='export', close=False, callback=self.export)
        self.btn_withdraw = self.add_button('Withdraw selected...', result='withdraw', close=False, callback=self.withdraw)
        self.add_button('Close', cancel=True, default=True)
        self.reload()

    def reload(self):
        self.rows = F.all_assignments(True, self.demo)
        self.table.set_rows(self.rows)
        active = sum(1 for r in self.rows if r['active'])
        self.count_label.setText(f'{len(self.rows)} assignment(s), {active} in use' + ('  ·  demo session' if self.demo else ''))

    # hooks the tests replace
    def ask_save_path(self) -> str:
        path, _f = QFileDialog.getSaveFileName(self, 'Export field assignments', 'field_assignments.csv', 'CSV (*.csv)')
        return path

    def ask_withdraw(self):
        d = ModalDialog(self, 'Withdraw this assignment', subtitle='The record stays in the list, marked withdrawn.', width=520)
        who = QLineEdit(_remembered_name())
        why = QLineEdit()
        who.setPlaceholderText('Your name')
        why.setPlaceholderText('Reason')
        d.body.addWidget(who)
        d.body.addWidget(why)
        d.add_button('Cancel', cancel=True)
        d.add_button('Withdraw', role='danger', result='ok')
        return (who.text(), why.text()) if d.run() == 'ok' else None

    def export(self):
        path = self.ask_save_path()
        if not path:
            return False
        try:
            n = F.export_csv(path, self.rows, self.demo)
        except OSError as e:
            self.status_line.setText(f'Could not write the file: {e}')
            return False
        self.status_line.setText(f'Exported {n} row(s) to {path}')
        return False

    def withdraw(self):
        sel = self.table.selected_rows()
        if len(sel) != 1 or not sel[0]['active']:
            self.status_line.setText('Select one assignment that is in use.')
            return False
        got = self.ask_withdraw()
        if not got:
            return False
        try:
            F.withdraw(sel[0]['id'], got[0], got[1], demo=self.demo)
        except (F.Refused, F.StorageError) as e:
            self.status_line.setText(str(e))
            return False
        self.reload()
        self.status_line.setText('Withdrawn. The record stays in the list.')
        return False


def open_list(parent=None):
    return FieldAssignmentsDialog(parent).run()


# ======================================================================================================================================== from a running procedure
def build_model_for_app(app):
    """(model, demo) of the points the running procedure has recorded so far, annotated, or None when the engine is not covered (report_review_flow.build_models)."""
    import report_review_flow as flow
    built = flow.build_models(None, '', app)
    if built is flow.UNAVAILABLE:
        return None
    models, demo = built
    return models[0], demo


def missing_count(app) -> int:
    """How many recorded points should carry an uncertainty and have none (and no assignment yet).  0 when the engine is not covered.  Never raises."""
    try:
        built = build_model_for_app(app)
        if built is None:
            return 0
        model, _demo = built
        return sum(1 for i in model.field_missing if model.rows[i].assigned is None)
    except Exception:
        return 0


def open_for_app(parent, app, idx=None):
    """The panel for a running procedure: the first recorded point without an uncertainty (or `idx`).  Returns the dialog outcome or None."""
    built = build_model_for_app(app)
    if built is None:
        return None
    model, demo = built
    todo = [i for i in sorted(model.field_missing) if model.rows[i].assigned is None]
    if idx is None:
        if not todo:
            return None
        idx = todo[0]
    return AssignDialog(parent, model, idx, asset=model.asset, demo=demo).run()
