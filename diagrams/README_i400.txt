Fluke i400 hook-up diagrams
===========================
The procedure shows a picture each time the wiring changes. Drop PNG files in this folder. A missing picture does not stop a run: the dialog shows the text
instructions and names the file it looked for.

File name:   hook_i400_<calibrator>_<GROUP>.png     e.g. hook_i400_5522A_COIL_AUX.png
Fallback:    hook_i400_<GROUP>.png                  used for every calibrator when there is no calibrator-specific file
<calibrator> = 5560A or 5522A (the 5520A uses the 5522A pictures)

GROUP (one picture per separate hook-up)
  DMM_REF    calibrator output straight into the reading multimeter current input (the multimeter pre-calibration); no clamp
  WIRE_1T    calibrator through the single-turn wire loop, clamp jaws round the wire, clamp output cable to the multimeter (Figure 2, p. 6)
  COIL_AUX   calibrator low-current output (5560A VI AUX, 5522A/5520A AUX) through the 50-turn coil, clamp round the coil (2 A step, Figure 3, p. 7)
  COIL_20A   calibrator 20 A output (5560A 30A, 5522A/5520A 20 A) through the 50-turn coil (8 A step)
