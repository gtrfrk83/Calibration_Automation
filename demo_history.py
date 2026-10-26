"""Fictional Asset History for demonstrations (showing the suite to people).  UI-free; no instrument is touched.

    lab_registry_demo.sqlite3   a SEPARATE file in the data folder, next to (never inside) the real lab_registry.sqlite3

Rules (project: demo mode must never produce real-looking evidence):
  * The real registry is never opened here.  generate() refuses any file that is not named lab_registry_demo.sqlite3 and the real registry's own path.
  * Everything is fictional and says so: asset numbers DEMO-0001 ..., serial numbers DEMO-SN-..., technician 'Demo Technician', report names ending
    -DEMO.pdf, no standards listed, no report snapshot (so no PDF can be made from a demo event; see report_snapshot), no calibrator serials.
  * The Manager reads the file READ ONLY (labregistry._db(path) opens it with mode=ro); only generate() writes, to a temporary file that replaces the
    old demo file in one step.  Nothing a procedure records ever goes here: labregistry.DB is always the real file.
  * Same tables as the real registry (labregistry.SCHEMA: runs, points) so the Asset History tab, the drift chart and Next due behave as with real
    data, plus two demo-only tables: demo_marker (what the file is, the date its dates are counted back from) and demo_assets (the calibration
    interval of each demo asset; the Manager's instruments table is never consulted for them).
  * Deterministic: a fixed seed per asset.  Dates are counted back from `today` (default: today) so 'overdue' and 'due soon' stay true; with the same
    `today` the file has identical contents.  Every event is dated before `today`.
  * Limits are ILLUSTRATIVE, written for this demonstration; they are not any manufacturer's limits and no procedure uses them.
"""
from __future__ import annotations

import os
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import labregistry

DEMO_DB_NAME = labregistry.DEMO_DB_NAME
PREFIX = 'DEMO-'
BANNER = 'DEMONSTRATION DATA: fictional assets, not real calibration records'
PDF_REFUSAL = ('Not available for demonstration data. These fictional events are never turned into a PDF, so a demonstration report can not be '
               'mistaken for a calibration record.')
PDF_HINT = 'Demonstration events are never made into a PDF.'
TECHNICIAN = 'Demo Technician'
SEED = 20261025
MARKER_PURPOSE = 'DEMONSTRATION DATA: fictional assets, not real calibration records'

MARKER_SQL = '''
CREATE TABLE IF NOT EXISTS demo_marker (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS demo_assets (asset_id TEXT PRIMARY KEY COLLATE NOCASE, interval_months INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '');
'''

OHM = 'Ω'

# ---------------------------------------------------------------------------------------------------------------------------- point sets
# (section, description, nominal, +/- tolerance, unit, decimals).  Illustrative figures, see the module note.
BENCH_DMM = [
    ('DC Voltage', '100 mV DC', 100.0, 0.0060, 'mV', 4), ('DC Voltage', '1 V DC', 1.0, 0.000040, 'V', 6),
    ('DC Voltage', '10 V DC', 10.0, 0.00035, 'V', 5), ('DC Voltage', '100 V DC', 100.0, 0.0050, 'V', 4),
    ('DC Current', '10 mA DC', 10.0, 0.0030, 'mA', 4), ('DC Current', '100 mA DC', 100.0, 0.020, 'mA', 3),
    ('DC Current', '1 A DC', 1.0, 0.00040, 'A', 5),
    ('Resistance', f'100 {OHM}', 100.0, 0.0060, OHM, 4), ('Resistance', f'1 k{OHM}', 1.0, 0.000040, f'k{OHM}', 6),
    ('Resistance', f'10 k{OHM}', 10.0, 0.00040, f'k{OHM}', 5),
    ('AC Voltage', '1 V AC 1 kHz', 1.0, 0.00080, 'V', 5), ('AC Voltage', '10 V AC 1 kHz', 10.0, 0.0070, 'V', 4),
]
HANDHELD = [
    ('DC Voltage', '600 mV DC', 600.0, 0.5, 'mV', 1), ('DC Voltage', '6 V DC', 6.0, 0.004, 'V', 3), ('DC Voltage', '60 V DC', 60.0, 0.04, 'V', 2),
    ('AC Voltage', '6 V AC 60 Hz', 6.0, 0.022, 'V', 3), ('AC Voltage', '60 V AC 60 Hz', 60.0, 0.22, 'V', 2),
    ('DC Current', '60 mA DC', 60.0, 0.11, 'mA', 2), ('DC Current', '6 A DC', 6.0, 0.016, 'A', 3),
    ('Resistance', f'600 {OHM}', 600.0, 0.7, OHM, 1), ('Resistance', f'6 k{OHM}', 6.0, 0.004, f'k{OHM}', 3),
    ('Resistance', f'60 k{OHM}', 60.0, 0.04, f'k{OHM}', 2),
]
FGEN = [
    ('Frequency', '1 MHz', 1.0, 0.000001, 'MHz', 6), ('Frequency', '10 MHz', 10.0, 0.00001, 'MHz', 6),
    ('Amplitude', '100 mVpp 1 kHz', 100.0, 2.0, 'mVpp', 1), ('Amplitude', '1 Vpp 1 kHz', 1.0, 0.010, 'Vpp', 3),
    ('Amplitude', '5 Vpp 1 kHz', 5.0, 0.051, 'Vpp', 3),
    ('DC Offset', '0 V offset', 0.0, 0.0021, 'V', 4), ('DC Offset', '2.5 V offset', 2.5, 0.0071, 'V', 4),
    ('Flatness', '100 kHz relative to 1 kHz', 0.0, 0.10, 'dB', 2),
]
SCOPE = [
    ('DC Gain', '2 mV/div, 4 div', 8.0, 0.24, 'mV', 2), ('DC Gain', '10 mV/div, 4 div', 40.0, 1.2, 'mV', 1),
    ('DC Gain', '100 mV/div, 4 div', 400.0, 12.0, 'mV', 1), ('DC Gain', '1 V/div, 4 div', 4.0, 0.12, 'V', 3),
    ('Offset', 'Zero offset, 10 mV/div', 0.0, 2.0, 'mV', 1),
    ('Time Base', '1 ms/div, 1 kHz reference', 1.0, 0.00005, 'kHz', 5), ('Time Base', '10 MHz sample clock', 10.0, 0.0005, 'MHz', 4),
    ('Trigger', 'Trigger sensitivity, 50 MHz', 500.0, 50.0, 'mV', 1),
]

# ---------------------------------------------------------------------------------------------------------------------------- the assets
# days: how many days before `today` each event was; drift: {description: (dev % at the first event, change per event)} (in % of the tolerance, the
# unit the drift chart uses); fails: {(event index, description): dev %}, index -1 = the latest.  due: what the demonstration shows.
ASSETS = [
    dict(id='DEMO-0001', model='Fluke 87V', serial='DEMO-SN-87V-0001', proc='Fluke 87V performance verification', months=12, points=HANDHELD, scale=1.0,
         days=[1085, 720, 355, 150], drift={'600 mV DC': (8, 14)}, fails={}, note='4 reports, slow drift on 600 mV, current'),
    dict(id='DEMO-0002', model='Fluke 8846A', serial='DEMO-SN-8846-0002', proc='Fluke 8846A performance verification', months=12, points=BENCH_DMM, scale=1.0,
         days=[1040, 690, 346], drift={'10 V DC': (35, 24)}, fails={}, note='3 reports, 10 V DC drifting toward its limit, DUE SOON'),
    dict(id='DEMO-0003', model='Keysight 34401A', serial='DEMO-SN-34401-0003', proc='Keysight 34401A performance verification', months=12, points=BENCH_DMM,
         scale=1.4, days=[1090, 730, 455], drift={}, fails={}, note='3 reports, all in tolerance, OVERDUE'),
    dict(id='DEMO-0004', model='Fluke 8808A', serial='DEMO-SN-8808-0004', proc='Fluke 8808A performance verification', months=12, points=BENCH_DMM,
         scale=3.0, days=[1010, 650, 280], drift={}, fails={(-1, '10 V AC 1 kHz'): 112}, note='3 reports, latest has 1 point out of tolerance'),
    dict(id='DEMO-0005', model='Keithley 2000', serial='DEMO-SN-K2000-0005', proc='Keithley 2000 performance verification', months=24, points=BENCH_DMM,
         scale=3.0, days=[960, 230], drift={}, fails={}, note='2 reports, 24 month interval'),
    dict(id='DEMO-0006', model='Keysight 33220A', serial='DEMO-SN-33220-0006', proc='Keysight 33220A performance verification', months=12, points=FGEN,
         scale=1.0, days=[1060, 700, 330, 95], drift={'10 MHz': (-10, -17)}, fails={(1, '5 Vpp 1 kHz'): -108}, note='4 reports, an early failure, 10 MHz drifting'),
    dict(id='DEMO-0007', model='Tektronix TDS2000C', serial='DEMO-SN-TDS2-0007', proc='Tektronix TDS2000C performance verification', months=12, points=SCOPE,
         scale=1.0, days=[1030, 668, 301], drift={}, fails={}, note='3 reports, all in tolerance'),
    dict(id='DEMO-0008', model='Tektronix MDO4000C', serial='DEMO-SN-MDO4-0008', proc='Tektronix MDO4000C performance verification', months=12, points=SCOPE,
         scale=1.0, days=[1070, 905, 740, 560, 205], drift={'100 mV/div, 4 div': (5, 17)}, fails={}, note='5 reports, 100 mV/div gain drifting'),
    dict(id='DEMO-0009', model='Fluke 117', serial='DEMO-SN-117-0009', proc='Fluke 117 performance verification', months=12, points=HANDHELD, scale=1.0,
         days=[700, 320], drift={}, fails={}, note='2 reports, all in tolerance'),
    dict(id='DEMO-0010', model='Fluke 289', serial='DEMO-SN-289-0010', proc='Fluke 289 performance verification', months=12, points=HANDHELD, scale=1.0,
         days=[980, 610, 240], drift={'6 A DC': (30, 22)}, fails={(-1, '6 A DC'): 131}, note='3 reports, latest has 1 point out of tolerance'),
    dict(id='DEMO-0011', model='Keysight 34461A', serial='DEMO-SN-34461-0011', proc='Keysight 34461A performance verification', months=12, points=BENCH_DMM,
         scale=1.0, days=[1055, 800, 560, 340, 120], drift={f'100 {OHM}': (-12, 11)}, fails={}, note='5 reports, 100 ohm drifting slowly upward'),
    dict(id='DEMO-0012', model='Keysight 33210A', serial='DEMO-SN-33210-0012', proc='Keysight 33210A performance verification', months=24, points=FGEN,
         scale=1.0, days=[900, 175], drift={}, fails={}, note='2 reports, 24 month interval'),
]


# ---------------------------------------------------------------------------------------------------------------------------- paths and checks
def demo_path() -> Path:
    """lab_registry_demo.sqlite3 in the data folder (next to the real registry)."""
    import appdata
    return appdata.db_path(DEMO_DB_NAME)


def _same(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return os.path.abspath(a) == os.path.abspath(b)


def is_demo_db(path) -> bool:
    """True for a file named lab_registry_demo.sqlite3 or one that carries the demo_marker table.  Reads only; never raises."""
    if not path:
        return False
    if Path(str(path)).name.lower() == DEMO_DB_NAME:
        return True
    try:
        if not Path(path).is_file():
            return False
        con = sqlite3.connect(f'file:{Path(str(path)).as_posix()}?mode=ro', uri=True, timeout=3)
        try:
            return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_marker'").fetchone() is not None
        finally:
            con.close()
    except sqlite3.Error:
        return False


def verify(path=None):
    """(ok, reason).  The demo file is only shown when it carries the marker and every event belongs to a DEMO- asset of the demo technician."""
    path = Path(path or demo_path())
    if not path.is_file():
        return False, 'The demonstration history file does not exist.'
    try:
        con = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=3)
        try:
            marker = dict(con.execute('SELECT key,value FROM demo_marker').fetchall())
            if marker.get('purpose') != MARKER_PURPOSE:
                return False, 'The file is not marked as demonstration data.'
            n, bad = con.execute("SELECT COUNT(*), SUM(asset_id NOT LIKE 'DEMO-%' OR technician <> ?) FROM runs", (TECHNICIAN,)).fetchone()
            if not n:
                return False, 'The demonstration history is empty.'
            if bad:
                return False, 'The file holds an event that is not a demonstration event, so it is not shown.'
            return True, ''
        finally:
            con.close()
    except sqlite3.Error as exc:
        return False, f'The demonstration history cannot be read ({exc.__class__.__name__}).'


def anchor_of(path=None):
    """The date the file's dates were counted back from (ISO text), or ''."""
    try:
        con = sqlite3.connect(f'file:{Path(path or demo_path()).as_posix()}?mode=ro', uri=True, timeout=3)
        try:
            row = con.execute("SELECT value FROM demo_marker WHERE key='anchor'").fetchone()
        finally:
            con.close()
        return row[0] if row else ''
    except sqlite3.Error:
        return ''


# ---------------------------------------------------------------------------------------------------------------------------- building the data
def _fmt(value, dec):
    text = f'{value:.{dec}f}'
    return f'{0.0:.{dec}f}' if float(text) == 0 else text          # never '-0.000'


def _events(asset, today):
    """[(run_at datetime, rows)] oldest first; rows are in the dict form labregistry.record_run takes."""
    rng = random.Random(f'{SEED}-{asset["id"]}')
    out = []
    n_events = len(asset['days'])
    for k, ago in enumerate(asset['days']):
        when = datetime.combine(today - timedelta(days=ago), datetime.min.time()) + timedelta(hours=8 + rng.randrange(0, 8), minutes=rng.randrange(0, 60))
        rows = []
        for section, desc, nominal, tol, unit, dec in asset['points']:
            tol = tol * asset['scale']
            if desc in asset['drift']:
                start, step = asset['drift'][desc]
                dev = start + step * k + rng.uniform(-4, 4)
            else:
                dev = max(-55.0, min(55.0, rng.gauss(0, 22)))
            for (idx, d), forced in asset['fails'].items():
                if d == desc and (idx % n_events) == k:
                    dev = forced
            found = nominal + dev / 100.0 * tol
            low, high = nominal - tol, nominal + tol
            f_txt = _fmt(found, dec)
            oot = not (low <= float(f_txt) <= high)
            rows.append({'Section': section, 'Description': desc, 'Nominal': _fmt(nominal, dec), 'Tolerance -': _fmt(low, dec), 'Tolerance +': _fmt(high, dec),
                         'UOM': unit, 'As Found': f_txt, 'OOT': 'OOT' if oot else ''})
        out.append((when, rows, rng.choice(('22.5', '23.0', '23.4', '22.8')), rng.choice(('41', '44', '47', '50'))))
    return out


def generate(path=None, today=None) -> Path:
    """Write the demonstration registry.  Only a file named lab_registry_demo.sqlite3 that is not the real registry is accepted.  The new file is
    built beside the old one and moved into place, so a failure leaves the old file as it was.  Returns the path."""
    path = Path(path) if path else demo_path()
    if path.name.lower() != DEMO_DB_NAME:
        raise ValueError(f'refusing to write {path.name}: the demonstration history is always {DEMO_DB_NAME}')
    if _same(path, labregistry.DB):
        raise ValueError('refusing to write the real registry')
    today = today or date.today()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript(labregistry.SCHEMA)
        con.executescript(MARKER_SQL)
        con.executemany('INSERT INTO demo_marker VALUES(?,?)', [('purpose', MARKER_PURPOSE), ('anchor', today.isoformat()), ('seed', str(SEED)),
                                                               ('prefix', PREFIX)])
        for a in ASSETS:
            con.execute('INSERT INTO demo_assets VALUES(?,?,?)', (a['id'], a['months'], a['note']))
            for when, rows, temp, hum in _events(a, today):
                total = len(rows)
                failed = sum(1 for r in rows if r['OOT'])
                name = f'{a["id"]}-{when.strftime("%m-%d-%Y")}-DEMO.pdf'
                rid = con.execute(
                    'INSERT INTO runs(asset_id,serial,model,procedure,run_at,technician,temperature,humidity,total,failed,report_file,standards_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (a['id'], a['serial'], a['model'], a['proc'], when.isoformat(timespec='seconds'), TECHNICIAN, f'{temp} C', f'{hum} %', total, failed, name, '[]')).lastrowid
                con.executemany('INSERT INTO points VALUES(?,?,?,?,?,?,?,?,?,?)', [
                    (rid, r['Section'], r['Description'], r['Nominal'], r['Tolerance -'], r['Tolerance +'], r['UOM'], r['As Found'], 'FAIL' if r['OOT'] else 'PASS',
                     labregistry.deviation_pct(r['Nominal'], r['Tolerance -'], r['Tolerance +'], r['As Found'])) for r in rows])
        con.commit()
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(tmp, path)
    return path


def ensure(path=None, today=None):
    """The demonstration registry, created when missing and rebuilt when it is damaged, unmarked, or was counted back from another day (so Overdue
    and Due soon stay true).  Returns the path, or None when it could not be made."""
    path = Path(path) if path else demo_path()
    today = today or date.today()
    try:
        if path.is_file() and verify(path)[0] and anchor_of(path) == today.isoformat():
            return path
        return generate(path, today)
    except (OSError, ValueError, sqlite3.Error):
        return None
