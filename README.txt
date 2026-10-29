CALIBRATION SUITE - restyled (Manager v70 Beta 2)
==========================================

BETA 1: own data folder (see USER_GUIDE.txt), Help menu, friendly error window with diagnostic log, icon, Start_Calibration_Suite.bat.
New files to copy with it: suite_info.py, appdata.py, diagnostics.py, branding.py, assets\\, USER_GUIDE.txt.

NEW in v70: As Found / As Left toggle in every verification procedure, 'Run Shown Section' button, shorter buttons that wrap in
small windows, and Save / Load progress / Export buttons moved to the bottom bar. New file: datamode.py (copy it beside ui_theme.py).
If nothing was adjusted, leave the toggle on As Found: the report prints 'Same' under As Left as before.

Folder layout (same as before, plus one new file):

  00_START_Calibration_Suite.bat     <- start here (runs Calibration_Procedure_Manager_qt.py; the suite is Qt only, needs PySide6)
  mdd_importer_v49.py                (unchanged)
  ui_theme_core.py                   (shared helpers: SI formatting, Settings, report names; no GUI)
  datamode.py                        (NEW - As Found / As Left toggle; must sit next to the Manager)
  labregistry.py, labregistry_ui.py  (NEW - asset history; lab_registry.sqlite3 is created beside them on first use)
  instrument_scan.py, instrument_scan_ui.py  (NEW - 'Find instruments...' button in the Manager: which VISA resource / GPIB channel each instrument is on; read-only identity queries only)
  Procedures\
      Agilent_34401A.py              v54
      Fluke_8846A_Verification.py    v58
      Fluke_8846A_Adjustment.py      v57
      WaveSurfer_WS4104HD.py         v56

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
The Fluke 87V procedure built from the MDD datasheet was replaced (2026-10-28) by the Fluke 83V / 87V / 88V procedures built from the
80 Series V Calibration Manual: see 'Fluke 83V / 87V / 88V' below.

Asset history and per-asset results
-----------------------------------
Asset History tab (Manager): every PDF report you export is recorded (instrument ID, serial, procedure, technician, date, every point
with limits and as-found value). Pick an instrument, a report and a test point (double-click) to see its drift across reports as a % of the
tolerance used; 'Open report PDF' opens the saved file. (The Manager's Instruments tab, which showed 'Last report' and 'Next due', was removed:
assets are tracked in other software.) Demo reports are never recorded; exporting the same file again replaces its record.
Typing a known Instrument ID in a procedure window fills an empty Serial number and shows the last report / next due date in the status bar.

WaveSurfer v56: the trigger level uncertainty is now the laboratory's DC voltage CMC (A2LA scope, 1 MOhm: 0.06 % of the level + 40 uV)
  at the DC voltage the Fluke sources for the point. The two bracket steps (20 mV short of and 20 mV past the trigger level) decide
  pass/fail, so the larger of the two is used: 52 uV for the 0 mV points, 232 uV for the +/-300 mV points. It is the uncertainty of the
  sourced voltage only; it does not include the scope's trigger noise or resolution, so it is much smaller than the figures on the
  old data sheet (11 mV and 17 mV).

WaveSurfer v55: the time base test reported '5560A rejected the setting (SCOPE MARKER): -117'. ERR? returns the OLDEST
  error, and nothing had read the 5560A queue before, so an error left from an earlier session was blamed on SCOPE MARKER
  (the 5560A reports SCOPE? = MARKER in time-marker mode). The queue is now read out first (read-only ERR?, every reply in the
  command log, old errors saved with the result); only a fresh error after SCOPE MARKER stops the test.

WaveSurfer v54: the time base test stopped at 'P1 engine Frequency, expected Freq'. The 4104HD reports the frequency
  measurement by its long name; 'Frequency' is now accepted, as 'PeakToPeak' already was for PkPk. Nothing else changed.

WaveSurfer v53: two new functions in the results table, with limits from the HAZ-OSC-02 data sheet (pages 10-11, read from the page images).
  Time base (1 point): Fluke 5560A SCOPE MARKER into CH1 at DC 50 Ohm, scope P1 Freq averaged; frequency error limit +/-0.350 Hz. The marker
  period is in Test settings (default 10 us = 100 kHz; the data sheet does not state it) and is saved with the result and printed on the report.
  Trigger level (24 points): CH1-CH4 x 0 / +300 / -300 mV x positive and negative slope, +/-20 mV, at 100 mV/div DC 1 MOhm 20 MHz BW. Bracket
  test: the scope is armed in Single at the level, the Fluke steps from 100 mV before the level to 20 mV short (must not trigger) and then 20 mV
  past (must trigger); the technician answers both prompts. The report shows 'Within +/-20 mV' (no trigger voltage is measured). The Fluke output
  is at most 0.4 V and returns to STBY after every point. Time base uncertainty is left blank (no A2LA scope entry).
  NOT yet verified on hardware: 5560A SCOPE MARKER / OUT <period>S and the scope VBS Trigger.Edge.Slope, Trigger.Edge.Level and TriggerMode.
  Each is read back, and the output is never enabled after a rejected or unexpected reply. Check the first point of each on screen.
  Input impedance fix: the channel points passed 'C1' to the VBS scale setter, which asked the scope for app.Acquisition.CC1 and failed with
  "could not convert string to float". The setter now takes the channel number and refuses anything other than 1-4; a non-numeric scope reply
  now gives a clear error naming the property.

WaveSurfer v52: the scope now waits 0.4 s after each coupling and bandwidth-limit change before its next command (a query sent
immediately after the relay change could leave the USB session stuck with VI_ERROR_IO while the scope itself kept working).
If a read-only scope query still fails, the session gets a device clear before the 2nd try and is closed and reopened before
the 3rd; both steps appear in the command log. Writes are never repeated. Commands, limits, pass/fail and safety prompts are unchanged.

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

Procedures/Keithley_2000_Verification.py
                  Two-way verification of the Keithley Model 2000 6.5-digit multimeter from the Model 2000 Calibration Manual (2000-905-01 Rev. F),
                  section 1, Tables 1-2 to 1-6: DC volts, AC volts, DC current, AC current, 4-wire resistance and 100 Mohm (38 points, the optional
                  700 V at 50 kHz needs a 5725A amplifier and is sourced by hand). The program sets function, range, speed and filter over GPIB
                  (address 16) or RS-232 (SCPI, 4800 baud by default), drives a Fluke 5560A or 5522A, reads each result with :READ?, judges it against
                  the printed 1-year limits and writes the 'Calibration Data' report. Warm-up (1 hour) and a hook-up dialog (pictures per
                  diagrams/README_k2000.txt) are confirmed before the run. Engine: keithley2000_verification.py; driver: drivers/keithley_2000.py;
                  spec builder: specs/build_k2000_spec.py. Demo (virtual instruments): python Procedures/Keithley_2000_Verification.py --demo
                  Not included: the adjustment (see Procedures/Keithley_2000_Adjustment.py).

Procedures/Keithley_2000_Adjustment.py
                  Guided ADJUSTMENT (calibration) of the Keithley Model 2000 by the remote :CAL:PROT commands of the Calibration Manual (2000-905-01
                  Rev. F, pp. 2-14 to 2-19): 13 DC steps (front short and open, +10 V, -10 V, +100 V, 4-wire 1 kohm to 10 Mohm, 10 mA to 1 A) and 13 AC steps
                  (10 mV to 700 V at 1 kHz and 50 kHz, 100 mA to 2 A) in the manual's order, with a Fluke 5560A, 5522A or 5520A as the source (the manual's
                  Table 2-1 ratios are shown in the window: the 5522A and 5520A meet none, the 5560A four of the 24). Category 'Digital Multimeter Adjustment',
                  sidecar kind 'adjustment' (Adjustments tab). THIS CHANGES THE INSTRUMENT CALIBRATION: both instruments are reset first, the operator
                  confirms warm-up, the As Found verification and authority, then types the calibration code (asked at run time, sent once, NEVER stored,
                  logged or written to the audit record). Every step asks for the hook-up, programs and reads back the calibrator, waits to settle, asks again
                  and sends the command ONCE (never repeated automatically); the calibrator goes to standby after each step. Nothing is stored in the
                  2000 until the dates are set and 'SAVE 2000' is typed; an abort before that leaves the stored constants unchanged. Audit record: new
                  tables in lab_registry.sqlite3 (a demo run writes nothing). Not built: manufacturing calibration, the front-panel method, a PDF record.
                  Engine: keithley2000_adjustment.py + adjustment_audit.py; driver: drivers/keithley_2000_cal.py; spec: specs/keithley_2000_adjustment.json
                  (specs/build_k2000_adjustment_spec.py). Demo (simulated meter, nothing saved): python Procedures/Keithley_2000_Adjustment.py --demo

Procedures/Fluke_8808A_Adjustment.py
                  Guided ADJUSTMENT (calibration) of the Fluke 8808A by the RS-232 calibration dialog of the Calibration Manual (Oct 2008, pp. 3-16 / 3-17,
                  Table 3-9): 124 steps in the manual's order (DC volts 21, AC volts 21, frequency 12, resistance 28, AC current 17, DC current 25) with a Fluke
                  5522A, 5560A or 5520A as the source (one point, 1.9 V at 750 kHz, needs your own standard; the zero ohm point uses the 4-wire short). Category
                  'Digital Multimeter Adjustment', sidecar kind 'adjustment' (Adjustments tab). THIS CHANGES THE INSTRUMENT CALIBRATION. YOU enter the calibration
                  mode at the 8808A front panel with the calibration button and confirm it; the program sends nothing to enter it (an optional, UNVERIFIED
                  *TER is off by default; if the meter does not answer the first function name the program offers ONE operator-confirmed *TER, UNVERIFIED) and checks it only when the meter answers the first function name. The manual has no password, SAVE or lock for the
                  8808A, so every function start and EVERY POINT is confirmed by the operator, the calibrator's output is programmed, read back and operated for
                  each point, and the meter's Enter key is sent ONCE per point (never repeated automatically); the calibrator goes to standby after each point.
                  The meter's own recommended value is compared with the manual (seven first-gain points differ between Table 3-9 and the Calibration Points
                  lists; the default is to follow the meter); the four characterized DC current ranges ask for the value measured with your Keysight 3458A
                  (CALREF; recorded in the audit as source '3458A characterised'). Audit record: tables in lab_registry.sqlite3 only (a demo run writes nothing); no PDF record. No hook-up pictures are used (text
                  wording only). Run the performance verification before (As Found) and after (As Left): this program does not. Not built: the front-panel
                  keystroke method. Engine: fluke8808a_adjustment.py + adjustment_audit.py; driver: drivers/fluke_8808a_cal.py; spec:
                  specs/fluke_8808a_adjustment.json (specs/build_8808a_adjustment.py). Demo (simulated meter, nothing saved):
                  python Procedures/Fluke_8808A_Adjustment.py --demo

Procedures/Agilent_34410A_Verification.py
                  Two-way verification of the Agilent / Keysight 34410A 6.5-digit multimeter from the 34410A/11A/L4411A Service Guide, chapter 3
                  Verification Tests (printed pp. 68-87): zero offset (front and rear terminals), DC volts, DC current, resistance, frequency, AC volts and AC
                  current (86 points; the optional extra AC volts, AC current and capacitance tests are tick-boxes). The meter is connected over GPIB
                  (address 22) or USB (a VISA resource string); the choice and an address for each are remembered. The program sets function, range, 100 NPLC or
                  the 3 Hz AC filter, drives a Fluke 5560A, 5522A or 5520A, reads each result with READ?, and judges it against the printed 24 hour, 90 day or
                  1 year limits (1 year by default). It reads the Front/Rear switch before every point (it cannot be set remotely). Hook-up pictures per
                  diagrams/README_34410a.txt. Engine: agilent34410a_verification.py; driver: drivers/keysight_34410a.py; spec builder: specs/build_34410a_spec.py;
                  calibrator suitability (TAR / TUR): specs/34410a_standards_suitability.md. Demo (virtual instruments):
                  python Procedures/Agilent_34410A_Verification.py --demo      Not included: adjustment, self-test.

Procedures/Agilent_34411A_Verification.py
                  The same procedure for the Agilent / Keysight 34411A (a model of the 34410A family: the Service Guide tables are headed "34410A/11A" and are the
                  same for both, so one spec, one engine and one driver module serve both; the launcher only selects the model). 103 points, 86 by default, GPIB or USB,
                  Fluke 5560A / 5522A / 5520A, same limits. The 34411A-only features (digitizing, pre-trigger, 1 million readings of memory) are not part of the
                  verification and are not used. Hook-up pictures: diagrams/hook_34411a_* first, then the 34410A names (README_34410a.txt).
                  Demo: python Procedures/Agilent_34411A_Verification.py --demo      Not included: the L4411A (no Front/Rear switch), adjustment, self-test.

Fluke 110 / 113 / 114 / 115 / 116 / 117 handheld meters (manual-reading procedures)
-------------------------------------------------------------------------------
Hook-up diagrams (all handheld meters: Fluke 110-117, Fluke 87V, Fluke 77 Series IV, Fluke 175 / 177 / 179, Fluke 365 (names in diagrams/README_fluke365.txt), Fluke 376 (names in diagrams/README_fluke376.txt), Klein MM325)
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
iflex_option.py   Subclass of the engine for the Fluke 374 / 375 / 376 / 376-II clamp meters: the window option "iFlex probe supplied: run the iFlex tests"
                  (a spec's options.include_toggles; a spec without it runs as the engine does). Not used by any other procedure.
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
The value is the CMC (k = 2) and excludes the unit under test.
Coil lines (5500A/COIL DC rows, Clamp-On Only AC rows, transconductance amplifier/coil AC rows, scope pp. 9 and 30) are in the table too, so currents above 30.2 A are covered
(added by specs/build_a2la_cmc_coil_rows.py; the same lines are standards sheets A2LA-5500A-COIL and A2LA-CURRENT-AMP-COIL).
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

Fluke Model 77 Series IV (autoranging handheld multimeter)
----------------------------------------------------------
Procedures/Fluke_77IV_Verification.py   (engine: handheld_dmm.py; spec: specs/fluke_77iv_pv.json built by specs/build_77_spec.py; diagrams: diagrams/hook_fluke77_*)
  35 steps = Table 2 "Performance Tests" of the Model 77 Series IV Calibration Information (printed pp. 12-13): ohms 5 (500 ohm ... 40 Mohm), continuity 2
  (25 ohm beeper on / 250 ohm beeper off), AC volts 9 (50 mV 45 Hz; 5 / 50 / 500 / 1000 V at 45 Hz and 1 kHz), AC volts frequency 1 (5 V 50 kHz),
  DC volts 4 (5 / 300 / 1000 / -1000 V), DC millivolts 3 (30 / -300 / 600 mV), capacitance 1 (900 nF), AC milliamps 3, AC amps 2, DC milliamps 3, DC amps 2.
  Limits are the table's own (read from the page images, then checked against the accuracy table on p. 5); ONE is corrected: step 8 prints 0.47 to 0.53 V ac for a
  50 mV input, the procedure uses 0.047 to 0.053 V ac and says so (spec note, on-screen note, report row "(limits corrected)").
  Calibrator: Fluke 5522A or 5560A (the manual names a 5500A), automatic or Manual. The meter has no remote interface: you type the display reading.
  Prompts: a hook-up dialog with diagram at every cable change (volts / ohms / capacitance, 400 mA input, 10 A input), and "Change the function" every time the
  rotary switch or YELLOW button has to change function (11 times in a full run). Confirmation before every output of 30 V or more (the manual's shock-hazard level, p. 2);
  high voltages go straight to the test value (no ramp). Report: PDF 'Calibration Data', asset-MM-DD-YYYY.pdf.
  Not included: the calibration ADJUSTMENT (Table 3, pp. 14-16), fuse test, diode test (it has no step in Table 2).
  Rebuild the spec after editing the table:  python3 specs/build_77_spec.py     Demo with:  python Procedures/Fluke_77IV_Verification.py --demo

Fluke 365 detachable jaw clamp meter (automated performance verification: lists on the Automated Calibrations tab)
-------------------------------------------------------------------------------------------------
Procedures/Fluke_365_Verification.py   (engine: handheld_dmm.py; spec: specs/fluke_365_pv.json built by specs/build_fluke_365_spec.py; diagrams: diagrams/README_fluke365.txt)
  32 points = Table 2 "Performance Tests" of the Fluke 365 Calibration Manual (printed pp. 7-8): AC volts 6 (30 / 300 / 570 V at 50 and 400 Hz), DC volts 7 (0, +-30, +-300, +-570 V),
  ohms 7 (0 ... 5700 ohm), AC amps 6 and DC amps 6 (0.5 / 5 / 9.5 A driven through a 20-turn coil: the meter reads 20 x the calibrator current, the limits are the meter readings).
  Limits are the table's own, unchanged; four rows whose printed limit is not half of the published specification (900 ohm, and the three 190 A points) are flagged in the point note.
  Calibrator: Fluke 5522A or 5560A (the manual names a 55xxA), automatic or Manual. The meter has no remote interface: you type the display reading in the reading window of each point.
  Prompts as the other handhelds: hook-up dialog only when the hook-up group changes (test leads; coil on the low- or high-current output, with 'remove the test leads from the jacks'),
  "Change the function" at every dial change, ONE high-voltage confirmation per hook-up group (30 V and above). Run queue as the other handhelds.
  Report: PDF 'Calibration Data', asset-MM-DD-YYYY.pdf; the coil points print the calibrator's current uncertainty at the output current (point / 20), not multiplied by 20 (owner-chosen convention), TAR / TUR against the meter-reading tolerance.
  Not included: the calibration ADJUSTMENT (not needed). Rebuild the spec after editing the table:  python3 specs/build_fluke_365_spec.py     Demo with:  python Procedures/Fluke_365_Verification.py --demo

Fluke 374 / 375 / 376 / 376-II clamp meters (automated performance verification: four rows on the Automated Calibrations tab, one family spec)
-------------------------------------------------------------------------------------------------
Procedures/Fluke_374_Verification.py, Fluke_375_Verification.py, Fluke_376_Verification.py, Fluke_376II_Verification.py
  (engine: handheld_dmm.py through iflex_option.py; spec: specs/fluke_376_pv.json built by specs/build_fluke_376_spec.py; diagrams: diagrams/README_fluke376.txt, the same seven pictures for all four)
  Table 1 "Performance Tests" of the Fluke 374 / 375 / 376 / 376-II Calibration Manual (printed pp. 3-4), 38 rows, one X / - column per model: 374 = 28 points, 375 = 34, 376 = 38, 376-II = 38.
  AC volts 4 (10 V and 500 V at 50 Hz, 900 V at 50 Hz, 500 V at 500 Hz), DC volts 8 (-500, 10, 500, 900 V and -250, 50, 250, 450 mV), ohms 7 (60 ohm .. 54 kohm), capacitance 3 (10, 500, 900 uF),
  AC amps 4 and DC amps 3 (0.2 / 10 / 18 / 6 A driven through the 50-turn coil: the meter reads 50 x the calibrator current), iFlex simulated 5 (3 to 75 mV at 50 Hz, 750 mV at 500 Hz applied to
  the iFlex input) and iFlex with the 50-turn coil 4. The 374 has no mV, 30 / 54 kohm, 900 V or 18 A jaw rows; the 375 no 900 V or 18 A jaw rows; all four have all nine iFlex points.
  iFlex option: the window has a check box "iFlex probe supplied: run the iFlex tests" (default ON). OFF skips the nine iFlex points (and their cable-change and dial prompts) for a meter
  received without an iFlex: it asks first, never discards a recorded reading, is saved in the progress file and printed on the report ("iFlex tests: Not tested (no iFlex supplied)").
  Prompts per full run (cable + function + high voltage + reading), iFlex ON / OFF: 374 44 / 31, 375 51 / 38, 376 and 376-II 55 / 42.
  Limits are the table's own, unchanged; rows whose printed limit differs from the accuracy printed in the 374 FC / 375 FC / 376 FC Users Manual (pp. 20-26) are flagged in the point note (NOTES.md).
  The 900 V rows (1000 V range, 1 V resolution) are shown and typed as whole volts.
  Calibrator: Fluke 5522A or 5560A (the manual names a 55xxA), automatic or Manual. The meter has no remote interface: you type the display reading in the reading window of each point.
  Prompts as the other handhelds: hook-up dialog only when the hook-up group changes (test leads; coil on the low- or high-current output; iFlex simulation leads; iFlex loop on the coil),
  "Change the function" at every dial change, ONE high-voltage confirmation per hook-up group (30 V and above). Run queue as the other handhelds, with a per-meter iFlex setting (each queue meter: iFlex supplied, default ON; set in the Connections drawer; its report says Tested / Not tested).
  Report: PDF 'Calibration Data', asset-MM-DD-YYYY.pdf; the coil points print the calibrator's current uncertainty at the output current (not multiplied by 50, owner-chosen convention),
  the iFlex simulated points the calibrator's AC volts uncertainty (TAR / TUR blank there).
  Not included: the calibration ADJUSTMENT (Table 3). Rebuild the spec after editing the table:  python3 specs/build_fluke_376_spec.py     Demo with:  python Procedures/Fluke_376_Verification.py --demo

Fluke 175 / 177 / 179 (handheld multimeters, one spec for the family)
-------------------------------------------------------------------
Procedures/Fluke_175_Verification.py, Fluke_177_Verification.py, Fluke_179_Verification.py   (engine: handheld_dmm.py; spec: specs/fluke_170_series_pv.json built by specs/build_170_spec.py; diagrams: diagrams/hook_fluke170_*)
  175 = Table 2 of the 175 / 177 / 179 Calibration Information (printed pp. 10-11, 52 points); 177 = Table 3 (pp. 12-13, 51 points); 179 = Table 3 plus the temperature points (54: 0, -40, 400 degC, K-type thermocouple through the 80AK adapter).
  Functions: AC volts (15), AC / DC volts frequency, DC volts, DC millivolts, ohms (500 ohm ... 19 Mohm), capacitance (0.9 ... 900 uF), continuity (beeper), diode, AC / DC mA, AC / DC A.
  Calibrator: Fluke 5522A or 5560A (the manual names a 5500A), automatic or Manual. No remote interface: you type the display reading. Prompts: hook-up dialog with diagram at every cable change (volts / ohms, 400 mA, 10 A, thermocouple),
  "Change the function" at every dial / yellow-button change, HIGH VOLTAGE confirmation from 30 V, no ramp. Report: PDF 'Calibration Data', asset-MM-DD-YYYY.pdf.
  Three printed table values are corrected and flagged (see NOTES.md). Not included: the calibration ADJUSTMENT (Table 4), fuse test.
  Rebuild after editing the table:  python3 specs/build_170_spec.py     Demo with:  python Procedures/Fluke_175_Verification.py --demo

Fluke 83V / 87V / 88V (handheld multimeters, one spec for the family)
-------------------------------------------------------------------
Procedures/Fluke_83V_Verification.py, Fluke_87V_Verification.py, Fluke_88V_Verification.py   (engine: handheld_dmm.py; spec: specs/fluke_80_series_v_pv.json built by specs/build_80v_spec.py; diagrams: diagrams/hook_fluke87v_*)
  Table 3 "Accuracy Tests" of the Fluke 80 Series V Calibration Manual (printed pp. 9-11): 87V = the '87' column (56 points); 83V = the '83 and 88' column without the 87-only rows, Peak Min/Max and temperature (46);
  88V = the '83 and 88' column with Peak Min/Max and temperature (50). Each includes the display, pushbutton and backlight checks.
  Calibrator: Fluke 5560A (the manual's) or 5522A, automatic or Manual. No remote interface: you type the display reading. HIGH VOLTAGE confirmation from 30 V, no ramp.
  Not included: the 88V inductive pickup test (oscilloscope + function generator), the calibration ADJUSTMENT (Table 4).
  Rebuild after editing the table:  python3 specs/build_80v_spec.py     Demo with:  python Procedures/Fluke_87V_Verification.py --demo

Tektronix TDS2000C / TDS1000C-EDU
---------------------------------
Procedures/Tektronix_TDS2000C_Verification.py   (engine: tds2000c_verification.py; spec: specs/tektronix_tds2000c_pv.json)
  Automated performance verification from the TDS2000C and TDS1000C-EDU Service Manual (077-0446-01), Chapter 4: self test, self
  calibration, DC gain, analog bandwidth, sample rate / delay time, edge trigger, external edge trigger (vertical position accuracy is
  not included). Ten models (2-channel and 4-channel); the oscilloscope is connected by USB. Stimulus: the scope option of one Fluke
  5560A, 5522A or 5520A (DC volts, leveled sine, time marker). The program asks before every cable, terminator or splitter change; the
  calibrator goes to standby after every point. Hook-up pictures: diagrams/README_tds2000c.txt.
  Demo with:  python Procedures/Tektronix_TDS2000C_Verification.py --demo

Tektronix TBS1000C (TBS1052C / 1072C / 1102C / 1202C) and TBS1000 (TBS1022 to TBS1154)
--------------------------------------------------------------------------------------
Procedures/Tektronix_TBS1000C_Verification.py   (spec: specs/tektronix_tbs1000c_pv.json; driver: drivers/tektronix_tbs1000c.py)
Procedures/Tektronix_TBS1000_Verification.py    (spec: specs/tektronix_tbs1000_pv.json; driver: drivers/tektronix_tbs1000.py = the TDS2000C driver)
  The TDS2000C procedure on the same engine (tds2000c_verification.py; the two families are declared in tbs1000_verification.py): self test,
  self calibration, DC gain, analog bandwidth, sample rate / delay time, edge trigger, external (TBS1000C: Aux In) edge trigger. TBS1000C limits
  from its Specification and Performance Verification manual 077-1583-03 Rev A; TBS1000 limits from its Service Manual 077-0772-01 Rev D.
  Vertical position / offset accuracy is not included (as on the TDS2000C). Same calibrator choices, prompts and report as the TDS2000C.
  Hook-up pictures: diagrams/README_tbs1000.txt (none supplied). Demo with:  python Procedures/Tektronix_TBS1000C_Verification.py --demo

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
  Math per point (worksheet values are kept in the checkpoint and the detail pane):
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

Tektronix 3 Series MDO (MDO32 / MDO34, 100 MHz - 1 GHz)
--------------------------------------------------------
Procedures/Tektronix_MDO3_Verification.py   (engine: mdo3_verification.py, with the model-independent helpers of mdo4000c_verification.py; spec: specs/tektronix_mdo3_pv.json, written by
  specs/build_mdo3_spec.py; driver: drivers/tektronix_mdo3.py; windows: mdo3_view_qt.py / mdo3_view_tk.py)
  Automated performance verification from the 3 Series MDO Specifications and Performance Verification manual (077-1499-10), test record
  pp. 48-89, procedures pp. 90-130; commands from the 3 Series MDO Programmer Manual (077-1498-06), page cited per command. Same standards
  and the same uncertainty / TAR / TUR / review-window mechanism as the MDO4000C (5560A, 96270A, 33220A / 33250A, optional reference DMM /
  counter / power meter). The technician picks the model (MDO32 / MDO34 and its bandwidth) and the options (3-SA3, 3-AFG, 3-DVM, TPA-N-PRE);
  176 to 483 points apply. DC balance and the sample-rate test are reported in divisions, as the test record prints them. Not built: the
  digital threshold (logic probe, 3-MSO) test - removed from the MDO4000C at the owner's request. Method as the manual prints it: bandwidth
  reference at 1 ms/div, DANL at the fixed centre frequencies, DVM frequency with a time-mark square wave (function generator; 150 MHz a sine). Demo:  python Procedures/Tektronix_MDO3_Verification.py --demo

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
