"""Report snapshots: everything report_pdf needs to print a report again, saved when the report is issued, and the logic to regenerate it.

    report_snapshots   NEW table in lab_registry.sqlite3, one row per Asset History event (runs.id) written when a real (non-demo) report is issued

What is stored (JSON, canonical, with a SHA-256 over exactly that text):
    header pairs, title, the details dict from the report dialog (technician, conditions, standards with their cal info, procedure, TAR / TUR choice),
    the report rows exactly as printed (As Found / As Left / OOT / uncertainty / TAR / TUR; the strings are already display-scaled by report_pdf.cert_row,
    nothing is rescaled or re-judged), the footer note (uncertainty source text), the modifications list handed to the report, the printed
    issue date, and version stamps (suite version, a hash of the engine code and of the spec the run used, the procedure-modification summary).

Who calls what:
    report_pdf.write_calibration_pdf  ->  record_issued()   the ONE shared helper; every engine's PDF goes through that function
    each engine's export call          ->  context_for(app)  (via report_pdf.context_for) for the version stamps
    labregistry_ui.HistoryPanel        ->  availability() / regenerate()   the Asset History 'Regenerate PDF' action

Rules (project): calibration_procedures.sqlite3 is never touched; the new table is additive in lab_registry.sqlite3; no function raises on a
missing or damaged database (callers get False / None / a message); demo data is never snapshotted; a reprint carries the ORIGINAL issue date and
technician and adds one clearly worded line to the page footer only; nothing is guessed - an event without a snapshot is rebuilt from the history
rows only when those rows are complete, and the report says so.  No tkinter in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

FORMAT = 'calsuite-report-snapshot'
SCHEMA_VERSION = 1
HERE = Path(__file__).resolve().parent

TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS report_snapshots (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
'''

# load / plan statuses
OK, MISSING, MISMATCH, DAMAGED, DEMO, UNLINKED = 'ok', 'missing', 'mismatch', 'damaged', 'demo', 'unlinked'
SNAPSHOT, REBUILT, NONE = 'snapshot', 'rebuilt', 'none'

Loaded = namedtuple('Loaded', 'status data message')
Plan = namedtuple('Plan', 'kind message data run missing')           # data: the report dict; run: the history row; missing: what a rebuilt report lacks
Result = namedtuple('Result', 'ok path kind message')


class _NotJson(ValueError):
    pass


# ------------------------------------------------------------------------------------------------------------ canonical json
def _jsonable(value):
    """Plain JSON data for a report argument.  A TarTur selection becomes {'__tar_tur__': [tar, tur]}.  Anything that cannot be represented
    exactly (NaN, objects) raises _NotJson: a snapshot is all or nothing, never a lossy copy."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float('inf'), float('-inf')):
            raise _NotJson('non-finite number')
        return value
    if hasattr(value, 'tar') and hasattr(value, 'tur') and hasattr(value, '_fields'):
        return {'__tar_tur__': [bool(value.tar), bool(value.tur)]}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat(timespec='seconds')
    if isinstance(value, Path):
        return str(value)
    raise _NotJson(type(value).__name__)


def _restore(value):
    """Inverse of _jsonable for the one special form (TarTur)."""
    if isinstance(value, dict):
        if set(value) == {'__tar_tur__'}:
            import report_pdf
            tar, tur = value['__tar_tur__']
            return report_pdf.TarTur(bool(tar), bool(tur))
        return {k: _restore(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_restore(v) for v in value]
    return value


def canon(data) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ------------------------------------------------------------------------------------------------------------ database
def _db_path(path=None):
    if path:
        return Path(path)
    import labregistry
    return Path(labregistry.DB)


@contextmanager
def _db(path=None):
    con = sqlite3.connect(str(_db_path(path)), timeout=5)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        import labregistry
        con.executescript(labregistry.SCHEMA)              # the runs table must exist for the link; creating it is idempotent and additive
        con.executescript(TABLE_SQL)
        yield con
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------------------ version stamps
def _file_sha(path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ''


def context_for(app) -> dict:
    """Version stamps for an engine's App: suite version, the hash of each project module the engine class is built from (its 'procedure
    version'), the spec it ran (file name + file hash, or a hash of the in-memory spec) with the spec's schema / datasheet identity, As Left
    present, and the procedure modifications in effect (procmods_engine.applied_info; informational: the PDF does not print them today).
    Never raises; a stamp that cannot be read is simply left out."""
    ctx = {}
    try:
        import suite_info
        ctx['suite'] = {'name': suite_info.NAME, 'version': suite_info.full_version()}
    except Exception:
        pass
    try:
        code = {}
        for cls in type(app).__mro__:
            mod = sys.modules.get(getattr(cls, '__module__', ''))
            f = getattr(mod, '__file__', None)
            if f and Path(f).resolve().is_relative_to(HERE):
                code[mod.__name__] = _file_sha(f)
        import report_pdf
        code['report_pdf'] = _file_sha(report_pdf.__file__)
        ctx['code_sha256'] = code
    except Exception:
        pass
    try:
        mod = sys.modules.get(type(app).__module__)
        spec = getattr(app, 'spec', None)
        if not isinstance(spec, dict):
            spec = getattr(mod, 'SPEC', None)
        stamp = {}
        spec_path = getattr(app, 'spec_path', None) or getattr(mod, 'SPEC_PATH', None)
        if isinstance(spec, dict):
            stamp['schema'] = _jsonable(spec.get('schema'))
            stamp['sha256'] = sha(canon(_jsonable(spec)))
            dsb = spec.get('dsb')
            if isinstance(dsb, dict):
                stamp['datasheet'] = {k: _jsonable(dsb.get(k)) for k in ('uid', 'version', 'revision', 'title', 'period') if dsb.get(k) is not None}
        if spec_path and Path(str(spec_path)).is_file() and not (isinstance(spec, dict) and spec.get('dsb')):
            stamp['file'] = Path(str(spec_path)).name
            stamp['file_sha256'] = _file_sha(spec_path)
        if stamp:
            ctx['spec'] = stamp
    except Exception:
        pass
    try:
        ctx['as_left_present'] = bool(getattr(app, 'left', None))
    except Exception:
        pass
    try:
        if getattr(app, 'pm_state', None) is not None:
            import procmods_engine
            ctx['procedure_modifications'] = _jsonable(procmods_engine.applied_info(app))
    except Exception:
        pass
    return ctx


# ------------------------------------------------------------------------------------------------------------ saving
def build_payload(*, header, rows, title, details, footer_note, show_tar_tur, modifications, issued_at, context=None) -> dict:
    """The snapshot dict (plain JSON data).  Raises _NotJson when something cannot be stored exactly."""
    return {
        'format': FORMAT, 'schema': SCHEMA_VERSION,
        'title': _jsonable(title),
        'header': [[str(k), _jsonable(v)] for k, v in (header or [])],
        'rows': [_jsonable(dict(r)) for r in rows],
        'details': _jsonable(dict(details or {})),
        'show_tar_tur': _jsonable(show_tar_tur),
        'modifications': _jsonable(list(modifications)) if modifications else [],
        'footer_note': _jsonable(footer_note or ''),
        'issued_at': str(issued_at),
        'demo': False,
        'stamps': _jsonable(context or {}),
    }


def record_issued(run_id, *, header, rows, title='Calibration Data', details=None, footer_note='', show_tar_tur=None, modifications=None,
                  issued_at='', context=None, demo=False, db_path=None, now=None) -> bool:
    """Save the snapshot of an issued report against its Asset History event.  False (nothing written) for a demo report, for no event
    (run_id not an int: the report has no Instrument ID so it is not in the history), for data that cannot be stored exactly, or on any
    database problem.  Never raises."""
    if demo or not isinstance(run_id, int) or isinstance(run_id, bool) or not rows:
        return False
    try:
        payload = build_payload(header=header, rows=rows, title=title, details=details, footer_note=footer_note, show_tar_tur=show_tar_tur,
                                modifications=modifications, issued_at=issued_at, context=context)
        text = canon(payload)
        stamp = (now or datetime.now)().isoformat(timespec='seconds')
        with _db(db_path) as con:
            con.execute('INSERT OR REPLACE INTO report_snapshots(run_id,schema_version,created_at,sha256,payload_json) VALUES(?,?,?,?,?)',
                        (run_id, SCHEMA_VERSION, stamp, sha(text), text))
        return True
    except (_NotJson, TypeError, ValueError, sqlite3.Error, OSError):
        return False
    except Exception:
        return False


# ------------------------------------------------------------------------------------------------------------ loading
MSG_MISSING = ('There is no saved report record for this event. It was issued before report records were kept, or the record has been removed.')
MSG_MISMATCH = ('The saved record for this report no longer matches its checksum, so it was changed or damaged after it was saved. '
                'The PDF was not regenerated.')
MSG_DAMAGED = 'The saved record for this report cannot be read, so the PDF was not regenerated.'
MSG_DB = 'The lab registry database could not be read.'
MSG_DEMO = 'The saved record is marked as demo data, which is never reissued as a calibration report.'


def run_row(run_id, db_path=None):
    """The Asset History event as a dict (columns of labregistry.runs), or None."""
    try:
        with _db(db_path) as con:
            row = con.execute('SELECT id,asset_id,serial,model,procedure,run_at,technician,temperature,humidity,total,failed,report_file,standards_json '
                              'FROM runs WHERE id=?', (int(run_id),)).fetchone()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return None
    keys = ('id', 'asset_id', 'serial', 'model', 'procedure', 'run_at', 'technician', 'temperature', 'humidity', 'total', 'failed', 'report_file',
            'standards_json')
    return dict(zip(keys, row)) if row else None


def load(run_id, db_path=None) -> Loaded:
    """The verified snapshot of an event.  status ok / missing / mismatch (hash differs) / damaged / demo / unlinked (the event is gone or
    belongs to another asset).  Never raises."""
    try:
        with _db(db_path) as con:
            row = con.execute('SELECT schema_version,sha256,payload_json FROM report_snapshots WHERE run_id=?', (int(run_id),)).fetchone()
            run = con.execute('SELECT asset_id FROM runs WHERE id=?', (int(run_id),)).fetchone()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return Loaded(DAMAGED, None, MSG_DB)
    if row is None:
        return Loaded(MISSING, None, MSG_MISSING)
    version, digest, text = row
    if not isinstance(text, str) or sha(text) != digest:
        return Loaded(MISMATCH, None, MSG_MISMATCH)
    try:
        data = json.loads(text)
        if data.get('format') != FORMAT or int(version) != SCHEMA_VERSION or data.get('schema') != SCHEMA_VERSION:
            return Loaded(DAMAGED, None, 'The saved record uses a format this version of the program does not know, so the PDF was not regenerated.')
        for key in ('header', 'rows', 'details', 'title', 'issued_at'):
            if key not in data:
                return Loaded(DAMAGED, None, MSG_DAMAGED)
        if not isinstance(data['rows'], list) or not data['rows'] or not all(isinstance(r, dict) for r in data['rows']):
            return Loaded(DAMAGED, None, MSG_DAMAGED)
    except (ValueError, TypeError, AttributeError):
        return Loaded(DAMAGED, None, MSG_DAMAGED)
    if data.get('demo'):
        return Loaded(DEMO, None, MSG_DEMO)
    asset = next((v for k, v in data['header'] if k == 'Instrument ID'), None)
    if run is None or str(asset or '').strip().lower() != str(run[0]).strip().lower():
        return Loaded(UNLINKED, None, 'The saved record does not belong to this history entry, so the PDF was not regenerated.')
    data['content_sha256'] = digest
    return Loaded(OK, data, '')


# ------------------------------------------------------------------------------------------------------------ old events: history rows
REBUILT_LACKS = ('As Left readings', 'uncertainty values', 'TAR / TUR', 'procedure modifications', 'the original title', 'the exact time of issue')


def rebuild_from_history(run_id, db_path=None):
    """(report dict, run row, problem).  A report built ONLY from what the Asset History stored for the event (labregistry runs / points).
    problem is '' when the rows are complete enough, else plain words saying what is missing (report dict is None then).  Nothing is invented:
    As Left, uncertainty, TAR / TUR are left blank, the title is the standard 'Calibration Data'."""
    run = run_row(run_id, db_path)
    if run is None:
        return None, None, 'This history entry could not be read.'
    points = _points(run_id, db_path)
    if not points:
        return None, run, 'No test points were stored for this event.'
    if len(points) != int(run['total'] or 0):
        return None, run, f'Only {len(points)} of the {run["total"]} points of this report are stored.'
    if sum(1 for p in points if p['result'] == 'FAIL') != int(run['failed'] or 0):
        return None, run, 'The stored points do not agree with the stored pass / fail count.'
    gaps = [p for p in points if not (p['description'] and p['nominal'] and p['found'] != '' and p['low'] != '' and p['high'] != '')]
    if gaps:
        return None, run, (f'{len(gaps)} of the stored points have no As Found reading or no limits (for example a point measured only after an '
                           'adjustment), so the report cannot be rebuilt without guessing.')
    try:
        standards = json.loads(run['standards_json'] or '[]')
    except ValueError:
        standards = []
    when = str(run['run_at']).replace('T', ' ')[:16]
    rows = [{'Section': p['section'], 'Description': p['description'], 'Nominal': p['nominal'], 'Tolerance -': p['low'], 'Tolerance +': p['high'],
             'UOM': p['unit'], 'As Found': p['found'], 'OOT': 'OOT' if p['result'] == 'FAIL' else '', 'As Left': '', 'Uncertainty': ''} for p in points]
    data = {
        'format': FORMAT, 'schema': SCHEMA_VERSION, 'title': 'Calibration Data',
        'header': [['Instrument', run['model']], ['Instrument ID', run['asset_id']], ['Serial', run['serial']]],
        'rows': rows,
        'details': {'technician': run['technician'], 'temperature': run['temperature'], 'humidity': run['humidity'],
                    'standards': standards, 'procedure': run['procedure']},
        'show_tar_tur': None, 'modifications': [], 'footer_note': '', 'issued_at': when, 'demo': False, 'stamps': {},
    }
    return data, run, ''


def _points(run_id, db_path):
    keys = ('section', 'description', 'nominal', 'low', 'high', 'unit', 'found', 'result', 'dev_pct')
    try:
        with _db(db_path) as con:
            return [dict(zip(keys, r)) for r in con.execute(
                'SELECT section,description,nominal,low,high,unit,found,result,dev_pct FROM points WHERE run_id=? ORDER BY rowid', (int(run_id),))]
    except (sqlite3.Error, OSError):
        return []


# ------------------------------------------------------------------------------------------------------------ plan
def plan(run_id, db_path=None) -> Plan:
    """What 'Regenerate PDF' can do for an event: from the saved snapshot, rebuilt from history rows, or nothing (with the reason).
    A snapshot that fails its checksum is never replaced by a rebuild: the event is refused."""
    run = run_row(run_id, db_path)
    if run is None:
        return Plan(NONE, 'This history entry could not be read.', None, None, ())
    got = load(run_id, db_path)
    if got.status == OK:
        return Plan(SNAPSHOT, 'The report will be printed again from the record saved when it was issued.', got.data, run, ())
    if got.status != MISSING:
        return Plan(NONE, got.message, None, run, ())
    data, run, problem = rebuild_from_history(run_id, db_path)
    if data is None:
        return Plan(NONE, f'{MSG_MISSING} It cannot be rebuilt from the history either: {problem}', None, run, ())
    return Plan(REBUILT, 'There is no saved report record for this event (it was issued before report records were kept). The report can be rebuilt '
                         'from the test points stored in the history, but it will NOT be identical to the original: ' +
                         ', '.join(REBUILT_LACKS) + ' are not stored and are left out or blank. It is marked on every page as rebuilt.',
                data, run, REBUILT_LACKS)


def availability(run_id, db_path=None) -> tuple:
    """(kind, one short line) for the History tab, without writing anything."""
    p = plan(run_id, db_path)
    short = {SNAPSHOT: 'Saved report record found: the PDF can be regenerated.',
             REBUILT: 'No saved record (older event): can be rebuilt from history rows, not identical to the original.',
             NONE: 'Cannot regenerate: ' + p.message}[p.kind]
    return p.kind, short


# ------------------------------------------------------------------------------------------------------------ writing
def reprint_note(kind, now=None):
    """Footer line for a reprint: none for a reprint of the saved record (identical to the original);
    a rebuilt-from-history reprint is always marked."""
    stamp = (now or datetime.now()).strftime('%Y-%m-%d')
    if kind == REBUILT:
        return (f'REBUILT {stamp} from history rows, no original snapshot (As Left, uncertainty, TAR/TUR and modifications were not stored). '
                'Not the original report.')
    return None


def reprint_filename(asset, issued_at, ext='.pdf') -> str:
    """asset#-date, the same pattern as ui_theme.report_filename, with the ORIGINAL issue date."""
    import ui_theme_core as ui
    when = None
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            when = datetime.strptime(str(issued_at).strip(), fmt)
            break
        except ValueError:
            continue
    return ui.report_filename(asset, ext, when=when)


def write_report(data, path, kind, now=None):
    """Write the PDF for a snapshot / rebuilt dict through report_pdf.write_calibration_pdf (the same code as the original).  The history is not
    touched (record_history=False).  Written to a temporary file next to `path` and moved into place, so a failure never leaves half a file."""
    import report_pdf
    details = _restore(data['details'])
    tmp = str(path) + '.reprint.tmp'
    try:
        report_pdf.write_calibration_pdf(
            tmp, data['rows'], header=[tuple(x) for x in data['header']], title=data['title'], demo=False, details=details,
            footer_note=data.get('footer_note') or '', show_tar_tur=_restore(data.get('show_tar_tur')), modifications=data.get('modifications') or None,
            issued_at=data['issued_at'], reprint_note=reprint_note(kind, now), record_history=False)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def regenerate(run_id, *, choose_path, confirm_overwrite, confirm_rebuilt=None, now=None, db_path=None) -> Result:
    """The whole 'Regenerate PDF' action, with the questions injected so it runs without a window.

        choose_path(default_name, original_file) -> path or None (cancel)
        confirm_overwrite(path, is_original) -> bool    called when the chosen file already exists; False cancels (nothing is replaced silently)
        confirm_rebuilt(message) -> bool                called for an event without a snapshot, before anything is written

    Returns Result(ok, path, kind, message); message says why when ok is False (a cancel has an empty message).  Never raises."""
    try:
        pl = plan(run_id, db_path)
        if pl.kind == NONE:
            return Result(False, '', NONE, pl.message)
        if pl.kind == REBUILT and confirm_rebuilt is not None and not confirm_rebuilt(pl.message):
            return Result(False, '', REBUILT, '')
        asset = next((v for k, v in pl.data['header'] if k == 'Instrument ID'), '') or pl.run['asset_id']
        path = choose_path(reprint_filename(asset, pl.data['issued_at']), pl.run.get('report_file') or '')
        if not path:
            return Result(False, '', pl.kind, '')
        path = str(path)
        if os.path.exists(path):
            original = bool(pl.run.get('report_file')) and os.path.abspath(path) == os.path.abspath(pl.run['report_file'])
            if not confirm_overwrite(path, original):
                return Result(False, '', pl.kind, '')
        write_report(pl.data, path, pl.kind, now)
        return Result(True, path, pl.kind, 'Rebuilt from history rows (not the original report): ' + path if pl.kind == REBUILT
                      else 'Regenerated from the saved record: ' + path)
    except ImportError:
        return Result(False, '', NONE, 'Install the PDF package with:  py -m pip install reportlab')
    except Exception as exc:
        return Result(False, '', NONE, f'The PDF could not be written: {exc}')
