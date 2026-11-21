"""Router for the Monte-Carlo test bench (nmr_twin.bench): simulated follow-ups with known truth.

GET  /api/bench              cached results without the packets and the truth file (computed once if absent)
POST /api/bench/run          {"seed": int, "n": int}: a fresh run (n bounded), cached to state/bench_results.json
GET  /api/bench/packets      student-facing evidence packets of the cached run (no truth inside)
GET  /api/bench/truth        instructor truth file of the cached run (dossier §4.8, Appendix C.6)
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from nmr_twin import bench
from routes.common import ctx

router = APIRouter()
_lock = threading.Lock()
_cache: dict | None = None

HEAVY = ("packets", "truth_file")


class RunRequest(BaseModel):
    seed: int = bench.DEFAULT_SEED
    n: int = bench.DEFAULT_N


def _results() -> dict:
    global _cache
    if _cache is None:
        _cache = bench.load_cached()
    if _cache is None or _cache.get("bench_version") != bench.BENCH_VERSION:
        _cache = bench.run(bench.DEFAULT_SEED, bench.DEFAULT_N, ctx)
    return _cache


def _light(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k not in HEAVY}
    out["limits"] = {"n_min": 20, "n_max": bench.MAX_N, "default_n": bench.DEFAULT_N, "default_seed": bench.DEFAULT_SEED}
    return out


@router.get("/bench")
def get_bench():
    with _lock:
        return _light(_results())


@router.post("/bench/run")
def run_bench(req: RunRequest):
    global _cache
    if not 20 <= req.n <= bench.MAX_N:
        raise HTTPException(400, f"n must be between 20 and {bench.MAX_N}")
    if not 0 <= req.seed <= 2**31 - 1:
        raise HTTPException(400, "seed must be a non-negative integer")
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "A bench run is already in progress. Try again in a few seconds.")
    try:
        _cache = bench.run(req.seed, req.n, ctx)
        return _light(_cache)
    finally:
        _lock.release()


@router.get("/bench/packets")
def get_packets():
    with _lock:
        r = _results()
    return JSONResponse({"seed": r["seed"], "n": r["n"], "origin": "SIMULATED", "packets": r["packets"]},
                        headers={"Content-Disposition": f"attachment; filename=bench_packets_seed{r['seed']}.json"})


@router.get("/bench/truth")
def get_truth():
    with _lock:
        r = _results()
    return JSONResponse(r["truth_file"],
                        headers={"Content-Disposition": f"attachment; filename=bench_truth_seed{r['seed']}.json"})
