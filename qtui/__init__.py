"""qtui: the shared PySide6 (Qt Widgets) design system and application bootstrap.

    from qtui import theme, widgets, table, app          # each needs PySide6; importing the bare package does not

No Tk import anywhere in this package.  theme / widgets / table import no instrument or engine code; engines are reached only through ui_port.
See NOTES.md 'Qt design system (qtui/)'.
"""
