"""8846A 1-year gain verification. RS-232 DMM + Fluke 5560A.
Hardware I/O is OFF in demo mode. Never run unattended: wiring confirmations required.
Source: Fluke 8845A/8846A Calibration Manual, Tables 3-4 and 3-18 (1-year).
"""
import csv, json, math, sys, threading, time, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # shared ui_theme.py sits next to the Manager
import ui_theme as ui
import drivers
DATA=HERE/'8846A_results.json'
POINTS=[]
def add(kind,nominal,rng,low,high,unit,frequency=None,description=None,wiring=None):
    POINTS.append(dict(id=len(POINTS)+1,kind=kind,nominal=nominal,range=rng,
        error=max(abs(high-nominal),abs(nominal-low)),low=low,high=high,
        unit=unit,frequency=frequency,description=description or kind,
        wiring=wiring or ('CURRENT' if kind in ('DCI','ACI') else 'VOLTAGE' if kind in ('DCV','ACV','FREQ') else 'RESISTANCE_4W' if kind=='OHM4' else 'RESISTANCE_2W'),
        verified=True))

# Manufacturer 1-year verification values: Fluke 8845A/8846A Calibration Manual,
# Appendix A, Table A-2 (8846A-specific entries).  Numeric SI base units.
# AC, capacitance, and frequency stimulus/meter SCPI commands REQUIRE lab validation.
TEST_TABLES = {'DCV': '0 .1 -3.5e-6 3.5e-6\n.1 .1 .0999928 .1000072\n-.1 .1 -.1000072 -.0999928\n0 1 -7e-6 7e-6\n1 1 .999968 1.000032\n-1 1 -1.000032 -.999968\n0 10 -50e-6 50e-6\n5 10 4.999830 5.000170\n-5 10 -5.000170 -4.999830\n10 10 9.999710 10.000290\n-10 10 -10.000290 -9.999710\n0 100 -600e-6 600e-6\n100 100 99.9956 100.0044\n-100 100 -100.0044 -99.9956\n0 1000 -.01 .01\n1000 1000 999.949 1000.051\n-1000 1000 -1000.051 -999.949', 'ACV': ' .1 .1 .0999 .1001 10\n.1 .1 .0999 .1001 20000\n.1 .1 .09983 .10017 50000\n.1 .1 .09932 .10068 100000\n.1 .1 .0955 .1045 300000\n1 1 .9991 1.0009 10\n1 1 .9991 1.0009 20000\n1 1 .9983 1.0017 50000\n1 1 .9932 1.0068 100000\n1 1 .955 1.045 300000\n10 10 9.991 10.009 10\n10 10 9.991 10.009 20000\n10 10 9.983 10.017 50000\n10 10 9.932 10.068 100000\n3 10 2.83 3.17 300000\n100 100 99.91 100.09 45\n100 100 99.91 100.09 20000\n100 100 99.83 100.17 50000\n100 100 99.32 100.68 100000\n1000 1000 999.1 1000.9 45\n1000 1000 999.1 1000.9 1000\n1000 1000 999.1 1000.9 10000\n320 1000 319.508 320.492 20000\n320 1000 319.116 320.884 50000\n320 1000 317.28 322.72 100000', 'FREQ': '10 1 9.997 10.003 10\n40 1 39.996 40.004 40\n300000 .1 299970 300030 300000\n1000000 .1 999900 1000100 1000000', 'OHM4': '0 10 0 .003\n10 10 9.996 10.004\n0 100 0 .004\n100 100 99.986 100.014\n0 1000 0 .01\n1000 1000 999.89 1000.11\n0 10000 0 .1\n10000 10000 9998.9 10001.1\n0 100000 0 1\n100000 100000 99989 100011', 'OHM2': '0 100 0 .004\n100 100 99.99 100.014\n0 1000 0 .01\n1000 1000 999.89 1000.11\n0 10000 0 .1\n10000 10000 9998.9 10001.1\n0 100000 0 1\n100000 100000 99989 100011\n0 1000000 0 10\n1000000 1000000 999890 1000110\n0 10000000 0 100\n10000000 10000000 9995900 10004100\n0 100000000 0 10000\n100000000 100000000 99190000 100810000\n0 1000000000 0 100000\n1000000000 1000000000 979900000 1020100000', 'CAP': '0 1e-9 0 25e-12\n1e-9 1e-9 955e-12 1.045e-9\n10e-9 10e-9 9.85e-9 10.15e-9\n100e-9 100e-9 98.5e-9 101.5e-9\n1e-6 1e-6 985e-9 1.015e-6\n10e-6 10e-6 9.85e-6 10.15e-6\n100e-6 100e-6 98.5e-6 101.5e-6\n1e-3 1e-3 985e-6 1.015e-3\n10e-3 10e-3 9.85e-3 10.15e-3\n100e-3 100e-3 95.8e-3 104.2e-3', 'DCI': '0 100e-6 -25e-9 25e-9\n100e-6 100e-6 99.935e-6 100.075e-6\n-100e-6 100e-6 -100.065e-6 -99.925e-6\n0 1e-3 -50e-9 50e-9\n1e-3 1e-3 999.45e-6 1.00055e-3\n-1e-3 1e-3 -1.00055e-3 -999.45e-6\n0 10e-3 -2e-6 2e-6\n10e-3 10e-3 9.993e-3 10.007e-3\n-10e-3 10e-3 -10.007e-3 -9.993e-3\n0 100e-3 -5e-6 5e-6\n100e-3 100e-3 99.945e-3 100.055e-3\n-100e-3 100e-3 -100.055e-3 -99.945e-3\n0 400e-3 -20e-6 20e-6\n400e-3 400e-3 399.78e-3 400.22e-3\n-400e-3 400e-3 -400.22e-3 -399.78e-3\n0 1 -200e-6 200e-6\n1 1 .9993 1.0007\n-1 1 -1.0007 -.9993\n0 3 -600e-6 600e-6\n1.9 3 1.8975 1.9025\n-1.9 3 -1.9025 -1.8975\n0 10 -800e-6 800e-6\n10 10 9.9842 10.0158\n-10 10 -10.0158 -9.9842', 'ACI': '100e-6 100e-6 99.86e-6 100.14e-6 10\n100e-6 100e-6 99.86e-6 100.14e-6 1000\n100e-6 100e-6 99.86e-6 100.14e-6 5000\n100e-6 100e-6 99.55e-6 100.45e-6 10000\n1e-3 1e-3 998.6e-6 1.0014e-3 10\n1e-3 1e-3 998.6e-6 1.0014e-3 1000\n1e-3 1e-3 998.6e-6 1.0014e-3 5000\n1e-3 1e-3 995.5e-6 1.0045e-3 10000\n10e-3 10e-3 9.986e-3 10.014e-3 10\n10e-3 10e-3 9.986e-3 10.014e-3 1000\n10e-3 10e-3 9.986e-3 10.014e-3 5000\n10e-3 10e-3 9.955e-3 10.045e-3 10000\n100e-3 100e-3 99.86e-3 100.14e-3 10\n100e-3 100e-3 99.86e-3 100.14e-3 1000\n100e-3 100e-3 99.86e-3 100.14e-3 5000\n100e-3 100e-3 99.55e-3 100.45e-3 10000\n329e-3 400e-3 327.613e-3 330.387e-3 10\n329e-3 400e-3 328.271e-3 329.729e-3 1000\n329e-3 400e-3 325.542e-3 332.458e-3 5000\n329e-3 400e-3 325.542e-3 332.458e-3 10000\n1 1 .9986 1.0014 45\n1 1 .9986 1.0014 1000\n1 1 .9986 1.0014 5000\n1 1 .9895 1.0105 10000\n1.9 3 1.89535 1.90465 45\n1.9 3 1.89535 1.90465 1000\n1.9 3 1.87235 1.92765 10000\n10 10 9.979 10.021 45\n10 10 9.979 10.021 1000'}
for kind, block in TEST_TABLES.items():
    unit={'DCV':'V','ACV':'V','FREQ':'Hz','OHM4':'ohm','OHM2':'ohm','CAP':'F','DCI':'A','ACI':'A'}[kind]
    for line in block.splitlines():
        vals=list(map(float,line.split()))
        nominal,rng,low,high=vals[:4]
        freq=vals[4] if len(vals)==5 else None
        label=f'{kind} {nominal:.9g} {unit}' + (f' @ {freq:.9g} Hz' if freq else '') + f' (range {rng:.9g})'
        wiring={'DCV':'VOLTAGE','ACV':'VOLTAGE','FREQ':'VOLTAGE',
                'DCI':'CURRENT','ACI':'CURRENT','OHM4':'RESISTANCE_4W',
                'OHM2':'RESISTANCE_2W','CAP':'CAPACITANCE'}[kind]
        add(kind,nominal,rng,low,high,unit,frequency=freq,description=label,wiring=wiring)
        POINTS[-1]['zero_offset']=(nominal==0 and kind in ('DCV','DCI','OHM4','OHM2','CAP'))
        POINTS[-1]['terminal']='FRONT'
        POINTS[-1]['source']='Fluke Calibration Manual Appendix A, Table A-2 (1-year)'
# Point 107 (ACI 100 uA @ 10 Hz) is an optional manual-table test and is deleted at the technician's request.
# The other points keep their ids (no renumbering), so existing checkpoints still match.
REMOVED_POINTS=[q['id'] for q in POINTS if q['kind']=='ACI' and q['nominal']==100e-6 and q['frequency']==10]
assert len(REMOVED_POINTS)==1,'expected exactly one ACI 100 uA @ 10 Hz point'
POINTS[:]=[q for q in POINTS if q['id'] not in REMOVED_POINTS]
# All zero-offset points form ONE block at the start of the run (one section in the list and the report).
# Shorted-input zeros first, then the open-input ones (DCI, CAP), so the technician fits each fixture once.
# Point ids are left unchanged so existing checkpoint files still match their points.
HIGH_CURRENT_A=3.0     # at or above this the calibrator output is on its high-current terminals (the table has only 1.9 A and 10 A around it)
_ZERO_ORDER={'DCV':0,'OHM2':1,'OHM4':2,'DCI':3,'CAP':4}
def needs_null(p):
    """Points measured as: 0 ohm output, null the meter, then the test value. 2-wire 100 ohm only (the table's limits
    for that point have no lead-resistance allowance). Add (kind, range, nominal) tuples here to extend it."""
    return (p['kind'],p['range'],p['nominal']) in NULL_POINTS and not p.get('zero_offset')
NULL_POINTS={('OHM2',100,100)}
def setup_key(p):
    """What the technician must have connected: one key for the whole zero block's shorted inputs, one for open inputs."""
    if p.get('zero_offset'):return 'ZERO_OPEN' if p['kind'] in ('DCI','CAP') else 'ZERO_SHORT'
    if p['kind'] in ('DCI','ACI') and abs(p['nominal'])>=HIGH_CURRENT_A:return 'CURRENT_HIGH'
    return p['wiring']
POINTS.sort(key=lambda q:(0,_ZERO_ORDER[q['kind']]) if q.get('zero_offset') else (1,0))   # stable: gain points keep their order
# Zero-offset limits for resistance and capacitance are symmetric (+/- the table value), like the DCV / DCI zero points:
# the table was transcribed as 0 to +limit, which failed small negative readings (e.g. -2 mOhm against a 100 mOhm limit).
# The upper limits are unchanged and have not been re-checked against the manual page.
for _q in POINTS:
    if _q.get('zero_offset') and _q['kind'] in ('OHM2','OHM4','CAP') and _q['low']==0:
        _q['low']=-_q['high']
BY_ID={q['id']:q for q in POINTS}      # the list is no longer in id order (zero block first): always look points up by id
# The manual also specifies optional DC ratio, rear-terminal and split-lead tests.
# Those require distinct setups/measurement commands and are not executed here.

class LiveLog(drivers.CommandLog):
    """CommandLog that also appends every command to ~/.calibration_suite/command_log_live.txt the moment it is
    sent or received, so a hung instrument leaves the last command on disk (the normal log is saved on error / close)."""
    def add(self,direction,text,instrument=''):
        super().add(direction,text,instrument)
        try:
            folder=Path.home()/'.calibration_suite';folder.mkdir(parents=True,exist_ok=True)
            with open(folder/'command_log_live.txt','a',encoding='utf-8') as f:
                f.write(f'{datetime.now().strftime("%H:%M:%S.%f")[:-3]}  {instrument:<6} {direction}  {text}\n')
        except OSError:pass

def waiting_text(log,p,elapsed):
    """Status-bar text while a point is running: what the program is waiting on (the last command on the wire)."""
    if not log.entries:return f'Running {p["id"]}: starting ...'
    _t,inst,direction,text=log.entries[-1]
    what=f'sent {inst} {text}' if direction=='>>' else f'got reply from {inst}'
    return f'Running {p["id"]} ({elapsed:.0f} s): last {what}' + (' - no reply yet' if direction=='>>' and text.rstrip().endswith('?') else '')

class IO:
    """Bench I/O for this procedure: the DMM and the Fluke 5560A, both through the instrument drivers."""
    def __init__(self, dmm_port, fluke_port, baud, parity, bits):
        self.log=LiveLog()
        self.dmm=drivers.Fluke8846A(drivers.open_visa(f'ASRL{dmm_port}::INSTR',timeout=20,baud=baud,data_bits=bits,
            parity=parity.lower(),stop_bits=1,write_termination='\n',read_termination='\n'),self.log,label='8846A')
        self.fluke=drivers.Fluke5560A(drivers.open_visa(f'ASRL{fluke_port}::INSTR',timeout=20,baud=9600,
            write_termination='\n',read_termination='\n'),self.log,label='5560A')
        try:
            self.fluke.open(verify_model=False)
            self.fluke.write('STBY')
            self.dmm.connect()
        except Exception:
            self.close();raise
        self.ident=self.dmm.idn
    def standby(self):
        self.fluke.standby_quiet()
    def close(self):
        try:self.standby()
        except Exception:pass
        try:self.dmm.cleanup()
        except Exception:pass
        for obj in (self.dmm,self.fluke):
            try:obj.close()
            except Exception:pass
        self.save_log()
    _saved=0
    def save_log(self):
        """Append the commands sent since the last save to ~/.calibration_suite/command_log.txt (each command once)."""
        try:
            new=self.log.lines()[self._saved:]
            if not new:return
            folder=Path.home()/'.calibration_suite';folder.mkdir(parents=True,exist_ok=True)
            with open(folder/'command_log.txt','a',encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  8846A session\n'+'\n'.join(new)+'\n')
            self._saved+=len(new)
        except OSError:pass
    # ---- settling --------------------------------------------------------------------------------
    # A flat 2 s after OPER was too short for the 5560A to ramp to 100 V / 1000 V, for high resistance
    # (cable capacitance x MOhm) and for the high current points, so READ? caught the output mid-settle.
    # Now: a minimum wait that scales with the point, then READ? repeated (read-only query) until
    # STABLE_COUNT consecutive readings agree within STABLE_FRACTION of the tolerance band.
    FREQ_LEVEL_V=1.0     # 1 V rms source level for every frequency point (technician's choice; not from the manual)
    STABLE_COUNT=3
    STABLE_FRACTION=0.10
    READ_INTERVAL=0.5
    @staticmethod
    def settle(p):
        """Minimum wait in seconds before the first reading is considered."""
        k,r,v=p['kind'],p['range'],abs(p['nominal'])
        if k in ('OHM2','OHM4'):
            if r>=1e9:return 15.0
            if r>=1e8:return 10.0
            if r>=1e7:return 6.0
            if r>=1e6:return 4.0
            return 3.0
        if k=='DCV':
            if v>=500:return 6.0       # 5560A high-voltage ramp
            if v>=50:return 4.0
            return 2.5
        if k=='DCI':
            if v>=1:return 4.0         # 1 A to 10 A: shunt / lead thermal settling
            if r<=1e-3:return 4.0      # 100 uA / 1 mA ranges: slow, high-impedance
            return 3.0
        if k=='FREQ':return 3.0        # 1 s gate
        if k=='CAP':return 8.0 if r>=1e-3 else 3.0
        return 8.0 if k in ('ACV','ACI') else 2.0   # AC: 3 Hz filter settling, ~7 s per reading
    @classmethod
    def settle_timeout(cls,p):
        if p['kind'] in ('ACV','ACI'):return 90.0         # 3 Hz filter: several 7 s readings
        if p.get('zero_offset'):return 15.0     # tiny tolerance band: don't let meter noise stall 27 zero points for 30 s each
        return max(30.0,cls.settle(p)*4)
    def settled_read(self,p,min_wait):
        """Wait min_wait, then READ? until the last STABLE_COUNT readings agree within the
        stability window. On timeout the last reading is returned (as before) and a note is logged."""
        time.sleep(min_wait)
        window=max(p['high']-p['low'],0.0)*self.STABLE_FRACTION
        end=time.monotonic()+self.settle_timeout(p)
        history=[]
        while True:
            history.append(self.dmm.read())
            recent=history[-self.STABLE_COUNT:]
            if len(recent)==self.STABLE_COUNT and max(recent)-min(recent)<=window:
                return history[-1]
            if time.monotonic()>end:
                self.log.add('NOTE',f'reading did not settle within {self.settle_timeout(p):g} s '
                             f'(last {len(recent)}: {", ".join(f"{x:.9g}" for x in recent)}); last reading used','8846A')
                return history[-1]
            time.sleep(self.READ_INTERVAL)
    def measure(self,p):
        try:
            return self._measure(p)
        except Exception:
            self.save_log()      # a failed point leaves its commands on disk straight away, without closing the program
            raise
    def _measure_nulled(self,p):
        """2-wire 100 ohm point: the calibrator outputs 0 ohm, the meter is nulled on that reading (offset set, read back
        and compared), the calibrator then goes to the test value and the reading is taken. The null is always turned off
        again and the output always goes to standby. The 5560A 0 ohm output and the meter null commands are unverified."""
        zp=next(q for q in POINTS if q.get('zero_offset') and q['kind']==p['kind'] and q['range']==p['range'])
        self.fluke.clear_status()                       # only this point's own commands can trip the error check
        self.fluke.set_output_ohms(0)
        self.fluke.check_error('0 ohm for '+p['description'])
        self.fluke.operate_unverified()
        nulled=done=False
        try:
            zero=self.settled_read(zp,self.settle(p))   # settles to the zero point's own stability window
            nulled=True                                 # set before the call so a half-applied null is always switched off
            self.dmm.null_on(zero)
            left=self.dmm.read()
            if abs(left)>5*zp['high']:                  # a null that took effect leaves ~0; one that did not leaves the lead resistance
                raise RuntimeError(f'After nulling, 0 ohm reads {left:.6g} ohm (limit {5*zp["high"]:.3g}); the null did not take effect. Point not measured.')
            self.fluke.set_output_ohms(p['nominal'])
            self.fluke.check_error(p['description'])
            reading=self.settled_read(p,self.settle(p))
            done=True
        finally:
            self.standby()
            if nulled:
                try:self.dmm.null_off()
                except Exception as exc:
                    self.log.add('NOTE',f'null off failed: {exc}','8846A')
                    if done:raise               # never let this hide the error that stopped the point
        return reading
    def _measure(self,p):
        k=p['kind'];v=p['nominal'];r=p['range'];f=p['frequency']
        self.standby()
        if p.get('zero_offset'):
            # Zero-offset verification requires a physical copper short or OPEN current
            # input. The 5560A must remain in STBY and is never used as a zero source.
            self.dmm.configure(k,r)
            return self.settled_read(p,max(1.5,self.settle(p)-1.0))
        if k in ('FREQ','CAP','ACI'):
            # These points read the 5560A error queue before OPER. Earlier points (AC volts etc.) never read it, so an
            # old rejection can still be sitting there and would be blamed on this point: clear it first (*CLS).
            self.fluke.clear_status()
        if k in ('DCV','ACV','DCI','ACI'):
            self.dmm.configure(k,r)
            if k in ('ACV','ACI'):
                self.dmm.set_ac_filter(3)     # slow 3 Hz filter, set by the program (read back and compared); no manual step
            if k.endswith('V'):self.fluke.set_output_volts(v,f)
            else:self.fluke.set_output_amps(v,f)
        elif k in ('OHM2','OHM4'):
            self.dmm.configure(k,r)
            if needs_null(p):return self._measure_nulled(p)
            self.fluke.set_output_ohms(v)
        elif k=='CAP':
            self.dmm.configure(k,r)
            self.fluke.set_output_capacitance(v)
        else:                                  # FREQ: nominal is the frequency, range is the meter's voltage range
            self.dmm.configure_frequency_point(r)
            self.fluke.set_output_volts(self.FREQ_LEVEL_V,v)
        if k in ('FREQ','CAP','ACI'):          # newly automated and unverified: a rejected command must stop the run
            self.dmm.check_errors('configuring '+p['description'])
            self.fluke.check_error(p['description'])   # the calibrator refuses outputs it cannot make; never operate then
        self.fluke.operate_unverified()
        try:
            reading=self.settled_read(p,self.settle(p))
        finally:
            self.standby()               # output to standby even if a read fails
        return reading

class App:
    SETUP_TEXT = {
        'VOLTAGE': '5560A voltage output to the meter HI / LO terminals',
        'CURRENT': '5560A current output to the meter current (A) input and LO',
        'CURRENT_HIGH': '5560A HIGH-current output terminals (AUX) to the meter 10 A input and LO',
        'RESISTANCE_2W': '2-wire resistance leads from the 5560A',
        'RESISTANCE_4W': '4-wire force and sense leads from the 5560A',
        'CAPACITANCE': 'Capacitance fixture (confirm OPEN compensation per manual)',
    }

    def __init__(self,root,demo=False):
        self.root=root;self.demo=demo;self.io=None;self._busy=False;self.stop=False
        self.results={}
        ui.apply_theme(root)
        root.title('Fluke 8846A | Performance Verification v58'+(' [DEMO]' if demo else ''))
        ui.fit_window(root,1280,800,min_w=1060,min_h=620)
        self.settings=ui.Settings('8846A')
        self.asset=tk.StringVar();self.serial=tk.StringVar()
        self.dmm_port=tk.StringVar(value=self.settings.get('dmm_port','COM3'))
        self.fluke_port=tk.StringVar(value=self.settings.get('fluke_port','COM9'))
        self.baud=tk.StringVar(value=self.settings.get('baud','9600'))
        self.parity=tk.StringVar(value=self.settings.get('parity','None'))
        self.bits=tk.StringVar(value=self.settings.get('bits','8'))
        self.status=tk.StringVar()
        self.detail=tk.StringVar(value='Select a test point to see its limits and wiring.')
        self.show_section=tk.StringVar(value='All sections')
        self.show_status=tk.StringVar(value='All points')
        self._build_ui()
        self.refresh_ports()
        self.refresh()
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose COM ports and press Test Connections. Step 3: Run All.')
        root.protocol('WM_DELETE_WINDOW',self.on_close)
        root.bind('<Control-s>',lambda _e:self.save())
        import labregistry
        labregistry.attach(root,self.asset,self.serial, self.status.set)

    # ------------------------------------------------------------------ layout
    @property
    def busy(self):return self._busy
    @busy.setter
    def busy(self,value):
        self._busy=value
        if hasattr(self,'btn_run'):self._sync_buttons()

    def _sync_buttons(self):
        idle='disabled' if self._busy else 'normal'
        for b in (self.btn_run,self.btn_rerun,self.btn_override,self.btn_test,self.btn_load,self.btn_refresh_ports):b.configure(state=idle)
        self.btn_stop.configure(state='normal' if self._busy else 'disabled')
        for c in (self.dmm_combo,self.fluke_combo):c.configure(state='disabled' if self._busy else 'normal')

    def _build_ui(self):
        root=self.root
        banner=ui.Banner(root,'Fluke 8846A  -  Performance Verification','1-year verification  |  Fluke 8845A/8846A Calibration Manual, Appendix A, Table A-2')
        banner.pack(fill='x')
        if self.demo:banner.add_pill('DEMO MODE  -  simulated readings','warn')
        else:banner.add_pill('HARDWARE MODE','info')
        self.conn_pill=banner.add_pill('Not connected','neutral')
        bar=ui.StatusBar(root,self.status,right='v58')
        bar.pack(side='bottom',fill='x')
        body=ttk.Frame(root,padding=(18,14,18,10));body.pack(fill='both',expand=True)

        top=ttk.Frame(body);top.pack(fill='x')
        top.columnconfigure(1,weight=1)
        dut=ttk.LabelFrame(top,text='Instrument under test',padding=12)
        dut.grid(row=0,column=0,sticky='nsew',padx=(0,12))
        ttk.Label(dut,text='Instrument ID *').grid(row=0,column=0,sticky='w',pady=3)
        e=ttk.Entry(dut,textvariable=self.asset,width=22);e.grid(row=0,column=1,padx=(10,0),pady=3);e.focus_set()
        ttk.Label(dut,text='Serial number').grid(row=1,column=0,sticky='w',pady=3)
        ttk.Entry(dut,textvariable=self.serial,width=22).grid(row=1,column=1,padx=(10,0),pady=3)
        conn=ttk.LabelFrame(top,text='Instrument connections',padding=12)
        conn.grid(row=0,column=1,sticky='nsew')
        ttk.Label(conn,text='8846A port').grid(row=0,column=0,sticky='w',pady=3)
        self.dmm_combo=ttk.Combobox(conn,textvariable=self.dmm_port,width=10,state='normal')
        self.dmm_combo.grid(row=0,column=1,padx=(8,20),pady=3)
        ttk.Label(conn,text='Fluke 5560A port').grid(row=0,column=2,sticky='w',pady=3)
        self.fluke_combo=ttk.Combobox(conn,textvariable=self.fluke_port,width=10,state='normal')
        self.fluke_combo.grid(row=0,column=3,padx=(8,20),pady=3)
        self.btn_refresh_ports=ttk.Button(conn,text='Refresh ports',command=self.refresh_ports)
        self.btn_refresh_ports.grid(row=0,column=4,padx=(0,8))
        self.btn_test=ttk.Button(conn,text='Test connections',command=self.test_connections)
        self.btn_test.grid(row=0,column=5)
        ttk.Label(conn,text='Serial settings').grid(row=1,column=0,sticky='w',pady=(6,0),padx=(0,10))
        row=ttk.Frame(conn);row.grid(row=1,column=1,columnspan=5,sticky='w',pady=(6,0))
        for text,var,values in (('Baud',self.baud,['9600','4800','2400','1200','600','300']),('Parity',self.parity,['Even','Odd','None']),('Data bits',self.bits,['7','8'])):
            ttk.Label(row,text=text,style='Muted.TLabel').pack(side='left')
            ttk.Combobox(row,textvariable=var,values=values,width=7,state='readonly').pack(side='left',padx=(5,14))
        ttk.Label(row,text='Match the meter RS-232 settings and SCPI language.',style='Muted.TLabel').pack(side='left')

        if self.demo:
            ui.Notice(body,'Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.','warn',title='Demo mode').pack(fill='x',pady=(12,0))
        else:
            ui.Notice(body,'The program pauses and asks you to confirm the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.','info',title='Hardware mode').pack(fill='x',pady=(12,0))

        ttk.Label(body,text='Optional DC-ratio, rear-terminal and split-lead tests need a separate setup and are not included. AC, frequency and capacitance points are guided review only.',style='Small.TLabel').pack(anchor='w',pady=(6,0))
        tools=ttk.Frame(body);tools.pack(fill='x',pady=(8,6))
        self.btn_run=ttk.Button(tools,text='▶  Run All Pending',style='Accent.TButton',command=self.run_all);self.btn_run.pack(side='left')
        self.btn_rerun=ttk.Button(tools,text='Rerun Selected',command=self.rerun);self.btn_rerun.pack(side='left',padx=8)
        self.btn_override=ttk.Button(tools,text='Override Reading…',command=self.override_reading);self.btn_override.pack(side='left',padx=(0,8))
        self.btn_stop=ttk.Button(tools,text='■  Stop After This Point',style='Danger.TButton',command=self.request_stop,state='disabled');self.btn_stop.pack(side='left')
        for text,cb in (('Export Report (PDF)',self.export_pdf),('Export Excel (.xlsx)',self.export_excel),):
            ttk.Button(tools,text=text,command=cb).pack(side='right',padx=(8,0))
        self.btn_load=ttk.Button(tools,text='Load progress',command=self.load);self.btn_load.pack(side='right',padx=(8,0))
        ttk.Button(tools,text='Save progress',command=self.save).pack(side='right',padx=(8,0))

        sumrow=ttk.Frame(body);sumrow.pack(fill='x',pady=(2,8))
        self.summary=ui.Summary(sumrow);self.summary.pack(side='left',fill='x',expand=True)
        filt=ttk.Frame(sumrow);filt.pack(side='right',padx=(24,0))
        sections=['All sections']
        for p in POINTS:
            s=self._section(p)
            if s not in sections:sections.append(s)
        ttk.Label(filt,text='Show',style='Muted.TLabel').pack(side='left')
        c1=ttk.Combobox(filt,textvariable=self.show_section,values=sections,width=15,state='readonly');c1.pack(side='left',padx=6)
        c2=ttk.Combobox(filt,textvariable=self.show_status,values=['All points','Not tested','Passed','Failed (OOT)'],width=13,state='readonly');c2.pack(side='left')
        for c in (c1,c2):c.bind('<<ComboboxSelected>>',lambda _e:self.refresh())

        info=ttk.LabelFrame(body,text='Selected test point',padding=(12,8));info.pack(side='bottom',fill='x',pady=(10,0))
        ttk.Label(info,textvariable=self.detail,wraplength=900,justify='left').pack(anchor='w',fill='x')
        cols=('n','section','description','range','nominal','low','high','reading','units','result')
        self.tree=ui.make_table(body,cols,('#','Section','Description','Range','Nominal','Low limit','High limit','Reading','Units','Result'),
                                (44,92,270,84,92,100,100,110,64,90),anchors={'description':'w','section':'w','nominal':'e','low':'e','high':'e','reading':'e','range':'e','units':'w'},height=12,
                                stretch={'n':False,'section':False,'range':False,'nominal':False,'low':False,'high':False,'reading':False,'units':False,'result':False})
        self.tree.tag_configure('pending',foreground=ui.C['muted'])
        self.tree.bind('<<TreeviewSelect>>',self.on_select)
        ui.polish(root)

    @staticmethod
    def _section(p):
        return 'ZERO OFFSET' if p.get('zero_offset') else p['kind']

    def _visible(self,p):
        res=self.results.get(str(p['id']),{}).get('result','')
        sec=self.show_section.get();st=self.show_status.get()
        if sec!='All sections' and self._section(p)!=sec:return False
        if st=='Not tested' and res:return False
        if st=='Passed' and res!='PASS':return False
        if st=='Failed (OOT)' and res!='FAIL':return False
        return True

    def _row(self,p):
        rec=self.results.get(str(p['id']),{});res=rec.get('result','')
        reading=rec.get('reading','')
        vals,reads,unit_text=ui.si_row([p['nominal'],p["low"],p["high"]],p['unit'],[reading] if reading!='' else [])
        shown={'PASS':'✔ PASS','FAIL':'✖ FAIL'}.get(res,'—')+(' ✎' if rec.get('manual') else '')   # ✎ = typed by hand
        return (p['id'],self._section(p),p['description'],ui.si(p["range"],p["unit"]),vals[0],
                vals[1],vals[2],reads[0] if reads else '',unit_text,shown),(res.lower() or 'pending',)

    def refresh_ports(self):
        # Keep user-entered COM numbers; detection is advisory and may be unavailable in demo mode.
        ports=[]
        try:
            from serial.tools import list_ports
            ports=sorted({p.device.upper() for p in list_ports.comports()
                          if p.device.upper().startswith('COM')},
                         key=lambda v: int(v[3:]) if v[3:].isdigit() else 9999)
        except ImportError:
            self.status.set('Port detection needs pyserial (py -m pip install pyserial). You can still type a COM number.')
        except Exception as exc:
            self.status.set(f'COM port detection unavailable: {exc}. You can still type a COM number.')
        for widget,current in ((self.dmm_combo,self.dmm_port),(self.fluke_combo,self.fluke_port)):
            value=current.get().strip().upper()
            if value and not value.startswith('COM') and value.isdigit():value='COM'+value
            widget['values']=ports
            if value:current.set(value)
        if ports:self.status.set('Serial ports found: '+', '.join(ports)+'. Pick the port for each instrument.')

    @staticmethod
    def parse_com(value):
        value=value.strip().upper()
        if value.startswith('COM'):value=value[3:]
        if not value.isdigit() or int(value)<1:
            raise ValueError('Select a valid COM port, such as COM3, or enter its number.')
        return int(value)

    def refresh(self):
        keep=self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for p in POINTS:
            if self._visible(p):
                values,tags=self._row(p);self.tree.insert('','end',iid=str(p['id']),values=values,tags=tags)
        if keep and self.tree.exists(keep[0]):self.tree.selection_set(keep[0])
        self.update_summary()

    def _update_row(self,p):
        iid=str(p['id'])
        if self.tree.exists(iid):
            values,tags=self._row(p);self.tree.item(iid,values=values,tags=tags)
        self.update_summary()

    def update_summary(self):
        vals=[self.results.get(str(p['id']),{}).get('result','') for p in POINTS]
        self.summary.update_counts(len(POINTS),vals.count('PASS'),vals.count('FAIL'))

    def on_select(self,_event=None):
        sel=self.tree.selection()
        if not sel:return
        p=BY_ID[int(sel[0])]
        setup=('Zero offset: select the '+p['terminal']+' terminals and fit the short (open for current) - the 5560A stays in STANDBY.'
               if p.get('zero_offset') else self.SETUP_TEXT.get(setup_key(p),p['wiring']))
        _v,_r,_u=ui.si_row([p["low"],p["high"]],p['unit'])
        note=''
        _rec=self.results.get(str(p['id']),{})
        if _rec.get('manual'):
            _o=_rec.get('original')
            _ot='no automatic reading' if _o in (None,'') else 'automatic reading '+ui.si_row([p['nominal'],p['low'],p['high']],p['unit'],[_o])[1][0]+' '+_u
            note=f'\nMANUAL OVERRIDE: {_ot}; reason: {_rec.get("reason","")}'
        self.detail.set(f'{p["description"]}\nAcceptable reading: {_v[0]} to {_v[1]} {_u}     |     Setup: {setup}'+note)

    def test_connections(self):
        if self.demo:messagebox.showinfo('Demo mode','Demo mode uses no hardware, so there is nothing to connect.');return
        self.status.set('Connecting ...');self.root.update_idletasks()
        try:
            self.disconnect();self.io=IO(self.parse_com(self.dmm_port.get()),self.parse_com(self.fluke_port.get()),
                                        int(self.baud.get()),self.parity.get(),int(self.bits.get()))
        except Exception as exc:
            self.disconnect();self._set_conn(False)
            self.status.set('Connection error: '+str(exc))
            messagebox.showerror('Connection error',str(exc));return
        self._set_conn(True);self._save_settings()
        self.status.set('Connected: '+self.io.ident+'. Fluke output is NOT enabled.')
        messagebox.showinfo('Connected',f'8846A: {self.io.ident}\nFluke port opened (output not enabled).')
    def disconnect(self):
        if self.io:self.io.close();self.io=None
        self._set_conn(None)
    def _set_conn(self,ok):
        if hasattr(self,'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')
    def _save_settings(self):
        for key,var in (('dmm_port',self.dmm_port),('fluke_port',self.fluke_port),('baud',self.baud),('parity',self.parity),('bits',self.bits)):
            self.settings.set(key,var.get())
        self.settings.save()
    def request_stop(self):self.stop=True;self.status.set('Stopping after current test point.')
    def run_all(self):self.execute([p for p in POINTS if str(p['id']) not in self.results])
    def rerun(self):
        selected=self.tree.selection()
        if selected:self.execute([BY_ID[int(selected[0])]])
        else:messagebox.showinfo('Selection','Select a test point first.')
    def execute(self,points):
        if self.busy or not points:return
        if not self.asset.get().strip():messagebox.showwarning('Instrument ID','Enter an instrument ID.');return
        if not self.demo and self.io is None:self.test_connections()
        if not self.demo and self.io is None:return
        self.stop=False;self.busy=True
        self._next(points,0,None)
    def _next(self,points,i,previous):
        if i>=len(points) or self.stop:
            self.busy=False;self.save();self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.');return
        p=points[i]
        if setup_key(p)!=previous:
            if not self.demo and p.get('zero_offset'):
                self.io.standby()
                location=p['terminal']
                instruction=('Leave CURRENT input OPEN (no calibrator connected).' if p['kind']=='DCI' else
                             'Use the manual-prescribed OPEN capacitance fixture.' if p['kind']=='CAP' else
                             'Install the manual-prescribed low-thermal short/shorted leads. Do NOT use the 5560A as a zero source.')
                if not ui.confirm_steps(self.root,'Zero offset \u2014 physical setup required',f'Zero-offset setup: {location} terminals',
                    [('Select terminals',f'Use the front-panel FRONT/REAR switch to select the {location} terminals.'),
                     ('Set up the input',instruction)],
                    facts=[('Point',f'{p["id"]} of {len(POINTS)}'),('Terminals',location)],
                    caution='The 5560A stays in STANDBY. Confirm the terminal selection and physical setup before measuring.',
                    ok='Set up \u2014 measure'):
                    self.busy=False;self.status.set('Paused for zero-offset setup');return
            elif not self.demo:
                msg={'CURRENT_HIGH':'Put calibrator in STANDBY. Move the calibrator leads from its LOW-current output terminals to its HIGH-current output terminals (AUX), and the meter leads to the 10 A input. Check fuses, lead rating and current ratings before continuing.',
                     'VOLTAGE':'Connect 5560A voltage output to 8846A HI/LO voltage terminals. Verify safe leads and ranges.',
                     'CURRENT':'Put calibrator in STANDBY. Move leads to 8846A CURRENT input and LO (and, if coming from the 10 A points, back to the calibrator\'s LOW-current output terminals). Check fuses and current ratings.',
                     'RESISTANCE_2W':'Put calibrator in STANDBY. Connect 2-wire resistance leads. 2-wire limits include the manual 0.2 ohm allowance; verify zero/null handling.',
                     'RESISTANCE_4W':'Put calibrator in STANDBY. Connect 4-wire force and sense leads to the correct DMM and calibrator terminals.',
                     'CAPACITANCE':'Put calibrator in STANDBY. Connect capacitance fixture; verify OPEN compensation and meter setup per manual.'}[setup_key(p)]
                if not ui.confirm_steps(self.root,'Rewire / verify before enabling output',f'Connect for {p["kind"]} tests',
                    [('Wiring',msg)],
                    facts=[('Next point',f'{p["id"]} of {len(POINTS)}'),('Test',p['description'])],
                    caution='Continue only after physically verifying the connections.',
                    ok='Connections verified \u2014 continue'):
                    self.busy=False;self.status.set('Paused for wiring');return
        if not self.demo and abs(p['nominal'])>=1000 and p['kind'] in ('DCV','ACV'):
            if not messagebox.askyesno('HIGH VOLTAGE — 1000 V','This point requires hazardous high voltage. Verify leads, connections, clearance and personnel safety. Enable output?'):
                self.busy=False;return
        if not self.demo and p['kind']=='ACV' and p['nominal']>=750:
            if not messagebox.askyesno('HIGH VOLTAGE — 750 V AC','Verify the calibrator can deliver this voltage/frequency into the load. Confirm safety before proceeding.'):
                self.busy=False;return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        
        if self.tree.exists(str(p['id'])):self.tree.selection_set(str(p['id']));self.tree.see(str(p['id']))
        if self.demo:
            # Synthetic reading explicitly labeled; deterministic for reproducibility.
            reading=(p['low']+p['high'])/2+(p['high']-p['low'])/2*math.sin(p['id']*1.71)*0.38
            self._record(p,reading,True);self.root.after(50,lambda:self._next(points,i+1,setup_key(p)))
        else:
            def work():
                try:
                    reading=self.io.measure(p)
                    self.root.after(0,lambda:self._done(points,i,p,reading))
                except Exception as exc:
                    try:self.io.standby()
                    except Exception:pass
                    self.root.after(0,lambda:self._error(exc))
            worker=threading.Thread(target=work,daemon=True);worker.start()
            self._watch(p,worker,time.monotonic())
    def _watch(self,p,worker,t0):
        """Every 2 s while a point runs: show the last command sent, so a hang is visible in the status bar."""
        if not worker.is_alive() or not self.busy:return
        elapsed=time.monotonic()-t0
        if elapsed>=4 and self.io is not None:self.status.set(waiting_text(self.io.log,p,elapsed))
        self.root.after(2000,lambda:self._watch(p,worker,t0))
    def _done(self,points,i,p,reading):
        self._record(p,reading,False)
        self.root.after(50,lambda:self._next(points,i+1,setup_key(p)))
    def _error(self,exc):self.busy=False;self.status.set('Error - run stopped: '+str(exc));messagebox.showerror('Measurement stopped',str(exc)+'\n\nThe commands sent are saved in ~/.calibration_suite/command_log.txt')
    # ---- manual override ------------------------------------------------------------------------
    @staticmethod
    def _display_scale(p):
        """(divisor, unit text) the list uses for this point, so a typed reading is in the unit the technician sees."""
        return ui.si_scale(max(abs(p['nominal']),abs(p['low']),abs(p['high'])),p['unit'])
    def apply_override(self,p,text,reason):
        """Record a reading typed by the technician (in the list's display unit) for point p. It is judged against the limits
        exactly like an automatic reading and stored with manual=True, the automatic reading it replaced, the reason and the time.
        Raises ValueError (with a message for the technician) if the text or the reason is not acceptable."""
        reason=(reason or '').strip()
        if not reason:raise ValueError('Enter a reason for the override.')
        try:shown=float((text or '').strip().replace(' ',''))
        except ValueError:raise ValueError('Enter the reading as a number, in the unit shown.') from None
        if not math.isfinite(shown):raise ValueError('Enter the reading as a number, in the unit shown.')
        reading=shown*self._display_scale(p)[0]
        prior=self.results.get(str(p['id']),{})
        original=prior.get('original') if prior.get('manual') else prior.get('reading')   # always the AUTOMATIC reading, if there was one
        rec=dict(reading=reading,result='PASS' if p['low']<=reading<=p['high'] else 'FAIL',synthetic=self.demo,
                 timestamp=datetime.now().isoformat(timespec='seconds'),manual=True,original=original,reason=reason)
        self.results[str(p['id'])]=rec
        self._audit_override(p,rec)
        self._update_row(p);self.save(silent=True)
        return rec
    def _audit_override(self,p,rec):
        """One line per override in the command log and in ~/.calibration_suite/override_log.txt."""
        line=(f'OVERRIDE point {p["id"]} {p["description"]}: automatic {rec["original"]!r} -> typed {rec["reading"]:.9g} {p["unit"]} '
              f'({rec["result"]}); reason: {rec["reason"]}')
        try:
            if self.io is not None:self.io.log.add('NOTE',line,'8846A')
        except Exception:pass
        try:
            folder=Path.home()/'.calibration_suite';folder.mkdir(parents=True,exist_ok=True)
            with open(folder/'override_log.txt','a',encoding='utf-8') as f:
                f.write(f'{rec["timestamp"]}  asset {self.asset.get().strip() or "?"}  {line}\n')
        except OSError:pass
    def override_reading(self):
        sel=self.tree.selection()
        if not sel:messagebox.showinfo('Selection','Select a test point first.');return
        if self.busy:return
        p=BY_ID[int(sel[0])]
        scale,unit_text=self._display_scale(p)
        prior=self.results.get(str(p['id']),{})
        vals,reads,_u=ui.si_row([p['nominal'],p['low'],p['high']],p['unit'],[prior['reading']] if prior.get('reading') not in (None,'') else [])
        win=tk.Toplevel(self.root);win.title('Override reading');win.transient(self.root);win.resizable(False,False)
        frm=ttk.Frame(win,padding=16);frm.pack(fill='both',expand=True)
        ttk.Label(frm,text=p['description']).grid(row=0,column=0,columnspan=3,sticky='w')
        ttk.Label(frm,text=f'Acceptable reading: {vals[1]} to {vals[2]} {unit_text}').grid(row=1,column=0,columnspan=3,sticky='w',pady=(2,0))
        if reads:ttk.Label(frm,text=f'Current reading: {reads[0]} {unit_text}'+(' (typed by hand)' if prior.get('manual') else '')).grid(row=2,column=0,columnspan=3,sticky='w')
        reading_var=tk.StringVar();reason_var=tk.StringVar();error_var=tk.StringVar()
        ttk.Label(frm,text='Reading:').grid(row=3,column=0,sticky='w',pady=(12,0))
        entry=ttk.Entry(frm,textvariable=reading_var,width=18);entry.grid(row=3,column=1,sticky='w',pady=(12,0),padx=6)
        ttk.Label(frm,text=unit_text).grid(row=3,column=2,sticky='w',pady=(12,0))
        ttk.Label(frm,text='Reason:').grid(row=4,column=0,sticky='w',pady=(8,0))
        ttk.Entry(frm,textvariable=reason_var,width=44).grid(row=4,column=1,columnspan=2,sticky='we',pady=(8,0),padx=6)
        ttk.Label(frm,textvariable=error_var,foreground='#9C1C1C').grid(row=5,column=0,columnspan=3,sticky='w',pady=(8,0))
        def ok(_e=None):
            try:self.apply_override(p,reading_var.get(),reason_var.get())
            except ValueError as exc:error_var.set(str(exc));return
            win.destroy();self.on_select()
        buttons=ttk.Frame(frm);buttons.grid(row=6,column=0,columnspan=3,sticky='e',pady=(12,0))
        ttk.Button(buttons,text='Cancel',command=win.destroy).pack(side='right')
        ttk.Button(buttons,text='Use this reading',style='Accent.TButton',command=ok).pack(side='right',padx=(0,8))
        win.bind('<Return>',ok);win.bind('<Escape>',lambda _e:win.destroy())
        win.grab_set();entry.focus_set()
    def _record(self,p,reading,synthetic):
        result='PASS' if p['low']<=reading<=p['high'] else 'FAIL'
        self.results[str(p['id'])]=dict(reading=reading,result=result,synthetic=synthetic,timestamp=datetime.now().isoformat(timespec='seconds'))
        self._update_row(p);self.save(silent=True)
    def save(self,silent=False):
        path=HERE/f'8846A_{"".join(c if c.isalnum() or c in "-_" else "_" for c in self.asset.get()) or "UNASSIGNED"}_checkpoint.json'
        path.write_text(json.dumps(dict(asset=self.asset.get(),serial=self.serial.get(),demo=self.demo,results=self.results),indent=2))
        if not silent:self.status.set(f'Saved {path.name}')
    def load(self):
        path=filedialog.askopenfilename(filetypes=[('Checkpoint','*.json')]);
        if not path:return
        data=json.loads(Path(path).read_text())
        if any(v.get('synthetic') for v in data.get('results',{}).values()) and not self.demo:
            if not messagebox.askyesno('Synthetic data','Checkpoint contains DEMO results. Load only for review (not a real calibration)?'):return
        self.asset.set(data.get('asset',''));self.serial.set(data.get('serial',''));self.results=data.get('results',{})
        self.results={k:v for k,v in self.results.items() if int(k) in BY_ID}     # drop results of deleted points
        for _id,_r in self.results.items():     # same test as _record(), against the current limits (the zero limits were corrected)
            _p=BY_ID.get(int(_id))
            if _p is not None and isinstance(_r.get('reading'),(int,float)):_r['result']='PASS' if _p['low']<=_r['reading']<=_p['high'] else 'FAIL'
        self.refresh();self.status.set(f'Loaded progress: {len(self.results)} point(s) restored.')
    @staticmethod
    def report_section(p):
        import report_pdf
        if p.get('zero_offset'):return 'Zero offset - '+p['terminal'].title()
        return report_pdf.KIND_NAMES[p['kind']]
    @staticmethod
    def report_mixed(p):
        return bool(p.get('zero_offset'))
    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        import report_pdf
        rows=[]
        for p in POINTS:
            r=self.results.get(str(p['id']))
            if not r:continue
            rows.append(report_pdf.point_row(p,r['reading'],r['result']=='FAIL',section=self.report_section(p),mixed=self.report_mixed(p)))
        return rows
    def export_pdf(self):
        rows=self.certificate_rows()
        if not rows:messagebox.showinfo('No results','No recorded results to export yet.');return
        try:import report_pdf,report_dialog
        except ImportError as exc:messagebox.showerror('Report export',str(exc));return
        details=report_dialog.ask_details(self.root,'Fluke 8846A one-year verification')
        if details is None:return
        asset=''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path=filedialog.asksaveasfilename(defaultextension='.pdf',filetypes=[('PDF report','*.pdf')],initialfile=ui.report_filename(asset))
        if not path:return
        demo=self.demo or any(v.get('synthetic') for v in self.results.values())
        try:
            report_pdf.write_calibration_pdf(path,rows,header=[('Instrument','Fluke 8846A'),('Instrument ID',self.asset.get()),('Serial',self.serial.get()),('Source','Fluke 8845A/8846A Calibration Manual, Appendix A Table A-2 - 1-year verification')],demo=demo,details=details,footer_note=report_pdf.uncertainty_note(rows))
        except ImportError:
            messagebox.showerror('PDF export dependency','Install the PDF package with:  py -m pip install reportlab');return
        except Exception as exc:
            messagebox.showerror('PDF export error',str(exc));return
        self.status.set(f'Exported {len(rows)} rows: {path}')
    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='8846A_verification.csv')
        if not path:return
        with open(path,'w',newline='',encoding='utf-8-sig') as file:
            writer=csv.writer(file);writer.writerow(['Instrument ID',self.asset.get(),'Serial Number',self.serial.get()]);writer.writerow(['SOURCE','Fluke 8845A/8846A Calibration Manual Appendix A Table A-2; 1-year verification']);writer.writerow(['DEMO DATA','YES' if self.demo or any(v.get('synthetic') for v in self.results.values()) else 'NO']);writer.writerow([])
            writer.writerow(['Section','Description','Nominal','Tolerance -','Tolerance +','UOM','As Found','OOT','Status','Timestamp','Synthetic','Manual override','Original reading','Override reason'])
            for p in POINTS:
                r=self.results.get(str(p['id']),{});n=p['nominal'];e=p['error']
                writer.writerow(['ZERO '+p['kind'] if p.get('zero_offset') else p['kind'],p['description'],n,p['low'],p['high'],p['unit'],r.get('reading',''),'OOT' if r.get('result')=='FAIL' else '',r.get('result',''),r.get('timestamp',''),r.get('synthetic',''),'MANUAL' if r.get('manual') else '',r.get('original','') if r.get('manual') else '',r.get('reason','') if r.get('manual') else ''])
        self.status.set(f'Exported 1-year verification: {path}')
    def export_excel(self):
        """Export a formatted, sectioned verification report. No synthetic results are certified."""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
            from openpyxl.worksheet.page import PageMargins
        except ImportError:
            messagebox.showerror('Excel dependency',
                'Install openpyxl using: py -m pip install openpyxl')
            return
        path=filedialog.asksaveasfilename(defaultextension='.xlsx',
            filetypes=[('Excel workbook','*.xlsx')],
            initialfile='8846A_Professional_Verification.xlsx')
        if not path:return
        wb=Workbook(); ws=wb.active;ws.title='Calibration Data'
        navy='17365D'; teal='DCEAF4'; light='F1F5FA'; red='FCE8E6'
        ws.merge_cells('A1:J1'); ws['A1']='FLUKE 8846A | PERFORMANCE VERIFICATION'
        ws['A1'].font=Font(name='Aptos Display',size=17,bold=True,color='FFFFFF')
        ws['A1'].fill=PatternFill('solid',fgColor=navy);ws['A1'].alignment=Alignment(vertical='center');ws.row_dimensions[1].height=36
        ws.merge_cells('A2:J2');ws['A2']='1-Year Verification  |  Manufacturer Appendix A, Table A-2'
        ws['A2'].font=Font(name='Aptos',size=11,italic=True,color=navy)
        ws.merge_cells('A3:J3');ws['A3']=f'Instrument ID: {self.asset.get().strip() or "NOT ENTERED"}    |    Serial Number: {self.serial.get().strip() or "NOT ENTERED"}'
        ws['A3'].font=Font(name='Aptos',size=11,bold=True,color=navy)
        synthetic=self.demo or any(v.get('synthetic') for v in self.results.values())
        ws.merge_cells('A4:J4');ws['A4']='DEMO / SYNTHETIC RESULTS — NOT FOR CERTIFICATION' if synthetic else 'Measured results only; blank cells indicate untested points'
        ws['A4'].font=Font(name='Aptos',bold=True,color='9C1C1C' if synthetic else navy)
        done=sum(bool(self.results.get(str(p['id']),{}).get('result')) for p in POINTS)
        fails=sum(self.results.get(str(p['id']),{}).get('result')=='FAIL' for p in POINTS)
        ws.merge_cells('A5:J5');ws['A5']=f'Test points: {len(POINTS)}    Completed: {done}    OOT: {fails}    Exported: {datetime.now():%Y-%m-%d %H:%M}'
        ws['A5'].font=Font(name='Aptos',bold=True,color=navy)
        heads=['Description','Nominal','Tolerance −','Tolerance +','UOM','As Found','OOT','Result','Timestamp','Manual override']
        row=7; last=None
        for p in POINTS:
            section={'DCV':'DC VOLTAGE','ACV':'AC VOLTAGE','FREQ':'FREQUENCY',
                     'OHM4':'4-WIRE RESISTANCE','OHM2':'2-WIRE RESISTANCE',
                     'CAP':'CAPACITANCE','DCI':'DC CURRENT','ACI':'AC CURRENT'}.get(p['kind'],p['kind'])
            if section!=last:
                if last is not None:row+=1
                ws.merge_cells(start_row=row,start_column=1,end_row=row,end_column=10)
                cell=ws.cell(row,1,section);cell.font=Font(name='Aptos',size=12,bold=True,color='FFFFFF')
                cell.fill=PatternFill('solid',fgColor=navy);ws.row_dimensions[row].height=23;row+=1
                for j,h in enumerate(heads,1):
                    c=ws.cell(row,j,h);c.font=Font(name='Aptos',bold=True,color=navy)
                    c.fill=PatternFill('solid',fgColor=teal);c.alignment=Alignment(wrap_text=True)
                ws.row_dimensions[row].height=24;row+=1;last=section
            r=self.results.get(str(p['id']),{})
            vals=[p['description'],p['nominal'],p['low'],p['high'],p['unit'],
                  r.get('reading'), 'OOT' if r.get('result')=='FAIL' else '',
                  r.get('result',''),r.get('timestamp',''),
                  (f'MANUAL: {r.get("reason","")} (automatic reading: {r.get("original") if r.get("original") not in (None,"") else "none"})' if r.get('manual') else '')]
            for j,value in enumerate(vals,1):
                c=ws.cell(row,j,value)
                c.font=Font(name='Aptos',size=10,bold=(j in (7,8) and r.get('result')=='FAIL'))
                c.alignment=Alignment(vertical='center')
                if row%2==0:c.fill=PatternFill('solid',fgColor=light)
                if r.get('result')=='FAIL' and j in (6,7,8):c.fill=PatternFill('solid',fgColor=red)
                if j in (2,3,4,6):c.number_format='0.##########'
            row+=1
        for j,w in enumerate([48,17,17,17,12,17,10,12,22,46],1):ws.column_dimensions[get_column_letter(j)].width=w
        ws.freeze_panes='B9';ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
        ws.print_options.horizontalCentered=True
        ws.page_margins=PageMargins(left=.25,right=.25,top=.4,bottom=.4,header=.2,footer=.2)
        ws.oddFooter.center.text='Page &P of &N'
        try:wb.save(path)
        except Exception as exc:
            messagebox.showerror('Excel export failed',str(exc));return
        self.status.set(f'Professional Excel report exported: {path}')
    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run','A point may be active. Stop and close?'):return
        self.stop=True;self._save_settings();self.disconnect();self.root.destroy()
if __name__=='__main__':
    import sys
    root=tk.Tk();App(root,demo='--demo' in sys.argv);root.mainloop()
