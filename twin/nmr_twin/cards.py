"""Measurement card (Quantum Engineering) and uncertainty card (Precision Mechanics / Metrology) for Cho/Cr."""
from __future__ import annotations

import math

MEASUREMENT_CARD = {
    "variable": "Cho_Cr",
    "name": "Choline-to-creatine ratio",
    "unit": "1 (dimensionless)",
    "physical_meaning": ("Ratio of two peak areas in a ¹H spectrum of one 20 mm cube of frontal tissue: choline "
                         "(3.20 ppm, cell-membrane turnover) over creatine (3.03 ppm, energy metabolism, assumed stable)."),
    "how_measured": "PRESS single-voxel spectroscopy, TE 30 ms, TR 2 s, 64 averages, 123.25 MHz (B0 = 2.895 T; label 3 T).",
    "chain": ["¹H spins precess at 123.25 MHz (MEASURED: FID)",
              "Fourier transform → spectrum (DERIVED)",
              "Lorentzian fit of Cho and Cr peaks → amplitudes (DERIVED)",
              "Ratio Cho/Cr (DERIVED)",
              "Twin belief about the metabolic state (INFERRED)"],
    "why_a_ratio": "Coil sensitivity and voxel size cancel in a ratio; linewidth, relaxation and tissue mix do not.",
    "spatial_support": "VOI centre (-16, 45, 6) mm RAS, 20 × 20 × 20 mm; Cho and NAA voxels offset by 2.4 mm (chemical-shift displacement).",
    "quality_indicators": ["SNR (≥ 25)", "linewidth FWHM (≤ 10 Hz)", "registration RMS (≤ 2 mm)", "fit uncertainty (CRLB)"],
    "valid_range": [0, 3],
    "cannot_tell": ["absolute concentrations (needs a water reference and tissue correction)",
                    "anything outside the voxel",
                    "a diagnosis (this is synthetic teaching data)"],
    "failure_modes": ["broad lines make Cho and Cr overlap (only ~21 Hz apart)", "low SNR",
                      "voxel placed on different tissue", "Cr not actually stable"],
    "validation": "Synthetic spectra with known amplitudes (StarterPack v0.3 FIDs).",
    "epistemic": "FID MEASURED-level (origin SIMULATED here); ratio DERIVED; twin state INFERRED",
}

# Dossier Appendix D / Figure 12: teaching budget for the follow-up Cho/Cr ratio.
UNCERTAINTY_BUDGET = [
    {"source": "Spectral fit (CRLB at 11.4 Hz, SNR 24.8)", "u": 0.045, "how": "fit covariance / CRLB",
     "fix": "better shim, more averages"},
    {"source": "Lineshape / frequency-drift model error", "u": 0.025, "how": "residual shape, drift estimate",
     "fix": "re-shim, drift correction"},
    {"source": "Voxel placement / partial volume", "u": 0.020, "how": "registration residual",
     "fix": "fixture, auto-align"},
    {"source": "Chemical-shift displacement", "u": 0.015, "how": "Eq. (5.1)", "fix": "higher-bandwidth pulses, sLASER"},
    {"source": "Frequency / RF calibration", "u": 0.010, "how": "phantom, reference scan", "fix": "calibration before session"},
]


def budget() -> dict:
    total_var = sum(r["u"] ** 2 for r in UNCERTAINTY_BUDGET)
    rows = [{**r, "share": r["u"] ** 2 / total_var} for r in UNCERTAINTY_BUDGET]
    dominant = max(rows, key=lambda r: r["share"])
    return {"variable": "Cho_Cr", "session": "ses-followup", "rows": rows, "u_combined": math.sqrt(total_var),
            "u_packet": 0.06, "dominant": dominant["source"], "dominant_share": dominant["share"],
            "rule": "u_c = sqrt(sum of u_i^2) for independent sources (GUM)",
            "lesson": "The fit term carries ~60 % of the variance, so the cheapest improvement is to re-shim and repeat."}
