"""Runs the Felix (Larmor assistant) evaluation set against the live local model and writes a report.

Usage (from the twin folder, with the local model running):  py tools/eval_assistant.py [--only q01,q24]
Re-run after every change to the system prompt or the docs (INTEGRATION.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LARMOR_ASSISTANT_WARM", "0")

from nmr_twin import assistant  # noqa: E402


def grade(answer: str, case: dict) -> list[str]:
    low = answer.lower()
    problems = [f"missing one of {group}" for group in case.get("must_include", [])
                if not any(alt.lower() in low for alt in group)]
    problems += [f"contains forbidden '{bad}'" for bad in case.get("must_not", []) if bad.lower() in low]
    if "source:" not in low:
        problems.append("no Source line")
    if "<think>" in low:
        problems.append("reasoning leaked")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated case ids")
    args = ap.parse_args()
    cases = json.loads((ROOT / "tests" / "assistant_eval.json").read_text(encoding="utf-8"))["cases"]
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    if not assistant.healthy():
        print("The local model is not running. Start it first (see INTEGRATION.md).")
        return 2
    try:
        import server  # noqa: F401  (registers the live twin-state provider, as in the app)
    except Exception as e:  # the eval still runs without it
        print(f"(twin state not available: {e})")
    assistant._set("ready", "eval")
    results, t_all = [], time.time()
    for c in cases:
        t = time.time()
        try:
            answer = assistant.ask_once(c["question"], [], c.get("screen"))
            problems = grade(answer, c)
        except RuntimeError as e:
            answer, problems = "", [f"error: {e}"]
        results.append({"id": c["id"], "question": c["question"], "pass": not problems, "problems": problems,
                        "seconds": round(time.time() - t, 1), "answer": answer})
        print(f"{'PASS' if not problems else 'FAIL'} {c['id']} ({results[-1]['seconds']} s) {c['question']}"
              + ("" if not problems else f"  -> {'; '.join(problems)}"), flush=True)
    passed = sum(r["pass"] for r in results)
    report = {"passed": passed, "total": len(results), "seconds": round(time.time() - t_all, 1), "results": results}
    out = ROOT / "state" / "assistant_eval_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{passed}/{len(results)} passed in {report['seconds']} s. Report: {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
