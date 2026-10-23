"""Fluke 365 Detachable Jaw True-rms Clamp Meter: manual calibration (Performance Tests, Table 2) on the shared handheld engine.

The 365 has no remote interface: the calibrator output is set for you (Fluke 5560A / 5522A, or by hand), you read the meter and type the value, either in the
reading window of Run All Pending or straight into the test point grid (Enter = save and next point). The current points are driven through a 20-turn coil.
Test points and limits: specs/fluke_365_pv.json (built by specs/build_fluke_365_spec.py from the Fluke 365 Calibration Manual, Table 2, printed pp. 7-8).
Demo (no hardware):  python Procedures/Fluke_365_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
# the shared handheld engine this procedure runs on (its reset-before-tests and in-run editor are checked by name), and the 365's window: handheld_dmm.App plus the typed-reading grid
import handheld_dmm
import fluke365_verification

if __name__ == '__main__':
    fluke365_verification.main()
