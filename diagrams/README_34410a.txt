Hook-up diagrams for the Keysight 34410A performance verification (supplied by Mike as PNGs in this folder; none has been drawn).

The procedure looks for, in this order:
    diagrams/hook_34410a_<CAL>_<GROUP>.png      CAL = 5560A or 5522A (a 5520A uses the 5522A picture)
    diagrams/hook_34410a_<GROUP>.png            one picture for any calibrator
When no file is found the hook-up prompt shows the written steps and names the file it expected.

GROUP names (one picture per wiring group):
    ZERO_SHORT   34172B low-thermal 4-terminal short across INPUT HI/LO and SENSE HI/LO (front and rear sets); calibrator in STANDBY
    ZERO_OPEN    current (I) input open, nothing connected (front and rear sets)
    DCV          DC volts: calibrator output to INPUT HI/LO, low-thermal leads on 100 mV and 1 V
    ACV          AC volts: calibrator output to INPUT HI/LO, shielded twisted pair
    DCI          DC current: calibrator current output to the 3 A (I) terminal and INPUT LO
    ACI          AC current: same terminals as DCI
    OHM4         4-wire ohms: output to INPUT HI/LO, calibrator sense to the 34410A SENSE HI/LO
    OHM2         2-wire ohms, 100 Mohm: output to INPUT HI/LO, calibrator external sense off
    FREQ         frequency: calibrator AC voltage output to INPUT HI/LO
    CAP          capacitance (optional): the capacitance standard on INPUT HI/LO

Examples:  hook_34410a_5560A_DCV.png   hook_34410a_5522A_OHM4.png   hook_34410a_ZERO_SHORT.png
