Fluke 287 / 289 hook-up picture
===============================
fluke28x_panel.png  (supplied by Mike): the meter front panel showing the jacks A (10 A fused), mA uA (400 mA fused), COM and V Ohm.
It is shown in every cable-change prompt of the 287 / 289 procedures (specs/fluke_287_289_pv.json groups VOHM, OHM4, UAMP, AMP10, TEMP).
Calibrator-specific wiring pictures can replace it per group by naming a file in the group's "diagram" key (specs/build_28x_spec.py).

Drawn diagrams: hook_fluke28x_<5560A|5522A>_<VOHM|OHM4|UAMP|AMP10|TEMP>.png (specs/build_hookups.py and build_hookups_ext.py), jack order A, mA uA, COM, V Ohm from the
photo.  The spec option "hookup_images": "fluke28x" makes the cable-change prompt show the one for the chosen calibrator (the panel photo remains the fallback).
UNVERIFIED: on the 5560A the OHM4 sense leads are drawn to SENSE HI / LO (the spec text names the 5522A AUX HI / LO).
