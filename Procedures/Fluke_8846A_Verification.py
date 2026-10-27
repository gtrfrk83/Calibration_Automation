"""8846A 1-year gain verification. RS-232 DMM + Fluke 5560A.
Hardware I/O is OFF in demo mode. Never run unattended: wiring confirmations required.
Source: Fluke 8845A/8846A Calibration Manual, Tables 3-4 and 3-18 (1-year).
"""
import json, math, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # shared ui_theme.py sits next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si, si_row, report_filename, Settings); the window code is in f8846a_view_qt.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import appdata
import datamode
import procmods_engine
import reset_startup
import virtualbench
import hookups
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
# The manual also specifies optional DC ratio, rear-terminal and split-lead tests.
# Those require distinct setups/measurement commands and are not executed here.

class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O for this procedure: the DMM and the Fluke 5560A, both through the instrument drivers."""
    def __init__(self, dmm_port, fluke_port, baud, parity, bits, mods=None, transports=None, virtual=False):
        self.log=drivers.CommandLog()
        self.virtual=bool(virtual)
        if self.virtual:virtualbench.mark_log(self.log)
        if transports:dmm_t,fluke_t=transports
        else:
            dmm_t=drivers.open_visa(f'ASRL{dmm_port}::INSTR',timeout=20,baud=baud,data_bits=bits,
                parity=parity.lower(),stop_bits=1,write_termination='\n',read_termination='\n')
            fluke_t=drivers.open_visa(f'ASRL{fluke_port}::INSTR',timeout=20,baud=9600,write_termination='\n',read_termination='\n')
        self.dmm=drivers.Fluke8846A(dmm_t,self.log,label='8846A')
        self.fluke=drivers.Fluke5560A(fluke_t,self.log,label='5560A')
        try:
            self.fluke.open(verify_model=False)
            self.fluke.write('STBY')
            self.dmm.connect()
            self.pm_attach(mods,*self.pm_drivers())
        except Exception:
            self.close();raise
        self.ident=self.dmm.idn
    def reset_roles(self):
        return [self.fluke],[self.dmm]
    def pm_drivers(self):
        return (self.dmm,self.fluke)
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
    def save_log(self):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt (a virtual demo session writes nothing)."""
        if virtualbench.log_is_virtual(self.log):return
        try:
            folder=Path.home()/'.calibration_suite';folder.mkdir(parents=True,exist_ok=True)
            with open(folder/'command_log.txt','a',encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  8846A session\n'+'\n'.join(self.log.lines())+'\n')
        except OSError:pass
    @procmods_engine.point_commands()
    def measure(self,p):
        k=p['kind'];v=p['nominal'];r=p['range'];f=p['frequency']
        self.standby()
        if p.get('zero_offset'):
            # Zero-offset verification requires a physical copper short or OPEN current
            # input. The 5560A must remain in STBY and is never used as a zero source.
            self.dmm.configure(k,r)
            time.sleep(virtualbench.scaled(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('f8846a.settle.zero',1.5),self.virtual))
            return self.dmm.read()
        if k in ('CAP','FREQ'):
            raise RuntimeError(f'{k} source/measurement commands must be verified at the lab before enabling hardware automation. Point is retained for guided review.')
        if k in ('DCV','ACV','DCI','ACI'):
            self.dmm.configure(k,r)
            if k.startswith('AC'):
                raise RuntimeError('AC filter and Fluke source setup must be lab-verified before automatic output is enabled.')
            if k.endswith('V'):self.fluke.set_output_volts(v,f,dc=k=='DCV')
            else:self.fluke.set_output_amps(v,f,dc=k=='DCI')
        elif k in ('OHM2','OHM4'):
            self.dmm.configure(k,r)
            self.fluke.set_output_ohms(v)
        else:
            self.dmm.configure_frequency()
            self.fluke.set_output_volts(p["amplitude"],f)
        self.fluke.operate_unverified()
        time.sleep(virtualbench.scaled(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('f8846a.settle.ac',3.5) if k.startswith('AC') else self.pm_param('f8846a.settle.default',2),self.virtual))
        reading=self.dmm.read()
        self.standby()
        return reading

class App(virtualbench.VirtualMixin,reset_startup.AppResetMixin,datamode.DataModeMixin,procmods_engine.ProcModsMixin):
    SETUP_TEXT = {
        'VOLTAGE': '5560A voltage output to the meter HI / LO terminals',
        'CURRENT': '5560A current output to the meter current (A) input and LO',
        'RESISTANCE_2W': '2-wire resistance leads from the 5560A',
        'RESISTANCE_4W': '4-wire force and sense leads from the 5560A',
        'CAPACITANCE': 'Capacitance fixture (confirm OPEN compensation per manual)',
    }

    def __init__(self,root,demo=False,fast_demo=False):
        self.init_virtual(demo,fast_demo)
        self.root=root;self.demo=demo;self.io=None;self._busy=False;self.stop=False
        self.results={}
        self.pm_init('f8846a','8846A',demo=demo,lists=[POINTS],shape='band')   # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings=ui.Settings('8846A')
        self.asset=port.var();self.serial=port.var()
        self.dmm_port=port.var(self.settings.get('dmm_port','COM3'))
        self.fluke_port=port.var(self.settings.get('fluke_port','COM9'))
        self.baud=port.var(self.settings.get('baud','9600'))
        self.parity=port.var(self.settings.get('parity','None'))
        self.bits=port.var(self.settings.get('bits','8'))
        self.status=port.var()
        self.detail=port.var('Select a test point to see its limits and wiring.')
        self.show_section=port.var('All sections')
        self.show_status=port.var('All points')
        self._build_ui()
        self.refresh_ports()
        self.refresh()
        self.status.set(virtualbench.status_text(self) if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose COM ports and press Test Connections. Step 3: Run All.')
        port.on_close(root,self.on_close)
        port.bind_key(root,'<Control-s>',self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ layout
    @property
    def busy(self):return self._busy
    @busy.setter
    def busy(self,value):
        self._busy=value
        if hasattr(self,'btn_run'):self._sync_buttons()

    VIEW = 'f8846a_view'                               # window code: f8846a_view_qt.py
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    def _build_ui(self): self.ui_view.build_ui(self)

    def _update_sections(self):
        self.update_shell_sections(POINTS,self._section)

    @staticmethod
    def _section(p):
        return 'ZERO '+p['terminal'] if p.get('zero_offset') else p['kind']

    def _visible(self,p):
        res=self.results.get(str(p['id']),{}).get('result','')
        sec=self.show_section.get();st=self.show_status.get()
        if sec!='All sections' and self._section(p)!=sec:return False
        if st=='Not tested' and res:return False
        if st=='Passed' and res!='PASS':return False
        if st=='Failed (OOT)' and res!='FAIL':return False
        if not self.status_visible(str(p['id']),st):return False
        return True

    def _row(self,p):
        cells,tags=self.shell_cells(p['id'],p['nominal'],p['low'],p['high'],p['unit'])
        return (p['id'],p['description'],*cells),tags

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
        for widget,current in (('dmm',self.dmm_port),('fluke',self.fluke_port)):
            value=current.get().strip().upper()
            if value and not value.startswith('COM') and value.isdigit():value='COM'+value
            self.ui_view.set_choices(self,widget,ports)
            if value:current.set(value)
        if ports:self.status.set('Serial ports found: '+', '.join(ports)+'. Pick the port for each instrument.')

    @staticmethod
    def parse_com(value):
        value=value.strip().upper()
        if value.startswith('COM'):value=value[3:]
        if not value.isdigit() or int(value)<1:
            raise ValueError('Select a valid COM port, such as COM3, or enter its number.')
        return int(value)

    def pm_driver_classes(self):return (drivers.Fluke8846A,drivers.Fluke5560A)
    def pm_plan_point(self,p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from unittest import mock
        from drivers.simulated import make_dmm_bench
        def build(mods):
            _bench,ft,dt=make_dmm_bench('8846A')
            queue_=[dt,ft]
            with mock.patch.object(drivers,'open_visa',lambda *a,**k:queue_.pop(0)):
                return IO('1','2',9600,'None',8,mods=mods)
        return procmods_plan.run_plan(self.pm_state,build,lambda io:io.measure(p))
    def refresh(self):
        keep=self.ui_view.table_selection(self)
        self.ui_view.table_set_rows(self,((str(p['id']),*self._row(p)) for p in POINTS if self._visible(p)),keep)
        self.update_summary()

    def _update_row(self,p):
        iid=str(p['id'])
        if self.ui_view.table_has(self,iid):
            values,tags=self._row(p);self.ui_view.table_update_row(self,iid,values,tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(POINTS)
        if hasattr(self,'_section_names'):self._update_sections()

    def on_select(self,_event=None):
        sel=self.ui_view.table_selection(self)
        if not sel:return
        p=POINTS[int(sel[0])-1]
        setup=('Zero offset: select the '+p['terminal']+' terminals and fit the short (open for current) - the 5560A stays in STANDBY.'
               if p.get('zero_offset') else self.SETUP_TEXT.get(p['wiring'],p['wiring']))
        _v,_r,_u=ui.si_row([p["low"],p["high"]],p['unit'])
        self.detail.set(f'{p["description"]}   |   Range {ui.si(p["range"],p["unit"])}\nAcceptable reading: {_v[0]} to {_v[1]} {_u}     |     Setup: {setup}')

    def test_connections(self):
        if self.fast_demo:port.message('info', 'Demo mode','Demo mode uses no hardware, so there is nothing to connect.');return
        self.status.set('Connecting ...');port.flush(self.root)
        try:
            self.disconnect()
            if self.virtual:          # demo: the real IO / driver code over a simulated DMM and calibrator
                self._vb=virtualbench.dmm_pair('8846A')
                self.io=IO('virtual','virtual',9600,'None',8,mods=self.pm_state,transports=(self._vb[2],self._vb[1]),virtual=True)
            else:self.io=IO(self.parse_com(self.dmm_port.get()),self.parse_com(self.fluke_port.get()),
                                        int(self.baud.get()),self.parity.get(),int(self.bits.get()),mods=self.pm_state)
        except Exception as exc:
            self.disconnect();self._set_conn(False)
            self.status.set('Connection error: '+str(exc))
            port.message('error', 'Connection error',str(exc));return
        self._set_conn(True)
        if not self.demo:self._save_settings()
        tag=' '+virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: '+self.io.ident+tag+'. Fluke output is NOT enabled.')
        port.message('info', 'Connected'+(' (DEMO)' if self.virtual else ''),f'8846A: {self.io.ident}{tag}\nFluke port opened (output not enabled).')
    def disconnect(self):
        if self.io:self.io.close();self.io=None
        self._set_conn(None)
    def _set_conn(self,ok):
        if hasattr(self,'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')
    def _save_settings(self):
        for key,var in (('dmm_port',self.dmm_port),('fluke_port',self.fluke_port),('baud',self.baud),('parity',self.parity),('bits',self.bits)):
            self.settings.set(key,var.get())
        self.settings.save()
    def request_stop(self):self.stop=True;self.status.set('Stopping after current test point.')
    def run_all(self):self.execute([p for p in POINTS if str(p['id']) not in self.results])
    def run_section(self):self.run_shown_section(POINTS)
    def rerun(self):
        selected=self.ui_view.table_selection(self)
        if selected:self.execute([POINTS[int(selected[0])-1]])
        else:port.message('info', 'Selection','Select a test point first.')
    def rerun_from(self):
        selected=self.ui_view.table_selection(self)
        if selected:self.execute(self.points_from(POINTS,selected[0]))
        else:port.message('info', 'Selection','Select a test point first.')
    def execute(self,points):
        if not self.confirm_found_overwrite(points):return
        if self.busy or not points:return
        if not self.asset.get().strip():port.message('warning', 'Instrument ID','Enter an instrument ID.');return
        points=self.pm_begin_run(points,self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points:self.status.set('Every selected point is skipped by a procedure modification.');return
        if not self.fast_demo and self.io is None:self.test_connections()
        if not self.fast_demo and self.io is None:return
        self.stop=False;self.busy=True
        self.reset_then(lambda:self._next(points,0,None))   # every run (first, re-run, resume): reset to defaults before the first point
    def _next(self,points,i,previous):
        if i>=len(points) or self.stop:
            self.busy=False;self.save();self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.');return
        p=points[i]
        try:p,previous=self.pm_step(points,i,previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc:self._error(exc);return
        if p is None:port.after(self.root,30,lambda:self._next(points,i+1,previous));return     # skipped by an edit made during the run
        if p['wiring']!=previous:
            if not self.fast_demo and p.get('zero_offset'):
                self.io.standby()
                location=p['terminal']
                instruction=('Leave CURRENT input OPEN (no calibrator connected).' if p['kind']=='DCI' else
                             'Use the manual-prescribed OPEN capacitance fixture.' if p['kind']=='CAP' else
                             'Install the manual-prescribed low-thermal short/shorted leads. Do NOT use the 5560A as a zero source.')
                if not port.operator_prompt('Zero offset \u2014 physical setup required',f'Zero-offset setup: {location} terminals',
                    [('Select terminals',f'Use the front-panel FRONT/REAR switch to select the {location} terminals.'),
                     ('Set up the input',instruction)],
                    facts=[('Point',f'{p["id"]} of {len(POINTS)}'),('Terminals',location)],
                    caution='The 5560A stays in STANDBY. Confirm the terminal selection and physical setup before measuring.',
                    ok='Set up \u2014 measure', image=hookups.bench_image('8846A','ZERO',terminal=location,open_input=p['kind']=='DCI') if p['kind']!='CAP' else hookups.panel_image('8846A'), parent=self.root):
                    self.busy=False;self.status.set('Paused for zero-offset setup');return
            elif not self.fast_demo:
                msg={'VOLTAGE':'Connect 5560A voltage output to 8846A HI/LO voltage terminals. Verify safe leads and ranges.',
                     'CURRENT':'Put calibrator in STANDBY. Move leads to 8846A CURRENT input and LO. Check fuses and current ratings.',
                     'RESISTANCE_2W':'Put calibrator in STANDBY. Connect 2-wire resistance leads. 2-wire limits include the manual 0.2 ohm allowance; verify zero/null handling.',
                     'RESISTANCE_4W':'Put calibrator in STANDBY. Connect 4-wire force and sense leads to the correct DMM and calibrator terminals.',
                     'CAPACITANCE':'Put calibrator in STANDBY. Connect capacitance fixture; verify OPEN compensation and meter setup per manual.'}[p['wiring']]
                if not port.operator_prompt('Rewire / verify before enabling output',f'Connect for {p["kind"]} tests',
                    [('Wiring',msg)],
                    facts=[('Next point',f'{p["id"]} of {len(POINTS)}'),('Test',p['description'])],
                    caution='Continue only after physically verifying the connections.',
                    ok='Connections verified \u2014 continue', image=hookups.bench_image('8846A',{'VOLTAGE':'VOLT','CURRENT':'CURRENT','RESISTANCE_2W':'RES2','RESISTANCE_4W':'RES4'}.get(p['wiring']),nominal=p['nominal'],rng=p.get('range')), parent=self.root):
                    self.busy=False;self.status.set('Paused for wiring');return
        if not self.fast_demo and abs(p['nominal'])>=1000 and p['kind'] in ('DCV','ACV'):
            if not port.ask_yes_no('HIGH VOLTAGE — 1000 V','This point requires hazardous high voltage. Verify leads, connections, clearance and personnel safety. Enable output?'):
                self.busy=False;return
        if not self.fast_demo and p['kind']=='ACV' and p['nominal']>=750:
            if not port.ask_yes_no('HIGH VOLTAGE — 750 V AC','Verify the calibrator can deliver this voltage/frequency into the load. Confirm safety before proceeding.'):
                self.busy=False;return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        
        if self.ui_view.table_has(self,str(p['id'])):self.ui_view.table_select(self,str(p['id']),see=True)
        if self.virtual:virtualbench.operator_sets_up(self._vb,p,terminal=p.get('terminal') if p.get('zero_offset') else None)     # the virtual operator does what the prompt asked
        if self.fast_demo:
            # Synthetic reading explicitly labeled; deterministic for reproducibility.
            reading=(p['low']+p['high'])/2+(p['high']-p['low'])/2*math.sin(p['id']*1.71)*0.38
            self._record(p,reading,True);port.after(self.root,50,lambda:self._next(points,i+1,p['wiring']))
        else:
            def work():
                try:
                    reading=self.io.measure(p)
                    port.post(self.root,lambda:self._done(points,i,p,reading))
                except Exception as exc:
                    try:self.io.standby()
                    except Exception:pass
                    err=exc   # 'exc' is deleted when the except block ends; capture by default arg
                    port.post(self.root,lambda err=err:self._error(err))
            threading.Thread(target=work,daemon=True).start()
    def _done(self,points,i,p,reading):
        self._record(p,reading,bool(self.demo))
        port.after(self.root,50,lambda:self._next(points,i+1,p['wiring']))
    def _error(self,exc):self.busy=False;self.status.set('Error - run stopped: '+str(exc));port.message('error', 'Measurement stopped',str(exc))
    def _record(self,p,reading,synthetic):
        result='PASS' if p['low']<=reading<=p['high'] else 'FAIL'
        self.results[str(p['id'])]=dict(reading=reading,result=result,synthetic=synthetic,timestamp=datetime.now().isoformat(timespec='seconds'),data=self.mode_label,**self.pm_result_fields())
        self._update_row(p);self.save(silent=True)
    def save(self,silent=False):
        path=appdata.progress_path(f'8846A_{"".join(c if c.isalnum() or c in "-_" else "_" for c in self.asset.get()) or "UNASSIGNED"}_checkpoint.json')
        path.write_text(json.dumps(dict(asset=self.asset.get(),serial=self.serial.get(),demo=self.demo,**self.save_fields(),**self.pm_checkpoint_fields()),indent=2))
        if not silent:self.status.set(f'Saved {path.name}')
    def load(self):
        path=port.choose_file(filetypes=[('Checkpoint','*.json')]);
        if not path:return
        data=json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data','Checkpoint contains DEMO results. Load only for review (not a real calibration)?'):return
        self.asset.set(data.get('asset',''));self.serial.set(data.get('serial',''));self.load_results(data);self.pm_on_checkpoint(data);self.refresh();self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')
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
        return self.certificate_rows_and_points()[0]
    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from (for the optional TAR / TUR fields)."""
        import report_pdf
        rows=[];pts=[]
        for p in POINTS:
            row=self.found_left_row(p,lambda r:report_pdf.point_row(p,r['reading'],r['result']=='FAIL',section=self.report_section(p),mixed=self.report_mixed(p),standard='5560A'))
            if row:rows.append(row);pts.append(p)
        return rows,pts
    def export_pdf(self):
        rows,pts=self.certificate_rows_and_points()
        if not rows:port.message('info', 'No results','No recorded results to export yet.');return
        try:import report_pdf
        except ImportError as exc:port.message('error', 'Report export',str(exc));return
        details=port.report_details('Fluke 8846A one-year verification', parent=self.root)
        if details is None:return
        asset=''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path=port.save_file(defaultextension='.pdf',filetypes=[('PDF report','*.pdf')],initialfile=ui.report_filename(asset))
        if not path:return
        demo=self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows=report_pdf.apply_tar_tur(rows,details.get('show_tar_tur'),[tartur_wiring.point_fields(p,'5560A') for p in pts])
            report_pdf.write_calibration_pdf(path,rows,header=[('Instrument','Fluke 8846A'),('Instrument ID',self.asset.get()),('Serial',self.serial.get()),('Source','Fluke 8845A/8846A Calibration Manual, Appendix A Table A-2 - 1-year verification')],demo=demo,details=details,footer_note=report_pdf.uncertainty_note(rows,'5560A'),snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency','Install the PDF package with:  py -m pip install reportlab');return
        except Exception as exc:
            port.message('error', 'PDF export error',str(exc));return
        self.status.set(f'Exported {len(rows)} rows: {path}')
    def export_excel(self):
        """Export a formatted, sectioned verification report. No synthetic results are certified."""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
            from openpyxl.worksheet.page import PageMargins
        except ImportError:
            port.message('error', 'Excel dependency',
                'Install openpyxl using: py -m pip install openpyxl')
            return
        path=port.save_file(defaultextension='.xlsx',
            filetypes=[('Excel workbook','*.xlsx')],
            initialfile='8846A_Professional_Verification.xlsx')
        if not path:return
        wb=Workbook(); ws=wb.active;ws.title='Calibration Data'
        navy='17365D'; teal='DCEAF4'; light='F1F5FA'; red='FCE8E6'
        ws.merge_cells('A1:I1'); ws['A1']='FLUKE 8846A | PERFORMANCE VERIFICATION'
        ws['A1'].font=Font(name='Aptos Display',size=17,bold=True,color='FFFFFF')
        ws['A1'].fill=PatternFill('solid',fgColor=navy);ws['A1'].alignment=Alignment(vertical='center');ws.row_dimensions[1].height=36
        ws.merge_cells('A2:I2');ws['A2']='1-Year Verification  |  Manufacturer Appendix A, Table A-2'
        ws['A2'].font=Font(name='Aptos',size=11,italic=True,color=navy)
        ws.merge_cells('A3:I3');ws['A3']=f'Instrument ID: {self.asset.get().strip() or "NOT ENTERED"}    |    Serial Number: {self.serial.get().strip() or "NOT ENTERED"}'
        ws['A3'].font=Font(name='Aptos',size=11,bold=True,color=navy)
        synthetic=self.any_synthetic()
        ws.merge_cells('A4:I4');ws['A4']='DEMO / SYNTHETIC RESULTS — NOT FOR CERTIFICATION' if synthetic else 'Measured results only; blank cells indicate untested points'
        ws['A4'].font=Font(name='Aptos',bold=True,color='9C1C1C' if synthetic else navy)
        done=sum(bool(self.found.get(str(p['id']),{}).get('result')) for p in POINTS)
        fails=sum(self.found.get(str(p['id']),{}).get('result')=='FAIL' for p in POINTS)
        ws.merge_cells('A5:I5');ws['A5']=f'Test points: {len(POINTS)}    Completed: {done}    OOT: {fails}    Exported: {datetime.now():%Y-%m-%d %H:%M}'
        ws['A5'].font=Font(name='Aptos',bold=True,color=navy)
        heads=['Description','Nominal','Tolerance −','Tolerance +','UOM','As Found','OOT','Result','Timestamp','As Left']
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
            r=self.found.get(str(p['id']),{});lr=self.left.get(str(p['id']),{})
            vals=[p['description'],p['nominal'],p['low'],p['high'],p['unit'],
                  r.get('reading'), 'OOT' if r.get('result')=='FAIL' else '',
                  r.get('result',''),r.get('timestamp',''),
                  (lr.get('reading') if lr else ('Same' if r else ''))]
            for j,value in enumerate(vals,1):
                c=ws.cell(row,j,value)
                c.font=Font(name='Aptos',size=10,bold=(j in (7,8) and r.get('result')=='FAIL'))
                c.alignment=Alignment(vertical='center')
                if row%2==0:c.fill=PatternFill('solid',fgColor=light)
                if r.get('result')=='FAIL' and j in (6,7,8):c.fill=PatternFill('solid',fgColor=red)
                if j in (2,3,4,6):c.number_format='0.##########'
            row+=1
        for j,w in enumerate([48,17,17,17,12,17,10,12,22,17],1):ws.column_dimensions[get_column_letter(j)].width=w
        ws.freeze_panes='B9';ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
        ws.print_options.horizontalCentered=True
        ws.page_margins=PageMargins(left=.25,right=.25,top=.4,bottom=.4,header=.2,footer=.2)
        ws.oddFooter.center.text='Page &P of &N'
        try:wb.save(path)
        except Exception as exc:
            port.message('error', 'Excel export failed',str(exc));return
        self.status.set(f'Professional Excel report exported: {path}')
    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run','A point may be active. Stop and close?'):return
        self.stop=True;self._save_settings();self.disconnect();port.close(self.root)
if __name__=='__main__':
    import sys
    def build(root):_demo,_fast=virtualbench.flags(sys.argv);App(root,demo=_demo,fast_demo=_fast)
    port.run_app(build)
