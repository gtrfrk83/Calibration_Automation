"""Fluke 88V performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 110-117, 170 series and 77 IV procedures: the calibrator output (Fluke 5560A / 5522A, or by hand) is set for you,
a hook-up diagram is shown whenever the cables change, you are asked to turn the rotary switch whenever the function changes, you type the display
reading, and the result is a PDF 'Calibration Data' report.
Test points and limits: specs/fluke_80_series_v_pv.json (built by specs/build_80v_spec.py from the 80 Series V Calibration Manual,
Table 3 "Accuracy Tests" pp. 9-11, '83 and 88' column). The inductive pickup test (88 only, pp. 11-14) is not included.
Demo (no hardware):  python Procedures/Fluke_88V_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '88V'
SPEC = 'fluke_80_series_v_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
