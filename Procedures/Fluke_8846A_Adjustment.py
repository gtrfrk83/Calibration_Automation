"""Fluke 8846A guided adjustment v57 — controlled initial implementation.

CAUTION: Calibration commands modify volatile adjustment coefficients. CAL:REC
writes nonvolatile calibration memory. Only trained technicians should use live mode.
Source: Fluke 8845A/8846A Calibration Manual, Chapter 3, and Programmer's Manual.
The verified open-step subset is provided; other adjustment stages are intentionally
review-only until the exact revision-specific tables and 5560A commands are validated.
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.append(str(BASE.parent))  # shared ui_theme.py sits next to the Manager
import ui_port
import ui_theme as ui                   # only its toolkit-free helpers here (Settings); the window code is in fluke8846a_adjust_view_tk.py
import drivers
import reset_startup
from ui_port import ui as port          # every dialog, variable and window operation goes through the UI port (ui_port.py)
DB = BASE / 'calibration_procedures.sqlite3'
STEPS = [
    ('PRE', 'As Found verification', 'Run and save the complete independent 8846A performance verification before any adjustment.', '', '', False),
    ('PRE', 'Equipment and safety', 'Verify technician authorization, warm-up, 5560A traceability, required fixtures, firmware and correct 8846A identity.', '', '', False),
    ('OPEN', '100 MΩ open', 'Disconnect all leads from meter inputs. Verify open terminals and correct front/rear selection.', 'ORES', '100000000', True),
    ('OPEN', '1 GΩ open (8846A)', 'Keep all terminals open. This step applies to the 8846A only.', 'ORES', '1000000000', True),
    ('OPEN', '1 nF capacitance open (8846A)', 'Keep terminals open and confirm the capacitance setup specified by the manual.', 'ZCAP', '1.00E-09', True),
    ('ZERO', 'AC voltage short adjustments', 'Install the specified 4-wire low-thermal short. Complete the ACV zero sequence from the revision-matched adjustment table.', '', '', False),
    ('ZERO', 'DC voltage short adjustments', 'With the prescribed low-thermal short, complete the DCV zero sequence from the adjustment table.', '', '', False),
    ('ZERO', 'Resistance and current zero adjustments', 'Use the manual-specific shorts/opens and current terminals; confirm each connection before adjustment.', '', '', False),
    ('REAR', 'Rear-panel zero adjustments', 'Select rear terminals and install the manual-specified low-thermal fixtures; perform all required rear-zero steps.', '', '', False),
    ('GAIN', 'DC gain adjustments', 'Verify Fluke 5560A range, uncertainty, polarity, wiring and each adjustment setpoint from the manual before enabling source automation.', '', '', False),
    ('GAIN', 'AC gain and linearity', 'Follow manual order. AC linearity adjustments must be followed by AC gain adjustment.', '', '', False),
    ('GAIN', 'Resistance, current, frequency, capacitance', 'Perform only with the required standards, cables, guards, and manual-specific setup.', '', '', False),
    ('FINISH', 'Record coefficients', 'After successful complete adjustment and review, explicitly commit changed calibration coefficients.', '', '', False),
    ('FINISH', 'As Left verification', 'Relock calibration and run the independent performance verification again; archive results.', '', '', False),
]


def connect_db():
    con = sqlite3.connect(DB)
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('''CREATE TABLE IF NOT EXISTS adjustment_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id TEXT NOT NULL, serial_number TEXT NOT NULL,
        technician TEXT NOT NULL, meter_idn TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    con.execute('''CREATE TABLE IF NOT EXISTS adjustment_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES adjustment_runs(id),
        event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        step_index INTEGER, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '')''')
    con.commit()
    return con


def open_meter(port, baud, parity, bits):
    """Open the 8846A for adjustment through the instrument driver (RS-232, 1 stop bit, LF terminated)."""
    settings = drivers.SerialSettings(baud=int(baud), data_bits=int(bits), parity=parity.lower(), stop_bits=1,
                                      write_termination='\n', read_termination='\n')
    meter = drivers.Fluke8846A(drivers.SerialTransport(port, settings, timeout=10), drivers.CommandLog(), label='8846A')
    return meter.connect_for_adjustment()


class App:
    def __init__(self, root, demo=False):
        self.root, self.demo = root, demo
        self.meter = None
        self.run_id = None
        self.committed = False
        self.unlocked = False
        self.conn = connect_db()
        self.ui_view.setup_window(self)
        self.settings = ui.Settings('8846A_adjustment')
        self.asset = port.var()
        self.serial = port.var()
        self.tech = port.var()
        self.port = port.var(self.settings.get('port', 'COM3'))
        self.baud = port.var(self.settings.get('baud', '9600'))
        self.parity = port.var(self.settings.get('parity', 'None'))
        self.bits = port.var(self.settings.get('bits', '8'))
        self.password = port.var()
        self.status = port.var('DEMO — commands simulated' if demo else 'DISCONNECTED — no adjustment commands enabled')
        self.next_hint = port.var()
        self.detail = port.var('Select a step to see its setup instructions.')
        self._build_ui()
        self.refresh_ports(quiet=True)
        self._sync()
        port.on_close(root, self.close)

    # ------------------------------------------------------------------ layout
    VIEW = 'fluke8846a_adjust_view'                      # the toolkit's window code: fluke8846a_adjust_view_tk (Tk), later _qt

    @property
    def ui_view(self): return port.view(self.VIEW)

    def _build_ui(self): self.ui_view.build_ui(self)

    # ------------------------------------------------------------------ state display
    def _toggle_log(self): self.ui_view.toggle_log(self)

    def _set_state(self, idx, text):
        self.ui_view.table_set_state(self, idx, text, ('done',) if text in ('Reviewed', 'Adjusted', 'Simulated') else
                                     ('eligible',) if STEPS[idx][5] else ())

    def _on_select(self):
        sel = self.ui_view.table_selection(self)
        if sel:
            phase, name, setup, _, _, ok = STEPS[int(sel[0])]
            self.detail.set(f'{name}  ({phase})\n{setup}\n' + ('This step can be executed after you unlock adjustment.' if ok else
                            'Guided review only: perform it on the instrument following the manual; this program will not send commands for it.'))
        self._sync()

    def _sync(self):
        live = self.meter is not None
        ready = live or self.demo
        unlocked = self.unlocked
        self.ui_view.sync_pills(self, live, unlocked)
        sel = self.ui_view.table_selection(self)
        eligible = bool(sel) and STEPS[int(sel[0])][5]
        self.ui_view.sync_buttons(self, not self.unlocked and not self.demo, ready, True, self.run_id is not None,
                                  self.run_id is not None and ready and not self.unlocked,
                                  self.unlocked and self.run_id is not None and eligible, self.unlocked and self.run_id is not None, live or self.unlocked)
        if not ready:
            hint = 'Choose the COM port and press "Connect / verify 8846A".'
        elif self.run_id is None:
            hint = 'Enter Instrument ID, Serial number and Technician, then press "Start new adjustment record".'
        elif self.committed:
            hint = 'Coefficients recorded. Run the independent As Left verification, then press "Relock and disconnect".'
        elif self.unlocked:
            hint = 'Calibration is UNLOCKED. Select an eligible step and execute it, then commit, then relock.'
        else:
            hint = 'Select each step, follow its setup and press "Mark setup reviewed". Unlock only when you are authorised.'
        self.next_hint.set(hint)

    def _audit_row(self, action, detail, outcome):
        tag = 'bad' if outcome in ('ERROR', 'FAILED') else 'ok' if outcome in ('OK', 'CONFIRMED', 'ISSUED', 'DEMO') else ''
        self.ui_view.log_add(self, (dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), action, outcome, detail), (tag,))

    def refresh_ports(self, quiet=False):
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception as e:
            ports = []
            if not quiet:
                port.message('error', 'COM ports', str(e))
        self.ui_view.set_ports(self, ports)
        if not quiet:
            self.status.set('Serial ports found: ' + ', '.join(ports) if ports else 'No serial ports detected - you can still type a port name.')

    def log(self, action, detail='', outcome='', index=None):
        if self.run_id is None: return
        self.conn.execute('INSERT INTO adjustment_events(run_id,step_index,action,detail,outcome) VALUES(?,?,?,?,?)',
                          (self.run_id,index,action,detail,outcome))
        self._audit_row(action, detail, outcome)
        self.conn.execute('UPDATE adjustment_runs SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(self.run_id,))
        self.conn.commit()

    def connect(self):
        if self.demo:
            self.status.set('DEMO — simulated 8846A connection');self._sync();return
        try:
            if self.meter:self.meter.close()
            self.meter=open_meter(self.port.get(),self.baud.get(),self.parity.get(),self.bits.get())
            self.status.set('Connected: '+self.meter.idn)
            self.log('CONNECT',self.meter.idn,'OK')
            if self.run_id is not None and not self.reset_meter():    # resuming a record: reset after reconnecting, before any step
                self.meter.close();self.meter=None;self._sync();return
            self.settings.set('port',self.port.get());self.settings.set('baud',self.baud.get());self.settings.set('parity',self.parity.get());self.settings.set('bits',self.bits.get());self.settings.save()
            self._sync()
        except Exception as e:
            self.meter=None;self._sync()
            self.status.set('Connection error: '+str(e))
            port.message('error', 'Connection error',str(e))

    def reset_meter(self):
        """Reset the 8846A to its default settings before an adjustment record starts (or resumes after reconnecting). The notice about the
        unit under test is asked first; declining or a failed reset ends the start before any adjustment step. Calibration stays locked
        (nothing here sends a CAL: command). Returns True when the meter is reset (or there is no meter: demo)."""
        if self.demo or not self.meter:
            return True
        try:
            reset_startup.reset_all([], [self.meter], confirm=lambda t: port.ask_ok_cancel('Reset instruments', t, icon='warning'),
                                    log=self.meter.log)
        except reset_startup.ResetDeclined as e:
            self.status.set('Not started: the 8846A was not reset (nothing was touched).');self.log('RESET','declined by operator','CANCELLED');return False
        except Exception as e:
            self.status.set('Reset failed - not started: '+str(e).splitlines()[0]);self.log('RESET',str(e).splitlines()[0],'FAILED')
            port.message('error', 'Reset failed - not started',str(e));return False
        self.log('RESET','Instruments reset to default settings at start: '+self.meter.label,'OK')
        return True

    def start(self):
        if not all([self.asset.get().strip(),self.serial.get().strip(),self.tech.get().strip()]):
            port.message('warning', 'Required information','Enter instrument ID, serial number and technician.');return
        if not self.demo and not self.meter:
            port.message('warning', 'Connection required','Connect and identify the 8846A first.');return
        if not port.ask_yes_no('Start new record','Start a new adjustment audit record? This does not unlock the meter.'):
            return
        if not self.reset_meter():return
        cur=self.conn.execute('INSERT INTO adjustment_runs(asset_id,serial_number,technician,meter_idn) VALUES(?,?,?,?)',
                (self.asset.get().strip(),self.serial.get().strip(),self.tech.get().strip(),
                 self.meter.idn if self.meter else 'DEMO'))
        self.run_id=cur.lastrowid;self.conn.commit();self.committed=False;self.ui_view.log_clear(self)
        self.log('RUN_STARTED','Guided adjustment v57','OK')
        self.status.set(f'Adjustment record #{self.run_id} active; no coefficients committed');self._sync()

    def resume(self):
        if not self.asset.get().strip():
            port.message('warning', 'Instrument ID','Enter instrument ID to find previous records.');return
        row=self.conn.execute('SELECT id,serial_number,technician,status FROM adjustment_runs WHERE asset_id=? ORDER BY id DESC LIMIT 1',
                              (self.asset.get().strip(),)).fetchone()
        if not row:
            port.message('info', 'No record','No previous adjustment record found.');return
        if row[3] not in ('IN_PROGRESS','ADJUSTED_NOT_VERIFIED'):
            port.message('warning', 'Record closed','Most recent record is closed. Start a new record.');return
        if not port.ask_yes_no('Resume',f'Resume run #{row[0]} for serial {row[1]}?'):
            return
        self.run_id=row[0];self.serial.set(row[1]);self.tech.set(row[2]);self.log('RUN_RESUMED','Resumed by operator','OK')
        self.status.set(f'Resumed adjustment record #{self.run_id}; reconnect and unlock explicitly');self._sync()

    def selected(self):
        s=self.ui_view.table_selection(self)
        if not s:
            port.message('warning', 'Select a step','Select a row first.');return None
        return int(s[0])

    def mark_reviewed(self):
        idx=self.selected()
        if idx is None:return
        if self.run_id is None:
            port.message('warning', 'Record required','Start or resume an adjustment record first.');return
        if port.ask_yes_no('Review confirmation',f'Confirm you reviewed the setup and manual requirements for:\n{STEPS[idx][1]}'):
            self.log('SETUP_REVIEWED',STEPS[idx][1],'CONFIRMED',idx)
            self._set_state(idx,'Reviewed')

    def unlock(self):
        if self.run_id is None or (not self.demo and not self.meter):
            port.message('warning', 'Prerequisites','Start a record and connect the identified 8846A first.');return
        if not port.ask_yes_no('Authorized adjustment','I am authorized to adjust this instrument, have reviewed the calibration manual, and understand coefficients may change. Continue?'):
            return
        if self.demo:
            self.unlocked=True;self.log('UNLOCK','Simulated','DEMO');self.status.set('DEMO: unlocked (simulated)');self._sync();return
        pw=port.ask_text('Calibration password','Enter the instrument calibration password:',show='*',parent=self.root)
        if not pw:return
        if not re.fullmatch(r'[A-Za-z0-9]{1,12}',pw):
            port.message('error', 'Password','Expected 1–12 alphanumeric characters.');return
        try:
            self.meter.unlock_calibration(pw)
            self.unlocked=True;self.log('UNLOCK','Calibration security verified OFF','OK')
            self.status.set('UNLOCKED — live adjustment enabled for verified open steps only');self._sync()
        except Exception as e:
            self.log('UNLOCK','Unlock failed','ERROR')
            port.message('error', 'Unlock failed',str(e))

    def execute(self):
        idx=self.selected()
        if idx is None:return
        phase,name,setup,mode,value,eligible=STEPS[idx]
        if not eligible:
            port.message('info', 'Not yet validated','This stage is review-only in v56. Exact revision-specific setpoints and 5560A controls require bench validation.');return
        if not self.run_id or not self.unlocked:
            port.message('warning', 'Prerequisites','Start a record and explicitly unlock adjustment first.');return
        if not port.ask_yes_no('Confirm physical setup',f'{name}\n\n{setup}\n\nConfirm all inputs are OPEN and no source is connected. Execute one calibration step?'):
            return
        if not port.ask_yes_no('Final command confirmation',f'Command: CAL:VAL {mode},{value}\nThen: CAL? ON\n\nThis changes volatile calibration coefficients. Proceed?'):
            return
        try:
            if self.demo:reply='+0'
            else:
                # Driver checks for the +0 success reply (calibration manual example); confirm against your firmware.
                reply=self.meter.adjust_step(mode,value)
            self.log('ADJUST_STEP',f'{mode},{value}; reply={reply}','OK' if not self.demo else 'DEMO',idx)
            self._set_state(idx,'Adjusted' if not self.demo else 'Simulated')
            self.status.set(f'Step {idx} accepted; coefficients NOT committed')
        except Exception as e:
            self.log('ADJUST_STEP',f'{mode},{value}: {e}','FAILED',idx)
            port.message('error', 'Adjustment step failed',str(e))

    def commit(self):
        if not self.run_id or not self.unlocked:
            port.message('warning', 'Prerequisites','Active run and unlocked calibration required.');return
        if not port.ask_yes_no('Commit calibration coefficients',
             'CAL:REC writes adjusted coefficients to NONVOLATILE MEMORY.\n\nHave you completed the FULL manual adjustment sequence, validated all steps and checked for errors?'):
            return
        phrase=port.ask_text('Final confirmation','Type COMMIT 8846A to authorize CAL:REC:',parent=self.root)
        if phrase!='COMMIT 8846A':return
        try:
            if not self.demo:self.meter.record_calibration()
            self.log('CAL_RECORD','CAL:REC issued; independent As Left verification required','DEMO' if self.demo else 'ISSUED')
            self.conn.execute("UPDATE adjustment_runs SET status='ADJUSTED_NOT_VERIFIED' WHERE id=?",(self.run_id,));self.conn.commit()
            self.committed=True;self._sync()
            self.status.set('Coefficients recorded; run independent As Left verification before closing calibration')
            port.message('warning', 'As Left verification required','Coefficient record command issued. Perform independent As Left verification and save its report.')
        except Exception as e:
            self.log('CAL_RECORD',str(e),'ERROR');port.message('error', 'Commit failed',str(e))

    def disconnect(self):
        if self.meter:
            try:
                if self.unlocked:
                    pw=port.ask_text('Relock calibration','Enter calibration password to relock:',show='*',parent=self.root)
                    if not pw or not re.fullmatch(r'[A-Za-z0-9]{1,12}',pw):
                        port.message('warning', 'Relock not confirmed','Calibration may remain unlocked. Do not leave the instrument unattended.');return
                    self.meter.lock_calibration(pw)
                    self.log('RELOCK','Security state ON','OK')
                self.meter.log.append_default(f'8846A adjustment {self.asset.get().strip()} run {self.run_id}')
                self.meter.close()
            except Exception as e:
                port.message('error', 'Relock/close error',f'{e}\nMeter may remain unlocked.');return
        self.meter=None;self.unlocked=False;self.committed=False
        self.status.set('Disconnected / demo lock reset');self._sync()

    def close(self):
        if self.meter and self.unlocked:
            port.message('warning', 'Relock first','Calibration is unlocked. Use Relock and Disconnect before exiting.');return
        try:self.disconnect()
        except Exception:pass
        self.conn.close();port.close(self.root)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--demo',action='store_true')
    args=parser.parse_args()
    port.enable_hidpi()
    port.run_app(lambda root: App(root,demo=args.demo))

if __name__=='__main__':main()
