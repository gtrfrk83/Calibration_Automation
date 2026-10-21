"""'Calibration Data' PDF report.

    rows = [cert_row('Ch. 1 Impedance 100mV/Div', 1e6, 0.99e6, 1.01e6, 'ohm', reading=1.0002e6, section='Impedance'), ...]
    write_calibration_pdf('report.pdf', rows, header=[('Instrument', 'WaveSurfer 4104HD'), ('Instrument ID', 'A123')],
                          details=report_dialog.ask_details(root))

Layout: title, header strip, overall verdict, grouped table (shaded rows, out-of-tolerance rows tinted red),
'Page x of y' with the instrument ID on every page.  Needs reportlab (py -m pip install reportlab).
"""
from __future__ import annotations

from datetime import datetime

COLUMNS = ('Description', 'Nominal', 'Tolerance -', 'Tolerance +', 'UOM', 'As Found', 'OOT', 'As Left', 'Uncertainty')


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


def write_calibration_pdf(path, rows, header=None, title='Calibration Data', demo=False, details=None, footer_note=''):
    """Write the report; returns the number of data rows.

    header   list of (label, value) shown under the title
    details  optional dict from report_dialog.ask_details: technician, temperature, humidity, standards[]"""
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
    info = header + [('Procedure', details.get('procedure')), ('Technician', details.get('technician')),
                     ('Temperature', details.get('temperature')), ('Humidity', details.get('humidity')),
                     ('Report date', datetime.now().strftime('%Y-%m-%d %H:%M'))]
    info = [(k, v) for k, v in info if v not in (None, '') and k not in HEADER_HIDDEN]
    story = [Paragraph(f'<u>{clean(title)}</u>', title_style), Spacer(1, 6)]
    # two items per line keeps long source citations from running off the page
    pairs = [info[i:i + 3] for i in range(0, len(info), 3)]
    for group in pairs:
        story.append(Paragraph('&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;'.join(f'<b>{clean(k)}:</b> {clean(v)}' for k, v in group), meta))
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

    # Standards used and the signature block are on the lab's cover certificate, so they are not printed here.

    # ---- table with section headings ------------------------------------------------------------------
    right = {'Nominal', 'Tolerance -', 'Tolerance +', 'As Found', 'Uncertainty'}
    centre = {'UOM', 'OOT', 'As Left'}

    def style_for(col, base):
        return ParagraphStyle(f'a_{col}_{base.name}', parent=base, alignment=2 if col in right else 1 if col in centre else 0)

    has_uncertainty = any(r.get('Uncertainty') for r in rows)
    data = [[Paragraph(c, style_for(c, head_style)) for c in COLUMNS]]
    spans, tints, last_section, shade = [], [], None, 0
    for row in rows:
        sec = row.get('Section') or ''
        if sec and sec != last_section:
            data.append([Paragraph(clean(sec), section_style)] + [''] * (len(COLUMNS) - 1))
            spans.append(len(data) - 1)
            last_section, shade = sec, 0
        cells = []
        for col in COLUMNS:
            value = row.get(col, '')
            if col == 'Uncertainty' and not value and has_uncertainty:
                value = 'N/A'          # the scope of accreditation has no entry for this point
            cells.append(Paragraph(clean(value), style_for(col, red if col == 'OOT' and value else small)))
        data.append(cells)
        i = len(data) - 1
        if row.get('OOT'):
            tints.append((i, '#F8D7DA'))
        elif shade % 2 == 1:
            tints.append((i, '#EAEAEA'))
        shade += 1

    widths = [2.3, 0.95, 0.66, 0.66, 0.5, 0.66, 0.34, 0.5, 0.74]
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
            self.drawRightString(W - margin, 0.34 * inch, f'Page {self._pageNumber} of {count}')
            self.drawString(margin, 0.34 * inch, f'Instrument ID: {instrument_id or "-"}   |   {title}')
            if demo:
                self.setFillColorRGB(0.85, 0.2, 0.2); self.setFont(BOLD, 8)
                self.drawCentredString(W / 2, 0.34 * inch, 'DEMO DATA - NOT CALIBRATION EVIDENCE')
                self.setFillAlpha(0.10)
                self.setFillColorRGB(0.85, 0.1, 0.1); self.setFont(BOLD, 74)
                self.translate(W / 2, H / 2); self.rotate(45)
                self.drawCentredString(0, 0, 'DEMO DATA')
            self.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=margin, rightMargin=margin,
                            topMargin=0.62 * inch, bottomMargin=0.68 * inch, title=title, author='Calibration Suite')
    doc.build(story, canvasmaker=Numbered)
    if not demo:                                   # asset history (lab_registry.sqlite3); never affects the report
        try:
            import labregistry
            labregistry.record_run(header, rows, details, report_file=path)
        except Exception:
            pass
    return total
