"""Headless stand-ins for tkinter (not installed in the CI sandbox): every attribute is a do-nothing class.  Test helper only."""
import sys
import types


# methods that must answer with real numbers (the window code does arithmetic on them)
_NUMBERS = {'winfo_reqwidth': 100, 'winfo_reqheight': 20, 'winfo_width': 1, 'winfo_height': 1, 'winfo_ismapped': False, 'yview': (0.0, 1.0)}


class _Dummy:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if name in _NUMBERS:
            return lambda *a, **k: _NUMBERS[name]
        return _Dummy()

    def __call__(self, *a, **k):
        return _Dummy()

    def __iter__(self):
        return iter(())


class _Var:
    def __init__(self, *a, value='', **k):
        self._v = value
        self._cbs = []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in list(self._cbs):                    # like Tk: 'write' traces run on every set
            cb('', '', 'write')

    def trace_add(self, mode, callback):
        self._cbs.append(callback)
        return str(len(self._cbs))


class _Mod(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        cls = type(name, (_Dummy,), {})
        setattr(self, name, cls)
        return cls


MESSAGES = []


def install():
    """Put stub tkinter modules in sys.modules; returns True (the stubs are in use). Several test modules call this, and they must all agree that tkinter is the stub.
    Always the stub, even where a real tkinter is installed: the tests are written against the do-nothing stand-ins (the real widgets need a display and a main loop).
    Before, a real tkinter was left in place, so install_legacy_layer() found no 'tkinter.messagebox' stand-in and every test module that calls it failed to load."""
    current = sys.modules.get('tkinter')
    if current is not None and getattr(current, '_cal_stub', False):
        return True
    for name in [n for n in sys.modules if n == 'tkinter' or n.startswith('tkinter.')]:
        del sys.modules[name]                       # a real tkinter, or the None entry some tests set to make `import tkinter` fail
    names = ('tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.filedialog', 'tkinter.font', 'tkinter.scrolledtext')
    mods = {n: _Mod(n) for n in names}
    for n, m in mods.items():
        m.__path__ = []
        if '.' in n:
            setattr(mods['tkinter'], n.split('.')[1], m)
    t = mods['tkinter']
    t._cal_stub = True
    t.TclError = type('TclError', (Exception,), {})              # a real exception class, so `except tk.TclError` works
    for v in ('StringVar', 'IntVar', 'BooleanVar', 'DoubleVar'):
        setattr(t, v, _Var)
    mb = mods['tkinter.messagebox']
    for n in ('showinfo', 'showwarning', 'showerror'):
        setattr(mb, n, lambda *a, _n=n, **k: MESSAGES.append((_n, a)))
    for n in ('askyesno', 'askokcancel', 'askretrycancel'):
        setattr(mb, n, lambda *a, **k: True)
    sys.modules.update(mods)
    return True


# ======================================================================================================================================================
# The Tk build was removed (2026-10-27).  Many engine tests were written against the Tk port: they patch `messagebox` / `filedialog`, `ui_theme.confirm_steps`,
# `report_dialog.ask_details` and the `ui_shell` widget builders.  The shipping code has none of these any more; this test-only layer keeps those tests running
# over the stub tkinter above until each is moved to ui_port.ScriptedUiPort.  Nothing here ships and nothing imports a real toolkit.
# ======================================================================================================================================================
class _ShimModule(types.ModuleType):
    """A stand-in module: names of `base` (a real module) first, any other name a MagicMock (patchable, callable)."""
    def __init__(self, name, base=None):
        super().__init__(name)
        self._base = base
        self._cal_shim = True

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if self._base is not None and hasattr(self._base, name):
            return getattr(self._base, name)
        from unittest import mock
        m = mock.MagicMock(name=f'{self.__name__}.{name}')
        setattr(self, name, m)
        return m


def _stub_port_class():
    import threading
    import ui_port

    def _kw(**kw):
        return {k: v for k, v in kw.items() if v is not None}

    class StubTkPort(ui_port.ScriptedUiPort):
        """The old TkUiPort calls, over the stub modules: each method makes the call the engines used to make, looked up at call time so patches work."""
        def message(self, kind, title, text, *, parent=None):
            mb = sys.modules['tkinter.messagebox']
            {'info': mb.showinfo, 'warning': mb.showwarning, 'error': mb.showerror}[kind](title, text, **_kw(parent=parent))

        def ask_yes_no(self, title, text, *, icon=None, default=None, parent=None):
            mb = sys.modules['tkinter.messagebox']
            return mb.askyesno(title, text, **_kw(icon=icon, default=default, parent=parent))

        def ask_ok_cancel(self, title, text, *, icon=None, parent=None):
            mb = sys.modules['tkinter.messagebox']
            return mb.askokcancel(title, text, **_kw(icon=icon, parent=parent))

        def ask_retry_cancel(self, title, text, *, icon=None, parent=None):
            mb = sys.modules['tkinter.messagebox']
            return mb.askretrycancel(title, text, **_kw(icon=icon, parent=parent))

        def ask_yes_no_cancel(self, title, text, *, icon=None, parent=None):
            mb = sys.modules['tkinter.messagebox']
            return mb.askyesnocancel(title, text, **_kw(icon=icon, parent=parent))

        def ask_text(self, title, prompt, *, initial=None, show=None, parent=None):
            sd = sys.modules['tkinter.simpledialog']
            return sd.askstring(title, prompt, **_kw(initialvalue=initial, show=show, parent=parent))

        def ask_number(self, title, prompt, *, initial=None, minvalue=None, maxvalue=None, integer=False, parent=None):
            sd = sys.modules['tkinter.simpledialog']
            ask = sd.askinteger if integer else sd.askfloat
            return ask(title, prompt, **_kw(initialvalue=initial, minvalue=minvalue, maxvalue=maxvalue, parent=parent))

        def choose_file(self, *, parent=None, **opts):
            fd = sys.modules['tkinter.filedialog']
            return fd.askopenfilename(**_kw(parent=parent, **opts))

        def save_file(self, *, parent=None, **opts):
            fd = sys.modules['tkinter.filedialog']
            return fd.asksaveasfilename(**_kw(parent=parent, **opts))

        def choose_dir(self, *, parent=None, **opts):
            fd = sys.modules['tkinter.filedialog']
            return fd.askdirectory(**_kw(parent=parent, **opts))

        def operator_prompt(self, title, heading, steps, *, parent=None, **opts):
            import ui_theme
            return ui_theme.confirm_steps(parent, title, heading, steps, **opts)

        def report_details(self, procedure='', *, parent=None):
            import report_dialog
            return report_dialog.ask_details(parent, procedure)

        def call_from_worker(self, win, fn, *args):
            box, done = {}, threading.Event()

            def run():
                try:
                    box['v'] = fn(*args)
                finally:
                    done.set()
            win.after(0, run)
            done.wait()
            return box.get('v')

        def run_app(self, factory):
            tk = sys.modules['tkinter']
            root = tk.Tk()
            factory(root)
            root.mainloop()

        def post(self, win, fn, *args):
            win.after(0, fn, *args)

        def after(self, win, ms, fn, *args):
            return win.after(ms, fn, *args)

        def var(self, value='', kind='str'):
            tk = sys.modules['tkinter']
            return {'str': tk.StringVar, 'bool': tk.BooleanVar, 'int': tk.IntVar, 'float': tk.DoubleVar}[kind](value=value)

        def ask_value(self, title, prompt, default, *, parent=None):
            return default

        def surprise_handler(self, win):
            import surprise
            return surprise.tk_handler(win) if hasattr(surprise, 'tk_handler') else None

    return StubTkPort


def install_legacy_layer():
    """Register the stand-in modules ui_theme / ui_shell / report_dialog and make the stub-backed port the default one (unless a test installed its own)."""
    root = str(__import__('pathlib').Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    import ui_port
    import ui_theme_core
    for name, base in (('ui_theme', ui_theme_core), ('ui_shell', None), ('report_dialog', None)):
        if not vars(sys.modules[name]).get('_cal_shim') if name in sys.modules else True:
            sys.modules[name] = _ShimModule(name, base)
    rd = sys.modules['report_dialog']
    if 'ask_details' not in vars(rd):
        rd.USE_REVIEW = True

        def ask_details_plain(parent, procedure=''):
            return None                                      # the plain popup is cancelled (no window without a toolkit)

        def ask_details(parent, procedure=''):
            """The chain of the removed Tk module: the review flow for the engines it covers, else the plain popup."""
            if rd.USE_REVIEW:
                import report_review as rr
                out = rr.ask(parent, procedure)
                if out is not rr.UNAVAILABLE:
                    return out
            return rd.ask_details_plain(parent, procedure)
        rd.ask_details_plain = ask_details_plain
        rd.ask_details = ask_details
    if not isinstance(sys.modules.get('report_review'), types.ModuleType):
        import report_review_flow as flow
        rr = types.ModuleType('report_review')                 # the review flow of the removed Tk window; the window class is replaced by the tests
        for n in ('COVERED', 'SHORT', 'UNAVAILABLE', 'asset_of', 'build_models', 'find_app', 'finish', 'hint_kinds', 'is_demo'):
            setattr(rr, n, getattr(flow, n))

        class NoWindow(RuntimeError):
            pass

        class ReviewWindow:
            def __init__(self, *a, **k):
                raise NoWindow('no review window without a toolkit: the test replaces report_review.ReviewWindow')
        rr.ReviewWindow = ReviewWindow

        def ask(parent, procedure='', app=None):
            built = rr.build_models(parent, procedure, app)
            if built is rr.UNAVAILABLE:
                return rr.UNAVAILABLE
            models, demo = built
            details = None
            for n, model in enumerate(models, 1):
                try:
                    win = rr.ReviewWindow(parent, model, procedure, demo=demo, details=details, position=(n, len(models)))
                except NoWindow:
                    return rr.UNAVAILABLE                      # like the Tk flow: when the window cannot be built, the plain popup follows
                details = win.run()
                if details is None:
                    return None
            return rr.finish(models, details)
        rr.ask = ask
        sys.modules['report_review'] = rr
    existing = sys.modules.get('ui_port_tk')
    port_cls = existing.TkUiPort if isinstance(existing, types.ModuleType) and hasattr(existing, 'TkUiPort') else _stub_port_class()
    if not isinstance(existing, types.ModuleType):
        m = types.ModuleType('ui_port_tk')                     # tests patch ui_port_tk.messagebox / .filedialog: the stub modules the stub port calls
        m.TkUiPort = port_cls
        m.messagebox = sys.modules['tkinter.messagebox']
        m.filedialog = sys.modules['tkinter.filedialog']
        m.simpledialog = sys.modules['tkinter.simpledialog']
        sys.modules['ui_port_tk'] = m
    if not isinstance(ui_port._ui, port_cls):             # an earlier test module may have left another port installed
        ui_port.set_ui(port_cls())


_install_stub_only = install


def install():
    ok = _install_stub_only()
    install_legacy_layer()
    return ok
