"""Instrument command registry, formatter and validator (Tk-free, no I/O, no instrument access).

Drivers declare their commands once, at class level:

    COMMANDS = {'out.volts': Cmd('OUT {volts:.9g}V', 'Program a voltage',
                                 placeholders={'volts': Placeholder('float', '.9g', 1.0)},
                                 kind='set', readback=None, verified=True, ref='5560A Remote Programming')}

and a driver (or the override layer) resolves the merged table with `merge_commands(DriverClass)`.

Public API (stable):

    Placeholder(type, fmt='', sample=None, required=True, enum=None)   type: 'float' | 'int' | 'str' | 'enum' | 'secret'
    Cmd(template, name='', description='', placeholders={}, kind='set', readback=None, risk='normal',
        verified=False, ref='', lang='scpi')                            kind: 'set' | 'query' | 'action'; risk: 'normal' | 'output' | 'locked'
    merge_commands(cls_or_obj) -> {key: Cmd}                  COMMANDS merged along the MRO (subclass wins)
    command_owners(cls_or_obj) -> {key: class name}           which class in the MRO declared each key
    render(cmd_or_text, values) -> str                        identical to the f-string with the same format specs; raises CmdError
    validate(text, cmd, driver_name=None) -> [Problem]        [] means acceptable as an OVERRIDE of cmd; never raises
    validate_bundle(templates, registry) -> [Problem]         cross-command rules (a set keeps its paired read-back query)
    lint_registry(registry) -> [Problem]                      sanity check of a driver's own declarations
    is_overridable(cmd) -> (bool, reason)
    has_placeholders / placeholders_of(text) -> [names]

`Problem` is a str subclass (its text is the message) with a `.code` attribute, so tests and UIs can switch on the code:
ascii, length, empty, syntax, attr, conv, format, placeholder.unknown, placeholder.missing, forbidden, output, readback,
secret, locked, vbs, type.

Rules (see the design in procmods_design.md): printable ASCII and <= 256 characters; named placeholders only, a subset of the declared
ones with every required one present; each format spec is checked against the declared sample value; no attribute/index access, no
conversion flags, no nested fields; every ';' segment is scanned for forbidden commands (*RST *SAV *RCL SYST:PRES, first node
CAL(?!C) SEC PASS DIAG SERV FACT, plus the extras in EXTRA_FORBIDDEN); output-enable tokens (OPER, OUTP ON, OUTP:STAT) only in a command
whose risk is 'output' - and 'output' / 'locked' commands are not overridable at all in v1; a command with a secret placeholder is not
overridable; a 'set' may not contain a query and a 'query' must contain one; LeCroy VBS commands allow only the property path and value
to change.  Nothing here knows whether a command really exists on an instrument: that is unverified until tested on hardware.
"""
from __future__ import annotations

import math
import re
import string
from dataclasses import dataclass, field

MAX_LEN = 256
KINDS = ('set', 'query', 'action')
RISKS = ('normal', 'output', 'locked')
PTYPES = ('float', 'int', 'str', 'enum', 'secret')

# Forbidden regardless of driver (matched per ';' segment on the upper-cased, ':'-split node list; see _segments).
EXTRA_FORBIDDEN = (('SYST', 'SEC'), ('SYST', 'COMM'), ('SYST', 'CPON'), ('MMEM', 'DEL'), ('MEM', 'DEL'))
FORBIDDEN_FIRST_NODE = (r'CAL(?!C)', r'SEC', r'PASS', r'DIAG', r'SERV', r'FACT')
# Per-driver additions, keyed by a lower-case substring of the driver class name.
DRIVER_FORBIDDEN = {'8846': (re.compile(r'(?:^|[\s:;])CAL(?:IBRATION)?\s*:', re.I),),
                    '8808': (re.compile(r'(?:^|[\s;])(?:\*TER|CALREF|EXIT)(?![A-Za-z])', re.I),)}      # 8808A: *TER enters calibration mode (Cal Manual Table 3-9)
VBS_PATH = re.compile(r'^app\.(Acquisition|Measure|Math)[\w.()]*$')
VBS_FORBIDDEN = re.compile(r'CreateObject|Shell|WScript|Exec|Calibrat', re.I)
_SPEC = re.compile(r'^(?:[<>^=])?[+\- ]?#?0?(?:\d{1,3})?[,_]?(?:\.\d{1,2})?[bcdeEfFgGnosxX%]?$')
_STR_SPEC = re.compile(r'^(?:[<>^])?(?:\d{1,3})?s?$')


class CmdError(ValueError):
    """Raised by render() for a value that does not fit the command (callers validate first)."""


class Problem(str):
    """A validation message; `.code` says which rule it came from."""
    code = ''

    def __new__(cls, code, message):
        obj = super().__new__(cls, message)
        obj.code = code
        return obj


@dataclass(frozen=True)
class Placeholder:
    type: str = 'float'
    fmt: str = ''
    sample: object = None
    required: bool = True
    enum: tuple | None = None


@dataclass(frozen=True)
class Cmd:
    template: str
    name: str = ''
    description: str = ''
    placeholders: dict = field(default_factory=dict)
    kind: str = 'set'
    readback: str | None = None
    risk: str = 'normal'
    verified: bool = False
    ref: str = ''
    lang: str = 'scpi'                                  # 'scpi' | 'vbs'

    @property
    def secret(self) -> bool:
        return any(getattr(p, 'type', '') == 'secret' for p in (self.placeholders or {}).values())


# ------------------------------------------------------------------------------------------------------------ registry
def merge_commands(cls_or_obj) -> dict:
    """COMMANDS merged along the MRO: a subclass key replaces the base's."""
    cls = cls_or_obj if isinstance(cls_or_obj, type) else type(cls_or_obj)
    out = {}
    for klass in reversed(cls.__mro__):
        table = klass.__dict__.get('COMMANDS')
        if isinstance(table, dict):
            out.update(table)
    return out


def command_owners(cls_or_obj) -> dict:
    cls = cls_or_obj if isinstance(cls_or_obj, type) else type(cls_or_obj)
    out = {}
    for klass in reversed(cls.__mro__):
        table = klass.__dict__.get('COMMANDS')
        if isinstance(table, dict):
            for key in table:
                out[key] = klass.__name__
    return out


# ------------------------------------------------------------------------------------------------------------ parsing
def _fields(text):
    """[(literal, field_name, spec, conversion)] or raises ValueError on a malformed template."""
    return list(string.Formatter().parse(text))


def placeholders_of(text) -> list:
    """Names used by a template, in order of first use ([] if it cannot be parsed)."""
    try:
        names = []
        for _lit, name, _spec, _conv in _fields(text):
            if name is not None and name not in names:
                names.append(name)
        return names
    except (ValueError, TypeError):
        return []


def has_placeholders(text) -> bool:
    return bool(placeholders_of(text))


def _default_sample(ph):
    if ph.sample is not None:
        return ph.sample
    if ph.type == 'int':
        return 1
    if ph.type == 'float':
        return 1.0
    if ph.type == 'enum' and ph.enum:
        return ph.enum[0]
    return 'X'


def _check_value(name, ph, value):
    """Problem text for a value that does not fit placeholder ph, else None."""
    t = ph.type
    if t in ('float', 'int'):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f'{name}: expected a number'
        if isinstance(value, float) and not math.isfinite(value):
            return f'{name}: not a finite number'
        if t == 'int' and not isinstance(value, int) and value != int(value):
            return f'{name}: expected an integer'
    elif t == 'enum':
        if value not in (ph.enum or ()):
            return f'{name}: {value!r} is not one of {list(ph.enum or ())}'
    else:                                                # str / secret
        if not isinstance(value, str):
            return f'{name}: expected text'
        if any(not 32 <= ord(c) < 127 for c in value):
            return f'{name}: text must be printable ASCII'
    return None


def render(cmd_or_text, values=None) -> str:
    """Format a template exactly as the equivalent f-string would (`'{v:.9g}'` -> `f'{v:.9g}'`).

    With a Cmd the values are checked against the declared placeholders (missing required, wrong type, enum, NaN/inf are CmdError);
    extra values are ignored.  With plain text the values are used as given.  Raises CmdError; use validate() first on edited text."""
    values = dict(values or {})
    cmd = cmd_or_text if isinstance(cmd_or_text, Cmd) else None
    text = cmd.template if cmd else cmd_or_text
    if not isinstance(text, str):
        raise CmdError('template is not text')
    try:
        fields = _fields(text)
    except ValueError as e:
        raise CmdError(f'bad template: {e}')
    out = []
    for literal, name, spec, conv in fields:
        out.append(literal)
        if name is None:
            continue
        if conv or '.' in name or '[' in name or not name.isidentifier():
            raise CmdError(f'unsupported field {{{name}}}')
        ph = cmd.placeholders.get(name) if cmd else None
        if cmd and ph is None:
            raise CmdError(f'unknown placeholder {{{name}}}')
        if name not in values or values[name] is None:
            if ph is not None and not ph.required:
                continue
            raise CmdError(f'missing value for {{{name}}}')
        if ph is not None:
            bad = _check_value(name, ph, values[name])
            if bad:
                raise CmdError(bad)
        try:
            out.append(format(values[name], spec or ''))
        except (ValueError, TypeError) as e:
            raise CmdError(f'{name}: {e}')
    return ''.join(out)


# ------------------------------------------------------------------------------------------------------------ SCPI scan
def _segments(text):
    """Per ';' segment: (first_header_nodes, raw_upper).  Nodes are upper-case, argument and '?' removed, leading ':' dropped."""
    segs = []
    for seg in text.split(';'):
        s = seg.strip()
        if not s:
            continue
        head = s.split(None, 1)[0] if not s.upper().startswith('VBS') else s
        head = head.upper().lstrip(':')
        nodes = [re.sub(r'\d+$', '', n.rstrip('?')) for n in head.split(':')]
        segs.append((nodes, s.upper()))
    return segs


def _node_is(node, short, long=None):
    """SCPI mnemonics are accepted in short or long form only."""
    return node in {short, (long or short)}


_COMMON_FORBIDDEN = ('*RST', '*SAV', '*RCL')
_OUTPUT_RES = (
    re.compile(r'^:?OPER(ATE)?\b'),
    re.compile(r'^:?OUTP(UT)?\d*\s+(ON|1)\b'),
    re.compile(r'^:?OUTP(UT)?\d*:STAT'),
)


def _forbidden(text, driver_name):
    probs = []
    for nodes, raw in _segments(text):
        first = nodes[0] if nodes else ''
        if first in _COMMON_FORBIDDEN:
            probs.append(f'{first} is not allowed')
        if len(nodes) > 1 and _node_is(nodes[0], 'SYST', 'SYSTEM') and _node_is(nodes[1], 'PRES', 'PRESET'):
            probs.append('SYST:PRES is not allowed')
        for a, b in EXTRA_FORBIDDEN:
            if len(nodes) > 1 and nodes[0].startswith(a) and nodes[1].startswith(b) and (a, b) != ('SYST', 'PRES'):
                probs.append(f'{a}:{b} is not allowed')
        for pat in FORBIDDEN_FIRST_NODE:
            if re.match(pat, first):
                probs.append(f'{first}: calibration, security, service and factory commands are not allowed')
                break
    low = (driver_name or '').lower()
    for sub, pats in DRIVER_FORBIDDEN.items():
        if sub in low:
            for pat in pats:
                if pat.search(text):
                    probs.append('CAL: commands are not allowed on this instrument')
    return probs


def _output_tokens(text):
    return [raw for _n, raw in _segments(text) if any(r.match(raw) for r in _OUTPUT_RES)]


# ------------------------------------------------------------------------------------------------------------ VBS
def _vbs_parts(text):
    """(prefix, path, value, suffix) of a LeCroy VBS command, or None if it does not contain 'app.'."""
    i = text.find('app.')
    if i < 0:
        return None
    prefix, rest = text[:i], text[i:]
    suffix = ''
    if rest and rest[-1] in '\'"':
        suffix, rest = rest[-1], rest[:-1]
    if '=' in rest:
        path, value = rest.split('=', 1)
        return prefix, path.strip(), value.strip(), suffix, True
    return prefix, rest.strip(), '', suffix, False


def _vbs_problems(text, cmd):
    probs = []
    if VBS_FORBIDDEN.search(text):
        probs.append(Problem('vbs', 'VBS: CreateObject / Shell / WScript / Exec / Calibrat are not allowed'))
    new, old = _vbs_parts(text), _vbs_parts(cmd.template if cmd else text)
    if new is None:
        return probs + [Problem('vbs', 'VBS: the command must address an app.* property')]
    pre, path, value, suf, has_eq = new
    if not VBS_PATH.match(path):
        probs.append(Problem('vbs', 'VBS: the property path must match app.(Acquisition|Measure|Math)...'))
    if ':' in value or ':' in path or '\n' in text or "'" in value:
        probs.append(Problem('vbs', "VBS: statement separators and quotes are not allowed in the value"))
    if old is not None:
        if (pre, suf, has_eq) != (old[0], old[3], old[4]):
            probs.append(Problem('vbs', 'VBS: only the property path and value may be edited'))
    return probs


# ------------------------------------------------------------------------------------------------------------ validate
def is_overridable(cmd) -> tuple:
    if cmd is None:
        return False, 'unknown command'
    if cmd.risk == 'locked':
        return False, 'locked (bootstrap, calibration or safety command)'
    if cmd.risk == 'output':
        return False, 'locked (changes the instrument output state)'
    if cmd.secret:
        return False, 'locked (contains a secret value)'
    return True, ''


def _is_vbs(text, cmd, driver_name):
    if cmd is not None and cmd.lang == 'vbs':
        return True
    low = (driver_name or '').lower()
    return ('lecroy' in low or 'ws4104' in low) and text.lstrip().upper().startswith('VBS')


def validate(text, cmd, driver_name=None) -> list:
    """Problems with `text` as an override of `cmd` ([] = acceptable).  Pure; never raises.

    Text identical to the factory template is always acceptable.  `cmd` None checks only the generic rules."""
    try:
        return _validate(text, cmd, driver_name)
    except Exception as e:                              # defensive: a validator must not take the session down
        return [Problem('syntax', f'could not check the command ({type(e).__name__})')]


def _validate(text, cmd, driver_name):
    probs = []
    if cmd is not None and text == cmd.template:
        return probs
    if not isinstance(text, str) or not text.strip():
        return [Problem('empty', 'the command is empty')]
    if any(not 32 <= ord(c) < 127 for c in text):
        probs.append(Problem('ascii', 'only printable ASCII characters are allowed'))
    if len(text) > MAX_LEN:
        probs.append(Problem('length', f'longer than {MAX_LEN} characters'))
    if cmd is not None:
        ok, why = is_overridable(cmd)
        if not ok:
            code = 'secret' if cmd.secret and cmd.risk == 'normal' else 'locked'
            probs.append(Problem(code, f'{cmd.name or "this command"} is not editable: {why}'))
    # placeholders
    sample = {}
    used = []
    try:
        fields = _fields(text)
    except ValueError as e:
        return probs + [Problem('syntax', f'unbalanced or malformed braces ({e})')]
    declared = (cmd.placeholders if cmd is not None else None)
    for _lit, name, spec, conv in fields:
        if name is None:
            continue
        if conv:
            probs.append(Problem('conv', f'conversion flags such as !{conv} are not allowed'))
        if '.' in name or '[' in name or ']' in name:
            probs.append(Problem('attr', f'attribute or index access in {{{name}}} is not allowed'))
            continue
        if not name or not name.isidentifier():
            probs.append(Problem('syntax', 'placeholders must be named, e.g. {volts:.9g}'))
            continue
        used.append(name)
        if spec and '{' in spec:
            probs.append(Problem('format', f'nested fields in the format of {{{name}}} are not allowed'))
            continue
        if declared is None:
            continue
        ph = declared.get(name)
        if ph is None:
            probs.append(Problem('placeholder.unknown', f'{{{name}}} is not a placeholder of this command (allowed: {", ".join(declared) or "none"})'))
            continue
        pattern = _SPEC if ph.type in ('float', 'int') else _STR_SPEC
        if spec and not pattern.match(spec):
            probs.append(Problem('format', f'format ":{spec}" is not allowed for {{{name}}}'))
            continue
        value = _default_sample(ph)
        if ph.type == 'enum' and ph.enum and value not in ph.enum:
            value = ph.enum[0]
        try:
            sample[name] = format(value, spec or '')
        except (ValueError, TypeError):
            probs.append(Problem('format', f'format ":{spec}" does not fit {{{name}}} (a {ph.type}, e.g. {value!r})'))
    if declared is not None:
        for name, ph in declared.items():
            if ph.required and name not in used:
                probs.append(Problem('placeholder.missing', f'required placeholder {{{name}}} is missing'))
    # scan the text with sample values in place (so a placeholder cannot hide a token)
    scan = ''.join(lit + (sample.get(name, '') if name is not None else '') for lit, name, _s, _c in fields)
    if _is_vbs(text, cmd, driver_name):
        return probs + _vbs_problems(scan, cmd)          # VBS commands skip the SCPI scans
    for msg in _forbidden(scan, driver_name):
        probs.append(Problem('forbidden', msg))
    allow_output = cmd is not None and cmd.risk == 'output'
    if not allow_output:
        for raw in _output_tokens(scan):
            probs.append(Problem('output', f'"{raw}" changes the output state; output commands are locked'))
    if cmd is not None:
        has_q = any('?' in seg.split(None, 1)[0] for seg in scan.split(';') if seg.strip())
        if cmd.kind == 'query' and not has_q:
            probs.append(Problem('readback', 'a query must stay a query (it needs a "?")'))
        if cmd.kind in ('set', 'action') and has_q:
            probs.append(Problem('type', 'a set/action command must not contain a query'))
    return probs


def validate_bundle(templates, registry) -> list:
    """Cross-command rules for a whole set of effective templates {key: text} against {key: Cmd}.

    A 'set' with a read-back keeps it: the read-back key must exist and its effective text must still be a query."""
    probs = []
    try:
        for key, cmd in registry.items():
            if cmd.kind == 'set' and cmd.readback:
                rb = registry.get(cmd.readback)
                if rb is None:
                    probs.append(Problem('readback', f'{key}: read-back command {cmd.readback!r} does not exist'))
                    continue
                text = templates.get(cmd.readback, rb.template)
                if not isinstance(text, str) or '?' not in text:
                    probs.append(Problem('readback', f'{key}: the paired read-back {cmd.readback!r} must stay a query'))
    except Exception as e:
        probs.append(Problem('syntax', f'could not check read-backs ({type(e).__name__})'))
    return probs


def reset_cmd(verified=False, ref='', template='*RST', note=''):
    """The registered, LOCKED reset-to-defaults command every driver declares as COMMANDS['reset'] (Stage 7 rule): never overridable,
    so a modified procedure can never skip the reset. verified=True only with a manual page in `ref`."""
    return Cmd(template, 'Reset to default settings', ('Returns the instrument to its default state before a run (never overridable). ' + note).strip(),
               kind='set', risk='locked', verified=verified, ref=ref)


def opc_cmd(verified=False, ref=''):
    """*OPC? - read-only wait for completion after the reset (locked plumbing, like *CLS)."""
    return Cmd('*OPC?', 'Operation complete', 'Waits for pending operations; used after the reset (never overridable)', kind='query',
               risk='locked', verified=verified, ref=ref)


def lint_registry(registry) -> list:
    """Sanity check of a driver's own COMMANDS (not the override rules)."""
    probs = []
    for key, cmd in registry.items():
        if not isinstance(cmd, Cmd):
            probs.append(Problem('type', f'{key}: not a Cmd'))
            continue
        if cmd.kind not in KINDS:
            probs.append(Problem('type', f'{key}: kind {cmd.kind!r}'))
        if cmd.risk not in RISKS:
            probs.append(Problem('type', f'{key}: risk {cmd.risk!r}'))
        if cmd.readback and cmd.readback not in registry:
            probs.append(Problem('readback', f'{key}: read-back {cmd.readback!r} is not registered'))
        for name in placeholders_of(cmd.template):
            if name not in cmd.placeholders:
                probs.append(Problem('placeholder.unknown', f'{key}: {{{name}}} is not declared'))
        for name, ph in cmd.placeholders.items():
            if ph.type not in PTYPES:
                probs.append(Problem('type', f'{key}: placeholder {name} type {ph.type!r}'))
            if ph.type == 'enum' and not ph.enum:
                probs.append(Problem('type', f'{key}: enum placeholder {name} has no values'))
    return probs
