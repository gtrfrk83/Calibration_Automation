"""Shared look-and-feel for the Calibration Suite (Tk / ttk, standard library only).

Put this one file next to Calibration_Procedure_Manager.py. Every procedure in the
Procedures folder finds it there automatically (or inside the Procedures folder).

Nothing in here talks to instruments or databases; it only draws windows.
"""
import json
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk

# ----------------------------------------------------------------------------- palette
LIGHT = dict(
    bg='#F5F5F7', card='#FFFFFF', bar='#EDEDF2', border='#D8D8DE', border_strong='#C7C7CC',
    text='#1D1D1F', muted='#6E6E73', faint='#A1A1A6',
    navy='#1D1D1F', navy_hi='#3A3A3C', accent_line='#007AFF',
    primary='#007AFF', primary_hi='#0A6EE6', primary_lo='#0058C0',
    select='#D2E4FF', row_alt='#FAFAFC', head='#FAFAFC', head_hi='#EFEFF4',
    good='#1F7A3A', good_bg='#E4F6E9', good_dot='#34C759',
    bad='#C4121F', bad_bg='#FFE9EA', bad_dot='#FF3B30',
    warn='#9A5B00', warn_bg='#FFF3DC', warn_dot='#FF9500',
    info='#0A5FD6', info_bg='#E5F0FF', info_dot='#007AFF',
    neutral='#55555A', neutral_bg='#E8E8ED', neutral_dot='#A1A1A6',
    field='#FFFFFF', table='#FFFFFF', on_primary='#FFFFFF', primary_off='#A9CFFF',
    btn=('#FFFFFF', '#D2D2D7'), btn_hi=('#F0F0F5', '#C7C7CC'), btn_lo=('#E3E3E8', '#BCBCC2'), btn_off=('#F5F5F7', '#E3E3E8'),
    danger='#FF3B30', danger_hi='#E0281D', danger_lo='#C21A10', danger_off='#FFB3AE',
    combo_btn='#EAEFF5', combo_btn_hi='#DCE5F0', trough='#E3E3E8', scroll='#D1D1D6', scroll_hi='#A1A1A6', scroll_lo='#8E8E93',
    tip='#3A3A3C', row_even='#FFFFFF',
    row_pass='#FFFFFF', row_pass_fg='#1D1D1F', row_fail='#FFFFFF', row_fail_fg='#B3261E', row_warn='#FFFFFF', row_warn_fg='#8A5A00',
)

# Flat warm-charcoal dark theme with one clay-orange accent, like claude.ai (the beta's default look).
DARK = dict(
    bg='#262624', card='#2B2A28', bar='#262624', border='#3B3A37', border_strong='#4A4945',
    text='#ECE9E1', muted='#A09D95', faint='#6F6D67',
    navy='#ECE9E1', navy_hi='#BFBCB4', accent_line='#D97757',
    primary='#D97757', primary_hi='#E58B6D', primary_lo='#C4633F',            # claude.ai's clay orange
    select='#3A2E29', row_alt='#2F2E2B', head='#262624', head_hi='#33322F',
    good='#6FCF9F', good_bg='#14302A', good_dot='#6FCF9F',
    bad='#E5736A', bad_bg='#3A1F1D', bad_dot='#E5736A',
    warn='#F2C14E', warn_bg='#2F2810', warn_dot='#F2C14E',
    info='#EBB9A3', info_bg='#3A2A22', info_dot='#D97757',
    neutral='#A09D95', neutral_bg='#33322F', neutral_dot='#6F6D67',
    field='#1F1E1D', table='#2B2A28', on_primary='#FFFFFF', primary_off='#5A3A2E',
    btn=('#2D2C2A', '#44433F'), btn_hi=('#363532', '#555450'), btn_lo=('#262624', '#555450'), btn_off=('#262624', '#33322F'),
    danger='#B5483B', danger_hi='#C9574A', danger_lo='#9A3C31', danger_off='#4A2522',
    combo_btn='#33322F', combo_btn_hi='#3B3A37', trough='#33322F', scroll='#555450', scroll_hi='#6F6D67', scroll_lo='#8A8780',
    tip='#44433F', row_even='#2B2A28',
    row_pass='#2B2A28', row_pass_fg='#ECE9E1', row_fail='#2B2A28', row_fail_fg='#E5736A', row_warn='#2B2A28', row_warn_fg='#F2C14E',
)
PALETTES = {'light': LIGHT, 'dark': DARK}
C = dict(LIGHT)                    # the live palette: modules read ui.C at use time; use_palette() changes it in place
THEME = 'light'


def theme_choice() -> str:
    """Which palette to use: CALSUITE_THEME, else the person's saved choice (Help > Appearance), else the edition's default."""
    import os
    name = os.environ.get('CALSUITE_THEME', '').strip().lower()
    if name not in PALETTES:
        try:
            name = str(Settings('appearance').get('theme', '')).lower()
        except Exception:
            name = ''
    if name not in PALETTES:
        try:
            import suite_info
            name = getattr(suite_info, 'DEFAULT_THEME', 'light')
        except ImportError:
            name = 'light'
    return name if name in PALETTES else 'light'


def use_palette(name: str):
    global THEME
    THEME = name if name in PALETTES else 'light'
    C.clear()
    C.update(PALETTES[THEME])


def is_dark() -> bool:
    return THEME == 'dark'


KINDS = ('good', 'bad', 'warn', 'info', 'neutral')

FAMILY = 'TkDefaultFont'
MONO = 'TkFixedFont'
SCALE = 1.0          # screen scale vs. 96 dpi (1.0, 1.25, 1.5 ...)


def px(n):
    """Scale a pixel size for high-DPI screens."""
    return int(round(n * SCALE))


def enable_hidpi():
    """Call BEFORE tk.Tk(): makes text crisp on scaled Windows displays."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ----------------------------------------------------------------------------- theme
def _pick(root, prefs, fallback):
    try:
        have = {f.lower(): f for f in tkfont.families(root)}
    except tk.TclError:
        return fallback
    for name in prefs:
        if name.lower() in have:
            return have[name.lower()]
    return fallback


_IMAGE_REFS = []
_FONT_REFS = []


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _rounded_image(root, r, fill, border, bg, bw=1):
    """9-slice rounded-rectangle PhotoImage, anti-aliased against the window colour."""
    size = 2 * r + 2
    f, b, g = _hex(fill), _hex(border), _hex(bg)
    half = size / 2.0
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            qx = abs(x + 0.5 - half) - (half - r)
            qy = abs(y + 0.5 - half) - (half - r)
            d = (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** 0.5 + min(max(qx, qy), 0) - r
            outer = min(1.0, max(0.0, 0.5 - d))
            inner = min(1.0, max(0.0, 0.5 - (d + bw)))
            col = [g[i] + (b[i] - g[i]) * outer for i in range(3)]
            col = [col[i] + (f[i] - col[i]) * inner for i in range(3)]
            row.append('#%02x%02x%02x' % tuple(int(round(v)) for v in col))
        rows.append('{' + ' '.join(row) + '}')
    img = tk.PhotoImage(master=root, width=size, height=size)
    img.put(' '.join(rows))
    _IMAGE_REFS.append(img)
    return img


def _dress(root):
    try:
        import branding
        branding.dress(root)
    except ImportError:
        pass


def apply_theme(root):
    """Style every ttk widget in the application. Call once, right after tk.Tk()."""
    global FAMILY, MONO, SCALE
    use_palette(theme_choice())
    style = ttk.Style(root)
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    if isinstance(root, tk.Tk):                         # main windows only: title pattern, icon, Help menu, friendly error window
        root.after(250, lambda: _dress(root))
    try:
        SCALE = max(1.0, float(root.winfo_fpixels('1i')) / 96.0)
    except tk.TclError:
        SCALE = 1.0
    FAMILY = _pick(root, ('Segoe UI', 'SF Pro Text', '.AppleSystemUIFont', 'Helvetica Neue', 'Segoe UI Variable Text',
                          'Inter', 'Noto Sans', 'DejaVu Sans', 'Arial'), 'TkDefaultFont')
    MONO = _pick(root, ('Cascadia Mono', 'Consolas', 'Menlo', 'DejaVu Sans Mono', 'Courier New'), 'TkFixedFont')
    base = 10
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkIconFont', 'TkCaptionFont',
                 'TkSmallCaptionFont', 'TkTooltipFont', 'TkHeadingFont'):
        try:
            tkfont.nametofont(name).configure(family=FAMILY, size=base)
        except tk.TclError:
            pass
    try:
        tkfont.nametofont('TkHeadingFont').configure(weight='bold')
        tkfont.nametofont('TkFixedFont').configure(family=MONO, size=base)
    except tk.TclError:
        pass

    def font(name, size, weight='normal', family=None):
        try:
            f = tkfont.nametofont(name)
            f.configure(family=family or FAMILY, size=size, weight=weight)
        except tk.TclError:
            f = tkfont.Font(root=root, name=name, family=family or FAMILY, size=size, weight=weight)
            _FONT_REFS.append(f)   # a Font object deletes its Tk font when garbage-collected
        return name

    f_title = font('CalTitle', 20, 'bold')
    f_h1 = font('CalH1', 16, 'bold')
    f_h2 = font('CalH2', 12, 'bold')
    f_bold = font('CalBold', base, 'bold')
    f_small = font('CalSmall', 9)
    f_smallb = font('CalSmallBold', 9, 'bold')
    f_big = font('CalBig', 22, 'bold')
    f_metric = font('CalMetric', 18, 'bold')
    f_mono = font('CalMono', base, 'normal', MONO)
    f_banner = font('CalBanner', 19, 'bold')

    root.configure(background=C['bg'])
    row_h = max(px(28), int(tkfont.nametofont('TkDefaultFont').metrics('linespace') * 2.1))

    s = style
    s.configure('.', background=C['bg'], foreground=C['text'], font='TkDefaultFont',
                bordercolor=C['border'], lightcolor=C['bg'], darkcolor=C['border'],
                troughcolor=C['bar'], focuscolor=C['primary'], selectbackground=C['select'],
                selectforeground=C['text'], insertcolor=C['text'])
    s.map('.', foreground=[('disabled', C['faint'])])

    # frames
    s.configure('TFrame', background=C['bg'])
    s.configure('Bar.TFrame', background=C['bar'])
    s.configure('Banner.TFrame', background=C['bg'])
    s.configure('TSeparator', background=C['border'])

    # labels
    s.configure('TLabel', background=C['bg'], foreground=C['text'])
    s.configure('Bar.TLabel', background=C['bar'], foreground=C['text'])
    s.configure('BarMuted.TLabel', background=C['bar'], foreground=C['muted'], font=f_small)
    s.configure('Title.TLabel', font=f_title, foreground=C['navy'])
    s.configure('Header.TLabel', font=f_h1, foreground=C['navy'])
    s.configure('Section.TLabel', font=f_h2, foreground=C['navy'])
    s.configure('Subtitle.TLabel', foreground=C['muted'])
    s.configure('Muted.TLabel', foreground=C['muted'])
    s.configure('Small.TLabel', foreground=C['muted'], font=f_small)
    s.configure('Bold.TLabel', font=f_bold)
    s.configure('Reading.TLabel', font=f_big, foreground=C['navy'])
    s.configure('Metric.TLabel', font=f_metric, foreground=C['navy'])
    s.configure('MetricCap.TLabel', font=f_smallb, foreground=C['muted'])
    s.configure('Mono.TLabel', font=f_mono)
    s.configure('BannerTitle.TLabel', background=C['bg'], foreground=C['text'], font=f_banner)
    s.configure('BannerSub.TLabel', background=C['bg'], foreground=C['muted'])
    for kind in KINDS:
        s.configure(f'Pill{kind.title()}.TLabel', background=C[kind + '_bg'], foreground=C[kind],
                    font=f_smallb, padding=(10, 3))
        s.configure(f'Notice{kind.title()}.TLabel', background=C[kind + '_bg'], foreground=C['text'])
        s.configure(f'Notice{kind.title()}.TFrame', background=C[kind + '_bg'])
        s.configure(f'Dot{kind.title()}.TLabel', background=C['bar'], foreground=C[kind + '_dot'])

    # buttons - rounded, macOS-style (drawn as small images so the corners are really round)
    radius = px(7)
    def round_button(name, states, fg, disabled_fg, quiet=False):
        """states: dict(normal, hover, pressed, disabled) -> (fill, border)."""
        imgs = {k: _rounded_image(root, radius, fill, border, C['bg']) for k, (fill, border) in states.items()}
        elem = 'Mac' + name.replace('.', '')
        try:
            s.element_create(elem, 'image', imgs['normal'], ('disabled', imgs['disabled']),
                             ('pressed', imgs['pressed']), ('active', imgs['hover']),
                             border=(radius, radius, radius, radius), sticky='nsew')
        except tk.TclError:
            pass
        s.layout(name, [(elem, {'sticky': 'nswe', 'children': [
            ('Button.padding', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})]})])
        s.configure(name, padding=(px(16), px(5)), foreground=fg, anchor='center', relief='flat', borderwidth=0)
        s.map(name, foreground=[('disabled', disabled_fg)])
    plain = dict(normal=C['btn'], hover=C['btn_hi'], pressed=C['btn_lo'], disabled=C['btn_off'])
    round_button('TButton', plain, C['text'], C['faint'])
    round_button('Compact.TButton', plain, C['text'], C['faint'])
    s.configure('Compact.TButton', padding=(px(10), px(2)), font=f_small)         # small file-action buttons (Save / Load / Export)
    round_button('Accent.TButton', dict(normal=(C['primary'], C['primary']), hover=(C['primary_hi'], C['primary_hi']),
                                        pressed=(C['primary_lo'], C['primary_lo']), disabled=(C['primary_off'], C['primary_off'])),
                 C['on_primary'], C['on_primary'])
    round_button('Danger.TButton', dict(normal=(C['danger'],) * 2, hover=(C['danger_hi'],) * 2,
                                        pressed=(C['danger_lo'],) * 2, disabled=(C['danger_off'],) * 2),
                 '#FFFFFF', '#FFFFFF')
    s.configure('Quiet.TButton', padding=(8, 5), relief='flat', borderwidth=0, background=C['bg'],
                foreground=C['primary'], focuscolor=C['bg'], lightcolor=C['bg'], darkcolor=C['bg'], bordercolor=C['bg'])
    s.map('Quiet.TButton', background=[('active', C['head_hi']), ('pressed', C['bar'])],
          lightcolor=[('active', C['head_hi'])], darkcolor=[('active', C['head_hi'])])

    # inputs
    for name in ('TEntry', 'TSpinbox'):
        s.configure(name, padding=(6, 5), fieldbackground=C['field'], foreground=C['text'],
                    bordercolor=C['border_strong'], lightcolor=C['border_strong'], darkcolor=C['border_strong'])
        s.map(name, bordercolor=[('focus', C['primary'])], lightcolor=[('focus', C['primary'])],
              darkcolor=[('focus', C['primary'])], fieldbackground=[('disabled', C['bar']), ('readonly', C['bar'])])
    s.configure('TCombobox', padding=(6, 5), fieldbackground=C['field'], foreground=C['text'], arrowcolor=C['muted'],
                background=C['combo_btn'], bordercolor=C['border_strong'], lightcolor=C['border_strong'],
                darkcolor=C['border_strong'], arrowsize=px(14))
    s.map('TCombobox', fieldbackground=[('disabled', C['bar']), ('readonly', C['field'])],
          selectbackground=[('readonly', C['field'])], selectforeground=[('readonly', C['text'])],
          bordercolor=[('focus', C['primary'])], lightcolor=[('focus', C['primary'])],
          darkcolor=[('focus', C['primary'])], background=[('active', C['combo_btn_hi'])])
    root.option_add('*TCombobox*Listbox.font', 'TkDefaultFont')
    root.option_add('*TCombobox*Listbox.background', C['field'])
    root.option_add('*TCombobox*Listbox.foreground', C['text'])
    root.option_add('*TCombobox*Listbox.selectBackground', C['select'])
    root.option_add('*TCombobox*Listbox.selectForeground', C['text'])
    root.option_add('*Listbox.font', 'TkDefaultFont')

    for name in ('TCheckbutton', 'TRadiobutton'):
        s.configure(name, background=C['bg'], padding=(2, 3))
        s.map(name, background=[('active', C['bg'])],
              indicatorcolor=[('selected', C['primary']), ('pressed', C['primary_lo']), ('!selected', C['field'])])

    # containers
    s.configure('TLabelframe', background=C['bg'], bordercolor=C['border'], lightcolor=C['border'],
                darkcolor=C['border'], relief='solid', borderwidth=1)
    s.configure('TLabelframe.Label', background=C['bg'], foreground=C['navy'], font=f_bold)
    s.configure('TNotebook', background=C['bg'], borderwidth=0, tabmargins=(12, 8, 12, 0),
                bordercolor=C['border'], lightcolor=C['bg'], darkcolor=C['bg'])
    s.configure('TNotebook.Tab', padding=(22, 10), background=C['bar'], foreground=C['muted'],
                bordercolor=C['border'], lightcolor=C['bar'], darkcolor=C['bar'], font='CalBold')
    s.map('TNotebook.Tab', background=[('selected', C['primary']), ('active', C['head_hi'])],
          foreground=[('selected', C['on_primary'])], lightcolor=[('selected', C['primary'])],
          darkcolor=[('selected', C['primary'])], expand=[('selected', (0, 0, 0, 0))])
    s.configure('TPanedwindow', background=C['bar'])

    # progress + scrollbars (slim, no arrow buttons - like macOS)
    s.configure('Horizontal.TProgressbar', troughcolor=C['trough'], background=C['primary'],
                bordercolor=C['trough'], lightcolor=C['primary'], darkcolor=C['primary'], thickness=px(8))
    s.configure('Good.Horizontal.TProgressbar', troughcolor=C['trough'], background=C['good_dot'],
                bordercolor=C['trough'], lightcolor=C['good_dot'], darkcolor=C['good_dot'], thickness=px(8))
    for orient, sticky in (('Vertical', 'ns'), ('Horizontal', 'ew')):
        s.layout(f'{orient}.TScrollbar', [(f'{orient}.Scrollbar.trough', {'sticky': sticky, 'children': [
            (f'{orient}.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})]})])
        s.configure(f'{orient}.TScrollbar', background=C['scroll'], troughcolor=C['card'], bordercolor=C['card'],
                    lightcolor=C['scroll'], darkcolor=C['scroll'], relief='flat', width=px(11), gripcount=0)
        s.map(f'{orient}.TScrollbar', background=[('active', C['scroll_hi']), ('pressed', C['scroll_lo'])],
              lightcolor=[('active', C['scroll_hi'])], darkcolor=[('active', C['scroll_hi'])])

    # tables
    s.configure('Treeview', background=C['table'], fieldbackground=C['table'], foreground=C['text'],
                rowheight=row_h, borderwidth=0, relief='flat', bordercolor=C['border'],
                lightcolor=C['table'], darkcolor=C['table'])
    s.configure('Treeview.Heading', background=C['head'], foreground=C['muted'], font=f_bold,
                relief='flat', padding=(8, 8), bordercolor=C['border'], lightcolor=C['head'], darkcolor=C['head'])
    s.map('Treeview.Heading', background=[('active', C['head_hi'])])
    # Tk 8.6.9 ignores row tag colours unless the stock '!disabled !selected' map entries are removed.
    def fixed(option):
        return [e for e in s.map('Treeview', query_opt=option) if e[:2] != ('!disabled', '!selected')]
    try:
        s.map('Treeview', foreground=fixed('foreground'), background=fixed('background'))
    except (tk.TclError, TypeError):
        pass
    s.map('Treeview', background=[('selected', C['select'])], foreground=[('selected', C['text'])])
    return style


# ----------------------------------------------------------------------------- small helpers
def style_result_tags(tree, zebra=False):
    """Standard row colours: pass / fail / error(warn) / pending, optional zebra stripes."""
    tree.tag_configure('pass', background=C['row_pass'], foreground=C['row_pass_fg'])
    tree.tag_configure('fail', background=C['row_fail'], foreground=C['row_fail_fg'])
    tree.tag_configure('error', background=C['row_warn'], foreground=C['row_warn_fg'])
    tree.tag_configure('pending', foreground=C['muted'])
    tree.tag_configure('next', background=C['info_bg'], foreground=C['info'])
    if zebra:
        tree.tag_configure('even', background=C['row_even'])
        tree.tag_configure('odd', background=C['row_alt'])


def make_table(parent, columns, headings, widths, anchors=None, height=10, selectmode='browse',
               zebra=False, hscroll=False, stretch=None, pack=True):
    """Treeview + scrollbars in one tidy frame. Returns the Treeview (frame is tree.master)."""
    holder = ttk.Frame(parent)
    holder.rowconfigure(0, weight=1)
    holder.columnconfigure(0, weight=1)
    tree = ttk.Treeview(holder, columns=columns, show='headings', selectmode=selectmode, height=height)
    anchors = anchors or {}
    stretch = stretch or {}
    for col, head, width in zip(columns, headings, widths):
        tree.heading(col, text=head)
        tree.column(col, width=px(width), minwidth=px(40), anchor=anchors.get(col, 'center'),
                    stretch=stretch.get(col, True))
    tree._cal_scaled = True
    y = ttk.Scrollbar(holder, orient='vertical', command=tree.yview)

    def _yset(lo, hi):          # like macOS: the scrollbar only appears when there is more to scroll
        y.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            y.grid_remove()
        else:
            y.grid()
    tree.configure(yscrollcommand=_yset)
    tree.grid(row=0, column=0, sticky='nsew')
    y.grid(row=0, column=1, sticky='ns')
    if hscroll:
        x = ttk.Scrollbar(holder, orient='horizontal', command=tree.xview)
        tree.configure(xscrollcommand=x.set)
        x.grid(row=1, column=0, sticky='ew')
    style_result_tags(tree, zebra)
    if pack:
        holder.pack(fill='both', expand=True)
    return tree


def fit_window(win, width, height, min_w=800, min_h=500):
    """Size a window in 96-dpi units, keep it on screen, and centre it."""
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w = min(px(width), sw - px(60))
    h = min(px(height), sh - px(110))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 3)
    win.geometry(f'{w}x{h}+{x}+{y}')
    win.minsize(min(px(min_w), w), min(px(min_h), h))
    win.after(400, lambda: keep_table_rows(win))


def _all_widgets(widget):
    for w in widget.winfo_children():
        yield w
        yield from _all_widgets(w)


def keep_table_rows(win, rows=5):
    """Stop the window shrinking so far that the results table is squeezed away: the minimum height leaves room for `rows` table rows."""
    try:
        win.update_idletasks()
        trees = [w for w in _all_widgets(win) if isinstance(w, ttk.Treeview)]
        if not trees:
            return
        tree = max(trees, key=lambda t: int(t.cget('height')))
        shown = int(tree.cget('height'))
        if shown <= rows:
            return
        row_h = tree.winfo_reqheight() / (shown + 1)             # the +1 is the heading line
        need = int(win.winfo_reqheight() - (shown - rows) * row_h)
        need = min(need, win.winfo_screenheight() - px(110))
        min_w, min_h = win.minsize()
        if need > min_h:
            win.minsize(min_w, need)
    except tk.TclError:
        pass


def center_on(win, parent):
    win.update_idletasks()
    try:
        x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f'+{max(0, x)}+{max(0, y)}')
    except tk.TclError:
        pass


def dialog(parent, title, modal=True):
    """A themed, centred, Esc-closable popup window."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(background=C['bg'])
    win.transient(parent)
    win.bind('<Escape>', lambda _e: win.destroy())
    if modal:
        win.after(10, lambda: _safe_grab(win))
    return win


def confirm_steps(parent, title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None):
    """Technician-friendly confirmation: heading, key facts, numbered steps, optional caution and picture.

    steps   - list of strings, or (bold lead, detail) tuples
    facts   - list of (label, value) shown in a compact card, e.g. [('Channel', 'CH1')]
    image   - optional path to a PNG hook-up diagram, shown beside the text
    Returns True when the OK button is pressed (Enter), False for Cancel / Esc / closing."""
    win = dialog(parent, title)
    result = {'ok': False}
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(px(22), px(18), px(22), px(16)))
    outer.pack(fill='both', expand=True)
    photo = None
    if image:
        try:
            photo = tk.PhotoImage(master=win, file=str(image))
        except tk.TclError:
            photo = None
    if photo is not None:
        main = ttk.Frame(outer)
        main.pack(fill='both', expand=True)
        pic = tk.Label(main, image=photo, background='#FFFFFF', borderwidth=1, relief='solid')
        pic.image = photo
        pic.pack(side='left', anchor='n', padx=(0, px(20)))
        host = ttk.Frame(main)
        host.pack(side='left', fill='both', expand=True, anchor='n')
        wrap = 400
    else:
        host, wrap = outer, 480
    ttk.Label(host, text=heading, style='Section.TLabel', wraplength=px(wrap + 40), justify='left').pack(anchor='w')
    if facts:
        card = tk.Frame(host, background=C['bar'], highlightthickness=1, highlightbackground=C['border'])
        card.pack(fill='x', pady=(10, 0))
        inner = tk.Frame(card, background=C['bar'])
        inner.pack(fill='x', padx=px(12), pady=px(8))
        for i, (label, value) in enumerate(facts):
            tk.Label(inner, text=label, background=C['bar'], foreground=C['muted'], anchor='w').grid(
                row=i, column=0, sticky='w', padx=(0, px(18)), pady=1)
            tk.Label(inner, text=value, background=C['bar'], foreground=C['text'], anchor='w',
                     font='CalBold', wraplength=px(wrap - 90), justify='left').grid(row=i, column=1, sticky='w', pady=1)
    ttk.Label(host, text='Before you continue', style='Muted.TLabel').pack(anchor='w', pady=(14, 4))
    for n, step in enumerate(steps, 1):
        row = tk.Frame(host, background=C['bg'])
        row.pack(fill='x', pady=3)
        tk.Label(row, text=str(n), width=2, background=C['primary'], foreground='#FFFFFF',
                 font='CalBold').pack(side='left', anchor='n', padx=(0, px(10)))
        lead, detail = step if isinstance(step, (tuple, list)) else ('', step)
        box = tk.Frame(row, background=C['bg'])
        box.pack(side='left', fill='x', expand=True)
        if lead:
            tk.Label(box, text=lead, background=C['bg'], foreground=C['text'], font='CalBold',
                     anchor='w', justify='left', wraplength=px(wrap)).pack(anchor='w')
        if detail:
            tk.Label(box, text=detail, background=C['bg'], foreground=C['text'] if not lead else C['muted'],
                     anchor='w', justify='left', wraplength=px(wrap)).pack(anchor='w')
    if caution:
        note = Notice(host, text=caution, kind='warn', title='Caution')
        note.pack(fill='x', pady=(12, 0))
    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(16, 0))

    def finish(value):
        result['ok'] = value
        win.destroy()
    okb = ttk.Button(bar, text=ok, style='Accent.TButton', command=lambda: finish(True))
    okb.pack(side='right')
    ttk.Button(bar, text=cancel, command=lambda: finish(False)).pack(side='right', padx=(0, 8))
    win.bind('<Return>', lambda _e: finish(True))
    win.protocol('WM_DELETE_WINDOW', lambda: finish(False))
    center_on(win, parent.winfo_toplevel())
    okb.focus_set()
    win.wait_window()
    return result['ok']


def _safe_grab(win):
    try:
        win.grab_set()
    except tk.TclError:
        pass


_SI_STEPS = ((1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, '\u00b5'), (1e-9, 'n'), (1e-12, 'p'))


def si_scale(ref, unit=''):
    """Pick the SI prefix for a reference magnitude. Returns (divisor, unit_text) e.g. (1e-3, 'mV')."""
    sym = {'ohm': '\u03a9'}.get(unit, unit)
    try:
        a = abs(float(ref))
    except (TypeError, ValueError):
        return 1.0, sym
    if a == 0:
        return 1.0, sym
    for scale, prefix in _SI_STEPS:
        if a >= scale * 0.9999999:
            return scale, prefix + sym
    return 1e-12, 'p' + sym


def _decimals_needed(x, sig=7):
    t = f'{x:.{sig}g}'
    if 'e' in t.lower():
        t = f'{float(t):.12f}'.rstrip('0')
    return len(t.split('.')[1]) if '.' in t else 0


def si_one(value, unit='', sig=4):
    """Single value -> (number_text, unit_text) with `sig` significant digits, e.g. 0.00037 V -> ('370.0', '\u00b5V')."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '', {'ohm': '\u03a9'}.get(unit, unit)
    scale, unit_text = si_scale(v, unit)
    x = v / scale
    if x == 0:
        return '0', unit_text
    import math
    dec = max(0, sig - 1 - int(math.floor(math.log10(abs(x)))))
    return f'{x:.{dec}f}', unit_text


def si_row(values, unit='', readings=(), extra=2, ref=None, max_decimals=9):
    """Format one row of related values (nominal, limits ...) with a shared prefix and resolution.

    Returns (value_texts, reading_texts, unit_text). Display only - callers keep base-unit numbers.
    Limits use just enough decimals to show every value exactly (so 0.006 V -> '6' mV, 5.947 mV
    stays '5.947'); readings get `extra` more decimals so small deviations remain visible."""
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            nums.append(None)
    good = [n for n in nums if n is not None]
    if ref is None:
        ref = max((abs(n) for n in good), default=0)
    scale, unit_text = si_scale(ref, unit)
    dec = max((_decimals_needed(n / scale) for n in good), default=0)
    dec = min(dec, max_decimals)

    def fmt(n, d):
        if n is None:
            return ''
        t = f'{n / scale:.{d}f}'
        return '0' if float(t) == 0 and d == 0 else ('0' if t.lstrip('-0.') == '' else t)

    vals = [fmt(n, dec) for n in nums]
    reads = []
    for r in readings:
        try:
            reads.append(fmt(float(r), min(dec + extra, max_decimals + extra)))
        except (TypeError, ValueError):
            reads.append('')
    return vals, reads, unit_text


def si(value, unit=''):
    """12500 -> '12.5 k' + unit; 0.0001 -> '100 \u00b5' + unit. Ohm shows as the omega sign."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    sym = {'ohm': '\u03a9'}.get(unit, unit)
    if v == 0:
        return f'0 {sym}'.strip()
    a = abs(v)
    for scale, prefix in ((1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, '\u00b5'),
                          (1e-9, 'n'), (1e-12, 'p')):
        if a >= scale * 0.9999999:
            return f'{v / scale:.6g} {prefix}{sym}'.strip()
    return f'{v:.3g} {sym}'.strip()


def fmt_num(value, digits=9):
    try:
        return f'{float(value):.{digits}g}'
    except (TypeError, ValueError):
        return str(value)


def status_kind(text):
    """Pick a colour for a status message from its wording."""
    t = (text or '').lower()
    if not t:
        return 'neutral'
    if 'disconnected' in t or 'not connected' in t or 'no datasheet' in t:
        return 'neutral'
    if any(k in t for k in ('error', 'failed', 'cannot', 'refus', 'invalid', 'could not', 'mismatch')):
        return 'bad'
    if any(k in t for k in ('demo', 'stopp', 'paus', 'caution', 'warning', 'unlocked', 'interrupted')):
        return 'warn'
    if any(k in t for k in ('saved', 'exported', 'connected', 'complete', 'restored', 'loaded', 'launched',
                            'recorded', 'resumed', 'installed', 'ready')):
        return 'good'
    return 'info'


# ----------------------------------------------------------------------------- widgets
class Pill(ttk.Label):
    """Small coloured status badge."""

    def __init__(self, parent, text='', kind='neutral'):
        super().__init__(parent, text=text, style=f'Pill{kind.title()}.TLabel')

    def set(self, text, kind=None):
        self.configure(text=text)
        if kind:
            self.configure(style=f'Pill{kind.title()}.TLabel')


class Banner(ttk.Frame):
    """Dark title strip at the top of a window."""

    def __init__(self, parent, title, subtitle=''):
        super().__init__(parent)
        bar = ttk.Frame(self, style='Banner.TFrame', padding=(px(22), px(16)))
        bar.pack(fill='x')
        self.right = ttk.Frame(bar, style='Banner.TFrame')       # packed first so the status pills are never squeezed out
        self.right.pack(side='right', anchor='n')
        left = ttk.Frame(bar, style='Banner.TFrame')
        left.pack(side='left', fill='x', expand=True)
        ttk.Label(left, text=title, style='BannerTitle.TLabel').pack(anchor='w')
        self.subtitle = tk.StringVar(value=subtitle)
        sub = ttk.Label(left, textvariable=self.subtitle, style='BannerSub.TLabel', justify='left')
        sub.pack(anchor='w', pady=(2, 0))
        left.bind('<Configure>', lambda e: sub.configure(wraplength=max(px(200), e.width - px(8))), add='+')    # long subtitles wrap
        tk.Frame(self, height=1, background=C['border']).pack(fill='x')

    def add_pill(self, text, kind='info'):
        pill = Pill(self.right, text, kind)
        pill.pack(side='left', padx=(8, 0))
        return pill


class Notice(ttk.Frame):
    """Coloured call-out box with a stripe on the left. Text wraps with the window."""

    def __init__(self, parent, text='', kind='info', textvariable=None, title=None):
        super().__init__(parent, style=f'Notice{kind.title()}.TFrame')
        tk.Frame(self, width=5, background=C[kind + '_dot']).pack(side='left', fill='y')
        body = ttk.Frame(self, style=f'Notice{kind.title()}.TFrame', padding=(px(12), px(8)))
        body.pack(side='left', fill='both', expand=True)
        if title:
            ttk.Label(body, text=title, style=f'Notice{kind.title()}.TLabel',
                      font='CalBold').pack(anchor='w')
        kw = dict(textvariable=textvariable) if textvariable is not None else dict(text=text)
        self.label = ttk.Label(body, style=f'Notice{kind.title()}.TLabel', justify='left', wraplength=px(600), **kw)
        self.label.pack(anchor='w', fill='x')
        self.bind('<Configure>', lambda e: self.label.configure(wraplength=max(px(200), e.width - px(60))))


class StatusBar(ttk.Frame):
    """Bottom strip: coloured dot + message, with small action buttons at the right (add_button / dock_button).
    Colour follows the wording of the message."""

    def __init__(self, parent, variable=None, right=''):
        super().__init__(parent, style='Bar.TFrame', padding=(px(14), px(5)))
        tk.Frame(self, height=1, background=C['border']).place(x=0, y=0, relwidth=1)
        self.var = variable or tk.StringVar()
        self._buttons = []
        self.dot = ttk.Label(self, text='●', style='DotInfo.TLabel')
        self.msg = ttk.Label(self, textvariable=self.var, style='Bar.TLabel')
        try:                                           # every window shows the same suite version (a spec/procedure note may come first)
            import suite_info
            right = suite_info.full_version() if (not right or right.startswith('v')) else f'{right}  |  {suite_info.full_version()}'
        except ImportError:
            pass
        self.right = ttk.Label(self, text=right, style='BarMuted.TLabel')
        self._layout()
        self.msg.bind('<Configure>', lambda e: self.msg.configure(wraplength=max(px(200), e.width)))
        self.var.trace_add('write', lambda *_: self._recolor())
        self._recolor()
        try:
            parent._cal_statusbar = self            # lets a procedure dock buttons here: ui.dock_button(root, ...)
        except AttributeError:
            pass

    def _layout(self):
        """Pack order matters: the buttons and version text are packed before the (stretching) message, so a long message wraps
        instead of squeezing them."""
        for w in (self.dot, self.right, *self._buttons, self.msg):
            w.pack_forget()
        self.dot.pack(side='left')
        self.right.pack(side='right', padx=(10, 0))
        for b in reversed(self._buttons):           # the first button added ends up leftmost
            b.pack(side='right', padx=(6, 0))
        self.msg.pack(side='left', padx=(8, 0), fill='x', expand=True)

    def add_button(self, text, command, style='Compact.TButton'):
        b = ttk.Button(self, text=text, command=command, style=style)
        self._buttons.append(b)
        self._layout()
        return b

    def _recolor(self):
        self.dot.configure(style=f'Dot{status_kind(self.var.get()).title()}.TLabel')

    def set(self, text):
        self.var.set(text)


def dock_button(root, text, command):
    """A small button at the right of the window's bottom bar (Save progress, Load progress, Export ...). Returns the button."""
    return root._cal_statusbar.add_button(text, command)


class Summary(ttk.Frame):
    """Progress strip: 'x of y tested', progress bar, pass / fail / remaining badges."""

    def __init__(self, parent):
        super().__init__(parent)
        self.text = tk.StringVar(value='Nothing tested yet')
        top = ttk.Frame(self)
        top.pack(fill='x')
        ttk.Label(top, textvariable=self.text, style='Bold.TLabel').pack(side='left')
        self.rem = Pill(top, '0 remaining', 'neutral')
        self.fail = Pill(top, '0 fail', 'neutral')
        self.ok = Pill(top, '0 pass', 'neutral')
        for p in (self.rem, self.fail, self.ok):
            p.pack(side='right', padx=(6, 0))
        self.bar = ttk.Progressbar(self, maximum=1, mode='determinate')
        self.bar.pack(fill='x', pady=(6, 0))

    def update_counts(self, total, passed, failed):
        done = passed + failed
        self.bar.configure(maximum=max(total, 1), value=done,
                           style='Good.Horizontal.TProgressbar' if total and done == total and not failed
                           else 'Horizontal.TProgressbar')
        self.text.set(f'{done} of {total} tested' if done else f'0 of {total} tested')
        self.ok.set(f'{passed} pass', 'good' if passed else 'neutral')
        self.fail.set(f'{failed} fail', 'bad' if failed else 'neutral')
        left = total - done
        self.rem.set('All points tested' if left == 0 and total else f'{left} remaining',
                     'good' if left == 0 and total and not failed else 'neutral')


class Stepper(ttk.Frame):
    """Numbered workflow indicator:  (1) Load  >  (2) Details  >  (3) Record."""

    def __init__(self, parent, steps):
        super().__init__(parent)
        self.steps = steps
        self.widgets = []
        for i, name in enumerate(steps):
            if i:
                ttk.Label(self, text='›', style='Muted.TLabel').pack(side='left', padx=8)
            lab = ttk.Label(self, text=f'{i + 1}  {name}', style='PillNeutral.TLabel')
            lab.pack(side='left')
            self.widgets.append(lab)
        self.set(0)

    def set(self, current):
        """Steps before `current` show as done, `current` as active, the rest as waiting."""
        for i, lab in enumerate(self.widgets):
            name = self.steps[i]
            if i < current:
                lab.configure(text=f'✔  {name}', style='PillGood.TLabel')
            elif i == current:
                lab.configure(text=f'{i + 1}  {name}', style='PillInfo.TLabel')
            else:
                lab.configure(text=f'{i + 1}  {name}', style='PillNeutral.TLabel')


def _round_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class TabStrip(tk.Canvas):
    """macOS-style segmented control that replaces the notebook's native tab row.

    All segments are the same height and use the same font, so nothing shifts when the selection
    changes; the selected segment is an accent-coloured rounded pill with white text. The notebook keeps working
    as before (add / select / tab(text=...)); the strip follows it, including tabs added later.
    """

    def __init__(self, notebook):
        self.nb = notebook
        self._h = px(36)
        super().__init__(notebook.master, height=self._h, background=C['bg'], highlightthickness=0, borderwidth=0)
        style = ttk.Style(notebook)
        style.layout('Strip.TNotebook.Tab', [])
        style.configure('Strip.TNotebook', tabmargins=(0, 0, 0, 0), borderwidth=0, background=C['bg'])
        notebook.configure(style='Strip.TNotebook')
        self._font = tkfont.nametofont('CalBold')
        self._hits = []
        self._state = None
        self._hover = None
        self.pack(fill='x', before=notebook)
        tk.Frame(notebook.master, height=1, background=C['border']).pack(fill='x', before=notebook)
        self.configure(cursor='hand2')
        self.bind('<Button-1>', self._click)
        self.bind('<Motion>', self._motion)
        self.bind('<Leave>', lambda _e: self._set_hover(None))
        self.refresh()
        self._poll()

    def _poll(self):
        try:
            self.refresh()
            self.after(150, self._poll)
        except tk.TclError:
            pass

    def refresh(self, force=False):
        tabs = self.nb.tabs()
        current = self.nb.select()
        state = (tuple((t, self.nb.tab(t, 'text')) for t in tabs), current, self._hover)
        if state == self._state and not force:
            return
        self._state = state
        self.delete('all')
        self._hits = []
        pad = px(20)
        gap = px(2)
        total = sum(self._font.measure(self.nb.tab(t, 'text').strip()) + 2 * pad for t in tabs) + gap * max(0, len(tabs) - 1)
        x0, y0, y1 = px(14), px(5), self._h - px(5)
        _round_rect(self, x0 - px(3), y0 - px(3), x0 + total + px(3), y1 + px(3), px(9), fill=C['bar'], outline='')
        x = x0
        for t in tabs:
            text = self.nb.tab(t, 'text').strip()
            w = self._font.measure(text) + 2 * pad
            if t == current:
                _round_rect(self, x, y0, x + w, y1, px(7), fill=C['primary'], outline='')
                color = '#FFFFFF'
            else:
                if self._hover == t:
                    _round_rect(self, x, y0, x + w, y1, px(7), fill=C['head_hi'], outline='')
                color = C['text'] if self._hover == t else C['muted']
            self.create_text(x + w / 2, (y0 + y1) / 2, text=text, fill=color, font='CalBold')
            self._hits.append((x, x + w, t))
            x += w + gap

    def _tab_at(self, x):
        for x1, x2, t in self._hits:
            if x1 <= x <= x2:
                return t
        return None

    def _click(self, event):
        t = self._tab_at(event.x)
        if t:
            self.nb.select(t)
            self.refresh()

    def _motion(self, event):
        self._set_hover(self._tab_at(event.x))

    def _set_hover(self, tab):
        if tab != self._hover:
            self._hover = tab
            self.refresh()


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind('<Enter>', self._show, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')

    def _show(self, _e=None):
        text = self.text() if callable(self.text) else self.text
        if self.tip or not text:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip.wm_geometry(f'+{x}+{y}')
        tk.Label(self.tip, text=text, background=C['tip'], foreground='#FFFFFF', padx=8, pady=4,
                 font='TkDefaultFont', justify='left', wraplength=px(360)).pack()

    def _hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Settings:
    """Tiny per-user JSON store (ports, window sizes ...). Never raises."""

    def __init__(self, name):
        self.path = Path.home() / '.calibration_suite' / f'{name}.json'
        try:
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        except Exception:
            pass


# ----------------------------------------------------------------------------- one-shot polish
def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


_BUTTON_RULES = (
    ('Danger.TButton', ('stop', '■')),
    ('Accent.TButton', ('run', 'start', '▶', 'export professional', 'export excel', 'measure next', 'approve')),
)


def _pad_pair(value):
    """A pack/grid padx value as (before, after) pixels; accepts 8, (8, 0), '8' and '{8 0}'."""
    try:
        parts = [int(float(x)) for x in str(value).replace('{', ' ').replace('}', ' ').replace(',', ' ').replace('(', ' ').replace(')', ' ').split()]
    except ValueError:
        parts = []
    if not parts:
        return 0, 0
    return (parts[0], parts[-1]) if len(parts) > 1 else (parts[0], parts[0])


def flow_row(frame, vgap=6):
    """Make a packed toolbar row wrap onto more lines when the window is narrow, so no button is ever squeezed or clipped.

    On one line the row looks as before (left group at the left, right group flush right).  When it does not fit, the left group flows
    onto further lines at full button size and the right group (Save / Load / Export ...) drops to its own line, flush right.
    Only plain rows are converted: three or more widgets, at least two buttons, all packed to the left or right, none expanding, and the
    row itself packed to fill the width.  Returns True when the row was converted."""
    if getattr(frame, '_cal_flow', None) is not None:
        return False
    try:
        infos = [(w, w.pack_info()) for w in frame.pack_slaves()]
        own = frame.pack_info()
    except tk.TclError:
        return False
    if len(infos) < 3 or sum(isinstance(w, ttk.Button) for w, _i in infos) < 2 or str(own.get('fill')) not in ('x', 'both'):
        return False
    for _w, i in infos:
        if str(i.get('side')) not in ('left', 'right') or str(i.get('expand')) not in ('0', '') or str(i.get('fill')) != 'none':
            return False
    left = [(w, i) for w, i in infos if str(i['side']) == 'left']
    right = [(w, i) for w, i in infos if str(i['side']) == 'right'][::-1]      # the first widget packed right is the rightmost
    left = [(w,) + _pad_pair(i.get('padx', 0)) for w, i in left]
    right = [(w,) + _pad_pair(i.get('padx', 0)) for w, i in right]
    for w, _i in infos:
        w.pack_forget()
    state = {'width': 0}

    def need(item):
        return item[0].winfo_reqwidth() + item[1] + item[2]

    def flow(items, width, rows):
        """Append items to rows, starting a new row when one does not fit."""
        row, used = [], 0
        for item in items:
            n = need(item) - (item[1] if not row else 0)
            if row and used + n > width:
                rows.append(row); row, used = [], 0
                n = need(item) - item[1]
            row.append(item); used += n
        if row:
            rows.append(row)

    def layout(width):
        rows = []                                              # each row: (items, flush_right)
        left_total, right_total = sum(need(i) for i in left), sum(need(i) for i in right)
        if left_total + right_total <= width:
            rows.append((left, right))
        else:
            parts = []
            flow(left, width, parts)
            rows += [(r, []) for r in parts]
            if right:
                if right_total <= width:
                    rows.append(([], right))
                else:
                    parts = []
                    flow(right, width, parts)
                    rows += [(r, []) for r in parts]
        y = 0
        for lefts, rights in rows:
            height = max([i[0].winfo_reqheight() for i in lefts + rights] or [0])
            x = 0
            for k, (w, a, b) in enumerate(lefts):
                x += a if (k or len(rows) == 1) else 0
                w.place(x=x, y=y + (height - w.winfo_reqheight()) // 2)
                x += w.winfo_reqwidth() + b
            x = width - sum(need(i) for i in rights)
            for w, a, b in rights:
                x += a
                w.place(x=x, y=y + (height - w.winfo_reqheight()) // 2)
                x += w.winfo_reqwidth() + b
            y += height + vgap
        frame.configure(height=max(1, y - vgap))

    def on_configure(event):
        if event.widget is frame and event.width > 40 and event.width != state['width']:
            state['width'] = event.width
            layout(event.width)

    def relayout():
        if state['width']:
            layout(state['width'])

    frame._cal_flow = relayout
    frame.bind('<Configure>', on_configure, add='+')
    layout(10 ** 5)                      # first pass, before the real width is known
    return True


def reflow(frame):
    """Lay a wrapping toolbar out again (after a button's text or visibility changed)."""
    fn = getattr(frame, '_cal_flow', None)
    if fn:
        fn()


def polish(root):
    """Finish-up pass for big existing windows: wraps long labels to the window width,
    colours Run/Stop buttons, and scales table columns on high-DPI screens."""
    for w in _walk(root):
        try:
            if isinstance(w, ttk.Label) and int(float(str(w.cget('wraplength')) or 0)) > 0 \
                    and not getattr(w, '_cal_wrap', False):
                w._cal_wrap = True
                parent = w.master
                parent.bind('<Configure>',
                            lambda e, lab=w: lab.configure(wraplength=max(px(220), e.width - px(36))), add='+')
            elif isinstance(w, ttk.Button) and not str(w.cget('style')):
                text = str(w.cget('text')).lower().lstrip()
                for style_name, keys in _BUTTON_RULES:
                    if text.startswith(keys) or any(text.startswith(k) for k in keys):
                        w.configure(style=style_name)
                        break
            elif isinstance(w, ttk.Treeview) and not getattr(w, '_cal_scaled', False):
                w._cal_scaled = True
                style_result_tags(w)
                if SCALE > 1.05:
                    for col in w['columns']:
                        w.column(col, width=px(int(w.column(col, 'width'))), minwidth=px(int(w.column(col, 'minwidth'))))
            elif isinstance(w, ttk.Frame) and type(w) is ttk.Frame:
                flow_row(w)                      # button rows wrap instead of squeezing their buttons
        except (tk.TclError, ValueError):
            continue


def report_filename(asset, ext='.pdf', tag=''):
    """Default report name: <asset>-MM-DD-YYYY.pdf  (a slash cannot be used in a Windows file name, so dashes separate the date)."""
    from datetime import datetime
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in str(asset or '')) or 'UNASSIGNED'
    return f"{safe}{'-' + tag if tag else ''}-{datetime.now():%m-%d-%Y}{ext}"
