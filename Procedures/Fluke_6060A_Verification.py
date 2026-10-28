"""Fluke 6060A / 6060A-AF synthesized signal generator performance verification (automated, GPIB: the 6060A under test; the HP 8902A measuring receiver, the Fluke 96270A power
meter with an R&S NRP40T sensor, the HP 8563E spectrum analyzer and a Keysight 33210A / 33220A / 33250A function generator as the measuring equipment).

Test points and limits come from the 6060A Instruction Manual, Section 4A (4A-3 to 4A-8, 4A-11, 4A-12; output leakage 4A-9 / 4A-10 is not built): specs/fluke_6060a_pv.json (built by
specs/build_fluke_6060a_spec.py). The shared engine is fluke6060a_verification.py; hook-up pictures go in diagrams/ (see diagrams/README_6060a.txt). Verification only: there is no adjustment here.
Demo (no hardware):  python Procedures/Fluke_6060A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import fluke6060a_verification

if __name__ == '__main__':
    fluke6060a_verification.main()
