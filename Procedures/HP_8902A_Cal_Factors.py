"""HP 8902A power-sensor cal factors, window.  The logic is hp8902a_calfactors.py (no UI toolkit), the window code is hp8902a_calfactors_view_qt.py.

THIS CHANGES THE CAL-FACTOR TABLE STORED IN THE 8902A (non-volatile).  Method: special function 37 of the 8902A Operating and Calibration Manual (pp. 3-75 to 3-78, 3-82, 3-87).
Nothing is sent to the receiver before the typed ENTER confirmation; reading the table (37.4 / 37.5 / 37.6) changes nothing.  Every write is sent once, read back and compared;
the first mismatch stops the run.  The audit record (adjustment_runs / adjustment_events in lab_registry.sqlite3) is the report: no PDF, like the Keithley 2000 adjustment.
Demo (virtual instrument, nothing persisted):  python Procedures/HP_8902A_Cal_Factors.py --demo
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import adjustment_audit
import drivers
import hp8902a_calfactors as cfx
import sensor_cal_factor_store
import ui_theme_core as ui                   # only its toolkit-free helpers here (Settings)
import virtualbench
from drivers.gpib_address import address_of, check_address
from ui_port import ui as port          # every dialog, variable and window operation goes through the UI port (ui_port.py)

TITLE = 'HP 8902A  -  Power Sensor Cal Factors'
NOTICE = cfx.NOTICE
PROBLEM_TITLE = 'Cal-factor list'


def to_visa(text):
    """'14' -> 'GPIB0::14::INSTR'; a full VISA resource passes through."""
    t = str(text).strip()
    if '::' in t or t.upper().startswith(('GPIB', 'USB', 'TCPIP', 'ASRL')):
        return t
    if t.isdigit() and 0 <= int(t) <= 30:
        return f'GPIB0::{int(t)}::INSTR'
    raise ValueError('Enter a GPIB address (0 to 30, factory default 14) or a full VISA resource such as GPIB0::14::INSTR.')


class IO:
    """The 8902A through its driver (a simulated transport in demo)."""

    def __init__(self, addr, transport=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual:
            self.log.virtual = True
        n = None
        if transport is None:
            res = to_visa(addr)
            n = address_of(res)
            if n is None:
                raise ValueError(f'The 8902A address must be a GPIB address, not {str(addr).strip()!r}.')
            n = check_address(n)
            transport = drivers.open_visa(res, timeout=40)
        self.rx = drivers.HP8902A(transport, self.log, label='8902A', address=n)
        try:
            self.rx.connect()
        except Exception:
            self.close()
            raise
        self.ident = self.rx.idn or 'HP 8902A (no ID reply)'

    def close(self):
        try:
            self.rx.cleanup()
        except Exception:
            pass
        try:
            self.rx.close()
        except Exception:
            pass


class App(virtualbench.VirtualMixin):
    VIEW = 'hp8902a_calfactors_view'                    # window code: hp8902a_calfactors_view_qt.py

    def __init__(self, root, demo=False):
        self.init_virtual(demo, False)
        self.root, self.demo = root, demo
        self.io = None
        self.session = None
        self.busy = False
        self.audit = adjustment_audit.AuditStore(demo=demo)
        self.tables = sensor_cal_factor_store.SensorTableStore(demo=demo)
        self.ui_view.setup_window(self)
        self.settings = ui.Settings('HP8902ACalFactors')
        self.asset, self.serial, self.tech = port.var(), port.var(), port.var()
        self.sensor_model, self.sensor_serial = port.var('11722A'), port.var()
        self.reference = port.var()
        self.remove_stale = port.var(True, 'bool')
        self.addr = port.var(self.settings.get('addr_8902A', str(drivers.HP8902A.DEFAULT_ADDRESS)))
        self.status = port.var()
        self.next_hint = port.var()
        self._build_ui()
        self.status.set('DEMO MODE (virtual instrument): commands go to a simulated 8902A; nothing is saved or recorded as evidence.' if demo
                        else 'Enter the instrument ID, the GPIB address and press Connect.')
        self._sync()
        port.on_close(root, self.on_close)

    @property
    def ui_view(self): return port.view(self.VIEW)

    def _build_ui(self): self.ui_view.build_ui(self)

    def _toggle_log(self): self.ui_view.toggle_log(self)

    # ------------------------------------------------------------------ state
    def _active(self):
        return self.session is not None and not self.session.entered and self.audit.status() not in ('ABORTED', 'STOPPED')

    def _sync(self):
        live, act, b = self.io is not None, self._active(), self.busy
        self.ui_view.sync_pills(self, live)
        self.ui_view.sync_buttons(self, not live and not b, live and not act and not b, not b, act and not b, not b, not b, bool(act), live and not b)
        self.ui_view.rows_lock(self, b)
        if not live:
            hint = 'Enter the instrument ID, the GPIB address and press Connect.'
        elif not act and not (self.session and self.session.entered):
            hint = 'Enter instrument ID, serial number, technician and the sensor model and serial, then press "Start record and read table".'
        elif self.session and self.session.entered:
            hint = 'The table is entered. Read the audit log for the pass / fail summary, then press "Disconnect" (or start another record).'
        else:
            hint = 'Type the label values (or load a saved table), press "Check my list", then "Enter table into the 8902A".'
        self.next_hint.set(hint)

    def _audit_row(self, row, step_id=''):
        t, action, outcome, detail = row
        tag = 'bad' if outcome in ('FAILED', 'ERROR', 'NOT CONFIRMED', 'COULD NOT CONFIRM', 'NOT READ') else 'ok' if outcome in ('OK', 'CONFIRMED') else ''
        self.ui_view.log_add(self, (t, step_id, action, outcome, detail), (tag,) if tag else ())

    def _show_table(self, data):
        self.ui_view.table_clear(self)
        if not data or data['count'] < 1:
            return
        self.ui_view.table_add(self, 'ref', ('R', '50 (reference)', f'{data["reference"]:g}', '', 'in the 8902A'), ())
        for i, (f, c) in enumerate(data['pairs'], 1):
            self.ui_view.table_add(self, f'p{i}', (str(i), f'{f:g}', f'{c:g}', '', 'in the 8902A'), ())

    def _show_result(self, res):
        self.ui_view.table_clear(self)
        for i, c in enumerate(res.checks, 1):
            name = {'reference': '50 (reference)', 'count': 'entry count'}.get(c.kind, f'{c.mhz:g}' if c.mhz is not None else '')
            self.ui_view.table_add(self, f'c{i}', (str(i), name, '' if c.entered is None else f'{c.entered:g}', '' if c.read is None else f'{c.read:g}',
                                                  ('PASS' if c.ok else 'FAIL') + (f' - {c.note}' if c.note else '')), ('done',) if c.ok else ('failed',))

    def _list(self):
        """(Table, problems) of the typed values."""
        return cfx.validate(self.reference.get(), self.ui_view.rows_get(self))

    # ------------------------------------------------------------------ connect
    def connect(self):
        if not self.asset.get().strip():
            port.message('warning', 'Instrument ID', 'Enter the instrument ID first.')
            return
        self.status.set('Connecting ...')
        port.flush(self.root)
        try:
            if self.demo:
                from drivers.simulated_8902a import make_8902a_bench
                _bench, t = make_8902a_bench()
                self.io = IO('14', transport=t, virtual=True)
            else:
                self.io = IO(self.addr.get())
        except Exception as exc:
            self.io = None
            self.status.set('Connection error: ' + str(exc).splitlines()[0])
            port.message('error', 'Connection error', str(exc))
            self._sync()
            return
        if not self.demo:
            self.settings.set('addr_8902A', self.addr.get())
            self.settings.save()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set(f'Connected: {self.io.ident}{tag}. Nothing has been changed.')
        self._sync()

    # ------------------------------------------------------------------ record and read
    def start_record(self):
        need = [self.asset, self.serial, self.tech, self.sensor_model, self.sensor_serial]
        if not all(v.get().strip() for v in need):
            port.message('warning', 'Required information', 'Enter instrument ID, serial number, technician, sensor model and sensor serial number.')
            return
        if self.io is None or self.busy:
            return
        facts = [('Instrument', f'{self.asset.get().strip()}  (serial {self.serial.get().strip()})'), ('Power sensor', f'{self.sensor_model.get().strip()}  serial {self.sensor_serial.get().strip()}')]
        if not port.operator_prompt('Start record', 'Read the cal-factor table of the 8902A?', list(cfx.SENSOR_CHECKLIST), facts=facts,
                                    caution='Reading changes nothing in the table. Nothing is written until you type ENTER later.', ok='Start record and read', parent=self.root):
            return
        self.busy = True
        self._sync()
        port.flush(self.root)
        try:
            self.audit.start_run(cfx.INSTRUMENT, self.asset.get().strip(), self.serial.get().strip(), self.tech.get().strip(), uut_idn=self.io.ident,
                                 scope=f'sensor {self.sensor_model.get().strip()} {self.sensor_serial.get().strip()}')
            self.ui_view.log_clear(self)
            self.session = cfx.Session(self.io.rx, self.audit, on_log=self._audit_row)
            self.session.log('RUN_STARTED', 'OK', f'{cfx.INSTRUMENT} {self.io.ident}; sensor {self.sensor_model.get().strip()} {self.sensor_serial.get().strip()}'
                             + (' [DEMO: nothing saved]' if self.demo else ''))
            data = self.session.read_existing()
            self._show_table(data)
        except Exception as exc:
            self.session = None
            self.status.set('Not started: ' + str(exc).splitlines()[0])
            port.message('error', 'Table not read', str(exc))
            return
        finally:
            self.busy = False
            self._sync()
        n = max(data['count'] - 1, 0)
        self.status.set(f'Record active ({self.audit.run_id}). The 8902A holds {n} pair(s) and ' + (f'reference {data["reference"]:g} %.' if data['count'] >= 1 else 'no reference.')
                        + ' Nothing has been changed.')

    # ------------------------------------------------------------------ list
    def check_list(self):
        table, problems = self._list()
        if table is None:
            port.message('warning', PROBLEM_TITLE, 'Fix these before anything can be entered:\n\n- ' + '\n- '.join(problems))
            self.status.set(f'{len(problems)} problem(s) in the list.')
            return None
        self.status.set(f'The list is valid: reference {table.reference:g} %, {len(table.pairs)} pair(s), ascending {table.pairs[0][0]:g} to {table.pairs[-1][0]:g} MHz. Nothing was sent.')
        return table

    def load_saved(self):
        got = self.tables.load(self.sensor_model.get(), self.sensor_serial.get())
        if got is None:
            port.message('info', 'Saved table', 'No saved table for this sensor model and serial number.' + ('\n\nDEMO: nothing is kept after the window closes.' if self.demo else ''))
            return
        self.reference.set(f'{got["reference"]:g}')
        self.ui_view.rows_set(self, [(f'{f:g}', f'{c:g}') for f, c in got['pairs']])
        self.status.set(f'Loaded the table saved {got["saved_at"]} by {got["saved_by"] or "?"}. Check it against the sensor label before entering it.')

    def save_list(self):
        table = self.check_list()
        if table is None:
            return
        try:
            self.tables.save(self.sensor_model.get(), self.sensor_serial.get(), table.reference, table.pairs, self.tech.get().strip())
        except ValueError as exc:
            port.message('warning', 'Save', str(exc))
            return
        self.status.set('List saved for this sensor' + (' (DEMO: only until the window closes).' if self.demo else ' in lab_registry.sqlite3.'))

    # ------------------------------------------------------------------ the entry
    def enter_table(self):
        s = self.session
        if s is None or self.busy or not self._active():
            return
        table = self.check_list()
        if table is None:
            return
        try:
            stale, after = s.plan(table, bool(self.remove_stale.get()))
        except cfx.CalFactorError as exc:
            port.message('error', 'Cannot enter this list', str(exc))
            return
        lines = [f'Sensor: {self.sensor_model.get().strip()} serial {self.sensor_serial.get().strip()}', f'Reference cal factor: {table.reference:g} %',
                 'Pairs: ' + ', '.join(f'{f:g} MHz {c:g} %' for f, c in table.pairs)]
        if stale:
            lines.append('Entries removed from the 8902A (entered as 0 %): ' + ', '.join(f'{f:g} MHz' for f in stale))
        text = ('THIS CHANGES THE CAL-FACTOR TABLE STORED IN THE 8902A. It is non-volatile and the manual has no undo.\n\n' + '\n'.join(lines)
                + f'\n\nThe table will then hold {after} pair(s). Each entry is sent once and read back; the first mismatch stops the run.\n\nType  {cfx.CONFIRM_ENTER}  to enter it:')
        phrase = port.ask_text('ENTER the cal-factor table', text, parent=self.root)
        if phrase != cfx.CONFIRM_ENTER:
            s.log('CONFIRM', 'NOT CONFIRMED', 'the confirmation was not typed; nothing was sent')
            self.status.set('Not entered: the confirmation was not typed. Nothing was sent.')
            return
        self.busy = True
        self._sync()
        port.flush(self.root)
        try:
            res = s.enter(table, phrase, bool(self.remove_stale.get()))
        except cfx.EntryStopped as exc:
            self.status.set('STOPPED: ' + str(exc).splitlines()[0])
            port.message('error', 'Entry stopped', str(exc))
            return
        except cfx.CalFactorError as exc:
            self.status.set(str(exc).splitlines()[0])
            port.message('error', 'Not entered', str(exc))
            return
        finally:
            self.busy = False
            self._sync()
        self._show_result(res)
        self.status.set(('Table entered and read back: all checks passed.' if res.ok else 'Table entered but the read-back FAILED: see the list and the audit log.')
                        + (' [DEMO: simulated 8902A]' if self.demo else ''))
        port.message('info' if res.ok else 'error', ('Entered' if res.ok else 'Read-back failed') + (' (DEMO)' if self.demo else ''),
                     '\n'.join(res.lines) + ('\n\nThe read-back mechanism is UNVERIFIED on the real receiver: compare the 8902A display (37.5 / 37.6 SPCL) with the sensor label.' if not self.demo else
                                            '\n\nDEMO: this was a simulated receiver; nothing was recorded as evidence.'))

    def abort(self):
        s = self.session
        if s is None or self.busy or not self._active():
            return
        if not port.ask_yes_no('Abort', 'Stop this record? Nothing further is sent. (Entries already written stay in the 8902A.)', icon='warning'):
            return
        s.abort('operator')
        self._sync()
        self.status.set('Record aborted.')

    def disconnect(self):
        if self.session and self._active():
            self.session.abort('operator (disconnect)')
        if self.io:
            self.io.close()
            self.io = None
        self.session = None
        self.ui_view.table_clear(self)
        self._sync()
        self.status.set('Disconnected.')

    def on_close(self):
        if self.busy:
            return
        try:
            if self.io:
                self.io.close()
        finally:
            self.audit.close()
            self.tables.close()
            port.close(self.root)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    demo, _fast = virtualbench.flags(argv)
    port.enable_hidpi()
    port.run_app(lambda root: App(root, demo=demo))


if __name__ == '__main__':
    main()
