"""Keysight U1251B handheld digital multimeter performance verification - manual-reading procedure on the shared handheld engine.

Same flow as the Fluke 287 / 289 and clamp-meter procedures: the calibrator output (Fluke 5560A / 5522A, or by hand) is set for you, a hook-up dialog with the diagram is shown whenever the cables change,
you are asked to turn the rotary switch (and press Shift) whenever the function changes, you type the display reading, and the result is a PDF 'Calibration Data' report.
The meter has no documented remote command set, so readings are typed.  The frequency counter and square wave output points (U1252B) are set up by hand.
Test points and limits: specs/keysight_u1251b_u1252b_pv.json (built by specs/build_keysight_u1251b_spec.py from the Keysight U1251B and U1252B User's and Service Guide, Table 6-2,
printed pp. 155-160); the spec is a family spec (U1251B, U1252B); this launcher runs the U1251B.
Demo (no hardware):  python Procedures/Keysight_U1251B_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = 'U1251B'
SPEC = 'keysight_u1251b_u1252b_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
