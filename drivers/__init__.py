"""Instrument drivers for the calibration suite (one driver per model).

    from drivers import Fluke5560A, WaveSurfer4104HD, open_visa
    with Fluke5560A(open_visa('ASRL9::INSTR', baud=9600)) as cal: ...

Add a model by copying drivers/TEMPLATE.md's checklist - see README.txt in this folder.
"""
from .base import Instrument, InstrumentError, SafetyError
from .fluke_5560a import SERIAL_DEFAULT as FLUKE_5560A_SERIAL
from .fluke_5560a import Fluke5522A, Fluke5560A
from .lecroy_ws4104hd import WaveSurfer4104HD
from .keysight_truevolt import Keysight34460A, Keysight34461A, Keysight34465A, Keysight34470A, KeysightTruevolt
from .keysight_dacq import Keysight34970A, Keysight34972A, KeysightDacq, channel_for, pair_channel
from .scpi_dmm import Agilent34401A, Fluke8846A, ScpiDmm
from .tektronix_mdo4000c import TektronixMDO4000C
from .reference_instruments import AgilentAFG, Fluke96270A, ReferenceMeter
from .transport import CommandLog, SerialSettings, SerialTransport, Transport, TransportError, VisaTransport, bus_of


def open_visa(address, timeout=10.0, **serial_kwargs):
    """Transport for a VISA address (USB..., GPIB..., ASRL...). Serial keywords (baud, parity ...) only
    matter for ASRL/RS-232 resources."""
    serial = SerialSettings(**serial_kwargs) if serial_kwargs else None
    return VisaTransport(address, timeout=timeout, serial=serial)
