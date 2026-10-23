"""Window option 'iFlex probe supplied: run the iFlex tests' for the Fluke 374 / 375 / 376 / 376-II clamp meter procedures (handheld engine, handheld_dmm.App).

Not every clamp meter is received with its iFlex probe.  This option decides whether the iFlex tests (the steps tagged "include": "iflex" in specs/fluke_376_pv.json: the 5 iFlex
simulated points and the 4 iFlex-with-coil points) are part of the run.  It is a subclass of handheld_dmm.App and touches NO shared file: the engine's own hooks are used
(build_points, report_header, source_note, save_fields, load_results, execute).

Behaviour
  * Declared in the spec: options.include_toggles = [{id, label, default, off_text, on_text, count_text}]; a step belongs to a toggle by step['include'] = <id>.  A spec without
    include_toggles runs exactly as handheld_dmm.App does.
  * Default ON (every test is run); turning it OFF asks for a confirmation and says what happens; nothing is skipped silently.
  * While OFF the tagged points are not in the point list: they are not run, not asked for, not counted, not in the section list and not shown as pending or failed; the point numbers
    ("point 12 of 29"), the progress counts and the prompts follow the shorter list.
  * Changing it never discards a reading: a tagged point that already has a recorded reading (As Found or As Left) stays in the list and in the report while the option is OFF.
    It cannot be changed while a run is active.
  * Audit record: the progress (checkpoint) file stores the setting (include) and a log of every change (include_log: time, setting, readings recorded at that moment); the report
    header carries a line 'iFlex tests' (Tested (iFlex supplied) / Not tested (no iFlex supplied)) and the report note repeats it.  The point rows of a report are the recorded points,
    as for every handheld report: the points that were not run have no row (the existing convention for unrecorded points).
  * A run queue (several meters, one point at a time) shares one window; the setting is per meter, so the queue is not offered for these procedures (QUEUE_SUPPORTED False).

    iflex_option.main('376', spec='fluke_376_pv.json')       # what Procedures/Fluke_376_Verification.py does
"""
from __future__ import annotations

import re
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import handheld_dmm
import virtualbench


class App(handheld_dmm.App):
    QUEUE_SUPPORTED = False

    # ------------------------------------------------------------------ the options
    def include_defs(self):
        return list(self.spec.get('options', {}).get('include_toggles') or [])

    def build_points(self):
        self._all_points = super().build_points()
        defs = self.include_defs()
        self._include = {d['id']: bool(d.get('default', True)) for d in defs}
        self._include_log = []
        return [p for p in self._all_points if self._wanted(p)]

    def _recorded_ids(self):
        found, left = getattr(self, '_found', None) or {}, getattr(self, '_left', None) or {}
        return set(found) | set(left)

    def _wanted(self, p):
        """True when the point is part of the run: its toggle is ON, or it already has a recorded reading (a reading is never discarded)."""
        key = p.get('include')
        if not key or self._include.get(key, True):
            return True
        return p['id'] in self._recorded_ids()

    def include_is_on(self, key='iflex'):
        return bool(self._include.get(key, True))

    def _relist(self):
        """Rebuild self.points in place (the procedure-modification list and the tree hold the same list object) after the setting changed."""
        st = self.pm_state
        if st is not None:
            self.pm_revert(self.points)                      # procedure modifications: the factory points back in the list before it changes (they are applied again by the next Run)
        keep = [p for p in self._all_points if self._wanted(p)]
        for n, p in enumerate(keep, 1):
            p['n'] = n
        self.points[:] = keep
        self.by_id = {p['id']: p for p in self.points}
        if st is not None:
            st.lists.pop(id(self.points), None)              # the modification layer keeps a copy of the list it restores on every Run: it must be this list, not the first one
            st.register(self.points)
        if self.show_section.get() not in ['All sections'] + [p['section'] for p in self.points]:
            self.show_section.set('All sections')

    def set_include(self, key, value, ask=True):
        """Switch a toggle; returns True when it changed.  Refused while a run is active."""
        value = bool(value)
        if self._include.get(key, True) == value:
            return False
        d = next(x for x in self.include_defs() if x['id'] == key)
        if self.busy:
            self.status.set(f'The setting "{d["label"]}" cannot be changed while a run is active. Stop the run first.')
            return False
        tagged = [p for p in self._all_points if p.get('include') == key]
        if not value and ask:
            recorded = sum(1 for p in tagged if p['id'] in self._recorded_ids())
            text = (f'Turn OFF "{d["label"]}"?\n\n{len(tagged) - recorded} {d.get("count_text", "point")}(s) will not be run or asked for, and the report will state '
                    f'"{d.get("off_text", "not tested")}".')
            if recorded:
                text += f'\n\n{recorded} reading(s) already recorded stay in the list and in the report.'
            if not messagebox.askyesno('Skip the iFlex tests', text):
                return False
        self._include[key] = value
        self._include_log.append(dict(time=datetime.now().isoformat(timespec='seconds'), id=key, value=value, recorded=len(self._recorded_ids())))
        self._relist()
        self._sync_include_widgets()
        self.refresh()
        self.status.set(self.include_text(key))
        if self._recorded_ids():                                   # progress already exists: the change is saved with it (never an empty progress file over an earlier one)
            self.save(silent=True)
        return True

    def include_text(self, key='iflex', short=False):
        d = next((x for x in self.include_defs() if x['id'] == key), None)
        if not d:
            return ''
        n = sum(1 for p in self._all_points if p.get('include') == key)
        shown = sum(1 for p in self.points if p.get('include') == key)
        lead = '' if short else f'{d["label"]}: '
        if self.include_is_on(key):
            return f'{lead}ON, {n} {d.get("count_text", "point")}(s) in the run ({len(self.points)} points in all).'
        return (f'{lead}OFF, {d.get("off_text", "not tested")}: {n - shown} {d.get("count_text", "point")}(s) not run' +
                (f', {shown} recorded earlier kept' if shown else '') + f' ({len(self.points)} points in all).')

    # ------------------------------------------------------------------ window
    def _build_ui(self):
        super()._build_ui()
        defs = self.include_defs()
        if not defs:
            return
        self._include_vars, self._include_labels = {}, {}
        bar = ttk.Frame(self.shell.content)
        slaves = self.shell.content.pack_slaves()
        bar.pack(side='top', fill='x', pady=(0, 6), **({'before': slaves[0]} if slaves else {}))
        self.include_bar = bar
        for d in defs:
            var = tk.BooleanVar(self.root, value=self._include.get(d['id'], True))
            self._include_vars[d['id']] = var
            ttk.Checkbutton(bar, text=d['label'], variable=var, command=lambda k=d['id']: self._on_include_click(k)).pack(side='left')
            label = ttk.Label(bar, text=self.include_text(d['id'], short=True), style='Muted.TLabel')
            label.pack(side='left', padx=(12, 0))
            self._include_labels[d['id']] = label
        self.refresh()

    def _on_include_click(self, key):
        var = self._include_vars[key]
        if not self.set_include(key, var.get()):
            var.set(self._include.get(key, True))             # refused (run active) or cancelled: the box shows the setting that is really in force

    def _sync_include_widgets(self):
        for key, var in getattr(self, '_include_vars', {}).items():
            if bool(var.get()) != self._include.get(key, True):
                var.set(self._include.get(key, True))
            self._include_labels[key].configure(text=self.include_text(key, short=True))
        sub = self.shell.subtitle.get() if hasattr(self, 'shell') else None
        if isinstance(sub, str):                                   # the banner says how many points the window has
            self.shell.subtitle.set(re.sub(r'\|  \d+ points  \|', f'|  {len(self.points)} points  |', sub))

    # ------------------------------------------------------------------ run
    def execute(self, points):
        super().execute([p for p in points if self._wanted(p)])

    # ------------------------------------------------------------------ progress file
    def save_fields(self):
        out = super().save_fields()
        if self.include_defs():
            out['include'] = dict(self._include)
            out['include_log'] = list(self._include_log)
        return out

    def load_results(self, data):
        super().load_results(data)
        if not self.include_defs():
            return
        saved = data.get('include') or {}
        for d in self.include_defs():                          # a progress file saved before this option existed: the default (ON)
            self._include[d['id']] = bool(saved.get(d['id'], d.get('default', True)))
        self._include_log = list(data.get('include_log') or [])
        self._relist()
        self._sync_include_widgets()

    # ------------------------------------------------------------------ report
    def include_report_lines(self):
        lines = []
        for d in self.include_defs():
            on = self.include_is_on(d['id'])
            kept = sum(1 for p in self.points if p.get('include') == d['id'])
            lines.append((d['id'], d['label'], (d.get('on_text', 'tested') if on else d.get('off_text', 'not tested') +
                                                (f'; {kept} reading(s) recorded before it was turned off are included' if kept else ''))))
        return lines

    def report_header(self, src):
        rows = list(super().report_header(src))
        for key, label, text in self.include_report_lines():
            rows.append(('iFlex tests' if key == 'iflex' else label, text[:1].upper() + text[1:]))
        return rows

    def source_note(self):
        note = super().source_note()
        extra = ' '.join(f'{label}: {text}.' for key, label, text in self.include_report_lines())
        return ' '.join(x for x in (note, extra) if x)


def main(model, argv=None, spec=None):
    """spec: a spec file name inside specs/ (or a path)."""
    import sys
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    demo, fast = virtualbench.flags(argv)
    App(root, model, demo=demo, spec=handheld_dmm.load_spec(spec) if spec else None, fast_demo=fast)
    root.mainloop()
