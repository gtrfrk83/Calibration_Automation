Fluke 323 / 324 / 325 hook-up diagrams
======================================
The procedures show a picture each time the wiring changes. Drop PNG files in this folder. A missing picture does not stop a run: the dialog shows the text instructions and names the file it looked for.

Leads (volts, ohms, capacitance):   hook_fluke323_<calibrator>_VOHM.png        <calibrator> = 5560A or 5522A (the 5520A uses the 5522A pictures)
Coil and temperature (the spec's own groups, one picture for every calibrator):
  hook_fluke323_COIL_AUX.png    calibrator low-current output (5522A/5520A AUX, 5560A VI AUX) -> 50-turn coil -> meter jaw (calibrator current below 3 A)
  hook_fluke323_COIL_20A.png    calibrator 20 A output (5522A/5520A 20 A, 5560A 30A) -> 50-turn coil -> meter jaw (3 A and above: 323 4.2 A and 7.8 A, 324 / 325 6 A)
  hook_fluke323_TEMP.png        calibrator TC output -> meter temperature input (324 / 325)
The frequency points (325) use the coil pictures.  Manual figures: Figure 4 (printed p. 11) for the leads, Figure 5 (printed p. 12) for the coil.
