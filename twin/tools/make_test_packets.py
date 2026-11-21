"""Generates the 'unseen' test packets used to rehearse the live defense (and by the test suite).

Each packet is a variation of the StarterPack follow-up Cho/Cr packet with ONE deliberate property.
Run:  py tools/make_test_packets.py
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nmr_twin import config  # noqa: E402

OUT = ROOT / "test_packets"
TEMPLATE = json.loads((config.TWIN_READY / "packets" / "E-t1-cho.json").read_text(encoding="utf-8"))


def declared_hash(src: str) -> str:
    """The producer's declared SHA-256 of a repeat-scan file we do not hold (synthetic, but fixed). With a declared
    hash a missing file is only INFO; without one it is WARN ("provenance cannot be verified")."""
    return hashlib.sha256(f"synthetic repeat scan bytes: {src}".encode()).hexdigest()


def low_field(p: dict) -> dict:
    """Same repeat scan, but acquired on a 1.5 T scanner (63.87 MHz). Linewidth in Hz is smaller at lower field."""
    p["acquisition_context"].update(field_strength_T=1.5, spectrometer_frequency_MHz=63.87)
    return p


def repeat_session(p: dict, pid: str, value: float, snr: float, lw: float, reg: float = 0.6, u: float = 0.05) -> dict:
    p = copy.deepcopy(p)
    src = "04_MRS_BIDS/sub-01/ses-repeat/mrs/sub-01_ses-repeat_acq-press_nuc-1H_voi-frontal_svs.nii.gz"
    p.update(packet_id=pid, session_id="ses-repeat", relative_time={"value": 7, "unit": "month"}, value=value,
             source_object=src, source_sha256=declared_hash(src),
             system_qc_id="sysqc-synthetic-20261220", calibration_id="phantom-2026-12")
    p["uncertainty"] = {"type": "SD", "value": u, "budget_ref": "D-worksheet-t2"}
    p["provenance"] = {"parents": [p["source_object"]], "activities": ["NIfTI-MRS ingest", "spectral fit", "ratio to Cr", "QC aggregation"]}
    p["qc_checks"] = [
        {"name": "mrs_snr", "value": snr, "unit": "1", "threshold": "WARN < 25; FAIL < 10", "status": "PASS" if snr >= 25 else "WARN", "owner": "QE"},
        {"name": "mrs_linewidth_Hz", "value": lw, "unit": "Hz", "threshold": "WARN > 10; FAIL > 20", "status": "PASS" if lw <= 10 else "WARN", "owner": "PM"},
        {"name": "registration_rms_mm", "value": reg, "unit": "mm", "threshold": "WARN > 2.0; FAIL > 3.0", "status": "PASS", "owner": "PM"},
        {"name": "missing_values", "value": 0, "unit": "1", "threshold": "FAIL > 0", "status": "PASS", "owner": "DS"},
    ]
    worst = "WARN" if any(c["status"] == "WARN" for c in p["qc_checks"]) else "PASS"
    p["qc_status"] = worst
    p["qc_reasons"] = [f"{c['name']} {c['value']}" for c in p["qc_checks"] if c["status"] != "PASS"]
    p["twin_action"] = {"recommended": "update" if worst == "PASS" else "update_with_warning", "reason": "producer recommendation"}
    return p


def register_sessions(rows: list[tuple[str, str, str]]) -> None:
    path = config.SESSIONS_EXTRA
    path.parent.mkdir(exist_ok=True)
    keep = []
    if path.exists():
        with open(path, encoding="utf-8", newline="") as fh:
            keep = [r for r in csv.DictReader(fh, delimiter="	")
                    if (r.get("subject_id"), r.get("session_id")) not in {(a, b) for a, b, _ in rows}]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ["subject_id", "session_id", "acq_time"], delimiter="	", extrasaction="ignore")
        w.writeheader()
        w.writerows(keep)
        w.writerows({"subject_id": a, "session_id": b, "acq_time": t} for a, b, t in rows)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    clean = repeat_session(TEMPLATE, "E-t2-cho", 0.78, 33.0, 8.6)
    packets: dict[str, dict | str] = {
        "U01_repeat_after_reshim_PASS": clean,
        "U03_simulated_labelled_measured": {**copy.deepcopy(clean), "packet_id": "E-t2-cho_label", "value_epistemic": "MEASURED"},
        "U04_wrong_unit": {**copy.deepcopy(clean), "packet_id": "E-t2-cho_unit", "unit": "mmol/L"},
        "U07_out_of_range": {**copy.deepcopy(clean), "packet_id": "E-t2-cho_range", "value": 3.4},
        "U08_unknown_observable": {**copy.deepcopy(clean), "packet_id": "E-t2-glx", "observable": "Glx_Cr"},
        "U09_surprising_value": {**copy.deepcopy(clean), "packet_id": "E-t2-cho_surprise", "value": 1.40},
        "U12_unregistered_session": {**copy.deepcopy(clean), "packet_id": "E-t3-cho", "session_id": "ses-month9",
                                     "relative_time": {"value": 9, "unit": "month"}},
    }
    # U05: the producer claims PASS although its SNR is below the limit
    opt = repeat_session(TEMPLATE, "E-t2-cho_opt", 0.80, 18.0, 9.0)
    opt["qc_checks"][0]["status"] = "PASS"
    opt["qc_status"], opt["qc_reasons"] = "PASS", []
    opt["twin_action"] = {"recommended": "update", "reason": "producer says all good"}
    packets["U05_optimistic_status"] = opt
    # U06: points to the real follow-up file but with the baseline file's hash
    bad_hash = copy.deepcopy(TEMPLATE)
    bad_hash.update(packet_id="E-t1-cho_hash", source_sha256="bc30ca7d26d8973fa95b54470ec33783ea4fd3d3b89917f6d4d922a0792d804c")
    packets["U06_hash_mismatch"] = bad_hash
    # U10: different echo time (a protocol change)
    proto = repeat_session(TEMPLATE, "E-t2-cho_te", 0.79, 30.0, 8.8)
    proto["acquisition_context"]["TE_s"] = 0.144
    packets["U10_protocol_change_TE144"] = proto
    # U11: exact copy of the follow-up packet (double counting)
    packets["U11_duplicate_followup"] = copy.deepcopy(TEMPLATE)
    # U02: not even JSON
    packets["U02_malformed_json"] = '{"packet_version": "1.0", "packet_id": "E-t2-cho", "value": 0.8,,, }'

    # ---- hardening packets (one per rule added for the live defense) ----
    # U13: follow-up from a 1.5 T scanner, no harmonization -> not comparable with the 3 T baseline (dossier §5.8)
    packets["U13_lowfield_1p5T_followup"] = low_field(repeat_session(TEMPLATE, "E-t2-cho_lowfield", 0.80, 27.0, 4.5))
    # U14: stated uncertainty 1e-6 -> implausibly small, carried forward at the floor
    packets["U14_tiny_uncertainty"] = repeat_session(TEMPLATE, "E-t2-cho_tinyu", 0.78, 33.0, 8.6, u=1e-6)
    # U15: source file not held here and no hash -> provenance cannot be verified
    unver = repeat_session(TEMPLATE, "E-t2-cho_nohash", 0.78, 33.0, 8.6)
    unver["source_sha256"] = None
    packets["U15_unverifiable_source"] = unver
    # U16: provenance with no parent file -> no traceable source
    orphan = repeat_session(TEMPLATE, "E-t2-cho_orphan", 0.78, 33.0, 8.6)
    orphan["provenance"]["parents"] = []
    packets["U16_no_provenance_parents"] = orphan
    # U17: a phantom (calibration) measurement of Cho/Cr -> belongs to the scanner's quality record
    cal = repeat_session(TEMPLATE, "E-t2-phantom_cho", 0.30, 120.0, 3.0)
    cal.update(subject_id="sub-phantom", session_id="ses-qc20261220", modality="calibration",
               interpretation_limit="phantom of known concentrations; scanner quality record only")
    packets["U17_phantom_calibration"] = cal
    # U18: the follow-up spectrum refitted with pipeline v0.4 (same session, same observable)
    rep = copy.deepcopy(TEMPLATE)
    rep["packet_id"] = "E-t1-cho_v04"
    rep["processing"]["version"] = "0.4"
    rep["value"] = 0.82
    packets["U18_reprocessed_v04"] = rep
    # U19: the 1.5 T follow-up WITH a declared harmonization (dossier §6.5) -> allowed, with a warning
    harm = low_field(repeat_session(TEMPLATE, "E-t2-cho_harmonized", 0.79, 27.0, 4.5))
    harm["processing"]["harmonization"] = {
        "method": "linear 1.5 T to 3 T mapping from paired phantom scans (teaching example)",
        "fit_for_trend": True, "raw_value": 0.80}
    packets["U19_lowfield_1p5T_harmonized"] = harm

    for name, p in packets.items():
        text = p if isinstance(p, str) else json.dumps(p, indent=2)
        (OUT / f"{name}.json").write_text(text, encoding="utf-8")
    # the repeat session (month 7) is registered by the team; ses-month9 deliberately is not
    config.SESSIONS_EXTRA.parent.mkdir(exist_ok=True)
    config.SESSIONS_EXTRA.write_text("subject_id\tsession_id\tacq_time\nsub-01\tses-repeat\t2026-12-20T09:00:00\n", encoding="utf-8")
    print(f"wrote {len(packets)} packets to {OUT}")


if __name__ == "__main__":
    main()
