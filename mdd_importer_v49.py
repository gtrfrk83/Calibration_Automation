"""Read-only Cal Processor MDD parser and SQLite datasheet template storage.

The MDD contains other sections (commands, scripts, specifications). We retain the
original file as an archival copy and the complete test-point fields as JSON.
Importing never runs the embedded commands and never registers executable code.
"""
import csv
import hashlib
import io
import json
import shutil
import sqlite3
from pathlib import Path

MAX_FILE_SIZE = 30 * 1024 * 1024


def _decode(data):
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError('Unrecognized text encoding.')


def _section(lines, name):
    marker = '</' + name + '>'
    end = '<' + name + '/>'
    try:
        start = lines.index(marker) + 1
        stop = lines.index(end, start)
    except ValueError:
        raise ValueError('Missing or incomplete MDD section: ' + name)
    return lines[start:stop]


def _records(lines, section_name):
    part = _section(lines, section_name)
    if len(part) < 3:
        raise ValueError('Incomplete MDD table: ' + section_name)
    # MDD table: names, types, then data rows. Tab-delimited, not XML.
    header = next(csv.reader([part[0]], delimiter='\t'))
    rows = []
    for line in part[2:]:
        if not line.strip():
            continue
        values = next(csv.reader([line], delimiter='\t'))
        if len(values) != len(header):
            raise ValueError(f'Malformed {section_name} record: expected {len(header)} fields, got {len(values)}')
        rows.append(dict(zip(header, values)))
    return rows


def parse_mdd(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError('MDD file exceeds 30 MB import limit.')
    data = path.read_bytes()
    lines = _decode(data).splitlines()
    headers = _records(lines, 'Data Sheet Header')
    if len(headers) != 1 or headers[0].get('App_Name', '').strip() != 'Cal Processor':
        raise ValueError('This importer supports Cal Processor MDD datasheets only.')
    raw_points = _records(lines, 'Test Points')
    points = []
    for raw in raw_points:
        # Header rows and layout records are not actual test points.
        if raw.get('IsHeaderRow', '0') == '1' or raw.get('TP_ID', '') in ('', '0'):
            continue
        points.append(raw)
    if not points:
        raise ValueError('No measurement test points found.')
    return {'header': headers[0], 'points': points, 'sha256': hashlib.sha256(data).hexdigest(),
            'source_path': str(path.resolve()), 'raw_bytes': data}


def init_datasheet_db(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS datasheet_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_sha256 TEXT NOT NULL UNIQUE,
        source_filename TEXT NOT NULL,
        archive_filename TEXT NOT NULL,
        app_version TEXT NOT NULL DEFAULT '',
        manufacturer TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        procedure_name TEXT NOT NULL DEFAULT '',
        cal_interval TEXT NOT NULL DEFAULT '',
        test_count INTEGER NOT NULL,
        metadata_json TEXT NOT NULL,
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS datasheet_test_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL REFERENCES datasheet_templates(id) ON DELETE CASCADE,
        point_order INTEGER NOT NULL,
        tp_id TEXT NOT NULL,
        page_number TEXT NOT NULL DEFAULT '',
        function_text TEXT NOT NULL DEFAULT '',
        nominal_text TEXT NOT NULL DEFAULT '',
        tolerance_text TEXT NOT NULL DEFAULT '',
        spec_text TEXT NOT NULL DEFAULT '',
        as_found_text TEXT NOT NULL DEFAULT '',
        as_left_text TEXT NOT NULL DEFAULT '',
        oot_text TEXT NOT NULL DEFAULT '',
        tol_low_text TEXT NOT NULL DEFAULT '',
        tol_high_text TEXT NOT NULL DEFAULT '',
        original_fields_json TEXT NOT NULL,
        UNIQUE(template_id, point_order)
    )''')


def import_mdd(db_path, path):
    parsed = parse_mdd(path)
    sha = parsed['sha256']
    db_path = Path(db_path)
    archive_dir = db_path.parent / 'mdd_archive'
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / (sha + '.MDD')
    # Immutable archive, named by checksum to prevent collision and overwrites.
    if archive_path.exists():
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != sha:
            raise ValueError('Existing archive checksum mismatch; import aborted.')
    else:
        archive_path.write_bytes(parsed['raw_bytes'])
    h = parsed['header']
    with sqlite3.connect(db_path) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        init_datasheet_db(conn)
        old = conn.execute('SELECT id FROM datasheet_templates WHERE file_sha256=?', (sha,)).fetchone()
        if old:
            return old[0], False, len(parsed['points'])
        cursor = conn.execute('''INSERT INTO datasheet_templates
            (file_sha256,source_filename,archive_filename,app_version,manufacturer,model,description,
             procedure_name,cal_interval,test_count,metadata_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (sha, Path(path).name, str(archive_path.relative_to(db_path.parent)),
             h.get('App_Version','').strip(), h.get('Manufacturer','').strip(),
             h.get('Model','').strip(),h.get('Description','').strip(),
             h.get('Procedure_Name','').strip(),h.get('CalInterval','').strip(),
             len(parsed['points']), json.dumps(h,ensure_ascii=False)))
        tid = cursor.lastrowid
        for n,p in enumerate(parsed['points'],1):
            conn.execute('''INSERT INTO datasheet_test_points
                (template_id,point_order,tp_id,page_number,function_text,nominal_text,tolerance_text,
                 spec_text,as_found_text,as_left_text,oot_text,tol_low_text,tol_high_text,original_fields_json)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (tid,n,p.get('TP_ID',''),p.get('DS_PageNo',''),p.get('Text_Function',''),
                 p.get('Text_Nominal',''),p.get('Text_Tolerance',''),p.get('Text_SpecStatement',''),
                 p.get('Text_AsFound',''),p.get('Text_AsLeft',''),p.get('Text_OutOfTol',''),
                 p.get('Tol_Low',''),p.get('Tol_High',''),json.dumps(p,ensure_ascii=False)))
    return tid, True, len(parsed['points'])
