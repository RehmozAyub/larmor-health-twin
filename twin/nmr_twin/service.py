"""High-level actions used by the API and the tests: build the twin, run the golden path, check packets."""
from __future__ import annotations

import json
from pathlib import Path

from . import config
from .checker import check_packet
from .context import PackContext, load_context
from .twin import Twin

BASELINE = ["E-t0-roi", "E-t0-naa", "E-t0-cho"]
FOLLOWUP = ["E-t1-roi", "E-t1-naa", "E-t1-cho"]


def packet_path(ctx: PackContext, packet_id: str) -> Path:
    return ctx.root / "05_TwinReady_JSON_CSV" / "packets" / f"{packet_id}.json"


def load_packet_text(ctx: PackContext, packet_id: str) -> str:
    return packet_path(ctx, packet_id).read_text(encoding="utf-8")


def new_twin(ctx: PackContext) -> Twin:
    return Twin("sub-01", json.loads(json.dumps(ctx.policy)))


def ingest(twin: Twin, ctx: PackContext, raw: str | dict, apply: bool = True) -> dict:
    verdict = check_packet(raw, ctx, twin)
    event = twin.assimilate(verdict) if apply else None
    return {"verdict": verdict.to_dict(), "event": event}


def golden_path(ctx: PackContext | None = None, include_followup: bool = True) -> Twin:
    """Baseline packets initialize the twin; follow-up packets update it (dossier §8.5)."""
    ctx = ctx or load_context()
    twin = new_twin(ctx)
    for pid in BASELINE + (FOLLOWUP if include_followup else []):
        ingest(twin, ctx, load_packet_text(ctx, pid))
    return twin


def library(ctx: PackContext) -> list[dict]:
    """All packets the UI can offer: StarterPack packets + our unseen test packets."""
    out = []
    for p in sorted((ctx.root / "05_TwinReady_JSON_CSV" / "packets").glob("*.json")):
        out.append({"id": p.stem, "group": "StarterPack", "file": p.name})
    for p in sorted((config.PROJECT_ROOT / "test_packets").glob("*.json")):
        out.append({"id": p.stem, "group": "Practice packets (ours)", "file": p.name})
    return out


def read_library_packet(ctx: PackContext, item_id: str) -> str:
    if not item_id or any(c in item_id for c in ("/", chr(92), ":")) or ".." in item_id:   # ids are plain file stems, never paths
        raise FileNotFoundError(item_id)
    for base in (ctx.root / "05_TwinReady_JSON_CSV" / "packets", config.PROJECT_ROOT / "test_packets"):
        p = base / f"{item_id}.json"
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError(item_id)
