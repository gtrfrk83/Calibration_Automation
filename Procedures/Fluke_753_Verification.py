"""Fluke 753 Documenting Process Calibrator performance verification - manual-reading procedure on the shared handheld engine.

The 753 is itself a calibrator, so each point goes one way or the other (see fluke_753_754.py):
  UUT input points   the lab calibrator (Fluke 5522A, the manual's own; 5560A / 5520A also offered) sources the value, you type the 753's display.
  UUT OUTPUT points  the 753 sources: MANUAL ENTRY ONLY, you type the reading of the external measuring instrument (nothing is read automatically);
                     the uncertainty is that of the measuring standard you choose per point (right-click the point; default Keysight 3458A).
A hook-up dialog is shown whenever the cables change, the result is a PDF 'Calibration Data' report.
Test points and limits: specs/fluke_753_754_pv.json (built by specs/build_fluke_753_754_spec.py from the Fluke 753/754 Calibration Manual, Performance Verification Tests, printed pp. 9-32);
the spec is a family spec (753, 754); this launcher runs the 753: 90 points (no HART).
Demo (no hardware):  python Procedures/Fluke_753_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
# the shared engine (handheld_dmm); fluke_753_754.App is its subclass (direction-aware uncertainty, per-point measuring-standard choice)
import handheld_dmm
import fluke_753_754

MODEL = '753'
SPEC = 'fluke_753_754_pv.json'

if __name__ == '__main__':
    fluke_753_754.main(MODEL, spec=SPEC)
