"""Standards spec editor: the file / database side (Tk-free).

    save_edit(doc, ...)        document an edit and write the sheet file
    restore_edit(id, ...)      put a sheet back as it was before an earlier documented edit (itself a documented edit)
    rebuild_sheet(...)         bring the standard in lab_registry.sqlite3 in line with the edited file, keeping what the database holds on its own
    export_history_csv / export_history_pdf

Writes (project rules): the sheet file is written once, atomically (temporary file in the same folder, then replace), read back and compared with
what was intended; it is never written twice to 'try again'.  If the read-back differs, or the log row cannot be written, the file is put back to
the bytes it had (one recovery write, read back again) and the problem is reported.  The only files written are the sheet, its optional backup in
Backups/spec_editor/, and the temporary file; the only database rows are the log rows (spec_edit_log) and, when asked, the rebuild of the standard's own
rows in lab_registry.sqlite3.  calibration_procedures.sqlite3 is never opened.  Builder scripts are not touched.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import spec_edit_log as log
import spec_editor as se
import specmanager as sm

HERE = Path(__file__).resolve().parent
BACKUP_DIR = HERE / 'Backups' / 'spec_editor'
RESTORE_SOURCE = 'restore of documented edit'


class SaveError(Exception):
    """Nothing was left changed (or, if `file_changed`, the file could not be put back: the message says so and names the backup)."""

    def __init__(self, message, file_changed=False):
        super().__init__(message)
        self.file_changed = file_changed


@dataclass
class RebuildResult:
    done: bool = False
    message: str = ''
    changed: int = 0
    added: int = 0
    removed: int = 0
    kept: list = field(default_factory=list)          # edits made in Standards Specs that were kept
    replaced: list = field(default_factory=list)      # edits made in Standards Specs that this edit's own value replaced


@dataclass
class SaveResult:
    edit_id: int
    kind: str
    path: Path
    backup: object            # Path or None
    sha_before: str
    sha_after: str
    rebuild: object           # RebuildResult or None
    messages: list = field(default_factory=list)


# ------------------------------------------------------------------------------------------------------------ files
def next_backup(name, directory=None) -> Path:
    """<dir>/<stem>_backup_vNN.json with the first free NN (two digits or more), the convention of packages.next_backup."""
    folder = Path(directory) if directory else BACKUP_DIR
    r = Path(name)
    n = 1
    while True:
        cand = folder / f'{r.stem}_backup_v{n:02d}{r.suffix}'
        if not cand.exists():
            return cand
        n += 1


def atomic_write(dest, raw: bytes):
    """Temporary file in the same folder, flushed to disk, then os.replace: the file is either the old bytes or the new bytes."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.spec_edit_', suffix='.tmp', dir=str(dest.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _same_file(path, raw: bytes, data=None) -> bool:
    try:
        back = Path(path).read_bytes()
    except OSError:
        return False
    if back != raw:
        return False
    return True if data is None else json.loads(back.decode('utf-8')) == data


# ------------------------------------------------------------------------------------------------------------ the shared write pipeline
def _write_documented(path, intended: bytes, intended_data, current: bytes, *, kind, edited_by, reason, source, diff, summary, make_backup,
                      backup_dir, rebuild, rebuild_fn, db_path, restored_from, writer, spec_file, model):
    path = Path(path)
    sha_before, sha_after = se.sha256_bytes(current), se.sha256_bytes(intended)
    messages = []
    backup = None
    if make_backup:
        backup = next_backup(spec_file, backup_dir)
        try:
            atomic_write(backup, current)
        except OSError as e:
            raise SaveError(f'The backup could not be written ({e}); nothing was changed.')
        if not _same_file(backup, current):
            raise SaveError(f'The backup {backup.name} does not match the file it should hold; nothing was changed.')
        messages.append(f'Backup saved: {backup}')
    # one write of the sheet, read back, compared
    try:
        writer(path, intended)
    except OSError as e:
        if _same_file(path, current):
            raise SaveError(f'The sheet could not be written ({e}); the file is unchanged.')
        raise _recover(path, current, backup, f'The sheet write failed ({e})')
    if not _same_file(path, intended, intended_data):
        raise _recover(path, current, backup, 'The file read back after the write is not what was intended')
    # the log row; without it the edit is not documented, so the file goes back
    try:
        edit_id = log.append(spec_file, model, kind, edited_by, reason, source, sha_before, sha_after, diff, summary, current,
                             backup_file=backup.name if backup else '', restored_from=restored_from, rebuild_requested=bool(rebuild), path=db_path)
    except (sqlite3.Error, ValueError) as e:
        raise _recover(path, current, backup, f'The edit could not be logged ({e})')
    messages.append(f'Edit {edit_id} documented; file SHA-256 {sha_before[:12]}... -> {sha_after[:12]}...')
    rb = None
    if rebuild:
        try:
            rb = rebuild_fn()
        except Exception as e:                       # the file and the log are already right; say what did not happen
            rb = RebuildResult(done=False, message=f'The standard in the database was not rebuilt ({type(e).__name__}: {e}). The file is saved; reopen Standards Specs or import the file.')
        try:
            log.add_event(edit_id, 'sheet rebuilt' if rb.done else 'sheet not rebuilt', rb.message, path=db_path)
        except sqlite3.Error:
            messages.append('The rebuild result could not be written to the log.')
        messages.append(rb.message)
    return SaveResult(edit_id=edit_id, kind=kind, path=path, backup=backup, sha_before=sha_before, sha_after=sha_after, rebuild=rb, messages=messages)


def _recover(path, original: bytes, backup, why) -> SaveError:
    """One recovery write of the bytes the file had, read back.  Never a second try."""
    try:
        atomic_write(path, original)
        if _same_file(path, original):
            return SaveError(f'{why}. The file was put back to what it was; nothing is changed.')
    except OSError as e:
        why = f'{why}; putting the file back failed too ({e})'
    where = f' The previous file is in {backup}.' if backup else ''
    return SaveError(f'{why}. THE SHEET FILE MAY BE DAMAGED: check {path}.{where}', file_changed=True)


def _check_inputs(edited_by, reason, source):
    for name, value in (('Edited by', edited_by), ('Reason', reason), ('Source / reference', source)):
        if not str(value or '').strip():
            raise SaveError(f'{name} is required.')


# ------------------------------------------------------------------------------------------------------------ save
def save_edit(doc: se.SpecDoc, *, edited_by, reason, source, backup=True, rebuild=True, db_path=None, backup_dir=None, writer=atomic_write) -> SaveResult:
    """Document and write the working copy of `doc`.  Raises SaveError (with the reason) when it cannot; the file is then unchanged."""
    _check_inputs(edited_by, reason, source)
    rep = se.validate(doc)
    if not rep.can_save:
        ne = rep.new_errors
        raise SaveError(f'{len(ne)} validation error{"s" if len(ne) != 1 else ""} introduced by this edit must be fixed first: {ne[0].message}')
    try:
        current = doc.path.read_bytes()
    except OSError as e:
        raise SaveError(f'The sheet file cannot be read ({e}).')
    if se.sha256_bytes(current) != doc.sha:
        raise SaveError('The file changed on disk after it was opened here (a builder script or another editor?). Close the editor and open it again; nothing was written.')
    intended = doc.to_bytes()
    if intended == current or not doc.diff():
        raise SaveError('There are no changes to save.')
    ranges_map = _range_map_from_doc(doc)
    prev_data, new_data = json.loads(current.decode('utf-8')), doc.current
    res = _write_documented(
        doc.path, intended, doc.current, current, kind='edit', edited_by=edited_by, reason=reason, source=source, diff=[c.as_json() for c in doc.diff()],
        summary=doc.summary(), make_backup=backup, backup_dir=backup_dir, rebuild=rebuild,
        rebuild_fn=lambda: rebuild_sheet(prev_data, new_data, ranges_map, who=edited_by, reason=reason, db_path=db_path),
        db_path=db_path, restored_from=None, writer=writer, spec_file=doc.name, model=doc.model)
    doc.rebase(doc.path.read_bytes())
    return res


def restore_edit(edit_id, *, spec_dir=None, edited_by, reason, source='', backup=True, rebuild=True, db_path=None, backup_dir=None, writer=atomic_write) -> SaveResult:
    """Put the sheet back as it was before documented edit `edit_id`.  This is an edit like any other: reason and name required, new log entry."""
    source = (source or '').strip() or f'{RESTORE_SOURCE} {edit_id}'
    _check_inputs(edited_by, reason, source)
    e = log.entry(edit_id, db_path)
    if e is None:
        raise SaveError(f'Edit {edit_id} is not in the log.')
    path = Path(spec_dir or se.STANDARDS_DIR) / e['spec_file']
    before = log.before_bytes(edit_id, db_path)
    if before is None and e['backup_file']:
        cand = Path(backup_dir or BACKUP_DIR) / e['backup_file']
        if cand.is_file() and se.sha256_bytes(cand.read_bytes()) == e['sha_before']:
            before = cand.read_bytes()
    if before is None:
        raise SaveError('The file as it was before this edit is not available (neither the log nor the backup holds a copy that matches its SHA-256).')
    try:
        current = path.read_bytes()
        old_data = json.loads(current.decode('utf-8'))
    except (OSError, ValueError) as e2:
        raise SaveError(f'The current sheet file cannot be read ({e2}).')
    if se.sha256_bytes(current) == e['sha_before']:
        raise SaveError('The file is already exactly as it was before that edit.')
    try:
        new_data = json.loads(before.decode('utf-8'))
    except ValueError:
        raise SaveError('The stored earlier version is not valid JSON.')
    diff = [c.as_json() for c in se.compare_data(old_data, new_data)]
    ranges_map = _range_map_by_key(old_data, new_data)
    summary = f'restored the file as it was before edit {edit_id} ({len(diff)} change{"s" if len(diff) != 1 else ""})'
    res = _write_documented(
        path, before, new_data, current, kind='restore', edited_by=edited_by, reason=reason, source=source, diff=diff, summary=summary,
        make_backup=backup, backup_dir=backup_dir, rebuild=rebuild,
        rebuild_fn=lambda: rebuild_sheet(old_data, new_data, ranges_map, who=edited_by, reason=reason, db_path=db_path),
        db_path=db_path, restored_from=edit_id, writer=writer, spec_file=e['spec_file'], model=e['model'])
    return res


# ------------------------------------------------------------------------------------------------------------ rebuilding the standard in the database
def _flat_ranges(data):
    return [(f, r) for f in data.get('functions') or [] if isinstance(f, dict) for r in f.get('ranges') or [] if isinstance(r, dict)]


def _range_map_from_doc(doc: se.SpecDoc):
    """For every range of the working copy, the 0-based position of the same row in the file as it was opened (None for a new row)."""
    org_pos = {doc._uid_org[id(r)]: i for i, (_, r) in enumerate(_flat_ranges(doc.original))}
    return [org_pos.get(doc.uid(r)) for _, r in doc.ranges()]


def _range_map_by_key(old_data, new_data):
    """Same, for two versions of a file with no editing session: rows are matched by their printed identity (label, variant, kind, span)."""
    def key(f, r):
        return (f.get('name'), f.get('direction'), r.get('label'), r.get('variant'), r.get('kind'), r.get('amp_lo'), r.get('amp_hi'), r.get('freq_lo'), r.get('freq_hi'))
    seen, pos = {}, {}
    for i, (f, r) in enumerate(_flat_ranges(old_data)):
        k = key(f, r)
        n = seen.get(k, 0)
        seen[k] = n + 1
        pos[(k, n)] = i
    seen, out = {}, []
    for f, r in _flat_ranges(new_data):
        k = key(f, r)
        n = seen.get(k, 0)
        seen[k] = n + 1
        out.append(pos.get((k, n)))
    return out


ROW_COLUMNS = ('function', 'direction', 'kind', 'variant', 'label', 'unit', 'amp_lo', 'amp_hi', 'freq_lo', 'freq_hi', 'range_max', 'resolution', 'res_src',
               'qualifiers_json', 'specs_json', 'note_refs', 'page')
ROW_EDITABLE = ('variant', 'amp_lo', 'amp_hi', 'freq_lo', 'freq_hi', 'range_max', 'resolution', 'res_src', 'specs_json')       # what Standards Specs lets a person change (specmanager.update_row)
HEADER_COLUMNS = (('manufacturer', 'manufacturer'), ('description', 'description'), ('confidence_text', 'confidence_text'), ('confidence_pct', 'confidence_pct'),
                  ('reference', 'reference'), ('revision', 'revision'), ('author', 'author'), ('approved_by', 'approved_by'), ('approve_date', 'approve_date'),
                  ('source_file', 'source_pdf'))


def _row_values(fn, r) -> dict:
    """The spec_rows columns of one range, built the way specmanager.import_data builds them."""
    notes = sorted({x for p in r.get('params', []) for x in p.get('notes', [])})
    return dict(function=fn['name'], direction=fn.get('direction') or 'output', kind=r.get('kind', 'OTHER'), variant=r.get('variant', ''), label=r['label'],
                unit=r.get('unit', ''), amp_lo=r.get('amp_lo'), amp_hi=r.get('amp_hi'), freq_lo=r.get('freq_lo'), freq_hi=r.get('freq_hi'), range_max=r.get('range_max'),
                resolution=r.get('resolution'), res_src=r.get('res_src', ''), qualifiers_json=json.dumps(r.get('qualifiers', [])), specs_json=json.dumps(r.get('specs', [])),
                note_refs=','.join(str(x) for x in notes), page=r.get('page'))


def _same_value(col, a, b) -> bool:
    if col == 'specs_json':
        try:
            return json.loads(a or '[]') == json.loads(b or '[]')
        except ValueError:
            return a == b
    return (a if a not in ('',) else None) == (b if b not in ('',) else None)


def rebuild_sheet(prev_data, new_data, ranges_map, *, who, reason, db_path=None) -> RebuildResult:
    """Bring the standard of `new_data` in lab_registry.sqlite3 in line with the edited file, in ONE transaction, keeping its database id, assets, divisor,
    default period and the change log; rows keep their ids.  What a person changed in Standards Specs (a calibrator resolution, the divisor, an approval ...)
    is kept unless the edit itself changed the same field.  Nothing is guessed: when the database does not hold the sheet as it was before the edit and has
    edits of its own, it is left alone and the result says why.  calibration_procedures.sqlite3 is not opened."""
    model = str((new_data.get('standard') or {}).get('model', '')).strip()
    if not model:
        return RebuildResult(message='The sheet has no model; the database was not touched.')
    prev_ranges, new_ranges = _flat_ranges(prev_data), _flat_ranges(new_data)
    try:
        with sm._db(db_path) as con:
            std = con.execute('SELECT id FROM standards WHERE model=?', (model,)).fetchone()
            if not std:
                return RebuildResult(message=f'{model} is not loaded in lab_registry.sqlite3 yet; it loads from the file the next time Standards Specs is opened. Nothing to rebuild.')
            sid = std[0]
            cols = ','.join(('id', 'ordinal', 'edited') + ROW_COLUMNS)
            old_rows = [dict(zip(('id', 'ordinal', 'edited') + ROW_COLUMNS, r)) for r in con.execute(f'SELECT {cols} FROM spec_rows WHERE standard_id=? ORDER BY ordinal', (sid,))]
            in_sync = len(old_rows) == len(prev_ranges) and all(o['function'] == f.get('name') and o['label'] == r.get('label') for o, (f, r) in zip(old_rows, prev_ranges))
            if not in_sync and any(o['edited'] for o in old_rows):
                return RebuildResult(message=f'The database rows of {model} differ from the file as it was before this edit and carry edits made in Standards Specs; they could not be matched '
                                             'safely, so the database was left alone. The file is saved; review the resolutions in Standards Specs.')
            res = RebuildResult()
            matched = {}
            if in_sync:
                for new_i, old_i in enumerate(ranges_map):
                    if old_i is not None and old_i < len(old_rows):
                        matched[new_i] = old_i
            keep_ids = set()
            ordinal = 0
            for new_i, (f, r) in enumerate(new_ranges):
                ordinal += 1
                new_vals = _row_values(f, r)
                if new_i in matched:
                    old = old_rows[matched[new_i]]
                    prev_vals = _row_values(*prev_ranges[matched[new_i]])
                    vals, edited = dict(new_vals), 0
                    for col in ROW_EDITABLE:
                        db_only = not _same_value(col, old[col], prev_vals[col])
                        if not db_only:
                            continue
                        if _same_value(col, new_vals[col], prev_vals[col]):
                            vals[col] = old[col]
                            edited = 1
                            res.kept.append(f"row {ordinal} {col}")
                        else:
                            res.replaced.append(f"row {ordinal} {col}: {old[col]} -> {new_vals[col]}")
                    changed = any(not _same_value(c, vals[c], old[c]) for c in ROW_COLUMNS) or old['ordinal'] != ordinal
                    con.execute(f'UPDATE spec_rows SET ordinal=?, edited=?, {",".join(c + "=?" for c in ROW_COLUMNS)} WHERE id=?',
                                (ordinal, edited) + tuple(vals[c] for c in ROW_COLUMNS) + (old['id'],))
                    keep_ids.add(old['id'])
                    res.changed += 1 if changed else 0
                else:
                    cur = con.execute(f'INSERT INTO spec_rows(standard_id,ordinal,{",".join(ROW_COLUMNS)}) VALUES(?,?,{",".join("?" * len(ROW_COLUMNS))})',
                                      (sid, ordinal) + tuple(new_vals[c] for c in ROW_COLUMNS))
                    keep_ids.add(cur.lastrowid)
                    res.added += 1
            for o in old_rows:
                if o['id'] not in keep_ids:
                    con.execute('DELETE FROM spec_rows WHERE id=?', (o['id'],))
                    res.removed += 1
            # header: file values, except what a person set in Standards Specs and this edit did not change
            cur_db = dict(zip([c for c, _ in HEADER_COLUMNS], con.execute(f'SELECT {",".join(c for c, _ in HEADER_COLUMNS)} FROM standards WHERE id=?', (sid,)).fetchone()))
            prev_std, new_std = prev_data.get('standard') or {}, new_data.get('standard') or {}
            sets = {}
            for col, key in HEADER_COLUMNS:
                nv, pv = new_std.get(key), prev_std.get(key)
                nv_db = '' if (nv is None and col != 'confidence_pct') else nv
                pv_db = '' if (pv is None and col != 'confidence_pct') else pv
                if cur_db[col] != pv_db and nv_db == pv_db:
                    res.kept.append(f'header {col}')
                    continue
                if cur_db[col] != pv_db and nv_db != pv_db:
                    res.replaced.append(f'header {col}: {cur_db[col]} -> {nv_db}')
                sets[col] = nv_db
            problems = new_data.get('problems') or sm.validate_data(new_data)
            sets['notes_json'] = json.dumps(new_data.get('notes', {}))
            sets['problems_json'] = json.dumps(problems)
            sets['imported_at'] = datetime.now().isoformat(timespec='seconds')
            con.execute(f'UPDATE standards SET {",".join(k + "=?" for k in sets)} WHERE id=?', tuple(sets.values()) + (sid,))
            note = f'{len(new_ranges)} rows ({res.changed} changed, {res.added} added, {res.removed} removed); kept {len(res.kept)} field(s) edited in Standards Specs'
            sm._log(con, sid, None, 'sheet_rebuild', f'{len(prev_ranges)} rows', note, who, f'spec editor: {reason}')
            for r_ in res.replaced:
                sm._log(con, sid, None, 'sheet_rebuild_replaced', r_, 'value from the edited sheet', who, f'spec editor: {reason}')
            res.done = True
            res.message = f'Standard {model} rebuilt in the database from the edited sheet: {note}.' + (
                f' {len(res.replaced)} edit(s) made in Standards Specs were replaced by this edit\'s own values (listed in the change log).' if res.replaced else '')
            return res
    except sqlite3.Error as e:
        return RebuildResult(message=f'The database could not be updated ({e}); the standard keeps its previous rows. The file is saved.')


# ------------------------------------------------------------------------------------------------------------ reading state
def sheet_state(doc_or_path, db_path=None) -> dict:
    """The sheet's standing against its log: edited by hand since built / changed outside the editor / as built (see spec_edit_log.hand_edit_state)."""
    path = Path(doc_or_path.path if hasattr(doc_or_path, 'path') else doc_or_path)
    try:
        sha = se.sha256_bytes(path.read_bytes())
    except OSError:
        return dict(state='missing', edits=0, last=None, built_sha='')
    st = log.hand_edit_state(path.name, sha, db_path)
    st['builders'] = se.builders_for(path.name)
    return st


def state_text(st) -> str:
    """One line for the Standard info tab / the history header."""
    b = ', '.join(n for n, _ in st.get('builders') or []) or 'its builder script'
    last = st.get('last')
    if st['state'] == 'edited by hand':
        return (f"Edited by hand since built: {st['edits']} documented edit{'s' if st['edits'] != 1 else ''}, last {last['at'].replace('T', ' ')} by {last['edited_by']}. "
                f'Running {b} again would overwrite them.')
    if st['state'] == 'changed outside':
        return (f"Changed outside the editor since the last documented edit ({last['at'].replace('T', ' ')}): the file was replaced or edited some other way "
                f'(for example {b} was run again). Its documented edits may no longer be in it.')
    if st['state'] == 'back to as built':
        return f"Back to the file as built ({st['edits']} documented edit{'s' if st['edits'] != 1 else ''} in the history, the last one a restore or a reversal)."
    if st['state'] == 'missing':
        return 'The sheet file is missing.'
    return f'As built: no documented edits. Running {b} would rewrite the file.'


def database_notes(doc: se.SpecDoc, db_path=None) -> list:
    """[(level, text)] about the standard in lab_registry.sqlite3 that only the database can tell (read only)."""
    out = []
    try:
        with sm._db(db_path) as con:
            row = con.execute('SELECT id, divisor FROM standards WHERE model=?', (doc.model,)).fetchone()
            if not row:
                return [('info', f'{doc.model} is not loaded in the database yet: the rebuild option has nothing to update (the file is read the next time Standards Specs opens).')]
            edited = con.execute('SELECT COUNT(*) FROM spec_rows WHERE standard_id=? AND edited=1', (row[0],)).fetchone()[0]
            divisor = row[1]
    except sqlite3.Error:
        return []
    if any(c.key == 'confidence_pct' for c in doc.diff()) and divisor:
        out.append(('warn', f'A divisor of {divisor:g} was set in Standards Specs; it wins over the confidence level, so changing the confidence changes nothing until it is cleared there.'))
    if edited:
        out.append(('info', f'{edited} row(s) carry resolutions or values set in Standards Specs; a rebuild keeps them unless this edit changes the same field.'))
    return out


# ------------------------------------------------------------------------------------------------------------ history export
def history_lines(entry) -> list:
    """Printable lines for one log entry's changes."""
    lines = []
    for c in entry.get('diff') or []:
        where = c.get('where', '')
        if c.get('op') == 'set':
            lines.append(f"{where} / {c.get('field', '')}")
            lines.append(f"  - {c.get('old_text', '')}")
            lines.append(f"  + {c.get('new_text', '')}")
        elif c.get('op') == 'add':
            lines.append(f"{where}: {c.get('field', '')}")
            lines.append(f"  + {c.get('new_text', '')}")
        else:
            lines.append(f"{where}: {c.get('field', '')}")
            lines.append(f"  - {c.get('old_text', '')}")
    return lines


def export_history_csv(spec_file, dest, db_path=None) -> int:
    es = list(reversed(log.entries(spec_file, db_path)))
    with open(dest, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'time', 'kind', 'edited by', 'reason', 'source', 'backup file', 'sha256 before', 'sha256 after', 'changes'])
        for e in es:
            w.writerow([e['id'], e['at'], e['kind'], e['edited_by'], e['reason'], e['source'], e['backup_file'], e['sha_before'], e['sha_after'], ' | '.join(history_lines(e))])
    return len(es)


def pdf_available() -> bool:
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


def export_history_pdf(spec_file, dest, db_path=None, model='', state_line='') -> int:
    """PDF of the edit history of one sheet (oldest first).  Needs reportlab; fonts as the suite's reports (report_pdf._fonts) so the micro sign prints."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    import report_pdf
    from xml.sax.saxutils import escape
    reg, bold, _ = report_pdf._fonts()
    es = list(reversed(log.entries(spec_file, db_path)))
    st_h = ParagraphStyle('h', fontName=bold, fontSize=15, spaceAfter=4)
    st_n = ParagraphStyle('n', fontName=reg, fontSize=9, leading=12)
    st_b = ParagraphStyle('b', fontName=bold, fontSize=10.5, leading=13, spaceBefore=8)
    st_m = ParagraphStyle('m', fontName=reg, fontSize=8, leading=10, leftIndent=8)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(reg, 8)
        canvas.drawString(0.7 * inch, 0.45 * inch, f'Standards spec edit history - {spec_file}')
        canvas.drawRightString(letter[0] - 0.7 * inch, 0.45 * inch, f'Page {doc.page}')
        canvas.restoreState()
    story = [Paragraph('Standards spec edit history', st_h),
             Paragraph(escape(f'{model or spec_file}  -  specs/standards/{spec_file}  -  {len(es)} documented edit{"s" if len(es) != 1 else ""}  -  printed {datetime.now():%Y-%m-%d %H:%M}'), st_n)]
    if state_line:
        story.append(Paragraph(escape(state_line), st_n))
    story.append(Spacer(1, 6))
    for e in es:
        rows = [['Edited by', e['edited_by']], ['Kind', e['kind'] + (f" (undoes the edit before edit {e['restored_from']})" if e.get('restored_from') else '')], ['Reason', e['reason']],
                ['Source', e['source']], ['Backup file', e['backup_file'] or '(none)'], ['SHA-256 before', e['sha_before']], ['SHA-256 after', e['sha_after']]]
        table = Table([[Paragraph(escape(a), st_n), Paragraph(escape(str(b)), st_n)] for a, b in rows], colWidths=[1.2 * inch, 5.9 * inch])
        table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.lightgrey), ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
        block = [Paragraph(escape(f"Edit {e['id']}  -  {e['at'].replace('T', ' ')}  -  {e['summary']}"), st_b), table, Spacer(1, 3)]
        lines = history_lines(e)
        story.append(KeepTogether(block + ([Paragraph(escape(lines[0]).replace(' ', '&nbsp;') if lines else '', st_m)] if lines else [])))
        for ln in lines[1:]:
            story.append(Paragraph(escape(ln).replace(' ', '&nbsp;'), st_m))
    if not es:
        story.append(Paragraph('No documented edits.', st_n))
    SimpleDocTemplate(str(dest), pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.7 * inch, bottomMargin=0.8 * inch,
                      title=f'Standards spec edit history - {spec_file}').build(story, onFirstPage=footer, onLaterPages=footer)
    return len(es)
