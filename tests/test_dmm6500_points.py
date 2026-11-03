"""Keithley DMM6500 spec and driver: structure and the numbers read from the Calibration manual page images (DMM6500-905-01 Rev. E, section 2).

The DMM6500 data sheet is not part of the manual set, so these tests pin the PRINTED values (a regression guard for the builder) and the driver's declarations; they do not
re-derive limits from the specification.  No instrument is involved: every driver command is still verified=False (no bench session yet)."""
import json
import unittest
from pathlib import Path

import cmdreg
from drivers.keithley_dmm6500 import COMMANDS, KINDS, NODE, KeithleyDMM6500

SPEC = json.loads((Path(__file__).resolve().parent.parent / 'specs' / 'keithley_dmm6500_pv.json').read_text(encoding='utf-8'))
POINTS = {p['id']: p for s in SPEC['sections'] for p in s['points']}


def half(pid):
    return POINTS[pid]['limits']['1y']


class SpecShape(unittest.TestCase):
    def test_counts_per_section(self):
        counts = {s['id']: len(s['points']) for s in SPEC['sections']}
        self.assertEqual(counts, {'dcv': 21, 'acv': 20, 'digv': 20, 'freq': 5, 'tc': 3, 'rtd': 6, 'short4': 11, 'ohm4': 8, 'ohm2': 1, 'dci_low': 16, 'dci': 12,
                                  'digi': 24, 'aci': 17, 'rear10a': 12, 'cap': 13})
        self.assertEqual(sum(counts.values()), 189)

    def test_ids_unique_and_every_point_has_a_page(self):
        ids = [p['id'] for s in SPEC['sections'] for p in s['points']]
        self.assertEqual(len(ids), len(set(ids)))
        for p in POINTS.values():
            self.assertTrue(p['page'].startswith('2-'), p['id'])
            self.assertIn(p['kind'], KINDS)

    def test_one_period_only(self):
        self.assertEqual(SPEC['periods'], ['1y'])

    def test_only_the_zero_checks_are_optional(self):
        self.assertEqual([s['id'] for s in SPEC['sections'] if s['optional']], ['short4'])

    def test_negative_points_mirror_the_positive_ones_except_the_flagged_prints(self):
        for pid, p in POINTS.items():
            if p['nominal'] < 0 and p['kind'] not in ('TEMP',) and not p.get('flags'):
                pos = [q for q in POINTS.values() if q['kind'] == p['kind'] and q['range'] == p['range'] and q['nominal'] == -p['nominal'] and q.get('frequency') == p.get('frequency')]
                for q in pos:
                    if not q.get('flags'):
                        self.assertEqual(q['limits'], p['limits'], pid)


class PrintedNumbers(unittest.TestCase):
    """Spot values read from the page images (printed pages in brackets)."""

    def test_dc_volts(self):
        self.assertAlmostEqual(half('DCV.0.1.1'), 6.5e-6)        # [2-8] 99.9935 to 100.0065 mV
        self.assertAlmostEqual(half('DCV.10.1'), 3e-4)           # [2-8] 9.9997 to 10.0003 V (25 ppm + 5 ppm of the 10 V range)
        self.assertAlmostEqual(half('DCV.1000.1'), 0.056)        # [2-9]
        self.assertAlmostEqual(half('DCV.1000.4'), 0.069)        # [2-9] as printed, flagged
        self.assertTrue(POINTS['DCV.1000.4']['flags'])

    def test_100_v_full_scale_misprint_is_corrected_and_flagged(self):
        p = POINTS['DCV.100.1']                                  # [2-9] prints 99.954 / 100.0046: a digit is missing
        self.assertAlmostEqual(p['limits']['1y'], 0.0046)
        self.assertIn('99.954', p['printed_limits'])
        self.assertTrue(p['flags'])

    def test_ac_current_10_ma_upper_limit_misprint_is_corrected(self):
        self.assertAlmostEqual(half('ACI.10mA.1000'), 14e-6)     # [2-38] prints 9.986 to 10.14 mA; 10.014 mA used
        self.assertTrue(POINTS['ACI.10mA.1000']['flags'])

    def test_ac_volts_750_range(self):
        self.assertEqual(POINTS['ACV.750.100kHz']['nominal'], 740.0)
        self.assertAlmostEqual(half('ACV.750.100kHz'), 5.04)     # [2-14] 734.96 to 745.04
        self.assertAlmostEqual(half('ACV.0.1.100kHz'), 0.68e-3)  # [2-12] 99.32 to 100.68 mV

    def test_frequency_rows_are_in_khz_above_10_hz(self):
        self.assertAlmostEqual(half('FREQ.1'), 0.003)            # 10 Hz: 9.997 to 10.003 Hz
        self.assertAlmostEqual(half('FREQ.5'), 27.0)             # 300 kHz: 299.973 to 300.027 kHz = +/- 27 Hz
        self.assertEqual(POINTS['FREQ.5']['nominal'], 300000.0)

    def test_thermocouple_source_values(self):
        self.assertAlmostEqual(POINTS['TC.1']['source_value'], -7.659e-3)    # [2-20] NIST Monograph 175 type J
        self.assertAlmostEqual(POINTS['TC.3']['source_value'], 42.281e-3)
        self.assertEqual({p['limits']['1y'] for p in POINTS.values() if p['id'].startswith('TC.')}, {0.2})

    def test_rtd_tolerances(self):
        self.assertEqual(half('RTD4.2'), 0.06)
        self.assertEqual(half('RTD3.2'), 0.75)
        self.assertEqual(POINTS['RTD4.1']['cvd']['alpha'], '0.00385055')

    def test_resistance_half_widths_come_from_the_example_rows(self):
        self.assertAlmostEqual(half('OHM4.1'), 0.000285)         # [2-26] 0.999688 to 1.000258 about 0.999973
        self.assertAlmostEqual(half('OHM4.10000'), 0.81)         # 10 kohm: 75 ppm + 6 ppm of range, the manual's own worked example (p. 2-4)
        self.assertAlmostEqual(half('OHM4.1000000'), 106.0)
        self.assertTrue(all(POINTS[i]['std_relative'] for i in POINTS if i.startswith('OHM')))

    def test_four_wire_short_zero_limits(self):
        self.assertEqual([half(i) for i in ('ZR.1', 'ZR.10', 'ZR.100', 'ZR.1k', 'ZR.10k', 'ZR.100k')], [0.0002, 0.0002, 0.002, 0.006, 0.06, 1.0])
        self.assertAlmostEqual(half('ZV.1000'), 6e-3)            # unit not printed: microvolts
        self.assertAlmostEqual(half('ZV.0.1'), 3.5e-6)

    def test_dc_current_tolerances_are_in_the_ranges_own_unit(self):
        self.assertAlmostEqual(half('DCI.10uA.2'), 2.75e-9)      # [2-31] 0.00275 uA
        self.assertAlmostEqual(half('DCI.1mA.1'), 5e-7)          # 0.000500 mA
        self.assertAlmostEqual(half('DCI.10mA.1'), 2.5e-6)       # 0.00250 mA
        self.assertAlmostEqual(half('DCI.3A.1'), 0.00112)        # [2-33] 2 A on the 3 A range
        self.assertEqual(POINTS['DCI.3A.1']['nominal'], 2.0)

    def test_digitize_current_half_widths(self):
        self.assertAlmostEqual(half('DIGI.100uA.1'), 0.12e-6)    # [2-34] 99.878 to 100.118 about 99.998
        self.assertAlmostEqual(half('DIGI.3A.2'), 0.00255)       # [2-36]
        self.assertAlmostEqual(half('DIGI.10A.2'), 0.033)        # [2-46]
        self.assertFalse([i for i in POINTS if i.startswith('DIGI.10uA')])   # the 10 uA digitize range has no table in the manual

    def test_capacitance_is_sourced_by_the_calibrator_after_a_cable_only_reading(self):
        self.assertEqual(POINTS['CAP.1']['source'], 'none')                  # owner decision 2026-11-03: the calibrator sources the capacitance (not a decade box)
        self.assertTrue(POINTS['CAP.1']['rel_acquire'])
        self.assertEqual({POINTS[f'CAP.{n}']['source'] for n in range(2, 14)}, {'calibrator'})
        self.assertEqual({s['source'] for s in SPEC['sections'] if s['id'] == 'cap'}, {'calibrator'})

    def test_capacitance_units_follow_the_range(self):
        self.assertAlmostEqual(POINTS['CAP.2']['nominal'], 0.1e-9)           # 10 % of 1 nF
        self.assertAlmostEqual(half('CAP.13'), 0.5e-6)                       # 100 uF: 99.5 to 100.5 uF
        self.assertEqual(POINTS['CAP.13']['range'], 1e-4)


class DriverDeclarations(unittest.TestCase):
    def test_registry_is_clean_and_nothing_is_verified_yet(self):
        reg = cmdreg.merge_commands(KeithleyDMM6500)
        self.assertEqual([str(p) for p in cmdreg.lint_registry(reg)], [])
        self.assertEqual([k for k, c in reg.items() if c.verified], [])      # no bench session yet: every command stays UNVERIFIED

    def test_every_command_carries_a_manual_page(self):
        for key, c in COMMANDS.items():
            self.assertIn('p. ', c.ref, key)

    def test_no_calibration_or_save_recall_commands(self):
        for key, c in COMMANDS.items():
            t = c.template.upper()
            for bad in ('CAL', 'SYST:POS', '*SAV', '*RCL', 'PASS', 'SEC'):
                self.assertNotIn(bad, t.replace('CALC', ''), key)

    def test_reset_and_opc_are_declared(self):
        self.assertEqual(COMMANDS['reset'].template, '*RST')
        self.assertEqual(COMMANDS['reset'].risk, 'locked')
        self.assertIn('opc.query', COMMANDS)

    def test_every_kind_has_function_and_range_commands(self):
        for kind in KINDS:
            self.assertIn(f'func.{kind.lower()}', COMMANDS)
        for kind in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP', 'DIGV', 'DIGI'):
            tpl = COMMANDS[f'range.{kind.lower()}'].template
            self.assertIn(NODE[kind] + ':RANG', tpl)
            self.assertIn('RANG:AUTO OFF', COMMANDS[f'autooff.{kind.lower()}'].template)

    def test_digitize_commands_match_the_manual_examples(self):
        self.assertEqual(COMMANDS['func.digv'].template, ':SENS:DIG:FUNC "VOLT"')
        self.assertEqual(cmdreg.render(COMMANDS['dig.count'], {'count': 100}), ':SENS:DIG:COUN 100')
        self.assertEqual(cmdreg.render(COMMANDS['srate.digv'], {'srate': 1000.0}), ':SENS:DIG:VOLT:SRAT 1000')


if __name__ == '__main__':
    unittest.main()
