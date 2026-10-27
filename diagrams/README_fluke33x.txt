Fluke 333 / 334 / 335 / 336 / 337 hook-up diagrams
==================================================
The procedures show a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for. Nothing here is drawn by the program: the pictures are supplied by the lab.
One set of three pictures (plus the two leads pictures per calibrator) is shared by all five models (prefix hook_fluke33x).

Leads (AC volts, DC volts, continuity, ohms; test leads in the meter VΩ and COM jacks, Calibration Information printed p. 7 step 1; one picture per calibrator):
    hook_fluke33x_5560A_VOHM.png      Fluke 5560A  OUTPUT V/Ω HI -> meter VΩ (red),  OUTPUT V/Ω LO -> meter COM (black)
    hook_fluke33x_5522A_VOHM.png      Fluke 5522A  NORMAL HI -> meter VΩ (red),  NORMAL LO -> meter COM (black)   (the 5520A uses the 5522A pictures)

Current (named in the spec, one picture for every calibrator; NO test leads in the meter jacks; Figure 4, printed p. 7, '33x Amps/Hz Verification Setup'):
    hook_fluke33x_COIL_AUX.png        calibrator low-current output (5522A/5520A AUX, 5560A VI AUX) -> 50-turn coil -> meter jaw (calibrator current below 3 A: 0.4 A = 20 A, 0.1 A = 5 A inrush / 5 A at 10 Hz, 0.2 A = 10 A at 300 Hz, 0 A dc)
    hook_fluke33x_COIL_20A.png        calibrator 20 A output (5522A/5520A 20 A, 5560A 30A) -> 50-turn coil -> meter jaw (3 A and above: 4 A, 8 A, 12 A, 18 A = 200, 400, 600, 900 A)
The inrush, frequency and 0 A dc points use the coil pictures (there is no separate picture for them).

REUSE of pictures you already have: the layout is identical, so the existing pictures can be copied and renamed rather than redrawn -
    * the leads pictures: any of your two-jack clamp-meter lead pictures (hook_fluke323_<cal>_VOHM.png, hook_fluke365_..., hook_fluke376_..., hook_fluke381_...) if they show red lead -> VΩ and black lead -> COM;
      the Klein MM325 pictures (hook_mm325_5560A_VOHM.png, hook_mm325_5522A_VOHM.png) show the same two calibrator terminals but the MM325 meter body, so use them only if the meter body does not matter to you;
    * hook_fluke33x_COIL_AUX.png / hook_fluke33x_COIL_20A.png = hook_fluke323_COIL_AUX.png / hook_fluke323_COIL_20A.png (same coil, same terminals, same jaw closed on the coil).
Nothing was copied for you: the program never invents a diagram.
