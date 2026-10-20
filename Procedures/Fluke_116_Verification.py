"""Fluke 116 (and 116C) performance verification - manual-reading procedure.

The calibrator output is set automatically (Fluke 5560A / 5522A, or by hand); you read the meter and type the value.
Test points and limits: specs/fluke_110_series_pv.json (Fluke 110/113/114/115/116/117 Calibration Information, Table 3).
Demo (no hardware):  python Procedures/Fluke_116_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '116'

if __name__ == '__main__':
    handheld_dmm.main(MODEL)
