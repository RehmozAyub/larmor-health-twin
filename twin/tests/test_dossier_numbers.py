"""The worked example of the dossier (§3.10, §7.5, §7.6, §7.7, Appendix E.2) must be reproduced exactly."""
import math

import pytest

from nmr_twin import cards, planner


def _ev(twin, pid):
    return next(e for e in twin.events if e["packet_id"] == pid)


def test_cho_cr_update(twin):
    e = _ev(twin, "E-t1-cho")
    assert e["type"] == "update_with_warning"
    assert e["change_test"]["z"] == pytest.approx(2.05, abs=0.01)
    assert e["d2"] == pytest.approx(3.66, abs=0.01)
    assert e["K"] == pytest.approx(0.321, abs=0.001)
    assert e["posterior"]["mean"] == pytest.approx(0.741, abs=0.001)
    assert e["posterior"]["sd"] == pytest.approx(0.048, abs=0.001)
    assert not e["discrepancy"]


def test_cho_cr_without_warn_policy_moves_more(ctx):
    """Dossier Fig. 16 dotted curve: without the WARN policy K = 0.486, x+ = 0.768."""
    from nmr_twin.service import golden_path
    t = golden_path(ctx, include_followup=False)
    t.policy["WARN"]["R_factor"] = 1.0
    from nmr_twin.service import ingest, load_packet_text
    ev = ingest(t, ctx, load_packet_text(ctx, "E-t1-cho"))["event"]
    assert ev["K"] == pytest.approx(0.486, abs=0.001)
    assert ev["posterior"]["mean"] == pytest.approx(0.768, abs=0.001)


def test_naa_cr_update(twin):
    e = _ev(twin, "E-t1-naa")
    assert e["change_test"]["z"] == pytest.approx(-0.90, abs=0.01)
    assert e["K"] == pytest.approx(0.26, abs=0.005)
    assert e["d2"] == pytest.approx(0.74, abs=0.01)
    assert e["posterior"]["mean"] == pytest.approx(1.227, abs=0.001)
    assert e["posterior"]["sd"] == pytest.approx(0.058, abs=0.001)


def test_roi_consistency_and_hold(twin):
    e = _ev(twin, "E-t1-roi")
    cons = next(f for f in e["findings"] if f["check"] == "roi_u_consistency")
    assert cons["status"] == "WARN"
    assert cons["extra"]["implied_rel"] == pytest.approx(0.19, abs=0.002)
    assert e["change_test"]["u_delta"] == pytest.approx(5310, abs=15)
    assert e["change_test"]["z"] == pytest.approx(1.07, abs=0.01)
    assert e["K"] == pytest.approx(0.009, abs=0.001)
    assert e["d2"] == pytest.approx(1.14, abs=0.01)
    assert e["posterior"]["mean"] == pytest.approx(22190, abs=1)
    assert e["posterior"]["sd"] == pytest.approx(697, abs=1)


def test_prediction_range(twin):
    p = planner.prediction(twin, "Cho_Cr")
    assert (round(p["low"], 2), round(p["high"], 2)) == (0.61, 0.88)


def test_next_measurement_ranking(twin):
    ranked = planner.rank_next_measurements(twin)
    assert ranked[0]["name"] == "Repeat PRESS after re-shim"
    assert ranked[0]["sd_after"] == pytest.approx(0.035, abs=0.001)
    assert ranked[0]["gain_per_min"] == pytest.approx(2.7e-4, abs=0.05e-4)
    avg = next(r for r in ranked if r["name"].startswith("PRESS with 2x"))
    assert avg["sd_after"] == pytest.approx(0.038, abs=0.001)
    assert avg["gain_per_min"] == pytest.approx(2.1e-4, abs=0.05e-4)


def test_uncertainty_budget():
    b = cards.budget()
    assert b["u_combined"] == pytest.approx(0.058, abs=0.001)
    assert b["dominant"].startswith("Spectral fit")
    assert b["dominant_share"] == pytest.approx(0.60, abs=0.01)


def test_field_from_frequency(twin):
    e = _ev(twin, "E-t1-cho")
    f = next(f for f in e["findings"] if f["check"] == "field_vs_frequency")
    assert f["extra"]["B0_actual_T"] == pytest.approx(2.895, abs=0.001)
    assert math.isclose(123.25 / 42.577, 2.8948, abs_tol=1e-3)
