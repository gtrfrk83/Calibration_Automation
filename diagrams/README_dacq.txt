34970A / 34972A hook-up diagrams
================================
The procedures show a picture each time the wiring changes. Drop PNG files in this folder (any size; they are shown beside the instructions).
Missing pictures do not stop a run: the dialog shows the text instructions and names the file it looked for.

File name:   hook_<model>_<calibrator>_<GROUP>.png      e.g. hook_34970A_5560A_DCV.png
Shared:      hook_dacq_<calibrator>_<GROUP>.png          used for BOTH models when there is no model-specific file
             hook_<model>_<GROUP>.png / hook_dacq_<GROUP>.png   used for both calibrators when there is no calibrator-specific file
Search order: hook_<model>_<cal>_<G>  ->  hook_dacq_<cal>_<G>  ->  hook_<model>_<G>  ->  hook_dacq_<G>

<model> = 34970A or 34972A      <calibrator> = 5560A or 5522A

GROUP (one picture per separate hook-up)
  ZERO_SHORT   low-thermal copper shorts on the input channel (34901A ch 9, 34902A ch 7) and its 4-wire partner (ch 19 / 15); no calibrator
  ZERO_OPEN    current channel ch 21 left open; no calibrator
  DCV          calibrator voltage to the input channel (34901A ch 10, 34902A ch 8)
  OHM4         4-wire ohms: force to ch 10, sense to ch 20 (34902A: ch 8 / 16)
  OHM2         2-wire ohms to ch 10 (34902A ch 8)                           (only if "Include 2-wire ohms" is ticked)
  DCI          calibrator current to the current channel ch 21               (34901A only)
  ACV          calibrator AC voltage to the input channel (also used by the optional AC tests)
  ACI          calibrator AC current to ch 21                                (34901A only)
  FREQ         calibrator AC voltage (frequency test) to the input channel

34972A (owner, 2026-11-02): the DCV, ACV, FREQ, OHM4 and OHM2 groups use CHANNEL 1 of the module (34901A and 34902A), not ch 10 / ch 8, so its
DCV / ACV / FREQ pictures should show the calibrator on channel 1 (hook_34972A_<cal>_DCV.png etc. are used before the shared hook_dacq_ files).
The gain ohms groups OHM4 / OHM2 also use channel 1 on the 34972A (4-wire: force ch 1, sense ch 11). The zero shorts and the current hook-ups are unchanged. The 34970A is unchanged.

Channel numbers are slot*100 + channel; the program uses the module and slot chosen on screen (default 34901A in slot 2 = channels 209, 210, 219, 220, 221).
