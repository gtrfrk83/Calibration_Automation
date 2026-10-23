Fluke 376 clamp meter hook-up diagrams (Fluke 374 / 375 / 376 / 376-II family spec; the 376 is the registered procedure)
==============================================================================================================
The procedure shows a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for. Nothing here is drawn by the program:
the pictures are supplied by the lab.

Voltage, millivolts, resistance and capacitance (test leads in the meter VΩ and COM jacks; one picture per calibrator)
    hook_fluke376_5560A_VOHM.png      Fluke 5560A  OUTPUT V/Ω HI -> meter VΩ (red),  OUTPUT V/Ω LO -> meter COM (black)
    hook_fluke376_5522A_VOHM.png      Fluke 5522A  NORMAL HI -> meter VΩ (red),  NORMAL LO -> meter COM (black)
    Used for AC volts, DC volts, DC millivolts, ohms and capacitance (the group VOHM).

Current through the 50-turn coil (the detachable jaw closed around the coil; NO test leads in the meter jacks); one picture each, showing both calibrators' labels
    hook_fluke376_COIL_AUX.png        0.2 A points (group COIL_AUX):  coil on the calibrator low-current output
                                      (5522A AUX HI / AUX LO; 5560A VI AUX / OUTPUT V/Ω LO), jaw around the coil
    hook_fluke376_COIL_20A.png        10 A, 18 A and 6 A points (group COIL_20A):  coil on the calibrator high-current output
                                      (5522A 20 A / AUX LO; 5560A 30A / OUTPUT V/Ω LO), jaw around the coil
    (The calibration manual's Figure 3 shows the same coil box on a 5560A.)

iFlex simulation (calibrator voltage output to the iFlex input; no loop connected)
    hook_fluke376_IFLEX_SIM.png       group IFLEX_SIM:  calibrator HI -> iFlex 2 mm jack (far left of the meter), calibrator LO -> black COM jack,
                                      with the 2 mm to 4 mm Slim Reach probe (PN 6508922) and the test lead with retractable sheath (6358, PN 1903307);
                                      one picture showing both calibrators' voltage terminals

iFlex loop on the 50-turn coil (iFlex probe plugged into the meter, loop around the coil; NO test leads in the meter jacks)
    hook_fluke376_IFLEX_COIL_AUX.png  iFlex 0.2 A points (group IFLEX_COIL_AUX):  coil on the calibrator low-current output, iFlex loop around the coil
    hook_fluke376_IFLEX_COIL_20A.png  iFlex 10 A, 18 A and 6 A points (group IFLEX_COIL_20A):  coil on the calibrator high-current output, iFlex loop around the coil

The coil and iFlex pictures are named in the spec (specs/fluke_376_pv.json, groups COIL_AUX / COIL_20A / IFLEX_SIM / IFLEX_COIL_AUX / IFLEX_COIL_20A, key 'diagram'),
not looked up per calibrator.
The meter dial has no picture (Figure 1 of the calibration manual draws the dial positions as small symbols; see NOTES.md, Fluke 376).
