Fluke 753 / 754 Documenting Process Calibrator hook-up diagrams
==============================================================
The procedures (Fluke_753_Verification, Fluke_754_Verification) show a picture each time the wiring changes. A missing picture does not stop a run: the dialog then shows the owner's terminal photo
(fluke_753_754_terminals.png, then fluke_753_754_front.png) and the text instructions.

Owner-supplied photos (instrument reference pictures; hookups.METERS['fluke753']['panels'])
  fluke_753_754_front.png       front view of the 753 / 754 (display, keys, the jack block at the bottom)
  fluke_753_754_terminals.png   close-up of the jack block: top row  V Ω RTD (SOURCE side) | mA / mA Ω RTD (middle) | V (MEASURE side);
                                bottom row three commons (30 V MAX, 50 V MAX, CAT II 300 V MAX); the TC mini-jack at the lower left.

Per-hook-up diagrams (one calibrator-independent picture per group of specs/fluke_753_754_pv.json; drawn by specs/build_hookups_753.py with Pillow from the terminal photo and the
Calibration Manual's figures; the procedures themselves do not need Pillow)
  hook_fluke753_<GROUP>.png     the spec's own groups carry the diagram path (the manual's calibrator is the 5522A; the box text names the 5522A and the 5560A terminal)
  GROUP            figure (printed page)       UUT jacks
  MEAS_V           Figures 1 and 4  (11, 16)   top-right V + bottom-right common (UUT measures V / Hz)
  MEAS_MA          Figure 2         (13)       middle mA jack + middle common (UUT measures mA)
  MEAS_OHM         Figure 3         (15)       middle mA Ω RTD jack (two leads) + middle common (two leads)
  MEAS_TC          Figure 10        (24)       TC mini-jack (the manual sources mV through a lag bath; this procedure simulates Type K)
  MEAS_RTD4        Figure 11        (27)       middle + right top jacks, middle + right commons (four-wire)
  MEAS_RTD3        Figure 12        (28)       middle top jack, right top jack, right common, jumper between the two commons (three-wire)
  SRC_V            Figure 5         (17)       top-left V Ω RTD (SOURCE) + left common (UUT sources V)
  SRC_MA           Figure 6         (18)       middle mA jack + middle common (UUT sources mA)
  SRC_SIM          Figure 7         (19)       middle mA jack + middle common (simulate transmitter)
  SRC_OHM          Figure 8         (20)       left top jack (two leads) + left common (two leads) (UUT sources ohms / RTD)
  SRC_FREQ         Figure 9         (22)       left SOURCE jacks through a BNC adapter to the counter and the Fluke 123
  SRC_TC           Figure 10        (24)       TC mini-jack, Type K to the lag bath, the external DMM in place of the 5522A
  LOOP             Figure 13        (30)       middle mA jack + middle common (loop power, external DMM in volts)
  HART             Figure 15        (32)       middle mA jack + middle common (HART transmitter; 754 only)

Where each jack came from
  PHOTO  : the jack positions and the labels (SOURCE / MEASURE, V Ω RTD, mA, mA Ω RTD, V, the 30 V / 50 V / CAT II markings, the TC mini-jack).
  PDF    : which jack each lead uses, read from the 300 dpi page images of Figures 1-13 and 15.
  The two agree on the layout in every figure; nothing was assumed from the photo alone.
  Not clear in the PDF (UNVERIFIED, confirm on the bench): the two black leads of Figure 3 / Figure 11 (which common each uses), the lead on the V jack and the jumper in Figure 12,
  and the lead colours at the middle jacks in Figure 7.  Figure 5 / 6 / 8 name the SOURCE jacks only by their position (top-left jack and the common under it).
