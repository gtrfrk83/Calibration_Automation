"""Helpers shared by tests/test_qt_*.py (not a test module): force the tkinter stub (the engine harnesses expect it, and a machine that has PySide6 may well
have a real tkinter too), and create the one QApplication once per process (qtui.app.create_app re-applies the theme on every call)."""
import sys


def force_tk_stub():
    """Make `import tkinter` give the do-nothing stand-in of tests/_tk_stub.py even when a real tkinter is installed.  Call BEFORE importing an engine."""
    import _tk_stub
    tk = sys.modules.get('tkinter')
    if tk is not None and getattr(tk, '_cal_stub', False):
        return True
    for name in [n for n in sys.modules if n == 'tkinter' or n.startswith('tkinter.')]:
        del sys.modules[name]
    for name in ('tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.filedialog', 'tkinter.font', 'tkinter.scrolledtext'):
        sys.modules[name] = None                                 # an import now fails ...
    try:
        return _tk_stub.install()                                # ... so install() puts the stubs in
    finally:
        pass


def get_app():
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        from qtui import app as qapp
        qapp.create_app()
    return QApplication.instance()


def dclick(widget, pos):
    """A double-click as the user makes it: a click, then the double click (QTest.mouseDClick alone is taken as a plain press by the item views)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
