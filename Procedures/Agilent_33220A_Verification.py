"""Agilent 33220A function generator performance verification (automated: generator over USB / GPIB / LAN, Fluke 5790B
for AC amplitude, frequency counter and power meter by address or typed readings).

Test points and limits come from the 33220A Service Guide, Chapter 4 Calibration Procedures (pp. 58-72):
specs/keysight_33220a_pv.json, written by specs/build_fgen_spec.py. Default limits: 1 year. The shared engine is fgen_verification.py;
hook-up pictures, if you add them, go in diagrams/hook_332xx_<GROUP>.png (NONE, COUNTER, STD, POWER, POWER_ATT).
Demo (no hardware):  python Procedures/Agilent_33220A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import fgen_verification

MODEL = '33220A'

if __name__ == '__main__':
    fgen_verification.main(MODEL)
