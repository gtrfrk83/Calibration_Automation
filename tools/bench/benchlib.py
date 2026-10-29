"""Shared helpers of the bench scripts that drive the SUITE'S OWN DRIVERS (steps 6 and later): run them from the suite folder (python tools\\bench\\<script>.py).

The 6060A is handled with plain writes here (never the driver's connect(), which sends a device clear: on the 6060A that switches the RF ON at -10 dBm before the
driver switches it off again).  Every write is sent once; RF goes OFF at the end, confirmed by reading the 6060A back (IU field 3 = 400).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GEN_ADDR = 'GPIB1::2::INSTR'
RX_ADDR = 'GPIB1::14::INSTR'
SA_ADDR = 'GPIB1::18::INSTR'


class Bench:
    def __init__(self, step, title, owner_ok):
        self.name = f'bench_step{step}_result'
        self.out = open(self.name + '.txt', 'w', encoding='utf-8')
        self.t0 = time.time()
        self.log = {'step': step, 'title': title, 'owner_ok': owner_ok, 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'events': [], 'results': []}
        import drivers
        self.drivers = drivers
        self.cmdlog = drivers.CommandLog()               # what the drivers send and receive, exactly
        self.say(f'Bench step {step}: {title}  {self.log["started"]}   suite folder: {ROOT}')
        import pyvisa
        self.pyvisa = pyvisa
        self.rm = pyvisa.ResourceManager()
        self.gen = None
        self.rf_on = False

    # ---- output
    def say(self, text=''):
        print(text)
        self.out.write(text + '\n')
        self.out.flush()

    def event(self, who, kind, cmd=None, reply=None, error=None, note=''):
        rec = {'t': round(time.time() - self.t0, 3), 'who': who, 'kind': kind, 'cmd': cmd, 'reply': reply, 'error': error, 'note': note}
        self.log['events'].append(rec)
        self.say(f'   {rec["t"]:8.3f}  {who:6} {kind:6} ' + (f'{cmd!r} ' if cmd is not None else '') + (f'-> {reply!r}' if reply is not None else '')
                 + (f' ERROR {error}' if error else '') + (f'  {note}' if note else ''))

    def result(self, **kw):
        self.log['results'].append(kw)
        self.say('   RESULT ' + ', '.join(f'{k}={v}' for k, v in kw.items()))

    def ask_operator(self, question):
        try:
            return input(question).strip()
        except EOFError:
            return ''

    # ---- the 6060A, plain writes
    def open_gen(self):
        g = self.rm.open_resource(GEN_ADDR)
        g.write_termination = '\n'
        g.read_termination = '\n'
        g.timeout = 4000
        self.gen = g
        ident = self.gq('ID')
        if not ident or '6060A' not in ident:
            raise SystemExit(f'Not a 6060A at {GEN_ADDR}: {ident!r}. Nothing was switched on.')
        self.gq('IR', note='clear any old rejected entry (read)')
        self.gw('RO0', 'RF off first')
        return g

    def gw(self, cmd, note=''):
        try:
            self.gen.write(cmd)
            self.event('6060A', 'write', cmd, note=note)
        except Exception as exc:                 # noqa: BLE001
            self.event('6060A', 'write', cmd, error=f'{type(exc).__name__}: {str(exc)[:140]}', note=note)
            raise

    def gq(self, cmd, note=''):
        try:
            reply = self.gen.query(cmd).strip()
            self.event('6060A', 'query', cmd, reply=reply, note=note)
            return reply
        except Exception as exc:                 # noqa: BLE001
            self.event('6060A', 'query', cmd, error=f'{type(exc).__name__}: {str(exc)[:140]}', note=note)
            return None

    @staticmethod
    def learn(text):
        s = (text or '').strip()
        h = lambda t: int(''.join('0123456789ABCDEF'[ord(c) - 65] for c in t), 16)      # noqa: E731
        amp = h(s[8:12])
        amp = amp - 65536 if amp >= 32768 else amp
        return h(s[24:32]), amp / 10.0

    def gen_set(self, mhz=None, dbm=None):
        """FR / AP (each once), then IR must be all zero and LM99 must read back what was asked; raises SystemExit otherwise (the finally block turns RF off)."""
        if mhz is not None:
            self.gw(f'FR{mhz:g}MZ')
        if dbm is not None:
            self.gw(f'AP{dbm:g}DB')
        time.sleep(0.5)
        rej = self.gq('IR', note='rejected entries (000000,... = none)')
        f_hz, a = self.learn(self.gq('LM99', note='read back'))
        self.say(f'   6060A read back: {f_hz} Hz, {a} dBm')
        if rej is None or any(ch not in '0,' for ch in rej) or (mhz is not None and f_hz != round(mhz * 1e6)) or (dbm is not None and a != float(dbm)):
            raise SystemExit('The 6060A did not take the setting (see above).')
        self.last_mhz = f_hz / 1e6
        return f_hz, a

    def rf(self, on):
        if on:
            self.rf_on = True
            self.gw('RO1', 'RF ON')
            time.sleep(1.0)
            self.gq('IU', note='UNCAL codes with RF on (all zero = none)')
        else:
            self.gw('RO0', 'RF OFF')

    def finish(self):
        """RF off (confirmed), front panels back to local, the files written. Call it in a finally block."""
        if self.gen is not None:
            if self.rf_on:
                self.say('\n-- 6060A: RF OFF')
                try:
                    self.gw('RO0', 'RF off at the end')
                except Exception:                # noqa: BLE001
                    pass
                time.sleep(0.5)
                iu = self.gq('IU', note='RF off is confirmed when field 3 has 400')
                try:
                    off = bool(int(iu.split(',')[2], 8) & 0o400)
                except Exception:                # noqa: BLE001
                    off = None
                self.log['rf_off_confirmed'] = off
                self.say(f'   RF OFF confirmed by read-back: {off}' + ('' if off else '   <-- CHECK THE 6060A FRONT PANEL: press RF OUTPUT OFF'))
            try:
                self.gen.control_ren(self.pyvisa.constants.RENLineOperation.address_gtl)
            except Exception:                    # noqa: BLE001
                pass
            self.gen.close()
        self.log['driver_log'] = self.cmdlog.lines()
        self.log['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        self.say('\n-- the drivers\' own command log:')
        for line in self.log['driver_log']:
            self.say('   ' + line)
        with open(self.name + '.json', 'w', encoding='utf-8') as f:
            json.dump(self.log, f, indent=1, default=str)
        self.say(f'\nDone. Send back {self.name}.txt and {self.name}.json.')
