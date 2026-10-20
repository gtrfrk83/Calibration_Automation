"""Klein Tools MM325 performance verification - manual-reading procedure.

One test point per range at 90 % of the range, every AC point at 60 Hz. The calibrator output (Fluke 5560A / 5522A, or by hand)
is set for you; you turn the dial when prompted, change cables when prompted (each cable change shows a hook-up diagram) and type the display reading.
Test points and limits: specs/klein_mm325_pv.json (built by specs/build_mm325.py from the MM325 instruction manual, p. 3).
Demo (no hardware):  python Procedures/Klein_MM325_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = 'MM325'
SPEC = 'klein_mm325_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
