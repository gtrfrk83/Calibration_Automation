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
