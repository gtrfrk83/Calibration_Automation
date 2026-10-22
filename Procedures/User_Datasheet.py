"""Generic launcher for a user-built datasheet (Datasheet Builder): the Manager lists every saved datasheet as a 'user-built' procedure and starts this
script with the datasheet's runnable spec file.

    python Procedures/User_Datasheet.py --spec <data folder>/user_specs/<make>_<model>_<title>.json [--demo] [--asset ID] [--period 1y]

Without --spec the script asks for the spec file.  The engine is the handheld engine (handheld_dmm.py) extended by dsb_runtime.py.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import dsb_runtime

if __name__ == '__main__':
    dsb_runtime.main()
