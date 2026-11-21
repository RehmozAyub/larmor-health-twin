"""Build a static, read-only copy of the Larmor web app (for a static host such as GitHub Pages).

    py tools/build_static.py <output_dir> [--skip-tests]

The app normally talks to the Python engine through /api/... . This script drives the real engine in-process,
stores every answer the front end needs as JSON under <output_dir>/snapshot/, copies the front end (web/) next to
it and adds static-api.js, a small script that answers the same /api/... calls from those stored files.

Nothing is invented: every stored answer comes from the real checker, twin and test bench. What a static page
cannot do (check a packet that is not stored, apply a packet, start a new bench run) is refused with a clear
message instead of being faked.

The build never changes the saved twin state, the session table or the bench cache of the working copy.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["LARMOR_ASSISTANT_WARM"] = "0"     # never start or warm a local model during a build
os.environ["LARMOR_LLM_AUTOSTART"] = "0"

TWIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TWIN_ROOT))

from nmr_twin import bench, twin as twin_module  # noqa: E402

# Keep the working copy untouched: no state file is read or written, and the bench cache is a private copy.
twin_module.Twin.save = lambda self, path=None: None
twin_module.Twin.load = classmethod(lambda cls, path=None: None)
_tmp = Path(tempfile.mkdtemp(prefix="larmor_static_"))
if bench.RESULTS_FILE.exists():
    shutil.copy2(bench.RESULTS_FILE, _tmp / "bench_results.json")
bench.RESULTS_FILE = _tmp / "bench_results.json"

import server  # noqa: E402  (after the patches above, so the app starts from a fresh golden-path twin)
from fastapi.testclient import TestClient  # noqa: E402

VARIABLES = ("Cho_Cr", "NAA_Cr", "roi_volume")
SESSIONS = ("ses-baseline", "ses-followup")
POLICY_FACTORS = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)        # the WARN slider on the Twin state page
PRIVATE_FILES = {"reflection_template.md"}                   # individual course work: not part of the public copy
OFFLINE_ASSISTANT = {"state": "offline",
                     "detail": "Felix runs on a local model, so it is not part of this online copy."}

# Anything matching these must not reach a public copy (machine paths, local addresses, private notes).
PRIVATE_PATTERNS = [r"(?<![A-Za-z])[A-Za-z]:(?:\\\\|\\|/)(?!/)[A-Za-z]", r"/Users/", r"\\Users\\",
                    r"127\.0\.0\.1", r"localhost", r":9931\b",
                    r"claude\.ai", r"[\w.+-]+@[\w-]+\.[a-z]{2,}"]


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8", newline="\n")


def get(client: TestClient, url: str):
    r = client.get(url)
    return {"status": r.status_code, "body": r.json()}


def must(client: TestClient, method: str, url: str, **kw):
    r = getattr(client, method)(url, **kw)
    if r.status_code != 200:
        raise SystemExit(f"{method.upper()} {url} answered {r.status_code}: {r.text[:300]}")
    return r.json()


def capture_state(client: TestClient, state: dict) -> dict:
    """One twin state with everything that depends on it: the provenance graph of each variable."""
    return {"state": state, "provenance": {v: get(client, f"/api/provenance/{v}") for v in VARIABLES}}


def capture_checks(client: TestClient, packets: dict[str, str]) -> dict:
    """The checker's answer for every library packet against the twin as it is now (never applied)."""
    return {pid: must(client, "post", "/api/check", json={"text": text, "apply": False})["result"]
            for pid, text in packets.items()}


def build(out: Path, run_tests: bool) -> None:
    snap = out / "snapshot"
    if snap.exists():
        shutil.rmtree(snap)
    client = TestClient(server.app)

    # ---- answers that do not depend on the twin's state ----
    meta = must(client, "get", "/api/meta")
    packets = {item["id"]: must(client, "get", f"/api/packet/{item['id']}")["text"] for item in meta["library"]}
    about = must(client, "get", "/api/about")
    about["files"] = [f for f in about["files"] if f["name"] not in PRIVATE_FILES]
    about["reflection"] = {"title": "", "intro": [], "sections": []}
    fixed = {
        "/api/meta": meta,
        "/api/cards": must(client, "get", "/api/cards"),
        "/api/about": about,
        "/api/scene/library-geometry": must(client, "get", "/api/scene/library-geometry"),
        "/api/assistant/status": OFFLINE_ASSISTANT,
    }
    for s in SESSIONS:
        fixed[f"/api/spectrum/{s}"] = must(client, "get", f"/api/spectrum/{s}")
        fixed[f"/api/anatomy/{s}"] = must(client, "get", f"/api/anatomy/{s}")
    dump(snap / "fixed.json", fixed)
    dump(snap / "packets.json", packets)
    dump(snap / "scene.json", must(client, "get", "/api/scene"))
    dump(snap / "bench.json", must(client, "get", "/api/bench"))
    dump(snap / "files" / "bench_packets.json", must(client, "get", "/api/bench/packets"))
    dump(snap / "files" / "bench_truth.json", must(client, "get", "/api/bench/truth"))
    for f in about["files"]:
        r = client.get(f["url"])
        if r.status_code != 200:
            raise SystemExit(f"{f['url']} answered {r.status_code}")
        (snap / "files").mkdir(parents=True, exist_ok=True)
        (snap / "files" / f["name"]).write_bytes(r.content)

    # ---- the golden path, one packet at a time: states s0 (empty) to s6 (all six packets) ----
    steps = {}
    state = must(client, "post", "/api/reset", json={"mode": "empty"})
    dump(snap / "state" / "s0.json", capture_state(client, state))
    dump(snap / "checks" / "s0.json", capture_checks(client, packets))
    for k in range(1, 7):
        r = must(client, "post", "/api/step")
        if r["result"] is None:
            raise SystemExit(f"golden path ended early at step {k}")
        steps[str(k)] = r["result"]
        dump(snap / "state" / f"s{k}.json", capture_state(client, r["state"]))
        dump(snap / "checks" / f"s{k}.json", capture_checks(client, packets))
    dump(snap / "steps.json", steps)

    # ---- the WARN-policy slider: the full update replayed with each factor ----
    for f in POLICY_FACTORS:
        state = must(client, "post", "/api/policy", json={"warn_factor": f})
        dump(snap / "state" / f"p{f:.1f}.json", capture_state(client, state))

    # ---- the regression tests, run once ----
    if run_tests:
        tests = must(client, "post", "/api/tests")
        if not tests["ok"]:
            raise SystemExit(f"the test suite does not pass ({tests['summary']}); not publishing a failing run")
        dump(snap / "tests.json", tests)

    dump(snap / "index.json", {"policy_factors": [f"{f:.1f}" for f in POLICY_FACTORS], "default_factor": "2.0",
                               "variables": list(VARIABLES), "has_tests": run_tests,
                               "files": sorted(p.name for p in (snap / "files").iterdir())})

    # ---- the front end itself ----
    web = TWIN_ROOT / "web"
    for item in web.iterdir():
        target = out / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    shutil.copy2(Path(__file__).with_name("static-api.js"), out / "static-api.js")
    html = (web / "index.html").read_text(encoding="utf-8")
    module_tag = '<script type="module" src="js/main.js"></script>'
    badge_tag = '<div class="sim-badge"'
    if html.count(module_tag) != 1 or html.count(badge_tag) != 1:
        raise SystemExit("index.html no longer has the expected script tag or SIMULATED badge")
    html = html.replace(module_tag, '<script src="static-api.js"></script>\n  ' + module_tag)
    html = html.replace(badge_tag, '<div class="sim-badge" style="margin-right:8px" title="This copy runs without the Python engine. '
                        'It shows stored answers from the real checker, twin and test bench."><b>ONLINE COPY</b><span>Read-only</span></div>\n      '
                        + badge_tag)
    (out / "index.html").write_text(html, encoding="utf-8", newline="\n")

    # ---- last gate: nothing private in what was just written ----
    hits = []
    for p in snap.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            for pat in PRIVATE_PATTERNS:
                m = re.search(pat, text)
                if m:
                    hits.append(f"{p.relative_to(out)}: {pat!r} near ...{text[max(0, m.start() - 40):m.end() + 40]!r}")
    if hits:
        raise SystemExit("private-looking text in the snapshot:\n  " + "\n  ".join(hits))
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"static copy written: {len(list(snap.rglob('*.json')))} snapshot files, {size / 1e6:.1f} MB in total")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    build(Path(args[0]).resolve(), run_tests="--skip-tests" not in sys.argv)
