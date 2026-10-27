"""Embedded Procedure Generator: the toolkit-free model (no Qt, no network, no instrument I/O).

A technician (or the owner) uploads a manufacturer manual, picks the pages of the performance-verification tables, lets Claude read the page IMAGES into
candidate rows, reviews every row against the page image, and the program builds a runnable procedure from the accepted rows.  This module holds everything
that is not a window and not the network:

    MODES / MODE_INFO            the three ways a procedure can be automated, and what each one needs
    Project, FileRec, Row        the project (JSON serialisable); Row = one candidate test point
    Store                        projects on disk: files under <data folder>/generator/<project id>/, state in lab_registry.sqlite3 (table generator_projects)
    requirements(project)        the checklist for the chosen mode -> [Requirement(key, label, met, hint)]
    gate(project)                what the Build button says (disabled text naming exactly what is missing)
    validate_row(row)            flags: reversed limits, unit / kind mismatch, impossible values ...  (Decimal, never float)
    unverified_list(project)     everything the owner must still confirm, carried into the built procedure

What it does NOT do: call the API (procedure_generator_ai.py), build the procedure (procedure_generator_build.py), mark drafts (generated_draft.py).

Storage rules (NOTES.md 'Procedure Generator'): files are COPIED into the project folder, hashed with SHA-256 and never altered; the originals are never touched;
new tables go in lab_registry.sqlite3 only (calibration_procedures.sqlite3 is never opened here).  Every number is Decimal; scaling is display-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import appdata
import datasheet_builder as db

# ============================================================================================================== modes
MANUAL, ONEWAY, TWOWAY = 'manual', 'oneway', 'twoway'
MODES = (MANUAL, ONEWAY, TWOWAY)
ROLE_SPEC, ROLE_PROG, ROLE_PHOTO = 'spec', 'programming', 'photo'
ROLES = (ROLE_SPEC, ROLE_PROG, ROLE_PHOTO)

MODE_INFO = {
    MANUAL: dict(title='Manual data entry', tag='No automation at all',
                 summary='You set the stimulus with your own standards and type every reading. The program only holds the points, judges the readings and writes the report.',
                 needs=('Spec sheet or manual (PDF)',)),
    ONEWAY: dict(title='One-way automation', tag='Calibrator driven, readings typed',
                 summary='The unit under test cannot be communicated with. The program drives the calibrator or standards; you type what the unit shows.',
                 needs=('Spec sheet or manual (PDF)',)),
    TWOWAY: dict(title='Two-way automation', tag='Standards driven, readings read back',
                 summary='The program drives the standards and also reads the unit under test. Needs a programming manual for every instrument used and a hook-up photo.',
                 needs=('Spec sheet or manual (PDF)', 'Programming manual (PDF) for EACH instrument used', 'Hook-up photo (PNG or JPG)')),
}
TWOWAY_COMING = ('Two-way generation is coming. The project, its requirements and its uploaded files are saved; this release builds Manual and One-way procedures only.')

SPEC_EXT, PHOTO_EXT = ('.pdf',), ('.png', '.jpg', '.jpeg')
MAX_FILE_BYTES = 300 * 1024 * 1024
MAX_NAME = 120
STATUS_CANDIDATE, STATUS_ACCEPTED, STATUS_EDITED, STATUS_REJECTED = 'candidate', 'accepted', 'edited', 'rejected'
STATUSES = (STATUS_CANDIDATE, STATUS_ACCEPTED, STATUS_EDITED, STATUS_REJECTED)
IN_PROCEDURE = (STATUS_ACCEPTED, STATUS_EDITED)
THERMOCOUPLES = tuple('BCDEJKLNRSTU')

# function kinds the generator offers (the Datasheet Builder kinds that make sense for a manual's verification table)
GEN_KINDS = tuple(k for k, v in db.KINDS.items() if v['family'] in ('dmm', 'light', 'scope', 'generator'))

# ============================================================================================================== model
def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


@dataclass
class FileRec:
    id: str
    role: str
    name: str                      # the stored file name inside the project's files/ folder
    original: str                  # the name the person's file had
    size: int
    sha256: str
    pages: int = 0                 # PDF pages (0 = could not be counted); a photo is 1
    instrument: str = ''           # programming manual: the instrument id it belongs to
    added: str = ''

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(d['id'], d['role'], d['name'], d.get('original', d['name']), int(d.get('size', 0)), d.get('sha256', ''), int(d.get('pages', 0)),
                   d.get('instrument', ''), d.get('added', ''))


@dataclass
class Instrument:
    id: str
    name: str
    role: str = 'standard'         # 'uut' | 'standard'

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(d['id'], d.get('name', ''), d.get('role', 'standard'))


ROW_FIELDS = ('step', 'function', 'section', 'range', 'nominal', 'frequency', 'level', 'low', 'high', 'accuracy', 'tc_type')


@dataclass
class Row:
    """One candidate test point.  Quantities are TEXT with their unit ('10 mV', '1 kHz'): scaled only by parse_quantity (Decimal), never by float."""
    id: str
    file_id: str = ''
    page: int = 0
    step: str = ''
    function: str = ''             # a datasheet_builder.KINDS key
    section: str = ''
    range: str = ''
    nominal: str = ''
    frequency: str = ''
    level: str = ''
    low: str = ''
    high: str = ''
    accuracy: str = ''             # the printed accuracy statement, used only when no limits are printed
    tc_type: str = ''
    uncertain: bool = False        # the model marked it uncertain
    note: str = ''                 # the model's confidence note
    source: str = 'model'          # 'model' | 'typed'
    status: str = STATUS_CANDIDATE
    model_values: dict = field(default_factory=dict)      # what the model returned (kept for audit once a row is edited)

    def values(self) -> dict:
        return {k: getattr(self, k) for k in ROW_FIELDS}

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        r = cls(d['id'])
        for k in cls.__dataclass_fields__:
            if k in d and k != 'id':
                setattr(r, k, d[k])
        r.page = int(r.page or 0)
        r.uncertain = bool(r.uncertain)
        r.model_values = dict(r.model_values or {})
        return r


@dataclass
class Project:
    id: str
    name: str = ''
    make: str = ''
    model: str = ''                # instrument model(s) the procedure is for (free text)
    mode: str = ''
    created: str = ''
    updated: str = ''
    who: str = ''
    instruments: list = field(default_factory=list)       # [Instrument]: two-way lists every instrument used
    files: list = field(default_factory=list)             # [FileRec]
    pages: dict = field(default_factory=dict)             # {file id: [first, last]}  the pages of the verification tables
    rows: list = field(default_factory=list)              # [Row]
    checked: list = field(default_factory=list)           # ['<file id>:<page>'] pages whose numbers the reviewer confirmed against the image
    extraction: dict = field(default_factory=dict)        # {model, at, pages, rows, usage, error}
    build: dict = field(default_factory=dict)             # {uid, version, at, points, standard, source_files}
    standard: str = ''             # the standard the uncertainty is taken from ('' = chosen by the builder)

    # ---- lookups
    def file(self, fid):
        return next((f for f in self.files if f.id == fid), None)

    def files_of(self, role):
        return [f for f in self.files if f.role == role]

    def instrument(self, iid):
        return next((i for i in self.instruments if i.id == iid), None)

    def row(self, rid):
        return next((r for r in self.rows if r.id == rid), None)

    def to_dict(self):
        d = {k: getattr(self, k) for k in ('id', 'name', 'make', 'model', 'mode', 'created', 'updated', 'who', 'pages', 'checked', 'extraction', 'build', 'standard')}
        d['instruments'] = [i.to_dict() for i in self.instruments]
        d['files'] = [f.to_dict() for f in self.files]
        d['rows'] = [r.to_dict() for r in self.rows]
        return d

    @classmethod
    def from_dict(cls, d):
        p = cls(d['id'])
        for k in ('name', 'make', 'model', 'mode', 'created', 'updated', 'who', 'standard'):
            setattr(p, k, d.get(k, ''))
        p.pages = {k: list(v) for k, v in (d.get('pages') or {}).items()}
        p.checked = list(d.get('checked') or [])
        p.extraction = dict(d.get('extraction') or {})
        p.build = dict(d.get('build') or {})
        p.instruments = [Instrument.from_dict(x) for x in d.get('instruments') or []]
        p.files = [FileRec.from_dict(x) for x in d.get('files') or []]
        p.rows = [Row.from_dict(x) for x in d.get('rows') or []]
        return p


# ============================================================================================================== requirements and the Build gate
@dataclass
class Requirement:
    key: str
    label: str
    met: bool
    hint: str = ''


def requirements(p: Project) -> list:
    """The checklist for the chosen mode.  Manual and One-way need a spec sheet or manual; Two-way also needs a programming manual for EACH instrument used and a
    hook-up photo.  Nothing is required before a mode is chosen except the mode itself."""
    out = [Requirement('name', 'Project name', bool(p.name.strip()), 'Give the project a name.'),
           Requirement('model', 'Instrument make and model(s)', bool(p.model.strip()), 'Type the model(s) the procedure is for.'),
           Requirement('mode', 'Choose how the procedure is automated', p.mode in MODES, 'Pick Manual entry, One-way or Two-way automation.')]
    if p.mode not in MODES:
        return out
    out.append(Requirement('spec', 'Spec sheet or manual (PDF), at least one', bool(p.files_of(ROLE_SPEC)), 'Drop or browse for the manufacturer\'s manual or spec sheet.'))
    if p.mode == TWOWAY:
        out.append(Requirement('instruments', 'List every instrument used (the unit under test and each standard)', len(p.instruments) >= 1, 'Add the instruments with "Add instrument".'))
        for ins in p.instruments:
            have = any(f.instrument == ins.id for f in p.files_of(ROLE_PROG))
            out.append(Requirement(f'prog:{ins.id}', f'Programming manual (PDF) for {ins.name or "(unnamed instrument)"}', have,
                                   f'Upload the programming manual of {ins.name or "this instrument"}.'))
        out.append(Requirement('photo', 'Hook-up photo (PNG or JPG)', bool(p.files_of(ROLE_PHOTO)), 'Upload a photo of the hook-up.'))
    return out


def missing(p: Project) -> list:
    return [r for r in requirements(p) if not r.met]


@dataclass
class Gate:
    can_click: bool
    text: str                      # the button's caption / the line under it
    stage: str                     # 'requirements' | 'coming' | 'pages' | 'rows' | 'undecided' | 'errors' | 'unchecked' | 'ready'
    items: list = field(default_factory=list)


def in_procedure(p: Project) -> list:
    return [r for r in p.rows if r.status in IN_PROCEDURE]


def row_page_key(r: Row) -> str:
    return f'{r.file_id}:{r.page}'


def unchecked_pages(p: Project) -> list:
    """Pages that have an accepted / edited row whose numbers were not confirmed against the page image."""
    need = sorted({row_page_key(r) for r in in_procedure(p)})
    return [k for k in need if k not in set(p.checked)]


def gate(p: Project) -> Gate:
    """What the Build button says.  Disabled with the exact list of what is missing, in the order the person works."""
    miss = missing(p)
    if miss:
        return Gate(False, 'Build is waiting for: ' + '; '.join(r.label for r in miss) + '.', 'requirements', [r.label for r in miss])
    if p.mode == TWOWAY:
        return Gate(True, 'Build: two-way generation is coming (the project stays saved).', 'coming')
    if not p.pages:
        return Gate(False, 'Choose the pages of the verification tables (Tables and review), then read them.', 'pages')
    if not p.rows:
        return Gate(False, 'No test points yet: read the pages with Claude or add rows by hand.', 'rows')
    undecided = [r for r in p.rows if r.status == STATUS_CANDIDATE]
    if undecided:
        return Gate(False, f'{len(undecided)} row(s) are not decided: accept, edit or reject every row.', 'undecided', [r.id for r in undecided])
    use = in_procedure(p)
    if not use:
        return Gate(False, 'Every row is rejected: accept at least one row.', 'rows')
    bad = [(r, f) for r in use for f in validate_row(r, p) if f.level == 'error']
    if bad:
        return Gate(False, f'{len(bad)} problem(s) must be fixed or the row rejected: ' + '; '.join(f'row {r.step or r.id}: {f.text}' for r, f in bad[:3]) + ('...' if len(bad) > 3 else ''),
                    'errors', [r.id for r, _f in bad])
    un = unchecked_pages(p)
    if un:
        pretty = ', '.join(f'p. {k.rsplit(":", 1)[1]}' for k in un)
        return Gate(False, f'Confirm the numbers against the page image: {pretty} not checked.', 'unchecked', un)
    return Gate(True, 'Build the procedure', 'ready')


# ============================================================================================================== validation (Decimal)
@dataclass
class Flag:
    level: str                     # 'error' (blocks the build until fixed or the row rejected) | 'warn' (carried into the unverified list)
    code: str
    text: str

    def __str__(self):
        return self.text


_NUMBER_ONLY = re.compile(r'^\s*[+-]?(?:\d+(?:[.,]\d*)?|[.]\d+)(?:[eE][+-]?\d+)?\s*$')
_TAIL = re.compile(r'\s*(rms|pk-pk|p-p|pp|peak|pk|dc|ac)\b\.?\s*$', re.I)
_MICRO = str.maketrans({'µ': 'u', 'μ': 'u'})


def norm_qty(text: str) -> str:
    """'10 mV rms' -> '10 mV'; 'Ω' kept; a micro sign is left to parse_quantity.  Only the trailing qualifier words go; the number and unit are untouched."""
    t = (text or '').strip().replace('−', '-').replace(' ', ' ')
    t = re.sub(r'(?<=\d),(?=\d{3}\b)', '', t)              # 1,000 V -> 1000 V (a thousands separator)
    prev = None
    while prev != t:
        prev, t = t, _TAIL.sub('', t)
    return t.strip()


def qty(text, unit):
    """(Decimal SI value, problem text or '') for a quantity text.  A bare number (no unit) is a problem for a kind that has a unit: a missing 'm' would be a 1000x error."""
    t = norm_qty(text)
    if not t:
        return None, 'empty'
    if unit and _NUMBER_ONLY.match(t):
        return None, 'has no unit'
    try:
        return db.parse_quantity(t, unit or None), ''
    except db.DsError as exc:
        return None, str(exc)


def _why_code(why: str, default: str) -> str:
    return 'unit_mismatch' if 'expected' in why else 'no_unit' if 'no unit' in why else default


def validate_row(r: Row, p: Project | None = None) -> list:
    """Flags for one row.  Pure: changes nothing, never guesses.  'error' = cannot be built; 'warn' = built but listed as unverified."""
    out: list = []

    def err(code, text):
        out.append(Flag('error', code, text))

    def warn(code, text):
        out.append(Flag('warn', code, text))
    kind = r.function
    if kind not in db.KINDS or kind not in GEN_KINDS:
        err('bad_kind', f'function "{kind}" is not one the Datasheet Builder knows')
        return out
    info = db.KINDS[kind]
    unit = info['unit']
    if not r.page:
        err('no_page', 'no source page: every row must point at the page it was read from')
    elif p is not None and r.file_id and not _page_selected(p, r.file_id, r.page):
        err('page_not_selected', f'page {r.page} is not one of the selected table pages')
    nominal = low = high = freq = level = None
    if info.get('passfail') or kind in ('CHECK',):
        pass
    else:
        if not r.nominal.strip():
            err('nominal', 'no nominal value')
        else:
            nominal, why = qty(r.nominal, unit)
            if why:
                err(_why_code(why, 'nominal'), f'nominal "{r.nominal}": {why}' + (f' (a {kind} row is in {db.unit_symbol(unit)})' if unit else ''))
                nominal = None
    for name in ('low', 'high'):
        txt = getattr(r, name)
        if txt.strip():
            v, why = qty(txt, unit)
            if why:
                err(_why_code(why, 'limit'), f'{name} limit "{txt}": {why}' + (f' (a {kind} row is in {db.unit_symbol(unit)})' if unit else ''))
            elif name == 'low':
                low = v
            else:
                high = v
    if bool(r.low.strip()) != bool(r.high.strip()):
        err('one_limit', 'only one limit is given: a test point needs both a low and a high limit (or the printed accuracy)')
    if low is not None and high is not None:
        if low > high:
            err('limits_reversed', f'the low limit {r.low} is above the high limit {r.high}')
        elif low == high:
            warn('limits_equal', 'the low and high limits are equal (zero tolerance)')
        if nominal is not None and not (low <= nominal <= high):
            warn('nominal_outside', 'the nominal is outside its own limits as read (check the row against the page)')
    elif not (r.low.strip() or r.high.strip()):
        if r.accuracy.strip():
            try:
                db.parse_expr(r.accuracy, unit or '')
                if re.search(r'count|digit|\bLSD\b', r.accuracy, re.I):
                    err('accuracy_counts', 'the accuracy is given in counts / digits and the resolution of the range is not known here: type the printed low and high limits instead')
                else:
                    warn('limits_from_accuracy', 'no limits printed: they will be calculated from the printed accuracy statement')
            except db.DsError as exc:
                err('accuracy_unreadable', f'no limits and the accuracy "{r.accuracy}" cannot be read ({exc})')
        elif not info.get('passfail'):
            err('no_limits', 'no limits and no accuracy statement: the row cannot be judged')
    if r.frequency.strip():
        freq, why = qty(r.frequency, 'Hz')
        if why:
            err('frequency', f'frequency "{r.frequency}": {why}')
        elif freq <= 0 and kind not in ('SCOPE_TIMEBASE',):
            err('frequency_value', 'a frequency must be above zero')
    elif info.get('ac') and kind not in ('SCOPE_TRIGGER',):
        warn('no_frequency', 'AC row without a frequency (none is invented)')
    if r.level.strip():
        level, why = qty(r.level, 'V')
        if why:
            err('level', f'level "{r.level}": {why}')
    elif info.get('amplitude') and kind in ('FREQ', 'PERIOD', 'GEN_FREQ'):
        warn('no_amplitude', 'frequency / period row without an input level (none is invented)')
    if r.range.strip():
        rv, why = qty(r.range, unit) if unit else (None, '')
        if why:
            warn('range', f'range "{r.range}" could not be read ({why}); the row is kept without a range')
    if nominal is not None:
        if kind in ('OHM2', 'OHM4', 'CAP', 'FREQ', 'PERIOD') and nominal < 0:
            err('negative', f'a {info["name"].lower()} value cannot be negative')
        if abs(nominal) > Decimal('1e12'):
            err('impossible', 'the nominal is impossibly large')
    if kind == 'TEMP':
        tc = r.tc_type.strip().upper()
        if tc and tc not in THERMOCOUPLES:
            err('tc_type', f'thermocouple type "{r.tc_type}" is not one of {", ".join(THERMOCOUPLES)}')
        elif not tc:
            warn('tc_missing', 'temperature row without a thermocouple type (choose how it is sourced before relying on its uncertainty)')
    if r.uncertain:
        warn('model_uncertain', 'the reader marked this row uncertain' + (f': {r.note}' if r.note else ''))
    if r.source == 'typed':
        warn('typed', 'typed by hand')
    if p is not None:
        key = (r.function, r.section, r.range, r.nominal, r.frequency, r.level, r.step)
        dup = [o for o in p.rows if o is not r and o.status != STATUS_REJECTED and (o.function, o.section, o.range, o.nominal, o.frequency, o.level, o.step) == key]
        if dup and r.status != STATUS_REJECTED:
            warn('duplicate', 'another row has the same function, range, nominal, frequency and step')
    return out


def _page_selected(p: Project, fid: str, page: int) -> bool:
    sel = p.pages.get(fid)
    return bool(sel) and sel[0] <= page <= sel[1]


def unverified_list(p: Project) -> list:
    """Everything the owner must still confirm, one line each: the flags of the rows in the procedure, rows the reader marked uncertain, hand-typed rows."""
    out = []
    for r in in_procedure(p):
        label = f'p. {r.page}' + (f' step {r.step}' if r.step else '') + f' {r.function} {r.nominal}'.rstrip()
        for f in validate_row(r, p):
            if f.level == 'warn':
                out.append(f'{label}: {f.text}')
        if r.status == STATUS_EDITED:
            out.append(f'{label}: edited after the reader returned it')
    return out


# ============================================================================================================== files: PDF pages, magic bytes
class UploadError(ValueError):
    """The upload was refused; the message is the plain reason shown to the person."""


def pdf_page_count(path) -> int:
    """Pages of a PDF: pypdfium2, else pypdf, else pdfinfo; 0 when none can tell."""
    path = str(path)
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        pass
    try:
        import pypdf
        return len(pypdf.PdfReader(path).pages)
    except Exception:
        pass
    try:
        out = subprocess.run(['pdfinfo', path], capture_output=True, text=True, timeout=30).stdout
        m = re.search(r'^Pages:\s+(\d+)', out, re.M)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def _sniff(head: bytes, role: str, ext: str) -> str:
    """'' when the first bytes fit the role, else the reason."""
    if role == ROLE_PHOTO:
        if head.startswith(b'\x89PNG\r\n\x1a\n') and ext == '.png':
            return ''
        if head.startswith(b'\xff\xd8\xff') and ext in ('.jpg', '.jpeg'):
            return ''
        return 'this is not a PNG or JPEG image (the file contents do not match its name)'
    return '' if head.lstrip(b'\x00').startswith(b'%PDF-') or b'%PDF-' in head[:1024] else 'this is not a PDF (the file contents do not match its name)'


def safe_name(name: str) -> str:
    n = re.sub(r'[^A-Za-z0-9._ -]', '_', Path(name).name).strip(' .') or 'file'
    return n[:MAX_NAME]


def sha256_file(path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(chunk), b''):
            h.update(block)
    return h.hexdigest()


def human_size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n} B' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n} B'


# ============================================================================================================== storage
SCHEMA = '''
CREATE TABLE IF NOT EXISTS generator_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT '',
    who TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    state_json TEXT NOT NULL DEFAULT '{}'
);
'''


class Store:
    """The projects on disk.  `root` = the folder of project files (default <data folder>/generator), `registry` = lab_registry.sqlite3 (default the user's).
    Both are resolved when first used, so a test that points CALSUITE_DATA elsewhere gets its own."""

    def __init__(self, root=None, registry=None):
        self._root, self._registry = root, registry

    @property
    def root(self) -> Path:
        r = Path(self._root) if self._root else appdata.data_dir() / 'generator'
        r.mkdir(parents=True, exist_ok=True)
        return r

    @property
    def registry(self) -> Path:
        return Path(self._registry) if self._registry else appdata.db_path('lab_registry.sqlite3')

    @contextmanager
    def _con(self):
        try:
            self.registry.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        con = sqlite3.connect(str(self.registry), timeout=5)
        try:
            con.executescript(SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()

    def folder(self, pid: str) -> Path:
        return self.root / pid

    def files_dir(self, pid: str) -> Path:
        d = self.folder(pid) / 'files'
        d.mkdir(parents=True, exist_ok=True)
        return d

    def pages_dir(self, pid: str, fid: str) -> Path:
        d = self.folder(pid) / 'pages' / fid
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- projects
    def create(self, name='', who='') -> Project:
        p = Project(id='gp-' + datetime.now().strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:8], name=name, created=_now(), updated=_now(), who=who)
        self.save(p)
        return p

    def save(self, p: Project) -> Project:
        """Write the project.  Saving the same state twice leaves the row (and the files) as they are; only `updated` changes when the content does."""
        text_now = json.dumps({**p.to_dict(), 'updated': ''}, sort_keys=True)
        with self._con() as con:
            row = con.execute('SELECT state_json FROM generator_projects WHERE id=?', (p.id,)).fetchone()
            if row is not None and json.dumps({**json.loads(row[0]), 'updated': ''}, sort_keys=True) == text_now:
                return p
            p.updated = _now()
            blob = json.dumps(p.to_dict(), sort_keys=True)
            con.execute('INSERT INTO generator_projects(id,name,mode,created,updated,who,state_json) VALUES(?,?,?,?,?,?,?) '
                        'ON CONFLICT(id) DO UPDATE SET name=excluded.name, mode=excluded.mode, updated=excluded.updated, state_json=excluded.state_json',
                        (p.id, p.name, p.mode, p.created, p.updated, p.who, blob))
        self.folder(p.id).mkdir(parents=True, exist_ok=True)
        return p

    def load(self, pid: str) -> Project | None:
        try:
            with self._con() as con:
                row = con.execute('SELECT state_json FROM generator_projects WHERE id=? AND deleted=0', (pid,)).fetchone()
            return Project.from_dict(json.loads(row[0])) if row else None
        except (sqlite3.Error, ValueError, KeyError):
            return None

    def list(self) -> list:
        """[(id, name, mode, updated)] newest first.  Never raises."""
        try:
            with self._con() as con:
                return [tuple(r) for r in con.execute('SELECT id,name,mode,updated FROM generator_projects WHERE deleted=0 ORDER BY updated DESC, id DESC')]
        except sqlite3.Error:
            return []

    def delete(self, pid: str) -> bool:
        """Soft delete: the row stays (flagged) and the files are kept; the project disappears from the list."""
        with self._con() as con:
            return con.execute('UPDATE generator_projects SET deleted=1 WHERE id=?', (pid,)).rowcount > 0

    # ---- files
    def add_file(self, p: Project, src, role: str, instrument: str = '') -> FileRec:
        """Copy `src` into the project, hash it and record it.  The source file is only read.  Raises UploadError with the reason."""
        src = Path(src)
        if role not in ROLES:
            raise UploadError(f'unknown kind of upload "{role}"')
        if not src.is_file():
            raise UploadError(f'{src.name}: the file cannot be read')
        ext = src.suffix.lower()
        allowed = PHOTO_EXT if role == ROLE_PHOTO else SPEC_EXT
        if ext not in allowed:
            raise UploadError(f'{src.name}: a {"hook-up photo" if role == ROLE_PHOTO else "manual or spec sheet"} must be {" or ".join(e.upper().lstrip(".") for e in allowed)}')
        if role == ROLE_PROG and not p.instrument(instrument):
            raise UploadError('choose the instrument this programming manual belongs to')
        size = src.stat().st_size
        if size == 0:
            raise UploadError(f'{src.name}: the file is empty')
        if size > MAX_FILE_BYTES:
            raise UploadError(f'{src.name}: the file is larger than {human_size(MAX_FILE_BYTES)}')
        with open(src, 'rb') as f:
            why = _sniff(f.read(1100), role, ext)
        if why:
            raise UploadError(f'{src.name}: {why}')
        fid = uuid.uuid4().hex[:10]
        dest_dir = self.files_dir(p.id)
        tmp = Path(tempfile.mkstemp(dir=dest_dir, suffix='.part')[1])
        h = hashlib.sha256()
        try:
            with open(src, 'rb') as a, open(tmp, 'wb') as b:
                for block in iter(lambda: a.read(1 << 20), b''):
                    h.update(block)
                    b.write(block)
            digest = h.hexdigest()
            for f in p.files:
                if f.sha256 == digest and f.role == role and f.instrument == instrument:
                    raise UploadError(f'{src.name}: this file is already in the project ({f.original})')
            name = f'{fid}_{safe_name(src.name)}'
            os.replace(tmp, dest_dir / name)
        finally:
            if tmp.exists():
                tmp.unlink()
        pages = pdf_page_count(dest_dir / name) if role != ROLE_PHOTO else 1
        rec = FileRec(fid, role, name, src.name, size, digest, pages, instrument, _now())
        p.files.append(rec)
        self.save(p)
        return rec

    def file_path(self, p: Project, fid: str) -> Path | None:
        f = p.file(fid)
        return self.files_dir(p.id) / f.name if f else None

    def remove_file(self, p: Project, fid: str) -> bool:
        """Remove an upload from the project (our copy only; the person's original is never touched).  Refused for a file a built procedure was made from."""
        f = p.file(fid)
        if f is None:
            return False
        if f.sha256 in (p.build.get('source_files') or {}).values():
            raise UploadError(f'{f.original} was used to build "{p.build.get("title", "a procedure")}" and stays in the project as its source')
        path = self.files_dir(p.id) / f.name
        p.files.remove(f)
        p.pages.pop(fid, None)
        p.rows = [r for r in p.rows if r.file_id != fid]
        p.checked = [k for k in p.checked if not k.startswith(fid + ':')]
        for k in (path, ):
            try:
                k.unlink()
            except OSError:
                pass
        shutil.rmtree(self.folder(p.id) / 'pages' / fid, ignore_errors=True)
        self.save(p)
        return True


# ============================================================================================================== editing helpers (the review grid calls these)
def new_row_id(p: Project) -> str:
    n = 1 + max([int(r.id[1:]) for r in p.rows if re.fullmatch(r'r\d+', r.id)] + [0])
    return f'r{n}'


def set_pages(p: Project, fid: str, first: int, last: int) -> list:
    """Choose the verification-table pages of one uploaded manual.  Rows read from other pages of this file are dropped from the project (they were not asked for)."""
    f = p.file(fid)
    if f is None or f.role != ROLE_SPEC:
        raise ValueError('choose pages of an uploaded spec sheet or manual')
    first, last = int(first), int(last)
    if first < 1 or last < first or (f.pages and last > f.pages):
        raise ValueError(f'the pages must be between 1 and {f.pages or "the last page"}, first not after last')
    p.pages[fid] = [first, last]
    p.rows = [r for r in p.rows if r.file_id != fid or first <= r.page <= last]
    p.checked = [k for k in p.checked if not k.startswith(fid + ':') or first <= int(k.rsplit(':', 1)[1]) <= last]
    return [first, last]


def add_rows(p: Project, rows: list, replace_model_rows_of=None) -> list:
    """Add candidate rows (the reader's, or typed).  `replace_model_rows_of` = (file id, first page, last page): earlier undecided reader rows of those pages are replaced
    by the new reading (decided rows are kept).  Returns the Row objects added."""
    if replace_model_rows_of:
        fid, a, b = replace_model_rows_of
        p.rows = [r for r in p.rows if not (r.file_id == fid and a <= r.page <= b and r.source == 'model' and r.status == STATUS_CANDIDATE)]
    added = []
    for r in rows:
        r.id = new_row_id(p)
        p.rows.append(r)
        added.append(r)
    return added


def edit_row(p: Project, rid: str, **values) -> Row:
    """Change a row's values.  A change to a row the model returned makes it 'edited' (the model's values stay in model_values); the page it sits on is no longer
    confirmed (the numbers have to be checked against the image again)."""
    r = p.row(rid)
    if r is None:
        raise KeyError(rid)
    changed = False
    for k, v in values.items():
        if k not in ROW_FIELDS and k not in ('page', 'file_id', 'note', 'uncertain'):
            raise KeyError(k)
        if getattr(r, k) != v:
            if r.source == 'model' and not r.model_values:
                r.model_values = {**r.values(), 'page': r.page}
            setattr(r, k, v)
            changed = True
    if changed:
        if r.source == 'model' and r.status in (STATUS_ACCEPTED, STATUS_EDITED, STATUS_CANDIDATE):
            r.status = STATUS_EDITED
        p.checked = [k for k in p.checked if k != row_page_key(r)]
    return r


def set_status(p: Project, rid: str, status: str) -> Row:
    if status not in STATUSES:
        raise ValueError(status)
    r = p.row(rid)
    if r is None:
        raise KeyError(rid)
    if status == STATUS_ACCEPTED and r.model_values and r.status == STATUS_EDITED:
        status = STATUS_EDITED                    # an edited row stays 'edited' when accepted again: the audit trail says it was changed
    r.status = status
    if status in IN_PROCEDURE:
        p.checked = [k for k in p.checked if k != row_page_key(r)]       # a newly accepted row needs its page confirmed (again)
    return r


def confirm_page(p: Project, fid: str, page: int, on: bool = True) -> None:
    key = f'{fid}:{int(page)}'
    if on and key not in p.checked:
        p.checked.append(key)
    elif not on and key in p.checked:
        p.checked.remove(key)
