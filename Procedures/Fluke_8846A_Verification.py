"""8846A 1-year gain verification. RS-232 DMM + Fluke 5560A.
Hardware I/O is OFF in demo mode. Never run unattended: wiring confirmations required.
Source: Fluke 8845A/8846A Calibration Manual, Tables 3-4 and 3-18 (1-year).
"""
import json, math, sys, threading, time, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # shared ui_theme.py sits next to the Manager
import ui_theme as ui
import ui_shell
import appdata
import datamode
import procmods_engine
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

class IO(procmods_engine.ProcModsMixin):
    """Bench I/O for this procedure: the DMM and the Fluke 5560A, both through the instrument drivers."""
    def __init__(self, dmm_port, fluke_port, baud, parity, bits, mods=None):
        self.log=drivers.CommandLog()
        self.dmm=drivers.Fluke8846A(drivers.open_visa(f'ASRL{dmm_port}::INSTR',timeout=20,baud=baud,data_bits=bits,
            parity=parity.lower(),stop_bits=1,write_termination='\n',read_termination='\n'),self.log,label='8846A')
        self.fluke=drivers.Fluke5560A(drivers.open_visa(f'ASRL{fluke_port}::INSTR',timeout=20,baud=9600,
            write_termination='\n',read_termination='\n'),self.log,label='5560A')
        try:
            self.fluke.open(verify_model=False)
            self.fluke.write('STBY')
            self.dmm.connect()
            self.pm_attach(mods,*self.pm_drivers())
        except Exception:
            self.close();raise
        self.ident=self.dmm.idn
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
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt."""
        try:
            folder=Path.home()/'.calibration_suite';folder.mkdir(parents=True,exist_ok=True)
            with open(folder/'command_log.txt','a',encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  8846A session\n'+'\n'.join(self.log.lines())+'\n')
        except OSError:pass
    def measure(self,p):
        k=p['kind'];v=p['nominal'];r=p['range'];f=p['frequency']
        self.standby()
        if p.get('zero_offset'):
            # Zero-offset verification requires a physical copper short or OPEN current
            # input. The 5560A must remain in STBY and is never used as a zero source.
            self.dmm.configure(k,r)
            time.sleep(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('f8846a.settle.zero',1.5))
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
        time.sleep(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('f8846a.settle.ac',3.5) if k.startswith('AC') else self.pm_param('f8846a.settle.default',2))
        reading=self.dmm.read()
        self.standby()
        return reading

class App(datamode.DataModeMixin, procmods_engine.ProcModsMixin):
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
        self.pm_init('f8846a','8846A',demo=demo,lists=[POINTS],shape='band')   # procedure modifications: saved overrides for this model
        ui.apply_theme(root)
        root.title('Fluke 8846A | Performance Verification v58'+(' [DEMO]' if demo else ''))
        ui.fit_window(root, 1280, 800, min_w=900, min_h=620)
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
        for b in (self.btn_run,self.btn_section,self.btn_rerun,self.btn_test,self.btn_load,self.btn_refresh_ports,*self.mode_buttons):b.configure(state=idle)
        self.btn_stop.configure(state='normal' if self._busy else 'disabled')
        for c in (self.dmm_combo,self.fluke_combo):c.configure(state='disabled' if self._busy else 'normal')

    def _build_ui(self):
        root=self.root
        sh=self.shell=ui_shell.Shell(root,'Fluke 8846A  -  Performance Verification','1-year verification  |  Fluke 8845A/8846A Calibration Manual, Appendix A, Table A-2',
                                     demo=self.demo,on_section=self.pick_section,version='v58')
        self.status=sh.status_var
        self.conn_pill=sh.add_chip('Not connected','neutral')
        sh.build_identity(self.asset,self.serial)
        self.build_mode_segment(sh.strip,notice_holder=sh.notice_holder)
        self.summary=sh.build_progress()
        if self.demo:sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.','warn',title='Demo mode')
        else:sh.notice('The program pauses and asks you to confirm the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.','info')

        # connections live in the slide-in drawer
        conn=sh.drawer_body
        ttk.Label(conn,text='8846A port').grid(row=0,column=0,sticky='w',pady=4)
        self.dmm_combo=ttk.Combobox(conn,textvariable=self.dmm_port,width=10,state='normal')
        self.dmm_combo.grid(row=0,column=1,sticky='w',padx=(10,0),pady=4)
        ttk.Label(conn,text='Fluke 5560A port').grid(row=1,column=0,sticky='w',pady=4)
        self.fluke_combo=ttk.Combobox(conn,textvariable=self.fluke_port,width=10,state='normal')
        self.fluke_combo.grid(row=1,column=1,sticky='w',padx=(10,0),pady=4)
        for r,(text,var,values) in enumerate((('Baud',self.baud,['9600','4800','2400','1200','600','300']),('Parity',self.parity,['Even','Odd','None']),('Data bits',self.bits,['7','8'])),start=2):
            ttk.Label(conn,text=text).grid(row=r,column=0,sticky='w',pady=4)
            ttk.Combobox(conn,textvariable=var,values=values,width=10,state='readonly').grid(row=r,column=1,sticky='w',padx=(10,0),pady=4)
        btns = sh.drawer_footer
        self.btn_refresh_ports=ttk.Button(btns,text='Refresh ports',command=self.refresh_ports)
        self.btn_refresh_ports.pack(side='left',padx=(0,8))
        self.btn_test=ttk.Button(btns,text='Test connections',command=self.test_connections,style='Accent.TButton')
        self.btn_test.pack(side='left')
        ttk.Label(conn,text='Match the meter RS-232 settings and SCPI language.',style='Muted.TLabel',wraplength=ui.px(340),justify='left').grid(row=6,column=0,columnspan=2,sticky='w',pady=(12,0))

        # action bar
        self.btn_run=sh.add_action('▶  Run All Pending',self.run_all,accent=True,short='▶  Run')
        self.btn_section=sh.add_action('Run Shown Section',self.run_section,short='Section')
        self.btn_rerun=sh.add_action('Rerun Selected',self.rerun,short='Rerun')
        self.btn_stop=sh.add_action('■  Stop',self.request_stop,danger=True,short='■ Stop',state='disabled')
        sh.add_action('Export Report (PDF)',self.export_pdf,side='right',short='PDF')
        sh.add_action('Export Excel (.xlsx)',self.export_excel,side='right',short='Excel')
        self.btn_load=sh.add_action('Load progress',self.load,side='right',short='Load')
        sh.add_action('Save progress',self.save,side='right',short='Save')

        # table
        body=sh.content
        info=ttk.Frame(body);info.pack(side='bottom',fill='x',pady=(8,0))
        ttk.Label(info,textvariable=self.detail,wraplength=900,justify='left',style='Muted.TLabel').pack(anchor='w',fill='x')
        ttk.Label(info,text='Optional DC-ratio, rear-terminal and split-lead tests need a separate setup and are not included. AC, frequency and capacitance points are guided review only.',style='Small.TLabel').pack(anchor='w',pady=(4,0))
        filt=ttk.Frame(body);filt.pack(side='top',fill='x',pady=(0,6))
        ttk.Label(filt,text='Test points',style='Bold.TLabel').pack(side='left')
        c2=ttk.Combobox(filt,textvariable=self.show_status,values=datamode.STATUS_FILTERS,width=14,state='readonly');c2.pack(side='right')
        ttk.Label(filt,text='Show',style='Muted.TLabel').pack(side='right',padx=(0,6))
        c2.bind('<<ComboboxSelected>>',lambda _e:self.refresh())
        sections=[]
        for p in POINTS:
            s=self._section(p)
            if s not in sections:sections.append(s)
        self._section_names=sections
        self.tree=ui_shell.results_table(self,body)
        ui_shell.small_window(self,self.tree,filt)
        self.tree.bind('<<TreeviewSelect>>',self.on_select)
        self._update_sections()
        ui.polish(root)

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
        self.update_shell_progress(POINTS)
        if hasattr(self,'_section_names'):self._update_sections()

    def on_select(self,_event=None):
        sel=self.tree.selection()
        if not sel:return
        p=POINTS[int(sel[0])-1]
        setup=('Zero offset: select the '+p['terminal']+' terminals and fit the short (open for current) - the 5560A stays in STANDBY.'
               if p.get('zero_offset') else self.SETUP_TEXT.get(p['wiring'],p['wiring']))
        _v,_r,_u=ui.si_row([p["low"],p["high"]],p['unit'])
        self.detail.set(f'{p["description"]}   |   Range {ui.si(p["range"],p["unit"])}\nAcceptable reading: {_v[0]} to {_v[1]} {_u}     |     Setup: {setup}')

    def test_connections(self):
        if self.demo:messagebox.showinfo('Demo mode','Demo mode uses no hardware, so there is nothing to connect.');return
        self.status.set('Connecting ...');self.root.update_idletasks()
        try:
            self.disconnect();self.io=IO(self.parse_com(self.dmm_port.get()),self.parse_com(self.fluke_port.get()),
                                        int(self.baud.get()),self.parity.get(),int(self.bits.get()),mods=self.pm_state)
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
    def run_section(self):self.run_shown_section(POINTS)
    def rerun(self):
        selected=self.tree.selection()
        if selected:self.execute([POINTS[int(selected[0])-1]])
        else:messagebox.showinfo('Selection','Select a test point first.')
    def execute(self,points):
        if not self.confirm_found_overwrite(points):return
        if self.busy or not points:return
        if not self.asset.get().strip():messagebox.showwarning('Instrument ID','Enter an instrument ID.');return
        points=self.pm_begin_run(points,self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points:self.status.set('Every selected point is skipped by a procedure modification.');return
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
                msg={'VOLTAGE':'Connect 5560A voltage output to 8846A HI/LO voltage terminals. Verify safe leads and ranges.',
                     'CURRENT':'Put calibrator in STANDBY. Move leads to 8846A CURRENT input and LO. Check fuses and current ratings.',
                     'RESISTANCE_2W':'Put calibrator in STANDBY. Connect 2-wire resistance leads. 2-wire limits include the manual 0.2 ohm allowance; verify zero/null handling.',
                     'RESISTANCE_4W':'Put calibrator in STANDBY. Connect 4-wire force and sense leads to the correct DMM and calibrator terminals.',
                     'CAPACITANCE':'Put calibrator in STANDBY. Connect capacitance fixture; verify OPEN compensation and meter setup per manual.'}[p['wiring']]
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
        result='PASS' if p['low']<=reading<=p['high'] else 'FAIL'
        self.results[str(p['id'])]=dict(reading=reading,result=result,synthetic=synthetic,timestamp=datetime.now().isoformat(timespec='seconds'),data=self.mode_label,**self.pm_result_fields())
        self._update_row(p);self.save(silent=True)
    def save(self,silent=False):
        path=appdata.progress_path(f'8846A_{"".join(c if c.isalnum() or c in "-_" else "_" for c in self.asset.get()) or "UNASSIGNED"}_checkpoint.json')
        path.write_text(json.dumps(dict(asset=self.asset.get(),serial=self.serial.get(),demo=self.demo,**self.save_fields(),**self.pm_checkpoint_fields()),indent=2))
        if not silent:self.status.set(f'Saved {path.name}')
    def load(self):
        path=filedialog.askopenfilename(filetypes=[('Checkpoint','*.json')]);
        if not path:return
        data=json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not messagebox.askyesno('Synthetic data','Checkpoint contains DEMO results. Load only for review (not a real calibration)?'):return
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
        if not rows:messagebox.showinfo('No results','No recorded results to export yet.');return
        try:import report_pdf,report_dialog
        except ImportError as exc:messagebox.showerror('Report export',str(exc));return
        details=report_dialog.ask_details(self.root,'Fluke 8846A one-year verification')
        if details is None:return
        asset=''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path=filedialog.asksaveasfilename(defaultextension='.pdf',filetypes=[('PDF report','*.pdf')],initialfile=ui.report_filename(asset))
        if not path:return
        demo=self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows=report_pdf.apply_tar_tur(rows,details.get('show_tar_tur'),[tartur_wiring.point_fields(p,'5560A') for p in pts])
            report_pdf.write_calibration_pdf(path,rows,header=[('Instrument','Fluke 8846A'),('Instrument ID',self.asset.get()),('Serial',self.serial.get()),('Source','Fluke 8845A/8846A Calibration Manual, Appendix A Table A-2 - 1-year verification')],demo=demo,details=details,footer_note=report_pdf.uncertainty_note(rows,'5560A'))
        except ImportError:
            messagebox.showerror('PDF export dependency','Install the PDF package with:  py -m pip install reportlab');return
        except Exception as exc:
            messagebox.showerror('PDF export error',str(exc));return
        self.status.set(f'Exported {len(rows)} rows: {path}')
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
            messagebox.showerror('Excel export failed',str(exc));return
        self.status.set(f'Professional Excel report exported: {path}')
    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run','A point may be active. Stop and close?'):return
        self.stop=True;self._save_settings();self.disconnect();self.root.destroy()
if __name__=='__main__':
    import sys
    root=tk.Tk();App(root,demo='--demo' in sys.argv);root.mainloop()
