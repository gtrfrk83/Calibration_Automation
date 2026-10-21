CALIBRATION SUITE - restyled (Manager v69)
==========================================

Folder layout (same as before, plus one new file):

  Calibration_Procedure_Manager.py   <- start here
  mdd_importer_v49.py                (unchanged)
  ui_theme.py                        (NEW - shared look and feel; must sit next to the Manager)
  labregistry.py, labregistry_ui.py  (NEW - asset history; lab_registry.sqlite3 is created beside them on first use)
  Procedures\
      Agilent_34401A.py              v54
      Fluke_8846A_Verification.py    v58
      Fluke_8846A_Adjustment.py      v57
      Fluke_87V.py                   v52
      WaveSurfer_WS4104HD.py         v51

Install: copy these files over the old ones (keep your calibration_procedures.sqlite3,
Backups\ and any checkpoint files). The database layout is unchanged.
Procedures also run on their own: they find ui_theme.py one folder up (or beside them).

Nothing in the instrument control, limits, pass/fail maths, safety prompts, database
tables or report contents was changed.

Grids: every procedure now lists all of its test points as soon as it opens (next point
highlighted); readings, results and pass/fail colours fill in as the run progresses.

Units and scaling
-----------------
Column headings no longer carry units. Each grid has a "Units" column instead, and values are
auto-scaled with SI prefixes (0.006 V is shown as 6 mV, 1,000,123 ohm as 1.000123 MOhm) using only as
many decimals as the limits need; readings get two extra digits so small errors stay visible.
Display only: stored results, checkpoints, exports, limits and pass/fail still use base units.
The Fluke 87V now runs on the shared handheld engine (see the Fluke 110-117 section): specs/fluke_87v_pv.json, built by
specs/build_87v_spec.py from the 87V MDD datasheet. All 51 MDD points keep their limits exactly as printed (as-found values are
still typed in the units shown). Three rows the MDD marks Pass/Fail but prints a numeric range for (open capacitance and the two
low-pass-filter rows) are recorded as numeric readings against that range. Rows with no input signal (open capacitance, 0 nS) and the
frequency-trigger and duty-cycle rows (3.4 Vpp / 50 %) have no automatic calibrator output: the program tells you what to set. The old
MDD-import screen, Excel export and its saved runs in the database are no longer used (the data stays in the database).

Asset history and per-asset results
-----------------------------------
Asset History tab (Manager): every PDF report you export is recorded (instrument ID, serial, procedure, technician, date, every point
with limits and as-found value). Pick an instrument, a report and a test point (double-click) to see its drift across reports as a % of the
tolerance used; 'Open report PDF' opens the saved file. The Instruments tab gains 'Last report' and 'Next due' columns (last report + the
interval entered for that instrument; overdue rows are red). Demo reports are never recorded; exporting the same file again replaces its record.
Launching a procedure from the Instruments tab now fills in the Instrument ID, and typing a known ID fills an empty Serial number and shows
the last report / next due date in the status bar.

WaveSurfer results are now saved per Instrument ID (dcv_checkpoint_v6_<ID>.json etc., like the other procedures). Press Enter or leave
the Instrument ID box to switch to that instrument's saved results; Run Pending, Rerun, Clear and the exports do this first, so a report
can never carry another instrument's results. Run Pending now needs an Instrument ID. The first time you enter an ID, results saved by an
earlier version (one set for every instrument) can be assigned to it; they are renamed, not deleted.

The history lives in lab_registry.sqlite3 (a new file, created beside the Manager on first use; copy it to back it up).
calibration_procedures.sqlite3 is unchanged and only read (serial number and interval of registered instruments).
Standards and their calibration due dates are not tracked here; the report dialog's standards rows are free text as before.

Report naming (all procedures with an Instrument ID): <Instrument ID>-MM-DD-YYYY.pdf, e.g. KT-001-10-20-2026.pdf. A slash cannot be
used in a Windows file name, so dashes separate the date. WaveSurfer: the five tabs are replaced by ONE results table, like the handheld and MDO4000C
procedures. Use the 'Show' lists to filter by function (RMS noise, DC voltage, input impedance, offset, bandwidth) and by status. 'Run Pending'
runs every untested point in the chosen function (or all functions, in order); 'Rerun Selected', 'Stop After This Point' and 'Clear function
results' work on the table; settle times, samples, channels and limits are under 'Test settings...'. CSV export was removed. PDF/Excel names
use the same pattern (a section export adds the section, e.g. WS-01-dcv-10-20-2026.pdf), the details dialog comes before the file dialog, a
Serial number field sits next to the Instrument ID, and the PDF is titled 'Calibration Data'. Saved checkpoints and report layout are unchanged.

Drivers
-------
The drivers/ folder (next to ui_theme.py) holds per-model instrument drivers with simulators and a
self-test. See drivers/README.txt. Run:  python -m drivers.selftest --sim


Spec-driven procedures (new)
----------------------------
specs/            Machine-readable performance-verification test points (see specs/README.txt).
procspec.py       Loads a spec and hands a procedure its numbered test points and limits.
Procedures/Keysight_34460A_Verification.py, _34461A_, _34465A_, _34470A_
                  Automated verification of each Truevolt DMM from ITS OWN tables in the Keysight Truevolt Operating and
                  Service Guide (pp. 504-520): 80 / 101 / 107 / 107 points (zero offsets, DC/AC volts and current,
                  resistance, frequency, 10 A where the model has it, optional capacitance). Shared engine:
                  truevolt_verification.py; drivers/keysight_truevolt.py for the meter, Fluke 5560A as the source.
                  Limits default to the 1-YEAR column (selectable: 24 hours / 90 days / 1 year / 2 years). Full test or
                  the Q quick check. Demo:  python Procedures/Keysight_34470A_Verification.py --demo
                  The 34460A has one set of terminals (no Front/Rear switch, no 10 A input), so it has no rear-panel
                  zero offsets and no terminal check. The specs were extracted from the PDF's own cell geometry
                 , so merged cells are exact; the 34465A result matches the earlier
                  hand-built spec point for point.

Procedures/Keysight_34970A_Verification.py  (RS-232)   and   Keysight_34972A_Verification.py  (USB)
                  Fully automated verification of the internal DMM of the 34970A / 34972A from the Keysight 34970A/34972A
                  Service Guide, Chapter 4, pp. 80-87: zero offset (shorted input, open current), DC volts, 4-wire ohms,
                  DC current, AC volts, AC current, frequency, plus optional 2-wire ohms and the optional AC tests (72 points).
                  The program configures the DMM for every point (function, range, 10 PLC / 3 Hz AC filter / 1 s frequency gate),
                  selects the multiplexer channel (34901A in the chosen slot, default slot 2 = channels 209/210/219/220/221; the
                  34902A is supported without the current tests), drives a Fluke 5560A or 5522A and reads the result.
                  34970A: RS-232 with a selectable COM port (Refresh ports), baud, data bits / parity and flow control (factory
                  default 57600, 8 bits no parity, XON/XOFF; set the same on the instrument under Interface > I/O Config).
                  34972A: USB (Find instruments lists the VISA resources).
                  Limits default to 1 YEAR (24 hours / 90 days selectable). A hook-up dialog (with a picture, if installed in
                  diagrams/, see diagrams/README_dacq.txt) appears whenever the wiring changes. Shared engine: dacq_verification.py;
                  driver: drivers/keysight_dacq.py; spec builder: specs/build_dacq_spec.py. Demo:
                  python Procedures/Keysight_34970A_Verification.py --demo
                  Not included: gain/offset ADJUSTMENT, relay contact resistance, thermocouple reference junction, 34907A.

Fluke 110 / 113 / 114 / 115 / 116 / 117 handheld meters (manual-reading procedures)
-------------------------------------------------------------------------------
Hook-up diagrams (all handheld meters: Fluke 110-117, Fluke 87V, Klein MM325)
  hookups.py holds the connection tables; specs/build_hookups.py (needs Pillow) draws diagrams/hook_<meter>_<calibrator>_<group>.png
  (24 pictures). The text and picture follow the Calibrator selector, because the two calibrators wire differently:
      voltage / ohms        5560A: OUTPUT V/ohm HI / LO            5522A: NORMAL HI / LO
      uA / mA               5560A: VI AUX + OUTPUT LO              5522A: AUX HI + AUX LO
      10 A                  5560A: 30A + OUTPUT LO                 5522A: 20 A + AUX LO
      thermocouple          TC connector                           TC connector
  The 5560A picture is drawn from a photograph of the real front panel; the terminals in use are lit green (voltage) or blue
  (current), as on the instrument. The 5522A picture is drawn from a photograph of the real terminal block (NORMAL and AUX columns, 20A, GUARD, SCOPE OUT, TRIG, TC); the 5522A does not light its terminals, so those in use are ringed in amber.
  The 5522A 20 A return (AUX LO) is confirmed by its Operators Manual (p. 4-7 and the current-output text: 3 A and above is sourced between 20A and AUX LO; below 3 A between AUX HI and AUX LO). The 5560A 30A return (OUTPUT LO) and the Fluke 116 uA input (VOhm jack) are inferred, not taken from a manual: verify.
  Calibrator choices: 5560A / 5522A automatic, or Manual (5560A front panel) / Manual (5522A front panel). The 87V procedure has a
  Calibrator selector, shows the hook-up when the connections change and has a "Hook-up diagram" button.

handheld_dmm.py   Shared engine for meters with no remote interface. For each point the program programs and enables the
                  calibrator (Fluke 5560A or 5522A over RS-232, or Manual mode where it only tells you what to set), then
                  a dialog asks you to type what the meter displays (yes/no questions for beeper, display, VoltAlert).
                  Limits are the manual's display-reading limits, compared exactly; readings are stored in base units.
specs/fluke_110_series_pv.json
                  Every step of Table 3 (110/114/115/116/117) and Table 4 (113) plus the display / backlight / keypad checks
                  and the 117 VoltAlert test, each tagged with the models it applies to (read from the page images).
Procedures/Fluke_110_Verification.py ... Fluke_117_Verification.py   one launcher per model (28 / 25 / 31 / 35 / 41 / 40 points).
                  Demo with:  python Procedures/Fluke_117_Verification.py --demo
Safety: calibrator to STANDBY before every setup and after every reading; error queue read after every programmed output
and the output is never enabled after a rejection; voltages above 100 V are ramped in 50 V steps 5 s apart (the manual's
footnote); wiring confirmation when the connection changes; extra confirmation at 500 V and above.
Not verified on real hardware: capacitance (OUT <n>NF/UF), thermocouple simulation (TC_TYPE K / OUT <t>CEL) and 10 A / uA
outputs. If the calibrator rejects a command the run stops with its error text; use Manual mode for that point.
The report's uncertainty comes from the scope's Generate entries; points the scope does not cover (temperature, display
checks) show N/A. Fuse test and battery replacement (p. 2-4) are not points.

PDF reports
-----------
report_pdf.py writes the 'Calibration Data' report: header strip (instrument, ID, serial, date), an overall PASS / OUT OF TOLERANCE verdict
listing any out-of-tolerance points, the table grouped by section (Description, Nominal, Tolerance -/+, UOM, As Found, OOT,
As Left, Uncertainty) with shaded rows and red-tinted OOT rows, and 'Page x of y' plus the instrument ID on every page. Demo data gets a diagonal watermark.
report_dialog.py asks for technician, temperature, humidity and up to three standards (remembered between runs).
The DMM procedures and the WaveSurfer have an 'Export Report (PDF)' button.
Header: Instrument, Instrument ID, Serial and report date only. Limits applied, Source, Procedure, Technician, Temperature and
Humidity are on the lab's cover certificate, so they are left off (report_pdf.HEADER_HIDDEN); so are the standards used and the
Performed by / Reviewed by / Date block and the footnote under the table (uncertainty source, method notes). Everything entered in
the report dialog is still saved in the asset history.
Needs reportlab:  py -m pip install reportlab   (embeds Arial when present so the micro sign always prints).
As Left shows 'Same' (no adjustment made). Uncertainty is blank until per-range uncertainties are supplied.

Uncertainty from the A2LA scope
-------------------------------
specs/a2la_1888_03_cmc.json   Calibration CMCs from the Applied Technical Services scope (A2LA Cert. 1888.03, rev. 07/07/2026):
                              DC V / DC I / resistance / capacitance / AC V / AC I "Generate" (source) and "Measure" entries,
                              frequency "Measure", and the oscilloscope entries. uncertainty.py looks a point up; report_pdf.py prints it in the Uncertainty
                              column with a footnote naming the certificate.
Rules: the DMM reports use the scope's "Generate" entries (the calibrator that supplies the stimulus), by the generated value
(never by the DMM range), multifunction-calibrator bands only: the scope's resistance Fixed Points list is NOT used (e.g. 100 ohm
= 24 uohm/ohm + 1.0 mohm = 3.4 mohm). Where the scope lists two calibrator sets that overlap, the larger CMC is used. Frequency has
only a Measure entry. uncertainty.Scope.dmm(..., basis='measure') gives the Measure value. Oscilloscope reports: oscilloscope DC / level-sine flatness
entries for the WaveSurfer; Resistance - Measure for scope input impedance. A point on the boundary of two bands takes the
LARGER CMC. Points the scope does not cover (RMS noise, DC current zero, 10 A AC) are left blank and counted in the footnote.
The value is the CMC (k = 2) and excludes the unit under test. The CSV exports are unchanged.
To update after a scope revision: replace specs/a2la_1888_03_cmc.json (see specs/README.txt).

Klein Tools MM325 (manual-ranging digital multimeter)
-----------------------------------------------------
Procedures/Klein_MM325_Verification.py   (engine: handheld_dmm.py; spec: specs/klein_mm325_pv.json; diagrams: diagrams/)
  18 points from the MM325 instruction manual (specifications p. 3, operation pp. 5-10): ONE point per range at 90 % of the range
  (DC V 180 mV / 1800 mV / 18 V / 180 V / 540 V, AC V 180 V / 540 V at 60 Hz, battery 8.1 V / 1.35 V, resistance 180 ohm ... 1.8 Mohm,
  DC current 180 uA / 18 mA / 180 mA / 9 A). Limits = +/-(% of reading + digits x resolution) from the manual's accuracy table,
  evaluated exactly at the applied value; the working is shown for every point. AC is applied at 60 Hz (the manual specifies 50-60 Hz).
  Calibrator: Fluke 5560A / 5522A (automatic) or Manual. The meter has no remote interface: you type the display reading.
  Prompts: before EVERY point a "Turn the dial to ..." dialog shows the dial with the target position marked (the calibrator is in
  STANDBY while you turn it); whenever the cables change a dialog shows a hook-up diagram (voltage / resistance / battery, uA / mA, 10 A) for the
  calibrator chosen (see "Hook-up diagrams" below). Confirmation before every output of 60 V or more. The 10 A point follows the manual's duty limit (p. 9): the output
  is switched off automatically 30 s after it is enabled, and the point cannot be rerun for 10 minutes.
  Not included: diode test and continuity (the manual states no tolerance). The manual lists a 200.0 ohm range but the dial has no
  200 ohm position (p. 5): the procedure uses the continuity position for it - confirm on your meter (specs/build_mm325.py, NOTES).
  Rebuild the spec and diagrams after editing the point table:  python3 specs/build_mm325.py   (needs Pillow; the procedure does not).
  Demo with:  python Procedures/Klein_MM325_Verification.py --demo

Tektronix MDO4000C (MDO4024C / 4034C / 4054C / 4104C)
-----------------------------------------------------
Procedures/Tektronix_MDO4000C_Verification.py   (engine: mdo4000c_verification.py; spec: specs/tektronix_mdo4000c_pv.json)
  Automated performance verification from the MDO4000C Specifications and Performance Verification manual (077-1178-01 Rev B),
  test record pp. 35-83, procedures pp. 85-143. The oscilloscope is connected by USB (VISA). The technician picks the model, the
  spectrum-analyzer option (None / SA3 / SA6) and ticks AFG, DVM, digital channels and TPA-N-PRE attached ("Read options from
  scope" pre-fills them from *OPT?); only the points that apply are listed and run (476 to 731 points, depending on the choice).
  Stimulus: Fluke 5560A (SCOPE DCV / LEVSINE / MEASR / square) for the analog tests; Fluke 96270A for the RF tests (phase noise,
  absolute amplitude, crosstalk, TPA check; a second RF source for third-order intermodulation); Agilent 33220A or 33250A for the
  400 ms time mark and for delta-time / DVM-frequency points the 5560A cannot make (below 50 kHz or above its leveled-sine limits:
  SOURCE_5560A in the engine). If the 5560A rejects a setting the program falls back to the generator, else the point is
  SKIPPED with the reason (never guessed). AFG tests read the AFG with a SCPI DMM / counter, or the technician types the reading.
  Every cable, terminator, instrument or front-panel change is a prompt; DC points of 50 V and above and every RF output need a
  confirmation; all outputs go to standby / OFF after each point and on any error or Stop.
  Math per point (worksheet values are kept in the checkpoint, CSV and the detail pane):
    DC gain      Vdiff = |Vneg_meas - Vpos_meas|; gain accuracy = (Vdiff - Vdiff_expected) / Vdiff_expected x 100 %
    Bandwidth    Gain = Vbw-pp / Vin-pp (Vin-pp at 50 kHz, Vbw-pp at the bandwidth frequency); must be >= 0.707
    Random noise RMS noise = SMV (sample mode) - AMV (16-average mode)
    Digital      Vs- (first static HIGH rising) and Vs+ (first static LOW falling) on a 10 mV grid, found by bisection; result = (Vs- + Vs+) / 2
    Abs. amp.    greatest (scope reference marker - reference level) over the frequency steps (96270A level, or a power meter if configured)
    DANL / phase noise  dBm (or dBc) per RBW minus 10 log10(RBW x ENBW_FACTOR); ENBW_FACTOR = 1.0 in the engine - set it to the
                 analyzer's noise bandwidth ratio if your RBW filter differs. The noise floor is the highest point of a running median
                 (spurs ignored); the spectrum is read as a waveform (RF_NORMal / RF_AVErage) and analysed in software.
    Time base    edge time at the delayed centre minus the 400 ms delay; generator accuracy must be >= 4x better than the limit.
  Uncertainty: points with no input signal show N/A. 5560A-sourced points use the A2LA scope; RF, generator and meter points use
  specs/mdo4000c_reference_cmc.json (rel x reading + abs per kind) and show N/A until you fill that file in.
  Manual inconsistencies handled (also shown in the point details): DVM frequency row printed as 180 MHz with limits 149.98-150.02
  MHz -> applied at 150 MHz; DVM AC 1 V/div row prints "2.450 mV" -> volts; delta-time tables are used per channel exactly as
  printed (a few single-digit differences exist between channels in the manual); the 50 ohm impedance test is run on every channel
  as the test record lists it; the 5 mV/div 50 ohm bandwidth point on the MDO4104C uses 500 MHz (footnote p. 99).
  NOT verified on real hardware: the Tektronix RF / digital-waveform / DVM / AFG / diagnostics SCPI strings (collected in
  drivers/tektronix_mdo4000c.py, RF{} at the top) and the 5560A SCOPE SQUARE mode. The 96270A commands (RF_CMD in
  drivers/reference_instruments.py) were checked against the 96000 Series Remote Programmers Manual (Rev. 2) but have not yet
  been run on a real 96270A. Every write is checked through the instrument's event queue, so a wrong command stops the run with the
  instrument's message. Run the simulated bench (drivers/simulated_mdo.py) or demo mode first.

Keysight 33210A / Agilent 33220A / Agilent 33250A function generators
---------------------------------------------------------------------
Procedures/Keysight_33210A_Verification.py, Agilent_33220A_Verification.py, Agilent_33250A_Verification.py
  (engine: fgen_verification.py; specs: specs/keysight_33210a_pv.json / _33220a_ / _33250a_, written by specs/build_fgen_spec.py)
  Automated performance verification from Chapter 4 of each Service Guide (33210A pp. 62-77, 33220A pp. 58-72, 33250A pp. 53-67):
  self-test, internal timebase, AC amplitude (High Z, 1 kHz), low-frequency flatness (100 kHz), and 0 / +10 / +20 dB range flatness
  (39 points for the 33210A, 54 for the 33220A and 33250A; Quick check = the manual's Q points). Default limits 1 year; the
  33210A / 33220A timebase is +/-100 Hz at 90 days and +/-200 Hz at 1 year, the 33250A +/-20 Hz.
  Instruments: the generator (USB / GPIB / LAN; RS-232 on the 33250A), a Fluke 5790B (GPIB, USB, LAN or RS-232) for AC amplitude
  and low-frequency flatness in place of the 3458A the manual lists, a frequency counter, and for flatness either the 5790B
  WIDEBAND input or an RF power meter with sensor and a -20 dB attenuator. A 53131A / 53132A counter is recognised from *IDN?
  and set up by the program (drivers/keysight_5313x.py: channel 1, 50 ohm, AC, 1 s gate, expected frequency, each read back);
  Counter timebase ('Timebase', default External 10 MHz (GPS)): the program selects EXT, tests Ref In with ROSC:EXT:CHEC ONCE
  (error +2009 stops the run: no valid reference), leaves CHECk ON so a reference lost during the reading also stops it, and
  confirms 10 MHz with ROSC:EXT:FREQ?. The timebase row on the report states the counter timebase used. Choose Internal
  timebase only when no external reference is fitted. A generic counter's timebase is not checked (recorded as such). Leave the counter or power meter address blank to type
  its readings when asked.
  Flatness method ('Flatness with', 33210A and 33220A; default 5790B wideband): the 5790B WIDEBAND input (option /3, /5 or /AF,
  50 ohm, up to 7 V) measures each point directly relative to 1 kHz at the same dBm setting with the range locked:
  20 log(V(f) / V(1 kHz)), the method in the 5790B Operators Manual pp. 4-31 / 4-32. One cable for all three ranges, no attenuator
  (+23.9 dBm is 3.5 V rms), no power meter and no worksheet offsets. The program checks *OPT? for the option and that the /AF
  50 MHz cable correction is off (WBAF?, read only). Wideband flatness spec (pp. 1-20 to 1-22, 1 year, relative to 1 kHz):
  0.03 to 0.05 % to 2 MHz, 0.1 % to 10 MHz, 0.15 % to 20 MHz (0.013 dB) on the 700 mV to 7 V ranges used here. The 33250A
  (80 MHz) keeps the power meter. Each flatness result records the method; the report header and footnote state it.
  Power-meter method - worksheet maths (manual p. 63 / 67 / 59): offset_N = 10 log(5 V100k^2) - 10 log(5 V1k^2) from the 5790B readings at 670 mV, 2 V and
  7 V; each flatness point = P(f) - P(100 kHz) + offset_N, which is what the power meter shows in Relative Power mode with that
  offset entered. The 100 kHz reference is read at the start of each flatness section in every run. Flatness points need their
  reference points recorded first; re-running a reference point warns that the flatness results using it must be re-run.
  Safety: the generator output is OFF while every setting is made (APPLy is not used because it turns the output on), switched ON
  only to measure and OFF after every point and before every wiring prompt, each switch confirmed with OUTP?. The +20 dB range
  (+23.9 dBm) stops if the power meter reads above +10 dBm at the 100 kHz reference (attenuator missing).
  5790B loading: the 7 V range input is 50 kOhm (5790B manual Table 4-4), so the 7 Vrms points read about 0.1 % lower than with
  the manual's 1 MOhm DMM (about 10 % of the +/-70.7 mV limit). No correction is applied; the point details say so.
  Uncertainty: AC amplitude / LF flatness use the A2LA scope's AC Voltage - Measure entry, the timebase Frequency - Measure; RF
  flatness uses specs/fgen_332xx_reference_cmc.json and shows blank until you fill it in.
  Hook-up diagrams (optional): diagrams/hook_332xx_<GROUP>.png with GROUP = NONE, COUNTER, STD, WBND, POWER, POWER_ATT; shown in the wiring
  prompt when present.
  NOT verified on real hardware: every command in drivers/fluke_5790b.py and drivers/keysight_332xx.py (taken from the manuals; the
  WBAF? reply format is not documented - the manual has no detail page for it), the
  power-meter query (drivers.ReferenceMeter: MEASure:POWer?, no manual supplied), any counter other than a 53131A / 53132A
  (generic MEASure:FREQuency?), and the
  33250A RS-232 line endings. Run demo mode and the simulated bench (drivers/simulated_fgen.py) first.

Fluke 287 / 289 (handheld engine, with optional IR readings)
------------------------------------------------------------
Procedures/Fluke_287_Verification.py and Fluke_289_Verification.py   (engine: handheld_dmm.py; spec: specs/fluke_287_289_pv.json,
  built by specs/build_28x_spec.py from the 287/289 Calibration Manual, Performance Tests pp. 14-20: functional checks, Table 3
  temperature, Table 4; 72 points for the 289, 67 for the 287 - the 287 has no Low Pass, LoΩ or LoZ steps).
  The calibrator (5560A / 5522A, or by hand) is set for you, as in the other handheld procedures. 'Meter reading':
    Type the reading          - you read the display and type it in (no cable needed).
    Read over IR              - with the Fluke IR-to-USB cable (P/N 2166275) on the meter's IR port, COM port in 'IR cable port'.
                                For each point the program reads the display (QDDA), checks the reading unit, the range named in the
                                table, REL on / off, Low Pass on / off and, for temperature, that the offset is 000.0; waits for three
                                readings within 2 display counts; records the value at the meter's resolution, judged exactly like a
                                typed value. A wrong set-up puts the calibrator in STANDBY and shows what to fix: Re-check, Type the
                                reading instead, Skip or Stop. The IR port functional check is done automatically from ID.
  REL offsets (the table's grey rows) are prompts: steps 2, 11 and 46 apply 0 mV / 0 ohm and ask you to press REL when stable; step 42
  zeroes with the leads removed. Steps 25, 29 and 41 (950 kHz levsine, 15 % duty square, square with offset) are set on the calibrator
  by hand. Ohms steps 10-14 and LoΩ: set 2-wire COMP on the calibrator yourself (prompted). LoZ 120 V is reached through 60 V.
  The report footer says how many readings came over IR and how many were typed.
  The IR interface only reads: the program never sends the reset commands (DS, RI, RMP), so it never changes the meter's settings or memory.
  NOT verified on real hardware: the IR protocol (Fluke states it does not support that document), the QDDA function / range codes used
  for the checks, and the calibrator outputs for capacitance and thermocouple.
