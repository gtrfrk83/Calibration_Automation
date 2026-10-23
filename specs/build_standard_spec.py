"""Builds specs/standards/<model>_standard.json from a SpecTrack ("MudCats Specsheet") PDF of a calibration STANDARD.

    python specs/build_standard_spec.py "5522 specs.pdf" "5560a specs.pdf"          # writes specs/standards/fluke_5522a_standard.json ...
    python specs/build_standard_spec.py sheet.pdf --out somewhere.json

Needs pdfplumber (build time only; the suite itself reads the JSON).  The sheet is an indented tree:
    function  (Voltage, DC)            x = 83 pt   icon colour = input or output
      range   (329.9999 mV)            x = 97 pt
        parameter / specification      x = 110 pt   (value range, frequency band, [1 yr] / [90 day] Accuracy)
Nothing is guessed: text that does not parse is kept in 'raw' and reported, and every suspicious row is listed under 'problems'
(see specmanager.validate).  Per the project rule, check limit rows against the rendered page images (pdftoppm -r 110) - the
extracted text here has correct micro / ohm signs, but compare a few rows anyway.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402  (units, parsing helpers live there so the UI importer shares them)

X_FUNCTION, X_RANGE, X_PARAM = 83, 97, 110
# Confidence level printed in the manufacturer's manual where the SpecTrack sheet says [Not Specified] (NOTES.md, "Confidence level rule").
MANUAL_CONFIDENCE = {
    '5522A': (99.0, '99 % (5522A Operators Manual, General Specifications, printed p. 1-8: "Specification Confidence Interval 99 %"; '
                    'the SpecTrack sheet itself prints [Not Specified])'),
}

HEADER_FIELDS = {'Manufacturer': 'manufacturer', 'Model': 'model', 'Description': 'description', 'Confidence Level': 'confidence_text',
                 'Reference': 'reference', 'Revision': 'revision', 'Author': 'author', 'Approved By': 'approved_by', 'Approve Date': 'approve_date'}


def _icon_direction(page, top):
    """'output' for the red-arrow function icon, 'input' for the blue one, None if no icon is found on that line."""
    for im in page.images:
        if abs(im['top'] - top) < 4 and im['x0'] < 75:
            data = im['stream'].get_data()
            red = sum(1 for i in range(0, len(data) - 2, 3) if data[i] > 150 and data[i + 1] < 90 and data[i + 2] < 90)
            blue = sum(1 for i in range(0, len(data) - 2, 3) if data[i + 2] > 150 and data[i] < 90 and data[i + 1] < 120)
            return 'output' if red >= 14 else 'input' if blue and red < 14 else None
    return None


def read_lines(pdf_path):
    import pdfplumber
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            rows = defaultdict(list)
            for w in page.extract_words():
                rows[round(w['top'])].append(w)
            for top in sorted(rows):
                ws = sorted(rows[top], key=lambda w: w['x0'])
                text = ' '.join(w['text'] for w in ws)
                out.append(dict(page=number, x=round(ws[0]['x0']), text=text, direction=_icon_direction(page, top)))
    return out


def build(pdf_path):
    lines = read_lines(pdf_path)
    header, functions, notes = {}, [], {}
    fn = rng = None
    in_notes = False
    generated = ''
    for ln in lines:
        t, x = ln['text'], ln['x']
        if t.startswith('MudCats Specsheet'):
            m = re.search(r'Generated on (.+)$', t)
            generated = generated or (m.group(1) if m else '')
            continue
        if t.startswith('PUI:') or re.fullmatch(r'Fluke \S+ Calibrator', t) or re.fullmatch(r'Page \d+', t):
            continue
        if not functions and not in_notes and x <= 60:
            k, _, v = t.partition(':')
            if k in HEADER_FIELDS:
                header[HEADER_FIELDS[k]] = v.strip()
            continue
        if t.startswith('Key:') or t.startswith('Application '):
            continue
        if t.startswith('NOTES:'):
            in_notes = True
            continue
        if in_notes:
            m = re.match(r'(\d+)\)\s*(.*)$', t)
            if m:
                last = int(m.group(1)); notes[last] = m.group(2)
            elif notes:
                notes[last] += ' ' + t
            continue
        if x <= X_FUNCTION + 2:
            direction = ln['direction']
            if re.search(r'\bInput\]?$|Input\]', t) and 'Output' not in t:
                direction = 'input'
            elif 'Output]' in t:
                direction = 'output'
            fn = dict(name=t, direction=direction or 'output', page=ln['page'], ranges=[])
            functions.append(fn); rng = None
        elif x <= X_RANGE + 2:
            rng = dict(label=t, page=ln['page'], params=[], specs=[], raw_other=[])
            fn['ranges'].append(rng)
        else:
            if rng is None:
                continue
            if t.startswith('[') and 'Accuracy' in t and re.match(r'\[(1 yr|90 day|24 hr|2 yr|6 mo)\]', t):
                rng['specs'].append(sm.parse_spec(t))
            else:
                p = sm.parse_param(t)
                (rng['params'] if p else rng['raw_other']).append(p or t)
    # wrapped spec/param lines: a continuation line has no leading bracket / digits - none seen in these sheets, so report if any
    for f in functions:
        for r in f['ranges']:
            r.update(sm.analyse_range(f['name'], r['label'], r['params']))
            if r['raw_other']:
                print(f"WARNING unparsed line(s) under {f['name']} / {r['label']}: {r['raw_other']}", file=sys.stderr)
    conf = header.get('confidence_text', '')
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', conf)
    pct = float(m.group(1)) if m else None
    if pct is None and header.get('model') in MANUAL_CONFIDENCE:      # sheet prints [Not Specified]; the manufacturer manual states the level
        pct, header['confidence_text'] = MANUAL_CONFIDENCE[header['model']]
    return dict(schema=1, standard=dict(header, confidence_pct=pct, source_pdf=Path(pdf_path).name,
                                          sheet_generated=generated, built=datetime.now().isoformat(timespec='seconds')),
                notes={str(k): v for k, v in notes.items()}, functions=functions)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf', nargs='+')
    ap.add_argument('--out')
    a = ap.parse_args(argv)
    for pdf in a.pdf:
        data = build(pdf)
        model = re.sub(r'[^a-z0-9]+', '_', data['standard'].get('model', 'unknown').lower()).strip('_')
        out = Path(a.out) if a.out else HERE / 'standards' / f'fluke_{model}_standard.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        data['problems'] = sm.validate_data(data)
        out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        n = sum(len(f['ranges']) for f in data['functions'])
        print(f"{pdf}: {data['standard'].get('model')}  {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} flagged -> {out}")


if __name__ == '__main__':
    main()
