"""Keysight 53220A performance verification (automated: the counter over USB, LAN or GPIB; the Fluke 96270A RF reference source as the stimulus where it can make the signal, other standards elsewhere).

Test points and limits come from the Keysight 53210A/53220A/53230A Assembly Level Service Guide, chapter 1 Performance Tests: specs/keysight_53220a_pv.json (built by
specs/build_53220a_spec.py).  One spec and one engine (keysight_53220a_verification.py) serve the 53210A, 53220A and 53230A.
Demo (no hardware, virtual instruments):  python Procedures/Keysight_53220A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import keysight_53220a_verification

if __name__ == '__main__':
    keysight_53220a_verification.main(model='53220A')
