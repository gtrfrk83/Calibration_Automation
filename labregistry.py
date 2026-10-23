"""Lab registry: per-asset calibration history (every exported PDF report, with its points) and drift.

Stored in its own SQLite file, lab_registry.sqlite3, next to the Manager.  The Manager's calibration_procedures.sqlite3 schema is never
changed; its 'instruments' table is only READ (serial number and calibration interval) when it exists.

    runs / points  one row per issued PDF report and its measured points (as-found, limits, % of tolerance used) for history and drift

Nothing here talks to an instrument, and no function raises on a damaged or missing file: callers get empty results instead.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
import appdata  # noqa: E402
DB = appdata.db_path('lab_registry.sqlite3')
MAIN_DB = appdata.db_path('calibration_procedures.sqlite3')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL COLLATE NOCASE,
    serial TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    procedure TEXT NOT NULL DEFAULT '',
    run_at TEXT NOT NULL,
    technician TEXT NOT NULL DEFAULT '',
    temperature TEXT NOT NULL DEFAULT '',
    humidity TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    report_file TEXT NOT NULL DEFAULT '',
    standards_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS runs_asset ON runs(asset_id, run_at);
CREATE TABLE IF NOT EXISTS points (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    section TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    nominal TEXT NOT NULL DEFAULT '',
    low TEXT NOT NULL DEFAULT '',
    high TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    found TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    dev_pct REAL
);
CREATE INDEX IF NOT EXISTS points_run ON points(run_id);
'''


@contextmanager
def _db(path=None):
    con = sqlite3.connect(str(path or DB), timeout=5)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------------------ dates
def parse_date(text):
    """'2027-03-01', '03/01/2027', '3/1/27' -> date, or None."""
    text = (text or '').strip()
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%Y/%m/%d', '%m-%d-%Y', '%d-%b-%Y', '%b %d, %Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def iso(text):
    d = parse_date(text)
    return d.isoformat() if d else (text or '').strip()


def add_months(d, months):
    y, m = divmod(d.year * 12 + d.month - 1 + int(months), 12)
    m += 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


# ------------------------------------------------------------------------------------------------------------ assets
def _num(text):
    m = re.search(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', (text or '').replace(',', '')) if text not in (None, '') else None
    return float(m.group()) if m else None


def deviation_pct(nominal, low, high, found):
    """How much of the tolerance the as-found error used, in %: 0 = on nominal, +-100 = at a limit. None when it cannot be told."""
    n, lo, hi, f = _num(nominal), _num(low), _num(high), _num(found)
    if None in (n, lo, hi, f):
        return None
    span = (hi - n) if f >= n else (n - lo)
    return None if span <= 0 else (f - n) / span * 100.0


def record_run(header, rows, details, report_file='', when=None):
    """Called by report_pdf after a PDF is written. Replaces an earlier record of the same file. Returns the run id or None."""
    head = dict(header or [])
    asset = (head.get('Instrument ID') or '').strip()
    if not asset or asset.upper() == 'NOT ENTERED' or not rows:
        return None
    details = details or {}
    total = len(rows)
    failed = sum(1 for r in rows if r.get('OOT'))
    try:
        with _db() as con:
            if report_file:
                for (old,) in con.execute('SELECT id FROM runs WHERE asset_id=? AND report_file=?', (asset, str(report_file))).fetchall():
                    con.execute('DELETE FROM runs WHERE id=?', (old,))
            rid = con.execute(
                'INSERT INTO runs(asset_id,serial,model,procedure,run_at,technician,temperature,humidity,total,failed,report_file,standards_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (asset, (head.get('Serial') or '').strip(), head.get('Instrument') or '', details.get('procedure') or '',
                 (when or datetime.now()).isoformat(timespec='seconds'), details.get('technician') or '', details.get('temperature') or '',
                 details.get('humidity') or '', total, failed, str(report_file), json.dumps(details.get('standards') or []))).lastrowid
            con.executemany('INSERT INTO points VALUES(?,?,?,?,?,?,?,?,?,?)', [
                (rid, r.get('Section') or '', r.get('Description') or '', r.get('Nominal') or '', r.get('Tolerance -') or '', r.get('Tolerance +') or '',
                 r.get('UOM') or '', r.get('As Found') or '', 'FAIL' if r.get('OOT') else 'PASS',
                 deviation_pct(r.get('Nominal'), r.get('Tolerance -'), r.get('Tolerance +'), r.get('As Found'))) for r in rows])
            return rid
    except sqlite3.Error:
        return None


def instrument_record(asset):
    """(serial, model, interval_months) from the Manager's instruments table, read-only; None if not registered."""
    if not asset or not MAIN_DB.exists():
        return None
    try:
        con = sqlite3.connect(f'file:{MAIN_DB.as_posix()}?mode=ro', uri=True, timeout=3)
        try:
            row = con.execute('SELECT serial_number,model,interval_months FROM instruments WHERE asset_id=?', (asset.strip(),)).fetchone()
        finally:
            con.close()
        return row
    except sqlite3.Error:
        return None


def runs_for(asset):
    try:
        with _db() as con:
            rows = con.execute('SELECT id,asset_id,serial,model,procedure,run_at,technician,total,failed,report_file FROM runs WHERE asset_id=? ORDER BY run_at DESC, id DESC',
                               (asset.strip(),)).fetchall()
    except sqlite3.Error:
        return []
    keys = ('id', 'asset_id', 'serial', 'model', 'procedure', 'run_at', 'technician', 'total', 'failed', 'report_file')
    return [dict(zip(keys, r)) for r in rows]


def points_for(run_id):
    try:
        with _db() as con:
            rows = con.execute('SELECT section,description,nominal,low,high,unit,found,result,dev_pct FROM points WHERE run_id=? ORDER BY rowid', (run_id,)).fetchall()
    except sqlite3.Error:
        return []
    keys = ('section', 'description', 'nominal', 'low', 'high', 'unit', 'found', 'result', 'dev_pct')
    return [dict(zip(keys, r)) for r in rows]


def assets_overview(term=''):
    """One row per asset that has history: latest run, run count, whether the latest run passed."""
    try:
        with _db() as con:
            rows = con.execute('''SELECT r.asset_id, r.serial, r.model, r.run_at, r.failed, r.total, r.procedure,
                                         (SELECT COUNT(*) FROM runs c WHERE c.asset_id=r.asset_id)
                                  FROM runs r WHERE r.id=(SELECT id FROM runs x WHERE x.asset_id=r.asset_id ORDER BY x.run_at DESC, x.id DESC LIMIT 1)
                                    AND (?='' OR r.asset_id LIKE ? OR r.serial LIKE ? OR r.model LIKE ?)
                                  ORDER BY r.asset_id''', (term, *(['%' + term + '%'] * 3))).fetchall()
    except sqlite3.Error:
        return []
    keys = ('asset_id', 'serial', 'model', 'last', 'failed', 'total', 'procedure', 'runs')
    return [dict(zip(keys, r)) for r in rows]


def next_due(asset):
    """(date or None, interval_months or None): last report date + the interval stored for the instrument."""
    rec = instrument_record(asset)
    runs = runs_for(asset)
    if not rec or not rec[2] or not runs:
        return None, (rec[2] if rec else None)
    last = parse_date(runs[0]['run_at'][:10])
    return (add_months(last, rec[2]) if last else None), rec[2]


def drift(asset, section, description):
    """Oldest-first [(run_at, found text, dev_pct)] for one test point of an asset."""
    try:
        with _db() as con:
            rows = con.execute('''SELECT r.run_at,p.found,p.dev_pct FROM points p JOIN runs r ON r.id=p.run_id
                                  WHERE r.asset_id=? AND p.section=? AND p.description=? ORDER BY r.run_at, r.id''', (asset.strip(), section, description)).fetchall()
    except sqlite3.Error:
        return []
    return rows


def asset_summary(asset):
    """One-line status for the technician after the Instrument ID is typed; '' when the asset has no history and is not registered."""
    asset = (asset or '').strip()
    if not asset:
        return ''
    runs = runs_for(asset)
    due, _interval = next_due(asset)
    if not runs:
        return f'{asset}: no calibration history on this computer.' if instrument_record(asset) else ''
    last = runs[0]
    verdict = 'OUT OF TOLERANCE' if last['failed'] else 'PASS'
    text = f'{asset}: last report {last["run_at"][:10]} ({verdict}, {last["total"]} points), {len(runs)} report(s) on file'
    if due:
        left = (due - date.today()).days
        text += f'; next due {due.isoformat()}' + (f' (OVERDUE by {-left} days)' if left < 0 else f' (in {left} days)')
    return text + '.'


# ------------------------------------------------------------------------------------------------------------ procedure hook
def attach(root, asset_var, serial_var, notify):
    """One call from a procedure window's __init__.

    * `--asset <ID>` on the command line pre-fills the Instrument ID (nothing in the Manager passes it any more since the Instruments tab was removed)
    * typing an Instrument ID (after a short pause) fills an empty Serial number from the instrument list / last report and shows a one-line history
    `notify` is a callable taking one string (e.g. status_var.set).  Never raises."""
    try:
        if '--asset' in sys.argv:
            value = sys.argv[sys.argv.index('--asset') + 1]
            if value and not value.startswith('--'):
                asset_var.set(value)
    except Exception:
        pass
    state = {'job': None, 'last': None}

    def look():
        state['job'] = None
        asset = asset_var.get().strip()
        if asset == state['last']:
            return
        state['last'] = asset
        try:
            if serial_var is not None and asset and not serial_var.get().strip():
                rec = instrument_record(asset)
                serial = (rec[0] if rec and rec[0] else '') or next((r['serial'] for r in runs_for(asset) if r['serial']), '')
                if serial:
                    serial_var.set(serial)
            text = asset_summary(asset)
            if text:
                notify(text)
        except Exception:
            pass

    def changed(*_):
        try:
            if state['job']:
                root.after_cancel(state['job'])
            state['job'] = root.after(700, look)
        except Exception:
            pass

    try:
        asset_var.trace_add('write', changed)
        if asset_var.get().strip():
            changed()
    except Exception:
        return
