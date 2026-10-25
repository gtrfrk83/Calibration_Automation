"""Tektronix TBS2000B (TBS2072B / 2074B / 2102B / 2104B / 2202B / 2204B) performance verification, automated over USB.

Test points and limits come from the TBS2000B Series Oscilloscope Specification and Performance Verification manual (077-1538-03 Rev D) pp. 19-26,
specs/tektronix_tbs2000b_pv.json. Stimulus: the scope option of a Fluke 5560A, 5522A or 5520A.
Demo (no hardware):  python Procedures/Tektronix_TBS2000B_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import tbs2000b_verification

if __name__ == '__main__':
    tbs2000b_verification.main()
