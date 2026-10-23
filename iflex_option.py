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
  * Run queue (several meters of one model): the setting is PER METER.  Every queue meter carries its own 'iFlex supplied' value (default ON; meter.extra['include'], saved in the
    queue file <brand><model>_queue.json and, with the meter's own readings, in that meter's checkpoint), shown in the Connections drawer (one check box per meter), in the
    queue chip and in the set-up list, and editable under the same rules as the single-meter box (not while a run is active, never discarding a recorded reading).  The window
    lists the UNION of the points any meter takes part in; a meter that has the setting OFF is left out of those points by the run-queue planner (meter.wants), so a point is
    asked for, and its cable / function / high-voltage prompts name, only the meters that need it.  Each meter's report carries its own 'iFlex tests' line.

    iflex_option.main('376', spec='fluke_376_pv.json')       # what Procedures/Fluke_376_Verification.py does
"""
from __future__ import annotations

import re
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import handheld_dmm
import run_queue as RQ
import ui_theme as ui
import virtualbench


def _key(asset):
    return str(asset or '').strip().casefold()


class App(handheld_dmm.App):

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

    def _qmeters(self):
        """The meters of an active run queue (two or more); empty for the plain single-meter run."""
        return list(self.queue.meters) if self.queue_wants_run() else []

    def _wanted(self, p):
        """True when the point is part of the run: its toggle is ON, or it already has a recorded reading (a reading is never discarded).
        With a run queue the window lists every point at least one meter takes part in."""
        ms = self._qmeters()
        if ms:
            return any(self._meter_wants(m, p) for m in ms)
        key = p.get('include')
        if not key or self._include.get(key, True):
            return True
        return p['id'] in self._recorded_ids()

    # ------------------------------------------------------------------ per meter (run queue)
    def _defaults(self):
        return {d['id']: bool(d.get('default', True)) for d in self.include_defs()}

    @staticmethod
    def _clean_include(raw, defaults):
        raw = raw if isinstance(raw, dict) else {}
        return {k: (bool(raw[k]) if k in raw else v) for k, v in defaults.items()}

    def _seed_for(self, asset):
        """(include, log, saved ids) a meter starts with when it is not in memory yet: its saved checkpoint when that holds readings (the setting that was in force),
        else the queue file, else the defaults (ON)."""
        defaults = self._defaults()
        seeds = self.__dict__.get('_include_seed') or {}
        if _key(asset) in seeds:
            return seeds[_key(asset)]
        try:
            data = self._queue_checkpoint_for(asset)
        except Exception:
            data = None
        if data and (data.get('results') or data.get('left_results')):
            ids = {str(k) for k in (data.get('results') or {})} | {str(k) for k in (data.get('left_results') or {})}
            return self._clean_include(data.get('include'), defaults), list(data.get('include_log') or []), ids
        try:
            saved = RQ.read_queue(self._queue_path())
        except Exception:
            saved = None
        if isinstance(saved, dict) and saved.get('model') == self.model and bool(saved.get('demo')) == bool(self.demo):
            for row in saved.get('meters') or []:
                if isinstance(row, dict) and _key(row.get('asset')) == _key(asset):
                    return self._clean_include(row.get('include'), defaults), [], set()
        return dict(defaults), [], set()

    def _ensure_meter(self, m):
        """The meter's own include settings (created on first use) and the filter the run-queue planner asks (meter.wants)."""
        inc = m.extra.get('include')
        if isinstance(inc, dict):
            m.extra['include'] = self._clean_include(inc, self._defaults())
        else:
            inc, log, ids = self._seed_for(m.asset)
            m.extra['include'] = inc
            m.include_log = log
            m.saved_ids = ids
        if getattr(m, 'include_log', None) is None:
            m.include_log = []
        if getattr(m, 'saved_ids', None) is None:
            m.saved_ids = set()
        if m.skip is None:
            m.skip = lambda p, m=m: not self._meter_wants(m, p)
        return m.extra['include']

    def _meter_wants(self, m, p):
        key = p.get('include')
        if not key or self._ensure_meter(m).get(key, True):
            return True
        pid = str(p['id'])
        return pid in m.found or pid in m.left or pid in m.saved_ids          # a recorded reading (or one waiting in the meter's checkpoint) is never dropped

    def _shown_meter(self):
        ctx = self.queue_ctx
        return ctx if ctx is not None and ctx in self.queue.meters else None

    def _points_for(self, m):
        if m is not None and self._qmeters():
            return [p for p in self.points if self._meter_wants(m, p)]
        return list(self.points)

    def _shown_points(self):
        return self._points_for(self._shown_meter())

    def _visible(self, p):
        m = self._shown_meter()
        if m is not None and self._qmeters() and not self._meter_wants(m, p):
            return False                                                  # a point this meter does not take part in is not shown as pending or failed
        return super()._visible(p)

    def update_summary(self):
        pts = self._shown_points()
        self.update_shell_progress(pts)
        self.update_shell_sections(pts, lambda p: p['section'])

    def queue_total(self, m):
        return sum(1 for p in self.points if self._meter_wants(m, p))

    def queue_prepare_meters(self, meters):
        for m in meters:
            self._ensure_meter(m)

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

    def set_include(self, key, value, ask=True, meter=None):
        """Switch a toggle; returns True when it changed.  Refused while a run is active.  With a run queue it is the setting of one meter (`meter`, default the one shown)."""
        value = bool(value)
        m = meter if meter is not None else self._shown_meter()
        if m is not None and m not in self.queue.meters:
            m = None
        shown = m is None or m is self._shown_meter()
        inc = self._ensure_meter(m) if m is not None else self._include
        if inc.get(key, True) == value:
            return False
        d = next(x for x in self.include_defs() if x['id'] == key)
        who = f'asset {m.asset}: ' if m is not None and self._qmeters() else ''
        if self.busy:
            self.status.set(f'{who}The setting "{d["label"]}" cannot be changed while a run is active. Stop the run first.')
            return False
        tagged = [p for p in self._all_points if p.get('include') == key]
        recorded_ids = (set(m.found) | set(m.left)) if m is not None else self._recorded_ids()
        if not value and ask:
            recorded = sum(1 for p in tagged if p['id'] in recorded_ids)
            text = (f'{"Asset " + m.asset + chr(10) + chr(10) if who else ""}Turn OFF "{d["label"]}"?\n\n{len(tagged) - recorded} {d.get("count_text", "point")}(s) will not be run or asked for, '
                    f'and the report will state "{d.get("off_text", "not tested")}".')
            if recorded:
                text += f'\n\n{recorded} reading(s) already recorded stay in the list and in the report.'
            if not messagebox.askyesno('Skip the iFlex tests', text):
                return False
        inc[key] = value
        log = m.include_log if m is not None else self._include_log
        log.append(dict(time=datetime.now().isoformat(timespec='seconds'), id=key, value=value, recorded=len(recorded_ids)))
        if m is not None and shown:
            self._include[key] = value
            self._include_log = log
        self._relist()
        self._sync_include_widgets()
        self.refresh()
        self.status.set(who + self.include_text(key, meter=m))
        if m is not None:
            RQ.save_queue(self._queue_path(), self.queue, self.model, self.demo)
            self._queue_update_chip()
        if recorded_ids:                                           # progress already exists: the change is saved with it (never an empty progress file over an earlier one)
            if shown:
                self.save(silent=True)
            else:
                keep = self.queue_ctx
                self._queue_activate(m)
                self.save(silent=True)
                self._queue_activate(keep)
        return True

    def include_text(self, key='iflex', short=False, meter=None):
        d = next((x for x in self.include_defs() if x['id'] == key), None)
        if not d:
            return ''
        m = meter if meter is not None else self._shown_meter()
        inc = self._ensure_meter(m) if m is not None and self._qmeters() else self._include
        pts = self._points_for(m)
        n = sum(1 for p in self._all_points if p.get('include') == key)
        shown = sum(1 for p in pts if p.get('include') == key)
        lead = '' if short else f'{d["label"]}: '
        if m is not None and self._qmeters():
            lead = f'Asset {m.asset}: ' + lead
        if inc.get(key, True):
            return f'{lead}ON, {n} {d.get("count_text", "point")}(s) in the run ({len(pts)} points in all).'
        return (f'{lead}OFF, {d.get("off_text", "not tested")}: {n - shown} {d.get("count_text", "point")}(s) not run' +
                (f', {shown} recorded earlier kept' if shown else '') + f' ({len(pts)} points in all).')

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
        self._rebuild_include_rows()
        sub = self.shell.subtitle.get() if hasattr(self, 'shell') else None
        if isinstance(sub, str):                                   # the banner says how many points the window has
            self.shell.subtitle.set(re.sub(r'\|  \d+ points  \|', f'|  {len(self.points)} points  |', sub))

    # ------------------------------------------------------------------ run
    def execute(self, points):
        super().execute([p for p in points if self._wanted(p)])

    # ------------------------------------------------------------------ run queue: one setting per meter
    def _queue_activate(self, m):
        super()._queue_activate(m)
        self._include = dict(self._ensure_meter(m))                         # the window shows (and a single-meter run uses) this meter's own setting
        self._include_log = m.include_log
        if getattr(self, '_include_vars', None):
            for key, var in self._include_vars.items():
                if bool(var.get()) != self._include.get(key, True):
                    var.set(self._include.get(key, True))
                self._include_labels[key].configure(text=self.include_text(key, short=True))

    def _seeds_from_queue(self):
        seeds = {}
        for m in self.queue.meters:
            seeds[_key(m.asset)] = (dict(self._ensure_meter(m)), list(m.include_log), set(m.saved_ids))
        return seeds

    def apply_queue(self, meters, mode):
        """A meter that stays keeps its setting; a new one gets the setting of its saved progress, else of the queue file, else ON."""
        seeds = self._seeds_from_queue()
        for asset, _serial, _tech in meters:
            if _key(asset) not in seeds:
                seeds[_key(asset)] = self._seed_for(asset)
        self.__dict__['_include_seed'] = seeds
        try:
            super().apply_queue(meters, mode)
        finally:
            self.__dict__.pop('_include_seed', None)
        for m in self.queue.meters:
            self._ensure_meter(m)
        shown = self._shown_meter()
        if shown is not None:
            self._queue_activate(shown)
        self._relist()
        self._sync_include_widgets()
        self.refresh()
        RQ.save_queue(self._queue_path(), self.queue, self.model, self.demo)
        self._queue_update_chip()

    def _queue_resume(self):
        ok = super()._queue_resume()
        for m in self.queue.meters:
            m.saved_ids = set()                                            # resumed readings are in the meter now; 'start over' leaves nothing waiting
        if ok:
            self._relist()
            self.refresh()
        return ok

    def queue_sync_after_load(self):
        super().queue_sync_after_load()
        m = self._shown_meter()
        if m is None:
            return
        m.extra['include'] = self._clean_include(self._include, self._defaults())      # 'Load progress' brought the setting that file was saved with
        m.include_log = self._include_log
        self._relist()
        self._sync_include_widgets()
        RQ.save_queue(self._queue_path(), self.queue, self.model, self.demo)
        self._queue_update_chip()

    def _next(self, points, i, previous):
        self.__dict__['_cur_point'] = points[i] if i < len(points) else None
        super()._next(points, i, previous)

    def _q_names(self):
        q = self._q
        if q is None or q.unit is None:
            return ''
        p = self.__dict__.get('_cur_point')
        ms = q.unit.needs.get(str(p['id'])) if (p is not None and q.unit.shared) else None
        return ', '.join(m.asset for m in (ms or q.unit.meters))               # the meters that are wired for THIS point (a meter without the iFlex tests is not)

    def _queue_tick(self, p):
        q = self._q
        if q is None or p is None or q.unit is None or not q.unit.shared:
            return super()._queue_tick(p)
        ms = q.unit.needs.get(str(p['id']), q.unit.meters)
        self._queue_progress_update(f'Point {p["n"]} of {len(self.points)}  -  ' + (f'all {len(ms)} meters' if len(ms) == len(self.queue.meters) else f'{len(ms)} meters: ' + ', '.join(m.asset for m in ms)))

    def _inc_label(self, inc):
        d = next(iter(self.include_defs()), None)
        return 'iFlex' if d and d['id'] == 'iflex' else (d['id'] if d else '')

    def queue_status_text(self, asset):
        m = self.queue.find(asset)
        left = self.is_left
        if m is not None:
            inc = self._ensure_meter(m)
            n = self.queue_total(m)
        else:
            inc, _log, _ids = self._seed_for(asset)
            n = sum(1 for p in self._all_points if not p.get('include') or inc.get(p['include'], True))
        d = next(iter(self.include_defs()), None)
        tail = f'  |  {self._inc_label(inc)} {"ON" if inc.get(d["id"], True) else "OFF"}' if d else ''
        if m is not None and (m.found or m.left):
            return f'{len(m.results(left))} of {n} recorded' + (f' ({m.status})' if m.status not in ('Ready', 'Running') else '') + tail
        saved = self._queue_saved_counts(asset)
        return (f'Saved progress: {saved} of {n}' if saved else 'Ready') + tail

    def queue_chip_text(self):
        text = super().queue_chip_text()
        d = next(iter(self.include_defs()), None)
        if not text or d is None:
            return text
        on = sum(1 for m in self.queue.meters if self._ensure_meter(m).get(d['id'], True))
        n = len(self.queue.meters)
        who = 'ON for all' if on == n else 'OFF for all' if on == 0 else f'ON for {on} of {n}'
        return f'{text}, {self._inc_label(None)} {who}'

    def _queue_update_chip(self):
        super()._queue_update_chip()
        self._rebuild_include_rows()

    def build_queue_drawer(self, d, row):
        nxt = super().build_queue_drawer(d, row)
        if not self.include_defs():
            return nxt
        self._inc_rows = ttk.Frame(d)
        self._inc_rows.grid(row=nxt, column=0, columnspan=2, sticky='ew', pady=(6, 0))
        self._inc_row_vars, self._inc_row_notes, self._inc_rows_sig = {}, {}, None
        self._rebuild_include_rows()
        return nxt + 1

    def _rebuild_include_rows(self):
        """The Connections drawer: one 'iFlex supplied' check box for every meter of the queue (the window box is the one of the meter shown)."""
        box = getattr(self, '_inc_rows', None)
        if box is None:
            return
        meters, defs = list(self.queue.meters), self.include_defs()
        sig = tuple(m.asset for m in meters)
        if defs and meters and sig == getattr(self, '_inc_rows_sig', None):          # same meters: update the boxes in place (the box being clicked stays)
            for m in meters:
                inc = self._ensure_meter(m)
                self._inc_row_vars[m.asset].set(bool(inc.get(defs[0]['id'], True)))
                self._inc_row_notes[m.asset].configure(text=self._meter_include_note(m, defs[0]))
            return
        for w in list(box.winfo_children()):
            w.destroy()
        self._inc_row_vars, self._inc_row_notes, self._inc_rows_sig = {}, {}, sig
        if not meters or not defs:
            return
        d = defs[0]
        ttk.Label(box, text=f'{self._inc_label(None)} probe, per meter', style='Bold.TLabel').grid(row=0, column=0, sticky='w')
        box.columnconfigure(0, weight=1)
        for r, m in enumerate(meters):
            inc = self._ensure_meter(m)
            var = tk.BooleanVar(self.root, value=bool(inc.get(d['id'], True)))
            self._inc_row_vars[m.asset] = var
            ttk.Checkbutton(box, text=f'{m.asset}: {self._inc_label(None)} supplied', variable=var,
                            command=lambda m=m, v=var: self._on_meter_include_click(m, v)).grid(row=1 + 2 * r, column=0, sticky='w', pady=(4, 0))
            note = ttk.Label(box, text=self._meter_include_note(m, d), style='Muted.TLabel', wraplength=ui.px(320), justify='left')
            note.grid(row=2 + 2 * r, column=0, sticky='w', padx=(24, 0))
            self._inc_row_notes[m.asset] = note

    def _meter_include_note(self, m, d):
        inc = self._ensure_meter(m)
        n = sum(1 for p in self.points if self._meter_wants(m, p)) if self._qmeters() else len(self.points)
        return (f'{n} points' if inc.get(d['id'], True) else f'{n} points, {d.get("off_text", "not tested")}')

    def _on_meter_include_click(self, m, var):
        key = self.include_defs()[0]['id']
        if not self.set_include(key, var.get(), meter=m):
            var.set(bool(self._ensure_meter(m).get(key, True)))                # refused (run active) or cancelled: the box shows the setting really in force

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
            recorded = self._recorded_ids()
            kept = sum(1 for p in self._all_points if p.get('include') == d['id'] and p['id'] in recorded)
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
