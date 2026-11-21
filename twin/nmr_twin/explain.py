"""Competing explanations: for every changed variable, which reasons could explain the change, and what the
evidence says about each. The twin does not pick a winner automatically; it shows the evidence and names the
measurement that would tell the explanations apart (dossier §3.6, §8.6).

Every verdict is computed from ALL accepted evidence for the variable (baseline, follow-up, repeats), not only
from the newest packet. Example: after a clean repeat, "shim broadening" is judged by whether the value fell back
toward baseline once the line was narrow again.

Verdict words: supported, possible, unlikely, not supported, cannot be excluded, investigate (model disagreement).
"""
from __future__ import annotations

from . import config
from .twin import Twin

# Declared QC limits used to describe the evidence (they mirror the StarterPack thresholds "WARN > 10 Hz" and
# "WARN < 25"; the packet's own per-check status is used first when it is present).
LW_WARN_HZ = 10.0
SNR_WARN = 25.0
REG_NOTE_MM = 1.0
PPM_CHO, PPM_CR = 3.20, 3.03


# ---------------- evidence helpers (also used by planner.py) ----------------

def flags_of(ev: dict | None) -> list[str]:
    """Event flags. Older saved states have no "flags" key, so fall back to the discrepancy boolean."""
    if not ev:
        return []
    if "flags" in ev:
        return list(ev.get("flags") or [])
    return ["model_disagreement"] if ev.get("discrepancy") else []


def applied_events(twin: Twin, name: str) -> list[dict]:
    """Every accepted event for one variable, oldest first (initialize + updates; rejects excluded)."""
    return [e for e in twin.events if e.get("observable") == name and e.get("type") != "reject"]


def latest_update(twin: Twin, name: str) -> dict | None:
    return next((e for e in reversed(applied_events(twin, name)) if "change_test" in e), None)


def _check(packet: dict | None, name: str, field: str = "value"):
    for c in (packet or {}).get("qc_checks", []) or []:
        if isinstance(c, dict) and c.get("name") == name:
            return c.get(field)
    return None


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _series(twin: Twin, name: str) -> list[dict]:
    out = []
    for e in applied_events(twin, name):
        p = twin.packets.get(e.get("packet_id")) or {}
        acq = p.get("acquisition_context") or {}
        out.append({
            "event": e, "packet": p, "pid": e.get("packet_id"), "session": e.get("session_id") or p.get("session_id"),
            "y": (e.get("evidence") or {}).get("y", (e.get("posterior") or {}).get("mean")),
            "qc": e.get("qc_status"), "z": (e.get("change_test") or {}).get("z"),
            "significant": (e.get("change_test") or {}).get("significant", False),
            "lw": _num(_check(p, "mrs_linewidth_Hz")), "lw_status": _check(p, "mrs_linewidth_Hz", "status"),
            "snr": _num(_check(p, "mrs_snr")), "snr_status": _check(p, "mrs_snr", "status"),
            "reg": _num(_check(p, "registration_rms_mm")),
            "cal": p.get("calibration_id"), "sysqc": p.get("system_qc_id"),
            "freq": _num(acq.get("spectrometer_frequency_MHz")),
            "version": (p.get("processing") or {}).get("version"),
        })
    return out


def _f(x, d=2):
    return "n/a" if x is None else f"{x:.{d}f}"


def _trail(series: list[dict], key: str, d: int = 1) -> str:
    return " → ".join(_f(s[key], d) for s in series)


def _lw_broad(s: dict) -> bool:
    if s["lw"] is None:
        return False
    return s["lw_status"] in ("WARN", "FAIL") if s["lw_status"] else s["lw"] > LW_WARN_HZ


def _snr_low(s: dict) -> bool:
    if s["snr"] is None:
        return False
    return s["snr_status"] in ("WARN", "FAIL") if s["snr_status"] else s["snr"] < SNR_WARN


def _fell_back(base: dict, bad: dict, latest: dict) -> bool:
    """A clean repeat that falls back toward baseline, with no significant change left."""
    if None in (base["y"], bad["y"], latest["y"]):
        return False
    return abs(latest["y"] - base["y"]) < abs(bad["y"] - base["y"]) and not latest["significant"]


# ---------------- explanations ----------------

def explanations(twin: Twin, name: str) -> dict | None:
    ev = latest_update(twin, name)
    if ev is None:
        return None
    series = _series(twin, name)
    base, latest = series[0], series[-1]
    ct = ev["change_test"]
    flags = flags_of(ev)
    disagree = "model_disagreement" in flags
    rows = []

    def row(hyp, verdict, evidence, test):
        rows.append({"hypothesis": hyp, "verdict": verdict, "evidence": evidence, "discriminating_test": test})

    earlier = [s for s in series[1:-1]]
    history = "; ".join(f"{s['pid']} ({s['qc']}) gave z = {_f(s['z'])}" for s in earlier)

    if disagree:
        row("Data or processing error in the newest packet", "investigate",
            f"The twin did not expect {latest['pid']}: surprise d² = {ev['d2']:.2f}, above the gate "
            f"{config.D2_GATE:.2f}. Its QC can pass and the value can still be wrong (wrong file, wrong fit, "
            "wrong subject). Investigate before trusting it.",
            "Re-run processing from the source file; then repeat the measurement.")

    if name in ("Cho_Cr", "NAA_Cr"):
        # ---- true change: latest z vs baseline, and the quality of the evidence behind it ----
        if disagree:
            verdict = "investigate"
        elif ct["significant"]:
            verdict = "supported" if ev["qc_status"] == "PASS" else "possible"
        else:
            verdict = "not supported"
        txt = (f"Newest value {_f(latest['y'])} vs baseline {_f(base['y'])}: z = {ct['z']:.2f}, limit "
               f"{ct['z_crit']:.2f}. It rests on {ev['qc_status']} evidence ({latest['pid']}).")
        if history:
            txt += f" Earlier: {history}."
        if any(s["significant"] for s in earlier) and not ct["significant"]:
            txt += " The apparent change did not survive the newest, cleaner evidence."
        if ct["significant"] and ev["qc_status"] != "PASS":
            txt += " The change is above the limit, but only on warned evidence."
        test = ("A clean repeat already tested it." if (ev["qc_status"] == "PASS" and earlier and not disagree)
                else "Repeat PRESS after re-shim: a real change survives a clean repeat.")
        row("True metabolic change", verdict, txt, test)

        # ---- shim / linewidth broadening ----
        if latest["lw"] is not None and base["lw"] is not None:
            sep_hz = (PPM_CHO - PPM_CR) * (latest["freq"] or base["freq"] or 123.25)
            physics = (f" Broad lines make Cho ({PPM_CHO:.2f} ppm) and Cr ({PPM_CR:.2f} ppm), only about "
                       f"{sep_hz:.0f} Hz apart, overlap, which can bias the ratio.")
            broad_before = [s for s in series[:-1] if _lw_broad(s)]
            trail = f"Linewidth {_trail(series, 'lw')} Hz (limit {LW_WARN_HZ:.0f} Hz)."
            if _lw_broad(latest):
                row("Shim / linewidth broadening", "supported",
                    trail + " The newest evidence still has broad lines, so the cause is present." + physics,
                    "Re-shim and repeat; check the fit residual between 3.0 and 3.3 ppm.")
            elif broad_before:
                bad = broad_before[-1]
                if _fell_back(base, bad, latest):
                    row("Shim / linewidth broadening", "supported",
                        trail + f" With a narrow line again, the value fell back from {_f(bad['y'])} to "
                        f"{_f(latest['y'])}, toward the baseline {_f(base['y'])} (z {_f(bad['z'])} → {_f(latest['z'])}). "
                        "This is what a shim effect predicts: the clean repeat resolved this explanation.",
                        "Done: the re-shimmed repeat answered this.")
                else:
                    row("Shim / linewidth broadening", "not supported",
                        trail + f" The line is narrow again, but the value stayed at {_f(latest['y'])} "
                        f"(z = {_f(latest['z'])}). Broad lines cannot explain a change that survives a narrow line.",
                        "Done: the re-shimmed repeat answered this.")
            else:
                row("Shim / linewidth broadening", "possible" if latest["lw"] > base["lw"] else "not supported",
                    trail + " The line was within the limit in every session." + physics,
                    "Check the fit residual between 3.0 and 3.3 ppm.")

        # ---- low SNR (random error, already part of the stated uncertainty) ----
        if latest["snr"] is not None and base["snr"] is not None:
            low_before = [s for s in series[:-1] if _snr_low(s)]
            trail = f"SNR {_trail(series, 'snr')} (limit {SNR_WARN:.0f}). Lower SNR means a larger random fit error."
            if _snr_low(latest):
                row("Low signal-to-noise (noise)", "supported", trail + " The newest evidence is still below the limit.",
                    "More averages or a re-shimmed repeat.")
            elif low_before:
                bad = low_before[-1]
                fell = _fell_back(base, bad, latest)
                row("Low signal-to-noise (noise)", "possible" if fell else "not supported",
                    trail + (f" The clean repeat (SNR {_f(latest['snr'], 1)}) agrees with baseline, so noise may have "
                             "contributed to the earlier value." if fell else
                             f" The clean repeat (SNR {_f(latest['snr'], 1)}) still shows the change, so noise does not explain it."),
                    "Done: the clean repeat answered this.")
            else:
                row("Low signal-to-noise (noise)", "possible" if latest["snr"] < base["snr"] else "not supported",
                    trail + " SNR was above the limit in every session.", "More averages.")

        # ---- voxel placement ----
        csde = ((latest["packet"].get("spatial_reference") or {}).get("csde_mm_NAA_Cho"))
        r1 = latest["reg"]
        row("Voxel placement / chemical-shift displacement", "possible" if (r1 or 0) > REG_NOTE_MM else "unlikely",
            f"Alignment error {_trail(series, 'reg')} mm (newest {_f(r1, 1)} mm). NAA and Cho voxels are offset by "
            f"{csde} mm in every session, so it mostly cancels. A 2 mm shift exchanges about 10 % of the 20 mm "
            "voxel's tissue.",
            "Repeat placement with auto-align; compare the voxel position on the anatomy.")

        _processing_row(row, series, "Processing / software difference",
                        "Re-run all sessions with the same pipeline version.")
        _calibration_row(row, series)

    elif name == "roi_volume":
        b_y = base["y"] or 0
        rel = ct["delta"] / b_y if b_y else 0
        dt = (ev.get("time_month") or 0) - (base["event"].get("time_month") or 0)
        plaus = config.STATE_VARIABLES["roi_volume"]["plausible_change_6mo_rel"]
        cons = next((f for f in ev["findings"] if f["check"] == "roi_u_consistency"), None)
        held = ev.get("K", 1) < 0.05
        row("True volume change", "investigate" if disagree else ("possible" if ct["significant"] else "not supported"),
            f"Change {rel:+.1%} in {dt:.0f} months; z = {ct['z']:.2f} with the honest uncertainty (limit "
            f"{ct['z_crit']:.2f}). A change above about {plaus:.0%} in six months is implausible for this region "
            "(teaching assumption)." + (f" The twin moved only {ev['K']:.1%} toward it." if held else "") +
            (f" Earlier: {history}." if history else ""),
            "Registration + segmentation audit.")
        row("Registration / mask-propagation artifact",
            "supported" if cons and cons["status"] == "WARN" else ("possible" if (latest["reg"] or 0) > REG_NOTE_MM else "unlikely"),
            (cons["message"] if cons else f"Alignment error {_trail(series, 'reg')} mm.") +
            " A rigid shift alone does not change a volume; pushing a mask through an imperfect registration does.",
            "Re-register and re-segment the follow-up independently.")
        _processing_row(row, series, "Segmentation version change", "Same segmentation version on all sessions.")

    summary = (f"Judged on {len(series)} accepted packets: " +
               ", ".join(f"{s['pid']} ({s['qc']})" for s in series) + ".")
    return {"variable": name, "event_id": ev["event_id"], "rows": rows, "flags": flags,
            "evidence_used": [s["pid"] for s in series], "summary": summary,
            "note": "Explanations are not mutually exclusive; the twin keeps a mixed explanation open."}


def _processing_row(row, series, hyp, test):
    versions = [s["version"] for s in series]
    distinct = list(dict.fromkeys(versions))
    if len(distinct) > 1:
        row(hyp, "possible", f"Pipeline version changed across packets: {' → '.join(str(v) for v in versions)}.", test)
    else:
        row(hyp, "not supported", f"Same pipeline version {distinct[0]} in all {len(series)} packets.", test)


def _calibration_row(row, series):
    by_session = {}
    for s in series:
        by_session.setdefault(s["session"], s)
    missing = [sess for sess, s in by_session.items() if not s["cal"]]
    records = ", ".join(f"{sess}: {s['cal']}" for sess, s in by_session.items() if s["cal"])
    freqs = [s["freq"] for s in by_session.values() if s["freq"] is not None]
    f0 = freqs[0] if freqs else None
    freq_moved = bool(f0) and any(abs(f - f0) / f0 > config.FREQ_MATCH_REL for f in freqs)
    freq_txt = (f"spectrometer frequency {' → '.join(_f(f, 2) for f in freqs)} MHz" if freqs
                else "no spectrometer frequency recorded")
    test = "Phantom + frequency calibration."
    if freq_moved:
        row("Scanner calibration / frequency drift", "possible",
            f"The {freq_txt} changed by more than {config.FREQ_MATCH_REL:.1%}. Phantom records: {records or 'none'}.", test)
    elif missing:
        row("Scanner calibration / frequency drift", "cannot be excluded",
            f"No phantom calibration record for {', '.join(str(m) for m in missing)}"
            + (f" (records exist for {records})" if records else "") + f"; {freq_txt}.", test)
    else:
        row("Scanner calibration / frequency drift", "unlikely",
            f"Every session has a phantom calibration record ({records}) and the same spectrometer frequency "
            f"({_f(f0, 2) if f0 else 'not recorded'} MHz). "
            "A record shows the phantom check was done; it does not prove there was no drift during the scan.",
            test + " Only needed if a doubt remains.")
