"""Headless stand-ins for tkinter (not installed in the CI sandbox): every attribute is a do-nothing class.  Test helper only."""
import sys
import types


class _Dummy:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Dummy()

    def __call__(self, *a, **k):
        return _Dummy()

    def __iter__(self):
        return iter(())


class _Var:
    def __init__(self, *a, value='', **k):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Mod(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        cls = type(name, (_Dummy,), {})
        setattr(self, name, cls)
        return cls


MESSAGES = []


def install():
    """Put stub tkinter modules in sys.modules (only if the real one is missing); returns True when stubs were installed."""
    try:
        import tkinter  # noqa: F401
        return False
    except Exception:
        pass
    names = ('tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.filedialog', 'tkinter.font', 'tkinter.scrolledtext')
    mods = {n: _Mod(n) for n in names}
    for n, m in mods.items():
        m.__path__ = []
        if '.' in n:
            setattr(mods['tkinter'], n.split('.')[1], m)
    t = mods['tkinter']
    for v in ('StringVar', 'IntVar', 'BooleanVar', 'DoubleVar'):
        setattr(t, v, _Var)
    mb = mods['tkinter.messagebox']
    for n in ('showinfo', 'showwarning', 'showerror'):
        setattr(mb, n, lambda *a, _n=n, **k: MESSAGES.append((_n, a)))
    for n in ('askyesno', 'askokcancel', 'askretrycancel'):
        setattr(mb, n, lambda *a, **k: True)
    sys.modules.update(mods)
    return True
