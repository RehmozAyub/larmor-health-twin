"""The 'Architecture and limits' page: its endpoint serves the deliverables, and the twin data dictionary
cannot drift from the code (every field it names must exist in what the code really produces)."""
import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nmr_twin import planner
from nmr_twin.checker import Verdict
from nmr_twin.findings import Finding
from routes import about

app = FastAPI()
app.include_router(about.router, prefix="/api")
client = TestClient(app)


@pytest.fixture(scope="module")
def payload():
    r = client.get("/api/about")
    assert r.status_code == 200
    return r.json()


def _has_path(obj: dict, dotted: str) -> bool:
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return False
        obj = obj[part]
    return True


def _section(doc: dict, title: str) -> dict:
    return next(s for s in doc["sections"] if s["title"] == title)


def test_endpoint_returns_canvas_with_full_aim_contract(payload):
    table = next(b for b in _section(payload["canvas"], "Aim contract")["blocks"] if b["kind"] == "table")
    items = [row[0] for row in table["rows"]]
    # dossier §9.2: physical counterpart, modality, state variable, ambiguity, output, one limitation
    assert items == ["Physical counterpart", "Modality", "State variable to update", "Ambiguity to resolve",
                     "Prototype output", "One limitation"]
    assert all(row[1] for row in table["rows"])
    titles = [s["title"] for s in payload["canvas"]["sections"]]
    assert "Primary variable, declared before looking" in titles and "Success criterion" in titles


def test_canvas_claims_a_maturity_level_with_reasons(payload):
    blocks = _section(payload["canvas"], "Maturity level")["blocks"]
    levels = next(b for b in blocks if b["kind"] == "list")["items"]
    assert [x.split(",")[0] for x in levels[:3]] == ["Level 3", "Level 4", "Level 5"]
    assert all(":" in x for x in levels)             # the page splits each line into a label and its reason


def test_qc_report_is_a_downloadable_deliverable(payload):
    f = next(f for f in payload["files"] if f["name"] == "qc_report.json")
    r = client.get(f["url"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    packets = r.json()["packets"]
    assert len(packets) >= 6 and all(len(p["checks"]) >= 5 for p in packets)
    assert all(c["owner"] for p in packets for c in p["checks"])


def test_endpoint_returns_dictionary_and_files(payload):
    d = payload["dictionary"]
    assert len(d) > 60
    assert set(d[0]) >= {"field", "type", "unit", "owner", "epistemic", "meaning", "group"}
    assert {g["id"] for g in payload["dictionary_groups"]} == {r["group"] for r in d}
    assert all(r["meaning"] for r in d)
    for f in payload["files"]:
        r = client.get(f["url"])
        assert r.status_code == 200 and len(r.content) == f["bytes"]
    assert client.get("/api/about/files/server.py").status_code == 404


def test_limits_name_the_validation_domain(payload):
    text = str(payload["limits"])
    for must in ("not validated for this condition", "TE 30 ms", "PRESS", "pseudonymous", "Claude"):
        assert must.lower() in text.lower()


def test_no_em_or_en_dashes_in_deliverables():
    for path in about.DELIVERABLES.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "\u2013" not in text and "\u2014" not in text, path.name


def _fields(group: str) -> list[str]:
    return [r["field"].split(".", 1)[1] for r in about.read_dictionary() if r["group"] == group]


def test_event_fields_exist_in_golden_path_events(twin):
    missing = [f for f in _fields("event") if not any(_has_path(e, f) for e in twin.events)]
    assert not missing, f"dictionary names event fields the code does not write: {missing}"


def test_state_fields_exist_in_twin_state(twin):
    var = twin.to_dict()["variables"]["Cho_Cr"]
    missing = [f for f in _fields("state") if not _has_path(var, f)]
    assert not missing, missing


def test_verdict_and_finding_fields_match_the_dataclasses():
    verdict = {f.name for f in dataclasses.fields(Verdict)}
    finding = {f.name for f in dataclasses.fields(Finding)}
    assert set(_fields("verdict")) <= verdict, set(_fields("verdict")) - verdict
    assert set(_fields("finding")) <= finding, set(_fields("finding")) - finding


def test_prediction_and_next_fields_exist(twin):
    pred = planner.prediction(twin, "Cho_Cr")
    row = planner.rank_next_measurements(twin)[0]
    assert all(_has_path(pred, f) for f in _fields("prediction")), [f for f in _fields("prediction") if f not in pred]
    assert all(_has_path(row, f) for f in _fields("next")), [f for f in _fields("next") if f not in row]


def test_every_golden_event_key_is_documented(twin):
    """The other direction: a new top-level event key must be added to the dictionary."""
    documented = {f.split(".")[0] for f in _fields("event")}
    written = {k for e in twin.events for k in e}
    assert written <= documented, f"undocumented event keys: {sorted(written - documented)}"
