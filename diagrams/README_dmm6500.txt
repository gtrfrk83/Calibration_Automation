Keithley DMM6500 hook-up diagrams
=================================
The procedure shows a picture each time the wiring group changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for.

File name:   hook_dmm6500_<calibrator>_<GROUP>.png      e.g. hook_dmm6500_5560A_DCV.png
Shared:      hook_dmm6500_<GROUP>.png                    used for every calibrator when there is no calibrator-specific file
Search order: hook_dmm6500_<cal>_<G>  ->  hook_dmm6500_<G>        <calibrator> = 5560A or 5522A (a 5520A uses the 5522A picture)

Front panel photo supplied by the owner: diagrams/dmm6500_panel.png (INPUT HI / LO, SENSE Omega 4 WIRE HI / LO, AMPS 3A jack, TERMINALS FRONT / REAR button; the 10 A jack is on the rear).

GROUP (one picture per separate hook-up; the numbers are the Calibration Manual figures)
  DCV      calibrator voltage to INPUT HI / LO, low-thermal, shield to the calibrator LO (Figure 1); also the digitize voltage points (Figure 4)
  ACV      calibrator AC voltage to INPUT HI / LO, low-capacitance cable (Figure 2)
  ACV750   the 740 V points; the manual puts a 5725A amplifier behind the calibrator for 50 kHz and 100 kHz (Figure 3)
  FREQ     calibrator AC voltage to INPUT HI / LO (the manual uses a 3390 generator, Figure 5)
  TC       DC voltage source for the type J table values, low-thermal (Figure 6)
  RTD4     4-wire PT100 simulation: force to INPUT HI / LO, sense to SENSE HI / LO (Figure 7), calibrator external sense ON
  RTD3     3-wire PT100 simulation: SENSE HI not used (Figure 8)
  SHORT4   Keithley 8610 / 8620 4-wire short on INPUT and SENSE HI / LO, orientation as Figure 17; no calibrator
  OHM4     4-wire resistance: force to INPUT HI / LO, sense to SENSE HI / LO (Figure 9); with the 3458A in the loop for the 1 ohm and 10 ohm points
  OHM2     2-wire resistance, INPUT HI / LO only, no sense leads (Figure 10)
  DCI_LOW  calibrator current to AMPS 3A and INPUT LO with the 3458A (current function) in series, 10 uA to 10 mA (Figure 11)
  DCI      calibrator current to AMPS 3A and INPUT LO, 100 mA to 3 A (Figure 12)
  DIGI     the same as DCI, digitize current (Figure 13)
  ACI      calibrator AC current to AMPS 3A and INPUT LO (Figure 14)
  REAR10A  TERMINALS on REAR; calibrator current output (with the amplifier in the manual) to the rear 10A AMPS jack and INPUT LO, heavy short cables (Figures 18 to 20)
  CAP      calibrator capacitance output (owner decision 2026-11-03) to INPUT HI / LO with a short shielded cable; first the cable alone with the calibrator in standby

The TERMINALS switch cannot be set remotely: the program reads it (:ROUT:TERM?) before measuring and stops if it is not where the point needs it.
