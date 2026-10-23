"""Fluke 365 clamp meter performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 110-117, 87V and 77 Series IV procedures: the calibrator output (Fluke 5560A / 5522A, or by hand) is set for you,
a hook-up diagram is shown whenever the cables change, you are asked to turn the rotary switch whenever the function changes, you type the display
reading, and the result is a PDF 'Calibration Data' report.  The current points drive a 20-turn coil (meter reads 20 x the calibrator current).
Test points and limits: specs/fluke_365_pv.json (built by specs/build_fluke_365_spec.py from the Fluke 365 Calibration Manual, Table 2, printed pp. 7-8).
Demo (no hardware):  python Procedures/Fluke_365_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '365'
SPEC = 'fluke_365_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
