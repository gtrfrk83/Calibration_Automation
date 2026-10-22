"""Headless harness for the virtual bench tests (tests/test_beta_virtual_bench*.py).  Not a test module.

Builds on tests/dsb_run_harness.Harness (tkinter stubbed, modal dialogs scripted, simulated benches) with three differences:
  * the pump re-checks the queue after seeing no worker thread (the base pump can stop between a worker's last `after` and its exit);
  * ask_reading takes the new `demo_fill` argument: the scripted operator either presses 'Fill with a simulated reading' (mode 'fill', the default)
    or types a value (self.readings / self.default_reading, as the base harness);
  * every dialog is recorded with its title, so a test can assert which windows a real run shows.
"""
import sys
import time
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dsb_run_harness as DH  # noqa: E402
from dsb_run_harness import Harness, hh, wire  # noqa: E402,F401


class VHarness(Harness):
    def __init__(self, home=None):
        super().__init__(home)
        self.fill = True                   # press the Fill button when no typed reading is scripted for the point
        self.fills = []                    # ids of the points whose Fill button was offered (demo_fill given)
        self.simple = []                   # simpledialog.askfloat prompts (fgen typed readings)
        self.range_answer = 'ok'

    def start(self):
        super().start()
        for obj, name, val in ((hh, 'ask_reading', self._ask_reading_v), (hh, 'ask_range', lambda *a, **k: self.range_answer)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.patches.append(p)
        return self

    def _ask_reading_v(self, parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                       limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None):
        self.dialogs.append(('reading', p['id'], mode, device))
        if demo_fill is not None:
            self.fills.append(p['id'])
        typed = self.readings.get(p['id']) if p['id'] in self.readings else None
        if typed is None and self.default_reading:
            typed = self.default_reading(p)
        if mode == 'numeric':
            if typed is None and self.fill and demo_fill is not None:
                typed = demo_fill()
            if typed is None:
                return dict(action='stop', text='', ann=False, yes=None)
            if callable(typed):
                typed = typed(p)
            if validate:
                validate(typed)
            return dict(action='record', text=typed, ann=False, yes=None)
        if typed is None and self.fill and demo_fill is not None:
            typed = demo_fill()
        return dict(action='record', text='', ann=False, yes=bool(True if typed is None else typed))

    def pump(self, seconds=120):
        end = time.time() + seconds
        app = self.app
        while time.time() < end:
            if self.root.q:
                fn, a = self.root.q.pop(0)
                fn(*a)
                continue
            workers = [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon]
            if not workers:
                if self.root.q:
                    continue
                break
            time.sleep(0.002)
        return not app.busy

    def pump_poll(self, seconds=120):
        """For the engines whose window polls a message queue with a self-rescheduling `after` (MDO4000C, TDS2000C): run one callback per turn
        until the run is no longer busy."""
        end = time.time() + seconds
        app = self.app
        time.sleep(0.01)
        while time.time() < end:
            if self.root.q:
                fn, a = self.root.q.pop(0)
                fn(*a)
            else:
                time.sleep(0.002)
            if not app.busy and not [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon]:
                for fn, a in list(self.root.q):
                    pass
                break
        return not app.busy

    def titles(self):
        return [d[1] for d in self.dialogs if d[0] == 'confirm']

    def boxes(self, kind=None):
        return [d for d in self.dialogs if d[0] == 'box' and (kind is None or d[1] == kind)]
