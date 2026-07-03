"""Transcript turn extraction + offset bookkeeping."""
import json

from brethof_mind_client import transcript


def _write(tmp_path, lines):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return str(p)


def test_extract_turns(tmp_path):
    lines = [
        {"type": "user", "timestamp": "t0",
         "message": {"role": "user", "content": "hello world"}},
        {"type": "assistant",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "hi there"},
             {"type": "tool_use", "name": "Bash"}]}},
        {"type": "user",   # tool_result arrives as a list-form user message
         "message": {"role": "user", "content": [
             {"type": "tool_result", "content": [{"type": "text", "text": "out"}]}]}},
        {"type": "system", "content": "ignored"},   # non-conversation line, dropped
    ]
    tj = _write(tmp_path, lines)
    turns, off, idx = transcript.read_new_turns(tj, "sess-extract-1")
    assert len(turns) == 3
    assert turns[0]["line_type"] == "user" and turns[0]["embed"] is True
    assert "hi there" in turns[1]["text"] and turns[1]["embed"] is True
    assert turns[2]["embed"] is False            # tool_result not embedded
    assert idx == 3 and off > 0
    assert [t["index"] for t in turns] == [0, 1, 2]


def test_empty_and_missing(tmp_path):
    assert transcript.read_new_turns("", "s")[0] == []
    assert transcript.read_new_turns(str(tmp_path / "nope.jsonl"), "s")[0] == []


def test_state_roundtrip():
    transcript.save_state("sess-rt", 123, 5)
    s = transcript.load_state("sess-rt")
    assert s["offset"] == 123 and s["next_index"] == 5
    # a never-seen session has a clean zero state
    assert transcript.load_state("sess-never")["offset"] == 0
