# Limitations and ethics

## Short limitations statement

Larmor is an educational prototype on synthetic data. It follows one synthetic brain, one frontal voxel and two sessions six months apart. It shows how evidence should move a belief; it says nothing about any real person. The drift it allows for, the warning factor and two failure limits are teaching assumptions or declared team policy, and they are marked as such. Outside the conditions listed below, the correct output is "not validated for this condition".

## Validation domain

What the twin has been built and tested for. "Tested" means automatic tests on the StarterPack data and on our 19 practice packets.

| Condition | Validated for | What the code does outside it |
|---|---|---|
| Field strength | 3 T label; the real field is 2.895 T (123.25 MHz divided by 42.577 MHz/T) | Reports both values; warns when label and frequency disagree by more than 5 %; warns on a field change versus baseline |
| Sequence | PRESS single-voxel 1H spectroscopy; T1-weighted MRI for the region volume | Warns on a sequence change versus baseline |
| Echo and repetition time | TE 30 ms, TR 2 s | Warns on a TE or TR change (practice packet U10, TE 144 ms) |
| Voxel | Frontal, 20 mm cube, centre (-16, 45, 6) mm | Position is shown but not yet compared between sessions; a moved voxel is an open item |
| Quantities | Cho/Cr, NAA/Cr, region volume | Any other quantity is rejected: the twin has no observation model for it (U08) |
| Data | SIMULATED, StarterPack v0.3, subject sub-01, two sessions | Simulated data labelled MEASURED are rejected (U03) |
| Population | None. One synthetic subject. | No claim about any group, age, sex, scanner vendor or disease |

Anything outside this table is "not validated for this condition". Today the checker warns on a protocol change and rejects unknown quantities. It does not yet refuse every out-of-domain packet in those words; that is listed under open items.

## Synthetic data only

- Every value in the app is of SIMULATED origin: synthetic spectra and images from the organizers' StarterPack v0.3.
- The header of every page carries a SIMULATED badge. The engine adds the same disclaimer to the saved state.
- A simulated value labelled MEASURED is rejected by the checker, so synthetic data cannot be passed off as real.

## Clinical non-equivalence

- The twin does not diagnose, does not recommend treatment and does not predict risk for a person.
- Its strongest statement is "suggestive, not conclusive". Insufficient evidence is an accepted outcome.
- The next-measurement advice is about evidence (what to scan next), never about care.
- This is an educational prototype. It is not a research tool and not a clinical system, and it is not a medical device.

## Privacy

- Pseudonymous identifiers only: `sub-01`, `ses-baseline`, `ses-followup`. No names, birth dates or hospital numbers exist anywhere in the system.
- The twin works in relative time (months since baseline). Session dates are used only to cross-check the packet's own relative time.
- We never read DICOM headers. The code reads only NIfTI and NIfTI-MRS files and copies no DICOM identifiers into packets, state or logs.
- The event log stores packet IDs, fingerprints and processing steps, not images.
- Before any real health data: privacy, consent, governance and security review first, technical integration second (dossier Appendix I).

## Bias and transfer

- Bias is a measurement issue here. A model tuned on one scanner, field, protocol or population may not transfer.
- Everything was built on one synthetic subject from one simulated scanner. We make no claim beyond the validation domain above.
- Ratios to creatine assume creatine is stable. If creatine itself changes, the ratio is biased. We say this openly in the measurement card.
- The quality limits (SNR 25, linewidth 10 Hz at 3 T) are field-specific. At low field they would need new values.

## Teaching assumptions and declared policies

| Item | Value | Status | Where |
|---|---|---|---|
| Process noise Q (natural drift) | Cho/Cr and NAA/Cr: SD 0.03 per 6 months; region volume: 1 % per 6 months | Teaching assumption, to be replaced by test-retest data | `nmr_twin/config.py` |
| WARN factor | Evidence with warnings counts with 2 times its variance | Declared team policy; adjustable with the slider on Twin state | thresholds `twin_policy` |
| Linewidth FAIL limit | 20 Hz | Proposal, not yet agreed with the partners | thresholds-v1.0 |
| Registration FAIL limit | 3 mm | Proposal, not yet agreed with the partners | thresholds-v1.0 |
| Surprise gate | d² above 3.841 | Convention (chi-square, 95 %) | `nmr_twin/config.py` |
| Change limits | z above 1.96 (primary), 2.394 (secondary) | Declared before looking at the data | `nmr_twin/config.py` |
| Plausible region change | 5 % in 6 months | Teaching assumption | `nmr_twin/config.py` |
| Clean repeat SD | 0.05 for Cho/Cr | Assumed PASS-quality repeat after re-shim | `nmr_twin/config.py` |
| Uncertainty budget terms | Five sources, 0.010 to 0.045 | Teaching budget from dossier Appendix D | `nmr_twin/cards.py` |
| Measurement costs | 4.1 to 10 scanner minutes | Teaching values from dossier section 7.7 | `nmr_twin/config.py` |

## Epistemic labels

- MEASURED: recorded by an instrument. Here the spectra are SIMULATED instead.
- DERIVED: computed from data by a declared method. Example: the fitted Cho/Cr ratio.
- INFERRED: a model statement about something not observed directly. Example: the twin state, its posterior interval and every update decision.
- SIMULATED: produced by a forward model with known inputs. Example: every StarterPack file.

Every packet carries its origin and its label, and the twin data dictionary gives the label of every output field.

## Use of AI

- The team chose the question, the primary variable, the update policy and the limits, and answers for every claim.
- Claude (Anthropic) was our coding tool. It wrote the code and the first drafts of these documents to our direction. Rehmoz Ayub directed and reviewed the work.
- We did not take its output on trust. Every number the app shows is checked against the dossier by automatic tests, and the test bench grades the twin against known truth.
- The help assistant inside the app runs on a local model on our own laptop. It answers only from our documents, and nothing leaves the machine.
- No personal data were given to any AI. All inputs were the synthetic StarterPack and the dossier.

## Open items

- Refuse out-of-domain packets (other field, other voxel location) with the words "not validated for this condition", instead of only a warning.
- Replace the teaching drift Q with test-retest data.
- Repeat the WARN-factor measurement on real test-retest scans. Our test bench supports 1.4 on simulated scans, so the declared 2 is on the safe side there.
- Agree the two proposed FAIL limits with the partners.
