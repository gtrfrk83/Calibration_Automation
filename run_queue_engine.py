"""Run-queue logic for the handheld engine (handheld_dmm.App mixes in QueueMixin).  See run_queue.py for what a queue is.

HOW IT FITS THE EXISTING ENGINE.  The point loop (`App._next` and its prompts) is NOT copied: a queue run drives the same `_next` over a list of
points, once per UNIT of the plan (run_queue.plan):

  shared unit   all meters are on the calibrator.  `_next` runs the points once; the hook-up / function / HV prompts appear once and name every
                meter; the calibrator is set once per point; `_ask` shows ONE reading window for all meters and stores one record per meter.
  single unit   one meter: `_next` runs exactly as in a single-meter run (same windows, same prompts), with that meter's context active.

A meter's context (asset / serial variables, its two result dicts, its rest timer) is swapped in with `_queue_activate`, so everything the engine
does per asset - `_store`, the checkpoint file, the report rows, `certificate_*`, Asset History through write_calibration_pdf - is that meter's own.
With fewer than two meters in the queue none of this runs: `execute` goes the old way.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import run_queue as RQ
import ui_theme_core as ui                     # toolkit-free helpers only (Settings, report_filename); the windows are run_queue_view_qt.py / run_queue_ui.py
import virtualbench
from ui_port import ui as port


class QueueRun:
    """State of one queue run."""

    def __init__(self, units, mode, points, force=False):
        self.units, self.mode, self.points, self.force = list(units), mode, points, force
        self.unit: Any = None
        self.active: list[Any] = []      # meters read at the current point
        self.current: Any = None
        self.progress: Any = None        # the QueueProgress window (or None)
        self.total_units = len(units)


class QueueMixin:
    # Supplied by the procedure window this mixin is combined with (declared for the type checker only: these lines create nothing).
    _checkpoint_path: Any
    _next: Any
    _out_note: Any
    _record_demo: Any
    _safe_standby: Any
    _store: Any
    _update_row: Any
    _visible: Any
    accept_text: Any
    any_synthetic: Any
    asset: Any
    brand: Any
    calibrator_model: Any
    certificate_fields: Any
    certificate_rows_and_points: Any
    checkpoint_problem: Any
    confirm_found_overwrite: Any
    demo: Any
    fast_demo: Any
    info: Any
    io: Any
    ir: Any
    is_left: Any
    manual_cal: Any
    meter: Any
    model: Any
    pm_begin_run: Any
    pm_on_checkpoint: Any
    pm_state: Any
    points: Any
    read_mode: Any
    reading_labels: Any
    refresh: Any
    report_details: Any
    report_header: Any
    report_title: Any
    reset_then: Any
    root: Any
    run_all: Any
    save: Any
    serial: Any
    show_section: Any
    show_status: Any
    source_note: Any
    spec: Any
    status: Any
    temperature_note: Any
    test_connection: Any
    test_ir: Any
    use_ir: Any
    virtual: Any
    virtual_failures: Any

    QUEUE_SUPPORTED = True
    @staticmethod
    def queue_progress_factory(*a, **k):        # the progress window (run_queue_ui.QueueProgress on Tk)
        return port.view('run_queue_view').queue_progress(*a, **k)

    # ------------------------------------------------------------------ state
    @property
    def queue(self):
        if '_queue' not in self.__dict__:
            self._queue = RQ.RunQueue()
        return self._queue

    @property
    def _q(self) -> Any:
        """The active QueueRun, or None between runs."""
        return self.__dict__.get('_q_run')

    @_q.setter
    def _q(self, value):
        self.__dict__['_q_run'] = value

    @property
    def queue_ctx(self):
        return self.__dict__.get('_queue_ctx')

    def queue_supported(self):
        """The queue is for the handheld procedures with a typed or IR reading.  A user-built datasheet (Datasheet Builder) can use other standards
        and an oscilloscope, so it keeps its own single-meter flow."""
        return bool(self.QUEUE_SUPPORTED) and getattr(self, 'dsb', None) is None

    def queue_wants_run(self):
        return self.queue_supported() and self.queue.active()

    def queue_options(self):
        return self.spec.get('options', {})

    def _q_shared(self):
        q = self._q
        return q is not None and q.unit is not None and q.unit.shared

    def _q_names(self):
        q = self._q
        return ', '.join(m.asset for m in (q.unit.meters if q is not None and q.unit is not None else []))

    # hooks used by the prompts of handheld_dmm.App: identity (nothing added) unless a SHARED unit is running
    def _qfacts(self, facts):
        if not self._q_shared():
            return facts
        return list(facts) + [('Meters', self._q_names())]

    def _qsteps(self):
        if not self._q_shared():
            return []
        return [('Every meter', f'Do this on every meter in the queue: {self._q_names()}.')]

    def _qnote(self):
        if not self._q_shared():
            return ''
        return f' Every meter in the queue: {self._q_names()}.'

    def _q_hv_text(self, text):
        """The high-voltage question, naming every meter on the leads when several are wired together (asked once per hook-up group in a shared unit, once per point otherwise)."""
        if not self._q_shared():
            return text
        return text.replace('Enable output?', f'Meters on the calibrator: {self._q_names()}. Enable output?')

    def _q_hv_seen(self, p):
        """Shared unit: the high-voltage question is asked once per hook-up group (Mike's rule), not once per point."""
        if not self._q_shared():
            return False
        return p.get('group') in getattr(self._q.unit, 'hv_groups', set())

    def _q_hv_note(self, p):
        if self._q_shared():
            unit = self._q.unit
            unit.hv_groups = set(getattr(unit, 'hv_groups', set())) | {p.get('group')}

    # ------------------------------------------------------------------ context swap
    def _queue_activate(self, m):
        prev = self.queue_ctx
        if prev is not None and prev is not m:
            prev.last_high_current = self.last_high_current
        self.asset.set(m.asset)
        self.serial.set(m.serial)
        self._found, self._left = m.found, m.left
        self.last_high_current = m.last_high_current
        self.__dict__['_queue_ctx'] = m
        if self._q is not None:
            self._q.current = m

    def queue_forget_context(self):
        self.__dict__['_queue_ctx'] = None

    def queue_sync_after_load(self):
        """'Load progress' replaced the shown result sets: keep the queue meter that owns them in step (or detach when the file is for another asset)."""
        if not self.queue.meters:
            return
        m = self.queue.find(self.asset.get())
        if m is None:
            self.queue_forget_context()
            self.status.set(self.status.get() + ' (this asset is not in the run queue: shown for review only)')
            return
        m.found, m.left = self._found, self._left
        if not m.serial:
            m.serial = self.serial.get().strip()
        self.__dict__['_queue_ctx'] = m

    def queue_show(self, asset):
        m = self.queue.find(asset)
        if m is None or self.busy:
            return
        self._queue_activate(m)
        self.refresh()
        self.status.set(f'Showing the results of asset {m.asset}.')

    # ------------------------------------------------------------------ set-up window
    def queue_prepare_meters(self, meters):
        """Hook: give the meters of a queue being planned their per-meter settings (a procedure option set per meter).  Nothing by default."""

    def queue_total(self, m):
        """Points of the current list that meter `m` takes part in (all of them unless a per-meter option leaves some out)."""
        return sum(1 for p in self.points if m.wants(p))

    def queue_candidates(self):
        """[(asset, serial)] of this model from Asset History and the instrument list (suggestions for the Add meter box)."""
        out = []
        try:
            import labregistry
            name = self.info.get('name', '')
            for row in labregistry.assets_overview(''):
                if name and name.lower() in str(row.get('model') or '').lower() or str(self.model) in str(row.get('model') or ''):
                    out.append((row['asset_id'], row.get('serial') or ''))
        except Exception:
            pass
        return out

    def queue_status_text(self, asset):
        m = self.queue.find(asset)
        n = len(self.points)
        left = self.is_left
        if m is not None and (m.found or m.left):
            return f'{len(m.results(left))} of {n} recorded' + (f' ({m.status})' if m.status not in ('Ready', 'Running') else '')
        saved = self._queue_saved_counts(asset)
        return f'Saved progress: {saved} of {n}' if saved else 'Ready'

    def _queue_saved_counts(self, asset):
        try:
            data = self._queue_checkpoint_for(asset)
        except Exception:
            data = None
        if not data:
            return 0
        return len(data.get('left_results' if self.is_left else 'results') or {})

    def _queue_checkpoint_for(self, asset):
        """The saved checkpoint of `asset` when it can be resumed in this window (same model, same demo flag, datasheet check), else None."""
        path = self._checkpoint_path(asset)
        if not Path(path).exists():
            return None
        data = json.loads(Path(path).read_text())
        if data.get('model') != self.model or bool(data.get('demo')) != bool(self.demo) or str(data.get('asset', '')).strip() != str(asset).strip():
            return None
        if self.checkpoint_problem(data):
            return None
        return data

    def queue_summary(self, meters, mode):
        """What the set-up window shows under the two choices (and whether Start is allowed)."""
        q = RQ.RunQueue()
        for asset, serial, tech in meters:
            try:
                q.add(asset, serial, tech)
            except RQ.QueueError:
                pass
        self.queue_prepare_meters(q.meters)
        use_ir = self.use_ir and bool(self.ir)
        info: dict[str, Any] = RQ.summary(self.points, q, self.queue_options(), mode=mode, use_ir=use_ir)
        n = len(q.meters)
        warnings = []
        ok = True
        if n < 2:
            return dict(title='One meter: the procedure runs as it always did.', body='Add at least two meters to run a queue.', warnings=[], ok=bool(n), kind='warn')
        same, why = self._queue_mods_same(q.meters)
        if not same:
            ok = False
            warnings.append(why)
        if mode == RQ.POINT_BY_POINT and not use_ir:
            title = (f'Saves {info["saved"]} calibrator settings' if info['saved'] > 0 else 'No calibrator settings saved')
            body = (f'{info["points"]} points x {n} meters = {info["alone"]} settings one meter at a time; point by point needs {info["settings"]} '
                    f'({info["shared"]} shared point(s) set once, {info["single"]} point(s) done one meter at a time). Hook-up and function prompts: once per group.')
            if info['reasons']:
                body += '\nNot shared: ' + '; '.join(f'{k} ({v})' for k, v in info['reasons'].items()) + '.'
            kind = 'good' if info['saved'] > 0 else 'warn'
        else:
            title = 'One meter at a time'
            body = (f'{info["alone"]} calibrator settings ({info["points"]} points x {n} meters). You are asked to swap in the next meter after each one.'
                    + (f' {RQ.IR_REASON[0].upper() + RQ.IR_REASON[1:]}.' if use_ir else ''))
            kind = 'warn'
        return dict(title=title, body=body, warnings=warnings, ok=ok, kind='bad' if not ok else kind)

    def _queue_mods_same(self, meters):
        """Procedure modifications are stored per asset.  A shared point list can follow only one set, so every meter of a queue must resolve to the same one
        (normally none).  (True, '') or (False, why)."""
        st = self.pm_state
        if st is None or len(meters) < 2:
            return True, ''
        try:
            import procmods
            sigs = []
            for m in meters:
                oset = procmods.resolve(self.model, m.asset, getattr(st, 'run_entries', None), getattr(st, 'idn', ''), store=st._store(), devmode=st.devmode)
                sigs.append(tuple(sorted((str(e.get('uid')), str(e.get('kind')), str(e.get('target'))) for e in oset.active())))
        except Exception:
            return True, ''
        if len(set(sigs)) <= 1:
            return True, ''
        odd = [m.asset for m, s in zip(meters, sigs) if s != sigs[0]]
        return False, (f'Asset {", ".join(odd)} has procedure modifications that differ from asset {meters[0].asset}. A queue shares one set of test points and limits: '
                       'run these meters in separate runs.')

    def open_queue_setup(self):
        if self.busy:
            port.message('info', 'Run queue', 'Stop the run before changing the queue.')
            return
        if not self.queue_supported():
            port.message('info', 'Run queue', 'The run queue is not available for this procedure.')
            return
        start = [(m.asset, m.serial, m.tech) for m in self.queue.meters]
        mode = self.queue.mode
        if not start:
            saved = RQ.read_queue(self._queue_path())
            probe = RQ.RunQueue()
            if saved and probe.load_dict(saved, self.model, self.demo):
                start, mode = [(m.asset, m.serial, m.tech) for m in probe.meters], probe.mode
            elif self.asset.get().strip():
                start = [(self.asset.get().strip(), self.serial.get().strip(), self._default_tech())]
        ir_only = bool(self.use_ir and self.ir)
        got = port.view('run_queue_view').ask_queue_setup(self.root, f'Run queue - {self.info["name"]}', start, mode, self.queue_summary, status_of=self.queue_status_text,
                                           candidates=self.queue_candidates(), default_tech=self._default_tech(), ir_only=ir_only)
        if not got:
            return
        self.apply_queue(got['meters'], got['mode'])
        if got['action'] == 'start':
            port.after(self.root, 30, self._queue_start_pressed)
        else:
            self.status.set(self.queue_chip_text() or 'Run queue cleared: the procedure runs one meter as usual.')

    def _queue_start_pressed(self):
        self.run_all()                                           # one meter is not a queue: run_all / execute take the normal single-meter path

    def _default_tech(self):
        try:
            return str(ui.Settings('report_details').get('technician', '') or '')
        except Exception:
            return ''

    def apply_queue(self, meters, mode):
        """Replace the queue with `meters` [(asset, serial, tech)].  A meter that stays keeps its results; new ones start empty."""
        old = {RQ.clean_key(m.asset): m for m in self.queue.meters}
        new = RQ.RunQueue()
        for asset, serial, tech in meters:
            m = new.add(asset, serial, tech)
            prev = old.get(RQ.clean_key(asset))
            if prev is not None:
                m.found, m.left, m.status, m.last_high_current = prev.found, prev.left, prev.status, prev.last_high_current
        new.mode = mode if mode in RQ.MODES else RQ.POINT_BY_POINT
        self._queue = new
        if new.meters and self.queue_ctx not in new.meters:
            self._queue_activate(new.meters[0])                    # the window shows (and a single-meter run uses) the first meter's own results
            self.refresh()
        elif not new.meters:
            self.queue_forget_context()
        RQ.save_queue(self._queue_path(), new, self.model, self.demo)
        self._queue_update_chip()

    def queue_chip_text(self):
        q = self.queue
        return f'Run queue: {len(q.meters)} meters ({RQ.MODE_NAMES[str(q.mode)].lower()})' if q.active() else ''

    def _queue_update_chip(self):
        chip = getattr(self, 'queue_pill', None)
        text = self.queue_chip_text()
        if chip is not None:
            try:
                chip.set(text, 'info')
                if text and not chip.winfo_manager():
                    chip.pack(side='left', padx=(8, 0))
                elif not text:
                    chip.pack_forget()
            except Exception:
                pass
        label = getattr(self, 'queue_label', None)
        if label is not None:
            try:
                label.set(text or 'No queue: one meter, as usual.')
            except Exception:
                pass

    def _queue_path(self):
        import appdata
        return appdata.progress_path(f'{self.brand}{self.model}_queue.json')

    def build_queue_drawer(self, d, row):
        """The 'Run queue' area of the Connections drawer (rows row .. row+2).  Returns the next free row."""
        return port.view('run_queue_view').build_queue_drawer(self, d, row)

    # ------------------------------------------------------------------ pending points / selections
    def queue_lacking(self, p):
        left = self.is_left
        return any(m.wants(p) and str(p['id']) not in m.results(left) for m in self.queue.meters)

    def queue_pending(self, points):
        return [p for p in points if self.queue_lacking(p)]

    def shown_pending(self, points):
        if not self.queue_wants_run():
            return super().shown_pending(points)  # pyright: ignore[reportAttributeAccessIssue]  (the procedure class after this mixin provides it)
        if self.show_section.get() == 'All sections' and self.show_status.get() == 'All points':
            return None
        return [p for p in points if self._visible(p) and self.queue_lacking(p)]

    # ------------------------------------------------------------------ starting a run
    def queue_execute(self, points):
        """Start of a queue run (App.execute calls this when the queue has two or more meters)."""
        force = bool(self.__dict__.pop('_queue_force', False))
        q = self.queue
        problems = q.problems()
        if problems:
            port.message('warning', 'Run queue', '\n'.join(problems))
            return
        same, why = self._queue_mods_same(q.meters)
        if not same:
            port.message('warning', 'Run queue', why)
            return
        if not self._queue_resume():
            return
        lead = q.meters[0]
        self._queue_activate(lead)
        points = self.pm_begin_run(points, lead.asset)          # the saved modifications (the same for every meter of the queue; checked above)
        if not points:
            self.status.set('Every selected point is skipped by a procedure modification.')
            return
        left = self.is_left
        if not left:
            clash = next((m for m in q.meters if any(str(p['id']) in m.left for p in points)), None)
            if clash is not None:
                self._queue_activate(clash)
                if not self.confirm_found_overwrite(points):
                    return
        if self.virtual and self.use_ir:
            self.read_mode.set(self._typed_mode())
        if not self.fast_demo and not self.manual_cal and self.io is None:
            self.test_connection()
            if self.io is None:
                return
        if not self.demo and self.use_ir and self.meter is None:
            self.test_ir()
            if self.meter is None:
                return
        units = RQ.plan(points, q, self.queue_options(), mode=q.mode, use_ir=bool(self.use_ir and self.ir), force=force, left=left)
        if not units:
            self.status.set('Every meter in the queue already has a reading for these points.')
            self._queue_activate(lead)
            return
        self._q = QueueRun(units, q.mode, points, force)
        for m in q.meters:
            m.status = 'Ready' if not (m.results(left)) else m.status
        self.stop = False
        self.busy = True
        self._last_switch = None
        self._queue_open_progress()
        self._queue_save_all()
        self.reset_then(self._queue_advance)

    def _typed_mode(self):
        import handheld_dmm as H
        return H.READ_TYPED

    def _queue_resume(self):
        """Saved progress of meters whose results are not in memory: ask once whether to continue from it.  False = the operator cancelled."""
        left = self.is_left
        found = []
        for m in self.queue.meters:
            if m.found or m.left:
                continue
            try:
                data = self._queue_checkpoint_for(m.asset)
            except Exception:
                data = None
            if data and (data.get('results') or data.get('left_results')):
                found.append((m, data))
        if not found:
            return True
        lines = '\n'.join(f'   asset {m.asset}: {len(d.get("results") or {})} As Found, {len(d.get("left_results") or {})} As Left point(s)' for m, d in found)
        answer = port.ask_yes_no_cancel('Resume saved progress',
                                           f'Saved progress was found for:\n{lines}\n\nYes = continue from it (points already recorded are not measured again).\n'
                                           'No = start these meters over (their saved progress is replaced as new readings are recorded).\nCancel = do not run.')
        if answer is None:
            return False
        if answer:
            first = True
            for m, data in found:
                m.found, m.left = dict(data.get('results') or {}), dict(data.get('left_results') or {})
                if first:
                    self._queue_activate(m)
                    self.pm_on_checkpoint(data)
                    first = False
        return True

    # ------------------------------------------------------------------ the units
    def _queue_open_progress(self):
        q = self._q
        try:
            q.progress = self.queue_progress_factory(self.root, on_show=self.queue_show, on_export=self.queue_export_pdfs)
        except Exception:
            q.progress = None
        self._queue_tick(None)

    def _queue_tick(self, p):
        """Refresh the status line and the progress window (called at the top of every point and when the run ends)."""
        q = self._q
        if q is None:
            return
        total = len(self.points)
        if p is not None:
            if q.unit is not None and q.unit.shared:
                head = f'Point {p["n"]} of {total}  -  all {len(q.unit.meters)} meters'
            else:
                m = q.unit.meters[0] if q.unit is not None and q.unit.meters else None
                head = f'Point {p["n"]} of {total}  -  asset {m.asset}' if m else f'Point {p["n"]} of {total}'
        else:
            head = 'Starting the queue'
        self._queue_progress_update(head)

    def _queue_progress_update(self, head, finished=False, note=''):
        q = self.__dict__.get('_q_last') if self._q is None else self._q
        if q is None or q.progress is None:
            return
        rows = RQ.progress(self.queue, self.points, self.is_left)
        done = sum(r['recorded'] for r in rows)
        denom = max(1, sum(r['total'] for r in rows))
        try:
            q.progress.update(head, done / denom, rows, finished=finished, note=note)
        except Exception:
            pass

    def _queue_advance(self):
        q = self._q
        if q is None:
            return
        if self.stop or not q.units:
            self._queue_finish(stopped=self.stop)
            return
        unit = q.units.pop(0)
        q.unit = unit
        self._last_switch = None
        self._stage = {'id': None, 'done': set()}
        left = self.is_left
        for m in unit.meters:
            if m.status in ('Ready', 'Done', 'Incomplete', 'Stopped'):
                m.status = 'Running'
        if unit.shared:
            q.active = list(unit.meters)
            self._queue_activate(unit.meters[0])
            self.status.set(f'All {len(unit.meters)} meters are on the calibrator: {len(unit.points)} point(s), set once each.')
            self._next(unit.points, 0, None)
            return
        m = unit.meters[0]
        q.active = [m]
        if unit.prompt and not self._queue_swap_prompt(unit, m):
            self.status.set('Paused at the meter swap. Progress is saved for every meter.')
            self.busy = False                                      # (the setter ends the queue run: paused, progress saved)
            return
        self._queue_activate(m)
        if unit.reset and not self.fast_demo:
            self.reset_then(lambda: self._next(unit.points, 0, None))
        else:
            self._next(unit.points, 0, None)

    def _queue_swap_prompt(self, unit, m):
        q = self._q
        meters = self.queue.meters
        n = meters.index(m) + 1
        steps = [('Connect', f'Connect only meter {m.asset}' + (f' (serial {m.serial})' if m.serial else '') + ' to the calibrator and disconnect the other meters. '
                                                                'The calibrator output stays in STANDBY until you continue.')]
        if self.use_ir and self.ir:
            steps.append(('IR cable', f'Move the IR cable to meter {m.asset}.'))
        if unit.reason:
            steps.append(('Why one at a time', unit.reason[0].upper() + unit.reason[1:] + '.'))
        facts = [('Meter', f'{n} of {len(meters)}: asset {m.asset}'), ('Serial', m.serial or '-'), ('Points', str(len(unit.points)))]
        if self.io and not self.manual_cal:
            self._safe_standby()
        return port.operator_prompt('Next meter' if not unit.reason or q.mode == RQ.ONE_AT_A_TIME else 'One meter at a time', f'Asset {m.asset}', steps,
                                    facts=facts, caution='Continue only after the right meter is connected.', ok='Meter connected - continue', parent=self.root)

    def _queue_unit_done(self):
        """`_next` ran out of points (or the run was stopped) for the current unit."""
        q = self._q
        if q is None:
            return
        self._queue_save_all()
        if self.stop:
            self._queue_finish(stopped=True)
            return
        port.after(self.root, 20, self._queue_advance)

    def _queue_save_all(self):
        keep = self.queue_ctx
        for m in self.queue.meters:
            if m.found or m.left:
                self._queue_activate(m)
                self.save(silent=True)
        if keep is not None:
            self._queue_activate(keep)
        RQ.save_queue(self._queue_path(), self.queue, self.model, self.demo)

    def _queue_finish(self, stopped=False):
        q = self._q
        left = self.is_left
        self._queue_save_all()
        for m in self.queue.meters:
            total = self.queue_total(m)
            done = len(m.results(left))
            fails = sum(1 for r in m.results(left).values() if r.get('result') == 'FAIL')
            m.status = ('Done' if done >= total else 'Stopped' if stopped else 'Incomplete') + (f' - {fails} fail' if fails else '')
            if m.status.startswith('Done') and not fails:
                m.status = 'Done'
        self.__dict__['_q_last'] = q
        self._q = None
        self._queue_activate(self.queue.meters[0])
        self.busy = False
        self.refresh()
        self.status.set(('Queue stopped by the operator. Progress is saved for every meter.' if stopped else 'Queue complete. Each meter has its own results: export the reports.'))
        self.__dict__['_q_last'] = q
        self._queue_progress_update('Queue stopped' if stopped else 'Queue complete', finished=True)

    def _queue_aborted(self):
        """busy went False while a queue was running (a prompt was cancelled, an error, a reset failure): end the queue run, keep everything."""
        q = self._q
        if q is None:
            return
        self._queue_save_all()
        self.__dict__['_q_last'] = q
        self._q = None
        for m in self.queue.meters:
            if m.status == 'Running':
                m.status = 'Incomplete'
        try:
            self._queue_activate(self.queue.meters[0])
        except Exception:
            pass
        self._queue_progress_update('Queue paused', finished=True, note='The run was paused. Progress is saved for every meter: press Run All Pending to continue.')

    # ------------------------------------------------------------------ reading several meters at once
    def _reading_limit(self, p):
        limit = {}
        if p.get('max_on_s'):
            on_at = getattr(self.io, 'on_at', None) if self.io and not self.manual_cal else None
            used = (time.monotonic() - on_at) if on_at else 0.0
            limit = dict(limit_s=max(1.0, p['max_on_s'] - used), on_expire=self._safe_standby if self.io and not self.manual_cal else None)
        return limit

    def _delta_text(self, p, padded):
        try:
            from decimal import Decimal
            want = Decimal(str(p['nominal'])) / Decimal(str(p['factor']))
            places = max(0, max(-int(Decimal(p[k]).as_tuple().exponent) for k in ('low', 'high')))
            d = Decimal(padded) - want
            return f'{d:+.{places}f} {p["display_unit"]} from nominal'
        except Exception:
            return ''

    def _ask_shared(self, points, i, p, key):
        """One point, all meters of the shared unit: the calibrator is already set (once); the operator reads every meter."""
        import handheld_dmm as H
        q = self._q
        ms = list(q.unit.needs.get(str(p['id']), q.unit.meters))
        q.active = ms
        total = len(self.points)
        self.status.set(f'Point {p["n"]}/{total}: waiting for the readings of {len(ms)} meters.')
        r = dict(action='record')
        stored = []
        if p['test'] == 'numeric':
            def judge(meter_key, text):
                padded = H.pad_reading(p, text)
                state, _base = H.judge_numeric(p, padded)
                return state, padded, self._delta_text(p, padded)
            fill: dict[str, Any] = {}
            if self.virtual:
                fill = dict(demo_fill=lambda idx: virtualbench.plausible_text(p['low'], p['high'], p['n'] + 5 * idx, self.virtual_failures()))
            r = H.ask_readings(self.root, p, total, H.output_text(p), self._out_note(p, True), self.accept_text(p),
                               [(m.asset, m.asset, m.serial) for m in ms], unit=p['display_unit'], judge=judge, heading=H.describe(p),
                               tol_text=p.get('tol_text', ''), **self._reading_limit(p), **self._reading_labels_shared(p), **fill)
            if r['action'] == 'record':
                for m in ms:
                    text = r['texts'].get(m.asset)
                    if text is None:
                        continue
                    self._queue_activate(m)
                    entered = H.pad_reading(p, text)
                    ann = True
                    if p.get('annunciator'):
                        ann = bool(port.ask_yes_no('AC annunciator', f'{H.describe(p)}\n\nMeter: asset {m.asset}\n\nIs the AC annunciator ON in the meter display?\n\n'
                                                       'Yes = it is on.  No = it is not (the point then fails).'))
                    result, base = H.judge_numeric(p, entered, ann)
                    self._store(p, entered=entered, reading=base, result=result, annunciator=ann if p.get('annunciator') else None, source='typed')
        else:
            r, answers = self._ask_yesno_all(p, ms)
            if r['action'] == 'record':
                for m in ms:
                    self._queue_activate(m)
                    a = answers[m.asset]
                    if p.get('checks'):
                        self._store(p, entered='Pass' if all(a) else 'Fail', reading=None, result='PASS' if all(a) else 'FAIL', answers=a)
                    else:
                        ok = a[0]
                        self._store(p, entered=('Pass' if ok else 'Fail') if p['test'] == 'visual' else (f'Beeper {p["expect"]}' if ok else f'Beeper not {p["expect"]}'),
                                    reading=None, result='PASS' if ok else 'FAIL')
        if self.io and not self.manual_cal:
            self.io.standby()
        if r['action'] == 'stop':
            self.stop = True
        if ms:
            self._queue_activate(ms[0])
            self._update_row(p)
        port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _reading_labels_shared(self, p):
        labels = self.reading_labels(p)
        return {k: v for k, v in labels.items() if k in ('device', 'source')}

    def _ask_yesno_all(self, p, ms):
        """Yes / no points (display test, beeper, diode check ...) for several meters: the existing window once per meter, naming the asset.  Nothing is
        recorded unless every meter was answered (Skip / Stop apply to the whole queue)."""
        import handheld_dmm as H
        total = len(self.points)
        answers = {m.asset: [] for m in ms}
        phases = p['checks'] if p.get('checks') else [None]
        for n, chk in enumerate(phases, 1):
            if chk is not None and not chk['output'] and self.io and not self.manual_cal:
                self.io.standby()
            for idx, m in enumerate(ms):
                if chk is not None:
                    note = self._out_note(p, chk['output']) if not self.manual_cal else ('Output ON.' if chk['output'] else 'Put the calibrator in STANDBY.')
                    question, phase = chk['question'], f'check {n} of {len(phases)}  -  asset {m.asset}'
                else:
                    note, question, phase = self._out_note(p, True), p['question'], f'asset {m.asset}'
                fill: dict[str, Any] = {}
                if self.virtual:
                    fill = dict(demo_fill=lambda n=n, idx=idx: virtualbench.plausible_answer(p['n'] + (n if chk is not None else 0) + 3 * idx, self.virtual_failures()))
                r = H.ask_reading(self.root, p, total, H.output_text(p), note, question, 'yesno', question=question, phase=phase, **self.reading_labels(p), **fill)
                if r['action'] != 'record':
                    return r, answers
                answers[m.asset].append(r['yes'])
        return dict(action='record'), answers

    def _fast_demo_record(self, p):
        """Fast demo: the deterministic synthetic reading for every meter that still needs the point (one meter outside a shared unit)."""
        if not self._q_shared():
            self._record_demo(p)
            return
        for m in self._q.unit.needs.get(str(p['id']), self._q.unit.meters):
            self._queue_activate(m)
            self._record_demo(p)
        self._queue_activate(self._q.unit.meters[0])

    # ------------------------------------------------------------------ reports (one PDF per meter)
    def queue_offer_all_reports(self):
        """'Export Report (PDF)' with a run queue: offer one report per meter.  True = handled here (exported them all, or cancelled);
        False = go on with the ordinary single report of the meter shown."""
        if not self.queue_wants_run() or not any(m.found or m.left for m in self.queue.meters):
            return False
        answer = port.ask_yes_no_cancel('Reports', f'This run queue has {len(self.queue.meters)} meters.\n\nYes = one report for each meter (asset#-date).\n'
                                                      f'No = only the report of the meter shown (asset {self.asset.get()}).\nCancel = do nothing.')
        if answer is None:
            return True
        if answer:
            self.queue_export_pdfs()
            return True
        return False

    def queue_export_pdfs(self):
        """One 'Calibration Data' PDF per meter: asset#-date, its own rows, header, As Left, Asset History record and report snapshot."""
        import report_pdf
        meters = [m for m in self.queue.meters]
        if not meters:
            return
        keep = self.queue_ctx
        todo = []
        for m in meters:
            self._queue_activate(m)
            rows, pts = self.certificate_rows_and_points()
            if rows:
                todo.append((m, rows, pts))
        if keep is not None:
            self._queue_activate(keep)
        if not todo:
            port.message('info', 'No results', 'No recorded results to export yet.')
            return
        self.__dict__['_review_all_meters'] = True                 # the review window (report_review.py) then shows each meter in turn
        try:
            details = port.report_details(f'{self.info["name"]} performance verification', parent=self.root)
        finally:
            self.__dict__.pop('_review_all_meters', None)
        if details is None:
            return
        folder = port.choose_dir(title='Folder for the reports (one PDF per meter)')
        if not folder:
            return
        written, errors = [], []
        src = self.spec['source']
        for m, rows, pts in todo:
            self._queue_activate(m)
            d = dict(self.report_details(dict(details)))
            if m.tech:
                d['technician'] = m.tech
            name = ui.report_filename(''.join(c if c.isalnum() or c in '-_' else '_' for c in m.asset) or 'UNASSIGNED')
            path = Path(folder) / name
            n = 2
            while path.exists():                                   # never overwrite another report
                path = Path(folder) / f'{path.stem}-{n}{path.suffix}'
                n += 1
            try:
                use = rows
                if d.get('show_tar_tur'):
                    use = report_pdf.apply_tar_tur(rows, d.get('show_tar_tur'), [self.certificate_fields(p) for p in pts])
                report_pdf.write_calibration_pdf(str(path), use, header=self.report_header(src), title=self.report_title(), demo=self.any_synthetic(), details=d,
                                                 footer_note=' '.join(x for x in (report_pdf.uncertainty_note(use, self.calibrator_model()), self.temperature_note(), self.source_note()) if x),
                                                 snapshot_context=report_pdf.context_for(self))
                written.append(str(path))
            except Exception as exc:
                errors.append(f'asset {m.asset}: {exc}')
        if keep is not None:
            self._queue_activate(keep)
        else:
            self._queue_activate(meters[0])
        msg = f'{len(written)} report(s) written:\n' + '\n'.join(written)
        if errors:
            msg += '\n\nNot written:\n' + '\n'.join(errors)
        self.status.set(f'Exported {len(written)} report(s) to {folder}')
        port.message('warning' if errors else 'info', 'Queue reports', msg)
        return written
