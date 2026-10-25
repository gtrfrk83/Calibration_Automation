"""The review window's 'Why is there no uncertainty?' panel: what is missing for the selected point and one-click ways to fix it.

    WhyDialog(parent, model, idx, asset='').run()      # 'applied' | 'flagged' | None

Fixes, best first (uncertainty_why.diagnose): the standard's own specification (k = 2), the value used last time for this point, a saved
'all points like this' rule; then 'Work it out in the calculator' (the Uncertainty Calculator, filled in with the point) and 'Flag for quality'.
'Use it for all points like this' types the same value into the other not-in-scope rows of the same section and unit and keeps it as a rule for later
runs.  Every value is recorded with its source and the person's name; it is only ever typed into a row the lab scope does not cover.
Dialogs the tests replace: `_calculator(parent, prefill) -> text | None`, `_info(parent, title, text)`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

import report_review_model as M
import uncertainty_why as W

from ..widgets import ModalDialog, PrimaryButton, SecondaryButton, label

MARK = {'missing': ('✗', 'bad'), 'ok': ('✓', 'good'), 'hint': ('!', 'warn')}


def _info(parent, title, text):
    from ..widgets import MessageDialog
    MessageDialog.info(parent, title, text) if hasattr(MessageDialog, 'info') else None


def _calculator(parent, prefill):
    """The Uncertainty Calculator in a dialog, filled in with the point.  Returns the reported U as entry text ('0.012 dB') or None."""
    from .uncertainty_calculator import UncertaintyCalculatorPanel, fmt
    dlg = QDialog(parent)
    dlg.setWindowTitle('Work out the uncertainty')
    dlg.resize(1250, 760)
    lay = QVBoxLayout(dlg)
    panel = UncertaintyCalculatorPanel(dlg)
    panel.set_rail_open(False)
    panel.clear_all()
    panel.title_e.setText(prefill.get('measurand', ''))
    panel.nominal_e.setText(prefill.get('nominal', ''))
    panel.unit_e.setText(prefill.get('unit', ''))
    if prefill.get('cmc'):
        panel.cmc_e.setText(prefill['cmc'])
    if prefill.get('tolerance'):
        panel.tol_e.setText(prefill['tolerance'])
    if prefill.get('standard_value'):
        panel.add_type_b(prefill.get('standard_name', 'Standard specification'), prefill['standard_value'], 'k2')
    panel.recalc()
    lay.addWidget(panel, 1)
    row = QHBoxLayout()
    row.addStretch(1)
    out = {}
    cancel = SecondaryButton('Cancel')
    use = PrimaryButton('Use this result')

    def take():
        panel.recalc()
        if panel.result is None:
            return
        out['text'] = f'{fmt(panel.result.reported)} {panel.unit_e.text().strip()}'.strip()
        if panel.current_id is None and panel.is_dirty():
            pass                                       # the calculation is not saved by itself; the value goes to the point with its source
        dlg.accept()
    cancel.clicked.connect(dlg.reject)
    use.clicked.connect(take)
    row.addWidget(cancel)
    row.addWidget(use)
    lay.addLayout(row)
    dlg.exec()
    return out.get('text')


class WhyDialog(ModalDialog):
    def __init__(self, parent, model, idx, asset=''):
        row = model.rows[idx]
        super().__init__(parent, 'Why is there no uncertainty?', subtitle=f'Step {row.spec.step} · {row.spec.nominal_text} · {row.spec.description}', width=620)
        self.model, self.idx, self.asset = model, idx, asset
        self.outcome = None
        self.diag = W.diagnose(model, idx)
        for kind, title, text in self.diag.reasons:
            mark, tone = MARK.get(kind, ('•', 'muted'))
            line = QHBoxLayout()
            m = label(mark, 'h2')
            from ..theme import tokens
            m.setStyleSheet(f'color: {tokens().get(tone, tokens().get("text"))};')
            m.setFixedWidth(22)
            line.addWidget(m, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(title, 'kvkey'))
            col.addWidget(label(text, 'sub', wrap=True))
            line.addLayout(col, 1)
            self.body.addLayout(line)
        self.fix_buttons = []
        can = row.can_type()
        if can:
            self.body.addWidget(label('Fix it', 'section'))
            for n, sg in enumerate(self.diag.suggestions):
                b = (PrimaryButton if n == 0 else SecondaryButton)(sg.label)
                b.setToolTip(f'{sg.source}. {sg.detail}'.strip())
                b.clicked.connect(lambda _c=False, s=sg: self.use(s.text, s.source))
                self.body.addWidget(b)
                if sg.detail:
                    self.body.addWidget(label(sg.detail, 'hint', wrap=True))
                self.fix_buttons.append(b)
            self.btn_calc = (PrimaryButton if not self.diag.suggestions else SecondaryButton)('Work it out in the calculator…')
            self.btn_calc.clicked.connect(self.calculate)
            self.body.addWidget(self.btn_calc)
            like = W.like_rows(model, idx)
            self.like = QCheckBox(f'Use it for all points like this ({len(like)} more in this run, and in future runs)' if like else
                                  'Use it for points like this in future runs too')
            self.like.setToolTip(f'Same section ({row.spec.section or "-"}) and unit, not covered by the lab scope.')
            self.body.addWidget(self.like)
            self.reason = QLineEdit()
            self.reason.setPlaceholderText('Reason or note (optional, kept with the value)')
            self.body.addWidget(self.reason)
            self.body.addWidget(label('The value is printed for this point as entered (not covered by the accredited scope) and recorded with your name, '
                                      'the date and its source.', 'hint', wrap=True))
        else:
            self.body.addWidget(label('This point is covered by the lab scope: change the standard in the Standard column instead.', 'hint', wrap=True))
        self.btn_flag = SecondaryButton('Flag for quality')
        self.btn_flag.setToolTip('Adds the point to the uncertainty issues list for quality to look at; the report can still be generated.')
        self.btn_flag.clicked.connect(self.flag_it)
        self.body.addWidget(self.btn_flag)
        self.add_button('Close', cancel=True)

    # ---- actions
    def use(self, text, source):
        like = bool(getattr(self, 'like', None) and self.like.isChecked())
        reason = self.reason.text().strip() if hasattr(self, 'reason') else ''
        import uncertainty_fixes as F
        ok, msg, n = W.apply(self.model, self.idx, text, source, reason=reason, like=like, who=F.who_am_i())
        if not ok:
            self.sub_label.setText(msg)
            self.sub_label.setVisible(True)
            return False
        self.outcome = 'applied'
        self.applied_rows = n
        self.result_key = 'applied'
        self.accept()
        return True

    def calculate(self):
        row = self.model.rows[self.idx]
        scale, sym = M.entry_scale(row.spec, row.cur)

        def shown(v):
            return f'{v / float(scale):.6g}' if v else ''
        import tartur
        tol = tartur.half_width(row.spec.low, row.spec.high) if row.spec.low is not None and row.spec.high is not None else None
        prefill = dict(measurand=f'{row.spec.description}', nominal=row.spec.nominal_text, unit=sym, cmc=shown(row.cur.cmc),
                       tolerance=shown(tol) if tol and row.cur.unit == row.spec.unit else '',
                       standard_value=shown(row.cur.budget), standard_name=f'{M.label(row.standard) or row.spec.std_label or "Standard"} specification (k = 2)')
        text = _calculator(self, prefill)
        if text:
            return self.use(text, 'Uncertainty Calculator')
        return False

    def flag_it(self):
        import uncertainty_fixes as F
        row = self.model.rows[self.idx]
        note = self.reason.text().strip() if hasattr(self, 'reason') else ''
        F.flag(self.model.procedure or self.model.title, self.asset, row.spec.section, f'{row.spec.nominal_text} · {row.spec.description}', note, F.who_am_i())
        self.outcome = 'flagged'
        self.result_key = 'flagged'
        self.accept()

    def run(self):
        super().run()
        return self.outcome
