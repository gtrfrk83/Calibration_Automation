"""Transports: how bytes reach an instrument (USB, GPIB and RS-232 through VISA, or pyserial).

A driver never imports pyvisa/pyserial itself - it is handed a Transport. That keeps every SCPI string
in the driver, every wire detail here, and lets a simulator stand in for real hardware in tests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import serial
    from pyvisa.resources import MessageBasedResource, SerialInstrument


class TransportError(RuntimeError):
    """I/O failed (timeout, device gone, bad address)."""


@dataclass
class SerialSettings:
    baud: int = 9600
    data_bits: int = 8
    parity: str = 'none'        # none | even | odd
    stop_bits: float = 1
    write_termination: str = '\r'
    read_termination: str = '\r\n'
    flow_control: str = 'none'  # none | xon_xoff | rts_cts


@dataclass
class CommandLog:
    """Every write/query that crosses the wire, in order. Saved with a calibration run as evidence
    of exactly which commands were issued."""
    entries: list = field(default_factory=list)
    echo: bool = False
    virtual: bool = False        # a demo run on simulated instruments: never appended to the shared evidence log

    def add(self, direction, text, instrument=''):
        entry = (time.time(), instrument, direction, text)
        self.entries.append(entry)
        if self.echo:
            print(f'{instrument:>10} {direction} {text}')

    def lines(self):
        t0 = self.entries[0][0] if self.entries else 0
        return [f'{t - t0:9.3f}  {inst:<10} {d}  {txt}' for t, inst, d, txt in self.entries]

    def append_default(self, name):
        """Append to ~/.calibration_suite/command_log.txt (shared evidence log). Never raises. A virtual (demo) log writes nothing."""
        if self.virtual:
            return
        try:
            from datetime import datetime
            from pathlib import Path
            folder = Path.home() / '.calibration_suite'
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {name}\n')
                f.write('\n'.join(self.lines()) + '\n')
        except OSError:
            pass

    def save(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.lines()) + '\n')


class Transport:
    """Minimal interface every transport implements."""
    name = ''

    def open(self): raise NotImplementedError
    def close(self): raise NotImplementedError
    def write(self, text: str): raise NotImplementedError
    def read(self) -> str: raise NotImplementedError
    def query(self, text: str) -> str:
        self.write(text)
        return self.read()
    def set_timeout(self, seconds: float): pass
    def clear(self): pass
    def go_local(self): pass            # GPIB: address the instrument with GTL (go to local); other buses have nothing to send


def bus_of(address: str) -> str:
    """'USB' / 'GPIB' / 'RS232' / 'TCPIP' from a VISA resource string."""
    a = address.upper()
    for prefix, bus in (('USB', 'USB'), ('GPIB', 'GPIB'), ('ASRL', 'RS232'), ('COM', 'RS232'), ('TCPIP', 'LAN')):
        if a.startswith(prefix):
            return bus
    return 'UNKNOWN'


class VisaTransport(Transport):
    """USB (USBTMC), GPIB and RS-232 (ASRL) via pyvisa. `serial` only applies to ASRL resources."""

    def __init__(self, address, timeout=10.0, serial: SerialSettings | None = None, resource_manager=None):
        self.address = address
        self.name = address
        self.timeout = timeout
        self.serial = serial
        self._rm = resource_manager
        self._own_rm = resource_manager is None
        self._res: MessageBasedResource | None = None

    def _opened(self) -> MessageBasedResource:
        if self._res is None:
            raise TransportError(f'{self.address} is not open')
        return self._res

    def open(self):
        try:
            import pyvisa
            from pyvisa import constants as c
            if self._rm is None:
                self._rm = pyvisa.ResourceManager()
            self._res = cast('MessageBasedResource', self._rm.open_resource(self.address))
            self._res.timeout = int(self.timeout * 1000)
            if bus_of(self.address) == 'RS232':
                s = self.serial or SerialSettings()
                res = cast('SerialInstrument', self._res)
                res.baud_rate = s.baud
                res.data_bits = s.data_bits
                res.parity = {'none': c.Parity.none, 'even': c.Parity.even, 'odd': c.Parity.odd}[s.parity]
                res.stop_bits = {1: c.StopBits.one, 1.5: c.StopBits.one_and_a_half, 2: c.StopBits.two}[s.stop_bits]
                res.write_termination = s.write_termination
                res.read_termination = s.read_termination
                res.flow_control = {'none': c.ControlFlow.none, 'xon_xoff': c.ControlFlow.xon_xoff,
                                    'rts_cts': c.ControlFlow.rts_cts}[s.flow_control]
        except Exception as exc:
            raise TransportError(f'Could not open {self.address}: {exc}') from exc

    def close(self):
        for obj in (self._res, self._rm if self._own_rm else None):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        self._res = None

    def set_timeout(self, seconds):
        self.timeout = seconds
        if self._res is not None:
            self._res.timeout = int(seconds * 1000)

    def write(self, text):
        res = self._opened()
        try:
            res.write(text)
        except Exception as exc:
            raise TransportError(f'write {text!r} failed: {exc}') from exc

    def read(self):
        res = self._opened()
        try:
            return res.read()
        except Exception as exc:
            raise TransportError(f'read failed: {exc}') from exc

    def query(self, text):
        res = self._opened()
        try:
            return res.query(text)
        except Exception as exc:
            raise TransportError(f'query {text!r} failed: {exc}') from exc

    def clear(self):
        if self._res is None:
            return
        try:
            self._res.clear()
        except Exception:
            pass

    def go_local(self):
        """GPIB only: GTL (go to local) addressed to this instrument, which also restores its front panel keys. Never raises."""
        if bus_of(self.address) != 'GPIB' or self._res is None:
            return
        try:
            import pyvisa
            op = getattr(getattr(pyvisa.constants, 'RENLineOperation', None), 'address_gtl', None) or getattr(pyvisa.constants, 'VI_GPIB_REN_ADDRESS_GTL', None)
            if op is not None:
                self._res.control_ren(op)
        except Exception:
            pass


class SerialTransport(Transport):
    """RS-232 straight through pyserial (no VISA needed). Address is a port name like 'COM3'."""

    def __init__(self, port, settings: SerialSettings | None = None, timeout=10.0):
        self.port, self.settings, self.timeout = port, settings or SerialSettings(), timeout
        self.name = port
        self._ser: serial.Serial | None = None

    def _opened(self) -> serial.Serial:
        if self._ser is None:
            raise TransportError(f'{self.port} is not open')
        return self._ser

    def open(self):
        try:
            import serial
            s = self.settings
            self._ser = serial.Serial(
                self.port, baudrate=s.baud, bytesize=s.data_bits, timeout=self.timeout,
                parity={'none': 'N', 'even': 'E', 'odd': 'O'}[s.parity], stopbits=s.stop_bits,
                xonxoff=s.flow_control == 'xon_xoff', rtscts=s.flow_control == 'rts_cts',
                write_timeout=self.timeout)
        except Exception as exc:
            raise TransportError(f'Could not open {self.port}: {exc}') from exc

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def set_timeout(self, seconds):
        self.timeout = seconds
        if self._ser is not None:
            self._ser.timeout = seconds

    def write(self, text):
        ser = self._opened()
        try:
            ser.write((text + self.settings.write_termination).encode('ascii'))
            ser.flush()
        except Exception as exc:
            raise TransportError(f'write {text!r} failed: {exc}') from exc

    def read(self):
        ser = self._opened()
        term = self.settings.read_termination.encode('ascii')
        try:
            data = ser.read_until(term)
        except Exception as exc:
            raise TransportError(f'read failed: {exc}') from exc
        if not data.endswith(term):
            raise TransportError('read timed out')
        return data[:-len(term)].decode('ascii', 'replace')

    def clear(self):
        if self._ser is None:
            return
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
