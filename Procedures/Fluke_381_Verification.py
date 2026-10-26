"""Fluke 381 remote display clamp meter performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 376 procedure: the calibrator output (Fluke 5560A / 5522A / 5520A, or by hand) is set for you, a hook-up dialog is shown whenever the cables change,
you are asked to select the function whenever it changes, you type the display reading, and the result is a PDF 'Calibration Data' report.
The current points drive a 50-turn coil (the meter reads 50 x the calibrator current), with the jaw or with the iFlex loop; the 0 A dc point uses a single wire; the two iFlex simulation points apply 75 / 750 mV to the iFlex input.
The window option 'iFlex probe supplied: run the iFlex tests' (default ON; iflex_option.py) leaves out the 5 iFlex-with-coil points (the 2 simulation points always run).
Test points and limits: specs/fluke_381_pv.json (built by specs/build_fluke_381_spec.py from the Fluke 381 Calibration Manual, Tables 3 and 4, printed pp. 11-12 and 14): 47 points (42 without the iFlex-with-coil tests).
Demo (no hardware):  python Procedures/Fluke_381_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
# the shared engine (handheld_dmm); iflex_option.App is its subclass that adds the 50-turn coil uncertainty rule (coil_rule.py) and the window options (none in this spec)
import handheld_dmm
import iflex_option

MODEL = '381'
SPEC = 'fluke_381_pv.json'

if __name__ == '__main__':
    iflex_option.main(MODEL, spec=SPEC)
