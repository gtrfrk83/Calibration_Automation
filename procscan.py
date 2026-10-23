"""Procedure discovery: the Manager finds its procedures by scanning Procedures/ for metadata sidecars.  Tk-free; no instrument I/O.

    import procscan
    result = procscan.scan()                      # ScanResult: .procs (registration order), .problems (sidecars that were skipped, with the reason)
    for p in result.procs: p.name, p.launcher_name, p.fingerprint_code ...
    procscan.legacy_tables(procs)                 # the old STABLE / VERSIONS dicts

Each procedure is a launcher `Procedures/<Id>.py` plus a sidecar `Procedures/<Id>.procedure.json` (the sidecar is a separate file on purpose:
editing the metadata never changes the launcher, so it never changes what a verified procedure's fingerprint was taken from).  A launcher
without a sidecar is simply not a registered procedure (for example `User_Datasheet.py`, the generic launcher of user-built datasheets).

Sidecar fields (schema 1):

    schema        1
    id            the launcher's file name without .py (also the key the verified-on-hardware records use, plus '.py')
    name, manufacturer, model, category (= the instrument class, e.g. 'Digital Multimeter'), description, version, order (position in the list)
    launcher      'Procedures/<id>.py'
    engine        shared engine modules it runs (information; the fingerprint list below is what counts)
    drivers       driver modules under drivers/ (information)
    specs         test point / limit files
    fingerprint   {'code': [...], 'spec': [...]}: EXACTLY the files whose change makes a verified procedure 'changed since verification'.
                  A spec entry 'specs/x.json#117' means only the part of that shared spec which model 117 uses (its model entry and the steps that list it);
                  a code entry 'hookups.py#fluke110' means hookups.py with the data of the other meters left out (see verified.py).
    hookup        {'meter': hookups.py meter key or null, 'diagram_prefixes': ['hook_fluke110', ...]}: which diagrams/ files belong to it
    seed_verified true for the procedures the lab owner has attested as verified on hardware (verified.SEED is derived from this), seed_order their order
    kind          optional, 'verification' or 'adjustment': which Manager tab lists the procedure.  Left out, it follows the category / name
                  (classify(): 'adjust' in the category or the display name = adjustment, everything else = verification).  Changes no behaviour of the procedure.
    own_files     the files that belong to this procedure alone (what tools/make_package.py ships; shared files are listed in fingerprint but
                  not shipped, the target suite must already have them)
    tests         optional list of test files

Nothing here is executed: a sidecar is data, read with json.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIDECAR_SUFFIX = '.procedure.json'
SCHEMA = 1
ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_\-]{0,80}$')
DEFAULT_ORDER = 1000
KIND_VERIFICATION = 'verification'
KIND_ADJUSTMENT = 'adjustment'
KINDS = (KIND_VERIFICATION, KIND_ADJUSTMENT)


def classify(name='', category='', kind='') -> str:
    """Which list a procedure belongs to: an explicit valid `kind` wins, else 'adjust...' in the category or the display name means adjustment,
    everything else is a performance verification.  Pure text rules; used by the Manager's two tabs."""
    k = str(kind or '').strip().lower()
    if k in KINDS:
        return k
    if re.search(r'adjust', f'{category} {name}', re.IGNORECASE):
        return KIND_ADJUSTMENT
    return KIND_VERIFICATION


class ScanProblem(ValueError):
    pass


def safe_rel(path) -> bool:
    """A plain relative path inside the suite: no drive, no leading slash, no '..', no backslash tricks, not empty."""
    if not isinstance(path, str) or not path or path != path.strip():
        return False
    if '\\' in path or path.startswith('/') or re.match(r'^[A-Za-z]:', path) or '\x00' in path:
        return False
    parts = path.split('/')
    return all(p not in ('', '.', '..') for p in parts)


def split_label(label: str):
    """'specs/x.json#117' -> ('specs/x.json', '117'); 'specs/x.json' -> ('specs/x.json', '')."""
    path, _, part = str(label).partition('#')
    return path, part


@dataclass(frozen=True)
class Proc:
    id: str
    name: str
    manufacturer: str = ''
    model: str = ''
    category: str = ''
    description: str = ''
    version: str = ''
    order: int = DEFAULT_ORDER
    launcher: str = ''                                   # 'Procedures/<id>.py'
    engine: tuple = ()
    drivers: tuple = ()
    specs: tuple = ()
    fingerprint_code: tuple = ()
    fingerprint_spec: tuple = ()
    hookup_meter: str = ''
    diagram_prefixes: tuple = ()
    seed_verified: bool = False
    seed_order: int = DEFAULT_ORDER
    own_files: tuple = ()
    tests: tuple = ()
    sidecar: str = ''                                    # 'Procedures/<id>.procedure.json'
    kind: str = ''                                       # '' (derive, see classify), 'verification' or 'adjustment'

    @property
    def effective_kind(self) -> str:
        return classify(self.name, self.category, self.kind)

    @property
    def launcher_name(self) -> str:
        return self.launcher.rsplit('/', 1)[-1]

    @property
    def key(self) -> str:
        """The verified-on-hardware key: the launcher file name."""
        return self.launcher_name

    @property
    def registration(self) -> tuple:
        """The tuple the Manager used to list by hand: (name, manufacturer, model, category, launcher file name)."""
        return (self.name, self.manufacturer, self.model, self.category, self.launcher_name)

    def files(self) -> dict:
        """{'code': [...], 'spec': [...]} as verified.FILES held them (labels, possibly with a '#part')."""
        return {'code': list(self.fingerprint_code), 'spec': list(self.fingerprint_spec)}


@dataclass
class ScanResult:
    procs: list = field(default_factory=list)
    problems: list = field(default_factory=list)        # [(sidecar file name, reason)]

    def by_key(self) -> dict:
        return {p.key: p for p in self.procs}


def _str_list(doc, key, problems_label, required=False):
    value = doc.get(key, [])
    if value is None:
        value = []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ScanProblem(f'"{key}" must be a list of text entries')
    if required and not value:
        raise ScanProblem(f'"{key}" is required')
    return tuple(value)


def parse_sidecar(doc, stem: str) -> Proc:
    """Validate one sidecar document (already loaded) belonging to Procedures/<stem>.procedure.json.  Raises ScanProblem."""
    if not isinstance(doc, dict):
        raise ScanProblem('not a JSON object')
    if doc.get('schema') != SCHEMA:
        raise ScanProblem(f'schema {doc.get("schema")!r} is not supported (this suite reads schema {SCHEMA})')
    pid = doc.get('id')
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise ScanProblem('"id" is missing or not a plain name')
    if pid != stem:
        raise ScanProblem(f'"id" ({pid}) must match the file name ({stem}{SIDECAR_SUFFIX})')
    name = doc.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ScanProblem('"name" is required')
    launcher = doc.get('launcher', f'Procedures/{pid}.py')
    if launcher != f'Procedures/{pid}.py':
        raise ScanProblem(f'"launcher" must be Procedures/{pid}.py')
    text = {}
    for k in ('manufacturer', 'model', 'category', 'description', 'version'):
        v = doc.get(k, '')
        if not isinstance(v, str):
            raise ScanProblem(f'"{k}" must be text')
        text[k] = v
    kind = doc.get('kind', '')
    if kind is None:
        kind = ''
    if not isinstance(kind, str) or kind not in ('', *KINDS):
        raise ScanProblem('"kind" must be "verification" or "adjustment" (or left out)')
    order = doc.get('order', DEFAULT_ORDER)
    seed_order = doc.get('seed_order', DEFAULT_ORDER)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (order, seed_order)):
        raise ScanProblem('"order" and "seed_order" must be whole numbers')
    fp = doc.get('fingerprint')
    if not isinstance(fp, dict):
        raise ScanProblem('"fingerprint" ({"code": [...], "spec": [...]}) is required')
    fp_code = _str_list(fp, 'code', 'fingerprint', required=True)
    fp_spec = _str_list(fp, 'spec', 'fingerprint')
    engine, drivers, specs = (_str_list(doc, k, k) for k in ('engine', 'drivers', 'specs'))
    own, tests = _str_list(doc, 'own_files', 'own_files'), _str_list(doc, 'tests', 'tests')
    hook = doc.get('hookup') or {}
    if not isinstance(hook, dict):
        raise ScanProblem('"hookup" must be an object')
    meter = hook.get('meter') or ''
    prefixes = tuple(hook.get('diagram_prefixes') or ())
    if not isinstance(meter, str) or not all(isinstance(x, str) and re.match(r'^[A-Za-z0-9_\-]+$', x) for x in prefixes):
        raise ScanProblem('"hookup" holds a meter name and diagram prefixes (plain names)')
    for label in (*engine, *specs, *fp_code, *fp_spec, *own, *tests, launcher):
        if not safe_rel(split_label(label)[0]):
            raise ScanProblem(f'unsafe file path {label!r}')
    for d in drivers:
        if not re.match(r'^[A-Za-z0-9_]+$', d):
            raise ScanProblem(f'unsafe driver name {d!r}')
    if f'Procedures/{pid}.py' not in fp_code:
        raise ScanProblem('the launcher must be in the fingerprint list')
    return Proc(id=pid, name=name.strip(), manufacturer=text['manufacturer'], model=text['model'], category=text['category'],
                description=text['description'], version=text['version'], order=order, launcher=launcher, engine=engine, drivers=tuple(drivers),
                specs=specs, fingerprint_code=fp_code, fingerprint_spec=fp_spec, hookup_meter=meter, diagram_prefixes=prefixes,
                seed_verified=bool(doc.get('seed_verified', False)), seed_order=int(doc.get('seed_order', DEFAULT_ORDER)), own_files=own, tests=tests, sidecar=f'Procedures/{stem}{SIDECAR_SUFFIX}', kind=kind)


def scan_folder(folder) -> ScanResult:
    """Read every sidecar in `folder` (a Procedures folder).  A bad sidecar is skipped and listed in .problems; it never stops the others."""
    folder = Path(folder)
    out = ScanResult()
    seen_id, seen_name = {}, {}
    try:
        files = sorted(folder.glob('*' + SIDECAR_SUFFIX), key=lambda p: p.name.casefold())
    except OSError:
        return out
    for path in files:
        stem = path.name[:-len(SIDECAR_SUFFIX)]
        try:
            doc = json.loads(path.read_text(encoding='utf-8-sig'))
            proc = parse_sidecar(doc, stem)
            if proc.id.casefold() in seen_id:
                raise ScanProblem(f'same id as {seen_id[proc.id.casefold()]}')
            if proc.name.casefold() in seen_name:
                raise ScanProblem(f'same display name as {seen_name[proc.name.casefold()]}')
        except (OSError, ValueError) as ex:                                # ScanProblem and json errors are ValueErrors
            out.problems.append((path.name, str(ex)))
            continue
        seen_id[proc.id.casefold()] = path.name
        seen_name[proc.name.casefold()] = path.name
        out.procs.append(proc)
    out.procs.sort(key=lambda p: (p.order, p.id.casefold()))
    return out


_CACHE = {}


def scan(base=None) -> ScanResult:
    """Scan <base>/Procedures (the suite folder by default).  Cached until a sidecar is added, removed or changed."""
    base = Path(base) if base else HERE
    folder = base / 'Procedures'
    try:
        sig = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(folder.glob('*' + SIDECAR_SUFFIX)))
    except OSError:
        sig = ()
    hit = _CACHE.get(str(folder))
    if hit and hit[0] == sig:
        return hit[1]
    result = scan_folder(folder)
    _CACHE[str(folder)] = (sig, result)
    return result


def procs(base=None) -> list:
    return scan(base).procs


def find(key, base=None):
    """The Proc whose launcher file name (or id) is `key`, else None."""
    k = str(key or '').casefold()
    for p in scan(base).procs:
        if p.launcher_name.casefold() == k or p.id.casefold() == k:
            return p
    return None


def legacy_tables(proc_list):
    """(STABLE, VERSIONS) in the shape the Manager always had: {name: launcher file}, {launcher file: version}."""
    return ({p.name: p.launcher_name for p in proc_list}, {p.launcher_name: p.version for p in proc_list if p.version})


def seed_list(proc_list) -> tuple:
    """The procedures the lab owner attested as verified on hardware, in the form verified.SEED holds them."""
    return tuple(dict(proc_key=p.launcher_name, name=p.name, model=p.model)
                 for p in sorted((p for p in proc_list if p.seed_verified), key=lambda p: (p.seed_order, p.order)))
