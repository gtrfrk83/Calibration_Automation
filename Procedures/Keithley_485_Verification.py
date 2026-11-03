"""Keithley 485 Autoranging Picoammeter performance verification - manual-reading procedure on the shared handheld engine.

Instruction Manual (485-901-01 Rev. F) Section 3.5 and Table 3-2 (p. 3-2): each current range is driven by a DC calibrator (Fluke 5560A, 5522A or 5520A,
or set by hand) through a measured resistor of the lab's resistance box; the calibrator setting is V = I x R (measured value), so the 485 sees exactly the
required current.  Zero check first, then each range at + and - current.  The technician selects the range and types the 485 display reading; the result is a
PDF 'Calibration Data' report.  Points, limits and the resistor values: specs/keithley_485_pv.json (built by specs/build_keithley_485_spec.py).
Demo (no hardware):  python Procedures/Keithley_485_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import handheld_dmm

MODEL = '485'
SPEC = 'keithley_485_pv.json'

if __name__ == '__main__':
    handheld_dmm.main(MODEL, spec=SPEC)
