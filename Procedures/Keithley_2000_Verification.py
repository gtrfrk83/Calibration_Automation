"""Keithley Model 2000 performance verification (automated: the 2000 over GPIB or RS-232, Fluke 5560A or 5522A as the source).

Test points and limits come from the Keithley Model 2000 Multimeter Calibration Manual (2000-905-01 Rev. F), Tables 1-2 to 1-6:
specs/keithley_2000_pv.json (built by specs/build_k2000_spec.py). One interval is printed in the manual: 1 year, 18 to 28 C.
The engine is keithley2000_verification.py.
Demo (no hardware):  python Procedures/Keithley_2000_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import keithley2000_verification

if __name__ == '__main__':
    keithley2000_verification.main()
