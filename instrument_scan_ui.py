"""The 'Find instruments' window (the rules and the scan are in instrument_scan.py; this is only Tk wiring).

    instrument_scan_ui.open_find_instruments(parent)          the Manager tool: scan, look at the results, copy a resource string, Remember
    instrument_scan_ui.ask_resource(parent, model=None)       the same window as a chooser: returns the resource the technician accepted, or ''

The window sends read-only identity queries only (see instrument_scan.py), never connects an instrument for use, and remembers a result only when the
technician presses 'Accept and remember'.  The scan runs in a worker thread: the window stays alive, shows progress and has a Cancel button.
RS-232 ports are listed but only checked when the technician names the instrument type for the port.
"""
import tkinter as tk
from tkinter import ttk

import instrument_scan as S
import ui_theme as ui

INTRO = ('Asks each GPIB, USB and LAN instrument who it is, with read-only identity queries (*IDN? and, on GPIB, ID? for the 3458A). Nothing is changed on the '
         'instruments and nothing is connected for use. Serial (RS-232) ports are listed but are not asked unless you pick the instrument type for a port below.')


class FindInstrumentsWindow:
    def __init__(self, parent, memory=None, scanner_factory=None, serial_checker=None, serial_ports=None, model=None, choose=False):
        self.parent = parent
        self.memory = memory if memory is not None else S.ResourceMemory()
        self.scanner_factory = scanner_factory or (lambda probe_all, go_local: S.Scanner(probe_all_gpib=probe_all, go_local=go_local, preferred=self._preferred()))
        self.serial_checker = serial_checker or S.serial_hit
        self.serial_ports_source = serial_ports or S.system_serial_ports
        self.model, self.choose = model, choose
        self.result = ''
        self.job = None
        self.report = None
        self.rows = {}
        self.extra_hits = []                                  # serial checks asked for by hand
        self._serial_job = None

        self.win = win = ui.dialog(parent, 'Find instruments', modal=choose)
        self._size(win, 1120, 700, 760, 520)
        body = ttk.Frame(win, padding=16)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Find instruments', style='Header.TLabel').pack(anchor='w')
        ui.Notice(body, INTRO, 'info').pack(fill='x', pady=(8, 10))

        bar = ttk.Frame(body)
        bar.pack(fill='x')
        self.btn_scan = ttk.Button(bar, text='Scan instruments', style='Accent.TButton', command=self.start_scan)
        self.btn_scan.pack(side='left')
        self.btn_cancel = ttk.Button(bar, text='Cancel', command=self.cancel_scan, state='disabled')
        self.btn_cancel.pack(side='left', padx=(8, 12))
        self.progress = ttk.Progressbar(bar, mode='determinate', length=ui.px(220))
        self.progress.pack(side='left')
        self.progress_text = tk.StringVar(value='')
        ttk.Label(bar, textvariable=self.progress_text, style='Muted.TLabel').pack(side='left', padx=10)

        opts = ttk.Frame(body)
        opts.pack(fill='x', pady=(8, 0))
        self.probe_all = tk.BooleanVar(value=False)
        self.go_local = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text='Ask every GPIB address 0-30 (for adapters that do not list their instruments)', variable=self.probe_all).pack(side='left')
        ttk.Checkbutton(opts, text='Send GTL (back to front panel) afterwards', variable=self.go_local).pack(side='left', padx=(18, 0))

        self.backend = tk.StringVar(value='')
        ttk.Label(body, textvariable=self.backend, style='Small.TLabel', wraplength=ui.px(900), justify='left').pack(anchor='w', pady=(8, 4))

        self.problem_var = tk.StringVar(value='')
        self.problem = ui.Notice(body, textvariable=self.problem_var, kind='warn')          # shown (packed) only when there is something to say
        self.problem_shown = False

        cols = ('resource', 'idn', 'model', 'serial', 'state')
        self.table = ui.make_table(body, cols, ('Resource', 'Instrument (its own reply)', 'Model key', 'Serial', 'Status'), (290, 330, 90, 110, 230),
                                   anchors={c: 'w' for c in cols}, height=8, selectmode='extended', hscroll=True, pack=False)
        self.empty = ttk.Label(self.table.master, text='Press "Scan instruments".', style='Muted.TLabel')
        self.empty.place(relx=0.5, rely=0.45, anchor='center')
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.selection_changed())

        self.detail = tk.StringVar(value='')
        self.detail_label = ttk.Label(body, textvariable=self.detail, style='Small.TLabel', wraplength=ui.px(900), justify='left')

        actions = ttk.Frame(body)
        self.btn_copy = ttk.Button(actions, text='Copy resource', command=self.copy_resource, state='disabled')
        self.btn_copy.pack(side='left')
        self.btn_remember = ttk.Button(actions, text='Accept and remember', style='Accent.TButton', command=self.remember_selected, state='disabled')
        self.btn_remember.pack(side='left', padx=8)
        self.btn_forget = ttk.Button(actions, text='Forget', command=self.forget_selected, state='disabled')
        self.btn_forget.pack(side='left')
        if choose:
            self.btn_use = ttk.Button(actions, text='Use this resource', style='Accent.TButton', command=self.use_selected, state='disabled')
            self.btn_use.pack(side='right')

        serial = ttk.LabelFrame(body, text='Serial (RS-232) ports: never asked automatically', padding=10)
        row = ttk.Frame(serial)
        row.pack(fill='x')
        ttk.Label(row, text='Port').pack(side='left')
        self.port = tk.StringVar()
        self.port_box = ttk.Combobox(row, textvariable=self.port, width=24, values=[], state='normal')
        self.port_box.pack(side='left', padx=(6, 14))
        ttk.Label(row, text='Instrument type').pack(side='left')
        self.family = tk.StringVar()
        choices = S.serial_family_choices()
        self.family_labels = {f'{k}  {lab}': k for k, lab in choices}
        self.family_box = ttk.Combobox(row, textvariable=self.family, width=44, values=list(self.family_labels), state='readonly')
        self.family_box.pack(side='left', padx=(6, 14))
        self.btn_serial = ttk.Button(row, text='Check this port', command=self.check_port)
        self.btn_serial.pack(side='left')
        ttk.Label(serial, text='The check uses that instrument driver\'s own identity code and sends nothing else. Pick the type of the instrument you connected to the port.',
                  style='Small.TLabel', wraplength=ui.px(900), justify='left').pack(anchor='w', pady=(6, 0))
        self.refresh_ports()

        foot = ttk.Frame(body)
        self.serial_frame = serial
        self.log_visible = False
        self.btn_log = ttk.Button(foot, text='Show what was sent', command=self.toggle_log)
        self.btn_log.pack(side='left')
        ttk.Button(foot, text='Close', command=self.close).pack(side='right')
        self.status = tk.StringVar(value='')
        ttk.Label(foot, textvariable=self.status, style='Muted.TLabel').pack(side='left', padx=12)
        self.log_text = tk.Text(body, height=6, wrap='none', background=ui.C['field'], foreground=ui.C['text'], relief='flat',
                                highlightthickness=1, highlightbackground=ui.C['border'], font='TkFixedFont')
        # bottom parts first, so a short window squeezes the table and never the buttons
        foot.pack(side='bottom', fill='x')
        serial.pack(side='bottom', fill='x', pady=(0, 8))
        actions.pack(side='bottom', fill='x', pady=(2, 8))
        self.detail_label.pack(side='bottom', anchor='w', pady=(6, 4))
        self.table.master.pack(fill='both', expand=True)
        win.protocol('WM_DELETE_WINDOW', self.close)
        ui.center_on(win, parent)

    @staticmethod
    def _size(win, width, height, min_w, min_h):
        """Like ui.fit_window (96-dpi units, kept on screen, centred) but without its delayed callback: a window closed within 0.4 s must leave nothing pending."""
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = min(ui.px(width), sw - ui.px(60)), min(ui.px(height), sh - ui.px(110))
        win.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}')
        win.minsize(min(ui.px(min_w), w), min(ui.px(min_h), h))

    def show_problem(self, text):
        self.problem_var.set(text)
        if text and not self.problem_shown:
            self.problem.pack(fill='x', pady=(0, 6), before=self.table.master)
            self.problem_shown = True
        elif not text and self.problem_shown:
            self.problem.pack_forget()
            self.problem_shown = False

    # ------------------------------------------------------------------------------------------------ scan
    def _preferred(self):
        """A remembered resource is asked with its family's own query first (a remembered 3458A with ID?, so no *IDN? is sent to it)."""
        out = {}
        try:
            for r in self.memory.remembered():
                fam = S.FAMILY.get(r.model)
                if fam is not None and fam.probe != '*IDN?':
                    out[r.resource] = fam.probe
        except Exception:
            pass
        return out

    def start_scan(self):
        if self.job is not None and not self.job.finished and not self.job.abandoned:
            return
        self.clear_results()
        self.show_problem('')
        self.backend.set('')
        self.btn_scan.configure(state='disabled')
        self.btn_cancel.configure(state='normal')
        self.progress.configure(value=0, maximum=1)
        self.progress_text.set('Listing the VISA resources ...')
        self.status.set('')
        try:
            scanner = self.scanner_factory(self.probe_all.get(), self.go_local.get())
        except Exception as exc:
            self.scan_failed(str(exc))
            return
        self.job = S.ScanJob(scanner).start()
        self.win.after(100, self.poll)

    def poll(self):
        job = self.job
        if job is None or job.abandoned or not self._alive():
            return
        for kind, payload in job.poll():
            if kind == 'progress':
                i, n, msg = payload
                self.progress.configure(maximum=max(1, n), value=i)
                self.progress_text.set(f'{msg}  ({i}/{n})' if n else msg)
            elif kind == 'done':
                self.scan_done(payload)
                return
            elif kind == 'error':
                self.scan_failed(payload)
                return
        self.win.after(100, self.poll)

    def cancel_scan(self):
        if self.job is not None:
            self.job.cancel()
        self.btn_scan.configure(state='normal')
        self.btn_cancel.configure(state='disabled')
        self.progress_text.set('Cancelled.')
        self.status.set('Scan cancelled. A query already sent is allowed to finish; its answer is ignored.')

    def scan_failed(self, text):
        self.btn_scan.configure(state='normal')
        self.btn_cancel.configure(state='disabled')
        self.progress_text.set('')
        self.backend.set('')
        self.show_problem(text)
        self.empty.configure(text='The scan could not run.')
        self.status.set('The scan could not run.')

    def scan_done(self, report):
        self.report = report
        self.btn_scan.configure(state='normal')
        self.btn_cancel.configure(state='disabled')
        self.progress.configure(value=self.progress['maximum'])
        self.progress_text.set('Cancelled.' if report.cancelled else 'Done.')
        info = f'{report.backend}' + (f' ({report.backend_path})' if report.backend_path else '')
        notes = [f'Serial ports listed, not asked: {", ".join(report.serial_ports)}.'] if report.serial_ports else []
        self.backend.set('  '.join([info + '.'] + notes))
        self.show_problem(' '.join(report.warnings))
        self.show_rows()
        ports = self.refresh_ports(extra=report.serial_ports)
        n = len(report.identified())
        self.status.set(f'{n} instrument{"" if n == 1 else "s"} identified; {report.probed} resource{"" if report.probed == 1 else "s"} asked'
                        + (f'; {report.empty_gpib} empty GPIB address(es) skipped' if report.empty_gpib else '') + '.')
        if not ports and not report.hits:
            self.status.set(self.status.get() + ' Nothing found: check the cable, the adapter software and the instrument\'s GPIB address.')

    # ------------------------------------------------------------------------------------------------ results
    def clear_results(self):
        for k in self.table.get_children():
            self.table.delete(k)
        self.rows.clear()
        self.extra_hits.clear()
        self.report = None
        self.detail.set('')
        self.empty.configure(text='Press "Scan instruments".')
        self.empty.place(relx=0.5, rely=0.45, anchor='center')
        self.selection_changed()

    def show_rows(self):
        keep = {id(h) for h in self.selected_hits()}                 # the table is rebuilt (status column): the selection stays
        for k in self.table.get_children():
            self.table.delete(k)
        self.rows.clear()
        hits = (self.report.hits if self.report else []) + self.extra_hits
        for values, tag, hit in S.result_rows(hits, self.memory):
            iid = self.table.insert('', 'end', values=values, tags=(tag,))
            self.rows[iid] = hit
            if id(hit) in keep:
                self.table.selection_add(iid)
        if self.rows:
            self.empty.place_forget()
        else:
            self.empty.configure(text='No instrument answered.')
            self.empty.place(relx=0.5, rely=0.45, anchor='center')
        self.selection_changed()

    def selected_hits(self):
        return [self.rows[i] for i in self.table.selection() if i in self.rows]

    def selection_changed(self):
        hits = self.selected_hits()
        ident = [h for h in hits if h.status == 'identified' and not h.alias_of]
        self.btn_copy.configure(state='normal' if len(hits) == 1 else 'disabled')
        self.btn_remember.configure(state='normal' if ident else 'disabled')
        self.btn_forget.configure(state='normal' if any(self.memory.status_of(h).startswith('remembered') for h in ident) else 'disabled')
        if getattr(self, 'btn_use', None) is not None:
            self.btn_use.configure(state='normal' if len(ident) == 1 and len(hits) == 1 else 'disabled')
        if len(hits) == 1:
            h = hits[0]
            text = f'{h.resource}: {h.idn or h.error or h.status}'
            if h.needs_serial:
                text += '   Another instrument of this model was found: choose by serial number.'
            if h.status == 'identified' and not h.serial:
                text += '   (This model does not report a serial number.)'
            self.detail.set(text)
        else:
            self.detail.set('')

    def copy_resource(self):
        hits = self.selected_hits()
        if len(hits) != 1:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(hits[0].resource)
        self.status.set(f'Copied {hits[0].resource}')

    def remember_selected(self):
        done = []
        for h in self.selected_hits():
            if h.status == 'identified' and not h.alias_of:
                try:
                    self.memory.remember(h)
                    done.append(h.resource)
                except Exception as exc:
                    self.status.set(f'Could not save: {exc}')
                    return
        self.show_rows()
        self.status.set('Remembered ' + ', '.join(done) + ' for this workstation. It is checked again before it is offered.' if done else 'Nothing to remember.')

    def forget_selected(self):
        for h in self.selected_hits():
            if h.status == 'identified':
                self.memory.forget(h.key, h.serial)
        self.show_rows()
        self.status.set('Forgotten.')

    def use_selected(self):
        hits = [h for h in self.selected_hits() if h.status == 'identified' and not h.alias_of]
        if len(hits) == 1:
            self.result = hits[0].resource
            self.remember_selected()
            self.close()

    # ------------------------------------------------------------------------------------------------ serial
    def refresh_ports(self, extra=()):
        ports = []
        for p in list(extra) + list(self.serial_ports_source()):
            if p not in ports:
                ports.append(p)
        self.port_box.configure(values=ports)
        return ports

    def check_port(self):
        port, label = self.port.get().strip(), self.family.get()
        if not port or not label:
            self.status.set('Pick the port and the type of instrument connected to it first.')
            return
        key = self.family_labels.get(label)
        if '::' not in port:
            port = (S.serial_resource_names([port]) or [port])[0]
        self.btn_serial.configure(state='disabled')
        self.status.set(f'Asking {port} as a {key} ...')
        import queue
        import threading
        q = queue.Queue()

        def run():
            try:
                q.put(self.serial_checker(port, key))
            except Exception as exc:
                q.put(S.Hit(port, 'ASRL', 'error', error=str(exc)))
        threading.Thread(target=run, daemon=True, name='serial-check').start()

        def wait():
            if not self._alive():
                return
            try:
                hit = q.get_nowait()
            except queue.Empty:
                self.win.after(100, wait)
                return
            self.btn_serial.configure(state='normal')
            self.extra_hits = [h for h in self.extra_hits if h.resource != hit.resource] + [hit]
            self.show_rows()
            self.status.set(f'{port}: {hit.idn}' if hit.idn else f'{port}: {S.state_text(hit)}')
        self.win.after(100, wait)

    # ------------------------------------------------------------------------------------------------ the log
    def toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_text.configure(state='normal')
            self.log_text.delete('1.0', 'end')
            lines = [f'{d}  {name:34s} {text}' for d, name, text in (self.report.log if self.report else [])] or ['(nothing sent yet)']
            self.log_text.insert('1.0', '\n'.join(lines))
            self.log_text.configure(state='disabled')
            self.log_text.pack(side='bottom', fill='x', pady=(8, 0), before=self.serial_frame)
            self.btn_log.configure(text='Hide what was sent')
        else:
            self.log_text.pack_forget()
            self.btn_log.configure(text='Show what was sent')

    # ------------------------------------------------------------------------------------------------ window
    def _alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def close(self):
        if self.job is not None and not self.job.finished:
            self.job.cancel()
        try:
            self.win.destroy()
        except tk.TclError:
            pass


def open_find_instruments(parent, **kw):
    """The Manager's tool window (not modal, so a resource can be copied into a procedure window beside it)."""
    return FindInstrumentsWindow(parent, **kw)


def ask_resource(parent, model=None, **kw):
    """The same window as a chooser; returns the accepted resource, '' when closed without choosing."""
    w = FindInstrumentsWindow(parent, model=model, choose=True, **kw)
    parent.wait_window(w.win)
    return w.result
