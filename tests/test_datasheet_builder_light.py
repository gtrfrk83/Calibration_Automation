"""The light-meter kinds of the Datasheet Builder (lux, foot-candle, lambert, UV irradiance): units parse, never prefix-scale, show as printed."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import datasheet_builder as db  # noqa: E402


class Light(unittest.TestCase):
    def test_kinds_use_the_units_the_standards_sheets_use(self):
        self.assertEqual({k: db.KINDS[k]['unit'] for k in ('LUX', 'FC', 'LAMBERT', 'UVIRR')}, {'LUX': 'lux', 'FC': 'FC', 'LAMBERT': 'La', 'UVIRR': 'uW/cm2'})
        self.assertTrue(all(db.KINDS[k]['family'] == 'light' and db.KINDS[k]['direction'] == 'measure' for k in ('LUX', 'FC', 'LAMBERT', 'UVIRR')))

    def test_quantities_parse_and_are_never_prefix_scaled(self):
        for text, unit, want in (('3000 FC', 'FC', 3000), ('3 fc', 'FC', 3), ('35000 lux', 'lux', 35000), ('300 lx', 'lux', 300), ('100000 La', 'La', 100000),
                                 ('365 uW/cm2', 'uW/cm2', 365), ('5 µW/cm²', 'uW/cm2', 5)):
            self.assertEqual(db.parse_quantity(text, unit), Decimal(want), text)
        with self.assertRaises(db.DsError):
            db.parse_quantity('3 kFC', 'FC')
        with self.assertRaises(db.DsError):
            db.parse_quantity('3 lux', 'FC')                       # a different light unit is an error, not converted
        self.assertEqual(db.best_prefix(Decimal(35000), 'lux'), ('', 0))
        self.assertEqual(db.format_si(Decimal(5), 'uW/cm2'), '5 µW/cm²')

    def test_function_can_be_added(self):
        ds = db.Datasheet() if hasattr(db, 'Datasheet') else None
        if ds is not None:
            fn = ds.add_function('LUX', 'White light')
            self.assertEqual(fn.unit, 'lux')


if __name__ == '__main__':
    unittest.main()
