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
  keysight_34410a_pv.json   Keysight 34410A/11A/L4411A Service Guide, chapter 3 Verification Tests (printed pp. 68-87), 103 points in 11 sections (schema 1, written by build_34410a_spec.py from the page images; 86 run by default, the optional AC volts / AC current /
                            capacitance sections are marked optional). THREE periods: '24h', '90d', '1y' (default '1y'). Per point: kind (DCV ACV DCI ACI OHM2 OHM4 FREQ CAP), nominal, range (manual, never autorange), limits{24h, 90d, 1y} (half-widths, base units), printed_limits (text as printed),
                            frequency / amplitude (FREQ: the calibrator AC level), plc / filter_hz, terminal (FRONT / REAR), source (calibrator | none = zero offset with the calibrator in STANDBY | manual = capacitance standard connected by the technician), input (short | open), flags (e.g. the DC 1000 V
                            footnote 5 adder in the 1 year limit). Top level: measure{nplc, ac_bandwidth, freq_aperture_s}, equipment, general[]. The builder recomputes every printed limit in Decimal from the published accuracy and aborts on a mismatch.
  (family file: the 34411A uses this same file. Top-level family[] and models{} carry the per-model flags (title, *IDN? text, reading rate, memory, shortest NPLC,
                            digitizer / pre-trigger / level trigger: information only); no point has a models key, so every point applies to both models.)
  standards/a2la_light_standard.json  the lab's own A2LA scope CMC for Light - Measure (cert. 1888.03, p. 45 of 47) as a standards sheet 'A2LA-LIGHT': FC / lux / La 2.9 %, uW/cm2 at 365 nm 5.0 % of reading,
                            95 % (k = 2); written by build_light_standard.py (read from the rendered page image); units kept as printed, nothing converted.
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
                            Frequency rows (AC / DC volts frequency) are sourced as AC volts and read in Hz / kHz: no_uncertainty true. build_170_spec.py checks every limit against the published accuracy and fails on a disagreement.
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
  step.no_uncertainty       optional true (Fluke 170 series frequency rows): the report row gets no Uncertainty (and TAR / TUR stay blank); the 77 IV / 110 / 87V frequency steps do not set it (existing behaviour, unchanged).

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
