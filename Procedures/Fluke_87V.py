"""Fluke 87 Series V performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 110-117 and Klein MM325 procedures: the calibrator output (Fluke 5560A / 5522A, or by hand) is set for you,
a hook-up diagram is shown whenever the cables change, you type the display reading, and the result is a PDF 'Calibration Data' report.
Test points and limits: specs/fluke_87v_pv.json (built by specs/build_87v_spec.py from the 87V Cal Processor datasheet / MDD).
Demo (no hardware):  python Procedures/Fluke_87V.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '87V'
SPEC = 'fluke_87v_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
