# Challenge canvas: Larmor, an evidence-gated health twin

Team: Rehmoz Ayub, Ege Eroglu, Oussama Turki. Lane A (true change or measurement change?) joined with lane E (what measurement next?). Educational prototype on SIMULATED data. Not a clinical statement, not a diagnosis, not a medical device.

## Aim contract

| Item | Our answer |
|---|---|
| Physical counterpart | One synthetic brain (subject `sub-01`), seen through one 20 mm cube of frontal tissue. The same scanner measures it twice, six months apart. |
| Modality | Single-voxel proton spectroscopy (1H MRS, PRESS, TE 30 ms, TR 2 s, 64 averages, 123.25 MHz) plus a T1-weighted MRI for the region volume. |
| State variable to update | Cho/Cr: the choline peak (3.20 ppm) divided by the creatine peak (3.03 ppm) in that voxel. NAA/Cr and the region volume ride along as secondary variables. |
| Ambiguity to resolve | Cho/Cr went from 0.69 to 0.85. Did the tissue change, or did the measurement change? The second scan had broader lines (8.7 to 11.4 Hz) and less signal over noise (SNR 31 to 25). |
| Prototype output | A gated twin update with its reasons: Cho/Cr 0.69 becomes 0.741 ± 0.048 (update with warning, gain K = 0.32), a predicted range for a clean repeat (0.61 to 0.88), and one next measurement (re-shim and repeat, about 4 minutes). |
| One limitation | Synthetic data, one subject, two sessions. The natural drift we allow for (process noise Q) is a teaching assumption, not a measured test-retest value. |

## Aim contract in one paragraph

We follow one synthetic brain, seen through one frontal voxel, across two spectroscopy sessions six months apart. The twin keeps a belief about Cho/Cr: a best value and how unsure it is. The follow-up value rose from 0.69 to 0.85, but the follow-up scan was worse. We want the twin to decide how much of that rise it may believe, show why, and say which measurement would settle the question for the least scanner time. The limit: the data are synthetic, so the result says nothing about any real person.

## Primary variable, declared before looking

We named Cho/Cr as the primary variable before we looked at the follow-up numbers. Testing three variables and reporting whichever one moves is the multiple-testing trap (dossier section 3.10). So the rules are fixed in `nmr_twin/config.py`:

- Primary variable: Cho/Cr. A change counts as significant when the absolute z is above 1.96 (two-sided 5 %).
- Secondary variables (NAA/Cr, region volume): stricter limit, absolute z above 2.394 (Bonferroni, 0.05 divided by 3).
- Model surprise: d² above 3.841 (chi-square, one degree of freedom, 95 %) raises a "model disagreement" flag.

## Success criterion

We call the prototype a success when all of these hold. Each one is checked by an automatic test.

- The baseline-to-follow-up update reproduces the dossier's worked example: z = 2.05, d² = 3.66, K = 0.32, posterior 0.741 ± 0.048.
- Every twin number traces back to its source file, and the file's SHA-256 fingerprint is verified live.
- All 20 practice packets (19 of ours plus the organizers' bad packet) get the expected decision: update, update with warning, or reject.
- The twin names one next measurement, with its cost in scanner minutes and the uncertainty it removes.
- The scientific claim stays modest: "suggestive, not conclusive". z = 2.05 is just above 1.96, and d² = 3.66 is just below 3.84.

## Maturity level

We claim level 5 on the dossier's ladder (section 7.11), and one step past it.

- Level 3, dynamic twin: a saved belief with its uncertainty, updated only by checked evidence.
- Level 4, predictive: the twin states the range a clean repeat should fall in (0.61 to 0.88).
- Level 5, evidence-steering: the twin ranks the next measurements and names the one that separates the explanations. When that repeat arrives (practice packet U01), the open question closes and the advice changes.
- Past the ladder: we grade the twin against known truth. 250 simulated follow-ups with a known answer measure its error bars and its WARN factor (1.4 measured, 2 declared).

## The worked update, in numbers

| Quantity | Value | What it means |
|---|---|---|
| Baseline belief | 0.69 ± 0.05 | First packet sets the starting belief. Baseline is not truth; it keeps its uncertainty. |
| Follow-up evidence | 0.85 ± 0.06, QC WARN | Linewidth and SNR are at their warning limits, so the evidence counts with doubled variance. |
| Change test z | 2.05 (limit 1.96) | The change is a little larger than its combined noise. |
| Surprise d² | 3.66 (gate 3.84) | Given six months of allowed drift, the value is not quite surprising. |
| Gain K | 0.32 | The twin moves 32 % of the way toward the new value. |
| New belief | 0.741 ± 0.048 | Twin state after the update (INFERRED). |
| Expected clean repeat | 0.61 to 0.88 | A repeat outside this range would be real news. |
| Next measurement | Re-shim and repeat PRESS, 4.1 min | Best uncertainty gain per minute, and it removes the cause of the warning. |

## Four tracks on one number

| Track | Question | What it hands over |
|---|---|---|
| Quantum Engineering | What is physically observed? | Measurement card: meaning, unit, valid range, what Cho/Cr cannot tell. |
| Precision Mechanics / Metrology | Can we trust and reproduce it? | Uncertainty card: five error sources; the spectral fit carries about 60 % of the variance. |
| Data Science | How is the evidence carried and checked? | Evidence packet (schema v1.0), data dictionary, SHA-256 provenance. |
| Digital Twins | How does evidence update the state? | Gated update with an event log, a prediction and a next-measurement proposal. |
