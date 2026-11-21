"""Web server: exposes the twin engine as a small JSON API and serves the custom front end (web/).

Run:  py -m uvicorn server:app --port 8765      (from the twin/ folder)
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nmr_twin import assistant, cards, config, explain, imaging, planner, provenance
from routes import about, bench, scene
from routes import assistant as assistant_routes
from routes.common import ctx
from nmr_twin.findings import LAYER_TITLES, LAYERS, OWNERS
from nmr_twin.service import BASELINE, FOLLOWUP, golden_path, ingest, library, load_packet_text, new_twin, read_library_packet
from nmr_twin.twin import Twin

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

@asynccontextmanager
async def lifespan(_app):
    # Get the assistant ready in the background, so the first question does not wait for the model to load.
    # LARMOR_ASSISTANT_WARM=0 switches this off (the test suite does).
    if os.environ.get("LARMOR_ASSISTANT_WARM", "1") == "1":
        assistant.warm_in_background()
    yield


app = FastAPI(title="NMR Health Twin", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def no_stale_assets(request, call_next):
    """Always revalidate front-end files, so an edited script is never served from an old browser cache."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


_lock = threading.Lock()
twin: Twin = Twin.load() or golden_path(ctx)


def _state() -> dict:
    d = twin.to_dict()
    d["predictions"] = {k: planner.prediction(twin, k) for k in twin.variables}
    d["next"] = planner.recommendation(twin)
    d["explanations"] = {k: explain.explanations(twin, k) for k in twin.variables}
    d["models"] = {k: {**m, "modalities": sorted(m["modalities"])} for k, m in config.STATE_VARIABLES.items()}
    return d


def _assistant_state() -> str:
    """Compact, current numbers for the assistant: every variable, its newest evidence, and what is still open."""
    with _lock:
        lines = [f"State version {twin.version}; {len(twin.events)} events in the log; WARN policy x{twin.policy['WARN']['R_factor']}."]
        for name, v in twin.variables.items():
            last = next((e for e in reversed(twin.events) if e.get("observable") == name), None)
            line = f"- {name}: belief {v.mean:.4g} +/- {v.sd:.3g} {v.unit}, status {v.status}"
            if last is not None:
                line += f"; newest event #{last['event_id']} {last['type']} from {last.get('packet_id')} ({last.get('qc_status')})"
                if "K" in last:
                    ct = last.get("change_test", {})
                    line += f", K={last['K']:.3f}, d2={last['d2']:.2f}, z={ct.get('z', float('nan')):.2f}"
                if last.get("flags"):
                    line += f", flags={last['flags']}"
            lines.append(line)
        rejected = [e for e in twin.events if e["type"] == "reject"]
        if rejected:
            lines.append("Rejected packets: " + "; ".join(f"{e.get('packet_id')}: {str(e.get('reason', ''))[:140]}" for e in rejected[-3:]))
        try:
            rec = planner.recommendation(twin).get("recommended", [])
            if rec:
                lines.append("Recommended next: " + "; ".join(r["action"] for r in rec))
        except Exception:
            pass
        return "\n".join(lines)


assistant.set_state_provider(_assistant_state)


def _save() -> None:
    twin.save()


class CheckRequest(BaseModel):
    text: str
    apply: bool = False


class ResetRequest(BaseModel):
    mode: str = "golden"            # empty | baseline | golden


class SessionRequest(BaseModel):
    subject_id: str = "sub-01"
    session_id: str
    acq_time: str


class PolicyRequest(BaseModel):
    warn_factor: float


@app.get("/api/meta")
def meta():
    return {"disclaimer": config.DISCLAIMER, "primary": config.PRIMARY_VARIABLE, "d2_gate": config.D2_GATE,
            "z_crit": {"primary": config.Z_CRIT_PRIMARY, "secondary": config.Z_CRIT_SECONDARY},
            "layers": [{"id": l, "title": LAYER_TITLES[l]} for l in LAYERS], "owners": OWNERS,
            "thresholds": ctx.thresholds, "library": library(ctx), "baseline": BASELINE, "followup": FOLLOWUP,
            "sessions": {s: {k: v.isoformat() for k, v in d.items()} for s, d in ctx.sessions.items()}}


@app.get("/api/state")
def state():
    with _lock:
        return _state()


@app.get("/api/version")
def version():
    """Tiny change marker for live views: they poll this and fetch the full state only when it moves."""
    with _lock:
        return {"version": twin.version, "events": len(twin.events)}


@app.post("/api/reset")
def reset(req: ResetRequest):
    global twin
    with _lock:
        if req.mode == "empty":
            twin = new_twin(ctx)
        elif req.mode == "baseline":
            twin = golden_path(ctx, include_followup=False)
        else:
            twin = golden_path(ctx)
        _save()
        return _state()


@app.post("/api/step")
def step():
    """Golden path one packet at a time: ingest the next StarterPack packet that is not yet in the twin."""
    with _lock:
        for pid in BASELINE + FOLLOWUP:
            if not twin.has_packet(pid):
                out = ingest(twin, ctx, load_packet_text(ctx, pid))
                _save()
                return {"result": out, "state": _state()}
        return {"result": None, "state": _state()}


@app.post("/api/check")
def check(req: CheckRequest):
    with _lock:
        out = ingest(twin, ctx, req.text, apply=req.apply)
        if req.apply:
            _save()
        return {"result": out, "state": _state()}


@app.post("/api/policy")
def policy(req: PolicyRequest):
    if not 1.0 <= req.warn_factor <= 10.0:
        raise HTTPException(400, "WARN factor must be between 1 and 10")
    global twin
    with _lock:
        twin = golden_path(ctx, include_followup=False)
        twin.policy["WARN"]["R_factor"] = req.warn_factor
        for pid in FOLLOWUP:
            ingest(twin, ctx, load_packet_text(ctx, pid))
        _save()
        return _state()


@app.get("/api/packet/{item_id}")
def packet(item_id: str):
    try:
        return {"id": item_id, "text": read_library_packet(ctx, item_id)}
    except FileNotFoundError:
        raise HTTPException(404, f"unknown packet {item_id}")


@app.post("/api/session")
def register_session(req: SessionRequest):
    try:
        datetime.fromisoformat(req.acq_time)
    except ValueError:
        raise HTTPException(400, "acq_time must be ISO format, e.g. 2027-02-20T09:00:00")
    ctx.register_session(req.subject_id, req.session_id, req.acq_time)
    return meta()


@app.get("/api/provenance/{var}")
def prov(var: str):
    with _lock:
        return provenance.trace(twin, var, ctx)


@app.get("/api/cards")
def get_cards():
    return {"measurement": cards.MEASUREMENT_CARD, "budget": cards.budget(), "dictionary": ctx.data_dictionary}


@app.get("/api/spectrum/{session}")
def spec(session: str):
    if session not in ("ses-baseline", "ses-followup"):
        raise HTTPException(404, "spectra exist for ses-baseline and ses-followup")
    return imaging.spectrum(ctx, session)


@app.get("/api/anatomy/{session}")
def anat(session: str):
    if session not in ("ses-baseline", "ses-followup"):
        raise HTTPException(404, "images exist for ses-baseline and ses-followup")
    return imaging.anatomy(ctx, session)


@app.post("/api/tests")
def run_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA", "--color=no", "tests"],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    lines = [l for l in r.stdout.splitlines() if l.startswith(("PASSED", "FAILED", "ERROR"))]
    tests = [{"status": l.split(" ", 1)[0], "name": l.split(" ", 1)[1].split("::", 1)[-1]} for l in lines]
    return {"ok": r.returncode == 0, "summary": r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-500:],
            "tests": tests}


@app.get("/api/export")
def export():
    with _lock:
        return JSONResponse(twin.to_dict(), headers={"Content-Disposition": "attachment; filename=twin_audit_trail.json"})


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


for _r in (bench.router, scene.router, about.router, assistant_routes.router):
    app.include_router(_r, prefix="/api")

app.mount("/", StaticFiles(directory=WEB), name="web")
