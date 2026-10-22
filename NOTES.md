# Calibration Suite: project notes

Tkinter calibration suite. `Calibration_Procedure_Manager.py` (v69) launches one procedure per instrument from `Procedures/`.
Procedures are driven by JSON specs (`specs/`) of the manufacturer's performance-verification tables; shared engines hold the UI and run logic.

## Layout
- `Procedures/`: launchers (one per instrument), checkpoints are written here at run time (git-ignored).
- `specs/`: `*_pv.json` test points and limits, plus the `build_*.py` scripts that wrote them. See `specs/README.txt`.
- `drivers/`: instrument drivers, transports (VISA / pyserial), simulators (`simulated.py`). See `drivers/README.txt`.
- Engines: `truevolt_verification.py` (Keysight Truevolt), `dacq_verification.py` (34970A/34972A), `handheld_dmm.py` (Fluke 110-117, 87V, Klein MM325), `mdo4000c_verification.py`, `fgen_verification.py` (33210A/33220A/33250A).
- `labregistry.py` / `labregistry_ui.py`: per-asset report history and drift (`lab_registry.sqlite3`, not in the repo).
- `report_pdf.py` / `report_dialog.py`: PDF "Calibration Data" reports.
- `diagrams/`: hook-up PNGs. 34970A/34972A naming is in `diagrams/README_dacq.txt`.

## Procedures
WaveSurfer WS4104HD, Fluke 87V, Agilent 34401A, Fluke 8846A (verification + adjustment), Keysight 34460A/61A/65A/70A,
Tektronix MDO4000C, Fluke 110/113/114/115/116/117, Klein MM325, Keysight 34970A (RS-232), Keysight 34972A (USB),
Keysight 33210A, Agilent 33220A, Agilent 33250A (Fluke 5790B as the AC standard), Fluke 287 / 289 (typed or IR readings).

## Standing rules
- Display-only SI scaling. `calibration_procedures.sqlite3` schema is never changed (read only).
- Instrument commands, limits, pass/fail and safety prompts are unchanged unless requested.
- Never write passwords to logs. Writes: set, read back, compare; never retry a write.
- Outputs to standby/off after each point.
- Read limit tables from rendered page images, not extracted text.
- No cover sheets, no standards-due tracking (handled by other software).

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

## Testing
Python with tkinter, `pyvisa`, `pyserial`, `reportlab`. Run any launcher with `--demo` for no hardware.
Real-window tests (need a display; `xvfb-run -a python -m unittest tests.test_asleft tests.test_specmanager`).
Simulated bench: `drivers/simulated.py` (`make_dacq_bench`, `make_dmm_bench`, `make_bench`).

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
