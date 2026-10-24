"""Runs tests/dsb_scenario.py against the TK Datasheet Builder (datasheet_builder_ui under tests/_tk_stub.py) and prints what it saved plus every message as JSON.
tests/test_qt_dsb.py runs the same scenarios against the Qt builder and compares the two byte for byte.  Usage: python tests/dsb_tk_reference.py"""
import contextlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.modules['tkinter'] = None                      # force the stub even where a real tkinter exists (there is no display here)
spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
tk_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk_stub)
tk_stub.install()                                  # tkinter is None here, so install() puts the stubs in place (replacing the None)

import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_ui as ui_mod  # noqa: E402
import datasheet_builder_ui_model as M  # noqa: E402
from tests import dsb_scenario as sc  # noqa: E402
from tests.test_dsb_ui_model import REG  # noqa: E402

NOW = '2026-01-01T00:00:00'


def main():
    tmp = Path(tempfile.mkdtemp())
    store = M.Storage(tmp / 'user_specs', tmp / 'lab_registry.sqlite3', who='tester')
    matcher = dm.Matcher(REG)
    with sc.frozen_time(), mock.patch.object(ui_mod.ui, 'fit_window'):
        panel = ui_mod.DatasheetBuilderPanel(ui_mod.tk.Frame(), store, matcher_factory=lambda: matcher)

        def new(handheld):
            with mock.patch.object(ui_mod, 'ask_new_sheet', return_value=handheld):
                return panel.new()

        @contextlib.contextmanager
        def answer(yes):
            with mock.patch.object(ui_mod.messagebox, 'askyesno', return_value=yes):
                yield
        env = sc.Env(panel, new, answer)
        log = sc.run_all(env)
        dump = sc.dump_storage(tmp / 'user_specs', tmp / 'lab_registry.sqlite3')
    print(json.dumps(dict(log=log, saved=dump), sort_keys=True))


if __name__ == '__main__':
    main()
