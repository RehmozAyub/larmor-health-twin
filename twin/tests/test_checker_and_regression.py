"""Live-defense rehearsal: every 'unseen' packet must get the right decision, plus the dossier's
cross-team regression tests (§8.7)."""
import copy
import json

import pytest

from nmr_twin import config, provenance
from nmr_twin.checker import check_packet
from nmr_twin.service import golden_path, ingest, load_packet_text, read_library_packet

EXPECTED = {
    "U01_repeat_after_reshim_PASS": ("update", None),
    "U02_malformed_json": ("reject", "json_parse"),
    "U03_simulated_labelled_measured": ("reject", "epistemic_label"),
    "U04_wrong_unit": ("reject", "unit"),
    "U05_optimistic_status": ("update_with_warning", "mrs_snr"),
    "U06_hash_mismatch": ("reject", "source_hash"),
    "U07_out_of_range": ("reject", "valid_range"),
    "U08_unknown_observable": ("reject", "observation_model"),
    "U09_surprising_value": ("update", None),
    "U10_protocol_change_TE144": ("update_with_warning", "protocol_vs_baseline"),
    "U11_duplicate_followup": ("reject", "duplicate"),
    "U12_unregistered_session": ("reject", "session"),
    "U13_lowfield_1p5T_followup": ("reject", "field_vs_baseline"),
    "U14_tiny_uncertainty": ("update_with_warning", "uncertainty_floor"),
    "U15_unverifiable_source": ("update_with_warning", "source_hash"),
    "U16_no_provenance_parents": ("reject", "provenance_parents"),
    "U17_phantom_calibration": ("reject", "evidence_scope"),
    "U18_reprocessed_v04": ("reject", "reprocessed_evidence"),
    "U19_lowfield_1p5T_harmonized": ("update_with_warning", "field_vs_baseline"),
    "E-t1-chobad": ("reject", "missing_value"),
}


@pytest.mark.parametrize("name,expected", EXPECTED.items())
def test_unseen_packets(ctx, twin, name, expected):
    action, check = expected
    v = check_packet(read_library_packet(ctx, name), ctx, twin)
    assert v.action == action, [f.message for f in v.findings if f.status != "PASS"]
    if check:
        assert any(f.check == check and f.status in ("WARN", "FAIL") for f in v.findings)


# ---------------- hardening rules (live defense) ----------------

STARTERPACK_ACTIONS = {
    "E-t0-roi": "update", "E-t0-naa": "update", "E-t0-cho": "update",
    "E-t1-roi": "update_with_warning", "E-t1-naa": "update_with_warning", "E-t1-cho": "update_with_warning",
}
NEW_CHECKS = {"field_vs_baseline", "uncertainty_floor", "source_hash", "provenance_parents", "evidence_scope",
              "reprocessed_evidence"}


def test_starterpack_packets_keep_their_status(ctx):
    from nmr_twin.service import new_twin
    t = new_twin(ctx)
    for pid, action in STARTERPACK_ACTIONS.items():
        v = ingest(t, ctx, load_packet_text(ctx, pid))["verdict"]
        assert v["action"] == action, pid
        bad = [f["check"] for f in v["findings"] if f["check"] in NEW_CHECKS and f["status"] in ("WARN", "FAIL")]
        assert not bad, (pid, bad)
    assert set(t.variables) == {"roi_volume", "NAA_Cr", "Cho_Cr"}  # the golden path still produces a full state


def test_starterpack_bad_packet_still_rejected_for_missing_value(ctx, twin):
    v = check_packet(load_packet_text(ctx, "E-t1-chobad"), ctx, twin)
    assert v.action == "reject" and any(f.check == "missing_value" and f.status == "FAIL" for f in v.findings)


def _repeat(ctx):
    return json.loads(read_library_packet(ctx, "U01_repeat_after_reshim_PASS"))


def test_field_change_without_harmonization_is_not_merged(ctx, twin):
    before = twin.variables["Cho_Cr"].mean
    ev = ingest(twin, ctx, read_library_packet(ctx, "U13_lowfield_1p5T_followup"))["event"]
    assert ev["type"] == "reject" and twin.variables["Cho_Cr"].mean == before


def test_incomplete_harmonization_still_fails(ctx, twin):
    p = json.loads(read_library_packet(ctx, "U19_lowfield_1p5T_harmonized"))
    p["processing"]["harmonization"] = {"method": "something"}          # fit_for_trend not stated
    v = check_packet(p, ctx, twin)
    assert any(f.check == "field_vs_baseline" and f.status == "FAIL" for f in v.findings)


def test_nominal_label_alone_does_not_trigger_field_rule(ctx, twin):
    p = _repeat(ctx)
    p["acquisition_context"]["field_strength_T"] = 2.9                   # same 123.25 MHz, label differs
    v = check_packet(p, ctx, twin)
    assert v.action == "update"


def test_linewidth_limit_is_kept_in_ppm_at_other_fields(ctx, twin):
    p = _repeat(ctx)
    p["qc_checks"][1]["value"] = 7.0                                      # PASS at 3 T (limit 10 Hz)
    assert next(f for f in check_packet(p, ctx, twin).findings if f.check == "mrs_linewidth_Hz").status == "PASS"
    p["acquisition_context"].update(field_strength_T=1.5, spectrometer_frequency_MHz=63.87)
    f = next(f for f in check_packet(p, ctx, twin).findings if f.check == "mrs_linewidth_Hz")
    assert f.status == "WARN" and "ppm" in f.message                     # 0.081 ppm = 5.2 Hz at 63.9 MHz


def test_dossier_linewidth_numbers_unchanged_at_3T(ctx, twin):
    for lw, expected in ((10.0, "PASS"), (10.1, "WARN"), (20.0, "WARN"), (20.1, "FAIL")):
        p = _repeat(ctx)
        p["qc_checks"][1].update(value=lw, status="PASS")
        f = next(f for f in check_packet(p, ctx, twin).findings if f.check == "mrs_linewidth_Hz")
        assert f.status == expected, lw


def test_tiny_uncertainty_is_carried_at_the_floor(ctx, twin):
    v = check_packet(read_library_packet(ctx, "U14_tiny_uncertainty"), ctx, twin)
    floor = config.U_FLOOR["Cho_Cr"]["rel"] * v.value
    assert v.u_stated == pytest.approx(1e-6) and v.u_effective == pytest.approx(floor)
    ev = ingest(twin, ctx, read_library_packet(ctx, "U14_tiny_uncertainty"))["event"]
    assert ev["evidence"]["u_effective"] == pytest.approx(floor)
    assert twin.variables["Cho_Cr"].sd > 0.5 * floor                    # the twin did not collapse


def test_missing_file_with_declared_hash_is_only_info(ctx, twin):
    v = check_packet(read_library_packet(ctx, "U01_repeat_after_reshim_PASS"), ctx, twin)
    assert next(f for f in v.findings if f.check == "source_hash").status == "INFO"


@pytest.mark.parametrize("parents", [[], ["none"], ["None", ""], "n/a"])
def test_no_traceable_parent_is_rejected(ctx, twin, parents):
    p = _repeat(ctx)
    p["provenance"]["parents"] = parents
    v = check_packet(p, ctx, twin)
    assert v.action == "reject" and any(f.check == "provenance_parents" and f.status == "FAIL" for f in v.findings)


@pytest.mark.parametrize("change", [{"subject_id": "sub-phantom"}, {"modality": "calibration"},
                                    {"subject_id": "sub-phantom", "modality": "calibration", "observable": "water_linewidth_Hz"}])
def test_calibration_evidence_gets_one_clear_reason(ctx, twin, change):
    p = {**_repeat(ctx), **change}
    v = check_packet(p, ctx, twin)
    assert v.action == "reject"
    fails = [f.check for f in v.findings if f.status == "FAIL"]
    assert fails == ["evidence_scope"], fails                           # not "not in participants.tsv"
    assert "scanner" in v.headline


def test_reprocessed_evidence_rejected_even_with_same_packet_id(ctx, twin):
    p = json.loads(load_packet_text(ctx, "E-t1-cho"))
    p["processing"]["version"] = "0.4"
    v = check_packet(p, ctx, twin)
    assert v.action == "reject" and any(f.check == "reprocessed_evidence" for f in v.findings)
    assert "replay" in v.headline


def test_new_messages_have_no_long_dashes(ctx, twin):
    for name in EXPECTED:
        if name.startswith("E-"):
            continue
        for f in check_packet(read_library_packet(ctx, name), ctx, twin).findings:
            assert "—" not in f.message and "–" not in f.message, f.message


def test_surprise_raises_discrepancy_flag(ctx, twin):
    ev = ingest(twin, ctx, read_library_packet(ctx, "U09_surprising_value"))["event"]
    assert ev["discrepancy"] and ev["d2"] > config.D2_GATE


def test_checker_never_crashes_on_garbage(ctx, twin):
    for raw in ["", "null", "[]", "42", '{"value": "abc"}', '{"qc_checks": [1, "x", null]}', "{" * 50]:
        v = check_packet(raw, ctx, twin)
        assert v.action == "reject"


# ---------------- dossier §8.7 cross-team regression tests ----------------

def test_units_everywhere(twin):
    for var in twin.variables.values():
        assert var.unit == config.STATE_VARIABLES[var.name]["unit"]


def test_fail_packet_cannot_update(ctx, twin):
    before = twin.variables["Cho_Cr"].mean
    ingest(twin, ctx, load_packet_text(ctx, "E-t1-chobad"))
    assert twin.variables["Cho_Cr"].mean == before
    assert twin.events[-1]["type"] == "reject"


def test_larger_uncertainty_gives_smaller_gain(ctx):
    gains = []
    for u in (0.03, 0.06, 0.12):
        t = golden_path(ctx, include_followup=False)
        p = json.loads(load_packet_text(ctx, "E-t1-cho"))
        p["uncertainty"]["value"] = u
        gains.append(ingest(t, ctx, p)["event"]["K"])
    assert gains[0] > gains[1] > gains[2]


def test_provenance_reaches_verified_source(ctx, twin):
    g = provenance.trace(twin, "Cho_Cr", ctx)
    files = [n for n in g["nodes"] if n["kind"] == "file"]
    assert files and all(n["verified"] for n in files)


def test_version_change_is_visible(ctx):
    t = golden_path(ctx, include_followup=False)
    p = json.loads(load_packet_text(ctx, "E-t1-cho"))
    p["processing"]["version"] = "0.4"
    ev = ingest(t, ctx, p)["event"]
    assert ev["processing"]["version"] == "0.4"
    from nmr_twin.explain import explanations
    rows = explanations(t, "Cho_Cr")["rows"]
    assert next(r for r in rows if r["hypothesis"].startswith("Processing"))["verdict"] == "possible"


def test_simulated_never_shown_as_measured(twin):
    for e in twin.events:
        assert not (e.get("origin") == "SIMULATED" and e.get("value_epistemic") == "MEASURED")


def test_out_of_order_evidence_rejected(ctx):
    t = golden_path(ctx)
    p = json.loads(read_library_packet(ctx, "U01_repeat_after_reshim_PASS"))
    p = copy.deepcopy(p)
    p.update(packet_id="E-t0-cho_late", session_id="ses-baseline", relative_time={"value": 0, "unit": "month"})
    v = check_packet(p, ctx, t)
    assert v.action == "reject"


def test_state_round_trip(tmp_path, twin):
    from nmr_twin.twin import Twin
    path = tmp_path / "s.json"
    twin.save(path)
    t2 = Twin.load(path)
    assert t2.variables["Cho_Cr"].mean == pytest.approx(twin.variables["Cho_Cr"].mean)
    assert len(t2.events) == len(twin.events)


def test_disclaimer_present(twin):
    assert "not a clinical" in twin.to_dict()["disclaimer"].lower() or "Not a clinical" in config.DISCLAIMER
