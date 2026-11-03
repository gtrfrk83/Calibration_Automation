---
name: bench-issue-fix
description: Use when the owner reports an error, wrong reading or unwanted check from a real bench run of an existing Calibration Suite procedure (often a screenshot): reproduce it in the simulator, fix only that procedure, test, document, commit and send a new build.
---

# Fixing a problem found on the bench

The owner runs procedures on real instruments and reports what went wrong, usually with a screenshot ("8902 displays error 20 at 150 kHz", "uncal unless I step from 242 MHz", "read-back refused"). NOTES.md (Standing rules) is the authority if anything here is older.

## 1. Understand the report
- Read the screenshot exactly: instrument, point id, message text, any raw string (learn string, error number). The raw string is the evidence; decode it before changing code.
- Find the point in the spec builder (`specs/build_<model>_spec.py`) and the code path in the engine and driver that produced the message.
- If the fix is a choice the owner must make (move a point, delete points, mark not tested, change a limit), ask once with the options and a recommendation. Do not change limits, nominals or commands of other points or other procedures without being asked.

## 2. Reproduce it in the simulator first
- Make the simulated instrument behave like the real one (for example `Sim8902ATransport.tuned_floor_mhz`, `Sim6060ATransport.approach_band` and `pll_settle_reads`, `Sim5334BTransport.no_oscillator`).
- New realism is OPT-IN: a constructor attribute that defaults to off, set only in the test that needs it. An always-on change breaks other procedures' tests (an always-on 8902A tuned floor broke the Instruction Manual 4A-8 test).
- Put the attribute in `__init__`, not in the reset method, unless a reset on the real instrument also clears it. State that is cleared by a reset belongs in the reset.
- Write the failing test before the fix and see it fail for the reported reason.

## 3. Fix
- Smallest change that removes the problem for this procedure: a spec builder change (regenerate the JSON), an engine option, or a driver method. Keep the Instruction Manual and GIDEP variants separate where they differ (check `STATE_KEY`).
- Moving or deleting points renumbers them: saved checkpoints are keyed by point id, so stale results must be dropped (`drop_stale_results`, the spec option `checkpoint_requires_ref`, `moved_from` on the moved point for the report).
- Writes are still set, read back, compare, and never retried. If a read-back check itself is wrong (the 6060A FM field is in display digits, the deviation meter mode never has RF on), fix the decode or skip the check for that mode, and log what was skipped.
- A check that is too tight against display resolution (8902A 1 mW reading 1.0004 mW) is judged at the display resolution with a log line, not deleted, unless the owner asks for deletion.

## 4. Test
- Run the procedure's own modules first (for the 6060A: `tests.test_fluke6060a_gidep`, `tests.test_fluke6060a_points`, `tests.test_fluke6060a_drivers`, `tests.test_fluke6060a_uncertainty`, `tests.test_golden_commands`).
- Golden command transcripts: `python -m tests.golden_capture --update` only after reading the diff. Log or message changes are fine; any changed `>>` command line must be intended.
- The test harness answers yes/no prompts with True. Tests that must not trigger a calibration patch the question (the 8902A calibration question is answered No in the bench tests).
- Then run the full suite in the background and compare with the clean-main baseline by test NAME (see the `new-calibration-procedure` skill, section 6, for the known failures). `test_mdo_pause_scale_scales_every_wait` is order-dependent, and `test_tartur_wiring_dmm` fails when `origin/tartur-integration` has been fetched; neither is caused by your change.

## 5. Document, commit, build
- NOTES.md entry under the procedure: what the owner reported (quote it, with the date), what changed, what is UNVERIFIED, and "NOT run on the bench yet" until the owner confirms.
- Commit with the session attribution lines and push to the working branch.
- Build the zip from the commit (never from the working tree):
  `git archive --format=zip --prefix=Calibration_Suite/ -o <scratchpad>/Calibration_Suite_v70_<tag>_<shortsha>.zip HEAD`
  and send it with SendUserFile.
- Reply to the owner: what was wrong, what changed, what to try first on the bench, and any open questions as a short list.
