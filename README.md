# Larmor

A digital twin that decides how far new scan evidence may move its belief.

One number, Cho/Cr (choline divided by creatine in one small cube of brain tissue), rose from 0.69 to 0.85 between two scans taken six months apart. The second scan was worse: broader peaks and more noise. Larmor moves its belief a third of the way, to 0.741 ± 0.048, lists what else could explain the rise, and asks for a repeat scan.

All data are simulated. Larmor is an educational prototype and makes no clinical statement.

## See it

- How to use it: https://rehmozayub.github.io/larmor-health-twin/
- The twin and the test bench: https://rehmozayub.github.io/larmor-health-twin/app/

The online copy is read-only. It shows stored packets and one stored bench run. To check a packet of your own or run a new bench, run it on your own computer.

## Run it yourself

1. Install Python 3.11.
2. Install the packages:

   ```
   pip install -r requirements.txt
   ```

3. Get the organizers' StarterPack v0.3. It is not in this repository. Put the folder `MRI_Hackathon_DataScience_StarterPack_v0.3` next to the `twin` folder, or point the environment variable `NMR_STARTERPACK` at it.
4. Start the app from this folder, then open http://localhost:8765:

   ```
   py -m uvicorn server:app --app-dir twin --port 8765
   ```

   On macOS or Linux, write `python` in place of `py`.

5. Run the tests:

   ```
   py -m pytest twin/tests
   ```

Felix, the help assistant, is optional. It needs a language model running on your own machine with an OpenAI-style API. Point `LARMOR_LLM_BASE_URL` and `LARMOR_LLM_MODEL` at it. With no model, set `LARMOR_ASSISTANT_WARM=0` and everything else works as before.

## What is in here

| Folder | What it holds |
|---|---|
| `twin/nmr_twin/` | The engine: packet checker, twin update, planner, explanations, test bench |
| `twin/routes/`, `twin/server.py` | The web API |
| `twin/web/` | The front end and the slides |
| `twin/tests/` | Automatic tests, including every number of the organizers' worked example |
| `twin/test_packets/` | Our own practice packets |
| `twin/deliverables/` | Challenge canvas, architecture, limits, data dictionary, QC report |
| `docs/` | The published page and the read-only copy of the app |

## Limits

- The data are synthetic. They come from the organizers' StarterPack for the InnovateU NMR challenge "From Spins to a Health Digital Twin" (Ulm, 21 Nov 2026).
- One subject, two sessions.
- No clinical meaning. The twin advises what to measure next and never names a diagnosis.
- The drift we allow over six months is a teaching assumption.

## How we worked

The team is Rehmoz Ayub, Ege Eroglu and Oussama Turki. We chose the question, the primary variable, the update policy and the limits, and we answer for every claim.

Claude (Anthropic) was our coding tool. It wrote the code and first drafts to our direction. Every number is checked against the organizers' dossier by automatic tests.
