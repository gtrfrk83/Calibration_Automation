Keithley Model 2000 hook-up diagrams
====================================
The procedure shows a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for.

File name:   hook_k2000_<calibrator>_<GROUP>.png      e.g. hook_k2000_5560A_DCV.png
Shared:      hook_k2000_<GROUP>.png                    used for both calibrators when there is no calibrator-specific file
Search order: hook_k2000_<cal>_<G>  ->  hook_k2000_<G>

<calibrator> = 5560A or 5522A

GROUP (one picture per separate hook-up; the numbers are the Calibration Manual figures)
  DCV       calibrator voltage to the 2000 INPUT HI / LO (Figure 1-1); low-thermal connections for the 100 mV and 1 V ranges; also the 0 mV REL zero
  ACV       calibrator AC voltage to the 2000 INPUT HI / LO (Figure 1-2); shielded cable
  DCI       calibrator current to the 2000 AMPS and INPUT LO jacks (Figure 1-3)
  ACI       calibrator AC current to the 2000 AMPS and INPUT LO jacks (Figure 1-4)
  OHM4      4-wire resistance: force to INPUT HI / LO, sense to the SENSE Ohms 4 WIRE HI / LO jacks (Figure 1-5); calibrator external sense ON
  OHM100M   100 Mohm, pure 2-wire (lab decision): calibrator output to the 2000 INPUT HI / LO only, NO sense leads, calibrator external sense OFF
            (5522A ZCOMP NONE; 5560A 2-wire mode); the 2000 is on its 2-wire resistance function. The manual's Figure 1-6 shows the SENSE jacks wired: do not copy that.

The 2000 INPUTS switch must be on FRONT for every point; the program reads it (:SYST:FRSW?) before measuring.

ADJUSTMENT (Procedures/Keithley_2000_Adjustment.py)
---------------------------------------------------
The guided adjustment shows a picture at every change of wiring, with the same GROUPs plus the two front-terminal groups of the adjustment:
  SHORT     Keithley 8610 low-thermal shorting plug on the 2000 front INPUT HI / LO and SENSE jacks (Calibration Manual Figure 2-1)
  OPEN      all cables and accessories removed from the front jacks (p. 3-11); a picture is optional
  DCV / ACV / DCI / ACI / OHM4   as above, adjustment figures 2-2 (voltage and 4-wire ohms), 2-3 (current), 2-4 (AC voltage); calibrator external sense OFF for DC volts (p. 2-9), ON for all resistance steps (p. 2-10)
Search order: hook_k2000_ADJ_<cal>_<G>  ->  hook_k2000_ADJ_<G>  ->  hook_k2000_<cal>_<G>  ->  hook_k2000_<G>   (the verification pictures are used when no ADJ picture exists)
