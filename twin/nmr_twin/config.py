"""Team configuration: where the data live, which twin variables exist, and the declared team policies.

Everything that is a *choice* (not physics) lives here, so it can be shown and defended in one place.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]          # .../NMR Hackathon/twin
HACKATHON_ROOT = PROJECT_ROOT.parent                          # .../NMR Hackathon
STARTERPACK = Path(os.environ.get("NMR_STARTERPACK", HACKATHON_ROOT / "MRI_Hackathon_DataScience_StarterPack_v0.3"))
TWIN_READY = STARTERPACK / "05_TwinReady_JSON_CSV"
SESSIONS_EXTRA = PROJECT_ROOT / "data" / "sessions_extra.tsv"  # sessions registered by our team (e.g. a repeat scan)
STATE_FILE = PROJECT_ROOT / "state" / "twin_state.json"

GAMMA_BAR_MHZ_PER_T = 42.577  # 1H gyromagnetic ratio / 2 pi

# --- Twin state variables and their observation models (h = 1: the packet observes the variable directly) ---
# q_sd_6mo: expected natural drift over six months (process noise). TEACHING ASSUMPTION from dossier §7.5,
#           to be replaced by test-retest data. q_sd_6mo_rel is relative to the current state mean.
STATE_VARIABLES: dict[str, dict] = {
    "roi_volume": {
        "label": "ROI volume", "unit": "mm3", "modalities": {"MRI"}, "group": "G (geometry)",
        "q_sd_6mo_rel": 0.01, "plausible_change_6mo_rel": 0.05,
        "meaning": "Volume of one brain region from a partial-volume mask (sum of fractions x voxel volume).",
    },
    "NAA_Cr": {
        "label": "NAA/Cr", "unit": "1", "modalities": {"MRS", "MRSI"}, "group": "M (metabolic)",
        "q_sd_6mo": 0.03,
        "meaning": "Ratio of the NAA peak (2.01 ppm) to the creatine peak (3.03 ppm) in the frontal voxel.",
    },
    "Cho_Cr": {
        "label": "Cho/Cr", "unit": "1", "modalities": {"MRS", "MRSI"}, "group": "M (metabolic)",
        "q_sd_6mo": 0.03,
        "meaning": "Ratio of the choline peak (3.20 ppm) to the creatine peak (3.03 ppm) in the frontal voxel.",
    },
}

# Declared before looking at the data, to avoid the multiple-testing trap (dossier §3.10).
PRIMARY_VARIABLE = "Cho_Cr"
ALPHA = 0.05
Z_CRIT_PRIMARY = 1.960                  # two-sided 5 %
Z_CRIT_SECONDARY = 2.394                # two-sided 0.05/3 (Bonferroni over three features)
D2_GATE = 3.841                         # chi-square, 1 degree of freedom, 95 %

# Tolerances used by our own consistency rules (team choices, shown in the app).
FIELD_MISMATCH_WARN_REL = 0.05          # nominal vs frequency-derived B0
FREQ_MATCH_REL = 1e-3                   # spectrometer frequency equal to baseline within 0.1 %
RELATIVE_TIME_TOL_MONTH = 0.5           # packet relative_time vs sessions table

# --- Field comparability (dossier §5.8 protocol_match: "FAIL if field differs without harmonization"; §6.5) ---
# Two fields count as "the same field" when the frequency-derived B0 values agree within 5 %
# (so 2.895 T from 123.25 MHz and a nominal 3.0 T are the same field; 1.5 T vs 3 T is not).
FIELD_SAME_REL = 0.05
# A packet declares harmonization like this (our convention, following §6.5 "store the transformation used, and
# state whether the transformed value is fit for trend analysis"):
#   "processing": {..., "harmonization": {"method": "<name of the transformation>", "fit_for_trend": true,
#                                         "raw_value": <value before harmonization, optional>}}
HARMONIZATION_HOWTO = 'processing.harmonization = {"method": "...", "fit_for_trend": true}'

# --- Field-aware linewidth gate ---
# The 10 / 20 Hz linewidth gates are defined for 3 T 1H (thresholds context "3 T, 1H"). Metabolite peaks sit a fixed
# number of ppm apart (Cho 3.20 vs Cr 3.03 ppm), so whether they overlap depends on the width in ppm, not in Hz.
# At 3 T (within FIELD_SAME_REL) the Hz numbers are used exactly as written. At any other field the same limits are
# kept in ppm: 10 Hz at the StarterPack's 123.25 MHz = 0.081 ppm.
LINEWIDTH_REF_FIELD_T = 3.0
LINEWIDTH_REF_FREQ_MHZ = 123.25

# --- Uncertainty floor (dossier §5.6 repeatability, §5.7 budget, §5.8 "stated u >= implied u, carry the implied u") ---
# TEACHING FLOOR, to be replaced by the site's test-retest data (StarterPack v0.4). Below this, a stated uncertainty
# is not believable for ONE scan: voxel placement, chemical-shift displacement and calibration add error that no
# spectral fit or segmentation removes. A smaller stated u is carried forward as the floor (WARN), so one packet
# cannot collapse the twin's uncertainty.
U_FLOOR = {
    "Cho_Cr": {"rel": 0.02, "abs": 0.01},
    "NAA_Cr": {"rel": 0.02, "abs": 0.01},
    "roi_volume": {"rel": 0.01, "abs": 0.0},
}

# --- Evidence scope: calibration evidence is not health evidence (dossier §5.3 levels 1-2; §11.3: the scanner's own
# instrument checks and phantom calibrations form a health record of the INSTRUMENT, not of the person) ---
CALIBRATION_MODALITIES = {"calibration"}
CALIBRATION_SUBJECT_WORDS = ("phantom",)

# Provenance parents that mean "no source" (dossier §6.6-6.7: every feature is traceable to a source object).
NO_SOURCE_TOKENS = {"", "none", "n/a", "na", "null", "unknown", "-", "nan"}

# Candidate next measurements (dossier §7.7, Figure 17). sigma_m = expected SD of the new value, None = no
# direct variance information (the action tests a bias instead).
NEXT_MEASUREMENTS = [
    {"name": "Repeat PRESS after re-shim", "target": "Cho_Cr", "cost_min": 4.1, "sigma_m": 0.050,
     "expected_qc": "PASS", "removes": ["broad line (shim)", "low SNR"],
     "tests_hypotheses": ["shim / linewidth broadening", "low SNR"]},
    {"name": "PRESS with 2x averages (no re-shim)", "target": "Cho_Cr", "cost_min": 4.3, "sigma_m": 0.042,
     "expected_qc": "WARN", "removes": ["part of the noise"], "tests_hypotheses": ["low SNR"]},
    {"name": "Phantom + frequency calibration", "target": "Cho_Cr", "cost_min": 10.0, "sigma_m": None,
     "expected_qc": None, "removes": [], "tests_hypotheses": ["scanner calibration / frequency drift"]},
    {"name": "Repeat T1w + registration check", "target": "roi_volume", "cost_min": 6.0, "sigma_m": None,
     "expected_qc": None, "removes": [], "tests_hypotheses": ["registration / mask-propagation artifact"]},
    {"name": "Registration + segmentation audit (offline, no scanner time)", "target": "roi_volume",
     "cost_min": 0.0, "sigma_m": None, "expected_qc": None, "removes": [],
     "tests_hypotheses": ["registration / mask-propagation artifact", "segmentation version change"]},
]

# A PASS-quality repeat after re-shimming (dossier §7.6) — used for the "expected repeat range" prediction.
PREDICTION_SIGMA_NEXT = {"Cho_Cr": 0.050, "NAA_Cr": 0.060}

DISCLAIMER = ("Educational prototype on SIMULATED data. Not a clinical statement, not a diagnosis, "
              "not a medical device.")
