"""Datasheet Builder: the 'Sheet check' window and the bits of GridEditorWindow that show it (build-time rules 1-5, NOTES.md 'Two-way datasheet rules').

    SheetCheckWindow(owner)      the list of findings: Level, Rule, Row, What is wrong; below it the plain fix; Go to the row, Apply the fix, Check again,
                                 Commands to accept (rule 2).  Colours follow the other Builder lists (red = to fix, amber = warning, grey = for your information).
    CheckWindowMixin             mixed into GridEditorWindow: the Sheet check button (under the sheet) and pill (title strip), show_check(), the check that comes before
                                 Run / Try in demo (errors stop the run), and the real-run question that lists the unverified commands.
    CommandsWindow(parent, lines) the full list of commands a real run asks the operator to accept.

Everything is decided in datasheet_builder_check_model.CheckMixin / datasheet_builder_rules; this module draws it.  Written and looked at on a real Tk 9 under
Xvfb (light and dark); never seen on Windows.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import ui_theme as ui

LEVEL_TEXT = {'error': 'FIX', 'warn': 'warning', 'info': 'note'}
LEVEL_TAG = {'error': 'fail', 'warn': 'error', 'info': 'pending'}
SHOWN_IN_QUESTION = 12            # unverified commands named in the real-run question before 'and n more'


def _tip(widget, text):
    try:
        ui.Tooltip(widget, text)
    except (tk.TclError, AttributeError):
        pass


class SheetCheckWindow(tk.Toplevel):
    """Everything the build-time rules found, in plain words.  Double-click one to go to its row."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.title('Sheet check')
        self.configure(background=ui.C['bg'])
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)
        self.summary = tk.StringVar()
        ttk.Label(body, textvariable=self.summary, style='Bold.TLabel').pack(anchor='w')
        ttk.Label(body, text='Calibrator coverage, unverified commands, units, a dry run on the simulated instruments and the source of each uncertainty. '
                  'A line marked FIX keeps the sheet from being marked ready; a warning does not.', style='Muted.TLabel', wraplength=ui.px(900),
                  justify='left').pack(anchor='w', pady=(2, 6))
        self.table = ui.make_table(body, ('level', 'rule', 'row', 'text'), ('', 'Rule', 'Row', 'What was found'), (70, 50, 54, 760), anchors={'text': 'w'}, height=9,
                                   zebra=False, stretch={'level': False, 'rule': False, 'row': False})
        self.table.bind('<Double-1>', lambda _e: self.go())
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.show_detail())
        self.detail = tk.StringVar()
        ttk.Label(body, textvariable=self.detail, wraplength=ui.px(900), justify='left').pack(anchor='w', fill='x', pady=(8, 0))
        bar = ttk.Frame(body)
        bar.pack(fill='x', pady=(8, 0))
        self.go_b = ttk.Button(bar, text='Go to the row', command=self.go)
        self.fix_b = ttk.Button(bar, text='Apply the fix', style='Accent.TButton', command=self.fix)
        self.again_b = ttk.Button(bar, text='Check again', command=self.again)
        self.cmds_b = ttk.Button(bar, text='Commands to accept...', command=self.commands)
        close = ttk.Button(bar, text='Close', command=self.destroy)
        for b in (self.go_b, self.fix_b, self.again_b, self.cmds_b):
            b.pack(side='left', padx=(0, 8))
        close.pack(side='right')
        _tip(self.fix_b, 'Rule 1: enter the point by hand (the operator uses their own standard). Rule 3: turn the row into a flagged pass / fail check. One undo step.')
        _tip(self.again_b, 'Work the check out again for the sheet as it is now (it runs every point on the simulated instruments, which takes a moment).')
        _tip(self.cmds_b, 'The commands a run on real instruments asks you to accept: not verified on hardware, or no manual page reference.')
        self.bind('<Escape>', lambda _e: self.destroy())
        self._rows = []
        self.reload()
        ui.fit_window(self, 1020, 520, min_w=680, min_h=340)

    def reload(self):
        """Called after every edit of the sheet: shows the check of the sheet as it is (never starts the slow check by itself)."""
        m = self.owner.model
        self._rows = m.check_rows(compute=False)
        self.summary.set(m.check_summary(compute=False) if m.check_fresh() else
                         'The sheet changed since the last check. Press "Check again" to see where it stands.')
        rows = [dict(r, id=i, level_text=LEVEL_TEXT.get(r['level'], ''), rule_text=str(r['rule']), row_text=r['row'] or '') for i, r in enumerate(self._rows)]
        for item in tuple(self.table.get_children()):
            self.table.delete(item)
        for r in rows:
            self.table.insert('', 'end', iid=str(r['id']), values=(r['level_text'], r['rule_text'], r['row_text'], r['text']), tags=(LEVEL_TAG.get(r['level'], ''),))
        if not rows and m.check_fresh():
            self.detail.set('Nothing to fix and nothing to warn about.')
        else:
            self.detail.set('')
        self.fix_b.configure(state='disabled')
        self.go_b.configure(state='normal' if rows else 'disabled')
        chk = m.sheet_check(compute=False)
        self.cmds_b.configure(state='normal' if chk is not None and chk.unverified else 'disabled')

    def _selected(self):
        sel = self.table.selection()
        if not sel or int(sel[0]) >= len(self._rows):
            return None
        return self._rows[int(sel[0])]

    def show_detail(self):
        row = self._selected()
        if row is None:
            return
        what = row['text'] or row['title']                       # the table cuts a long line; the full sentence is here
        self.detail.set(f'{what}  What to do: {row["fix"]}' if row['fix'] else what)
        self.fix_b.configure(state='normal' if row['action'] else 'disabled')

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

    def again(self):
        self.owner.model.sheet_check(compute=True)
        self.owner.refresh()

    def commands(self):
        chk = self.owner.model.sheet_check(compute=False)
        if chk is not None:
            return CommandsWindow(self, chk.pre_run_lines())


class CommandsWindow(tk.Toplevel):
    """The commands a real run asks the operator to accept."""

    def __init__(self, parent, lines):
        super().__init__(parent)
        self.title('Commands to accept before a real run')
        self.configure(background=ui.C['bg'])
        body = ttk.Frame(self, padding=14)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=f'{len(lines)} command{"s" * (len(lines) != 1)} not verified on hardware or not tied to a manual page', style='Bold.TLabel').pack(anchor='w')
        ttk.Label(body, text='A run on real instruments lists these first and goes on only when the operator accepts them. Try in demo sends nothing to a real instrument.',
                  style='Muted.TLabel', wraplength=ui.px(620), justify='left').pack(anchor='w', pady=(2, 8))
        box = ttk.Frame(body)
        box.pack(fill='both', expand=True)
        text = tk.Text(box, width=84, height=16, wrap='word', background=ui.C['card'], foreground=ui.C['text'], relief='flat', highlightthickness=1,
                       highlightbackground=ui.C['border_strong'], padx=8, pady=6)
        sb = ttk.Scrollbar(box, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        text.pack(side='left', fill='both', expand=True)
        text.insert('1.0', '\n'.join(f'  {l}' for l in lines) or '  None.')
        text.configure(state='disabled')
        ttk.Button(body, text='Close', command=self.destroy).pack(anchor='e', pady=(10, 0))
        self.bind('<Escape>', lambda _e: self.destroy())
        ui.fit_window(self, 760, 460, min_w=520, min_h=300)


class CheckWindowMixin:
    """The Sheet check parts of GridEditorWindow."""

    _check_win = None

    # ---- building (called from _build_title / _build_footer)
    def build_check_pill(self):
        self.check_pill = ui.Pill(self.pills, '', 'good')
        self.check_pill.configure(cursor='hand2')
        self.check_pill.bind('<Button-1>', lambda _e: self.show_check())
        _tip(self.check_pill, lambda: 'Click to open the Sheet check.\n' + self.model.check_summary(compute=False))
        self._check_pill_shown = False

    def build_check_button(self, foot):
        b = ttk.Button(foot, text='Sheet check', style='Compact.TButton', command=self.show_check)
        b.pack(side='left', padx=(0, 6))
        _tip(b, 'Check the sheet against the build rules: calibrator coverage, unverified commands, units, a dry run on the simulated instruments, uncertainty sources.')
        self.check_b = b

    def refresh_check(self):
        text, kind = self.model.check_pill()
        if text:
            self.check_pill.set(text, kind)
            if not self._check_pill_shown:
                self.check_pill.pack(side='left', padx=(8, 0))
                self._check_pill_shown = True
        elif self._check_pill_shown:
            self.check_pill.pack_forget()
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
            if win is not None and win.winfo_exists():
                win.reload()
                win.lift()
                return win
        except tk.TclError:
            pass
        win = self._check_win = SheetCheckWindow(self)
        self.dialogs.append(win)
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
        yes = bool(messagebox.askyesno('Run on real instruments', text, icon='warning', default='no', parent=self))
        self._accepted_unverified = fingerprint if yes else ''
        return yes
