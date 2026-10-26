"""Tektronix TBS1000C performance verification, automated over USB.

Test points and limits come from the TBS1000C Specification and Performance Verification (077-1583-03 Rev A), pp. 23-30, specs/tektronix_tbs1000c_pv.json.
Stimulus: the scope option of a Fluke 5560A, 5522A or 5520A. Engine: the shared Tektronix engine (tds2000c_verification.py, families in tbs1000_verification.py).
Demo (no hardware):  python Procedures/Tektronix_TBS1000C_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import tds2000c_verification  # noqa: F401  (the shared engine: its App._worker resets every instrument before the first point)
import tbs1000_verification

if __name__ == '__main__':
    tbs1000_verification.main_tbs1000c()
