"""The explanations and the next-measurement recommendation are computed from the current state.
They must change when the evidence changes (clean repeat U01, surprising value U09)."""
import json

import pytest

from nmr_twin import config, explain, planner
from nmr_twin.service import golden_path, ingest, load_packet_text, read_library_packet


def _apply(ctx, twin, name):
    return ingest(twin, ctx, read_library_packet(ctx, name))["event"]


def _row(ex, prefix):
    return next(r for r in ex["rows"] if r["hypothesis"].startswith(prefix))


def _state(rec, name):
    return next(a for a in rec["variables"] if a["variable"] == name)


def test_golden_path_recommendation(twin):
    rec = planner.recommendation(twin)
    actions = [r["action"] for r in rec["recommended"]]
    assert actions[0] == "Repeat PRESS after re-shim"
    assert any("audit" in a for a in actions)
    assert "removes the cause" in rec["recommended"][0]["why"]
    assert _state(rec, "Cho_Cr")["state"] == "open"
    assert {o["code"] for o in _state(rec, "Cho_Cr")["open"]} >= {"warn_cause_present", "above_target_sd"}
    assert _state(rec, "roi_volume")["state"] == "open"
    assert rec["open_flags"] == []
    assert rec["ranked"][0]["name"] == "Repeat PRESS after re-shim" and rec["ranked"][0]["needed_now"]
    assert "E-t1-cho" in rec["since_last"]["text"]


def test_every_event_has_flags(twin):
    assert all(e["flags"] == [] for e in twin.events)


def test_clean_repeat_changes_recommendation(ctx, twin):
    before = planner.recommendation(twin)
    ev = _apply(ctx, twin, "U01_repeat_after_reshim_PASS")
    assert ev["type"] == "update" and ev["flags"] == []
    rec = planner.recommendation(twin)
    assert [r["action"] for r in rec["recommended"]] != [r["action"] for r in before["recommended"]]
    assert [r["action"] for r in rec["recommended"]] == [planner.AUDIT]
    # Cho/Cr: consistent with no change, SD below the declared target, shim explanation resolved
    cho = _state(rec, "Cho_Cr")
    assert cho["state"] == "settled" and cho["sd"] < cho["target_sd"]
    assert "consistent with no change" in cho["summary"] and "resolved the shim" in cho["summary"]
    assert "removes the cause" not in " ".join(r["why"] for r in rec["recommended"])
    # ranking: the audit now comes first; the Cho/Cr repeat is marked not needed now
    assert rec["ranked"][0]["name"] == planner.AUDIT
    repeat = next(r for r in rec["ranked"] if r["name"] == "Repeat PRESS after re-shim")
    assert not repeat["needed_now"] and repeat["relevance"].startswith("Not needed now")
    # what changed since the last evidence
    sl = rec["since_last"]
    assert sl["packet_id"] == "E-t2-cho"
    assert "Cho/Cr warning cause" in sl["closed"] and "recommendation changed" in sl["text"]


def test_clean_repeat_explanations_use_all_evidence(ctx, twin):
    _apply(ctx, twin, "U01_repeat_after_reshim_PASS")
    ex = explain.explanations(twin, "Cho_Cr")
    assert ex["evidence_used"] == ["E-t0-cho", "E-t1-cho", "E-t2-cho"]
    shim = _row(ex, "Shim")
    assert "fell back" in shim["evidence"] and shim["discriminating_test"].startswith("Done")
    true = _row(ex, "True metabolic change")
    assert true["verdict"] == "not supported" and "E-t1-cho (WARN) gave z = 2.05" in true["evidence"]


def test_surprise_sets_flag_and_recommendation(ctx, twin):
    ev = _apply(ctx, twin, "U09_surprising_value")
    assert ev["type"] == "update"                     # type unchanged: the UI depends on it
    assert ev["flags"] == ["model_disagreement"] and ev["discrepancy"]
    assert "did not expect" in ev["reason"] and "Investigate before trusting it" in ev["reason"]
    rec = planner.recommendation(twin)
    assert [f["flag"] for f in rec["open_flags"]] == ["model_disagreement"]
    assert rec["open_flags"][0]["packet_id"] == "E-t2-cho_surprise"
    first = rec["recommended"][0]
    assert first["action"].startswith("Check packet E-t2-cho_surprise") and "model_disagreement" in first["closes"]
    assert "model disagreement" in rec["since_last"]["text"].lower()
    ex = explain.explanations(twin, "Cho_Cr")
    assert ex["flags"] == ["model_disagreement"]
    assert _row(ex, "True metabolic change")["verdict"] == "investigate"
    assert _row(ex, "Shim")["verdict"] == "not supported"     # the line is narrow and the value stayed high


def test_explain_uses_calibration_id(twin):
    ex = explain.explanations(twin, "Cho_Cr")
    cal = _row(ex, "Scanner calibration")
    assert "phantom-2026-05" in cal["evidence"] and "phantom-2026-11" in cal["evidence"]
    assert "no phantom record" not in cal["evidence"].lower()
    assert cal["verdict"] == "unlikely"


def test_missing_calibration_is_reported(ctx):
    t = golden_path(ctx, include_followup=False)
    p = json.loads(load_packet_text(ctx, "E-t1-cho"))
    p.pop("calibration_id", None)
    ingest(t, ctx, p)
    assert t.events[-1]["type"] != "reject"
    cal = _row(explain.explanations(t, "Cho_Cr"), "Scanner calibration")
    assert cal["verdict"] == "cannot be excluded" and "ses-followup" in cal["evidence"]


def test_nothing_open_says_so(ctx, twin):
    """If every variable is settled, the planner says no further measurement is needed."""
    _apply(ctx, twin, "U01_repeat_after_reshim_PASS")
    for name in ("NAA_Cr", "roi_volume"):          # pretend these are settled: clean, precise, not held
        ev = explain.latest_update(twin, name)
        ev["qc_status"], ev["K"] = "PASS", 0.5
        twin.variables[name].var = 1e-12
    rec = planner.recommendation(twin)
    assert rec["recommended"] == []
    assert "no further measurement needed" in rec["summary"]


def test_baseline_only(ctx):
    rec = planner.recommendation(golden_path(ctx, include_followup=False))
    assert rec["recommended"] == [] and "baseline" in rec["summary"].lower()


def test_dossier_numbers_unchanged(twin):
    e = next(e for e in twin.events if e["packet_id"] == "E-t1-cho")
    assert e["K"] == pytest.approx(0.321, abs=0.001)
    assert e["posterior"]["mean"] == pytest.approx(0.741, abs=0.001)
    ranked = planner.rank_next_measurements(twin)
    assert ranked[0]["sd_after"] == pytest.approx(0.035, abs=0.001)
    assert ranked[0]["gain_per_min"] == pytest.approx(2.7e-4, abs=0.05e-4)
    assert config.D2_GATE == pytest.approx(3.841)
