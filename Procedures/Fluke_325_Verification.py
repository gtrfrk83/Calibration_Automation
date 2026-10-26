"""Fluke 325 clamp meter performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 365 / 376 procedures: the calibrator output (Fluke 5560A / 5522A / 5520A, or by hand) is set for you, a hook-up dialog is shown whenever the cables change,
you are asked to select the function whenever it changes, you type the display reading, and the result is a PDF 'Calibration Data' report.
The current points (and on the 325 the frequency points) drive a 50-turn coil (the meter reads 50 x the calibrator current).
Test points and limits: specs/fluke_323_pv.json (built by specs/build_fluke_323_spec.py from the Fluke 323 / 324 / 325 Calibration Manual, Table 4, printed pp. 13-14);
the spec is a family spec (323, 324, 325); this launcher runs the 325.
Demo (no hardware):  python Procedures/Fluke_325_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
# the shared engine (handheld_dmm); iflex_option.App is its subclass that adds the 50-turn coil uncertainty rule (coil_rule.py) and the window options (none in this spec)
import handheld_dmm
import iflex_option

MODEL = '325'
SPEC = 'fluke_323_pv.json'

if __name__ == '__main__':
    iflex_option.main(MODEL, spec=SPEC)
