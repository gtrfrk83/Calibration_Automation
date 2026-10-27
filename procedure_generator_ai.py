"""Procedure Generator: page images and the Claude API call (no Qt).

    renderer_name() / render_page(pdf, page, dpi, out)     rendered PAGE IMAGES (pypdfium2, else pdftoppm): the standing rule is that limit tables are read from
                                                          rendered images, never from extracted text (micro and ohm signs corrupt in text)
    page_png(store, project, fid, page, dpi)               the cached PNG of one page of an uploaded manual (the original PDF is never altered)
    build_request(png_paths, labels, model)                the exact request body: image blocks + one short instruction + a forced tool call; NO extracted text is ever sent
    extract(...)                                           pages -> candidate rows.  READ-ONLY (a query): a transient network error is retried, capped; nothing else is
    key_source() / get_key() / save_key() / remove_key()   the API key: ANTHROPIC_API_KEY, else a per-user file with restricted permissions.  Never logged, never echoed.
    scrub(text)                                            blanks the key and anything that looks like one (and uses diagnostics.scrub for password= / token= text)

What the API receives: a system prompt (read exactly what is printed, never compute, mark doubt), then for each page a one-line label ("Image 1 = page 37 of
'manual.pdf'") and the page PNG (base64), then the instruction to call the tool `report_table_rows`.  Nothing else leaves the machine: no project name, no file name
beyond the label, no key in the body (the key is an HTTP header added by the SDK).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import appdata
import datasheet_builder as db
import procedure_generator as pg

DEFAULT_MODEL = 'claude-sonnet-5-5'
DEFAULT_DPI = 150
PAGES_PER_REQUEST = 3
MAX_PAGES = 40                       # per reading: a larger range is refused (cost and time); read in parts
MAX_ATTEMPTS = 3                     # one try and two retries, transient read errors only
BACKOFF = (2.0, 5.0)
MAX_TOKENS = 16000
TOOL_NAME = 'report_table_rows'
SETTINGS_FILE = 'generator_settings.json'

# ============================================================================================================== settings and the key
def settings_path() -> Path:
    return appdata.data_dir() / SETTINGS_FILE


def load_settings() -> dict:
    out = dict(model=DEFAULT_MODEL, dpi=DEFAULT_DPI)
    try:
        d = json.loads(settings_path().read_text(encoding='utf-8'))
        if isinstance(d, dict):
            if isinstance(d.get('model'), str) and d['model'].strip():
                out['model'] = d['model'].strip()
            if isinstance(d.get('dpi'), int) and 72 <= d['dpi'] <= 300:
                out['dpi'] = d['dpi']
    except (OSError, ValueError):
        pass
    return out


def save_settings(model: str = '', dpi: int = 0) -> dict:
    cur = load_settings()
    if model.strip():
        cur['model'] = model.strip()
    if dpi:
        cur['dpi'] = max(72, min(300, int(dpi)))
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, indent=1), encoding='utf-8')
    return cur


def key_path() -> Path:
    """Per user (the home folder, not the shared data folder): ~/.calibration_suite/anthropic_api_key."""
    return Path.home() / '.calibration_suite' / 'anthropic_api_key'


_KEY_OK = re.compile(r'^[\x21-\x7e]{16,300}$')


def key_source() -> str:
    """'env' | 'file' | '' (none).  Says where a key is, never what it is."""
    if os.environ.get('ANTHROPIC_API_KEY', '').strip():
        return 'env'
    try:
        if key_path().is_file() and key_path().read_text(encoding='utf-8').strip():
            return 'file'
    except OSError:
        pass
    return ''


def get_key() -> str:
    env = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if env:
        return env
    try:
        return key_path().read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def save_key(key: str) -> str:
    """Store the key for this user with permissions 0600 (the folder 0700).  Returns '' or a warning (e.g. permissions cannot be restricted on this system)."""
    key = (key or '').strip()
    if not _KEY_OK.match(key):
        raise ValueError('That does not look like an API key (it should be one line of 16 or more printable characters, no spaces).')
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    warning = ''
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        warning = 'The permissions of the folder could not be restricted on this system.'
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(key + '\n')
    try:
        os.chmod(path, 0o600)
    except OSError:
        warning = 'The permissions of the key file could not be restricted on this system (it is in your own user folder).'
    return warning


def remove_key() -> bool:
    try:
        key_path().unlink()
        return True
    except OSError:
        return False


_KEYLIKE = re.compile(r'sk-ant-[A-Za-z0-9_\-]{6,}')


def scrub(text, key: str = '') -> str:
    """The text with the key (and anything shaped like one) blanked; the project's standard password / token scrub is applied too (qtui.app.scrub, diagnostics.scrub)."""
    t = str(text)
    for k in {key or '', get_key()}:
        if k and len(k) >= 8:
            t = t.replace(k, '<hidden>')
    t = _KEYLIKE.sub('<hidden>', t)
    try:
        import diagnostics
        t = diagnostics.scrub(t)
    except Exception:
        pass
    return t


# ============================================================================================================== page images
def renderer_name() -> str:
    """Which renderer this machine uses for page images: 'pypdfium2' | 'pdftoppm' | '' (none)."""
    try:
        import pypdfium2  # noqa: F401
        import PIL  # noqa: F401
        return 'pypdfium2'
    except Exception:
        pass
    return 'pdftoppm' if shutil.which('pdftoppm') else ''


class RenderError(RuntimeError):
    pass


def render_page(pdf, page: int, dpi: int, out) -> Path:
    """Render page `page` (1-based) of `pdf` to the PNG `out` (written atomically).  The PDF is only read."""
    pdf, out = Path(pdf), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.part')
    name = renderer_name()
    try:
        if name == 'pypdfium2':
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(str(pdf))
            try:
                doc[page - 1].render(scale=dpi / 72.0).to_pil().save(tmp, format='PNG')
            finally:
                doc.close()
        elif name == 'pdftoppm':
            stem = Path(tempfile.mkdtemp(prefix='pgpage_')) / 'p'
            subprocess.run(['pdftoppm', '-png', '-r', str(dpi), '-f', str(page), '-l', str(page), '-singlefile', str(pdf), str(stem)], check=True,
                           capture_output=True, timeout=120)
            shutil.move(str(stem) + '.png', tmp)
            shutil.rmtree(stem.parent, ignore_errors=True)
        else:
            raise RenderError('No PDF renderer is installed. Install pypdfium2 and pillow (py -m pip install pypdfium2 pillow).')
        os.replace(tmp, out)
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(f'Page {page} could not be drawn: {type(exc).__name__}: {exc}') from None
    finally:
        if tmp.exists():
            tmp.unlink()
    return out


def page_png(store: pg.Store, p: pg.Project, fid: str, page: int, dpi: int = DEFAULT_DPI) -> Path:
    """The cached PNG of one page (made on first use)."""
    src = store.file_path(p, fid)
    out = store.pages_dir(p.id, fid) / f'p{page:04d}_{dpi}.png'
    if not out.is_file():
        render_page(src, page, dpi, out)
    return out


# ============================================================================================================== the request
SYSTEM = (
    "You read tables of a calibration manual's PERFORMANCE VERIFICATION procedure from page IMAGES and report them as rows by calling the tool. "
    "Rules: (1) Report only what is printed. Copy every number exactly as printed, digit for digit, with the unit printed in the table (write micro as 'u' and ohm as 'ohm' "
    "or the symbol; keep k, M, m prefixes exactly). Never compute, convert, round, interpolate or fill a gap from memory or from what a typical meter does. "
    "(2) A test point is one row of a test table: the function, the range if printed, the nominal (input) value, a frequency or input level where the row has one, and the low "
    "and high limits the table prints (or, when the table prints only an accuracy statement, copy that statement into 'accuracy' and leave the limits empty). "
    "(3) Give every quantity as text including its unit, e.g. '10 mV', '1 kHz', '9.995 V'. If a unit is not printed for a column, take it from the column or table heading "
    "and write it out. (4) Set 'uncertain' to true and explain in 'confidence_note' whenever a digit, a sign, a unit, the row it belongs to or its function is hard to read "
    "or ambiguous; when unsure, say so rather than guess. (5) 'image' is the number of the image the row is on. 'step' is the step or row number printed in the table, if any. "
    "(6) Ignore text that is not a test point (introductions, notes, figures); do not invent rows. (7) 'function_kind' must be one of the allowed values; use CHECK for a "
    "pass / fail functional check with no numeric limits. For a thermocouple row give the thermocouple type letter in 'tc_type'."
)

KIND_HELP = ('DCV DC volts; ACV AC volts; DCI DC current; ACI AC current; OHM2 two-wire ohms; OHM4 four-wire ohms; CAP capacitance; FREQ frequency measured by the meter; '
             'PERIOD; TEMP temperature (degrees C); DIODE; CONT continuity; CHECK pass / fail check')

ITEM_PROPS = {
    'image': {'type': 'integer', 'description': 'Number of the image (1, 2, ...) this row is on.'},
    'step': {'type': 'string', 'description': 'Step or row number printed in the table, or empty.'},
    'function_kind': {'type': 'string', 'enum': list(pg.GEN_KINDS), 'description': KIND_HELP},
    'section': {'type': 'string', 'description': 'Heading of the table or group the row belongs to, as printed.'},
    'range': {'type': 'string', 'description': "Range as printed with unit, e.g. '100 mV', or empty."},
    'nominal': {'type': 'string', 'description': "The input / nominal value as printed with its unit, e.g. '10 mV'."},
    'frequency': {'type': 'string', 'description': "Frequency of the row as printed with unit, e.g. '1 kHz', or empty."},
    'level': {'type': 'string', 'description': "Input level where it is separate from the nominal (e.g. the amplitude of a frequency test), with unit, or empty."},
    'low_limit': {'type': 'string', 'description': 'Low limit as printed with unit, or empty.'},
    'high_limit': {'type': 'string', 'description': 'High limit as printed with unit, or empty.'},
    'accuracy': {'type': 'string', 'description': "Printed accuracy statement, e.g. '0.05 % of reading + 2 counts', ONLY when no limits are printed."},
    'tc_type': {'type': 'string', 'description': 'Thermocouple type letter for a thermocouple row, else empty.'},
    'uncertain': {'type': 'boolean', 'description': 'True when any value of this row was hard to read or ambiguous.'},
    'confidence_note': {'type': 'string', 'description': 'What is doubtful, or empty.'},
}
TOOL = {
    'name': TOOL_NAME,
    'description': 'Report every test point (row) found in the table images, exactly as printed.',
    'input_schema': {'type': 'object',
                     'properties': {'rows': {'type': 'array', 'items': {'type': 'object', 'properties': ITEM_PROPS,
                                                                          'required': ['image', 'function_kind', 'nominal', 'uncertain']}},
                                    'page_notes': {'type': 'string', 'description': 'Anything the reviewer should know about these pages (tables cut off, columns unreadable ...).'}},
                     'required': ['rows']},
}


def build_request(png_paths: list, labels: list, model: str) -> dict:
    """The keyword arguments of messages.create: page IMAGES (base64 PNG) and a short instruction; never extracted text."""
    content = []
    for i, (path, label) in enumerate(zip(png_paths, labels), 1):
        content.append({'type': 'text', 'text': f'Image {i} = {label}'})
        data = base64.standard_b64encode(Path(path).read_bytes()).decode('ascii')
        content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': data}})
    content.append({'type': 'text', 'text': f'Read every test point of the verification tables on these {len(png_paths)} image(s) and call the tool {TOOL_NAME}.'})
    return dict(model=model, max_tokens=MAX_TOKENS, system=SYSTEM, tools=[TOOL], tool_choice={'type': 'tool', 'name': TOOL_NAME},
                messages=[{'role': 'user', 'content': content}])


# ============================================================================================================== the call
class ExtractError(RuntimeError):
    """A reading failed; the text is safe to show (the key is scrubbed)."""


@dataclass
class ExtractResult:
    rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    requests: int = 0
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ''
    pages: list = field(default_factory=list)


TRANSIENT_NAMES = ('APIConnectionError', 'APITimeoutError', 'RateLimitError', 'InternalServerError', 'OverloadedError', 'ConnectionError', 'TimeoutError')


def is_transient(exc) -> bool:
    """A failed READ that may succeed if asked again: a dropped / timed-out connection, rate limiting, a server error (5xx, 529).  A bad key, a rejected request or an
    answer we cannot use is NOT transient (retrying would not help and, for a paid call, would only cost)."""
    code = getattr(exc, 'status_code', None)
    if isinstance(code, int):
        return code in (408, 409, 429) or code >= 500
    return any(c.__name__ in TRANSIENT_NAMES for c in type(exc).__mro__) or isinstance(exc, (ConnectionError, TimeoutError))


def make_client(key: str):
    try:
        import anthropic
    except ImportError:
        raise ExtractError('The "anthropic" package is not installed. Install it with:  py -m pip install anthropic') from None
    return anthropic.Anthropic(api_key=key, max_retries=0, timeout=180.0)       # our own capped retry loop below; the SDK's is off so a retry is always visible


def friendly(exc, key='') -> str:
    code = getattr(exc, 'status_code', None)
    name = type(exc).__name__
    if code in (401, 403):
        return 'The API key was refused. Check it in Settings (the key is not shown).'
    if code == 404:
        return 'The model name was not found. Check the model name in Settings.'
    if code == 400:
        return 'The request was rejected: ' + scrub(getattr(exc, 'message', '') or str(exc), key)[:300]
    if is_transient(exc):
        return ('Could not reach the Claude API (no network, or the service is busy). You can type the rows by hand in the review grid, or try again later. '
                f'({name}' + (f' {code}' if code else '') + ')')
    return f'{name}: ' + scrub(str(exc), key)[:300]


def _parse_rows(tool_input, mapping: list, notes: list) -> list:
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get('rows'), list):
        raise ExtractError('The answer did not have the expected table of rows.')
    if tool_input.get('page_notes'):
        notes.append(str(tool_input['page_notes'])[:600])
    rows = []
    for item in tool_input['rows']:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get('image'))
            fid, page = mapping[idx - 1]
        except (TypeError, ValueError, IndexError):
            fid, page = '', 0                                    # an image number we did not send: kept, with no page, so validation flags it
        text = lambda k: str(item.get(k) if item.get(k) is not None else '').strip()      # noqa: E731
        r = pg.Row('', file_id=fid, page=page, step=text('step'), function=text('function_kind'), section=text('section'), range=text('range'), nominal=text('nominal'),
                   frequency=text('frequency'), level=text('level'), low=text('low_limit'), high=text('high_limit'), accuracy=text('accuracy'), tc_type=text('tc_type').upper(),
                   uncertain=bool(item.get('uncertain')), note=text('confidence_note'), source='model')
        r.model_values = {**r.values(), 'page': r.page}
        rows.append(r)
    return rows


def extract(store: pg.Store, p: pg.Project, fid: str, first: int, last: int, client_factory=None, sleep=time.sleep, progress=None, settings=None) -> ExtractResult:
    """Read pages first..last of one uploaded manual into candidate rows (not yet in the project: the caller adds them with pg.add_rows).
    A READ-ONLY call: on a transient error the same request is sent again, at most MAX_ATTEMPTS in all; any other error ends the reading with a clear message.
    `client_factory(key)` and `sleep` are injectable (tests)."""
    settings = settings or load_settings()
    key = get_key()
    if not key:
        raise ExtractError('No API key. Add one in Settings (or set ANTHROPIC_API_KEY), or type the rows by hand in the review grid.')
    f = p.file(fid)
    if f is None or f.role != pg.ROLE_SPEC:
        raise ExtractError('Choose an uploaded spec sheet or manual.')
    pages = list(range(int(first), int(last) + 1))
    if not pages or pages[0] < 1 or (f.pages and pages[-1] > f.pages):
        raise ExtractError('Choose pages inside the manual.')
    if len(pages) > MAX_PAGES:
        raise ExtractError(f'{len(pages)} pages is too many for one reading (the limit is {MAX_PAGES}). Read the tables in parts.')
    try:
        client = (client_factory or make_client)(key)
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractError(friendly(exc, key)) from None
    res = ExtractResult(model=settings['model'], pages=pages)
    for start in range(0, len(pages), PAGES_PER_REQUEST):
        batch = pages[start:start + PAGES_PER_REQUEST]
        try:
            pngs = [page_png(store, p, fid, n, settings['dpi']) for n in batch]
        except RenderError as exc:
            raise ExtractError(str(exc)) from None
        labels = [f"page {n} of the file '{f.original}'" for n in batch]
        kwargs = build_request(pngs, labels, settings['model'])
        if progress:
            progress(f'Reading pages {batch[0]}-{batch[-1]} ...')
        resp = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            res.attempts += 1
            try:
                resp = client.messages.create(**kwargs)
                break
            except Exception as exc:
                if attempt < MAX_ATTEMPTS and is_transient(exc):
                    sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
                    continue
                raise ExtractError(friendly(exc, key)) from None
        res.requests += 1
        usage = getattr(resp, 'usage', None)
        res.input_tokens += int(getattr(usage, 'input_tokens', 0) or 0)
        res.output_tokens += int(getattr(usage, 'output_tokens', 0) or 0)
        if getattr(resp, 'stop_reason', '') == 'max_tokens':
            raise ExtractError('The answer was cut off (too many rows for one reading). Choose fewer pages and read again.')
        block = next((b for b in (getattr(resp, 'content', None) or []) if getattr(b, 'type', '') == 'tool_use' and getattr(b, 'name', '') == TOOL_NAME), None)
        if block is None:
            raise ExtractError('The answer did not contain the table of rows (the reader did not call the tool). Nothing was added.')
        res.rows += _parse_rows(getattr(block, 'input', None), [(fid, n) for n in batch], res.notes)
    return res
