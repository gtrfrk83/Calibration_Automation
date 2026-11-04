"""Every unit the standards sheets (specs/standards/*.json) carry is understood by the Datasheet Builder's unit reader, or is deliberately handled elsewhere."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import datasheet_builder as db  # noqa: E402

# Rate / compound units of accuracy TERMS (dB per 10 dB step, x reference level ...): these are tolerance terms, not point units.
TERM_UNITS = {'dB/10dB', 'dB/range', 'dB/dB', 'dB/10 dB step', 'dB p-p', 'x reference level p-p', 'x reference level', 'dB/kHz', 'dB/2 dB'}
# Amplitude spellings the Sheet check reads as the section's V / A with a note (Vrms, Vpp, Vp), and the key the sheets use for them.
AMPLITUDE_SPELLINGS = {'Vpp', 'App'}


def sheet_units():
    found = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ('unit', 'units', 'display_unit', 'unit_of_measure') and isinstance(v, str) and v:
                    found.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for f in sorted((ROOT / 'specs' / 'standards').glob('*.json')):
        walk(json.loads(f.read_text(encoding='utf-8')))
    return found


class Units(unittest.TestCase):
    def test_every_unit_in_the_standards_sheets_is_read_or_listed_as_handled_elsewhere(self):
        missing = []
        for u in sorted(sheet_units() - TERM_UNITS - AMPLITUDE_SPELLINGS):
            try:
                db.parse_quantity('1 ' + u)
            except db.DsError:
                missing.append(u)
        self.assertEqual(missing, [])

    def test_prefixes_and_values(self):
        D = db.D
        self.assertEqual(db.parse_quantity('2 mW'), D('0.002'))
        self.assertEqual(db.parse_quantity('5 uH'), D('0.000005'))
        self.assertEqual(db.parse_quantity('-20 dBm'), D(-20))
        self.assertEqual(db.parse_quantity('-110 dBc/Hz'), D(-110))
        self.assertEqual(db.parse_quantity('1 mrad'), D('0.001'))
        self.assertEqual(db.parse_quantity('50 %DC'), D(50))
        self.assertEqual(db.parse_quantity('1 pF'), D('1E-12'))        # picofarad stays a capacitance
        self.assertEqual(db.parse_quantity('1 PF'), D(1))              # power factor is a ratio

    def test_log_units_take_no_prefix(self):
        for u in ('dBm', 'dBc', 'dBc/Hz', 'deg', 'rpm'):
            self.assertIn(u, db._NO_PREFIX)
            self.assertEqual(db.best_prefix(1500, u), ('', 0))

    def test_new_kinds_exist_and_use_the_units(self):
        for kind, unit in (('RFLEVEL', 'dBm'), ('POWER', 'W'), ('INDUCT', 'H'), ('PHASE', 'deg'), ('SPEED', 'rpm')):
            self.assertEqual(db.KINDS[kind]['unit'], unit)
            self.assertEqual(db.KINDS[kind]['family'], 'other')


if __name__ == '__main__':
    unittest.main()
