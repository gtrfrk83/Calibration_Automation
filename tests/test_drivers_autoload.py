"""A driver file that `drivers/__init__.py` does not import is still found by name (so a procedure package can add a driver without editing that shared file)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import drivers  # noqa: E402


class Autoload(unittest.TestCase):
    def test_a_new_driver_file_is_found_by_class_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'zz_new_driver.py').write_text('class ZzNewDriver:\n    MODEL = "ZZ1"\n\nZZ_CONSTANT: int = 7\n', encoding='utf-8')
            drivers.__path__.append(tmp)
            try:
                self.assertEqual(drivers.ZzNewDriver.MODEL, 'ZZ1')
                from drivers import ZZ_CONSTANT                              # `from drivers import Name` goes through the same lookup
                self.assertEqual(ZZ_CONSTANT, 7)
                self.assertIn('ZzNewDriver', vars(drivers))                  # cached after the first lookup
            finally:
                drivers.__path__.remove(tmp)
                for name in ('ZzNewDriver', 'ZZ_CONSTANT'):
                    vars(drivers).pop(name, None)
                sys.modules.pop('drivers.zz_new_driver', None)

    def test_a_name_no_driver_defines_is_still_an_attribute_error(self):
        with self.assertRaises(AttributeError):
            drivers.NoSuchDriverAnywhere
        with self.assertRaises(ImportError):
            from drivers import NoSuchDriverAnywhere  # noqa: F401

    def test_the_drivers_the_suite_ships_are_unchanged(self):
        for name in ('HP8591A', 'Fluke6060A', 'Fluke5560A', 'open_visa', 'CommandLog', 'Keysight34470A'):
            self.assertTrue(hasattr(drivers, name), name)

    def test_private_and_dunder_names_are_not_searched(self):
        with self.assertRaises(AttributeError):
            drivers._not_a_driver
        with self.assertRaises(AttributeError):
            drivers.__wrapped__


if __name__ == '__main__':
    unittest.main()
