"""Fluke 365 clamp meter: manual calibration on the shared handheld engine (handheld_dmm.py), with the test point grid taking typed readings.

The 365 has no remote interface, so every reading is typed.  Everything else is the existing handheld engine unchanged: the calibrator (Fluke 5560A / 5522A
over RS-232, or by hand) is set per point and put in STANDBY after it, the rotary switch and cable-change prompts appear when the function or hook-up
changes, a typed reading is padded to the point's resolution, judged exactly (Decimal) against the limits, stored As Found / As Left, and the report is
the usual PDF 'Calibration Data'.  handheld_dmm.py is NOT edited (the verified handheld procedures fingerprint it).

What this adds (nothing else): the same typed-reading grid the Manual Calibrations use (manual_grid.py, the Cal Processor / Datasheet Builder manual
runtime) on top of the handheld window.  Click a point (or press Enter / start typing), type the meter reading, Enter = save and next point.
`type_reading` is the engine's own typed-reading path (pad_reading -> judge_numeric -> _store), the same as the reading window of Run All Pending, which still
works and still sets the calibrator for you.  The grid is for readings taken at the bench with the calibrator set by hand (calibrator 'Manual') or entered afterwards;
it never outputs anything.

Test points and limits: specs/fluke_365_pv.json (built by specs/build_fluke_365_spec.py from the Fluke 365 Calibration Manual, Table 2, printed pp. 7-8).
Demo (no hardware):  python Procedures/Fluke_365_Verification.py --demo
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import handheld_dmm as hh

MODEL = '365'
SPEC = 'fluke_365_pv.json'


class App(hh.App):
    """The handheld window plus the typed-reading grid of the Manual Calibrations."""
    QUEUE_SUPPORTED = False          # the run queue wires several meters to one calibrator output; a clamp reading a 20-turn coil is one meter at a time (not verified otherwise)
    GRID_HELP = ('Click a test point and type the meter reading (without the unit): Enter saves it and opens the next point, Esc closes the box, '
                 'Up / Down move. Run All Pending sets the calibrator for each point and asks for the reading in its own window instead.')

    def __init__(self, *args, **kw):
        self.grid_entry = None
        super().__init__(*args, **kw)
        self.root.title(f'{self.info["name"]} | Manual Calibration' + (' [DEMO]' if self.demo else ''))       # the title bar only; the engine's window is otherwise unchanged

    def _build_ui(self):
        super()._build_ui()
        import manual_grid
        self.grid_entry = manual_grid.GridEntry(self, self.tree)
        try:
            self.shell.notice('Manual calibration: the 365 has no remote interface, every reading is typed. ' + self.GRID_HELP)
        except Exception:                                   # a window without the notice strip must still open
            pass

    def type_reading(self, p, text):
        """Record a reading typed into the grid for point p in the data mode on screen (As Found / As Left): the engine's own steps for a typed reading
        (hh.pad_reading to the point's resolution, hh.judge_numeric, _store), nothing else.  Returns the stored record.  Raises ValueError with the reason in
        words for text that is not a reading and RuntimeError when it cannot be recorded now."""
        if self.busy:
            raise RuntimeError('A run is in progress: finish or stop it before typing readings into the grid.')
        asset = self.asset.get().strip()
        if not asset:
            raise RuntimeError('Enter the instrument ID first.')
        live = self.pm_begin_run([p], asset)             # the saved procedure modifications of this asset, as at the start of a run
        if not live:
            raise RuntimeError('This point is skipped by a procedure modification.')
        p = live[0]
        raw = (text or '').strip()
        if not raw:
            raise ValueError('Type a reading.')
        if ',' in raw:
            raise ValueError('Use a decimal point, not a comma.')
        entered = hh.pad_reading(p, raw)
        result, base = hh.judge_numeric(p, entered, True)          # ValueError: not a number / NaN / infinity
        self._store(p, entered=entered, reading=base, result=result, annunciator=None, source='typed')
        return self.results[p['id']]


def main(argv=None):
    argv = sys.argv if argv is None else argv
    import tkinter as tk
    import virtualbench
    root = tk.Tk()
    demo, fast = virtualbench.flags(argv)
    App(root, MODEL, demo=demo, spec=hh.load_spec(SPEC), fast_demo=fast)
    root.mainloop()


if __name__ == '__main__':
    main()
