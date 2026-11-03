"""Keithley DMM6500 performance verification (automated: the DMM6500 over USB, LAN or GPIB, Fluke 5560A / 5522A / 5520A as the source).

Test points and limits come from the Keithley DMM6500 Calibration and Adjustment Manual (DMM6500-905-01 Rev. E), section 2:
specs/keithley_dmm6500_pv.json (built by specs/build_dmm6500_spec.py). One interval is printed in the manual: 1 year, 18 to 28 C.
The engine is dmm6500_verification.py. Simulated bench only so far: no DMM6500 command has been verified on a real meter.
Demo (no hardware):  python Procedures/Keithley_DMM6500_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import dmm6500_verification

if __name__ == '__main__':
    dmm6500_verification.main()
