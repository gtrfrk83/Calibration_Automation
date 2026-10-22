"""Tektronix TDS2000C / TDS1000C-EDU performance verification, automated over USB.

Test points and limits come from the TDS2000C and TDS1000C-EDU Service Manual (077-0446-01) Chapter 4,
specs/tektronix_tds2000c_pv.json. Stimulus: the scope option of a Fluke 5560A, 5522A or 5520A.
Demo (no hardware):  python Procedures/Tektronix_TDS2000C_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import tds2000c_verification

if __name__ == '__main__':
    tds2000c_verification.main()
