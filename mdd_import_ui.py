"""Import preview for a Mudcats / Cal Processor .MDD datasheet as a MANUAL calibration procedure (opened from the Manager).

    mdd_import_ui.open_preview(root, path, on_created=callback, status=string_var)

Nothing is created until 'Create manual procedure' is pressed.  The window lists every MDD test point with what became of it (converted, converted but
uncertain, NOT converted and why), the counts, and - when the same file was imported before, or a procedure of that name exists - asks whether to make a
separate new copy or a new version of the existing one (nothing is ever overwritten silently).  The logic is in mdd_convert.py (Tk-free, tested headless)."""
from __future__ import annotations

import getpass
import tkinter as tk
from tkinter import messagebox, ttk

import mdd_convert as mc
import ui_theme as ui
from mdd_importer_v49 import parse_mdd

STATUS_TEXT = {'ok': 'Converted', 'uncertain': 'CHECK', 'skipped': 'NOT converted'}
STATUS_TAG = {'skipped': 'fail', 'uncertain': 'error'}
INTRO = ('The datasheet is imported as a MANUAL calibration: the technician types each reading straight into the test point grid. Nominals and limits are '
         'exactly as printed in the MDD; ranges are not in an MDD, so none is shown. The original .MDD is kept as an archive copy; its embedded commands '
         'and scripts are never run.')


def who():
    try:
        return getpass.getuser()
    except Exception:
        return ''


def open_preview(root, path, on_created=None, status=None, registry=None, spec_root=None, archive_to=None):
    """Parse `path` and open the preview.  Returns the window (None when the file cannot be read; the reason is shown)."""
    try:
        parsed = parse_mdd(path)
        conv = mc.convert(parsed)
    except (OSError, ValueError) as exc:
        messagebox.showerror('Cannot import datasheet', str(exc), parent=root)
        return None
    return Preview(root, parsed, conv, on_created, status, registry, spec_root, archive_to).win


class Preview:
    def __init__(self, root, parsed, conv, on_created, status, registry=None, spec_root=None, archive_to=None):
        self.root, self.parsed, self.conv = root, parsed, conv
        self.on_created, self.status = on_created, status
        self.registry, self.spec_root, self.archive_to = registry, spec_root, archive_to
        h = conv.source['header']
        self.make = tk.StringVar(value=conv.sheet.make)
        self.model = tk.StringVar(value=conv.sheet.model)
        self.title = tk.StringVar(value=conv.sheet.title)
        self.choice = tk.StringVar(value='new')
        self.std = None                                    # mdd_convert.StandardChoice of the current conversion (the 'Standard for the uncertainty' box)
        self.std_var = tk.StringVar(value='')
        win = self.win = ui.dialog(root, 'Import Mudcats datasheet as a manual calibration - review before creating')
        ui.fit_window(win, 1180, 760, min_w=820, min_h=520)
        self.bar = ttk.Frame(win, padding=12)
        self.bar.pack(side='bottom', fill='x')
        ttk.Button(self.bar, text='Cancel', command=win.destroy).pack(side='right')
        self.create_btn = ttk.Button(self.bar, text='Create manual procedure', style='Accent.TButton', command=self.create)
        self.create_btn.pack(side='right', padx=8)
        head = ttk.Frame(win, padding=(16, 14, 16, 4))
        head.pack(fill='x')
        self.heading = ttk.Label(head, text='', style='Header.TLabel')
        self.heading.pack(side='left')
        self.pills = ttk.Frame(head)
        self.pills.pack(side='right')
        ttk.Label(win, text=f"Source: {conv.source['filename'] or '-'}   |   Procedure: {h['Procedure_Name'] or '-'}   |   Interval: {h['CalInterval'] or '-'}",
                  style='Muted.TLabel').pack(anchor='w', padx=16)
        ui.Notice(win, INTRO, 'info').pack(fill='x', padx=16, pady=(8, 6))
        names = ttk.Frame(win, padding=(16, 0))
        names.pack(fill='x')
        for label, var, width in (('Make', self.make, 18), ('Model', self.model, 18), ('Title', self.title, 46)):
            ttk.Label(names, text=label).pack(side='left')
            e = ttk.Entry(names, textvariable=var, width=width)
            e.pack(side='left', padx=(6, 14))
            e.bind('<Return>', lambda _e: self.rebuild())
        ttk.Button(names, text='Update preview', style='Quiet.TButton', command=self.rebuild).pack(side='left')
        stdf = ttk.Frame(win, padding=(16, 6, 16, 0))
        stdf.pack(fill='x')
        ttk.Label(stdf, text='Standard for the uncertainty').pack(side='left')
        self.std_box = ttk.Combobox(stdf, textvariable=self.std_var, state='readonly', width=52)
        self.std_box.pack(side='left', padx=(6, 14))
        self.std_box.bind('<<ComboboxSelected>>', lambda _e: self.show_uncertainty())
        self.std_text = ttk.Label(win, text='', style='Muted.TLabel', wraplength=1100, justify='left')
        self.std_text.pack(anchor='w', padx=16, pady=(2, 0))
        self.existing = ttk.Frame(win, padding=(16, 6, 16, 0))
        self.existing.pack(fill='x')
        self.issue_text = tk.StringVar()
        self.issue_notice = None
        body = ttk.Frame(win, padding=(16, 6))
        body.pack(fill='both', expand=True)
        cols = ('no', 'section', 'nominal', 'unit', 'low', 'high', 'status', 'unc', 'note')
        self.grid = ui.make_table(body, cols, ('No.', 'Section', 'Nominal (as printed)', 'Unit', 'Low', 'High', 'Result', 'Uncertainty', 'Why / note'),
                                  (50, 170, 230, 70, 80, 80, 110, 150, 360), zebra=True, hscroll=True,
                                  anchors={'section': 'w', 'nominal': 'w', 'unc': 'w', 'status': 'w', 'note': 'w'}, stretch={'note': True, 'no': False})
        self.fill()

    # ---- content -----------------------------------------------------------------------------------------------------------------
    def fill(self):
        c = self.conv
        self.heading.configure(text=f'{self.make.get().strip()}  {self.model.get().strip()}  -  {self.title.get().strip()}')
        for w in self.pills.winfo_children():
            w.destroy()
        ui.Pill(self.pills, f'{c.sections} section(s)', 'info').pack(side='left', padx=3)
        ui.Pill(self.pills, f'{c.converted} of {c.total} points converted', 'good' if not c.skipped else 'info').pack(side='left', padx=3)
        if c.uncertain:
            ui.Pill(self.pills, f'{c.uncertain} to check', 'warn').pack(side='left', padx=3)
        if c.skipped:
            ui.Pill(self.pills, f'{c.skipped} NOT converted', 'bad').pack(side='left', padx=3)
        if self.std is None or self.std.sheet is not c.sheet:                 # a new conversion: the choices are worked out again, the person's choice is kept when it still exists
            prior = self.std.model_of(self.std_var.get()) if self.std is not None else None
            self.std = mc.StandardChoice(c.sheet)
            self.std_box.configure(values=self.std.labels)
            self.std_var.set(self.std.label_of(prior if prior in self.std.models else self.std.default))
        self.show_uncertainty()
        for w in self.existing.winfo_children():
            w.destroy()
        found = mc.find_existing(c, self.registry, self.spec_root)
        self.found = found
        self.choice.set('new')
        if found:
            e = found[0]
            why = ('This exact .MDD file was imported before as' if e.reason == 'same_file' else 'A procedure with this name already exists:')
            ui.Notice(self.existing, f'{why} "{e.title}" ({e.uid}, {e.versions} saved version(s)). Nothing is overwritten: choose what to do.', 'warn').pack(fill='x')
            ttk.Radiobutton(self.existing, text='Create a separate new procedure (default)', variable=self.choice, value='new').pack(anchor='w', pady=(4, 0))
            ttk.Radiobutton(self.existing, text=f'Save as a NEW VERSION of "{e.title}" (earlier versions are kept)', variable=self.choice,
                            value='version').pack(anchor='w')
        gen = [i for i in c.issues if i.point == 0]
        if gen:
            ui.Notice(self.existing, '  '.join(i.message for i in gen), 'warn').pack(fill='x', pady=(4, 0))
        self.create_btn.configure(state='normal')

    def selected_standard(self):
        """The model chosen in 'Standard for the uncertainty' ('' = None: waive)."""
        return self.std.model_of(self.std_var.get()) if self.std is not None else mc.STANDARD_NONE

    def show_uncertainty(self):
        """The table's Uncertainty column and the sentence under the box for the chosen standard (nothing is saved)."""
        _plan, rows, text = self.std.preview(self.selected_standard())
        self.std_text.configure(text=text)
        self.grid.delete(*self.grid.get_children())
        for r in self.conv.rows:
            tag = STATUS_TAG.get(r['status'], 'even' if r['no'] % 2 else 'odd')
            self.grid.insert('', 'end', values=(r['no'], r['section'], r['nominal'], r['unit'], r['low'], r['high'], STATUS_TEXT[r['status']],
                                                rows.get(r['no'], '') if r['status'] != 'skipped' else '', r['message']), tags=(tag,))

    def rebuild(self):
        try:
            self.conv = mc.convert(self.parsed, make=self.make.get(), model=self.model.get(), title=self.title.get())
        except ValueError as exc:
            messagebox.showerror('Cannot convert', str(exc), parent=self.win)
            return
        self.fill()

    def create(self):
        choice = self.choice.get()
        if (self.make.get().strip(), self.model.get().strip(), self.title.get().strip()) != (self.conv.sheet.make, self.conv.sheet.model, self.conv.sheet.title):
            self.rebuild()
            if self.found and choice == 'version':
                self.choice.set('version')
        replace = self.found[0].uid if (self.found and self.choice.get() == 'version') else None
        res = mc.register(self.conv, self.parsed, who(), replace_uid=replace, registry=self.registry, root=self.spec_root, archive_to=self.archive_to,
                          standard=self.selected_standard())
        if not res.ok:
            messagebox.showerror('Import failed', res.message or 'The procedure could not be created.', parent=self.win)
            return
        self.win.destroy()
        msg = (f'Created the manual calibration "{self.conv.sheet.title}" (version {res.version}): {self.conv.converted} of {self.conv.total} test points. '
               f'{self.conv.skipped} not converted, {self.conv.uncertain} to check. {self.std.preview(self.selected_standard())[2]} It is listed under Manual Calibrations.')
        if self.status is not None:
            self.status.set(msg)
        if self.on_created:
            self.on_created(res)
        messagebox.showinfo('Datasheet import', msg, parent=self.root)
