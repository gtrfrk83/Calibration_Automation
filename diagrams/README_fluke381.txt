Fluke 381 hook-up diagrams
==========================
The procedure shows a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for. Nothing here is drawn by the program: the pictures are supplied by the lab.

Leads (AC volts, DC volts, ohms; test leads in the meter VΩ and COM jacks; one picture per calibrator, Figure 5 of the manual):
    hook_fluke381_5560A_VOHM.png      Fluke 5560A  OUTPUT V/Ω HI -> meter VΩ (red),  OUTPUT V/Ω LO -> meter COM (black)
    hook_fluke381_5522A_VOHM.png      Fluke 5522A  NORMAL HI -> meter VΩ (red),  NORMAL LO -> meter COM (black)   (the 5520A uses the 5522A pictures)

Current (named in the spec, one picture for every calibrator; NO test leads in the meter jacks):
    hook_fluke381_COIL_AUX.png        calibrator low-current output (5522A/5520A AUX, 5560A VI AUX) -> 50-turn coil -> meter jaw (calibrator current below 3 A; polarity as Figure 4)
    hook_fluke381_COIL_20A.png        calibrator 20 A output (5522A/5520A 20 A, 5560A 30A) -> 50-turn coil -> meter jaw (12, 18, 19.5 A)
    hook_fluke381_WIRE_0A.png         0 A dc point: single wire AUX HI -> AUX LO, meter clamped around the wire (Table 3 footnote [1], Figure 3)
    hook_fluke381_IFLEX_SIM.png       iFlex simulation: calibrator voltage HI -> iFlex 2 mm jack (far left), LO -> COM, with probe TP2 and lead 6358 (Figure 7)
    hook_fluke381_IFLEX_COIL_AUX.png  iFlex loop around the 50-turn coil on the low-current output (0.2 A and 0.4 A points; Figure 6)
    hook_fluke381_IFLEX_COIL_20A.png  iFlex loop around the 50-turn coil on the high-current output (12 A and 19.9 A points)
The frequency points use the coil pictures. The iFlex pictures are only used while the window option "iFlex probe supplied: run the iFlex tests" is ON (the simulation picture is always used).
