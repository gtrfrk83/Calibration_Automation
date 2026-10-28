SPECS - machine-readable performance-verification test points
==============================================================

A spec is a JSON file holding one model's published performance-verification tables: every test point,
its range, input, the manufacturer's limit for each time period, and the manual page it came from.
procspec.py loads it; a procedure turns it into a run sheet. Limits live here, not in the procedure.

Included
  keysight_34460a_pv.json / _34461a_ / _34465a_ / _34470a_   Keysight Truevolt Operating and Service Guide pp. 504-520, each model's own tables
                            (80 / 101 / 107 / 107 points); default period 1 year; front_rear_switch false for the 34460A
  keysight_34970a_pv.json / keysight_34972a_pv.json   Keysight 34970A/34972A Service Guide pp. 80-87 (internal DMM verification), 72 points each
                            (49 standard + 2-wire ohms and extra AC tests marked optional); written by build_dacq_spec.py. Points carry a channel
                            role (short / input / current) and a hook-up group; the procedure maps roles onto the 34901A / 34902A channels.
  fluke_8808a_pv.json       Fluke 8808A Calibration Manual Tables 3-2 to 3-8 (printed pp. 3-4 to 3-11), 105 points (kind 'bench-dmm-band', schema 1, written by build_8808a_spec.py
                            from the page images; loaded by fluke8808a_verification.py, not procspec.py, because the printed limits are asymmetric). Per point: ref (T3-2 #1),
                            table/row/page, kind (DCV ACV DCI ACI OHM2 OHM4 FREQ), nominal, range, unit, frequency (FREQ: amplitude 0.1 V), source (none | calibrator), input
                            (short | open), terminal, group (ZERO_SHORT ZERO_OPEN VOLT OHM4 OHM2 IMA I2A I10A), limits {90d, 1y: {low, high}} in base units, std_relative (ohms:
                            tolerance about the calibrator setting), accuracy (the formula % of reading, % of range), cal_limits {5522A: why, 5560A: why} (points that calibrator cannot
                            make; a calibrator not listed drives the point: 10 A ac at 40 Hz is listed for the 5522A only), and, where the printed table was wrong, flags + printed_limits. build_8808a_spec.py checks every limit against the accuracy formula in Decimal.
  keithley_2000_pv.json     Keithley Model 2000 Calibration Manual 2000-905-01 Rev. F, Tables 1-2 .. 1-6 (printed pp. 1-7 .. 1-13), 37 points (schema 1, written by build_k2000_spec.py from the page images). ONE period, '1y' (the manual prints one
                            interval: 1 year, 18-28 C; the 90-day / 24-hour limits are not built). Per point: kind (DCV / ACV / DCI / ACI / OHM4, and OHM2 for the 100 Mohm point), nominal (negative for the minus points), range (the meter range, manual, never autorange), limits{'1y'}, frequency, plc,
                            group (hook-up key: DCV, ACV, DCI, ACI, OHM4, OHM100M), printed_limits (text as printed), computed_limit (219 V only). The optional 700 V @ 50 kHz point of the first version is removed (219 V @ 50 kHz, the manual's substitute, stays; nothing is hand-sourced).
                            The 100 Mohm point is a pure 2-wire hook-up on the 2000's 2-wire resistance function; its limit is the one printed in Table 1-6. Top level: measure{nplc, filter_state ('ON': DC volts / DC current / ohms), filter_count, filter_type,
                            ac_bandwidth (3, slow), ac_filter_state ('OFF': AC volts / AC current)}, prep.dcv_rel_zero, general[] (warm-up / environment lines), equipment. The builder recomputes every printed half-width in Decimal from the one-year accuracy specification and aborts on a mismatch.
  keithley_2000_adjustment.json   Keithley Model 2000 Calibration Manual 2000-905-01 Rev. F, the SCPI command calibration (pp. 2-14 to 2-19, Tables 2-1, 2-8 to 2-12, 3-1 to 3-2, B-1), 26 steps (D01-D13 DC, A01-A13 AC; schema 1, written by build_k2000_adjustment_spec.py from the page images). Per step: scope, group, title, a20 / a19 (the :STEP number on firmware A20 and later / A19 and earlier, Table 3-1 note: no 10 Mohm step on A19), source {kind, value, unit, frequency}, param {nominal, lo, hi, unit} (DC steps 3-13 take the calibrator's exact value), page, thermal_wait, flags (manual misprints, each stated). Top level: general[], equipment (Table 2-1 ppm), firmware, sequence[], errors (Table B-1), not_built[], times (thermal wait 180 s, SLOW = 10 PLC). specs/analyze_k2000_adjustment_standards.py writes k2000_adjustment_standards.md (which calibrator meets Table 2-1 at each step).
  fluke_8808a_adjustment.json     Fluke 8808A Calibration Manual (Oct 2008), the RS-232 calibration dialog (pp. 3-16, 3-17) and Table 3-9 (pp. 3-12 to 3-15), 124 steps S001-S124 (VDC 21, VAC 21, FREQ 12, OHMS 28, AAC 17, ADC 25; schema 1, written by build_8808a_adjustment.py from the page images, read twice). Per step: function, command, range, point {value, unit, text}, source {kind, value, unit, frequency} (null for zeros), group, zero, wire, page, list_value / conflict (seven steps differ from the Calibration Points lists, pp. 3-17 / 3-18), characterize (steps 101-108, 113-120). Also: equipment (Table 3-1), times (warm-up 30 min; the settle, quiet and point-timeout times are engineering choices), discrepancies.
  fluke_i400_pv.json   Fluke i400 AC Current Clamp Calibration Information 2414311, Table 3 Accuracy Tests (p. 6), 3 points (schema 1, written by build_fluke_i400_spec.py from the page images)
  keysight_34410a_pv.json   Keysight 34410A/11A/L4411A Service Guide, chapter 3 Verification Tests (printed pp. 68-87), 103 points in 11 sections (schema 1, written by build_34410a_spec.py from the page images; 86 run by default, the optional AC volts / AC current /
                            capacitance sections are marked optional). THREE periods: '24h', '90d', '1y' (default '1y'). Per point: kind (DCV ACV DCI ACI OHM2 OHM4 FREQ CAP), nominal, range (manual, never autorange), limits{24h, 90d, 1y} (half-widths, base units), printed_limits (text as printed),
                            frequency / amplitude (FREQ: the calibrator AC level), plc / filter_hz, terminal (FRONT / REAR), source (calibrator | none = zero offset with the calibrator in STANDBY | manual = capacitance standard connected by the technician), input (short | open), flags (e.g. the DC 1000 V
                            footnote 5 adder in the 1 year limit). Top level: measure{nplc, ac_bandwidth, freq_aperture_s}, equipment, general[]. The builder recomputes every printed limit in Decimal from the published accuracy and aborts on a mismatch.
  (family file: the 34411A uses this same file. Top-level family[] and models{} carry the per-model flags (title, *IDN? text, reading rate, memory, shortest NPLC,
                            digitizer / pre-trigger / level trigger: information only); no point has a models key, so every point applies to both models.)
  standards/a2la_light_standard.json  the lab's own A2LA scope CMC for Light - Measure (cert. 1888.03, p. 45 of 47) as a standards sheet 'A2LA-LIGHT': FC / lux / La 2.9 %, uW/cm2 at 365 nm 5.0 % of reading,
                            95 % (k = 2); written by build_light_standard.py (read from the rendered page image); units kept as printed, nothing converted.
  standards/keysight_3458a_standard.json  Keysight / Agilent 3458A 8.5-digit DMM accuracy (data sheet 5965-4971E pp. 8-35) as a MEASURING standard 'input': DC volts (std / Option 002 / transfer),
                            ohms 2- and 4-wire, DC and AC current, AC volts (SYNC / ANA / RNDM), frequency; periods 1 yr (default) and 90 day, 'ppm of range' terms (range = range name);
                            Option 002 DC volts is the plain-lookup default (the lab's unit), Standard stability is the variant;
                            no confidence level printed (k = 2 assumed); written by build_3458a_standard.py (read from rendered page images).
  standards/keysight_34461a_standard.json / keysight_34465a_standard.json  Keysight 34461A / 34465A 6 1/2 digit Truevolt DMM accuracy (data sheet 5991-1983EN, 'Specifications 34461A' pp. 13-14, '34465A' pp. 15-17) as MEASURING
                            standards 'input': DC volts, resistance (4-wire / 2-wire math null; 2-wire without null +0.2 ohm), DC and AC current, AC volts, capacitance, frequency (sine and square wave); '% of reading + % of range'
                            (range = range name); periods 90 day / 1 yr / 2 yr, default 1 yr (the 24 hour column is not stored); printed 'compliant to ISO/IEC 17025 for k = 2' -> stored 95 %, divisor 2;
                            written by build_34461a_standard.py / build_34465a_standard.py on truevolt_standard_engine.py (read from rendered page images). No driver.
  standards/agilent_33250a_standard.json  Agilent 33250A 80 MHz function / arbitrary waveform generator as a STANDARD (stimulus source), 1 yr, from the User's Guide 33250-90002 Ed. 2 Chapter 8 (printed pp. 319-323), built by build_33250a_standard.py; no confidence level printed (divisor 2)
  standards/a2la_5500a_coil_standard.json  the lab's own A2LA scope CMC lines for the Fluke 5500A/COIL as a standards sheet 'A2LA-5500A-COIL' (cert. 1888.03): DC Current - Generate (2 to 20) A 90 uA/A + 0.1 mA,
                            (20 to 120) A 80 uA/A + 8 mA, (120 to 3000) A 0.8 % + 0.08 A (p. 9, Transconductance amplifier/coil) and AC Current - Generate, Clamp-On Only (20.5 to 1025) A, 45-65 Hz 0.8 %,
                            65-440 Hz 0.99 % (p. 30, Multifunction calibrator/coil); 95 % (k = 2); written by build_coil_standard.py (read from the rendered page images). The coil datasheet
                            facts (50 turns, current limits, interaction uncertainty, NOT added) are in the sheet notes.
  standards/a2la_current_amp_coil_standard.json  the lab's A2LA scope CMC for AC current (20.5 to 3000) A with a transconductance amplifier/coil (p. 30): (16 to 850) Hz 0.7 % + 0.84 A, (0.85 to 6) kHz 0.8 % + 0.84 A
                            as sheet 'A2LA-CURRENT-AMP-COIL', 95 % (k = 2); written by build_current_amp_coil_standard.py.
  build_a2la_cmc_coil_rows.py  appends the coil lines (5500A/COIL DC and clamp-on AC rows, amplifier/coil AC rows) to a2la_1888_03_cmc.json (idempotent; the existing rows are untouched).
  34410a_standards_suitability.md  (generated by analyze_34410a_suitability.py) TAR / TUR of the 5560A, 5522A and 5520A (UNVERIFIED proxy) at every calibrator-sourced 34410A point, with a recommendation.
  fluke_110_series_pv.json  Fluke 110/113/114/115/116/117 Calibration Information, Tables 3-4 (schema 2: manual-reading; limits are the
                            exact printed display-reading strings, each step lists the models it applies to)
  fluke_87v_pv.json         Fluke 87 Series V, 51 points (schema 2, written by build_87v_spec.py from the MDD datasheet)
                            Duty cycle (1-16) and Peak Min/Max (1-48, 1-49) are sourced as square waves per the 87 Series V Calibration Manual
                            Table 3 (printed pp. 9, 11); temperature (1-50, 1-51) is read and sourced in degC (the MDD printed degF).
                            build_87v_spec.py was edited by hand for this and NOT re-run (the MDD is not in the repository).
  keysight_33210a_pv.json / _33220a_ / _33250a_   function generators (schema 4, written by build_fgen_spec.py from the page images of
                            each Service Guide's Chapter 4): 39 / 54 / 54 points; periods 90d / 1y (they differ only for the timebase)
  fgen_332xx_reference_cmc.json  editable uncertainties for the generator procedure (RF flatness has no A2LA entry; blank = N/A)
  fluke_287_289_pv.json     Fluke 287 / 289 Calibration Manual pp. 14-20 (schema 2, written by build_28x_spec.py from the page images):
                            functional checks, Table 3, Table 4; per point 'ir' (reading unit, range code, rel, lowpass, functions),
                            'rel_zero', 'prompt', 'ramp'; options.table_order runs Table 3 before Table 4
  fluke_77iv_pv.json        Fluke Model 77 Series IV Calibration Information, Table 2 (printed pp. 12-13), 35 steps (schema 2, written by build_77_spec.py from the page images):
                            33 numeric readings + 2 continuity (beeper) checks; ids 2-1 .. 2-35; the meter is autoranging so each step's 'range' is the range the reading falls in (p. 5).
                            Step 8 (AC volts, 50 mV, 45 Hz) prints 0.47 / 0.53 V ac; 0.047 / 0.053 V ac is used (printed text kept in step.printed_limits). build_77_spec.py
                            checks every limit against the +/-(% of reading + counts) accuracy table (p. 5) and fails if one disagrees.
  fluke_170_series_pv.json  Fluke 175 / 177 / 179 Calibration Information, Table 2 (175, pp. 10-11) and Table 3 (177 / 179, pp. 12-13) (schema 2, written by build_170_spec.py from the page images): per-step 'models' as in the 110-series spec;
                            175 = 52 points, 177 = 51, 179 = 54 (adds 3 temperature points, TEMP kind, degC). Steps are numbered in table order (the tables print no numbers): ids 2-1..2-52 (175), 3-1..3-54 (177 / 179).
                            THREE printed values are corrected (step.printed_limits keeps the printed text; the report row Description says 'limits corrected'); format-only changes keep step.printed_text.
                            Frequency rows (AC / DC volts frequency) are sourced as AC volts and read in Hz / kHz: unc_kind FREQ (the Frequency - Measure CMC alone). build_170_spec.py checks every limit against the published accuracy and fails on a disagreement.
  fluke_365_pv.json         Fluke 365 Detachable Jaw True-rms Clamp Meter Calibration Manual, Table 2 (printed pp. 7-8), 32 points (schema 3, written by build_fluke_365_spec.py from the page images, read twice):
                            AC volts 6, DC volts 7, ohms 7, AC amps 6, DC amps 6; ids 2-1 .. 2-32. The current rows list the CALIBRATOR current (applied.value 0.5 / 5 / 9.5 A) and the METER limits
                            (nominal 10 / 100 / 190 A: a 20-turn coil, 20 x); they carry the calibrator's current uncertainty at applied.value, unscaled (owner-chosen). groups{COIL_AUX, COIL_20A} are the spec's own cable-change prompts (calibrator low- / high-current
                            output to the coil, test leads out of the jacks, jaw round all 20 turns); VOHM comes from hookups.py ('fluke365'). step.check = a printed limit that is NOT half of the published
                            specification (900 ohm lower limit 894; the three 190 A rows +-2.5 against +-2.15): stored as printed, flagged in the note. step.dsb_desc / report_desc word the coil rows.
                            Tested by tests/test_fluke_365_points.py; options as the other handheld specs (hv_threshold_v 30, hv_once_per_group true (365 only), auto_ramp false, function_prompt, report_title 'Calibration Data').
  keysight_u1251b_u1252b_pv.json  Keysight U1251B / U1252B Handheld Digital Multimeter User's and Service Guide, Table 6-2 "Verification Test" (printed pp. 155-160, notes pp. 160-161; schema 3, written by build_keysight_u1251b_spec.py from
                            the page images, read twice; one family spec, per-model flags): U1251B 63 points (60 table + 3 yes/no checks), U1252B 87 (84 + 3; the charge-terminal alert check is not included, owner decision). Limits are nominal +- the printed ERROR (1-year column), recomputed in Decimal.
                            The 5 A / 10 A DC rows print no step number (read as DC); step 11 (counter, 600 mV 100 kHz) is sourced by the calibrator, options.two_wire_comp false, settle 0 on every calibrator point; steps 12 and 20 (U1252B counter 10 MHz and OUT ms square wave) are hand-set against a 33250A / 53131A / 34410A (kind NONE, no calibrator, no uncertainty).
                            Data sheet cross-check is a second-hand extraction (UNVERIFIED). Tested by tests/test_keysight_u1251b_points.py; hook-up names in diagrams/README_u1251b.txt.
  fluke_33x_pv.json         Fluke 33X ClampMeters Calibration Information (PN 1618765, Rev. 2, 12/03), Table 2 (printed pp. 8-9), 41 Table 2 points + 3 functional checks (schema 3, written by build_fluke_33x_spec.py from the page images, read twice):
                            a FAMILY spec for the 333 / 334 / 335 / 336 / 337 (333: 12 points, 334: 16, 335: 16, 336: 23, 337: 30; the checks F-1 display, F-2 backlight, F-3 keypad are yes / no 'visual' points that run first). The manual has no X / N/A columns: step.models come from the table a row is printed in
                            (table '2A' p. 8: 333 334 335; table '2B' p. 9: 336 337) and the printed model tags. AC volts, Min/Max (337), DC volts, continuity (test 'beeper'), ohms, AC amps, inrush, DC amps,
                            frequency (337); ids 2A-1 .. 2A-14, 2B-15 .. 2B-41. The '5520A Output' of the amps / inrush / frequency rows is the current the jaw sees: applied.value is that / 50 (50-turn coil, inferred),
                            nominal is the meter reading. 'Reading does not change' is a 'visual' yes / no step with a calibrator output. step.check = printed limits that are not the published specification (four ohms rows
                            'looser' = 1.5 % + 5 counts against the printed 1 % + 5; the 10 Hz row 'rounded'): stored as printed, flagged in the note. groups{COIL_AUX, COIL_20A}; VOHM from hookups.py ('fluke33x').
                            Tested by tests/test_fluke_33x_points.py; options as the 323 / 381 specs.
  fluke_376_pv.json         Fluke 374 / 375 / 376 / 376-II Calibration Manual, Table 1 (printed pp. 3-4), 38 points (schema 3, written by build_fluke_376_spec.py from the page images, read twice): a FAMILY spec,
                            step.models from the X columns (374: 28, 375: 34, 376 and 376-II: 38). AC volts 4, DC volts 8 (4 mV), ohms 7, capacitance 3, AC amps 4, DC amps 3, iFlex simulated 5, iFlex with coil 4;
                            ids 1-1 .. 1-38. Coil rows list the CALIBRATOR current (applied.value 0.2 / 10 / 18 / 6 A) and the METER limits (nominal 50 x); the iFlex simulated rows are sourced as AC volts (applied.value 0.003 ..
                            0.75 V) and read in amps, so they carry step.unc_unit 'V' (the unit of the Uncertainty; the only spec that uses it). groups{COIL_AUX, COIL_20A, IFLEX_SIM, IFLEX_COIL_AUX, IFLEX_COIL_20A}
                            are the spec's own cable-change prompts; VOHM comes from hookups.py ('fluke376'). step.check.models = a printed limit that is neither the full nor half of the accuracy printed in the 374 FC / 375 FC / 376 FC Users Manual (pp. 20-26), per model,
                            stored as printed: 1-1 (rounded for 374 / 375), 1-1 .. 1-4 (looser for 376 / 376-II: their AC volts accuracy is 1 %, the table prints 1.5 %), 1-28, 1-29, 1-36, 1-37 (tighter).
                            options.include_toggles + step.include 'iflex' = the window option that runs the nine iFlex steps only while it is ON (iflex_option.py; default ON); the 900 V rows are stored as whole volts, printed_text keeps 882.0 / 919.0. Tested by tests/test_fluke_376_points.py; options as the 365 (hv_threshold_v 30, hv_once_per_group true, auto_ramp false,
                            function_prompt, report_title 'Calibration Data').
  klein_mm325_pv.json       Klein Tools MM325 instruction manual (schema 3, written by build_mm325.py): one point per range at 90 %, AC at 60 Hz;
                            adds groups{} (cable-change prompts + hook-up diagram), dial{} (picture and position of every range) and options{}
                            (range_prompt, hv_threshold_v); per step: dial, dial_text, tol_text, max_on_s / recovery_s (10 A duty limit)

Options common to the handheld-meter specs (handheld_dmm.py; fluke_110_series, fluke_87v, fluke_287_289, klein_mm325, fluke_77iv)
  options.auto_ramp         default true: a DC/AC volts point above 100 V is reached in 50 V steps, 5 s apart (the 110-series manual). false = one
                            OUT command straight to the test value. Off in the 87V, 287/289 and MM325 specs (and their builders). A per-point
                            'ramp' list the manual prescribes (287/289 point 4-64: 60 V then 120 V) is always followed. The 110-series spec leaves
                            it on: its 600 V points carry one-step ramp lists, and only AUTO-V LoZ (3-40) uses the automatic ramp. The HIGH VOLTAGE
                            prompt mentions ramping only when a ramp actually happens.
  options.function_prompt   true = each time the rotary switch has to move to a different function (point.switch changes) the operator is asked to
                            turn the meter, with the calibrator in standby. Points of group NONE (functional checks, hand-set points) get none
                            (they carry their own prompt and set the function); with options.range_prompt (MM325) the dial prompt shown at every
                            point takes its place. On in all four handheld specs.

  options.report_title      optional (Fluke 77 IV: 'Calibration Data'): the PDF title; without it the report is titled '<model> Performance Verification' as before.
  options.hv_threshold_v    DC / AC volts points at or above this level get the HIGH VOLTAGE confirmation (default 500; 87V / 287 / MM325 60; 77 IV 30, the manual's shock-hazard level).
  source.report_note        optional text stored with the issued report (snapshot / footer note) - the 77 IV spec states its step-8 correction there.
  step.report_desc          optional: the report row's Description (77 IV: '99.99 kHz range (5 V applied)' for the frequency step, which would otherwise print the 110-series
                            '(2 V applied)' text, and '6.000 V range (limits corrected)' for step 8).
  step.printed_limits       optional record of limits as printed when the spec uses corrected ones (not read by the engine).
  step.printed_text         optional (Fluke 170 series): the printed limit text when the spec writes the same numbers at the display resolution (50.1 -> 50.10); not read by the engine.
  step.no_freq_suffix       optional true (Fluke 170 series Hz-unit frequency rows): the report Nominal has no 'at f Hz' suffix.
  step.no_uncertainty       optional true: the report row gets no Uncertainty (and TAR / TUR stay blank). No spec uses it for a frequency reading any more (see unc_kind).
  step.unc_kind             optional 'FREQ' (Fluke 170 series hzread rows, 77 IV 2-17, 110-series 3-17, 87V 1-11 .. 1-14, 287 / 289 4-24): the step sources AC volts and reads a frequency; the Uncertainty is the lab's 'Frequency - Measure' CMC at the applied frequency, on its own (no calibrator budget), TUR against it, TAR blank.

Square-wave sources in handheld specs (additive; handheld_dmm.py, procspec.validate_manual_reading)
  step.kind                 DUTY    square-wave source, the meter reads the duty cycle (%) (87V 1-16)
                            SQUARE  square-wave source, the meter reads DC volts (87V peak Min/Max 1-48 / 1-49)
  step.applied              {value: amplitude in V PEAK-TO-PEAK, frequency: Hz, duty: 1-99 % (default 50), offset: V DC (default 0)}
                            a DC offset needs duty 50 % (5522A Operators Manual p. 4-47). The calibrator sends one compound line
                            `WAVE SQUARE; OUT <vpp>V,<freq>; DC_OFFSET <offset>V` (coupled commands, 5522A p. 5-28), then `DUTY <duty>`, and reads back
                            WAVE? / DUTY? / DC_OFFSET? / OUT?. Whenever the output goes to standby (after the point, on stop / abort / close) the engine
                            sends `WAVE SINE; DC_OFFSET 0V` and reads it back; a square wave is never left selected.
  step.prompt               (existing field) shown in the 'Meter setup' dialog before the point (87V 1-48 / 1-49)
  TEMP steps                the calibrator sources degC, so display_unit must be degC (base_unit 'C' or 'degC'); a degF TEMP step is a spec error.

Schema (schema 1)
  periods / default_period      ["24h","90d","1y","2y"] / "90d"
  sections[]                    id, title, page, setup (technician text), source, points[]
    source                      calibrator | none (copper short / open input) | generator | manual (technician-supplied standard)
    optional                    true = left out unless the operator opts in (e.g. capacitance)
    terminal                    FRONT (default) | REAR | FRONT_10A
  points[]
    kind                        DCV ACV DCI ACI OHM2 OHM4 FREQ CAP
    nominal, range              SI base units (V, A, ohm, Hz, F)
    frequency, filter_hz, plc   input frequency, AC detector filter, NPLC (blank when not used)
    amplitude                   FREQ points only: source level in V rms
    limits                      allowed +/- error from nominal for each period, SI base units
    quick                       true = marked Q (quick check) in the manual
    typical                     true = the manual says the value is typical, not guaranteed
    note                        free text shown to the technician

Adding a model (the workflow that produced the 34465A spec)
  1. Locate the manufacturer's performance-verification section (service / calibration manual).
  2. Read the tables from the page images, not only extracted text: merged cells (one limit shared by
     several time-period columns, or one input shared by several rows) do not survive text extraction.
  3. Write the points into a JSON file (see how keysight_34465a_pv.json was built) and cite pages.
  4. Add or reuse a driver for the model in drivers/ and a procedure that maps each kind onto it.
  5. Run the procedure in demo mode and on the simulated bench; compare a few rows with the manual.

Notes on the 34465A spec
  * The manual recommends a Fluke 5720A/5725A and a Keysight 33500B. The procedure uses the Fluke 5560A as
    the source; the calibrator refuses outputs it cannot make (the program reads its error queue and
    never operates after a rejection). Check the 5560A can make every point before relying on it,
    especially the 70 V / 300 kHz AC volts and the 10 A points.
  * The manual's 2 A shortcut for the 10 A range (no 5725A) is not implemented: limits for 2 A are not published.
  * The rear terminals have no 10 A input, so 10 A zero offset is front only (an assumption from p. 519).
  * The manual prints the 2-wire 100 MOhm zero limit as "1 kOhm" with no sign; it is applied as +/- 1 kOhm.
  * Quick-check marks on merged cells (10 V and -100 V DC) follow the cell positions in the printed table.

a2la_1888_03_cmc.json
  (An optional entry {basis 'generate', kind 'TEMP', bands [{lo, hi, rel, abs}]} - signed degC bands - would make the temperature points of the handheld meters report no less than that CMC; the shipped file has none,
  so the temperature uncertainty there is the calibrator's Type K simulation budget alone.  See NOTES.md.)
  CMC tables from the lab's scope of accreditation. Bands carry rel (fraction of reading), abs (fixed floor, base units) and
  rng (fraction of range, AC current only); AC voltage bands are by voltage and frequency, AC current by instrument range.
  Built by reading the scope PDF's Section V (pp. 8-32); AC-voltage ranges (1 to 2) V is printed with three repeated rows
  ahead of it, which were dropped (same values as the 0.7 to 1 V band). Check any new scope revision against the page images.

tektronix_mdo4000c_pv.json (schema 2)
  Flat list of points for all four MDO4000C models. Each point: section, kind, desc, ch, nominal, low, high (null = one-sided limit),
  unit, stim (none / cal / rf / rf2 / gen), models (omitted = all), req (option tokens that must all be true: SA, SA6, noSA, AFG, DVM,
  DIG, TPA, noTPA) and the per-kind test parameters. Built by /scratch/build_mdo_spec.py from the test record (pp. 35-83); the
  delta-time tables were parsed from the manual text, every channel table as printed.
mdo4000c_reference_cmc.json
  Editable uncertainties for the 96270A, function generator and reference meters (rel x reading + abs). Blank = N/A on the report.

tektronix_tbs1000c_pv.json / tektronix_tbs1000_pv.json (schema 2, the point layout of tektronix_tds2000c_pv.json; run by the shared Tektronix engine)
  tbs1000c: TBS1000C Specification and Performance Verification 077-1583-03 Rev A, pp. 23-30, 14 points for each of TBS1052C / 1072C / 1102C /
            1202C (two channels); written by build_tbs1000c_spec.py from the page images (read twice). DC gain +/-3 % (5 mV/div 33.95 to 36.05 mV),
            bandwidth >= 2.12 V p-p, time base +/-2 div (test record; step 13 prints +/-2.5) at 10 ns/div, 1 ms marker, edge trigger,
            Aux In trigger. Vertical offset accuracy (pp. 30-31) not built.
  tbs1000:  TBS1000 Series Service Manual 077-0772-01 Rev D, Chapter 4 pp. 4-1 to 4-10, 24 points (TBS1022 / 1042 / 1062 / 1064 / 1102 / 1104 /
            1152 / 1154; CH3 / CH4 points list the four-channel models); written by build_tbs1000_spec.py from the page images (read twice).
            Same tests and limits as the TDS2000C chapter except the model list, bandwidths (25 to 150 MHz) and trigger frequencies.
  Extra trigger-stage frequency tags (engine): 'BW' = models_info bw_test_hz, '150M' = 150 MHz. Top-level 'flags' and 'not_built' list what
  differs from the printed procedure or was left out. The builders recompute the DC gain limits in Decimal and abort on a mismatch.
  Per point, report_notes [{text, models?}] are printed under the report table (the description gets "(see note)") for the models listed (all if none).
tektronix_mdo3_pv.json (schema 2; read by mdo3_verification.py)
  The same point fields as tektronix_mdo4000c_pv.json, plus top-level model_info{} (per model key '32-100' ... '34-1000': channels, bandwidth_hz,
  bw_limits, counter_max_hz, option), options{} and discrepancies[] (every disagreement between the test record, the procedure and the published
  specification, listed by the builder). Option tokens: SA3, noSA3, AFG, DVM, TPA, noTPA. Point parameters the MDO4000C spec does not have
  (read with p.get): per_div, method, hscale, vpp, coarse_hscale, fine_hscale, ref_level, detection, counter, vscale, ref_hscale (BW), center / span (DANL),
  waveform (DVMFREQ).
  Built by specs/build_mdo3_spec.py (committed; run it to rewrite the JSON) from the rendered page images of 077-1499-10, Decimal limits.
mdo3_reference_cmc.json
  As mdo4000c_reference_cmc.json, for the 3 Series kinds (REFFREQ in divisions).

Schema 4 (function generators: keysight_33210a/33220a/33250a_pv.json)
  periods / default_period      ["90d","1y"] / "1y"
  sections[]                    id, title, page (printed), kind, group (wiring prompt: NONE / COUNTER / STD / POWER / POWER_ATT), setup, points[]
  points[]
    kind                        SELFTEST | TIMEBASE | ACAMP | LFFLAT | FLAT
    function, frequency         SIN / SQU; Hz
    amplitude, amp_unit, load   the generator setting as printed (VRMS / VPP / DBM) and output setup (INF = High Z, or 50)
    nominal, unit, limits       expected reading in V, Hz or dB and the +/- limit per period (SELFTEST: 0 = pass)
    range_db                    FLAT only: attenuator range 0 / 10 / 20
    ref                         worksheet reference recorded by this point (1k_0dB, 100k_10dB ...)
    quick, typical, note        Q mark; the manual calls the limit a guideline (33250A square wave)
  references.offset_N           which two references make the N dB flatness offset (worksheet step 5; power-meter method)
  flatness_methods              WBND (5790B wideband, relative to 1 kHz) and/or POWER (manual method); the first is the default

User-built datasheets (Datasheet Builder; NOT stored in this folder)
  datasheet_builder.py / datasheet_builder_specs.py / datasheet_builder_match.py write runnable specs into the app data folder, user_specs/<make>_<model>_<title>.json
  (old versions in user_specs/versions/<uid>/), never into specs/.  The file is a schema-2 'manual-reading' spec (same steps[] keys as fluke_110_series_pv.json) plus the
  additive extension below, which the stock engine ignores.  procspec.validate_manual_reading(spec) checks both.
  top level   user_built       true
              dsb              schema 'dsb-1', uid, version, revision, title, make, model, exported_at, period, periods[], default_period,
                               engine{stock_runnable, points, runnable, hand_set, notes}, datasheet{the whole datasheet (re-openable)}, plan{optional matcher snapshot}
  per step    dsb              function, kind (DCV ... SCOPE_BW ... GEN_AMPL), direction ('measure' = UUT measures a sourced stimulus, 'source' = UUT outputs and a
                               standard measures), point_id (= step id), range_id, unit, engine_ready, stimulus{nominal, frequency, amplitude, settings},
                               limit{nominal, low, high, minus, plus, source, one_sided, periods{id:{low,high}}}, assignment{standard, mode, ...}
  Values inside 'dsb' are SI base units as exact decimal strings; low / high / nominal / factor / applied of the step itself follow the handheld convention above.
  A point may carry its own 'spec' (one SpecEntry; the grid editor writes it) inside dsb.datasheet.functions[].points[]; it governs that point instead of the function table. Optional, additive.
  Points the stock handheld engine cannot drive (scope bandwidth / time base / trigger, generator functions) are exported as hand-set points (kind NONE or VISUAL, group NONE).

tektronix_tbs2000b_pv.json (schema 2, the TDS2000C layout; written by build_tbs2000b_spec.py)
  TBS2000B Series Oscilloscope Specification and Performance Verification 077-1538-03 Rev D, pp. 19-26, read from the page images: self test, SPC, bandwidth (2.12 V min), vertical offset accuracy
  (source +/- 0.2 div, 4 rows per channel), time base (+/-2.5 div at 10 ns/div, 1 ms marker and delay), DC balance (+/-21 mV at 200 mV/div). models / models_info: 2072B 2074B 2102B 2104B 2202B 2204B
  (channels, bw_mhz, bw_test_hz); points on CH3 / CH4 list the 4-channel models. source.deviations lists where the procedure departs from the manual; point.printed keeps the printed values
  (bandwidth reference 1 kHz / 400 us/div). The builder recomputes every limit in Decimal from the specifications pp. 11-13 and aborts on a disagreement.

keysight_53220a_pv.json (kind 'counter-pv', written by build_53220a_spec.py)
  Keysight 53210A/53220A/53230A Assembly Level Service Guide, chapter 1 Performance Tests (pp. 28-99; the limits are the record pages 90-99), read from the page images. ONE spec for the
  three counters: models{} (channels, micro_channel [53210A: Channel 2, others Channel 3], time_tests, burst, gate_resolution_s, idn), options{} (010 / 106 / 115 / 150 / 201), measure{} (100
  readings, 10 ms gate, DC, 50 ohm, 5 V range, level 0 V, BUS trigger), equipment{} (the standards the manual lists), general{}, datasheet_check{} (the published accuracy ratios; UNVERIFIED mirror).
  periods: '1y' (counter in operation 1 year or less, default) and 'gt1y' (Test 1 limits halved).
  A point may carry record_page_printed (7c: the record page's printed minimum 1.348 865 000 GHz; the test-text value 1.348 650 000 GHz is applied, owner 2026-10-27).
  sections[].points[]
    ref, test, func           FREQ / SPER / PWID / TINT / BURST / TST; kind FREQ | PERIOD | PWID | TINT | TST (the readings are SI base units: Hz, s)
    stat                      mean | sdev (parent = the mean point whose 100 readings it shares) | pass (the self-test)
    channel                   1, 2, 3 (the microwave input) or 12 (time interval Channel 1 to Channel 2)
    nominal, unit, gate_s     the expected reading (a period for SPER), the gate (None = the CONFigure default)
    requires                  option codes the point needs (106 / 115 / 150); a point with no limit for the model does not exist on it
    timebase                  INT (Test 1) or EXT (10 MHz reference on EXT REF IN)
    stimulus                  group LH (96270A Leveling Head, up to 4.024 GHz) | MW (above that: Microwave O/P) | PULSE | BURST | NONE, frequency, level_dbm, width_s, period_s, delay_s, vpp, burst_width_s, pri_s
    limits                    per model {low, high, printed} (Mean) or {max, printed} (Std Dev, a strict '<'); Test 1: limits[model][std|010][1y|gt1y] with limits_by = 'timebase_option'
    quick, page, flags, text_limit    the Q mark, the manual pages, discrepancies noted on the point, the limit as written in the test text where it differs

  bk_5491b_pv.json          B&K Precision 5491B: the lab datasheet (Mudcats MDD, ATS-1042, 365 days, 55 points) reconciled with the 2831E / 5491B manual tables;
                            two selectable limit sets ('mdd' default, 'mfr'); six points (MDD #2, #3, #4, #5, #8, #21) differ and are flagged; written by build_bk_5491b_spec.py

  fluke_6060a_pv.json       Fluke 6060A / 6060A-AF RF signal generator (kind 'rf-generator-pv'; written by build_fluke_6060a_spec.py). Instruction Manual Section 4A, read from the
                            RENDERED pages 4A-3 to 4A-17 (PDF pages 117-133); every point carries its page. 470 points in 15 sections: 4A-3 power-on (1), 4A-4 synthesis (9), 4A-5 high level
                            (96: 6 frequencies x 8 sections + 7 section errors + the sum, derived), 4A-6 mid level (40), 4A-7 -127 dBm (5), 4A-8 alternate levels (144), 4A-11 harmonics and
                            spurs (20), 4A-12 tests 1-8 (T1..T8). Output leakage 4A-9 / 4A-10 is not built. Per point: gen{freq_mhz, level_dbm, attenuator, am, fm}, meas (freq_count,
                            level_tuned, level_power, level_pm, harmonic, spur, am, fm, ..., derived, thd_typed), rx / pm / sa (what the measuring instrument is set to), group (hook-up:
                            POWERON RX RXPWR PM SA EXT1K EXT10K EXT400), nominal / low / high / unit, strict_high (the manual's "<"), derive{kind section | sum, inputs, constant, level0,
                            attenuation} (the manual's formulas, NOT Figure 4A-3), limits_651 / skip_if_651 (Option -651 low-rate FM; the -651 limits are INFERRED), typed_only (THD at 10 kHz is
                            typed from the owner's analyzer), flags (UNVERIFIED notes), page. Top-level: constants (mid_low_freqs_mhz = 120, 244, 245, 850, 1050 by owner decision 2026-10-28),
                            discrepancies (printed typos, each listed and never silently corrected), options.
