"""The packet checker: reads any evidence packet and decides update / update_with_warning / reject, with reasons.

It works in six layers (findings.LAYERS). Each check produces a Finding with an owner track.
Principles (dossier §1.9, §5.8, §8.2; CTU lecture):
  * never crash on bad input — a broken packet is a FAIL with a reason, not an exception;
  * never strengthen a claim — the effective status is the worst of the declared status and every recomputed check;
  * never repair evidence silently — missing stays missing; a lookup that adds information is labelled as such.

Hardening rules for unseen packets (constants and reasons in config.py):
  * field_vs_baseline: a different field than the baseline is FAIL unless processing.harmonization is declared
    (then WARN), dossier §5.8 + §6.5; the linewidth gate keeps the 3 T limits in ppm at other fields;
  * uncertainty_floor: a stated u below a declared teaching floor is WARN and the floor is carried forward (§5.8);
  * source_hash WARN when the file is not held and no hash is given; provenance_parents FAIL when no parent (§6.7);
  * evidence_scope: calibration / phantom evidence belongs to the scanner's record, not the subject's twin (§5.3);
  * reprocessed_evidence: same session + observable with a new pipeline version would supersede, needs a replay.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Protocol

import jsonschema

from . import config
from .context import PackContext, file_sha256
from .findings import RANK, Finding, worst

UNIT_TO_MONTH = {"month": 1.0, "year": 12.0, "week": 7 / 30.4375, "day": 1 / 30.4375, "s": 1 / (86400 * 30.4375)}
ACTIONS = {"PASS": "update", "WARN": "update_with_warning", "FAIL": "reject"}


class TwinView(Protocol):
    """What the checker needs to know about the twin (kept small so the checker can run without one)."""
    subject_id: str

    def has_packet(self, packet_id: str) -> bool: ...
    def used_session(self, observable: str, session_id: str) -> bool: ...
    def current_time(self, observable: str) -> float | None: ...
    def baseline_packet(self, observable: str) -> dict | None: ...


@dataclass
class Verdict:
    packet: dict | None
    findings: list[Finding] = field(default_factory=list)
    status: str = "FAIL"
    action: str = "reject"
    value: float | None = None
    u_stated: float | None = None
    u_effective: float | None = None       # the SD the twin uses for the gate (may be larger than stated)
    time_month: float | None = None
    observable: str | None = None
    packet_id: str | None = None
    headline: str = ""

    def to_dict(self) -> dict:
        return {k: (v if k != "findings" else [f.to_dict() for f in v]) for k, v in self.__dict__.items()}


def _num(x: Any) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and abs(x) < 1e300
    except OverflowError:  # an integer too large for a float is not a usable measurement
        return False


def _reject_constant(name: str):
    raise ValueError(f"{name} is not a valid JSON number")


def _finite_float(text: str) -> float:
    x = float(text)
    if not math.isfinite(x):
        raise ValueError(f"the number {text[:20]} is too large to be a measurement")
    return x


def _gate_status(gate: dict, value: float) -> str:
    if "fail_above" in gate and value > gate["fail_above"]:
        return "FAIL"
    if "fail_below" in gate and value < gate["fail_below"]:
        return "FAIL"
    if "warn_above" in gate and value > gate["warn_above"]:
        return "WARN"
    if "warn_below" in gate and value < gate["warn_below"]:
        return "WARN"
    return "PASS"


def _gate_text(gate: dict) -> str:
    parts = []
    for key, sym in (("warn_above", "WARN >"), ("warn_below", "WARN <"), ("fail_above", "FAIL >"), ("fail_below", "FAIL <")):
        if key in gate:
            parts.append(f"{sym} {gate[key]}")
    return "; ".join(parts) or gate.get("rule", "")


def check_packet(raw: str | dict, ctx: PackContext, twin: TwinView | None = None) -> Verdict:
    """Check one packet. Whatever it contains, the answer is a verdict: an unexpected structure is rejected with a
    reason instead of raising, so a hostile packet can never take the twin down."""
    try:
        return _check_packet(raw, ctx, twin)
    except Exception as e:  # last line of defence; the specific checks below should catch everything first
        v = Verdict(packet=None)
        v.findings.append(Finding(
            "parse", "unreadable_packet", "FAIL", "DS",
            f"The packet has a structure the contract does not allow ({type(e).__name__}), so it cannot be checked. "
            "It is rejected and the twin is unchanged."))
        return _finish(v)


def _check_packet(raw: str | dict, ctx: PackContext, twin: TwinView | None = None) -> Verdict:
    v = Verdict(packet=None)
    F = v.findings
    add = lambda *a, **k: F.append(Finding(*a, **k))  # noqa: E731

    # ---------------- 1. parse ----------------
    if isinstance(raw, dict):
        p = raw
        add("parse", "json_parse", "PASS", "DS", "Packet given as a parsed object.")
    else:
        try:
            # NaN, Infinity and overflowing numbers are not JSON and not measurements: refuse them at the door.
            p = json.loads(raw, parse_constant=_reject_constant, parse_float=_finite_float)
        except RecursionError:
            add("parse", "json_parse", "FAIL", "DS", "The JSON is nested too deeply to be an evidence packet. Nothing else can be checked.")
            return _finish(v)
        except (ValueError, TypeError) as e:  # JSONDecodeError is a ValueError
            add("parse", "json_parse", "FAIL", "DS", f"The text is not valid JSON ({e}). Nothing else can be checked.")
            return _finish(v)
        if not isinstance(p, dict):
            add("parse", "json_parse", "FAIL", "DS", "The JSON is not an object (expected {...}).")
            return _finish(v)
        add("parse", "json_parse", "PASS", "DS", "Valid JSON.")
    v.packet = p
    v.packet_id = p.get("packet_id") if isinstance(p.get("packet_id"), str) else None
    v.observable = p.get("observable") if isinstance(p.get("observable"), str) else None

    # ---------------- 2. schema ----------------
    validator = jsonschema.Draft202012Validator(ctx.schema)
    errors = sorted(validator.iter_errors(p), key=lambda e: list(e.absolute_path))
    for e in errors:
        where = "/".join(str(x) for x in e.absolute_path) or "(top level)"
        add("schema", "schema", "FAIL", "DS", f"{where}: {e.message}")
    if not errors:
        add("schema", "schema", "PASS", "DS", "All 22 required fields present with valid types (schema v1.0).")

    obs = v.observable
    model = config.STATE_VARIABLES.get(obs) if obs else None
    value = p.get("value")
    is_cal = _is_calibration(p)
    unc = p.get("uncertainty") if isinstance(p.get("uncertainty"), dict) else {}

    # ---------------- 3. semantic ----------------
    if value is None:
        add("semantic", "missing_value", "FAIL", "DS", "The measured value is missing (null). Missing stays missing; it is never set to zero.")
    elif not _num(value):
        add("semantic", "value_type", "FAIL", "DS", f"The value {value!r} is not a number.")
    else:
        v.value = float(value)
        rng = p.get("valid_range")
        if isinstance(rng, list) and len(rng) == 2 and all(_num(x) for x in rng):
            ok = rng[0] <= value <= rng[1]
            add("semantic", "valid_range", "PASS" if ok else "FAIL", "QE",
                f"Value {value} is {'inside' if ok else 'OUTSIDE'} the declared valid range {rng}.", value, str(rng))
        else:
            add("semantic", "valid_range", "WARN", "QE", "No valid range declared, so the value cannot be range-checked.")

    u_type, u_val = unc.get("type"), unc.get("value")
    if u_val is None:
        add("semantic", "missing_uncertainty", "FAIL", "PM", "No uncertainty given. The contract requires an uncertainty for every value used in an update.")
    elif not _num(u_val) or u_val <= 0:
        add("semantic", "uncertainty_value", "FAIL", "PM", f"Uncertainty {u_val!r} is not a positive number, so the twin cannot weigh it.")
    elif u_type == "SD":
        v.u_stated = float(u_val)
        add("semantic", "uncertainty_value", "PASS", "PM", f"Standard uncertainty (SD) = {u_val}.")
    elif u_type == "CI95":
        v.u_stated = float(u_val) / 1.96
        add("semantic", "uncertainty_value", "INFO", "PM", f"95 % half-width {u_val} converted to SD = {v.u_stated:.4g} (divide by 1.96).")
    elif u_type == "CRLB":
        v.u_stated = float(u_val)
        add("semantic", "uncertainty_value", "WARN", "QE", "Only a Cramér-Rao bound is given. It is a LOWER bound, so the real error is probably larger.")
    else:
        add("semantic", "uncertainty_value", "FAIL", "PM", f"Uncertainty type {u_type!r} gives no number the twin can use.")

    if model is not None:
        unit = p.get("unit")
        ok = unit == model["unit"]
        add("semantic", "unit", "PASS" if ok else "FAIL", "DS",
            f"Unit '{unit}' {'matches' if ok else 'does not match'} the expected unit '{model['unit']}' for {obs}."
            + ("" if ok else " Units are never converted silently."), unit, model["unit"])
        mod = p.get("modality") if isinstance(p.get("modality"), str) else None
        if mod not in model["modalities"] and not is_cal:  # calibration packets get one clear reason in linkage
            add("semantic", "modality", "FAIL", "QE", f"{obs} cannot be measured with modality '{mod}' (expected {sorted(model['modalities'])}).")

    if p.get("origin") == "SIMULATED" and p.get("value_epistemic") == "MEASURED":
        add("semantic", "epistemic_label", "FAIL", "DS", "Simulated data are labelled MEASURED. Simulated values must never be shown as measured.")
    elif p.get("origin") in ("SIMULATED", "MEASURED"):
        add("semantic", "epistemic_label", "PASS", "DS", f"Origin {p.get('origin')}, value {p.get('value_epistemic')}: labels are consistent.")

    checks = p.get("qc_checks") if isinstance(p.get("qc_checks"), list) else []
    declared = p.get("qc_status") if isinstance(p.get("qc_status"), str) else None
    worst_declared_check = worst(c.get("status") for c in checks if isinstance(c, dict))
    if declared in RANK and RANK[declared] < RANK[worst_declared_check]:
        add("semantic", "qc_status_consistency", worst_declared_check, "Shared",
            f"Packet says {declared}, but its own worst check is {worst_declared_check}. We use {worst_declared_check} (a claim is never strengthened).")
    elif declared in RANK:
        add("semantic", "qc_status_consistency", "PASS", "Shared", f"Declared status {declared} matches its own checks.")
    if declared in RANK:
        add("semantic", "declared_qc_status", declared if declared != "PASS" else "PASS", "Shared",
            f"Status declared by the producing pipeline: {declared}.")

    # ---------------- 4. linkage ----------------
    sub, ses = p.get("subject_id"), p.get("session_id")
    if is_cal:
        # Checked before the subject: a phantom is never in participants.tsv, and that would be the wrong reason.
        add("linkage", "evidence_scope", "FAIL", "PM",
            f"This is calibration evidence ({is_cal}). It belongs to the scanner's own quality record "
            "(dossier §5.3, §11.3), not to a person's health twin. Use it as system QC for the sessions it covers.")
    elif isinstance(sub, str):
        if sub not in ctx.participants:
            add("linkage", "subject", "FAIL", "DS", f"Subject '{sub}' is not in participants.tsv.")
        elif twin is not None and sub != twin.subject_id:
            add("linkage", "subject", "FAIL", "DS", f"Packet is for '{sub}', but this twin represents '{twin.subject_id}'.")
        else:
            add("linkage", "subject", "PASS", "DS", f"Subject '{sub}' is registered.")
    if isinstance(sub, str) and isinstance(ses, str) and not is_cal:
        if ctx.session_time(sub, ses) is None:
            add("linkage", "session", "FAIL", "DS",
                f"Session '{ses}' is not in the sessions table. Register it (with its acquisition time) before its evidence can be used.")
        else:
            add("linkage", "session", "PASS", "DS", f"Session '{ses}' acquired {ctx.session_time(sub, ses):%Y-%m-%d}.")
            rt = p.get("relative_time") if isinstance(p.get("relative_time"), dict) else {}
            base_ses = next(iter(sorted(ctx.sessions.get(sub, {}).items(), key=lambda kv: kv[1])), (None,))[0]
            months = ctx.months_between(sub, base_ses, ses) if base_ses else None
            if _num(rt.get("value")) and rt.get("unit") in UNIT_TO_MONTH:
                v.time_month = rt["value"] * UNIT_TO_MONTH[rt["unit"]]
                if months is not None:
                    ok = abs(months - v.time_month) <= config.RELATIVE_TIME_TOL_MONTH
                    add("linkage", "relative_time", "PASS" if ok else "WARN", "DT",
                        f"Packet says month {v.time_month:.1f}; sessions table gives month {months:.1f}"
                        + ("." if ok else ". The times disagree, so time alignment is uncertain."))

    src, sha = p.get("source_object"), p.get("source_sha256")
    if isinstance(src, str) and src:
        path = ctx.root / src
        if path.is_file():
            actual = file_sha256(path)
            if sha:
                ok = actual == sha
                add("linkage", "source_hash", "PASS" if ok else "FAIL", "DS",
                    "SHA-256 of the source file matches the packet (the bytes are unchanged; this says nothing about the physics)."
                    if ok else "SHA-256 of the source file does NOT match the packet: the file changed or the packet points to the wrong file.",
                    extra={"actual": actual, "declared": sha})
            else:
                add("linkage", "source_hash", "INFO", "DS", "No hash in the packet; computed it from the file for the provenance trail.",
                    extra={"actual": actual})
            if src in ctx.manifest and ctx.manifest[src] != actual:
                add("linkage", "manifest", "FAIL", "DS", "The source file no longer matches the StarterPack manifest.")
        elif _is_sha256(sha):
            # A declared hash pins the bytes; we just cannot re-check them here. Not a measurement-quality problem,
            # so it does not down-weight the evidence.
            add("linkage", "source_hash", "INFO", "DS",
                f"Source file '{src}' is not held here, so its bytes cannot be re-checked. "
                "The declared SHA-256 is kept in the provenance trail, so they can be checked later.")
        else:
            add("linkage", "source_hash", "WARN", "DS",
                f"Source file '{src}' is not held here and the packet gives no SHA-256 hash, "
                "so its provenance cannot be verified (dossier §6.7). Used with a warning.")

    prov = p.get("provenance") if isinstance(p.get("provenance"), dict) else None
    if prov is not None:
        parents = prov.get("parents")
        parents = [parents] if isinstance(parents, str) else parents if isinstance(parents, list) else []
        real = [x for x in parents if isinstance(x, str) and x.strip().lower() not in config.NO_SOURCE_TOKENS]
        if real:
            add("linkage", "provenance_parents", "PASS", "DS", f"Provenance names {len(real)} source file{'' if len(real) == 1 else 's'}.")
        else:
            add("linkage", "provenance_parents", "FAIL", "DS",
                "Provenance lists no parent file, so the value has no traceable source (dossier §6.6, §6.7). "
                "A number without a source is never used.")

    # ---------------- 5. physics + metrology ----------------
    gates = ctx.gates
    acq = p.get("acquisition_context") if isinstance(p.get("acquisition_context"), dict) else {}
    reported = {c.get("name"): c for c in checks if isinstance(c, dict)}
    for c in checks:
        if not isinstance(c, dict):
            continue
        name, val = c.get("name"), c.get("value")
        g = gates.get(name)
        if g is None or not _num(val) or not any(k in g for k in ("warn_above", "warn_below", "fail_above", "fail_below")):
            continue
        field_note = ""
        if name == "mrs_linewidth_Hz":
            g, field_note = _linewidth_gate_for_field(g, acq)
        recomputed = _gate_status(g, val)
        declared_c = c.get("status")
        status = worst([recomputed, declared_c if declared_c in RANK else "PASS"])
        note = "" if declared_c == recomputed else f" (packet said {declared_c}; recomputed {recomputed} from {ctx.thresholds.get('id')})"
        add("physics", name, status, g.get("owner", c.get("owner", "Shared")),
            _explain_gate(name, val, status) + note + field_note, val, _gate_text(g))
    mod = p.get("modality") if isinstance(p.get("modality"), str) else None
    for name, g in gates.items():
        numeric = any(k in g for k in ("warn_above", "warn_below", "fail_above", "fail_below"))
        if numeric and mod in g.get("applies_to", []) and name not in reported and name != "missing_values":
            add("physics", name, "WARN", g.get("owner", "Shared"),
                f"Required check '{name}' was not reported, so quality cannot be verified.")

    if p.get("system_qc_id") in (None, ""):
        add("physics", "system_qc", "FAIL", "PM", "No system QC record: we cannot show the scanner was working correctly.")
    else:
        add("physics", "system_qc", "PASS", "PM", f"Scanner QC record present ({p.get('system_qc_id')}).")
    if p.get("comparable") is False:
        add("physics", "comparable", "FAIL", "PM", "The producer declares this measurement NOT comparable with the baseline.")
    if p.get("protocol_match") is False:
        add("physics", "protocol_match", "WARN", "PM", "The producer declares a protocol change versus the baseline.")

    b0n, nu0 = acq.get("field_strength_T"), acq.get("spectrometer_frequency_MHz")
    if _num(b0n) and _num(nu0) and b0n > 0:
        b0a = nu0 / config.GAMMA_BAR_MHZ_PER_T
        rel = abs(b0a - b0n) / b0n
        add("physics", "field_vs_frequency", "WARN" if rel > config.FIELD_MISMATCH_WARN_REL else "INFO", "QE",
            f"Label says {b0n} T; the frequency {nu0} MHz means the real field is {b0a:.3f} T. Both are kept.",
            extra={"B0_actual_T": round(b0a, 4)})

    if twin is not None and obs and not is_cal:
        base = twin.baseline_packet(obs)
        if base is not None and base.get("packet_id") != p.get("packet_id"):
            base_acq = base.get("acquisition_context") if isinstance(base.get("acquisition_context"), dict) else {}
            same_field = _field_comparability(p, base_acq, acq, add)
            diffs = _protocol_diffs(base_acq, acq, compare_frequency=same_field)
            add("physics", "protocol_vs_baseline", "WARN" if diffs else "PASS", "PM",
                "Protocol differs from the baseline: " + "; ".join(diffs) if diffs
                else "Same sequence, TE and TR as the baseline.")

    if obs == "roi_volume" and v.value is not None and v.u_stated is not None:
        _roi_consistency(p, v, add, ctx)

    v.u_effective = v.u_effective if v.u_effective is not None else v.u_stated
    if obs in config.U_FLOOR and v.value is not None and v.u_stated is not None:
        _uncertainty_floor(obs, v, add)

    # ---------------- 6. policy (twin side) ----------------
    if is_cal:
        pass  # one clear reason (evidence_scope) is enough; twin-side rules do not apply to scanner evidence
    elif obs and model is None:
        add("policy", "observation_model", "FAIL", "DT", f"The twin has no observation model for '{obs}', so it cannot use it.")
    session_used = twin is not None and not is_cal and obs and isinstance(ses, str) and twin.used_session(obs, ses)
    reproc = _reprocessing(twin, obs, ses, p) if session_used else None
    if reproc:
        add("policy", "reprocessed_evidence", "FAIL", "DT",
            f"This reprocesses {obs} from session '{ses}' ({reproc}). It would supersede evidence the twin already used, "
            "which needs a replay of the history from that session. This prototype deliberately does not replay, "
            "so it is rejected and the earlier evidence stays in place.")
    elif twin is not None and not is_cal and v.packet_id and twin.has_packet(v.packet_id):
        add("policy", "duplicate", "FAIL", "DT", f"Packet {v.packet_id} was already used. Using it twice would double-count evidence.")
    elif session_used:
        add("policy", "duplicate_session", "FAIL", "DT", f"The twin already used {obs} from session '{ses}'. A second packet would double-count it.")
    if twin is not None and not is_cal and obs and v.time_month is not None:
        cur = twin.current_time(obs)
        if cur is not None and v.time_month < cur:
            add("policy", "time_order", "FAIL", "DT",
                f"Evidence is from month {v.time_month:.1f}, older than the twin's current state (month {cur:.1f}). Out-of-order evidence needs a replay.")
    if model is not None and not is_cal and not any(f.layer == "policy" for f in F):
        add("policy", "twin_contract", "PASS", "DT",
            f"The twin has an observation model for {obs}; this evidence is new and in time order.")
        _surprise_preview(twin, obs, v, add)

    return _finish(v)


def _surprise_preview(twin, obs: str, v: Verdict, add) -> None:
    """Tell the user at check time whether the twin expects this value (the same d2 the update will compute).
    Informational only: it never changes the status, the action or the math, and it can never raise."""
    try:
        var = (getattr(twin, "variables", None) or {}).get(obs)
        if var is None or not (_num(v.value) and _num(v.u_effective) and v.u_effective > 0):
            return
        dt = (v.time_month or var.time_month) - var.time_month
        d2 = (v.value - var.mean) ** 2 / (var.var + twin.process_noise(obs, var.mean, dt) + v.u_effective ** 2)
        if not math.isfinite(d2):
            return
        above = d2 > config.D2_GATE
        add("policy", "surprise_preview", "INFO", "DT",
            (f"Surprise d2 = {d2:.2f} is above the gate {config.D2_GATE:.2f}: the twin did not expect this value. "
             "If applied, the update is flagged 'model disagreement' and must be investigated before it is trusted."
             if above else
             f"Surprise d2 = {d2:.2f}, below the gate {config.D2_GATE:.2f}: the twin expects a value like this."),
            round(d2, 3), f"d2 <= {config.D2_GATE:.2f}", extra={"above_gate": above})
    except Exception:  # a preview must never break a check
        return


def _explain_gate(name: str, val: float, status: str) -> str:
    words = {
        "mrs_snr": f"Signal-to-noise ratio {val}",
        "mrs_linewidth_Hz": f"Linewidth {val} Hz (broad lines = poor shim, peaks overlap)",
        "registration_rms_mm": f"Alignment error between sessions {val} mm",
    }
    return f"{words.get(name, f'{name} = {val}')}: {status}."


def _protocol_diffs(a: dict, b: dict, compare_frequency: bool = True) -> list[str]:
    """Sequence / TE / TR differences (WARN, dossier §5.8). A change of field is judged separately by
    _field_comparability; a small frequency shift at the same field is still reported here."""
    out = []
    for k in ("sequence", "TE_s", "TR_s"):
        if k in a and k in b and a[k] != b[k]:
            out.append(f"{k} {a[k]} -> {b[k]}")
    fa, fb = a.get("spectrometer_frequency_MHz"), b.get("spectrometer_frequency_MHz")
    if compare_frequency and _num(fa) and _num(fb) and fa > 0 and abs(fa - fb) / fa > config.FREQ_MATCH_REL:
        out.append(f"frequency {fa} -> {fb} MHz")
    return out


def _field_T(acq: dict) -> float | None:
    """The field we believe: from the measured frequency if given (§5.4: the nominal field is only a label)."""
    nu0, b0n = acq.get("spectrometer_frequency_MHz"), acq.get("field_strength_T")
    if _num(nu0) and nu0 > 0:
        return nu0 / config.GAMMA_BAR_MHZ_PER_T
    if _num(b0n) and b0n > 0:
        return float(b0n)
    return None


def _harmonization(p: dict) -> tuple[str, str | None]:
    """('ok', method) / ('incomplete', None) / ('none', None). Convention: see config.HARMONIZATION_HOWTO."""
    proc = p.get("processing") if isinstance(p.get("processing"), dict) else {}
    h = proc.get("harmonization")
    if h in (None, False, "", {}):
        return "none", None
    if isinstance(h, dict) and isinstance(h.get("method"), str) and h["method"].strip() and h.get("fit_for_trend") is True:
        return "ok", h["method"].strip()
    return "incomplete", None


def _field_comparability(p: dict, base_acq: dict, acq: dict, add) -> bool:
    """Dossier §5.8: acquisition comparable to baseline; FAIL if the field differs without harmonization (§6.5).
    Returns True when the field is the same as the baseline (or cannot be compared)."""
    b_base, b_new = _field_T(base_acq), _field_T(acq)
    if b_base is None or b_new is None:
        add("physics", "field_vs_baseline", "WARN", "PM",
            "Field or frequency missing, so we cannot confirm the field matches the baseline.")
        return True
    if abs(b_new - b_base) / b_base <= config.FIELD_SAME_REL:
        add("physics", "field_vs_baseline", "PASS", "PM", f"Same field as the baseline ({b_new:.2f} T).")
        return True
    kind, method = _harmonization(p)
    head = f"the field {b_new:.2f} T differs from the baseline field {b_base:.2f} T."
    if kind == "ok":
        add("physics", "field_vs_baseline", "WARN", "PM",
            f"{head[0].upper()}{head[1:]} Harmonization is declared (method: {method}), so the value is used "
            "with a warning (dossier §5.8, §6.5). The raw value before harmonization should stay in the record.",
            round(b_new, 3), f"same field as baseline ({b_base:.2f} T) or declared harmonization")
    else:
        why = ("Harmonization is declared but incomplete. " if kind == "incomplete" else "No harmonization is declared. ")
        add("physics", "field_vs_baseline", "FAIL", "PM",
            f"Not comparable: {head} {why}SNR, linewidth and peak overlap change with field, so mixing fields "
            f"would create a false trend (dossier §5.8). To declare one, add {config.HARMONIZATION_HOWTO}.",
            round(b_new, 3), f"same field as baseline ({b_base:.2f} T) or declared harmonization")
    return False


def _linewidth_gate_for_field(g: dict, acq: dict) -> tuple[dict, str]:
    """The 10 / 20 Hz limits are 3 T numbers. Peaks sit a fixed number of ppm apart, so overlap depends on the
    width in ppm; at another field we keep the same limits in ppm (10 Hz at 123.25 MHz = 0.081 ppm)."""
    b0 = _field_T(acq)
    ref_b0 = config.LINEWIDTH_REF_FIELD_T
    if b0 is None or abs(b0 - ref_b0) / ref_b0 <= config.FIELD_SAME_REL:
        return g, ""
    nu0 = b0 * config.GAMMA_BAR_MHZ_PER_T
    scale = nu0 / config.LINEWIDTH_REF_FREQ_MHZ
    g2 = dict(g)
    for k in ("warn_above", "warn_below", "fail_above", "fail_below"):
        if k in g2:
            g2[k] = round(g2[k] * scale, 2)
    ppm = g.get("warn_above", 10.0) / config.LINEWIDTH_REF_FREQ_MHZ
    note = (f" Limit set for this field: the 3 T limit of {g.get('warn_above', 10.0):g} Hz is {ppm:.3f} ppm, "
            f"which is {g2.get('warn_above', 0):g} Hz at {nu0:.1f} MHz. Peaks sit a fixed number of ppm apart, "
            "so overlap depends on the width in ppm.")
    return g2, note


def _uncertainty_floor(obs: str, v: Verdict, add) -> None:
    """Dossier §5.8 'stated u >= implied u: WARN, carry the implied u', with a declared teaching floor (config.U_FLOOR)."""
    fl = config.U_FLOOR[obs]
    floor = max(fl["rel"] * abs(v.value), fl.get("abs", 0.0))
    if floor <= 0:
        return
    label = config.STATE_VARIABLES.get(obs, {}).get("label", obs)
    if v.u_stated + 1e-15 < floor:
        v.u_effective = max(v.u_effective or 0.0, floor)
        add("physics", "uncertainty_floor", "WARN", "PM",
            f"Stated uncertainty {v.u_stated:.3g} is implausibly small. One scan of {label} cannot be repeatable to better "
            f"than about {floor:.3g} ({fl['rel']:.0%} of the value; teaching floor, dossier §5.6, §5.7). "
            f"We carry {floor:.3g} forward.",
            v.u_stated, f"u >= {floor:.3g}", extra={"u_floor": round(floor, 6), "u_effective": round(v.u_effective, 6)})
    else:
        add("physics", "uncertainty_floor", "PASS", "PM",
            f"Stated uncertainty {v.u_stated:.3g} is above the plausibility floor {floor:.3g}.")


def _is_calibration(p: dict) -> str:
    """Non-empty reason string when the packet is calibration / phantom evidence."""
    mod, sub = p.get("modality"), p.get("subject_id")
    if isinstance(mod, str) and mod in config.CALIBRATION_MODALITIES:
        return f"modality '{mod}'"
    if isinstance(sub, str) and any(w in sub.lower() for w in config.CALIBRATION_SUBJECT_WORDS):
        return f"subject '{sub}'"
    return ""


def _is_sha256(x: Any) -> bool:
    return isinstance(x, str) and len(x) == 64 and all(ch in "0123456789abcdef" for ch in x.lower())


def _reprocessing(twin: Any, obs: str, ses: str, p: dict) -> str | None:
    """If the twin used (obs, ses) with a different pipeline or version, describe the change; else None."""
    new = p.get("processing") if isinstance(p.get("processing"), dict) else {}
    for e in reversed(getattr(twin, "events", None) or []):
        if not isinstance(e, dict) or e.get("type") == "reject":
            continue
        if e.get("observable") == obs and e.get("session_id") == ses:
            old = e.get("processing") if isinstance(e.get("processing"), dict) else {}
            a = (str(old.get("pipeline")), str(old.get("version")))
            b = (str(new.get("pipeline")), str(new.get("version")))
            if a != b:
                return f"pipeline {a[0]} v{a[1]} -> {b[0]} v{b[1]}"
            return None
    return None


def _roi_consistency(p: dict, v: Verdict, add, ctx: PackContext) -> None:
    """Dossier §3.10 / thresholds roi_u_consistency: a mask pushed through an imperfect registration has a
    boundary error b ~ registration RMS, giving a relative volume error of about 3 b / r (r = equivalent radius)."""
    sr = p.get("spatial_reference") if isinstance(p.get("spatial_reference"), dict) else {}
    if not sr.get("mask_propagated"):
        add("physics", "roi_u_consistency", "INFO", "PM", "Mask not propagated through a registration; consistency rule not applicable.")
        return
    rms = sr.get("registration_rms_mm")
    if not _num(rms):
        rms = next((c.get("value") for c in p.get("qc_checks", []) if isinstance(c, dict) and c.get("name") == "registration_rms_mm"), None)
    ref = sr.get("reference_roi_volume_mm3")
    if not (_num(rms) and _num(ref) and ref > 0):
        add("physics", "roi_u_consistency", "WARN", "PM", "Registration error or reference volume missing: cannot test whether the stated uncertainty is honest.")
        return
    if not v.value > 0:
        add("physics", "roi_u_consistency", "FAIL", "PM", "A region volume of zero or less cannot be compared with the baseline.")
        return
    r_eq = (3 * ref / (4 * math.pi)) ** (1 / 3)
    implied_rel = 3 * rms / r_eq
    stated_rel = v.u_stated / v.value
    if stated_rel + 1e-12 < implied_rel:
        v.u_effective = implied_rel * v.value
        add("physics", "roi_u_consistency", "WARN", "PM",
            f"Stated uncertainty {stated_rel:.1%} is too small. A {rms} mm alignment error on a region of radius "
            f"{r_eq:.1f} mm implies about {implied_rel:.1%} (3 x {rms} / {r_eq:.1f}). We carry {implied_rel:.1%} forward.",
            round(stated_rel, 4), f"stated >= implied {implied_rel:.4f}",
            extra={"r_eq_mm": round(r_eq, 2), "implied_rel": round(implied_rel, 4), "u_effective": round(v.u_effective, 1)})
    else:
        add("physics", "roi_u_consistency", "PASS", "PM",
            f"Stated uncertainty {stated_rel:.1%} covers the {implied_rel:.1%} implied by the {rms} mm alignment error.")


def _finish(v: Verdict) -> Verdict:
    v.status = worst(f.status for f in v.findings)
    v.action = ACTIONS[v.status]
    fails = [f for f in v.findings if f.status == "FAIL"]
    warns = [f for f in v.findings if f.status == "WARN"]
    if fails:
        v.headline = (f"Reject: {len(fails)} blocking problem{'' if len(fails) == 1 else 's'}. "
                      f"{'It' if len(fails) == 1 else 'First'}: {fails[0].message}")
    elif warns:
        v.headline = (f"Use with a warning ({len(warns)} issue{'' if len(warns) == 1 else 's'}); "
                      "the twin trusts it less (variance x2).")
    elif any(f.check == "surprise_preview" and f.extra.get("above_gate") for f in v.findings):
        v.headline = ("All checks pass, but the twin did not expect this value (surprise d2 above the gate). "
                      "If applied, it is flagged for investigation.")
    else:
        v.headline = "All checks pass; the twin may update normally."
    return v
