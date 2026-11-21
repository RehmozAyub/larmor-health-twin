"""Monte-Carlo test bench: simulated follow-up sessions with KNOWN truth, graded through the real checker and twin.

Why: on real data nobody knows the true Cho/Cr, so nobody can say whether the twin's 95 % intervals are honest.
Here we write the truth ourselves, perturb the measurement the way a scanner does (broad lines, noise, frequency
drift, voxel misplacement, protocol change), fit every spectrum like a real pipeline would, and send the packet
through the same checker and the same Kalman update the app uses. Then we count how often the twin was right.

Dossier links: §4.6 (CRLB), §4.8 (simulate spectra, vary linewidth and SNR, export ground truth separately),
§5.6 (repeatability), §7.5 (the WARN factor 2 is a declared, testable policy: "95 % intervals should cover the
known truth in about 95 % of cases"), Appendix C (synthetic cases and the instructor truth file).

Pipeline per case (all seeded, so case i of seed s is always the same):
  1. generator   synthetic FID, StarterPack convention s(t) = sum a_j exp(-pi LW t) exp(+i 2 pi f_j t),
                 f_j = (ppm_j - 4.65) nu0, 1024 points, dwell 0.5 ms. Extra realism the fitter does NOT model:
                 Gaussian shim broadening (Voigt line), frequency drift during the scan, tissue-mix bias.
  2. estimator   time-domain Lorentzian fit (common linewidth, phase, shift; scipy least squares).
                 Cho/Cr = A_Cho / A_Cr(3.03 ppm). Its SD is the Cramer-Rao bound from the Fisher matrix
                 J^T J / sigma^2, with sigma measured in the signal-free window (-3 to 0 ppm).
                 QC values are recomputed exactly as the StarterPack defines them (SNR, FWHM of NAA).
  3. packet      a schema-valid evidence packet (origin SIMULATED, value DERIVED), student-facing, no truth inside.
  4. twin        a fresh twin per case: StarterPack baseline ROI and NAA packets, a SIMULATED Cho/Cr baseline
                 (true 0.69, StarterPack baseline quality), then the follow-up packet. Real check_packet + Twin.
  5. grade       compare decision, posterior and z with the truth (kept in a separate truth file).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import norm

from . import config, explain
from .checker import check_packet
from .context import PackContext, load_context
from .service import new_twin

RESULTS_FILE = config.PROJECT_ROOT / "state" / "bench_results.json"
BENCH_VERSION = "1.1"
DEFAULT_SEED = 2026
DEFAULT_N = 250
MAX_N = 600

# ---- acquisition convention (StarterPack README) ----
N_POINTS = 1024
DWELL_S = 5e-4
NU0_3T = 123.25
NU0_15T = 63.87
PPM_REF = 4.65
T = np.arange(N_POINTS) * DWELL_S

# name, ppm, amplitude at TE 30 ms (calibrated on the StarterPack baseline FID), T2 in s (for the TE-change scenario)
LINES = [("NAA", 2.01, 1.00, 0.25), ("Cr", 3.03, 0.80, 0.16), ("Cho", 3.20, None, 0.22),
         ("mI", 3.56, 0.36, 0.20), ("Glx", 3.75, 0.04, 0.12), ("Cr CH2", 3.92, 0.55, 0.12)]
PPM = np.array([l[1] for l in LINES])
I_CR, I_CHO = 1, 2

BASELINE_TRUE = 0.69                      # true Cho/Cr at baseline (StarterPack baseline value)
CHANGES = [0.0, 0.05, 0.10, 0.16]         # true change at month 6
CHANGE_P = [0.40, 0.20, 0.20, 0.20]
BASELINE_COND = {"lw": 8.7, "snr": 31.2, "reg_rms": 0.7}
LORENTZ_INTRINSIC_HZ = 8.0                # T2* part of the line; extra width from a poor shim is Gaussian
TISSUE_BIAS_PER_MM = 0.018                # SD of the Cho/Cr shift per mm of voxel misplacement (dossier budget: 0.020 at 1.1 mm)
TE_LONG_S = 0.144
LEVELS = [0.50, 0.68, 0.80, 0.90, 0.95, 0.99]
FACTORS = [round(x, 2) for x in np.arange(1.0, 8.01, 0.25)]


# ============================ 1. generator ============================

def _voigt_gauss_fwhm(fwhm: float, lorentz: float) -> float:
    """Gaussian FWHM that, combined with a Lorentzian of width `lorentz`, gives a Voigt of total FWHM `fwhm`
    (Olivero-Longbothum approximation). Zero if the requested width is narrower than the Lorentzian part."""
    a = fwhm - 0.5346 * lorentz
    g2 = a * a - 0.2166 * lorentz * lorentz
    return math.sqrt(g2) if g2 > 0 else 0.0


def _envelope(lw_hz: float) -> np.ndarray:
    lor = min(LORENTZ_INTRINSIC_HZ, lw_hz)
    gau = _voigt_gauss_fwhm(lw_hz, lor)
    return np.exp(-math.pi * lor * T) * np.exp(-(math.pi * gau * T) ** 2 / (4 * math.log(2)))


def synth_fid(amps: np.ndarray, nu0: float, lw_hz: float, snr_ref: float, rng: np.random.Generator,
              shift_hz: float = 0.0, phase: float = 0.0, drift_hz: float = 0.0) -> tuple[np.ndarray, float]:
    """One averaged FID. Linewidth = total FWHM (Voigt: 8 Hz Lorentzian + Gaussian shim part).
    drift_hz: linear frequency drift across the averages (a lineshape error the Lorentzian fit cannot see).
    snr_ref: sets the NOISE LEVEL. It is the StarterPack SNR this acquisition would have at the reference
    linewidth (8.7 Hz). A broader line spreads the same signal over more hertz, so its peak, and its measured
    SNR, drop (8.7 Hz / SNR 31.2 -> 11.4 Hz / about 24, as in the StarterPack follow-up)."""
    osc_lines = np.exp(2j * math.pi * np.outer(T, (PPM - PPM_REF) * nu0)) @ amps
    ref = np.fft.fftshift(np.fft.fft(_envelope(BASELINE_COND["lw"]) * osc_lines))
    ppm = PPM_REF + np.fft.fftshift(np.fft.fftfreq(N_POINTS, DWELL_S)) / nu0
    height = float(ref.real[(ppm >= 1.9) & (ppm <= 2.1)].max())
    sigma = height / (snr_ref * math.sqrt(N_POINTS))
    if drift_hz > 0:
        offs = np.linspace(-drift_hz / 2, drift_hz / 2, 16)
        drift = np.mean(np.exp(2j * math.pi * offs[:, None] * T[None, :]), axis=0)
    else:
        drift = 1.0
    clean = np.exp(1j * phase) * _envelope(lw_hz) * drift * np.exp(2j * math.pi * shift_hz * T) * osc_lines
    noise = rng.normal(0, sigma, N_POINTS) + 1j * rng.normal(0, sigma, N_POINTS)
    return clean + noise, sigma


# ============================ 2. estimator ============================

@lru_cache(maxsize=8)
def _osc(nu0: float) -> np.ndarray:
    return np.exp(2j * math.pi * np.outer(T, (PPM - PPM_REF) * nu0))


def _basis(nu0: float, lw: float, shift: float) -> np.ndarray:
    return _osc(nu0) * np.exp((-math.pi * lw + 2j * math.pi * shift) * T)[:, None]


def _model(p: np.ndarray, nu0: float) -> np.ndarray:
    A, phi, lw, sh = p[:6], p[6], p[7], p[8]
    return np.exp(1j * phi) * (_basis(nu0, lw, sh) @ A)


def _jac(p: np.ndarray, nu0: float) -> np.ndarray:
    A, phi, lw, sh = p[:6], p[6], p[7], p[8]
    E = np.exp(1j * phi) * _basis(nu0, lw, sh)
    s = E @ A
    cols = np.column_stack([E, 1j * s, -math.pi * T * s, 2j * math.pi * T * s])
    return np.vstack([cols.real, cols.imag])


def spectrum_of(fid: np.ndarray, nu0: float, phase: float = 0.0, zero_fill: int = 1) -> tuple[np.ndarray, np.ndarray]:
    n = N_POINTS * zero_fill
    spec = np.fft.fftshift(np.fft.fft(fid * np.exp(-1j * phase), n))
    ppm = PPM_REF + np.fft.fftshift(np.fft.fftfreq(n, DWELL_S)) / nu0
    return ppm, spec


def fit_spectrum(fid: np.ndarray, nu0: float) -> dict:
    """Lorentzian time-domain fit + CRLB + StarterPack QC values (SNR and NAA FWHM, on the phased spectrum)."""
    # start: grid over linewidth and shift with linear complex amplitudes
    def trial(lw, sh):
        B = _basis(nu0, lw, sh)
        Bh = B.conj().T
        c = np.linalg.solve(Bh @ B, Bh @ fid)          # linear amplitudes for this width and shift
        return float(np.sum(np.abs(fid - B @ c) ** 2)), lw, sh, c

    best = min((trial(10.0, sh) for sh in np.arange(-8.0, 8.01, 2.0)), key=lambda x: x[0])
    best = min([best] + [trial(lw, best[2] + d) for lw, d in ((10.0, -1.0), (10.0, 1.0), (7.0, 0.0), (14.0, 0.0))],
               key=lambda x: x[0])
    _, lw0, sh0, c0 = best
    phi0 = float(np.angle(np.sum(c0 * np.abs(c0))))
    A0 = (c0 * np.exp(-1j * phi0)).real
    p0 = np.concatenate([A0, [phi0, lw0, sh0]])
    def resid(p):
        d = _model(p, nu0) - fid
        return np.concatenate([d.real, d.imag])

    res = least_squares(resid,
                        p0, jac=lambda p: _jac(p, nu0), method="lm", x_scale="jac", max_nfev=200)
    p = res.x
    if p[7] < 0:                         # a negative width is unphysical; keep the starting grid point instead
        p = p0
    phi = float(p[6])

    # noise SD per channel from the signal-free window, as in the SNR definition (sd_real_spectrum = sigma sqrt(N))
    ppm, spec = spectrum_of(fid, nu0, phi)
    noise_sd = float(spec.real[(ppm >= -3.0) & (ppm <= 0.0)].std())
    sigma = noise_sd / math.sqrt(N_POINTS)
    J = _jac(p, nu0)
    F = J.T @ J / sigma ** 2
    try:
        cov = np.linalg.inv(F)
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(F)
    a_cho, a_cr = p[I_CHO], p[I_CR]
    ratio = float(a_cho / a_cr)
    g = np.zeros(9)
    g[I_CHO], g[I_CR] = 1 / a_cr, -a_cho / a_cr ** 2
    crlb = float(math.sqrt(max(g @ cov @ g, 0.0)))

    naa = (ppm >= 1.9) & (ppm <= 2.1)
    snr = float(spec.real[naa].max() / noise_sd)
    fwhm = _naa_fwhm(fid, nu0, phi)
    return {"ratio": ratio, "crlb": crlb, "snr": snr, "fwhm": fwhm, "lw_fit": float(p[7]), "shift_fit": float(p[8]),
            "phase": phi, "params": p.tolist(), "sigma": sigma, "converged": bool(res.success)}


def _naa_fwhm(fid: np.ndarray, nu0: float, phase: float) -> float:
    """Full width at half maximum of the NAA peak in the phased real spectrum (4x zero-filled), in Hz."""
    ppm, spec = spectrum_of(fid, nu0, phase, zero_fill=4)
    hz = (ppm - PPM_REF) * nu0
    y = spec.real
    win = np.where((ppm >= 1.85) & (ppm <= 2.17))[0]
    k = win[np.argmax(y[win])]
    half = y[k] / 2
    i = k
    while i > 0 and y[i] > half:
        i -= 1
    j = k
    while j < len(y) - 1 and y[j] > half:
        j += 1
    left = hz[i] + (half - y[i]) * (hz[i + 1] - hz[i]) / (y[i + 1] - y[i])
    right = hz[j - 1] + (half - y[j - 1]) * (hz[j] - hz[j - 1]) / (y[j] - y[j - 1])
    return float(right - left)


# ============================ scenario draw ============================

def draw_case(seed: int, i: int) -> dict:
    """The hidden truth and perturbations of case i (instructor side). Pure function of (seed, i)."""
    rng = np.random.default_rng([seed, i, 1])
    change = float(rng.choice(CHANGES, p=CHANGE_P))
    good = rng.random() < 0.40
    lw = float(rng.uniform(8.0, 10.0) if good else rng.uniform(8.7, 16.0))
    snr = float(rng.uniform(28.0, 40.0) if good else rng.uniform(14.0, 38.0))   # noise level, as SNR at 8.7 Hz
    u = rng.random()
    reg = float(rng.uniform(0.3, 2.0) if u < 0.75 else rng.uniform(2.0, 3.0) if u < 0.93 else rng.uniform(3.0, 3.6))
    drift = float(rng.uniform(2.0, 8.0)) if rng.random() < 0.30 else 0.0
    proto_u = rng.random()
    protocol = "TE144" if proto_u < 0.07 else "1.5T" if proto_u < 0.14 else "same"
    return {"case": i, "true_baseline": BASELINE_TRUE, "true_change": change, "true_followup": BASELINE_TRUE + change,
            "lw_hz": lw, "snr_target": snr, "reg_rms_mm": reg,
            "tissue_bias": float(rng.normal(0, TISSUE_BIAS_PER_MM * reg)),
            "baseline_tissue_bias": float(rng.normal(0, TISSUE_BIAS_PER_MM * BASELINE_COND["reg_rms"])),
            "drift_hz": drift, "shift_hz": float(rng.normal(0, 1.5)), "phase": float(rng.uniform(-0.5, 0.5)),
            "protocol": protocol, "quality_tier": "good" if good else "degraded"}


def _amps(ratio_in_voxel: float, te_s: float) -> np.ndarray:
    a = np.array([l[2] if l[2] is not None else 0.0 for l in LINES])
    a[I_CHO] = a[I_CR] * ratio_in_voxel
    t2 = np.array([l[3] for l in LINES])
    return a * np.exp(-(te_s - 0.03) / t2)


def simulate(truth: dict, session: str, seed: int) -> dict:
    """Generate and fit one spectrum for the baseline ('t0') or follow-up ('t1') session of a case."""
    i = truth["case"]
    rng = np.random.default_rng([seed, i, 2 if session == "t0" else 3])
    if session == "t0":
        nu0, te, lw, snr, drift = NU0_3T, 0.03, BASELINE_COND["lw"], BASELINE_COND["snr"], 0.0
        in_voxel = truth["true_baseline"] + truth["baseline_tissue_bias"]
        shift, phase = float(rng.normal(0, 1.5)), float(rng.uniform(-0.5, 0.5))
    else:
        nu0 = NU0_15T if truth["protocol"] == "1.5T" else NU0_3T
        te = TE_LONG_S if truth["protocol"] == "TE144" else 0.03
        lw, snr, drift = truth["lw_hz"], truth["snr_target"], truth["drift_hz"]
        if truth["protocol"] == "1.5T":
            lw *= NU0_15T / NU0_3T          # shim quality is a width in ppm; in Hz it halves at half the field
        in_voxel = truth["true_followup"] + truth["tissue_bias"]
        shift, phase = truth["shift_hz"], truth["phase"]
    amps = _amps(in_voxel, te)
    fid, sigma_true = synth_fid(amps, nu0, lw, snr, rng, shift, phase, drift)
    fit = fit_spectrum(fid, nu0)
    apparent = float(amps[I_CHO] / amps[I_CR])            # the ratio actually present in the spectrum
    return {"fid": fid, "nu0": nu0, "te": te, "fit": fit, "apparent_ratio": apparent, "in_voxel_ratio": in_voxel,
            "sigma_true": sigma_true, "sha256": hashlib.sha256(fid.astype(np.complex64).tobytes()).hexdigest()}


# ============================ 3. packets ============================

@lru_cache(maxsize=4)
def _template(root: str) -> dict:
    return json.loads((Path(root) / "05_TwinReady_JSON_CSV" / "packets" / "E-t1-cho.json").read_text(encoding="utf-8"))


def _gate(ctx: PackContext, name: str, value: float, nu0: float = NU0_3T) -> tuple[str, str]:
    g = dict(ctx.gates[name])
    if name == "mrs_linewidth_Hz" and abs(nu0 - NU0_3T) / NU0_3T > 0.05:   # same limits in ppm at another field
        for k in ("warn_above", "fail_above"):
            if k in g:
                g[k] = round(g[k] * nu0 / NU0_3T, 2)
    status = "PASS"
    if ("warn_above" in g and value > g["warn_above"]) or ("warn_below" in g and value < g["warn_below"]):
        status = "WARN"
    if ("fail_above" in g and value > g["fail_above"]) or ("fail_below" in g and value < g["fail_below"]):
        status = "FAIL"
    parts = [f"{s} {g[k]}" for k, s in (("warn_above", "WARN >"), ("warn_below", "WARN <"),
                                        ("fail_above", "FAIL >"), ("fail_below", "FAIL <")) if k in g]
    return status, "; ".join(parts)


def packet_uncertainty(crlb: float, reg_rms: float, mode: str) -> tuple[float, str]:
    """The SD the producer writes into the packet.
    'budget': CRLB combined with a voxel-placement term (0.018 per mm of registration error; the dossier budget
              gives 0.020 at 1.1 mm). Lineshape and drift error are left OUT on purpose: covering them is the job
              the WARN factor claims to do (dossier §7.5), so the bench can test that claim.
    'crlb':   the fit's Cramer-Rao bound alone (what many pipelines report)."""
    if mode == "crlb":
        return crlb, "fit covariance (CRLB) only"
    return math.sqrt(crlb ** 2 + (TISSUE_BIAS_PER_MM * reg_rms) ** 2), "CRLB + voxel placement (0.018 x registration RMS)"


def build_packet(ctx: PackContext, seed: int, truth: dict, sim: dict, session: str, mode: str = "budget") -> dict:
    """Student-facing evidence packet: what a producing pipeline would send. No truth inside."""
    p = copy.deepcopy(_template(str(ctx.root)))
    i = truth["case"]
    t1 = session == "t1"
    fit = sim["fit"]
    pid = f"E-{session}-sim_s{seed}_c{i:04d}"
    src = f"simulated/bench/seed-{seed}/case-{i:04d}/{session}_svs.fid"
    ses = "ses-followup" if t1 else "ses-baseline"
    reg = truth["reg_rms_mm"] if t1 else BASELINE_COND["reg_rms"]
    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    checks = []
    for name, val, unit, owner in (("mrs_snr", round(fit["snr"], 1), "1", "QE"),
                                   ("mrs_linewidth_Hz", round(fit["fwhm"], 1), "Hz", "PM"),
                                   ("registration_rms_mm", round(reg, 2), "mm", "PM"),
                                   ("missing_values", 0, "1", "DS")):
        st, txt = _gate(ctx, name, val, sim["nu0"])
        checks.append({"name": name, "value": val, "unit": unit, "threshold": txt, "status": st, "owner": owner})
    proto_change = t1 and truth["protocol"] != "same"
    u_val, u_ref = packet_uncertainty(fit["crlb"], reg, mode)
    status = max((c["status"] for c in checks), key=rank.get)
    if proto_change and status == "PASS":
        status = "WARN"
    reasons = [f"{c['name']} {c['value']} ({c['threshold']})" for c in checks if c["status"] != "PASS"]
    if proto_change:
        reasons.append("protocol differs from baseline")
    acq = dict(p["acquisition_context"])
    if t1 and truth["protocol"] == "1.5T":
        acq.update(field_strength_T=1.5, spectrometer_frequency_MHz=NU0_15T)
    if t1 and truth["protocol"] == "TE144":
        acq.update(TE_s=TE_LONG_S)
    processing = {"pipeline": "nmr_twin.bench", "version": BENCH_VERSION,
                  "fit": "time-domain Lorentzian, common linewidth, shift and phase; ratio to the Cr CH3 singlet "
                         "(3.03 ppm); SD = Cramer-Rao bound from the Fisher matrix"}
    if t1 and truth["protocol"] == "1.5T":
        # Team decision: the field change is declared as harmonized (checker -> WARN, not FAIL). In this generator
        # Cho/Cr has no field dependence, so the ratio is trend-fit; real data would need a field-specific check.
        processing["harmonization"] = {"method": "ratio to Cr at the same TE; linewidth gate kept in ppm",
                                       "fit_for_trend": True, "raw_value": round(fit["ratio"], 4)}
    p.update({
        "packet_id": pid, "session_id": ses, "relative_time": {"value": 6 if t1 else 0, "unit": "month"},
        "system_qc_id": f"sysqc-sim-s{seed}", "calibration_id": "phantom-sim",
        "protocol_match": not proto_change, "comparable": True,
        "interpretation_limit": "SIMULATED test-bench spectrum; frontal VOI only; Cr assumed stable; no clinical meaning",
        "value": round(fit["ratio"], 4), "value_epistemic": "DERIVED", "origin": "SIMULATED",
        "source_object": src, "source_sha256": sim["sha256"],
        "uncertainty": {"type": "SD", "value": round(max(u_val, 1e-4), 4), "budget_ref": u_ref},
        "qc_checks": checks, "qc_status": status, "qc_reasons": reasons, "acquisition_context": acq,
        "processing": processing,
        "provenance": {"parents": [src], "activities": ["synthetic FID generation (nmr_twin.bench)", "spectral fit",
                                                        "ratio to Cr", "QC aggregation"]},
        "twin_action": {"recommended": {"PASS": "update", "WARN": "update_with_warning", "FAIL": "reject"}[status],
                        "reason": "computed by the bench pipeline from its own QC checks"},
    })
    return p


# ============================ 4. twin ============================

def _base_twin(ctx: PackContext):
    """A fresh, empty twin with the team policy. Each case gets its own: the simulated Cho/Cr baseline packet
    initializes it, the simulated follow-up updates it, so no duplicate or session rule can interfere."""
    return new_twin(ctx)


MODES = ("budget", "crlb")
CALLS = ("supported", "possible", "investigate", "not supported")


def _twin_call(twin) -> str:
    """What the twin itself says about a true change, read from its own explanation table (explain.py):
    supported = z beyond its limit on evidence that passed every check; possible = the same z on warned evidence;
    investigate = the surprise gate fired; not supported = z within its limit."""
    rows = explain.explanations(twin, "Cho_Cr")["rows"]
    return next(r["verdict"] for r in rows if r["hypothesis"] == "True metabolic change")


def _grade_row(ctx: PackContext, seed: int, truth: dict, s0: dict, s1: dict, base_twin, mode: str) -> dict:
    p0, p1 = build_packet(ctx, seed, truth, s0, "t0", mode), build_packet(ctx, seed, truth, s1, "t1", mode)
    twin = new_twin(ctx)
    twin.policy = copy.deepcopy(base_twin.policy)
    v0 = check_packet(p0, ctx, twin)
    twin.assimilate(v0)
    v1 = check_packet(p1, ctx, twin)
    e1 = twin.assimilate(v1)
    issues = sorted({f.check for f in v1.findings if f.status in ("WARN", "FAIL")})
    row = {
        "case": truth["case"], "packet_id": p1["packet_id"],
        "truth": {k: truth[k] for k in ("true_change", "true_followup", "protocol", "quality_tier", "tissue_bias", "drift_hz")},
        "lw_true": round(truth["lw_hz"], 3), "snr_target": round(truth["snr_target"], 2), "reg_rms": round(truth["reg_rms_mm"], 3),
        "apparent_ratio": s1["apparent_ratio"],
        "y": p1["value"], "u_crlb": round(s1["fit"]["crlb"], 5), "u_stated": p1["uncertainty"]["value"], "u": v1.u_effective,
        "floor_applied": any(f.check == "uncertainty_floor" and f.status == "WARN" for f in v1.findings),
        "snr": p1["qc_checks"][0]["value"], "fwhm": p1["qc_checks"][1]["value"],
        "y0": p0["value"], "u0": v0.u_effective, "baseline_status": v0.status,
        "baseline_floor_applied": any(f.check == "uncertainty_floor" and f.status == "WARN" for f in v0.findings),
        "status": v1.status, "action": v1.action, "issues": issues, "event_type": e1["type"],
    }
    if e1["type"] != "reject":
        ct = e1["change_test"]
        row.update(post_mean=e1["posterior"]["mean"], post_sd=e1["posterior"]["sd"], d2=e1["d2"], K=e1["K"],
                   z=ct["z"], z_crit=ct["z_crit"], R_factor=e1["evidence"]["R_factor"],
                   prior_mean=e1["prior"]["mean_minus"], prior_var=e1["prior"]["var_minus"], call=_twin_call(twin))
    else:
        row["reject_reason"] = e1.get("reason", "")
    return {"row": row, "packets": [p0, p1], "verdict": v1}


def run_case(ctx: PackContext, seed: int, i: int, base_twin, modes=MODES) -> dict:
    """Simulate and fit case i once, then grade it under each uncertainty mode on its own fresh twin."""
    truth = draw_case(seed, i)
    s0, s1 = simulate(truth, "t0", seed), simulate(truth, "t1", seed)
    graded = {m: _grade_row(ctx, seed, truth, s0, s1, base_twin, m) for m in modes}
    for g in graded.values():      # keep only plain data, so a case can travel between processes
        v = g.pop("verdict")
        g["source_warn"] = any(f.check == "source_hash" and f.status in ("WARN", "FAIL") for f in v.findings)
    return {"truth": truth, "modes": graded}


def _run_all(ctx: PackContext, seed: int, n: int) -> list[dict]:
    """Cases are independent and seeded by (seed, i): case i is the same whatever n is.
    (A process pool was tried; on this machine process start-up cost more than it saved.)"""
    base = _base_twin(ctx)
    return [run_case(ctx, seed, i, base) for i in range(n)]


# ============================ 5. grading ============================

def _frac(xs) -> float | None:
    xs = list(xs)
    return (sum(1 for x in xs if x) / len(xs)) if xs else None


def _covered(row: dict, level: float, factor_override: float | None = None) -> bool:
    zq = norm.ppf(0.5 + level / 2)
    return abs(row["post_mean"] - row["truth"]["true_followup"]) <= zq * row["post_sd"]


def _post_with_factor(row: dict, factor: float) -> tuple[float, float]:
    """Posterior the twin would report with a different WARN factor (same prior and packet, Eq. 7.1)."""
    R = row["u"] ** 2 * (factor if row["status"] == "WARN" else 1.0)
    P = row["prior_var"]
    K = P / (P + R)
    return row["prior_mean"] + K * (row["y"] - row["prior_mean"]), math.sqrt((1 - K) * P)


def _factor_stats(rows: list[dict], ref: str = "true_followup") -> dict:
    if not rows:
        return {"n": 0}
    r = np.array([(x["y"] - (x["truth"][ref] if ref in x["truth"] else x[ref])) / x["u"] for x in rows])
    return {"n": len(rows), "mean_sq": float(np.mean(r ** 2)),
            "k95": float((np.quantile(np.abs(r), 0.95) / 1.96) ** 2),
            "coverage_at_1": float(np.mean(np.abs(r) <= 1.96)), "coverage_at_2": float(np.mean(np.abs(r) <= 1.96 * math.sqrt(2)))}


def _spectral_only(row: dict) -> bool:
    """WARN caused only by spectral quality (SNR / linewidth), same protocol: what the factor 2 is meant for."""
    return row["status"] == "WARN" and row["truth"]["protocol"] == "same" and \
        set(row["issues"]) <= {"mrs_snr", "mrs_linewidth_Hz", "declared_qc_status", "qc_status_consistency"}


def summarize(rows: list[dict], declared: float) -> dict:
    acc = [r for r in rows if r["event_type"] != "reject"]
    rej = [r for r in rows if r["event_type"] == "reject"]
    by = {s: [r for r in acc if r["status"] == s] for s in ("PASS", "WARN")}
    same = [r for r in acc if r["truth"]["protocol"] == "same"]

    cov = {"levels": LEVELS,
           "all": [_frac(_covered(r, L) for r in acc) for L in LEVELS],
           "PASS": [_frac(_covered(r, L) for r in by["PASS"]) for L in LEVELS],
           "WARN": [_frac(_covered(r, L) for r in by["WARN"]) for L in LEVELS],
           "nochange": [_frac(_covered(r, L) for r in acc if r["truth"]["true_change"] == 0) for L in LEVELS]}
    ev_cov = {"levels": LEVELS}
    for key, grp in (("PASS", by["PASS"]), ("WARN", by["WARN"])):
        ev_cov[key] = [_frac(abs(r["y"] - r["truth"]["true_followup"]) <= norm.ppf(0.5 + L / 2) * r["u"]
                             * math.sqrt(r["R_factor"]) for r in grp) for L in LEVELS]

    # (c) the WARN factor the data supports
    spectral = [r for r in acc if _spectral_only(r)]
    calib = {
        "PASS": _factor_stats(by["PASS"]),
        "WARN_spectral": _factor_stats(spectral),
        "WARN_registration": _factor_stats([r for r in by["WARN"] if "registration_rms_mm" in r["issues"] and r["truth"]["protocol"] == "same"]),
        "WARN_field": _factor_stats([r for r in by["WARN"] if r["truth"]["protocol"] == "1.5T"]),
        "WARN_echo_time": _factor_stats([r for r in by["WARN"] if r["truth"]["protocol"] == "TE144"]),
        "WARN_all": _factor_stats(by["WARN"]),
        "floor_applied": _factor_stats([r for r in acc if r["floor_applied"]]),
    }
    fitted = calib["WARN_spectral"].get("k95") or calib["WARN_all"].get("k95") or declared
    fitted = round(float(fitted), 2)
    factor_curve = {"factors": FACTORS}
    for key, grp in (("PASS", by["PASS"]), ("WARN_spectral", spectral), ("WARN_all", by["WARN"])):
        r = np.array([abs(x["y"] - x["truth"]["true_followup"]) / x["u"] for x in grp]) if grp else np.array([])
        factor_curve[key] = [float(np.mean(r <= 1.96 * math.sqrt(f))) if r.size else None for f in FACTORS]

    # (d) CRLB vs actual error by linewidth (same protocol, so a TE bias does not hide the lineshape effect)
    bins = [(8.0, 10.0), (10.0, 12.0), (12.0, 14.0), (14.0, 16.0)]
    lw_rows = []
    for lo, hi in bins:
        g = [r for r in same if lo <= r["lw_true"] < hi or (hi == 16.0 and r["lw_true"] == 16.0)]
        if not g:
            continue
        crlb = math.sqrt(np.mean([r["u_crlb"] ** 2 for r in g]))
        fit_err = math.sqrt(np.mean([(r["y"] - r["apparent_ratio"]) ** 2 for r in g]))
        tot_err = math.sqrt(np.mean([(r["y"] - r["truth"]["true_followup"]) ** 2 for r in g]))
        lw_rows.append({"lo": lo, "hi": hi, "n": len(g), "crlb_rms": crlb, "fit_err_rms": fit_err, "total_err_rms": tot_err,
                        "fit_ratio": (fit_err / crlb) ** 2, "total_ratio": (tot_err / crlb) ** 2,
                        "points": [[r["lw_true"], r["u_crlb"], abs(r["y"] - r["apparent_ratio"])] for r in g]})

    # (b) decisions vs truth
    table = []
    for ch in CHANGES:
        g = [r for r in rows if abs(r["truth"]["true_change"] - ch) < 1e-9]
        a = [r for r in g if r["event_type"] != "reject"]
        sig = [r for r in a if abs(r["z"]) > r["z_crit"]]
        table.append({"true_change": ch, "n": len(g), "rejected": len(g) - len(a), "flagged": len(sig),
                      "calls": {c: len([r for r in a if r["call"] == c]) for c in CALLS},
                      "rate_supported": (len([r for r in a if r["call"] == "supported"]) / len(a)) if a else None,
                      "not_flagged": len(a) - len(sig), "rate_flagged": (len(sig) / len(a)) if a else None,
                      "by_status": {s: {"n": len([r for r in a if r["status"] == s]),
                                        "flagged": len([r for r in sig if r["status"] == s])} for s in ("PASS", "WARN")}})
    null = [r for r in acc if r["truth"]["true_change"] == 0]
    alt = [r for r in acc if r["truth"]["true_change"] != 0]

    def z_policy(r):  # z if the change test also used the policy variance (a suggestion, not what the twin does)
        return (r["y"] - r["y0"]) / math.sqrt(r["u0"] ** 2 + r["R_factor"] * r["u"] ** 2)

    def z_fitted(r):
        f = fitted if r["status"] == "WARN" else 1.0
        return (r["y"] - r["y0"]) / math.sqrt(r["u0"] ** 2 + f * r["u"] ** 2)

    decisions = {
        "false_alarm": _frac(abs(r["z"]) > r["z_crit"] for r in null),
        "false_alarm_PASS": _frac(abs(r["z"]) > r["z_crit"] for r in null if r["status"] == "PASS"),
        "false_alarm_WARN": _frac(abs(r["z"]) > r["z_crit"] for r in null if r["status"] == "WARN"),
        "miss": _frac(abs(r["z"]) <= r["z_crit"] for r in alt),
        "false_alarm_policy_z": _frac(abs(z_policy(r)) > r["z_crit"] for r in null),
        "miss_policy_z": _frac(abs(z_policy(r)) <= r["z_crit"] for r in alt),
        "false_alarm_fitted_z": _frac(abs(z_fitted(r)) > r["z_crit"] for r in null),
        "miss_fitted_z": _frac(abs(z_fitted(r)) <= r["z_crit"] for r in alt),
        # the twin's own words, not the raw z: it calls a change "supported" only on evidence that passed every check
        "false_alarm_supported": _frac(r["call"] == "supported" for r in null),
        "null_possible": _frac(r["call"] == "possible" for r in null),
        "null_investigate": _frac(r["call"] == "investigate" for r in null),
        "found_supported": _frac(r["call"] == "supported" for r in alt),
        "found_possible": _frac(r["call"] == "possible" for r in alt),
        "found_investigate": _frac(r["call"] == "investigate" for r in alt),
        "raw_z_alarms_null": sum(1 for r in null if abs(r["z"]) > r["z_crit"]),
        "raw_z_alarms_null_protocol_change": sum(1 for r in null if abs(r["z"]) > r["z_crit"] and r["truth"]["protocol"] != "same"),
        "d2_flag_rate_null": _frac(r["d2"] > config.D2_GATE for r in null),
        "d2_flag_rate_change": _frac(r["d2"] > config.D2_GATE for r in alt),
        "n_null": len(null), "n_change": len(alt),
    }

    def cov_with(f, grp):
        out = []
        for r in grp:
            m, s = _post_with_factor(r, f)
            out.append(abs(m - r["truth"]["true_followup"]) <= 1.96 * s)
        return _frac(out)

    counterfactual = {"factor": fitted,
                      "coverage95_WARN_declared": cov_with(declared, by["WARN"]),
                      "coverage95_WARN_fitted": cov_with(fitted, by["WARN"]),
                      "coverage95_all_declared": cov_with(declared, acc),
                      "coverage95_all_fitted": cov_with(fitted, acc),
                      "evidence95_WARN_spectral_declared": _frac(abs(r["y"] - r["truth"]["true_followup"]) <= 1.96 * math.sqrt(declared) * r["u"] for r in spectral),
                      "evidence95_WARN_spectral_fitted": _frac(abs(r["y"] - r["truth"]["true_followup"]) <= 1.96 * math.sqrt(fitted) * r["u"] for r in spectral)}

    i95 = LEVELS.index(0.95)
    by_change = [{"true_change": ch,
                  "n": len([r for r in acc if abs(r["truth"]["true_change"] - ch) < 1e-9]),
                  "coverage95": _frac(_covered(r, 0.95) for r in acc if abs(r["truth"]["true_change"] - ch) < 1e-9),
                  "d2_flag_rate": _frac(r["d2"] > config.D2_GATE for r in acc if abs(r["truth"]["true_change"] - ch) < 1e-9)}
                 for ch in CHANGES]
    by_gate = {"quiet": {"n": len([r for r in acc if r["d2"] <= config.D2_GATE]),
                         "coverage95": _frac(_covered(r, 0.95) for r in acc if r["d2"] <= config.D2_GATE)},
               "flagged": {"n": len([r for r in acc if r["d2"] > config.D2_GATE]),
                           "coverage95": _frac(_covered(r, 0.95) for r in acc if r["d2"] > config.D2_GATE)}}
    proto = {}
    for name in ("same", "1.5T", "TE144"):
        g = [r for r in acc if r["truth"]["protocol"] == name]
        proto[name] = {"n": len(g), "coverage95": _frac(_covered(r, 0.95) for r in g),
                       "mean_error": float(np.mean([r["y"] - r["truth"]["true_followup"] for r in g])) if g else None}
    return {
        "n": len(rows), "n_accepted": len(acc), "n_rejected": len(rej),
        "n_floor_applied": sum(1 for r in rows if r["floor_applied"]),
        "n_floor_applied_baseline": sum(1 for r in rows if r["baseline_floor_applied"]),
        "status_counts": {s: sum(1 for r in rows if r["status"] == s) for s in ("PASS", "WARN", "FAIL")},
        "reject_reasons": _count([c for r in rej for c in r["issues"] if c not in ("declared_qc_status", "qc_status_consistency")]),
        "warn_reasons": _count([c for r in by["WARN"] for c in r["issues"] if c not in ("declared_qc_status", "qc_status_consistency")]),
        "headline": {"evidence95": _frac(abs(r["y"] - r["truth"]["true_followup"]) <= 1.96 * r["u"] * math.sqrt(r["R_factor"]) for r in acc),
                     "evidence95_PASS": ev_cov["PASS"][i95], "evidence95_WARN": ev_cov["WARN"][i95],
                     "coverage95_nochange": by_change[0]["coverage95"],
                     "false_alarm_same_protocol": _frac(abs(r["z"]) > r["z_crit"] for r in null if r["truth"]["protocol"] == "same"),
                     "coverage95": cov["all"][i95], "coverage95_PASS": cov["PASS"][i95], "coverage95_WARN": cov["WARN"][i95],
                     "false_alarm": decisions["false_alarm"], "miss": decisions["miss"],
                     "false_alarm_supported": decisions["false_alarm_supported"],
                     "fitted_warn_factor": fitted, "declared_warn_factor": declared,
                     "fitted_warn_factor_mean_sq": calib["WARN_spectral"].get("mean_sq"),
                     "pass_factor": calib["PASS"].get("k95")},
        "coverage": cov, "evidence_coverage": ev_cov, "calibration": calib, "factor_curve": factor_curve,
        "crlb_by_linewidth": lw_rows, "decision_table": table, "decisions": decisions,
        "counterfactual": counterfactual, "by_protocol": proto, "coverage_by_change": by_change, "coverage_by_gate": by_gate,
    }


def _count(items: list[str]) -> dict:
    out: dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _example(ctx: PackContext, seed: int, rows: list[dict]) -> dict | None:
    """One simulated follow-up close to the StarterPack follow-up conditions (11.4 Hz, SNR 24.8), with its fit."""
    cands = [r for r in rows if r["truth"]["protocol"] == "same" and r["event_type"] != "reject" and r["truth"]["drift_hz"] == 0]
    if not cands:
        return None
    r = min(cands, key=lambda r: ((r["lw_true"] - 11.4) / 2) ** 2 + ((r["snr"] - 24.8) / 5) ** 2)
    truth = draw_case(seed, r["case"])
    sim = simulate(truth, "t1", seed)
    fit = sim["fit"]
    p = np.array(fit["params"])
    model = _model(p, sim["nu0"])
    ppm, sd = spectrum_of(sim["fid"], sim["nu0"], fit["phase"], zero_fill=2)
    _, sm = spectrum_of(model, sim["nu0"], fit["phase"], zero_fill=2)
    keep = (ppm >= 1.7) & (ppm <= 4.2)
    parts = {}
    for j, (name, *_rest) in enumerate(LINES):
        q = np.zeros(9)
        q[j], q[6:] = p[j], p[6:]
        _, sj = spectrum_of(_model(q, sim["nu0"]), sim["nu0"], fit["phase"], zero_fill=2)
        if name in ("Cr", "Cho"):
            parts[name] = np.round(sj.real[keep], 3).tolist()
    return {"case": r["case"], "packet_id": r["packet_id"], "ppm": np.round(ppm[keep], 4).tolist(),
            "data": np.round(sd.real[keep], 3).tolist(), "fit": np.round(sm.real[keep], 3).tolist(),
            "residual": np.round((sd - sm).real[keep], 3).tolist(), "components": parts,
            "lw_true": r["lw_true"], "fwhm": r["fwhm"], "snr": r["snr"], "y": r["y"], "u": r["u"],
            "true_followup": r["truth"]["true_followup"], "apparent_ratio": r["apparent_ratio"], "status": r["status"],
            "peaks": [{"name": n, "ppm": q} for n, q, *_ in LINES]}


def _truth_entry(seed: int, out: dict) -> dict:
    """Instructor truth-file entry (dossier Appendix C.6 shape)."""
    t = out["truth"]
    pert = [f"linewidth {t['lw_hz']:.1f} Hz", f"noise level: SNR {t['snr_target']:.1f} at 8.7 Hz",
            f"registration {t['reg_rms_mm']:.2f} mm (tissue-mix bias {t['tissue_bias']:+.3f})"]
    if t["drift_hz"]:
        pert.append(f"frequency drift {t['drift_hz']:.1f} Hz during the scan")
    if t["protocol"] != "same":
        pert.append({"TE144": "TE 30 -> 144 ms (T2 weighting changes Cho/Cr)", "1.5T": "field 3 T -> 1.5 T"}[t["protocol"]])
    return {"case": f"bench-s{seed}-c{t['case']:04d}", "packets": [p["packet_id"] for p in out["modes"]["budget"]["packets"]],
            "features": {"Cho_Cr": {"true_baseline": t["true_baseline"], "true_followup": round(t["true_followup"], 4),
                                    "true_change": t["true_change"], "perturbations": pert,
                                    "expected_change_call": "change" if t["true_change"] else "no change"}}}


def run(seed: int = DEFAULT_SEED, n: int = DEFAULT_N, ctx: PackContext | None = None, save: bool = True) -> dict:
    n = int(max(1, min(n, MAX_N)))
    ctx = ctx or load_context()
    t0 = time.perf_counter()
    base = _base_twin(ctx)
    declared = float(base.policy["WARN"]["R_factor"])
    outs = _run_all(ctx, seed, n)
    rows = {m: [o["modes"][m]["row"] for o in outs] for m in MODES}
    summaries = {m: summarize(rows[m], declared) for m in MODES}
    source_warns = sum(1 for o in outs for m in MODES if o["modes"][m]["source_warn"])
    result = {
        "bench_version": BENCH_VERSION, "seed": seed, "n": n,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime_s": None,
        "origin": "SIMULATED",
        "setup": {
            "baseline_true": BASELINE_TRUE, "changes": CHANGES, "change_p": CHANGE_P, "baseline_conditions": BASELINE_COND,
            "linewidth_range_hz": [8.0, 16.0], "snr_at_8p7Hz_range": [14.0, 40.0], "registration_range_mm": [0.3, 3.6],
            "drift_share": 0.30, "protocol_share": {"TE144": 0.07, "1.5T": 0.07},
            "tissue_bias_per_mm": TISSUE_BIAS_PER_MM, "lorentz_intrinsic_hz": LORENTZ_INTRINSIC_HZ,
            "nu0_MHz": NU0_3T, "points": N_POINTS, "dwell_s": DWELL_S,
            "declared_warn_factor": declared, "z_crit": config.Z_CRIT_PRIMARY, "d2_gate": config.D2_GATE,
            "modes": {"budget": "packet SD = CRLB combined with a voxel-placement term (0.018 x registration RMS)",
                      "crlb": "packet SD = Cramer-Rao bound of the Lorentzian fit only"},
            "default_mode": "budget",
            "harmonization": "1.5 T follow-ups declare processing.harmonization (checker: WARN instead of FAIL)",
            "source_warn_count": source_warns,
        },
        "summary": summaries["budget"],
        "summaries": summaries,
        "example": _example(ctx, seed, rows["budget"]),
        "cases": rows["budget"],
        "cases_crlb": rows["crlb"],
        "truth_file": {"starterpack_version": "0.3", "generator": f"nmr_twin.bench {BENCH_VERSION}", "seed": seed,
                       "note": "Instructor side. Keep apart from the packets: the packets carry no truth.",
                       "cases": [_truth_entry(seed, o) for o in outs]},
        "packets": [p for o in outs for p in o["modes"]["budget"]["packets"]],
    }
    result["runtime_s"] = round(time.perf_counter() - t0, 2)
    if save:
        RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_FILE.write_text(json.dumps(result, separators=(",", ":"), default=_json_default), encoding="utf-8")
    return json.loads(json.dumps(result, default=_json_default))


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


def load_cached() -> dict | None:
    if not RESULTS_FILE.exists():
        return None
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


if __name__ == "__main__":  # py -m nmr_twin.bench [seed] [n]
    import sys
    s = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    k = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_N
    r = run(s, k)
    for m in MODES:
        sm = r["summaries"][m]
        print(m, json.dumps({"headline": sm["headline"], "status": sm["status_counts"], "floor": [sm["n_floor_applied"], sm["n_floor_applied_baseline"]],
                             "calib": {k: [v.get("n"), round(v.get("k95") or 0, 2), round(v.get("mean_sq") or 0, 2)] for k, v in sm["calibration"].items()},
                             "dec": sm["decisions"], "by_change": sm["coverage_by_change"], "gate": sm["coverage_by_gate"],
                             "cf": sm["counterfactual"], "proto": sm["by_protocol"]}, indent=None))
    print(json.dumps({"runtime_s": r["runtime_s"], "headline": r["summary"]["headline"],
                      "status": r["summary"]["status_counts"], "calibration": r["summary"]["calibration"],
                      "decisions": r["summary"]["decisions"], "lw": [{k: v for k, v in x.items() if k != "points"} for x in r["summary"]["crlb_by_linewidth"]],
                      "proto": r["summary"]["by_protocol"], "cf": r["summary"]["counterfactual"],
                      "source_warn": r["setup"]["source_warn_count"]}, indent=1))
