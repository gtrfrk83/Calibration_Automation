Hook-up diagrams for the Keysight 53210A / 53220A / 53230A performance verification (supplied by Mike as PNGs in this folder; none has been drawn).

The procedure looks for, in this order:
    diagrams/hook_53220a_<SRC>_<GROUP>.png      SRC = 96270A (stimulus from the Fluke 96270A) or manual (stimulus from another standard)
    diagrams/hook_53220a_<GROUP>.png            one picture for either stimulus
When no file is found the hook-up prompt shows the written steps and names the file it expected.

GROUP names (one picture per wiring group):
    TIMEBASE     Test 1, internal time base: 10 MHz from the stimulus to Channel 1 (50 ohm); the stimulus and the house standard share the primary frequency standard
    CH1          Test 2a / 3 Channel 1: sine to Channel 1 (50 ohm, DC); 10 MHz reference to EXT REF IN
    CH2          Test 2b / 3 Channel 2: sine to Channel 2 (50 ohm, DC); 10 MHz reference to EXT REF IN
    CH3_LH       Tests 6a / 6b below 4 GHz: 96270A Leveling Head output to the microwave input (Channel 3; Channel 2 on the 53210A)
    CH3_MW       Tests 6a / 6b above 4 GHz (5.88 GHz, 15 GHz): 96270A Microwave O/P to the microwave input; for 6a at 5.88 GHz (-27 dBm) an external attenuator after the Microwave O/P
                 (the O/P cannot go below -4 dBm) and a power meter check of the level at the counter input (+/- 0.5 dBm) - draw the attenuator in
    PULSE_CH1    Test 4a: pulse generator (5 ns, 1 Vpp; the Agilent 33250A cannot make 5 ns, so an 81134A or equivalent) to Channel 1                          (SRC is always manual)
    PULSE_CH2    Test 4b: pulse generator to Channel 2                                         (manual)
    TINT         Test 5: pulse generator, both outputs, to Channel 1 and Channel 2 with equal cable lengths   (manual)
    BURST        Test 7 (53230A with Option 150): pulse-modulated microwave generator to the microwave input   (manual)

Examples:  hook_53220a_96270A_CH1.png   hook_53220a_96270A_CH3_MW.png   hook_53220a_manual_PULSE_CH1.png   hook_53220a_TIMEBASE.png

The Keysight 53230A and 53210A (same connectors) use the same pictures. For them the procedure looks first for
    diagrams/hook_53230a_<SRC>_<GROUP>.png, then diagrams/hook_53230a_<GROUP>.png     (53210A: hook_53210a_ ...)
then the hook_53220a_ names above, so a model-specific picture is optional. The 53220A procedure never looks for the other models' files.
The self-test (OV2) connects nothing and needs no picture.
