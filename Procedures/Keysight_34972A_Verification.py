"""Keysight 34972A performance verification of the internal DMM (automated: USB, Fluke 5560A / 5522A as the source).

Test points and limits come from the 34970A/34972A Service Guide, Chapter 4 (pp. 80-87): specs/keysight_34972a_pv.json.
Default limits: 1 year. The shared engine is dacq_verification.py; hook-up pictures go in diagrams/ (see diagrams/README_dacq.txt).
Demo (no hardware):  python Procedures/Keysight_34972A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import dacq_verification

MODEL = '34972A'

if __name__ == '__main__':
    dacq_verification.main(MODEL)
