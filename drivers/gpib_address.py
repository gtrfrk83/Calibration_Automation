"""GPIB primary-address helpers shared by the Fluke 6060A, HP 8902A and HP 8563E drivers.

A driver never hard-codes an address: each class carries a DEFAULT_ADDRESS (the owner's lab address, shown in the engine's address box) and takes the address as a
constructor / connect() parameter. The transport is re-targeted to that address before it is opened. Transports with no GPIB resource string (the simulators, a serial
port) are left alone. Nothing here talks to an instrument.
"""
from __future__ import annotations

import re

from .base import InstrumentError

_GPIB = re.compile(r'^(GPIB\d*)::(\d+)((?:::.*)?)$', re.I)
MAX_ADDRESS = 30                     # IEEE-488 primary addresses 0 to 30 (31 is "unlisten / untalk")


def check_address(address) -> int:
    """The address as an int 0..30; raises InstrumentError for anything else (a bool, text with letters, 31 and up)."""
    if isinstance(address, bool):
        raise InstrumentError(f'GPIB address {address!r} is not a number')
    try:
        n = int(str(address).strip())
    except (TypeError, ValueError):
        raise InstrumentError(f'GPIB address {address!r} is not a number') from None
    if not 0 <= n <= MAX_ADDRESS:
        raise InstrumentError(f'GPIB address {n} is outside 0 to {MAX_ADDRESS}')
    return n


def resource_string(address: int, board: int = 0) -> str:
    """'GPIB0::<address>::INSTR'."""
    return f'GPIB{int(board)}::{check_address(address)}::INSTR'


def address_of(resource) -> int | None:
    """The primary address inside a VISA GPIB resource string, or None (not a GPIB string)."""
    m = _GPIB.match(str(resource or '').strip())
    return int(m.group(2)) if m else None


def retarget(transport, address: int) -> bool:
    """Point a VISA transport at `address` on the same GPIB board it already uses (or board 0 for an empty address). Only a transport with a text `address`
    attribute that is a GPIB resource (or empty) is changed; returns True when it was. Must be called before the transport is opened."""
    current = getattr(transport, 'address', None)
    if not isinstance(current, str):
        return False
    m = _GPIB.match(current.strip())
    if current.strip() and not m:
        return False
    board = m.group(1) if m else 'GPIB0'
    tail = (m.group(3) if m else '') or '::INSTR'
    new = f'{board}::{check_address(address)}{tail}'
    transport.address = new
    if hasattr(transport, 'name'):
        transport.name = new
    return True


def serial_poll(transport) -> int:
    """The status byte by serial poll (SPE / SPD: addressing, not a command text). Uses transport.read_stb() (the simulators) or a VISA resource's read_stb().
    Raises InstrumentError for a transport that cannot poll."""
    poll = getattr(transport, 'read_stb', None)
    if poll is None and getattr(transport, '_res', None) is not None:
        poll = getattr(transport._res, 'read_stb', None)
    if poll is None:
        raise InstrumentError('this transport has no serial poll')
    try:
        return int(poll())
    except InstrumentError:
        raise
    except Exception as exc:
        raise InstrumentError(f'serial poll failed: {exc}') from exc
