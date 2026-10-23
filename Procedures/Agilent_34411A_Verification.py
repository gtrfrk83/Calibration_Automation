"""Agilent / Keysight 34411A performance verification (automated: the 34411A over GPIB or USB, Fluke 5560A, 5522A or 5520A as the source).

The 34411A shares the 34410A's Service Guide tables ("34410A/11A/L4411A Service Guide", chapter 3 Verification Tests, printed pp. 68-87) and so its spec
(specs/keysight_34410a_pv.json, whose models{} block carries the per-model flags), its engine (agilent34410a_verification.py) and its driver
(drivers/keysight_34410a.py, class Keysight34411A). Three intervals are printed (24 hour, 90 day, 1 year); the default is 1 year.
Demo (no hardware, virtual instruments):  python Procedures/Agilent_34411A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import agilent34410a_verification

MODEL = '34411A'

if __name__ == '__main__':
    agilent34410a_verification.main(model=MODEL)
