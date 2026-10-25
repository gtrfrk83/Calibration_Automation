Front-panel pictures supplied by Mike (jack / terminal layout). They are saved here; the procedures do not show them yet
(these models have no hook-up picture lookup), except the Fluke 287 / 289 (see README_fluke28x.txt).
  fluke8846a_panel.png             Fluke 8846A terminals (INPUT HI/LO, SENSE HI/LO, 400 mA, 10 A, FRONT/REAR)
  keysight34401a_panel.png         Keysight 34401A (Input HI/LO, Sense HI/LO, I, FRONT/REAR)
  keysight34461a_34465a_panel.png  Keysight 34461A / 34465A (shown: 34461A; Input, Sense, 10 A, 3 A)
  keysight34460a_panel.png         Keysight 34460A (Input, Sense, 3 A only)
  tektronix_mdo4000_panel.png      Tektronix MDO4000 series

Drawn hook-up diagrams (specs/build_hookups_ext.py, Pillow; the procedures do not need it)
  hook_<model>_5560A_<KEY>.png for 34401A, 34460A, 34461A, 34465A, 8846A.  KEY: VOLT, RES2, RES4, SHORT (zero, copper short), OPEN (current zero),
  I_I / I_3A / I_10A / I_400MA (current).  Jack positions are read from the photos above.  hookups.bench_image() picks one per wiring and falls back to
  the supplied photo (rear terminals, capacitance, models without a drawing).  UNVERIFIED: which current jack each range uses on the 8846A (400 mA up to the
  400 mA range, else 10 A) and the 5560A SENSE leads for 4-wire; confirm on the real instruments.
