# System architecture

Larmor is one small program. A Python engine (`nmr_twin/`) holds the twin and all the rules. A FastAPI server (`server.py`, `routes/`) exposes the engine as a JSON API. A plain JavaScript front end (`web/`) draws the pages. There is no database: the twin state is one JSON file (`state/twin_state.json`) with an append-only event log.

## In one picture

A scanner file becomes an evidence packet. The packet goes through a six-layer check. The check decides update, update with warning, or reject. Only checked evidence may move the twin, and how far it moves depends on how much the evidence can be trusted. The twin then predicts the next value and proposes the next measurement, which closes the loop back to the scanner.

## Data flow

| Step | What happens | Modules | Output |
|---|---|---|---|
| Source file | The scanner data on disk: NIfTI-MRS spectra and NIfTI images from the StarterPack. We read the raw bytes ourselves and recompute SNR and the region volume. | `nmr_twin/imaging.py`, `nmr_twin/context.py` | File bytes, SHA-256 fingerprint, recomputed numbers |
| Evidence packet | One number with its unit, uncertainty, quality checks, source file, fingerprint and epistemic label, in the shared schema v1.0. | StarterPack `05_TwinReady_JSON_CSV`, `test_packets/` | JSON packet |
| Six-layer check | Parse, schema, semantic, linkage, physics, policy. Each finding names its owner track. A claim is never strengthened, missing stays missing, bad input never crashes. | `nmr_twin/checker.py`, `nmr_twin/findings.py` | Verdict: PASS, WARN or FAIL, with findings |
| Gated update | PASS updates normally. WARN updates with doubled variance. FAIL is logged and changes nothing. The gain K decides how far the twin moves. | `nmr_twin/twin.py`, `nmr_twin/service.py` | New belief plus one event in the log |
| Prediction | The range a clean repeat should land in if nothing changed: posterior ± 1.96 times the combined SD. | `nmr_twin/planner.py` | Expected repeat range |
| Explanations | For each change: true change, shim, noise, voxel position, software, calibration. Each gets the evidence for and against, and the test that would tell them apart. | `nmr_twin/explain.py` | Competing explanations |
| Next measurement | Candidate measurements ranked by uncertainty removed per scanner minute, plus tests that separate a bias from a real change. | `nmr_twin/planner.py`, `nmr_twin/config.py` | Ranked proposal |
| Provenance | Walks back from a twin value to the event, the packet, the processing steps and the source file, and re-verifies the fingerprint. | `nmr_twin/provenance.py` | Graph from twin value to file |

## Supporting components

| Component | What it does | Modules |
|---|---|---|
| Test bench | Simulates many follow-up scans with a known true Cho/Cr, sends each one through the real checker and twin, and counts how often the 95 % range contains the truth. This tests the WARN factor instead of assuming it. | `nmr_twin/bench.py`, `routes/bench.py` |
| 3D evidence view | Builds surfaces of the brain, the region mask and the spectroscopy voxel in scanner millimetres, so you can see where the evidence comes from. | `nmr_twin/mesh.py`, `routes/scene.py` |
| Regression tests | Check the dossier's worked numbers, its cross-team checks, every practice packet, and that the twin data dictionary matches the code. | `tests/` |

## Tracks and their handover artifacts

| Track | Question | Owns in the code | Hands over to |
|---|---|---|---|
| Quantum Engineering | What is physically observed? | Measurement card (`cards.py`), spectrum and SNR from the raw signal (`imaging.py`), SNR gate, valid range, field versus frequency check | Metrology: what the number means and what it cannot tell |
| Precision Mechanics / Metrology | Can we trust and reproduce it? | Uncertainty card and budget (`cards.py`), linewidth and registration gates, protocol match, honest region-volume uncertainty rule | Data Science: the uncertainty that must travel with the number |
| Data Science | How is the evidence organized, checked and queried? | Schema, units, epistemic labels, subject and session linkage, SHA-256 checks (`checker.py`, `context.py`), data dictionaries | Digital Twins: a checked packet with a verdict |
| Digital Twins | How does evidence update the virtual state? | State, update rule, gate, prediction, explanations, next measurement (`twin.py`, `planner.py`, `explain.py`) | Back to Quantum Engineering: which measurement to make next |

## Digital twin system components

The TU/e lecture (Dr. ir. Ion Barosan, 20 Nov) describes a digital twin system with five connected components, a cognitive component and a mission. This is how ours maps.

| Code | Component | In our prototype | Modules |
|---|---|---|---|
| PT | Physical twin | The synthetic brain voxel and the scanner that senses it. The measurement card states what it can see. | StarterPack data, `cards.py` |
| DT | Digital twin | Three state variables, each a mean and a variance, with observation model h = 1 and the gated update rule. | `twin.py`, `config.py` |
| DD | Digital twin data | Evidence packets, the event log, the data dictionaries and the provenance trail. | `state/twin_state.json`, `provenance.py`, `deliverables/twin_data_dictionary.csv` |
| CN | Connections | The data contract at every interface: unit, uncertainty and provenance travel with each number. Inside the app, a REST JSON API. | schema v1.0, `server.py`, `routes/` |
| SS | Services | Monitoring, the six-layer check, the update decision, the uncertainty display, the audit export and the regression tests. | `checker.py`, `server.py`, `web/` |
| CC | Cognitive component | Competing explanations and the next-measurement advice. The twin advises; it does not diagnose. | `explain.py`, `planner.py` |
| Mission | Mission | "Has it changed, and how sure can we be?" for one number, so the twin only believes what the measurement supports. | whole system |

## Four views

| View | Who looks | What they see | Where in the app |
|---|---|---|---|
| Domain | A physicist or clinician-scientist | Spins, spectrum, peaks, voxel, linewidth, SNR: what the number physically is | Twin state (journey of one number), Scans and spectra, Measurement cards |
| Developer | Whoever maintains the code | Modules, the packet schema, the event log, the regression tests | `nmr_twin/`, `tests/`, Regression tests page, this file |
| Application | The organization running the twin | Services: check a packet, update, predict, explain, propose, export the audit trail, test bench | Check a packet, What to measure next, Test bench, Audit trail export |
| User | A mentor or judge at the demo | One belief with its error bar, a plain verdict with reasons, and the next step | Twin state, Trace to source, Competing explanations, 3D evidence view on Scans |

## Interface contract

The dossier (section 8.3) lists what a consumer must not assume. This is how the code enforces each one.

- A number is not comparable across protocols. The checker compares sequence, TE, TR, field and frequency with the baseline and warns on any difference.
- Passing QC does not make a biological reading certain. The verdict says "suggestive, not conclusive", and the explanations stay open.
- A clean schema does not remove measurement bias. The schema is only layer 2 of 6; physics and metrology come after it.
- A model prediction is not clinical truth. Every twin output is labelled INFERRED, and the page header says SIMULATED.

## Technology

- Engine: Python 3.11, numpy, scipy, jsonschema; scikit-image only for the 3D surfaces. No machine learning.
- Server: FastAPI with uvicorn, one process, one lock around the twin.
- Front end: vanilla JavaScript modules and hand-drawn SVG, no build step, fonts and icons served locally.
- State: one JSON file plus an append-only event log. Any number on screen can be traced to its event.
- Tests: pytest. They check the dossier's worked numbers, its cross-team checks and every practice packet.

## Transfer to devices and objects

Only the observation model and the state variables are specific to the brain. The evidence packet, the six-layer check, the uncertainty budget and the update rule stay the same for a battery cell seen by lithium MRI, an elastomer seal seen by single-sided NMR, or the scanner itself followed through its phantom record (dossier J.6).
