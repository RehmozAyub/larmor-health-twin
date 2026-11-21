"""Prediction (what do we expect next?) and next-measurement ranking (what should we measure next?).

Dossier §7.6: expected repeat range if nothing changes = x+ ± 1.96 sqrt(P+ + R_next).
Dossier §7.7, Eq. 7.3: after a new unbiased measurement with SD sigma_m, P++ = (1/P+ + 1/R)^-1;
rank actions by (P+ - P++) / cost. When the competing explanation is a *bias* (shim, voxel shift, calibration),
an action that tells the explanations apart is worth doing even with zero variance gain.

The recommendation is computed from the current state. For every variable the planner asks four questions:
  1. Is a model-disagreement flag open (the newest value surprised the twin, d² above the gate)?
  2. Was the newest evidence WARN, so the cause of the warning is still in the data the twin relies on?
  3. Is the variable held (the newest evidence barely moved the belief, K < 5 %), pending an audit?
  4. Is the posterior SD still above the declared "good enough" target?
A variable with any "yes" is open; the recommended actions are the ones that close those items.
If nothing is open, the planner says so: no further measurement is needed for these variables right now.
"""
from __future__ import annotations

import copy
import math

from . import config
from .explain import explanations, flags_of, latest_update
from .twin import Twin

# ---- Declared "good enough" targets (team choice, teaching assumption; shown in the app) ----
# Smallest change we want to be able to see. Target SD = half of it, so a change of that size would sit two SDs
# away from the belief, about the 1.96 limit of the change test.
SMALLEST_CHANGE = {"Cho_Cr": 0.08,      # about 12 % of the 0.69 baseline; 2.7 x the six-month drift (0.03)
                   "NAA_Cr": 0.12}      # about 10 % of the 1.25 baseline
SMALLEST_CHANGE_REL = {"roi_volume": config.STATE_VARIABLES["roi_volume"]["plausible_change_6mo_rel"]}  # 5 %
TARGET_SD_FRACTION = 0.5
HELD_K = 0.05                           # an update that moved the belief less than 5 % = evidence held
PRIORITY = {"model_disagreement": 0, "warn_cause_present": 1, "evidence_held": 2, "above_target_sd": 3}
CODE_TEXT = {"model_disagreement": "model disagreement", "warn_cause_present": "warning cause",
             "evidence_held": "held pending an audit", "above_target_sd": "SD above target",
             "calibration_doubt": "calibration doubt"}
MRS_VARS = ("Cho_Cr", "NAA_Cr")
REPEAT = "Repeat PRESS after re-shim"
AUDIT = "Registration + segmentation audit (offline, no scanner time)"


def _label(name: str) -> str:
    return config.STATE_VARIABLES.get(name, {}).get("label", name)


def _f(x, d=3):
    if x is None:
        return "n/a"
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.{d}f}"


def prediction(twin: Twin, name: str) -> dict | None:
    var = twin.variables.get(name)
    sig = config.PREDICTION_SIGMA_NEXT.get(name)
    if var is None or sig is None:
        return None
    half = 1.96 * math.sqrt(var.var + sig ** 2)
    return {"variable": name, "mean": var.mean, "low": var.mean - half, "high": var.mean + half, "sigma_next": sig,
            "assumes": f"nothing changes, and the repeat is PASS quality (SD {sig}) after re-shimming",
            "epistemic": "INFERRED"}


def target_sd(twin: Twin, name: str) -> dict | None:
    """The declared 'good enough' posterior SD for one variable, with its reason."""
    var = twin.variables.get(name)
    if var is None:
        return None
    if name in SMALLEST_CHANGE:
        delta = SMALLEST_CHANGE[name]
        why = f"half the smallest change worth seeing ({delta:g})"
    elif name in SMALLEST_CHANGE_REL:
        rel = SMALLEST_CHANGE_REL[name]
        delta = rel * abs(var.baseline.get("y", var.mean))
        why = f"half the smallest change worth seeing ({rel:.0%} of baseline = {_f(delta)})"
    else:
        return None
    return {"value": TARGET_SD_FRACTION * delta, "smallest_change": delta, "why": why}


# ---------------- per-variable assessment ----------------

def assess(twin: Twin, name: str) -> dict:
    """What is still open for one variable, computed from its evidence and its current belief."""
    var = twin.variables[name]
    lab = _label(name)
    tgt = target_sd(twin, name)
    out = {"variable": name, "label": lab, "sd": var.sd, "target_sd": tgt["value"] if tgt else None,
           "target_why": tgt["why"] if tgt else None, "open": [], "state": "settled", "summary": ""}
    ev = latest_update(twin, name)
    if ev is None:
        out.update(state="baseline_only",
                   summary=f"{lab}: only baseline evidence so far. There is no change to test yet.")
        return out
    ct = ev["change_test"]
    flags = flags_of(ev)
    precise = tgt is None or var.sd <= tgt["value"]
    warn = ev.get("qc_status") == "WARN"
    held = ev.get("K", 1) < HELD_K
    causes = [f for f in ev.get("findings", []) if f.get("status") == "WARN" and f.get("check") != "declared_qc_status"]
    cause_txt = "; ".join(f["message"].rstrip(".") for f in causes) or "the producer declared WARN"
    out["latest"] = {"event_id": ev["event_id"], "packet_id": ev["packet_id"], "qc_status": ev.get("qc_status"),
                     "z": ct["z"], "z_crit": ct["z_crit"], "significant": ct["significant"], "d2": ev.get("d2"),
                     "K": ev.get("K"), "flags": flags, "y": (ev.get("evidence") or {}).get("y")}
    sd_txt = (f"SD {_f(var.sd)}, {'below' if precise else 'above'} the target {_f(tgt['value'])}" if tgt
              else f"SD {_f(var.sd)}")

    def add(code, text):
        out["open"].append({"code": code, "priority": PRIORITY[code], "variable": name, "text": text})

    if "model_disagreement" in flags:
        add("model_disagreement",
            f"{lab}: model disagreement. The twin did not expect {ev['packet_id']} "
            f"(d² = {ev['d2']:.2f}, gate {config.D2_GATE:.2f}). Investigate before trusting it.")
    if warn and not held and (ct["significant"] or not precise):
        add("warn_cause_present",
            f"{lab}: the newest evidence ({ev['packet_id']}) passed with warnings, so the cause is still in the data "
            f"({cause_txt}). The change z = {ct['z']:.2f} rests on it.")
    if held:
        add("evidence_held",
            f"{lab}: held pending an audit. The newest evidence moved the belief only {ev['K']:.1%} because its honest "
            f"uncertainty is large ({cause_txt}).")
    if not precise:
        add("above_target_sd", f"{lab}: {sd_txt}. The belief is not yet precise enough.")

    if out["open"]:
        out["state"] = "open"
        out["summary"] = " ".join(o["text"] for o in out["open"])
        out["short"] = f"{lab}: open ({', '.join(CODE_TEXT[o['code']] for o in out['open'])})."
    elif ct["significant"]:
        out["short"] = f"{lab}: change supported by clean evidence."
        out["summary"] = (f"{lab}: the change is supported by clean evidence (z = {ct['z']:.2f}, limit "
                          f"{ct['z_crit']:.2f}; {sd_txt}). The twin needs no more data to say this. "
                          "What it means is outside the twin.")
    elif warn:
        out["state"] = "watch"
        out["short"] = f"{lab}: no change seen; newest evidence was WARN, so keep watching."
        out["summary"] = (f"{lab}: consistent with no change (z = {ct['z']:.2f}, limit {ct['z_crit']:.2f}) and "
                          f"{sd_txt}. Its newest evidence was WARN, so a re-shimmed repeat spectrum would refresh it, "
                          "but it does not need a measurement of its own.")
    else:
        resolved = _resolved_shim(twin, name)
        out["short"] = (f"{lab}: consistent with no change" +
                        ("; the clean repeat resolved the shim explanation." if resolved else " on clean evidence."))
        out["summary"] = (f"{lab}: consistent with no change on clean evidence (z = {ct['z']:.2f}, limit "
                          f"{ct['z_crit']:.2f}; {sd_txt})." + (" The clean repeat resolved the shim explanation."
                                                               if resolved else ""))
    return out


def _resolved_shim(twin: Twin, name: str) -> bool:
    ex = explanations(twin, name)
    return bool(ex) and any(r["hypothesis"].startswith("Shim") and r["discriminating_test"].startswith("Done")
                            for r in ex["rows"])


def assess_all(twin: Twin) -> list[dict]:
    order = [config.PRIMARY_VARIABLE] + [n for n in config.STATE_VARIABLES if n != config.PRIMARY_VARIABLE]
    return [assess(twin, n) for n in order if n in twin.variables]


def _calibration_doubt(twin: Twin, name: str) -> bool:
    ex = explanations(twin, name)
    return bool(ex) and any(r["hypothesis"].startswith("Scanner calibration") and
                            r["verdict"] in ("possible", "cannot be excluded", "supported") for r in ex["rows"])


# ---------------- ranking ----------------

def rank_next_measurements(twin: Twin) -> list[dict]:
    """Candidates sorted: first those that close an open item (most urgent item first), then by variance gained per
    scanner minute (Eq. 7.3), then by cost. Each row says whether it is needed now, and why."""
    assessed = {a["variable"]: a for a in assess_all(twin)}
    out = []
    for c in config.NEXT_MEASUREMENTS:
        var = twin.variables.get(c["target"])
        row = {**c, "sd_now": var.sd if var else None, "sd_after": None, "gain_per_min": None}
        if var is not None and c["sigma_m"] is not None:
            factor = twin.policy.get(c["expected_qc"] or "PASS", {}).get("R_factor", 1.0)
            R = factor * c["sigma_m"] ** 2
            P_after = 1 / (1 / var.var + 1 / R)
            row["sd_after"] = math.sqrt(P_after)
            row["gain_per_min"] = (var.var - P_after) / c["cost_min"] if c["cost_min"] > 0 else None
        a = assessed.get(c["target"])
        is_cal = c["name"].startswith("Phantom")
        if a is None:
            items, why = [], f"No evidence for {_label(c['target'])} yet."
        elif is_cal:
            doubt = _calibration_doubt(twin, c["target"])
            items = [{"code": "calibration_doubt", "priority": 4}] if doubt else []
            why = ("A calibration doubt is open for this variable." if doubt else
                   "Not needed now: every session has a phantom calibration record at the same frequency.")
        else:
            items = a["open"]
            if c["target"] in MRS_VARS and not any("shim" in r for r in c.get("removes", [])):
                items = [o for o in items if o["code"] != "warn_cause_present"]   # it does not remove the shim cause
            why = (f"Closes for {a['label']}: " + ", ".join(CODE_TEXT[o["code"]] for o in items) + "."
                   if items else f"Not needed now. {a['summary']}")
        row["needed_now"] = bool(items)
        row["addresses"] = [o["code"] for o in items]
        row["priority"] = min((o["priority"] for o in items), default=99)
        row["relevance"] = why
        out.append(row)
    out.sort(key=lambda r: (not r["needed_now"], r["priority"], -(r["gain_per_min"] or 0), r["cost_min"]))
    return out


# ---------------- recommendation ----------------

def _actions(twin: Twin, assessed: list[dict], ranked: list[dict]) -> list[dict]:
    """Turn the open items into at most one action per measurement, most urgent first."""
    by_name = {r["name"]: r for r in ranked}
    acts: dict[str, dict] = {}

    def put(action, prio, why, variable, codes):
        a = acts.setdefault(action, {"action": action, "priority": prio, "why": [], "variables": [], "closes": []})
        a["priority"] = min(a["priority"], prio)
        a["why"].append(why)
        a["variables"].append(variable)
        a["closes"] += codes

    for a in assessed:
        if a["state"] != "open":
            continue
        name, lab, lat = a["variable"], a["label"], a["latest"]
        codes = [o["code"] for o in a["open"]]
        prio = min(o["priority"] for o in a["open"])
        base_y = twin.variables[name].baseline.get("y")
        if name in MRS_VARS:
            rep = by_name.get(REPEAT, {})
            gain = (f" It also shrinks the {lab} SD from {_f(rep['sd_now'])} to {_f(rep['sd_after'])} "
                    f"(target {_f(a['target_sd'])})." if rep.get("sd_after") and rep.get("target") == name else "")
            if "model_disagreement" in codes:
                put(f"Check packet {lat['packet_id']} (source file and processing), then repeat PRESS after re-shim", prio,
                    f"The twin did not expect {lab} = {_f(lat['y'], 2)} (d² = {lat['d2']:.2f}, gate "
                    f"{config.D2_GATE:.2f}). Its QC passed, so look for a wrong file, fit or subject first. Then a clean "
                    f"repeat shows whether the value is real: it should land near {_f(lat['y'], 2)} again if it is.",
                    name, codes)
            elif "warn_cause_present" in codes:
                put(REPEAT, prio,
                    f"The newest {lab} evidence passed with warnings, and the repeat removes the cause (broad line, "
                    f"low SNR). If {lab} falls back toward {_f(base_y, 2)} after re-shimming, the change was a "
                    f"measurement effect; if it stays near {_f(lat['y'], 2)}, the change becomes believable." + gain,
                    name, codes)
            else:
                put(REPEAT, prio, f"{lab} is not yet precise enough ({a['summary'].split(': ', 1)[-1]})" + gain,
                    name, codes)
        else:
            put(AUDIT, prio,
                f"The {lab} evidence barely moved the twin (K = {lat['K']:.1%}) because its honest uncertainty is "
                f"large. Only an audit of the mask propagation can tell a real volume change from a processing "
                f"artifact. It costs no scanner time." if "evidence_held" in codes else
                f"{lab} is not yet precise enough (SD {_f(a['sd'])}, target {_f(a['target_sd'])}). The audit checks the "
                "processing behind it before more scanning.", name, codes)
    out = sorted(acts.values(), key=lambda a: (a["priority"], a["action"]))
    return [{"action": a["action"], "why": " ".join(a["why"]), "variables": a["variables"], "closes": a["closes"]}
            for a in out]


def _state_before_last(twin: Twin) -> Twin | None:
    """A copy of the twin as it was before the newest event (the math is undone from the logged prior)."""
    if not twin.events:
        return None
    t = copy.deepcopy(twin)
    ev = t.events.pop()
    obs = ev.get("observable")
    if ev.get("type") == "initialize":
        t.variables.pop(obs, None)
    elif ev.get("type") != "reject" and obs in t.variables and ev.get("prior"):
        v = t.variables[obs]
        v.mean, v.var = ev["prior"]["mean"], ev["prior"]["var"]
        v.time_month = (ev.get("time_month") or v.time_month) - (ev["prior"].get("dt_month") or 0)
        if v.packet_ids and v.packet_ids[-1] == ev.get("packet_id"):
            v.packet_ids.pop()
            v.sessions.pop()
    return t


def _open_keys(assessed: list[dict]) -> dict[tuple, str]:
    return {(o["variable"], o["code"]): f"{_label(o['variable'])} {CODE_TEXT[o['code']]}"
            for a in assessed for o in a["open"]}


def _since_last(twin: Twin, assessed: list[dict], actions: list[dict]) -> dict | None:
    if not twin.events:
        return None
    ev = twin.events[-1]
    before = _state_before_last(twin)
    b_assessed = assess_all(before) if before else []
    b_actions = [a["action"] for a in _actions(before, b_assessed, rank_next_measurements(before))] if before else []
    now_k, was_k = _open_keys(assessed), _open_keys(b_assessed)
    closed = [was_k[k] for k in was_k if k not in now_k]
    opened = [now_k[k] for k in now_k if k not in was_k]
    still = [now_k[k] for k in now_k if k in was_k]
    lab = _label(ev.get("observable") or "")
    if ev["type"] == "reject":
        text = (f"Newest evidence {ev.get('packet_id') or '(no id)'} was rejected, so the twin did not change "
                "and neither did the recommendation.")
    elif ev["type"] == "initialize":
        text = f"Newest evidence {ev['packet_id']} ({ev['qc_status']}) set the starting belief for {lab}."
    else:
        text = (f"Newest evidence {ev['packet_id']} ({ev['qc_status']}) moved {lab} from "
                f"{_f(ev['prior']['mean'])} ± {_f(math.sqrt(ev['prior']['var']))} to "
                f"{_f(ev['posterior']['mean'])} ± {_f(ev['posterior']['sd'])}.")
        if "model_disagreement" in flags_of(ev):
            text += " It raised a model-disagreement flag."
    if ev["type"] != "reject":
        if closed:
            text += " Closed: " + ", ".join(closed) + "."
        if opened:
            text += " Newly open: " + ", ".join(opened) + "."
        if not closed and not opened:
            text += " The open items did not change."
        now_actions = [a["action"] for a in actions]
        if now_actions != b_actions:
            text += " The recommendation changed."
    return {"event_id": ev["event_id"], "packet_id": ev.get("packet_id"), "observable": ev.get("observable"),
            "type": ev["type"], "flags": flags_of(ev), "closed": closed, "opened": opened, "still_open": still,
            "text": text}


def recommendation(twin: Twin) -> dict:
    ranked = rank_next_measurements(twin)
    assessed = assess_all(twin)
    items = _actions(twin, assessed, ranked)
    open_flags = [{"variable": a["variable"], "flag": f, "event_id": a["latest"]["event_id"],
                   "packet_id": a["latest"]["packet_id"],
                   "text": f"{a['label']}: the twin did not expect {a['latest']['packet_id']} "
                           f"(d² = {a['latest']['d2']:.2f}, gate {config.D2_GATE:.2f}). Investigate before trusting it."}
                  for a in assessed if a.get("latest") for f in a["latest"]["flags"]]
    if not assessed:
        summary = "No evidence yet. Ingest the baseline first."
    elif all(a["state"] == "baseline_only" for a in assessed):
        summary = "Only baseline evidence so far. There is no change to test yet. Ingest the follow-up."
    elif not items:
        summary = "Nothing is open: no further measurement needed for these variables right now."
    else:
        opened = [f"{a['label']} ({', '.join(CODE_TEXT[o['code']] for o in a['open'])})"
                  for a in sorted(assessed, key=lambda a: min((o["priority"] for o in a["open"]), default=99))
                  if a["state"] == "open"]
        summary = f"Still open: {'; '.join(opened)}. " + " ".join(
            a.get("short", a["summary"]) for a in assessed if a["state"] not in ("open", "baseline_only"))
    return {"recommended": items, "ranked": ranked, "summary": summary.strip(), "open_flags": open_flags,
            "variables": assessed, "since_last": _since_last(twin, assessed, items),
            "targets": {a["variable"]: {"target_sd": a["target_sd"], "why": a["target_why"]} for a in assessed},
            "principle": "Choose evidence, not treatment: the twin advises what to measure next; it does not diagnose."}
