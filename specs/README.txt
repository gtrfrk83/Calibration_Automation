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
  fluke_110_series_pv.json  Fluke 110/113/114/115/116/117 Calibration Information, Tables 3-4 (schema 2: manual-reading; limits are the
                            exact printed display-reading strings, each step lists the models it applies to)
  fluke_87v_pv.json         Fluke 87 Series V, 51 points (schema 2, written by build_87v_spec.py from the MDD datasheet)
  keysight_33210a_pv.json / _33220a_ / _33250a_   function generators (schema 4, written by build_fgen_spec.py from the page images of
                            each Service Guide's Chapter 4): 39 / 54 / 54 points; periods 90d / 1y (they differ only for the timebase)
  fgen_332xx_reference_cmc.json  editable uncertainties for the generator procedure (RF flatness has no A2LA entry; blank = N/A)
  fluke_287_289_pv.json     Fluke 287 / 289 Calibration Manual pp. 14-20 (schema 2, written by build_28x_spec.py from the page images):
                            functional checks, Table 3, Table 4; per point 'ir' (reading unit, range code, rel, lowpass, functions),
                            'rel_zero', 'prompt', 'ramp'; options.table_order runs Table 3 before Table 4
  klein_mm325_pv.json       Klein Tools MM325 instruction manual (schema 3, written by build_mm325.py): one point per range at 90 %, AC at 60 Hz;
                            adds groups{} (cable-change prompts + hook-up diagram), dial{} (picture and position of every range) and options{}
                            (range_prompt, hv_threshold_v); per step: dial, dial_text, tol_text, max_on_s / recovery_s (10 A duty limit)

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

tektronix_tds2000c_pv.json  (built by build_tds2000c_spec.py)
  points: section, kind (SELFTEST SELFCAL GAIN BW TIMEBASE TRIG EXTTRIG), ch, nominal/low/high (None = one-sided), unit, stim (cal|none),
          models (omitted = all), passfail (low = high = 1), per-kind parameters (vscale, vpos/vneg, ref_hz, stages ...)
  models_info: channels, bw_mhz, bw_test_hz, trig_hz per model
