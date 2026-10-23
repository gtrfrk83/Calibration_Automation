"""Per-point manual override for user-built datasheets (rule 13 of the Datasheet Builder run-time rules; owner request, same wish as the 8808A's).

A technician may type a reading for any numeric point of a user-built datasheet: right-click the point > 'Enter reading manually...'.  It reuses
manual_override.ManualOverrideMixin (the 8808A's mixin: the right-click entry, the armed-while-measuring / replace-when-idle logic, the command-log line);
only what depends on a handheld point (its limits are strings in the DISPLAY unit, `factor` gives the base unit) is done here:

  * `parse_typed(p, text)`   a typed reading -> Typed (padded to the point's resolution by handheld_dmm.pad_reading, judged by handheld_dmm.judge_numeric):
                             the SAME entry, padding and judging as a reading typed in the reading window / the grid of a manual calibration.
  * the dialog and the confirmation ('Use 1.0003 V as the reading for point N?').
  * NO NOTE ON THE REPORT.  The trace is the COMMAND LOG line 'MANUAL OVERRIDE point N: auto reading X (or none), entered Y' and the progress file
    (`overridden`, `auto_reading` on the point's record).  The report rows are built from reading + result only, as for the 8808A; the record keeps the
    standard that was routed for the point, so a report with an override is identical to one without.
  * Demo: recorded as synthetic like every demo result; nothing is written to the shared command log.
Pass / fail is not decided here: the datasheet's limits judge the typed value.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from tkinter import messagebox, ttk
import tkinter as tk

import handheld_dmm as hh
import manual_override as MO
import ui_theme as ui

NOT_A_NUMBER = MO.NOT_A_NUMBER


@dataclass(frozen=True)
class Typed:
    text: str           # the typed reading, filled out to the point's resolution (what the sheet shows and prints)
    value: float        # the same reading in BASE units (judged, stored)
    unit: str           # display unit of `text`
    result: str         # 'PASS' / 'FAIL' by the datasheet's limits

    @property
    def shown(self) -> str:
        return f'{self.text} {self.unit}'.strip()


def parse_typed(p, text) -> Typed:
    """A typed reading -> Typed.  Raises ValueError (message to show) for anything that is not a plain finite number."""
    raw = (text or '').strip()
    if not raw:
        raise ValueError(NOT_A_NUMBER)
    if ',' in raw:
        raise ValueError('Use a decimal point, not a comma.')
    if raw.upper().replace('.', '') in ('OL', '0L', 'OVERLOAD'):
        raise ValueError('An overload cannot be entered here: type the number, or stop the run and check the input, range and function.')
    padded = hh.pad_reading(p, raw)
    result, base = hh.judge_numeric(p, padded, True)             # ValueError: not a number / NaN / infinity
    if base is None or abs(base) >= MO.OVERLOAD_LIMIT:
        raise ValueError('That is larger than any instrument here can read (overload).')
    return Typed(padded, base, p.get('display_unit') or '', result)


def base_text(p, value) -> str:
    unit = MO.ascii_text(hh.SYMBOL.get(p.get('base_unit'), p.get('base_unit') or ''))
    return f'{float(value):.9g} {unit}'.strip()


def log_text(p, typed: Typed, auto=None, why='', mode='') -> str:
    """'MANUAL OVERRIDE point N: auto reading X (or none), entered Y' - the command-log line (ASCII, no secrets)."""
    auto_t = 'none' + (f' ({why})' if why else '') if auto is None else base_text(p, auto)
    return (f'MANUAL OVERRIDE point {p["id"]}: auto reading {auto_t}, entered {MO.ascii_text(typed.shown)} = {base_text(p, typed.value)}'
            + (f' [{mode}]' if mode else ''))


def ask_typed(parent, p, total, reason='', cancel_text='Cancel', demo=False, stored=''):
    """Modal entry window.  Returns Typed, or None when cancelled / stopped.  The short confirmation is asked after the typed value is valid."""
    result = {'v': None}
    win = ui.dialog(parent, f'Point {p["n"]} of {total} - enter the reading')
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(ui.px(22), ui.px(16), ui.px(22), ui.px(14)))
    outer.pack(fill='both', expand=True)
    wrap = ui.px(520)
    unit = p.get('display_unit') or ''
    ttk.Label(outer, text=f'Point {p["n"]} of {total}  -  {p["section"]}', style='Small.TLabel').pack(anchor='w')
    ttk.Label(outer, text=hh.describe(p), style='Section.TLabel', wraplength=wrap, justify='left').pack(anchor='w', pady=(2, 8))
    if reason:
        ttk.Label(outer, text='The automatic reading failed: ' + reason, style='Bold.TLabel', wraplength=wrap, justify='left',
                  foreground=ui.C.get('bad', '#B3261E')).pack(anchor='w', pady=(0, 8))
    elif stored:
        ttk.Label(outer, text=f'Stored reading: {stored}. Typing a value replaces it.', style='Small.TLabel', wraplength=wrap, justify='left').pack(anchor='w', pady=(0, 8))
    if demo:
        ttk.Label(outer, text='DEMO: the value you type is recorded as demo data. Nothing here is calibration evidence.', style='Small.TLabel',
                  wraplength=wrap, justify='left', foreground=ui.C.get('warn', '#B26A00')).pack(anchor='w', pady=(0, 8))
    ttk.Label(outer, text='TYPE THE READING', style='MetricCap.TLabel').pack(anchor='w')
    row = ttk.Frame(outer)
    row.pack(fill='x', pady=(4, 0))
    text = tk.StringVar()
    entry = ttk.Entry(row, textvariable=text, width=16)
    entry.pack(side='left')
    ttk.Label(row, text=unit, style='Bold.TLabel').pack(side='left', padx=(10, 0))
    ttk.Label(outer, text=f'Acceptable reading: {p["low"]} to {p["high"]} {unit}', style='Small.TLabel').pack(anchor='w', pady=(6, 0))
    error = tk.StringVar()
    ttk.Label(outer, textvariable=error, wraplength=wrap, justify='left', foreground=ui.C.get('bad', '#B3261E')).pack(anchor='w', pady=(6, 0))

    def done(use):
        if not use:
            win.destroy()
            return
        try:
            typed = parse_typed(p, text.get())
        except ValueError as exc:
            error.set(str(exc))
            return
        error.set('')
        if not messagebox.askyesno('Use this reading?', f'Use {typed.shown} as the reading for point {p["n"]}?', parent=win):
            entry.focus_set()
            return
        result['v'] = typed
        win.destroy()
    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(14, 0))
    ok = ttk.Button(bar, text='Use this reading  (Enter)', style='Accent.TButton', command=lambda: done(True))
    ok.pack(side='right')
    ttk.Button(bar, text=cancel_text, style='Danger.TButton' if reason else 'TButton', command=lambda: done(False)).pack(side='left')
    win.bind('<Return>', lambda _e: done(True))
    win.protocol('WM_DELETE_WINDOW', lambda: done(False))
    ui.center_on(win, parent.winfo_toplevel())
    entry.focus_set()
    win.wait_window()
    return result['v']


class DsbOverrideMixin(MO.ManualOverrideMixin):
    """For dsb_runtime.DsbApp.  Provides the right-click 'Enter reading manually...' (no action-bar button: the owner asked for the point's menu)."""
    MANUAL_OVERRIDE = True

    # ---- hooks of ManualOverrideMixin ------------------------------------------------------------------------------------------
    def mo_point(self, iid):
        return self.by_id[iid]

    def mo_total(self) -> int:
        return len(self.points)

    def mo_mode_label(self) -> str:
        return getattr(self, 'mode_label', '')

    def mo_state(self, p):
        if p.get('test') != 'numeric':
            return False, 'This point is answered Yes / No, not typed as a number: answer it in the reading window.'
        if self.is_skipped(p):
            return False, 'This section is set to Not tested. Change the section setting first.'
        if self.busy and (self._mo_current is None or self._mo_current['id'] != p['id']):
            return False, 'A run is in progress: only the point being measured by a standard can be entered. Other points are typed in their reading window.'
        return True, ''

    def mo_ask(self, p, reason='', cancel_text='Cancel', stored=''):
        return ask_typed(self.root, p, self.mo_total(), reason=reason, cancel_text=cancel_text, demo=self.demo, stored=stored)

    # ---- an idle point (measured or not) ------------------------------------------------------------------------------------------
    def mo_replace(self, p):
        if not self.asset.get().strip():
            messagebox.showwarning('Instrument ID', 'Enter an instrument ID.', parent=self.root)
            return
        if not self.confirm_found_overwrite([p]):
            return
        old = self.results.get(str(p['id'])) or {}
        stored = f'{old["entered"]} {p.get("display_unit") or ""}'.strip() if old.get('entered') not in (None, '') else ''
        typed = self.mo_ask(p, stored=stored)
        if typed is None:
            return
        auto = old.get('auto_reading') if old.get('overridden') else old.get('reading')       # the reading the standard gave, not an earlier typed one
        self.mo_commit(p, typed, auto, why='' if old else 'point not measured', idle=True)
        self.status.set(f'Point {p["n"]}: reading {typed.shown} entered by hand.')

    # ---- recording ---------------------------------------------------------------------------------------------------------------------
    def mo_commit(self, p, typed: Typed, auto=None, why='', idle=False):
        """Log, then record the typed value through the datasheet's own typed path (padding and limits as for any typed reading)."""
        mode = (self.mo_mode_label() + (', demo' if self.demo else '')).strip(', ')
        self.mo_log(log_text(p, typed, auto, why, mode))
        if idle and getattr(self, 'io', None) is not None and not self.demo:
            try:
                self.io.standby()                      # nothing was output, but the standing rule is 'standby after every point': make sure
            except Exception:
                pass
        fields = dict(entered=typed.text, reading=typed.value, result=typed.result, annunciator=None, source='typed', overridden=True, auto_reading=auto)
        old = self.results.get(str(p['id'])) or {}
        if idle and old.get('standard'):                 # the record keeps the standard that was routed: the report is the same with or without an override
            fields['standard'] = old['standard']
            if old.get('route') is not None:
                fields['route'] = old['route']
        self._store(p, **fields)
