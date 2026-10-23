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
    """Put stub tkinter modules in sys.modules (only if the real one is missing); returns True when the stubs are in use (installed now or by an
    earlier test module: several test modules call this, and they must all agree that tkinter is the stub), False when the real tkinter is there."""
    try:
        import tkinter
        return bool(getattr(tkinter, '_cal_stub', False))
    except Exception:
        pass
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
