"""34401A 1-year gain verification. RS-232 DMM + Fluke 5560A.
Hardware I/O is OFF in demo mode. Never run unattended: wiring confirmations required.
Source: Keysight 34401A Service Guide, Ch 4 pp 69-71.
"""
import json, math, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # shared ui_theme.py sits next to the Manager
import ui_port
import ui_theme as ui                   # only its toolkit-free helpers here (si, si_row, report_filename, Settings); the window code is in a34401a_view_tk.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import appdata
import datamode
import procmods_engine
import reset_startup
import virtualbench
import drivers
DATA=HERE/'34401A_results.json'
POINTS=[]
def add(kind, value, rng, error, unit, freq=None, wiring=None, label=None):
    POINTS.append(dict(id=len(POINTS)+1,kind=kind,nominal=value,range=rng,error=error,unit=unit,frequency=freq,
                       wiring=wiring or ('CURRENT' if kind in ('DCI','ACI') else 'VOLTAGE' if kind in ('DCV','ACV','FREQ') else 'RESISTANCE_4W' if kind=='OHM4' else 'RESISTANCE_2W' if kind=='OHM2' else 'RESISTANCE'),
                       description=label or f'{kind} {value:g} {unit}'+(f' @ {freq:g} Hz' if freq else '')))
# One-year gain limits, absolute error in SI base units; 34401A Service Guide pp 69-71.
for v,r,e in [(.1,.1,8.5e-6),(1,1,47e-6),(10,10,400e-6),(-10,10,400e-6),(100,100,5.1e-3),(1000,1000,55e-3)]:add('DCV',v,r,e,'V')
for v,r,e in [(100,100,.014),(1000,1000,.110),(1e4,1e4,1.1),(1e5,1e5,11),(1e6,1e6,110),(1e7,1e7,4100),(1e8,1e8,810000)]:
    for k in ('OHM2','OHM4'):add(k,v,r,e+(0.2 if k=='OHM2' else 0),'ohm',label=f'{k} {v:g} ohm'+(' (2-wire +0.2 ohm allowance)' if k=='OHM2' else ''))
for v,r,e in [(.01,.01,7e-6),(.1,.1,55e-6),(1,1,1.1e-3),(2,3,3e-3)]:add('DCI',v,r,e,'A')
for v,f,r,e in [(.01,1e3,.1,46e-6),(.1,1e3,.1,100e-6),(.1,50e3,.1,170e-6),(1,1e3,1,900e-6),(1,50e3,1,1.7e-3),
                  (10,1e3,10,9e-3),(10,50e3,10,17e-3),(10,10,10,9e-3),(100,1e3,100,90e-3),(100,50e3,100,170e-3),
                  (750,1e3,750,.675),(750,50e3,750,1.275)]:add('ACV',v,r,e,'V',f)
for v,r,e in [(1,1,1.4e-3),(2,3,4.8e-3)]:add('ACI',v,r,e,'A',1e3)
for amplitude,f,r,e in [(.01,100,.1,.1),(1,100000,1,10)]:
    # Frequency nominal is Hz, but the source amplitude is voltage.
    add('FREQ',f,r,e,'Hz',freq=f,label=f'Frequency {f:g} Hz, {amplitude:g} V rms')
    POINTS[-1]['amplitude']=amplitude

# 34401A Service Guide, Ch. 4, pp. 67-68: one-year ZERO OFFSET limits.
# Front and rear have separate offset constants; test BOTH terminal sets.
# 2-wire resistance includes the manual's 0.2-ohm allowance when Math Null is not used.
ZERO_LIMITS = {
    'DCI': [(0.01,2e-6),(0.1,5e-6),(1,100e-6),(3,600e-6)],
    'DCV': [(0.1,3.5e-6),(1,7e-6),(10,50e-6),(100,600e-6),(1000,10e-3)],
    'OHM': [(100,0.004),(1000,0.010),(10000,0.100),(100000,1.0),
            (1e6,10.0),(1e7,100.0),(1e8,10000.0)]
}
for terminal in ('FRONT','REAR'):
    for kind in ('DCI','DCV','OHM2','OHM4'):
        limits=ZERO_LIMITS['OHM' if kind.startswith('OHM') else kind]
        for rng,err in limits:
            extra=0.2 if kind=='OHM2' else 0.0
            wiring=f'ZERO_{terminal}_{"OPEN_CURRENT" if kind=="DCI" else "SHORT"}'
            add(kind,0.0,rng,err+extra,'A' if kind=='DCI' else 'V' if kind=='DCV' else 'ohm',
                wiring=wiring,label=f'ZERO OFFSET {terminal} {kind} range {rng:g}'+
                (' (no Math Null; +0.2 ohm allowance)' if kind=='OHM2' else ''))
            POINTS[-1]['zero_offset']=True
            POINTS[-1]['terminal']=terminal
            POINTS[-1]['manual_limit']=err

class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O for this procedure: the DMM and the Fluke 5560A, both through the instrument drivers."""
    def __init__(self, dmm_port, fluke_port, baud, parity, bits, mods=None, transports=None, virtual=False):
        self.log=drivers.CommandLog()
        self.virtual=bool(virtual)
        if self.virtual:virtualbench.mark_log(self.log)
        if transports:dmm_t,fluke_t=transports
        else:
            dmm_t=drivers.open_visa(f'ASRL{dmm_port}::INSTR',timeout=20,baud=baud,data_bits=bits,
                parity=parity.lower(),stop_bits=2,write_termination='\n',read_termination='\n')
            fluke_t=drivers.open_visa(f'ASRL{fluke_port}::INSTR',timeout=20,baud=9600,write_termination='\n',read_termination='\n')
        self.dmm=drivers.Agilent34401A(dmm_t,self.log,label='34401A')
        self.fluke=drivers.Fluke5560A(fluke_t,self.log,label='5560A')
        try:
            self.fluke.open(verify_model=False)
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
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  34401A session\n'+'\n'.join(self.log.lines())+'\n')
        except OSError:pass
    @procmods_engine.point_commands()
    def measure(self,p):
        k=p['kind'];v=p['nominal'];r=p['range'];f=p['frequency']
        self.standby()
        if p.get('zero_offset'):
            # Zero-offset verification requires a physical copper short or OPEN current
            # input. The 5560A must remain in STBY and is never used as a zero source.
            self.dmm.configure(k,r)
            time.sleep(virtualbench.scaled(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('a34401.settle.zero',1.5),self.virtual))
            return self.dmm.read()
        if k in ('DCV','ACV','DCI','ACI'):
            self.dmm.configure(k,r)
            if k.startswith('AC'):
                self.dmm.set_ac_filter_slow()  # DET:BAND 3 - slow AC filter
            if k.endswith('V'):self.fluke.set_output_volts(v,f,dc=k=='DCV')
            else:self.fluke.set_output_amps(v,f,dc=k=='DCI')
        elif k in ('OHM2','OHM4'):
            self.dmm.configure(k,r)
            self.fluke.set_output_ohms(v)
        else:
            self.dmm.configure_frequency()
            self.fluke.set_output_volts(p["amplitude"],f)
        self.fluke.operate_unverified()
        time.sleep(virtualbench.scaled(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('a34401.settle.ac',3.5) if k.startswith('AC') else self.pm_param('a34401.settle.default',2),self.virtual))
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
        self.pm_init('a34401','34401A',demo=demo,lists=[POINTS])   # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings=ui.Settings('34401A')
        self.asset=port.var();self.serial=port.var()
        self.dmm_port=port.var(self.settings.get('dmm_port','COM3'))
        self.fluke_port=port.var(self.settings.get('fluke_port','COM9'))
        self.baud=port.var(self.settings.get('baud','9600'))
        self.parity=port.var(self.settings.get('parity','Even'))
        self.bits=port.var(self.settings.get('bits','7'))
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

    VIEW = 'a34401a_view'                               # the toolkit's window code: a34401a_view_tk (Tk), later _qt
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    def _build_ui(self): self.ui_view.build_ui(self)

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
        cells,tags=self.shell_cells(p['id'],p['nominal'],p['nominal']-p['error'],p['nominal']+p['error'],p['unit'])
        return (p['id'],f'{p["description"]}   (range {ui.si(p["range"],p["unit"])})',*cells),tags

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

    def pm_driver_classes(self):return (drivers.Agilent34401A,drivers.Fluke5560A)
    def pm_plan_point(self,p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from unittest import mock
        from drivers.simulated import make_dmm_bench
        def build(mods):
            _bench,ft,dt=make_dmm_bench('34401A')
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
        if hasattr(self,'tree'):self.update_shell_sections(POINTS,self._section)

    def on_select(self,_event=None):
        sel=self.ui_view.table_selection(self)
        if not sel:return
        p=POINTS[int(sel[0])-1]
        setup=('Zero offset: select the '+p['terminal']+' terminals and fit the short (open for current) - the 5560A stays in STANDBY.'
               if p.get('zero_offset') else self.SETUP_TEXT.get(p['wiring'],p['wiring']))
        _v,_r,_u=ui.si_row([p["nominal"]-p["error"],p["nominal"]+p["error"]],p['unit'])
        self.detail.set(f'{p["description"]}\nAcceptable reading: {_v[0]} to {_v[1]} {_u}     |     Setup: {setup}')

    def test_connections(self):
        if self.fast_demo:port.message('info', 'Demo mode','Demo mode uses no hardware, so there is nothing to connect.');return
        self.status.set('Connecting ...');port.flush(self.root)
        try:
            self.disconnect()
            if self.virtual:          # demo: the real IO / driver code over a simulated DMM and calibrator
                self._vb=virtualbench.dmm_pair('34401A')
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
        port.message('info', 'Connected'+(' (DEMO)' if self.virtual else ''),f'34401A: {self.io.ident}{tag}\nFluke port opened (output not enabled).')
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
                instruction=('Leave CURRENT input OPEN (no calibrator connected).'
                             if p['kind']=='DCI' else
                             'Install a low-thermal-EMF copper four-terminal SHORT across INPUT HI/LO and SENSE HI/LO. Do NOT use the 5560A as a zero source.')
                if not port.operator_prompt('Zero offset \u2014 physical setup required',f'Zero-offset setup: {location} terminals',
                    [('Select terminals',f'Use the front-panel FRONT/REAR switch to select the {location} terminals.'),
                     ('Set up the input',instruction)],
                    facts=[('Point',f'{p["id"]} of {len(POINTS)}'),('Terminals',location)],
                    caution='The 5560A stays in STANDBY. Confirm the terminal selection and physical setup before measuring.',
                    ok='Set up \u2014 measure', parent=self.root):
                    self.busy=False;self.status.set('Paused for zero-offset setup');return
            elif not self.fast_demo:
                msg={'VOLTAGE':'Connect 5560A voltage output to 34401A HI/LO voltage terminals. Verify safe leads and ranges.',
                     'CURRENT':'Put calibrator in STANDBY. Move leads to 34401A CURRENT input and LO. Check fuses and current ratings.',
                     'RESISTANCE_2W':'Put calibrator in STANDBY. Connect 2-wire resistance leads. 2-wire limits include the manual 0.2 ohm allowance; verify zero/null handling.',
                     'RESISTANCE_4W':'Put calibrator in STANDBY. Connect 4-wire force and sense leads to the correct DMM and calibrator terminals.'}[p['wiring']]
                if not port.operator_prompt('Rewire / verify before enabling output',f'Connect for {p["kind"]} tests',
                    [('Wiring',msg)],
                    facts=[('Next point',f'{p["id"]} of {len(POINTS)}'),('Test',p['description'])],
                    caution='Continue only after physically verifying the connections.',
                    ok='Connections verified \u2014 continue', parent=self.root):
                    self.busy=False;self.status.set('Paused for wiring');return
        if not self.fast_demo and p['nominal']==1000 and p['kind']=='DCV':
            if not port.ask_yes_no('HIGH VOLTAGE — 1000 V','This point requires 1000 V DC. Verify CAT-rated leads, connections, clearance, and personnel safety. Enable output?'):
                self.busy=False;return
        if not self.fast_demo and p['kind']=='ACV' and p['nominal']>=750:
            if not port.ask_yes_no('HIGH VOLTAGE — 750 V AC','Verify the calibrator can deliver this voltage/frequency into the load. Confirm safety before proceeding.'):
                self.busy=False;return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        
        if self.ui_view.table_has(self,str(p['id'])):self.ui_view.table_select(self,str(p['id']),see=True)
        if self.virtual:virtualbench.operator_sets_up(self._vb,p,terminal=p.get('terminal') if p.get('zero_offset') else None)     # the virtual operator does what the prompt asked
        if self.fast_demo:
            # Synthetic reading explicitly labeled; deterministic for reproducibility.
            reading=p['nominal']+p['error']*math.sin(p['id']*1.71)*0.38
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
        result='PASS' if abs(reading-p['nominal'])<=p['error'] else 'FAIL'
        self.results[str(p['id'])]=dict(reading=reading,result=result,synthetic=synthetic,timestamp=datetime.now().isoformat(timespec='seconds'),data=self.mode_label,**self.pm_result_fields())
        self._update_row(p);self.save(silent=True)
    def save(self,silent=False):
        path=appdata.progress_path(f'34401A_{"".join(c if c.isalnum() or c in "-_" else "_" for c in self.asset.get()) or "UNASSIGNED"}_checkpoint.json')
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
        details=port.report_details('Agilent 34401A one-year verification', parent=self.root)
        if details is None:return
        asset=''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path=port.save_file(defaultextension='.pdf',filetypes=[('PDF report','*.pdf')],initialfile=ui.report_filename(asset))
        if not path:return
        demo=self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows=report_pdf.apply_tar_tur(rows,details.get('show_tar_tur'),[tartur_wiring.point_fields(p,'5560A') for p in pts])
            report_pdf.write_calibration_pdf(path,rows,header=[('Instrument','Agilent 34401A'),('Instrument ID',self.asset.get()),('Serial',self.serial.get()),('Source','Keysight 34401A Service Guide, Ch. 4 - one-year gain and zero-offset verification')],demo=demo,details=details,footer_note=report_pdf.uncertainty_note(rows,'5560A'),snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency','Install the PDF package with:  py -m pip install reportlab');return
        except Exception as exc:
            port.message('error', 'PDF export error',str(exc));return
        self.status.set(f'Exported {len(rows)} rows: {path}')
    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run','A point may be active. Stop and close?'):return
        self.stop=True;self._save_settings();self.disconnect();port.close(self.root)
if __name__=='__main__':
    import sys
    def build(root):_demo,_fast=virtualbench.flags(sys.argv);App(root,demo=_demo,fast_demo=_fast)
    port.run_app(build)
