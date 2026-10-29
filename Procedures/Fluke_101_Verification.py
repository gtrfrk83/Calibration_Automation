"""Fluke 101 digital multimeter performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 77 Series IV, 365 and 87V procedures: the calibrator output (Fluke 5522A / 5560A, or by hand) is set for you,
a hook-up diagram is shown when the cables change, you are asked to turn the rotary switch whenever the function changes, you type the display
reading, and the result is a PDF 'Calibration Data' report.
The Fluke 101 Users Manual has no calibration procedure: one point per range at 90 % of the range (AC volts and AC millivolts at 60 Hz and 400 Hz),
limits from the published 1-year accuracy specification.  Points and limits: specs/fluke_101_pv.json (built by specs/build_fluke_101_spec.py).
Demo (no hardware):  python Procedures/Fluke_101_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '101'
SPEC = 'fluke_101_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
