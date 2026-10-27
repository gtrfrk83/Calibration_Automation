Keysight U1251B / U1252B handheld multimeter hook-up pictures
==============================================================
The procedures show a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for. Nothing here is drawn by the program:
the pictures are supplied by the lab (no picture is invented).  One set of pictures serves both launchers (Keysight_U1251B_Verification, Keysight_U1252B_Verification).

Jacks of the meter (User's and Service Guide Figure 1-9 and Table 1-10, printed p. 47), left to right: A (10 A, fused 11 A), "uA mA" (also CHG / OUT on the U1252B; fused 440 mA), COM, and
"Ohm V mV" (also temperature, diode, capacitance, frequency).  The red lead uses "Ohm V mV" for voltage, mV, ohms, nS, diode, capacitance and temperature, "uA mA" for the microamp / milliamp
points and "A" for the 5 A and 10 A points; the black lead is always COM.

Files needed (one per calibrator and group; hookups.py, meter key 'u1251b'):
    hook_u1251b_5560A_VOHM.png     Fluke 5560A  OUTPUT V/Ω HI -> meter Ω V mV (red),  OUTPUT V/Ω LO -> meter COM (black)
    hook_u1251b_5522A_VOHM.png     Fluke 5522A  NORMAL HI -> meter Ω V mV (red),  NORMAL LO -> meter COM (black)
                                   Used for AC / DC volts, mV, ohms (2-wire compensation on the calibrator, note [o]), nS, diode, capacitance, frequency and duty cycle (group VOHM).
    hook_u1251b_5560A_UAMP.png     Fluke 5560A  VI AUX -> meter uA mA (red),  OUTPUT V/Ω LO -> COM (black)
    hook_u1251b_5522A_UAMP.png     Fluke 5522A  AUX HI -> meter uA mA (red),  AUX LO -> COM (black)       (group UAMP: uA and mA, AC and DC)
    hook_u1251b_5560A_AMP10.png    Fluke 5560A  30A -> meter A (red),  OUTPUT V/Ω LO -> COM (black)
    hook_u1251b_5522A_AMP10.png    Fluke 5522A  20 A -> meter A (red),  AUX LO -> COM (black)             (group AMP10: 5 A and 10 A, AC and DC)
    hook_u1251b_TEMP.png           K-type thermocouple extension (miniature connector on both ends) from the calibrator TC output to the TC-to-banana adapter in the meter Ω V mV and COM jacks
                                   (named in the spec, group TEMP, not looked up per calibrator)

The hand-set points need no picture (the set-up window describes them): the frequency counter points (Keysight 33250A into the meter, U1252B) and the square wave output points (meter OUT jack to a
Keysight 53131A / 34410A, U1252B).

Reuse of existing pictures: the jack ORDER of the Fluke 287 / 289 meter (A, mA uA, COM, V Ohm) is the same as this meter's (A, uA mA, COM, Ohm V mV), so
hook_fluke28x_<5560A|5522A>_<VOHM|UAMP|AMP10>.png show the right wiring for this meter.  They carry the Fluke jack labels ("mA uA", "V Ohm"), which differ from the Keysight labels, so they are NOT used
automatically: copy and rename them to the names above only if that is acceptable.  The Fluke 287 / 289 OHM4 (4-wire) and TEMP pictures do not apply (these meters use a 2-wire ohms connection with
calibrator compensation, and a TC-to-banana adapter rather than the Fluke 80AK).
