"""Fluke 289 performance verification on the shared handheld engine (handheld_dmm.py).

The calibrator output (Fluke 5560A / 5522A, or by hand) is set for you and a prompt is shown whenever the cables or the meter setup
change. The meter reading is either typed in, or - with the Fluke IR-to-USB cable on the meter's IR port - read over IR: the program
then checks the meter's function, range and REL / Low Pass state, waits for a stable reading and records it.
Test points and limits: specs/fluke_287_289_pv.json (built by specs/build_28x_spec.py from the 287/289 Calibration Manual, Tables 3-4).
IR driver: drivers/fluke_28x.py (Fluke 289/287 Remote Interface Specification). Demo (no hardware):  python Procedures/Fluke_289_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '289'
SPEC = 'fluke_287_289_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
