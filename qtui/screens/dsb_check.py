"""Datasheet Builder (Qt): the 'Sheet check' window and the parts of the editor window that show it (build-time rules 1-5, NOTES.md 'Two-way datasheet rules').
Port of datasheet_builder_check_ui: SheetCheckWindow (the list of findings; Go to the row, Apply the fix, Waive..., Check again, Commands to accept...),
ask_waiver, CommandsWindow and CheckWindowMixin (the pill, the button, the check that comes before Run / Try in demo, the real-run question that lists the
unverified commands).  Everything is decided in datasheet_builder_check_model / datasheet_builder_rules.  No Tk import."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit

from qtui import widgets
from qtui.screens import dsb_common as C
from qtui.screens.dsb_dialogs import present
from qtui.table import Column

LEVEL_TEXT = {'error': 'FIX', 'warn': 'warning', 'info': 'note'}
LEVEL_TONE = {'error': 'fail', 'warn': 'warn', 'info': 'info'}
SHOWN_IN_QUESTION = 12            # unverified commands named in the real-run question before 'and n more'


class SheetCheckWindow(widgets.ModalDialog):
    """Everything the build-time rules found, in plain words.  Double-click one to go to its row."""

    def __init__(self, owner):
        super().__init__(owner, 'Sheet check', width=680, modal=False)
        self.title_label.hide()
        self._size_hint = (1020, 520)
        self.owner = owner
        self.summary = widgets.label('', 'section', wrap=True)
        self.body.addWidget(self.summary)
        self.body.addWidget(widgets.label('Calibrator coverage, unverified commands, units, a dry run on the simulated instruments and the source of each uncertainty. '
                                          'A line marked FIX keeps the sheet from being marked ready; a warning does not.', 'sub', wrap=True))
        self.table = C.table([Column('level_text', '', 70), Column('rule_text', 'Rule', 50), Column('row_text', 'Row', 54), Column('text', 'What was found', 760, stretch=True)],
                             row_tone=lambda r: LEVEL_TONE.get(r['level']))
        self.table.selectionChangedRows.connect(lambda _r: self.show_detail())
        self.table.rowActivated.connect(lambda _r: self.go())
        self.body.addWidget(self.table, 1)
        self.detail = widgets.label('', wrap=True)
        self.body.addWidget(self.detail)
        self.go_b = self.add_button('Go to the row', close=False, callback=self.go)
        self.fix_b = self.add_button('Apply the fix', role='primary', close=False, callback=self.fix)
        self.waive_b = self.add_button('Waive...', close=False, callback=self.waive)
        self.again_b = self.add_button('Check again', close=False, callback=self.again)
        self.cmds_b = self.add_button('Commands to accept...', close=False, callback=self.commands)
        self.add_button('Close', cancel=True)
        C.tip(self.fix_b, 'Rule 1: enter the point by hand (the operator uses their own standard). Rule 3: turn the row into a flagged pass / fail check. One undo step.')
        C.tip(self.waive_b, 'Rule 5: a reading that should have an uncertainty has none. Record why (own standard, zero check, scope does not cover it, or type a reason). '
                            'The waiver is saved with the sheet and named in its history.')
        C.tip(self.again_b, 'Work the check out again for the sheet as it is now (it runs every point on the simulated instruments, which takes a moment).')
        C.tip(self.cmds_b, 'The commands a run on real instruments asks you to accept: not verified on hardware, or no manual page reference.')
        self._rows = []
        self.reload()

    def reload(self):
        """Called after every edit of the sheet: shows the check of the sheet as it is (never starts the slow check by itself)."""
        m = self.owner.model
        self._rows = m.check_rows(compute=False)
        self.summary.setText(m.check_summary(compute=False) if m.check_fresh() else 'The sheet changed since the last check. Press "Check again" to see where it stands.')
        rows = [dict(r, id=i, level_text=LEVEL_TEXT.get(r['level'], ''), rule_text=str(r['rule']), row_text=r['row'] or '') for i, r in enumerate(self._rows)]
        C.fill(self.table, rows)
        self.detail.setText('Nothing to fix and nothing to warn about.' if not rows and m.check_fresh() else '')
        self.fix_b.setEnabled(False)
        self.fix_b.setText('Apply the fix')
        self.waive_b.setEnabled(False)
        self.go_b.setEnabled(bool(rows))
        chk = m.sheet_check(compute=False)
        self.cmds_b.setEnabled(chk is not None and bool(chk.unverified))

    def _selected(self):
        sel = C.selected_ids(self.table)
        if not sel or int(sel[0]) >= len(self._rows):
            return None
        return self._rows[int(sel[0])]

    def show_detail(self):
        row = self._selected()
        if row is None:
            return
        what = row['text'] or row['title']                       # the table cuts a long line; the full sentence is here
        self.detail.setText(f'{what}  What to do: {row["fix"]}' if row['fix'] else what)
        self.fix_b.setEnabled(row['action'] not in ('', 'waive'))
        self.fix_b.setText('Remove waiver' if row['action'] == 'unwaive' else 'Apply the fix')
        self.waive_b.setEnabled(row['action'] == 'waive')

    def go(self):
        row = self._selected()
        if row and row['key']:
            self.owner.goto_row(row['key'])
        return row

    def fix(self):
        row = self._selected()
        if row is None or not row['action']:
            return None
        res = self.owner.model.apply_check_fix(row['idx'])
        self.owner.changed(res)
        self.owner.model.sheet_check(compute=True)          # the edit changed the sheet: look again
        self.owner.refresh()
        return res

    def waive(self):
        row = self._selected()
        if row is None or row['action'] != 'waive':
            return None
        got = ask_waiver(self, row['count'])
        if got is None:
            return None
        res = self.owner.model.waive_finding(row['idx'], *got)
        self.owner.changed(res)
        if res.ok:
            self.owner.model.sheet_check(compute=True)
        self.owner.refresh()
        return res

    def again(self):
        self.owner.model.sheet_check(compute=True)
        self.owner.refresh()

    def commands(self):
        chk = self.owner.model.sheet_check(compute=False)
        if chk is not None:
            return present(CommandsWindow(self, chk.pre_run_lines()))


def ask_waiver(parent, count=1):
    """The waiver question (rule 5): a reason from the list or typed.  Returns (code, typed text) or None when cancelled.  `count` readings are waived."""
    import datasheet_builder_rules as rules
    out = {}
    dlg = widgets.ModalDialog(parent, 'Waive the uncertainty', width=520)
    dlg.set_title(f'{count} reading{"s" * (count != 1)} will have no uncertainty on the report')
    dlg.setWindowTitle('Waive the uncertainty')
    dlg.add_text('Say why. The reason is saved with the sheet, shown in the Sheet check and named in the sheet\'s history; the report leaves the uncertainty blank (never zero).', 'sub')
    labels = [t for _c, t in rules.WAIVER_REASONS]
    pick = QComboBox()
    pick.addItems(labels)
    dlg.body.addWidget(pick)
    dlg.body.addWidget(widgets.label('Typed reason (required for "Other", optional otherwise)'))
    ent = QLineEdit()
    dlg.body.addWidget(ent)
    msg = widgets.label('', 'hint')
    dlg.body.addWidget(msg)
    dlg.initial_focus = pick

    def ok():
        code = rules.WAIVER_REASONS[labels.index(pick.currentText())][0]
        if code == 'other' and not ent.text().strip():
            msg.setText('Type the reason.')
            ent.setFocus()
            return False
        out['v'] = (code, ent.text().strip())
        return True
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('Waive', role='primary', result='waive', default=True, callback=ok)
    dlg.run()
    return out.get('v')


class CommandsWindow(widgets.ModalDialog):
    """The commands a real run asks the operator to accept."""

    def __init__(self, parent, lines):
        super().__init__(parent, 'Commands to accept before a real run', width=620, modal=False)
        self.title_label.hide()
        self._size_hint = (760, 460)
        self.body.addWidget(widgets.label(f'{len(lines)} command{"s" * (len(lines) != 1)} not verified on hardware or not tied to a manual page', 'section'))
        self.body.addWidget(widgets.label('A run on real instruments lists these first and goes on only when the operator accepts them. Try in demo sends nothing to a real instrument.',
                                          'sub', wrap=True))
        self.text = QPlainTextEdit('\n'.join(f'  {l}' for l in lines) or '  None.')
        self.text.setReadOnly(True)
        self.body.addWidget(self.text, 1)
        self.add_button('Close', cancel=True)


class CheckWindowMixin:
    """The Sheet check parts of the editor window."""

    _check_win = None

    # ---- building (called from the title strip / the footer)
    def build_check_pill(self, layout):
        self.check_pill = widgets.Badge('', 'good')
        C.Clickable(self.check_pill, self.show_check)
        C.tip(self.check_pill, lambda: 'Click to open the Sheet check.\n' + self.model.check_summary(compute=False))
        self.check_pill.setVisible(False)
        layout.addWidget(self.check_pill)
        self._check_pill_shown = False

    def build_check_button(self, layout):
        b = C.button('Sheet check', self.show_check, compact=True,
                     tooltip='Check the sheet against the build rules: calibrator coverage, unverified commands, units, a dry run on the simulated instruments, uncertainty sources.')
        layout.addWidget(b)
        self.check_b = b

    def refresh_check(self):
        text, kind = self.model.check_pill()
        if text:
            self.check_pill.set(text, kind)
            self.check_pill.setVisible(True)
            self._check_pill_shown = True
        elif self._check_pill_shown:
            self.check_pill.setVisible(False)
            self._check_pill_shown = False

    # ---- showing
    def show_check(self, compute=True):
        """Open the Sheet check (working the check out first)."""
        self.commit_header()
        if compute:
            self.model.sheet_check(compute=True)
            self.refresh()
        win = self._check_win
        try:
            if win is not None and win.isVisible():
                win.reload()
                win.raise_()
                return win
        except RuntimeError:
            pass
        win = self._check_win = SheetCheckWindow(self)
        self.dialogs.append(win)
        present(win)
        return win

    # ---- before Run / Try in demo
    def check_blocks_run(self):
        """Run the sheet check; with errors open it and return the message, else None."""
        chk = self.model.sheet_check(compute=True)
        if chk.errors():
            self.refresh()
            self.show_check(compute=False)
            n = len(chk.errors())
            return f'The sheet check found {n} thing{"s" * (n != 1)} to fix before this can run. The Sheet check window shows them.'
        return None

    def real_run_question(self):
        """(text, fingerprint) of the real-run question: the base question, plus the unverified commands the operator accepts by answering Yes."""
        title = (self.model.ds.title or self.model.ds.model or 'this datasheet').strip()
        text = f'Run {title} on real instruments? The calibrator will be driven from this program.'
        info = self.model.pre_run_list(compute=True)
        if not info['count']:
            return text, ''
        lines = info['lines']
        text += (f'\n\n{info["count"]} command{"s" * (info["count"] != 1)} in this run {"are" if info["count"] != 1 else "is"} not verified on hardware or not tied to a manual page '
                 f'({info["points"]} point{"s" * (info["points"] != 1)}). Yes means you accept them:\n\n')
        text += '\n'.join('  ' + l for l in lines[:SHOWN_IN_QUESTION])
        if len(lines) > SHOWN_IN_QUESTION:
            text += f'\n  ... and {len(lines) - SHOWN_IN_QUESTION} more (Sheet check > Commands to accept)'
        return text, info['fingerprint']

    def confirm_real_run(self):
        """A run on REAL instruments asks first (default No).  The question lists the commands that are not verified; Yes accepts them."""
        text, fingerprint = self.real_run_question()
        yes = bool(C.ask_yes_no(self, 'Run on real instruments', text, default='no', kind='warning'))
        self._accepted_unverified = fingerprint if yes else ''
        return yes
