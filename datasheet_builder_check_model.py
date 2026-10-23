"""Datasheet Builder: the 'Sheet check' of the grid editor, model side (no tkinter).  Mixed into datasheet_builder_ui_model.GridModel.

    g.sheet_check()            -> datasheet_builder_rules.SheetCheck for the sheet as it is now (cached until the next edit; the dry run is part of it)
    g.check_counts()           -> dict(errors, warnings, info) or None when the check has not been run for this version of the sheet
    g.check_rows()             -> [dict(idx, level, rule, title, where, row, key, text, fix, action)] for the Sheet check window
    g.check_pill()             -> (text, kind) for the pill beside 'saved' / the warnings pill ('' when the check has not been run)
    g.apply_check_fix(idx)     -> Outcome: 'enter it by hand' (rule 1) or 'make it a pass / fail check' (rule 3), one undo step
    g.uncertainty_line()       -> (text, level) for the selected row: the standards sheet its uncertainty comes from, or 'none: blank (...)'  (rule 5)
    g.pre_run_list()           -> dict(count, points, lines, fingerprint) the commands a real run asks the operator to accept (rule 2)

Presentation and validation only: nothing here changes a limit, a command, a pass / fail rule or a safety prompt.  The edits it offers (enter by hand,
make a flagged pass / fail check) are ordinary undoable edits of the sheet.
"""
from __future__ import annotations

import datasheet_builder as db
import datasheet_builder_rules as rules


def _outcome(ok, message):
    from datasheet_builder_ui_model import Outcome
    return Outcome(ok, message)


class CheckMixin:
    _check_cache = None            # (rev, period, SheetCheck)
    _src_cache = None              # (rev, period, {point id: UncertaintySource})

    # ---- the check
    def sheet_check(self, compute=True, dry_run=True):
        key = (self._rev, self.period)
        c = self._check_cache
        if c is not None and c[:2] == key:
            return c[2]
        if not compute:
            return None
        try:
            matcher = self._get_matcher()
        except Exception:
            matcher = None
        chk = rules.check(self.ds, self.period, matcher=matcher, dry_run_on=dry_run)
        self._check_cache = (self._rev, self.period, chk)
        return chk

    def check_fresh(self):
        return self.sheet_check(compute=False) is not None

    def check_counts(self, compute=False):
        chk = self.sheet_check(compute=compute)
        return None if chk is None else chk.counts()

    def check_pill(self):
        chk = self.sheet_check(compute=False)
        if chk is None:
            return '', 'good'
        c = chk.counts()
        if c['errors']:
            return f'check: {c["errors"]} to fix', 'bad'
        if c['warnings']:
            return f'check: {c["warnings"]} warning{"s" * (c["warnings"] != 1)}', 'warn'
        return 'check: ok', 'good'

    def check_rows(self, compute=True):
        chk = self.sheet_check(compute=compute)
        if chk is None:
            return []
        idx = {r['key']: r['n'] for r in self.rows()}
        out = []
        for i, f in enumerate(chk.findings):
            if f.level == rules.INFO and f.rule != 4 and not f.text:
                continue
            out.append(dict(idx=i, level=f.level, rule=f.rule, title=f.title, where=f.section or ('Whole datasheet' if not f.function_id else f.function_id),
                            row=idx.get(f.key), key=f.key, text=f.text, fix=f.fix, action=f.action, count=f.count, code=f.code))
        return out

    def check_summary(self, compute=False):
        chk = self.sheet_check(compute=compute)
        if chk is None:
            return 'Sheet check: not run yet for this version of the sheet.'
        extra = ''
        if not chk.dry.available and chk.dry.reason and not self.ds.options.get('manual_entry'):
            extra = f' (the dry run did not run: {chk.dry.reason})'
        elif chk.dry.available:
            extra = f' ({chk.dry.ran} points tried on the simulated bench)'
        return chk.summary() + extra

    # ---- the fixes the check offers
    def apply_check_fix(self, idx):
        chk = self.sheet_check(compute=False)
        if chk is None or not 0 <= idx < len(chk.findings):
            return _outcome(False, 'Run the sheet check again: the sheet has changed.')
        f = chk.findings[idx]
        if f.action == 'waive':
            return _outcome(False, 'Press "Waive..." and give the reason.')
        if not f.action:
            return _outcome(False, 'This finding has no automatic fix. Read the "what to do" text.')

        def act():
            if f.action == 'manual_entry':
                n = rules.manual_entry_for(self.ds, f)
                return f'{n} point{"s" * (n != 1)} will be entered by hand (the operator uses their own standard).'
            if f.action == 'unwaive':
                n = rules.clear_waiver(self.ds, f.point_ids)
                return f'{n} waiver{"s" * (n != 1)} removed: the uncertainty is missing again until a standard covers the point or it is waived.'
            if f.action == 'make_check':
                for pid in f.point_ids:
                    rules.make_check_row(self.ds, f.function_id, pid)
                return f'{len(f.point_ids)} row{"s" * (len(f.point_ids) != 1)} turned into a flagged pass / fail check (answered Yes / No).'
            raise db.DsError('fix', 'Unknown fix.')
        return self._do('sheet check fix', act)

    def waive_finding(self, idx, code, reason=''):
        """Record a waiver (reason chosen from rules.WAIVER_REASONS or typed) for the points of finding `idx` (rule 5).  One undo step."""
        chk = self.sheet_check(compute=False)
        if chk is None or not 0 <= idx < len(chk.findings) or chk.findings[idx].action != 'waive':
            return _outcome(False, 'Run the sheet check again: the sheet has changed.')
        f = chk.findings[idx]
        who = getattr(getattr(self, 'storage', None), 'who', '') or ''

        def act():
            n = rules.set_waiver(self.ds, f.point_ids, code, reason, who)
            return f'{n} reading{"s" * (n != 1)} waived: the report shows no uncertainty for {"them" if n != 1 else "it"}. The waiver is saved with the sheet.'
        return self._do('waive uncertainty', act)

    # ---- rule 5 in the inspector
    def uncertainty_line(self, key=None):
        """(text, level) for the selected row, level ok | info | warn.  ('', 'ok') for a row that is not a test point."""
        row = (self.row(key) if key else self.selected_row()) or {}
        if row.get('kind') != 'point' or not row.get('fid'):
            return '', 'ok'
        fid, pid = row['fid'], row.get('pid') or ''
        if not pid:
            pid = str(row['key']).rsplit(':', 1)[-1]
        chk = self.sheet_check(compute=False)
        if chk is not None and pid in chk.sources:
            s = chk.sources[pid]
        else:
            c = self._src_cache
            if c is None or c[:2] != (self._rev, self.period):
                c = self._src_cache = (self._rev, self.period, {})
            if pid not in c[2]:
                try:
                    c[2][pid] = rules.point_source(self.ds, fid, pid, matcher=self._get_matcher(), period=self.period)
                except Exception:
                    c[2][pid] = None
            s = c[2][pid]
        if s is None:
            return '', 'ok'
        return s.text, s.level

    # ---- rule 2 before a real run
    def pre_run_list(self, compute=True):
        chk = self.sheet_check(compute=compute)
        if chk is None:
            return dict(count=0, points=0, lines=[], fingerprint='', dry=False)
        return dict(count=len(chk.unverified), points=len(chk.unverified_points()), lines=chk.pre_run_lines(), fingerprint=chk.fingerprint(), dry=chk.dry.available)
