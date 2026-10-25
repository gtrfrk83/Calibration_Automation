"""Find instruments: which VISA resource (GPIB adapter channel, USB, LAN) each instrument is on.  Tk-free; the window is instrument_scan_ui.py.

Why: the resource name differs from technician to technician (GPIB0::22 on one PC, GPIB1::22 on another with a USB-GPIB adapter, a USB or LAN
address for a 34972A), so the suite asks the instruments instead of making the technician type the address.

What a scan does (read this before changing anything here):
  * The VISA resource list (pyvisa ResourceManager().list_resources()) is read.  Every GPIB / USB / TCPIP *INSTR* resource gets ONLY read-only
    identity queries, a short timeout and no device clear: '*IDN?' (SCPI instruments), then 'ID?' on GPIB (the 3458A speaks HP Multimeter Language
    and has no *IDN?).  `assert_read_only` refuses anything that is not a single query (must end with '?'), so no write, *RST or *CLS can leave this
    module.  A query that timed out is retried once (the LAST probe of a resource only); nothing else is ever retried.  No GTL / local is sent unless
    the technician asks for it (`go_local`), because a program window may still hold the instrument.
  * Serial ports (ASRL) are LISTED but never probed blind: a stray query can confuse a meter or a calibrator on RS-232.  A port is only checked when
    the technician names the instrument type for it, and then with that driver's own identity code (`serial_identity`: the driver's `identify()`,
    for the 8808A the prompt-tolerant one).  Nothing else is sent.
  * Nothing is connected for use.  Results are shown to the technician (instrument_scan_ui) and only an accepted result is remembered.
Memory: lab_registry.sqlite3, NEW table instrument_resources (per workstation and user).  calibration_procedures.sqlite3 is not touched.  A remembered
resource is offered as a default only after a quick read-only identity check confirms it in this session (`default_resource`); adapters renumber.
"""
from __future__ import annotations

import getpass
import platform
import queue
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_TIMEOUT_MS = 2000          # one identity query; a GPIB instrument that is present answers in milliseconds
DEFAULT_OPEN_TIMEOUT_MS = 3000
GPIB_ADDRESSES = range(0, 31)      # primary addresses 0-30

# ------------------------------------------------------------------------------------------------------------ what may be sent
PROBES = {                          # per interface, in order.  Queries only.
    'GPIB': ('*IDN?', 'ID?'),
    'USB': ('*IDN?',),
    'TCPIP': ('*IDN?',),
}
PROBE_BUSES = tuple(PROBES)
_FORBIDDEN = re.compile(r'\*(RST|CLS|SAV|RCL|TRG|PSC|SRE|ESE|OPC(?!\?))|;|\n|\r', re.I)


class ReadOnlyError(ValueError):
    """Something that is not a single query was about to be sent."""


def assert_read_only(text):
    """Return `text` when it is one read-only query; raise ReadOnlyError otherwise.  Every wire access of the scan goes through this."""
    t = str(text).strip()
    if not t or not t.endswith('?') or _FORBIDDEN.search(t):
        raise ReadOnlyError(f'refusing to send {text!r}: the scan sends single read-only queries only')
    return t


# ------------------------------------------------------------------------------------------------------------ the models the suite has procedures for
@dataclass(frozen=True)
class Family:
    key: str                  # the model key shown to the technician and stored in the registry
    label: str
    model_re: str             # against the model field of the reply, upper case, spaces removed
    driver: str = ''          # class name in drivers/ (used for the explicit serial check)
    probe: str = '*IDN?'      # the query this family answers
    serial_ok: bool = False   # can be checked on RS-232 with the driver's identity code
    serial_attr: str = ''     # where the driver's serial settings live when the class has no SERIAL: 'module.NAME'
    source: str = ''          # where the reply form was read (UNVERIFIED when empty or 'assumed')


FAMILIES = (
    Family('5560A', 'Fluke 5560A calibrator', r'^5560A$', 'Fluke5560A', serial_ok=True, serial_attr='fluke_5560a.SERIAL_DEFAULT',
           source='assumed: FLUKE,5560A,<serial>,<fw> (driver IDN_MATCH 5560; the 5522A form, Operators Manual p. 6-19)'),
    Family('5522A', 'Fluke 5522A calibrator', r'^5522A$', 'Fluke5522A', serial_ok=True, serial_attr='fluke_5560a.SERIAL_DEFAULT',
           source='5522A Operators Manual p. 6-19: FLUKE,5522A,5248000,1.0+1.3+1.8'),
    Family('5520A', 'Fluke 5520A calibrator', r'^5520A$', 'Fluke5520A', serial_ok=True, serial_attr='fluke_5560a.SERIAL_DEFAULT',
           source='assumed: the 5522A form (only the 5520A Service Manual was supplied)'),
    Family('5502A', 'Fluke 5502A calibrator', r'^5502A$', 'Fluke5522A', serial_ok=True, serial_attr='fluke_5560a.SERIAL_DEFAULT',
           source='assumed: the 5522A form (driver IDN_MATCH 5502)'),
    Family('5500A', 'Fluke 5500A calibrator', r'^5500A(/COIL)?$', 'Fluke5522A', serial_ok=True, serial_attr='fluke_5560a.SERIAL_DEFAULT',
           source='assumed: the 5522A form (driver IDN_MATCH 5500)'),
    Family('5790B', 'Fluke 5790B AC measurement standard', r'^5790B$', 'Fluke5790B', serial_ok=True, serial_attr='fluke_5790b.SERIAL_DEFAULT',
           source='5790B Operators Manual p. 6-19: FLUKE,5790B,7649820, v1.08+v1.01 FPGAv4'),
    Family('8808A', 'Fluke 8808A multimeter', r'^8808A$', 'Fluke8808A', serial_ok=True,
           source='assumed: FLUKE,8808A,<serial>,<fw> (RS-232 only in this suite; the driver reads *IDN? prompt-tolerantly)'),
    Family('8846A', 'Fluke 8846A multimeter', r'^8846A$', 'Fluke8846A', serial_ok=True, source='assumed: FLUKE,8846A,<serial>,<fw> (driver IDN_MATCH 8846)'),
    Family('34401A', 'Agilent / HP 34401A multimeter', r'^34401A$', 'Agilent34401A', serial_ok=True,
           source='assumed: HEWLETT-PACKARD,34401A,0,<fw> (driver IDN_MATCH 34401)'),
    Family('34410A', 'Keysight 34410A multimeter', r'^34410A$', 'Keysight34410A', source='assumed: Agilent Technologies,34410A,<serial>,<fw> (simulator form)'),
    Family('34411A', 'Keysight 34411A multimeter', r'^34411A$', 'Keysight34411A', source='assumed: the 34410A form'),
    Family('34460A', 'Keysight 34460A multimeter', r'^34460A$', 'Keysight34460A', serial_ok=True, source='assumed: Keysight Technologies,34460A,<serial>,<fw>'),
    Family('34461A', 'Keysight 34461A multimeter', r'^34461A$', 'Keysight34461A', serial_ok=True, source='assumed: as the 34460A'),
    Family('34465A', 'Keysight 34465A multimeter', r'^34465A$', 'Keysight34465A', serial_ok=True, source='assumed: as the 34460A'),
    Family('34470A', 'Keysight 34470A multimeter', r'^34470A$', 'Keysight34470A', serial_ok=True, source='assumed: as the 34460A'),
    Family('34970A', 'Keysight 34970A data acquisition', r'^34970A$', 'Keysight34970A', serial_ok=True, source='assumed: Agilent Technologies,34970A,<serial>,<fw>'),
    Family('34972A', 'Keysight 34972A data acquisition', r'^34972A$', 'Keysight34972A', serial_ok=True, source='assumed: Agilent Technologies,34972A,<serial>,<fw>'),
    Family('33210A', 'Keysight 33210A function generator', r'^33210A$', 'Keysight33210A', source='assumed: Agilent Technologies,33210A,<serial>,<fw>'),
    Family('33220A', 'Agilent 33220A function generator', r'^33220A$', 'Keysight33220A', source='assumed: Agilent Technologies,33220A,<serial>,<fw>'),
    Family('33250A', 'Agilent 33250A function generator', r'^33250A$', 'Keysight33250A', source='assumed: Agilent Technologies,33250A,<serial>,<fw>'),
    Family('53131A', 'Agilent 53131A counter', r'^53131A$', 'Keysight53131A', source='53131A/53132A Programming Guide p. 4-130: HEWLETT-PACKARD, 53131A,0,XXXX'),
    Family('53132A', 'Agilent 53132A counter', r'^53132A$', 'Keysight53132A', source='53131A/53132A Programming Guide p. 4-130: HEWLETT-PACKARD, 53132A,0,XXXX'),
    Family('96270A', 'Fluke 96270A reference source', r'^96270A$', 'Fluke96270A', source='96270A manual p. 57: Fluke,96270A,<serial>,<firmware> (as the driver notes)'),
    Family('Keithley 2000', 'Keithley Model 2000 multimeter', r'^MODEL2000$', 'Keithley2000', serial_ok=True, serial_attr='keithley_2000.SERIAL_DEFAULT',
           source='Model 2000 User Manual form: KEITHLEY INSTRUMENTS INC.,MODEL 2000,0123456,A19  /A02 (as drivers/keithley_2000_cal.py)'),
    Family('3458A', 'Keysight / HP 3458A multimeter', r'^3458A$', 'Agilent3458A', probe='ID?',
           source='3458A User\'s Guide p. 276: ID? answers "Keysight 3458A" (older firmware "HP3458A"); no serial number in the reply'),
    Family('MDO4000C', 'Tektronix MDO4000C oscilloscope', r'^MDO4\d{3}C?$', 'TektronixMDO4000C', source='assumed: TEKTRONIX,MDO4104C,<serial>,CF:91.1CT FV:<fw>'),
    Family('TDS2000C', 'Tektronix TDS2000C / TDS1000C-EDU oscilloscope', r'^TDS\d{4}C(-EDU)?$', 'TektronixTDS2000C',
           source='assumed: TEKTRONIX,TDS 2024C,<serial>,CF:91.1CT FV:v24.00 (as drivers/tektronix_tds2000c.py)'),
    Family('TBS2000B', 'Tektronix TBS2000B oscilloscope', r'^TBS2(07|10|20)[24]B?$', 'TektronixTBS2000B',
           source='TBS2000B Programmer Manual 077-1149-04 p. 121: TEKTRONIX,TBS2104 ,CU10100,CF:91.1CT FV:<fw> (the example has no B; UNVERIFIED on a real unit)'),
    Family('WS4104HD', 'Teledyne LeCroy WaveSurfer 4104HD', r'^WS4\d{3}HD$', 'WaveSurfer4104HD',
           source='assumed: LECROY,WS4104HD,<serial>,<fw> (driver IDN_MATCH LECROY / TELEDYNE)'),
)
FAMILY = {f.key: f for f in FAMILIES}


def family_for_probe(key):
    f = FAMILY.get(key)
    return f.probe if f else '*IDN?'


# ------------------------------------------------------------------------------------------------------------ reading a reply
@dataclass
class Identity:
    raw: str = ''
    manufacturer: str = ''
    model: str = ''
    serial: str = ''
    firmware: str = ''


def clean_reply(text):
    return str(text).replace('\x00', '').strip().strip('"').strip()


def parse_identity(reply) -> Identity:
    """Manufacturer / model / serial / firmware from an identity reply.  Comma separated (*IDN?, fields trimmed: 'HEWLETT-PACKARD, 53132A,0,XXXX')
    or the 3458A's plain text ('Keysight 3458A', 'HP3458A')."""
    raw = clean_reply(reply)
    if not raw:
        return Identity()
    if ',' in raw:
        parts = [p.strip() for p in raw.split(',')]
        serial = parts[2] if len(parts) > 2 else ''
        return Identity(raw, parts[0], parts[1] if len(parts) > 1 else '', '' if serial in ('0', '-', 'N/A') else serial, ','.join(parts[3:]).strip())
    m = re.search(r'(?<![A-Za-z0-9])(?:HP|HEWLETT-PACKARD|KEYSIGHT|AGILENT)?\s*(\d{4,5}[A-Z]?)\b', raw, re.I)
    if m:
        return Identity(raw, raw[:m.start(1)].strip(), m.group(1).upper())
    return Identity(raw, '', raw)


def _norm_model(model):
    return re.sub(r'\s+', '', str(model or '')).upper()


def match_family(ident: Identity):
    """The Family whose model pattern matches the model field, or None (an instrument this suite has no procedure for)."""
    m = _norm_model(ident.model)
    if not m:
        return None
    for f in FAMILIES:
        if re.search(f.model_re, m):
            return f
    return None


# ------------------------------------------------------------------------------------------------------------ resource names
def bus_of(resource):
    r = str(resource).upper()
    for bus in ('GPIB', 'USB', 'TCPIP', 'ASRL', 'VXI', 'PXI'):
        if r.startswith(bus):
            return bus
    return 'OTHER'


def is_instr(resource):
    return str(resource).upper().endswith('::INSTR')


def gpib_boards(resources):
    out = set()
    for r in resources:
        m = re.match(r'(?i)GPIB(\d+)::', str(r))
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def gpib_address(resource):
    m = re.match(r'(?i)GPIB\d+::(\d+)::', str(resource))
    return int(m.group(1)) if m else None


class ScanError(RuntimeError):
    """The scan cannot run at all (no pyvisa / no VISA library); the text is for the technician."""


def default_resource_manager():
    """pyvisa's ResourceManager: the installed NI-VISA / Keysight VISA when there is one, else pyvisa-py.  Raises ScanError in plain words."""
    try:
        import pyvisa
    except ImportError as exc:
        raise ScanError('pyvisa is not installed. Install it with:  pip install pyvisa   (and a VISA library: NI-VISA or the Keysight IO Libraries Suite; '
                        'pyvisa-py also works for USB and LAN, and for GPIB only with linux-gpib / gpib-ctypes).') from exc
    first = None
    for spec in ((), ('@py',)):
        try:
            return pyvisa.ResourceManager(*spec)
        except Exception as exc:      # OSError when no library is found
            first = first or exc
    raise ScanError('No VISA library was found, so instruments cannot be listed. Install NI-VISA or the Keysight IO Libraries Suite '
                    f'(or pip install pyvisa-py).  Detail: {first}') from first


def describe_backend(rm):
    """('pyvisa-py' | 'VISA library', detail) for the status line."""
    lib = getattr(rm, 'visalib', None)
    mod = type(lib).__module__ if lib is not None else ''
    path = str(getattr(lib, 'library_path', '') or '')
    if 'pyvisa_py' in mod or path.strip().strip('@').lower() == 'py':
        return 'pyvisa-py', path
    return 'VISA library (NI-VISA / Keysight)', path


GPIB_NAMING_NOTE = ('GPIB board numbers depend on the VISA software and the adapter: NI-VISA usually numbers the first interface GPIB0, the Keysight IO Libraries '
                    'use the interface ID set in Connection Expert (a USB-GPIB adapter is often GPIB1 or higher), pyvisa-py with linux-gpib follows gpib.conf. '
                    'The address after the board (the 22 in GPIB1::22::INSTR) is the instrument\'s own. Do not assume GPIB0.')


# ------------------------------------------------------------------------------------------------------------ results
@dataclass
class Hit:
    resource: str
    bus: str = ''
    status: str = 'unknown'          # identified | unknown (answered, not an instrument this suite drives) | no reply | error | empty
    probe: str = ''
    idn: str = ''
    identity: Identity = field(default_factory=Identity)
    key: str = ''                    # model key of the matching Family, '' when none
    label: str = ''
    error: str = ''
    alias_of: str = ''               # same model and serial seen on another resource (first one wins)
    needs_serial: bool = False       # another resource has the same model with a different serial: the technician picks by serial

    @property
    def serial(self):
        return self.identity.serial

    def line(self):
        return f'{self.resource}  {self.idn or self.error or self.status}'


@dataclass
class ScanReport:
    backend: str = ''
    backend_path: str = ''
    hits: list = field(default_factory=list)
    serial_ports: list = field(default_factory=list)       # listed, never probed
    skipped: list = field(default_factory=list)            # (resource, reason)
    empty_gpib: int = 0
    probed: int = 0
    cancelled: bool = False
    warnings: list = field(default_factory=list)
    log: list = field(default_factory=list)                # ('>>', resource, text) / ('<<', resource, text): what crossed the wire, for the details box

    def identified(self):
        return [h for h in self.hits if h.status == 'identified' and not h.alias_of]


def annotate_duplicates(hits):
    """Same model + same serial on two resources = one instrument reachable twice (the first listed wins, the other is an alias); same model with
    different serials (or no serial to tell them apart) = the technician must choose, so every one of them is flagged."""
    seen = {}
    by_key = {}
    for h in hits:
        if h.status != 'identified':
            continue
        sig = (h.key, h.serial)
        if h.serial and sig in seen:
            h.alias_of = seen[sig]
            continue
        seen[sig] = h.resource
        by_key.setdefault(h.key, []).append(h)
    for group in by_key.values():
        if len(group) > 1:
            for h in group:
                h.needs_serial = True
    return hits


# ------------------------------------------------------------------------------------------------------------ the scanner
def is_timeout(exc):
    code = getattr(exc, 'error_code', None)
    return code in (-1073807339, 0xBFFF0015) or 'timeout' in str(exc).lower() or 'timed out' in str(exc).lower()


def probe_order(bus, preferred=None):
    probes = list(PROBES.get(bus, ()))
    if preferred and preferred in probes:
        probes.remove(preferred)
        probes.insert(0, preferred)
    return probes


class Scanner:
    """`rm_factory()` -> a ResourceManager (tests give a fake).  `preferred` {resource: probe} lets a remembered resource be asked with its own query first."""

    def __init__(self, rm_factory=None, timeout_ms=DEFAULT_TIMEOUT_MS, open_timeout_ms=DEFAULT_OPEN_TIMEOUT_MS, probe_all_gpib=False, go_local=False,
                 preferred=None):
        self.rm_factory = rm_factory or default_resource_manager
        self.timeout_ms = int(timeout_ms)
        self.open_timeout_ms = int(open_timeout_ms)
        self.probe_all_gpib = bool(probe_all_gpib)
        self.go_local = bool(go_local)
        self.preferred = dict(preferred or {})

    # ---- one resource
    def _open(self, rm, name):
        try:
            res = rm.open_resource(name, open_timeout=self.open_timeout_ms)
        except TypeError:
            res = rm.open_resource(name)
        res.timeout = self.timeout_ms
        return res

    def _release(self, res, bus):
        if res is None:
            return
        if self.go_local and bus == 'GPIB':
            try:
                import pyvisa
                const = pyvisa.constants
                op = getattr(getattr(const, 'RENLineOperation', None), 'address_gtl', None) or getattr(const, 'VI_GPIB_REN_ADDRESS_GTL', None)
                if op is not None:
                    res.control_ren(op)
            except Exception:
                pass
        try:
            res.close()
        except Exception:
            pass

    def probe_resource(self, rm, name, probes=None, log=None, cancel=None) -> Hit:
        """Identity queries on one INSTR resource.  Never raises."""
        bus = bus_of(name)
        hit = Hit(name, bus)
        probes = list(probes if probes is not None else probe_order(bus, self.preferred.get(name)))
        if not probes:
            hit.status, hit.error = 'error', f'no identity query is defined for {bus}'
            return hit
        res = None
        try:
            try:
                res = self._open(rm, name)
            except Exception as exc:
                hit.status, hit.error = ('empty' if re.search(r'listener', str(exc), re.I) else 'error'), f'could not open: {exc}'
                return hit
            last_error = ''
            for i, text in enumerate(probes):
                if cancel is not None and cancel.is_set():
                    hit.status, hit.error = 'no reply', 'cancelled'
                    return hit
                query = assert_read_only(text)
                attempts = 2 if i == len(probes) - 1 else 1          # read-only query: one retry, after a timeout, on the last probe only
                for attempt in range(attempts):
                    if log is not None:
                        log.append(('>>', name, query))
                    try:
                        reply = res.query(query)
                    except Exception as exc:
                        last_error = str(exc)
                        if log is not None:
                            log.append(('!!', name, last_error))
                        if is_timeout(exc) and attempt + 1 < attempts:
                            continue
                        break
                    reply = clean_reply(reply)
                    if log is not None:
                        log.append(('<<', name, reply))
                    if reply:
                        ident = parse_identity(reply)
                        fam = match_family(ident)
                        hit.probe, hit.idn, hit.identity = query, reply, ident
                        hit.status = 'identified' if fam else 'unknown'
                        if fam:
                            hit.key, hit.label = fam.key, fam.label
                        return hit
                    break
            hit.status = 'no reply'
            hit.error = last_error or 'no answer to ' + ' / '.join(probes)
            if bus == 'GPIB' and re.search(r'listener|nolisten', hit.error, re.I):
                hit.status = 'empty'
            return hit
        finally:
            self._release(res, bus)

    # ---- the whole scan
    def candidates(self, found):
        """(resources to probe, ASRL list, skipped [(name, reason)], extra GPIB names probed by address)."""
        probe, asrl, skipped = [], [], []
        for r in found:
            bus = bus_of(r)
            if bus == 'ASRL':
                asrl.append(r)
            elif not is_instr(r):
                skipped.append((r, 'not an INSTR resource (interface or socket): nothing to ask'))
            elif bus in PROBE_BUSES:
                probe.append(r)
            else:
                skipped.append((r, f'{bus} is not probed'))
        extra = []
        boards = gpib_boards(found)
        listed = {r.upper() for r in found}
        for b in boards:
            has_instr = any(bus_of(r) == 'GPIB' and is_instr(r) and gpib_boards([r]) == [b] for r in found)
            if self.probe_all_gpib or not has_instr:
                extra += [n for n in (f'GPIB{b}::{a}::INSTR' for a in GPIB_ADDRESSES) if n.upper() not in listed]
        return probe, asrl, skipped, extra

    def scan(self, progress=None, cancel=None) -> ScanReport:
        rm = self.rm_factory()
        report = ScanReport()
        try:
            report.backend, report.backend_path = describe_backend(rm)
            try:
                found = list(rm.list_resources())
            except Exception as exc:
                raise ScanError(f'The VISA library could not list the instruments: {exc}') from exc
            probe, report.serial_ports, report.skipped, extra = self.candidates(found)
            if gpib_boards(found) and extra:
                report.warnings.append('VISA lists a GPIB interface with no instruments on it (or all addresses were requested), so GPIB addresses 0-30 were asked '
                                       'one by one. ' + GPIB_NAMING_NOTE)
            if not [r for r in found if bus_of(r) == 'GPIB'] and report.backend == 'pyvisa-py':
                report.warnings.append('pyvisa-py lists no GPIB interface: it needs linux-gpib or gpib-ctypes and the adapter\'s driver for GPIB. Install NI-VISA or the '
                                       'Keysight IO Libraries Suite, or type the address by hand.')
            work = [(r, False) for r in probe] + [(r, True) for r in extra]
            for i, (name, guessed) in enumerate(work):
                if cancel is not None and cancel.is_set():
                    report.cancelled = True
                    break
                if progress:
                    progress(i, len(work), f'Asking {name}')
                hit = self.probe_resource(rm, name, log=report.log, cancel=cancel)
                report.probed += 1
                if hit.status == 'empty' or (guessed and hit.status in ('error', 'no reply')):
                    report.empty_gpib += 1
                    continue
                report.hits.append(hit)
            if progress and not report.cancelled:
                progress(len(work), len(work), 'Done')
            annotate_duplicates(report.hits)
            return report
        finally:
            try:
                rm.close()
            except Exception:
                pass

    # ---- one remembered resource (quick check)
    def verify(self, resource, key, serial='') -> 'Check':
        """Ask the remembered resource with the ONE query its family answers (never an RS-232 port) and compare model and serial."""
        bus = bus_of(resource)
        fam = FAMILY.get(key)
        if bus == 'ASRL':
            return Check(False, None, 'a serial port is not checked automatically; use the serial check with the instrument type')
        if fam is None or bus not in PROBE_BUSES:
            return Check(False, None, 'unknown model or interface')
        try:
            rm = self.rm_factory()
        except ScanError as exc:
            return Check(False, None, str(exc))
        try:
            hit = self.probe_resource(rm, resource, probes=[fam.probe])
        finally:
            try:
                rm.close()
            except Exception:
                pass
        if hit.status != 'identified' or hit.key != key:
            return Check(False, hit, f'{resource} now answers: {hit.idn or hit.error or hit.status}')
        if serial and hit.serial and hit.serial != serial:
            return Check(False, hit, f'{resource} is a {key} with serial {hit.serial}, not {serial}')
        return Check(True, hit, 'confirmed')


@dataclass
class Check:
    ok: bool
    hit: object = None
    reason: str = ''


# ------------------------------------------------------------------------------------------------------------ a scan in a worker thread
class ScanJob:
    """Runs `scanner.scan` in a daemon thread so a window never waits on a VISA timeout.  The window calls `poll()` from a Tk `after`.  `cancel()` returns at
    once: a call stuck inside VISA is abandoned (its result is dropped), never waited for."""

    def __init__(self, scanner, runner=None):
        self.scanner, self.runner = scanner, runner
        self.events = queue.Queue()
        self._cancel = threading.Event()
        self.thread = None
        self.finished = False
        self.abandoned = False

    def start(self):
        self.thread = threading.Thread(target=self._run, name='instrument-scan', daemon=True)
        self.thread.start()
        return self

    def _run(self):
        try:
            if self.runner is not None:
                result = self.runner(lambda i, n, m: self.events.put(('progress', (i, n, m))), self._cancel)
            else:
                result = self.scanner.scan(progress=lambda i, n, m: self.events.put(('progress', (i, n, m))), cancel=self._cancel)
            self.events.put(('done', result))
        except ScanError as exc:
            self.events.put(('error', str(exc)))
        except Exception as exc:                      # a bug or a VISA failure must show up as a message, not a dead window
            self.events.put(('error', f'The scan stopped: {exc}'))

    def cancel(self):
        self._cancel.set()
        self.abandoned = True

    def poll(self):
        """[(kind, payload)] since the last call; kind progress | done | error.  Nothing after a cancel."""
        out = []
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if self.abandoned:
                continue
            if kind in ('done', 'error'):
                self.finished = True
            out.append((kind, payload))
        return out


# ------------------------------------------------------------------------------------------------------------ RS-232: only on request, with the driver's own code
def serial_settings_for(family: Family):
    """The serial settings of the family's driver (class SERIAL, else the module constant named in the family)."""
    import drivers
    from drivers.transport import SerialSettings
    cls = getattr(drivers, family.driver, None)
    s = getattr(cls, 'SERIAL', None)
    if s is None and family.serial_attr:
        mod, _, name = family.serial_attr.partition('.')
        try:
            s = getattr(__import__(f'drivers.{mod}', fromlist=[name]), name)
        except Exception:
            s = None
    return s or SerialSettings()


def serial_identity(port, key, timeout=3.0, transport_factory=None):
    """The identity text of the instrument on RS-232 `port` (a VISA name such as ASRL9::INSTR), read with the DRIVER'S OWN identify() for the instrument
    type `key` the technician chose.  Raises ScanError when the family cannot be checked this way.  Nothing but that one query is sent; the port is closed."""
    fam = FAMILY.get(key)
    if fam is None or not fam.serial_ok:
        raise ScanError(f'{key} is not checked over RS-232 by this tool.')
    if bus_of(port) != 'ASRL':
        raise ScanError(f'{port} is not a serial port.')
    import drivers
    cls = getattr(drivers, fam.driver)
    settings = serial_settings_for(fam)
    if transport_factory is not None:
        transport = transport_factory(port, settings)
    else:
        from drivers.transport import VisaTransport
        transport = VisaTransport(port, timeout=timeout, serial=settings)
    inst = cls(transport)
    try:
        inst.open(verify_model=False)           # opens and sets the timeout; sends nothing
        inst.t.set_timeout(timeout)
        return clean_reply(inst.identify())
    finally:
        try:
            inst.close()
        except Exception:
            pass


def serial_hit(port, key, timeout=3.0, transport_factory=None) -> Hit:
    """A Hit for an explicitly requested serial check (never raises)."""
    hit = Hit(port, 'ASRL', probe='driver identify()')
    try:
        reply = serial_identity(port, key, timeout, transport_factory)
    except Exception as exc:
        hit.status, hit.error = 'no reply', str(exc)
        return hit
    ident = parse_identity(reply)
    fam = match_family(ident)
    hit.idn, hit.identity = reply, ident
    if fam is None:
        hit.status = 'unknown'
    elif fam.key != key and fam.driver != FAMILY[key].driver:
        hit.status, hit.key, hit.label = 'unknown', fam.key, fam.label
        hit.error = f'you chose {key} but the instrument says it is {fam.key}'
    else:
        hit.status, hit.key, hit.label = 'identified', fam.key, fam.label
    return hit


# ------------------------------------------------------------------------------------------------------------ memory (lab_registry.sqlite3)
SCHEMA = '''
CREATE TABLE IF NOT EXISTS instrument_resources (
    workstation TEXT NOT NULL,
    model TEXT NOT NULL,
    serial TEXT NOT NULL DEFAULT '',
    resource TEXT NOT NULL,
    idn TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL,
    PRIMARY KEY (workstation, model, serial)
);
'''


def workstation_id():
    try:
        user = getpass.getuser()
    except Exception:
        user = 'user'
    return f'{user}@{platform.node() or "pc"}'


@dataclass
class Remembered:
    model: str
    resource: str
    serial: str
    idn: str
    last_seen: str


class ResourceMemory:
    """What this technician on this workstation accepted.  `path` None = the real lab registry.  Reading never creates a file; writing adds the one table."""

    def __init__(self, path=None, workstation=None, now=None):
        if path is None:
            import labregistry
            path = labregistry.DB
        self.path = Path(path)
        self.workstation = workstation or workstation_id()
        self._now = now or datetime.now

    @contextmanager
    def _write(self):
        con = sqlite3.connect(str(self.path), timeout=5)
        try:
            con.executescript(SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()

    def remembered(self, model=None) -> list:
        """Most recently seen first.  [] for a missing file, a missing table or a damaged file."""
        if not self.path.is_file():
            return []
        try:
            con = sqlite3.connect(f'file:{self.path.as_posix()}?mode=ro', uri=True, timeout=5)
            try:
                sql = 'SELECT model,resource,serial,idn,last_seen FROM instrument_resources WHERE workstation=?'
                args = [self.workstation]
                if model:
                    sql, args = sql + ' AND model=?', args + [model]
                return [Remembered(*r) for r in con.execute(sql + ' ORDER BY last_seen DESC, model, serial', args)]
            finally:
                con.close()
        except sqlite3.Error:
            return []

    def remember(self, hit: Hit):
        """Save an ACCEPTED identified result (the technician pressed Remember)."""
        if hit.status != 'identified' or not hit.key:
            raise ValueError('only an identified instrument can be remembered')
        with self._write() as con:
            con.execute('INSERT OR REPLACE INTO instrument_resources (workstation,model,serial,resource,idn,last_seen) VALUES (?,?,?,?,?,?)',
                        (self.workstation, hit.key, hit.serial, hit.resource, hit.idn, self._now().isoformat(sep=' ', timespec='seconds')))

    def forget(self, model, serial=''):
        if not self.path.is_file():
            return
        with self._write() as con:
            con.execute('DELETE FROM instrument_resources WHERE workstation=? AND model=? AND serial=?', (self.workstation, model, serial))

    def status_of(self, hit: Hit) -> str:
        """'' (not remembered) | 'remembered' | 'address changed (was X)' for the dialog column."""
        if hit.status != 'identified':
            return ''
        for r in self.remembered(hit.key):
            if r.serial == hit.serial or not r.serial or not hit.serial:
                return 'remembered' if r.resource == hit.resource else f'address changed (was {r.resource})'
        return ''


_SESSION_OK: dict = {}          # (workstation, model, serial, resource) -> True once confirmed in this process: adapters can renumber between sessions


def default_resource(model, memory=None, scanner=None, serial='') -> str:
    """The remembered resource for `model`, only when a quick read-only identity check confirms it now; '' otherwise (the technician then uses Find instruments).
    One confirmed answer per session is cached.  With several remembered serials of the model, `serial` must say which; else '' unless exactly one confirms."""
    memory = memory or ResourceMemory()
    scanner = scanner or Scanner()
    ok = []
    for rec in memory.remembered(model):
        if serial and rec.serial and rec.serial != serial:
            continue
        sig = (memory.workstation, rec.model, rec.serial, rec.resource)
        if _SESSION_OK.get(sig) or scanner.verify(rec.resource, rec.model, rec.serial).ok:
            _SESSION_OK[sig] = True
            ok.append(rec)
    return ok[0].resource if len(ok) == 1 else ''


def clear_session_cache():
    _SESSION_OK.clear()


# ------------------------------------------------------------------------------------------------------------ what the window shows
def serial_resource_names(devices):
    """VISA names for serial devices pyserial lists ('COM9' -> 'ASRL9::INSTR', '/dev/ttyUSB0' -> 'ASRL/dev/ttyUSB0::INSTR').  Listing a port sends nothing."""
    out = []
    for d in devices:
        d = str(d)
        m = re.fullmatch(r'(?i)COM(\d+)', d)
        name = f'ASRL{int(m.group(1))}::INSTR' if m else (d if d.upper().startswith('ASRL') else f'ASRL{d}::INSTR')
        if name not in out:
            out.append(name)
    return out


def system_serial_ports():
    """Serial ports of this computer (pyserial); [] without pyserial.  Nothing is sent to them."""
    try:
        from serial.tools import list_ports
        return serial_resource_names(sorted((p.device for p in list_ports.comports()), key=lambda s: (len(s), s)))
    except Exception:
        return []


def serial_family_choices():
    """[(key, label)] of the instrument types whose RS-232 identity can be checked with the driver's own code."""
    return [(f.key, f.label) for f in FAMILIES if f.serial_ok]


def state_text(hit: Hit, memory=None) -> str:
    if hit.status == 'identified':
        if hit.alias_of:
            return f'Same instrument as {hit.alias_of}'
        mem = memory.status_of(hit) if memory is not None else ''
        extra = 'choose by serial' if hit.needs_serial else ''
        return '; '.join(x for x in ('Identified', extra, mem) if x)
    if hit.status == 'unknown':
        return hit.error or 'Not a model this suite has a procedure for'
    if hit.status == 'no reply':
        err = hit.error or ''
        return 'No answer (timed out)' if (not err or 'imeout' in err or 'timed out' in err.lower() or 'TMO' in err) else 'No answer: ' + err[:50]
    return 'Error: ' + (hit.error[:60] if hit.error else '')


def row_tag(hit: Hit) -> str:
    return {'identified': 'pass', 'unknown': 'pending', 'no reply': 'error', 'error': 'error'}.get(hit.status, 'pending') if not hit.alias_of else 'pending'


def result_rows(hits, memory=None):
    """[(values, tag, hit)] for the results table: Resource | Instrument | Model key | Serial | Status.  Identified first, then by resource."""
    def order(h):
        return (0 if h.status == 'identified' and not h.alias_of else 1 if h.status == 'identified' else 2 if h.status == 'unknown' else 3, h.bus, h.resource)
    rows = []
    for h in sorted(hits, key=order):
        rows.append(((h.resource, h.idn or '(no reply)', h.key or '-', h.serial or ('-' if h.status == 'identified' else ''), state_text(h, memory)), row_tag(h), h))
    return rows
