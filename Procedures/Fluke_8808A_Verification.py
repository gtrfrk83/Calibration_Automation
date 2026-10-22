"""Fluke 8808A performance verification (automated: RS-232 only, Fluke 5522A / 5560A as the source).

Test points and limits come from the 8808A Calibration Manual, Tables 3-2 to 3-8 (pp. 3-4 to 3-11): specs/fluke_8808a_pv.json
(built by specs/build_8808a_spec.py). Default limits: 1 year (90 days selectable). The shared engine is fluke8808a_verification.py;
hook-up pictures go in diagrams/ (see diagrams/README_8808a.txt). Verification only: the 8808A adjustment is not part of this procedure.
Demo (no hardware):  python Procedures/Fluke_8808A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import fluke8808a_verification

if __name__ == '__main__':
    fluke8808a_verification.main()
