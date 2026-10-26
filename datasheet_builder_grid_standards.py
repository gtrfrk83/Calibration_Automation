"""Datasheet Builder: the STANDARD and UNCERTAINTY columns of the grid editor, model side (no tkinter).  Mixed into datasheet_builder_ui_model.GridModel.

    g.refresh_standard_columns()    -> True when the standards matcher was run for this version of the sheet (the rows then carry the two cells); cheap when already done
    g.standard_columns_ready()      -> True when the cells are worked out for the sheet as it is now
    g.standard_choices(key)         -> [dict(value, label, scope, checked, enabled)] for the drop-down of a STANDARD cell (a point row or a section heading)
    g.choose_standard(key, value, scope='point' | 'section')  -> Outcome; ONE undo step, the same ds.assignments the Automation page writes

Row fields added to GridModel.rows(): standard, standard_tip, std_hand (chosen by hand), unc, unc_tip.  The UNCERTAINTY cell is a read-only display of what the sheet
check (datasheet_builder_rules.uncertainty_source) and the matcher give for the point: the assigned standard's own spec row, k = 2, rounded up as everywhere
(uncertainty.format_value); BLANK, never zero, when it cannot be worked out, with the reason in its tooltip.  Rows of a kind that carries no uncertainty by design
(rules._no_uncertainty_kind), switched-off rows and headings show nothing.

The matcher is run ONCE per version of the sheet (cached on the revision, like rows()), never from rows(): the window asks for it when edits have settled and the
cells are blank until then.  Nothing here changes a limit, a command, a pass / fail rule or the printed datasheet.
"""
from __future__ import annotations

import datasheet_builder as db
import datasheet_builder_rules as rules

AUTOMATIC = ''
MANUAL = 'MANUAL'


def _outcome(ok, message, detail=None):
    from datasheet_builder_ui_model import Outcome
    return Outcome(ok, message, detail)


class StandardColumnsMixin:
    _gm = None                 # (rev, period, MatchResult | None, why)
    _x_ready = 0               # bumped whenever the cells are (re)worked out, so the cached rows are rebuilt

    # ---- the matcher result for the grid (the Automation page's own result is reused when it is current)
    def _gm_fresh(self):
        g = self._gm
        return g is not None and g[0] == self._rev and g[1] == self.period

    def standard_columns_ready(self):
        return self._gm_fresh()

    def _grid_result(self):
        """The MatchResult for the sheet as it is now, or None (not worked out yet / could not be)."""
        if self.match_fresh() and self.match_result is not None:
            return self.match_result
        return self._gm[2] if self._gm_fresh() else None

    def refresh_standard_columns(self, force=False):
        """Run the standards matcher for this version of the sheet if that was not done yet.  Returns True when it ran now.  Never raises."""
        if self._gm_fresh() and not force:
            return False
        why, res = '', None
        if self.ds.options.get('manual_entry'):
            why = 'manual calibration: nothing is sourced'
        elif not any(p.enabled for _f, p in self.ds.all_points()):
            why = 'no test points'
        elif self.match_fresh() and self.match_result is not None:
            res = self.match_result
        else:
            try:
                res = self._get_matcher().match(self.ds, self.period)
            except Exception as exc:                               # standards database missing / damaged: the cells stay blank, the window keeps working
                why = f'the standards could not be loaded or matched ({type(exc).__name__})'
        self._gm = (self._rev, self.period, res, why)
        self._x_ready += 1
        self._rows_cache = None
        return True

    # ---- the two cells of a point row
    def standard_cells(self, fn, p, problem=''):
        """dict(standard, standard_tip, std_hand, unc, unc_tip) for one test point (all '' for a kind with no uncertainty by design, a switched-off row)."""
        import uncertainty
        blank = dict(standard='', standard_tip='', std_hand=False, unc='', unc_tip='')
        if rules._no_uncertainty_kind(fn) or not p.enabled:
            return blank
        manual_sheet = bool(self.ds.options.get('manual_entry'))
        import dsb_sensors as sens
        skey = sens.sensor_of(fn, p)
        if fn.kind == 'TEMP' and not skey and not manual_sheet:           # no sensor chosen: nothing is assumed, nothing is shown
            return dict(blank, standard_tip=sens.NOT_CHOSEN + '.', unc_tip=f'none: blank ({sens.NOT_CHOSEN[0].lower() + sens.NOT_CHOSEN[1:]})')
        if problem and not manual_sheet:                           # the row's own problem comes first (its limits are not known), as in the sheet check
            return dict(blank, standard_tip=f'Fix this row first: {problem}', unc_tip=f'none: blank (fix this row first: {problem})')
        hand = p.id in self.ds.assignments
        if not self._gm_fresh() and not (self.match_fresh() and self.match_result is not None):
            if manual_sheet:
                s = rules.uncertainty_source(self.ds, fn, p, None, True)
                return dict(blank, standard_tip='Manual calibration: nothing is sourced, so no standard is used.', unc_tip=s.text)
            return dict(blank, standard_tip='Working out the standards...', unc_tip='Working out the uncertainty...')
        res = self._grid_result()
        a = res.assignments.get(p.id) if res is not None else None
        if a is None and not manual_sheet:
            why = self._gm[3] if self._gm_fresh() and self._gm[3] else 'the standards could not be matched'
            return dict(blank, standard_tip=why[:1].upper() + why[1:] + '.', unc_tip=f'none: blank ({why})')
        src = rules.uncertainty_source(self.ds, fn, p, a, manual_sheet)
        out = dict(blank, std_hand=hand, unc_tip=src.text)
        if manual_sheet:
            out['standard_tip'] = 'Manual calibration: nothing is sourced, so no standard is used.'
            return out
        if a.status == 'manual':
            out.update(standard=MANUAL, standard_tip='Set by hand: the operator uses their own standard (no standards sheet, so no uncertainty).')
        elif a.status == 'uncovered':
            out.update(standard='none covers it', standard_tip=(a.message or 'No standard covers this point.') + (' (chosen by hand)' if hand else ''))
        else:
            out.update(standard=a.standard + (' (chosen)' if hand else ''),
                       standard_tip=f'{a.standard}: ' + ('chosen by hand.' if hand else 'the best fit, picked automatically.') + ' Click to choose another.')
        if src.level == 'ok' and a is not None and a.uncertainty and a.uncertainty > 0:
            out['unc'] = uncertainty.format_value(a.uncertainty, fn.unit)
            out['unc_tip'] = f'{src.text}. Expanded uncertainty, k = 2, rounded up.'
        if skey:
            out['unc_tip'] += f' Sourced as {sens.short(skey)}.'
            out['standard_tip'] += f' Sourced as {sens.short(skey)}.'
            if a is not None and a.cap_kind == 'TEMP_OTHER':
                out['standard_tip'] += ' The suite cannot source this sensor yet: the operator sets the calibrator by hand.'
        return out

    # ---- the drop-down
    def _candidates_of(self, pid):
        res = self._grid_result()
        a = res.assignments.get(pid) if res is not None else None
        return a, (list(a.candidates) if a is not None else [])

    def _section_points(self, fid):
        fn = self.ds.function(fid)
        if fn is None or rules._no_uncertainty_kind(fn):
            return fn, []
        return fn, [p for p in fn.points if p.enabled]

    def standard_choices(self, key=None):
        """The entries of the STANDARD drop-down for a row: 'Automatic', the standards that cover the point (with TUR) and MANUAL; for a point also the same for the
        whole section.  A heading offers only the whole-section entries.  [] when the row has none (blank row, kind with no uncertainty)."""
        key = key or self.sel_key
        row = self.row(key)
        if row is None or not self.standard_columns_ready() and not (self.match_fresh() and self.match_result is not None):
            return []
        out = []
        if row['kind'] == 'header':
            fn, pts = self._section_points(row['fid'])
            if not pts:
                return []
            out.append(dict(value=AUTOMATIC, label='Automatic (best fit) for the whole section', scope='section', checked=not any(p.id in self.ds.assignments for p in pts), enabled=True))
            for std, label in self._common_standards(pts):
                out.append(dict(value=std, label=f'Set for the whole section: {label}', scope='section',
                                checked=all(self.ds.assignments.get(p.id) == std for p in pts), enabled=True))
            out.append(dict(value=MANUAL, label='Set for the whole section: MANUAL (my own standard)', scope='section',
                            checked=all(self.ds.assignments.get(p.id) == MANUAL for p in pts), enabled=True))
            return out
        if row['kind'] != 'point':
            return []
        fn, p = self.point_of(key)
        if p is None or rules._no_uncertainty_kind(fn) or not p.enabled:
            return []
        a, cands = self._candidates_of(p.id)
        cur = self.ds.assignments.get(p.id, '')
        out.append(dict(value=AUTOMATIC, label='Automatic (best fit)', scope='point', checked=not cur, enabled=True))
        for c in cands:
            if not c.covered and c.standard != cur:
                continue
            tur = f'   TUR {_ratio(c.tur)}' if c.tur else ''
            out.append(dict(value=c.standard, label=c.standard + tur + ('' if c.covered else '   (does not cover this point)'), scope='point',
                            checked=cur == c.standard, enabled=True))
        out.append(dict(value=MANUAL, label='MANUAL (my own standard)', scope='point', checked=cur == MANUAL, enabled=True))
        pts = self._section_points(row['fid'])[1]
        if len(pts) > 1:
            out.append(dict(value=AUTOMATIC, label='Set for the whole section: Automatic', scope='section', checked=False, enabled=True))
            for std, label in self._common_standards(pts):
                out.append(dict(value=std, label=f'Set for the whole section: {label}', scope='section', checked=False, enabled=True))
        return out

    def _common_standards(self, pts):
        """[(standard, label)] for the standards that cover EVERY point in `pts`, best first (the first point's ranking), with the worst TUR in the label."""
        res = self._grid_result()
        if res is None:
            return []
        lists = []
        for p in pts:
            a = res.assignments.get(p.id)
            if a is None:
                return []
            lists.append({c.standard: c for c in a.candidates if c.covered})
        if not lists:
            return []
        first = res.assignments[pts[0].id]
        out = []
        for c in first.candidates:
            if all(c.standard in d for d in lists):
                turs = [d[c.standard].tur for d in lists if d[c.standard].tur]
                out.append((c.standard, c.standard + (f'   TUR {_ratio(min(turs))}+' if len(turs) == len(lists) and turs else '')))
        return out

    def choose_standard(self, key, value, scope='point'):
        """The person's choice from the drop-down: ds.assignments[point id] = standard ('' = automatic again), for one point or all the points of its section.
        ONE undo step.  The same writes as the Automation page's 'Use this standard for the point'."""
        if getattr(self, 'locked', False):
            from datasheet_builder_ui_model import LOCKED_MESSAGE
            return _outcome(False, LOCKED_MESSAGE)
        row = self.row(key)
        if row is None or row['kind'] not in ('point', 'header'):
            return _outcome(False, 'Click a test row first.')
        value = value or ''
        if not self.standard_columns_ready():
            self.refresh_standard_columns()                                # the choice is checked against the candidates of the sheet as it is now
        if row['kind'] == 'header':
            scope = 'section'
        if scope == 'section':
            fn, pts = self._section_points(row['fid'])
            pids = [p.id for p in pts]
        else:
            fn, p = self.point_of(key)
            pids = [p.id] if p is not None else []
        if not pids:
            return _outcome(False, 'There is no test point here to choose a standard for.')
        if value not in (AUTOMATIC, MANUAL):
            ok = {s for s, _l in self._common_standards([fn.point(i) for i in pids])} if len(pids) > 1 else \
                {c.standard for c in self._candidates_of(pids[0])[1] if c.covered}
            if value not in ok and value != self.ds.assignments.get(pids[0]):
                return _outcome(False, f'{value} does not cover {"all of these points" if len(pids) > 1 else "this point"}.')

        def act():
            for pid in pids:
                if value == AUTOMATIC:
                    self.ds.assignments.pop(pid, None)
                else:
                    self.ds.assignments[pid] = value
            n = len(pids)
            what = f'{n} points' if n != 1 else 'This point'
            return (f'{what} back to the automatic choice.' if value == AUTOMATIC else f'{what} will use {value}.')
        res = self._do('choose standard', act)
        if res.ok and self.match_result is not None:
            self.run_match(self.match_period or self.period)               # the Automation page's table follows, as for set_assignment
        return res


def _ratio(v):
    import tartur
    return tartur.format_ratio(v)
