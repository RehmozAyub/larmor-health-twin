"""Built-in support assistant: answers questions about Larmor from our own docs and from what is on the screen.

It uses the model that already runs on this laptop (llama.cpp, OpenAI-compatible API), following
our local-model integration rules:
  * no model download, no second runtime, no second server: we only call the existing API (and, if it is down,
    run the owner's launcher with -NoTools, which itself refuses to start a second server);
  * never send `tools`, never call the server's /tools endpoint;
  * our own docs are the single source of truth: they are read from disk at request time, in a fixed order,
    so the server can cache the identical prefix and later questions start answering almost immediately;
  * base URL and model name are settings (environment variables), so the code can point elsewhere unchanged;
  * thinking is off (quick answers) and any reasoning text is dropped before it reaches the user.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

import httpx

from . import config

# ---------------- settings (rule 6: configurable endpoint) ----------------
BASE_URL = os.environ.get("LARMOR_LLM_BASE_URL", "http://127.0.0.1:9931/v1").rstrip("/")
MODEL = os.environ.get("LARMOR_LLM_MODEL", "local")
HEALTH_URL = os.environ.get("LARMOR_LLM_HEALTH_URL", BASE_URL.removesuffix("/v1") + "/health")
LAUNCHER = os.environ.get("LARMOR_LLM_LAUNCHER", "")   # optional script that starts your local model
AUTOSTART = os.environ.get("LARMOR_LLM_AUTOSTART", "1") == "1"
MAX_ANSWER_TOKENS = int(os.environ.get("LARMOR_LLM_MAX_TOKENS", "900"))

# Token budget inside the 32,768-token context: docs (~13k) + history + screen + answer.
CHARS_PER_TOKEN = 3.5
HISTORY_TOKEN_BUDGET = 5000
SCREEN_CHAR_LIMIT = 3500                  # ~1,000 tokens: the top of the page; more text slows the first words noticeably

# ---------------- the docs: single source of truth (rule 5), fixed order for prefix caching ----------------
DOCS: list[tuple[Path, str]] = [
    (config.HACKATHON_ROOT / "DEFENSE_NOTES.md", "Every page of the app, what it shows, why, and short answers"),
    (config.PROJECT_ROOT / "deliverables" / "challenge_canvas.md", "Aim contract and success criteria"),
    (config.PROJECT_ROOT / "deliverables" / "architecture.md", "System architecture, tracks, data flow"),
    (config.PROJECT_ROOT / "deliverables" / "limitations_and_ethics.md", "Validation domain, privacy, bias, limits"),
    (config.PROJECT_ROOT / "deliverables" / "twin_data_dictionary.csv", "Every field the twin writes, with units"),
]

SYSTEM_RULES = """You are Felix, the built-in help assistant of Larmor, an educational prototype of an evidence-gated digital twin \
built for the InnovateU NMR hackathon. It compares two synthetic brain scans (MRI and 1H spectroscopy) taken six months \
apart and decides how far the twin's belief may move. All data are SIMULATED.

How to answer:
- Use ONLY the DOCS below and the SCREEN and TWIN STATE blocks in the user's message. Do not use outside knowledge for \
facts about Larmor, its numbers, its pages or its rules.
- When the user says "this", "here" or "this result", they mean what is on the SCREEN block. Explain it using the docs.
- If the docs and the screen do not cover the question, say plainly: "Our docs do not cover that." Then suggest asking \
the team (Rehmoz Ayub, Ege Eroglu, Oussama Turki). Do not guess.
- Never invent features, buttons, settings, numbers, thresholds or steps. Copy numbers exactly as written.
- Never give medical advice or a diagnosis. Larmor is not a clinical tool.
- Write plain English for a beginner: short sentences, define any technical term in a few words, use short lists \
where they help. Keep most answers under 150 words unless the user asks for more.
- Do not show your reasoning. Give the answer directly.
- End every answer with one line: "Source: <file name> > <section heading>" (add "Screen" when you used the screen).
"""


class _DocCache:
    """Docs are read from disk on every request (rule 5), but the built prompt is reused while no file changed,
    so the text sent to the server stays byte-identical and its prefix cache keeps working."""

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._prompt = ""
        self._lock = threading.Lock()

    def system_prompt(self) -> str:
        key = tuple((str(p), p.stat().st_mtime if p.exists() else None) for p, _ in DOCS)
        with self._lock:
            if key != self._key:
                parts = [SYSTEM_RULES, "\n=== DOCS (read-only, in fixed order) ===\n"]
                for path, about in DOCS:
                    if not path.exists():
                        continue
                    text = path.read_text(encoding="utf-8").strip()
                    parts.append(f"\n<<<DOC {path.name} | {about}>>>\n{text}\n<<<END {path.name}>>>\n")
                self._prompt = "".join(parts)
                self._key = key
            return self._prompt


docs = _DocCache()


def sources() -> list[dict]:
    return [{"file": p.name, "about": a, "present": p.exists(), "bytes": p.stat().st_size if p.exists() else 0}
            for p, a in DOCS]


# ---------------- live twin state (provided by the server, so this module needs no import of server.py) ----------------
_state_provider: Callable[[], str] | None = None


def set_state_provider(fn: Callable[[], str]) -> None:
    global _state_provider
    _state_provider = fn


def _state_text() -> str:
    try:
        return _state_provider() if _state_provider else "(not available)"
    except Exception as e:  # the assistant must never break because a summary failed
        return f"(could not read the twin state: {e})"


# ---------------- background readiness: start (if allowed) and pre-fill the prompt cache ----------------
_status = {"state": "idle", "detail": "Not started yet.", "since": time.time()}
_request_lock = threading.Lock()          # the local server answers one request at a time (INTEGRATION.md)
_warm_thread: threading.Thread | None = None


def _set(state: str, detail: str) -> None:
    _status.update(state=state, detail=detail, since=time.time())


def status() -> dict:
    return {**_status, "model_url": BASE_URL, "docs": sources()}


def healthy(timeout: float = 2.0) -> bool:
    try:
        r = httpx.get(HEALTH_URL, timeout=timeout)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def _payload(messages: list[dict], stream: bool, max_tokens: int) -> dict:
    # Request settings from INTEGRATION.md. Never add "tools" here (rule 4).
    return {"model": MODEL, "messages": messages, "stream": stream, "max_tokens": max_tokens,
            "temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0,
            "chat_template_kwargs": {"enable_thinking": False}}


def _warm() -> None:
    try:
        if not healthy():
            if not AUTOSTART or not Path(LAUNCHER).exists():
                _set("offline", "The local model is not running. Start it, then press Retry.")
                return
            _set("starting", "Starting the local model in the background (about 45 seconds).")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            # The launcher checks /health itself and never starts a second server (rule 2). -NoTools (rule 4).
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", LAUNCHER, "-NoTools"],
                             creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + 300
            while not healthy():
                if time.time() > deadline:
                    _set("offline", "The local model did not start within 5 minutes.")
                    return
                time.sleep(2)
        _set("warming", "Reading our docs into the model's memory.")
        msgs = [{"role": "system", "content": docs.system_prompt()}, {"role": "user", "content": "Reply with: ready"}]
        with _request_lock:
            r = httpx.post(f"{BASE_URL}/chat/completions", json=_payload(msgs, False, 1), timeout=300)
            r.raise_for_status()
        _set("ready", "Ready. Docs are loaded, so answers start quickly.")
        _watch_docs()
    except Exception as e:
        _set("offline", f"Could not reach the local model: {e}")


def _watch_docs() -> None:
    """When a doc file changes, re-read the docs into the model in the background (while it is idle), so the next
    question does not pay the one-minute cost of reading ~15,000 tokens of changed docs."""
    loaded = docs.system_prompt()
    while True:
        time.sleep(15)
        current = docs.system_prompt()
        if current == loaded:
            continue
        if not healthy():
            _set("offline", "The local model stopped. Start it, then press Retry.")
            return
        if not _request_lock.acquire(blocking=False):
            continue                               # busy answering; try again on the next tick
        try:
            _set("warming", "A doc changed. Re-reading the docs in the background.")
            msgs = [{"role": "system", "content": current}, {"role": "user", "content": "Reply with: ready"}]
            httpx.post(f"{BASE_URL}/chat/completions", json=_payload(msgs, False, 1), timeout=300).raise_for_status()
            loaded = current
            _set("ready", "Ready. Docs are loaded, so answers start quickly.")
        except httpx.HTTPError as e:
            _set("offline", f"Could not reach the local model: {e}")
            return
        finally:
            _request_lock.release()


def warm_in_background() -> None:
    """Idempotent: starts the warm-up thread unless one is already running."""
    global _warm_thread
    if _warm_thread and _warm_thread.is_alive():
        return
    _warm_thread = threading.Thread(target=_warm, name="assistant-warm", daemon=True)
    _warm_thread.start()


# ---------------- asking ----------------
def _clean_screen(screen: dict | None) -> str:
    if not screen:
        return "(no screen information was sent)"
    page = str(screen.get("page", "?"))[:40]
    title = str(screen.get("title", ""))[:200]
    text = re.sub(r"[ \t]+", " ", str(screen.get("text", "")))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    if len(text) > SCREEN_CHAR_LIMIT:
        text = text[:SCREEN_CHAR_LIMIT] + "\n[... rest of the page cut for length]"
    extra = screen.get("focus")
    focus = f"\nThe user is focused on: {str(extra)[:600]}" if extra else ""
    return f"Page: {page} ({title}){focus}\n{text}"


def build_messages(question: str, history: list[dict] | None, screen: dict | None) -> list[dict]:
    """System prompt (docs, cached prefix) + trimmed plain history + one user turn carrying the live screen."""
    hist = [m for m in (history or []) if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    kept: list[dict] = []
    used = 0
    for m in reversed(hist):                       # keep the newest turns that fit the budget
        cost = len(m["content"]) / CHARS_PER_TOKEN
        if used + cost > HISTORY_TOKEN_BUDGET:
            break
        kept.insert(0, {"role": m["role"], "content": m["content"][:4000]})
        used += cost
    if kept and kept[0]["role"] == "assistant":    # a conversation must start with the user
        kept.pop(0)
    user = (f"SCREEN (what the user sees right now):\n{_clean_screen(screen)}\n\n"
            f"TWIN STATE (live from the engine):\n{_state_text()}\n\n"
            f"QUESTION: {question.strip()[:2000]}")
    return [{"role": "system", "content": docs.system_prompt()}, *kept, {"role": "user", "content": user}]


class _ThinkFilter:
    """Drops any <think>...</think> text even if the tags arrive split across stream chunks."""

    def __init__(self) -> None:
        self.inside = False
        self.buf = ""

    def feed(self, text: str) -> str:
        self.buf += text
        out = ""
        while True:
            if self.inside:
                end = self.buf.find("</think>")
                if end < 0:
                    self.buf = self.buf[-8:]
                    return out
                self.buf = self.buf[end + 8:]
                self.inside = False
            else:
                start = self.buf.find("<think>")
                if start < 0:
                    keep = len(self.buf) - 7 if len(self.buf) > 7 else 0   # a split "<think" may still arrive
                    safe, self.buf = self.buf[:keep], self.buf[keep:]
                    return out + safe
                out += self.buf[:start]
                self.buf = self.buf[start + 7:]
                self.inside = True

    def flush(self) -> str:
        rest, self.buf = ("" if self.inside else self.buf), ""
        return rest


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def ask_stream(question: str, history: list[dict] | None, screen: dict | None) -> Iterator[str]:
    """Server-sent events for the browser: {"t": text} chunks, then {"done": true} or {"error": message}."""
    if not question or not question.strip():
        yield _sse({"error": "Please type a question."})
        return
    if not healthy():
        warm_in_background()
        yield _sse({"error": "The local model is not running yet. It is being started in the background; "
                             "please ask again in about a minute."})
        return
    messages = build_messages(question, history, screen)
    filt = _ThinkFilter()
    started = time.time()
    first = None
    with _request_lock:
        try:
            with httpx.stream("POST", f"{BASE_URL}/chat/completions",
                              json=_payload(messages, True, MAX_ANSWER_TOKENS),
                              timeout=httpx.Timeout(10.0, read=180.0)) as r:
                if r.status_code != 200:
                    yield _sse({"error": f"The local model answered with status {r.status_code}."})
                    return
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0].get("delta", {})
                    except (ValueError, KeyError, IndexError):
                        continue
                    text = delta.get("content") or ""          # reasoning_content is never forwarded
                    out = filt.feed(text) if text else ""
                    if out:
                        if first is None:
                            first = time.time() - started
                        yield _sse({"t": out})
            tail = filt.flush()
            if tail:
                yield _sse({"t": tail})
            yield _sse({"done": True, "first_token_s": round(first or 0, 2), "total_s": round(time.time() - started, 2)})
            _set("ready", "Ready. Docs are loaded, so answers start quickly.")
        except httpx.HTTPError as e:
            yield _sse({"error": f"Lost the connection to the local model: {e}"})


def ask_once(question: str, history: list[dict] | None = None, screen: dict | None = None) -> str:
    """Whole answer as one string (used by the evaluation script)."""
    out = []
    for ev in ask_stream(question, history, screen):
        obj = json.loads(ev[6:])
        if "error" in obj:
            raise RuntimeError(obj["error"])
        out.append(obj.get("t", ""))
    return "".join(out)
