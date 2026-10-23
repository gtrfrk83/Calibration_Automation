Instrument drivers
==================
One driver per instrument MODEL. Procedures call intent-level methods
(fluke.set_dc_volts(0.006), scope.set_vertical_scale(1, 0.01)); the command strings live only here.

  transport.py          USB / GPIB / RS-232 through VISA, or RS-232 through pyserial; command log
  base.py               Instrument base class: logging, model check, read-only retry, cleanup
  fluke_5560a.py        Fluke 5560A calibrator (SCOPE DCV / MEASR / LEVSINE, normal V / A / ohm outputs, OPER, STBY)
  scpi_dmm.py           Fluke 8846A and Agilent 34401A (CONF / READ?, remote/local; 8846A also has the
                        calibration-adjustment commands - the password is masked in the command log)
  fluke_8808a.py        Fluke 8808A 5-1/2 digit bench DMM over RS-232 only (function / WIRE / FIXED / RANGE n / RATE read back, MEAS1?, errors from *ESR? bits; every command carries
                        its Users Manual page; the calibration (*TER) interface is deliberately absent)
  simulated_8808a.py    Simulated 8808A (measures what the simulated calibrator outputs, only when the function / range / DC-AC set-up fits) and a 5522A that refuses what it cannot make
  lecroy_ws4104hd.py    LeCroy WaveSurfer 4104HD (VBS automation: scale, offset, coupling, P1, timebase)
  simulated.py          Simulated 5560A + scope that talk to each other (no hardware needed)
  fluke_5790b.py        Fluke 5790B AC Measurement Standard (INPUT, EXTRIG, RANGE, MEAS? with settle wait, ERR?,
                        *OPT? wideband option check)
  keithley_2000.py      Keithley Model 2000 (GPIB or RS-232 SCPI: function, range, speed, filter, REL, :READ?, error queue) and the 5522A with its
                        ZCOMP command; every command has a page reference and a verified flag (the read-back reply formats are unverified)
  simulated_k2000.py    Simulated 2000 on the simulated calibrator (GPIB / RS-232 behaviour, REL, overflow, error queue)
  keysight_34410a.py    Keysight / Agilent 34410A (GPIB or USB SCPI: function, range, 100 NPLC / AC filter, READ?, ROUT:TERM? Front/Rear, error queue); every command has a
                        page reference and a verified flag (21 of 46 unverified: reply formats and a few node names the guides do not print)
                        Keysight34411A in the same file is the 34411A (subclass: *IDN? match and message text only; every command is the 34410A's)
  simulated_34410a.py   Simulated 34410A (or 34411A: make_34410a_bench(..., model='34411A')) on the simulated calibrator (GPIB / USB behaviour, Front/Rear switch, overflow, error queue)
  agilent_3458a.py      Keysight / Agilent 3458A (GPIB, HP Multimeter Language, not SCPI: FUNC / NPLC / TRIG SYN reads in ASCII, SREAL, DREAL, null, ACAL, error queue); every command has a verified flag and a User's Guide page
  simulated_3458a.py    Simulated 3458A measuring an applied source or the bench calibrator (make_3458a_bench)
  keysight_332xx.py     Keysight/Agilent 33210A, 33220A, 33250A generators under test (settings one at a time with the
                        output OFF - never APPLy -, OUTP? confirmed, *TST? self-test)
  keysight_5313x.py     Agilent / HP 53131A and 53132A counters (frequency: input, gate, expected frequency, reference
                        oscillator, READ?; *TST?)
  fluke_28x.py          Fluke 287 / 289 over the IR cable: ID, QM, QDDA (two-line CMD_ACK protocol), display parser, set-up check,
                        stable reading; read-only (no reset commands)
  simulated_28x.py      Simulated 287 / 289 on the IR cable (function, range, REL, Low Pass, drift, overload)
  simulated_fgen.py     Simulated generator + 5790B + counter (53131A / 53132A or generic) + power meter bench for fgen_verification.py
  selftest.py           Safe hardware check:  python -m drivers.selftest --sim
                        python -m drivers.selftest --fluke ASRL9::INSTR --baud 9600 --scope USB0::...::INSTR
  _template.py          Starting point for a new model (includes the reset declaration)
  ../reset_startup.py   Shared start-of-run reset helper used by every engine (notice, reset, standby/off on failure, log line)

Rules every driver follows
  * Every setting is written, read back and compared; a mismatch raises InstrumentError.
  * Writes are never retried automatically (their effect is unknown after a failure).
    Only read-only queries may be retried (query_retry).
  * cleanup() leaves outputs off / standby and never raises; procedures call it in a finally block.
  * Every command and reply is recorded in a CommandLog. The WaveSurfer DCV test appends it to
    ~/.calibration_suite/command_log.txt so each reading can be traced to the exact commands sent.

Addresses
  USB     USB0::0x05FF::0x1023::<serial>::0::INSTR
  GPIB    GPIB0::6::INSTR
  RS-232  ASRL9::INSTR   (COM9)   - pass baud/parity etc: open_visa('ASRL9::INSTR', baud=9600)
  (pyserial instead of VISA:  SerialTransport('COM9', SerialSettings(baud=9600)))

Adding a model
  1. Copy _template.py to <maker>_<model>.py; set MODEL and IDN_MATCH.
  2. Add one method per thing a procedure needs. Cite the manual page in the docstring.
  3. Add the model to __init__.py, and a simulator class to simulated.py that understands the same strings.
  4. Add it to selftest.py with only safe checks (identify, set + read back with sources off).
  5. Declare the reset (Stage 7 rule): COMMANDS['reset'] = cmdreg.reset_cmd(verified, ref) (*RST or the model's equivalent; locked, never
     overridable) and COMMANDS['opc.query'] = cmdreg.opc_cmd(...); add 'status.clear' / 'err.query' if the model has them; override
     _reset_extra() with the model's known-state steps (re-enter remote, restore what connect() sets, confirm output OFF / standby).
     verified=True only with a manual page in ref. A model with no safe software reset sets RESET_EXEMPT = 'reason' and
     RESET_KNOWN_STATE = 'how its state is established instead' (see fluke_28x.py). Add the simulator's *RST / *OPC? handling.
     Every engine resets all its instruments through reset_startup before the first point; tests/test_reset_startup.py enforces both.
     (The TDS2000C scope resets with FACtory, never *RST or the self calibration; its scope-option calibrator is left in standby with SCOPE OFF.)
  6. Run the self-test on the real instrument and read the command log before using it in a procedure.

Status
  Every procedure now talks to instruments only through these drivers: the WaveSurfer tabs, the
  34401A and 8846A verification apps, and the 8846A adjustment app. Each run appends its exact
  commands to ~/.calibration_suite/command_log.txt (passwords are masked).
  Fluke 5560A in NORMAL mode (DMM procedures) does not read back OPER/STBY by default, matching the
  original procedures; use operate()/standby() instead of operate_unverified()/standby_quiet()
  once you have confirmed the readback on your calibrator.
