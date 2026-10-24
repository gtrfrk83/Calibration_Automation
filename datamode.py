"""As Found / As Left data collection, shared by the verification procedures.

A calibration normally records the instrument As Found.  When a point is out of tolerance the instrument is adjusted and the point is
measured again, As Left.  This mixin gives a procedure two result sets and a toggle that says which one is being collected:

    As Found   the first measurements, before any adjustment (what every procedure did before this feature)
    As Left    the measurements taken after an adjustment; they are stored beside the As Found values, never over them

Nothing is adjusted by this program.  When nothing was adjusted the As Left set stays empty and the report prints 'Same' in the
As Left column, exactly as before.  Points that were re-measured print their As Left reading (marked OOT if it is still outside the
limits); the other points print 'Same'.

Using it in a procedure's App class (see truevolt_verification.py for the reference):

    class App(DataModeMixin):
        self.results = {}                                  # unchanged: the dict of the mode being collected
        parent = self.build_mode_bar(body)                 # the toggle; call once while building the window
        self.save():   dict(..., **self.save_fields())     # both result sets go into the progress file
        self.load():   self.load_results(data)
        report rows:   self.found_left_row(p, build)       # build(record) -> the row for that record
        report:        self.any_synthetic()                # demo data in either set marks the report as demo

`self.results` always refers to the set being collected, so the existing run / rerun / refresh code works unchanged in both modes.
Needs nothing from the procedure except an optional `busy` flag, `refresh()` and a `status` StringVar.
"""
from __future__ import annotations

import ui_theme_core as ui                   # toolkit-free helpers only (si); the toggle's widgets are datamode_view_tk.py
from ui_port import ui as port                 # dialogs go through the UI port (ui_port.py)

FOUND, LEFT = 'found', 'left'
LABEL = {FOUND: 'As Found', LEFT: 'As Left'}
STATUS_FILTERS = ['All points', 'Not tested', 'Passed', 'Failed (OOT)', 'As Found failed']
HINT_FOUND = "First measurements, before any adjustment. If nothing is adjusted, leave this on: the report prints 'Same' under As Left."
HINT_LEFT = ('Measure again after the adjustment. The readings are stored beside the As Found values; the As Found values are not changed. '
             "Points you do not re-measure print 'Same'.")


class DataModeMixin:
    _mode = FOUND                      # class default: As Found, so a procedure works even if the toggle was never built

    # ---- the two result sets ------------------------------------------------------------------------
    @property
    def found(self) -> dict:
        if '_found' not in self.__dict__:
            self._found = {}
        return self._found

    @property
    def left(self) -> dict:
        if '_left' not in self.__dict__:
            self._left = {}
        return self._left

    @property
    def results(self) -> dict:
        """The result set being collected (As Found or As Left)."""
        return self.left if self._mode == LEFT else self.found

    @results.setter
    def results(self, value):
        if self._mode == LEFT:
            self._left = value
        else:
            self._found = value

    @property
    def is_left(self) -> bool:
        return self._mode == LEFT

    @property
    def mode_label(self) -> str:
        return LABEL[self._mode]

    def all_records(self):
        """Every stored record, As Found and As Left (for re-judging against new limits, demo checks ...)."""
        yield from self.found.values()
        yield from self.left.values()

    def any_synthetic(self) -> bool:
        return bool(getattr(self, 'demo', False)) or any(r.get('synthetic') for r in self.all_records())

    # ---- progress file -------------------------------------------------------------------------------
    def save_fields(self) -> dict:
        """Keys to add to the progress (checkpoint) file."""
        return {'results': self.found, 'left_results': self.left}

    def load_results(self, data: dict):
        """Restore both result sets from a progress file (files saved before this feature have no As Left set)."""
        self._found = data.get('results', {}) or {}
        self._left = data.get('left_results', {}) or {}
        self._mode = FOUND                      # a loaded file starts on As Found
        self._apply_mode_ui()

    @staticmethod
    def file_has_synthetic(data: dict) -> bool:
        return any(v.get('synthetic') for key in ('results', 'left_results') for v in (data.get(key) or {}).values())

    # ---- the toggle -------------------------------------------------------------------------------------
    def build_mode_bar(self, parent, **pack):
        """The 'Collecting data' toggle (As Found | As Left).  Returns the frame; it is packed with **pack (default: fill x)."""
        return self.dm_view().build_mode_bar(self, parent, **pack)

    def build_mode_segment(self, parent, notice_holder=None):
        """The redesigned toggle: a compact  Collecting [ As Found | As Left ]  switch for the shell's top strip.  It keeps the same
        attributes as build_mode_bar (mode_var, mode_buttons, mode_hint, mode_notice_holder), so everything else works unchanged;
        the hint becomes a tooltip and the As Left warning becomes a one-line amber notice under the strip."""
        return self.dm_view().build_mode_segment(self, parent, notice_holder)

    @staticmethod
    def dm_view():
        """The toolkit's window code for the toggle (datamode_view_tk for Tk)."""
        return port.view('datamode_view')

    def _mode_clicked(self):
        self.set_data_mode(self.mode_var.get(), from_ui=True)

    def set_data_mode(self, mode, from_ui=False):
        if mode not in LABEL:
            return
        if getattr(self, 'busy', False):                      # never switch in the middle of a run
            if from_ui:
                self.mode_var.set(self._mode)
            return
        self._mode = mode
        self._apply_mode_ui()
        if hasattr(self, 'status'):
            self.status.set(f'Collecting {self.mode_label} data.' + (' Run the points again after the adjustment.' if mode == LEFT else ''))
        if hasattr(self, 'tree') or hasattr(self, 'refresh'):
            try:
                self.refresh()
            except Exception:
                pass
        if hasattr(self, 'mode_changed'):
            self.mode_changed()

    def _apply_mode_ui(self):
        """Bring the toggle, its hint and notice, and the table heading in line with the mode."""
        if hasattr(self, 'mode_var'):
            self.mode_var.set(self._mode)
            self.mode_hint.set(HINT_LEFT if self._mode == LEFT else HINT_FOUND)
            self._show_mode_notice()
        self._relabel_reading_column()

    def _show_mode_notice(self):
        self.dm_view().show_mode_notice(self)

    def _relabel_reading_column(self):
        self.dm_view().relabel_reading_column(self)


    # ---- the redesigned window (ui_shell) --------------------------------------------------------------------
    def shell_cells(self, key, nominal, low, high, unit, fmt=None):
        """The cells of one results-table row in the redesigned window:  nominal, low, high, limits, as found, error, as left, result
        (every number carries its unit, scaled for display only), and the row tag.  Which reading is the 'error' follows the mode
        being collected; in As Left mode the points that were not re-measured show 'Same'."""
        key = str(key)
        rec, f, l = self.results.get(key, {}), self.found.get(key), self.left.get(key)

        def num(r):
            try:
                return float(r.get('reading', ''))
            except (TypeError, ValueError, AttributeError):
                return None
        show = fmt or (lambda v: ui.si(v, unit))          # fmt: a procedure's own number formatter (plain dB, %, ratio ...)
        fv, lv, av = num(f or {}), num(l or {}), num(rec)
        found = show(fv) if fv is not None else ((f or {}).get('entered', '') if f else '')
        left = show(lv) if lv is not None else ('Same' if (self.is_left and f) else '')
        err = ''
        if av is not None and nominal is not None:
            e = av - nominal
            err = ('+' + show(e)) if e > 0 else show(e)
        res = rec.get('result', '')
        shown = {'PASS': '✔ PASS', 'FAIL': '✖ FAIL'}.get(res, '—')
        lo_t = 'N/A' if low is None else show(low)               # one-sided limits
        hi_t = 'N/A' if high is None else show(high)
        limits = lo_t + ' … ' + hi_t if (low is not None and high is not None) else (('≥ ' + lo_t) if high is None else ('≤ ' + hi_t))
        nom_t = '' if nominal is None else show(nominal)
        return (nom_t, lo_t, hi_t, limits, found, err, left, shown), (res.lower() or 'pending',)

    def update_shell_progress(self, points):
        """Feed the progress ring: tested / pass / fail in As Found, re-run progress in As Left."""
        summary = self.shell.summary
        if self.is_left:
            redo = [str(p['id']) for p in points if self.found.get(str(p['id']), {}).get('result') == 'FAIL']
            done = [k for k in redo if k in self.left]
            summary.set_rerun(len(redo), len(done), sum(self.left[k].get('result') == 'PASS' for k in done),
                              sum(self.left[k].get('result') == 'FAIL' for k in done))
        else:
            vals = [self.results.get(str(p['id']), {}).get('result', '') for p in points]
            summary.update_counts(len(points), vals.count('PASS'), vals.count('FAIL'))

    def update_shell_sections(self, points, section_of):
        """Sidebar rows (status dot and x/y count per section) in the order the sections first appear."""
        order, groups = [], {}
        for p in points:
            s = section_of(p)
            if s not in groups:
                groups[s] = []
                order.append(s)
            groups[s].append(self.results.get(str(p['id']), {}).get('result', ''))
        self.shell.set_sections([(s, groups[s].count('PASS'), groups[s].count('FAIL'), len(groups[s])) for s in order])

    def pick_section(self, name):
        """Sidebar / drop-down choice."""
        self.show_section.set(name)
        self.refresh()

    # ---- running ------------------------------------------------------------------------------------------
    def confirm_found_overwrite(self, points) -> bool:
        """Re-measuring As Found after As Left readings exist replaces the original reading of an instrument that has since been
        adjusted.  Ask first; As Left runs never need this."""
        if self._mode != FOUND:
            return True
        clash = [p for p in points if str(p['id']) in self.left]
        if not clash:
            return True
        return port.ask_yes_no(
            'Replace the As Found reading?',
            f'{len(clash)} of these point(s) already have As Left readings, so the instrument has been adjusted since the As Found run.\n\n'
            'Measuring As Found again now replaces the original As Found reading with a reading from the adjusted instrument.\n\n'
            'To measure after an adjustment, switch to As Left instead.\n\nReplace the As Found reading anyway?', default='no')

    def shown_pending(self, points):
        """The points the Show boxes are showing that have no reading yet in the mode being collected.  None when nothing is narrowed
        down (both boxes on 'All'), so Run Shown Section never starts a whole run by accident."""
        if self.show_section.get() == 'All sections' and self.show_status.get() == 'All points':
            return None
        return [p for p in points if self._visible(p) and str(p['id']) not in self.results]

    def run_shown_section(self, points=None):
        """The 'Run Shown Section' button: runs the points not yet measured in the section chosen in the Show box
        (and, if a status is chosen too, only those)."""
        pts = self.shown_pending(points if points is not None else self.active_points())
        if pts is None:
            port.message('info', 'Section', 'Choose a section in the Show box first.')
            return
        if not pts:
            port.message('info', 'Section', f'Nothing left to run there: every shown point already has an {self.mode_label} reading.')
            return
        self.execute(pts)

    def status_visible(self, key, status) -> bool:
        """The 'As Found failed' choice of the status filter (judged on the As Found result whichever mode is on screen)."""
        if status == 'As Found failed':
            return self.found.get(key, {}).get('result') == 'FAIL'
        return True

    def found_left_text(self, p) -> str:
        """One line for the 'Selected test point' box: both readings of the point."""
        key = str(p['id'])
        f, l = self.found.get(key), self.left.get(key)
        if not f and not l:
            return ''
        def part(label, rec):
            if not rec:
                return f'{label}: not measured'
            reading = rec.get('entered') or rec.get('reading', '')
            return f'{label}: {reading} ({rec.get("result", "")})'
        return part('As Found', f) + '   |   ' + part('As Left', l)

    # ---- report rows --------------------------------------------------------------------------------------
    def found_left_row(self, p, build):
        """One report row.  build(record) must return the row for that record as if it were the As Found reading.
        build may return None (a skipped point).  Without an As Left record the As Left cell keeps whatever build() put there ('Same');
        with one it carries the As Left reading and 'As Left OOT' says whether that reading is still outside the limits."""
        key = str(p['id'])
        f, l = self.found.get(key), self.left.get(key)
        frow = build(f) if f else None
        lrow = build(l) if l else None
        if frow is None and lrow is None:
            return None
        if frow is None:                        # only measured after the adjustment
            return dict(lrow, **{'As Found': '', 'OOT': '', 'As Left': lrow.get('As Found', ''), 'As Left OOT': bool(lrow.get('OOT'))})
        if lrow is not None:
            frow['As Left'] = lrow.get('As Found', '')
            frow['As Left OOT'] = bool(lrow.get('OOT'))
        return frow
