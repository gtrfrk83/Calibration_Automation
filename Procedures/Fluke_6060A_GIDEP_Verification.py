"""Fluke 6060A / 6060A-AN signal generator performance verification from the GIDEP document T.O. 33K3-4-911-1 (Calibration Procedure for Synthesized Signal Generator 6060 A/AN, 30 April 2017).
Automated over GPIB on the same bench and engine as Fluke_6060A_Verification.py: HP 8902A, Fluke 96270A + NRP40T, HP 8563E and a Keysight 33210A / 33220A / 33250A (not needed for this document's tests).

Test points and limits are the document's own tables: specs/fluke_6060a_gidep_pv.json (built by specs/build_fluke_6060a_gidep_spec.py). The Instruction Manual procedure
(Fluke_6060A_Verification.py) is a separate procedure and is not changed; this one keeps its own settings, saved progress and procedure modifications.
Demo (no hardware):  python Procedures/Fluke_6060A_GIDEP_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
sys.path.append(str(Path(__file__).resolve().parent))          # the engine and its window code sit here, with the launcher
import fluke6060a_verification

if __name__ == '__main__':
    fluke6060a_verification.main(spec_path=Path(__file__).resolve().parent.parent / 'specs' / 'fluke_6060a_gidep_pv.json',
                                 state_key='6060A-gidep', variant_label='GIDEP T.O. 33K3-4-911-1')
