# Bench records (bench-first driver workflow, NOTES.md)
Raw results of the scripts in tools/bench, as the owner ran them on the bench PC. They are the "recorded real reply" a driver command needs before it is marked verified.

## 2026-10-29 step 1, read-only (2026-10-29_step1_readonly.json)
Bus: every 6060A-bench instrument is on GPIB1 (6060A 2, 8902A 14, 8563E 18, 96270A 4). GPIB0 has OTHER instruments at 14 and 18: a bare "14" in an address box
means GPIB0::14 and reaches the wrong instrument (the 2026-10-28 hang). Python 3.15 64-bit, pyvisa 1.16.2, Keysight visa32.dll.
- 6060A: ID -> "6060A/AN"; IV -> "V1.1"; IO -> "5,0,1" (field 3 = 1: Option -870 reverse-power protection is fitted; field 1 is 5, the manual says 3);
  II -> "00004"; IM -> "00192"; IU -> "000000,000000,000400" (RF off); IR -> "000020,000000,000000" (three 6-digit octal fields; 020 = a syntax error left over
  from an earlier session); LM99 -> 64 letters; XA -> "00023" (full attenuation, RF off). Replies end with LF only (no CR). Serial poll 23 before (ready +
  rejected entry + UNCAL + output valid), 21 after IR cleared the rejected entry.
- 8902A: does NOT answer ID (twice now); talk-only with nothing pending times out; the first serial poll timed out, the second read 0.  With the 6060A RF OFF
  every measurement (M5 with T1/T3, AU, manual tune, T0, T2) returns +9000009600E+01 CR LF at once = error 96, no input signal (2026-10-29_probe_8902a_rf_off.txt).
- 8563E: ID? -> "HP8563E"; REV? -> "971024"; SER? -> "3611A04800"; ERR? -> "112,111" (unrecognised command / not enough arguments, left from earlier);
  DONE? -> "1"; RL? -> "0 " (trailing space); AT? -> "10 "; RB? / VB? -> "1.0000E6"; ST? -> "5.3000E-1"; AUNITS? -> "DBM"; TDF? -> "P". Replies end with LF.
- 96270A: *IDN? -> "Fluke,96270A,398472732,1.17"; INST:CAT? -> "SINE,SWEEP,AM,FM,PM,FCO,PMET"; PMET1:IDN? and PMET2:IDN? -> "NONE,NONE,NONE,NONE":
  NO POWER SENSOR IS SEEN (the NRP40T is not connected, or not recognised). PMET1:FREQ? -> "5.0E+7" (the manual gives *RST 1E6).
- LF generator: not run (no address given).

## 2026-10-29 step 2, 6060A RF on, 8902A frequency (2026-10-29_step2_8902a_frequency.json)
- 6060A: RO0, FR111.1111MZ, AP-10DB accepted (IR 000000,000000,000000); LM99 read back 111 111 100 Hz and -10.0 dBm (characters 25-32 and 9-12 decode as the
  driver does); RO1 -> IU 000000,000000,000000; RO0 -> IU 000000,000000,000400 (RF off confirmed).  VERIFIED on the bench: FR..MZ, AP..DB, RO0/RO1, IR, IU, LM99.
- 8902A: IP, M5, 7.1SP, then T1 T3: the DISPLAY read 111.11110 MHz but nothing came over the bus in 20 s, three times; status byte 0 throughout.
  (With the RF off the same sequence returned error 96 at once.)  Step 3 looks for the way the reading is handed over.

## 2026-10-29 step 3, seven ways to get the 8902A frequency (2026-10-29_step3_8902a_frequency_ways.json)
GET after T1, GET alone, T3 with the data-ready mask, T2, T0, 7.0SP + T3, T3 with 60 s: the display always read 111.1111 MHz (111.11109 / 111.11110 at 10 Hz) and
every read timed out. With 22.3SP the serial poll read 65 (data ready + RQS) right after the setup and again right after T3: the receiver HAD a reading ready.
The reads of steps 2 and 3 ended on EOI only; the RF-off probe (whose read ended at LF) got its error word at once. Conclusion to confirm in step 4: the
8902A does not assert EOI with a reading, so the read must end at the LF of its CR LF (drivers/hp_8902a.py _line_ends already does this since 2026-10-28).

## 2026-10-29 step 4, the same as step 2 with the 8902A read ending at LF (2026-10-29_step4_8902a_read_to_lf.json)
CONFIRMED: IP, M5, 7.1SP, T1, T3, read (ends at LF) -> "+0011111109E+01" CR LF, "+0011111108E+01", "+0011111109E+01" = 111 111 090 / 080 / 090 Hz, 1.4 to 2.7 s after T3,
display 111.11109. The 8902A does not assert EOI with a reading. The driver reads to LF (since 2026-10-28) and no longer sends a tune code before M5.
The 8902A reads 10 to 20 Hz BELOW the 6060A's 111 111 100 Hz: one to two counts at 10 Hz. The two were most likely on separate time bases (4A-4 step a connects the
6060A 10 MHz IN/OUT to the counter's reference input): to be checked before 4A-4 is judged (limit +/- 1 count).

## 2026-10-29 step 5, 96270A power meter + R&S NRP40T on the 6060A at 120 MHz (2026-10-29_step5_96270a_power_meter.json)
- The 96270A (firmware 1.17) sees the sensor: PMET1:IDN? -> "ROHDE&SCHWARZ,NRP40T,101033,03.50.25102101". NRP40T support CONFIRMED on this unit.
- INST PMET -> INST? PMET; PMET1:FREQ 120E6 -> 1.2E+8; PMET1:AVER AUTO -> AUTO; PMET1:TRIG CONT -> CONT; SYST:ERR? 0 throughout; OUTP? 0 throughout.
- UNIT:POW? answers NONE in power-meter mode: the driver no longer sets or checks it. Readings are dBm.
- PMET1:ZERO? -> 0 after 10.6 s (6060A RF off). RF off: -37.831 dBm.
- 6060A -10 dBm -> -10.51 dBm (x3); 0 dBm -> -0.484 dBm (x3; front panel -0.49). Both inside the 4A-5 +/-1.5 dB.
- INST SINE at the end -> SINE, OUTP? 0.
Driver: PMET1: commands (as on the bench), continuous trigger by default (SING is UNVERIFIED), no UNIT:POW in power-meter mode.

## 2026-10-29 step 6, 8902A tuned RF level with the suite driver, no power-sensor calibration (2026-10-29_step6_8902a_tuned_level.json)
- With reads ending at LF the 8902A DOES answer ID: "+0000089021E-01" (= 8902.1, the model as a number). The earlier "no reply" was the EOI read.
- 120MZ, S4, LG, 4.0SP, T1, T3: -10 -> -10.58, -30 -> -30.58, -60 -> -60.85, -90 -> -91.50 dBm (display agrees), 6.8 to 17.7 s per reading; -120 and -127: error 96 (display "--").
- The serial poll stayed 0 throughout: the preset SRQ mask hides RECAL (bit value 32), so the driver never saw a RECAL and never calibrated a range. The power-sensor
  zero / 1 mW calibration was not done either (owner: "the -120 and -127 no reading have to do with the sensor not being calibrated before hand").
  Step 6b repeats it the manual's way (p. 3-97): ZR + C1T3SC first, mask 22.34SP so RECAL shows, 6 dB steps, C1 at each RECAL.
