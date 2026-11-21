"""Offline tests of the assistant plumbing (no model needed). The live answers are checked by tools/eval_assistant.py."""
import json

import pytest

from nmr_twin import assistant


def test_docs_in_fixed_order_and_present():
    prompt = assistant.docs.system_prompt()
    positions = [prompt.find(f"<<<DOC {p.name}") for p, _ in assistant.DOCS if p.exists()]
    assert all(pos > 0 for pos in positions)
    assert positions == sorted(positions)
    assert "Use ONLY the DOCS" in prompt
    assert len(prompt) / assistant.CHARS_PER_TOKEN < 20000          # fits the guide's whole-docs-in-prompt limit


def test_prompt_is_byte_identical_between_calls():                  # needed for the server's prefix cache
    assert assistant.docs.system_prompt() == assistant.docs.system_prompt()


def test_payload_never_sends_tools_and_thinking_is_off():
    p = assistant._payload([{"role": "user", "content": "x"}], True, 10)
    assert "tools" not in p and "tool_choice" not in p
    assert p["chat_template_kwargs"] == {"enable_thinking": False}
    assert p["stream"] is True


@pytest.mark.parametrize("chunks,expected", [
    (["Hello ", "world"], "Hello world"),
    (["A <think>hidden</think> B"], "A  B"),
    (["A <thi", "nk>hid", "den</th", "ink> B"], "A  B"),
    (["<think>only hidden"], ""),
])
def test_think_filter(chunks, expected):
    f = assistant._ThinkFilter()
    assert "".join(f.feed(c) for c in chunks) + f.flush() == expected


def test_history_is_trimmed_and_starts_with_user():
    long = [{"role": r, "content": "x" * 6000} for r in ("user", "assistant") * 10]
    msgs = assistant.build_messages("Q?", long, None)
    assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
    assert msgs[1]["role"] == "user"
    hist_chars = sum(len(m["content"]) for m in msgs[1:-1])
    assert hist_chars / assistant.CHARS_PER_TOKEN <= assistant.HISTORY_TOKEN_BUDGET


def test_screen_is_capped_and_question_goes_last():
    screen = {"page": "twin", "title": "T", "text": "y" * 50000}
    user = assistant.build_messages("What is K?", [], screen)[-1]["content"]
    assert "[... rest of the page cut for length]" in user
    assert user.rstrip().endswith("QUESTION: What is K?")


def test_ask_reports_clearly_when_model_is_down(monkeypatch):
    monkeypatch.setattr(assistant, "healthy", lambda timeout=2.0: False)
    monkeypatch.setattr(assistant, "warm_in_background", lambda: None)
    events = [json.loads(e[6:]) for e in assistant.ask_stream("hi", [], None)]
    assert events and "not running" in events[0]["error"]


def test_empty_question_is_refused():
    events = [json.loads(e[6:]) for e in assistant.ask_stream("   ", [], None)]
    assert "error" in events[0]


def test_evaluation_set_is_well_formed():
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "assistant_eval.json").read_text(encoding="utf-8"))
    assert 20 <= len(data["cases"]) <= 30
    assert len({c["id"] for c in data["cases"]}) == len(data["cases"])
