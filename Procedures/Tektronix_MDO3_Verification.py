"""Tektronix 3 Series MDO (MDO32 / MDO34, 100 MHz - 1 GHz) performance verification, automated over USB.

Test points and limits come from the 3 Series MDO Specifications and Performance Verification manual (077-1499-10), specs/tektronix_mdo3_pv.json,
written by specs/build_mdo3_spec.py. The engine is mdo3_verification.py (its own; the model-independent helpers come from mdo4000c_verification.py); the
driver is drivers/tektronix_mdo3.py. Standards as the MDO4000C procedure: Fluke 5560A (analog / DVM), Fluke 96270A (RF), Agilent 33220A / 33250A (time mark and
the low-frequency points), reference DMM / counter / power meter optional. The technician selects the model (channels and bandwidth) and the options.
Demo (no hardware):  python Procedures/Tektronix_MDO3_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import mdo3_verification

if __name__ == '__main__':
    mdo3_verification.main()
