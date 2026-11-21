"""The digital twin: a persistent belief (mean + variance) per variable, updated by checked evidence.

Update rule (dossier §7.5, Eq. 7.1–7.2), for each scalar variable with observation model h = 1:
    prior      x-, P- = P + Q(dt)                 Q = expected natural drift since the last update
    surprise   d2 = (y - x-)^2 / (P- + R_packet)  gate at 3.84; ALWAYS uses the packet's own variance
    policy     R = R_packet x factor               PASS x1, WARN x2 (declared team policy), FAIL -> no update
    gain       K = P- / (P- + R)
    posterior  x+ = x- + K (y - x-),  P+ = (1 - K) P-
Every step is written to an append-only event log, so any number on screen can be traced back.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .checker import Verdict


@dataclass
class Variable:
    name: str
    unit: str
    mean: float
    var: float
    time_month: float
    status: str = "initialized"
    baseline: dict = field(default_factory=dict)       # {"y", "u", "packet_id", "session_id"}
    packet_ids: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)

    @property
    def sd(self) -> float:
        return math.sqrt(self.var)


class Twin:
    def __init__(self, subject_id: str = "sub-01", policy: dict | None = None):
        self.subject_id = subject_id
        self.policy = policy or {"PASS": {"action": "update", "R_factor": 1.0},
                                 "WARN": {"action": "update_with_warning", "R_factor": 2.0},
                                 "FAIL": {"action": "reject"}}
        self.variables: dict[str, Variable] = {}
        self.events: list[dict] = []
        self.packets: dict[str, dict] = {}                  # packet_id -> packet, for provenance
        self.version = 0

    # ---- what the checker may ask (checker.TwinView) ----
    def has_packet(self, packet_id: str) -> bool:
        return any(e.get("packet_id") == packet_id and e["type"] != "reject" for e in self.events)

    def used_session(self, observable: str, session_id: str) -> bool:
        var = self.variables.get(observable)
        return bool(var and session_id in var.sessions)

    def current_time(self, observable: str) -> float | None:
        var = self.variables.get(observable)
        return var.time_month if var else None

    def baseline_packet(self, observable: str) -> dict | None:
        var = self.variables.get(observable)
        return self.packets.get(var.baseline.get("packet_id")) if var else None

    # ---- the update ----
    def process_noise(self, name: str, mean: float, dt_month: float) -> float:
        m = config.STATE_VARIABLES[name]
        q_sd = m["q_sd_6mo"] if "q_sd_6mo" in m else m["q_sd_6mo_rel"] * abs(mean)
        return q_sd ** 2 * max(dt_month, 0.0) / 6.0

    def assimilate(self, verdict: Verdict) -> dict:
        """Apply one checked packet. Returns the event written to the log."""
        p = verdict.packet or {}
        obs = verdict.observable
        ev = {
            "event_id": len(self.events) + 1,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "packet_id": verdict.packet_id, "observable": obs, "session_id": p.get("session_id"),
            "time_month": verdict.time_month, "qc_status": verdict.status, "headline": verdict.headline,
            "findings": [f.to_dict() for f in verdict.findings],
            "source_object": p.get("source_object"),
            "source_sha256": p.get("source_sha256") or next(
                (f.extra.get("actual") for f in verdict.findings if f.check == "source_hash" and f.extra.get("actual")), None),
            "hash_verified": any(f.check == "source_hash" and f.status == "PASS" for f in verdict.findings),
            "provenance": p.get("provenance"), "processing": p.get("processing"),
            "origin": p.get("origin"), "value_epistemic": p.get("value_epistemic"),
            "decision_epistemic": "INFERRED",
        }
        if verdict.action == "reject" or obs not in config.STATE_VARIABLES:
            ev.update(type="reject", flags=[],
                      reason="; ".join(f.message for f in verdict.findings if f.status == "FAIL") or "rejected")
            self._log(ev)
            return ev

        y, u = verdict.value, verdict.u_effective
        R_packet = u ** 2
        factor = float(self.policy[verdict.status]["R_factor"])
        R = factor * R_packet
        ev["evidence"] = {"y": y, "u_stated": verdict.u_stated, "u_effective": u, "R_packet": R_packet,
                          "R_factor": factor, "R_used": R}
        if verdict.packet_id:
            self.packets[verdict.packet_id] = p

        var = self.variables.get(obs)
        if var is None:  # first evidence for this variable: it becomes the baseline belief
            self.variables[obs] = Variable(
                name=obs, unit=config.STATE_VARIABLES[obs]["unit"], mean=y, var=R_packet,
                time_month=verdict.time_month or 0.0, status="initialized",
                baseline={"y": y, "u": u, "packet_id": verdict.packet_id, "session_id": p.get("session_id")},
                packet_ids=[verdict.packet_id], sessions=[p.get("session_id")])
            ev.update(type="initialize", posterior={"mean": y, "var": R_packet, "sd": u}, flags=[],
                      reason="First evidence for this variable: it sets the starting belief (baseline is not truth; it keeps its uncertainty).")
            self._log(ev)
            return ev

        dt = (verdict.time_month or var.time_month) - var.time_month
        Q = self.process_noise(obs, var.mean, dt)
        x_prior, P_prior = var.mean, var.var + Q
        d2 = (y - x_prior) ** 2 / (P_prior + R_packet)
        K = P_prior / (P_prior + R)
        x_post = x_prior + K * (y - x_prior)
        P_post = (1 - K) * P_prior

        b = var.baseline
        u_delta = math.sqrt(b["u"] ** 2 + u ** 2)
        z = (y - b["y"]) / u_delta
        primary = obs == config.PRIMARY_VARIABLE
        z_crit = config.Z_CRIT_PRIMARY if primary else config.Z_CRIT_SECONDARY

        ev.update(
            type=self.policy[verdict.status]["action"],
            prior={"mean": var.mean, "var": var.var, "Q": Q, "dt_month": dt, "mean_minus": x_prior, "var_minus": P_prior},
            d2=d2, d2_gate=config.D2_GATE, discrepancy=d2 > config.D2_GATE, K=K,
            posterior={"mean": x_post, "var": P_post, "sd": math.sqrt(P_post)},
            change_test={"delta": y - b["y"], "u_delta": u_delta, "z": z, "z_crit": z_crit, "primary": primary,
                         "significant": abs(z) > z_crit, "baseline_packet": b["packet_id"]},
            # Flags are added labels; they never change the math. "model_disagreement" = the surprise d2 is above
            # the gate: the twin did not expect this value, so it must be investigated before it is trusted.
            flags=["model_disagreement"] if d2 > config.D2_GATE else [],
            reason=self._reason(verdict.status, K, d2, z, z_crit, primary),
        )
        var.mean, var.var, var.time_month = x_post, P_post, verdict.time_month or var.time_month
        var.status = "updated_with_warning" if verdict.status == "WARN" else "updated"
        var.packet_ids.append(verdict.packet_id)
        var.sessions.append(p.get("session_id"))
        self._log(ev)
        return ev

    @staticmethod
    def _reason(status: str, K: float, d2: float, z: float, z_crit: float, primary: bool) -> str:
        parts = [f"The twin moved {K:.0%} of the way toward the new value"]
        parts.append("because the evidence passed with warnings (its variance was doubled)" if status == "WARN"
                     else "because the evidence passed all checks")
        txt = ", ".join(parts) + ". "
        txt += (f"Change vs baseline: z = {z:.2f}; " + ("beyond" if abs(z) > z_crit else "within") +
                f" the {'primary' if primary else 'Bonferroni-corrected'} limit {z_crit:.2f}. ")
        if d2 > config.D2_GATE:
            txt += (f"Surprise d² = {d2:.2f} is ABOVE the gate {config.D2_GATE:.2f}. Model disagreement: the twin did "
                    "not expect this value. The update was applied by the declared policy, but it is flagged. "
                    "Investigate before trusting it: check the source file and the processing, then repeat the measurement.")
        else:
            txt += f"Surprise d² = {d2:.2f} below the gate {config.D2_GATE:.2f}: the value is one the twin expected."
        return txt

    def _log(self, ev: dict) -> None:
        self.version += 1
        ev["state_version"] = self.version
        self.events.append(ev)

    # ---- persistence ----
    def to_dict(self) -> dict:
        return {"subject_id": self.subject_id, "policy": self.policy, "version": self.version,
                "variables": {k: {**v.__dict__, "sd": v.sd} for k, v in self.variables.items()},
                "events": self.events, "packets": self.packets,
                "origin": "SIMULATED", "disclaimer": config.DISCLAIMER}

    @classmethod
    def from_dict(cls, d: dict) -> "Twin":
        t = cls(d["subject_id"], d.get("policy"))
        t.version = d.get("version", 0)
        t.variables = {k: Variable(**{f: x for f, x in v.items() if f != "sd"}) for k, v in d.get("variables", {}).items()}
        t.events = d.get("events", [])
        t.packets = d.get("packets", {})
        return t

    def save(self, path: Path = config.STATE_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(), indent=2, default=str, allow_nan=False)
        tmp = path.with_suffix(".tmp")           # write beside, then swap: a crash mid-write cannot leave half a file
        tmp.write_text(text, encoding="utf-8")
        try:
            tmp.replace(path)
        except OSError:                          # some synced folders refuse the swap; fall back to a direct write
            path.write_text(text, encoding="utf-8")

    @classmethod
    def load(cls, path: Path = config.STATE_FILE) -> "Twin | None":
        """The saved twin, or None when there is no usable state file (the caller then rebuilds from the packets)."""
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
        except Exception:
            return None
