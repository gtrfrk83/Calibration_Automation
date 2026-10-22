# Calibration Suite: project notes

Tkinter calibration suite. `Calibration_Procedure_Manager.py` (v69) launches one procedure per instrument from `Procedures/`.
Procedures are driven by JSON specs (`specs/`) of the manufacturer's performance-verification tables; shared engines hold the UI and run logic.

## Layout
- `Procedures/`: launchers (one per instrument), checkpoints are written here at run time (git-ignored).
- `specs/`: `*_pv.json` test points and limits, plus the `build_*.py` scripts that wrote them. See `specs/README.txt`.
- `drivers/`: instrument drivers, transports (VISA / pyserial), simulators (`simulated.py`). See `drivers/README.txt`.
- Engines: `truevolt_verification.py` (Keysight Truevolt), `dacq_verification.py` (34970A/34972A), `handheld_dmm.py` (Fluke 110-117, 77 IV, 175/177/179, 87V, 287/289, Klein MM325), `mdo4000c_verification.py`, `tds2000c_verification.py`, `fgen_verification.py` (33210A/33220A/33250A), `fluke8808a_verification.py` (Fluke 8808A bench DMM), `keithley2000_verification.py` (Keithley 2000, two-way over GPIB / RS-232).
- `procscan.py`: procedures register themselves. `Procedures/<id>.procedure.json` (sidecar) per launcher; the Manager scans them (no hand-written list). `packages.py` / `packages_ui.py` / `tools/make_package.py`: procedure packages (zip) export / import. See 'Procedure registration and packages'.
- `labregistry.py` / `labregistry_ui.py`: per-asset report history and drift (`lab_registry.sqlite3`, not in the repo).
- `report_pdf.py` / `report_dialog.py`: PDF "Calibration Data" reports.
  Optional TAR / TUR columns: two independent checkboxes (TAR, TUR) in `report_dialog.ask_details` (`details["show_tar"]`, `["show_tur"]`, `["show_tar_tur"]` = `report_pdf.TarTur`, default off, remembered in `~/.calibration_suite/report_tartur.json`); `report_pdf.apply_tar_tur`. TAR / TUR appear on the PDF data file only (there is no CSV export). Off = the PDF is unchanged.
- `diagrams/`: hook-up PNGs. 34970A/34972A naming is in `diagrams/README_dacq.txt`, the Keithley 2000 naming in `diagrams/README_k2000.txt`.

## Procedures
WaveSurfer WS4104HD, Fluke 87V, Agilent 34401A, Fluke 8846A (verification + adjustment), Keysight 34460A/61A/65A/70A,
Tektronix MDO4000C, Tektronix TDS2000C / TDS1000C-EDU, Fluke 110/113/114/115/116/117, Fluke 77 Series IV, Fluke 175/177/179, Klein MM325, Keysight 34970A (RS-232), Keysight 34972A (USB),
Keysight 33210A, Agilent 33220A, Agilent 33250A (Fluke 5790B as the AC standard), Fluke 287 / 289 (typed or IR readings), Fluke 8808A (RS-232), Keithley 2000 (GPIB / RS-232).

## Standing rules
- Display-only SI scaling. `calibration_procedures.sqlite3` schema is never changed (read only).
- Instrument commands, limits, pass/fail and safety prompts are unchanged unless requested.
- Never write passwords to logs. Writes: set, read back, compare; never retry a write.
- Outputs to standby/off after each point.
- Handheld multimeters, manual entry: a typed reading is filled out with zeros to the test point's display resolution (typing 5 on a
  5.000 V point stores and prints 5.000; more decimals than the resolution are kept as typed). Use `handheld_dmm.pad_reading` in any new
  manual-entry procedure; `tests/test_pad_reading.py` covers it.
- Multimeter procedures (any procedure that drives a calibrator to a DMM): every DC volts / DC amps output is sent with an explicit `,0Hz`
  (`set_output_volts(..., dc=True)` / `set_output_amps(..., dc=True)`). An OUT with no frequency keeps the previous one, so the
  calibrator errors going from an AC point to a DC point. `tests/test_dc_zero_hz.py` fails if a DMM engine drops it. Add this to
  every new multimeter procedure.
- Handheld multimeter procedures (`handheld_dmm.py`) go straight to the high-voltage test value: no 50 V ramp, except where the manual
  prescribes one (explicit per-point `ramp` lists, e.g. 287/289 point 4-64: 60 V then 120 V; the 110-series AUTO-V LoZ point 3-40 keeps
  the 50 V ramp). Spec option `options.auto_ramp` (default true) is false in the 87V, 287/289 and MM325 specs and builders; the HIGH VOLTAGE
  prompt mentions ramping only when one happens. `tests/test_handheld_options.py` covers it.
- Handheld multimeter procedures: every function change prompts the operator to turn the rotary switch (`options.function_prompt`, on in
  all handheld specs; output in standby meanwhile). Group NONE points (functional checks, hand-set points) keep their own prompts and
  are not given a 'turn the meter to' prompt; the MM325 already shows its dial prompt at every point, which covers the function change.
- Read limit tables from rendered page images, not extracted text.
- No cover sheets, no standards-due tracking (handled by other software).
- Reset to default settings (Stage 7): every instrument is reset to its default settings BEFORE the first test point of every run (first run,
  re-run, resume after Stop). Every driver declares a locked `COMMANDS['reset']` (risk 'locked', never overridable; `cmdreg.reset_cmd`) plus
  `opc.query`, or a documented `RESET_EXEMPT` reason with `RESET_KNOWN_STATE`. `Instrument.reset_to_defaults()` runs reset, `*CLS`, wait,
  error-queue drain, then the model's `_reset_extra()` (re-enter remote, restore connect-time settings, confirm outputs off/standby) and returns
  a `ResetReport`; a reset write is never retried; a failure stops the run before any point and sends outputs to standby/off. Engines call the
  shared helper `reset_startup` (`AppResetMixin.reset_then` / `IOResetMixin.reset_at_start` / `reset_all`) and log
  'Instruments reset to default settings at start'. Because a UUT reset can erase stored settings, a notice is confirmed first (declining touches
  nothing). Fast demo sends nothing; a virtual-bench demo resets the SIMULATED instruments (see Virtual bench). A new procedure must call the helper before its first point; `tests/test_reset_startup.py` enforces it.

## Reset to default settings: what is verified (Stage 7)
- Backed by a manual page: Fluke 5522A `*RST` (Operators Manual p. 6-35) and `*OPC?` (p. 5-44); Fluke 5790B `*RST` (Operators Manual pp. 6-11,
  6-22) and `*OPC?` (pp. 6-10, 6-22); Agilent 53131A/53132A `*RST` (Programming Guide p. 2-40, Table 2-3; `*OPC?` p. 4-133; the reference
  oscillator source returns to AUTO, so the procedure selects it again); Fluke 96270A Master Reset equals `*RST` (Operator Manual p. 3-46).
- NOT verified (manual not available when written; `verified=False`): Fluke 5560A, 8845A/8846A, 34401A, Keysight Truevolt 34460A-70A,
  34970A/34972A, 33210A/33220A/33250A (also as the AFG in the MDO4000C procedure), LeCroy WaveSurfer 4104HD, Tektronix MDO4000C (`*RST`
  vs `FACtory`, reply format after reset), Tektronix TDS2000C (`FACtory`), generic ReferenceMeter (power meter / counters), plus `*CLS`/`*OPC?`/`SYST:ERR?` on the DMMs.
- TDS2000C procedure (`tds2000c_verification.py`): at the start of every run (first, re-run, resume) the calibrator is reset first, then the scope.
  5520A/5522A (`Fluke5522AScope`): `*RST` (Operators Manual p. 6-35; the values it evokes, p. 6-36, include SCOPE OFF, OUT_IMP Z1M, STBY), then STBY
  confirmed, then `SCOPE OFF` read back (`SCOPE?` = OFF; pp. 9-28 / 9-29). 5560A: `*RST` (UNVERIFIED), STBY confirmed, `SCOPE OFF` read back.
  The calibrator is left in standby with no SCOPE mode; the procedure selects the mode again for each test. Scope: `FACtory` (Default Setup, p. 2-87
  as cited by `default_setup()`; UNVERIFIED, programmer manual not available when added), then `*CLS`, `*OPC?`, `HEADer OFF`, `VERBose OFF`,
  `*ESR?` clean. It is deliberately NOT `*RST` and never `*CAL?` / self calibration (the procedure runs the self test and self cal as its own points).
- Exempt: Fluke 287/289 over IR (read-only protocol, no reset command; known state = the unchanged set-up check).
- The 8846A adjustment procedure resets the meter when an adjustment record starts (and after reconnecting a resumed record), never between steps.

## Open items: Keysight 34970A / 34972A (not yet run on hardware)
- Unverified SCPI: `FREQ:APER`, AC bandwidth on the current channel, reading with `ROUT:SCAN` + `READ?`.
- Calibrator external-sense / 2-wire settings are front-panel instructions, not commands.
- Some calibrators may refuse 300 V at 50 kHz / 300 kHz; the run stops on a rejection.
- Manual's DC current table says "Channel 209"; the procedure uses 221 (current channel).
- Limits were transcribed from page images; compare a few rows against the manual.
- Hook-up diagrams still to be supplied.

## Fluke 8808A (branch `fluke-8808a`; checked on the simulated bench only, never run on hardware or a real UI)
Launcher `Procedures/Fluke_8808A_Verification.py`, engine `fluke8808a_verification.py`, driver `drivers/fluke_8808a.py`, simulator `drivers/simulated_8808a.py`,
spec `specs/fluke_8808a_pv.json` (written by `specs/build_8808a_spec.py`), diagram names in `diagrams/README_8808a.txt`, tests `tests/test_beta_8808a.py`.
- Sources: 8808A Calibration Manual (56 pp.) chapter 3, Tables 3-2 to 3-8, printed pp. 3-4 to 3-11, 105 points (DC volts 17, AC volts 28, 4-wire ohms 6, 2-wire ohms 14,
  DC current 18, AC current 16, frequency 6); Table 3-1 (equipment) p. 3-3; accuracy specifications pp. 1-10 to 1-14. Users Manual (100 pp.) chapter 4 for every command.
  Every number was read from rendered page images (150 / 130 dpi), twice.
- Both the 90-day and 1-year limits are printed; the window offers both (default 1 year; the manual uses 90 days for an acceptance test after calibration). Verification
  only: the manual's adjustment (Table 3-9, 124 steps, entered with `*TER` over RS-232) is NOT built, and `*TER`, `CALREF` and `EXIT` are on the forbidden list for the driver.
- The builder checks every printed limit against the manual's own specification formula (+/-(% of reading + % of range)) in Decimal and stops on a disagreement it does
  not know. Known disagreements, each stored in the point as `flags` with the printed text in `printed_limits`: TYPOS corrected from the formula (T3-2 #11 1y low sign;
  T3-3 #10 90d high 1.903985; T3-3 #27 90d low 747.48 -> 747.38; T3-5 #4 1y 0.0044 -> 0.00044; T3-6 #9 1y low -190.0116; T3-6 #12 90d low sign; T3-7 #13 1y low 04855),
  printed limits LOOSER than the formula, so the formula is used (T3-3 #1 90d 10.120 / 9.890 mV -> 10.115 / 9.885; T3-6 #10 1y +/-0.020 -> +/-0.016 mA), printed limits
  TIGHTER than the formula, kept (T3-8 #2 50 Hz, T3-8 #3 1900 Hz), and column misprints (T3-3 #24 Ampl. / Range swapped: 30 V on the 750 V range; T3-7 #15 "45 A" is 45 Hz;
  T3-8 #4-6 limits print "Hz" for kHz). Confirm against the printed manual.
- Ohms limits are "STD +/- tol" in the manual (STD = the 5700A reading). The calibrator setting is used as STD (the 5522A / 5560A reading is not read back), so the limits are
  setting +/- tol (`std_relative`).
- Interface (Users Manual Table 4-1, p. 4-4): RS-232 only, no IEEE-488, no USB. 9600 baud, 8 data bits, no parity, 1 stop bit, echo off; changed from the front panel only.
  The engine's baud / format boxes are the lab's choice if those settings were changed. Echo must be OFF: the driver refuses to run on a reply that carries a prompt.
- Commands (page references are in `drivers/fluke_8808a.py` COMMANDS; all verified in the Users Manual except as listed): `*IDN?`, `*RST` ("power-up reset", Table 4-8 p. 4-16),
  `*CLS`, `*OPC?`, `*ESR?`, `REMS`, `LOCS`, `VDC VAC ADC AAC OHMS FREQ`, `WIRE2 WIRE4`, `FIXED`, `AUTO?`, `RANGE n`, `RANGE1?`, `RATE S`, `RATE?`, `FORMAT 1`, `FORMAT?`,
  `TRIGGER 1`, `TRIGGER?`, `MEAS1?`, `SERIAL?`, `*STB?` (registered, not used). Everything is set once, read back and compared where a query exists; no write is retried.
- Flagged, not verified or not stated by the manual: (1) `FUNC1?` reply text (registered `verified=False`); (2) the wire mode has no query, so the operator confirms the 2W / 4W
  annunciator in the hook-up prompt (the program selects the function and WIRE2 / WIRE4 first); (3) there is no state query for REMS / LOCS; (4) whether `*RST` leaves remote mode
  and whether it touches the RS-232 settings is not stated: REMS is sent again afterwards and the settings it needs are set and read back (`FORMAT 1`, `TRIGGER 1`, `RATE S`);
  (5) with echo off there is no prompt, so `COMMAND_GAP_S` (0.15 s) between commands and `RESET_SETTLE_S` (3 s) after `*RST` are this driver's choices, not manual figures; `*OPC?`
  after the per-point set-up is the "done" signal; (6) that `MEAS1?` right after a range change is a fresh reading is not stated: the first of two `MEAS1?` is discarded;
  (7) there is no error queue: errors are bits of `*ESR?` (mask 0x3C, Table 4-6 p. 4-12), read once per check because the read clears it (never retried); (8) the simulator's
  power-up FORMAT (2) is a simulation choice.
- Reset (Stage 7): `*RST` is manual-verified (p. 4-16), so `Fluke8808A` is in the verified-reset list of tests/test_reset_startup.py. The reset can erase settings stored on the meter (Users Manual).
- Calibrators: Fluke 5522A or 5560A. The manual names a 5700A + 5725A (voltage, current, 750 V), a Fluke 271 (frequency) and a 5520A (resistance adjust). Points the 5522A cannot
  make: T3-3 #26-28 (750 V ac above 10 kHz, 5522A Operators Manual p. 1-12), T3-7 #14 (10 A ac at 40 Hz, below the 45 Hz of 3 A and up, p. 1-14), T3-8 #6 (1000 kHz, above 500 kHz).
  The spec lists them under `cal_limits`; the run asks the technician to connect their own standard and reads the meter automatically (report Uncertainty / TAR / TUR left empty).
  The 5560A (Product Specifications Rev. 8, 6/26, read from the page images; PDF pp. 4-5 = printed pp. 3-4 ACV, PDF p. 9 = printed p. 8 ACI) cannot make four of them: 750 V ac at 20 / 50 / 100 kHz (the 1020 V range is
  specified 3 Hz - 10 kHz only, the 330 V range stops at 100 kHz) and 1000 kHz (ACV stops at 500 kHz); `cal_limits` has a `5560A` entry for each (T3-3 #26-28, T3-8 #6) and they stay external-standard points.
  10 A ac at 40 Hz (T3-7 #14) is NOT a 5560A limit: the 12 A range is specified 3 - 45 Hz (1 year, 95 %: 290 uA/A + 1 mA; 99 %: 375 uA/A + 1 mA), so with the 5560A selected the calibrator drives it
  (`cal_limits` of that point lists only the 5522A) and its report row gets the 5560A budget (the '12A @ 3 - 45 Hz' row of `fluke_5560a_standard.json`; the scope CMC is the larger figure there, so the
  Uncertainty prints 14 mA) and TAR / TUR (TAR 35.1:1 on the 5560A spec; blank for the 5522A, which has no spec at 40 Hz). `is_manual` is now simply 'the selected calibrator is in the point's `cal_limits`';
  the old 'Try the 5560A' check box (and its 'unverified' fallback) is gone. Still unverified for the 5560A: the 30A + OUTPUT LO terminal names (taken from hookups.py; the specifications name no terminals),
  whether the unit refuses 10 A 40 Hz for some reason the specifications do not state (the run stops on a rejection as before), and the 30 A terminal fuse / cool-down (specs: sourcing > 3 A may need a cooling-off time).
- Zero-offset points run first, in two fixtures: 15 points with the 4-wire short (DC volts 5, 4-wire ohms 3, 2-wire ohms 7), then 6 DC-current points with the input OPEN
  (Table 3-1 lists the 4-wire short under Amps dc as well: question open). The calibrator is in STANDBY for every zero point.
- Not in the engine: no Excel export (the 8846A launcher has one), no capacitance / temperature / diode / continuity points (the manual has no verification table for them),
  no front / rear switch (the 8808A has none), no fixture for ranges beyond Tables 3-2 to 3-8.
- The window opens with a half-hour warm-up question (Calibration Manual); the specifications are valid in the slow rate only, which the program selects.
- Not viewed: the Tk windows (tkinter is not installed where this was built); only the real App code on the simulated bench was run (tests/test_beta_8808a.py, live_editor_harness).

## Open items: 33210A / 33220A / 33250A and the Fluke 5790B driver (not yet run on hardware)
- Unverified: all 5790B commands (INPUT, EXTRIG, RANGE/RANGE?, MEAS?, ERR?) and all generator commands, taken from the manuals;
  53131A/53132A driver (drivers/keysight_5313x.py, from the Programming Guide); power meter `MEASure:POWer?` and other counters
  `MEASure:FREQuency?` (generic ReferenceMeter, no manuals supplied); 33250A RS-232 line endings.
- Counters run on the lab's external 10 MHz GPS timebase: the generator procedure selects and checks EXT on a 53131A/53132A.
- The MDO4000C procedure still uses the generic ReferenceMeter for its counter (AFG frequency check).
- 5790B 7 V range is 50 kOhm: 7 Vrms points read about 0.1 % low versus the manual's 3458A. Not corrected.
- Power sensor cal factor vs frequency is not set by the program (the manual does not set it either).
- The manual's 80 % guard band (no adjustment made) is not applied.
- 33210A / 33220A flatness defaults to the 5790B WIDEBAND input, relative to 1 kHz (5790B manual pp. 4-31/4-32); power meter selectable.
  33250A keeps the power meter (80 MHz). WBAF? reply format undocumented in the 5790B manual.
- Hook-up diagrams still to be supplied: diagrams/hook_332xx_<NONE|COUNTER|STD|WBND|POWER|POWER_ATT>.png.

## Open items: Fluke 287 / 289 (not yet run on hardware)
- IR protocol from Fluke's unsupported remote spec; QDDA function / range codes used for the set-up check unverified (400 mA and
  diode ranges not checked). 'Type the reading instead' is the fallback if a check is wrong.
- Calibrator 2-wire COMP is set by the technician (prompted); capacitance and thermocouple outputs unverified on the 5560A.
- Steps 25, 29, 41 are set on the calibrator by hand (levsine 950 kHz, 15 % duty square, square + offset).
- Handheld reports are titled '<model> Performance Verification', not 'Calibration Data' (existing engine behaviour, unchanged).

## Open items: Fluke 96270A driver (checked against the manual, not yet run on hardware)
- On connect the driver selects INST SINE, UNIT:POW DBM, turns power/frequency offsets off and the output off, reading each back.
- Frequency and level go in one message (`FREQ ...;:POW ...`) so the source applies its frequency/power coupling.
- Output route (`OUTP:ROUT` HEAD / MICRowave) and sensor leveling (`OUTP:LEV`) are left as set on the front panel.

## As Found / As Left, Run Shown Section, bottom-bar buttons (v70)
- `datamode.py` is shared by every verification procedure (the Truevolt, DAQ, function generator, MDO4000C and handheld engines, the 34401A and
  8846A, and the WaveSurfer). A "Collecting data" toggle (As Found | As Left) picks the set being recorded; both sets are stored and saved
  (progress files gain `left_results`; WaveSurfer keeps As Left in `*_AsLeft.json` files beside its As Found ones). Files saved before this
  feature load unchanged. A loaded file starts on As Found. The toggle is locked while a run is active.
- As Left readings are taken by re-running the points through the same procedure; nothing is adjusted by the program. If nothing was adjusted the
  As Left set stays empty and the report prints "Same", exactly as before. Re-measured points print the As Left reading (red OOT if still out).
- Measuring As Found again after As Left readings exist asks first (it would replace the original reading with one from the adjusted instrument).
- "Run Shown Section" runs the points not yet measured in the section chosen in the Show box (needs a section or status chosen, so it never starts a
  whole run by accident). The Show status box also has "As Found failed" for choosing the points to re-run As Left.
- WaveSurfer: the engine records each function in order, so As Left is run per function (Show = one function, Run Shown Section). Re-measuring only
  some points inside one function is done with Rerun Selected.
- Toolbars wrap instead of squeezing; Save / Load progress and the export buttons live in the bottom bar (`ui.dock_button`). Windows keep room for 5 table rows.
- Not verified: lab_registry history still records only As Found; no instrument commands, limits or pass/fail logic were changed.

## Beta edition (v70 Beta 2) - branch `beta`
- `suite_info.py` holds name / version / edition; every window title, status bar and the PDF footer use it. Set `EDITION = ''` for a release.
- `appdata.py`: databases and saved progress live in a per-user data folder (`%LOCALAPPDATA%\\CalibrationSuite-Beta`), separate from the program files and
  from the released copy. Copy-only: `import_from()` (Help > Import data from another copy) backs up any file it replaces. `CALSUITE_DATA` overrides the
  folder; an empty `portable.txt` beside the program keeps the old layout. The calibration_procedures.sqlite3 schema is unchanged.
- `diagnostics.py`: missing-package message with the exact pip command; unexpected errors show a plain window and write a diagnostic log (passwords scrubbed).
- `branding.py`: one title pattern, the icon (assets/), a Help menu in every window, Ctrl+S / Ctrl+O / Ctrl+P / F1.
- PDF footer carries the software version (no logo on the data report: the logo belongs on the cover certificate).
- Not done: a signed installer / single .exe (needs a Windows build machine), a resizable table divider, per-procedure guides (USER_GUIDE.txt is general).
- tests: `tests/__init__.py` points CALSUITE_DATA at a throw-away folder, so tests never touch real data. `tests/test_beta.py`.

## Redesigned test window (beta only)
- `ui_theme.py`: palettes `LIGHT` and `DARK` (flat warm charcoal, one blue accent); `use_palette()` mutates `ui.C` in place, `apply_theme()` picks it
  (`CALSUITE_THEME`, else Help > Appearance, else `suite_info.DEFAULT_THEME`: dark in the beta, light in the released copy). Colours come from tokens, never hex.
- `ui_shell.py`: `Shell` (header with chips + Connections button, top strip with ID / serial / As Found | As Left / progress ring, section sidebar with status dots,
  slide-in Connections drawer with a pinned footer, action bar, status bar), `ProgressPanel` (ring; re-run progress in As Left), `results_table()` and
  `small_window()` (below ~1100 px the sidebar becomes a drop-down, Low/High merge into Limits, buttons shorten). Nothing in it talks to an instrument.
- `datamode.py`: `build_mode_segment`, `shell_cells` (row cells with units, error, As Found / As Left / 'Same'), `update_shell_progress`, `update_shell_sections`.
- Converted: 8846A, 34401A, Truevolt, DACQ, function generators, MDO4000C, handheld DMMs, WaveSurfer (sidebar = its seven functions). Instrument commands, limits,
  pass/fail logic and safety prompts were not touched; only widgets were rearranged. `Fluke_8846A_Adjustment.py` and the Manager keep their layouts (they pick up the dark palette).
- Tests: `tests/test_shell.py` (sidebar / drawer / small window / As Left columns), the toolbar-fit tests in `tests/test_asleft.py` run at 900 / 1000 / 1400 px.

## Open items: Tektronix TDS2000C / TDS1000C-EDU (checked on the simulated bench only, not run on hardware or a real UI)
- Source: Service Manual 077-0446-01 Chapter 4 + Appendix A; commands from the TBS1000-B/TDS2000-B-C/... Programmer manual. Limits read from page images.
- Fluke 5520A/5522A scope option: `SCOPE VOLT`, `SCOPE LEVSINE`, `SCOPE MARKER`, `OUT_IMP 1M|50`, the `SCOPE?` reply text and `OUT?` in levsine/marker modes are
  NOT confirmed (the 5520A Programmers Guide gives the commands SCOPE, SCOPE?, OUT_IMP, TMWAVE and the 5-field OUT? layout only). The 5560A path reuses existing driver commands.
- Time base test: edge time is read from the waveform (t = XZEro + n*XINcr, relative to the trigger point). A guard raises an error if the record centre is
  more than 1.5 div from the 10 ms delay; the XZEro / HORizontal:POSition convention is unverified.
- "Stable trigger" is judged by engine criteria (trigger Normal, >= 5 acquisitions/s, edge position spread <= 0.2 period over 8 records); the manual's check is visual.
- SETLevel with an EXT trigger source may be rejected; that is tolerated on the external-trigger points only.
- Average-mode NUMACq counting and the 0.05 div position readback tolerance are unverified.
- Vertical position accuracy (manual p. 4-10 to 4-13) is not part of this procedure (removed at the lab's request).
- Manual prints "TDS2004B" in the bandwidth list; TDS2004C is used. USB VISA address of the scope is entered by hand.
- The TDS driver (`drivers/tektronix_tds2000c.py`) and `drivers/fluke_5522a_scope.py` still send through legacy write/query (not yet on the command registry);
  their wire text is locked by `tests/golden/tektronix_tds2000c.json`, `fluke_5522a_scope.json` and `engine_tds2000c.json`.
- No procedure modifications (procmods) are wired into this engine yet. TAR/TUR: TUR only on the DC gain points (volts); TAR is blank.

## Fluke 87V notes
- Temperature 1-50 / 1-51 are read and sourced in degC. Limits follow the 87 Series V Calibration Manual (Table 3 steps 49 / 50, printed p. 11): -1.0..1.0 at 0 degC
  and 98.0..102.0 at 100 degC (decided by the lab owner; the MDD-derived 99.0..101.0 is not used).
- Duty cycle 1-16 (5 V p-p square, 1 kHz, 2.5 V DC offset, 50 % duty; manual Table 3 step 16, p. 9) and Peak Min/Max 1-48 / 1-49 (6 V p-p square, 2 kHz,
  1 V DC offset: MAX 3.897..4.103 V, MIN -2.102..-1.898 V; manual Table 3 step 47, p. 11) are sourced by the calibrator as square waves. The MDD's MAX row
  (+6 V DC source, 5.896..6.104 V) disagreed with the manual and was replaced. 5522A commands (WAVE p. 6-48, DC_OFFSET p. 6-13, DUTY p. 6-14, coupled commands
  p. 5-28, p-p amplitude pp. 4-42 / 1-24) are marked verified; the 5560A equivalents are NOT (5560A manual not read) and the remote OUT? reply for a square wave
  (p-p vs rms, field layout) is not documented, so the point stops if OUT? disagrees. Uncertainty / TAR / TUR are blank for these square-wave points.
- build_87v_spec.py was edited by hand and not re-run (the MDD file is not available); fluke_87v_pv.json was changed by the same rules.

## Fluke 77 Series IV notes (branch `fluke-77`; checked on the simulated bench only, never run on hardware or a real UI)
- Source: Model 77 Series IV Calibration Information (20 pp.), Table 2 Performance Tests, printed pp. 12-13 (35 steps); spec table pp. 4-6. Limits were read from rendered page images (260 dpi) twice;
  `specs/build_77_spec.py` additionally checks each limit against the accuracy table (+/-(% of reading + counts x resolution), to half a display step) and refuses to write the spec on a disagreement.
- ONE printed limit is corrected: step 8 (AC volts 50 mV, 45 Hz) prints 0.47 / 0.53 V ac; 0.047 / 0.053 V ac is used (2 % + 2 counts of 0.001 V, the manual's own method). Recorded in the spec
  (`printed_limits`, `source.report_note`), the on-screen note and the report row ("6.000 V range (limits corrected)"). Lab owner to confirm.
- 35 steps: ohms 5, continuity 2 (beeper, 25 / 250 ohm), AC volts 9, AC volts frequency 1, DC volts 4, DC mV 3, capacitance 1, AC mA 3, AC A 2, DC mA 3, DC A 2. Manual order is kept (5 cable changes: VOHM, 400 mA, 10 A, 400 mA, 10 A).
  Calibrator: 5522A or 5560A (Table 1 names a 5500A); only existing driver commands are used (OUT ...OHM / V / A with explicit ,0Hz on DC / NF); no new command and no registry change.
- Standing rules as in the other handhelds: `,0Hz` on every DC point, HV straight to the test value (the manual prescribes no ramp; `options.auto_ramp` false), function prompt on every function change (11 in a run),
  reading padded to the display resolution (`pad_reading`), reset before the first point, standby after each point, typed readings. HIGH VOLTAGE confirmation from 30 V (`hv_threshold_v` 30: p. 2 warns above 30 V ac rms / 60 V dc).
  Not applicable to the 77 IV: AUTO-V LoZ, temperature, square-wave sources (duty / peak), IR readings, REL.
- Shared-engine additions (additive; every other handheld is unchanged): `options.report_title` (77 IV: 'Calibration Data', so the report follows the project rule; the other handhelds keep
  '<model> Performance Verification'), `step.report_desc`, `source.report_note` (see specs/README.txt), the `fluke77` meter in `hookups.py` and `specs/build_hookups.py` (6 diagrams, only the 77 files were drawn).
  Editing `handheld_dmm.py` / `hookups.py` changes the fingerprint of every procedure that uses them, so the verified Fluke 117 will show 'Changed since verification' (verified.py); its behaviour did not change.
- Verified from the lab's photos of the real case plus the manual: the jacks are a 2 x 2 block, top-left '400 mA', bottom-left '10A' (the two FUSED inputs), top-right 'V Ω' (red), bottom-right 'COM' (black); the dial has Hz V~, V⎓, mV⎓, Ω / capacitance, continuity / diode, mA and A positions plus OFF,
  and a YELLOW button (orange symbols: Hz, capacitance, diode, DC on the mA and A positions). Function prompts name the dial position as printed and repeat the manual's own wording 'Press the YELLOW button to access this function' (Table 2 footnote 1: V~ Hz, capacitance, diode, DC mA, DC A);
  AC volts, continuity, AC mA and AC A carry no yellow-button step in the manual, so none is invented (the AC mA / A notes only say the display should show AC).
- Unverified: the exact yellow-button toggle behaviour (the manual does not describe it beyond footnote 1);
  calibrator capacitance output (`OUT <n>NF`, unverified on both calibrators) and DC current (`OUT <n>A,0Hz` unverified on the 5560A); whether a 5522A / 5560A can make 9 A at 1 kHz (the calibrator refuses what it cannot; TAR is 0.9:1 there).
- Existing quirk found, not changed: the shared engine prints '(2 V applied)' on every kHz frequency row of the 110-series and 87V reports whatever the applied level is (the 77 IV uses `report_desc`).
- Tests: `tests/test_77_points.py` (spec vs an independent second transcription of Table 2, specification check, step 8, padding, prompt sequences, wire commands on both simulated calibrators, full run on the bench, PDF, demo),
  plus the 77 IV in `tests/test_handheld_options.py`. The Tk windows were not viewed (no tkinter here).

## Fluke 175 / 177 / 179 notes (branch `fluke-170-series`; checked on the simulated bench only, never run on hardware or a real UI)
- Source: Fluke 175, 177, 179 Calibration Information (22 pp., PN 1600476 Rev. 7, 3/23): Table 1 calibrator (a 5500A), procedure p. 9, Table 2 = 175 (printed pp. 10-11, 52 rows), Table 3 = 177 / 179 (pp. 12-13, 51 rows + 3 temperature rows, 179 only).
  Read from rendered page images (220 dpi) twice, plus a machine check of every printed limit against the extracted DIGITS (text extraction is used for digits only; it scrambles the 177/179 DC-frequency row).
  The tables have no step numbers: steps are numbered in table order (ids `2-1`..`2-52` for the 175, `3-1`..`3-54` for the 177 / 179; the 179 adds `3-52`..`3-54`).
- ONE spec for the family (`specs/fluke_170_series_pv.json`, `specs/build_170_spec.py`), per-step `models` like the 110 series: 175 = 52 points, 177 = 51, 179 = 54. Launchers `Procedures/Fluke_175_Verification.py`,
  `Fluke_177_Verification.py`, `Fluke_179_Verification.py`; Manager rows 'Fluke 175 Performance Verification', 'Fluke 177 ...', 'Fluke 179 ...' (Digital Multimeter); `verified.FILES` entries; not verified on hardware (nothing seeded).
- Points per function (175 / 177 / 179): AC volts 15 (300 mV 45 Hz; 500 mV 500 Hz / 1 kHz; 5, 50 V at 45 / 500 / 1k Hz; 300 V 45 Hz; 500 V 500 Hz / 1 kHz; 1000 V 45 / 500 / 1k Hz), AC volts frequency 4 (1 V 45 Hz, 900 Hz, 9 kHz; 5 V 50 kHz),
  DC volts 5 (5, 50, 300, 1000, -1000 V), DC volts frequency 2 / 1 / 1, DC millivolts 3 (30, -300, 600 mV), ohms 6 (500 ohm ... 19 Mohm), capacitance 4 (0.9, 9, 90, 900 uF), continuity 2 (25 ohm on / 250 ohm off), diode 1 (2.0 V),
  AC mA 3, AC A 2, DC mA 3, DC A 2, temperature 3 (179 only: 0, -40, 400 degC).
- THREE printed values are corrected, each flagged in the spec (`printed_limits`), on the on-screen note and in the report row Description ('... (limits corrected)'; `report_pdf` does not print footer notes, so `source.report_note` is stored with the issued snapshot only):
  2-30 (175, 500 ohm): upper limit printed '504.7 kOhm', judged 504.7 ohm (the 177/179 table prints 504.7 Ohm, accuracy 0.9 % + 2 counts of 0.1 ohm = 4.7 ohm);
  3-4 (177/179, 5 V 45 Hz): upper limit printed 5.103 V, judged 5.053 V (4.947 lower, the 175 table, 1.0 % + 3 counts of 0.001 V);
  3-25 (177/179, DC volts frequency): printed '3 V 45 kHz, 45.06 Hz / 44.94 Hz' (input in kHz, lower / upper columns swapped), judged 3 V at 45 Hz, 44.94 .. 45.06 Hz (the 175 table prints 3 V 45 Hz, 44.94 / 45.06). The 177/179 table has only this ONE
  DC-volts-frequency row (the 175 has 3 V 45 Hz and 30 V 50 kHz); no second row is invented. Lab owner to confirm all three.
  Format only (same number, printed text kept in `printed_text`): 50.1 -> 50.10 V (175), 899 / 901 -> 899.0 / 901.0 Hz, 8.99 / 9.01 -> 8.990 / 9.010 kHz, so the typed reading is padded to the meter's display resolution.
- The published accuracy is NOT in the calibration manual. `build_170_spec.py` checks every limit against +/-(% of reading + counts x resolution) from the Fluke 170 Series Technical Data AS SUMMARISED FROM THE WEB (secondary source, the PDF itself was not downloaded:
  AC 1.0 % + 3 (45-500 Hz) / 2.0 % + 3 (500 Hz-1 kHz); DC V 0.15 % + 2 (175), 0.09 % + 2 (177/179, 0.1 % at 1000 V); ohms 0.9 % + 2 / + 1, 50 Mohm 1.5 % + 3; capacitance 1.2 % + 2; diode 1 % + 2; AC mA / A 1.5 % + 3; DC mA / A 1.0 % + 3; Hz 0.1 % + 1;
  temperature 1 % + 1.0 degC) to within half a display step; all 106 steps agree (the three corrected rows were found by this check and by the table itself). Ranges (600.0 mV ... 50.00 Mohm, 60.00 mA, 400.0 mA, 6.000 A, 10.00 A, 1000 nF ... 9999 uF, 99.99 Hz ... 99.99 kHz)
  come from the same data sheet and the decimals of the limits: the manual names no range. Re-check against the real Technical Data before relying on them.
- Standing rules as in the other handhelds: `,0Hz` on every DC point (incl. the diode 2.0 V point), HV straight to the test value (`auto_ramp` false; the manual prescribes none), `hv_threshold_v` 30 (project convention; the 170 manual gives no shock threshold), function prompt on every function change (13 in a 175 / 177 run, 14 in a 179 run),
  reading padded to the display resolution, reset before the first point, standby after each point, typed readings (no remote interface in the manual: no IR / Bluetooth reading built, none described). Report: PDF 'Calibration Data' (`options.report_title`, like the 77), named asset-MM-DD-YYYY.pdf.
  Not applicable: AUTO-V LoZ / annunciator pop-up (none of these points), square-wave sources (none), IR (none), REL.
- Calibrator: 5522A or 5560A (the manual names a 5500A); only existing driver commands (`OUT ...V,<f>Hz`, `OUT ...A`, `OUT ...OHM`, `OUT ...NF / UF`, `TC_TYPE K` + `OUT ...CEL` for temperature), nothing new, no registry change. Sections: AC / DC volts, DC mV, diode, frequency rows: NORMAL output;
  ohms: NORMAL (2-wire); capacitance: NORMAL; currents up to 400 mA: AUX (5522A) / VI AUX (5560A); 4 A / 9 A: 20 A (5522A) / 30 A (5560A); temperature: TC connector + Fluke 80AK adapter (Table 1), K-type thermocouple.
- Frequency rows (AC and DC volts frequency) are sourced as AC volts and READ in Hz / kHz: `no_uncertainty` is set (the calibrator's voltage uncertainty is not a frequency uncertainty) and the natural-unit guard (`tartur.NATURAL_UNITS`) blanks TAR / TUR. Existing quirk found, NOT changed: the 77 IV, 110-series and 87V frequency steps still
  print the voltage uncertainty with a Hz unit (e.g. '2.9 mHz' on 5 V at 50 kHz); set `no_uncertainty` on those steps (a spec-only change) if the lab agrees.
- TAR / TUR (calibrator 5522A): below 1:1 at 9 A AC 1 kHz (0.6:1), about 1.8:1 at 400 mA AC 1 kHz and on capacitance; the report prints what it computes.
- Shared-engine / shared-file edits (all small and additive): `handheld_dmm.py` one line (opt-in per point: `no_freq_suffix` true drops the 'at f Hz' from the report Nominal of a frequency reading; set only on the 170 Hz-unit frequency rows, every other procedure's report is unchanged); `hookups.py` + `specs/build_hookups.py` meter `fluke170` (8 diagrams drawn,
  only the 170 files; the other diagrams are byte for byte unchanged); `Calibration_Procedure_Manager.py`; `verified.py`. The fingerprint of the verified Fluke 117 changes with `handheld_dmm.py` / `hookups.py` (verified.py shows 'Changed since verification'); its behaviour did not change.
- Verified from the manual: jacks named VOhm, 400 mA, 10 A, COM (pp. 2, 3, 9; fuses 440 mA / 11 A p. 18); the four front buttons HOLD, MIN MAX, RANGE and a blank YELLOW button (Figure 1, p. 3; 'B (YELLOW button)', p. 14); the LEAd test-lead alert (p. 2); footnote 1 'Press the yellow button to access this function'
  (capacitance, diode, DC mA, DC A, AC / DC volts frequency, temperature); note 2 (ohms exclude lead resistance); note 3 (correct cable) and 4 (20 minutes soak) for temperature; AC current noise note (short VOhm to COM or leave it unconnected, p. 9).
- UNVERIFIED (Mike to confirm on the real meter): the rotary switch positions, their order and the yellow-button sequence (the manual has no dial figure; the 'Change the function' prompts use the table's own 'Test (Switch Position)' names and the footnote wording, and do not invent a toggle sequence; whether Ohms / Continuity / Diode /
  Capacitance share one position); the jack ORDER and layout (the diagrams draw an 87V-style row 10A, 400 mA, COM, VOhm); that temperature is on the mV position with the yellow button (the manual says only 'press yellow'; 179 only); °C / °F selection on the 179; the ranges / resolutions listed above; the 30 V threshold;
  calibrator capacitance output (`OUT <n>NF / UF`, unverified on both calibrators), DC current (`OUT <n>A,0Hz` unverified on the 5560A), thermocouple output (`TC_TYPE K` / `OUT <n>CEL` unverified on both) and whether the calibrators can make 9 A at 1 kHz, 30 V at 50 kHz and 1000 V at 1 kHz (the calibrator refuses what it cannot; the run stops).
- Tests: `tests/test_170_points.py` (spec vs an independent second transcription of both tables, accuracy check, the three corrections, padding, prompt / cable / HV sequences, wire commands on both simulated calibrators for all three models, full runs, PDF, demo, checkpoint, registration; tkinter stubbed in setUpModule).
  The Tk windows were not viewed (no tkinter here). `tests/test_tartur_wiring_dmm.test_off_identical_to_baseline` compares PDFs byte for byte and fails on a clean `main` too (a time stamp inside the PDF), unrelated.

## Keithley Model 2000 notes (branches `keithley-2000`, revision `k2000-rev1`; checked on the simulated bench and on a real Tk under Xvfb only, never run on hardware)
- REVISION 1 (`k2000-rev1`, lab owner's answers; everything below is already updated to it): (1) one interval only, 1 year 18-28 C (no 90-day / 24-hour limits); (2) AC detector bandwidth 3 (slow) on every AC point, AC settle raised to 20 s;
  (3) digital filter: the manual's 10-reading REPEAT filter stays ON for DC volts, DC current and ohms and is OFF for AC volts and AC current (see the INTERPRETATION below); (4) the optional 700 V @ 50 kHz point is gone, 219 V @ 50 kHz stays (37 points, all default);
  (5) the calibrator interface is RS-232 by default (GPIB selectable); (6) the manual's "recalculate ohm limits" step is intentionally not implemented; (7) 100 Mohm is a pure 2-wire point on the 2000's 2-wire resistance function.
- INTERPRETATION TO CONFIRM (filter): the answer to the filter question was "10-reading REPEAT filter on every function, including AC: No". It is built as: filter ON (REPEAT, 10 readings) for DC volts, DC current and ohms, which is the manual / specification-sheet condition, and filter OFF for AC volts and AC current
  (`:SENS:VOLT:AC:AVER:STAT OFF`, `:SENS:CURR:AC:AVER:STAT OFF`, read back; no type / count is sent for AC). The other reading ("No" = filter off everywhere) would be a one-line change in the spec (`measure.filter_state`). Spec keys: `measure.filter_state` (DC / ohms), `measure.ac_filter_state`, `measure.ac_bandwidth`.
- AC settling (UNVERIFIED ESTIMATE): at bandwidth 3 one reading takes about 2 s (specification sheet, AC operating characteristics: SLOW, 3 Hz-300 kHz, 2 s/reading; User Manual chapter 3 "Bandwidth": the RMS value is calculated from 1200 samples at 1 kHz = 1.2 s). Neither manual gives a settling time for the RMS converter at 3 Hz after a change of level or
  frequency. The wait from OPER to the first `:READ?` of an AC point is therefore a conservative engineering value, `k2000.settle.ac` = 20 s (was 6 s at bandwidth 30), tunable in procedure modifications (0.2-120 s). The first reading is not discarded. Tune it on the real meter; the AC prompt says so.
- Sources: Keithley Model 2000 Multimeter Calibration Manual 2000-905-01 Rev. F (Aug 2007), section 1, Tables 1-2 .. 1-6 (printed pp. 1-7 .. 1-13), and the Model 2000 User Manual 2000-900 Rev. J (Aug 2010) for every command.
  Limits were read from rendered page images twice. ONE interval is printed (1 year, 18-28 C, calculated from the one-year accuracy specification, without calibrator uncertainty, p. 1-5): `periods` is just `["1y"]`. The 90-day / 24-hour limits
  are NOT in the verification tables and are NOT built (lab decision: 1-year limits only). `specs/build_k2000_spec.py` recomputes every printed half-width in Decimal from the one-year accuracy specification and aborts on a disagreement:
  all 37 built points agree (38 before the 700 V @ 50 kHz point was removed); the only rounded printed value is 219 V @ 50 kHz (printed 218.362 to 219.638 V, exact 0.6378, the printed 0.638 is used, the exact one is kept in `computed_limit`).
- Points (37, all run by default): DC volts 10 (+/- each of 100 mV, 1, 10, 100, 1000 V), AC volts 10 (1 kHz and 50 kHz on 100 mV, 1, 10, 100 V; 700 V @ 1 kHz; 219 V @ 50 kHz, the manual's own substitute for 700 V @ 50 kHz, with its note kept), DC current 8 (+/- 10 mA, 100 mA, 1 A, 2.2 A on the 3 A range), AC current 2 (1 A and 2.2 A @ 1 kHz),
  4-wire ohms 6 (100 ohm .. 10 Mohm, decades), 100 Mohm 1 (own hook-up group OHM100M, kind OHM2). The 700 V @ 50 kHz point (optional in the first version, hand-sourced, 5725A) is REMOVED: no spec point, no checkbox, no dialog, no diagram entry, no tests; there is no hand-sourced point and no `source: manual` path any more (the `k2000.settle.manual` tunable was removed with it).
  The manual verifies no frequency, temperature, diode, continuity or capacitance, and has no separate 2-wire ohms table.
- Standards: DC volts / current, AC volts / current, ohms: Fluke 5560A or 5522A (the manual names a 5700A). With the 5522A the AC current points (TUR about 0.1-0.3:1) and 100 V @ 50 kHz (0.6:1) come out below 1:1; with the 5560A every point is at least 1.4:1 TUR. Whether either calibrator can make 700 V @ 1 kHz and 219 V @ 50 kHz is not verified here (the 5522A
  is specified 45 Hz-10 kHz only from 330 V up; 219 V is below that, but check; a calibrator that refuses an output stops the run before OPER).
- Measurement conditions (spec `measure`): DC volts, DC current, ohms: 1 PLC (medium), digital filter ON, 10 readings, REPEAT type (one :READ? = ten fresh conversions). AC volts and AC current: detector bandwidth 3 (slow; was 30), digital filter OFF, one :READ? (about 2 s). Manual range for every point (the range command takes 90 % of the range as the
  expected reading), autorange asserted off. The spec sheet's "add ppm of range" extras are waived with a filter of 10 (footnote 1); the AC low-frequency error is 0 at 1 kHz and 50 kHz for SLOW as well as MED (AC low frequency errors table), so the printed limits stand unchanged. A manual inconsistency, resolved by setting everything explicitly:
  User Manual Table 5-6 lists the filter default OFF while Table 2-2 / the Cal Manual say ON / moving average.
- DC volts REL (Cal Manual p. 1-7 steps 2-4): after each reset the first DC volts point does the zero: 100 mV range, calibrator `OUT 0V,0Hz` in operate, settle, `:READ?` (a reading must exist, p. 5-44), `:SENS:VOLT:DC:REF:ACQ`, `:REF?` compared with the reading, `:REF:STAT ON`, read back,
  calibrator to STBY. REL stays on for DC volts and is set OFF (and read back) on every other function. The state is read from the meter (`:SENS:VOLT:DC:REF:STAT?`), so a re-run after a reset zeroes again.
- Resistance: calibrator STBY, `OUT <n>OHM`, then on the 5522A `ZCOMP WIRE4` (4-wire points below 110 kohm) or `ZCOMP NONE` (110 kohm and up, and the 2-wire 100 Mohm point), read back with `ZCOMP?` (5522A Operators Manual p. 6-49), `ERR?`, then `OPER`. The 5560A has no such command in the project manuals:
  the operator sets its own 4-wire / 2-wire mode (the hook-up prompt says so). "Recalculate the limits from the actual calibrator values" (p. 1-5, p. 1-12, the blank columns of Table 1-6) is intentionally NOT implemented (lab decision): the printed limits are used.
- 100 Mohm (rev 1): a pure 2-wire hook-up. The 2000 is set to `:SENS:FUNC 'RES'` (the SCPI short form of 'RESistance', User Manual p. 5-37 :FUNCtion list, "Select 2-wire Resistance"; not FRES) with `:SENS:RES:RANG 90000000`, NPLC 1, filter ON REPEAT 10; INPUT HI / LO only, nothing on the SENSE Ohms 4 WIRE jacks, calibrator external sense OFF (5522A ZCOMP NONE, 5560A 2-wire mode set by the operator).
  The limit is kept as printed (99.8470 to 100.1530 Mohm). The Calibration Manual does NOT give 100 Mohm under a separate Ohm2 table: Table 1-6 is the single resistance table, its procedure (p. 1-12) selects the Ohm4 key once (step 3) and steps 7-10 only change the hook-up (Figure 1-6, which still draws the SENSE jacks) and the range, so the printed 100 Mohm limit was written for the 4-wire function.
  The specification sheet has one "Resistance" row for 2-wire and 4-wire (1 year 1500 ppm + 30 ppm of range at 100 Mohm) with note 15: "Specifications are for 4-wire ohms. For 2-wire ohms, add 1 ohm additional uncertainty": 1 ohm on 100 Mohm is 0.000001 %, negligible against the printed +/-153 kohm, so the printed limit is not changed. The builder cross-check still passes.
- Calibrator interface (rev 1): RS-232 is preselected in the settings drawer ("Calibrator interface", default RS-232, remembered), GPIB stays selectable; the port / address typed for each interface is remembered separately (RS-232 default COM9 at the calibrator baud, GPIB default example GPIB0::4::INSTR: the GPIB address is only an example, UNVERIFIED, enter the real one; the baud rate is sent on RS-232 only). The meter's own interface is unchanged (GPIB default, its RS-232 assumptions below stay UNVERIFIED).
- Interface (the Model 2000's): GPIB (default address 16, p. 4-12; `GPIB0::<n>::INSTR`, no remote command, GTL on exit through `Transport.go_local`) or RS-232 (`:SYST:REM` at connect, `:SYST:LOC` on exit; 8 data bits, no parity, 1 stop bit; baud 300-19200, default 4800; TX TERM LF / CR / LFCR; flow none / XON-XOFF; CR to end what is
  sent). RS-232 supports SCPI only. Bench settings assumed (UNVERIFIED on the real meter): GPIB 16, RS-232 4800 baud, TX TERM LF, flow none, write terminator CR.
- Driver `drivers/keithley_2000.py`: 101 registry commands, every one with a page reference and a `verified` flag. VERIFIED (63): *CLS, :SYST:ERR?, :SYST:FRSW?, :SYST:REM / :LOC, :SYST:AZER:STAT?, :INIT:CONT OFF, :FORM:ELEM READ, :READ?, :FETC?, *RST (locked; never :SYST:PRESet), *OPC? (locked),
  and for each function :SENS:FUNC '<f>', :RANG <expected>, :RANG:AUTO?, :NPLC (DC / ohms) or :DET:BAND (AC, default 3), :AVER:TCON REP, :AVER:COUN, :AVER:STAT ON/OFF, :REF:STAT ON/OFF, DC volts :REF:ACQ, :REF? and :REF:STAT? (the manual states "0 or 1" for DC volts); ZCOMP / ZCOMP? on the 5522A.
  UNVERIFIED (38: the QUERY commands exist in the manual but the reply TEXT is not stated, so the parser is tolerant of case, quotes, 0 / OFF, 1 / ON and any number format and strict only about a clearly different value): :INIT:CONT?, :FORM:ELEM?, :SENS:FUNC?, every :RANG?, :NPLC?, :DET:BAND?,
  :AVER:TCON?, :AVER:COUN?, :AVER:STAT?, and :REF:STAT? of AC volts / DC current / AC current / ohms. Also unverified: the 5560A OUT? / ERR? behaviour at 700 V and 2.2 A, the 5560A's 4-wire command, the 5522A current terminals and the hook-up wording for 1 / 10 / 100 Mohm.
  Writes are set, read back, compared and never retried; read-only queries (:FETC?, :SYST:ERR?) may retry; :READ? never. The error queue is read to empty after configuring and after reading (the queue holds 10).
- Engine `keithley2000_verification.py` (a copy of the truevolt engine shape): `IO.measure` = STBY, INPUTS switch must be FRONT (`:SYST:FRSW?`, it cannot be set remotely), [REL zero], configure + read back + error queue, source (explicit `,0Hz` on DC), compensation, `ERR?`, OPER, settle, `:READ?`, error queue, STBY (also on any error).
  Prompts: a start prompt (1 hour warm-up, 18-28 C, RH < 80 %, INPUTS FRONT, no scanner, p. 1-3 / 1-6), a hook-up prompt on each group change (DCV, ACV, DCI, ACI, OHM4, OHM100M), a high-voltage confirmation at 100 V and above. Settle waits are engineering values (the manual says only to let the signal settle), tunable
  (`k2000.settle.default 2 s, .ac 20 (UNVERIFIED estimate for bandwidth 3), .dci 3, .ohm 3, .ohm_high 5, .rel_zero 5`). Pass / fail is Decimal (|reading - nominal| <= error); the displayed limits are the float `error` of the shared engines (display only).
- Report: PDF 'Calibration Data' named `<asset>-MM-DD-YYYY.pdf`; uncertainty and TAR / TUR through `report_pdf.point_row(standard=<calibrator>)` / `tartur_wiring.point_fields` (negative nominals give the same values as positive). Demo mode is the virtual bench (`drivers/simulated_k2000.py`; records synthetic, DEMO-stamped, nothing in Asset History).
- Did not map to the engine, or deliberately not done: 90-day / 24-hour limits (not built, lab decision); the 700 V @ 50 kHz point (removed, lab decision); no 5560A compensation command; the adjustment procedure (not built, see below). The manual's "recalculate the ohm limits from actual calibrator values" is intentionally not implemented (lab decision), no longer a gap.
- Still UNVERIFIED after rev 1 (bench read-back reply formats are not available yet): the reply TEXT of every read-back query (the 38 `verified=False` registry entries, now including `:SENS:RES:...?` for the 2-wire function and the AC `:AVER:STAT?` reading 0), the AC settle of 20 s, the filter interpretation above, `:SENS:FUNC 'RES'` reply text, the GPIB example address of the calibrator, the 5560A 2-wire / 4-wire setting (operator), the meter's assumed GPIB / RS-232 bench settings, rotary / terminal wording of the hook-up prompts, and whether the 5522A / 5560A accept 700 V @ 1 kHz, 219 V @ 50 kHz, 2.2 A and 100 Mohm.
- ADJUSTMENT (NOT built; for a later `Keithley_2000_Adjustment.py` like the 8846A one). From the Calibration Manual section 2 (procedures) and section 3 (command reference, pp. 3-2 to 3-21): a 5700A-class source (Table 1-1), 1 hour warm-up, unlock `:CAL:PROT:CODE 'KI002000'` (default code, sent ONCE; never logged,
  masked like the 8846A password), `:CAL:PROT:INIT`; DC steps `:CAL:PROT:DC:STEP1` (front short) / STEP2 (open) / STEP3 +10 V / STEP4 -10 V / STEP5 100 V / STEP6-9 1 k, 10 k, 100 k, 1 M (4-wire) / STEP10-13 10 Mohm, 10 mA, 100 mA, 1 A with the exact calibrator value as the parameter (STEP0 = rear short;
  STEP10-13 DIFFER BETWEEN FIRMWARE A19 and A20: A19 and earlier have no 10 Mohm step and steps 10-12 are A20's 11-13: read the firmware from *IDN? first), AC steps `:CAL:PROT:AC:STEP1-13` (10 mV 1 kHz; 100 mV, 1 V, 10 V, 100 V at 1 kHz and 50 kHz; 700 V 1 kHz; 100 mA, 1 A, 2 A at 1 kHz; STEP14-15 are manufacturing steps),
  then `:CAL:PROT:DATE`, `:CAL:PROT:NDUE`, `:CAL:PROT:SAVE` (constants are temporary until saved), `:CAL:PROT:LOCK`. Step completion is detected with `*OPC?` (MAV in the status byte) or `*ESE 1` + `;*OPC` on the same line and the ESB bit (pp. 3-20, 3-21); `*CLS` clears it.
  Feasible with the same pieces (ordered steps, set / read back / compare where a read-back exists, masked code, operator hook-ups, calibrator `OUT` + OPER / STBY, an `*OPC?` wait per step); open points: a 5522A cannot make all of the AC steps at the accuracy the manual wants (700 V), and the low-thermal short steps need the operator.
  Manufacturing calibration (OPEN-key power-up, 1 V rms at 10 Hz / 1 kHz and a function generator) is out of scope.
- Shared-file edits (small, additive): `drivers/transport.py` (`Transport.go_local()` no-op, VISA GPIB sends GTL), `drivers/__init__.py`, `procmods_engine.py` (`_t('k2000', ...)` tunables and `MODEL_IDS['k2000']`), `Calibration_Procedure_Manager.py` (STABLE, VERSIONS, records), `verified.py` (FILES), tests (`tests/golden_capture.py`, `tests/golden_engines.py`,
  `tests/test_procmods_engines.py`, `tests/test_reset_startup.py`; golden fixtures `keithley_2000.json`, `engine_keithley_2000.json` added, every other fixture unchanged byte for byte).
- Tests: `tests/test_k2000_points.py` (spec second typing, no 700 V @ 50 kHz point, AC bandwidth 3 / filter off, 2-wire 100 Mohm, calibrator interface default, printed text vs numbers, builder reproduces the file, driver on the simulated 2000 over GPIB and RS-232, command order, no retried write, REL, ZCOMP, refusals, Decimal judge, report rows, TAR / TUR, virtual run, registration).

## Testing
Python with tkinter, `pyvisa`, `pyserial`, `reportlab`. Run any launcher with `--demo` for no hardware.
Real-window tests (need a display; `xvfb-run -a python -m unittest tests.test_asleft tests.test_specmanager`).
Simulated bench: `drivers/simulated.py` (`make_dacq_bench`, `make_dmm_bench`, `make_bench`).

## Procedure modifications in the engines (procmods_engine.py)
Every procedure (truevolt, dacq, fgen, handheld, 34401A, 8846A, MDO4000C, WaveSurfer) mixes in `procmods_engine.ProcModsMixin`. At the start of a Run
(`pm_begin_run`) it loads the stored overrides for the model / instrument ID, patches the point list in place (skip, text, per-point settle, and - only
from valid, enabled, HMAC-verified `limit` rows - error / low / high), and binds the command overrides to the drivers (`use_commands`). Tunables are read
with `self.pm_param(name, default)`: with nothing stored it returns `default` itself, so unmodified runs are byte-identical (the golden transcripts prove
it). What is tunable is listed in `procmods_engine.TUNABLES` (name, default, bounds); a default declared there must equal what the engine passes (a test
checks it). Ranges are not tunable (they are part of a point's identity and of the manufacturer's table). Engines that judge `low <= x <= high` while the
point also carries `error` (8846A) are registered with shape='band': create overrides against `pm_limit_points()`. The report reads
`procmods_engine.applied_modifications(run)` / `applied_info(run)`; the checkpoint carries `overrides` (snapshot) only when something is modified.
New procedure rule: wire the mixin (pm_init / pm_begin_run / pm_attach / pm_checkpoint_fields / skip filter) and read every settle time through pm_param.

## Standards specification manager and uncertainty budget
- `specs/build_standard_spec.py <SpecTrack pdf>` reads a manufacturer accuracy sheet into `specs/standards/<maker>_<model>_standard.json` (with a `problems` list
  from `specmanager.validate_data`).  `specmanager.seed()` loads those files into **lab_registry.sqlite3** (tables standards, standard_assets, spec_rows,
  spec_changes); calibration_procedures.sqlite3 is untouched.  All values are SI base units; scaling is display-only.
- `uncertainty_budget.py`: u(standard) = published accuracy / divisor (2.0 when the sheet gives no confidence level or says 95 % (laboratory convention), 2.576 for 99 %, editable per standard),
  u(resolution) = calibrator last digit / sqrt(12), EMU = k * RSS, k = 2.  Reported = larger of budget and A2LA scope CMC, rounded UP (never below either).
  `audit(reported, budget)` returns OK / UNDER CMC / UNDER BUDGET / NOT IN SCOPE.
- `report_pdf.point_uncertainty(p, standard=None)` uses the budget when the calibrator model is passed (handheld_dmm passes 5522A / 5560A from its calibrator
  choice; truevolt_verification, Procedures/Agilent_34401A.py and Procedures/Fluke_8846A_Verification.py pass 5560A; dacq_verification passes the selected
  calibrator).  Every multimeter procedure now uses the budget.  The MDO4000C, FGEN and WaveSurfer (oscilloscope / generator) engines are still CMC-only.
- Temperature (thermocouple simulation) uncertainty and TAR / TUR, all handheld multimeters (110-series 116, 87V, 287/289, 170-series 179; the Fluke 77 and Klein MM325 have no temperature point):
  the handheld engine sources Type K from the 5522A / 5560A (`TC_TYPE K` + `OUT <t>CEL`, through the 80AK adapter) and the report row now gets an Uncertainty and TAR / TUR from the
  calibrator's published 1-year Type K SIMULATION specification in degC (`specs/standards/fluke_5522a_standard.json` / `fluke_5560a_standard.json`, kind TEMP, direction output, loaded
  into lab_registry.sqlite3 as for every other kind; no new data file).  `specmanager.StandardSpec.lookup_temperature(celsius, tc='K')` is the lookup (signed closed bands, degC rows only, larger
  limit on a border, never extrapolates; the generic `lookup()` works on magnitudes and would mix in the degF rows, so TEMP does not use it).  `uncertainty_budget.build` routes kind TEMP to it:
  u = spec / 2 (+ resolution / sqrt(12) when known), EMU = 2 * RSS, rounded UP to 2 sig. figs.  Printed like '0.17 degC' (`uncertainty.format_value`, never SI-prefixed).  TAR = (high - low) / 2 / spec in degC;
  TUR = the same tolerance / the printed uncertainty.  Outside the calibrator's range (-200 to 1372 degC), with no calibrator chosen, or for a degF point: Uncertainty / TAR / TUR print N/A.
  `Temperature, open input` (functional check, no source) stays N/A.  `handheld_dmm.App.has_uncertainty` decides which points carry an uncertainty; `temperature_note()` adds the basis to the stored footer note.
  Manual values (5522A Operators Manual R0, Ch. 1 'Temperature Calibration (Thermocouple)', printed p. 1-17 = PDF page 37, read from the page image twice), Type K, degC, 90 day / 1 year:
  -200..-100 0.25 / 0.33, -100..-25 0.14 / 0.18, -25..120 0.12 / 0.16, 120..1000 0.19 / 0.26, 1000..1372 0.30 / 0.40; resolution 0.01 degC (note 2) is used for the 5522A (`specmanager.TC_RESOLUTION`; a value edited in
  Standards Specs wins); note 3: 'does not include thermocouple error'.  5560A (checked 2026-10-22 against the 5560A Product Specifications Rev. 8, 6/26, 'TC Specifications', Type K rows on PDF p. 17 = printed p. 16, table header and resolution on printed p. 15, rendered page image):
  1 year, 95 % confidence column, degC: -200..-100 0.22, -100..-25 0.10, -25..120 0.09, 120..1000 0.16, 1000..1372 0.27 = the stored sheet values, unchanged (they were the 95 % / 1 y column; the 5560A sheet is stored at
  95 %, divisor 2, for every function, so TC uses the same column; the 99 % / 1 y column prints 0.28 / 0.13 / 0.11 / 0.21 / 0.35, 99 % / 90 d 0.22 / 0.10 / 0.09 / 0.17 / 0.28).  The 5522A values above are the manual's single
  published column, stored with no confidence on the sheet (divisor 2 assumed), so the two calibrators are not on the same confidence level: unchanged, to be decided by the lab.  Resolution 0.01 degC is printed (p. 15)
  and is now in `specmanager.TC_RESOLUTION['5560A']`, so the 5560A budget includes it as the 5522A does: reported 0.091 (0 / 100 degC, was 0.090), 0.17 (400, was 0.16), 0.11 (-40, was 0.10), 0.28 (1000, was 0.27), 0.23 (-200, was 0.22).
  A2LA: the shipped scope file (a2la_1888_03_cmc.json, Section V pp. 8-32 and XII) has no temperature entry, so NO CMC applies and none is invented: the budget alone is reported.  If the lab's scope lists
  a temperature CMC, add an entry {basis 'generate', kind 'TEMP', bands [{lo, hi (signed degC), rel, abs}]} to that file: `Scope.dmm('TEMP', t)` then floors the reported value as for every other kind (tests cover it).
  Spec condition: the manual's table states none for the reference junction ('tcal +/- 5 degC', 'source/measure', excludes thermocouple error).  The procedure never sends `TC_REF`, so the calibrator is at its reset
  default INT (internal isothermal block, p. 6-35; p. 4-37: use INT for alloy-wire thermocouples, EXT at 0 degC gives the best accuracy); no TC offset is used (TC_OFFSET is for measure mode only).  The printed figures are applied as published.
  `tests/test_beta_temp_uncertainty.py` (hand-computed 5522A / 5560A values, out-of-range N/A, PDF rows, demo marking); `tests/test_tartur_wiring_dmm.py::Exports::test_off_identical_to_baseline` now allows the 287 Temperature rows to differ
  from the baseline (Uncertainty only), like the 87V rows before; every non-temperature row is byte-identical.  `tests/dmm_export_harness.py` knows 'Fluke 116' / 'Fluke 179' (not in ENGINES) and a `cal_mode` argument.
- "Standards Specs" tab: divisor, assets, calibrator resolution per range (logged in spec_changes), sheet issues, "Check an EMU".
- Tests: `python -m unittest tests.test_specmanager`.

## Datasheet Builder core (stage A, branch dsb-core; no UI yet)
- `datasheet_builder.py` (model, exact-Decimal specification expressions, test point calculator, validation, versioned storage), `datasheet_builder_specs.py`
  (datasheet -> runnable `manual-reading` spec with the additive `dsb` extension), `datasheet_builder_match.py` (which imported standard sources / measures each
  point, TAR / TUR, driver capability table). API: module docstrings; extension schema: `specs/README.txt`.
- User datasheets live in the app data folder (`user_specs/`, versions kept, soft delete) plus two NEW tables in `lab_registry.sqlite3`
  (`user_datasheets`, `user_datasheet_versions`); `calibration_procedures.sqlite3` is untouched. Limits are exact (nominal -/+ tolerance), like `build_mm325.py`.
- `procspec.validate_manual_reading(spec)` checks handheld `manual-reading` specs (the shipped ones pass); `procspec.load` now accepts them.
- Not verified: every automation status marked 'unverified' in `datasheet_builder_match.DRIVER_TABLE` (capacitance / thermocouple outputs, 5522A scope option,
  5790B, 53131A/53132A); the example accuracy numbers in tests/dsb_fixtures.py are illustrative, not any manufacturer's.
- Tests: `tests/test_datasheet_builder*.py`.

## Datasheet Builder runtime (stage C, branch dsb-run)
- A saved user-built datasheet is listed by the Manager as its own row (`dsb_manager.user_rows()`, iid `ds:<uid>`, tag `user-built`; nothing is written to
  calibration_procedures.sqlite3) and launched through `Procedures/User_Datasheet.py --spec <file>` -> `dsb_runtime.main()`.
- `dsb_runtime.DsbApp` extends the handheld engine (handheld_dmm.App) with the spec injected, so reset-before-tests, standby after each point, function
  prompts, direct HV, explicit 0 Hz DC, reading padding, TAR/TUR, procmods, checkpoint/resume, As Found / As Left and the PDF are the engine's own.
  `handheld_dmm.py` got additive hooks only (build_points, reading_labels, checkpoint_problem, report_title/header/details, dsb_out/dsb_desc/dsb_device).
- `DsbIO` opens the standards: 5560A / 5522A (sources, scope option for scope points), 5790B and 53131A/53132A (measure generator outputs).
  Per point `route_for` picks the assigned standard when connected and able (driver_table / automation_status), else the engine's calibrator, else by hand.
  Writes are the drivers' set / read back / compare, never retried; outputs go to standby after each point.
- datasheet_builder.save() writes the runnable spec without a matcher plan, so `with_plan()` runs the matcher at load time (read only).
- Tests: tests/test_dsb_runtime.py (units), tests/test_dsb_runtime_bench.py (simulated benches; tkinter stubbed, harness in tests/dsb_run_harness.py).

## Regenerate a report PDF from Asset History (branch reprint-pdf)
- `report_snapshot.py` (UI-free): `report_pdf.write_calibration_pdf` (the one function every engine's PDF goes through) calls `report_snapshot.record_issued` after it writes a REAL
  (non-demo) report that has an Asset History event; it stores header, title, details (technician, conditions, standards with cal info, TAR / TUR choice), the rows exactly as printed,
  footer note, modifications list, printed issue date and version stamps as canonical JSON with a SHA-256, in the NEW table `report_snapshots` of lab_registry.sqlite3 (key = `runs.id`,
  the history event; `ON DELETE CASCADE`). Engines pass the stamps with `snapshot_context=report_pdf.context_for(self)`. Nothing raises on a missing / damaged database; the PDF is unchanged.
- Rows are stored as the display strings that were printed (report_pdf.cert_row already scaled them); no SI numbers exist at that boundary, so none are stored.
- Asset History tab (`labregistry_ui.HistoryPanel`): button, right-click menu and double-click choice on a report row call `report_snapshot.regenerate`: verifies the hash (a mismatch is
  refused, never replaced by a rebuild), asks where to save (default `asset-MM-DD-YYYY.pdf` with the ORIGINAL issue date), asks before replacing any existing file, writes through
  `write_calibration_pdf(issued_at=..., reprint_note=..., record_history=False)`: original Report date kept, one footer line added, no new history event.
- Events from before this feature (no snapshot) are rebuilt from the history rows only if those are complete (point count and fail count agree, every point has As Found and limits); the
  PDF is then marked REBUILT on every page and leaves As Left, uncertainty, TAR/TUR and modifications blank (history does not store them). Otherwise a plain message says what is missing.
- Not stored anywhere today (so not in any snapshot): procedure modifications are not printed by any engine (`modifications=` is never passed) - their summary is kept in the stamps only.
- Tests: `tests/test_reprint_*.py` (named to sort after test_beta because they install tests/_tk_stub.py); `tests/reprint_harness.py` runs the engines' real export code on the simulated benches.


## Live procedure editor (branch live-editor)
"Edit point" (formerly "Edit procedure"; see the next section) in every running procedure window opens the per-point window; the whole-procedure procmods editor (ModifyWindow) is no longer reachable from a running procedure (the point window's "All procedure changes..." button was removed; the module is kept). Logic is in
procmods_live.py (LiveState, diff, events, LiveBridge) and the pm_* live methods of procmods_engine.ProcModsMixin; tests: tests/test_beta_live_editor*.py.
- Edits are saved at once but applied only at the next point boundary (`pm_step`, or `pm_live_boundary` for WaveSurfer). The point in flight is never changed. Outputs go to standby first (a failed standby stops the run and leaves the edits saved); the instrument reset is not re-run.
- Every edit is an event in the run's audit trail (`live_edits` in the checkpoint; who/when/old/new/before_point) and a normal override, or run-only ("this run only"). Developer-mode gate, locked/risk commands, verified flags and HMAC limit rules are unchanged. Live editing is blocked while a pinned progress file or a factory run is active.
- Limits: allowed with the existing rules (devmode, reason, HMAC). The tolerance of a point that already has a reading changes only together with a redo of that point.
- Redo uses the engine's own queue (no automatic write retries). WaveSurfer has no skip and no redo. Demo edits are marked DEMO and stay run-only.
- Covered: truevolt, dacq, fgen, handheld family (incl. DsbApp by inheritance), 34401A, 8846A verification, MDO4000C, WaveSurfer. Not wired: TDS2000C (no procmods layer), Fluke_8846A_Adjustment.
- Unverified: the Tk windows (never viewed); live command edits (no engine supplies a test_command); the simulator accepts command shape only.
- 5522A OUT? reply for a square wave (observed on the bench): `2.000000E+00,VPP,0E+00,0,6.000E+01` for 2 Vpp at 60 Hz = amplitude, unit VPP, 0, 0, frequency. The square-wave read-back requires unit VPP.
## Datasheet Builder grid editor (branch dsb-grid-ui)
- The editor window is now one spreadsheet-like grid (`datasheet_builder_ui.GridEditorWindow`, drawn on a Canvas by `SheetCanvas`) instead of the seven-step wizard: columns STEP NUM, FUNCTION TESTED,
  NOMINAL VALUE, AS FOUND, AS LEFT, Out of Tol, CALIBRATION TOLERANCE; an Edit Cell bar above it; the spec boxes (Select Spec Types, entry fields, Calc / Recalc, Test Point Definitions) below; a tool column at
  the right (symbols, Ins. Header, Warnings, row remark, Run this row, Lock Status). As Found / As Left stay blank: the printed sheet is a template, never a record (the preview says so).
- All grid logic is in `datasheet_builder_ui_model.GridModel` (a subclass of EditorModel; tkinter-free): rows, selection, keys, cell edits, the boxes -> tolerance (Decimal expression model), multiple test points,
  undo (the EditorModel snapshot gate), print view / PDF. `GridGeometry` holds the pixel maths. The older detail pages (Ranges, Specification table, Sections, Details, Standards and automation) open from More.
- Core change, additive only: `Point.spec` (optional list-of-one `SpecEntry` that governs that one point; written to JSON only when set). `Function.governing(point)` picks it, `limit_for` / `tol_text` / `export_spec`
  use it, and the function-level 'no_spec' error is raised only for points that have neither their own spec nor a function table entry. Old files (no `spec`) load and export unchanged; the schema id stays 'dsb-1'.
- Rows are created in an auto-made range (the next decade up from the nominal); Meas Res / Auto Res / Display Decs write `Range.resolution`.
- Tests: tests/test_dsb_grid_model.py (no tkinter), tests/test_dsb_ui_widgets.py (tests/_tk_stub.py; the stub now has a real `TclError`). The window has never been viewed on a real display.

## Verified on hardware, and the lock (branch `verified-lock`)
- `verified.py` (Tk-free): `Registry` over a NEW append-only table `proc_verify_events` (verify / unlock / relock / seed) in lab_registry.sqlite3; no existing table is touched.
  A procedure's key is its launcher file name (`Fluke_117_Verification.py`) or `ds:<uid>` for a user-built datasheet. State is worked out from the events (who / when / why).
- Seed: `verified.SEED` (code, shipped with every copy) = TDS2000C / TDS1000C-EDU (`Tektronix_TDS2000C_Verification.py`), WaveSurfer WS4104HD (`WaveSurfer_WS4104HD.py`), Fluke 117
  (`Fluke_117_Verification.py`). Written into the real registry the first time it is used; a registry given an explicit path (tests) is never seeded; an unreadable registry keeps the seeded ones locked.
  To seed another one, add it to `SEED` (or use the button in the Procedures list).
- Locked means refused where the edit is saved: `procmods.Store._insert` / `set_enabled` (devmode command / setting / point / text / tolerance edits, import), `procmods_ui_model.ProcModsModel.read_only_reason`
  (the editor before a run and the in-run editor, run scope included), `ModsState.live_blocked_reason`, `datasheet_builder.save` (existing uid) and `.delete`. The in-run 'Edit procedure' control is disabled with the reason
  (`procmods_ui.LiveHook`, green chip via `ui_shell.Shell.set_verified`). Running is unaffected; overrides saved before the lock stay and still apply. Locks are by model for library procedures (the saved changes are kept per
  model) and by key for user-built ones.
- Fingerprint (the files the procedure's own sidecar declares: launcher + engine + driver files, the spec / limit JSON, the saved overrides for the model; line endings and JSON layout ignored; see 'Per-procedure fingerprints' below) is stored at verification time.
  If a LOCKED procedure no longer matches it, it is auto-unlocked: one `unlock` event, who `system`, reason `files changed since verification: <files>` (`Registry.sync`, run by the list refresh and by `lock_reason`, so an
  editor never refuses a changed procedure and the event is written once). Status kind `changed` = 'Changed since verification - needs hardware re-verification' (warn, not green); it stays until 'Mark verified on hardware'
  is pressed again. 'Unlock for editing' (typed reason) remains for an unchanged procedure. User-built procedures are synced by the Procedures list (their spec path is known there).
  When you add a procedure to `Procedures/`, add its `Procedures/<id>.procedure.json` (its `fingerprint` block replaces the old `verified.FILES` table; `tests/test_verified_model.py` and `tests/test_procscan.py` fail otherwise). The suite never blocks an update.
- Not in the PDF reports. Tests: `tests/test_verified_model.py`, `test_verified_editors.py`, `test_verified_ui.py` (the windows have never been viewed).

## Per-point editor (branch point-editor)
Right-click a test point in any engine's point list -> Edit opens a small window for THAT point (procmods_point_ui.PointWindow; logic in tkinter-free
procmods_point_model.PointEditModel; tests: tests/test_point_editor_*.py). The toolbar button is now "Edit point" and opens the same window for the selected row;
the point window has no button for the old whole-procedure editor any more (removed on request; the module stays). Layout: grid, bounded command table (5 rows), scrolling details area, footer always visible, default 980x960 (clamped to the screen), minimum 720x560, resizable; viewed on real Tk 9 under Xvfb in light and dark. The menu item is disabled, with the reason,
on a verified/locked procedure and while that point is being measured. Storage, scopes, audit trail, next-point-boundary rule and redo are the existing
procmods / procmods_live layer; nothing in calibration_procedures.sqlite3 changes.
- Commands panel: the commands the engine will send for this point, in send order, with this point's values filled in. Derived by a DRY RUN of the engine's own
  point routine (`pm_plan_point`, procmods_plan.py) on throw-away drivers over simulator transports with a private clone of the override state; waits are skipped
  (thread-aware `dry_clock`); the live app, io, override state and clock are untouched. So the list cannot drift from the engine (tests compare it with the
  golden transcripts). Per row: registry key, rendered text, read-back query, risk class, verified/UNVERIFIED, changed-from-default marker, Restore default.
- Editable: NORMAL-risk commands. A command is edited as its TEMPLATE (cmdreg.validate requires the placeholders to be kept); locked/output rows are read-only with
  the reason. Stored as kind 'command', target `Driver:key@<pointkey>` (this point only; wins over a driver-wide override). Extra lines before/after the point:
  target `Driver:+before1@pk` / `+after2@pk`, at most `procmods_pointdef.MAX_EXTRA`; a write needs a read-back query and the expected reply; sent once, read back,
  compared, never retried; a mismatch stops the point (outputs to standby). Extra lines are logged `[EXTRA ... UNVERIFIED]`. Everything typed is UNVERIFIED.
- Developer mode (existing gate, devmode.py unchanged: passphrase, PBKDF2, 15-minute idle auto-lock, lock-out; UI `procmods_ui.shared_lock` / `UnlockDialog`): the
  window's toggle only asks that gate. While locked, the limit/nominal/unit/description fields are read-only and the saved scopes (this asset / this model)
  are unavailable. **A RUN-ONLY command edit (typed command, extra line, or removing one made this run) needs NO passphrase (Mike, 'no' to 'should typed
  commands need the passphrase even for a run-only edit'):** `PointEditModel` sets `ProcModsModel.run_commands_ungated`; `ProcModsModel.run_only_commands()` is true only
  when scope is 'run' and every staged item is a kind 'command' (a reset only of an entry in `ctx.run_entries`); `_write_set` then calls
  `procmods.make_run_entry(..., dev_gate=False)`, which `build_entry` honours ONLY for scope 'run' + kind 'command' (limit/param/text/point and every
  stored scope still raise without a session). Run entries are in memory (`ctx.run_entries`), so `procmods.Store` is never touched and its `_need_dev` gate is
  unchanged (tests/test_point_editor_store.py). Blocks that apply whatever the passphrase: verified/locked procedure, point in progress, locked/output-risk
  commands, extra-line rules (write needs read-back + expected reply, sent once, never retried, UNVERIFIED), reason, audit event (who/when/old/new/reason),
  DEMO marking. A mixed change (field edit + command) or a scope other than run still needs developer mode; if the idle auto-lock fires after a saved scope
  was chosen the scope falls back to 'run' and Apply for field edits is blocked. The older all-procedure window (ModifyWindow) is still fully gated. Run-only
  entries live until the instrument ID changes (`pm_state.load(asset=...)`) or the window closes, as before; they never reach the store or another window. When on: tolerance (low/high or +/- error), unit, nominal, description. Stored inside the HMAC-protected 'limit' value (`nominal`, `new_unit`,
  `description`, `fields`). Decimal parsing, display-only SI scaling, low<=nominal<=high unless one-sided, valid units, typed reason, acknowledgement that
  pass/fail changes. A tolerance change on a point with a reading forces a redo; unit/description alone do not.
- Scopes: this run only (default; the only one in demo, marked DEMO) / this asset / this model. Audit event carries who, when, old, new, reason, point id,
  effective-from (`[point X]`, redo list in `live_edits`).
- Engine support: truevolt, dacq, a34401, 8846A verification, fgen, MDO4000C, handheld family: commands + fields. Handheld points with no calibrator output or
  a Manual calibrator: fields only (no commands, a note says why). 8846A AC / capacitance / frequency points: partial commands plus the refusal the procedure
  raises. fgen FLAT / TIMEBASE and MDO: the plan depends on the chosen method / group (MDO shows the scope default-setup block as for the first point of a group).
  DsbApp: source points only. WaveSurfer: no per-point commands (its measurements are driven from the section code, not a point routine): tolerance only.
  Not wired: TDS2000C, Fluke_8846A_Adjustment.
- "Test command": no engine supplies one, so the window says "not tested".
- Unverified: the Tk windows (never viewed, only constructed under tests/_tk_stub.py); every typed command; the dry-run plan is made on the simulator and does not
  predict real replies; fgen / MDO nominal semantics.
- FIXED (branch engine-err-fix): the `work()` worker threads used `except Exception as exc: ... root.after(0, lambda: self._error(exc))`; `exc` is deleted when the
  except block ends, so the lambda raised NameError and a failed point (including a read-back mismatch of an extra line) never reached `_error`. Same bug in
  truevolt, dacq, fgen, Agilent_34401A, Fluke_8846A_Verification. Fix: `err = exc` inside the block and `lambda err=err: self._error(err)`. Nothing else changed
  (the standby-on-failure in the first four is as it was; fgen never had one). Guard: `tests/test_beta_except_closure.py` (AST scan of every repo .py except
  tests/ and .claude/: no lambda / nested def inside an `except ... as NAME` may read NAME) and `tests/test_beta_except_closure_engines.py` (failed measure
  reaches `_error` with its message, busy cleared, on the simulated benches). Not covered by the behavioural test: mdo, tds2000c, handheld, WaveSurfer (the scan
  found no occurrence there).



## Virtual bench (demo mode)
`--demo` = a real run with VIRTUAL instruments (`virtualbench.py`, Tk-free). `--fast-demo` = the old quick demo (no windows, no commands; Manager
checkbox "Fast demo (no windows)"). Apps use `VirtualMixin`: `demo` (any demo), `fast_demo`, `virtual`. An object with only `demo` counts as fast demo.
- Commands go through the REAL driver code over `drivers/simulated*.py` (`calibrator_transport`, `dmm_pair`, `dacq_pair`, fgen/TDS/MDO benches).
  Shared modules test `fast_demo` (not `demo`) for reset (`reset_startup.reset_then`) and standby (`procmods_engine.pm_standby/commit_live`).
- Operator actions that cannot be commands are done on the simulator after the prompt (`operator_sets_up`: Front/Rear, connect a standard;
  `fgen_operator_sets_up`; `mdo_operator_confirmed`). Simulator additions are opt-in (`SimBench.freq_aware`, `external_input`) so golden transcripts hold.
- Handheld typed readings: reading window + marked "Fill with a simulated reading (DEMO)" button (deterministic, in tolerance; "Include some failures"
  toggle in the drawer, seeded by point number). The operator may type anything. Instrument-read procedures read the simulator.
- Waits are scaled by `virtualbench.WAIT_SCALE`; driver-internal sleeps are not. Dialogs are never skipped.
- Evidence: title suffix [DEMO], banner, chip "Demo - virtual instruments", `synthetic=True` on every record, PDF stamped DEMO on every page,
  `CommandLog.virtual` => never appended to ~/.calibration_suite/command_log.txt, no Asset History / registry / standards usage, no settings saved.
- Not switched: WaveSurfer (`--demo` loads canned data; ~4000-line engine, SimScope covers only a few VBS commands), Fluke_8846A_Adjustment (demo
  issues no CAL commands on purpose - safety), IR reading of 287/289 (typed/Fill instead), 5790B / counter standards of user datasheets (done by hand).
- Editing engine/driver files changes their `verified.py` fingerprints: Fluke 117, TDS2000C and WaveSurfer show "Changed since verification" until re-marked.
- Tests: `tests/test_beta_virtual_bench*.py`, harness `tests/virtual_harness.py`.
## Looking at the windows on a real Tk (Linux sandbox)
- `uv python install 3.13` (python-build-standalone from GitHub; includes tkinter) + `xvfb-run -a -s "-screen 0 1600x1000x24" <that python> script.py`; screenshots with
  `PIL.ImageGrab.grab(bbox=..., xdisplay=os.environ['DISPLAY'])`. pip/PyPI is not reachable there: borrow Pillow/reportlab by putting the system `dist-packages` of the
  SAME minor Python on PYTHONPATH. `tests/real_tk_checks.py` + `tests/test_beta_real_tk_windows.py` drive the point window, Edit point, Mark verified / Unlock, the Datasheet
  Builder grid and Asset History Regenerate PDF on a real Tk (skipped without tkinter / a display). The older stub-based tests are designed for NO tkinter: do not run the
  whole suite under a real Tk.
- Point window layout (procmods_point_ui.py): grid; command table 5 rows then scrolls; details (selected command, add a line, developer fields) scroll; footer always visible.

## Procedure registration and packages (branch `procedure-packages`; checked on the simulated bench / throw-away trees and on a real Tk under Xvfb only)
- Registration: the Manager no longer lists procedures by hand. Each procedure is `Procedures/<id>.py` + `Procedures/<id>.procedure.json` (schema 1; fields in `procscan.py`'s docstring: id, name,
  manufacturer, model, category (= instrument class), version, order, launcher, engine, drivers, specs, `fingerprint {code, spec}`, `hookup {meter, diagram_prefixes}`, `seed_verified` / `seed_order`, `own_files`, `tests`).
  `procscan.scan()` reads them (cached on the sidecars' mtimes; a bad sidecar is skipped and listed in `ScanResult.problems`, it never stops the others). `Calibration_Procedure_Manager.init_db()` registers
  `[p.registration for p in procscan.procs(BASE)]` exactly as the old hand list did (same names, order, categories, launch behaviour; same `INSERT` / rename / de-duplication logic; the procedures table
  schema is untouched); `STABLE` and `VERSIONS` are filled from the scan. A launcher with no sidecar (`User_Datasheet.py`) is not a registered procedure.
  The sidecar is a separate file so editing metadata never changes a launcher (a launcher edit changes a verified procedure's fingerprint).
  New procedure = launcher + sidecar (+ spec / driver / diagrams / tests). Nothing to edit in the Manager, `hookups.py` or `verified.py` any more. Exception: a NEW handheld meter family still needs its
  `hookups.py` tables (not done from metadata; `hookups.py` and the engines were deliberately not touched).
  `tests/test_procscan.py` compares the scan with `tests/fixtures/legacy_registry.json`, the frozen hand-written lists of main 59cfe1c (records, STABLE, VERSIONS, verified.FILES, verified.SEED).
  Older tests that grepped the Manager source for the hand list use `tests/_registry_text.manager_text()` (the same strings rebuilt from the scan).
- Per-procedure fingerprints (`verified.py`): `FILES` is now a read-only view of the sidecars' `fingerprint` lists (paths only). A label `specs/x.json#117` = only the part of a shared multi-model spec that
  model 117 uses (its `models` entry and the steps that list it; everything common stays); `hookups.py#fluke110` = hookups.py with the other meters' entries of METERS / AVAILABLE / EXTRA left out
  (code and shared tables still count). So editing 113's steps or the 87V jack names no longer unlocks 117; a step shared by two models, the common part of the spec, `handheld_dmm.py`, `drivers/fluke_5560a.py`,
  `drivers/base.py`, `drivers/transport.py` and the hookups code DO still unlock everything that runs on them (they change what those procedures do). `hookups.py` was dropped from 287 / 289 (their spec has no `hookup_meter`).
  Records taken before this (whole files stored) are still compared: only the files declared TODAY are looked at, a sliced label is compared on the whole file when the record has none, a declared file the record
  lacks counts as changed (`Registry.changes_since`). Auto-unlock, the lock rules, `proc_verify_events` and the seed are as before. The three seeded procedures (TDS2000C, WaveSurfer, Fluke 117) are NOT re-marked.
  `verified.SEED` is derived from `seed_verified` in the sidecars; a package can neither add nor remove that flag (refused on import; an existing flag is kept when a package replaces its sidecar; `make_package` strips it).
- Packages (`packages.py`): zip with `manifest.json` at the root (package_format 1, procedure id / name / version, min_suite_version, author, created, requires, `files` [{path, sha256, size}], optional `verified` {date, who, fingerprint}).
  `packages.inspect()` checks everything and writes nothing; `packages.install()` repeats the check, refuses if the zip changed since the preview, backs up every replaced file to `Backups/packages/<folder>/<name>_backup_vNN<ext>`,
  writes atomically one by one, rolls back on failure, and records the import in the NEW append-only table `package_imports` of lab_registry.sqlite3 (procedure, version, zip sha256, origin, who, when, files, backups, unlocked, mark).
  `calibration_procedures.sqlite3` is never opened by the importer (the Manager registers a new procedure the usual way when the list refreshes). Allowed: Procedures/ specs/ drivers/ diagrams/ tests/ only; extensions .py .json .png .jpg .txt .md .csv;
  never executable / database names; `.py` is parsed with `ast`, never run. Zip-slip, absolute / drive / backslash / `..` / hidden / device-name paths, symlinks, unlisted or missing files, bad or missing checksums, a sidecar that disagrees,
  a duplicate display name, the seeded flag, unmet requirements (a fingerprint file that is neither packaged nor installed), newer format / suite, size limits are all refused. Engines at the suite root cannot be packaged (outside the allowed folders):
  they are `requires` (the target must have them); a NEW procedure's engine has to live in `Procedures/`.
  Verified: replacing files of a verified-and-locked procedure unlocks it (`unlock`, who `package import`); a package mark counts only if `file_fingerprint` (declared files with the package's files in place, no overrides) equals the mark and the model has
  no saved procedure changes; then a `verify` event (mark's date / name) follows. The mark is the exporting lab's claim: it proves identical files, not a hardware run. Other locked procedures hit by a replaced shared file are listed in the preview (`Preview.affected`) and show 'changed'.
  `tools/make_package.py <id> [--out DIR] [--include PATH] [--verified-mark] [--author NAME]` (`--list`). Zips are reproducible.
- UI: Procedures tab button 'Import procedure package...' (`Manager.import_package`: picker -> `packages_ui.ask_install` preview -> install -> refresh); Procedure Development tab 'Procedure packages' row = library folder setting
  (`~/.calibration_suite/packages.json`, key `library_folder`, default empty; the picker opens there; the preview says whether the file is inside it). The preview carries a plain warning that a package is program code, shows the origin
  (full path + sha256), and keeps Install disabled until a confirmation box is ticked. No hosting, no database of packages. Tests: `test_procscan`, `test_packages`, `test_fingerprint_isolation`, `test_packages_ui`, plus `checks_import_package` in
  `tests/real_tk_checks.py` (run by `test_beta_real_tk_windows`; screenshots when PKG_SHOTS is set).
- UNVERIFIED / limits: nothing here sends an instrument command. The package windows were viewed on a real Tk under Xvfb only (Linux), never on Windows. Mark validity cannot prove a hardware run. Packaging of engines at the root and of a new `hookups.py` meter family is not supported.
