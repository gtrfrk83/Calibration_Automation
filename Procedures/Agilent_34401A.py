"""34401A 1-year gain verification. RS-232 DMM + Fluke 5560A.
Hardware I/O is OFF in demo mode. Never run unattended: wiring confirmations required.
Source: Keysight 34401A Service Guide, Ch 4 pp 69-71.
"""
import csv, json, math, sys, threading, time, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # shared ui_theme.py sits next to the Manager
import ui_theme as ui
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

class IO:
    """Bench I/O for this procedure: the DMM and the Fluke 5560A, both through the instrument drivers."""
    def __init__(self, dmm_port, fluke_port, baud, parity, bits):
        self.log=drivers.CommandLog()
        self.dmm=drivers.Agilent34401A(drivers.open_visa(f'ASRL{dmm_port}::INSTR',timeout=20,baud=baud,data_bits=bits,
            parity=parity.lower(),stop_bits=2,write_termination='\n',read_termination='\n'),self.log,label='34401A')
        self.fluke=drivers.Fluke5560A(drivers.open_visa(f'ASRL{fluke_port}::INSTR',timeout=20,baud=9600,
            write_termination='\n',read_termination='\n'),self.log,label='5560A')
        try:
            self.fluke.open(verify_model=False)
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
    def save_log(self):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt."""
        try:
            folder=Path.home()/'.calibration_suite';folder.mkdir(parents=True,exist_ok=True)
            with open(folder/'command_log.txt','a',encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  34401A session\n'+'\n'.join(self.log.lines())+'\n')
        except OSError:pass
    def measure(self,p):
        k=p['kind'];v=p['nominal'];r=p['range'];f=p['frequency']
        self.standby()
        if p.get('zero_offset'):
            # Zero-offset verification requires a physical copper short or OPEN current
            # input. The 5560A must remain in STBY and is never used as a zero source.
            self.dmm.configure(k,r)
            time.sleep(1.5)
            return self.dmm.read()
        if k in ('DCV','ACV','DCI','ACI'):
            self.dmm.configure(k,r)
            if k.startswith('AC'):
                self.dmm.set_ac_filter_slow()  # DET:BAND 3 - slow AC filter
            if k.endswith('V'):self.fluke.set_output_volts(v,f)
            else:self.fluke.set_output_amps(v,f)
        elif k in ('OHM2','OHM4'):
            self.dmm.configure(k,r)
            self.fluke.set_output_ohms(v)
        else:
            self.dmm.configure_frequency()
            self.fluke.set_output_volts(p["amplitude"],f)
        self.fluke.operate_unverified()
        time.sleep(3.5 if k.startswith('AC') else 2)
        reading=self.dmm.read()
        self.standby()
        return reading

class App:
    SETUP_TEXT = {
        'VOLTAGE': '5560A voltage output to the meter HI / LO terminals',
        'CURRENT': '5560A current output to the meter current (A) input and LO',
        'RESISTANCE_2W': '2-wire resistance leads from the 5560A',
        'RESISTANCE_4W': '4-wire force and sense leads from the 5560A',
        'CAPACITANCE': 'Capacitance fixture (confirm OPEN compensation per manual)',
    }

    def __init__(self,root,demo=False):
        self.root=root;self.demo=demo;self.io=None;self._busy=False;self.stop=False
        self.results={}
        ui.apply_theme(root)
        root.title('Agilent 34401A | Performance Verification v54'+(' [DEMO]' if demo else ''))
        ui.fit_window(root,1280,800,min_w=1060,min_h=620)
        self.settings=ui.Settings('34401A')
        self.asset=tk.StringVar();self.serial=tk.StringVar()
        self.dmm_port=tk.StringVar(value=self.settings.get('dmm_port','COM3'))
        self.fluke_port=tk.StringVar(value=self.settings.get('fluke_port','COM9'))
        self.baud=tk.StringVar(value=self.settings.get('baud','9600'))
        self.parity=tk.StringVar(value=self.settings.get('parity','Even'))
        self.bits=tk.StringVar(value=self.settings.get('bits','7'))
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
        for b in (self.btn_run,self.btn_rerun,self.btn_test,self.btn_load,self.btn_refresh_ports):b.configure(state=idle)
        self.btn_stop.configure(state='normal' if self._busy else 'disabled')
        for c in (self.dmm_combo,self.fluke_combo):c.configure(state='disabled' if self._busy else 'normal')

    def _build_ui(self):
        root=self.root
        banner=ui.Banner(root,'Agilent 34401A  -  Performance Verification','One-year gain and zero-offset verification  |  Keysight 34401A Service Guide, Ch. 4, pp. 67-71')
        banner.pack(fill='x')
        if self.demo:banner.add_pill('DEMO MODE  -  simulated readings','warn')
        else:banner.add_pill('HARDWARE MODE','info')
        self.conn_pill=banner.add_pill('Not connected','neutral')
        bar=ui.StatusBar(root,self.status,right='v54')
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
        ttk.Label(conn,text='34401A port').grid(row=0,column=0,sticky='w',pady=3)
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
        ttk.Label(row,text='Match the DMM front-panel RS-232 settings (2 stop bits).',style='Muted.TLabel').pack(side='left')

        if self.demo:
            ui.Notice(body,'Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.','warn',title='Demo mode').pack(fill='x',pady=(12,0))
        else:
            ui.Notice(body,'The program pauses and asks you to confirm the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.','info',title='Hardware mode').pack(fill='x',pady=(12,0))

        ttk.Label(body,text='Zero offsets are verified on BOTH the FRONT and REAR terminals. Optional AC tests are not included.',style='Small.TLabel').pack(anchor='w',pady=(6,0))
        tools=ttk.Frame(body);tools.pack(fill='x',pady=(8,6))
        self.btn_run=ttk.Button(tools,text='▶  Run All Pending',style='Accent.TButton',command=self.run_all);self.btn_run.pack(side='left')
        self.btn_rerun=ttk.Button(tools,text='Rerun Selected',command=self.rerun);self.btn_rerun.pack(side='left',padx=8)
        self.btn_stop=ttk.Button(tools,text='■  Stop After This Point',style='Danger.TButton',command=self.request_stop,state='disabled');self.btn_stop.pack(side='left')
        for text,cb in (('Export Report (PDF)',self.export_pdf),):
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
        return 'ZERO '+p['terminal'] if p.get('zero_offset') else p['kind']

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
        vals,reads,unit_text=ui.si_row([p['nominal'],p["nominal"]-p["error"],p["nominal"]+p["error"]],p['unit'],[reading] if reading!='' else [])
        shown={'PASS':'✔ PASS','FAIL':'✖ FAIL'}.get(res,'—')
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
        p=POINTS[int(sel[0])-1]
        setup=('Zero offset: select the '+p['terminal']+' terminals and fit the short (open for current) - the 5560A stays in STANDBY.'
               if p.get('zero_offset') else self.SETUP_TEXT.get(p['wiring'],p['wiring']))
        _v,_r,_u=ui.si_row([p["nominal"]-p["error"],p["nominal"]+p["error"]],p['unit'])
        self.detail.set(f'{p["description"]}\nAcceptable reading: {_v[0]} to {_v[1]} {_u}     |     Setup: {setup}')

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
        messagebox.showinfo('Connected',f'34401A: {self.io.ident}\nFluke port opened (output not enabled).')
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
        if selected:self.execute([POINTS[int(selected[0])-1]])
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
        if p['wiring']!=previous:
            if not self.demo and p.get('zero_offset'):
                self.io.standby()
                location=p['terminal']
                instruction=('Leave CURRENT input OPEN (no calibrator connected).'
                             if p['kind']=='DCI' else
                             'Install a low-thermal-EMF copper four-terminal SHORT across INPUT HI/LO and SENSE HI/LO. Do NOT use the 5560A as a zero source.')
                if not ui.confirm_steps(self.root,'Zero offset \u2014 physical setup required',f'Zero-offset setup: {location} terminals',
                    [('Select terminals',f'Use the front-panel FRONT/REAR switch to select the {location} terminals.'),
                     ('Set up the input',instruction)],
                    facts=[('Point',f'{p["id"]} of {len(POINTS)}'),('Terminals',location)],
                    caution='The 5560A stays in STANDBY. Confirm the terminal selection and physical setup before measuring.',
                    ok='Set up \u2014 measure'):
                    self.busy=False;self.status.set('Paused for zero-offset setup');return
            elif not self.demo:
                msg={'VOLTAGE':'Connect 5560A voltage output to 34401A HI/LO voltage terminals. Verify safe leads and ranges.',
                     'CURRENT':'Put calibrator in STANDBY. Move leads to 34401A CURRENT input and LO. Check fuses and current ratings.',
                     'RESISTANCE_2W':'Put calibrator in STANDBY. Connect 2-wire resistance leads. 2-wire limits include the manual 0.2 ohm allowance; verify zero/null handling.',
                     'RESISTANCE_4W':'Put calibrator in STANDBY. Connect 4-wire force and sense leads to the correct DMM and calibrator terminals.'}[p['wiring']]
                if not ui.confirm_steps(self.root,'Rewire / verify before enabling output',f'Connect for {p["kind"]} tests',
                    [('Wiring',msg)],
                    facts=[('Next point',f'{p["id"]} of {len(POINTS)}'),('Test',p['description'])],
                    caution='Continue only after physically verifying the connections.',
                    ok='Connections verified \u2014 continue'):
                    self.busy=False;self.status.set('Paused for wiring');return
        if not self.demo and p['nominal']==1000 and p['kind']=='DCV':
            if not messagebox.askyesno('HIGH VOLTAGE — 1000 V','This point requires 1000 V DC. Verify CAT-rated leads, connections, clearance, and personnel safety. Enable output?'):
                self.busy=False;return
        if not self.demo and p['kind']=='ACV' and p['nominal']>=750:
            if not messagebox.askyesno('HIGH VOLTAGE — 750 V AC','Verify the calibrator can deliver this voltage/frequency into the load. Confirm safety before proceeding.'):
                self.busy=False;return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        
        if self.tree.exists(str(p['id'])):self.tree.selection_set(str(p['id']));self.tree.see(str(p['id']))
        if self.demo:
            # Synthetic reading explicitly labeled; deterministic for reproducibility.
            reading=p['nominal']+p['error']*math.sin(p['id']*1.71)*0.38
            self._record(p,reading,True);self.root.after(50,lambda:self._next(points,i+1,p['wiring']))
        else:
            def work():
                try:
                    reading=self.io.measure(p)
                    self.root.after(0,lambda:self._done(points,i,p,reading))
                except Exception as exc:
                    try:self.io.standby()
                    except Exception:pass
                    self.root.after(0,lambda:self._error(exc))
            threading.Thread(target=work,daemon=True).start()
    def _done(self,points,i,p,reading):
        self._record(p,reading,False)
        self.root.after(50,lambda:self._next(points,i+1,p['wiring']))
    def _error(self,exc):self.busy=False;self.status.set('Error - run stopped: '+str(exc));messagebox.showerror('Measurement stopped',str(exc))
    def _record(self,p,reading,synthetic):
        result='PASS' if abs(reading-p['nominal'])<=p['error'] else 'FAIL'
        self.results[str(p['id'])]=dict(reading=reading,result=result,synthetic=synthetic,timestamp=datetime.now().isoformat(timespec='seconds'))
        self._update_row(p);self.save(silent=True)
    def save(self,silent=False):
        path=HERE/f'34401A_{"".join(c if c.isalnum() or c in "-_" else "_" for c in self.asset.get()) or "UNASSIGNED"}_checkpoint.json'
        path.write_text(json.dumps(dict(asset=self.asset.get(),serial=self.serial.get(),demo=self.demo,results=self.results),indent=2))
        if not silent:self.status.set(f'Saved {path.name}')
    def load(self):
        path=filedialog.askopenfilename(filetypes=[('Checkpoint','*.json')]);
        if not path:return
        data=json.loads(Path(path).read_text())
        if any(v.get('synthetic') for v in data.get('results',{}).values()) and not self.demo:
            if not messagebox.askyesno('Synthetic data','Checkpoint contains DEMO results. Load only for review (not a real calibration)?'):return
        self.asset.set(data.get('asset',''));self.serial.set(data.get('serial',''));self.results=data.get('results',{});self.refresh();self.status.set(f'Loaded progress: {len(self.results)} point(s) restored.')
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
        details=report_dialog.ask_details(self.root,'Agilent 34401A one-year verification')
        if details is None:return
        asset=''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path=filedialog.asksaveasfilename(defaultextension='.pdf',filetypes=[('PDF report','*.pdf')],initialfile=ui.report_filename(asset))
        if not path:return
        demo=self.demo or any(v.get('synthetic') for v in self.results.values())
        try:
            report_pdf.write_calibration_pdf(path,rows,header=[('Instrument','Agilent 34401A'),('Instrument ID',self.asset.get()),('Serial',self.serial.get()),('Source','Keysight 34401A Service Guide, Ch. 4 - one-year gain and zero-offset verification')],demo=demo,details=details,footer_note=report_pdf.uncertainty_note(rows))
        except ImportError:
            messagebox.showerror('PDF export dependency','Install the PDF package with:  py -m pip install reportlab');return
        except Exception as exc:
            messagebox.showerror('PDF export error',str(exc));return
        self.status.set(f'Exported {len(rows)} rows: {path}')
    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='34401A_verification.csv')
        if not path:return
        with open(path,'w',newline='',encoding='utf-8-sig') as file:
            writer=csv.writer(file);writer.writerow(['Instrument ID',self.asset.get(),'Serial Number',self.serial.get()]);writer.writerow(['SOURCE','34401A Service Guide Chapter 4, one-year gain and zero-offset verification; front/rear']);writer.writerow(['DEMO DATA','YES' if self.demo or any(v.get('synthetic') for v in self.results.values()) else 'NO']);writer.writerow([])
            writer.writerow(['Section','Description','Nominal','Tolerance -','Tolerance +','UOM','As Found','OOT','Status','Timestamp','Synthetic'])
            for p in POINTS:
                r=self.results.get(str(p['id']),{});n=p['nominal'];e=p['error']
                writer.writerow(['ZERO OFFSET '+p['terminal'] if p.get('zero_offset') else p['kind'],p['description'],n,n-e,n+e,p['unit'],r.get('reading',''),'OOT' if r.get('result')=='FAIL' else '',r.get('result',''),r.get('timestamp',''),r.get('synthetic','')])
        self.status.set(f'Exported {path}')
    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run','A point may be active. Stop and close?'):return
        self.stop=True;self._save_settings();self.disconnect();self.root.destroy()
if __name__=='__main__':
    import sys
    root=tk.Tk();App(root,demo='--demo' in sys.argv);root.mainloop()
