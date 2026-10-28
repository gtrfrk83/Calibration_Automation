"""B&K Precision 5491B performance verification (automated: RS-232 or USB virtual COM, Fluke 5522A / 5560A / 5520A as the source).

Test points and limits come from the lab datasheet B_K_Precision_5491B_Digital_Multimeter__365_Days_.MDD (ATS-1042), cross-checked against the 2831E / 5491B User Manual,
Chapter 7, pp. 67 to 72: specs/bk_5491b_pv.json (built by specs/build_bk_5491b_spec.py). Default limits: the lab datasheet (the manufacturer specification is selectable).
The shared engine is bk5491b_verification.py; hook-up pictures go in diagrams/ (see diagrams/README_5491b.txt). Verification only: there is no adjustment here.
Demo (no hardware):  python Procedures/BK_5491B_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import bk5491b_verification

if __name__ == '__main__':
    bk5491b_verification.main()
