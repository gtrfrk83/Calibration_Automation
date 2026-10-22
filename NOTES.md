# Calibration Suite: project notes

Tkinter calibration suite. `Calibration_Procedure_Manager.py` (v69) launches one procedure per instrument from `Procedures/`.
Procedures are driven by JSON specs (`specs/`) of the manufacturer's performance-verification tables; shared engines hold the UI and run logic.

## Layout
- `Procedures/`: launchers (one per instrument), checkpoints are written here at run time (git-ignored).
- `specs/`: `*_pv.json` test points and limits, plus the `build_*.py` scripts that wrote them. See `specs/README.txt`.
- `drivers/`: instrument drivers, transports (VISA / pyserial), simulators (`simulated.py`). See `drivers/README.txt`.
- Engines: `truevolt_verification.py` (Keysight Truevolt), `dacq_verification.py` (34970A/34972A), `handheld_dmm.py` (Fluke 110-117, 87V, Klein MM325), `mdo4000c_verification.py`, `tds2000c_verification.py`, `fgen_verification.py` (33210A/33220A/33250A).
- `labregistry.py` / `labregistry_ui.py`: per-asset report history and drift (`lab_registry.sqlite3`, not in the repo).
- `report_pdf.py` / `report_dialog.py`: PDF "Calibration Data" reports.
  Optional TAR / TUR columns: two independent checkboxes (TAR, TUR) in `report_dialog.ask_details` (`details["show_tar"]`, `["show_tur"]`, `["show_tar_tur"]` = `report_pdf.TarTur`, default off, remembered in `~/.calibration_suite/report_tartur.json`); `report_pdf.apply_tar_tur`. TAR / TUR appear on the PDF data file only (there is no CSV export). Off = the PDF is unchanged.
- `diagrams/`: hook-up PNGs. 34970A/34972A naming is in `diagrams/README_dacq.txt`.

## Procedures
WaveSurfer WS4104HD, Fluke 87V, Agilent 34401A, Fluke 8846A (verification + adjustment), Keysight 34460A/61A/65A/70A,
Tektronix MDO4000C, Tektronix TDS2000C / TDS1000C-EDU, Fluke 110/113/114/115/116/117, Klein MM325, Keysight 34970A (RS-232), Keysight 34972A (USB),
Keysight 33210A, Agilent 33220A, Agilent 33250A (Fluke 5790B as the AC standard), Fluke 287 / 289 (typed or IR readings).

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
  nothing). Demo mode sends nothing. A new procedure must call the helper before its first point; `tests/test_reset_startup.py` enforces it.

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
