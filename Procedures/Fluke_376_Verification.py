"""Fluke 376 clamp meter performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 365, 110-117, 87V and 77 Series IV procedures: the calibrator output (Fluke 5560A / 5522A, or by hand) is set for you, a hook-up dialog is shown whenever the
cables change, you are asked to turn the rotary switch whenever the function changes, you type the display reading, and the result is a PDF 'Calibration Data' report.
The current points drive a 50-turn coil (the meter reads 50 x the calibrator current), with the detachable jaw or with the iFlex loop; the iFlex simulation points apply 3 to 750 mV to the iFlex input.
The window has an option 'iFlex probe supplied: run the iFlex tests' (default ON; iflex_option.py): switch it off for a meter received without its iFlex and the 9 iFlex points are not run.
Test points and limits: specs/fluke_376_pv.json (built by specs/build_fluke_376_spec.py from the Fluke 374 / 375 / 376 / 376-II Calibration Manual, Table 1, printed pp. 3-4);
the spec is a family spec (374, 375, 376, 376-II); this launcher runs the 376: 38 points (29 without the iFlex tests).
Demo (no hardware):  python Procedures/Fluke_376_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import iflex_option

MODEL = '376'
SPEC = 'fluke_376_pv.json'

if __name__ == '__main__':
    iflex_option.main(MODEL, spec=SPEC)
