"""Tektronix MDO4000C performance verification (MDO4024C / 4034C / 4054C / 4104C), automated over USB.

Test points and limits come from the MDO4000C Series Specifications and Performance Verification manual (077-1178-01 Rev B),
specs/tektronix_mdo4000c_pv.json. Stimulus: Fluke 5560A (analog), Fluke 96270A (RF), Agilent 33220A / 32250A (time mark and
delta-time points the 5560A cannot make). The technician selects the model and installed options in the window.
Demo (no hardware):  python Procedures/Tektronix_MDO4000C_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import mdo4000c_verification

if __name__ == '__main__':
    mdo4000c_verification.main()
