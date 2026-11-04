---
name: uncertainty-from-scope
description: Use when assigning measurement uncertainties (and TUR) to a Calibration Suite procedure's points from the standards' published specifications and the lab's A2LA scope (CMCs), including marking points the scope does not cover.
---

# Uncertainties from the standards and the A2LA scope

Worked example: `Procedures/fluke6060a_uncertainty.py` (6060A GIDEP), `specs/a2la_1888_03_rf.json` (built by `specs/build_a2la_cmc_rf.py`), `report_pdf.py` (`scope_star_note`). NOTES.md is the authority if anything here is older.

## 1. Inputs
- The scope: A2LA certificate 1888.03. Encode the lines you need in a `specs/a2la_*.json` with a committed builder script, read from the RENDERED scope pages (not extracted text).
- Each standard's specification as a `specs/standards/<model>_standard.json` built from the manual by a committed `specs/build_<model>_standard_from_manual.py`, every row with page reference and confidence.
- Ask the owner once about the standards' options (for example "no Option 050" on the 8902A) and about scope lines whose fit is unclear.

## 2. Budget per point
- Each contributor = printed spec / divisor. Divisor 2 when the spec states no confidence (treated as k=2), otherwise the divisor for the stated confidence (for 99 % ask the owner; it is still an open question for the 96270A).
- Combine by root-sum-square, expand with k=2, round UP to 2 significant figures (`ceil_sig`). Decimal arithmetic for limits.
- Use the standard that actually makes the measurement for that point (the deviation meter is measured with the 96270A; frequency points with the counter on the GPS 10 MHz).
- Where several spec rows or scope lines apply, use the narrowest modulation-rate or frequency band that contains the point.

## 3. Scope marking
- Point covered by a scope line: reported uncertainty = max(budget, CMC). Show TUR.
- Point not covered: report the budget with " *" appended. `report_pdf` prints the footnote only when some Uncertainty cell ends with "*". No TUR.
- Unclear fit: star it and list it on the review page for the owner to decide. Do not guess in either direction.
- Frequency points (frequency, reference frequency, modulation rate): report the A2LA Frequency - Measure CMC alone (7.1e-12 x f, GPS), `Result.cmc_only`.

## 4. Wiring
- One `evaluate(point, reading, path)` with a handler per measurement kind; keep the decisions in a `DECISIONS` table so the review page can show them.
- Register the state key in the engine's `UNCERTAINTY_STATE_KEYS`. Format values in the point's natural unit (kHz values printed in Hz; "310 mkHz" was a bug).
- Tests: a test per handler with a hand-computed number, plus a test that starred points carry no TUR and the footnote appears in the PDF.

## 5. Deliver
- Show the owner a sample PDF and the full report before calling it done. NOTES.md entry listing every assumption (divisors, options, chosen scope lines, starred points). Commit, push and build as in the `bench-issue-fix` skill, section 5.
