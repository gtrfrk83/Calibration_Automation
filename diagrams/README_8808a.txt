Fluke 8808A hook-up diagrams
============================
The procedure shows a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for.

File name:   hook_8808A_<calibrator>_<GROUP>.png      e.g. hook_8808A_5522A_VOLT.png
Shared:      hook_8808A_<GROUP>.png                    used for both calibrators when there is no calibrator-specific file
Search order: hook_8808A_<cal>_<G>  ->  hook_8808A_<G>

<calibrator> = 5522A or 5560A

GROUP (one picture per separate hook-up; Calibration Manual Figures 3-1 to 3-5 show the manual's own set-ups)
  ZERO_SHORT   low-thermal 4-wire short (Fluke PN 2653346) across INPUT HI / LO and SENSE HI / LO; no calibrator (DC volts, 4-wire and 2-wire ohms zeros)
  ZERO_OPEN    mA and 10 A terminals left open; no calibrator (DC current zeros)
  VOLT         calibrator voltage to INPUT HI / LO (DC volts, AC volts, frequency); also used for the points measured with your own standard
  OHM4         4-wire ohms: calibrator output to INPUT HI / LO, calibrator SENSE to the meter SENSE 4W HI / LO (Figure 3-2)
  OHM2         2-wire ohms: calibrator output (with its sense) to INPUT HI / LO (Figure 3-3)
  IMA          calibrator current to the mA terminal and COM, ranges 200 uA to 200 mA (Figure 3-4)
  I2A          calibrator current to the 10 A terminal and COM, 2 A range (Figure 3-4)
  I10A         calibrator current to the 10 A terminal and COM, 10 A range (Figure 3-5)
