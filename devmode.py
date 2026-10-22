"""Developer mode: the gate for editing tolerances (limit overrides).  Tk-free; the only I/O is one small JSON file.

    dm = DevMode()                         # path defaults to ~/.calibration_suite/devmode.json (injectable: DevMode(path=...))
    dm.is_set()                            # has a passphrase been chosen yet?
    session = dm.set_passphrase(pw)        # first use only; returns an unlocked session
    session = dm.unlock(pw)                # raises BadPassphrase / LockedOut(wait_s)
    session.valid()                        # unlocked and not idle for more than idle_s (default 15 minutes)
    session.touch()                        # activity: restarts the idle timer (procmods calls it on every use)
    session.lock()                         # explicit lock; also happens automatically when idle
    dm.mac(bytes) / dm.verify_mac(bytes, hexmac)   # HMAC-SHA256 with the device key (integrity of limit override rows)

What is stored in devmode.json: PBKDF2-HMAC-SHA256 hash + random salt + iteration count of the passphrase, a random device key (for the
row HMACs), and the failure counter / lock-out time.  The passphrase and any key derived from it are never logged, never put in the
override database, the command log or a report, and a session object holds no key at all.  A forgotten passphrase is reset by deleting
the file (that also makes existing limit overrides read as TAMPERED, because the device key is regenerated; nothing else is affected).

Limitation (state it in the docs): this stops casual editing of the database and of the settings by someone using the suite.  Anyone
with access to the files and the program can bypass it; it is not a security boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

IDLE_S = 15 * 60
ITERATIONS = 240_000
MIN_LEN = 8
FREE_ATTEMPTS = 3            # wrong passphrases before the delay starts
MAX_DELAY_S = 15 * 60


class DevModeError(Exception):
    pass


class BadPassphrase(DevModeError):
    pass


class LockedOut(DevModeError):
    def __init__(self, wait_s):
        super().__init__(f'too many wrong passphrases; try again in {int(wait_s) + 1} s')
        self.wait_s = wait_s


def default_path() -> Path:
    return Path.home() / '.calibration_suite' / 'devmode.json'


class DevSession:
    """An unlocked developer-mode session.  Holds no secret; `valid()` is the only thing callers need."""

    def __init__(self, devmode, clock):
        self.devmode = devmode
        self._clock = clock
        self._last = clock()
        self._locked = False

    def valid(self) -> bool:
        if self._locked:
            return False
        if self._clock() - self._last > self.devmode.idle_s:
            self._locked = True
        return not self._locked

    def touch(self) -> bool:
        """Count this as activity (restarts the idle timer).  False if the session is already locked."""
        if not self.valid():
            return False
        self._last = self._clock()
        return True

    def lock(self):
        self._locked = True

    @property
    def remaining_s(self) -> float:
        return 0.0 if not self.valid() else max(0.0, self.devmode.idle_s - (self._clock() - self._last))

    def __repr__(self):
        return f'<DevSession {"unlocked" if self.valid() else "locked"}>'


class DevMode:
    def __init__(self, path=None, clock=time.monotonic, wall=time.time, iterations=ITERATIONS, idle_s=IDLE_S):
        self.path = Path(path) if path else default_path()
        self._clock = clock
        self._wall = wall
        self.iterations = iterations
        self.idle_s = idle_s

    # ------------------------------------------------------------------------------------------------ file
    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix='.devmode', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=1, sort_keys=True)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def is_set(self) -> bool:
        d = self._read()
        return bool(d.get('hash') and d.get('salt'))

    # ------------------------------------------------------------------------------------------------ passphrase
    def _hash(self, passphrase: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac('sha256', passphrase.encode('utf-8'), salt, iterations, dklen=32)

    def set_passphrase(self, passphrase: str) -> DevSession:
        """First use: choose the passphrase.  Refuses when one is already set (delete the file to reset)."""
        if self.is_set():
            raise DevModeError('a passphrase is already set')
        if not isinstance(passphrase, str) or len(passphrase) < MIN_LEN:
            raise DevModeError(f'the passphrase needs at least {MIN_LEN} characters')
        data = self._read()
        salt = secrets.token_bytes(16)
        data.update({'version': 1, 'salt': salt.hex(), 'iterations': self.iterations,
                     'hash': self._hash(passphrase, salt, self.iterations).hex(),
                     'device_key': data.get('device_key') or secrets.token_hex(32), 'fails': 0, 'locked_until': 0})
        self._write(data)
        return DevSession(self, self._clock)

    def change_passphrase(self, old: str, new: str) -> DevSession:
        self.unlock(old)
        if len(new or '') < MIN_LEN:
            raise DevModeError(f'the passphrase needs at least {MIN_LEN} characters')
        data = self._read()
        salt = secrets.token_bytes(16)
        data.update({'salt': salt.hex(), 'iterations': self.iterations, 'hash': self._hash(new, salt, self.iterations).hex()})
        self._write(data)
        return DevSession(self, self._clock)

    def lockout_remaining(self) -> float:
        return max(0.0, float(self._read().get('locked_until') or 0) - self._wall())

    def unlock(self, passphrase: str) -> DevSession:
        data = self._read()
        if not (data.get('hash') and data.get('salt')):
            raise DevModeError('no passphrase is set yet')
        wait = max(0.0, float(data.get('locked_until') or 0) - self._wall())
        if wait > 0:
            raise LockedOut(wait)
        try:
            salt = bytes.fromhex(data['salt'])
            good = bytes.fromhex(data['hash'])
            got = self._hash(passphrase if isinstance(passphrase, str) else '', salt, int(data.get('iterations') or self.iterations))
        except (ValueError, TypeError):
            raise DevModeError('devmode.json is damaged; delete it to reset')
        if not hmac.compare_digest(good, got):
            fails = int(data.get('fails') or 0) + 1
            data['fails'] = fails
            if fails >= FREE_ATTEMPTS:
                data['locked_until'] = self._wall() + min(MAX_DELAY_S, 5 * 2 ** (fails - FREE_ATTEMPTS))
            self._write(data)
            raise BadPassphrase('wrong passphrase')
        if data.get('fails') or data.get('locked_until'):
            data['fails'] = 0
            data['locked_until'] = 0
            self._write(data)
        return DevSession(self, self._clock)

    # ------------------------------------------------------------------------------------------------ integrity key
    def device_key(self, create=False):
        """The HMAC key (bytes) or None when the file has none.  create=True makes one (needed when signing)."""
        data = self._read()
        key = data.get('device_key')
        if not key and create:
            data['device_key'] = key = secrets.token_hex(32)
            data.setdefault('version', 1)
            self._write(data)
        try:
            return bytes.fromhex(key) if key else None
        except ValueError:
            return None

    def mac(self, payload: bytes) -> str:
        key = self.device_key(create=True)
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    def verify_mac(self, payload: bytes, mac: str) -> bool:
        key = self.device_key(create=False)
        if not key or not mac:
            return False
        return hmac.compare_digest(hmac.new(key, payload, hashlib.sha256).hexdigest(), str(mac))
