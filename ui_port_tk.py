"""TkUiPort: the Tk implementation of ui_port.UiPort.  The ONLY module of the port that imports tkinter.

Everything here is the code the engines used to carry, moved and not redesigned: each method makes exactly the call the engine made (same function, same
arguments), looked up at call time through the module (`messagebox.askyesno`, `ui_theme.confirm_steps`, ...) so the test harnesses that patch those functions
keep working.  Arguments the caller did not give are not passed.  `parent` is passed to a message box only when given (Tk uses the default root otherwise, as before).
"""
from __future__ import annotations

import importlib
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk


def _kw(**kw):
    return {k: v for k, v in kw.items() if v is not None}


class TkUiPort:
    """See ui_port.py for the contract."""

    # ---- messages and questions -----------------------------------------------------------------------------------------------------------
    def message(self, kind, title, text, *, parent=None):
        fn = {'info': messagebox.showinfo, 'warning': messagebox.showwarning, 'error': messagebox.showerror}[kind]
        fn(title, text, **_kw(parent=parent))

    def ask_yes_no(self, title, text, *, icon=None, default=None, parent=None):
        return messagebox.askyesno(title, text, **_kw(icon=icon, default=default, parent=parent))

    def ask_ok_cancel(self, title, text, *, icon=None, parent=None):
        return messagebox.askokcancel(title, text, **_kw(icon=icon, parent=parent))

    def ask_retry_cancel(self, title, text, *, icon=None, parent=None):
        return messagebox.askretrycancel(title, text, **_kw(icon=icon, parent=parent))

    def ask_yes_no_cancel(self, title, text, *, icon=None, parent=None):
        return messagebox.askyesnocancel(title, text, **_kw(icon=icon, parent=parent))

    def ask_text(self, title, prompt, *, initial=None, show=None, parent=None):
        return simpledialog.askstring(title, prompt, **_kw(initialvalue=initial, show=show, parent=parent))

    def ask_number(self, title, prompt, *, initial=None, minvalue=None, maxvalue=None, integer=False, parent=None):
        ask = simpledialog.askinteger if integer else simpledialog.askfloat
        return ask(title, prompt, **_kw(initialvalue=initial, minvalue=minvalue, maxvalue=maxvalue, parent=parent))

    def choose_file(self, *, parent=None, **opts):
        return filedialog.askopenfilename(**_kw(parent=parent, **opts))

    def save_file(self, *, parent=None, **opts):
        return filedialog.asksaveasfilename(**_kw(parent=parent, **opts))

    def choose_dir(self, *, parent=None, **opts):
        return filedialog.askdirectory(**_kw(parent=parent, **opts))

    def operator_prompt(self, title, heading, steps, *, parent=None, **opts):
        import ui_theme
        return ui_theme.confirm_steps(parent, title, heading, steps, **opts)

    def report_details(self, procedure='', *, parent=None):
        import report_dialog
        return report_dialog.ask_details(parent, procedure)

    # ---- threads and time -----------------------------------------------------------------------------------------------------------------
    def post(self, win, fn, *args):
        win.after(0, fn, *args)

    def after(self, win, ms, fn, *args):
        return win.after(ms, fn, *args)

    def call_from_worker(self, win, fn, *args):
        """The pattern of fgen_verification.ask_number_threadsafe: ask on the Tk thread, wait.  An exception in fn is reported by Tk on the UI thread (the
        worker gets None), exactly as before."""
        box, done = {}, threading.Event()

        def run():
            try:
                box['v'] = fn(*args)
            finally:
                done.set()
        win.after(0, run)
        done.wait()
        return box.get('v')

    # ---- window and variables -------------------------------------------------------------------------------------------------------------
    def run_app(self, factory):
        root = tk.Tk()
        factory(root)
        root.mainloop()

    def set_title(self, win, text):
        win.title(text)

    def on_close(self, win, fn):
        win.protocol('WM_DELETE_WINDOW', fn)

    def bind_key(self, win, sequence, fn):
        win.bind(sequence, lambda _e: fn())

    def close(self, win):
        win.destroy()

    def flush(self, win):
        win.update_idletasks()

    def var(self, value='', kind='str'):
        cls = {'str': tk.StringVar, 'bool': tk.BooleanVar, 'int': tk.IntVar, 'float': tk.DoubleVar}[kind]
        return cls(value=value)

    def surprise_handler(self, win):
        import surprise
        return surprise.tk_handler(win)

    def view(self, name):
        return importlib.import_module(f'{name}_tk')

    # ==== APPEND-ONLY BLOCK, WP-H (handheld): the reading windows and the progress window ===============================================
    # The windows are the code the engine carried, moved: handheld_dmm_view_tk (reading, IR problem, dial) and run_queue_ui (run-queue reading window, progress).
    def ask_reading(self, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                    limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, *, parent=None):
        return self.view('handheld_dmm_view').ask_reading(parent, p, total, out_text, out_note, accept, mode, question, unit, annunciator, validate, phase,
                                                          limit_s, on_expire, device, source, demo_fill)

    def ask_readings(self, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None, device='METER',
                     source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading='', *, parent=None):
        import run_queue_ui
        return run_queue_ui.ask_readings(parent, p, total, out_text, out_note, accept, meters, unit, judge, limit_s, on_expire, device, source, demo_fill,
                                         tol_text, phase, heading)

    def ask_range(self, p, total, dial, standby_text, *, parent=None):
        return self.view('handheld_dmm_view').ask_range(parent, p, total, dial, standby_text)

    def ask_ir_problem(self, p, total, problems, shown, *, parent=None):
        return self.view('handheld_dmm_view').ask_ir_problem(parent, p, total, problems, shown)

    def progress_window(self, win, title='Queue progress', on_show=None, on_export=None):
        import run_queue_ui
        return run_queue_ui.QueueProgress(win, **_kw(title=title if title != 'Queue progress' else None, on_show=on_show, on_export=on_export))

    # ---- APPENDED BY WP-A (adjustment launchers; append-only block) -----------------------------------------------------------------------
    def ask_value(self, title, prompt, default, *, parent=None):
        """The value-entry window of Keithley_2000_Adjustment / Fluke_8808A_Adjustment (their former App.ask_value), moved unchanged; `parent` was self.root."""
        import ui_theme as ui
        win = ui.dialog(parent, title)
        var, result = tk.StringVar(value=default), {'v': None}
        frame = ttk.Frame(win, padding=16)
        frame.pack()
        ttk.Label(frame, text=prompt, wraplength=ui.px(460), justify='left').pack(anchor='w')
        ent = ttk.Entry(frame, textvariable=var, width=24)
        ent.pack(anchor='w', pady=(10, 0))
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=(14, 0))

        def done(ok):
            result['v'] = var.get() if ok else None
            win.destroy()
        ttk.Button(row, text='Use this value', style='Accent.TButton', command=lambda: done(True)).pack(side='right')
        ttk.Button(row, text='Cancel', command=lambda: done(False)).pack(side='right', padx=(0, 8))
        win.bind('<Return>', lambda _e: done(True))
        ui.center_on(win, parent)
        ent.focus_set()
        ent.select_range(0, 'end')
        win.wait_window()
        return result['v']

    def update(self, win):
        win.update()

    def enable_hidpi(self):
        import ui_theme
        ui_theme.enable_hidpi()
