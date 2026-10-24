"""34401A one-year verification (Agilent 34401A): the Tk window code (layout, button states, results table, window chrome).

Moved out of Agilent_34401A.py unchanged (the bodies are the engine's former `_build_ui` / `_sync_buttons`; only the table and port-box helpers below are new, each the exact
statements the engine used to make on `self.tree` / `self.dmm_combo` / `self.fluke_combo`).  The engine reaches this module through `ui_port.ui.view('a34401a_view')`, which resolves
to `a34401a_view_tk` under Tk; a Qt port provides `a34401a_view_qt` with the same functions.  Every function takes the engine's App as `self` and keeps its widgets as attributes of it
(`self.tree`, `self.btn_run`, ... the shared mixins use them too).  The engine module (`E`) is found through the App's class, because the launcher may run as __main__.
Nothing here decides anything about a calibration.
"""
import sys
import tkinter as tk
from tkinter import ttk

import datamode
import ui_shell
import ui_theme as ui
import virtualbench


def setup_window(self):
    """Theme, title and size of the main window (statements of the engine's former App.__init__)."""
    root, demo = self.root, self.demo
    ui.apply_theme(root)
    root.title('Agilent 34401A | Performance Verification v54'+(' [DEMO]' if demo else ''))
    ui.fit_window(root, 1280, 800, min_w=900, min_h=620)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's former App.__init__)."""
    import labregistry
    labregistry.attach(self.root,self.asset,self.serial, self.status.set)


def sync_buttons(self):
    idle='disabled' if self._busy else 'normal'
    for b in (self.btn_run,self.btn_section,self.btn_rerun,self.btn_test,self.btn_load,self.btn_refresh_ports,*self.mode_buttons):b.configure(state=idle)
    self.btn_stop.configure(state='normal' if self._busy else 'disabled')
    for c in (self.dmm_combo,self.fluke_combo):c.configure(state='disabled' if self._busy else 'normal')


def build_ui(self):
    E = sys.modules[type(self).__module__]                      # the engine's own module (it may run as __main__, so it is not imported by name)
    POINTS = E.POINTS
    root=self.root
    sh=self.shell=ui_shell.Shell(root,'Agilent 34401A  -  Performance Verification','One-year gain and zero-offset verification  |  Keysight 34401A Service Guide, Ch. 4, pp. 67-71',
                                 demo=self.demo,on_section=self.pick_section,version='v54',virtual=self.virtual)
    self.status=sh.status_var
    self.conn_pill=sh.add_chip(self.chip_text() if self.demo else 'Not connected','neutral')
    sh.build_identity(self.asset,self.serial)
    self.build_mode_segment(sh.strip,notice_holder=sh.notice_holder)
    self.summary=sh.build_progress()
    if self.demo:sh.notice(self.banner_text(),'warn',title=virtualbench.BANNER_TITLE)
    else:sh.notice('The program pauses and asks you to confirm the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.','info')

    conn=sh.drawer_body
    ttk.Label(conn,text='34401A port').grid(row=0,column=0,sticky='w',pady=4)
    self.dmm_combo=ttk.Combobox(conn,textvariable=self.dmm_port,width=10,state='normal')
    self.dmm_combo.grid(row=0,column=1,sticky='w',padx=(10,0),pady=4)
    ttk.Label(conn,text='Fluke 5560A port').grid(row=1,column=0,sticky='w',pady=4)
    self.fluke_combo=ttk.Combobox(conn,textvariable=self.fluke_port,width=10,state='normal')
    self.fluke_combo.grid(row=1,column=1,sticky='w',padx=(10,0),pady=4)
    for r,(text,var,values) in enumerate((('Baud',self.baud,['9600','4800','2400','1200','600','300']),('Parity',self.parity,['Even','Odd','None']),('Data bits',self.bits,['7','8'])),start=2):
        ttk.Label(conn,text=text).grid(row=r,column=0,sticky='w',pady=4)
        ttk.Combobox(conn,textvariable=var,values=values,width=10,state='readonly').grid(row=r,column=1,sticky='w',padx=(10,0),pady=4)
    ttk.Label(conn,text='Match the DMM front-panel RS-232 settings (2 stop bits).',style='Muted.TLabel',wraplength=ui.px(340),justify='left').grid(row=5,column=0,columnspan=2,sticky='w',pady=(12,0))
    btns=sh.drawer_footer
    self.btn_refresh_ports=ttk.Button(btns,text='Refresh ports',command=self.refresh_ports)
    self.btn_refresh_ports.pack(side='left',padx=(0,8))
    self.btn_test=ttk.Button(btns,text='Test connections',command=self.test_connections,style='Accent.TButton')
    self.btn_test.pack(side='left')

    self.btn_run=sh.add_action('▶  Run All Pending',self.run_all,accent=True,short='▶  Run')
    self.btn_section=sh.add_action('Run Shown Section',self.run_section,short='Section')
    self.btn_rerun=sh.add_action('Rerun Selected',self.rerun,short='Rerun')
    self.btn_stop=sh.add_action('■  Stop',self.request_stop,danger=True,short='■ Stop',state='disabled')
    sh.add_action('Export Report (PDF)',self.export_pdf,side='right',short='PDF')
    self.btn_load=sh.add_action('Load progress',self.load,side='right',short='Load')
    sh.add_action('Save progress',self.save,side='right',short='Save')
    self.pm_live_attach(sh)   # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well, usable during a run

    body=sh.content
    info=ttk.Frame(body);info.pack(side='bottom',fill='x',pady=(8,0))
    ttk.Label(info,textvariable=self.detail,wraplength=900,justify='left',style='Muted.TLabel').pack(anchor='w',fill='x')
    ttk.Label(info,text='Zero offsets are verified on BOTH the FRONT and REAR terminals. Optional AC tests are not included.',style='Small.TLabel').pack(anchor='w',pady=(4,0))
    filt=ttk.Frame(body);filt.pack(side='top',fill='x',pady=(0,6))
    ttk.Label(filt,text='Test points',style='Bold.TLabel').pack(side='left')
    c2=ttk.Combobox(filt,textvariable=self.show_status,values=datamode.STATUS_FILTERS,width=14,state='readonly');c2.pack(side='right')
    ttk.Label(filt,text='Show',style='Muted.TLabel').pack(side='right',padx=(0,6))
    c2.bind('<<ComboboxSelected>>',lambda _e:self.refresh())
    self.tree=ui_shell.results_table(self,body)
    ui_shell.small_window(self,self.tree,filt)
    self.tree.bind('<<TreeviewSelect>>',self.on_select)
    self.update_shell_sections(POINTS,self._section)
    ui.polish(root)


# ---- results table and address boxes: the exact statements the engine used to make on self.tree / self.dmm_entry / self.cal_entry
def table_selection(self):
    return self.tree.selection()


def table_has(self, iid):
    return self.tree.exists(iid)


def table_select(self, iid, see=False):
    self.tree.selection_set(iid)
    if see:
        self.tree.see(iid)


def table_set_rows(self, rows, keep):
    """rows: iterable of (iid, values, tags); keep: the selection before the refresh (the first row of it is selected again if it is still there)."""
    self.tree.delete(*self.tree.get_children())
    for iid, values, tags in rows:
        self.tree.insert('', 'end', iid=iid, values=values, tags=tags)
    if keep and self.tree.exists(keep[0]): self.tree.selection_set(keep[0])


def table_update_row(self, iid, values, tags):
    self.tree.item(iid, values=values, tags=tags)


def set_choices(self, which, values):
    """The drop-down values of the DMM port ('dmm') or Fluke port ('fluke') box."""
    (self.dmm_combo if which == 'dmm' else self.fluke_combo)['values'] = values
