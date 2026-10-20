"""Keysight 34465A performance verification (automated: DMM over USB / GPIB / LAN / RS-232, Fluke 5560A as the source).

Test points and limits come from the 34465A tables of the Keysight Truevolt Series DMM Operating and Service Guide
(pp. 504-520): specs/keysight_34465a_pv.json. Default limits: 1 year. The shared engine is truevolt_verification.py.
Demo (no hardware):  python Procedures/Keysight_34465A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import truevolt_verification

MODEL = '34465A'

if __name__ == '__main__':
    truevolt_verification.main(MODEL)
