"""Agilent / Keysight 34410A performance verification (automated: the 34410A over GPIB or USB, Fluke 5560A, 5522A or 5520A as the source).

Test points and limits come from the 34410A/11A/L4411A Service Guide, chapter 3 Verification Tests (printed pp. 68-87): specs/keysight_34410a_pv.json (built by
specs/build_34410a_spec.py). Three intervals are printed (24 hour, 90 day, 1 year); the default is 1 year. The engine is agilent34410a_verification.py.
Demo (no hardware, virtual instruments):  python Procedures/Agilent_34410A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import agilent34410a_verification

if __name__ == '__main__':
    agilent34410a_verification.main()
