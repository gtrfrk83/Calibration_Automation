"""Fluke i400 AC Current Clamp performance verification (automated: the clamp's output is read by a multimeter, Fluke 5560A / 5522A / 5520A as the source).

Test points and limits come from the i400 Calibration Information (part 2414311), Table 3 Accuracy Tests (p. 6): specs/fluke_i400_pv.json (built by
specs/build_fluke_i400_spec.py). The engine is i400_verification.py.
Demo (no hardware, virtual instruments):  python Procedures/Fluke_i400_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import i400_verification

if __name__ == '__main__':
    i400_verification.main()
