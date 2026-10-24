"""'Calibration Data' PDF report.

    rows = [cert_row('Ch. 1 Impedance 100mV/Div', 1e6, 0.99e6, 1.01e6, 'ohm', reading=1.0002e6, section='Impedance'), ...]
    write_calibration_pdf('report.pdf', rows, header=[('Instrument', 'WaveSurfer 4104HD'), ('Instrument ID', 'A123')],
                          details=report_dialog.ask_details(root))

Layout: title, header strip, overall verdict, grouped table (shaded rows, out-of-tolerance rows tinted red),
'Page x of y' with the instrument ID on every page.  Needs reportlab (py -m pip install reportlab).
"""
from __future__ import annotations

from collections import namedtuple
from datetime import datetime

COLUMNS = ('Description', 'Nominal', 'Tolerance -', 'Tolerance +', 'UOM', 'As Found', 'OOT', 'As Left', 'Uncertainty')
LIMIT_HEADINGS = {'Tolerance -': 'Low Limit', 'Tolerance +': 'High Limit'}     # what the two limit columns are called when details['limit_labels'] is set
TAR_TUR_COLUMNS = ('TAR', 'TUR')          # optional, after Uncertainty; each only when the user ticks its checkbox (default off)


# ---------------------------------------------------------------------------------------------- optional TAR / TUR
# The choice lives in report_dialog.ask_details (details['show_tar_tur']) and is remembered in ~/.calibration_suite/report_tartur.json.
# Everything below is inert unless the flag is on: with it off every export is identical to what it was before this feature.
_TAR_DEF = ('TAR (test accuracy ratio) is the unit under test tolerance, taken as half the width of its pass/fail limits at the test point, '
            'divided by the accuracy specification of the standard used.')
_TUR_DEF = ('TUR (test uncertainty ratio) is the unit under test tolerance, taken as half the width of its pass/fail limits at the test point, '
            'divided by the reported expanded uncertainty of the measurement.')
_TAR_TUR_PLACEHOLDER = _TAR_DEF + ' ' + _TUR_DEF


class TarTur(namedtuple('TarTur', 'tar tur')):
    """Which of the optional columns are selected.  Immutable; truthy if either is on, so a value that used to be a plain
    bool (details.get('show_tar_tur')) keeps working.  A plain True / False anywhere means both on / both off."""
    __slots__ = ()

    def __bool__(self):
        return bool(self.tar or self.tur)


def as_tar_tur(value) -> TarTur:
    """Normalise None / bool / TarTur / (tar, tur) pair to a TarTur."""
    if isinstance(value, TarTur):
        return value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return TarTur(bool(value[0]), bool(value[1]))
    return TarTur(bool(value), bool(value))


def details_tar_tur(details) -> TarTur:
    """Selection carried by a details dict: 'show_tar_tur' (bool or TarTur), else the separate 'show_tar' / 'show_tur' keys."""
    details = details or {}
    if 'show_tar_tur' in details:
        return as_tar_tur(details['show_tar_tur'])
    return TarTur(bool(details.get('show_tar')), bool(details.get('show_tur')))


def settings_path():
    from pathlib import Path
    return Path.home() / '.calibration_suite' / 'report_tartur.json'


def remembered_show_tar_tur(path=None) -> TarTur:
    """The last choice of the two checkboxes; both off on first run or if the file is missing or unreadable. Never raises.
    An old file with the single key show_tar_tur: true means both on."""
    import json
    try:
        from pathlib import Path
        data = json.loads(Path(path or settings_path()).read_text(encoding='utf-8'))
        if 'show_tar' in data or 'show_tur' in data:
            return TarTur(bool(data.get('show_tar', False)), bool(data.get('show_tur', False)))
        return as_tar_tur(bool(data.get('show_tar_tur', False)))
    except Exception:
        return TarTur(False, False)


def remember_show_tar_tur(value, path=None) -> bool:
    """Store the choice (bool or TarTur); returns False (and does nothing else) if the file cannot be written. Never raises."""
    import json
    try:
        from pathlib import Path
        v = as_tar_tur(value)
        p = Path(path or settings_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'show_tar': v.tar, 'show_tur': v.tur}, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def tar_tur_definition(show=None) -> str:
    """Footer paragraph defining the selected term(s) (default both).  Both: tartur.definition_text() (placeholder text if the
    module is not present); one term: its own sentence plus the shared closing sentence about blank ratios."""
    v = TarTur(True, True) if show is None else as_tar_tur(show)
    full = ''
    try:
        import tartur
        full = str(tartur.definition_text() or '')
    except Exception:
        pass
    if v.tar and v.tur:
        return full or _TAR_TUR_PLACEHOLDER
    if not (v.tar or v.tur):
        return ''
    sentences = [x.strip() for x in full.replace('. ', '.\n').split('\n') if x.strip()]
    own = next((x for x in sentences if x.startswith('TAR' if v.tar else 'TUR')), '')
    if v.tur and own.startswith('TUR') and 'same tolerance' in own:   # tartur's TUR sentence refers back to the TAR one
        own = own.replace('is the same tolerance', 'is the unit under test tolerance (half the width of its pass/fail limits at the test point)')
    tail = ' '.join(x for x in sentences if x.startswith('Ratios')) or ''
    if not own:
        own = _TAR_DEF if v.tar else _TUR_DEF
    if v.tar and own.startswith('TAR') and full and 'TUR' in own:
        own = _TAR_DEF
    return f'{own} {tail}'.strip()


def shown_tar_tur_columns(rows, show) -> tuple:
    """The selected columns that have at least one non-blank value, in TAR, TUR order."""
    v = as_tar_tur(show)
    return tuple(c for c, on in zip(TAR_TUR_COLUMNS, v) if on and any(str(r.get(c) or '').strip() for r in rows))


def has_tar_tur(rows, show=True) -> bool:
    return bool(shown_tar_tur_columns(rows, show))


def apply_tar_tur(rows, show, point_fields):
    """Rows with the selected 'TAR' / 'TUR' merged in.  show: bool or TarTur.  point_fields is a sequence parallel to rows
    (each a dict like tartur.row_fields(p, low, high, standard) returns, or None) or a callable row -> dict.  With nothing selected
    the rows are returned untouched (same list).  Input rows are never modified."""
    v = as_tar_tur(show)
    if not v:
        return rows
    keys = [c for c, on in zip(TAR_TUR_COLUMNS, v) if on]
    out = []
    for i, row in enumerate(rows):
        f = point_fields(row) if callable(point_fields) else (point_fields[i] if i < len(point_fields) else None)
        f = f or {}
        out.append(dict(row, **{c: str(f.get(c) or '') for c in keys}))
    return out


_FONT_CANDIDATES = (
    ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
    ('/Library/Fonts/Arial.ttf', '/Library/Fonts/Arial Bold.ttf'),
    ('/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
    ('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
)


def _fonts():
    """(regular, bold, embedded). Embeds Arial/Liberation/DejaVu when found so the micro sign always prints;
    otherwise falls back to the built-in Helvetica (the viewer substitutes a font for the micro sign)."""
    from pathlib import Path
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).is_file() and Path(bold).is_file():
            try:
                pdfmetrics.registerFont(TTFont('CalReg', regular))
                pdfmetrics.registerFont(TTFont('CalBold', bold))
                pdfmetrics.registerFontFamily('CalReg', normal='CalReg', bold='CalBold', italic='CalReg', boldItalic='CalBold')
                return 'CalReg', 'CalBold', True
            except Exception:
                continue
    return 'Helvetica', 'Helvetica-Bold', False


def ascii_unit(unit: str) -> str:
    """Report-safe unit text: the standard PDF fonts have no Omega, so ohms are spelled 'Ohm' (kOhm, MOhm)."""
    return unit.replace('Ω', 'Ohm').replace('Ω', 'Ohm')


def _decimals(text) -> int:
    text = str(text)
    return len(text.split('.')[1]) if '.' in text else 0


def _tidy(reading: str, limit_decimals: int) -> str:
    """Drop trailing zeros beyond the resolution of the limits (100.021000 -> 100.0210 when limits have 4 decimals)."""
    while '.' in reading and _decimals(reading) > limit_decimals and reading.endswith('0'):
        reading = reading[:-1]
    return reading.rstrip('.') if reading.endswith('.') else reading


KIND_NAMES = {'DCV': 'DC Volts', 'ACV': 'AC Volts', 'DCI': 'DC Current', 'ACI': 'AC Current', 'OHM2': '2-wire Ohms',
              'OHM4': '4-wire Ohms', 'FREQ': 'Frequency', 'CAP': 'Capacitance'}


def _trim(number: str) -> str:
    """'1.000' -> '1', '100.0' -> '100', '2.500' -> '2.5' (labels only; limits keep their resolution)."""
    return number.rstrip('0').rstrip('.') if '.' in number else number


def _freq_text(hz) -> str:
    import ui_theme as ui
    number, unit = ui.si_one(hz, 'Hz')
    return f'{_trim(number)} {unit}'


def _si(value, unit) -> str:
    import ui_theme as ui
    number, symbol = ui.si_one(value, unit)
    return ascii_unit(f'{_trim(number)} {symbol}')


def point_description(p) -> str:
    """Short description for the report. The stimulus (nominal and frequency) lives in the Nominal column and the
    function in the section heading, so this is just the range, plus the filter and, for zero offsets, the input."""
    kind = p['kind']
    zero = p.get('zero_offset') or p.get('source') == 'none'
    range_text = _si(p['range'], 'V' if kind == 'FREQ' else p['unit']) + ' range'
    if zero:
        state = p.get('input') or ('open' if kind in ('DCI', 'ACI') else 'shorted')
        return f'{KIND_NAMES[kind]}, {range_text} ({state})'
    parts = [range_text]
    if p.get('filter_hz'):
        parts.append(f"{p['filter_hz']:g} Hz filter")
    if p.get('mixed'):                       # a section that mixes functions needs the function name
        parts.insert(0, KIND_NAMES[kind])
    return ', '.join(parts)


_SCOPE = {}


def scope():
    """The laboratory's A2LA scope (specs/a2la_1888_03_cmc.json), loaded once; None if it is not installed."""
    if 'scope' not in _SCOPE:
        try:
            import uncertainty
            _SCOPE['scope'] = uncertainty.load()
        except Exception:
            _SCOPE['scope'] = None
    return _SCOPE['scope']


def point_uncertainty(p, standard=None) -> str:
    """Uncertainty for a verification point, formatted for the report; '' if the scope does not cover it.
    Without `standard` this is the scope CMC.  With the calibrator that applied the point (model text such as '5522A', see specmanager) the
    value is the larger of the budget built from that standard's published specification and the CMC, rounded up: never below the CMC."""
    sc = scope()
    if sc is None or p.get('source') == 'none':      # zero-offset points (short / open input) use no source, so no source CMC applies
        return ''
    import uncertainty
    unit = 'ohm' if p['kind'].startswith('OHM') else p['unit']
    if p['kind'] == 'FREQ':
        standard = None             # a frequency is measured against the GPS-referenced lab standard: the 'Frequency - Measure' CMC ALONE, never combined with the calibrator's own frequency accuracy
    if standard:
        try:
            import uncertainty_budget
            b = uncertainty_budget.build(p['kind'], p['nominal'], unit, standard=standard, frequency=p.get('frequency'), scope=sc, range_value=p.get('range'))
            if b.reported is not None:
                return uncertainty.format_value(b.reported, unit)
        except Exception:
            pass                                        # fall back to the CMC rather than lose the report
    value = sc.dmm(p['kind'], p['nominal'], p.get('range'), p.get('frequency'))
    return uncertainty.format_value(value, unit) if value is not None else ''


def uncertainty_note(rows, standard=None) -> str:
    """Footer text: where the uncertainties come from, and how many points the scope does not cover."""
    sc = scope()
    if sc is None or not any(r.get('Uncertainty') for r in rows):
        return ''
    blank = sum(1 for r in rows if not r.get('Uncertainty'))
    note = sc.citation
    if standard:
        note += (f' Where the published specification of the {standard} calibrator (divided by its coverage divisor, with the calibrator resolution) '
                 'gives a larger uncertainty than the CMC, the larger value is reported.')
    if blank:
        note += f' {blank} of {len(rows)} points show no uncertainty because the scope of accreditation does not cover them.'
    return note


def point_row(p, reading, failed, section='', mixed=False, standard=None):
    """Report row for a verification point dict (kind, nominal, range, unit, error or low/high, frequency ...)."""
    zero = p.get('zero_offset') or p.get('source') == 'none'
    low = p['low'] if 'low' in p else p['nominal'] - p['error']
    high = p['high'] if 'high' in p else p['nominal'] + p['error']
    q = dict(p, mixed=mixed)
    freq = None if (zero or p['kind'] == 'FREQ') else p.get('frequency')
    return cert_row(point_description(q), p['nominal'], low, high, p['unit'], reading, failed, section=section, frequency=freq,
                    uncertainty=point_uncertainty(p, standard))


def cert_row(description, nominal, low, high, unit, reading=None, failed=False, as_left='Same', uncertainty='',
             nominal_text=None, section='', frequency=None):
    """One report row from base-unit numbers. Display scaling (6 mV, 1.00 MOhm) matches the on-screen tables;
    reading=None gives an untested row. Limits are the ABSOLUTE low/high values, as on the certificate."""
    import ui_theme as ui
    vals, reads, unit_text = ui.si_row([nominal, low, high], unit, [] if reading is None else [reading])
    unit_text = ascii_unit(unit_text)
    limit_dp = max(_decimals(vals[1]), _decimals(vals[2]))
    return {
        'Section': section,
        'Description': ascii_unit(description),
        'Nominal': nominal_text or (f'{vals[0]} {unit_text}'.strip() + (f' @ {_freq_text(frequency)}' if frequency else '')),
        'Tolerance -': vals[1], 'Tolerance +': vals[2], 'UOM': unit_text,
        'As Found': _tidy(reads[0], limit_dp) if reads else '',
        'OOT': 'OOT' if failed else '',
        'As Left': as_left if reading is not None else '',
        'Uncertainty': uncertainty,
    }


# Shown on the lab's cover certificate instead, so left off this report. They are still passed in (and kept in the asset history).
HEADER_HIDDEN = {'Limits applied', 'Source', 'Procedure', 'Technician', 'Temperature', 'Humidity'}
# The standards-used table and the Performed by / Reviewed by / Date block are on the cover certificate too, so they are not drawn.
# So is the footnote under the table (footer_note is accepted and ignored).


def _mod_lines(modifications) -> list:
    """Summary dicts for the modifications block: the list from procmods.modifications_for_report / modifications_summary, or an
    OverrideSet.  Anything else (None, empty, unreadable) means no block."""
    if not modifications:
        return []
    try:
        if not isinstance(modifications, (list, tuple)):
            import procmods
            modifications = procmods.modifications_summary(modifications)
        return [m for m in modifications if isinstance(m, dict)]
    except Exception:
        return []


def context_for(app) -> dict:
    """Version stamps of an engine's App for the report snapshot (report_snapshot.context_for); pass as write_calibration_pdf(snapshot_context=...).
    Never raises."""
    try:
        import report_snapshot
        return report_snapshot.context_for(app)
    except Exception:
        return {}


DEMO_FOOTER_TEXT = 'DEMO DATA - NOT CALIBRATION EVIDENCE'


def demo_footer_left(text, font, size, margin, page_width, demo_font, demo_size, gap=8.0):
    """Left page-footer text for a DEMO report: cut with '...' so it ends before the centred red demo line (a long title would print over it)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    limit = page_width / 2 - stringWidth(DEMO_FOOTER_TEXT, demo_font, demo_size) / 2 - gap - margin
    if stringWidth(text, font, size) <= limit:
        return text
    while text and stringWidth(text + '...', font, size) > limit:
        text = text[:-1]
    return text.rstrip() + '...'


def write_calibration_pdf(path, rows, header=None, title='Calibration Data', demo=False, details=None, footer_note='', show_tar_tur=None, modifications=None,
                          issued_at=None, reprint_note=None, record_history=True, snapshot_context=None):
    """Write the report; returns the number of data rows.

    header   list of (label, value) shown under the title
    details  optional dict from report_dialog.ask_details: technician, temperature, humidity, standards[]
    show_tar_tur  None (default) follows details['show_tar_tur'] (bool or TarTur; default off); a bool or TarTur forces it.  Each selected
             kind with at least one value gets a column after Uncertainty; the definition of the shown term(s) is printed under the table.
    issued_at / reprint_note / record_history  used only to print a saved report again (report_snapshot.py): issued_at (text 'YYYY-MM-DD HH:MM' or a
             datetime) replaces the 'Report date' of the header; reprint_note is one line drawn in the page footer of every page (the data pages are
             otherwise identical); record_history=False writes no Asset History event and no snapshot.  All default to the old behaviour.
    snapshot_context  version stamps from context_for(app), stored with the report snapshot (see report_snapshot.py); no effect on the PDF."""
    mods = _mod_lines(modifications)
    show_tar_tur_arg = show_tar_tur                    # as passed (the name is reused below for the effective choice); kept for the report snapshot
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    # keep each section together (rows of one section may arrive interleaved), in order of first appearance
    order = {}
    for row in rows:
        order.setdefault(row.get('Section') or '', len(order))
    rows = sorted(rows, key=lambda r: order[r.get('Section') or ''])
    details = details or {}
    columns = COLUMNS
    selected = details_tar_tur(details) if show_tar_tur is None else as_tar_tur(show_tar_tur)
    extra = shown_tar_tur_columns(rows, selected)
    columns = COLUMNS + extra
    show_tar_tur = bool(extra)
    shown_sel = TarTur('TAR' in extra, 'TUR' in extra)
    REG, BOLD, embedded = _fonts()
    header = list(header or [])
    instrument_id = next((v for k, v in header if k == 'Instrument ID'), '') or ''
    W, H = letter
    margin = 0.5 * inch

    small = ParagraphStyle('s', fontName=REG, fontSize=6.6, leading=8)
    head_style = ParagraphStyle('h', parent=small, fontSize=6.8, fontName=BOLD)
    red = ParagraphStyle('r', parent=small, fontName=BOLD, textColor=colors.HexColor('#B00020'))
    section_style = ParagraphStyle('sec', parent=small, fontName=BOLD, fontSize=7.4, leading=9, textColor=colors.HexColor('#1F2A44'))
    title_style = ParagraphStyle('t', fontName=BOLD, fontSize=13, leading=16, alignment=1)
    meta = ParagraphStyle('m', parent=small, fontSize=7.4, leading=10, textColor=colors.HexColor('#222222'))
    verdict_pass = ParagraphStyle('vp', parent=small, fontName=BOLD, fontSize=8.6, leading=11, textColor=colors.HexColor('#1B6E3A'))
    verdict_fail = ParagraphStyle('vf', parent=verdict_pass, textColor=colors.HexColor('#B00020'))

    def clean(value):
        return ('' if value is None else str(value)).replace('μ', 'µ').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # ---- header strip ---------------------------------------------------------------------------------
    report_date = issued_at if isinstance(issued_at, str) and issued_at else (issued_at or datetime.now()).strftime('%Y-%m-%d %H:%M')
    info = header + [('Procedure', details.get('procedure')), ('Technician', details.get('technician')),
                     ('Temperature', details.get('temperature')), ('Humidity', details.get('humidity')),
                     ('Report date', report_date)]
    info = [(k, v) for k, v in info if v not in (None, '') and k not in HEADER_HIDDEN]
    story = [Paragraph(f'<u>{clean(title)}</u>', title_style), Spacer(1, 6)]
    # two items per line keeps long source citations from running off the page
    pairs = [info[i:i + 3] for i in range(0, len(info), 3)]
    for group in pairs:
        story.append(Paragraph('&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;'.join(f'<b>{clean(k)}:</b> {clean(v)}' for k, v in group), meta))
    story.append(Spacer(1, 6))
    tol_modified = any(m.get('limit') or m.get('tolerances_modified') for m in mods)
    if tol_modified:
        story.append(Paragraph("Tolerances in this report were modified from the manufacturer's specification - see Procedure modifications. "
                               'PASS/FAIL is judged against the tolerance used.', red))
        story.append(Spacer(1, 6))

    # ---- verdict --------------------------------------------------------------------------------------
    total = len(rows)
    failed = [r for r in rows if r.get('OOT')]
    if total:
        if failed:
            names = '; '.join(clean(r['Description']) for r in failed[:8]) + (f'; and {len(failed) - 8} more' if len(failed) > 8 else '')
            story.append(Paragraph(f'RESULT: OUT OF TOLERANCE — {len(failed)} of {total} points outside limits', verdict_fail))
            story.append(Paragraph(names, meta))
        else:
            story.append(Paragraph(f'RESULT: PASS — all {total} points within tolerance', verdict_pass))
        story.append(Spacer(1, 6))
    left_rows = [r for r in rows if str(r.get('As Left') or '') not in ('', 'Same')]      # points measured again after an adjustment
    if left_rows:
        left_bad = [r for r in left_rows if r.get('As Left OOT')]
        if left_bad:
            story.append(Paragraph(f'AS LEFT: OUT OF TOLERANCE — {len(left_bad)} of {len(left_rows)} points measured after adjustment '
                                   'are still outside limits', verdict_fail))
        else:
            story.append(Paragraph(f'AS LEFT: PASS — all {len(left_rows)} points measured after adjustment are within tolerance', verdict_pass))
        story.append(Paragraph("Points without an As Left reading were not adjusted (shown as 'Same').", meta))
        story.append(Spacer(1, 6))

    # Standards used and the signature block are on the lab's cover certificate, so they are not printed here.

    # ---- table with section headings ------------------------------------------------------------------
    right = {'Nominal', 'Tolerance -', 'Tolerance +', 'As Found', 'Uncertainty', 'TAR', 'TUR'}
    centre = {'UOM', 'OOT', 'As Left'}

    def style_for(col, base, align=None):
        return ParagraphStyle(f'a_{col}_{base.name}_{align}', parent=base,
                              alignment=align if align is not None else 2 if col in right else 1 if col in centre else 0)

    has_uncertainty = any(r.get('Uncertainty') for r in rows)
    # The row keys stay 'Tolerance -' / 'Tolerance +' (snapshots, history and every engine use them); the two columns hold the ABSOLUTE low and high
    # limits.  A report that asks for it (details['limit_labels'], set by the Datasheet Builder runtime) prints them as Low Limit / High Limit.
    heading = LIMIT_HEADINGS if details.get('limit_labels') else {}
    data = [[Paragraph(heading.get(c, c), style_for(c, head_style)) for c in columns]]
    spans, tints, last_section, shade = [], [], None, 0
    for row in rows:
        sec = row.get('Section') or ''
        if sec and sec != last_section:
            data.append([Paragraph(clean(sec), section_style)] + [''] * (len(columns) - 1))
            spans.append(len(data) - 1)
            last_section, shade = sec, 0
        cells = []
        for col in columns:
            value = row.get(col, '')
            if col == 'Uncertainty' and not value and has_uncertainty:
                value = 'N/A'          # the scope of accreditation has no entry for this point
            if col in TAR_TUR_COLUMNS and not str(value or '').strip():
                value = 'N/A'          # no ratio for this point (same rule as Uncertainty)
            if col == 'As Left' and str(value) not in ('', 'Same'):          # an As Left reading: right aligned like As Found, red if still OOT
                if row.get('As Left OOT'):
                    value = f'{value} OOT'
                cells.append(Paragraph(clean(value), style_for(col, red if row.get('As Left OOT') else small, 2)))
                continue
            cells.append(Paragraph(clean(value), style_for(col, red if col == 'OOT' and value else small)))
        data.append(cells)
        i = len(data) - 1
        if row.get('OOT'):
            tints.append((i, '#F8D7DA'))
        elif shade % 2 == 1:
            tints.append((i, '#EAEAEA'))
        shade += 1

    widths = [2.3, 0.95, 0.66, 0.66, 0.5, 0.66, 0.34, 0.5, 0.74]
    if left_rows:                                      # room for the As Left readings
        widths[0] -= 0.34
        widths[7] += 0.34
    if show_tar_tur:                                   # two narrow columns, paid for mostly by the description
        widths = widths + [0.5] * len(extra)
        widths[0] -= 0.275 * len(extra)
    scale = (W - 2 * margin) / (sum(widths) * inch)
    widths = [w * inch * scale for w in widths]
    table = LongTable(data, colWidths=widths, repeatRows=1)
    style = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, 0), 0.8, colors.black),
             ('TOPPADDING', (0, 0), (-1, -1), 1.6), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.6),
             ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3)]
    for i, colour in tints:
        style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor(colour)))
    for i in spans:
        style += [('SPAN', (0, i), (-1, i)), ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#D5DCE8')),
                  ('TOPPADDING', (0, i), (-1, i), 2), ('BOTTOMPADDING', (0, i), (-1, i), 1.5)]
    table.setStyle(TableStyle(style))
    story.append(table)
    # footer_note (uncertainty source, method notes) is not printed: that information is on the lab's cover certificate.
    if show_tar_tur:                                   # only when the optional columns are on
        story += [Spacer(1, 6), Paragraph(clean(tar_tur_definition(shown_sel)), meta)]

    if mods:                                           # only when the run had overrides: unmodified reports are unchanged
        story += [Spacer(1, 8), Paragraph('Procedure modifications', section_style)]
        mdata = [[Paragraph(c, head_style) for c in ('Kind', 'Item', 'Factory', 'Used', 'Ver', 'Reason', 'Date')]]
        for m in mods:
            mdata.append([Paragraph(clean(x), small) for x in (m.get('kind'), m.get('item') or m.get('text'), m.get('factory'),
                                                               m.get('used'), m.get('version'), m.get('reason'), m.get('date'))])
        mt = LongTable(mdata, colWidths=[w * (W - 2 * margin) for w in (0.09, 0.22, 0.17, 0.17, 0.05, 0.22, 0.08)], repeatRows=1)
        mt.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, 0), 0.8, colors.black),
                                ('TOPPADDING', (0, 0), (-1, -1), 1.6), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.6)]))
        story.append(mt)
        if tol_modified and show_tar_tur:
            story.append(Paragraph('TAR and TUR use the tolerance printed in this report (the modified one).', meta))

    # ---- page furniture -------------------------------------------------------------------------------
    class Numbered(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            count = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._furniture(count)
                super().showPage()
            super().save()

        def _furniture(self, count):
            self.saveState()
            self.setLineWidth(1.1)
            self.line(margin, H - 0.42 * inch, W - margin, H - 0.42 * inch)
            self.line(margin, 0.5 * inch, W - margin, 0.5 * inch)
            self.setFont(REG, 7)
            try:
                import suite_info
                software = f'{suite_info.NAME} {suite_info.full_version()}   |   '
            except ImportError:
                software = ''
            self.drawRightString(W - margin, 0.34 * inch, f'{software}Page {self._pageNumber} of {count}')
            left = f'Instrument ID: {instrument_id or "-"}   |   {title}'
            if demo:                                   # non-demo footers are unchanged
                left = demo_footer_left(left, REG, 7, margin, W, BOLD, 8)
            self.drawString(margin, 0.34 * inch, left)
            if demo:
                self.setFillColorRGB(0.85, 0.2, 0.2); self.setFont(BOLD, 8)
                self.drawCentredString(W / 2, 0.34 * inch, DEMO_FOOTER_TEXT)
                self.setFillAlpha(0.10)
                self.setFillColorRGB(0.85, 0.1, 0.1); self.setFont(BOLD, 74)
                self.translate(W / 2, H / 2); self.rotate(45)
                self.drawCentredString(0, 0, 'DEMO DATA')
            self.restoreState()
            if reprint_note:                           # a reprint: one line in the page footer, drawn last; nothing is added to the data area
                self.saveState()
                self.setFont(BOLD, 6.2); self.setFillColorRGB(0.69, 0, 0.13)
                self.drawString(margin, 0.56 * inch, str(reprint_note))
                self.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=margin, rightMargin=margin,
                            topMargin=0.62 * inch, bottomMargin=0.68 * inch, title=title, author='Calibration Suite',
                            **({'subject': str(reprint_note)} if reprint_note else {}))
    doc.build(story, canvasmaker=Numbered)
    if not demo and record_history:                # asset history (lab_registry.sqlite3); never affects the report
        run_id = None
        try:
            import labregistry
            run_id = labregistry.record_run(header, rows, details, report_file=path)
        except Exception:
            pass
        try:                                       # the snapshot that lets Asset History print this report again (report_snapshot.py)
            import report_snapshot
            report_snapshot.record_issued(run_id, header=header, rows=rows, title=title, details=details, footer_note=footer_note,
                                          show_tar_tur=show_tar_tur_arg, modifications=mods, issued_at=report_date, context=snapshot_context, demo=demo)
        except Exception:
            pass
    return total
