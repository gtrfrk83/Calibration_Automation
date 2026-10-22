"""Fluke 179 performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 110-117, 77 IV, 87V and Klein MM325 procedures: the calibrator output (Fluke 5560A / 5522A, or by hand) is set for you,
a hook-up diagram is shown whenever the cables change, you are asked to turn the rotary switch (and press the YELLOW button) whenever the function
changes, you type the display reading, and the result is a PDF 'Calibration Data' report.
Test points and limits: specs/fluke_170_series_pv.json (built by specs/build_170_spec.py from the 175 / 177 / 179 Calibration Information, Tables 2 and 3, pp. 10-13).
Demo (no hardware):  python Procedures/Fluke_179_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '179'
SPEC = 'fluke_170_series_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
