"""Router for the 'Architecture and limits' page.

Single source of truth: the deliverable files in deliverables/. This router parses them (markdown tables,
lists and paragraphs; the twin data dictionary CSV) and serves both the parsed content and the raw files,
so the page and the files a judge downloads can never disagree.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from nmr_twin import config
from nmr_twin.findings import LAYER_TITLES, LAYERS, OWNERS

router = APIRouter()

DELIVERABLES = Path(__file__).resolve().parents[1] / "deliverables"

# key -> (file name, short description). Order is the order shown on the page.
FILES = {
    "canvas": ("challenge_canvas.md", "One-page canvas with the aim contract and success criterion"),
    "architecture": ("architecture.md", "Tracks, digital twin system components, four views, data flow"),
    "limits": ("limitations_and_ethics.md", "Validation domain, privacy, bias, assumptions, AI use"),
    "dictionary": ("twin_data_dictionary.csv", "Machine-readable dictionary of every twin output field"),
    "reflection": ("reflection_template.md", "Individual reflections, one section per member"),
    "qc": ("qc_report.json", "QC report: every check on the StarterPack packets, with its owner track"),
}

GROUPS = {
    "state": ("Twin state", "One belief per variable: what the twin holds between scans."),
    "event": ("Event log", "One entry per packet: prior, evidence, gain, posterior and the reasons."),
    "verdict": ("Checker verdict", "What the six-layer check returns for one packet."),
    "finding": ("Checker finding", "One checked fact about a packet, with its owner track."),
    "prediction": ("Prediction", "The range a clean repeat should land in."),
    "next": ("Next measurement", "Candidate measurements, ranked by uncertainty removed per minute."),
}

_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_markdown(text: str) -> dict:
    """Parse the small markdown subset our deliverables use: # title, ## sections, paragraphs, - lists, tables.

    Blocks keep their order. Inline markup (**bold**, `code`, *italic*) is left for the page to render.
    """
    doc: dict = {"title": "", "intro": [], "sections": []}
    current: dict | None = None
    para: list[str] = []
    lines = text.replace("\r\n", "\n").split("\n")

    def blocks() -> list:
        return current["blocks"] if current is not None else doc["intro"]

    def flush_para() -> None:
        if para:
            blocks().append({"kind": "p", "text": " ".join(para)})
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("# ") and not doc["title"]:
            flush_para()
            doc["title"] = line[2:].strip()
        elif line.startswith("## "):
            flush_para()
            title = line[3:].strip()
            current = {"title": title, "id": _slug(title), "blocks": []}
            doc["sections"].append(current)
        elif line.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1].strip()):
            flush_para()
            header = _cells(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            blocks().append({"kind": "table", "header": header, "rows": rows})
            continue
        elif re.match(r"^\s*[-*] ", line):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*] ", lines[i]):
                items.append(re.sub(r"^\s*[-*] ", "", lines[i]).strip())
                i += 1
            blocks().append({"kind": "list", "items": items})
            continue
        elif not line.strip():
            flush_para()
        else:
            para.append(line.strip())
        i += 1
    flush_para()
    return doc


def read_dictionary() -> list[dict]:
    text = (DELIVERABLES / FILES["dictionary"][0]).read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    for r in rows:
        r["group"] = r["field"].split(".", 1)[0]
    return rows


@router.get("/about")
def about():
    try:
        # The reflections are optional: a copy of the project without them still shows this page.
        docs = {k: parse_markdown((DELIVERABLES / name).read_text(encoding="utf-8"))
                for k, (name, _) in FILES.items()
                if name.endswith(".md") and (k != "reflection" or (DELIVERABLES / name).exists())}
        dictionary = read_dictionary()
    except FileNotFoundError as e:
        raise HTTPException(500, f"deliverable file missing: {Path(e.filename).name}")
    files = []
    for key, (name, desc) in FILES.items():
        path = DELIVERABLES / name
        if not path.exists() and key in ("reflection", "qc"):
            continue
        files.append({"key": key, "name": name, "description": desc, "bytes": path.stat().st_size,
                      "url": f"/api/about/files/{name}"})
    groups = [{"id": g, "title": t, "description": d, "count": sum(r["group"] == g for r in dictionary)}
              for g, (t, d) in GROUPS.items()]
    return {
        "files": files,
        "canvas": docs["canvas"],
        "architecture": docs["architecture"],
        "limits": docs["limits"],
        "reflection": docs.get("reflection"),
        "dictionary": dictionary,
        "dictionary_groups": groups,
        "layers": [{"id": layer, "title": LAYER_TITLES[layer]} for layer in LAYERS],
        "owners": OWNERS,
        "disclaimer": config.DISCLAIMER,
    }


@router.get("/about/files/{name}")
def about_file(name: str):
    allowed = {n for n, _ in FILES.values()}
    if name not in allowed:
        raise HTTPException(404, f"unknown deliverable {name}")
    media = {".csv": "text/csv", ".json": "application/json"}.get(Path(name).suffix, "text/markdown")
    return FileResponse(DELIVERABLES / name, media_type=f"{media}; charset=utf-8", filename=name)
