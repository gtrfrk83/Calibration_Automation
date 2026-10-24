"""Calibration Procedure Manager, Qt build.  Run: python Calibration_Procedure_Manager_qt.py

The same Manager as Calibration_Procedure_Manager.py (the Tk launcher is unchanged) in the Qt look; needs PySide6.  The procedures it starts are separate
processes, exactly as in the Tk Manager; their toolkit is chosen by the CALSUITE_UI environment variable (tk | qt, default tk until the cut-over, see
ui_port.select_toolkit) and they open their Qt window when the engine has one, the Tk window otherwise.
"""
import sys


def main(argv=None):
    import appdata
    import manager_model
    import ui_port
    appdata.migrate_legacy_progress()
    core = manager_model.ManagerCore()
    core.init_db()
    from qtui import app
    from qtui.screens import help_menu
    from qtui.screens.manager import ManagerWindow
    help_menu.install_hooks()
    qapp = app.create_app(argv)
    ui_port.select_toolkit('qt')              # the Manager's own panels (reports, prompts) talk to the Qt port when it exists; a missing one falls back to Tk with a note
    win = ManagerWindow(core)
    win.show()
    return qapp.exec()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
