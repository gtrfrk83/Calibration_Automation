"""HP 8591A spectrum analyzer performance verification from the USAF technical manual T.O. 33K3-4-2864-1 (Calibration Procedure for Spectrum Analyzer 8591A, 30 May 2012).
Automated over GPIB: the 8591A and the Fluke 96270A (leveled sine, internal AM, NRP40T power-meter mode) in place of the document's sweeper, power meter, synthesizer, generators and step attenuators.

Test points and limits are the document's own tables: specs/hp_8591a_pv.json (built by specs/build_hp_8591a_spec.py). Every replacement of the document's instruments is flagged UNVERIFIED on the point.
Demo (no hardware):  python Procedures/HP_8591A_Verification.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
sys.path.append(str(Path(__file__).resolve().parent))          # the engine and its window code sit here, with the launcher
import hp8591a_verification

if __name__ == '__main__':
    hp8591a_verification.main()
