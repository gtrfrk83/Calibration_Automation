"""The drawn hook-up pictures: chosen per calibrator / wiring, with the supplied panel photo as the fallback; nothing else about a prompt changes."""
import unittest
from pathlib import Path

import hookups

D = Path(hookups.__file__).resolve().parent / 'diagrams'


class BenchImages(unittest.TestCase):
    def test_every_bench_wiring_has_a_drawing(self):
        for model, jack in (('34401A', 'I'), ('34460A', '3A'), ('34461A', '3A'), ('34465A', '3A')):
            for w in ('VOLT', 'RES2', 'RES4'):
                self.assertEqual(hookups.bench_image(model, w).name, f'hook_{model}_5560A_{w}.png')
            self.assertEqual(hookups.bench_image(model, 'CURRENT', nominal=1).name, f'hook_{model}_5560A_I_{jack}.png')
            self.assertEqual(hookups.bench_image(model, 'ZERO').name, f'hook_{model}_5560A_SHORT.png')
            self.assertEqual(hookups.bench_image(model, 'ZERO', open_input=True).name, f'hook_{model}_5560A_OPEN.png')
        for key in ('VOLT', 'RES2', 'RES4', 'SHORT', 'OPEN', 'I_400MA', 'I_10A'):
            self.assertTrue((D / f'hook_8846A_5560A_{key}.png').is_file(), key)

    def test_current_jack_choice(self):
        self.assertEqual(hookups.bench_image('34461A', 'CURRENT', terminal='FRONT_10A').name, 'hook_34461A_5560A_I_10A.png')
        self.assertEqual(hookups.bench_image('8846A', 'CURRENT', rng=0.4).name, 'hook_8846A_5560A_I_400MA.png')
        self.assertEqual(hookups.bench_image('8846A', 'CURRENT', rng=3).name, 'hook_8846A_5560A_I_10A.png')

    def test_fallback_is_the_supplied_photo(self):
        self.assertEqual(hookups.bench_image('34401A', 'ZERO', terminal='REAR'), hookups.panel_image('34401A'))
        self.assertEqual(hookups.bench_image('8846A', None), hookups.panel_image('8846A'))
        self.assertIsNone(hookups.bench_image('34470A', 'VOLT'))


class Handheld28x(unittest.TestCase):
    def test_pictures_exist_for_both_calibrators(self):
        for cal in ('5560A', '5522A'):
            for g in ('VOHM', 'OHM4', 'UAMP', 'AMP10', 'TEMP'):
                self.assertIsNotNone(hookups.image_path('fluke28x', cal, g), (cal, g))


if __name__ == '__main__':
    unittest.main()
