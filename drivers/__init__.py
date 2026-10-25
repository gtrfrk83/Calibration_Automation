"""Instrument drivers for the calibration suite (one driver per model).

    from drivers import Fluke5560A, WaveSurfer4104HD, open_visa
    with Fluke5560A(open_visa('ASRL9::INSTR', baud=9600)) as cal: ...

Add a model by copying drivers/TEMPLATE.md's checklist - see README.txt in this folder.
"""
from .base import Instrument, InstrumentError, SafetyError
from .fluke_5560a import SERIAL_DEFAULT as FLUKE_5560A_SERIAL
from .fluke_5560a import Fluke5520A, Fluke5522A, Fluke5560A
from .fluke_5522a_scope import Fluke5522AScope
from .lecroy_ws4104hd import WaveSurfer4104HD
from .keithley_2000 import Fluke5522AComp, Keithley2000
from .keithley_2000_cal import Keithley2000Cal
from .keysight_34410a import Keysight34410A, Keysight34411A
from .agilent_3458a import Agilent3458A
from .keysight_truevolt import Keysight34460A, Keysight34461A, Keysight34465A, Keysight34470A, KeysightTruevolt
from .keysight_dacq import Keysight34970A, Keysight34972A, KeysightDacq, channel_for, pair_channel
from .scpi_dmm import Agilent34401A, Fluke8846A, ScpiDmm
from .fluke_8808a import Fluke8808A
from .fluke_8808a_cal import Fluke8808ACal
from .tektronix_mdo4000c import TektronixMDO4000C
from .tektronix_mdo3 import TektronixMDO3
from .tektronix_tds2000c import TektronixTDS2000C
from .reference_instruments import AgilentAFG, Fluke96270A, ReferenceMeter
from .fluke_5790b import SERIAL_DEFAULT as FLUKE_5790B_SERIAL
from .fluke_5790b import Fluke5790B
from .keysight_332xx import Keysight332xx, Keysight33210A, Keysight33220A, Keysight33250A
from .keysight_5313x import Keysight5313x, Keysight53131A, Keysight53132A
from . import fluke_28x
from .fluke_28x import Fluke28x
from .transport import CommandLog, SerialSettings, SerialTransport, Transport, TransportError, VisaTransport, bus_of


def open_visa(address, timeout=10.0, **serial_kwargs):
    """Transport for a VISA address (USB..., GPIB..., ASRL...). Serial keywords (baud, parity ...) only
    matter for ASRL/RS-232 resources."""
    serial = SerialSettings(**serial_kwargs) if serial_kwargs else None
    return VisaTransport(address, timeout=timeout, serial=serial)
