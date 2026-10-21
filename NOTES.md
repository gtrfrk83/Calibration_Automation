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

## Testing
Python with tkinter, `pyvisa`, `pyserial`, `reportlab`. Run any launcher with `--demo` for no hardware.
Simulated bench: `drivers/simulated.py` (`make_dacq_bench`, `make_dmm_bench`, `make_bench`).
