Fluke 365 clamp meter hook-up diagrams
======================================
The procedure shows a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for. Nothing here is drawn by the program:
the pictures are supplied by the lab.

Voltage and resistance (test leads in the meter VΩ and COM jacks; one picture per calibrator)
    hook_fluke365_5560A_VOHM.png      Fluke 5560A  OUTPUT V/Ω HI -> meter VΩ (red),  OUTPUT V/Ω LO -> meter COM (black)
    hook_fluke365_5522A_VOHM.png      Fluke 5522A  NORMAL HI -> meter VΩ (red),  NORMAL LO -> meter COM (black)
    Used for AC volts, DC volts and ohms (the group VOHM).

Current through the 20-turn coil (the detachable jaw closed around all 20 turns; NO test leads in the meter jacks); one picture each, showing both calibrators' labels
    hook_fluke365_COIL_AUX.png        0.5 A points (group COIL_AUX):  coil on the calibrator low-current output
                                      (5522A AUX HI / AUX LO; 5560A VI AUX / OUTPUT V/Ω LO), jaw around the coil
    hook_fluke365_COIL_20A.png        5 A and 9.5 A points (group COIL_20A):  coil on the calibrator high-current output
                                      (5522A 20 A / AUX LO; 5560A 30A / OUTPUT V/Ω LO), jaw around the coil
    These two are named in the spec (specs/fluke_365_pv.json, groups COIL_AUX / COIL_20A, key 'diagram'), not looked up per calibrator.

The meter dial has no picture (the 365 dial positions are symbols only; see NOTES.md, Fluke 365).
